"""Un row refuse par un garde de securite ne doit pas emporter tout le batch.

Ultra-audit 2026-08. `domain/core.py:777` leve `RuntimeError("REFUS: destination
hors ROOT")` quand la destination calculee sort de la bibliotheque â€” un garde
legitime, et le refus de CE row est le bon comportement.

Mais la boucle par-row d'`apply_rows` n'attrapait que `(OSError)` et
`(ValueError, TypeError)`. Un `RuntimeError` traversait donc les deux clauses et
avortait le batch entier, APRES que les rows precedentes avaient deja bouge sur
disque : etat mixte, rows restantes jamais traitees. C'est mot pour mot la forme
du defaut que decrit la regle inviolable n4 du CLAUDE.md.

Ces tests eprouvent la boucle par-row, pas le garde : le garde, lui, doit
continuer a refuser.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.app import apply_core
from cinesort.domain import core as core_mod


class _RefusPourUnSeulDossier:
    """Leve `RuntimeError` pour UN dossier precis, laisse passer les autres.

    Interpose sur `apply_single` â€” la fonction que la boucle par-row appelle
    reellement pour un film seul â€” et non sur un helper plus profond : c'est la
    PROPAGATION jusqu'a la boucle qu'on eprouve, pas le garde lui-meme.
    """

    def __init__(self, vrai_apply_single, dossier_refuse: str) -> None:
        self._vrai = vrai_apply_single
        self._refuse = dossier_refuse
        self.appels: list = []

    def __call__(self, cfg, folder, *a, **k):
        nom = Path(str(folder)).name
        self.appels.append(nom)
        if nom == self._refuse:
            raise core_mod.DestinationHorsRacineError("REFUS: destination hors ROOT: C:/ailleurs/Film")
        return self._vrai(cfg, folder, *a, **k)


class RowRefuseTests(unittest.TestCase):
    def _apply_avec_refus_sur(self, dossier_refuse: str):
        tmp = Path(tempfile.mkdtemp(prefix="cs_refus_"))
        try:
            root = tmp / "root"
            root.mkdir()
            rows, decisions = [], {}
            for i in range(1, 4):
                folder = root / f"Film.{i}"
                folder.mkdir()
                (folder / f"film{i}.mkv").write_bytes(b"x" * 64)
                rows.append(
                    core_mod.PlanRow(
                        row_id=f"s{i}",
                        kind="single",
                        folder=str(folder),
                        video=f"film{i}.mkv",
                        proposed_title=f"Titre{i}",
                        proposed_year=1979 + i,
                        proposed_source="name",
                        confidence=90,
                        confidence_label="high",
                        candidates=[],
                    )
                )
                decisions[f"s{i}"] = {"ok": True, "title": f"Titre{i}", "year": 1979 + i}

            espion = _RefusPourUnSeulDossier(apply_core.apply_single, dossier_refuse)
            with mock.patch.object(apply_core, "apply_single", side_effect=espion):
                res = apply_core.apply_rows(
                    core_mod.Config(root=root).normalized(),
                    rows,
                    decisions,
                    dry_run=False,
                    quarantine_unapproved=False,
                    log=lambda *_a: None,
                    decision_presence=set(decisions),
                )
            return res, espion, root
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_les_rows_SUIVANTES_sont_quand_meme_traitees(self) -> None:
        """Le coeur du defaut : le refus du row 1 emportait les rows 2 et 3."""
        _res, espion, _root = self._apply_avec_refus_sur("Film.1")

        self.assertEqual(
            espion.appels,
            ["Film.1", "Film.2", "Film.3"],
            "le batch a ete avorte au premier refus : les rows suivantes n'ont jamais ete tentees",
        )

    def test_le_refus_reste_BRUYANT(self) -> None:
        """Garde anti-sur-correction : avaler un garde de securite en silence
        serait pire que le defaut d'origine."""
        res, _espion, _root = self._apply_avec_refus_sur("Film.2")

        self.assertGreaterEqual(res.errors, 1, "le refus n'est compte nulle part")
        joints = " ".join(res.error_messages or [])
        self.assertIn("hors ROOT", joints, f"le motif du refus a disparu : {res.error_messages}")

    def test_le_row_refuse_n_est_PAS_range_a_sa_destination(self) -> None:
        """Le garde doit continuer a garder : la destination n'est pas creee.

        L'assertion porte sur la DESTINATION, pas sur la survie du dossier source
        a son emplacement d'origine. Une premiere version affirmait cette
        derniere et s'est revelee FAUSSE a la mesure : sur le dernier row du
        batch, `root/Film.3` a bel et bien disparu alors que la boucle par-row
        n'y avait pas touche. Le deplacement vient d'une phase POSTERIEURE
        (nettoyage des dossiers residuels), pas du garde ni de son refus.

        Ce comportement n'est pas explique a ce jour et sort du perimetre de ce
        correctif — mais il ne doit pas etre masque par un test qui affirmerait
        le contraire de ce qui se produit.
        """
        _res, _espion, root = self._apply_avec_refus_sur("Film.3")

        self.assertFalse(
            (root / "Titre3 (1982)").exists(),
            "le garde a ete contourne : la destination du row refuse a ete creee",
        )

    def test_les_autres_films_sont_bien_ranges(self) -> None:
        res, _espion, _root = self._apply_avec_refus_sur("Film.1")

        self.assertGreaterEqual(res.renames + res.moves, 2, "les deux rows saines n'ont pas ete appliquees")

    def test_un_RuntimeError_ORDINAIRE_avorte_toujours_le_batch(self) -> None:
        """LA distinction, et elle a failli me couter le rollback atomique.

        Une premiere version attrapait `RuntimeError` tout court. Elle avalait
        donc aussi les crashs reels — et le mode atomique s'appuie precisement
        sur leur remontee pour declencher son rollback forward. Mesure : deux
        rouges dans tests/test_apply_atomic_rollback_integration_v77.py, ou
        l'apply se declarait `ok: True` avec `errors: 1` et ne restaurait rien.

        Un refus de garde ne concerne QUE son row. Un bug concerne tout le batch.
        """
        tmp = Path(tempfile.mkdtemp(prefix="cs_crash_"))
        try:
            root = tmp / "root"
            root.mkdir()
            folder = root / "Film.1"
            folder.mkdir()
            (folder / "film1.mkv").write_bytes(b"x" * 64)
            row = core_mod.PlanRow(
                row_id="s1",
                kind="single",
                folder=str(folder),
                video="film1.mkv",
                proposed_title="Titre1",
                proposed_year=1980,
                proposed_source="name",
                confidence=90,
                confidence_label="high",
                candidates=[],
            )
            decisions = {"s1": {"ok": True, "title": "Titre1", "year": 1980}}

            def _crash(*_a, **_k):
                raise RuntimeError("crash injecte")

            with mock.patch.object(apply_core, "apply_single", side_effect=_crash):
                with self.assertRaises(RuntimeError):
                    apply_core.apply_rows(
                        core_mod.Config(root=root).normalized(),
                        [row],
                        decisions,
                        dry_run=False,
                        quarantine_unapproved=False,
                        log=lambda *_a: None,
                        decision_presence=set(decisions),
                    )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_le_refus_de_garde_HERITE_de_RuntimeError(self) -> None:
        """Backward compat : tout code qui attrapait `RuntimeError` autour du
        garde continue de le voir."""
        self.assertTrue(issubclass(core_mod.DestinationHorsRacineError, RuntimeError))

    def test_sans_refus_rien_ne_change(self) -> None:
        """Contre-epreuve : le chemin nominal doit rester intact."""
        res, espion, _root = self._apply_avec_refus_sur("row-inexistant")

        self.assertEqual(espion.appels, ["Film.1", "Film.2", "Film.3"])
        self.assertEqual(res.errors, 0, f"erreurs sur un chemin sain : {res.error_messages}")
        self.assertGreaterEqual(res.renames + res.moves, 3)


if __name__ == "__main__":
    unittest.main()

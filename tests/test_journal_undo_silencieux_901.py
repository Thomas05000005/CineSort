"""Un apply qui n'a PAS pu journaliser ne doit plus se declarer reussi en silence.

Issue #901 : batch cree, `apply_ts` present, mais `counts.total = 0` et
`can_undo = False` — l'apply s'etait declare `ok: True` sans qu'aucune erreur
ne remonte. L'utilisateur ne peut plus annuler et rien ne le lui dit.

CAUSE TROUVEE PAR MESURE, pas par intuition : `record_apply_op` rend `False`
depuis toujours quand la journalisation echoue, et sa docstring l'annonce. Mais
sur ses **14 sites d'appel**, **AUCUN** ne lisait ce retour.

    sites d'appel : 14
    retour UTILISE :  0
    retour IGNORE  : 14

Un apply pouvait donc deplacer des dossiers, ne rien journaliser, et rapporter
un succes. C'est exactement la regle du depot qu'on enfreint : un echec ne doit
jamais devenir un succes silencieux.

CE QUE LE CORRECTIF NE FAIT PAS : il ne fait pas ECHOUER l'apply. L'operation
physique a deja reussi ; avorter laisserait un etat mixte sur le disque. Il
cesse seulement de le taire.
"""

from __future__ import annotations

import sqlite3
import unittest
from pathlib import Path

from cinesort.app.apply_core import record_apply_op
from cinesort.domain.core import ApplyResult


class _RecordOpQuiEchoue:
    """Journal indisponible — le cas reel : `database is locked`."""

    def __init__(self, exc: Exception) -> None:
        self._exc = exc
        self.appels = 0

    def __call__(self, payload):  # noqa: ARG002
        self.appels += 1
        raise self._exc


class RecordApplyOpCompteSesEchecsTests(unittest.TestCase):
    def _journaliser(self, record_op) -> bool:
        return record_apply_op(
            record_op,
            op_type="MOVE",
            src_path=Path("C:/x/Film.mkv"),
            dst_path=Path("C:/y/Film.mkv"),
            row_id="r1",
        )

    def test_un_echec_est_COMPTE_par_le_proxy(self) -> None:
        """Le comptage vit dans `_CompteurEchecsJournal`, pas sur l'emballage.

        Premiere version : on comptait sur le callable recu par
        `record_apply_op`. Elle ne marchait pas — ce callable est un emballage
        cree A L'INTERIEUR d'`apply_rows` et jete a la fin de chaque row.
        Mesure : le compteur restait a 0 sur un vrai apply dont CHAQUE ecriture
        echouait.
        """
        from cinesort.app.apply_core import _CompteurEchecsJournal

        proxy = _CompteurEchecsJournal(_RecordOpQuiEchoue(sqlite3.OperationalError("database is locked")))
        self.assertFalse(self._journaliser(proxy))
        self.assertEqual(proxy.journal_failures, 1)

    def test_les_echecs_s_ACCUMULENT(self) -> None:
        from cinesort.app.apply_core import _CompteurEchecsJournal

        proxy = _CompteurEchecsJournal(_RecordOpQuiEchoue(sqlite3.OperationalError("database is locked")))
        for _ in range(3):
            self._journaliser(proxy)
        self.assertEqual(proxy.journal_failures, 3)

    def test_le_proxy_PRESERVE_les_attributs_du_journal(self) -> None:
        """`atomic_move` lit `journal_store` / `journal_batch_id` : les perdre
        desactiverait SILENCIEUSEMENT le journal write-ahead, donc la protection
        contre un crash mi-move."""
        from cinesort.app.apply_core import _CompteurEchecsJournal

        def _fn(_p):
            pass

        _fn.journal_store = "STORE"
        _fn.journal_batch_id = "B1"
        proxy = _CompteurEchecsJournal(_fn)
        self.assertEqual(proxy.journal_store, "STORE")
        self.assertEqual(proxy.journal_batch_id, "B1")

    def test_le_proxy_RELANCE_l_exception(self) -> None:
        """Il compte, il ne DECIDE pas : les tolerances existantes doivent
        continuer de s'appliquer exactement comme avant."""
        from cinesort.app.apply_core import _CompteurEchecsJournal

        proxy = _CompteurEchecsJournal(_RecordOpQuiEchoue(sqlite3.OperationalError("locked")))
        with self.assertRaises(sqlite3.OperationalError):
            proxy({"op_type": "MOVE"})

    def test_sqlite3_Error_est_bien_attrapee(self) -> None:
        """Regle inviolable n°4 : elle n'herite PAS d'OSError.

        Sans elle dans la clause, un « database is locked » avortait tout le
        batch APRES un move deja fait sur disque.
        """
        self.assertFalse(issubclass(sqlite3.Error, OSError))
        rec = _RecordOpQuiEchoue(sqlite3.DatabaseError("disk image is malformed"))
        self.assertFalse(self._journaliser(rec), "l'exception a traverse record_apply_op")

    def test_un_succes_ne_compte_RIEN(self) -> None:
        """Contre-epreuve : le compteur ne doit pas s'armer tout seul."""
        vus = []
        self.assertTrue(self._journaliser(vus.append))
        self.assertEqual(getattr(vus.append, "journal_failures", 0), 0)

    def test_record_op_ABSENT_reste_un_succes(self) -> None:
        """`record_op=None` veut dire « pas de journal demande », pas « echec »."""
        self.assertTrue(self._journaliser(None))


class ApplyResultPorteLeCompteurTests(unittest.TestCase):
    def test_le_champ_existe_et_vaut_zero_par_defaut(self) -> None:
        self.assertEqual(ApplyResult().journal_failures, 0)

    def test_le_champ_est_serialisable(self) -> None:
        """`apply_support` retourne `ApplyResult.__dict__` au boundary REST.

        Sans presence dans le dict, l'UI ne pourrait pas afficher l'alerte.
        """
        self.assertIn("journal_failures", ApplyResult(journal_failures=2).__dict__)


class ApplyReelRemonteLeCompteurTests(unittest.TestCase):
    """LE SITE D'APPEL : un vrai `apply_rows` avec un journal verrouille.

    Premiere version de ces tests : elle n'exercait que `record_apply_op` et le
    dataclass. Retirer la remontee dans `res` les laissait donc tous VERTS —
    exactement le defaut qu'on corrige, mais dans le test.
    """

    def _apply_avec_journal_verrouille(self, nb_films=2):
        import shutil
        import tempfile

        from cinesort.app.apply_core import apply_rows
        from cinesort.domain import core as core_mod

        def _journal_verrouille(_payload):
            raise sqlite3.OperationalError("database is locked")

        tmp = Path(tempfile.mkdtemp(prefix="cs_901_"))
        try:
            root = tmp / "root"
            root.mkdir()
            rows, decisions = [], {}
            for i in range(1, nb_films + 1):
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
            return apply_rows(
                core_mod.Config(root=root).normalized(),
                rows,
                decisions,
                dry_run=False,
                quarantine_unapproved=False,
                log=lambda *_a: None,
                decision_presence=set(decisions),
                record_op=_journal_verrouille,
            )
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_le_resultat_PORTE_le_nombre_d_operations_non_journalisees(self) -> None:
        res = self._apply_avec_journal_verrouille()
        self.assertGreater(
            res.journal_failures,
            0,
            "apply declare reussi sans dire qu'AUCUNE operation n'a ete journalisee — c'est le symptome de #901",
        )

    def test_le_message_NOMME_la_consequence_pour_l_utilisateur(self) -> None:
        """Un compteur muet ne sert a rien : il faut dire que l'undo sera incomplet."""
        res = self._apply_avec_journal_verrouille()
        joints = " ".join(res.error_messages or [])
        self.assertIn("annulation", joints.lower(), f"consequence non nommee : {res.error_messages}")

    def test_les_films_sont_QUAND_MEME_ranges(self) -> None:
        """On ne fait PAS echouer l'apply : le disque a deja bouge.

        Avorter laisserait un etat mixte — c'est l'invariant documente dans
        move_journal : « un failure du journal ne DOIT JAMAIS empecher un move
        legitime ».
        """
        res = self._apply_avec_journal_verrouille()
        self.assertGreaterEqual(res.renames + res.moves, 2, "le batch a ete avorte")
        self.assertEqual(res.errors, 0, "un echec de journal ne doit pas compter comme erreur d'apply")


if __name__ == "__main__":
    unittest.main()

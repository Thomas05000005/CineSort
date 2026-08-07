"""Un film mis en quarantaine par l'undo doit rester atteignable par la reprise.

LE DEFAUT (#987). Quand l'undo ne peut pas remettre un film a sa place — la
destination est occupee — il le deplace vers `<run_dir>/_review/_undo_conflicts/`
et marque l'operation `FAILED`. Or `FAILED` est TERMINAL pour les trois chemins
de reprise du depot :

    undo selectif      apply_support.py    ne selectionne que `PENDING`
    apercu par ligne   apply_support.py    ne compte comme annulable que `PENDING`
    rollback forward   apply_rollback.py   SAUTE les `FAILED`

Le film etait donc dans un bac que rien ne savait plus atteindre. La seule
recuperation possible etait de le deplacer a la main.

POURQUOI PAS UN STATUT « REPRENABLE » SUR L'OPERATION D'ORIGINE. C'est la piste
qui vient d'abord a l'esprit, et elle ne marche pas : le fichier BLOQUANT n'a pas
bouge. Le conflit vient de `target_path`, auquel l'undo ne touche pas. Rendre
l'operation d'origine reprenable ferait donc rejouer un undo GARANTI de
reconflicter — et de re-deplacer le film dans le bac. Un cycle, pas une reprise.

LE CORRECTIF. Le deplacement vers le bac est journalise comme une OPERATION A
PART ENTIERE (`UNDO_QUARANTINE`), qui nait `PENDING` et decrit un mouvement
reellement reversible : `bac -> emplacement d'avant la quarantaine`. Les trois
lecteurs la voient sans qu'aucun n'ait a connaitre un nouveau vocabulaire.

L'operation d'origine reste `FAILED` : c'est la verite, son undo n'a pas abouti.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.ui.api.apply_support import _execute_undo_ops
from tests.test_apply_robustness import _FakeApi, _FakeRunPaths, _log_noop

_BATCH = "batch-987"


class _RepoQuiEnregistre:
    """Repository d'apply minimal qui RETIENT ce qui est journalise."""

    def __init__(self, index_libre: int = 7) -> None:
        self.marks: list = []
        self.operations_ajoutees: list = []
        self._index_libre = index_libre
        self.appels_index = 0

    # --- ce que `_execute_undo_ops` attend deja ---
    def mark_apply_operation_undo_status(self, **kw) -> None:
        self.marks.append(kw)

    # --- ce que le correctif ajoute ---
    def next_free_op_index(self, *, batch_id: str) -> int:
        self.appels_index += 1
        assert batch_id == _BATCH, f"batch_id inattendu : {batch_id!r}"
        return self._index_libre

    def append_apply_operation(self, **kw) -> int:
        self.operations_ajoutees.append(kw)
        return len(self.operations_ajoutees)


class _StoreQuiEnregistre:
    def __init__(self, index_libre: int = 7) -> None:
        self.apply = _RepoQuiEnregistre(index_libre)

    @property
    def marks(self):
        return self.apply.marks


class QuarantineJournaliseeTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_987_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir()
        self.run_dir = Path(self._tmp) / "run_dir"
        self.run_dir.mkdir()
        self.store = _StoreQuiEnregistre()
        self.api = _FakeApi()
        self.run_paths = _FakeRunPaths(self.run_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _conflit(self, nom: str = "Rocky.1976.mkv") -> tuple[Path, dict]:
        """Prepare UN conflit : le film existe, sa destination d'undo est occupee."""
        courant = self.root / "Films" / nom
        courant.parent.mkdir(parents=True, exist_ok=True)
        courant.write_bytes(b"le film")
        cible = self.root / "Films" / "occupee.mkv"
        cible.write_bytes(b"deja la")
        op = {
            "id": 1,
            "batch_id": _BATCH,
            "op_index": 3,
            "op_type": "MOVE",
            "src_path": str(cible),
            "dst_path": str(courant),
            "row_id": "row-42",
        }
        return courant, op

    def _jouer(self) -> dict:
        courant, op = self._conflit()
        resultat = _execute_undo_ops(
            self.api, [op], self.store, _log_noop, self.run_paths, empty_bucket=None, residual_bucket=None
        )
        self.assertEqual(resultat["conflict_moves"], 1, resultat)
        return resultat

    def test_la_quarantaine_EST_journalisee(self) -> None:
        """Le coeur du correctif. Avant, rien n'etait ecrit."""
        self._jouer()

        ajoutees = self.store.apply.operations_ajoutees
        self.assertEqual(len(ajoutees), 1, f"la quarantaine n'est pas journalisee : {ajoutees}")
        self.assertEqual(ajoutees[0]["op_type"], "UNDO_QUARANTINE")

    def test_elle_est_REVERSIBLE_donc_visible_des_trois_chemins(self) -> None:
        """`reversible=True` + `undo_status` par defaut `PENDING` : c'est
        exactement ce que filtrent les trois lecteurs."""
        self._jouer()

        ajoutee = self.store.apply.operations_ajoutees[0]
        self.assertIs(ajoutee["reversible"], True, "l'operation ne sera vue par aucun chemin de reprise")

    def test_elle_decrit_le_mouvement_REELLEMENT_fait(self) -> None:
        """`src` -> `dst` doit decrire le deplacement qui vient d'avoir lieu :
        l'annuler remettra le film la ou il etait avant la quarantaine.

        Se tromper de sens produirait une reprise qui deplace le film vers le
        bac au lieu de l'en sortir.
        """
        courant, _ = self._conflit()
        # `_conflit` a recree les fichiers : on rejoue proprement.
        shutil.rmtree(self.run_dir, ignore_errors=True)
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.store = _StoreQuiEnregistre()
        self._jouer()

        ajoutee = self.store.apply.operations_ajoutees[0]
        self.assertEqual(Path(ajoutee["src_path"]).name, "Rocky.1976.mkv")
        self.assertIn("_undo_conflicts", ajoutee["dst_path"])
        self.assertTrue(Path(ajoutee["dst_path"]).is_file(), "le fichier n'est pas la ou le journal le dit")

    def test_l_index_vient_de_la_BASE_et_non_des_ops_chargees(self) -> None:
        """`UNIQUE (batch_id, op_index)`. La liste passee a `_execute_undo_ops`
        est FILTREE sur `reversible` : son maximum local (ici 3) peut etre
        inferieur au maximum reel du batch (ici 6), et reutiliser 4 violerait
        la contrainte.
        """
        self._jouer()

        ajoutee = self.store.apply.operations_ajoutees[0]
        self.assertEqual(ajoutee["op_index"], 7, "l'index ne vient pas de la base")
        self.assertEqual(self.store.apply.appels_index, 1, "la base est relue a chaque conflit")

    def test_le_row_id_est_conserve(self) -> None:
        """Sans lui, l'aperçu par ligne ne peut pas rattacher la quarantaine au
        film qu'elle concerne."""
        self._jouer()

        self.assertEqual(self.store.apply.operations_ajoutees[0]["row_id"], "row-42")

    def test_l_operation_d_origine_reste_FAILED(self) -> None:
        """C'est la verite : son undo n'a pas abouti. La reprise passe par la
        NOUVELLE operation, pas par une reecriture de l'histoire."""
        self._jouer()

        statuts = [m.get("undo_status") for m in self.store.marks]
        self.assertIn("FAILED", statuts, f"statuts observes : {statuts}")


class LEchecDuJournalNAvortePasLUndoTests(unittest.TestCase):
    """Le fichier est deja deplace : refuser de continuer ne le ramenerait pas.

    Mais l'echec doit etre SIGNALE — un journal muet est precisement ce que #901
    a coute.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_987b_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir()
        self.run_dir = Path(self._tmp) / "run_dir"
        self.run_dir.mkdir()
        self.api = _FakeApi()
        self.run_paths = _FakeRunPaths(self.run_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_un_store_SANS_la_methode_ne_fait_pas_echouer_l_undo(self) -> None:
        """Compatibilite : une doublure ancienne, ou une base indisponible."""

        class _RepoSansJournal:
            def __init__(self) -> None:
                self.marks: list = []

            def mark_apply_operation_undo_status(self, **kw) -> None:
                self.marks.append(kw)

        class _StoreSansJournal:
            def __init__(self) -> None:
                self.apply = _RepoSansJournal()

            @property
            def marks(self):
                return self.apply.marks

        courant = self.root / "Films" / "Alien.1979.mkv"
        courant.parent.mkdir(parents=True, exist_ok=True)
        courant.write_bytes(b"le film")
        cible = self.root / "Films" / "occupee.mkv"
        cible.write_bytes(b"deja la")
        op = {"id": 1, "batch_id": "b", "op_type": "MOVE", "src_path": str(cible), "dst_path": str(courant)}

        avertissements: list = []

        def _log(niveau: str, message: str) -> None:
            if niveau == "WARN":
                avertissements.append(message)

        resultat = _execute_undo_ops(
            self.api, [op], _StoreSansJournal(), _log, self.run_paths, empty_bucket=None, residual_bucket=None
        )

        self.assertEqual(resultat["conflict_moves"], 1, "l'undo a ete avorte par un defaut de JOURNAL")
        self.assertTrue(
            any("NON journalisee" in m for m in avertissements),
            f"l'echec du journal est SILENCIEUX : {avertissements}",
        )


if __name__ == "__main__":
    unittest.main()

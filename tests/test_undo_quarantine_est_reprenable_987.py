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

    def __init__(self) -> None:
        self.marks: list = []
        self.operations_ajoutees: list = []

    # --- ce que `_execute_undo_ops` attend deja ---
    def mark_apply_operation_undo_status(self, **kw) -> None:
        self.marks.append(kw)

    # --- ce que le correctif ajoute ---
    def append_apply_operation_a_la_suite(self, **kw) -> int:
        assert kw.get("batch_id") == _BATCH, f"batch_id inattendu : {kw.get('batch_id')!r}"
        assert "op_index" not in kw, "l'index ne doit PAS venir de l'appelant : la course revient"
        self.operations_ajoutees.append(kw)
        return len(self.operations_ajoutees)


class _StoreQuiEnregistre:
    def __init__(self) -> None:
        self.apply = _RepoQuiEnregistre()

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

    def test_l_appelant_ne_CHOISIT_PAS_l_index(self) -> None:
        """`UNIQUE (batch_id, op_index)`, et la course qui allait avec.

        Une premiere version exposait `next_free_op_index()` puis laissait
        l'appelant appeler `append_apply_operation()`. La connexion etait
        relachee ENTRE LES DEUX : deux undo concurrents du meme batch lisaient
        le meme index, l'un des INSERT violait la contrainte, et
        `_journaliser_quarantaine_undo` — qui absorbe l'erreur pour ne pas
        avorter un undo deja engage sur le disque — laissait le deplacement NON
        journalise. Le defaut corrige ici serait revenu en concurrence.

        L'index est desormais calcule DANS l'instruction d'insertion. Ce test
        verrouille le fait que l'appelant ne le fournit plus (l'assertion vit
        dans la doublure, qui refuse un `op_index`).
        """
        self._jouer()

        ajoutee = self.store.apply.operations_ajoutees[0]
        self.assertNotIn("op_index", ajoutee)

    def test_l_empreinte_du_fichier_quarantaine_est_PERSISTEE(self) -> None:
        """Sans `src_sha1`/`src_size`, la pre-verification de l'undo (P1.2) ne
        peut pas detecter qu'un utilisateur a remplace le fichier DANS le bac
        entre la quarantaine et la reprise : elle le restaurerait en croyant
        que c'est le sien."""
        self._jouer()

        ajoutee = self.store.apply.operations_ajoutees[0]
        self.assertTrue(ajoutee.get("src_sha1"), "aucune empreinte : un remplacement passerait inapercu")
        self.assertEqual(ajoutee.get("src_size"), len(b"le film"))

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


class LInsertionAtomiqueSurUneVRAIEBaseTests(unittest.TestCase):
    """Les tests ci-dessus passent par une DOUBLURE : ils prouvent le site
    d'appel, pas le SQL. Ceux-ci s'executent contre un vrai `SQLiteStore`.

    C'est la que vit le risque : `INSERT ... SELECT COALESCE(MAX(op_index),-1)+1
    FROM apply_operations WHERE batch_id=?` doit rendre 0 sur un batch vide,
    s'incrementer ensuite, et ne jamais violer `UNIQUE (batch_id, op_index)`.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_987_sql_")
        from cinesort.infra.db.sqlite_store import SQLiteStore

        self.store = SQLiteStore(db_path=Path(self._tmp) / "cinesort.sqlite")
        self.store.initialize()
        # `apply_operations.batch_id` porte une FOREIGN KEY vers `apply_batches`.
        # Sans batch reel, l'INSERT leve `IntegrityError` — ce que la premiere
        # version de ces tests a decouvert, et qu'aucune doublure n'aurait pu
        # montrer. C'est aussi la preuve que `_journaliser_quarantaine_undo`
        # echouerait (silencieusement, par son `except`) si un appelant fournissait
        # un `batch_id` vide : son WARN est donc necessaire, pas decoratif.
        for batch in ("b1", "b2"):
            self.store.apply.insert_apply_batch(
                run_id=f"run-{batch}", dry_run=False, quarantine_unapproved=False, batch_id=batch
            )

    def tearDown(self) -> None:
        with __import__("contextlib").suppress(Exception):
            self.store.close()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _ajouter(self, batch: str = "b1") -> int:
        return self.store.apply.append_apply_operation_a_la_suite(
            batch_id=batch,
            op_type="UNDO_QUARANTINE",
            src_path="C:/a.mkv",
            dst_path="C:/bac/a.mkv",
            reversible=True,
        )

    def test_le_premier_index_d_un_batch_VIDE_vaut_zero(self) -> None:
        """`MAX()` sur un ensemble vide rend NULL : sans le `COALESCE`, l'INSERT
        ecrirait NULL et la contrainte d'unicite ne protegerait plus rien."""
        self._ajouter()

        ops = self.store.apply.list_apply_operations(batch_id="b1")
        self.assertEqual([o["op_index"] for o in ops], [0])

    def test_les_index_s_incrementent_sans_COLLISION(self) -> None:
        for _ in range(5):
            self._ajouter()

        indices = [o["op_index"] for o in self.store.apply.list_apply_operations(batch_id="b1")]
        self.assertEqual(indices, [0, 1, 2, 3, 4], indices)
        self.assertEqual(len(set(indices)), len(indices), "deux operations partagent un index")

    def test_l_index_est_PROPRE_a_chaque_batch(self) -> None:
        """La contrainte porte sur le COUPLE : deux batchs distincts doivent
        pouvoir avoir chacun leur index 0."""
        self._ajouter("b1")
        self._ajouter("b2")

        self.assertEqual([o["op_index"] for o in self.store.apply.list_apply_operations(batch_id="b1")], [0])
        self.assertEqual([o["op_index"] for o in self.store.apply.list_apply_operations(batch_id="b2")], [0])

    def test_elle_prend_la_suite_des_operations_DEJA_presentes(self) -> None:
        """Le cas reel : le batch porte deja les operations de l'apply."""
        for i in range(3):
            self.store.apply.append_apply_operation(
                batch_id="b1",
                op_index=i,
                op_type="MOVE",
                src_path=f"C:/s{i}",
                dst_path=f"C:/d{i}",
                reversible=True,
            )

        self._ajouter("b1")

        indices = sorted(o["op_index"] for o in self.store.apply.list_apply_operations(batch_id="b1"))
        self.assertEqual(indices, [0, 1, 2, 3], "la quarantaine n'a pas pris la suite")

    def test_l_empreinte_est_bien_PERSISTEE_en_base(self) -> None:
        self.store.apply.append_apply_operation_a_la_suite(
            batch_id="b1",
            op_type="UNDO_QUARANTINE",
            src_path="C:/a.mkv",
            dst_path="C:/bac/a.mkv",
            reversible=True,
            src_sha1="abc123",
            src_size=4242,
        )

        op = self.store.apply.list_apply_operations(batch_id="b1")[0]
        self.assertEqual(op["src_sha1"], "abc123")
        self.assertEqual(op["src_size"], 4242)
        self.assertEqual(op["undo_status"], "PENDING", "l'operation nait deja consommee")


if __name__ == "__main__":
    unittest.main()

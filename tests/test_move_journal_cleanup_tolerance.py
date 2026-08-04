"""Issue #670 — le nettoyage du journal APRES un move ne doit jamais casser l'undo.

`journaled_move` INSERT une entree pending AVANT le deplacement, puis la DELETE
APRES. Le DELETE ne catchait que `(sqlite3.Error, OSError, AttributeError)`.

Or ce DELETE s'execute quand les octets ont DEJA bouge sur le disque, et tous les
call sites sont batis ainsi (ici `cleanup._move_dirs_to_bucket`, mais c'est le
meme motif dans les 12 sites d'`apply_core`) :

    atomic_move(record_op, src=..., dst=..., op_type="MOVE_DIR")   # journaled_move
    record_apply_op(record_op, op_type="MOVE_DIR", ...)            # journal d'undo

Une exception hors du tuple qui s'echappe du DELETE saute donc le
`record_apply_op` qui suit : le dossier a change de place mais aucune operation
n'est ecrite dans `apply_operations` -> l'undo ne peut plus rien restaurer.
C'est l'etat mixte non annulable que le module dit vouloir eviter
(move_journal.py : « un failure du journal ne DOIT JAMAIS empecher un move
legitime »).

Les types atteignables hors de l'ancien tuple ne sont pas theoriques :
`delete_pending_move` appelle `_ensure_schema_group` -> `_schema_group_tables`,
qui leve `KeyError` (« Groupe de schema inconnu », sqlite_store.py:876), et le
bootstrap de schema leve `RuntimeError` (sqlite_store.py:284).

PIEGE EVITE (verifie par instrumentation avant d'ecrire ces tests) : le chemin
« un film, un dossier renomme » n'emprunte PAS `atomic_move` — `apply_single`
fait un `folder.rename(dst)` direct (apply_core.py:2426) et n'insere donc AUCUNE
entree pending. Un test d'integration bati dessus serait VACANT : il resterait
vert avec ou sans correctif. On passe donc par le nettoyage des dossiers
residuels, qui lui appelle bien `atomic_move`, et chaque test d'integration
compte les appels reellement injectes pour interdire toute vacuite future.
"""

from __future__ import annotations

import logging
import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

import cinesort.domain.core as core
from cinesort.app import cleanup as cleanup_mod
from cinesort.app.move_journal import RecordOpWithJournal, journaled_move
from cinesort.infra.db.repositories.apply import ApplyRepository
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done

# Exceptions REELLEMENT atteignables depuis `delete_pending_move` et absentes de
# l'ancien tuple (sqlite3.Error, OSError, AttributeError).
_HORS_ANCIEN_TUPLE = {
    "KeyError": KeyError("Groupe de schema inconnu: apply_pending"),
    "RuntimeError": RuntimeError("Aucune migration SQL disponible pour initialiser le schema SQLite."),
    "TypeError": TypeError("int() argument must be a string or a real number, not 'NoneType'"),
    "ValueError": ValueError("invalid literal for int()"),
}

_PANNE_SCHEMA = "Groupe de schema inconnu: apply_pending"


class _StoreFactice:
    """Surface minimale de SQLiteStore utilisee par `journaled_move`."""

    def __init__(
        self,
        *,
        delete_raises: Optional[BaseException] = None,
        insert_raises: Optional[BaseException] = None,
    ) -> None:
        self.apply = self
        self._delete_raises = delete_raises
        self._insert_raises = insert_raises
        self.inserted: List[Dict[str, Any]] = []
        self.deleted: List[int] = []

    def insert_pending_move(self, **kwargs: Any) -> int:
        if self._insert_raises is not None:
            raise self._insert_raises
        self.inserted.append(dict(kwargs))
        return len(self.inserted)

    def delete_pending_move(self, pending_id: int) -> None:
        self.deleted.append(int(pending_id))
        if self._delete_raises is not None:
            raise self._delete_raises


class NettoyagePostMoveTests(unittest.TestCase):
    """Garde unitaire : rien ne doit sortir du bloc de nettoyage post-move."""

    def test_aucune_exception_ne_sort_du_nettoyage_post_move(self) -> None:
        for nom, exc in _HORS_ANCIEN_TUPLE.items():
            with self.subTest(exception=nom):
                store = _StoreFactice(delete_raises=exc)
                corps_execute: List[str] = []

                with self.assertLogs("cinesort.app.move_journal", level=logging.ERROR) as journal:
                    with journaled_move(store, src="/src/Film", dst="/dst/Film", op_type="MOVE_DIR"):
                        corps_execute.append("move")

                self.assertEqual(corps_execute, ["move"], "le corps du with doit s'etre execute")
                self.assertEqual(store.deleted, [1], "le nettoyage doit bien avoir ete TENTE")
                self.assertTrue(
                    any("delete_pending_move" in ligne for ligne in journal.output),
                    "l'echec doit rester visible dans les logs, pas disparaitre",
                )

    def test_linsert_pre_move_reste_fail_closed(self) -> None:
        """Garde anti-sur-correction : l'asymetrie INSERT / DELETE est deliberee.

        AVANT le deplacement, rien n'a bouge : une erreur inattendue doit remonter
        et empecher le move (sens restrictif). Elargir CE tuple-la ferait tourner
        un apply entier sans journal write-ahead, donc sans reconciliation possible
        apres un crash. Ce test doit rester VERT des deux cotes du correctif.
        """
        store = _StoreFactice(insert_raises=KeyError(_PANNE_SCHEMA))
        corps_execute: List[str] = []

        with self.assertRaises(KeyError):
            with journaled_move(store, src="/src/Film", dst="/dst/Film", op_type="MOVE_DIR"):
                corps_execute.append("move")

        self.assertEqual(corps_execute, [], "aucun deplacement ne doit etre tente si le journal n'a pas pu s'armer")
        self.assertEqual(store.deleted, [])

    def test_une_db_verrouillee_a_linsert_ne_bloque_pas_le_move(self) -> None:
        """Non-regression : la tolerance existante de l'INSERT reste en place."""
        store = _StoreFactice(insert_raises=sqlite3.OperationalError("database is locked"))
        corps_execute: List[str] = []

        with self.assertLogs("cinesort.app.move_journal", level=logging.WARNING):
            with journaled_move(store, src="/src/Film", dst="/dst/Film", op_type="MOVE_DIR") as pending_id:
                corps_execute.append("move")

        self.assertIsNone(pending_id, "sans pending_id, aucun nettoyage ne doit etre tente")
        self.assertEqual(corps_execute, ["move"])
        self.assertEqual(store.deleted, [])

    def test_succes_nominal_inchange(self) -> None:
        store = _StoreFactice()
        with journaled_move(store, src="/src/Film", dst="/dst/Film", op_type="MOVE_DIR") as pending_id:
            pass
        self.assertEqual(pending_id, 1)
        self.assertEqual(store.deleted, [1], "l'entree pending doit etre nettoyee quand tout va bien")

    def test_une_exception_dans_le_corps_laisse_lentree_pending(self) -> None:
        """Non-regression : le nettoyage ne doit PAS avoir lieu si le move a echoue."""
        store = _StoreFactice()
        with self.assertRaises(OSError):
            with journaled_move(store, src="/src/Film", dst="/dst/Film", op_type="MOVE_DIR"):
                raise OSError("disque plein")
        self.assertEqual(store.deleted, [], "l'entree pending doit survivre pour la reconciliation au boot")


class CallSiteDeProductionTests(unittest.TestCase):
    """Le vrai enchainement de production : `cleanup._move_dirs_to_bucket`.

    Cette fonction est le motif exact de tous les sites de deplacement :
    `atomic_move(...)` PUIS `_record_apply_op(...)`. On n'y reproduit rien a la
    main : on l'appelle telle quelle avec un store dont le nettoyage est en panne.
    """

    def test_le_move_reste_journalise_donc_annulable(self) -> None:
        store = _StoreFactice(delete_raises=KeyError(_PANNE_SCHEMA))
        ops: List[Dict[str, Any]] = []
        record_op = RecordOpWithJournal(ops.append, store=store, batch_id="b1")
        # PR#852 : `_move_dirs_to_bucket` incremente desormais `res` dossier par
        # dossier au lieu d'un `+=` du caller, `res` est donc obligatoire.
        res = core.ApplyResult()

        with tempfile.TemporaryDirectory() as tmp_name:
            tmp = Path(tmp_name)
            residuel = tmp / "root" / "Residual.Noise"
            bucket = tmp / "root" / "_Dossier Nettoyage"
            _create_file(residuel / "movie.nfo", size=64)

            with self.assertLogs("cinesort.app.move_journal", level=logging.ERROR):
                moved = cleanup_mod._move_dirs_to_bucket(
                    [residuel],
                    is_eligible=lambda _path: True,
                    bucket_root=bucket,
                    dry_run=False,
                    log=lambda _level, _message: None,
                    log_prefix="TEST",
                    res=res,
                    counter_attr="cleanup_residual_folders_moved_count",
                    record_op=record_op,
                )

            self.assertEqual(moved, 1)
            self.assertEqual(res.cleanup_residual_folders_moved_count, 1)
            self.assertEqual(res.errors, 0, f"le nettoyage du journal n'est pas une erreur : {res.error_messages}")
            self.assertFalse(residuel.exists(), "le dossier a bien bouge sur le disque")
            self.assertTrue((bucket / "Residual.Noise").exists())

        self.assertEqual(store.deleted, [1], "garde anti-test-vacant : la panne doit avoir ete injectee")
        self.assertEqual(
            [op["op_type"] for op in ops],
            ["MOVE_DIR"],
            "le move doit etre journalise dans apply_operations, sinon plus aucun undo possible",
        )
        self.assertEqual(ops[0]["src_path"], str(residuel))
        self.assertTrue(ops[0]["reversible"])


class UndoResteReellementPossibleTests(unittest.TestCase):
    """INTEGRATION : apply reel (SQLiteStore reel) + undo reel, nettoyage en panne.

    On ne se contente pas de constater que l'exception est attrapee : on rejoue
    l'undo de production et on verifie que le dossier revient a sa place.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_670_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        patch_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patch_min_video.start()
        self.addCleanup(patch_min_video.stop)
        self.appels: Dict[str, int] = {"insert": 0, "delete": 0}

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _panne_sur_le_nettoyage(self) -> Any:
        """Patch les 2 methodes du journal : compte les INSERT, casse les DELETE."""
        vrai_insert = ApplyRepository.insert_pending_move
        appels = self.appels

        def _insert(repo: Any, **kwargs: Any) -> int:
            appels["insert"] += 1
            return vrai_insert(repo, **kwargs)

        def _delete_casse(_repo: Any, _pending_id: int) -> None:
            appels["delete"] += 1
            raise KeyError(_PANNE_SCHEMA)

        return mock.patch.multiple(
            ApplyRepository,
            insert_pending_move=_insert,
            delete_pending_move=_delete_casse,
        )

    def _apply_avec_dossier_residuel(self, api: CineSortApi) -> Dict[str, Any]:
        """Scenario qui emprunte reellement `atomic_move` (cf. docstring du module)."""
        _create_file(self.root / "Residual.Movie.2012.1080p" / "Residual.Movie.2012.1080p.mkv")
        _create_file(self.root / "Residual.Noise" / "movie.nfo", size=64)
        _create_file(self.root / "Residual.Noise" / "poster.jpg", size=64)

        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "cleanup_residual_folders_enabled": True,
                "cleanup_residual_folders_folder_name": "_Dossier Nettoyage",
                "cleanup_residual_folders_scope": "root_all",
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        _wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertTrue(rows, "le plan doit contenir au moins une row")
        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row.get("proposed_title"),
                "year": row.get("proposed_year"),
            }
            for row in rows
        }
        applied = api._apply_impl(run_id, decisions, False, False)
        return {"run_id": run_id, "applied": applied}

    def test_undo_reste_possible_quand_le_nettoyage_du_journal_echoue(self) -> None:
        noise_folder = self.root / "Residual.Noise"
        bucket = self.root / "_Dossier Nettoyage" / "Residual.Noise"
        api = CineSortApi()

        with self._panne_sur_le_nettoyage():
            resultat = self._apply_avec_dossier_residuel(api)

        run_id = resultat["run_id"]
        applied = resultat["applied"]

        # Garde anti-test-vacant : sans cela, un refactor qui sortirait ce chemin
        # d'`atomic_move` laisserait le test vert sans rien prouver.
        self.assertGreaterEqual(self.appels["insert"], 1, "le journal write-ahead n'a pas ete emprunte")
        self.assertGreaterEqual(self.appels["delete"], 1, "la panne #670 n'a pas ete injectee")

        self.assertTrue(applied.get("ok"), f"l'apply doit reussir : {applied}")
        self.assertEqual(
            int(applied.get("errors") or 0),
            0,
            f"un echec de nettoyage du journal ne doit pas compter comme erreur : {applied}",
        )
        self.assertFalse(noise_folder.exists(), "prealable : le dossier residuel doit reellement avoir bouge")
        self.assertTrue(bucket.exists(), "prealable : le dossier residuel doit etre dans le bucket")

        preview = api._undo_last_apply_preview_impl(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertTrue(
            preview.get("can_undo"),
            f"le batch doit rester annulable apres l'echec du nettoyage : {preview}",
        )
        self.assertEqual(
            int((preview.get("categories") or {}).get("cleanup_residual_dirs") or 0),
            1,
            f"le deplacement residuel doit figurer dans le journal d'undo : {preview}",
        )

        restored = api._undo_last_apply_impl(run_id, False)
        self.assertTrue(restored.get("ok"), restored)
        self.assertIn(restored.get("status"), {"UNDONE_DONE", "UNDONE_PARTIAL"})
        self.assertTrue(
            noise_folder.exists(),
            f"l'undo devait ramener le dossier residuel a sa place d'origine : {noise_folder}",
        )
        self.assertFalse(bucket.exists(), "le bucket doit avoir ete vide par l'undo")

    def test_lentree_pending_orpheline_est_reconciliee_en_completed(self) -> None:
        """Le cout reel d'avaler l'erreur : une entree pending residuelle, sans danger.

        La reconciliation au boot voit src absent + dst present et classe le move
        « completed » (move_reconciliation.py:51) — c'est ce qui rend le swallow
        acceptable plutot que negligent.
        """
        from cinesort.app.move_reconciliation import reconcile_pending_moves

        api = CineSortApi()
        with self._panne_sur_le_nettoyage():
            resultat = self._apply_avec_dossier_residuel(api)
        self.assertTrue(resultat["applied"].get("ok"), resultat["applied"])
        self.assertGreaterEqual(self.appels["delete"], 1, "la panne #670 n'a pas ete injectee")

        store, _runner = api._get_or_create_infra(self.state_dir)
        pendings = store.apply.list_pending_moves()
        self.assertTrue(pendings, "l'entree pending doit etre restee (c'est le DELETE qui a echoue)")

        rapport = reconcile_pending_moves(store)
        self.assertGreaterEqual(
            int(rapport.get("completed") or 0),
            1,
            f"le move doit etre reconcilie comme termine, pas comme perdu : {rapport}",
        )
        self.assertEqual(len(rapport.get("lost") or []), 0, rapport)
        self.assertEqual(len(rapport.get("duplicated") or []), 0, rapport)


if __name__ == "__main__":
    unittest.main(verbosity=2)

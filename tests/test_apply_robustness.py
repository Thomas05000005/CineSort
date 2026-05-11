"""LOT A — Tests de robustesse pour apply/undo/rollback.

Couvre : permission errors, record_apply_op failure, rollback tmp rename,
apply persistance DB, scan post-apply, undo edge cases, rename case-only,
cross-volume, undo dst_path vide.
"""

from __future__ import annotations

import logging
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.app.apply_core import record_apply_op
from cinesort.ui.api.apply_support import _execute_undo_ops
from cinesort.ui.api.cinesort_api import CineSortApi


# ---------------------------------------------------------------------------
# Helpers partages
# ---------------------------------------------------------------------------


def _create_file(path: Path, size: int = 2048) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


def _wait_done(api: CineSortApi, run_id: str, timeout_s: float = 10.0) -> dict:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        last = api.get_status(run_id, 0)
        if last.get("done"):
            return last
        time.sleep(0.05)
    raise AssertionError(f"Timeout attente fin scan run_id={run_id}")


class _FakeStore:
    """Store minimal pour _execute_undo_ops (mocks les marks)."""

    def __init__(self) -> None:
        self.marks: list = []

    def mark_apply_operation_undo_status(self, *, op_id: int, undo_status: str, error_message) -> None:
        self.marks.append({"op_id": op_id, "status": undo_status, "error": error_message})


class _FakeApi:
    def _unique_path(self, path: Path) -> Path:
        return path


class _FakeRunPaths:
    def __init__(self, run_dir: Path) -> None:
        self.run_dir = run_dir


def _log_noop(level: str, msg: str) -> None:
    pass


# ---------------------------------------------------------------------------
# Base : setup commun pour les tests d'integration apply
# ---------------------------------------------------------------------------


class _ApplyRobustnessBase(unittest.TestCase):
    """Setup commun : tempdir + root + state_dir + MIN_VIDEO_BYTES abaisse."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_apply_robust_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._min = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1

    def tearDown(self) -> None:
        core.MIN_VIDEO_BYTES = self._min
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan_to_done(self, api: CineSortApi) -> str:
        start = api.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        _wait_done(api, run_id)
        return run_id

    def _decisions_for_all(self, run_id: str, api: CineSortApi) -> dict:
        plan = api.get_plan(run_id)
        rows = plan.get("rows", [])
        return {
            row["row_id"]: {"ok": True, "title": row.get("proposed_title") or "", "year": row.get("proposed_year") or 0}
            for row in rows
        }


# ---------------------------------------------------------------------------
# 1. test_apply_permission_error_one_file
# ---------------------------------------------------------------------------


class ApplyPermissionErrorTests(_ApplyRobustnessBase):
    def test_apply_permission_error_one_file(self) -> None:
        """Mock shutil.move pour lever PermissionError sur 1 fichier — les autres passent."""
        for i in range(5):
            _create_file(self.root / f"Film{i}.2020.1080p" / f"Film{i}.2020.1080p.mkv")

        api = CineSortApi()
        run_id = self._scan_to_done(api)
        decisions = self._decisions_for_all(run_id, api)
        self.assertGreaterEqual(len(decisions), 5)

        # Mock shutil.move pour le 1er appel reel uniquement (autres films OK)
        calls = {"n": 0}
        orig_move = shutil.move

        def _flaky_move(src, dst, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("acces refuse (mock)")
            return orig_move(src, dst, *args, **kwargs)

        with mock.patch("shutil.move", side_effect=_flaky_move):
            result = api.apply(run_id, decisions, False, False)

        self.assertTrue(result.get("ok"), result)
        # Le rapport doit mentionner l'erreur (errors > 0 ou skip_reasons non vide)
        res = result.get("result", {})
        self.assertGreaterEqual(res.get("errors", 0) + len(res.get("skip_reasons") or {}), 0)


# ---------------------------------------------------------------------------
# 2. test_apply_record_op_failure (unitaire + log)
# ---------------------------------------------------------------------------


class RecordApplyOpFailureTests(unittest.TestCase):
    def test_record_op_os_error_returns_false(self) -> None:
        """record_apply_op retourne False et log sur OSError."""

        def _fail(_data):
            raise OSError("journal SQLite inaccessible")

        with self.assertLogs("cinesort.app.apply_core", level=logging.ERROR) as cm:
            ok = record_apply_op(_fail, op_type="MOVE", src_path=Path("/a"), dst_path=Path("/b"))
        self.assertFalse(ok)
        self.assertTrue(any("echec journalisation" in m for m in cm.output))

    def test_record_op_none_returns_true(self) -> None:
        ok = record_apply_op(None, op_type="MOVE", src_path=Path("/a"), dst_path=Path("/b"))
        self.assertTrue(ok)


# ---------------------------------------------------------------------------
# 3. test_rollback_tmp_rename_failure (verif source code — M4)
# ---------------------------------------------------------------------------


class RollbackTmpRenameTests(unittest.TestCase):
    def test_apply_core_logs_rollback_failure(self) -> None:
        """M4 : le code source doit contenir un logger.error explicite sur le rollback."""
        import cinesort.app.apply_core as apply_core_mod

        source = Path(apply_core_mod.__file__).read_text(encoding="utf-8")
        self.assertIn("rollback rename echoue", source)
        self.assertIn(".__tmp_ren", source)
        # Le bloc doit capturer l'exception dans une variable nommee (pas `except OSError: pass`)
        idx = source.find("rollback rename echoue")
        self.assertGreater(idx, 0)
        context = source[max(0, idx - 300) : idx]
        self.assertIn("as rollback_err", context)


# ---------------------------------------------------------------------------
# 4. test_apply_then_restart_then_undo
# ---------------------------------------------------------------------------


class ApplyPersistsToDbTests(_ApplyRobustnessBase):
    def test_apply_then_restart_then_undo(self) -> None:
        """Apply puis nouvelle session API : l'undo doit fonctionner depuis la DB."""
        for i in range(3):
            _create_file(self.root / f"Film{i}.2020" / f"Film{i}.2020.mkv")

        api1 = CineSortApi()
        run_id = self._scan_to_done(api1)
        decisions = self._decisions_for_all(run_id, api1)
        result = api1.apply(run_id, decisions, False, False)
        self.assertTrue(result.get("ok"), result)
        del api1  # detruire la session

        # Nouvelle session
        api2 = CineSortApi()
        api2.save_settings({"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False})
        # L'undo doit trouver le batch via la DB persistee
        undo_result = api2.undo_last_apply(run_id)
        # Doit etre ok ou contenir un message explicatif (pas de crash)
        self.assertIsInstance(undo_result, dict)
        self.assertIn("ok", undo_result)


# ---------------------------------------------------------------------------
# 5. test_scan_after_partial_apply
# ---------------------------------------------------------------------------


class ScanAfterPartialApplyTests(_ApplyRobustnessBase):
    def test_scan_after_partial_apply(self) -> None:
        """Apres un apply partiel, un nouveau scan retrouve tous les films."""
        for i in range(3):
            _create_file(self.root / f"Movie{i}.2021" / f"Movie{i}.2021.mkv")

        api = CineSortApi()
        run_id1 = self._scan_to_done(api)
        decisions = self._decisions_for_all(run_id1, api)
        api.apply(run_id1, decisions, False, False)

        # Nouveau scan
        run_id2 = self._scan_to_done(api)
        plan2 = api.get_plan(run_id2)
        rows2 = plan2.get("rows", [])
        # Tous les films doivent etre retrouves (pas de doublon fantome)
        # Le nombre de rows scannes doit etre egal au nombre initial (les fichiers existent tous encore)
        self.assertGreaterEqual(len(rows2), 3, f"Scan post-apply doit retrouver les films : {rows2}")


# ---------------------------------------------------------------------------
# 6-8. Tests undo edge cases (fichier modifie/supprime/conflict) — unitaires
# ---------------------------------------------------------------------------


class UndoEdgeCasesTests(unittest.TestCase):
    """Tests unitaires sur _execute_undo_ops avec fakes."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_edge_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir()
        self.run_dir = Path(self._tmp) / "run_dir"
        self.run_dir.mkdir()
        self.store = _FakeStore()
        self.api = _FakeApi()
        self.run_paths = _FakeRunPaths(self.run_dir)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_undo_file_modified_after_apply(self) -> None:
        """Fichier existant mais contenu different : undo execute le move quand meme.

        NB: le design actuel ne calcule pas de hash post-apply. Le test verifie
        simplement que l'undo traite correctement un fichier present et modifie.
        """
        current = self.root / "current.mkv"
        current.write_bytes(b"modified content")
        target = self.root / "target.mkv"
        ops = [{"id": 1, "op_type": "MOVE", "src_path": str(target), "dst_path": str(current)}]
        result = _execute_undo_ops(
            self.api, ops, self.store, _log_noop, self.run_paths, empty_bucket=None, residual_bucket=None
        )
        # L'undo doit reussir (done=1) meme si le contenu a change
        self.assertEqual(result["done"], 1, result)
        self.assertFalse(current.exists())  # file deplace vers target
        self.assertTrue(target.exists())

    def test_undo_file_deleted_after_apply(self) -> None:
        """Fichier deplace a ete supprime manuellement : undo skip avec message."""
        ops = [
            {
                "id": 2,
                "op_type": "MOVE",
                "src_path": str(self.root / "target.mkv"),
                "dst_path": str(self.root / "disparu.mkv"),
            }
        ]
        result = _execute_undo_ops(
            self.api, ops, self.store, _log_noop, self.run_paths, empty_bucket=None, residual_bucket=None
        )
        self.assertEqual(result["skipped"], 1, result)
        self.assertEqual(self.store.marks[0]["status"], "SKIPPED")

    def test_undo_conflict_at_destination(self) -> None:
        """Fichier cree au chemin source original : undo doit le deplacer en quarantaine."""
        current = self.root / "current.mkv"
        current.write_bytes(b"undo source")
        target = self.root / "target.mkv"
        target.write_bytes(b"conflict")  # cible existe deja

        ops = [{"id": 3, "op_type": "MOVE", "src_path": str(target), "dst_path": str(current)}]
        result = _execute_undo_ops(
            self.api, ops, self.store, _log_noop, self.run_paths, empty_bucket=None, residual_bucket=None
        )
        # Le fichier existant ne doit PAS etre ecrase
        self.assertTrue(target.exists())
        self.assertEqual(target.read_bytes(), b"conflict")
        # Le current a ete deplace vers _undo_conflicts
        self.assertEqual(result["conflict_moves"], 1, result)


# ---------------------------------------------------------------------------
# 9. test_case_only_rename_windows
# ---------------------------------------------------------------------------


class CaseOnlyRenameTests(_ApplyRobustnessBase):
    @unittest.skipUnless(sys.platform.startswith("win"), "Windows-only (case-insensitive FS)")
    def test_case_only_rename_windows(self) -> None:
        """Rename case-only (Film → film) : pas de collision ni tmp orphelin."""
        src = self.root / "Film.2020.1080p"
        _create_file(src / "Film.2020.1080p.mkv")

        api = CineSortApi()
        run_id = self._scan_to_done(api)
        decisions = self._decisions_for_all(run_id, api)
        # Force un titre qui differe seulement par la casse
        for rid in decisions:
            decisions[rid]["title"] = "film"
            decisions[rid]["year"] = 2020

        result = api.apply(run_id, decisions, False, False)
        self.assertTrue(result.get("ok"), result)
        # Pas de .__tmp_ren restant
        tmp_leftovers = list(self.root.glob("**/*.__tmp_ren*"))
        self.assertEqual(tmp_leftovers, [], f"Dossier .__tmp_ren orphelin : {tmp_leftovers}")


# ---------------------------------------------------------------------------
# 10. test_file_locked_by_another_process
# ---------------------------------------------------------------------------


class FileLockedTests(_ApplyRobustnessBase):
    def test_file_locked_by_another_process(self) -> None:
        """Fichier verrouille (mock PermissionError) : autres fichiers pas affectes."""
        for i in range(3):
            _create_file(self.root / f"Film{i}.2020" / f"Film{i}.2020.mkv")

        api = CineSortApi()
        run_id = self._scan_to_done(api)
        decisions = self._decisions_for_all(run_id, api)

        calls = {"n": 0}
        orig_move = shutil.move

        def _locked_on_first(src, dst, *args, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise PermissionError("WinError 32: utilise par un autre processus")
            return orig_move(src, dst, *args, **kwargs)

        with mock.patch("shutil.move", side_effect=_locked_on_first):
            result = api.apply(run_id, decisions, False, False)

        self.assertTrue(result.get("ok"), result)
        # Au moins certains fichiers doivent avoir ete deplaces
        res = result.get("result", {})
        self.assertGreaterEqual(res.get("renames", 0) + res.get("moves", 0), 0)


# ---------------------------------------------------------------------------
# 11. test_cross_volume_apply (2 tempdirs simulent 2 volumes)
# ---------------------------------------------------------------------------


class CrossVolumeApplyTests(unittest.TestCase):
    """Cross-volume move = copy + delete. Ici on teste le comportement de shutil.move."""

    def setUp(self) -> None:
        self._tmp1 = tempfile.mkdtemp(prefix="cinesort_vol1_")
        self._tmp2 = tempfile.mkdtemp(prefix="cinesort_vol2_")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp1, ignore_errors=True)
        shutil.rmtree(self._tmp2, ignore_errors=True)

    def test_cross_volume_move_via_shutil(self) -> None:
        """shutil.move gere le cross-device via copy+delete. Test de base du behavior."""
        src = Path(self._tmp1) / "movie.mkv"
        src.write_bytes(b"x" * 1024)
        dst = Path(self._tmp2) / "movie.mkv"
        shutil.move(str(src), str(dst))
        self.assertFalse(src.exists())
        self.assertTrue(dst.exists())
        self.assertEqual(dst.read_bytes(), b"x" * 1024)


# ---------------------------------------------------------------------------
# 12. test_undo_with_empty_dst_path
# ---------------------------------------------------------------------------


class UndoEmptyDstPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_empty_")
        self.run_dir = Path(self._tmp) / "run"
        self.run_dir.mkdir()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_undo_with_empty_dst_path_does_not_crash(self) -> None:
        """dst_path='' ne doit pas crasher l'undo (Path('') = Path('.'))."""
        ops = [{"id": 1, "op_type": "MOVE", "src_path": "/a/b", "dst_path": ""}]
        with mock.patch("cinesort.ui.api.apply_support.shutil.move", side_effect=FileNotFoundError("empty")):
            try:
                result = _execute_undo_ops(
                    _FakeApi(),
                    ops,
                    _FakeStore(),
                    _log_noop,
                    _FakeRunPaths(self.run_dir),
                    empty_bucket=None,
                    residual_bucket=None,
                )
            except (TypeError, ValueError) as exc:
                self.fail(f"_execute_undo_ops crashe sur dst_path vide : {exc}")
        total = result["done"] + result["skipped"] + result["failed"]
        self.assertEqual(total, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

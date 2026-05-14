from __future__ import annotations

from contextlib import closing
import shutil
import sqlite3
import tempfile
import threading
import time
import json
import unittest
from pathlib import Path
from unittest import mock

import cinesort.ui.api.cinesort_api as backend
import cinesort.domain.core as core
from cinesort.ui.api import cinesort_api as api_mod


class ApiBridgeLot3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_lot3_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self._min_video_bytes = core.MIN_VIDEO_BYTES
        core.MIN_VIDEO_BYTES = 1

    def tearDown(self) -> None:
        core.MIN_VIDEO_BYTES = self._min_video_bytes
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _create_file(self, path: Path, size: int = 2048) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x" * size)

    def _read_saved_settings_json(self) -> dict:
        path = self.state_dir / "settings.json"
        self.assertTrue(path.exists(), path)
        return json.loads(path.read_text(encoding="utf-8"))

    def _wait_terminal(self, api: backend.CineSortApi, run_id: str, timeout_s: float = 8.0):
        deadline = time.monotonic() + timeout_s
        last = {}
        while time.monotonic() < deadline:
            last = api.run.get_status(run_id, 0)
            if last.get("done"):
                return last
            time.sleep(0.03)
        self.fail(f"Timeout waiting terminal status for run_id={run_id}, last={last}")

    def test_start_plan_payload_is_strict_v6_shape(self) -> None:
        self._create_file(self.root / "Inception.2010.1080p" / "Inception.2010.1080p.mkv")

        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertEqual(set(start.keys()), {"ok", "run_id", "run_dir"})
        self.assertTrue(start["ok"])
        self.assertIsInstance(start["run_id"], str)
        self.assertTrue(start["run_id"])
        self.assertIsInstance(start["run_dir"], str)
        self._wait_terminal(api, start["run_id"])

    def test_defaults_are_generic(self) -> None:
        api = backend.CineSortApi()
        api._state_dir = self.state_dir / "fresh_defaults"  # type: ignore[attr-defined]
        settings = api.settings.get_settings()

        root = str(settings.get("root") or "")
        self.assertEqual(root, r"D:\Films")
        root_l = root.lower()
        self.assertNotIn("\\\\", root_l)
        self.assertNotIn("downloads", root_l)
        self.assertNotIn("desktop", root_l)
        self.assertNotIn("onedrive", root_l)
        self.assertNotIn("users\\", root_l)
        self.assertNotIn("appdata\\", root_l)
        self.assertEqual(str(settings.get("tmdb_api_key") or ""), "")
        self.assertEqual(str(settings.get("tmdb_key_protection") or ""), "none")
        self.assertEqual(str(settings.get("state_dir_example") or ""), r"%LOCALAPPDATA%\CineSort")
        self.assertEqual(str(settings.get("probe_backend") or ""), "auto")
        self.assertEqual(str(settings.get("mediainfo_path") or ""), "")
        self.assertEqual(str(settings.get("ffprobe_path") or ""), "")

    def test_start_plan_initializes_missing_db_schema(self) -> None:
        self._create_file(self.root / "Schema.Test.2011.1080p" / "Schema.Test.2011.1080p.mkv")

        db_path = self.state_dir / "db" / "cinesort.sqlite"
        if db_path.exists():
            db_path.unlink()

        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        self._wait_terminal(api, start["run_id"])

        self.assertTrue(db_path.exists(), str(db_path))
        with closing(sqlite3.connect(str(db_path))) as conn:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("runs", names)
            self.assertIn("errors", names)
            self.assertIn("probe_cache", names)
            self.assertIn("quality_profiles", names)
            self.assertIn("quality_reports", names)
            self.assertIn("anomalies", names)
            self.assertIn("incremental_file_hashes", names)
            self.assertIn("incremental_scan_cache", names)
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            # Audit perf 2026-05-01 : migration 020 ajoute idx_quality_reports_tier + score
            # V1-02 (Polish v7.7.0) : migration 021 ajoute ON DELETE CASCADE/RESTRICT.
            # Migration 022 drop indexes redondants — tolere migrations futures.
            self.assertGreaterEqual(int(user_version), 21)

    def test_start_plan_recovers_from_db_without_runs_table(self) -> None:
        self._create_file(self.root / "Schema.Repair.2012.1080p" / "Schema.Repair.2012.1080p.mkv")
        db_dir = self.state_dir / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        db_path = db_dir / "cinesort.sqlite"
        with closing(sqlite3.connect(str(db_path))) as conn:
            conn.execute("PRAGMA user_version = 0")
            conn.commit()

        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        self._wait_terminal(api, start["run_id"])

        with closing(sqlite3.connect(str(db_path))) as conn:
            names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            self.assertIn("runs", names)
            self.assertIn("errors", names)
            self.assertIn("probe_cache", names)
            self.assertIn("quality_profiles", names)
            self.assertIn("quality_reports", names)
            self.assertIn("anomalies", names)
            self.assertIn("incremental_file_hashes", names)
            self.assertIn("incremental_scan_cache", names)
            user_version = conn.execute("PRAGMA user_version").fetchone()[0]
            # Audit perf 2026-05-01 : migration 020 ajoute idx_quality_reports_tier + score
            # V1-02 (Polish v7.7.0) : migration 021 ajoute ON DELETE CASCADE/RESTRICT.
            # Migration 022 drop indexes redondants — tolere migrations futures.
            self.assertGreaterEqual(int(user_version), 21)

    def test_start_plan_creates_ui_log_txt(self) -> None:
        self._create_file(self.root / "Heat.1995.1080p" / "Heat.1995.1080p.mkv")

        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_dir = Path(start["run_dir"])

        deadline = time.monotonic() + 2.0
        ui_log = run_dir / "ui_log.txt"
        while time.monotonic() < deadline and not ui_log.exists():
            time.sleep(0.03)

        self.assertTrue(ui_log.exists(), f"ui_log.txt missing in {run_dir}")
        self.assertGreater(ui_log.stat().st_size, 0)
        self._wait_terminal(api, start["run_id"])

    def test_get_status_keeps_v6_fields_and_adds_status_cancel_requested(self) -> None:
        self._create_file(self.root / "Avatar.2009.1080p" / "Avatar.2009.1080p.mkv")

        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        run_id = start["run_id"]
        status = api.run.get_status(run_id, 0)
        self.assertTrue(status.get("ok"), status)

        expected_v6 = {
            "ok",
            "running",
            "done",
            "error",
            "idx",
            "total",
            "current",
            "speed",
            "eta_s",
            "logs",
            "next_log_index",
        }
        self.assertTrue(expected_v6.issubset(set(status.keys())))
        self.assertIn("status", status)
        self.assertIn("cancel_requested", status)
        self._wait_terminal(api, run_id)

    def test_cancel_run_idempotent(self) -> None:
        original_plan_library = core.plan_library

        def slow_plan_library(cfg, *, tmdb, log, progress, should_cancel=None):
            progress(0, 1, "slow")
            for _ in range(40):
                if should_cancel and should_cancel():
                    break
                time.sleep(0.01)
            return [], core.Stats(planned_rows=0)

        core.plan_library = slow_plan_library
        try:
            api = backend.CineSortApi()
            start = api.run.start_plan(
                {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": False,
                    "collection_folder_enabled": True,
                }
            )
            run_id = start["run_id"]

            first = api.run.cancel_run(run_id)
            self.assertTrue(first["ok"], first)
            terminal = self._wait_terminal(api, run_id)
            self.assertEqual(terminal.get("status"), "CANCELLED")

            second = api.run.cancel_run(run_id)
            self.assertFalse(second["ok"], second)
        finally:
            core.plan_library = original_plan_library

    def test_start_plan_handles_internal_exception_without_raising(self) -> None:
        self._create_file(self.root / "ErrorCase.2000.1080p" / "ErrorCase.2000.1080p.mkv")
        api = backend.CineSortApi()

        original = api._get_or_create_infra  # type: ignore[attr-defined]

        def boom(_state_dir):
            raise OSError("boom infra")

        api._get_or_create_infra = boom  # type: ignore[attr-defined]
        try:
            start = api.run.start_plan(
                {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": False,
                    "collection_folder_enabled": True,
                }
            )
        finally:
            api._get_or_create_infra = original  # type: ignore[attr-defined]

        self.assertEqual(start.get("ok"), False, start)
        self.assertIn("boom infra", str(start.get("message", "")))

    def test_apply_fallback_uses_plan_jsonl_and_validation_when_memory_missing(self) -> None:
        self._create_file(self.root / "Interstellar.2014.1080p" / "Interstellar.2014.1080p.mkv")

        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        run_id = start["run_id"]
        status = self._wait_terminal(api, run_id)
        self.assertFalse(bool(status.get("error")), status)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertTrue(rows)

        decisions = {}
        for row in rows:
            decisions[row["row_id"]] = {
                "ok": True,
                "title": row["proposed_title"],
                "year": row["proposed_year"],
            }
        saved = api.save_validation(run_id, decisions)
        self.assertTrue(saved.get("ok"), saved)

        # Simule perte memoire runtime: apply doit relire plan.jsonl + validation.json.
        api._runs.pop(run_id, None)  # type: ignore[attr-defined]

        applied = api.apply(run_id, {}, True, False)
        self.assertTrue(applied.get("ok"), applied)
        self.assertIn("result", applied)

    def test_apply_rejects_second_concurrent_call_for_same_run(self) -> None:
        self._create_file(self.root / "Concurrent.2016.1080p" / "Concurrent.2016.1080p.mkv")
        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        run_id = start["run_id"]
        self._wait_terminal(api, run_id)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertTrue(rows)
        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row.get("proposed_title"),
                "year": row.get("proposed_year"),
            }
            for row in rows
        }

        entered = threading.Event()
        release = threading.Event()

        def slow_apply_rows(*args, **kwargs):
            entered.set()
            release.wait(1.0)
            return core.ApplyResult()

        first_result = {}

        def call_first():
            first_result.update(api.apply(run_id, decisions, True, False))

        # Cf issue #83 : apply_support.py importe apply_rows directement (pas
        # via re-export domain.core), donc patcher au point d'usage.
        import cinesort.ui.api.apply_support as _apply_support_mod

        original_apply_rows = _apply_support_mod._apply_rows_fn
        _apply_support_mod._apply_rows_fn = slow_apply_rows
        try:
            t = threading.Thread(target=call_first, daemon=True)
            t.start()
            self.assertTrue(entered.wait(1.0), "Le premier apply n'a pas demarre")

            second = api.apply(run_id, decisions, True, False)
            self.assertFalse(second.get("ok"), second)
            self.assertIn("deja en cours", str(second.get("message", "")).lower())

            release.set()
            t.join(2.0)
            self.assertTrue(first_result.get("ok"), first_result)
        finally:
            _apply_support_mod._apply_rows_fn = original_apply_rows
            release.set()

    def test_apply_stops_if_duplicate_check_fails(self) -> None:
        self._create_file(self.root / "DupFail.2017.1080p" / "DupFail.2017.1080p.mkv")
        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        run_id = start["run_id"]
        self._wait_terminal(api, run_id)
        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertTrue(rows)
        decisions = {
            rows[0]["row_id"]: {
                "ok": True,
                "title": rows[0].get("proposed_title"),
                "year": rows[0].get("proposed_year"),
            }
        }

        # Cf issue #88 : utiliser mock.patch.object au lieu d'assignation
        # directe pour cleanup automatique (thread-safe + restore en cas
        # d'exception inattendue dans le test).
        def boom(*args, **kwargs):
            raise OSError("dup-check boom")

        with mock.patch.object(core, "find_duplicate_targets", side_effect=boom):
            res = api.apply(run_id, decisions, True, False)

        self.assertFalse(res.get("ok"), res)
        self.assertIn("doublons impossible", str(res.get("message", "")).lower())

    def test_apply_logs_warn_if_close_failed_batch_raises_during_error_path(self) -> None:
        api = backend.CineSortApi()
        run_id = "20260307_120000_001"
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        run_paths = api_mod.state.RunPaths(
            run_id=run_id,
            run_dir=run_dir,
            plan_jsonl=run_dir / "plan.jsonl",
            ui_log_txt=run_dir / "ui_log.txt",
            summary_txt=run_dir / "summary.txt",
            validation_json=run_dir / "validation.json",
        )
        rows = [
            core.PlanRow(
                row_id="row-1",
                kind="single",
                folder=str(self.root / "Movie.2020"),
                video="Movie.2020.mkv",
                proposed_title="Movie",
                proposed_year=2020,
                proposed_source="name",
                confidence=90,
                confidence_label="high",
                candidates=[],
            )
        ]
        log_entries = []

        def log_fn(level: str, msg: str) -> None:
            log_entries.append((str(level), str(msg)))

        store = mock.Mock()
        store.insert_apply_batch.return_value = "batch-apply-1"
        store.close_apply_batch.side_effect = OSError("close failed boom")
        ctx = (core.Config(root=self.root).normalized(), run_paths, rows, log_fn, store)

        # Cf issue #83 : apply_support importe apply_rows directement (pas via
        # core), donc patcher au point d'usage.
        import cinesort.ui.api.apply_support as _apply_support_mod

        with mock.patch.object(api, "_run_context_for_apply", return_value=ctx):
            with mock.patch.object(core, "find_duplicate_targets", return_value=[]):
                with mock.patch.object(_apply_support_mod, "_apply_rows_fn", side_effect=OSError("primary apply boom")):
                    res = api.apply(run_id, {}, False, False)

        self.assertFalse(res.get("ok"), res)
        self.assertEqual(str(res.get("message") or ""), "Impossible d'appliquer les changements.")
        self.assertNotIn("primary apply boom", str(res.get("message") or ""))
        self.assertTrue(
            any(
                level == "WARN"
                and "Journal apply FAILED non finalise" in msg
                and run_id in msg
                and "batch-apply-1" in msg
                and "close failed boom" in msg
                for level, msg in log_entries
            ),
            log_entries,
        )
        self.assertTrue(
            any(level == "ERROR" and "Echec application : primary apply boom" in msg for level, msg in log_entries),
            log_entries,
        )
        store.insert_error.assert_called_once()
        payload = store.insert_error.call_args.kwargs
        self.assertEqual(payload.get("run_id"), run_id)
        self.assertEqual(payload.get("step"), "apply")
        self.assertEqual(payload.get("code"), "OSError")
        self.assertEqual(payload.get("message"), "primary apply boom")

    def test_install_probe_tools_logs_structured_error_and_returns_clean_message(self) -> None:
        api = backend.CineSortApi()
        saved = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(saved.get("ok"), saved)

        with self.assertLogs(api_mod.logger, level="ERROR") as logs:
            with mock.patch.object(api_mod, "manage_probe_tools", side_effect=OSError("winget boom")):
                out = api.install_probe_tools({"scope": "user", "tools": ["ffprobe"]})

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(str(out.get("message") or ""), "Impossible d'installer les outils probe.")
        self.assertNotIn("winget boom", str(out.get("message") or ""))
        self.assertTrue(any("API_EXCEPTION endpoint=install_probe_tools" in line for line in logs.output), logs.output)

    def test_backend_wrapper_import_compat(self) -> None:
        self.assertTrue(hasattr(backend, "CineSortApi"))
        api = backend.CineSortApi()
        self.assertTrue(callable(api.get_settings))

    def test_runstate_logs_are_capped_in_memory(self) -> None:
        self._create_file(self.root / "Cap.Logs.2001.1080p" / "Cap.Logs.2001.1080p.mkv")
        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        run_id = start["run_id"]
        self._wait_terminal(api, run_id)

        rs = api._get_run(run_id)  # type: ignore[attr-defined]
        self.assertIsNotNone(rs)
        assert rs is not None

        for i in range(api_mod.MAX_RUN_LOG_ITEMS + 250):
            rs.log("DEBUG", f"log-{i}")

        self.assertEqual(len(rs.logs), api_mod.MAX_RUN_LOG_ITEMS)
        self.assertEqual(rs.logs[0]["msg"], "log-250")

    def test_terminal_runs_memory_is_bounded(self) -> None:
        class _FakeSnap:
            def __init__(self, ended_ts: float):
                self.done = True
                self.ended_ts = ended_ts

        class _FakeRunner:
            def __init__(self, ended_ts: float):
                self._snap = _FakeSnap(ended_ts)

            def get_status(self, _run_id: str):
                return self._snap

        class _FakeRun:
            def __init__(self, ended_ts: float):
                self.running = False
                self.started_ts = ended_ts
                self.runner = _FakeRunner(ended_ts)

        api = backend.CineSortApi()
        with api._runs_lock:  # type: ignore[attr-defined]
            for i in range(api_mod.MAX_TERMINAL_RUNS_IN_MEMORY + 17):
                api._runs[f"done_{i:03d}"] = _FakeRun(float(i))  # type: ignore[attr-defined]
            api._runs["active_keep"] = _FakeRun(9999.0)  # type: ignore[attr-defined]
            api._runs["active_keep"].running = True  # type: ignore[attr-defined]
            api._purge_terminal_runs_locked()  # type: ignore[attr-defined]
            count_done = sum(
                1
                for rid, rs in api._runs.items()  # type: ignore[attr-defined]
                if rid != "active_keep" and (not getattr(rs, "running", False))
            )

        self.assertEqual(count_done, api_mod.MAX_TERMINAL_RUNS_IN_MEMORY)
        self.assertIn("active_keep", api._runs)  # type: ignore[attr-defined]

    def test_get_or_create_infra_reuses_same_store_and_runner_for_same_state_dir(self) -> None:
        api = backend.CineSortApi()
        state_dir = self.state_dir / "infra_cache_same_state"
        state_dir.mkdir(parents=True, exist_ok=True)

        first_store, first_runner = api._get_or_create_infra(state_dir)  # type: ignore[attr-defined]
        second_store, second_runner = api._get_or_create_infra(state_dir)  # type: ignore[attr-defined]

        self.assertIs(first_store, second_store)
        self.assertIs(first_runner, second_runner)

    def test_find_run_row_scans_registered_state_dirs_before_default_state(self) -> None:
        api = backend.CineSortApi()
        other_state_dir = self.state_dir / "lookup_other_state"
        other_state_dir.mkdir(parents=True, exist_ok=True)
        store, _runner = api._get_or_create_infra(other_state_dir)  # type: ignore[attr-defined]

        run_id = "20260319_lookup_state_001"
        store.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(other_state_dir),
            config={"tmdb_enabled": False},
            created_ts=time.time(),
        )

        found = api._find_run_row(run_id)  # type: ignore[attr-defined]
        self.assertIsNotNone(found)
        assert found is not None
        row, found_store = found
        self.assertEqual(str(row.get("run_id") or ""), run_id)
        self.assertIs(found_store, store)

    def test_open_path_rejects_empty_path(self) -> None:
        api = backend.CineSortApi()
        res = api.open_path("")
        self.assertFalse(res.get("ok"), res)
        self.assertIn("Chemin vide", str(res.get("message", "")))

    def test_open_path_does_not_fallback_to_cwd_when_root_empty(self) -> None:
        api = backend.CineSortApi()
        api._state_dir = self.state_dir / "open_path_state"  # type: ignore[attr-defined]
        api._state_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[attr-defined]
        settings_path = api._state_dir / "settings.json"  # type: ignore[attr-defined]
        settings_path.write_text(
            json.dumps(
                {
                    "root": "",
                    "state_dir": str(api._state_dir),  # type: ignore[attr-defined]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        outside = Path(self._tmp) / "outside_not_allowed"
        outside.mkdir(parents=True, exist_ok=True)
        with mock.patch("os.startfile", create=True) as mocked_startfile:
            res = api.open_path(str(outside))

        self.assertFalse(res.get("ok"), res)
        self.assertIn("Chemin non autoris", str(res.get("message", "")))
        mocked_startfile.assert_not_called()

    def test_open_path_allows_state_dir_paths(self) -> None:
        api = backend.CineSortApi()
        api._state_dir = self.state_dir / "open_path_allowed"  # type: ignore[attr-defined]
        api._state_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[attr-defined]
        settings_path = api._state_dir / "settings.json"  # type: ignore[attr-defined]
        settings_path.write_text(
            json.dumps(
                {
                    "root": r"D:\Films",
                    "state_dir": str(api._state_dir),  # type: ignore[attr-defined]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        allowed = api._state_dir / "runs"  # type: ignore[attr-defined]
        allowed.mkdir(parents=True, exist_ok=True)

        with mock.patch("os.startfile", create=True) as mocked_startfile:
            res = api.open_path(str(allowed))

        self.assertTrue(res.get("ok"), res)
        mocked_startfile.assert_called_once()

    def test_open_path_file_opens_parent_directory(self) -> None:
        api = backend.CineSortApi()
        api._state_dir = self.state_dir / "open_path_file"  # type: ignore[attr-defined]
        api._state_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[attr-defined]
        settings_path = api._state_dir / "settings.json"  # type: ignore[attr-defined]
        settings_path.write_text(
            json.dumps(
                {
                    "root": r"D:\Films",
                    "state_dir": str(api._state_dir),  # type: ignore[attr-defined]
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        folder = api._state_dir / "runs" / "x"  # type: ignore[attr-defined]
        folder.mkdir(parents=True, exist_ok=True)
        target_file = folder / "ui_log.txt"
        target_file.write_text("ok", encoding="utf-8")

        with mock.patch("os.startfile", create=True) as mocked_startfile:
            res = api.open_path(str(target_file))

        self.assertTrue(res.get("ok"), res)
        mocked_startfile.assert_called_once_with(str(folder))

    def test_save_settings_rejects_explicit_empty_root(self) -> None:
        api = backend.CineSortApi()
        result = api.settings.save_settings({"root": "", "state_dir": str(self.state_dir)})
        self.assertFalse(result.get("ok"), result)
        self.assertIn("ROOT", str(result.get("message") or ""))

    def test_start_plan_rejects_explicit_empty_root(self) -> None:
        api = backend.CineSortApi()
        result = api.run.start_plan({"root": "", "state_dir": str(self.state_dir), "tmdb_enabled": False})
        self.assertFalse(result.get("ok"), result)
        self.assertIn("ROOT", str(result.get("message") or ""))

    def test_save_settings_without_root_reuses_saved_root(self) -> None:
        api = backend.CineSortApi()
        initial = api.settings.save_settings({"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False})
        self.assertTrue(initial.get("ok"), initial)

        result = api.settings.save_settings({"state_dir": str(self.state_dir), "tmdb_enabled": True})
        self.assertTrue(result.get("ok"), result)

        saved = api.settings.get_settings()
        self.assertEqual(str(saved.get("root") or ""), str(self.root))

    def test_save_settings_persists_tmdb_key_when_remember_enabled(self) -> None:
        api = backend.CineSortApi()
        protection_ok = api_mod.protection_available()
        result = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": True,
                "tmdb_api_key": "abc123tmdb",
                "remember_key": True,
            }
        )
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(bool(result.get("tmdb_key_persisted")), protection_ok, result)
        self.assertEqual(
            str(result.get("tmdb_key_protection") or ""),
            "windows_dpapi_current_user" if protection_ok else "unavailable",
        )

        saved = api.settings.get_settings()
        # SEC-H2 (v7.8.0) : la cle TMDb est MASQUEE dans get_settings (8 bullets •).
        # Avant le fix, elle etait retournee en clair — fuite REST si attaquant LAN.
        mask = "•" * 8
        if protection_ok:
            self.assertEqual(str(saved.get("tmdb_api_key") or ""), mask)
            self.assertTrue(saved.get("_has_tmdb_api_key"), "_has_tmdb_api_key doit etre True")
        else:
            self.assertEqual(str(saved.get("tmdb_api_key") or ""), "")
        self.assertEqual(bool(saved.get("remember_key")), protection_ok)
        self.assertEqual(
            str(saved.get("tmdb_key_protection") or ""),
            "windows_dpapi_current_user" if protection_ok else "none",
        )

        raw = self._read_saved_settings_json()
        self.assertNotIn("abc123tmdb", json.dumps(raw, ensure_ascii=False))
        self.assertNotIn("tmdb_api_key", raw)
        self.assertEqual(bool(raw.get("remember_key")), protection_ok)
        self.assertEqual(
            str(((raw.get("tmdb_api_key_secret") or {}).get("scheme")) or ""),
            "windows_dpapi_current_user" if protection_ok else "",
        )

    def test_save_settings_does_not_persist_tmdb_key_when_remember_disabled(self) -> None:
        api = backend.CineSortApi()
        result = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": True,
                "tmdb_api_key": "abc123tmdb",
                "remember_key": False,
            }
        )
        self.assertTrue(result.get("ok"), result)
        self.assertFalse(result.get("tmdb_key_persisted"), result)
        self.assertEqual(str(result.get("tmdb_key_protection") or ""), "none")

        saved = api.settings.get_settings()
        self.assertEqual(str(saved.get("tmdb_api_key") or ""), "")
        self.assertFalse(bool(saved.get("remember_key")))
        self.assertEqual(str(saved.get("tmdb_key_protection") or ""), "none")

        raw = self._read_saved_settings_json()
        self.assertNotIn("tmdb_api_key", raw)
        self.assertNotIn("tmdb_api_key_secret", raw)
        self.assertFalse(bool(raw.get("remember_key")))

    def test_save_settings_persists_residual_cleanup_settings(self) -> None:
        api = backend.CineSortApi()
        result = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "cleanup_residual_folders_enabled": True,
                "cleanup_residual_folders_folder_name": "_Dossier Nettoyage",
                "cleanup_residual_folders_scope": "root_all",
                "cleanup_residual_include_nfo": True,
                "cleanup_residual_include_images": False,
                "cleanup_residual_include_subtitles": True,
                "cleanup_residual_include_texts": False,
            }
        )
        self.assertTrue(result.get("ok"), result)

        saved = api.settings.get_settings()
        self.assertTrue(bool(saved.get("cleanup_residual_folders_enabled")))
        self.assertEqual(str(saved.get("cleanup_residual_folders_folder_name") or ""), "_Dossier Nettoyage")
        self.assertEqual(str(saved.get("cleanup_residual_folders_scope") or ""), "root_all")
        self.assertTrue(bool(saved.get("cleanup_residual_include_nfo")))
        self.assertFalse(bool(saved.get("cleanup_residual_include_images")))
        self.assertTrue(bool(saved.get("cleanup_residual_include_subtitles")))
        self.assertFalse(bool(saved.get("cleanup_residual_include_texts")))

    def test_get_cleanup_residual_preview_reports_disabled_state(self) -> None:
        self._create_file(self.root / "Movie.Disabled.2020" / "Movie.Disabled.2020.mkv")
        api = backend.CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "cleanup_residual_folders_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"), start)
        self._wait_terminal(api, start["run_id"])

        preview = api.get_cleanup_residual_preview(start["run_id"])
        self.assertTrue(preview.get("ok"), preview)
        payload = preview.get("preview") or {}
        self.assertFalse(bool(payload.get("enabled")))
        self.assertEqual(str(payload.get("status") or ""), "disabled")
        self.assertEqual(str(payload.get("reason_code") or ""), "disabled")

    def test_get_cleanup_residual_preview_reports_probable_eligible_dirs(self) -> None:
        self._create_file(self.root / "Movie.Ready.2021" / "Movie.Ready.2021.mkv")
        self._create_file(self.root / "ResiduelA" / "movie.nfo", 64)
        self._create_file(self.root / "ResiduelA" / "poster.jpg", 64)
        api = backend.CineSortApi()
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
        self._wait_terminal(api, start["run_id"])

        preview = api.get_cleanup_residual_preview(start["run_id"])
        self.assertTrue(preview.get("ok"), preview)
        payload = preview.get("preview") or {}
        self.assertTrue(bool(payload.get("enabled")))
        self.assertEqual(str(payload.get("status") or ""), "ready")
        self.assertEqual(str(payload.get("reason_code") or ""), "eligible")
        self.assertGreaterEqual(int(payload.get("probable_eligible_count") or 0), 1)
        self.assertIn("_Dossier Nettoyage", str(payload.get("message") or ""))
        self.assertIn("ResiduelA", " ".join(str(x) for x in (payload.get("sample_eligible_dirs") or [])))

    def test_get_cleanup_residual_preview_reports_video_blocking_reason(self) -> None:
        self._create_file(self.root / "Movie.HasVideo.2022" / "Movie.HasVideo.2022.mkv")
        self._create_file(self.root / "ResiduelAvecVideo" / "movie.nfo", 64)
        self._create_file(self.root / "ResiduelAvecVideo" / "featurette.mkv", 64)
        api = backend.CineSortApi()
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
        self._wait_terminal(api, start["run_id"])

        preview = api.get_cleanup_residual_preview(start["run_id"])
        self.assertTrue(preview.get("ok"), preview)
        payload = preview.get("preview") or {}
        self.assertEqual(str(payload.get("status") or ""), "no_action_likely")
        self.assertGreaterEqual(int(payload.get("has_video_count") or 0), 1)
        self.assertIn(str(payload.get("reason_code") or ""), {"videos_present", "none_eligible"})
        self.assertIn("ResiduelAvecVideo", " ".join(str(x) for x in (payload.get("sample_video_blocked_dirs") or [])))

    def test_partial_save_settings_preserves_remembered_tmdb_key(self) -> None:
        api = backend.CineSortApi()
        protection_ok = api_mod.protection_available()
        first = api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": True,
                "tmdb_api_key": "abc123tmdb",
                "remember_key": True,
            }
        )
        self.assertTrue(first.get("ok"), first)

        partial = api.settings.save_settings(
            {
                "state_dir": str(self.state_dir),
                "tmdb_enabled": True,
                "probe_backend": "auto",
            }
        )
        self.assertTrue(partial.get("ok"), partial)
        self.assertEqual(bool(partial.get("tmdb_key_persisted")), protection_ok, partial)
        self.assertEqual(
            str(partial.get("tmdb_key_protection") or ""),
            "windows_dpapi_current_user" if protection_ok else "none",
        )

        saved = api.settings.get_settings()
        # SEC-H2 (v7.8.0) : la cle TMDb est MASQUEE dans get_settings (8 bullets •).
        # Avant le fix, elle etait retournee en clair — fuite REST si attaquant LAN.
        mask = "•" * 8
        if protection_ok:
            self.assertEqual(str(saved.get("tmdb_api_key") or ""), mask)
            self.assertTrue(saved.get("_has_tmdb_api_key"), "_has_tmdb_api_key doit etre True")
        else:
            self.assertEqual(str(saved.get("tmdb_api_key") or ""), "")
        self.assertEqual(bool(saved.get("remember_key")), protection_ok)
        self.assertEqual(
            str(saved.get("tmdb_key_protection") or ""),
            "windows_dpapi_current_user" if protection_ok else "none",
        )

    def test_tmdb_key_is_available_after_relaunch_when_remembered(self) -> None:
        protection_ok = api_mod.protection_available()
        first_api = backend.CineSortApi()
        saved = first_api.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": True,
                "tmdb_api_key": "abc123tmdb",
                "remember_key": True,
            }
        )
        self.assertTrue(saved.get("ok"), saved)

        second_api = backend.CineSortApi()
        second_api._state_dir = self.state_dir  # type: ignore[attr-defined]
        loaded = second_api.get_settings()
        # SEC-H2 (v7.8.0) : get_settings() masque les cles maintenant. La cle reste
        # disponible en interne (DPAPI blob), seul le retour REST est masque.
        mask = "•" * 8
        if protection_ok:
            self.assertEqual(str(loaded.get("tmdb_api_key") or ""), mask)
            self.assertTrue(loaded.get("_has_tmdb_api_key"))
        else:
            self.assertEqual(str(loaded.get("tmdb_api_key") or ""), "")
        self.assertEqual(
            str(loaded.get("tmdb_key_protection") or ""),
            "windows_dpapi_current_user" if protection_ok else "none",
        )

        # Recuperer la VRAIE cle via le store interne (pas via get_settings qui masque).
        # En usage reel, l'utilisateur re-saisirait la cle pour la tester ; ici on
        # simule le test automatique au demarrage via le store DPAPI direct.
        from cinesort.ui.api.settings_support import read_settings as _read_settings

        raw_tmdb_key = str(_read_settings(self.state_dir).get("tmdb_api_key") or "")
        if protection_ok:
            self.assertEqual(raw_tmdb_key, "abc123tmdb")  # cle bien dechiffree en interne

        fake_tmdb = mock.Mock()
        fake_tmdb.validate_key.return_value = (True, "TMDb OK")
        with mock.patch.object(api_mod, "TmdbClient", return_value=fake_tmdb):
            result = second_api.test_tmdb_key(raw_tmdb_key, str(self.state_dir), 10.0)

        if protection_ok:
            self.assertTrue(result.get("ok"), result)
            self.assertIn("TMDb OK", str(result.get("message") or ""))
            fake_tmdb.validate_key.assert_called_once()
            fake_tmdb.flush.assert_called_once()
        else:
            self.assertFalse(result.get("ok"), result)
            self.assertIn("vide", str(result.get("message") or "").lower())
            fake_tmdb.validate_key.assert_not_called()

    def test_legacy_plaintext_tmdb_key_is_migrated_on_next_save(self) -> None:
        protection_ok = api_mod.protection_available()
        settings_path = self.state_dir / "settings.json"
        settings_path.write_text(
            json.dumps(
                {
                    "root": str(self.root),
                    "state_dir": str(self.state_dir),
                    "tmdb_enabled": True,
                    "tmdb_api_key": "legacy_tmdb_key",
                    "remember_key": True,
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        api = backend.CineSortApi()
        api._state_dir = self.state_dir  # type: ignore[attr-defined]
        loaded = api.settings.get_settings()
        # SEC-H2 (v7.8.0) : meme la cle legacy plaintext est masquee dans le retour
        # de get_settings (defense en profondeur). La vraie valeur est accessible
        # via read_settings() interne pour la migration.
        mask = "•" * 8
        self.assertEqual(str(loaded.get("tmdb_api_key") or ""), mask)
        self.assertTrue(loaded.get("_has_tmdb_api_key"))
        self.assertEqual(str(loaded.get("tmdb_key_protection") or ""), "plaintext_legacy")

        migrated = api.settings.save_settings(
            {
                "state_dir": str(self.state_dir),
                "tmdb_enabled": True,
                "probe_backend": "auto",
            }
        )
        self.assertTrue(migrated.get("ok"), migrated)
        self.assertEqual(bool(migrated.get("tmdb_key_persisted")), protection_ok, migrated)
        self.assertEqual(
            str(migrated.get("tmdb_key_protection") or ""),
            "windows_dpapi_current_user" if protection_ok else "unavailable",
        )

        raw = self._read_saved_settings_json()
        self.assertNotIn("tmdb_api_key", raw)
        self.assertNotIn("legacy_tmdb_key", json.dumps(raw, ensure_ascii=False))
        self.assertEqual(
            str(((raw.get("tmdb_api_key_secret") or {}).get("scheme")) or ""),
            "windows_dpapi_current_user" if protection_ok else "",
        )

    def test_save_settings_without_root_rejects_when_no_saved_root_exists(self) -> None:
        api = backend.CineSortApi()
        result = api.settings.save_settings({"state_dir": str(self.state_dir), "tmdb_enabled": False})
        self.assertFalse(result.get("ok"), result)
        self.assertIn("ROOT", str(result.get("message") or ""))

    def test_start_plan_without_root_uses_saved_root(self) -> None:
        self._create_file(self.root / "Saved.Root.2014.1080p" / "Saved.Root.2014.1080p.mkv")
        api = backend.CineSortApi()
        saved = api.settings.save_settings({"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False})
        self.assertTrue(saved.get("ok"), saved)

        start = api.run.start_plan(
            {"state_dir": str(self.state_dir), "tmdb_enabled": False, "collection_folder_enabled": True}
        )
        self.assertTrue(start.get("ok"), start)
        self._wait_terminal(api, start["run_id"])

    def test_start_plan_without_root_rejects_when_no_saved_root_exists(self) -> None:
        api = backend.CineSortApi()
        result = api.run.start_plan({"state_dir": str(self.state_dir), "tmdb_enabled": False})
        self.assertFalse(result.get("ok"), result)
        self.assertIn("ROOT", str(result.get("message") or ""))

    def test_save_settings_with_explicit_state_dir_does_not_leak_root_from_other_context(self) -> None:
        api = backend.CineSortApi()
        other_state = self.state_dir / "other_ctx"
        target_state = self.state_dir / "target_ctx"
        other_state.mkdir(parents=True, exist_ok=True)
        target_state.mkdir(parents=True, exist_ok=True)
        self.assertTrue(
            api.settings.save_settings({"root": str(self.root), "state_dir": str(other_state), "tmdb_enabled": False}).get("ok")
        )
        api._state_dir = other_state  # type: ignore[attr-defined]

        result = api.settings.save_settings({"state_dir": str(target_state), "tmdb_enabled": False})
        self.assertFalse(result.get("ok"), result)
        self.assertIn("ROOT", str(result.get("message") or ""))

    def test_start_plan_with_explicit_state_dir_does_not_leak_root_from_other_context(self) -> None:
        api = backend.CineSortApi()
        other_state = self.state_dir / "other_ctx_start"
        target_state = self.state_dir / "target_ctx_start"
        other_state.mkdir(parents=True, exist_ok=True)
        target_state.mkdir(parents=True, exist_ok=True)
        self.assertTrue(
            api.settings.save_settings({"root": str(self.root), "state_dir": str(other_state), "tmdb_enabled": False}).get("ok")
        )
        api._state_dir = other_state  # type: ignore[attr-defined]

        result = api.run.start_plan({"state_dir": str(target_state), "tmdb_enabled": False})
        self.assertFalse(result.get("ok"), result)
        self.assertIn("ROOT", str(result.get("message") or ""))

    def test_to_bool_parses_string_values(self) -> None:
        self.assertFalse(api_mod._to_bool("false", True))
        self.assertFalse(api_mod._to_bool("0", True))
        self.assertFalse(api_mod._to_bool("off", True))
        self.assertTrue(api_mod._to_bool("true", False))
        self.assertTrue(api_mod._to_bool("1", False))

    def test_run_id_validation_rejects_invalid_ids(self) -> None:
        api = backend.CineSortApi()
        bad_ids = ["", "../evil", "abc/def", "run id", "x", "tri:123"]
        for bad in bad_ids:
            st = api.run.get_status(bad, 0)
            self.assertFalse(st.get("ok"), (bad, st))
            self.assertIn("run_id invalide", str(st.get("message", "")))

            plan = api.run.get_plan(bad)
            self.assertFalse(plan.get("ok"), (bad, plan))
            self.assertIn("run_id invalide", str(plan.get("message", "")))

            app = api.apply(bad, {}, True, False)
            self.assertFalse(app.get("ok"), (bad, app))
            self.assertIn("run_id invalide", str(app.get("message", "")))

    def test_get_probe_tools_status_shape(self) -> None:
        api = backend.CineSortApi()
        api._state_dir = self.state_dir / "probe_tools_status"  # type: ignore[attr-defined]
        api._state_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[attr-defined]
        settings_path = api._state_dir / "settings.json"  # type: ignore[attr-defined]
        settings_path.write_text(
            json.dumps(
                {
                    "root": r"D:\Films",
                    "state_dir": str(api._state_dir),  # type: ignore[attr-defined]
                    "probe_backend": "auto",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        out = api.get_probe_tools_status()
        self.assertTrue(out.get("ok"), out)
        self.assertIn("tools", out)
        self.assertIn("hybrid_ready", out)
        self.assertIn("degraded_mode", out)

    def test_set_probe_tool_paths_rejects_invalid_paths(self) -> None:
        api = backend.CineSortApi()
        api._state_dir = self.state_dir / "probe_tools_paths"  # type: ignore[attr-defined]
        api._state_dir.mkdir(parents=True, exist_ok=True)  # type: ignore[attr-defined]
        settings_path = api._state_dir / "settings.json"  # type: ignore[attr-defined]
        settings_path.write_text(
            json.dumps(
                {
                    "root": r"D:\Films",
                    "state_dir": str(api._state_dir),  # type: ignore[attr-defined]
                    "probe_backend": "auto",
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        out = api.set_probe_tool_paths(
            {
                "ffprobe_path": str(Path(self._tmp) / "missing_ffprobe.exe"),
                "mediainfo_path": "",
                "probe_backend": "auto",
            }
        )
        self.assertFalse(out.get("ok"), out)
        self.assertIn("ffprobe", str(out.get("message", "")).lower())


class ValidateDroppedPathTests(unittest.TestCase):
    """Tests pour validate_dropped_path."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp(prefix="cinesort_drop_")
        self.api = api_mod.CineSortApi()
        self.api._state_dir = Path(self.tmp) / "state"
        self.api._state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_valid_directory(self):
        d = Path(self.tmp) / "films"
        d.mkdir()
        r = self.api.validate_dropped_path(str(d))
        self.assertTrue(r["ok"])
        self.assertIn("path", r)

    def test_nonexistent_path(self):
        r = self.api.validate_dropped_path(str(Path(self.tmp) / "nope"))
        self.assertFalse(r["ok"])
        self.assertIn("introuvable", r["message"])

    def test_file_not_directory(self):
        f = Path(self.tmp) / "file.txt"
        f.write_text("hi")
        r = self.api.validate_dropped_path(str(f))
        self.assertFalse(r["ok"])
        self.assertIn("dossier", r["message"])

    def test_empty_path(self):
        r = self.api.validate_dropped_path("")
        self.assertFalse(r["ok"])


if __name__ == "__main__":
    unittest.main(verbosity=2)

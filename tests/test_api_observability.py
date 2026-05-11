from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api import cinesort_api as api_mod


class ApiObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_observability_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.api = backend.CineSortApi()
        saved = self.api.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
                "probe_backend": "auto",
            }
        )
        self.assertTrue(saved.get("ok"), saved)
        self.store, _runner = self.api._get_or_create_infra(self.state_dir)  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _write_plan_rows(self, run_id: str, rows: list[dict]) -> None:
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        run_dir.mkdir(parents=True, exist_ok=True)
        plan = run_dir / "plan.jsonl"
        payload = "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"
        plan.write_text(payload, encoding="utf-8")

    def _insert_run_done(self, run_id: str, *, started_ts: float, stats: dict) -> None:
        self.store.insert_run_pending(
            run_id=run_id,
            root=str(self.root),
            state_dir=str(self.state_dir),
            config={"tmdb_enabled": False},
            created_ts=started_ts - 2.0,
        )
        self.store.mark_run_running(run_id, started_ts=started_ts)
        self.store.mark_run_done(run_id, stats=stats, ended_ts=started_ts + 10.0)

    def test_get_dashboard_logs_structured_error_and_returns_clean_message(self) -> None:
        run_id = "20260309_120000_001"
        started = time.time() - 30.0
        self._insert_run_done(run_id, started_ts=started, stats={"planned_rows": 1})
        self._write_plan_rows(
            run_id,
            [
                {
                    "row_id": "row_1",
                    "kind": "single",
                    "folder": str(self.root / "Film A"),
                    "video": str(self.root / "Film A" / "Film.A.mkv"),
                    "proposed_title": "Film A",
                    "proposed_year": 2010,
                    "proposed_source": "name",
                    "confidence": 72,
                    "confidence_label": "med",
                    "candidates": [],
                    "notes": "",
                    "collection_name": None,
                }
            ],
        )

        with mock.patch.object(self.store, "list_quality_reports", side_effect=OSError("dashboard boom")):
            out = self.api.get_dashboard(run_id)

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(str(out.get("message") or ""), "Impossible de charger la synthese du run.")
        self.assertNotIn("dashboard boom", str(out.get("message") or ""))

        errs = self.store.list_errors(run_id)
        self.assertTrue(errs, errs)
        last = errs[-1]
        self.assertEqual(str(last.get("step") or ""), "get_dashboard")
        ctx = json.loads(str(last.get("context_json") or "{}"))
        self.assertEqual(str(ctx.get("endpoint") or ""), "get_dashboard")
        self.assertEqual(str(ctx.get("run_id") or ""), run_id)

    def test_install_probe_tools_logs_structured_error_and_returns_clean_message(self) -> None:
        with self.assertLogs(api_mod.logger, level="ERROR") as logs:
            with mock.patch.object(api_mod, "manage_probe_tools", side_effect=OSError("winget boom")):
                out = self.api.install_probe_tools({"scope": "user", "tools": ["ffprobe"]})

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(str(out.get("message") or ""), "Impossible d'installer les outils probe.")
        self.assertNotIn("winget boom", str(out.get("message") or ""))
        self.assertTrue(any("API_EXCEPTION endpoint=install_probe_tools" in line for line in logs.output), logs.output)

    def test_set_probe_tool_paths_logs_structured_error_and_returns_clean_message(self) -> None:
        with self.assertLogs(api_mod.logger, level="ERROR") as logs:
            with mock.patch.object(self.api, "recheck_probe_tools", side_effect=OSError("paths boom")):
                out = self.api.set_probe_tool_paths(
                    {
                        "ffprobe_path": "",
                        "mediainfo_path": "",
                        "probe_backend": "auto",
                    }
                )

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(
            str(out.get("message") or ""),
            "Impossible d'enregistrer les chemins des outils probe.",
        )
        self.assertNotIn("paths boom", str(out.get("message") or ""))
        self.assertTrue(any("API_EXCEPTION endpoint=set_probe_tool_paths" in line for line in logs.output), logs.output)

    def test_analyze_quality_batch_logs_structured_error_and_returns_clean_message(self) -> None:
        run_id = "20260309_120000_010"
        with self.assertLogs(api_mod.logger, level="ERROR") as logs:
            with mock.patch.object(self.api, "get_quality_report", side_effect=OSError("quality batch boom")):
                out = self.api.analyze_quality_batch(run_id, ["row_1"], {"reuse_existing": False})

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(str(out.get("message") or ""), "Impossible de terminer l'analyse qualite.")
        self.assertNotIn("quality batch boom", str(out.get("message") or ""))
        self.assertTrue(
            any("API_EXCEPTION endpoint=analyze_quality_batch" in line for line in logs.output), logs.output
        )

    def test_apply_logs_structured_error_and_returns_clean_message_when_context_load_fails(self) -> None:
        run_id = "20260309_120000_011"
        with self.assertLogs(api_mod.logger, level="ERROR") as logs:
            with mock.patch.object(self.api, "_run_context_for_apply", side_effect=OSError("apply context boom")):
                out = self.api.apply(run_id, {}, False, False)

        self.assertFalse(out.get("ok"), out)
        self.assertEqual(str(out.get("message") or ""), "Impossible d'appliquer les changements.")
        self.assertNotIn("apply context boom", str(out.get("message") or ""))
        self.assertTrue(any("API_EXCEPTION endpoint=apply" in line for line in logs.output), logs.output)


if __name__ == "__main__":
    unittest.main(verbosity=2)

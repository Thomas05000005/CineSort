"""LOTC-B1 : _resolve_run_id doit resoudre le dernier run UTILISABLE.

Le bulk "Re-scanner" (rescan_rows_bulk -> JobRunner.start_job) insere un run
de tracking SANS plan propre (config {"rescan_run_id": ..., "rescan_row_ids":
[...]}). Avant le fix, _resolve_run_id (list_runs limit=1) resolvait ce run
parasite -> get_library_filtered retournait 0 film pour toute la session.

Tests sur base SQLite REELLE (pas de mock DB, convention projet).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any

from cinesort.infra import state
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import library_support


class _FakeSettingsFacade:
    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    def get_settings(self) -> dict:
        return {"state_dir": str(self._state_dir)}


class _FakeApi:
    """Api minimale : juste ce que _resolve_run_id consomme."""

    def __init__(self, state_dir: Path, store: SQLiteStore) -> None:
        self.settings = _FakeSettingsFacade(state_dir)
        self._store = store

    def _get_or_create_infra(self, state_dir: Any):
        return self._store, None


class ResolveRunIdLotcB1Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_resolve_run_"))
        self.state_dir = self._tmp / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.store = SQLiteStore(self.state_dir / "cinesort.sqlite")
        self.store.initialize()
        self.api = _FakeApi(self.state_dir, self.store)

    def tearDown(self) -> None:
        try:
            self.store.close()
        except (OSError, AttributeError):
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- helpers -----------------------------------------------------------

    def _insert_scan_run_with_plan(self, run_id: str, *, created_ts: float) -> None:
        """Run de scan reel : config nominale + plan.jsonl ecrit sur disque."""
        self.store.run.insert_run_pending(
            run_id=run_id,
            root="D:/Films",
            state_dir=str(self.state_dir),
            config={"library_path": "D:/Films"},
            created_ts=created_ts,
        )
        self.store.run.mark_run_running(run_id, started_ts=created_ts)
        self.store.run.mark_run_done(run_id, stats={"planned_rows": 1}, ended_ts=created_ts + 10.0)
        paths = state.new_run(self.state_dir, run_id)
        paths.plan_jsonl.write_text(
            json.dumps({"row_id": "row-1", "title": "Film Test", "year": 2020}) + "\n",
            encoding="utf-8",
        )

    def _insert_rescan_parasite_run(
        self, run_id: str, *, target_run_id: str, created_ts: float, done: bool = True
    ) -> None:
        """Run parasite : exactement le config pose par rescan_rows_bulk."""
        self.store.run.insert_run_pending(
            run_id=run_id,
            root=str(self.state_dir),
            state_dir=str(self.state_dir),
            config={"rescan_run_id": target_run_id, "rescan_row_ids": ["row-1"]},
            created_ts=created_ts,
        )
        self.store.run.mark_run_running(run_id, started_ts=created_ts)
        if done:
            self.store.run.mark_run_done(
                run_id,
                stats={"ok": True, "rescan": {"run_id": target_run_id}},
                ended_ts=created_ts + 5.0,
            )

    # -- gate LOTC-B1 ------------------------------------------------------

    def test_parasite_rescan_run_is_skipped_latest_plan_run_wins(self) -> None:
        """GATE LOTC-B1 : run avec plan + run parasite plus recent -> le run plan."""
        self._insert_scan_run_with_plan("run-scan-1", created_ts=1000.0)
        self._insert_rescan_parasite_run("run-parasite-1", target_run_id="run-scan-1", created_ts=2000.0)
        # Pre-condition : le parasite EST bien le dernier run tout court
        # (c'etait exactement la resolution buggee list_runs(limit=1)).
        latest = self.store.run.list_runs(limit=1)
        self.assertEqual(latest[0]["run_id"], "run-parasite-1")

        resolved = library_support._resolve_run_id(self.api, None)
        self.assertEqual(resolved, "run-scan-1")

    def test_multiple_parasites_stacked_still_resolve_scan_run(self) -> None:
        self._insert_scan_run_with_plan("run-scan-1", created_ts=1000.0)
        for i in range(3):
            self._insert_rescan_parasite_run(
                f"run-parasite-{i}",
                target_run_id="run-scan-1",
                created_ts=2000.0 + i * 100,
            )
        resolved = library_support._resolve_run_id(self.api, None)
        self.assertEqual(resolved, "run-scan-1")

    def test_parasite_still_running_is_skipped_too(self) -> None:
        """Le skip repose sur le marqueur config, pas sur le statut du run."""
        self._insert_scan_run_with_plan("run-scan-1", created_ts=1000.0)
        self._insert_rescan_parasite_run(
            "run-parasite-1",
            target_run_id="run-scan-1",
            created_ts=2000.0,
            done=False,  # statut RUNNING
        )
        resolved = library_support._resolve_run_id(self.api, None)
        self.assertEqual(resolved, "run-scan-1")

    def test_parasite_only_window_falls_back_to_its_target(self) -> None:
        """Base ne contenant QUE le parasite : on retombe sur le run cible."""
        self._insert_rescan_parasite_run("run-parasite-1", target_run_id="run-scan-old", created_ts=2000.0)
        resolved = library_support._resolve_run_id(self.api, None)
        self.assertEqual(resolved, "run-scan-old")

    # -- non-regression des autres consommateurs ---------------------------

    def test_explicit_run_id_passthrough(self) -> None:
        self.assertEqual(library_support._resolve_run_id(self.api, "run-explicit"), "run-explicit")

    def test_no_runs_returns_none(self) -> None:
        self.assertIsNone(library_support._resolve_run_id(self.api, None))

    def test_normal_latest_run_still_resolved(self) -> None:
        """Sans parasite, comportement historique inchange : dernier run."""
        self._insert_scan_run_with_plan("run-scan-1", created_ts=1000.0)
        self._insert_scan_run_with_plan("run-scan-2", created_ts=2000.0)
        resolved = library_support._resolve_run_id(self.api, None)
        self.assertEqual(resolved, "run-scan-2")

    def test_run_dict_without_config_json_is_usable(self) -> None:
        """Compat mocks : un run sans config_json n'est pas un parasite."""
        self.assertIsNone(library_support._rescan_target_run_id({"run_id": "r1"}))

    def test_rescan_target_extraction(self) -> None:
        self.assertEqual(
            library_support._rescan_target_run_id(
                {
                    "run_id": "rB",
                    "config_json": json.dumps({"rescan_run_id": "rA", "rescan_row_ids": ["x"]}),
                }
            ),
            "rA",
        )
        # Config JSON corrompu contenant le marqueur : pas de crash, pas de cible.
        self.assertIsNone(library_support._rescan_target_run_id({"run_id": "rB", "config_json": '{"rescan_run_id": '}))
        # Config nominale de scan : pas une cible rescan.
        self.assertIsNone(
            library_support._rescan_target_run_id({"run_id": "rA", "config_json": json.dumps({"library_path": "D:/F"})})
        )


if __name__ == "__main__":
    unittest.main()

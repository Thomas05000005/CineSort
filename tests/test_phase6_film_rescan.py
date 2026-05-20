"""Phase 6 spec 06 §3.6 — Tests de la vraie impl de `rescan_row` (1 row synchrone).

Couvre :
- rescan_row delegue a run_flow_support.rescan_row (probe + perceptual)
- rescan_row tente un re-match TMDb via replan_single_row
- rescan_row met a jour plan.jsonl avec nouvelle row (score/confidence/candidates)
- rescan_row best-effort si TMDb indispo (pas de cle, pas de net) -> tmdb_rematched=False
- rescan_row gere les erreurs de validation (row_id vide, run_id introuvable)
"""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.infra import state


def _make_run_paths(tmp_path: Path, run_id: str = "r1") -> state.RunPaths:
    run_dir = tmp_path / "runs" / f"tri_films_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return state.RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def _write_plan_jsonl(plan_jsonl: Path, rows: list) -> None:
    with open(plan_jsonl, "w", encoding="utf-8") as fp:
        for row in rows:
            fp.write(json.dumps(row, ensure_ascii=False) + "\n")


def _make_mock_api(tmp_path: Path, run_id: str = "r1"):
    api = MagicMock()
    api.settings.get_settings.return_value = {"state_dir": str(tmp_path)}
    paths = _make_run_paths(tmp_path, run_id)
    api._run_paths_for.return_value = paths

    store = MagicMock()
    store.run.list_runs.return_value = [{"run_id": run_id}]
    api._get_or_create_infra.return_value = (store, MagicMock())
    api._state_dir = tmp_path

    api.run.get_plan.return_value = {
        "ok": True,
        "rows": [
            {
                "row_id": "f1",
                "folder": "C:/movies/La Doublure (2006)",
                "video": "La.Doublure.2006.mkv",
                "kind": "single",
                "proposed_title": "La Doublure",
                "proposed_year": 2006,
                "confidence": 90,
                "candidates": [{"tmdb_id": 12345, "title": "La Doublure", "year": 2006}],
                "warning_flags": [],
            }
        ],
    }
    return api, store, paths


class RescanRowFullPipelineTests(unittest.TestCase):
    """Verifie que rescan_row execute bien les 4 etapes du pipeline."""

    def test_rescan_row_delegates_to_run_flow_support(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api, _store, _paths = _make_mock_api(Path(tmp))
            with patch(
                "cinesort.ui.api.run_flow_support.rescan_row",
                return_value={
                    "ok": True,
                    "run_id": "r1",
                    "row_id": "f1",
                    "plan_row": {"row_id": "f1", "proposed_title": "La Doublure"},
                    "quality": {"score": 75, "tier": "silver"},
                    "perceptual": {"global_score_v2": 72.0, "global_tier_v2": "silver"},
                },
            ) as mock_run_flow:
                res = library_actions_support.rescan_row(api, "f1", run_id="r1")

        self.assertTrue(res["ok"])
        mock_run_flow.assert_called_once_with(api, "r1", "f1")
        self.assertEqual(res["quality"]["score"], 75)
        self.assertEqual(res["perceptual"]["global_score_v2"], 72.0)

    def test_rescan_row_empty_id_returns_error(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api, _, _ = _make_mock_api(Path(tmp))
            res = library_actions_support.rescan_row(api, "")
        self.assertFalse(res["ok"])

    def test_rescan_row_no_active_run_returns_error(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = MagicMock()
            api.settings.get_settings.return_value = {"state_dir": tmp}
            store = MagicMock()
            store.run.list_runs.return_value = []
            api._get_or_create_infra.return_value = (store, MagicMock())
            res = library_actions_support.rescan_row(api, "f1")
        self.assertFalse(res["ok"])

    def test_rescan_row_propagates_run_flow_failure(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api, _, _ = _make_mock_api(Path(tmp))
            with patch(
                "cinesort.ui.api.run_flow_support.rescan_row",
                return_value={"ok": False, "error": "row introuvable"},
            ):
                res = library_actions_support.rescan_row(api, "f1", run_id="r1")
        self.assertFalse(res["ok"])


class RescanRowTmdbRematchTests(unittest.TestCase):
    """Verifie le re-match TMDb et la mise a jour du plan.jsonl."""

    def test_rescan_row_no_video_skips_rematch_gracefully(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api, _, paths = _make_mock_api(Path(tmp))
            _write_plan_jsonl(
                paths.plan_jsonl,
                [
                    {
                        "row_id": "f1",
                        "folder": str(Path(tmp) / "movies"),
                        "video": "nonexistent.mkv",
                        "kind": "single",
                        "candidates": [],
                        "warning_flags": [],
                    }
                ],
            )
            with patch(
                "cinesort.ui.api.run_flow_support.rescan_row",
                return_value={
                    "ok": True,
                    "run_id": "r1",
                    "row_id": "f1",
                    "plan_row": {"row_id": "f1"},
                    "quality": {},
                    "perceptual": {},
                },
            ):
                res = library_actions_support.rescan_row(api, "f1", run_id="r1")
        self.assertTrue(res["ok"])
        self.assertFalse(res.get("tmdb_rematched"))
        self.assertEqual(res.get("candidates_count"), 0)

    def test_rescan_row_with_video_calls_replan_and_updates_plan(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            api, _, paths = _make_mock_api(tmp_path)
            video_folder = tmp_path / "movies" / "La Doublure (2006)"
            video_folder.mkdir(parents=True, exist_ok=True)
            video_file = video_folder / "La.Doublure.2006.mkv"
            video_file.write_bytes(b"\x00" * 1024)

            _write_plan_jsonl(
                paths.plan_jsonl,
                [
                    {
                        "row_id": "f1",
                        "folder": str(video_folder),
                        "video": "La.Doublure.2006.mkv",
                        "kind": "single",
                        "proposed_title": "La Doublure",
                        "proposed_year": 2006,
                        "confidence": 50,
                        "candidates": [],
                        "warning_flags": ["root_level_source"],
                    },
                    {
                        "row_id": "f2",
                        "folder": str(tmp_path / "other"),
                        "video": "other.mkv",
                        "kind": "single",
                        "candidates": [],
                    },
                ],
            )
            api.settings.get_settings.return_value = {
                "state_dir": tmp,
                "tmdb_api_key": "fake_key",
            }

            new_row_mock = MagicMock()
            new_row_mock.candidates = []
            with patch(
                "cinesort.ui.api.run_flow_support.rescan_row",
                return_value={
                    "ok": True,
                    "run_id": "r1",
                    "row_id": "f1",
                    "plan_row": {"row_id": "f1"},
                    "quality": {},
                    "perceptual": {},
                },
            ), patch(
                "cinesort.app.plan_support.replan_single_row",
                return_value=new_row_mock,
            ) as mock_replan, patch(
                "cinesort.app.plan_support.plan_row_to_jsonable",
                return_value={
                    "row_id": "F1_NEW",
                    "proposed_title": "La Doublure",
                    "proposed_year": 2006,
                    "confidence": 90,
                    "candidates": [{"tmdb_id": 12345, "title": "La Doublure"}],
                    "warning_flags": [],
                },
            ):
                res = library_actions_support.rescan_row(api, "f1", run_id="r1")

        self.assertTrue(res["ok"])
        self.assertTrue(res["tmdb_rematched"])
        self.assertEqual(res["candidates_count"], 1)
        mock_replan.assert_called_once()
        updated = [
            json.loads(line)
            for line in paths.plan_jsonl.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        self.assertEqual(len(updated), 2)
        self.assertEqual(updated[0]["row_id"], "f1")  # row_id stable
        self.assertEqual(updated[0]["confidence"], 90)
        self.assertEqual(len(updated[0]["candidates"]), 1)
        self.assertEqual(updated[1]["row_id"], "f2")

    def test_rescan_row_tmdb_failure_keeps_base_result(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            api, _, paths = _make_mock_api(tmp_path)
            video_folder = tmp_path / "movies"
            video_folder.mkdir(parents=True, exist_ok=True)
            (video_folder / "x.mkv").write_bytes(b"\x00")
            _write_plan_jsonl(
                paths.plan_jsonl,
                [{"row_id": "f1", "folder": str(video_folder), "video": "x.mkv", "kind": "single"}],
            )
            api.settings.get_settings.return_value = {"state_dir": tmp, "tmdb_api_key": "k"}

            with patch(
                "cinesort.ui.api.run_flow_support.rescan_row",
                return_value={
                    "ok": True,
                    "run_id": "r1",
                    "row_id": "f1",
                    "plan_row": {"row_id": "f1"},
                    "quality": {},
                    "perceptual": {},
                },
            ), patch(
                "cinesort.app.plan_support.replan_single_row",
                side_effect=ValueError("boom"),
            ):
                res = library_actions_support.rescan_row(api, "f1", run_id="r1")
        self.assertTrue(res["ok"])
        self.assertFalse(res["tmdb_rematched"])


class ReplanSingleRowHelperTests(unittest.TestCase):
    """plan_support.replan_single_row est expose et utilisable."""

    def test_replan_single_row_is_exported(self) -> None:
        from cinesort.app import plan_support

        self.assertTrue(hasattr(plan_support, "replan_single_row"))
        self.assertTrue(callable(plan_support.replan_single_row))


if __name__ == "__main__":
    unittest.main()

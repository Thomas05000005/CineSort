"""Tests Phase 4 spec 07 — Bibliotheque backend endpoints.

Couvre les 4 nouveaux endpoints :
- library/get_library_counters_by_chip(filters)
- library/mark_for_deletion_bulk(row_ids)
- run/rescan_rows_bulk(row_ids)
- library/export_films(row_ids, format)
"""

from __future__ import annotations

import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.infra import state


def _make_mock_api_with_rows(tmp_path: Path) -> MagicMock:
    """Mock API avec 5 films varies (couvre tiers, subs, sagas, doublons, source)."""
    api = MagicMock()
    rows = [
        # Inception : platinum, subs FR ok, identifie, pas de saga
        {
            "row_id": "f1",
            "proposed_title": "Inception",
            "proposed_year": 2010,
            "mtime": 1700000000,
            "source_path": "C:/movies/Inception (2010).mkv",
            "subtitle_languages": ["fr", "en"],
            "subtitle_missing_langs": [],
            "proposed_source": "tmdb",
            "confidence": 95,
            "tmdb_collection_name": None,
            "edition": None,
            "size_bytes": 18_000_000_000,
        },
        # La Doublure : bronze, manque subs FR, identifie
        {
            "row_id": "f2",
            "proposed_title": "La Doublure",
            "proposed_year": 2006,
            "mtime": 1700000000,
            "source_path": "C:/movies/La Doublure (2006).mkv",
            "subtitle_languages": ["en"],
            "subtitle_missing_langs": ["fr"],
            "proposed_source": "tmdb",
            "confidence": 90,
            "tmdb_collection_name": None,
            "edition": None,
            "size_bytes": 4_200_000_000,
        },
        # Avatar : silver, manque subs FR, identifie, dans saga
        {
            "row_id": "f3",
            "proposed_title": "Avatar",
            "proposed_year": 2009,
            "mtime": 1700000000,
            "source_path": "C:/movies/Avatar (2009).mkv",
            "subtitle_languages": [],
            "subtitle_missing_langs": ["fr"],
            "proposed_source": "tmdb",
            "confidence": 80,
            "tmdb_collection_name": "Avatar Collection",
            "edition": None,
            "size_bytes": 12_100_000_000,
        },
        # Dune : gold, manque subs FR, identifie, dans saga
        {
            "row_id": "f4",
            "proposed_title": "Dune",
            "proposed_year": 2021,
            "mtime": 1700000000,
            "source_path": "C:/movies/Dune (2021).mkv",
            "subtitle_languages": ["en"],
            "subtitle_missing_langs": ["fr"],
            "proposed_source": "tmdb",
            "confidence": 91,
            "tmdb_collection_name": "Dune Collection",
            "edition": None,
            "size_bytes": 15_500_000_000,
        },
        # Film inconnu : reject, non identifie
        {
            "row_id": "f5",
            "proposed_title": "Unknown Title",
            "proposed_year": 0,
            "mtime": 1700000000,
            "source_path": "C:/movies/junk.mkv",
            "subtitle_languages": [],
            "subtitle_missing_langs": ["fr"],
            "proposed_source": "unknown",
            "confidence": 0,
            "tmdb_collection_name": None,
            "edition": None,
            "size_bytes": 800_000_000,
        },
    ]
    api.run.get_plan.return_value = {"ok": True, "rows": rows}
    api.settings.get_settings.return_value = {"state_dir": str(tmp_path)}

    store = MagicMock()
    store.perceptual.list_perceptual_reports.return_value = [
        {
            "row_id": "f1",
            "global_tier_v2": "platinum",
            "global_score_v2": 92,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
        {
            "row_id": "f2",
            "global_tier_v2": "bronze",
            "global_score_v2": 58,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
        {
            "row_id": "f3",
            "global_tier_v2": "silver",
            "global_score_v2": 72,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
        {
            "row_id": "f4",
            "global_tier_v2": "gold",
            "global_score_v2": 85,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
        {
            "row_id": "f5",
            "global_tier_v2": "reject",
            "global_score_v2": 30,
            "global_score_v2_payload": {"warnings": [], "adjustments_applied": []},
        },
    ]
    store.quality.list_quality_reports.return_value = [
        {
            "row_id": "f1",
            "metrics": {
                "video": {"codec": "hevc", "width": 3840, "height": 2160},
                "audio": [{"language": "fr"}, {"language": "en"}],
                "duration_s": 8800,
            },
        },
        {
            "row_id": "f2",
            "metrics": {
                "video": {"codec": "h264", "width": 1920, "height": 1080},
                "audio": [{"language": "en"}],
                "duration_s": 6300,
            },
        },
        {
            "row_id": "f3",
            "metrics": {
                "video": {"codec": "h264", "width": 1920, "height": 1080},
                "audio": [{"language": "en"}],
                "duration_s": 9700,
            },
        },
        {
            "row_id": "f4",
            "metrics": {
                "video": {"codec": "hevc", "width": 3840, "height": 2160},
                "audio": [{"language": "en"}],
                "duration_s": 9300,
            },
        },
        {
            "row_id": "f5",
            "metrics": {
                "video": {"codec": "h264", "width": 1280, "height": 720},
                "audio": [],
                "duration_s": 5400,
            },
        },
    ]
    store.run.list_runs.return_value = [{"run_id": "r1"}]
    runner = MagicMock()
    runner.start_job.return_value = "job_xyz"
    api._get_or_create_infra.return_value = (store, runner)

    # _run_paths_for utilise par mark_for_deletion : on cree un run_dir reel.
    run_dir = tmp_path / "runs" / "tri_films_r1"
    run_dir.mkdir(parents=True, exist_ok=True)
    paths = state.RunPaths(
        run_id="r1",
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )
    api._run_paths_for.return_value = paths
    return api


# ---------------------------------------------------------------------------
# 1. get_library_counters_by_chip
# ---------------------------------------------------------------------------


class GetLibraryCountersByChipTests(unittest.TestCase):
    def test_returns_all_11_counters(self) -> None:
        from cinesort.ui.api import library_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_support.get_library_counters_by_chip(api, run_id="r1")
            self.assertTrue(res["ok"])
            counts = res["counts"]
            # 11 chips attendus
            expected_keys = {
                "platinum",
                "gold",
                "silver",
                "bronze",
                "reject",
                "unknown",
                "subs_missing_fr",
                "unidentified",
                "recently_modified",
                "in_duplicates",
                "sagas_incomplete",
            }
            self.assertEqual(set(counts.keys()), expected_keys)
            self.assertEqual(len(counts), 11)

    def test_tier_counts_correct(self) -> None:
        from cinesort.ui.api import library_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_support.get_library_counters_by_chip(api, run_id="r1")
            counts = res["counts"]
            self.assertEqual(counts["platinum"], 1)  # Inception
            self.assertEqual(counts["gold"], 1)  # Dune
            self.assertEqual(counts["silver"], 1)  # Avatar
            self.assertEqual(counts["bronze"], 1)  # La Doublure
            self.assertEqual(counts["reject"], 1)  # Unknown

    def test_subs_missing_fr_counted(self) -> None:
        from cinesort.ui.api import library_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_support.get_library_counters_by_chip(api, run_id="r1")
            counts = res["counts"]
            # Inception a "fr" + "en" → ok ; les 4 autres manquent fr
            self.assertEqual(counts["subs_missing_fr"], 4)

    def test_unidentified_counted(self) -> None:
        from cinesort.ui.api import library_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_support.get_library_counters_by_chip(api, run_id="r1")
            counts = res["counts"]
            self.assertEqual(counts["unidentified"], 1)  # f5

    def test_sagas_counted(self) -> None:
        from cinesort.ui.api import library_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_support.get_library_counters_by_chip(api, run_id="r1")
            counts = res["counts"]
            # f3 (Avatar Collection) + f4 (Dune Collection)
            self.assertEqual(counts["sagas_incomplete"], 2)

    def test_filters_applied_before_counting(self) -> None:
        from cinesort.ui.api import library_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            # Filter on tier=bronze : should only count La Doublure (1 row)
            res = library_support.get_library_counters_by_chip(
                api,
                filters={"tier_v2": ["bronze"]},
                run_id="r1",
            )
            self.assertEqual(res["total"], 1)
            self.assertEqual(res["counts"]["bronze"], 1)
            self.assertEqual(res["counts"]["platinum"], 0)

    def test_no_run_returns_zero_counts(self) -> None:
        from cinesort.ui.api import library_support

        api = MagicMock()
        api.settings.get_settings.return_value = {"state_dir": None}
        api._get_or_create_infra.return_value = (MagicMock(), None)
        api._get_or_create_infra.return_value[0].run.list_runs.return_value = []
        res = library_support.get_library_counters_by_chip(api, run_id=None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["total"], 0)
        self.assertEqual(len(res["counts"]), 11)


# ---------------------------------------------------------------------------
# 2. mark_for_deletion / mark_for_deletion_bulk
# ---------------------------------------------------------------------------


class MarkForDeletionBulkTests(unittest.TestCase):
    def test_bulk_marks_multiple_rows(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.mark_for_deletion_bulk(
                api,
                ["f1", "f2", "f3"],
                run_id="r1",
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["count"], 3)
            self.assertEqual(res["failed"], [])
            # Fichier deletion_marks.json existe et contient les row_ids
            path = Path(tmp) / "runs" / "tri_films_r1" / "deletion_marks.json"
            self.assertTrue(path.exists())
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(sorted(data["row_ids"]), ["f1", "f2", "f3"])

    def test_bulk_idempotent_same_rows(self) -> None:
        """Marquer 2x les memes rows ne les recompte pas (count=0 au 2e appel)."""
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            r1 = library_actions_support.mark_for_deletion_bulk(api, ["f1"], run_id="r1")
            self.assertEqual(r1["count"], 1)
            r2 = library_actions_support.mark_for_deletion_bulk(api, ["f1"], run_id="r1")
            self.assertTrue(r2["ok"])
            self.assertEqual(r2["count"], 0)  # deja marque

    def test_bulk_empty_row_ids_ok(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.mark_for_deletion_bulk(api, [], run_id="r1")
            self.assertTrue(res["ok"])
            self.assertEqual(res["count"], 0)

    def test_bulk_invalid_row_ids_listed_in_failed(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.mark_for_deletion_bulk(
                api,
                ["f1", "", "   "],
                run_id="r1",
            )
            self.assertTrue(res["ok"])
            self.assertEqual(res["count"], 1)
            self.assertEqual(len(res["failed"]), 2)

    def test_bulk_invalid_param_returns_error(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.mark_for_deletion_bulk(
                api,
                "not_a_list",
                run_id="r1",  # type: ignore[arg-type]
            )
            self.assertFalse(res["ok"])

    def test_single_mark_for_deletion(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.mark_for_deletion(api, "f1", run_id="r1")
            self.assertTrue(res["ok"])
            self.assertEqual(res["row_id"], "f1")

    def test_single_mark_requires_row_id(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.mark_for_deletion(api, "", run_id="r1")
            self.assertFalse(res["ok"])


# ---------------------------------------------------------------------------
# 3. rescan_rows_bulk
# ---------------------------------------------------------------------------


class RescanRowsBulkTests(unittest.TestCase):
    def test_bulk_launches_job(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.rescan_rows_bulk(api, ["f1", "f2"], run_id="r1")
            self.assertTrue(res["ok"])
            self.assertEqual(res["job_id"], "job_xyz")
            self.assertEqual(res["count"], 2)
            _store, runner = api._get_or_create_infra.return_value
            self.assertEqual(runner.start_job.call_count, 1)

    def test_bulk_empty_returns_error(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.rescan_rows_bulk(api, [], run_id="r1")
            self.assertFalse(res["ok"])

    def test_bulk_invalid_type_returns_error(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.rescan_rows_bulk(
                api,
                "not_a_list",
                run_id="r1",  # type: ignore[arg-type]
            )
            self.assertFalse(res["ok"])

    def test_bulk_handles_run_already_active(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            _store, runner = api._get_or_create_infra.return_value
            runner.start_job.side_effect = RuntimeError("Un run est deja en cours")
            res = library_actions_support.rescan_rows_bulk(api, ["f1"], run_id="r1")
            self.assertFalse(res["ok"])

    def test_single_rescan_row_delegates_to_bulk(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.rescan_row(api, "f1", run_id="r1")
            self.assertTrue(res["ok"])
            self.assertEqual(res["count"], 1)


# ---------------------------------------------------------------------------
# 4. export_films
# ---------------------------------------------------------------------------


class ExportFilmsTests(unittest.TestCase):
    def _patch_default_state_dir(self, tmp_path: Path):
        return patch("cinesort.ui.api.library_actions_support.state.default_state_dir", return_value=tmp_path)

    def test_export_csv_produces_valid_file(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            with self._patch_default_state_dir(Path(tmp)):
                res = library_actions_support.export_films(
                    api,
                    ["f1", "f2"],
                    fmt="csv",
                    run_id="r1",
                )
            self.assertTrue(res["ok"])
            self.assertEqual(res["format"], "csv")
            self.assertEqual(res["count"], 2)
            file_path = Path(res["file_path"])
            self.assertTrue(file_path.exists())
            # CSV parseable + 2 rows + headers
            with open(file_path, encoding="utf-8") as fp:
                reader = csv.reader(fp)
                rows = list(reader)
            self.assertEqual(len(rows), 3)  # header + 2 rows
            header = rows[0]
            self.assertIn("title", header)
            self.assertIn("year", header)
            self.assertIn("tier", header)

    def test_export_json_inline_films(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            with self._patch_default_state_dir(Path(tmp)):
                res = library_actions_support.export_films(
                    api,
                    ["f1"],
                    fmt="json",
                    run_id="r1",
                )
            self.assertTrue(res["ok"])
            self.assertEqual(res["format"], "json")
            self.assertIn("films", res)
            self.assertEqual(len(res["films"]), 1)
            self.assertEqual(res["films"][0]["title"], "Inception")
            # Verifier les champs requis spec 07
            f = res["films"][0]
            for key in (
                "title",
                "year",
                "score_v2",
                "tier",
                "path",
                "size_bytes",
                "duration_min",
                "codec",
                "resolution",
                "audio_langs",
                "subs_langs",
                "warnings",
            ):
                self.assertIn(key, f)

    def test_export_all_when_no_row_ids(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            with self._patch_default_state_dir(Path(tmp)):
                res = library_actions_support.export_films(
                    api,
                    [],
                    fmt="json",
                    run_id="r1",
                )
            self.assertTrue(res["ok"])
            self.assertEqual(res["count"], 5)

    def test_export_invalid_format(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.export_films(
                api,
                ["f1"],
                fmt="xml",
                run_id="r1",
            )
            self.assertFalse(res["ok"])

    def test_export_invalid_row_ids_type(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            res = library_actions_support.export_films(
                api,
                "not_a_list",
                fmt="csv",
                run_id="r1",  # type: ignore[arg-type]
            )
            self.assertFalse(res["ok"])


# ---------------------------------------------------------------------------
# 5. Integration : facades expose les nouvelles methodes
# ---------------------------------------------------------------------------


class FacadesExposeNewEndpointsTests(unittest.TestCase):
    def test_library_facade_has_new_methods(self) -> None:
        from cinesort.ui.api.facades.library_facade import LibraryFacade

        for name in (
            "get_library_counters_by_chip",
            "mark_for_deletion",
            "mark_for_deletion_bulk",
            "export_films",
        ):
            self.assertTrue(
                hasattr(LibraryFacade, name),
                f"LibraryFacade should expose {name}",
            )

    def test_run_facade_has_rescan_methods(self) -> None:
        from cinesort.ui.api.facades.run_facade import RunFacade

        for name in ("rescan_row", "rescan_rows_bulk"):
            self.assertTrue(
                hasattr(RunFacade, name),
                f"RunFacade should expose {name}",
            )


if __name__ == "__main__":
    unittest.main()

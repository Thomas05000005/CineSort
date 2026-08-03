"""Tests Phase 4 spec 07 — Bibliotheque backend endpoints.

Couvre les 4 nouveaux endpoints :
- library/get_library_counters_by_chip(filters)
- library/mark_for_deletion_bulk(row_ids)
- run/rescan_rows_bulk(row_ids)
- library/export_films(row_ids, format)
"""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from typing import Dict
from unittest.mock import MagicMock, patch

from cinesort.infra import state


class _FakeFilmModal:
    """AUDIT 2026-07-13 (HIGH-18) : store UNIQUE des marquages suppression (table
    DB film_marked_for_deletion). Le mecanisme bulk n'ecrit plus dans
    deletion_marks.json (store additif, sans annulation possible) -> le mock doit
    exposer la meme surface que cinesort.infra.db.repositories.film_modal."""

    def __init__(self) -> None:
        self.marks: dict[tuple[str, str], str] = {}

    def mark_for_deletion(self, *, run_id: str, row_id: str, source_path: str = "") -> dict:
        self.marks[(str(run_id), str(row_id))] = str(source_path or "")
        return {"ok": True, "marked_at": 1.0}

    def unmark_for_deletion(self, *, run_id: str, row_id: str) -> dict:
        return {"ok": True, "removed": self.marks.pop((str(run_id), str(row_id)), None) is not None}

    def is_marked_for_deletion(self, *, run_id: str, row_id: str) -> bool:
        return (str(run_id), str(row_id)) in self.marks

    def list_marked_for_deletion(self, *, run_id: str) -> list:
        return [
            {"row_id": rid, "source_path": src, "marked_at": 1.0}
            for (rid_run, rid), src in self.marks.items()
            if rid_run == str(run_id)
        ]

    def get_tmdb_override(self, *, run_id: str, row_id: str):
        """Aucun override manuel (le MagicMock renvoyait un mock truthy, ce qui
        faisait ecraser titre/annee des rows Library par des MagicMock)."""
        return None


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
    # Fix audit 2026-05-26 (v1.5.6) Vague L (lib-3) : la vraie structure persistee
    # par compute_quality_score est metrics["detected"] (cf
    # cinesort/domain/quality_score.py _build_quality_metrics_helper, lignes
    # 1318-1372). L'ancien schema fictif metrics["video"]/metrics["audio"] masquait
    # les bugs lib-1 et lib-2 : _build_library_rows retournait silencieusement
    # width=0/height=0/codec=unknown/duration_s=0 sur le code reel, mais ces
    # fixtures menteuses faisaient passer les tests (vacuous).
    # Nouvelles cles fournies (extraites du Discovery sample) :
    #   detected.video_codec / detected.width / detected.height
    #   detected.languages (audio ISO639) / detected.audio_tracks_count
    #   detected.duration_s / detected.file_size_bytes (taille estimee)
    #   detected.hdr10 / detected.hdr_dolby_vision / detected.hdr10_plus
    store.quality.list_quality_reports.return_value = [
        {
            "row_id": "f1",
            "metrics": {
                "detected": {
                    "video_codec": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "languages": ["fra", "eng"],
                    "audio_tracks_count": 2,
                    "duration_s": 8800.0,
                    "file_size_bytes": 17_000_000_000,
                    "hdr10": True,
                    "hdr_dolby_vision": False,
                    "hdr10_plus": False,
                },
            },
        },
        {
            "row_id": "f2",
            "metrics": {
                "detected": {
                    "video_codec": "h264",
                    "width": 1920,
                    "height": 1080,
                    "languages": ["eng"],
                    "audio_tracks_count": 1,
                    "duration_s": 6300.0,
                    "file_size_bytes": 4_100_000_000,
                    "hdr10": False,
                    "hdr_dolby_vision": False,
                    "hdr10_plus": False,
                },
            },
        },
        {
            "row_id": "f3",
            "metrics": {
                "detected": {
                    "video_codec": "h264",
                    "width": 1920,
                    "height": 1080,
                    "languages": ["eng"],
                    "audio_tracks_count": 1,
                    "duration_s": 9700.0,
                    "file_size_bytes": 11_900_000_000,
                    "hdr10": False,
                    "hdr_dolby_vision": False,
                    "hdr10_plus": False,
                },
            },
        },
        {
            "row_id": "f4",
            "metrics": {
                "detected": {
                    "video_codec": "hevc",
                    "width": 3840,
                    "height": 2160,
                    "languages": ["eng"],
                    "audio_tracks_count": 1,
                    "duration_s": 9300.0,
                    "file_size_bytes": 15_400_000_000,
                    "hdr10": False,
                    "hdr_dolby_vision": True,
                    "hdr10_plus": False,
                },
            },
        },
        {
            "row_id": "f5",
            "metrics": {
                "detected": {
                    "video_codec": "h264",
                    "width": 1280,
                    "height": 720,
                    "languages": [],
                    "audio_tracks_count": 0,
                    "duration_s": 5400.0,
                    "file_size_bytes": 700_000_000,
                    "hdr10": False,
                    "hdr_dolby_vision": False,
                    "hdr10_plus": False,
                },
            },
        },
    ]
    store.run.list_runs.return_value = [{"run_id": "r1"}]
    store.film_modal = _FakeFilmModal()
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
            # AUDIT 2026-07-13 (HIGH-18) : le bulk ecrit dans le SEUL store de
            # verite (table DB film_marked_for_deletion), celui que le modal sait
            # annuler — plus dans deletion_marks.json (irrevocable / invisible).
            store, _runner = api._get_or_create_infra.return_value
            marked = sorted(m["row_id"] for m in store.film_modal.list_marked_for_deletion(run_id="r1"))
            self.assertEqual(marked, ["f1", "f2", "f3"])
            self.assertFalse((Path(tmp) / "runs" / "tri_films_r1" / "deletion_marks.json").exists())

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
            # Fix audit 2026-05-24 : mark_for_deletion renomme en mark_single_for_deletion
            res = library_actions_support.mark_single_for_deletion(api, "f1", run_id="r1")
            self.assertTrue(res["ok"])
            self.assertEqual(res["row_id"], "f1")

    def test_single_mark_requires_row_id(self) -> None:
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            # Fix audit 2026-05-24 : mark_for_deletion renomme en mark_single_for_deletion
            res = library_actions_support.mark_single_for_deletion(api, "", run_id="r1")
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

    def test_single_rescan_row_delegates_to_full_pipeline(self) -> None:
        """Spec 06 §3.6 : rescan_row appelle le vrai pipeline (probe + perceptual
        + TMDb re-match) via run_flow_support.rescan_row, pas un JobRunner.

        Cf phase 6 — rescan_row n'est plus un stub bulk : la version single
        est synchrone et adaptee au Modal Film.
        """
        from cinesort.ui.api import library_actions_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            with patch(
                "cinesort.ui.api.run_flow_support.rescan_row",
                return_value={
                    "ok": True,
                    "run_id": "r1",
                    "row_id": "f1",
                    "plan_row": {"row_id": "f1"},
                    "quality": {"score": 80, "tier": "gold"},
                    "perceptual": {},
                },
            ) as mock_run_flow:
                res = library_actions_support.rescan_row(api, "f1", run_id="r1")
            self.assertTrue(res["ok"])
            mock_run_flow.assert_called_once_with(api, "r1", "f1")
            # Le retour contient les nouveaux champs (plan_row, quality, perceptual)
            self.assertIn("plan_row", res)
            self.assertEqual(res["quality"]["score"], 80)


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
            # AUDIT 2026-07-13 (M15) : convention Excel-FR alignee sur
            # dashboard_support (BOM UTF-8 + separateur ";"). On lit donc en
            # `utf-8-sig` (absorbe le BOM) et delimiter=";".
            with open(file_path, encoding="utf-8-sig", newline="") as fp:
                reader = csv.reader(fp, delimiter=";")
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
# 5. Fix audit 2026-05-26 (v1.5.6) Vague L : couverture lib-1 (cles metrics.detected)
#    et lib-2 (size_bytes via detected.file_size_bytes).
#
#    Ces tests doivent ECHOUER avec l'implementation buggee (qui lisait
#    metrics["video"]/["audio"]/["duration_s"]/["size_bytes"]) et PASSER avec
#    le fix qui lit metrics["detected"].{width,height,video_codec,...,file_size_bytes}.
#
#    Mutation testing : si on stub _build_library_rows pour renvoyer
#    width=0/height=0/codec="unknown"/duration_s=0/audio_languages=[]/size_bytes=0,
#    ces assertions tombent toutes.
# ---------------------------------------------------------------------------


class LibraryRowsReadDetectedMetricsTests(unittest.TestCase):
    """Verifie que _build_library_rows lit bien metrics.detected.*."""

    def _rows_by_id(self, tmp_path: Path) -> Dict[str, Dict[str, object]]:
        from cinesort.ui.api import library_support

        api = _make_mock_api_with_rows(tmp_path)
        rows = library_support._build_library_rows(api, run_id="r1")
        return {str(r.get("row_id")): r for r in rows}

    def test_width_height_extracted_from_detected(self) -> None:
        """lib-1 : width/height proviennent de detected.width/.height."""
        with tempfile.TemporaryDirectory() as tmp:
            by_id = self._rows_by_id(Path(tmp))
            self.assertEqual(by_id["f1"]["width"], 3840)
            self.assertEqual(by_id["f1"]["height"], 2160)
            self.assertEqual(by_id["f2"]["width"], 1920)
            self.assertEqual(by_id["f2"]["height"], 1080)
            self.assertEqual(by_id["f5"]["width"], 1280)
            self.assertEqual(by_id["f5"]["height"], 720)

    def test_resolution_classified_from_detected_dimensions(self) -> None:
        """lib-1 : sans width/height, resolution=unknown sur 5/5 films."""
        with tempfile.TemporaryDirectory() as tmp:
            by_id = self._rows_by_id(Path(tmp))
            self.assertEqual(by_id["f1"]["resolution"], "4k")  # 3840x2160
            self.assertEqual(by_id["f2"]["resolution"], "1080p")
            self.assertEqual(by_id["f3"]["resolution"], "1080p")
            self.assertEqual(by_id["f4"]["resolution"], "4k")
            self.assertEqual(by_id["f5"]["resolution"], "720p")

    def test_codec_extracted_from_detected_video_codec(self) -> None:
        """lib-1 : codec lit detected.video_codec (pas detected.codec)."""
        with tempfile.TemporaryDirectory() as tmp:
            by_id = self._rows_by_id(Path(tmp))
            self.assertEqual(by_id["f1"]["codec"], "hevc")
            self.assertEqual(by_id["f2"]["codec"], "h264")
            self.assertEqual(by_id["f4"]["codec"], "hevc")

    def test_duration_s_extracted_from_detected(self) -> None:
        """lib-1 : duration_s lit detected.duration_s (pas metrics.duration_s)."""
        with tempfile.TemporaryDirectory() as tmp:
            by_id = self._rows_by_id(Path(tmp))
            self.assertEqual(by_id["f1"]["duration_s"], 8800.0)
            self.assertEqual(by_id["f1"]["duration_min"], 8800 // 60)
            self.assertEqual(by_id["f5"]["duration_s"], 5400.0)

    def test_audio_languages_extracted_from_detected_languages(self) -> None:
        """lib-1 : audio_languages = detected.languages normalise lowercase.

        Avant : on cherchait metrics.audio (liste de dicts) -> audio_languages=[]
        partout (5/5 films), invisible cote chip.
        """
        with tempfile.TemporaryDirectory() as tmp:
            by_id = self._rows_by_id(Path(tmp))
            # f1 a deux langues audio
            self.assertEqual(sorted(by_id["f1"]["audio_languages"]), ["eng", "fra"])
            self.assertEqual(by_id["f2"]["audio_languages"], ["eng"])
            self.assertEqual(by_id["f5"]["audio_languages"], [])

    def test_hdr_classified_from_detected_booleans(self) -> None:
        """lib-1 : _classify_hdr lit detected.hdr10 / hdr_dolby_vision / hdr10_plus.

        Avant : has_hdr10 / has_dv etaient inexistants -> hdr='sdr' systematique.
        """
        with tempfile.TemporaryDirectory() as tmp:
            by_id = self._rows_by_id(Path(tmp))
            self.assertEqual(by_id["f1"]["hdr"], "hdr10")
            self.assertEqual(by_id["f4"]["hdr"], "dv")
            self.assertEqual(by_id["f2"]["hdr"], "sdr")

    def test_size_bytes_falls_back_to_detected_file_size_bytes(self) -> None:
        """lib-2 : si PlanRow.size_bytes = 0 (cas reel post-scan rapide), on
        retombe sur detected.file_size_bytes plutot que metrics.size_bytes
        (qui n'existe pas).

        On clone _make_mock_api_with_rows en mettant PlanRow.size_bytes=0 pour
        forcer le fallback metrics.
        """
        from cinesort.ui.api import library_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            # Reset des size_bytes top-level pour forcer fallback metrics
            plan = api.run.get_plan.return_value
            for row in plan["rows"]:
                row["size_bytes"] = 0
            rows = library_support._build_library_rows(api, run_id="r1")
            by_id = {str(r.get("row_id")): r for r in rows}
            # Les size_bytes doivent venir de detected.file_size_bytes
            self.assertEqual(by_id["f1"]["size_bytes"], 17_000_000_000)
            self.assertEqual(by_id["f2"]["size_bytes"], 4_100_000_000)
            self.assertEqual(by_id["f5"]["size_bytes"], 700_000_000)


class LibraryRowsRejectOldSchemaTests(unittest.TestCase):
    """Garde-fou : verifie qu'un faux schema (ancienne forme metrics.video/audio)
    ne produit PAS width/codec/duration valides. Sinon le code lirait deux
    chemins et masquerait une regression future.

    Ces assertions echouent si quelqu'un re-ajoute un fallback metrics["video"].
    """

    def test_old_schema_video_audio_does_not_leak(self) -> None:
        from cinesort.ui.api import library_support

        with tempfile.TemporaryDirectory() as tmp:
            api = _make_mock_api_with_rows(Path(tmp))
            # On remplace les quality_reports par l'ancien faux schema
            api._get_or_create_infra.return_value[0].quality.list_quality_reports.return_value = [
                {
                    "row_id": "f1",
                    "metrics": {
                        # Ancien schema fictif (lib-1 bug)
                        "video": {"codec": "hevc", "width": 3840, "height": 2160},
                        "audio": [{"language": "fra"}],
                        "duration_s": 8800,
                        "size_bytes": 17_000_000_000,
                    },
                },
            ]
            # On reset size_bytes top-level pour exposer le fallback
            for row in api.run.get_plan.return_value["rows"]:
                row["size_bytes"] = 0
            rows = library_support._build_library_rows(api, run_id="r1")
            by_id = {str(r.get("row_id")): r for r in rows}
            # Si lib-1 etait re-introduit, on aurait width=3840 ici.
            self.assertEqual(by_id["f1"]["width"], 0)
            self.assertEqual(by_id["f1"]["height"], 0)
            self.assertEqual(by_id["f1"]["codec"], "unknown")
            self.assertEqual(by_id["f1"]["duration_s"], 0.0)
            # lib-2 : metrics.size_bytes ne doit pas leaker non plus
            self.assertEqual(by_id["f1"]["size_bytes"], 0)


# ---------------------------------------------------------------------------
# 6. Integration : facades expose les nouvelles methodes
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

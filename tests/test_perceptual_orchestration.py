"""Tests orchestration analyse perceptuelle — Phase VI (item 9.24).

Couvre :
- get_perceptual_report : resultat complet, cache DB, force, erreurs
- analyze_perceptual_batch : batch avec erreurs
- quality_report enrichi avec perceptual
- settings_dict, endpoints exposes, persistence DB
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cinesort.ui.api.perceptual_support import (
    _build_settings_dict,
    analyze_perceptual_batch,
    enrich_quality_report_with_perceptual,
    get_perceptual_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _mock_api(perceptual_enabled: bool = True, ffprobe_path: str = "/usr/bin/ffprobe"):
    """Cree un mock API avec les methodes requises."""
    api = mock.MagicMock()
    api.settings.get_settings.return_value = {
        "perceptual_enabled": perceptual_enabled,
        "ffprobe_path": ffprobe_path,
        "perceptual_timeout_per_film_s": 120,
        "perceptual_frames_count": 5,
        "perceptual_skip_percent": 5,
        "perceptual_dark_weight": 1.5,
        "perceptual_audio_deep": False,
        "perceptual_audio_segment_s": 30,
        "perceptual_comparison_frames": 20,
        "perceptual_comparison_timeout_s": 600,
    }
    return api


def _mock_store_with_run(run_id: str = "run1"):
    """Mock store avec perceptual report vide."""
    store = mock.MagicMock()
    store.get_perceptual_report.return_value = None
    return store


def _mock_row(row_id: str = "r1"):
    """Mock PlanRow basique."""
    return SimpleNamespace(
        row_id=row_id,
        proposed_title="Inception",
        proposed_year=2010,
        folder="/films/Inception",
        video="inception.mkv",
        candidates=[SimpleNamespace(tmdb_id=27205)],
    )


# ---------------------------------------------------------------------------
# Settings dict (1 test)
# ---------------------------------------------------------------------------


class SettingsDictTests(unittest.TestCase):
    """Tests de la construction du dict settings perceptuels."""

    def test_all_keys_present(self) -> None:
        """Le dict contient tous les parametres perceptuels."""
        settings = {
            "perceptual_enabled": True,
            "perceptual_auto_on_scan": False,
            "perceptual_auto_on_quality": True,
            "perceptual_timeout_per_film_s": 120,
            "perceptual_frames_count": 10,
            "perceptual_skip_percent": 5,
            "perceptual_dark_weight": 1.5,
            "perceptual_audio_deep": True,
            "perceptual_audio_segment_s": 30,
            "perceptual_comparison_frames": 20,
            "perceptual_comparison_timeout_s": 600,
        }
        d = _build_settings_dict(settings)
        self.assertTrue(d["enabled"])
        self.assertEqual(d["frames_count"], 10)
        self.assertEqual(d["timeout_per_film_s"], 120)
        self.assertEqual(d["comparison_timeout_s"], 600)
        self.assertIn("audio_deep", d)
        self.assertIn("dark_weight", d)


# ---------------------------------------------------------------------------
# Endpoints exposes (1 test)
# ---------------------------------------------------------------------------


class EndpointsExposedTests(unittest.TestCase):
    """Tests que les endpoints sont dans CineSortApi."""

    def test_methods_exist(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        api = backend.CineSortApi()
        self.assertTrue(hasattr(api.quality, "get_perceptual_report"))
        self.assertTrue(hasattr(api.quality, "analyze_perceptual_batch"))


# ---------------------------------------------------------------------------
# get_perceptual_report (7 tests)
# ---------------------------------------------------------------------------


class GetPerceptualReportTests(unittest.TestCase):
    """Tests de l'orchestrateur single-film."""

    def test_disabled_returns_error(self) -> None:
        """perceptual_enabled=False → erreur propre."""
        api = _mock_api(perceptual_enabled=False)
        result = get_perceptual_report(api, "run1", "r1")
        self.assertFalse(result["ok"])
        self.assertIn("desactivee", result["message"])

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value=None)
    def test_ffmpeg_not_found(self, _mock_resolve) -> None:
        """ffmpeg introuvable → erreur propre."""
        api = _mock_api()
        result = get_perceptual_report(api, "run1", "r1")
        self.assertFalse(result["ok"])
        self.assertIn("ffmpeg", result["message"].lower())

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")
    def test_run_not_found(self, _) -> None:
        """Run introuvable → erreur propre."""
        api = _mock_api()
        api._find_run_row.return_value = None
        result = get_perceptual_report(api, "run_fake", "r1")
        self.assertFalse(result["ok"])
        self.assertIn("introuvable", result["message"].lower())

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")
    def test_cache_hit_returns_existing(self, _) -> None:
        """Rapport deja en DB → retourne le cache sans ré-analyser."""
        api = _mock_api()
        store = mock.MagicMock()
        store.get_perceptual_report.return_value = {
            "run_id": "run1",
            "row_id": "r1",
            "global_score": 80,
            "global_tier": "excellent",
            "visual_score": 78,
            "audio_score": 82,
            "metrics": {"global_score": 80},
            "settings_used": {},
            "ts": 1.0,
        }
        api._find_run_row.return_value = ({"state_dir": "/tmp"}, store)
        result = get_perceptual_report(api, "run1", "r1")
        self.assertTrue(result["ok"])
        self.assertTrue(result["cache_hit"])

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")
    def test_force_bypasses_cache(self, _) -> None:
        """force=True → ignore le cache et ré-analyse."""
        api = _mock_api()
        store = mock.MagicMock()
        store.get_perceptual_report.return_value = {
            "run_id": "run1",
            "row_id": "r1",
            "global_score": 80,
            "metrics": {"global_score": 80},
            "settings_used": {},
            "ts": 1.0,
            "global_tier": "excellent",
            "visual_score": 78,
            "audio_score": 82,
        }
        api._find_run_row.return_value = ({"state_dir": "/tmp"}, store)
        # Mais le row n'est pas trouvable → erreur (prouve que le cache est ignore)
        rs = mock.MagicMock()
        rs.rows = []
        api._get_run.return_value = rs
        api._load_rows_from_plan_jsonl.return_value = []
        result = get_perceptual_report(api, "run1", "r1", {"force": True})
        # Soit erreur "Film introuvable" (cache contourne), soit erreur autre
        self.assertFalse(result["ok"])

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")
    def test_row_not_found(self, _) -> None:
        """PlanRow inexistant → erreur propre."""
        api = _mock_api()
        store = _mock_store_with_run()
        api._find_run_row.return_value = ({"state_dir": "/tmp"}, store)
        rs = mock.MagicMock()
        rs.rows = []
        api._get_run.return_value = rs
        api._load_rows_from_plan_jsonl.return_value = []
        result = get_perceptual_report(api, "run1", "r_missing")
        self.assertFalse(result["ok"])
        self.assertIn("introuvable", result["message"].lower())

    @mock.patch("cinesort.ui.api.perceptual_support.resolve_ffmpeg_path", return_value="/usr/bin/ffmpeg")
    def test_probe_incomplete(self, _) -> None:
        """Probe sans dimensions → erreur propre."""
        api = _mock_api()
        store = _mock_store_with_run()
        api._find_run_row.return_value = ({"state_dir": "/tmp"}, store)
        row = _mock_row()
        rs = mock.MagicMock()
        rs.rows = [row]
        rs.cfg = mock.MagicMock()
        api._get_run.return_value = rs
        media = mock.MagicMock()
        media.exists.return_value = True
        api._resolve_media_path_for_row.return_value = media

        # Probe retourne pas de video ni audio
        with mock.patch("cinesort.ui.api.perceptual_support._load_probe") as mock_probe:
            mock_probe.return_value = {"normalized": {"video": {}, "duration_s": 0, "audio_tracks": []}}
            result = get_perceptual_report(api, "run1", "r1")
        self.assertFalse(result["ok"])
        self.assertIn("probe", result["message"].lower())


# ---------------------------------------------------------------------------
# Batch (2 tests)
# ---------------------------------------------------------------------------


class BatchTests(unittest.TestCase):
    """Tests du batch perceptuel."""

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_batch_with_mixed_results(self, mock_get) -> None:
        """3 films dont 1 erreur → 2 succes + 1 erreur."""
        mock_get.side_effect = [
            {"ok": True, "cache_hit": False, "perceptual": {"global_score": 80}},
            {"ok": False, "message": "erreur film 2"},
            {"ok": True, "cache_hit": False, "perceptual": {"global_score": 70}},
        ]
        result = analyze_perceptual_batch(mock.MagicMock(), "run1", ["r1", "r2", "r3"])
        self.assertTrue(result["ok"])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["success_count"], 2)
        self.assertEqual(result["error_count"], 1)

    @mock.patch("cinesort.ui.api.perceptual_support.get_perceptual_report")
    def test_batch_empty(self, mock_get) -> None:
        """0 row_ids → resultat vide."""
        result = analyze_perceptual_batch(mock.MagicMock(), "run1", [])
        self.assertEqual(result["total"], 0)
        self.assertEqual(result["success_count"], 0)
        mock_get.assert_not_called()


# ---------------------------------------------------------------------------
# Enrichissement quality report (2 tests)
# ---------------------------------------------------------------------------


class EnrichQualityReportTests(unittest.TestCase):
    """Tests de l'enrichissement du rapport qualite avec perceptual."""

    def test_enriched_when_available(self) -> None:
        """Perceptual disponible → cle 'perceptual' ajoutee."""
        store = mock.MagicMock()
        store.get_perceptual_report.return_value = {
            "global_score": 80,
            "global_tier": "excellent",
            "visual_score": 78,
            "audio_score": 82,
        }
        result: dict = {"ok": True, "score": 85}
        enrich_quality_report_with_perceptual(store, "run1", "r1", result)
        self.assertIn("perceptual", result)
        self.assertEqual(result["perceptual"]["global_score"], 80)

    def test_not_enriched_when_absent(self) -> None:
        """Perceptual absent → pas de cle 'perceptual'."""
        store = mock.MagicMock()
        store.get_perceptual_report.return_value = None
        result: dict = {"ok": True, "score": 85}
        enrich_quality_report_with_perceptual(store, "run1", "r1", result)
        self.assertNotIn("perceptual", result)


# ---------------------------------------------------------------------------
# Persistence DB (1 test)
# ---------------------------------------------------------------------------


class PersistenceTests(unittest.TestCase):
    """Verifie que le resultat est persiste en DB."""

    def test_db_roundtrip(self) -> None:
        """upsert + get retourne le resultat."""
        tmp = tempfile.mkdtemp(prefix="cinesort_perc_orch_")
        try:
            db_path = Path(tmp) / "db" / "cinesort.sqlite"
            from cinesort.infra.db.sqlite_store import SQLiteStore

            store = SQLiteStore(db_path)
            store.initialize()

            store.upsert_perceptual_report(
                run_id="run1",
                row_id="r1",
                visual_score=78,
                audio_score=82,
                global_score=80,
                global_tier="excellent",
                metrics={"global_score": 80, "visual_score": 78},
                settings_used={"frames_count": 10},
            )
            result = store.get_perceptual_report(run_id="run1", row_id="r1")
            self.assertIsNotNone(result)
            self.assertEqual(result["global_score"], 80)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

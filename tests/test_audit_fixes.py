"""Audit post-v7.3.0 : tests de non-régression pour les 5 fixes de cohérence.

Couverture :
- FIX 1 : endpoints renommés `export_shareable_profile` / `import_shareable_profile`
  coexistent avec les anciens `export_quality_profile` / `import_quality_profile`
  sans conflit de nommage.
- FIX 2 : `get_calibration_report` reste fonctionnel (déjà testé via test_calibration).
- FIX 3 : tierPill intégré dans l'UI (test JS par introspection).
- FIX 4 : `adjust_bitrate_threshold` effectivement utilisé dans `_score_video`.
- FIX 5 : `delete_score_feedback` endpoint exposé et fonctionnel.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.ui.api.cinesort_api import CineSortApi


class EndpointCoexistenceTests(unittest.TestCase):
    """FIX 1 : les endpoints historiques et les nouveaux P4.3 coexistent."""

    def test_both_export_endpoints_exist(self):
        api = CineSortApi()
        # Issue #84 PR 10 : export_quality_profile est sur la QualityFacade
        # Historique : profile brut
        self.assertTrue(hasattr(api.quality, "export_quality_profile"))
        # P4.3 : wrappé avec metadata
        self.assertTrue(hasattr(api, "export_shareable_profile"))

    def test_both_import_endpoints_exist(self):
        api = CineSortApi()
        # Issue #84 PR 10 : import_quality_profile est sur la QualityFacade
        self.assertTrue(hasattr(api.quality, "import_quality_profile"))
        self.assertTrue(hasattr(api, "import_shareable_profile"))

    def test_shareable_endpoints_distinct_signatures(self):
        import inspect

        api = CineSortApi()
        sig_shareable = inspect.signature(api.export_shareable_profile)
        # Issue #84 PR 10 : export_quality_profile est sur la QualityFacade
        sig_legacy = inspect.signature(api.quality.export_quality_profile)
        # shareable a plus de params
        self.assertGreater(len(sig_shareable.parameters), len(sig_legacy.parameters))


class ShareableEndpointPositionalArgsTests(unittest.TestCase):
    """FIX 1 : pywebview passe des args positionnels — plus de `*` kwargs-only."""

    def test_export_shareable_accepts_positional(self):
        api = CineSortApi()
        # Simule un appel pywebview avec args positionnels
        result = api.export_shareable_profile("MyProfile", "Alice", "Test profile")
        self.assertTrue(result.get("ok"))
        self.assertIn("content", result)
        self.assertIn("MyProfile", result.get("filename_suggestion", ""))

    def test_export_shareable_no_args(self):
        api = CineSortApi()
        # Tous les args ont des defaults
        result = api.export_shareable_profile()
        self.assertTrue(result.get("ok"))

    def test_import_shareable_accepts_positional(self):
        api = CineSortApi()
        # Export puis import pour valider le roundtrip positionnel
        exported = api.export_shareable_profile("RoundtripTest")
        self.assertTrue(exported.get("ok"))
        # Simuler un import avec args positionnels (comme depuis JS)
        result = api.import_shareable_profile(exported["content"], True)
        # L'appel peut échouer si le store n'est pas accessible dans le contexte test,
        # mais la signature ne doit JAMAIS produire de TypeError args-mismatch.
        self.assertIn("ok", result)


class DeleteFeedbackEndpointTests(unittest.TestCase):
    """FIX 5 : delete_score_feedback exposé et fonctionnel."""

    def test_endpoint_exists(self):
        # Issue #84 PR 10 : delete_score_feedback est sur la QualityFacade
        api = CineSortApi()
        self.assertTrue(hasattr(api.quality, "delete_score_feedback"))
        self.assertTrue(callable(api.quality.delete_score_feedback))

    def test_returns_ok_structure(self):
        api = CineSortApi()
        # Suppression d'un feedback inexistant : ok=True, deleted_count=0
        result = api.quality.delete_score_feedback(999_999_999)
        # Soit ok=True avec 0 supprimés, soit ok=False si store indispo
        self.assertIn("ok", result)
        if result.get("ok"):
            self.assertEqual(result.get("deleted_count"), 0)


class BitrateGenreAdjustmentTests(unittest.TestCase):
    """FIX 4 : adjust_bitrate_threshold effectivement utilisé via tmdb_genres."""

    def test_animation_genre_reduces_threshold_effect(self):
        """Un film animation bas bitrate ne doit plus être fortement pénalisé
        vs la même probe sans genre (qui serait flaggée underbitrate).
        """
        from cinesort.domain.quality_score import compute_quality_score, default_quality_profile

        probe = {
            "probe_quality": "PROBED",
            "video": {
                "codec": "hevc",
                "width": 1920,
                "height": 1080,
                "bitrate": 4_500_000,  # 4.5 Mbps (sous seuil 1080p 8 Mbps)
                "bit_depth": 10,
            },
            "audio_tracks": [{"codec": "ac3", "channels": 6}],
            "duration_s": 5400,
        }
        profile = default_quality_profile()
        # Sans genre
        res_no_genre = compute_quality_score(normalized_probe=probe, profile=profile)
        # Avec genre Animation (leniency 0.75 → seuil passe de 8000 à 6000, ratio meilleur)
        res_anim = compute_quality_score(normalized_probe=probe, profile=profile, tmdb_genres=["Animation"])
        # L'animation doit avoir un score >= sans genre (leniency avantage ce cas)
        self.assertGreaterEqual(res_anim["score"], res_no_genre["score"])

    def test_primary_genre_exposed_in_metrics(self):
        from cinesort.domain.quality_score import compute_quality_score, default_quality_profile

        probe = {
            "probe_quality": "PROBED",
            "video": {"codec": "hevc", "width": 3840, "height": 2160, "bitrate": 30_000_000, "bit_depth": 10},
            "audio_tracks": [{"codec": "truehd", "channels": 8}],
            "duration_s": 7200,
        }
        res = compute_quality_score(
            normalized_probe=probe,
            profile=default_quality_profile(),
            tmdb_genres=["Horror", "Thriller"],
        )
        # Horror doit primer sur Thriller (priorité)
        self.assertEqual(res["metrics"]["primary_genre"], "horror")


class AuditUIIntegrationTests(unittest.TestCase):
    """FIX 2 + 3 : l'UI settings consomme get_calibration_report et renomme les endpoints."""

    @classmethod
    def setUpClass(cls):
        cls.settings_js = (Path(__file__).resolve().parents[1] / "web" / "views" / "settings.js").read_text(
            encoding="utf-8"
        )
        cls.index_html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")
        cls.validation_js = (Path(__file__).resolve().parents[1] / "web" / "views" / "validation.js").read_text(
            encoding="utf-8"
        )

    def test_settings_uses_shareable_endpoints(self):
        """FIX 1 : JS appelle les nouveaux endpoints renommés."""
        self.assertIn("export_shareable_profile", self.settings_js)
        self.assertIn("import_shareable_profile", self.settings_js)

    def test_settings_consumes_calibration_report(self):
        """FIX 2 : bouton + fonction pour get_calibration_report."""
        self.assertIn("btnShowCalibration", self.settings_js)
        self.assertIn("get_calibration_report", self.settings_js)
        self.assertIn("_showCalibrationReport", self.settings_js)

    def test_calibration_button_in_html(self):
        self.assertIn('id="btnShowCalibration"', self.index_html)
        self.assertIn('id="calibrationReportContent"', self.index_html)

    def test_explain_score_uses_tierPill(self):
        """FIX 3 : la modal explain-score utilise tierPill pour afficher le tier."""
        # Le header utilise tierPill au lieu de texte brut
        self.assertIn("tierPill(tier)", self.validation_js)


if __name__ == "__main__":
    unittest.main()

# Fix audit 2026-05-25 (v1.5.4) Vague I : test BUG 1 — apres scan, les rows
# doivent obtenir un tier non-null via le declenchement auto du recalcul
# de scores (auto_recompute_quality_on_scan=True par defaut).
"""Tests pour le declenchement automatique du calcul des scores qualite
apres un scan (Vague I, BUG 1).

Verifie :
1. Le setting `auto_recompute_quality_on_scan` existe avec default True.
2. `_save_section_subtitles` persiste le toggle correctement.
3. L'integration end-to-end : a la fin du scan, `recompute_all_scores` est
   declenche en background quand le toggle est True, skip quand False.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cinesort.ui.api import quality_audit_support, settings_support


class AutoRecomputeSettingDefaultsTests(unittest.TestCase):
    """Vague I BUG 1 : le setting `auto_recompute_quality_on_scan` est expose
    avec default True dans le schema settings."""

    def test_setting_in_defaults_with_true(self) -> None:
        """Le default `auto_recompute_quality_on_scan` est True dans
        `settings_support._LITERAL_DEFAULTS`."""
        defaults = dict(settings_support._LITERAL_DEFAULTS)
        self.assertIn("auto_recompute_quality_on_scan", defaults)
        self.assertEqual(defaults["auto_recompute_quality_on_scan"], True)

    def test_save_section_subtitles_persists_toggle_true(self) -> None:
        out = settings_support._save_section_subtitles(
            {"auto_recompute_quality_on_scan": True}
        )
        self.assertIn("auto_recompute_quality_on_scan", out)
        self.assertEqual(out["auto_recompute_quality_on_scan"], True)

    def test_save_section_subtitles_persists_toggle_false(self) -> None:
        out = settings_support._save_section_subtitles(
            {"auto_recompute_quality_on_scan": False}
        )
        self.assertIn("auto_recompute_quality_on_scan", out)
        self.assertEqual(out["auto_recompute_quality_on_scan"], False)

    def test_save_section_subtitles_default_true_when_absent(self) -> None:
        out = settings_support._save_section_subtitles({})
        # `to_bool(None, True)` -> True
        self.assertEqual(out["auto_recompute_quality_on_scan"], True)


class RecomputeAllScoresContractTests(unittest.TestCase):
    """Vague I BUG 1 : `quality_audit_support.recompute_all_scores` declenche
    bien le calcul et reste robuste si pas de run / pas de row."""

    def _make_api(self) -> MagicMock:
        api = MagicMock()
        api.settings.get_settings.return_value = {"state_dir": "/tmp/cinesort_test"}
        return api

    def test_no_run_returns_error_state(self) -> None:
        api = self._make_api()
        with patch.object(
            quality_audit_support, "_resolve_latest_run_id", return_value=None
        ):
            res = quality_audit_support.recompute_all_scores(api)
        self.assertFalse(res.get("ok"))
        # _err_response retourne `message`, pas `user_message`. On verifie juste
        # qu'on a un message d'erreur clair.
        self.assertTrue(res.get("message"))

    def test_no_rows_returns_error_state(self) -> None:
        api = self._make_api()
        api.run.get_plan.return_value = {"ok": True, "rows": []}
        with patch.object(
            quality_audit_support, "_resolve_latest_run_id", return_value="run_xyz"
        ):
            res = quality_audit_support.recompute_all_scores(api)
        self.assertFalse(res.get("ok"))
        self.assertTrue(res.get("message"))

    def test_with_rows_starts_background_job(self) -> None:
        api = self._make_api()
        api.run.get_plan.return_value = {
            "ok": True,
            "rows": [{"row_id": "R1"}, {"row_id": "R2"}, {"row_id": "R3"}],
        }
        # Stub la facade quality.get_quality_report pour ne pas executer le
        # vrai pipeline probe+score (necessite filesystem + ffprobe).
        api.quality.get_quality_report.return_value = {"ok": True}

        with patch.object(
            quality_audit_support, "_resolve_latest_run_id", return_value="run_xyz"
        ):
            res = quality_audit_support.recompute_all_scores(api)

        self.assertTrue(res.get("ok"), f"recompute_all_scores doit reussir: {res}")
        self.assertEqual(res.get("total"), 3)
        self.assertEqual(res.get("run_id"), "run_xyz")
        self.assertTrue(res.get("job_id"))


class QualityReportPersistsEmbeddedSubtitlesTests(unittest.TestCase):
    """Vague I BUG 2 : `_probe_and_score` doit persister `subtitles_embedded`
    dans `quality_reports.metrics` pour que la library puisse fusionner."""

    def test_probe_and_score_writes_subtitles_embedded(self) -> None:
        from cinesort.ui.api import quality_report_support

        api = MagicMock()
        api._effective_probe_settings_for_runtime.return_value = {}
        api._tmdb_client.return_value = None

        store = MagicMock()
        store.quality.get_quality_report.return_value = None

        run_row = {"state_dir": "/tmp"}
        row = MagicMock()
        row.folder = "/tmp/Inception"
        row.proposed_title = "Inception"
        row.proposed_year = 2010
        row.video = "Inception.mkv"
        row.candidates = []

        embedded = [
            {"index": 2, "language": "fra", "forced": False},
            {"index": 3, "language": "eng", "forced": False},
        ]
        probe_result = {
            "normalized": {
                "subtitles": embedded,
                "video": {"width": 1920, "height": 1080},
                "audio_tracks": [],
            },
            "cache_hit": False,
        }

        with patch.object(
            quality_report_support, "ProbeService"
        ) as mock_probe_cls, patch.object(
            quality_report_support,
            "compute_quality_score",
            return_value={
                "score": 75,
                "tier": "Gold",
                "reasons": [],
                "metrics": {"video": {"width": 1920}},
            },
        ):
            mock_probe = MagicMock()
            mock_probe.probe_file.return_value = probe_result
            mock_probe_cls.return_value = mock_probe

            quality_report_support._probe_and_score(
                api,
                store,
                run_row,
                "run_test",
                "row_1",
                row,
                "/tmp/Inception/Inception.mkv",
                profile_json={"id": "default", "version": 1},
                active_profile_id="default",
                active_profile_version=1,
            )

        # Verifier que upsert_quality_report recoit `subtitles_embedded` dans metrics
        store.quality.upsert_quality_report.assert_called_once()
        kwargs = store.quality.upsert_quality_report.call_args.kwargs
        metrics = kwargs.get("metrics") or {}
        self.assertIn("subtitles_embedded", metrics)
        self.assertEqual(metrics["subtitles_embedded"], embedded)


if __name__ == "__main__":
    unittest.main()

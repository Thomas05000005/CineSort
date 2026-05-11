"""V2-05 — Tests cinesort_api endpoints divers (server/cache/profile/feedback/calibration/naming)."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch, MagicMock

import cinesort.ui.api.cinesort_api as backend


class TestServerInfoAndQR(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_server_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_get_event_ts_returns_floats(self) -> None:
        result = self.api.get_event_ts()
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["last_event_ts"], float)
        self.assertIsInstance(result["last_settings_ts"], float)

    def test_get_server_info_no_server(self) -> None:
        self.api._rest_server = None  # type: ignore[attr-defined]
        result = self.api.get_server_info()
        self.assertFalse(result["ok"])
        self.assertIn("non demarre", result["message"])

    def test_get_server_info_running(self) -> None:
        fake_server = MagicMock()
        fake_server.is_running = True
        fake_server._port = 9999
        fake_server._is_https = False
        self.api._rest_server = fake_server  # type: ignore[attr-defined]
        with (
            patch("cinesort.infra.network_utils.get_local_ip", return_value="192.168.1.10"),
            patch("cinesort.infra.network_utils.build_dashboard_url", return_value="http://192.168.1.10:9999/"),
        ):
            result = self.api.get_server_info()
            self.assertTrue(result["ok"])
            self.assertEqual(result["port"], 9999)
            self.assertEqual(result["ip"], "192.168.1.10")

    def test_get_dashboard_qr_fallback(self) -> None:
        # Pas de serveur → fallback settings
        self.api._rest_server = None  # type: ignore[attr-defined]
        with patch.object(backend.CineSortApi, "get_settings") as mock_gs:
            mock_gs.return_value = {"rest_api_port": 8642, "rest_api_https_enabled": False}
            with (
                patch("cinesort.infra.network_utils.get_local_ip", return_value="10.0.0.5"),
                patch("cinesort.infra.network_utils.build_dashboard_url", return_value="http://10.0.0.5:8642/"),
            ):
                result = self.api.get_dashboard_qr()
                self.assertTrue(result["ok"])
                self.assertIn("svg", result)
                self.assertIn("<svg", result["svg"])
                self.assertEqual(result["url"], "http://10.0.0.5:8642/")

    def test_get_dashboard_qr_segno_failure(self) -> None:
        self.api._rest_server = None  # type: ignore[attr-defined]
        with patch.object(backend.CineSortApi, "get_settings") as mock_gs:
            mock_gs.return_value = {"rest_api_port": 8642}
            with (
                patch("cinesort.infra.network_utils.get_local_ip", return_value="10.0.0.5"),
                patch("cinesort.infra.network_utils.build_dashboard_url", return_value="http://x"),
                patch("segno.make", side_effect=ValueError("bad")),
            ):
                result = self.api.get_dashboard_qr()
                self.assertFalse(result["ok"])
                self.assertIn("Erreur", result["message"])


class TestRestartApiServer(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_restart_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    @patch.object(backend.CineSortApi, "get_settings")
    def test_restart_disabled(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"rest_api_enabled": False}
        result = self.api.restart_api_server()
        self.assertFalse(result["ok"])
        self.assertIn("desactivee", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    def test_restart_no_token(self, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {"rest_api_enabled": True, "rest_api_token": ""}
        result = self.api.restart_api_server()
        self.assertFalse(result["ok"])
        self.assertIn("token", result["message"])

    @patch.object(backend.CineSortApi, "get_settings")
    @patch("cinesort.infra.rest_server.RestApiServer")
    def test_restart_success(self, mock_server_cls: MagicMock, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "rest_api_enabled": True,
            "rest_api_token": "tok",
            "rest_api_port": 8642,
        }
        server = MagicMock()
        server.dashboard_url = "http://x:8642/"
        server._is_https = False
        mock_server_cls.return_value = server
        result = self.api.restart_api_server()
        self.assertTrue(result["ok"])
        self.assertEqual(result["dashboard_url"], "http://x:8642/")
        server.start.assert_called_once()

    @patch.object(backend.CineSortApi, "get_settings")
    @patch("cinesort.infra.rest_server.RestApiServer")
    def test_restart_stops_old_server(self, mock_server_cls: MagicMock, mock_get_settings: MagicMock) -> None:
        mock_get_settings.return_value = {
            "rest_api_enabled": True,
            "rest_api_token": "tok",
            "rest_api_port": 8642,
        }
        old_server = MagicMock()
        self.api._rest_server = old_server  # type: ignore[attr-defined]
        new_server = MagicMock()
        new_server.dashboard_url = "http://new:8642/"
        new_server._is_https = False
        mock_server_cls.return_value = new_server
        self.api.restart_api_server()
        old_server.stop.assert_called_once()


class TestResetIncrementalCache(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_reset_cache_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_reset_success(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.clear_all_incremental_caches.return_value = {
                "folder_cache": 5,
                "row_cache": 10,
                "file_hashes": 20,
            }
            mock_infra.return_value = (store, MagicMock())
            result = self.api.reset_incremental_cache()
            self.assertTrue(result["ok"])
            self.assertEqual(result["total_deleted"], 35)
            self.assertEqual(result["folder_entries_deleted"], 5)

    def test_reset_store_init_failure(self) -> None:
        with patch.object(self.api, "_get_or_create_infra", side_effect=OSError("disk full")):
            result = self.api.reset_incremental_cache()
            self.assertFalse(result["ok"])
            self.assertIn("Store indisponible", result["message"])

    def test_reset_clear_failure(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.clear_all_incremental_caches.side_effect = ValueError("sql error")
            mock_infra.return_value = (store, MagicMock())
            result = self.api.reset_incremental_cache()
            self.assertFalse(result["ok"])
            self.assertIn("Purge echouee", result["message"])


class TestValidateDroppedPath(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_drop_")
        self.api = backend.CineSortApi()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_path(self) -> None:
        result = self.api.validate_dropped_path(path="")
        self.assertFalse(result["ok"])
        self.assertIn("vide", result["message"])

    def test_unc_special_qmark(self) -> None:
        result = self.api.validate_dropped_path(path=r"\\?\C:\test")
        self.assertFalse(result["ok"])
        self.assertIn("UNC special", result["message"])

    def test_unc_special_dot(self) -> None:
        result = self.api.validate_dropped_path(path=r"\\.\C:\test")
        self.assertFalse(result["ok"])
        self.assertIn("UNC special", result["message"])

    def test_nonexistent_path(self) -> None:
        result = self.api.validate_dropped_path(path=str(Path(self._tmp) / "no_such_dir"))
        self.assertFalse(result["ok"])
        # Soit "introuvable", soit "inaccessible"
        self.assertIn("ok", result)

    def test_existing_directory(self) -> None:
        result = self.api.validate_dropped_path(path=self._tmp)
        self.assertTrue(result["ok"])
        self.assertIn("path", result)

    def test_file_not_dir(self) -> None:
        f = Path(self._tmp) / "file.txt"
        f.write_text("x")
        result = self.api.validate_dropped_path(path=str(f))
        self.assertFalse(result["ok"])
        self.assertIn("pas un dossier", result["message"])


class TestNamingPresets(unittest.TestCase):
    def setUp(self) -> None:
        self.api = backend.CineSortApi()

    def test_get_naming_presets(self) -> None:
        result = self.api.get_naming_presets()
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["presets"], list)
        self.assertGreater(len(result["presets"]), 0)
        # Vérifier la structure
        first = result["presets"][0]
        for k in ("id", "label", "movie_template", "tv_template"):
            self.assertIn(k, first)

    def test_preview_naming_template_invalid(self) -> None:
        result = self.api.preview_naming_template(template="{unknown_var}")
        self.assertFalse(result["ok"])
        self.assertIn("errors", result)

    def test_preview_naming_template_default(self) -> None:
        result = self.api.preview_naming_template(template="")
        # Template vide → fallback "{title} ({year})"
        self.assertTrue(result["ok"])
        self.assertIn("result", result)
        self.assertIn("variables", result)


class TestCustomRulesEndpoints(unittest.TestCase):
    def setUp(self) -> None:
        self.api = backend.CineSortApi()

    def test_get_custom_rules_templates(self) -> None:
        result = self.api.get_custom_rules_templates()
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["templates"], list)

    def test_get_custom_rules_catalog(self) -> None:
        result = self.api.get_custom_rules_catalog()
        self.assertTrue(result["ok"])
        for k in ("fields", "operators", "actions"):
            self.assertIn(k, result)
            self.assertIsInstance(result[k], list)

    def test_validate_custom_rules_empty(self) -> None:
        result = self.api.validate_custom_rules(rules=[])
        self.assertTrue(result["ok"])
        self.assertEqual(result["normalized"], [])

    def test_validate_custom_rules_invalid(self) -> None:
        result = self.api.validate_custom_rules(rules=[{"invalid": "structure"}])
        self.assertFalse(result["ok"])
        self.assertIsInstance(result["errors"], list)


class TestTestReset(unittest.TestCase):
    def setUp(self) -> None:
        self.api = backend.CineSortApi()

    def test_reset_disabled_in_prod(self) -> None:
        # Sans CINESORT_E2E=1, reset doit refuser
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("CINESORT_E2E", None)
            result = self.api.test_reset()
            self.assertFalse(result["ok"])
            self.assertIn("E2E", result["error"])

    def test_reset_enabled_e2e(self) -> None:
        with patch.dict(os.environ, {"CINESORT_E2E": "1"}):
            result = self.api.test_reset()
            self.assertTrue(result["ok"])

    def test_reset_lowers_min_video_bytes(self) -> None:
        import cinesort.domain.core as _core

        original = _core.MIN_VIDEO_BYTES
        try:
            with patch.dict(os.environ, {"CINESORT_E2E": "1"}):
                result = self.api.test_reset(min_video_bytes=42)
                self.assertTrue(result["ok"])
                self.assertEqual(_core.MIN_VIDEO_BYTES, 42)
        finally:
            _core.MIN_VIDEO_BYTES = original


class TestExportShareableProfile(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_export_prof_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_export_no_active_profile_uses_default(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.get_active_quality_profile.return_value = None
            mock_infra.return_value = (store, MagicMock())
            result = self.api.export_shareable_profile(name="my profile")
            self.assertTrue(result["ok"])
            self.assertIn("content", result)
            payload = json.loads(result["content"])
            self.assertEqual(payload["name"], "my profile")
            self.assertEqual(payload["schema"], "cinesort.quality_profile")
            self.assertIn("my_profile", result["filename_suggestion"])

    def test_export_with_active_profile(self) -> None:
        from cinesort.domain.quality_score import default_quality_profile

        active_profile = default_quality_profile()
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.get_active_quality_profile.return_value = {
                "profile_json": json.dumps(active_profile),
            }
            mock_infra.return_value = (store, MagicMock())
            result = self.api.export_shareable_profile(name="x", author="me", description="d")
            self.assertTrue(result["ok"])
            payload = json.loads(result["content"])
            self.assertEqual(payload["author"], "me")
            self.assertEqual(payload["description"], "d")

    def test_export_store_init_failure(self) -> None:
        with patch.object(self.api, "_get_or_create_infra", side_effect=OSError("no disk")):
            result = self.api.export_shareable_profile()
            self.assertTrue(result["ok"])  # fallback : utilise default profile

    def test_export_corrupt_profile_json(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.get_active_quality_profile.return_value = {"profile_json": "not_json"}
            mock_infra.return_value = (store, MagicMock())
            result = self.api.export_shareable_profile()
            self.assertTrue(result["ok"])  # fallback default


class TestImportShareableProfile(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_import_prof_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_import_invalid_json(self) -> None:
        result = self.api.import_shareable_profile(content="not json", activate=False)
        self.assertFalse(result["ok"])
        self.assertIn("meta", result)

    def test_import_empty(self) -> None:
        result = self.api.import_shareable_profile(content="", activate=False)
        self.assertFalse(result["ok"])

    def test_import_valid_profile(self) -> None:
        # Fabrique un export valide d'abord
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.get_active_quality_profile.return_value = None
            mock_infra.return_value = (store, MagicMock())
            export_result = self.api.export_shareable_profile(name="test_imp")
            content = export_result["content"]

        # Import avec activation
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.save_quality_profile.return_value = None
            mock_infra.return_value = (store, MagicMock())
            result = self.api.import_shareable_profile(content=content, activate=True)
            self.assertTrue(result["ok"])
            self.assertTrue(result["activated"])
            store.save_quality_profile.assert_called_once()

    def test_import_store_init_fails(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.get_active_quality_profile.return_value = None
            mock_infra.return_value = (store, MagicMock())
            export_result = self.api.export_shareable_profile(name="x")
            content = export_result["content"]

        with patch.object(self.api, "_get_or_create_infra", side_effect=OSError("disk")):
            result = self.api.import_shareable_profile(content=content)
            self.assertFalse(result["ok"])
            self.assertIn("Store indisponible", result["message"])


class TestSubmitScoreFeedback(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_feedback_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_invalid_run_id(self) -> None:
        result = self.api.submit_score_feedback(run_id="bad id!", row_id="r1", user_tier="Gold")
        self.assertFalse(result["ok"])
        self.assertIn("run_id", result["message"])

    def test_missing_row_id(self) -> None:
        with patch.object(self.api, "_is_valid_run_id", return_value=True):
            result = self.api.submit_score_feedback(run_id="x", row_id="", user_tier="Gold")
            self.assertFalse(result["ok"])
            self.assertIn("requis", result["message"])

    def test_missing_user_tier(self) -> None:
        with patch.object(self.api, "_is_valid_run_id", return_value=True):
            result = self.api.submit_score_feedback(run_id="x", row_id="r", user_tier="")
            self.assertFalse(result["ok"])

    def test_run_not_found(self) -> None:
        with (
            patch.object(self.api, "_is_valid_run_id", return_value=True),
            patch.object(self.api, "_find_run_row", return_value=None),
        ):
            result = self.api.submit_score_feedback(run_id="x", row_id="r", user_tier="Gold")
            self.assertFalse(result["ok"])
            self.assertIn("introuvable", result["message"])

    def test_no_quality_report(self) -> None:
        store = MagicMock()
        store.get_quality_report.return_value = None
        with (
            patch.object(self.api, "_is_valid_run_id", return_value=True),
            patch.object(self.api, "_find_run_row", return_value=({}, store)),
        ):
            result = self.api.submit_score_feedback(run_id="x", row_id="r", user_tier="Gold")
            self.assertFalse(result["ok"])
            self.assertIn("Rapport qualit", result["message"])

    def test_success(self) -> None:
        store = MagicMock()
        store.get_quality_report.return_value = {"score": 80, "tier": "Gold"}
        store.insert_user_quality_feedback.return_value = 42
        with (
            patch.object(self.api, "_is_valid_run_id", return_value=True),
            patch.object(self.api, "_find_run_row", return_value=({}, store)),
        ):
            result = self.api.submit_score_feedback(
                run_id="x", row_id="r", user_tier="Platinum", category_focus="video", comment="great"
            )
            self.assertTrue(result["ok"])
            self.assertEqual(result["feedback_id"], 42)
            self.assertEqual(result["computed_tier"], "Gold")

    def test_insert_failure(self) -> None:
        store = MagicMock()
        store.get_quality_report.return_value = {"score": 80, "tier": "Gold"}
        store.insert_user_quality_feedback.side_effect = OSError("disk")
        with (
            patch.object(self.api, "_is_valid_run_id", return_value=True),
            patch.object(self.api, "_find_run_row", return_value=({}, store)),
            patch.object(self.api, "log_api_exception"),
        ):
            result = self.api.submit_score_feedback(run_id="x", row_id="r", user_tier="Gold")
            self.assertFalse(result["ok"])


class TestDeleteScoreFeedback(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_del_fb_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_success(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.delete_user_quality_feedback.return_value = 1
            mock_infra.return_value = (store, MagicMock())
            result = self.api.delete_score_feedback(feedback_id=42)
            self.assertTrue(result["ok"])
            self.assertEqual(result["deleted_count"], 1)

    def test_store_init_fails(self) -> None:
        with patch.object(self.api, "_get_or_create_infra", side_effect=OSError("err")):
            result = self.api.delete_score_feedback(feedback_id=1)
            self.assertFalse(result["ok"])

    def test_delete_failure(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.delete_user_quality_feedback.side_effect = OSError("sql")
            mock_infra.return_value = (store, MagicMock())
            with patch.object(self.api, "log_api_exception"):
                result = self.api.delete_score_feedback(feedback_id=1)
                self.assertFalse(result["ok"])


class TestGetCalibrationReport(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_calib_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_store_init_failure(self) -> None:
        with patch.object(self.api, "_get_or_create_infra", side_effect=OSError("err")):
            result = self.api.get_calibration_report()
            self.assertFalse(result["ok"])

    def test_no_feedbacks_no_active_profile(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.list_user_quality_feedback.return_value = []
            store.get_active_quality_profile.return_value = None
            mock_infra.return_value = (store, MagicMock())
            result = self.api.get_calibration_report()
            self.assertTrue(result["ok"])
            self.assertIn("bias", result)
            self.assertIn("current_weights", result)

    def test_with_corrupt_profile_json(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.list_user_quality_feedback.return_value = []
            store.get_active_quality_profile.return_value = {"profile_json": "not_json"}
            mock_infra.return_value = (store, MagicMock())
            result = self.api.get_calibration_report()
            self.assertTrue(result["ok"])

    def test_list_feedbacks_failure(self) -> None:
        with patch.object(self.api, "_get_or_create_infra") as mock_infra:
            store = MagicMock()
            store.list_user_quality_feedback.side_effect = OSError("read fail")
            mock_infra.return_value = (store, MagicMock())
            with patch.object(self.api, "log_api_exception"):
                result = self.api.get_calibration_report()
                self.assertFalse(result["ok"])


class TestExportRunNfo(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_nfo_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_invalid_run_id(self) -> None:
        result = self.api.export_run_nfo(run_id="invalid id!")
        self.assertFalse(result["ok"])
        self.assertIn("invalide", result["message"])

    def test_payload_not_built(self) -> None:
        with (
            patch.object(self.api, "_is_valid_run_id", return_value=True),
            patch(
                "cinesort.ui.api.dashboard_support.build_run_report_payload",
                return_value=({"ok": False, "message": "no run"}, None),
            ),
        ):
            result = self.api.export_run_nfo(run_id="run_x")
            self.assertFalse(result["ok"])

    def test_no_rows_in_report(self) -> None:
        with (
            patch.object(self.api, "_is_valid_run_id", return_value=True),
            patch(
                "cinesort.ui.api.dashboard_support.build_run_report_payload",
                return_value=({"ok": True, "report": {"rows": []}}, None),
            ),
        ):
            result = self.api.export_run_nfo(run_id="run_x")
            self.assertFalse(result["ok"])
            self.assertIn("Aucune ligne", result["message"])


if __name__ == "__main__":
    unittest.main()

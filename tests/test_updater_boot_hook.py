"""V3-12 — Hook updater au boot + UI Settings + endpoints + badge dashboard."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

REPO_ROOT = Path(__file__).resolve().parent.parent


class UpdaterBootHookTests(unittest.TestCase):
    """V3-12 — checks structurels + endpoints + helpers."""

    def test_app_py_has_boot_hook(self) -> None:
        app = (REPO_ROOT / "app.py").read_text(encoding="utf-8")
        # Reference au systeme updater + au flag auto-check
        self.assertIn("updater", app.lower())
        self.assertIn("auto_check_updates", app)
        # Hook lance en thread daemon (non bloquant)
        self.assertIn("daemon=True", app)
        # Helper de check au boot present
        self.assertIn("_check_updates_in_background", app)

    def test_updater_module_exposes_required_functions(self) -> None:
        from cinesort.app import updater

        funcs = dir(updater)
        # V1-13 helpers
        has_check = any(
            name in funcs
            for name in (
                "check_for_update_async",
                "force_check",
                "check_for_updates",
                "fetch_latest_release",
            )
        )
        self.assertTrue(
            has_check, f"Aucune fonction de check trouvee. Disponibles: {[f for f in funcs if not f.startswith('_')]}"
        )
        # V3-12 helpers explicits
        self.assertIn("default_cache_path", funcs)
        self.assertIn("get_cached_info", funcs)
        self.assertIn("info_to_dict", funcs)

    def test_default_cache_path_under_state_dir(self) -> None:
        from cinesort.app import updater

        with tempfile.TemporaryDirectory() as tmp:
            p = updater.default_cache_path(Path(tmp))
            self.assertEqual(p.parent, Path(tmp))
            self.assertEqual(p.name, updater.CACHE_FILENAME)

    def test_info_to_dict_no_update(self) -> None:
        from cinesort.app import updater

        d = updater.info_to_dict(None, "7.6.0")
        self.assertFalse(d["update_available"])
        self.assertEqual(d["current_version"], "7.6.0")
        self.assertIsNone(d["latest_version"])
        self.assertIsNone(d["release_url"])

    def test_info_to_dict_with_update(self) -> None:
        from cinesort.app import updater

        info = updater.UpdateInfo(
            latest_version="7.7.0",
            current_version="7.6.0",
            release_url="https://example.com/r",
            release_notes_excerpt="Notes",
            download_url="https://example.com/r.exe",
            published_at="2026-06-01T12:00:00Z",
        )
        d = updater.info_to_dict(info, "7.6.0")
        self.assertTrue(d["update_available"])
        self.assertEqual(d["latest_version"], "7.7.0")
        self.assertEqual(d["release_url"], "https://example.com/r")
        self.assertEqual(d["release_notes_short"], "Notes")
        self.assertEqual(d["download_url"], "https://example.com/r.exe")

    def test_force_check_skips_when_no_repo(self) -> None:
        from cinesort.app import updater

        self.assertIsNone(updater.force_check("7.6.0", ""))

    def test_check_for_update_async_skips_when_no_repo(self) -> None:
        from cinesort.app import updater

        self.assertIsNone(updater.check_for_update_async("7.6.0", ""))

    def test_get_cached_info_returns_none_without_cache(self) -> None:
        from cinesort.app import updater

        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(updater.get_cached_info("7.6.0", cache_path=Path(tmp) / "missing.json"))

    def test_get_cached_info_returns_info_when_cache_present(self) -> None:
        from cinesort.app import updater

        payload = {
            "tag_name": "7.7.0",
            "html_url": "https://example.com/r",
            "body": "Notes",
            "published_at": "2026-06-01T12:00:00Z",
            "assets": [],
        }
        with tempfile.TemporaryDirectory() as tmp:
            cache = Path(tmp) / "update_cache.json"
            cache.write_text(json.dumps({"ts": 9_999_999_999, "payload": payload}), encoding="utf-8")
            info = updater.get_cached_info("7.6.0", cache_path=cache)
            self.assertIsNotNone(info)
            self.assertEqual(info.latest_version, "7.7.0")  # type: ignore[union-attr]


class SettingsUpdateDefaultsTests(unittest.TestCase):
    def test_settings_defaults_include_update_keys(self) -> None:
        from cinesort.ui.api.settings_support import apply_settings_defaults

        with tempfile.TemporaryDirectory() as tmp:
            s = apply_settings_defaults(
                {},
                state_dir=Path(tmp),
                default_root="C:\\Films",
                default_state_dir_example=tmp,
                default_collection_folder_name="_Collection",
                default_empty_folders_folder_name="_Vide",
                default_residual_cleanup_folder_name="_Dossier Nettoyage",
                default_probe_backend="auto",
                debug_enabled=False,
            )
        self.assertIn("auto_check_updates", s)
        self.assertIn("update_github_repo", s)
        self.assertIn("update_check_enabled", s)


class CineSortApiUpdateEndpointsTests(unittest.TestCase):
    def test_get_update_info_returns_payload_without_cache(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        with tempfile.TemporaryDirectory() as tmp:
            api = CineSortApi()
            api._state_dir = Path(tmp)
            res = api.get_update_info()
            self.assertTrue(res.get("ok"))
            self.assertIn("data", res)
            self.assertIn("update_available", res["data"])
            self.assertFalse(res["data"]["update_available"])

    def test_check_for_updates_skips_when_no_repo(self) -> None:
        from cinesort.ui.api.cinesort_api import CineSortApi

        with tempfile.TemporaryDirectory() as tmp:
            api = CineSortApi()
            api._state_dir = Path(tmp)
            with mock.patch.object(api, "get_settings", return_value={"update_github_repo": ""}):
                res = api.check_for_updates()
            self.assertFalse(res.get("ok"))
            self.assertIn("data", res)


class FrontendStructureTests(unittest.TestCase):
    """Verifie que les chaines attendues sont presentes dans le frontend."""

    def test_settings_v5_has_update_section(self) -> None:
        # web/views/settings-v5.js : section Mises a jour ajoutee dans le schema
        js = (REPO_ROOT / "web" / "views" / "settings-v5.js").read_text(encoding="utf-8")
        self.assertIn("Mises à jour", js)
        self.assertIn("btnCheckUpdates", js)
        self.assertIn("ckAutoCheckUpdates", js)
        self.assertIn("update_github_repo", js)

    def test_dashboard_app_js_has_update_badge_logic(self) -> None:
        app = (REPO_ROOT / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")
        self.assertIn("_checkUpdateBadge", app)
        self.assertIn("get_update_info", app)
        # V5B-01 : badge MAJ pose via sidebarV5.setUpdateBadge (sidebar dynamique).
        self.assertIn("setUpdateBadge", app)
        sidebar_v5 = (REPO_ROOT / "web" / "dashboard" / "components" / "sidebar-v5.js").read_text(encoding="utf-8")
        self.assertIn("v5-sidebar-update-badge", sidebar_v5)

    def test_dashboard_css_update_styles(self) -> None:
        css = (REPO_ROOT / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")
        self.assertIn(".update-card", css)
        self.assertIn(".update-badge", css)

    def test_shared_css_update_styles(self) -> None:
        css = (REPO_ROOT / "web" / "shared" / "components.css").read_text(encoding="utf-8")
        self.assertIn(".update-card", css)
        self.assertIn(".update-badge", css)


if __name__ == "__main__":
    unittest.main()

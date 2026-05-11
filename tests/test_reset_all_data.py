"""V3-09 — Reset all user data backend + frontend structural."""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, ".")


class ResetBackendTests(unittest.TestCase):
    def test_reset_requires_correct_confirmation(self):
        from cinesort.ui.api.reset_support import reset_all_user_data

        with tempfile.TemporaryDirectory() as tmp:

            class FakeApi:
                def _get_state_dir(self_inner):
                    return tmp

            out = reset_all_user_data(FakeApi(), "wrong")
            self.assertFalse(out["ok"])
            self.assertIn("invalide", out["error"].lower())

    def test_reset_with_correct_confirmation(self):
        from cinesort.ui.api.reset_support import reset_all_user_data

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "userdata"
            state.mkdir()
            (state / "settings.json").write_text(json.dumps({"x": 1}))
            (state / "logs").mkdir()
            (state / "logs" / "app.log").write_text("log content")
            (state / "runs").mkdir()
            (state / "runs" / "20260101_run").mkdir()
            (state / "runs" / "20260101_run" / "plan.jsonl").write_text("{}")

            class FakeApi:
                def _get_state_dir(self_inner):
                    return str(state)

            out = reset_all_user_data(FakeApi(), "RESET")
            self.assertTrue(out["ok"], f"Reset failed: {out.get('error')}")
            self.assertIn("settings.json", out["removed"])
            self.assertIn("runs", out["removed"])
            # Logs preserves
            self.assertNotIn("logs", out["removed"])
            self.assertTrue((state / "logs" / "app.log").exists())
            # Backup cree
            backup = Path(out["backup_path"])
            self.assertTrue(backup.exists())
            self.assertTrue(backup.name.endswith(".zip"))

    def test_reset_missing_state_dir(self):
        from cinesort.ui.api.reset_support import reset_all_user_data

        class FakeApi:
            def _get_state_dir(self_inner):
                return "/path/that/does/not/exist/at/all"

        out = reset_all_user_data(FakeApi(), "RESET")
        self.assertFalse(out["ok"])
        self.assertIn("introuvable", out["error"].lower())

    def test_reset_supports_state_dir_attribute(self):
        """L'API reelle expose `_state_dir` (attribut), pas `_get_state_dir()`."""
        from cinesort.ui.api.reset_support import reset_all_user_data

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "userdata"
            state.mkdir()
            (state / "settings.json").write_text("{}")

            class FakeApi:
                _state_dir = state

            out = reset_all_user_data(FakeApi(), "RESET")
            self.assertTrue(out["ok"])
            self.assertIn("settings.json", out["removed"])

    def test_get_user_data_size(self):
        from cinesort.ui.api.reset_support import get_user_data_size

        with tempfile.TemporaryDirectory() as tmp:
            state = Path(tmp) / "userdata"
            state.mkdir()
            (state / "f1.txt").write_text("a" * 1024)
            (state / "f2.txt").write_text("b" * 2048)

            class FakeApi:
                def _get_state_dir(self_inner):
                    return str(state)

            out = get_user_data_size(FakeApi())
            self.assertEqual(out["items"], 2)
            self.assertGreaterEqual(out["size_mb"], 0)

    def test_get_user_data_size_missing_dir(self):
        from cinesort.ui.api.reset_support import get_user_data_size

        class FakeApi:
            def _get_state_dir(self_inner):
                return "/nope/nope/nope"

        out = get_user_data_size(FakeApi())
        self.assertEqual(out, {"size_mb": 0, "items": 0})


class ResetEndpointTests(unittest.TestCase):
    def test_endpoints_exist_on_api(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        self.assertTrue(callable(getattr(CineSortApi, "reset_all_user_data", None)))
        self.assertTrue(callable(getattr(CineSortApi, "get_user_data_size", None)))


class ResetFrontendTests(unittest.TestCase):
    def test_settings_v5_has_danger_zone(self):
        # Vrai chemin (le prompt mentionnait web/dashboard/views/settings-v5.js
        # qui n'existe pas dans ce repo, le fichier reel est web/views/settings-v5.js).
        js_path = Path("web/views/settings-v5.js")
        self.assertTrue(js_path.exists(), f"Missing {js_path}")
        js = js_path.read_text(encoding="utf-8")
        self.assertIn("danger-zone", js)
        self.assertIn("RESET", js)
        self.assertIn("reset_all_user_data", js)
        self.assertIn("get_user_data_size", js)

    def test_css_danger_styles(self):
        css_path = Path("web/shared/components.css")
        self.assertTrue(css_path.exists(), f"Missing {css_path}")
        css = css_path.read_text(encoding="utf-8")
        self.assertIn(".danger-zone", css)
        self.assertIn(".danger-card", css)
        self.assertIn(".btn--danger", css)


if __name__ == "__main__":
    unittest.main()

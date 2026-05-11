"""Tests plugin hooks post-action — item 9.15.

Couvre :
- Decouverte : dossier avec .py + .bat, vide, inexistant
- Convention nommage : post_scan_hook, any_logger, sans prefixe
- Execution : stdin JSON, env vars, exit 0/1, timeout
- Integration : dispatch conditionnel, plugins_enabled toggle
- Settings : defaults, round-trip
- UI : toggle present dans settings.js
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.app.plugin_hooks import (
    discover_plugins,
    _events_from_name,
    _run_plugin,
    HOOK_EVENTS,
)


# ---------------------------------------------------------------------------
# Decouverte (3 tests)
# ---------------------------------------------------------------------------


class DiscoverPluginsTests(unittest.TestCase):
    """Tests de la decouverte des plugins dans le dossier."""

    def test_py_and_bat_detected(self) -> None:
        """Dossier avec .py + .bat → detectes."""
        tmp = tempfile.mkdtemp(prefix="cinesort_plugins_")
        try:
            (Path(tmp) / "hook_a.py").write_text("# plugin", encoding="utf-8")
            (Path(tmp) / "hook_b.bat").write_text("@echo off", encoding="utf-8")
            (Path(tmp) / "readme.txt").write_text("not a plugin", encoding="utf-8")
            plugins = discover_plugins(Path(tmp))
            self.assertEqual(len(plugins), 2)
            names = {p["name"] for p in plugins}
            self.assertIn("hook_a.py", names)
            self.assertIn("hook_b.bat", names)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_empty_dir(self) -> None:
        """Dossier vide → 0 plugin."""
        tmp = tempfile.mkdtemp(prefix="cinesort_plugins_")
        try:
            plugins = discover_plugins(Path(tmp))
            self.assertEqual(len(plugins), 0)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_nonexistent_dir(self) -> None:
        """Dossier inexistant → 0 plugin, pas de crash."""
        plugins = discover_plugins(Path("/nonexistent/plugins/xyz"))
        self.assertEqual(len(plugins), 0)


# ---------------------------------------------------------------------------
# Convention nommage (3 tests)
# ---------------------------------------------------------------------------


class NamingConventionTests(unittest.TestCase):
    """Tests de la convention de nommage des fichiers plugin."""

    def test_post_scan_prefix(self) -> None:
        self.assertEqual(_events_from_name("post_scan_discord"), ["post_scan"])

    def test_any_prefix(self) -> None:
        events = _events_from_name("any_logger")
        self.assertEqual(events, sorted(HOOK_EVENTS))

    def test_no_prefix_matches_all(self) -> None:
        events = _events_from_name("my_webhook")
        self.assertEqual(events, sorted(HOOK_EVENTS))

    def test_post_apply_prefix(self) -> None:
        self.assertEqual(_events_from_name("post_apply_webhook"), ["post_apply"])

    def test_post_undo_prefix(self) -> None:
        self.assertEqual(_events_from_name("post_undo_cleanup"), ["post_undo"])


# ---------------------------------------------------------------------------
# Execution (4 tests)
# ---------------------------------------------------------------------------


class PluginExecutionTests(unittest.TestCase):
    """Tests d'execution de scripts plugin."""

    def test_stdin_json_received(self) -> None:
        """Le plugin recoit le JSON sur stdin."""
        tmp = tempfile.mkdtemp(prefix="cinesort_plugin_exec_")
        try:
            out_file = Path(tmp) / "output.json"
            script = Path(tmp) / "check_stdin.py"
            script.write_text(
                f"import sys, json\ndata = json.load(sys.stdin)\nopen(r'{out_file}', 'w').write(json.dumps(data))\n",
                encoding="utf-8",
            )
            _run_plugin(script, "post_scan", {"run_id": "test123", "ts": 1.0, "data": {"rows": 5}}, timeout_s=10)
            self.assertTrue(out_file.exists())
            content = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(content["event"], "post_scan")
            self.assertEqual(content["run_id"], "test123")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_env_vars_present(self) -> None:
        """Le plugin recoit les env vars CINESORT_EVENT et CINESORT_RUN_ID."""
        tmp = tempfile.mkdtemp(prefix="cinesort_plugin_env_")
        try:
            out_file = Path(tmp) / "env.json"
            script = Path(tmp) / "check_env.py"
            script.write_text(
                f"import os, json\n"
                f"open(r'{out_file}', 'w').write(json.dumps({{'event': os.environ.get('CINESORT_EVENT'), 'run_id': os.environ.get('CINESORT_RUN_ID')}}))\n",
                encoding="utf-8",
            )
            _run_plugin(script, "post_apply", {"run_id": "run42", "ts": 1.0, "data": {}}, timeout_s=10)
            self.assertTrue(out_file.exists())
            content = json.loads(out_file.read_text(encoding="utf-8"))
            self.assertEqual(content["event"], "post_apply")
            self.assertEqual(content["run_id"], "run42")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_exit_nonzero_no_crash(self) -> None:
        """Plugin exit code 1 → log warning, pas de crash."""
        tmp = tempfile.mkdtemp(prefix="cinesort_plugin_err_")
        try:
            script = Path(tmp) / "fail.py"
            script.write_text("import sys; sys.exit(1)\n", encoding="utf-8")
            # Ne doit pas lever d'exception
            _run_plugin(script, "post_scan", {"run_id": "x", "ts": 1.0, "data": {}}, timeout_s=10)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_timeout_no_crash(self) -> None:
        """Plugin qui bloque → timeout, pas de crash."""
        tmp = tempfile.mkdtemp(prefix="cinesort_plugin_to_")
        try:
            script = Path(tmp) / "hang.py"
            script.write_text("import time; time.sleep(60)\n", encoding="utf-8")
            _run_plugin(script, "post_scan", {"run_id": "x", "ts": 1.0, "data": {}}, timeout_s=1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# Settings (2 tests)
# ---------------------------------------------------------------------------


class PluginSettingsTests(unittest.TestCase):
    """Tests des settings plugins."""

    def test_defaults(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        # Utiliser un state_dir temporaire vide pour tester les vrais defaults
        tmp = tempfile.mkdtemp(prefix="cinesort_plug_def_")
        try:
            api = backend.CineSortApi()
            api._state_dir = Path(tmp)
            s = api.get_settings()
            self.assertFalse(s.get("plugins_enabled"))
            self.assertEqual(s.get("plugins_timeout_s"), 30)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_round_trip(self) -> None:
        import cinesort.ui.api.cinesort_api as backend

        tmp = tempfile.mkdtemp(prefix="cinesort_plugin_s_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "plugins_enabled": True,
                    "plugins_timeout_s": 15,
                }
            )
            s = api.get_settings()
            self.assertTrue(s["plugins_enabled"])
            self.assertEqual(s["plugins_timeout_s"], 15)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


# ---------------------------------------------------------------------------
# UI (1 test)
# ---------------------------------------------------------------------------


class PluginUiTests(unittest.TestCase):
    """Tests presence UI plugins."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.settings_js = (root / "web" / "views" / "settings.js").read_text(encoding="utf-8")
        cls.index_html = (root / "web" / "index.html").read_text(encoding="utf-8")

    def test_settings_toggle_present(self) -> None:
        self.assertIn("plugins_enabled", self.settings_js)
        self.assertIn("plugins_timeout_s", self.settings_js)
        self.assertIn("ckPluginsEnabled", self.index_html)
        self.assertIn("pluginsTimeout", self.index_html)


if __name__ == "__main__":
    unittest.main()

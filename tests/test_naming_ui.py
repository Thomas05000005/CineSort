"""Tests Phases G+H — UI des profils de renommage.

Couvre :
- Structure HTML : section naming dans settings, dropdown preset, inputs template, preview zone
- JS settings : presets connus, hookNamingEvents, gatherSettingsFromForm inclut naming
- Dashboard status : profil actif affiche
- HTTP : endpoints naming via REST
"""

from __future__ import annotations

import json
import shutil
import tempfile
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from typing import Any, Dict

import cinesort.ui.api.cinesort_api as backend
from cinesort.infra.rest_server import RestApiServer


def _find_free_port() -> int:
    import socket

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Structure HTML desktop
# ---------------------------------------------------------------------------


class NamingHtmlStructureTests(unittest.TestCase):
    """Tests de structure HTML pour la section naming dans les settings."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.html = (Path(__file__).resolve().parents[1] / "web" / "index.html").read_text(encoding="utf-8")

    def test_preset_dropdown_present(self) -> None:
        self.assertIn('id="selNamingPreset"', self.html)

    def test_preset_has_5_options(self) -> None:
        for preset in ("default", "plex", "jellyfin", "quality", "custom"):
            self.assertIn(f'value="{preset}"', self.html, f"Option preset {preset} manquante")

    def test_movie_template_input(self) -> None:
        self.assertIn('id="inNamingMovie"', self.html)

    def test_tv_template_input(self) -> None:
        self.assertIn('id="inNamingTv"', self.html)

    def test_preview_zone(self) -> None:
        self.assertIn('id="namingPreview"', self.html)

    def test_variables_list_displayed(self) -> None:
        self.assertIn("{title}", self.html)
        self.assertIn("{tmdb_tag}", self.html)
        self.assertIn("{resolution}", self.html)

    def test_section_eyebrow(self) -> None:
        self.assertIn("Profil de renommage", self.html)


# ---------------------------------------------------------------------------
# Structure JS desktop
# ---------------------------------------------------------------------------


class NamingJsStructureTests(unittest.TestCase):
    """Tests de structure JS pour la logique naming dans settings.js."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = (Path(__file__).resolve().parents[1] / "web" / "views" / "settings.js").read_text(encoding="utf-8")

    def test_naming_presets_defined(self) -> None:
        self.assertIn("_NAMING_PRESETS", self.js)
        for preset in ("default", "plex", "jellyfin", "quality", "custom"):
            self.assertIn(f"{preset}:", self.js)

    def test_load_naming_preset(self) -> None:
        self.assertIn("_loadNamingPreset", self.js)

    def test_hook_naming_events(self) -> None:
        self.assertIn("_hookNamingEvents", self.js)

    def test_on_preset_change(self) -> None:
        self.assertIn("_onPresetChange", self.js)

    def test_gather_includes_naming(self) -> None:
        """gatherSettingsFromForm inclut les champs naming."""
        self.assertIn("naming_preset", self.js)
        self.assertIn("naming_movie_template", self.js)
        self.assertIn("naming_tv_template", self.js)

    def test_preview_debounce(self) -> None:
        self.assertIn("_namingPreviewTimer", self.js)
        self.assertIn("300", self.js)

    def test_preview_calls_api(self) -> None:
        self.assertIn("preview_naming_template", self.js)

    def test_readonly_toggle(self) -> None:
        """Les inputs sont readOnly quand preset != custom."""
        self.assertIn("readOnly", self.js)

    def test_fetch_naming_preview(self) -> None:
        self.assertIn("_fetchNamingPreview", self.js)


# ---------------------------------------------------------------------------
# CSS naming preview
# ---------------------------------------------------------------------------


class NamingCssTests(unittest.TestCase):
    """Tests CSS pour le naming preview."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.css = (Path(__file__).resolve().parents[1] / "web" / "styles.css").read_text(encoding="utf-8")

    def test_naming_preview_class(self) -> None:
        self.assertIn(".naming-preview", self.css)

    def test_naming_preview_error_class(self) -> None:
        self.assertIn(".naming-preview-error", self.css)


# ---------------------------------------------------------------------------
# Dashboard status — profil actif
# ---------------------------------------------------------------------------


@unittest.skip("V5C-01: dashboard/views/status.js supprime — adaptation v5 deferee a V5C-03")
class DashboardNamingTests(unittest.TestCase):
    """Tests du profil actif dans le dashboard status."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.status_js = (Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "status.js").read_text(
            encoding="utf-8"
        )

    def test_shows_naming_preset(self) -> None:
        self.assertIn("naming_preset", self.status_js)

    def test_shows_naming_label(self) -> None:
        """Le label du preset est affiche (Standard, Plex, etc.)."""
        for label in ("Standard", "Plex", "Jellyfin", "Qualite", "Personnalise"):
            self.assertIn(label, self.status_js, f"Label {label} manquant dans status.js")

    def test_shows_custom_template(self) -> None:
        """En mode custom, le template est affiche."""
        self.assertIn("naming_movie_template", self.status_js)


# ---------------------------------------------------------------------------
# HTTP — endpoints naming via REST
# ---------------------------------------------------------------------------


class NamingHttpTests(unittest.TestCase):
    """Tests HTTP des endpoints naming."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="cinesort_naming_ui_")
        cls.root = Path(cls._tmp) / "root"
        cls.state_dir = Path(cls._tmp) / "state"
        cls.root.mkdir()
        cls.state_dir.mkdir()

        cls.api = backend.CineSortApi()
        cls.api.settings.save_settings(
            {
                "root": str(cls.root),
                "state_dir": str(cls.state_dir),
                "tmdb_enabled": False,
            }
        )

        cls.port = _find_free_port()
        cls.token = "naming-ui-test"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _post(self, path: str, body: Any = None) -> tuple[int, Dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"}
        data = json.dumps(body).encode() if body is not None else b"{}"
        conn.request("POST", path, body=data, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read().decode("utf-8")
        conn.close()
        return status, json.loads(raw)

    def test_preview_endpoint_via_rest(self) -> None:
        status, data = self._post("/api/preview_naming_template", {"template": "{title} ({year})"})
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(data["result"], "Inception (2010)")

    def test_presets_endpoint_via_rest(self) -> None:
        status, data = self._post("/api/get_naming_presets")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertEqual(len(data["presets"]), 5)

    def test_save_naming_preset_via_rest(self) -> None:
        """Sauvegarder un preset via save_settings et verifier.

        Issue #84 PR 10 : routes get/save_settings sont sur SettingsFacade.
        """
        # Charger settings actuels
        _, settings = self._post("/api/settings/get_settings")
        settings["naming_preset"] = "jellyfin"
        _, save_result = self._post("/api/settings/save_settings", {"settings": settings})
        # Recharger
        _, reloaded = self._post("/api/settings/get_settings")
        self.assertEqual(reloaded.get("naming_preset"), "jellyfin")
        self.assertIn("resolution", reloaded.get("naming_movie_template", ""))


if __name__ == "__main__":
    unittest.main()

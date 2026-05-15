"""Tests Phase 2 — Shell SPA du dashboard distant.

Couvre :
- Fichiers statiques Phase 2 (CSS, JS modules, font, HTML complet)
- Types MIME corrects (css, js, ttf)
- Structure HTML du shell SPA (vues, login form, sidebar, script module)
- Login flow HTTP (token valide → 200, token invalide → 401)
- Garde auth : les fichiers statiques sont accessibles sans token
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


class DashboardShellHttpTests(unittest.TestCase):
    """Tests HTTP des fichiers statiques Phase 2."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="cinesort_dash_shell_")
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
        cls.token = "shell-test-token"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _get(self, path: str) -> tuple[int, bytes, dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("GET", path)
        resp = conn.getresponse()
        status = resp.status
        headers = {k.lower(): v for k, v in resp.getheaders()}
        body = resp.read()
        conn.close()
        return status, body, headers

    def _post(self, path: str, body: Any = None, token: str | None = None) -> tuple[int, Dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else b"{}"
        conn.request("POST", path, body=data, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read().decode("utf-8")
        conn.close()
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, {"_raw": raw}

    # --- Fichiers statiques CSS/JS/Font ---

    def test_styles_css_served(self) -> None:
        """Le CSS du dashboard est accessible et a le bon MIME type."""
        status, body, headers = self._get("/dashboard/styles.css")
        self.assertEqual(status, 200)
        self.assertIn("text/css", headers.get("content-type", ""))
        self.assertIn(b"CinemaLux", body)

    def test_app_js_served(self) -> None:
        """Le bootstrap JS est accessible."""
        status, body, headers = self._get("/dashboard/app.js")
        self.assertEqual(status, 200)
        ct = headers.get("content-type", "")
        # JavaScript MIME : application/javascript ou text/javascript
        self.assertTrue(
            "javascript" in ct or "text/javascript" in ct or "application/x-javascript" in ct,
            f"Unexpected content-type: {ct}",
        )
        self.assertIn(b"startRouter", body)

    def test_core_modules_served(self) -> None:
        """Les modules core/ sont accessibles."""
        for module in ("dom.js", "state.js", "api.js", "router.js"):
            status, body, _ = self._get(f"/dashboard/core/{module}")
            self.assertEqual(status, 200, f"core/{module} should return 200")
            self.assertGreater(len(body), 50, f"core/{module} should not be empty")

    def test_login_view_served(self) -> None:
        """La vue login est accessible."""
        status, body, _ = self._get("/dashboard/views/login.js")
        self.assertEqual(status, 200)
        self.assertIn(b"initLogin", body)

    def test_font_served_with_correct_mime(self) -> None:
        """La police Manrope est servie avec le bon MIME type.

        V3-02 (v7.7.0) : la police a ete deduplique vers web/shared/fonts/
        et est maintenant servie via /shared/fonts/* (handler _serve_shared_file).
        """
        status, body, headers = self._get("/shared/fonts/Manrope-Variable.ttf")
        self.assertEqual(status, 200)
        ct = headers.get("content-type", "")
        self.assertIn("font", ct, f"Font should have font/* MIME type, got: {ct}")
        # Verifier que c'est bien un fichier binaire non vide
        self.assertGreater(len(body), 1000)

    def test_static_files_accessible_without_auth(self) -> None:
        """Les fichiers statiques sont publics (pas de Bearer requis)."""
        status, _, _ = self._get("/dashboard/styles.css")
        self.assertEqual(status, 200)

    # --- Structure HTML ---

    def test_index_html_has_login_form(self) -> None:
        """L'index contient le formulaire de login."""
        status, body, _ = self._get("/dashboard/index.html")
        self.assertEqual(status, 200)
        html = body.decode("utf-8")
        self.assertIn('id="loginForm"', html)
        self.assertIn('id="loginToken"', html)
        self.assertIn('id="loginPersist"', html)
        self.assertIn('type="password"', html)

    @unittest.skip(
        "V5B-01: sidebar v5 rendue dynamiquement par sidebar-v5.js, plus de data-route statiques dans index.html"
    )
    def test_index_html_has_sidebar_nav(self) -> None:
        pass

    def test_index_html_has_view_placeholders(self) -> None:
        """L'index contient les placeholder de chaque vue."""
        _, body, _ = self._get("/dashboard/index.html")
        html = body.decode("utf-8")
        for view_id in (
            "view-login",
            "view-status",
            "view-library",
            "view-jellyfin",
            "view-logs",
            "view-quality",
            "view-settings",
        ):
            self.assertIn(f'id="{view_id}"', html, f"Vue {view_id} manquante")

    def test_index_html_loads_app_js_as_module(self) -> None:
        """Le script app.js est charge en type=module."""
        _, body, _ = self._get("/dashboard/index.html")
        html = body.decode("utf-8")
        self.assertIn('type="module"', html)
        self.assertIn('src="./app.js"', html)

    def test_index_html_links_css(self) -> None:
        """Le HTML reference le CSS."""
        _, body, _ = self._get("/dashboard/index.html")
        html = body.decode("utf-8")
        self.assertIn('href="./styles.css"', html)

    # --- Login flow HTTP ---

    def test_login_valid_token_gets_settings(self) -> None:
        """Un token valide permet d'appeler get_settings (flow de login).

        Issue #84 PR 10 : path facade /api/settings/get_settings.
        """
        status, data = self._post("/api/settings/get_settings", body={}, token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("root", data)

    def test_login_invalid_token_returns_401(self) -> None:
        """Un mauvais token retourne 401."""
        status, data = self._post("/api/settings/get_settings", body={}, token="wrong-token")
        self.assertEqual(status, 401)
        self.assertFalse(data["ok"])

    def test_health_accessible_for_version_check(self) -> None:
        """GET /api/health est accessible sans auth (utilise par le login)."""
        status, body, _ = self._get("/api/health")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("version", data)


class DashboardShellStructureTests(unittest.TestCase):
    """Tests de structure des fichiers du dashboard (sans serveur HTTP)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.dashboard_root = Path(__file__).resolve().parents[1] / "web" / "dashboard"

    def test_all_expected_files_exist(self) -> None:
        """Tous les fichiers Phase 2 existent."""
        expected = [
            "index.html",
            "styles.css",
            "app.js",
            "core/dom.js",
            "core/state.js",
            "core/api.js",
            "core/router.js",
            "views/login.js",
        ]
        for f in expected:
            self.assertTrue((self.dashboard_root / f).exists(), f"Fichier manquant : web/dashboard/{f}")
        # V3-02 (v7.7.0) : la police est partagee dans web/shared/fonts/
        shared_root = self.dashboard_root.parent / "shared"
        self.assertTrue(
            (shared_root / "fonts" / "Manrope-Variable.ttf").exists(), "Police Manrope manquante dans web/shared/fonts/"
        )

    def test_css_has_cinemalux_tokens(self) -> None:
        """Le CSS contient les tokens CinemaLux essentiels."""
        css = (self.dashboard_root / "styles.css").read_text(encoding="utf-8")
        for token in (
            "--bg-base",
            "--accent",
            "--bg-glass",
            "--text-primary",
            "--radius-sm",
            "--shadow",
            "backdrop-filter",
        ):
            self.assertIn(token, css, f"Token CSS manquant : {token}")

    def test_css_has_responsive_breakpoints(self) -> None:
        """Le CSS contient les media queries responsive."""
        css = (self.dashboard_root / "styles.css").read_text(encoding="utf-8")
        self.assertIn("max-width: 1023px", css, "Breakpoint tablette manquant")
        self.assertIn("max-width: 767px", css, "Breakpoint mobile manquant")
        self.assertIn("prefers-reduced-motion", css, "Media query reduced motion manquante")

    def test_js_modules_use_export(self) -> None:
        """Les modules JS utilisent export (ES modules)."""
        for module in ("core/dom.js", "core/state.js", "core/api.js", "core/router.js", "views/login.js"):
            content = (self.dashboard_root / module).read_text(encoding="utf-8")
            self.assertIn("export", content, f"{module} devrait utiliser des exports ES module")

    def test_api_js_handles_401_redirect(self) -> None:
        """api.js gere le 401 avec redirect vers login."""
        api_js = (self.dashboard_root / "core" / "api.js").read_text(encoding="utf-8")
        self.assertIn("401", api_js)
        self.assertIn("#/login", api_js)
        self.assertIn("clearToken", api_js)

    def test_api_js_handles_429(self) -> None:
        """api.js gere le 429 (rate limiting)."""
        api_js = (self.dashboard_root / "core" / "api.js").read_text(encoding="utf-8")
        self.assertIn("429", api_js)

    def test_router_has_auth_guard(self) -> None:
        """Le router a un guard d'authentification."""
        router_js = (self.dashboard_root / "core" / "router.js").read_text(encoding="utf-8")
        self.assertIn("requireAuth", router_js)
        self.assertIn("hasToken", router_js)

    def test_state_has_token_management(self) -> None:
        """state.js gere get/set/clear token avec les deux storages."""
        state_js = (self.dashboard_root / "core" / "state.js").read_text(encoding="utf-8")
        self.assertIn("sessionStorage", state_js)
        self.assertIn("localStorage", state_js)
        self.assertIn("getToken", state_js)
        self.assertIn("setToken", state_js)
        self.assertIn("clearToken", state_js)

    def test_state_has_polling_management(self) -> None:
        """state.js gere les timers de polling avec pause sur hidden."""
        state_js = (self.dashboard_root / "core" / "state.js").read_text(encoding="utf-8")
        self.assertIn("startPolling", state_js)
        self.assertIn("stopPolling", state_js)
        self.assertIn("document.hidden", state_js)

    def test_login_view_handles_persist_checkbox(self) -> None:
        """login.js gere la checkbox Rester connecte."""
        login_js = (self.dashboard_root / "views" / "login.js").read_text(encoding="utf-8")
        self.assertIn("loginPersist", login_js)
        self.assertIn("isPersistent", login_js)

    def test_dom_js_has_escape_html(self) -> None:
        """dom.js exporte escapeHtml pour eviter les XSS."""
        dom_js = (self.dashboard_root / "core" / "dom.js").read_text(encoding="utf-8")
        self.assertIn("escapeHtml", dom_js)
        # Verifie que les 4 entites sont echappees
        self.assertIn("&amp;", dom_js)
        self.assertIn("&lt;", dom_js)
        self.assertIn("&gt;", dom_js)
        self.assertIn("&quot;", dom_js)

    def test_app_js_registers_all_routes(self) -> None:
        """app.js enregistre toutes les routes attendues."""
        app_js = (self.dashboard_root / "app.js").read_text(encoding="utf-8")
        # Routes V4 : 8 onglets + login + routes legacy (runs, review)
        for route in ("/login", "/status", "/library", "/quality", "/jellyfin", "/logs", "/settings"):
            self.assertIn(f'"{route}"', app_js, f"Route {route} non enregistree dans app.js")

    def test_api_js_exposes_settings_cache_wrapper(self) -> None:
        """V2-B / H13 : api.js expose cachedGetSettings() + invalidateSettingsCache()
        pour deduper les 4+ appels concurrents au boot du dashboard."""
        api_js = (self.dashboard_root / "core" / "api.js").read_text(encoding="utf-8")
        self.assertIn("export function cachedGetSettings", api_js, "cachedGetSettings doit etre exporte (V2-B)")
        self.assertIn(
            "export function invalidateSettingsCache", api_js, "invalidateSettingsCache doit etre exporte (V2-B)"
        )
        # Le wrapper doit dedupliquer les requetes paralleles via promise singleton
        self.assertIn("_settingsInFlight", api_js, "cachedGetSettings doit utiliser un singleton in-flight")
        # Le cache doit etre invalide automatiquement apres save_settings
        self.assertIn("save_settings", api_js)
        self.assertIn("invalidateSettingsCache()", api_js, "save_settings doit invalider le cache automatiquement")

    def test_app_js_uses_cached_get_settings_at_boot(self) -> None:
        """V2-B / H13 : les 4 sites du boot doivent utiliser cachedGetSettings,
        pas apiPost('get_settings'). Reduit la latence boot de ~200ms (4x50ms)."""
        app_js = (self.dashboard_root / "app.js").read_text(encoding="utf-8")
        self.assertIn("cachedGetSettings", app_js, "app.js doit importer/utiliser cachedGetSettings")
        # Compte les apiPost('get_settings') restants : ne doit pas y en avoir
        # dans les fonctions de boot (theme, sidebar, notif, demo).
        bare_calls = app_js.count('apiPost("get_settings"')
        self.assertEqual(
            bare_calls,
            0,
            f"app.js ne doit plus appeler apiPost('get_settings') directement "
            f"(trouve {bare_calls}, attendu 0). Utiliser cachedGetSettings().",
        )


if __name__ == "__main__":
    unittest.main()

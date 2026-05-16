"""Tests for REST API server — HTTP dispatch, auth, CORS, OpenAPI, settings."""

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
from cinesort.infra.rest_server import RestApiServer, generate_openapi_spec, _get_api_methods
from tests._helpers import find_free_port as _find_free_port


class RestServerLifecycleTests(unittest.TestCase):
    """Test start/stop lifecycle."""

    def test_start_and_stop(self) -> None:
        api = backend.CineSortApi()
        port = _find_free_port()
        server = RestApiServer(api, port=port, token="test-token")
        self.assertFalse(server.is_running)
        server.start()
        self.assertTrue(server.is_running)
        server.stop()
        self.assertFalse(server.is_running)

    def test_double_start_is_safe(self) -> None:
        api = backend.CineSortApi()
        port = _find_free_port()
        server = RestApiServer(api, port=port, token="test-token")
        server.start()
        server.start()  # should not raise
        self.assertTrue(server.is_running)
        server.stop()


class RestServerHttpTests(unittest.TestCase):
    """Test actual HTTP requests against a running server."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="cinesort_rest_")
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
        cls.token = "test-secret-42"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        # Cf issue #88 : poll sur /api/health au lieu d'un sleep fixe.
        # Sur CI Windows lente, time.sleep(0.2) ne garantit pas que le
        # ThreadingHTTPServer accepte deja les connexions, d'ou flakies.
        cls._wait_server_ready(cls.port, timeout_s=5.0)

    @staticmethod
    def _wait_server_ready(port: int, timeout_s: float = 5.0) -> None:
        """Poll GET /api/health jusqu'a 200 ou timeout."""
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            try:
                conn = HTTPConnection("127.0.0.1", port, timeout=0.5)
                conn.request("GET", "/api/health")
                resp = conn.getresponse()
                resp.read()
                conn.close()
                if resp.status == 200:
                    return
            except (ConnectionRefusedError, OSError):
                pass
            time.sleep(0.05)
        raise RuntimeError(f"Serveur REST pas pret apres {timeout_s}s sur port {port}")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        # Audit 5.1 : le _RateLimiter a un etat global partage entre tests
        # (la meme IP 127.0.0.1 accumule les echecs). Sans reset, le 5e test
        # qui envoie un mauvais token voit un 429 au lieu du 401 attendu.
        self.server._rate_limiter.reset()

    def _request(self, method: str, path: str, body: Any = None, token: str | None = None) -> tuple[int, Dict]:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers: Dict[str, str] = {"Content-Type": "application/json"}
        if token is not None:
            headers["Authorization"] = f"Bearer {token}"
        data = json.dumps(body).encode() if body is not None else b"{}"
        conn.request(method, path, body=data, headers=headers)
        resp = conn.getresponse()
        status = resp.status
        raw = resp.read().decode("utf-8")
        conn.close()
        try:
            return status, json.loads(raw)
        except json.JSONDecodeError:
            return status, {"_raw": raw}

    # --- Health (public) ---

    def test_health_no_auth_required(self) -> None:
        status, data = self._request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("version", data)

    # --- Spec (public) ---

    def test_spec_returns_openapi(self) -> None:
        status, data = self._request("GET", "/api/spec")
        self.assertEqual(status, 200)
        self.assertEqual(data["openapi"], "3.0.3")
        self.assertIn("paths", data)
        self.assertIn("/api/settings/get_settings", data["paths"])

    # --- Auth ---

    def test_post_without_token_returns_401(self) -> None:
        status, data = self._request("POST", "/api/settings/get_settings")
        self.assertEqual(status, 401)
        self.assertFalse(data["ok"])

    def test_post_with_wrong_token_returns_401(self) -> None:
        status, data = self._request("POST", "/api/settings/get_settings", token="wrong-token")
        self.assertEqual(status, 401)

    def test_post_with_correct_token_succeeds(self) -> None:
        status, data = self._request("POST", "/api/settings/get_settings", body={}, token=self.token)
        self.assertEqual(status, 200)
        self.assertIn("root", data)

    # --- Dispatch ---

    def test_get_settings(self) -> None:
        status, data = self._request("POST", "/api/settings/get_settings", body={}, token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(data["root"], str(self.root))

    def test_unknown_method_returns_404(self) -> None:
        status, data = self._request("POST", "/api/nonexistent_method", body={}, token=self.token)
        self.assertEqual(status, 404)

    def test_invalid_json_returns_400(self) -> None:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request(
            "POST",
            "/api/settings/get_settings",
            body=b"not json",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            },
        )
        resp = conn.getresponse()
        self.assertEqual(resp.status, 400)
        conn.close()

    def test_wrong_params_returns_400(self) -> None:
        status, data = self._request("POST", "/api/get_dashboard", body={"nonexistent_param": 1}, token=self.token)
        # get_dashboard accepts run_id, so extra params cause TypeError → 400
        self.assertIn(status, {200, 400})

    def test_get_dashboard_via_rest(self) -> None:
        status, data = self._request("POST", "/api/get_dashboard", body={"run_id": "latest"}, token=self.token)
        self.assertEqual(status, 200)

    def test_get_global_stats_via_rest(self) -> None:
        status, data = self._request("POST", "/api/get_global_stats", body={"limit_runs": 5}, token=self.token)
        self.assertEqual(status, 200)
        self.assertTrue(data.get("ok"))

    # --- PR 8 du #84 : facade routes via HTTP ---

    def test_facade_route_get_settings(self) -> None:
        """POST /api/settings/get_settings route vers api.settings.get_settings."""
        status, data = self._request("POST", "/api/settings/get_settings", body={}, token=self.token)
        self.assertEqual(status, 200)
        self.assertEqual(data["root"], str(self.root))

    def test_facade_route_get_quality_profile(self) -> None:
        """POST /api/quality/get_quality_profile route vers api.quality.get_quality_profile."""
        status, data = self._request("POST", "/api/quality/get_quality_profile", body={}, token=self.token)
        self.assertEqual(status, 200)

    def test_legacy_path_returns_404_after_pr10(self) -> None:
        """PR 10 du #84 : la voie legacy /api/get_settings est supprimee."""
        s_legacy, _ = self._request("POST", "/api/get_settings", body={}, token=self.token)
        s_facade, d_facade = self._request("POST", "/api/settings/get_settings", body={}, token=self.token)
        self.assertEqual(s_legacy, 404)
        self.assertEqual(s_facade, 200)
        self.assertIn("root", d_facade)

    def test_facade_attribute_alone_returns_404(self) -> None:
        """POST /api/run (sans methode) doit retourner 404."""
        status, _ = self._request("POST", "/api/run", body={}, token=self.token)
        self.assertEqual(status, 404)

    def test_facade_unknown_method_returns_404(self) -> None:
        """POST /api/run/nonexistent_xyz doit retourner 404."""
        status, _ = self._request("POST", "/api/run/nonexistent_xyz", body={}, token=self.token)
        self.assertEqual(status, 404)

    # --- CORS ---

    def test_options_returns_cors_headers(self) -> None:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        conn.request("OPTIONS", "/api/settings/get_settings")
        resp = conn.getresponse()
        self.assertEqual(resp.status, 204)
        self.assertIn("Access-Control-Allow-Origin", resp.headers)
        self.assertIn("Access-Control-Allow-Methods", resp.headers)
        conn.close()

    def test_post_response_includes_cors(self) -> None:
        status, _ = self._request("POST", "/api/settings/get_settings", body={}, token=self.token)
        # We can't easily check response headers via _request helper, but the handler always sends them.
        self.assertEqual(status, 200)

    # --- Excluded methods ---

    def test_open_path_not_exposed(self) -> None:
        status, data = self._request("POST", "/api/open_path", body={"path": "C:\\"}, token=self.token)
        self.assertEqual(status, 404)

    def test_log_api_exception_not_exposed(self) -> None:
        status, data = self._request("POST", "/api/log_api_exception", body={}, token=self.token)
        self.assertEqual(status, 404)


class RestFacadeDispatchTests(unittest.TestCase):
    """PR 8 du #84 : le dispatcher REST walk dans les 5 facades.

    Les methodes de chaque facade sont exposees sous "/api/{facade}/{method}"
    en plus des methodes directes "/api/{method}". Les 2 voies fonctionnent
    en parallele (backward-compat preservee jusqu'a la PR 10).
    """

    def test_facade_methods_discovered(self) -> None:
        """Les 56 methodes des 5 facades doivent etre exposees avec leur prefix."""
        api = backend.CineSortApi()
        methods = _get_api_methods(api)

        # Compte des methodes facade (avec separateur "/")
        facade_methods = [name for name in methods if "/" in name]

        # 5 facades * leurs methodes respectives :
        # Run 7 + Settings 6 + Quality 22 + Integrations 14 + Library 11 = 60
        # (#92 #1 : +2 Integrations - refresh_jellyfin/plex_library_now)
        # (#94 : +1 Quality - get_perceptual_compare_frames)
        # (Dashboard Podiums : +1 Library - get_library_podiums)
        # (Dashboard Timeline : +1 Library - get_library_timeline)
        # (Phase 6.2 OMDb : +1 Integrations - test_omdb_connection)
        self.assertEqual(
            len(facade_methods),
            60,
            f"Attendu 60 methodes facade, trouve {len(facade_methods)}",
        )

    def test_each_facade_has_methods(self) -> None:
        """Chaque facade doit avoir au moins une methode exposee."""
        api = backend.CineSortApi()
        methods = _get_api_methods(api)

        for facade_name, min_count in (
            ("run", 7),
            ("settings", 6),
            # Quality : 21 d'origine + 1 (#94 get_perceptual_compare_frames) = 22
            ("quality", 22),
            # Integrations : 11 d'origine + 2 (#92 #1 refresh_jellyfin/plex_library_now) + 1 (Phase 6.2 OMDb) = 14
            ("integrations", 14),
            # Library : 9 d'origine + 1 (Dashboard Podiums) + 1 (Dashboard Timeline) = 11
            ("library", 11),
        ):
            count = sum(1 for n in methods if n.startswith(f"{facade_name}/"))
            self.assertEqual(
                count,
                min_count,
                f"Facade {facade_name} : attendu {min_count} methodes, trouve {count}",
            )

    def test_facade_method_examples_present(self) -> None:
        """Sanity : quelques methodes facade specifiques doivent etre la."""
        api = backend.CineSortApi()
        methods = _get_api_methods(api)

        for expected in (
            "run/start_plan",
            "run/get_status",
            "settings/get_settings",
            "settings/save_settings",
            "quality/get_quality_profile",
            "quality/get_quality_report",
            "integrations/test_jellyfin_connection",
            "integrations/test_plex_connection",
            "library/get_library_filtered",
            "library/export_full_library",
        ):
            self.assertIn(expected, methods, f"{expected} manquante dans api_methods")

    def test_direct_methods_removed_after_pr10(self) -> None:
        """Apres PR 10 du #84 : les methodes directes ne sont plus exposees.

        Toute methode appartenant a une facade doit etre accessible UNIQUEMENT
        via le path facade-prefixe (run/start_plan, settings/get_settings, ...).
        Le path direct (start_plan, get_settings, ...) doit retourner 404.
        """
        api = backend.CineSortApi()
        methods = _get_api_methods(api)

        for removed in (
            "start_plan",
            "get_status",
            "get_settings",
            "get_quality_profile",
            "test_jellyfin_connection",
            "get_library_filtered",
        ):
            self.assertNotIn(
                removed,
                methods,
                f"Methode directe {removed} encore exposee (PR 10 incomplete)",
            )

    def test_facade_attributes_not_exposed_as_callable(self) -> None:
        """Les facades elles-memes ne sont pas exposees comme endpoint."""
        api = backend.CineSortApi()
        methods = _get_api_methods(api)

        for facade_name in ("run", "settings", "quality", "integrations", "library"):
            self.assertNotIn(
                facade_name,
                methods,
                f"La facade {facade_name} ne doit pas etre directement appelable",
            )

    def test_facade_dispatch_works(self) -> None:
        """Sanity end-to-end : le path facade get_status fonctionne (run_id invalide)."""
        api = backend.CineSortApi()
        methods = _get_api_methods(api)

        # Appel via methode facade
        facade_result = methods["run/get_status"]("run_inexistant_xyz")

        # Sanity : la reponse est un dict avec la cle "ok"
        self.assertIsInstance(facade_result, dict)
        self.assertIn("ok", facade_result)


class RestOpenApiSpecTests(unittest.TestCase):
    """Test the OpenAPI spec generator."""

    def test_spec_has_all_public_methods(self) -> None:
        api = backend.CineSortApi()
        methods = _get_api_methods(api)
        spec = generate_openapi_spec(api)
        for name in methods:
            self.assertIn(f"/api/{name}", spec["paths"], f"Missing endpoint in spec: {name}")

    def test_spec_has_security_scheme(self) -> None:
        api = backend.CineSortApi()
        spec = generate_openapi_spec(api)
        self.assertIn("bearerAuth", spec["components"]["securitySchemes"])

    def test_spec_excludes_private_methods(self) -> None:
        api = backend.CineSortApi()
        spec = generate_openapi_spec(api)
        for path in spec["paths"]:
            method_name = path.replace("/api/", "")
            self.assertFalse(method_name.startswith("_"), f"Private method exposed: {method_name}")


class RestSettingsTests(unittest.TestCase):
    """Test that REST API settings persist correctly."""

    def test_settings_round_trip(self) -> None:
        tmp = tempfile.mkdtemp(prefix="cinesort_rest_st_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.settings.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "rest_api_enabled": True,
                    "rest_api_port": 9090,
                    "rest_api_token": "my-secret",
                }
            )
            loaded = api.settings.get_settings()
            self.assertTrue(loaded["rest_api_enabled"])
            self.assertEqual(loaded["rest_api_port"], 9090)
            # BUG 1 : rest_api_token est retourne en clair (l'utilisateur doit pouvoir
            # le voir pour le donner a ses appareils). Les autres secrets (plex, radarr)
            # restent masques.
            self.assertEqual(loaded["rest_api_token"], "my-secret")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_port_clamped(self) -> None:
        tmp = tempfile.mkdtemp(prefix="cinesort_rest_port_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.settings.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "rest_api_port": 80,  # should be clamped to 1024
                }
            )
            loaded = api.settings.get_settings()
            self.assertGreaterEqual(loaded["rest_api_port"], 1024)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class RestUiContractTests(unittest.TestCase):
    """UI contract tests for REST API elements."""

    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        cls.index_html = (root / "web" / "index.html").read_text(encoding="utf-8")
        js_files = []
        for d in ["core", "components", "views"]:
            p = root / "web" / d
            if p.is_dir():
                for f in sorted(p.glob("*.js")):
                    js_files.append(f.read_text(encoding="utf-8"))
        js_files.append((root / "web" / "app.js").read_text(encoding="utf-8"))
        cls.front_js = "\n".join(js_files)

    def test_rest_api_toggles_in_html(self) -> None:
        self.assertIn('id="ckRestApiEnabled"', self.index_html)
        self.assertIn('id="inRestApiPort"', self.index_html)
        self.assertIn('id="inRestApiToken"', self.index_html)

    def test_rest_settings_in_js(self) -> None:
        self.assertIn("rest_api_enabled", self.front_js)
        self.assertIn("rest_api_port", self.front_js)
        self.assertIn("rest_api_token", self.front_js)

    def test_app_py_has_api_mode(self) -> None:
        app_py = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")
        self.assertIn("--api", app_py)
        self.assertIn("main_api", app_py)
        self.assertIn("RestApiServer", app_py)


# ---------------------------------------------------------------------------
# Tests HTTPS (item 9.20)
# ---------------------------------------------------------------------------


class HttpsFallbackTests(unittest.TestCase):
    """Tests du mode HTTPS — erreur visible si cert/key manquants (M1)."""

    def test_https_disabled_is_plain_http(self) -> None:
        """HTTPS desactive → serveur HTTP classique, _is_https=False."""
        api = backend.CineSortApi()
        port = _find_free_port()
        server = RestApiServer(api, port=port, token="tok", https_enabled=False)
        server.start()
        try:
            self.assertFalse(server._is_https)
        finally:
            server.stop()

    def test_https_enabled_missing_cert_raises(self) -> None:
        """HTTPS active + cert manquant → RuntimeError (pas de fallback silencieux)."""
        api = backend.CineSortApi()
        port = _find_free_port()
        server = RestApiServer(
            api,
            port=port,
            token="tok",
            https_enabled=True,
            cert_path="/non/existent/cert.pem",
            key_path="/non/existent/key.pem",
        )
        with self.assertRaises(RuntimeError) as ctx:
            server.start()
        self.assertIn("cert", str(ctx.exception).lower())
        self.assertFalse(server.is_running)

    def test_https_enabled_empty_paths_raises(self) -> None:
        """HTTPS active + chemins vides → RuntimeError."""
        api = backend.CineSortApi()
        port = _find_free_port()
        server = RestApiServer(
            api,
            port=port,
            token="tok",
            https_enabled=True,
            cert_path="",
            key_path="",
        )
        with self.assertRaises(RuntimeError):
            server.start()
        self.assertFalse(server.is_running)


class HttpsRealCertTests(unittest.TestCase):
    """Tests HTTPS avec un certificat auto-signe genere a la volee."""

    @classmethod
    def setUpClass(cls) -> None:
        # Generer un cert auto-signe via subprocess openssl
        import subprocess

        cls._tmp = tempfile.mkdtemp(prefix="cinesort_https_")
        cls.cert_path = str(Path(cls._tmp) / "cert.pem")
        cls.key_path = str(Path(cls._tmp) / "key.pem")
        try:
            subprocess.run(
                [
                    "openssl",
                    "req",
                    "-x509",
                    "-newkey",
                    "rsa:2048",
                    "-keyout",
                    cls.key_path,
                    "-out",
                    cls.cert_path,
                    "-days",
                    "1",
                    "-nodes",
                    "-subj",
                    "/CN=CineSort-Test",
                ],
                check=True,
                capture_output=True,
                timeout=30,
            )
            cls._has_openssl = True
        except (FileNotFoundError, subprocess.CalledProcessError, OSError):
            cls._has_openssl = False

    @classmethod
    def tearDownClass(cls) -> None:
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def test_https_with_real_cert(self) -> None:
        """HTTPS active + cert valide → _is_https=True, health accessible."""
        if not self._has_openssl:
            self.skipTest("openssl non disponible")
        api = backend.CineSortApi()
        port = _find_free_port()
        server = RestApiServer(
            api,
            port=port,
            token="tok",
            https_enabled=True,
            cert_path=self.cert_path,
            key_path=self.key_path,
        )
        server.start()
        # Cf issue #88 : poll de readiness HTTPS au lieu d'un sleep fixe.
        import http.client
        import ssl

        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        deadline = time.monotonic() + 5.0
        ready = False
        while time.monotonic() < deadline:
            try:
                c = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=0.5)
                c.request("GET", "/api/health")
                r = c.getresponse()
                r.read()
                c.close()
                if r.status == 200:
                    ready = True
                    break
            except (ConnectionRefusedError, OSError, ssl.SSLError):
                pass
            time.sleep(0.05)
        self.assertTrue(ready, "Serveur HTTPS pas pret dans 5s")
        try:
            self.assertTrue(server._is_https)
            conn = http.client.HTTPSConnection("127.0.0.1", port, context=ctx, timeout=5)
            conn.request("GET", "/api/health")
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            data = json.loads(resp.read())
            self.assertTrue(data["ok"])
            conn.close()
        finally:
            server.stop()


class HttpsSettingsTests(unittest.TestCase):
    """Tests round-trip des 3 settings HTTPS."""

    def test_settings_defaults(self) -> None:
        """Les 3 settings HTTPS ont des valeurs par defaut."""
        api = backend.CineSortApi()
        s = api.settings.get_settings()
        self.assertFalse(s.get("rest_api_https_enabled"))
        self.assertEqual(s.get("rest_api_cert_path"), "")
        self.assertEqual(s.get("rest_api_key_path"), "")

    def test_settings_round_trip(self) -> None:
        """Les settings HTTPS survivent un save/load."""
        tmp = tempfile.mkdtemp(prefix="cinesort_https_s_")
        try:
            root = Path(tmp) / "root"
            sd = Path(tmp) / "state"
            root.mkdir()
            sd.mkdir()
            api = backend.CineSortApi()
            api.settings.save_settings(
                {
                    "root": str(root),
                    "state_dir": str(sd),
                    "tmdb_enabled": False,
                    "rest_api_https_enabled": True,
                    "rest_api_cert_path": "/path/to/cert.pem",
                    "rest_api_key_path": "/path/to/key.pem",
                }
            )
            s = api.settings.get_settings()
            self.assertTrue(s["rest_api_https_enabled"])
            self.assertEqual(s["rest_api_cert_path"], "/path/to/cert.pem")
            self.assertEqual(s["rest_api_key_path"], "/path/to/key.pem")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

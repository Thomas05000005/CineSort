"""Tests Phase 1 — Infrastructure du dashboard distant.

Couvre :
- Handler fichiers statiques /dashboard/* (200, 404, path traversal)
- Rate limiting 401 (429 apres 5 echecs, reset apres 60s)
- Health enrichi (active_run_id)
- _RateLimiter en isolation
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
from cinesort.infra.rest_server import (
    _RATE_LIMIT_MAX_FAILURES,
    RestApiServer,
    _CineSortHandler,
    _find_active_run_id,
    _RateLimiter,
)
from tests._helpers import find_free_port as _find_free_port

# ---------------------------------------------------------------------------
# Tests unitaires _RateLimiter (sans serveur HTTP)
# ---------------------------------------------------------------------------


class RateLimiterUnitTests(unittest.TestCase):
    """Tests du rate limiter en isolation."""

    def test_not_blocked_before_threshold(self) -> None:
        rl = _RateLimiter(max_failures=5, window_s=60.0)
        for _ in range(4):
            rl.record_failure("1.2.3.4")
        self.assertFalse(rl.is_blocked("1.2.3.4"))

    def test_blocked_at_threshold(self) -> None:
        rl = _RateLimiter(max_failures=5, window_s=60.0)
        for _ in range(5):
            rl.record_failure("1.2.3.4")
        self.assertTrue(rl.is_blocked("1.2.3.4"))

    def test_different_ips_independent(self) -> None:
        rl = _RateLimiter(max_failures=3, window_s=60.0)
        for _ in range(3):
            rl.record_failure("10.0.0.1")
        self.assertTrue(rl.is_blocked("10.0.0.1"))
        self.assertFalse(rl.is_blocked("10.0.0.2"))

    def test_expiry_after_window(self) -> None:
        rl = _RateLimiter(max_failures=2, window_s=0.1)
        rl.record_failure("5.5.5.5")
        rl.record_failure("5.5.5.5")
        self.assertTrue(rl.is_blocked("5.5.5.5"))
        time.sleep(0.15)
        # Apres expiration de la fenetre, l'IP est debloquee
        self.assertFalse(rl.is_blocked("5.5.5.5"))

    def test_reset_clears_all_failures(self) -> None:
        rl = _RateLimiter(max_failures=2, window_s=60.0)
        for _ in range(3):
            rl.record_failure("127.0.0.1")
        self.assertTrue(rl.is_blocked("127.0.0.1"))
        rl.reset()
        self.assertFalse(rl.is_blocked("127.0.0.1"))

    def test_record_success_clears_failures_for_ip(self) -> None:
        rl = _RateLimiter(max_failures=3, window_s=60.0)
        for _ in range(2):
            rl.record_failure("1.1.1.1")
        rl.record_success("1.1.1.1")
        # Apres 1 echec supplementaire, on est a 1/3 (pas 3/3)
        rl.record_failure("1.1.1.1")
        self.assertFalse(rl.is_blocked("1.1.1.1"))

    def test_global_cap_blocks_across_ips(self) -> None:
        """S6 audit : un attaquant avec N IPs ne peut pas contourner la limite.

        Avec max_failures=3 et global_multiplier=4 → global_cap=12.
        Si 5 IPs distincts font chacun 3 echecs → 15 echecs au total,
        la 13e tentative doit etre bloquee globalement.
        """
        rl = _RateLimiter(max_failures=3, window_s=60.0, global_multiplier=4)
        for ip in ("2.2.2.1", "2.2.2.2", "2.2.2.3", "2.2.2.4"):
            for _ in range(3):
                rl.record_failure(ip)
        # 4 IPs x 3 = 12 echecs — on atteint pile le seuil global
        self.assertTrue(rl.is_blocked("2.2.2.99"), msg="une IP fraiche devrait etre bloquee globalement")


# ---------------------------------------------------------------------------
# Tests unitaires _find_active_run_id
# ---------------------------------------------------------------------------


class FindActiveRunIdTests(unittest.TestCase):
    """Tests de la detection de run actif pour /api/health."""

    def test_no_active_run(self) -> None:
        api = backend.CineSortApi()
        result = _find_active_run_id(api)
        self.assertIsNone(result)

    def test_with_mock_active_run(self) -> None:
        """Simule un RunState running dans api._runs."""
        api = backend.CineSortApi()

        class FakeRS:
            running = True
            done = False

        with api._runs_lock:
            api._runs["test-run-123"] = FakeRS()
        result = _find_active_run_id(api)
        self.assertEqual(result, "test-run-123")
        # Nettoyage
        with api._runs_lock:
            del api._runs["test-run-123"]

    def test_done_run_not_returned(self) -> None:
        api = backend.CineSortApi()

        class FakeRS:
            running = False
            done = True

        with api._runs_lock:
            api._runs["done-run"] = FakeRS()
        result = _find_active_run_id(api)
        self.assertIsNone(result)
        with api._runs_lock:
            del api._runs["done-run"]


# ---------------------------------------------------------------------------
# Tests HTTP integres (serveur reel)
# ---------------------------------------------------------------------------


class DashboardStaticFileTests(unittest.TestCase):
    """Tests du handler de fichiers statiques /dashboard/*."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="cinesort_dash_")
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
        cls.token = "dash-test-token"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _get(self, path: str) -> tuple[int, bytes, dict]:
        """GET request, retourne (status, body bytes, headers dict)."""
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

    # --- Fichiers statiques ---

    def test_dashboard_root_serves_index(self) -> None:
        """GET /dashboard/ retourne index.html."""
        status, body, headers = self._get("/dashboard/")
        self.assertEqual(status, 200)
        self.assertIn("text/html", headers.get("content-type", ""))
        self.assertIn(b"CineSort", body)

    def test_dashboard_without_slash_redirects_to_slash(self) -> None:
        """GET /dashboard renvoie 301 vers /dashboard/ pour fixer la resolution
        des chemins relatifs (./styles.css -> /dashboard/styles.css au lieu
        de /styles.css). Sans cette redirection, la page de login s'affichait
        en HTML brut sans CSS (bug confirme screenshot 2026-06-05)."""
        status, body, headers = self._get("/dashboard")
        self.assertEqual(status, 301)
        self.assertEqual(headers.get("location"), "/dashboard/")

    def test_dashboard_index_explicit(self) -> None:
        """GET /dashboard/index.html retourne 200."""
        status, body, headers = self._get("/dashboard/index.html")
        self.assertEqual(status, 200)
        self.assertIn(b"<html", body)

    def test_dashboard_nonexistent_file_returns_404(self) -> None:
        """Fichier inexistant → 404."""
        status, body, headers = self._get("/dashboard/nope.js")
        self.assertEqual(status, 404)

    def test_dashboard_path_traversal_blocked(self) -> None:
        """Tentative de path traversal via .. → 403 ou 404."""
        status, _, _ = self._get("/dashboard/../../../etc/passwd")
        self.assertIn(status, {403, 404})

    def test_dashboard_path_traversal_encoded_blocked(self) -> None:
        """Tentative de path traversal via %2e%2e → 403 ou 404."""
        status, _, _ = self._get("/dashboard/%2e%2e/%2e%2e/etc/passwd")
        self.assertIn(status, {403, 404})

    def test_dashboard_cache_header(self) -> None:
        """Les fichiers statiques ont une politique de cache explicite.

        Pour index.html (SPA entry point), `no-cache, must-revalidate` est
        la bonne pratique : on ne veut PAS que les users voient une vieille
        version apres une nouvelle release. `max-age` reste accepte si
        configure (ex: assets versionnes par hash).
        """
        status, _, headers = self._get("/dashboard/index.html")
        self.assertEqual(status, 200)
        self.assertIn("cache-control", headers)
        cache_control = headers["cache-control"].lower()
        # Accepter soit max-age=N (cache positif) soit no-cache (revalidation forcee).
        self.assertTrue(
            "max-age" in cache_control or "no-cache" in cache_control,
            f"Cache-Control doit specifier max-age ou no-cache, got: {cache_control!r}",
        )

    # --- Health enrichi ---

    def test_health_returns_active_run_id_when_present(self) -> None:
        """Health retourne active_run_id si un run est en cours."""

        class FakeRS:
            running = True
            done = False

        with self.api._runs_lock:
            self.api._runs["health-run-1"] = FakeRS()
        try:
            status, body, _ = self._get("/api/health")
            data = json.loads(body)
            self.assertEqual(status, 200)
            self.assertEqual(data["active_run_id"], "health-run-1")
        finally:
            with self.api._runs_lock:
                del self.api._runs["health-run-1"]

    def test_health_no_active_run_id_when_idle(self) -> None:
        """Health ne contient pas active_run_id si aucun run actif."""
        status, body, _ = self._get("/api/health")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertNotIn("active_run_id", data)

    def test_health_contains_last_event_ts(self) -> None:
        """Health retourne last_event_ts (float)."""
        status, body, _ = self._get("/api/health")
        data = json.loads(body)
        self.assertEqual(status, 200)
        self.assertIn("last_event_ts", data)
        self.assertIsInstance(data["last_event_ts"], float)

    def test_last_event_ts_updates_after_save_settings(self) -> None:
        """last_event_ts change apres un save_settings reussi."""
        _, body1, _ = self._get("/api/health")
        ts1 = json.loads(body1)["last_event_ts"]
        # Sauvegarder des settings valides
        self.api.settings.save_settings(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        _, body2, _ = self._get("/api/health")
        ts2 = json.loads(body2)["last_event_ts"]
        self.assertGreater(ts2, ts1)


class RateLimitHttpTests(unittest.TestCase):
    """Tests du rate limiting via HTTP."""

    @classmethod
    def setUpClass(cls) -> None:
        cls._tmp = tempfile.mkdtemp(prefix="cinesort_rl_")
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
        cls.token = "rl-test-token"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        time.sleep(0.3)

    @classmethod
    def tearDownClass(cls) -> None:
        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def setUp(self) -> None:
        # Audit 5.1 : reset du rate limiter pour eviter que l'ordre d'execution
        # des tests influe sur le resultat (meme IP 127.0.0.1 partagee).
        self.server._rate_limiter.reset()

    def _post(self, path: str, token: str = "wrong") -> int:
        conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        }
        conn.request("POST", path, body=b"{}", headers=headers)
        resp = conn.getresponse()
        status = resp.status
        resp.read()
        conn.close()
        return status

    def test_rate_limit_blocks_after_5_failures(self) -> None:
        """ITER14 #2 SOLDE (2026-06-10) — re-ancrage sur chemin facade non-loopback.

        Historique :
          - FIX DEFINITIF 2026-06-07 : 127.0.0.1 exempte du rate-limit (saturation
            par 401 silents _safeBearer + BOM U+FEFF). Bypass conserve.
          - ITER14 RATE_LIMIT_429_FACADE : la voie publique testee passe par le
            chemin facade /api/<facade>/<method>. Le test legacy /api/get_settings
            tombe sur la garde 410 Gone (P0 #233) avant meme d'atteindre l'auth,
            ce qui rendait le scenario rate-limit invisible.

        DEUX NOTIONS DISTINCTES, A NE PAS CONFONDRE (2026-08-07) :
          - l'exemption de RATE LIMITING pour le loopback est **CONSERVEE**
            (`_is_rate_limited` sort tot pour `_LOCAL_CLIENT_IPS`) — c'est le
            sujet de ce test ;
          - le bypass d'AUTHENTIFICATION loopback est **RETIRE**. Une version
            anterieure de cette docstring citait « memoire user BYPASS LOOPBACK
            CONSERVE » et affirmait que le point 4 prouvait le bypass intact :
            elle disait donc l'inverse du corps depuis le retrait.

        Strategie de re-ancrage (alignee sur scripts/_check_iter14_rate_limit_429.py) :
          1. Monkey-patch `_CineSortHandler._client_ip` pour simuler une IP LAN
             (10.0.0.42) : le rate-limit redevient actif (le loopback en reste
             exempte par design).
          2. Pre-saturer le compteur _RateLimiter via record_failure (5 echecs).
          3. POST sur le VRAI chemin facade `/api/settings/get_settings` avec un
             bon token : on doit recevoir 429 + Retry-After (28e85c3 fix #2).
          4. Verifier que le POST loopback reel (sans patch) N'est PAS 429 : il
             rend 401, car l'authentification s'execute AVANT la garde 410 du
             chemin legacy. L'assertion qui porte le sens du test est « ce n'est
             pas 429 » ; le 401 en est la consequence, pas le sujet.
        """
        # 1. Simuler IP LAN distante via monkey-patch.
        original_client_ip = _CineSortHandler._client_ip

        def fake_client_ip(self: Any) -> str:
            return "10.0.0.42"

        _CineSortHandler._client_ip = fake_client_ip  # type: ignore[assignment]
        try:
            # 2. Pre-saturer le compteur (5 echecs sur 10.0.0.42).
            for _ in range(_RATE_LIMIT_MAX_FAILURES):
                self.server._rate_limiter.record_failure("10.0.0.42")
            self.assertTrue(
                self.server._rate_limiter.is_blocked("10.0.0.42"),
                "le rate-limiter aurait du bloquer 10.0.0.42 apres 5 echecs",
            )

            # 3. POST facade avec bon token : 429 + Retry-After.
            conn = HTTPConnection("127.0.0.1", self.port, timeout=5)
            conn.request(
                "POST",
                "/api/settings/get_settings",
                body=b"{}",
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.token}",
                },
            )
            resp = conn.getresponse()
            status_429 = resp.status
            retry_after = resp.getheader("Retry-After")
            xreq = resp.getheader("X-Request-ID") or resp.getheader("x-request-id")
            resp.read()
            conn.close()
            self.assertEqual(
                status_429,
                429,
                f"facade path doit renvoyer 429 quand 10.0.0.42 est sature, got {status_429}",
            )
            self.assertEqual(retry_after, "60", f"Retry-After=60 attendu (RFC 7231), got {retry_after!r}")
            self.assertIsNotNone(xreq, "X-Request-ID doit etre present sur 429")
        finally:
            _CineSortHandler._client_ip = original_client_ip  # type: ignore[assignment]

        # 4. Loopback NON patche : toujours exempte du rate-limit.
        #
        # Ce que ce point mesure est INCHANGE — le compteur de 10.0.0.42 reste
        # sature, et 127.0.0.1 ne doit pas en heriter. Seul le code attendu
        # bouge : jusqu'au 2026-08-07 le bypass d'auth laissait passer la
        # requete jusqu'a la garde du chemin legacy (410) ; depuis son retrait,
        # l'authentification s'execute d'abord et un mauvais jeton rend 401.
        #
        # L'assertion qui porte le sens du test est la SECONDE : ce n'est pas
        # 429. Un 401 prouve l'exemption aussi bien qu'un 410.
        status_loop = self._post("/api/get_settings", token="bad-token")
        self.assertNotEqual(
            status_loop,
            429,
            "loopback a herite du rate-limit de 10.0.0.42 : l'exemption locale est cassee",
        )
        self.assertEqual(
            status_loop,
            401,
            f"loopback + mauvais jeton attendu 401 depuis le retrait du bypass, got {status_loop}",
        )

    def test_rate_limit_does_not_block_valid_requests_before_threshold(self) -> None:
        """Un bon token passe si on n'a pas atteint le seuil (nouveau serveur necessaire)."""
        # Ce test utilise le bon token — ne devrait pas etre bloque
        # Note : le rate limiter du setUpClass peut etre pollue par le test precedent
        # On teste simplement qu'un bon token retourne 200 sur un serveur frais
        port2 = _find_free_port()
        server2 = RestApiServer(self.api, port=port2, token=self.token)
        server2.start()
        time.sleep(0.2)
        try:
            conn = HTTPConnection("127.0.0.1", port2, timeout=5)
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.token}",
            }
            # Issue #84 PR 10 : path facade /api/settings/get_settings
            conn.request("POST", "/api/settings/get_settings", body=b"{}", headers=headers)
            resp = conn.getresponse()
            self.assertEqual(resp.status, 200)
            resp.read()
            conn.close()
        finally:
            server2.stop()


if __name__ == "__main__":
    unittest.main()

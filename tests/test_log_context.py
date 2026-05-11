"""V3-04 polish v7.7.0 — tests du contexte de log transversal.

Couvre R4-LOG-1 (run_id ContextVar), R4-LOG-2 (request_id), R4-LOG-3
(log_level configurable + env vars), R4-LOG-4 (CINESORT_DEBUG implementee).
"""

from __future__ import annotations

import io
import logging
import threading
import unittest

from cinesort.infra.log_context import (
    DEFAULT_LOG_FORMAT_WITH_CONTEXT,
    LogContextFilter,
    attach_filter_to_handler,
    clear_request_id,
    clear_run_id,
    get_request_id,
    get_run_id,
    install_log_context_filter,
    normalize_log_level_setting,
    reset_for_tests,
    resolve_log_level,
    set_request_id,
    set_run_id,
)


class RunIdContextVarTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_run_id()
        clear_request_id()
        reset_for_tests()

    def tearDown(self) -> None:
        clear_run_id()
        clear_request_id()
        reset_for_tests()

    def test_set_get_clear_run_id(self) -> None:
        self.assertIsNone(get_run_id())
        set_run_id("20260504_120000_001")
        self.assertEqual(get_run_id(), "20260504_120000_001")
        clear_run_id()
        self.assertIsNone(get_run_id())

    def test_set_run_id_with_none_clears(self) -> None:
        set_run_id("abc")
        set_run_id(None)
        self.assertIsNone(get_run_id())

    def test_set_run_id_returns_token_resettable(self) -> None:
        from cinesort.infra.log_context import reset_run_id

        token = set_run_id("first")
        set_run_id("second")
        self.assertEqual(get_run_id(), "second")
        reset_run_id(token)
        # reset_run_id revert au state d'avant token (pas de valeur)
        self.assertIsNone(get_run_id())


class RequestIdContextVarTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_request_id()

    def tearDown(self) -> None:
        clear_request_id()

    def test_set_get_clear_request_id(self) -> None:
        self.assertIsNone(get_request_id())
        set_request_id("abcd1234")
        self.assertEqual(get_request_id(), "abcd1234")
        clear_request_id()
        self.assertIsNone(get_request_id())


class LogContextFilterTests(unittest.TestCase):
    def setUp(self) -> None:
        clear_run_id()
        clear_request_id()

    def tearDown(self) -> None:
        clear_run_id()
        clear_request_id()

    def _make_record(self) -> logging.LogRecord:
        return logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )

    def test_filter_injects_dash_when_unset(self) -> None:
        flt = LogContextFilter()
        record = self._make_record()
        flt.filter(record)
        self.assertEqual(record.run_id, "-")
        self.assertEqual(record.request_id, "-")

    def test_filter_injects_run_id_when_set(self) -> None:
        flt = LogContextFilter()
        set_run_id("20260504_010203_004")
        record = self._make_record()
        flt.filter(record)
        self.assertEqual(record.run_id, "20260504_010203_004")
        self.assertEqual(record.request_id, "-")

    def test_filter_injects_request_id_when_set(self) -> None:
        flt = LogContextFilter()
        set_request_id("deadbeef")
        record = self._make_record()
        flt.filter(record)
        self.assertEqual(record.request_id, "deadbeef")

    def test_filter_returns_true_always(self) -> None:
        """Le filter ne doit JAMAIS supprimer un record."""
        flt = LogContextFilter()
        record = self._make_record()
        self.assertTrue(flt.filter(record))


class FormatIntegrationTests(unittest.TestCase):
    """Verifie que le format complet rend bien run_id + request_id."""

    def setUp(self) -> None:
        clear_run_id()
        clear_request_id()
        self.logger = logging.getLogger("cinesort.test.log_context.format")
        self.logger.handlers.clear()
        self.logger.setLevel(logging.DEBUG)
        self.stream = io.StringIO()
        handler = logging.StreamHandler(self.stream)
        handler.setFormatter(logging.Formatter(DEFAULT_LOG_FORMAT_WITH_CONTEXT))
        attach_filter_to_handler(handler)
        self.logger.addHandler(handler)
        self.logger.propagate = False

    def tearDown(self) -> None:
        self.logger.handlers.clear()
        clear_run_id()
        clear_request_id()

    def test_format_with_run_id_and_request_id(self) -> None:
        set_run_id("20260504_120000_999")
        set_request_id("ab12cd34")
        self.logger.info("scan demarre")
        out = self.stream.getvalue()
        self.assertIn("[run=20260504_120000_999 req=ab12cd34]", out)
        self.assertIn("scan demarre", out)

    def test_format_without_context_uses_dash(self) -> None:
        self.logger.info("hors contexte")
        out = self.stream.getvalue()
        self.assertIn("[run=- req=-]", out)


class ThreadSafetyTests(unittest.TestCase):
    """Le ContextVar doit etre isole par thread (pas de fuite cross-thread)."""

    def setUp(self) -> None:
        clear_run_id()
        clear_request_id()

    def test_run_id_isolated_per_thread(self) -> None:
        captured: dict = {}
        barrier = threading.Barrier(3)

        def worker(name: str, run_id: str) -> None:
            set_run_id(run_id)
            barrier.wait()  # tous les threads ont set leur run_id
            barrier.wait()  # synchroniser avant la lecture
            captured[name] = get_run_id()

        t1 = threading.Thread(target=worker, args=("a", "RUN_A"))
        t2 = threading.Thread(target=worker, args=("b", "RUN_B"))
        t1.start()
        t2.start()
        # Le thread main n'a pas set : doit voir None peu importe l'etat des
        # workers (ContextVar par-thread).
        barrier.wait()  # attendre les set
        self.assertIsNone(get_run_id())
        barrier.wait()  # libere les workers pour la lecture
        t1.join()
        t2.join()
        self.assertEqual(captured["a"], "RUN_A")
        self.assertEqual(captured["b"], "RUN_B")

    def test_main_thread_unaffected_by_worker(self) -> None:
        set_run_id("MAIN")

        def worker() -> None:
            set_run_id("WORKER")
            # Pas de clear : on verifie que ca n'affecte pas le main thread.

        t = threading.Thread(target=worker)
        t.start()
        t.join()
        self.assertEqual(get_run_id(), "MAIN")


class InstallLogContextFilterTests(unittest.TestCase):
    """install_log_context_filter doit etre idempotent et installer sur root."""

    def setUp(self) -> None:
        reset_for_tests()
        # Snapshot des filters existants pour restoration en tearDown
        self.root = logging.getLogger()
        self._original_filters = list(self.root.filters)

    def tearDown(self) -> None:
        # Retirer les LogContextFilter ajoutes durant le test
        for f in list(self.root.filters):
            if isinstance(f, LogContextFilter) and f not in self._original_filters:
                self.root.removeFilter(f)
        reset_for_tests()

    def test_install_adds_filter_to_root(self) -> None:
        before = sum(1 for f in self.root.filters if isinstance(f, LogContextFilter))
        install_log_context_filter()
        after = sum(1 for f in self.root.filters if isinstance(f, LogContextFilter))
        self.assertGreaterEqual(after, before)
        self.assertGreaterEqual(after, 1)

    def test_install_is_idempotent(self) -> None:
        install_log_context_filter()
        count1 = sum(1 for f in self.root.filters if isinstance(f, LogContextFilter))
        install_log_context_filter()
        install_log_context_filter()
        count2 = sum(1 for f in self.root.filters if isinstance(f, LogContextFilter))
        self.assertEqual(count1, count2)


class ResolveLogLevelTests(unittest.TestCase):
    """R4-LOG-3 / R4-LOG-4 : env var override + setting + defaut."""

    def test_default_is_info(self) -> None:
        self.assertEqual(resolve_log_level(None, env={}), logging.INFO)

    def test_setting_value_used(self) -> None:
        self.assertEqual(resolve_log_level("DEBUG", env={}), logging.DEBUG)
        self.assertEqual(resolve_log_level("WARNING", env={}), logging.WARNING)
        self.assertEqual(resolve_log_level("ERROR", env={}), logging.ERROR)
        self.assertEqual(resolve_log_level("CRITICAL", env={}), logging.CRITICAL)

    def test_setting_value_lowercase_normalized(self) -> None:
        self.assertEqual(resolve_log_level("debug", env={}), logging.DEBUG)
        self.assertEqual(resolve_log_level("info", env={}), logging.INFO)

    def test_invalid_setting_falls_back_to_info(self) -> None:
        self.assertEqual(resolve_log_level("garbage", env={}), logging.INFO)
        self.assertEqual(resolve_log_level("", env={}), logging.INFO)

    def test_env_cinesort_log_level_overrides(self) -> None:
        env = {"CINESORT_LOG_LEVEL": "WARNING"}
        # Settings dit DEBUG mais env dit WARNING → env gagne
        self.assertEqual(resolve_log_level("DEBUG", env=env), logging.WARNING)

    def test_env_cinesort_debug_forces_debug(self) -> None:
        env = {"CINESORT_DEBUG": "1"}
        self.assertEqual(resolve_log_level(None, env=env), logging.DEBUG)
        self.assertEqual(resolve_log_level("ERROR", env=env), logging.DEBUG)

    def test_env_cinesort_debug_other_truthy(self) -> None:
        for value in ("true", "yes", "on", "debug"):
            env = {"CINESORT_DEBUG": value}
            self.assertEqual(resolve_log_level(None, env=env), logging.DEBUG, msg=value)

    def test_cinesort_log_level_takes_priority_over_cinesort_debug(self) -> None:
        env = {"CINESORT_LOG_LEVEL": "ERROR", "CINESORT_DEBUG": "1"}
        # CINESORT_LOG_LEVEL est en haut de la priorite, gagne sur CINESORT_DEBUG
        self.assertEqual(resolve_log_level(None, env=env), logging.ERROR)

    def test_invalid_env_log_level_falls_through(self) -> None:
        env = {"CINESORT_LOG_LEVEL": "GARBAGE"}
        # Invalid env → tombe sur le settings
        self.assertEqual(resolve_log_level("WARNING", env=env), logging.WARNING)


class NormalizeLogLevelSettingTests(unittest.TestCase):
    def test_valid_values(self) -> None:
        for v in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
            self.assertEqual(normalize_log_level_setting(v), v)

    def test_lowercase_normalized_to_upper(self) -> None:
        self.assertEqual(normalize_log_level_setting("debug"), "DEBUG")
        self.assertEqual(normalize_log_level_setting("info"), "INFO")

    def test_invalid_falls_back_to_info(self) -> None:
        self.assertEqual(normalize_log_level_setting("garbage"), "INFO")
        self.assertEqual(normalize_log_level_setting(None), "INFO")
        self.assertEqual(normalize_log_level_setting(""), "INFO")


class RestRequestIdHeaderTests(unittest.TestCase):
    """R4-LOG-2 : verifier que le serveur REST emet bien X-Request-ID."""

    @classmethod
    def setUpClass(cls) -> None:
        import socket
        import tempfile
        import time as _time
        from pathlib import Path

        import cinesort.ui.api.cinesort_api as backend
        from cinesort.infra.rest_server import RestApiServer

        cls._tmp = tempfile.mkdtemp(prefix="cinesort_log_ctx_rest_")
        root = Path(cls._tmp) / "root"
        state_dir = Path(cls._tmp) / "state"
        root.mkdir()
        state_dir.mkdir()

        cls.api = backend.CineSortApi()
        cls.api.save_settings(
            {
                "root": str(root),
                "state_dir": str(state_dir),
                "tmdb_enabled": False,
            }
        )

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            cls.port = s.getsockname()[1]
        cls.token = "log-context-test-token-42"
        cls.server = RestApiServer(cls.api, port=cls.port, token=cls.token)
        cls.server.start()
        _time.sleep(0.2)

    @classmethod
    def tearDownClass(cls) -> None:
        import shutil

        cls.server.stop()
        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _request(self, method: str, path: str, headers: dict | None = None, body: bytes = b"") -> tuple:
        import http.client

        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            resp = conn.getresponse()
            data = resp.read()
            return resp.status, dict(resp.getheaders()), data
        finally:
            conn.close()

    def test_x_request_id_on_health(self) -> None:
        status, headers, _data = self._request("GET", "/api/health")
        self.assertEqual(status, 200)
        # Headers normalises lowercase par http.client
        rid = headers.get("X-Request-ID") or headers.get("x-request-id")
        self.assertIsNotNone(rid, msg=f"X-Request-ID absent. Headers: {headers}")
        self.assertEqual(len(rid), 8, msg=f"format inattendu: {rid}")
        # Hex pur
        int(rid, 16)  # leve si non-hex

    def test_x_request_id_on_unauthorized_post(self) -> None:
        status, headers, _data = self._request("POST", "/api/get_settings", body=b"{}")
        self.assertEqual(status, 401)
        rid = headers.get("X-Request-ID") or headers.get("x-request-id")
        self.assertIsNotNone(rid, msg=f"X-Request-ID absent sur 401. Headers: {headers}")

    def test_x_request_id_unique_per_request(self) -> None:
        ids = set()
        for _ in range(5):
            _status, headers, _data = self._request("GET", "/api/health")
            rid = headers.get("X-Request-ID") or headers.get("x-request-id")
            ids.add(rid)
        self.assertEqual(len(ids), 5, msg=f"request_id doit varier: {ids}")


if __name__ == "__main__":
    unittest.main()

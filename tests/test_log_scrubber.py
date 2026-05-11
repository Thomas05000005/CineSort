"""H-3/S-4/S-5 audit QA 20260428 — tests du scrubber de secrets dans les logs.

Verifie que les patterns de cles API et tokens sont bien remplaces par
[REDACTED] dans les messages de log, args et exc_text. Ne doit JAMAIS
supprimer un log ni lever d'exception.
"""

from __future__ import annotations

import io
import logging
import unittest

from cinesort.infra.log_scrubber import (
    SecretsScrubFilter,
    install_global_scrubber,
    reset_for_tests,
    scrub_secrets,
)
import contextlib


class ScrubSecretsFunctionTests(unittest.TestCase):
    def test_tmdb_api_key_in_query_string(self) -> None:
        text = "GET https://api.themoviedb.org/3/search/movie?api_key=abc123def&query=Inception"
        result = scrub_secrets(text)
        self.assertIn("api_key=[REDACTED]", result)
        self.assertNotIn("abc123def", result)
        # Le reste de l'URL doit etre preserve
        self.assertIn("query=Inception", result)

    def test_tmdb_api_key_uppercase(self) -> None:
        text = "URL: API_KEY=SECRETKEY42"
        result = scrub_secrets(text)
        self.assertIn("[REDACTED]", result)
        self.assertNotIn("SECRETKEY42", result)

    def test_jellyfin_authorization_header(self) -> None:
        text = 'HTTP error: Authorization: MediaBrowser Token="jelly_secret_xyz"'
        result = scrub_secrets(text)
        self.assertIn('Token="[REDACTED]"', result)
        self.assertNotIn("jelly_secret_xyz", result)

    def test_bearer_token(self) -> None:
        text = "Authorization: Bearer ey.J0eXAi.OiJKV1Q"
        result = scrub_secrets(text)
        self.assertIn("Bearer [REDACTED]", result)
        self.assertNotIn("ey.J0eXAi.OiJKV1Q", result)

    def test_plex_token_header(self) -> None:
        text = "Headers: X-Plex-Token: plex_token_abc;"
        result = scrub_secrets(text)
        self.assertNotIn("plex_token_abc", result)
        self.assertIn("[REDACTED]", result)

    def test_plex_token_query(self) -> None:
        text = "GET /library?X-Plex-Token=plex_xyz_42"
        result = scrub_secrets(text)
        self.assertNotIn("plex_xyz_42", result)
        self.assertIn("[REDACTED]", result)

    def test_radarr_api_key(self) -> None:
        text = "Headers: X-Api-Key: radarr_key_999"
        result = scrub_secrets(text)
        self.assertNotIn("radarr_key_999", result)
        self.assertIn("[REDACTED]", result)

    def test_json_dump_with_api_keys(self) -> None:
        text = '{"tmdb_api_key": "secret_tmdb", "jellyfin_api_key": "secret_jelly"}'
        result = scrub_secrets(text)
        self.assertNotIn("secret_tmdb", result)
        self.assertNotIn("secret_jelly", result)
        self.assertEqual(result.count("[REDACTED]"), 2)

    def test_smtp_password_json(self) -> None:
        text = '{"smtp_password": "p@ssw0rd!"}'
        result = scrub_secrets(text)
        self.assertNotIn("p@ssw0rd!", result)
        self.assertIn("[REDACTED]", result)

    def test_email_smtp_password_sec_h1(self) -> None:
        """SEC-H1 (Phase 1 v7.8.0) : email_smtp_password etait oublie par le scrubber."""
        text = '{"email_smtp_password": "gmail-app-pwd-xxx"}'
        result = scrub_secrets(text)
        self.assertNotIn("gmail-app-pwd-xxx", result)
        self.assertIn("[REDACTED]", result)

    def test_omdb_osdb_api_keys_sec_h1(self) -> None:
        """SEC-H1 : nouvelles cles API (OMDb/OSDB) ne fuient pas."""
        for key_name in ("omdb_api_key", "osdb_api_key", "trakt_api_key", "anidb_api_key"):
            with self.subTest(key=key_name):
                text = f'{{"{key_name}": "secret-value-{key_name}"}}'
                result = scrub_secrets(text)
                self.assertNotIn(f"secret-value-{key_name}", result)
                self.assertIn("[REDACTED]", result)

    def test_dpapi_secret_blobs_sec_h1(self) -> None:
        """SEC-H1 : blobs DPAPI (`*_secret`) sont aussi masques par precaution."""
        for key_name in ("tmdb_api_key_secret", "jellyfin_api_key_secret", "email_smtp_password_secret"):
            with self.subTest(key=key_name):
                text = f'{{"{key_name}": "ZG1raWVycw=="}}'
                result = scrub_secrets(text)
                self.assertNotIn("ZG1raWVycw==", result)
                self.assertIn("[REDACTED]", result)

    def test_full_settings_dump_no_leak_sec_h1(self) -> None:
        """SEC-H1 : dump complet d'un settings.json realiste ne fuit aucune cle."""
        import json

        settings = {
            "root": "C:/Films",
            "auto_approve_threshold": 85,
            "tmdb_api_key": "tmdb-real-secret-abc",
            "jellyfin_api_key": "jf-real-token-def",
            "jellyfin_url": "http://localhost:8096",
            "plex_token": "plex-real-tok-ghi",
            "radarr_api_key": "rad-real-key-jkl",
            "rest_api_token": "rest-real-bearer-mno",
            "email_smtp_password": "smtp-pass-pqr",
        }
        dump = json.dumps(settings)
        scrubbed = scrub_secrets(dump)
        # Aucun secret ne doit fuiter
        for secret in (
            "tmdb-real-secret-abc",
            "jf-real-token-def",
            "plex-real-tok-ghi",
            "rad-real-key-jkl",
            "rest-real-bearer-mno",
            "smtp-pass-pqr",
        ):
            self.assertNotIn(secret, scrubbed, f"Secret '{secret}' a fuite : {scrubbed}")
        # Les valeurs non-secret restent visibles
        self.assertIn("C:/Films", scrubbed)
        self.assertIn("localhost", scrubbed)
        self.assertIn("85", scrubbed)

    def test_clean_text_unchanged(self) -> None:
        text = "Just a normal log message with no secrets in it."
        self.assertEqual(scrub_secrets(text), text)

    def test_non_string_returned_as_is(self) -> None:
        # Les non-strings doivent passer sans modification (pas crash)
        self.assertIsNone(scrub_secrets(None))  # type: ignore[arg-type]
        self.assertEqual(scrub_secrets(42), 42)  # type: ignore[arg-type]
        self.assertEqual(scrub_secrets([]), [])  # type: ignore[arg-type]

    def test_empty_string(self) -> None:
        self.assertEqual(scrub_secrets(""), "")


class ScrubFilterIntegrationTests(unittest.TestCase):
    """Verifie que le filter installe sur un logger scrub bien les records."""

    def setUp(self) -> None:
        reset_for_tests()
        # Logger isole pour ne pas polluer le root
        self.logger = logging.getLogger("cinesort.test_scrub")
        self.logger.setLevel(logging.DEBUG)
        self.logger.handlers.clear()
        self.stream = io.StringIO()
        self.handler = logging.StreamHandler(self.stream)
        self.handler.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)
        self.logger.addFilter(SecretsScrubFilter())
        self.logger.propagate = False

    def tearDown(self) -> None:
        self.logger.handlers.clear()
        self.logger.filters.clear()
        reset_for_tests()

    def test_filter_scrubs_simple_message(self) -> None:
        self.logger.error("Failed: api_key=mySecretKey123")
        output = self.stream.getvalue()
        self.assertIn("[REDACTED]", output)
        self.assertNotIn("mySecretKey123", output)

    def test_filter_scrubs_args(self) -> None:
        # Args sont substitues a getMessage() — on doit aussi les scrubber
        self.logger.error("URL: %s", "https://api.tmdb.org?api_key=tupleArgs999")
        output = self.stream.getvalue()
        self.assertIn("[REDACTED]", output)
        self.assertNotIn("tupleArgs999", output)

    def test_filter_scrubs_exc_text_via_exc_info(self) -> None:
        # Quand exc_info=True, la traceback peut contenir un secret
        # (ex: dans une URL passee a requests). On verifie qu'apres
        # formatage par le handler, le secret n'apparait plus.
        try:
            url = "https://api.tmdb.org/3/movie/123?api_key=tracebackSecret42"
            raise RuntimeError(f"HTTP 401 sur {url}")
        except RuntimeError:
            self.logger.error("Erreur API", exc_info=True)
        output = self.stream.getvalue()
        self.assertIn("[REDACTED]", output)
        self.assertNotIn("tracebackSecret42", output)

    def test_filter_does_not_drop_records(self) -> None:
        """Le filter ne doit JAMAIS retourner False (sinon les logs disparaissent)."""
        self.logger.info("Message normal sans secret.")
        output = self.stream.getvalue()
        self.assertIn("Message normal sans secret.", output)


class InstallRotatingLogTests(unittest.TestCase):
    """H-6 audit QA 20260429 : RotatingFileHandler pour eviter logs infinis."""

    def setUp(self) -> None:
        reset_for_tests()
        self._tmp = __import__("tempfile").mkdtemp(prefix="cinesort_rotlog_")
        self.log_dir = __import__("pathlib").Path(self._tmp) / "logs"
        self._initial_handlers = list(logging.getLogger().handlers)

    def tearDown(self) -> None:
        # Retire les handlers ajoutes (sinon polluent les tests suivants)
        root = logging.getLogger()
        for h in list(root.handlers):
            if h not in self._initial_handlers:
                root.removeHandler(h)
                with contextlib.suppress(Exception):
                    h.close()
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)
        reset_for_tests()

    def test_install_creates_log_file(self) -> None:
        from cinesort.infra.log_scrubber import install_rotating_log

        result = install_rotating_log(self.log_dir, max_bytes=1024, backup_count=2)
        self.assertIsNotNone(result)
        self.assertTrue(result.parent.is_dir())

    def test_install_is_idempotent(self) -> None:
        from cinesort.infra.log_scrubber import install_rotating_log

        first = install_rotating_log(self.log_dir)
        second = install_rotating_log(self.log_dir)
        self.assertIsNotNone(first)
        self.assertIsNone(second)  # second appel = no-op

    def test_install_attaches_scrubber_to_handler(self) -> None:
        from cinesort.infra.log_scrubber import (
            SecretsScrubFilter,
            install_rotating_log,
        )

        log_path = install_rotating_log(self.log_dir)
        self.assertIsNotNone(log_path)
        # Cherche specifiquement le handler installe par CE test (par chemin),
        # pas rotating_handlers[0] qui pourrait pointer sur un handler residuel
        # d'un test precedent dans la suite full.
        target = str(log_path).lower()
        ours = [
            h
            for h in logging.getLogger().handlers
            if isinstance(h, logging.handlers.RotatingFileHandler) and getattr(h, "baseFilename", "").lower() == target
        ]
        self.assertEqual(len(ours), 1, f"Handler du test introuvable parmi {logging.getLogger().handlers}")
        self.assertTrue(any(isinstance(f, SecretsScrubFilter) for f in ours[0].filters))


class InstallGlobalScrubberTests(unittest.TestCase):
    def setUp(self) -> None:
        reset_for_tests()
        # Sauvegarder l'etat root pour pouvoir restaurer
        self.root = logging.getLogger()
        self._initial_filters = list(self.root.filters)

    def tearDown(self) -> None:
        # Retire les SecretsScrubFilter qu'on a pu ajouter
        self.root.filters = self._initial_filters
        for handler in self.root.handlers:
            handler.filters = [f for f in handler.filters if not isinstance(f, SecretsScrubFilter)]
        reset_for_tests()

    def test_install_is_idempotent(self) -> None:
        install_global_scrubber()
        install_global_scrubber()
        install_global_scrubber()
        scrub_filters = [f for f in self.root.filters if isinstance(f, SecretsScrubFilter)]
        self.assertEqual(len(scrub_filters), 1)

    def test_install_adds_filter_to_root(self) -> None:
        install_global_scrubber()
        scrub_filters = [f for f in self.root.filters if isinstance(f, SecretsScrubFilter)]
        self.assertEqual(len(scrub_filters), 1)


if __name__ == "__main__":
    unittest.main()

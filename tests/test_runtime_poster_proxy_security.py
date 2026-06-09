"""Tests runtime du proxy poster TMDb — securite (anti-SSRF, anti-open-relay, scrub key).

Verifie les garde-fous OPERATIONNELS du proxy `GET /api/poster?id=...&size=...` :

1. `size=w999` (hors whitelist) -> 400 validation
2. `size=../etc/passwd` (path traversal) -> 400 validation
3. `poster_path=https://evil.com/image.jpg` (parametre libre client) -> 400
   (anti-open-relay : tout parametre hors `id`/`size` est ignore et la
   validation `id` manquante declenche 400).
4. La cle TMDb (lue depuis `settings.json`) n'apparait JAMAIS dans les logs
   captures ni dans les headers de la reponse 400/200.

Les tests utilisent un fake handler et un fake TmdbClient pour ne pas dependre
du reseau ni de TMDb. Si le proxy n'existe pas (avant implementation), les
tests echouent franchement (`ImportError`/`AttributeError`).
"""

from __future__ import annotations

import io
import json
import logging
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Tuple
from unittest import mock

from cinesort.infra.integrations import poster_proxy


# ---------------------------------------------------------------------------
# Fake HTTP handler
# ---------------------------------------------------------------------------


class _FakeHandler:
    def __init__(self) -> None:
        self.status_code: int | None = None
        self.headers_sent: List[Tuple[str, str]] = []
        self.body = io.BytesIO()
        self.wfile = self.body
        self.headers = _CaseInsensitiveHeaders({})

    def send_response(self, code: int) -> None:
        self.status_code = code

    def send_header(self, key: str, value: str) -> None:
        self.headers_sent.append((key, str(value)))

    def end_headers(self) -> None:
        pass

    def _send_cors_headers(self) -> None:
        pass

    def _send_request_id_header(self) -> None:
        pass

    def all_header_values(self) -> str:
        """Concatene tous les headers (sortie pour assertion 'pas de cle')."""
        return " | ".join(f"{k}={v}" for k, v in self.headers_sent)

    def body_bytes(self) -> bytes:
        return self.body.getvalue()


class _CaseInsensitiveHeaders:
    def __init__(self, data: Dict[str, str]) -> None:
        self._data = {k.lower(): v for k, v in data.items()}

    def get(self, name: str, default: str = "") -> str:
        return self._data.get(name.lower(), default)


# ---------------------------------------------------------------------------
# Fake TmdbClient (pour les tests qui depasseraient la validation)
# ---------------------------------------------------------------------------


class _FakeTmdbClient:
    def __init__(self) -> None:
        self.calls = 0

    def get_movie_poster_path(self, movie_id: int) -> str | None:  # noqa: ARG002
        self.calls += 1
        return "/legit.jpg"


# ---------------------------------------------------------------------------
# Setup helper : settings.json avec cle FAUX-SECRETE pour traquer les fuites
# ---------------------------------------------------------------------------


SECRET_API_KEY = "SECRET_TMDB_KEY_SHOULD_NEVER_LEAK_42xyz"


def _setup_state_dir(state_dir: Path) -> Path:
    settings = {"tmdb_api_key": SECRET_API_KEY}
    (state_dir / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False),
        encoding="utf-8-sig",
    )
    cache_root = state_dir / "cache" / "posters"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


class _LogCapture:
    """Capture les logs sur tous les loggers cinesort.* pour grep posterieur."""

    def __init__(self) -> None:
        self.records: List[logging.LogRecord] = []
        self._handler = _CaptureHandler(self.records)

    def __enter__(self) -> "_LogCapture":
        root = logging.getLogger("cinesort")
        root.addHandler(self._handler)
        # S'assurer qu'on capture meme les DEBUG.
        self._prev_level = root.level
        root.setLevel(logging.DEBUG)
        return self

    def __exit__(self, *exc: Any) -> None:
        root = logging.getLogger("cinesort")
        root.removeHandler(self._handler)
        root.setLevel(self._prev_level)

    def all_messages(self) -> str:
        return " || ".join(r.getMessage() for r in self.records)


class _CaptureHandler(logging.Handler):
    def __init__(self, sink: List[logging.LogRecord]) -> None:
        super().__init__(level=logging.DEBUG)
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(record)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class PosterProxySecurityTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(prefix="poster_proxy_security_")
        self.state_dir = Path(self._tmp.name)
        self.cache_root = _setup_state_dir(self.state_dir)
        poster_proxy._tmdb_client_cache["client"] = None
        poster_proxy._tmdb_client_cache["api_key_hash"] = ""
        poster_proxy._tmdb_client_cache["state_dir"] = ""
        poster_proxy._session = None

    def tearDown(self) -> None:
        self._tmp.cleanup()
        poster_proxy._tmdb_client_cache["client"] = None
        poster_proxy._tmdb_client_cache["api_key_hash"] = ""
        poster_proxy._tmdb_client_cache["state_dir"] = ""
        poster_proxy._session = None

    # --- 1. size hors whitelist -> 400 ------------------------------------

    def test_size_w999_returns_400(self) -> None:
        """size=w999 (hors whitelist {w92,w185,w342,w500}) -> 400."""
        fake_client = _FakeTmdbClient()
        fake_session = mock.MagicMock()
        with mock.patch.object(
            poster_proxy, "_build_or_get_tmdb_client", return_value=fake_client
        ), mock.patch.object(poster_proxy, "_get_session", return_value=fake_session):
            handler = _FakeHandler()
            poster_proxy.serve_poster(
                handler,
                self.state_dir,
                self.cache_root,
                {"id": "42", "size": "w999"},
            )
        self.assertEqual(handler.status_code, 400)
        # Aucun appel TMDb : validation court-circuite avant fetch.
        self.assertEqual(fake_client.calls, 0)
        self.assertEqual(fake_session.get.call_count, 0)
        # Le body JSON contient category "validation".
        payload = json.loads(handler.body_bytes().decode("utf-8"))
        self.assertEqual(payload.get("ok"), False)
        self.assertEqual(payload.get("category"), "validation")

    # --- 2. path traversal -> 400 ----------------------------------------

    def test_size_path_traversal_returns_400(self) -> None:
        """size=../etc/passwd (path traversal) -> 400 + aucun fetch."""
        fake_client = _FakeTmdbClient()
        fake_session = mock.MagicMock()
        with mock.patch.object(
            poster_proxy, "_build_or_get_tmdb_client", return_value=fake_client
        ), mock.patch.object(poster_proxy, "_get_session", return_value=fake_session):
            handler = _FakeHandler()
            poster_proxy.serve_poster(
                handler,
                self.state_dir,
                self.cache_root,
                {"id": "42", "size": "../etc/passwd"},
            )
        self.assertEqual(handler.status_code, 400)
        # Aucun fichier ecrit hors cache_root.
        # On verifie qu'aucun chemin "etc/passwd" n'a ete cree sous state_dir.
        leaked = list(self.state_dir.rglob("passwd"))
        self.assertEqual(leaked, [], f"Path traversal a fuite: {leaked}")
        self.assertEqual(fake_client.calls, 0)
        self.assertEqual(fake_session.get.call_count, 0)

    # --- 3. poster_path=URL arbitraire -> 400 (anti-open-relay) -----------

    def test_arbitrary_poster_path_param_is_ignored_400(self) -> None:
        """Param `poster_path=https://evil.com/image.jpg` ignore + 400 (id manquant).

        Contrat anti-open-relay : seuls `id` et `size` sont consideres. Tout
        autre parametre est ignore silencieusement. Sans `id` valide -> 400.
        """
        fake_client = _FakeTmdbClient()
        fake_session = mock.MagicMock()
        with mock.patch.object(
            poster_proxy, "_build_or_get_tmdb_client", return_value=fake_client
        ), mock.patch.object(poster_proxy, "_get_session", return_value=fake_session):
            handler = _FakeHandler()
            poster_proxy.serve_poster(
                handler,
                self.state_dir,
                self.cache_root,
                {"poster_path": "https://evil.com/image.jpg", "size": "w185"},
            )
        self.assertEqual(
            handler.status_code,
            400,
            "Sans id valide, on rejette en validation. Le param libre 'poster_path' est ignore.",
        )
        # AUCUN appel reseau vers evil.com (ni TMDb).
        self.assertEqual(fake_session.get.call_count, 0)
        # Verifier qu'aucun call session.get ne contient "evil.com" en URL.
        for call in fake_session.get.call_args_list:
            url = call.args[0] if call.args else ""
            self.assertNotIn("evil.com", url)

    def test_arbitrary_poster_path_param_does_not_inject_in_url(self) -> None:
        """Meme avec id+size valides, poster_path libre n'apparait jamais dans l'URL TMDb."""
        # Pas de cache pre-peuple : on force le miss -> fetch.
        fake_client = _FakeTmdbClient()  # retourne /legit.jpg
        fake_session = mock.MagicMock()

        class _R:
            status_code = 200
            headers = {"Content-Type": "image/jpeg"}
            def iter_content(self, chunk_size: int = 8192):  # noqa: ARG002
                yield b"OK"
            def close(self) -> None:
                pass

        fake_session.get.return_value = _R()
        with mock.patch.object(
            poster_proxy, "_build_or_get_tmdb_client", return_value=fake_client
        ), mock.patch.object(poster_proxy, "_get_session", return_value=fake_session):
            handler = _FakeHandler()
            poster_proxy.serve_poster(
                handler,
                self.state_dir,
                self.cache_root,
                {
                    "id": "42",
                    "size": "w185",
                    "poster_path": "https://evil.com/image.jpg",
                    "url": "https://attacker.local/x",
                },
            )
        # L'URL fetchee doit etre l'URL TMDb officielle (construite cote serveur).
        self.assertEqual(fake_session.get.call_count, 1)
        called_url = fake_session.get.call_args.args[0]
        self.assertTrue(
            called_url.startswith("https://image.tmdb.org/t/p/w185/"),
            f"URL doit etre construite cote serveur, recu: {called_url}",
        )
        self.assertNotIn("evil.com", called_url)
        self.assertNotIn("attacker.local", called_url)

    # --- 4. Cle TMDb absente des logs et des headers --------------------

    def test_tmdb_key_not_in_logs_or_headers(self) -> None:
        """La cle TMDb (SECRET_TMDB_KEY...) n'apparait JAMAIS dans les logs/headers."""
        # On invoque 2 fois : un cas 400 (size invalide) + un cas 200 (cache hit).
        # Pre-peupler le cache pour le 2nd appel.
        size_dir = self.cache_root / "w92"
        size_dir.mkdir(parents=True, exist_ok=True)
        (size_dir / "42.jpg").write_bytes(b"FAKE")

        fake_client = _FakeTmdbClient()
        fake_session = mock.MagicMock()

        with _LogCapture() as logs, mock.patch.object(
            poster_proxy, "_build_or_get_tmdb_client", return_value=fake_client
        ), mock.patch.object(poster_proxy, "_get_session", return_value=fake_session):
            # Cas 1: 400
            h1 = _FakeHandler()
            poster_proxy.serve_poster(
                h1,
                self.state_dir,
                self.cache_root,
                {"id": "abc", "size": "w185"},
            )
            # Cas 2: 200 from cache
            h2 = _FakeHandler()
            poster_proxy.serve_poster(
                h2,
                self.state_dir,
                self.cache_root,
                {"id": "42", "size": "w92"},
            )

        # 1. Logs ne doivent jamais contenir la cle.
        log_blob = logs.all_messages()
        self.assertNotIn(
            SECRET_API_KEY,
            log_blob,
            f"Cle TMDb fuite dans les logs ! Extrait : {log_blob[:500]}",
        )
        # 2. Headers ne doivent jamais contenir la cle.
        h1_headers = h1.all_header_values()
        h2_headers = h2.all_header_values()
        self.assertNotIn(SECRET_API_KEY, h1_headers)
        self.assertNotIn(SECRET_API_KEY, h2_headers)
        # 3. Body de reponse ne doit jamais contenir la cle (cas 400 JSON).
        self.assertNotIn(SECRET_API_KEY.encode(), h1.body_bytes())
        self.assertNotIn(SECRET_API_KEY.encode(), h2.body_bytes())


if __name__ == "__main__":
    unittest.main()

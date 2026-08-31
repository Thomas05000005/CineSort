"""Tests runtime du proxy poster TMDb — cache disque + offline (iter12 / section TESTS).

Verifie la garantie OPERATIONNELLE du proxy `GET /api/poster?id=...&size=...`
sur 3 scenarios critiques :

1. 1ere requete : cache miss -> fetch TMDb mocke -> 200 + fichier ecrit dans
   le cache disque (`<state_dir>/cache/posters/<size>/<id>.<ext>`).
2. 2eme requete : cache hit -> 200 SANS appel reseau TMDb (`requests.get` mocke
   leve si invoque). Verifie la cle (`id`+`size`) et le mecanisme `resolve_cache_file`.
3. Offline : cache deja peuple, mais le client TMDb est coupe (mock leve
   `ConnectionError`). Le proxy doit servir 200 depuis le cache (fallback
   graceful) sans appeler la session HTTP.

Le proxy est invoque DIRECTEMENT (sans serveur HTTP) via `serve_poster()` avec
un fake handler, pour isoler le module testee. Aucune dependance reseau reelle.

Couches : test boite blanche en `infra` (mock du `TmdbClient` et de la session
`requests`). Conforme au pattern `tests/test_tmdb_client.py`.
"""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Dict, List, Tuple
from unittest import mock

from cinesort.infra.integrations import poster_proxy

# ---------------------------------------------------------------------------
# Fake HTTP handler (interface minimale exigee par serve_poster)
# ---------------------------------------------------------------------------


class _FakeHandler:
    """Reproduit l'interface BaseHTTPRequestHandler minimale.

    serve_poster() invoque : send_response, send_header, end_headers,
    wfile.write, headers.get, _send_cors_headers, _send_request_id_header.
    """

    def __init__(self, request_headers: Dict[str, str] | None = None) -> None:
        self.status_code: int | None = None
        self.headers_sent: List[Tuple[str, str]] = []
        self.body = io.BytesIO()
        self._ended = False
        # Headers entrants (If-None-Match etc.).
        self.headers = _CaseInsensitiveHeaders(request_headers or {})
        self.wfile = self.body  # serve_poster ecrit wfile.write(...)
        self.cors_calls = 0
        self.request_id_calls = 0

    def send_response(self, code: int) -> None:
        self.status_code = code

    def send_header(self, key: str, value: str) -> None:
        self.headers_sent.append((key, str(value)))

    def end_headers(self) -> None:
        self._ended = True

    def _send_cors_headers(self) -> None:
        self.cors_calls += 1

    def _send_request_id_header(self) -> None:
        self.request_id_calls += 1

    def header_value(self, name: str) -> str | None:
        for k, v in self.headers_sent:
            if k.lower() == name.lower():
                return v
        return None


class _CaseInsensitiveHeaders:
    """Mimic http.headers.Message.get (case insensitive)."""

    def __init__(self, data: Dict[str, str]) -> None:
        self._data = {k.lower(): v for k, v in data.items()}

    def get(self, name: str, default: str = "") -> str:
        return self._data.get(name.lower(), default)


# ---------------------------------------------------------------------------
# Fake TmdbClient
# ---------------------------------------------------------------------------


class _FakeTmdbClient:
    def __init__(self, poster_path: str | None = "/abc123.jpg") -> None:
        self.poster_path = poster_path
        self.calls = 0

    # `force_refresh` : signature alignee sur le vrai `TmdbClient` (le proxy le
    # transmet depuis le LOT 6).
    def get_movie_poster_path(self, movie_id: int, force_refresh: bool = False) -> str | None:  # noqa: ARG002
        self.calls += 1
        return self.poster_path


# ---------------------------------------------------------------------------
# Fake response requests.Session.get
# ---------------------------------------------------------------------------


class _FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        body: bytes = b"FAKE_JPEG_BYTES",
        content_type: str = "image/jpeg",
    ) -> None:
        self.status_code = status_code
        self._body = body
        self.headers = {"Content-Type": content_type}

    def iter_content(self, chunk_size: int = 8192):  # noqa: ARG002
        # Stream the body in one chunk for simplicity.
        if self._body:
            yield self._body

    def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# Setup helper : settings.json + cache dir minimal
# ---------------------------------------------------------------------------


def _setup_state_dir(state_dir: Path, api_key: str = "FAKE_KEY_XXX") -> Path:
    """Cree settings.json (utf-8-sig) + cache_root sous state_dir."""
    import json

    settings = {"tmdb_api_key": api_key}
    (state_dir / "settings.json").write_text(
        json.dumps(settings, ensure_ascii=False),
        encoding="utf-8-sig",
    )
    cache_root = state_dir / "cache" / "posters"
    cache_root.mkdir(parents=True, exist_ok=True)
    return cache_root


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class PosterProxyCacheTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(prefix="poster_proxy_cache_")
        self.state_dir = Path(self._tmp.name)
        self.cache_root = _setup_state_dir(self.state_dir)
        # Reinitialiser le cache module-level TmdbClient (pollue par d'autres tests).
        poster_proxy._tmdb_client_cache["client"] = None
        poster_proxy._tmdb_client_cache["api_key_hash"] = ""
        poster_proxy._tmdb_client_cache["state_dir"] = ""
        # Forcer reuse session a None pour pouvoir mocker proprement.
        poster_proxy._session = None

    def tearDown(self) -> None:
        self._tmp.cleanup()
        poster_proxy._tmdb_client_cache["client"] = None
        poster_proxy._tmdb_client_cache["api_key_hash"] = ""
        poster_proxy._tmdb_client_cache["state_dir"] = ""
        poster_proxy._session = None

    # --- 1. 1ere requete : 200 + fichier ecrit ----------------------------

    def test_first_request_writes_to_disk_cache(self) -> None:
        """Cache miss -> fetch TMDb mocke -> 200 + fichier ecrit dans le cache."""
        fake_client = _FakeTmdbClient(poster_path="/abc123.jpg")
        fake_response = _FakeResponse(
            status_code=200,
            body=b"\xff\xd8\xff\xe0FAKE_JPEG_BODY",
            content_type="image/jpeg",
        )
        fake_session = mock.MagicMock()
        fake_session.get.return_value = fake_response

        with (
            mock.patch.object(poster_proxy, "_build_or_get_tmdb_client", return_value=fake_client),
            mock.patch.object(poster_proxy, "_get_session", return_value=fake_session),
        ):
            handler = _FakeHandler()
            poster_proxy.serve_poster(
                handler,
                self.state_dir,
                self.cache_root,
                {"id": "42", "size": "w185"},
            )

        # Reponse 200 servie
        self.assertEqual(handler.status_code, 200, f"headers={handler.headers_sent}")
        # Fichier ecrit dans le cache disque
        expected_path = self.cache_root / "w185" / "42.jpg"
        self.assertTrue(
            expected_path.exists(),
            f"Cache file devait etre ecrit : {expected_path} (parent={list(expected_path.parent.iterdir()) if expected_path.parent.exists() else 'PAS DE PARENT'})",
        )
        # Le contenu disque = body fetche.
        self.assertEqual(expected_path.read_bytes(), b"\xff\xd8\xff\xe0FAKE_JPEG_BODY")
        # Le body HTTP servi = identique au fichier.
        self.assertEqual(handler.body.getvalue(), b"\xff\xd8\xff\xe0FAKE_JPEG_BODY")
        # 1 appel TMDb pour resoudre poster_path + 1 GET sur image.tmdb.org.
        self.assertEqual(fake_client.calls, 1)
        self.assertEqual(fake_session.get.call_count, 1)
        # URL TMDb construite cote serveur (anti-open-relay).
        call_args, call_kwargs = fake_session.get.call_args
        self.assertEqual(call_args[0], "https://image.tmdb.org/t/p/w185/abc123.jpg")
        self.assertFalse(call_kwargs.get("allow_redirects", True))

    # --- 2. 2eme requete : cache hit, AUCUN appel TMDb --------------------

    def test_second_request_uses_cache_no_tmdb_call(self) -> None:
        """Cache pre-peuple -> 200 sans aucun appel reseau TMDb."""
        # Peupler le cache disque
        size_dir = self.cache_root / "w92"
        size_dir.mkdir(parents=True, exist_ok=True)
        cached_file = size_dir / "777.png"
        cached_file.write_bytes(b"PRE_CACHED_PNG_BYTES")

        fake_client = _FakeTmdbClient(poster_path="/should-not-be-called.jpg")
        fake_session = mock.MagicMock()
        # Si appele, on leve pour prouver le no-outbound.
        fake_session.get.side_effect = AssertionError("session.get NE DOIT PAS etre appele en cas de cache hit")

        with (
            mock.patch.object(poster_proxy, "_build_or_get_tmdb_client", return_value=fake_client),
            mock.patch.object(poster_proxy, "_get_session", return_value=fake_session),
        ):
            handler = _FakeHandler()
            poster_proxy.serve_poster(
                handler,
                self.state_dir,
                self.cache_root,
                {"id": "777", "size": "w92"},
            )

        self.assertEqual(handler.status_code, 200, f"headers={handler.headers_sent}")
        # No outbound HTTP TMDb
        self.assertEqual(fake_session.get.call_count, 0, "Aucun GET TMDb attendu")
        # poster_path n'est pas resolu non plus puisque le cache hit court-circuite.
        self.assertEqual(fake_client.calls, 0, "Aucun appel TMDb poster_path attendu")
        # Body servi = body du cache disque.
        self.assertEqual(handler.body.getvalue(), b"PRE_CACHED_PNG_BYTES")
        # Content-Type adapte a l'extension (png -> image/png).
        ct = handler.header_value("Content-Type")
        self.assertEqual(ct, "image/png")

    # --- 3. Offline : cache peuple + TMDb down -> 200 from cache ---------

    def test_offline_with_populated_cache_serves_200(self) -> None:
        """Cache peuple + TMDb coupe -> 200 from cache (fallback graceful)."""
        # Pre-peupler le cache
        size_dir = self.cache_root / "w342"
        size_dir.mkdir(parents=True, exist_ok=True)
        (size_dir / "999.webp").write_bytes(b"OFFLINE_CACHE_WEBP")

        fake_client = _FakeTmdbClient(poster_path="/something.jpg")
        fake_session = mock.MagicMock()
        # Simule reseau coupe : meme avec session existante, le cache hit doit
        # primer (la session ne devrait meme pas etre invoquee).
        import requests as _requests

        fake_session.get.side_effect = _requests.ConnectionError("Simule reseau coupe / DNS fail")

        with (
            mock.patch.object(poster_proxy, "_build_or_get_tmdb_client", return_value=fake_client),
            mock.patch.object(poster_proxy, "_get_session", return_value=fake_session),
        ):
            handler = _FakeHandler()
            poster_proxy.serve_poster(
                handler,
                self.state_dir,
                self.cache_root,
                {"id": "999", "size": "w342"},
            )

        # 200 servi depuis cache (pas 503 OFFLINE)
        self.assertEqual(
            handler.status_code,
            200,
            f"Cache hit doit servir 200 meme si TMDb down. status={handler.status_code}",
        )
        self.assertEqual(handler.body.getvalue(), b"OFFLINE_CACHE_WEBP")
        # Aucun appel reseau (cache hit prime sur fetch).
        self.assertEqual(fake_session.get.call_count, 0)

    def test_cache_peuple_sans_cle_tmdb_sert_200_et_non_503(self) -> None:
        """Cache peuple + cle TMDb ABSENTE -> 200 depuis le cache, pas 503.

        C'est l'etat d'un profil dont le blob DPAPI ne se dechiffre plus, ou
        d'une cle effacee. `serve_poster` resolvait le client TMDb AVANT de
        consulter le cache et sortait en 503 : les jaquettes de TOUT le
        dashboard (9 sites du front : grille bibliotheque w185, fiche film
        w342, et le constructeur d'URL de core/dom.js) devenaient des erreurs
        alors que chaque image etait sur le disque.

        Asymetrie mesuree le 2026-08-28 en bac a sable : sur le MEME id en
        cache, l'appelant loopback recevait 503 et l'appelant cross-site
        recevait l'image — l'appelant le moins fiable etait le mieux servi.

        Le garde voisin `test_offline_with_populated_cache_serves_200` ne
        pouvait pas le voir : il MOCKE `_build_or_get_tmdb_client` pour rendre
        un client, donc il saute par-dessus l'endroit ou le defaut vit. Et
        `_setup_state_dir` pose toujours une cle par defaut : aucun test de ce
        fichier n'exercait l'etat « pas de cle ».
        """
        # Reecrit settings.json SANS cle (le defaut en pose une).
        cache_root = _setup_state_dir(self.state_dir, api_key="")
        size_dir = cache_root / "w342"
        size_dir.mkdir(parents=True, exist_ok=True)
        (size_dir / "777.webp").write_bytes(b"CACHE_SANS_CLE_TMDB")

        # Aucun mock : on injecte la panne a la couche de PRODUCTION, c'est-a-dire
        # l'absence reelle de cle dans settings.json.
        handler = _FakeHandler()
        poster_proxy.serve_poster(
            handler,
            self.state_dir,
            cache_root,
            {"id": "777", "size": "w342"},
        )

        self.assertEqual(
            handler.status_code,
            200,
            f"une jaquette DEJA en cache doit etre servie meme sans cle TMDb ; status={handler.status_code}",
        )
        self.assertEqual(handler.body.getvalue(), b"CACHE_SANS_CLE_TMDB")

    def test_sans_cle_tmdb_et_sans_cache_reste_503(self) -> None:
        """CONTRE-TEST : servir le cache sans cle ne doit pas transformer un
        cache MISS en autre chose. Sans cle et sans cache, le proxy reste
        inoperant et le dit — 503 « Proxy TMDb non configure ».
        """
        cache_root = _setup_state_dir(self.state_dir, api_key="")
        handler = _FakeHandler()
        poster_proxy.serve_poster(
            handler,
            self.state_dir,
            cache_root,
            {"id": "778", "size": "w342"},
        )
        self.assertEqual(handler.status_code, 503, f"status={handler.status_code}")


class TestAtomicWriteConcurrency(unittest.TestCase):
    """Regression CWE-362 : `_atomic_write` sous ecriture multi-thread.

    Le serveur cache est multi-thread (ThreadingHTTPServer). Avant le fix, le
    fichier `.tmp` portait un nom fixe (`<target>.tmp`) partage par toutes les
    requetes concurrentes visant le meme poster : deux writes simultanes
    s'entremelaient dans le meme `.tmp`, corrompant le contenu final.
    Le nom de `.tmp` est desormais unique par pid/thread/instant.
    Audit 2026-07-08.
    """

    def test_concurrent_writes_never_corrupt(self) -> None:
        import threading

        with TemporaryDirectory() as td:
            target = Path(td) / "posters" / "w342" / "42.webp"
            # Payloads distincts, chacun d'une taille suffisante pour rendre un
            # entrelacement visible s'il survenait.
            payloads = [bytes([i]) * 4096 for i in range(1, 33)]
            barrier = threading.Barrier(len(payloads))
            errors: List[BaseException] = []

            def _worker(payload: bytes) -> None:
                try:
                    barrier.wait()
                    poster_proxy._atomic_write(target, payload)
                except BaseException as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=_worker, args=(p,)) for p in payloads]
            for t in threads:
                t.start()
            for t in threads:
                t.join()

            self.assertEqual(errors, [], f"Ecritures concurrentes en erreur: {errors}")
            # Le contenu final doit etre EXACTEMENT l'un des payloads (jamais un
            # melange). Un octet uniforme = pas d'entrelacement.
            final = target.read_bytes()
            self.assertIn(final, payloads, "Contenu final corrompu (entrelacement .tmp)")
            # Aucun `.tmp` residuel ne doit subsister apres coup.
            leftovers = list(target.parent.glob("*.tmp*"))
            self.assertEqual(leftovers, [], f".tmp residuels: {leftovers}")


if __name__ == "__main__":
    unittest.main()

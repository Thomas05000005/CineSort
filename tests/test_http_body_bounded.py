"""Issues #425 #753 #798 #824 #423 #433 #539 #664 — la borne anti-OOM doit
etre appliquee A LA LECTURE du corps HTTP, pas apres.

Le motif remplace etait copie-colle 18 fois dans tmdb/omdb/jellyfin/radarr :

    _body = getattr(resp, "content", b"")
    if _body and len(_body) > 10_000_000:
        raise ValueError("Response too large")

Il ne protegeait de RIEN : `requests` a deja telecharge et alloue tout le
corps en RAM au retour de `session.get()`, `resp.content` ne fait que rendre
ce buffer. Le garde-fou n'evitait que le `json.loads`.

La preuve n'est donc PAS « une exception est levee » (l'ancien code la levait
aussi) mais « combien d'octets ont reellement ete lus depuis le socket ».
C'est ce que mesure `_CountingRaw.sent` dans tout ce fichier : avec l'ancienne
mecanique il vaudrait la taille TOTALE du corps hostile ; avec la nouvelle il
est plafonne a la borne + un chunk.
"""

from __future__ import annotations

import json
import unittest

import requests
from requests.structures import CaseInsensitiveDict

from cinesort.infra._http_utils import (
    DEFAULT_MAX_BODY_BYTES,
    STREAM_CHUNK_BYTES,
    ResponseTooLargeError,
    enforce_body_limit,
    get_bounded,
)

# Corps hostile : 5x la borne par defaut. Tout octet au-dela de la borne qui
# arrive quand meme dans le processus est exactement le bug qu'on corrige.
_HOSTILE_BYTES = 5 * DEFAULT_MAX_BODY_BYTES

# Tolerance de sur-lecture : on detecte le depassement sur le chunk qui le
# franchit, donc au plus un chunk au-dela de la borne.
_OVERREAD_TOLERANCE = STREAM_CHUNK_BYTES


class _CountingRaw:
    """Faux flux urllib3 qui COMPTE les octets reellement remis au client.

    Pas d'attribut `stream` : `requests.Response.iter_content` retombe alors
    sur `self.raw.read(chunk_size)`, ce qui rend la lecture deterministe.
    """

    def __init__(self, total: int) -> None:
        self.total = int(total)
        self.sent = 0
        self.closed = False
        self.read_calls = 0

    def read(self, amt: int | None = None, **_kwargs: object) -> bytes:
        self.read_calls += 1
        if self.closed:
            return b""
        remaining = self.total - self.sent
        if remaining <= 0:
            return b""
        n = remaining if amt is None else min(int(amt), remaining)
        self.sent += n
        return b"x" * n

    def close(self) -> None:
        self.closed = True


def _response(body_size: int, *, content_length: int | None = None, payload: object = None) -> requests.Response:
    """Vraie `requests.Response` adossee a un flux comptabilise."""
    resp = requests.Response()
    resp.status_code = 200
    resp.url = "https://api.example.test/x"
    headers: dict[str, str] = {"Content-Type": "application/json"}
    if content_length is not None:
        headers["Content-Length"] = str(content_length)
    resp.headers = CaseInsensitiveDict(headers)
    if payload is not None:
        raw_body = json.dumps(payload).encode("utf-8")
        resp.raw = _CountingRaw(len(raw_body))
        # On veut un vrai contenu exploitable : on remplace read() par un
        # debit du payload reel, tout en gardant le compteur.
        raw = resp.raw
        buf = {"data": raw_body}

        def _read(amt: int | None = None, **_kw: object) -> bytes:
            raw.read_calls += 1
            if raw.closed or not buf["data"]:
                return b""
            n = len(buf["data"]) if amt is None else min(int(amt), len(buf["data"]))
            chunk, buf["data"] = buf["data"][:n], buf["data"][n:]
            raw.sent += len(chunk)
            return chunk

        raw.read = _read  # type: ignore[method-assign]
    else:
        resp.raw = _CountingRaw(body_size)
    return resp


class EnforceBodyLimitTests(unittest.TestCase):
    """Le coeur du correctif : la borne agit pendant la lecture du flux."""

    def test_oversized_stream_is_abandoned_before_full_download(self) -> None:
        limit = 1_000_000
        resp = _response(_HOSTILE_BYTES)
        raw = resp.raw

        with self.assertRaises(ResponseTooLargeError):
            enforce_body_limit(resp, max_bytes=limit)

        # LA preuve du correctif. Avec la borne post-materialisation, requests
        # aurait deja lu les 50 Mo et `sent` vaudrait _HOSTILE_BYTES.
        self.assertLessEqual(
            raw.sent,
            limit + _OVERREAD_TOLERANCE,
            f"{raw.sent} octets lus pour une borne de {limit} : le corps a ete telecharge avant d'etre refuse",
        )
        self.assertLess(raw.sent, _HOSTILE_BYTES, "le corps hostile a ete lu en entier")

    def test_oversized_stream_closes_the_connection(self) -> None:
        resp = _response(_HOSTILE_BYTES)
        raw = resp.raw
        with self.assertRaises(ResponseTooLargeError):
            enforce_body_limit(resp, max_bytes=1_000_000)
        self.assertTrue(raw.closed, "la connexion doit etre coupee, sinon le reste du corps arrive quand meme")

    def test_declared_content_length_refuses_before_reading_one_byte(self) -> None:
        resp = _response(_HOSTILE_BYTES, content_length=_HOSTILE_BYTES)
        raw = resp.raw
        with self.assertRaises(ResponseTooLargeError) as ctx:
            enforce_body_limit(resp, max_bytes=1_000_000)
        self.assertTrue(ctx.exception.declared)
        self.assertEqual(raw.sent, 0, "un Content-Length hors borne doit etre refuse sans lire le corps")

    def test_lying_content_length_is_still_caught_by_the_counter(self) -> None:
        """Content-Length menteur (ou taille compressee) : le compteur tranche."""
        resp = _response(_HOSTILE_BYTES, content_length=12)
        raw = resp.raw
        with self.assertRaises(ResponseTooLargeError):
            enforce_body_limit(resp, max_bytes=1_000_000)
        self.assertLessEqual(raw.sent, 1_000_000 + _OVERREAD_TOLERANCE)

    def test_body_under_the_limit_stays_fully_usable(self) -> None:
        """Non-regression : une reponse normale se parse comme avant.

        Cette assertion doit rester VERTE des deux cotes du correctif.
        """
        resp = _response(0, payload={"ServerName": "Test", "Version": "10.9"})
        enforce_body_limit(resp, max_bytes=DEFAULT_MAX_BODY_BYTES)
        self.assertEqual(resp.json(), {"ServerName": "Test", "Version": "10.9"})
        self.assertEqual(resp.content, json.dumps({"ServerName": "Test", "Version": "10.9"}).encode("utf-8"))
        self.assertIn("ServerName", resp.text)

    def test_error_is_a_valueerror(self) -> None:
        """Non-regression de contrat : les 18 sites remplaces levaient
        `ValueError` et sont entoures de `except (..., ValueError, ...)`.
        """
        self.assertTrue(issubclass(ResponseTooLargeError, ValueError))
        exc = ResponseTooLargeError(limit=10, observed=99)
        self.assertIn("Response too large", str(exc))
        self.assertEqual(exc.limit, 10)

    def test_rejects_a_nonsense_limit(self) -> None:
        with self.assertRaises(ValueError):
            enforce_body_limit(_response(0, payload={}), max_bytes=0)


class GetBoundedTests(unittest.TestCase):
    def test_stream_is_requested(self) -> None:
        """Sans `stream=True`, requests materialise tout avant de rendre la
        main et la borne redeviendrait cosmetique."""
        captured: dict = {}

        class _Session:
            def get(self, url: str, **kwargs: object) -> requests.Response:
                captured["url"] = url
                captured["kwargs"] = kwargs
                return _response(0, payload={"ok": True})

        resp = get_bounded(_Session(), "https://api.example.test/x", timeout=5.0)
        self.assertEqual(resp.json(), {"ok": True})
        self.assertIs(captured["kwargs"].get("stream"), True)
        self.assertEqual(captured["kwargs"].get("timeout"), 5.0)

    def test_oversized_response_closes_and_raises(self) -> None:
        raw_holder: dict = {}

        class _Session:
            def get(self, url: str, **kwargs: object) -> requests.Response:
                resp = _response(_HOSTILE_BYTES)
                raw_holder["raw"] = resp.raw
                return resp

        with self.assertRaises(ResponseTooLargeError):
            get_bounded(_Session(), "https://api.example.test/x", max_bytes=500_000)
        self.assertTrue(raw_holder["raw"].closed)
        self.assertLessEqual(raw_holder["raw"].sent, 500_000 + _OVERREAD_TOLERANCE)


class _RecordingSession:
    """Remplace `client._session.get/post/delete` en gardant un vrai flux."""

    def __init__(self, *, hostile: bool, payload: object = None) -> None:
        self.hostile = hostile
        self.payload = payload
        self.calls: list[dict] = []
        self.raws: list[_CountingRaw] = []

    def __call__(self, url: str, **kwargs: object) -> requests.Response:
        self.calls.append({"url": url, "kwargs": kwargs})
        resp = _response(_HOSTILE_BYTES) if self.hostile else _response(0, payload=self.payload)
        self.raws.append(resp.raw)
        return resp

    @property
    def bytes_read(self) -> int:
        return sum(raw.sent for raw in self.raws)


class ClientsAreRoutedThroughTheBoundedReadTests(unittest.TestCase):
    """La grappe entiere : chaque client doit passer par le helper.

    Un client qui redeviendrait un `session.get()` nu suivi d'un
    `len(resp.content)` re-telechargerait tout le corps hostile : ces tests
    mesurent les octets lus, pas la presence d'une exception.
    """

    def _assert_bounded(self, session: _RecordingSession) -> None:
        self.assertGreater(session.bytes_read, 0, "aucune lecture : le test ne prouve rien")
        self.assertLessEqual(
            session.bytes_read,
            len(session.raws) * (DEFAULT_MAX_BODY_BYTES + _OVERREAD_TOLERANCE),
            f"{session.bytes_read} octets lus : le corps hostile a ete materialise avant d'etre refuse",
        )
        for call in session.calls:
            self.assertIs(
                call["kwargs"].get("stream"),
                True,
                f"appel sans stream=True, la borne redevient cosmetique : {call}",
            )

    # -- Jellyfin (#425) --------------------------------------------------

    def test_jellyfin_validate_connection(self) -> None:
        from cinesort.infra.jellyfin_client import JellyfinClient

        client = JellyfinClient("http://jelly.local", "key", timeout_s=5.0)
        self.addCleanup(client.close)
        session = _RecordingSession(hostile=True)
        client._session.get = session  # type: ignore[method-assign]

        res = client.validate_connection()

        self.assertFalse(res.get("ok"))
        self._assert_bounded(session)

    def test_jellyfin_nominal_response_still_parsed(self) -> None:
        from cinesort.infra.jellyfin_client import JellyfinClient

        client = JellyfinClient("http://jelly.local", "key", timeout_s=5.0)
        self.addCleanup(client.close)
        client._session.get = _RecordingSession(  # type: ignore[method-assign]
            hostile=False, payload={"Items": [{"Id": "a", "Name": "Films", "CollectionType": "movies"}]}
        )

        libs = client.get_libraries("u1")

        self.assertEqual(libs, [{"id": "a", "name": "Films", "collection_type": "movies"}])

    # -- Radarr (#433 / #753) ---------------------------------------------

    def test_radarr_get_movies(self) -> None:
        from cinesort.infra.radarr_client import RadarrClient, RadarrError

        client = RadarrClient("http://radarr.local:7878", "key", timeout_s=5.0)
        self.addCleanup(client.close)
        session = _RecordingSession(hostile=True)
        client._session.get = session  # type: ignore[method-assign]

        with self.assertRaises(RadarrError):
            client.get_movies()
        self._assert_bounded(session)

    def test_radarr_nominal_response_still_parsed(self) -> None:
        from cinesort.infra.radarr_client import RadarrClient

        client = RadarrClient("http://radarr.local:7878", "key", timeout_s=5.0)
        self.addCleanup(client.close)
        client._session.get = _RecordingSession(  # type: ignore[method-assign]
            hostile=False, payload=[{"id": 7, "title": "Heat", "year": 1995, "tmdbId": 949}]
        )

        movies = client.get_movies()

        self.assertEqual(len(movies), 1)
        self.assertEqual(movies[0]["title"], "Heat")
        self.assertEqual(movies[0]["tmdb_id"], 949)

    # -- TMDb (#798) ------------------------------------------------------

    def test_tmdb_search_movie(self) -> None:
        import tempfile
        from pathlib import Path

        from cinesort.infra.tmdb_client import TmdbClient

        tmp = tempfile.TemporaryDirectory(prefix="cinesort_bounded_tmdb_")
        self.addCleanup(tmp.cleanup)
        client = TmdbClient(api_key="k", cache_path=Path(tmp.name) / "c.json", timeout_s=5.0)
        session = _RecordingSession(hostile=True)
        client._session.get = session  # type: ignore[method-assign]

        # Fallback gracieux documente : la recherche rend une liste vide.
        self.assertEqual(client.search_movie("Heat", 1995), [])
        self._assert_bounded(session)
        # Une reponse hors borne n'est PAS une panne serveur : le breaker ne
        # doit pas se fermer sur elle (cf CircuitBreaker.call).
        self.assertEqual(client._breaker.failures, 0)

    def test_tmdb_nominal_response_still_parsed(self) -> None:
        import tempfile
        from pathlib import Path

        from cinesort.infra.tmdb_client import TmdbClient

        tmp = tempfile.TemporaryDirectory(prefix="cinesort_bounded_tmdb_ok_")
        self.addCleanup(tmp.cleanup)
        client = TmdbClient(api_key="k", cache_path=Path(tmp.name) / "c.json", timeout_s=5.0)
        client._session.get = _RecordingSession(  # type: ignore[method-assign]
            hostile=False,
            payload={"results": [{"id": 949, "title": "Heat", "release_date": "1995-12-15", "popularity": 20.0}]},
        )

        results = client.search_movie("Heat", 1995)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].id, 949)
        self.assertEqual(results[0].title, "Heat")

    # -- OMDb (#824) ------------------------------------------------------

    def test_omdb_find_by_imdb_id(self) -> None:
        import tempfile
        from pathlib import Path

        from cinesort.infra.omdb_client import OmdbClient

        tmp = tempfile.TemporaryDirectory(prefix="cinesort_bounded_omdb_")
        self.addCleanup(tmp.cleanup)
        client = OmdbClient(api_key="k", cache_path=Path(tmp.name) / "c.json", timeout_s=5.0)
        session = _RecordingSession(hostile=True)
        client._session.get = session  # type: ignore[method-assign]

        self.assertIsNone(client.find_by_imdb_id("tt0113277"))
        self._assert_bounded(session)

    def test_omdb_test_connection_reports_invalid_response(self) -> None:
        import tempfile
        from pathlib import Path

        from cinesort.infra.omdb_client import OmdbClient

        tmp = tempfile.TemporaryDirectory(prefix="cinesort_bounded_omdb_tc_")
        self.addCleanup(tmp.cleanup)
        client = OmdbClient(api_key="k", cache_path=Path(tmp.name) / "c.json", timeout_s=5.0)
        session = _RecordingSession(hostile=True)
        client._session.get = session  # type: ignore[method-assign]

        res = client.test_connection()

        self.assertFalse(res.get("ok"))
        self.assertEqual(res.get("error_code"), "invalid_resp")
        self._assert_bounded(session)


if __name__ == "__main__":
    unittest.main()

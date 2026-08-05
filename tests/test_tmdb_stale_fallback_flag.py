"""Issue #413 — le repli sur cache TMDb EXPIRE ne doit plus etre silencieux.

Quand TMDb ne repond pas (timeout, 5xx, circuit ouvert), `TmdbClient` sert
l'entree de cache meme perimee. C'est le bon comportement offline-first, mais
il etait indistinguable d'une reponse fraiche : l'appelant recevait une valeur
ordinaire, l'UI l'affichait sans reserve, et l'utilisateur choisissait un titre
ou un poster potentiellement perime en croyant interroger TMDb.

Un echec presente comme un succes est proscrit dans ce depot. Les tests
ci-dessous verifient les deux moitiees de la chaine :
- le client garde trace du repli et de la DATE de la donnee servie ;
- `library/search_tmdb` transmet ce fait a l'UI (`stale`, `stale_cached_at`).
"""

from __future__ import annotations

import json
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict

import requests

from cinesort.infra.tmdb_client import TmdbClient
from cinesort.ui.api import tmdb_support

_SEARCH_PAYLOAD = [
    {
        "id": 949,
        "title": "Heat",
        "year": 1995,
        "original_title": "Heat",
        "popularity": 20.0,
        "vote_count": 100,
        "vote_average": 8.0,
        "poster_path": "/p.jpg",
    }
]


def _expired_cache_file(path: Path, key: str, value: Any, *, cached_at: float) -> None:
    path.write_text(
        json.dumps({key: {"_cached_at": cached_at, "value": value}}, ensure_ascii=False),
        encoding="utf-8",
    )


class _DownSession:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, url: str, **_kw: Any) -> Any:
        self.calls += 1
        raise requests.ConnectionError("TMDb injoignable")


class StaleFallbackIsReportedTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_413_")
        self.addCleanup(self._tmp.cleanup)
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"
        # 60 jours : au-dela du TTL search le plus long (30 j / 4 -> 7,5 j).
        self.cached_at = time.time() - 60 * 24 * 3600

    def _client(self) -> TmdbClient:
        return TmdbClient(api_key="k", cache_path=self.cache_path, timeout_s=2.0)

    def test_search_signale_le_repli_et_la_date(self) -> None:
        """ROUGE avant : la liste rendue etait identique a une reponse fraiche."""
        _expired_cache_file(self.cache_path, "search|fr-FR|heat|1995", _SEARCH_PAYLOAD, cached_at=self.cached_at)
        client = self._client()
        client._session.get = _DownSession()  # type: ignore[method-assign]

        results = client.search_movie("Heat", 1995)

        self.assertEqual(len(results), 1, "le fallback gracieux doit continuer de servir le cache")
        report = client.stale_fallback_report()
        self.assertEqual(report["count"], 1, "le repli sur cache expire n'a laisse aucune trace")
        self.assertEqual(report["last_key"], "search|fr-FR|heat|1995")
        self.assertAlmostEqual(float(report["last_cached_at"]), self.cached_at, places=3)

    def test_detail_signale_le_repli(self) -> None:
        _expired_cache_file(self.cache_path, "movie|949", {"poster_path": "/old.jpg"}, cached_at=self.cached_at)
        client = self._client()
        client._session.get = _DownSession()  # type: ignore[method-assign]

        self.assertEqual(client.get_movie_poster_path(949), "/old.jpg")

        report = client.stale_fallback_report()
        self.assertEqual(report["count"], 1)
        self.assertEqual(report["last_key"], "movie|949")

    def test_alternative_titles_signale_le_repli(self) -> None:
        _expired_cache_file(
            self.cache_path,
            "movie_alt_titles|949",
            [{"iso_3166_1": "FR", "title": "Heat FR", "type": ""}],
            cached_at=self.cached_at,
        )
        client = self._client()
        client._session.get = _DownSession()  # type: ignore[method-assign]

        titles = client.get_alternative_titles(949)

        self.assertEqual(len(titles), 1)
        self.assertEqual(client.stale_fallback_report()["count"], 1)

    # ---- non-regression : rien de faux quand tout va bien ----

    def test_une_reponse_fraiche_nest_pas_marquee_stale(self) -> None:
        client = self._client()

        class _Ok:
            def __init__(self) -> None:
                self.status_code = 200

            def json(self) -> Dict[str, Any]:
                return {"results": [{"id": 949, "title": "Heat", "release_date": "1995-12-15"}]}

            def raise_for_status(self) -> None:
                return None

        client._session.get = lambda url, **_kw: _Ok()  # type: ignore[method-assign, assignment]

        self.assertEqual(len(client.search_movie("Heat", 1995)), 1)
        self.assertEqual(client.stale_fallback_report()["count"], 0)

    def test_pas_de_cache_du_tout_ne_marque_rien(self) -> None:
        client = self._client()
        client._session.get = _DownSession()  # type: ignore[method-assign]

        self.assertEqual(client.search_movie("Inconnu", None), [])
        self.assertEqual(client.stale_fallback_report()["count"], 0)


class _FakeApi:
    def __init__(self, state_dir: str) -> None:
        self._state_dir = state_dir

    def _internal_settings(self) -> Dict[str, Any]:
        return {
            "tmdb_api_key": "REALKEY",
            "state_dir": self._state_dir,
            "tmdb_timeout_s": 1.0,
            "tmdb_cache_ttl_days": 30,
        }


class SearchTmdbEndpointExposesStaleTests(unittest.TestCase):
    """Le fait doit remonter jusqu'a la reponse lue par l'UI, pas rester dans infra."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_413api_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = Path(self._tmp.name)
        self.cache_path = self.state_dir / "tmdb_cache.json"
        self.cached_at = time.time() - 60 * 24 * 3600

    def _call(self, *, session_factory: Any) -> Dict[str, Any]:
        from unittest.mock import patch

        # `side_effect=` et non `new=` : `new=` installe une FONCTION comme
        # attribut de classe, que Python relie ensuite (`self` en 1er argument)
        # — l'appel partait alors en TypeError, avale par le fallback gracieux,
        # et le test « stale » aurait ete vert sans jamais lire le cache.
        with patch("requests.Session.get", side_effect=session_factory):
            return tmdb_support.search_tmdb(_FakeApi(str(self.state_dir)), "Heat", 1995)

    def test_reponse_de_secours_est_annoncee_a_l_ui(self) -> None:
        """ROUGE avant : `{"ok": True, "results": [...]}` sans aucune reserve."""
        _expired_cache_file(self.cache_path, "search|fr-FR|heat|1995", _SEARCH_PAYLOAD, cached_at=self.cached_at)

        def _down(url: str, **_kw: Any) -> Any:
            raise requests.ConnectionError("TMDb injoignable")

        res = self._call(session_factory=_down)

        self.assertIs(res.get("ok"), True)
        self.assertEqual(res.get("count"), 1, "les resultats de secours restent servis")
        self.assertIs(res.get("stale"), True, "l'UI ne peut pas distinguer secours et frais")
        self.assertAlmostEqual(float(res["stale_cached_at"]), self.cached_at, places=3)

    def test_reponse_fraiche_nest_pas_annoncee_stale(self) -> None:
        class _Ok:
            def __init__(self, url: str, **_kw: Any) -> None:
                self.status_code = 200
                self._is_search = "/search/" in url

            def json(self) -> Dict[str, Any]:
                if self._is_search:
                    return {"results": [{"id": 949, "title": "Heat", "release_date": "1995-12-15"}]}
                return {"overview": "o", "runtime": 170}

            def raise_for_status(self) -> None:
                return None

        res = self._call(session_factory=lambda url, **kw: _Ok(url, **kw))

        self.assertIs(res.get("ok"), True)
        self.assertEqual(res.get("count"), 1)
        self.assertIs(res.get("stale"), False)
        self.assertIsNone(res.get("stale_cached_at"))


class StaleTimestampHonestyTests(unittest.TestCase):
    """Une date inconnue doit rester inconnue (pas de valeur plausible inventee)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_413ts_")
        self.addCleanup(self._tmp.cleanup)
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"

    def test_entree_ancien_format_rend_une_date_nulle(self) -> None:
        # Ancien format : valeur directe, sans `_cached_at`.
        self.cache_path.write_text(
            json.dumps({"search|fr-FR|heat|1995": _SEARCH_PAYLOAD}, ensure_ascii=False),
            encoding="utf-8",
        )
        client = TmdbClient(api_key="k", cache_path=self.cache_path, timeout_s=2.0)
        # L'ancien format est considere FRAIS par `_cache_get` : on force le
        # chemin de repli en vidant la memoire, le disque restant seul porteur.
        client._cache.clear()

        def _down(url: str, **_kw: Any) -> Any:
            raise requests.ConnectionError("TMDb injoignable")

        client._session.get = _down  # type: ignore[method-assign]

        results = client.search_movie("Heat", 1995)

        self.assertEqual(len(results), 1)
        report = client.stale_fallback_report()
        self.assertEqual(report["count"], 1)
        self.assertIsNone(report["last_cached_at"], "une date absente ne doit pas etre remplacee")

    def test_cache_get_stale_conserve_son_contrat(self) -> None:
        """`_cache_get_stale` (3 appelants historiques) rend toujours la VALEUR."""
        cached_at = time.time() - 1000.0
        self.cache_path.write_text(
            json.dumps({"movie|1": {"_cached_at": cached_at, "value": {"poster_path": "/a.jpg"}}}),
            encoding="utf-8",
        )
        client = TmdbClient(api_key="k", cache_path=self.cache_path, timeout_s=2.0)

        value = client._cache_get_stale("movie|1")
        self.assertEqual(value, {"poster_path": "/a.jpg"})
        self.assertIsNone(client._cache_get_stale("movie|inconnu"))


if __name__ == "__main__":
    unittest.main()

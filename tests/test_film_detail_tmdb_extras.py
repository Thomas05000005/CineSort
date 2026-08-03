"""AUDIT F20 — la fiche film doit utiliser la cle TMDb EN CLAIR.

`film_support._fetch_tmdb_extras` lisait `api.settings.get_settings()`, dont
`tmdb_api_key` est MASQUEE ("••••••••") depuis SEC-H2. Le masque etant truthy,
le garde `if not api_key` ne stoppait rien : la cle masquee partait vers
api.themoviedb.org -> 401 -> runtime/director/overview systematiquement null
pour tout utilisateur ayant enregistre une cle TMDb.

Correctif : `api._internal_settings()` (secrets en clair) + garde explicite sur
le masque residuel. Miroir de tmdb_support.py:103 et library_actions_support.py:661.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from cinesort.ui.api import film_support
from cinesort.ui.api.settings_support import _SECRET_MASK

_TMDB_ID = 603  # The Matrix


class _FakeSettingsFacade:
    def __init__(self, payload: Dict[str, Any]) -> None:
        self._payload = payload
        self.calls = 0

    def get_settings(self) -> Dict[str, Any]:
        self.calls += 1
        return dict(self._payload)


class _FakeApi:
    """Double d'API : distingue explicitement le payload MASQUE du payload INTERNE."""

    def __init__(self, masked: Dict[str, Any], internal: Dict[str, Any]) -> None:
        self.settings = _FakeSettingsFacade(masked)
        self._internal = internal
        self.internal_calls = 0

    def _internal_settings(self) -> Dict[str, Any]:
        self.internal_calls += 1
        return dict(self._internal)


class _FakeTmdbClient:
    """Stub TmdbClient : aucune I/O reseau, memorise la cle recue."""

    constructed_with: List[Dict[str, Any]] = []

    def __init__(self, **kwargs: Any) -> None:
        _FakeTmdbClient.constructed_with.append(dict(kwargs))

    def get_movie_runtime(self, movie_id: int) -> Optional[int]:
        return None  # cache froid : le runtime viendra du GET HTTP

    def _get_movie_detail_cached(self, movie_id: int) -> Optional[Dict[str, Any]]:
        return None

    def flush(self) -> None:
        return None


class _FakeResponse:
    def __init__(self, status_code: int, payload: Dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> Dict[str, Any]:
        return self._payload


_DETAIL_PAYLOAD = {
    "overview": "o",
    "runtime": 148,
    "credits": {"crew": [{"job": "Producer", "name": "Z"}, {"job": "Director", "name": "X"}]},
}


class FetchTmdbExtrasSecretTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(prefix="cinesort_f20_")
        self.state_dir = str(Path(self._tmp.name))
        _FakeTmdbClient.constructed_with = []
        self.captured: List[Dict[str, Any]] = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _fake_get(self, url: str, params: Optional[Dict[str, Any]] = None, timeout: Any = None) -> _FakeResponse:
        self.captured.append(dict(params or {}))
        return _FakeResponse(200, _DETAIL_PAYLOAD)

    def _run(self, api: _FakeApi) -> Dict[str, Any]:
        with (
            patch("cinesort.infra.tmdb_client.TmdbClient", _FakeTmdbClient),
            patch("requests.get", side_effect=self._fake_get),
        ):
            return film_support._fetch_tmdb_extras(api, _TMDB_ID)

    def test_extras_utilisent_la_cle_en_clair(self) -> None:
        """ROUGE avant le fix : la cle envoyee a TMDb est le masque -> 401 -> extras null."""
        api = _FakeApi(
            masked={"tmdb_api_key": _SECRET_MASK, "state_dir": self.state_dir},
            internal={"tmdb_api_key": "REALKEY", "state_dir": self.state_dir, "tmdb_timeout_s": 1.0},
        )

        out = self._run(api)

        self.assertEqual(len(self.captured), 1, "un seul GET detail attendu")
        self.assertEqual(
            self.captured[0].get("api_key"),
            "REALKEY",
            "la requete TMDb doit porter la cle EN CLAIR, pas le masque",
        )
        self.assertEqual(_FakeTmdbClient.constructed_with[0].get("api_key"), "REALKEY")
        self.assertEqual(out["director"], "X")
        self.assertEqual(out["overview"], "o")
        self.assertEqual(out["runtime"], 148)

    def test_masque_ne_declenche_aucun_http(self) -> None:
        """ROUGE avant le fix : le masque est truthy -> requetes vouees au 401."""
        api = _FakeApi(
            masked={"tmdb_api_key": _SECRET_MASK, "state_dir": self.state_dir},
            internal={"tmdb_api_key": _SECRET_MASK, "state_dir": self.state_dir},
        )

        out = self._run(api)

        self.assertEqual(self.captured, [], "aucune requete HTTP ne doit partir avec le masque")
        self.assertEqual(_FakeTmdbClient.constructed_with, [], "pas de TmdbClient construit avec le masque")
        self.assertEqual(out, {"runtime": None, "director": None, "overview": None})

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    def test_sans_cle_configuree_retourne_extras_vides_sans_http(self) -> None:
        api = _FakeApi(
            masked={"tmdb_api_key": "", "state_dir": self.state_dir},
            internal={"tmdb_api_key": "", "state_dir": self.state_dir},
        )

        out = self._run(api)

        self.assertEqual(self.captured, [])
        self.assertEqual(out, {"runtime": None, "director": None, "overview": None})

    def test_tmdb_id_invalide_court_circuite(self) -> None:
        api = _FakeApi(
            masked={"tmdb_api_key": _SECRET_MASK, "state_dir": self.state_dir},
            internal={"tmdb_api_key": "REALKEY", "state_dir": self.state_dir},
        )

        with (
            patch("cinesort.infra.tmdb_client.TmdbClient", _FakeTmdbClient),
            patch("requests.get", side_effect=self._fake_get),
        ):
            out = film_support._fetch_tmdb_extras(api, 0)

        self.assertEqual(out, {"runtime": None, "director": None, "overview": None})
        self.assertEqual(self.captured, [])
        self.assertEqual(api.internal_calls, 0)


class FetchTmdbExtrasCacheTests(unittest.TestCase):
    """REVUE R1 — le correctif F20 a debloque un chemin NON CACHE.

    Avant F20 la cle masquee rendait ces requetes instantanees (401). Une fois la
    vraie cle passee, director/overview partaient en GET reel a CHAQUE appel :
    aucun cache ne les portait (`_get_movie_detail_cached` ne stocke ni l'un ni
    l'autre et ne demande meme pas append_to_response=credits). L'amplificateur
    n'est pas la fiche film mais la vue Doublons, qui lance UN
    library/get_film_full PAR GROUPE en parallele (Promise.allSettled).

    Ces tests utilisent le VRAI TmdbClient (cache disque reel) et ne stubbent que
    la couche HTTP, pour que le compteur de requetes soit celui de la production.
    """

    def setUp(self) -> None:
        self._tmp = TemporaryDirectory(prefix="cinesort_f20r1_")
        self.state_dir = str(Path(self._tmp.name))
        self.detail_calls = 0
        self.raw_calls = 0

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _api(self) -> _FakeApi:
        return _FakeApi(
            masked={"tmdb_api_key": _SECRET_MASK, "state_dir": self.state_dir},
            internal={"tmdb_api_key": "REALKEY", "state_dir": self.state_dir, "tmdb_timeout_s": 1.0},
        )

    def _fake_http_get(self, _self: Any, url: str, params: Any = None, **_kw: Any) -> _FakeResponse:
        """Couche HTTP interne du VRAI TmdbClient (endpoint /movie/{id})."""
        self.detail_calls += 1
        return _FakeResponse(200, _DETAIL_PAYLOAD)

    def _fake_raw_get(self, url: str, params: Any = None, timeout: Any = None, **_kw: Any) -> _FakeResponse:
        """GET direct de _fetch_tmdb_extras (append_to_response=credits)."""
        self.raw_calls += 1
        return _FakeResponse(200, _DETAIL_PAYLOAD)

    def _call(self) -> Dict[str, Any]:
        with (
            patch("cinesort.infra.tmdb_client.TmdbClient._http_get", self._fake_http_get),
            patch("requests.get", side_effect=self._fake_raw_get),
        ):
            return film_support._fetch_tmdb_extras(self._api(), _TMDB_ID)

    def test_director_et_overview_ne_repartent_pas_en_http_a_chaque_appel(self) -> None:
        """ROUGE avant : 3 appels = 3 GET TMDb (N groupes de doublons = N GET)."""
        outs = [self._call() for _ in range(3)]

        self.assertEqual(
            self.raw_calls,
            1,
            f"director/overview refetches a chaque appel ({self.raw_calls} GET pour 3 appels)",
        )
        for out in outs:
            self.assertEqual(out["director"], "X")
            self.assertEqual(out["overview"], "o")
            self.assertEqual(out["runtime"], 148)

    def test_le_cache_extras_est_persiste_dans_tmdb_cache_json(self) -> None:
        self._call()

        cache_file = Path(self.state_dir) / "tmdb_cache.json"
        self.assertTrue(cache_file.is_file())
        keys = set(json.loads(cache_file.read_text(encoding="utf-8")).keys())
        self.assertIn(f"movie_extras|{_TMDB_ID}", keys)

    def test_un_echec_http_nest_pas_memorise(self) -> None:
        """Un 401/5xx doit etre reessaye au prochain appel, pas fige pour le TTL."""

        def failing_get(url: str, params: Any = None, timeout: Any = None, **_kw: Any) -> _FakeResponse:
            self.raw_calls += 1
            return _FakeResponse(401, {})

        with (
            patch("cinesort.infra.tmdb_client.TmdbClient._http_get", self._fake_http_get),
            patch("requests.get", side_effect=failing_get),
        ):
            first = film_support._fetch_tmdb_extras(self._api(), _TMDB_ID)
            second = film_support._fetch_tmdb_extras(self._api(), _TMDB_ID)

        self.assertEqual(self.raw_calls, 2, "un echec ne doit pas etre cache")
        self.assertIsNone(first["director"])
        self.assertIsNone(second["director"])

    # ---- non-regression (VERT des deux cotes de la mutation) ----

    def test_extras_corrects_au_premier_appel(self) -> None:
        out = self._call()

        self.assertEqual(out, {"runtime": 148, "director": "X", "overview": "o"})
        self.assertEqual(self.raw_calls, 1)


if __name__ == "__main__":
    unittest.main()

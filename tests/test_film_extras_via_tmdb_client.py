"""Issue #599 — la fiche film ne doit plus contourner le client TMDb.

`film_support._fetch_tmdb_extras` faisait un `requests` direct sur
`/movie/{id}?append_to_response=credits`. Ce GET vivait donc hors du client :
- hors du circuit breaker (`TmdbClient._breaker`),
- hors de la session a retry/backoff (`make_session_with_retry`), donc sans
  respect du `Retry-After` que TMDb renvoie sur 429 — alors que la vue Doublons
  ouvre N fiches en parallele (un `library/get_film_full` par groupe).

Ce que ces tests prouvent :
1. l'appel de la fiche film est bien compte par le breaker du client (il ne
   l'etait pas : le GET direct ne passait par aucun breaker) ;
2. un circuit ouvert court-circuite la requete au lieu de payer le timeout ;
3. la semantique de cache est preservee (200 memorise, echec jamais memorise).

Ce que ces tests ne prouvent PAS, et qui reste vrai apres correctif : chaque
appel de `_fetch_tmdb_extras` construit un `TmdbClient` neuf (comme les 9 autres
sites du depot), donc le breaker repart a zero a chaque ouverture de fiche. Le
seuil de 10 echecs n'est atteignable que dans un client partage.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import requests

from cinesort.infra.tmdb_client import TmdbClient
from cinesort.ui.api import film_support

_TMDB_ID = 603  # The Matrix

_EXTRAS_PAYLOAD = {
    "overview": "Un synopsis.",
    "runtime": 136,
    "credits": {"crew": [{"job": "Producer", "name": "Z"}, {"job": "Director", "name": "Lana W."}]},
}


class _FakeResponse:
    def __init__(self, status_code: int, payload: Optional[Dict[str, Any]] = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> Dict[str, Any]:
        return self._payload

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}", response=self)  # type: ignore[arg-type]


class _FakeApi:
    def __init__(self, state_dir: str) -> None:
        self._state_dir = state_dir

    def _internal_settings(self) -> Dict[str, Any]:
        return {"tmdb_api_key": "REALKEY", "state_dir": self._state_dir, "tmdb_timeout_s": 1.0}


class _CapturingTmdbClient(TmdbClient):
    """VRAI client (aucun comportement stubbe), dont on retient les instances."""

    instances: List[TmdbClient] = []

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        _CapturingTmdbClient.instances.append(self)


class FicheFilmPasseParLeClientTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_599_")
        self.addCleanup(self._tmp.cleanup)
        self.state_dir = str(Path(self._tmp.name))
        _CapturingTmdbClient.instances = []
        self.urls: List[str] = []

    def _run_fiche(self, extras_status: int) -> Dict[str, Any]:
        def _get(url: str, params: Any = None, **_kw: Any) -> _FakeResponse:
            self.urls.append(url)
            if "append_to_response" in dict(params or {}):
                return _FakeResponse(extras_status, _EXTRAS_PAYLOAD)
            # L'endpoint detail (runtime/poster/genres) repond normalement :
            # sans ca, le breaker compterait cet echec-la et le test ne dirait
            # rien de l'appel « extras ».
            return _FakeResponse(200, {"runtime": 136, "poster_path": "/p.jpg"})

        with (
            patch("cinesort.infra.tmdb_client.TmdbClient", _CapturingTmdbClient),
            patch("requests.Session.get", side_effect=_get),
        ):
            return film_support._fetch_tmdb_extras(_FakeApi(self.state_dir), _TMDB_ID)

    def test_un_5xx_sur_la_fiche_film_est_compte_par_le_breaker(self) -> None:
        """ROUGE avant : le GET direct n'etait derriere aucun breaker (failures=0)."""
        out = self._run_fiche(503)

        self.assertEqual(len(_CapturingTmdbClient.instances), 1)
        client = _CapturingTmdbClient.instances[0]
        self.assertEqual(
            client._breaker.failures,
            1,
            "l'echec de la fiche film n'a pas ete vu par le circuit breaker du client",
        )
        self.assertIsNone(out["director"], "degradation gracieuse conservee")

    def test_un_401_ne_ferme_pas_le_robinet(self) -> None:
        """Contrat du breaker : un 4xx est une erreur de requete, pas une panne."""
        self._run_fiche(401)

        client = _CapturingTmdbClient.instances[0]
        self.assertEqual(client._breaker.failures, 0)

    def test_la_fiche_film_est_servie_par_le_cache_du_client(self) -> None:
        first = self._run_fiche(200)
        calls_after_first = len(self.urls)
        second = self._run_fiche(200)

        self.assertEqual(first["director"], "Lana W.")
        self.assertEqual(first["overview"], "Un synopsis.")
        self.assertEqual(first["runtime"], 136)
        self.assertEqual(second, first)
        self.assertEqual(
            len(self.urls) - calls_after_first,
            0,
            "le 2e affichage de la fiche a rappele TMDb",
        )


class GetMovieExtrasContractTests(unittest.TestCase):
    """Contrat de la methode neuve, au niveau du client."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_599c_")
        self.addCleanup(self._tmp.cleanup)
        self.calls = 0

    def _client(self) -> TmdbClient:
        return TmdbClient(api_key="k", cache_path=Path(self._tmp.name) / "c.json", timeout_s=5.0)

    def test_circuit_ouvert_ne_declenche_aucune_requete(self) -> None:
        """Le point de l'issue : TMDb down ne doit plus couter un timeout par appel."""
        client = self._client()

        def _down(url: str, **_kw: Any) -> _FakeResponse:
            self.calls += 1
            return _FakeResponse(503)

        client._session.get = _down  # type: ignore[method-assign]
        for movie_id in range(1, 11):
            self.assertIsNone(client.get_movie_extras(movie_id))
        self.assertEqual(self.calls, 10)
        self.assertTrue(client._breaker.is_open, "10 echecs consecutifs doivent ouvrir le circuit")

        self.assertIsNone(client.get_movie_extras(999))
        self.assertEqual(self.calls, 10, "le circuit ouvert n'a pas court-circuite la requete")

    def test_un_echec_nest_jamais_memorise(self) -> None:
        client = self._client()
        responses = [_FakeResponse(401), _FakeResponse(200, _EXTRAS_PAYLOAD)]

        def _get(url: str, **_kw: Any) -> _FakeResponse:
            self.calls += 1
            return responses.pop(0)

        client._session.get = _get  # type: ignore[method-assign]

        self.assertIsNone(client.get_movie_extras(_TMDB_ID))
        second = client.get_movie_extras(_TMDB_ID)
        assert second is not None
        self.assertEqual(second["director"], "Lana W.")
        self.assertEqual(self.calls, 2, "le 401 a ete fige en cache")

    def test_identifiant_invalide_ne_part_pas_en_reseau(self) -> None:
        client = self._client()

        def _get(url: str, **_kw: Any) -> _FakeResponse:
            self.calls += 1
            return _FakeResponse(200, _EXTRAS_PAYLOAD)

        client._session.get = _get  # type: ignore[method-assign]

        self.assertIsNone(client.get_movie_extras(0))
        self.assertIsNone(client.get_movie_extras(-5))
        self.assertIsNone(client.get_movie_extras("abc"))  # type: ignore[arg-type]
        self.assertEqual(self.calls, 0)

    def test_le_cache_retourne_une_copie(self) -> None:
        """Muter le dict rendu ne doit pas corrompre l'entree de cache."""
        client = self._client()

        def _get(url: str, **_kw: Any) -> _FakeResponse:
            self.calls += 1
            return _FakeResponse(200, _EXTRAS_PAYLOAD)

        client._session.get = _get  # type: ignore[method-assign]

        first = client.get_movie_extras(_TMDB_ID)
        assert first is not None
        first["director"] = "MUTATION"
        second = client.get_movie_extras(_TMDB_ID)
        assert second is not None
        self.assertEqual(second["director"], "Lana W.")
        self.assertEqual(self.calls, 1)


if __name__ == "__main__":
    unittest.main()

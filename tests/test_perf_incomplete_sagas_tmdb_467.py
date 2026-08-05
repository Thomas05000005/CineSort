"""Issue #467 — `get_incomplete_sagas` : N appels TMDb `collection/{id}` en serie.

Deux defauts trouves dans le code reel, plus lourds que l'enonce de l'issue :

1. `_fetch_collection_parts` construisait SON PROPRE `TmdbClient` a chaque saga
   (`getattr(api, "_tmdb_client", None)` est toujours None). Or
   `TmdbClient.__init__` termine par `_load_cache()` (lecture integrale de
   tmdb_cache.json) et instancie un `CircuitBreaker` NEUF. Le breaker (seuil 10
   echecs consecutifs, cf issue #76) ne pouvait donc JAMAIS s'ouvrir : chaque
   saga repartait d'un compteur a zero. Sur une bibliotheque a 30 collections
   avec TMDb en panne, les 30 payaient leurs 3 retries et leur backoff.

2. L'appel tapait `client._http_get` DIRECTEMENT, court-circuitant `_cache_get`
   / `_cache_set`. Le cache TMDb (et le reglage `tmdb_cache_ttl_days`) n'a
   jamais servi pour cet endpoint : chaque ouverture de la vue « sagas
   incompletes » refaisait N appels reseau.

MESURE (deterministe, deux tailles) : nombre de `TmdbClient` construits et
nombre de `_http_get` emis.
"""

from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import MagicMock

from cinesort.ui.api import library_audit_support


class _FakeTmdbClient:
    """Client TMDb minimal, avec le meme contrat de cache que le vrai."""

    built = 0

    def __init__(self, **kwargs) -> None:
        type(self).built += 1
        self.api_key = kwargs.get("api_key")
        self.cache_path = kwargs.get("cache_path")
        self._store: dict = {}
        self.http_calls: list = []
        self.saves = 0

    # --- contrat cache (miroir de TmdbClient) ---
    def _cache_get(self, key):
        return self._store.get(key)

    def _cache_set(self, key, value) -> None:
        self._store[key] = value

    def _save_cache_atomic(self, *, force: bool = False) -> None:
        self.saves += 1

    # --- reseau ---
    def _http_get(self, url, params=None):
        self.http_calls.append(url)
        resp = MagicMock()
        resp.json.return_value = {
            "parts": [
                {"id": 1, "title": "A", "release_date": "2000-01-01"},
                {"id": 2, "title": "B", "release_date": "2004-01-01"},
                {"id": 3, "title": "C", "release_date": "2008-01-01"},
            ]
        }
        return resp


class _FakeApi:
    def __init__(self, settings) -> None:
        self._settings = settings

    def _internal_settings(self):
        return self._settings


def _settings(tmp):
    return {"tmdb_api_key": "REAL_key", "state_dir": str(tmp)}


def _plan_rows(n_collections: int):
    """1 film possede par collection -> n_collections sagas incompletes."""
    return [
        {
            "row_id": f"r{i}",
            "proposed_title": "A",
            "proposed_year": 2000,
            "tmdb_id": 1,
            "tmdb_collection_id": 100 + i,
            "tmdb_collection_name": f"Saga {i}",
        }
        for i in range(n_collections)
    ]


def _api_with_plan(tmp, rows):
    api = MagicMock()
    api._internal_settings.return_value = _settings(tmp)
    api.run.get_plan.return_value = {"ok": True, "rows": rows}
    return api


class ClientConstructionCountTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeTmdbClient.built = 0

    def test_un_seul_client_tmdb_quel_que_soit_le_nombre_de_sagas(self) -> None:
        """MESURE : constructions de TmdbClient. AVANT : N. APRES : 1."""
        import tempfile

        for n in (2, 12):
            with self.subTest(sagas=n):
                _FakeTmdbClient.built = 0
                with tempfile.TemporaryDirectory() as tmp:
                    api = _api_with_plan(tmp, _plan_rows(n))
                    with (
                        mock.patch("cinesort.infra.tmdb_client.TmdbClient", _FakeTmdbClient),
                        mock.patch.object(library_audit_support, "_resolve_latest_run_id", return_value="run-1"),
                    ):
                        res = library_audit_support.get_incomplete_sagas(api)
                self.assertTrue(res["ok"], msg=str(res))
                self.assertEqual(res["total"], n, msg=str(res))
                self.assertEqual(
                    _FakeTmdbClient.built,
                    1,
                    f"{n} sagas doivent partager UN client TMDb (chaque construction "
                    f"relit tmdb_cache.json et remet le circuit breaker a zero) — "
                    f"observe : {_FakeTmdbClient.built}",
                )

    def test_le_circuit_breaker_est_partage_par_toutes_les_sagas(self) -> None:
        """Consequence directe : l'etat du breaker survit d'une saga a l'autre.

        Avec un client par saga, l'objet breaker changeait a chaque tour et son
        compteur d'echecs ne pouvait pas s'accumuler.
        """
        import tempfile

        seen_clients = []

        class _Tracking(_FakeTmdbClient):
            def _http_get(self, url, params=None):
                seen_clients.append(id(self))
                return super()._http_get(url, params=params)

        with tempfile.TemporaryDirectory() as tmp:
            api = _api_with_plan(tmp, _plan_rows(5))
            with (
                mock.patch("cinesort.infra.tmdb_client.TmdbClient", _Tracking),
                mock.patch.object(library_audit_support, "_resolve_latest_run_id", return_value="run-1"),
            ):
                library_audit_support.get_incomplete_sagas(api)

        self.assertEqual(len(seen_clients), 5, "5 collections distinctes -> 5 appels reseau")
        self.assertEqual(
            len(set(seen_clients)),
            1,
            "les 5 appels doivent passer par le MEME client (donc le meme circuit breaker et la meme Session)",
        )


class CollectionCacheTests(unittest.TestCase):
    def test_deuxieme_lecture_de_la_meme_collection_ne_retape_pas_le_reseau(self) -> None:
        client = _FakeTmdbClient(api_key="k")
        api = _FakeApi({"tmdb_api_key": "k", "state_dir": "/tmp/x"})

        first = library_audit_support._fetch_collection_parts(api, 42, client=client)
        second = library_audit_support._fetch_collection_parts(api, 42, client=client)

        self.assertEqual(first, second)
        self.assertEqual(len(first), 3)
        self.assertEqual(
            len(client.http_calls),
            1,
            f"la 2e lecture doit venir du cache TTL du client ({client.http_calls})",
        )

    def test_collections_differentes_ont_des_entrees_de_cache_distinctes(self) -> None:
        client = _FakeTmdbClient(api_key="k")
        api = _FakeApi({"tmdb_api_key": "k", "state_dir": "/tmp/x"})
        library_audit_support._fetch_collection_parts(api, 1, client=client)
        library_audit_support._fetch_collection_parts(api, 2, client=client)
        self.assertEqual(len(client.http_calls), 2, "deux collections = deux appels")
        library_audit_support._fetch_collection_parts(api, 1, client=client)
        self.assertEqual(len(client.http_calls), 2, "la 3e lecture rejoue la collection 1 depuis le cache")

    def test_entree_de_cache_corrompue_ne_court_circuite_pas_le_fetch(self) -> None:
        """Le cache vient d'un JSON sur disque : une valeur non-liste ne doit
        pas etre servie telle quelle a l'appelant."""
        client = _FakeTmdbClient(api_key="k")
        client._store["collection_parts|7"] = {"pas": "une liste"}
        api = _FakeApi({"tmdb_api_key": "k", "state_dir": "/tmp/x"})
        out = library_audit_support._fetch_collection_parts(api, 7, client=client)
        self.assertIsInstance(out, list)
        self.assertEqual(len(out), 3)
        self.assertEqual(len(client.http_calls), 1)

    def test_sans_cle_tmdb_aucun_client_et_aucun_appel(self) -> None:
        api = _FakeApi({"tmdb_api_key": "", "state_dir": "/tmp/x"})
        self.assertIsNone(library_audit_support._build_tmdb_client(api))
        self.assertIsNone(library_audit_support._fetch_collection_parts(api, 99))


if __name__ == "__main__":
    unittest.main()

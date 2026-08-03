"""GATE AUDIT 2026-06-10 (REAL 2/2) — le circuit breaker TMDb compte les 5xx.

Avant : raise_for_status() etait appele APRES _breaker.call() ; la Session ayant
raise_on_status=False, un 5xx ne levait rien DANS le lambda -> le breaker ne
comptait pas l'echec et ne s'ouvrait jamais (retries x 5000 films sur TMDb en
panne). On leve desormais raise_for_status DANS le lambda pour les 5xx/429.
Les 4xx (401/404) doivent rester intacts (callers gracieux).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import requests

from cinesort.infra._circuit_breaker import CircuitOpenError
from cinesort.infra.tmdb_client import TmdbClient


class _Resp:
    def __init__(self, status_code: int) -> None:
        self.status_code = status_code

    def raise_for_status(self) -> None:
        # Comme le vrai requests : leve sur >= 400.
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return {}

    @property
    def text(self) -> str:
        return ""


class TmdbBreaker5xxTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_tmdb_brk_")
        self.cache_path = Path(self._tmp.name) / "tmdb_cache.json"
        self.client = TmdbClient(api_key="k", cache_path=self.cache_path, timeout_s=0.1)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_breaker_opens_after_consecutive_5xx(self) -> None:
        """503 consecutifs -> le breaker compte les echecs et finit par s'ouvrir
        (CircuitOpenError) sans atteindre le reseau."""
        with mock.patch.object(self.client._session, "get", return_value=_Resp(503)) as mget:
            opened = False
            for _ in range(60):  # > failure_threshold (10)
                try:
                    self.client._http_get("https://api.themoviedb.org/3/x")
                except CircuitOpenError:
                    opened = True
                    break
                except requests.HTTPError:
                    pass  # echec compte par le breaker
            self.assertTrue(opened, "le breaker doit finir par s'ouvrir sur 503 repetes")
            # Une fois ouvert, le breaker court-circuite : moins d'appels reseau que d'iterations.
            self.assertLess(mget.call_count, 60)

    def test_4xx_does_not_raise_in_lambda(self) -> None:
        """Un 404 ne doit PAS lever dans le lambda (les 4xx passent intacts pour
        les callers gracieux ; seul raise_for_status du caller decidera)."""
        with mock.patch.object(self.client._session, "get", return_value=_Resp(404)):
            # _http_get ne doit pas lever : il retourne la reponse 404 telle quelle.
            resp = self.client._http_get("https://api.themoviedb.org/3/x")
            self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()

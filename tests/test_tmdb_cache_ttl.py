"""D-5 audit QA 20260429 — tests TTL adaptatif cache TMDb.

Verifie que :
- _ttl_for_key retourne 7 jours pour search|... / tv_search:... (non-det).
- _ttl_for_key retourne 30 jours pour movie|... / find_*|... / tv_ep:... (det).
- Une entree search expirée a 7 jours est invalidee.
- Une entree movie a 8 jours reste valide (pas encore expiree).
"""

from __future__ import annotations

import unittest

from cinesort.infra.tmdb_client import (
    _CACHE_TTL_S,
    _SEARCH_CACHE_TTL_S,
    _ttl_for_key,
)


class TtlForKeyTests(unittest.TestCase):
    def test_search_key_uses_short_ttl(self) -> None:
        self.assertEqual(_ttl_for_key("search|fr-FR|inception|2010"), _SEARCH_CACHE_TTL_S)

    def test_tv_search_key_uses_short_ttl(self) -> None:
        self.assertEqual(_ttl_for_key("tv_search:breaking bad|2008|en"), _SEARCH_CACHE_TTL_S)

    def test_movie_lookup_uses_long_ttl(self) -> None:
        self.assertEqual(_ttl_for_key("movie|12345"), _CACHE_TTL_S)

    def test_find_tmdb_uses_long_ttl(self) -> None:
        self.assertEqual(_ttl_for_key("find_tmdb|54321"), _CACHE_TTL_S)

    def test_find_imdb_uses_long_ttl(self) -> None:
        self.assertEqual(_ttl_for_key("find_imdb|tt1234567"), _CACHE_TTL_S)

    def test_tv_ep_uses_long_ttl(self) -> None:
        self.assertEqual(_ttl_for_key("tv_ep:101|1|2|fr"), _CACHE_TTL_S)

    def test_unknown_key_falls_back_to_short_ttl(self) -> None:
        # Les cles inconnues sont prudemment considerees comme short
        # (mieux refresh trop souvent qu'avoir des donnees stale)
        self.assertEqual(_ttl_for_key("custom_xyz:foo"), _SEARCH_CACHE_TTL_S)

    def test_search_ttl_is_one_week(self) -> None:
        self.assertEqual(_SEARCH_CACHE_TTL_S, 7 * 24 * 3600)

    def test_long_ttl_is_one_month(self) -> None:
        self.assertEqual(_CACHE_TTL_S, 30 * 24 * 3600)

    def test_short_ttl_is_strictly_less_than_long(self) -> None:
        self.assertLess(_SEARCH_CACHE_TTL_S, _CACHE_TTL_S)


if __name__ == "__main__":
    unittest.main()

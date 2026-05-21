"""Tests Phase 6 — recherche manuelle TMDb dans le Modal Film (spec 06 §3.4).

Couvre :
- tmdb_support.search_tmdb : validation, success, no api key, errors
- LibraryFacade.search_tmdb : delegation
- CineSortApi._search_tmdb_impl : pass-through
"""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.infra.tmdb_client import TmdbResult
from cinesort.ui.api import tmdb_support


def _make_api(
    api_key: str = "fake_key",
    state_dir: str = "/tmp/state",
    timeout_s: float = 10.0,
) -> MagicMock:
    """Construit un faux objet api compatible avec search_tmdb."""
    api = MagicMock()
    api.settings.get_settings.return_value = {
        "tmdb_api_key": api_key,
        "state_dir": state_dir,
        "tmdb_timeout_s": timeout_s,
        "tmdb_cache_ttl_days": 30,
    }
    api._normalize_user_path.return_value = Path(state_dir)
    return api


# ---------------------------------------------------------------------------
# Validation de l'input
# ---------------------------------------------------------------------------


class SearchTmdbValidationTests(unittest.TestCase):
    def test_empty_query_returns_validation_error(self) -> None:
        api = _make_api()
        res = tmdb_support.search_tmdb(api, "")
        self.assertFalse(res["ok"])
        self.assertIn("vide", res["message"].lower())

    def test_whitespace_query_returns_validation_error(self) -> None:
        api = _make_api()
        res = tmdb_support.search_tmdb(api, "   ")
        self.assertFalse(res["ok"])
        self.assertIn("vide", res["message"].lower())

    def test_single_char_query_rejected(self) -> None:
        api = _make_api()
        res = tmdb_support.search_tmdb(api, "a")
        self.assertFalse(res["ok"])
        self.assertIn("2 caracteres", res["message"].lower())

    def test_none_query_rejected(self) -> None:
        api = _make_api()
        res = tmdb_support.search_tmdb(api, None)  # type: ignore[arg-type]
        self.assertFalse(res["ok"])

    def test_invalid_year_is_ignored(self) -> None:
        # year hors plage -> on requete TMDb sans filtre year (pas d'erreur)
        api = _make_api()
        with patch("cinesort.ui.api.tmdb_support.TmdbClient") as mock_cls:
            client = MagicMock()
            client.search_movie.return_value = []
            client._get_movie_detail_cached.return_value = None
            mock_cls.return_value = client
            res = tmdb_support.search_tmdb(api, "Inception", year=42)
        self.assertTrue(res["ok"])
        self.assertIsNone(res["year"])
        client.search_movie.assert_called_once()
        # year doit etre passe a None
        kwargs = client.search_movie.call_args.kwargs
        self.assertIsNone(kwargs.get("year"))

    def test_year_string_converted(self) -> None:
        api = _make_api()
        with patch("cinesort.ui.api.tmdb_support.TmdbClient") as mock_cls:
            client = MagicMock()
            client.search_movie.return_value = []
            client._get_movie_detail_cached.return_value = None
            mock_cls.return_value = client
            res = tmdb_support.search_tmdb(api, "Inception", year="2010")  # type: ignore[arg-type]
        self.assertTrue(res["ok"])
        self.assertEqual(res["year"], 2010)


# ---------------------------------------------------------------------------
# Cles API manquantes
# ---------------------------------------------------------------------------


class SearchTmdbNoApiKeyTests(unittest.TestCase):
    def test_empty_api_key_returns_config_error(self) -> None:
        api = _make_api(api_key="")
        res = tmdb_support.search_tmdb(api, "Inception")
        self.assertFalse(res["ok"])
        self.assertIn("cle tmdb", res["message"].lower())

    def test_whitespace_api_key_returns_config_error(self) -> None:
        api = _make_api(api_key="   ")
        res = tmdb_support.search_tmdb(api, "Inception")
        self.assertFalse(res["ok"])


# ---------------------------------------------------------------------------
# Cas nominal
# ---------------------------------------------------------------------------


class SearchTmdbSuccessTests(unittest.TestCase):
    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_returns_results_with_poster_url(self, mock_cls) -> None:
        client = MagicMock()
        client.search_movie.return_value = [
            TmdbResult(
                id=27205,
                title="Inception",
                year=2010,
                original_title="Inception",
                popularity=120.5,
                vote_count=30000,
                vote_average=8.4,
                poster_path="/8h58SMRYUNl5OL2WJ.jpg",
            ),
        ]
        client._get_movie_detail_cached.return_value = {"overview": "Un voleur de reves..."}
        mock_cls.return_value = client

        api = _make_api()
        res = tmdb_support.search_tmdb(api, "Inception", year=2010)
        self.assertTrue(res["ok"])
        self.assertEqual(res["count"], 1)
        self.assertEqual(res["query"], "Inception")
        self.assertEqual(res["year"], 2010)
        result = res["results"][0]
        self.assertEqual(result["tmdb_id"], 27205)
        self.assertEqual(result["title"], "Inception")
        self.assertEqual(result["year"], 2010)
        self.assertEqual(result["vote_average"], 8.4)
        self.assertIn("w185", result["poster_url"])
        self.assertIn("/8h58SMRYUNl5OL2WJ.jpg", result["poster_url"])
        self.assertEqual(result["overview"], "Un voleur de reves...")

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_overview_truncated_at_240_chars(self, mock_cls) -> None:
        long_text = "x" * 500
        client = MagicMock()
        client.search_movie.return_value = [
            TmdbResult(
                id=1,
                title="T",
                year=2020,
                original_title=None,
                popularity=0,
                vote_count=0,
                vote_average=0,
                poster_path=None,
            ),
        ]
        client._get_movie_detail_cached.return_value = {"overview": long_text}
        mock_cls.return_value = client

        api = _make_api()
        res = tmdb_support.search_tmdb(api, "TT")
        # Pas de poster_url quand poster_path est None
        self.assertIsNone(res["results"][0]["poster_url"])
        # Overview tronquee a <= 240 chars + suffixe "..."
        ov = res["results"][0]["overview"]
        self.assertLessEqual(len(ov), 240)
        self.assertTrue(ov.endswith("..."))

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_no_year_passed(self, mock_cls) -> None:
        client = MagicMock()
        client.search_movie.return_value = []
        client._get_movie_detail_cached.return_value = None
        mock_cls.return_value = client

        api = _make_api()
        res = tmdb_support.search_tmdb(api, "Matrix")
        self.assertTrue(res["ok"])
        self.assertIsNone(res["year"])
        kwargs = client.search_movie.call_args.kwargs
        self.assertIsNone(kwargs.get("year"))

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_max_results_cap_propagated(self, mock_cls) -> None:
        client = MagicMock()
        client.search_movie.return_value = []
        client._get_movie_detail_cached.return_value = None
        mock_cls.return_value = client

        api = _make_api()
        tmdb_support.search_tmdb(api, "popular movie")
        # Cap defensif 10 propage au client
        kwargs = client.search_movie.call_args.kwargs
        self.assertEqual(kwargs.get("max_results"), 10)

    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_flush_called_at_end(self, mock_cls) -> None:
        client = MagicMock()
        client.search_movie.return_value = []
        client._get_movie_detail_cached.return_value = None
        mock_cls.return_value = client

        api = _make_api()
        tmdb_support.search_tmdb(api, "XY")
        client.flush.assert_called_once()


# ---------------------------------------------------------------------------
# Erreurs runtime
# ---------------------------------------------------------------------------


class SearchTmdbErrorsTests(unittest.TestCase):
    @patch("cinesort.ui.api.tmdb_support.TmdbClient")
    def test_oserror_returns_runtime_error(self, mock_cls) -> None:
        client = MagicMock()
        client.search_movie.side_effect = OSError("network fail")
        mock_cls.return_value = client

        api = _make_api()
        res = tmdb_support.search_tmdb(api, "Inception")
        self.assertFalse(res["ok"])
        self.assertIn("network fail", res["message"])

    def test_get_settings_keyerror_returns_runtime_error(self) -> None:
        api = MagicMock()
        api.settings.get_settings.side_effect = KeyError("missing")
        res = tmdb_support.search_tmdb(api, "Inception")
        self.assertFalse(res["ok"])
        self.assertIn("missing", res["message"])


# ---------------------------------------------------------------------------
# Facade + CineSortApi : delegation
# ---------------------------------------------------------------------------


class SearchTmdbDelegationTests(unittest.TestCase):
    def test_cinesort_api_impl_delegates_to_support(self) -> None:
        """_search_tmdb_impl delegue a tmdb_support.search_tmdb."""
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi.__new__(CineSortApi)
        with patch("cinesort.ui.api.cinesort_api.tmdb_support.search_tmdb") as mock_fn:
            mock_fn.return_value = {"ok": True, "results": []}
            res = api._search_tmdb_impl("Inception", year=2010)
        self.assertEqual(res, {"ok": True, "results": []})
        mock_fn.assert_called_once_with(api, "Inception", 2010)

    def test_library_facade_search_tmdb_delegates_to_api_impl(self) -> None:
        """LibraryFacade.search_tmdb delegue a CineSortApi._search_tmdb_impl."""
        from cinesort.ui.api.facades.library_facade import LibraryFacade

        mock_api = MagicMock()
        mock_api._search_tmdb_impl.return_value = {"ok": True, "results": [], "count": 0}
        facade = LibraryFacade(mock_api)
        res = facade.search_tmdb("Matrix", year=1999)
        self.assertEqual(res["ok"], True)
        mock_api._search_tmdb_impl.assert_called_once_with(query="Matrix", year=1999)

    def test_library_facade_search_tmdb_default_year(self) -> None:
        from cinesort.ui.api.facades.library_facade import LibraryFacade

        mock_api = MagicMock()
        mock_api._search_tmdb_impl.return_value = {"ok": True}
        facade = LibraryFacade(mock_api)
        facade.search_tmdb("Matrix")
        mock_api._search_tmdb_impl.assert_called_once_with(query="Matrix", year=None)


if __name__ == "__main__":
    unittest.main()

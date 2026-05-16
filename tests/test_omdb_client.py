"""Tests OmdbClient — parsing, cache, rate limit, gestion erreurs."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.infra.omdb_client import (
    OmdbClient,
    OmdbResult,
    _parse_omdb_response,
    _parse_rating,
    _parse_runtime,
    _parse_votes,
    _parse_year,
)


# --- Mock helpers ---


def _make_omdb_payload(**kwargs) -> dict:
    """Crée un payload OMDb minimal avec overrides."""
    default = {
        "Response": "True",
        "imdbID": "tt0111161",
        "Title": "The Shawshank Redemption",
        "Year": "1994",
        "Runtime": "142 min",
        "Genre": "Drama",
        "imdbRating": "9.3",
        "imdbVotes": "2,800,000",
        "Awards": "Nominated for 7 Oscars",
        "Plot": "Two imprisoned men...",
    }
    default.update(kwargs)
    return default


def _make_mock_response(payload: dict, status_code: int = 200):
    """Crée un mock requests.Response."""
    mock_resp = MagicMock()
    mock_resp.status_code = status_code
    mock_resp.json.return_value = payload
    mock_resp.raise_for_status = MagicMock()
    return mock_resp


# --- Parser primitives ---


class ParseYearTests(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(_parse_year("2017"), 2017)

    def test_series_dash(self):
        # OMDb series : "2018–2023" ou "2018–"
        self.assertEqual(_parse_year("2018–2023"), 2018)
        self.assertEqual(_parse_year("2018–"), 2018)

    def test_invalid(self):
        self.assertIsNone(_parse_year("N/A"))
        self.assertIsNone(_parse_year(""))
        self.assertIsNone(_parse_year(None))

    def test_clamp(self):
        self.assertIsNone(_parse_year("1800"))  # avant 1900
        self.assertIsNone(_parse_year("2200"))  # apres 2100


class ParseRuntimeTests(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(_parse_runtime("142 min"), 142)

    def test_no_unit(self):
        self.assertEqual(_parse_runtime("142"), 142)

    def test_na(self):
        self.assertIsNone(_parse_runtime("N/A"))

    def test_empty(self):
        self.assertIsNone(_parse_runtime(""))

    def test_clamp(self):
        self.assertIsNone(_parse_runtime("0"))  # implausible
        self.assertIsNone(_parse_runtime("700 min"))  # > 600


class ParseRatingTests(unittest.TestCase):
    def test_standard(self):
        self.assertEqual(_parse_rating("7.6"), 7.6)

    def test_integer(self):
        self.assertEqual(_parse_rating("9"), 9.0)

    def test_na(self):
        self.assertIsNone(_parse_rating("N/A"))


class ParseVotesTests(unittest.TestCase):
    def test_standard_with_comma(self):
        self.assertEqual(_parse_votes("828,114"), 828114)

    def test_no_comma(self):
        self.assertEqual(_parse_votes("1234"), 1234)

    def test_na(self):
        self.assertIsNone(_parse_votes("N/A"))


# --- _parse_omdb_response ---


class ParseOmdbResponseTests(unittest.TestCase):
    def test_valid_payload(self):
        payload = _make_omdb_payload()
        result = _parse_omdb_response(payload)
        self.assertIsNotNone(result)
        self.assertEqual(result.imdb_id, "tt0111161")
        self.assertEqual(result.title, "The Shawshank Redemption")
        self.assertEqual(result.year, 1994)
        self.assertEqual(result.runtime_min, 142)
        self.assertEqual(result.imdb_rating, 9.3)

    def test_response_false_returns_none(self):
        payload = {"Response": "False", "Error": "Movie not found"}
        self.assertIsNone(_parse_omdb_response(payload))

    def test_missing_id_returns_none(self):
        payload = _make_omdb_payload(imdbID="")
        self.assertIsNone(_parse_omdb_response(payload))

    def test_non_dict_returns_none(self):
        self.assertIsNone(_parse_omdb_response(None))
        self.assertIsNone(_parse_omdb_response("not a dict"))

    def test_partial_data_keeps_what_it_can(self):
        payload = _make_omdb_payload(Runtime="N/A", imdbRating="N/A")
        result = _parse_omdb_response(payload)
        self.assertIsNotNone(result)
        self.assertIsNone(result.runtime_min)
        self.assertIsNone(result.imdb_rating)


# --- OmdbClient ---


class OmdbClientTests(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp(prefix="omdb_test_")
        self.cache_path = Path(self.tmp_dir) / "omdb_cache.json"

    def _make_client(self, api_key: str = "test-key") -> OmdbClient:
        return OmdbClient(api_key=api_key, cache_path=self.cache_path, timeout_s=5.0)

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_find_by_imdb_id_success(self, mock_get, _mock_wait):
        mock_get.return_value = _make_mock_response(_make_omdb_payload())
        client = self._make_client()
        result = client.find_by_imdb_id("tt0111161")
        self.assertIsNotNone(result)
        self.assertEqual(result.title, "The Shawshank Redemption")
        # Verify URL params include i= and apikey=
        call_kwargs = mock_get.call_args.kwargs
        self.assertEqual(call_kwargs["params"]["i"], "tt0111161")
        self.assertEqual(call_kwargs["params"]["apikey"], "test-key")

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_find_by_imdb_id_uses_cache_on_second_call(self, mock_get, _mock_wait):
        mock_get.return_value = _make_mock_response(_make_omdb_payload())
        client = self._make_client()
        client.find_by_imdb_id("tt0111161")
        client.find_by_imdb_id("tt0111161")
        # 1 seul appel HTTP malgre 2 lookups
        self.assertEqual(mock_get.call_count, 1)

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_find_by_imdb_id_movie_not_found(self, mock_get, _mock_wait):
        mock_get.return_value = _make_mock_response({"Response": "False", "Error": "Movie not found!"})
        client = self._make_client()
        result = client.find_by_imdb_id("tt99999999")
        self.assertIsNone(result)

    def test_find_by_imdb_id_invalid_id_no_http_call(self):
        with patch("requests.Session.get") as mock_get:
            client = self._make_client()
            self.assertIsNone(client.find_by_imdb_id(""))
            self.assertIsNone(client.find_by_imdb_id("invalid"))
            mock_get.assert_not_called()

    def test_find_by_imdb_id_no_api_key(self):
        client = self._make_client(api_key="")
        with patch("requests.Session.get") as mock_get:
            self.assertIsNone(client.find_by_imdb_id("tt0111161"))
            mock_get.assert_not_called()

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_search_by_title_with_year(self, mock_get, _mock_wait):
        mock_get.return_value = _make_mock_response(_make_omdb_payload())
        client = self._make_client()
        result = client.search_by_title("Shawshank", year=1994)
        self.assertIsNotNone(result)
        call_kwargs = mock_get.call_args.kwargs
        self.assertEqual(call_kwargs["params"]["t"], "Shawshank")
        self.assertEqual(call_kwargs["params"]["y"], "1994")

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_search_by_title_without_year(self, mock_get, _mock_wait):
        mock_get.return_value = _make_mock_response(_make_omdb_payload())
        client = self._make_client()
        client.search_by_title("Shawshank")
        call_kwargs = mock_get.call_args.kwargs
        self.assertNotIn("y", call_kwargs["params"])

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_test_connection_success(self, mock_get, _mock_wait):
        mock_get.return_value = _make_mock_response(_make_omdb_payload())
        client = self._make_client()
        result = client.test_connection()
        self.assertTrue(result["ok"])
        self.assertIn("Shawshank", result["message"])

    def test_test_connection_no_key(self):
        client = self._make_client(api_key="")
        result = client.test_connection()
        self.assertFalse(result["ok"])
        self.assertIn("vide", result["message"].lower())

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_http_error_returns_none(self, mock_get, _mock_wait):
        import requests as _req

        mock_get.side_effect = _req.ConnectionError("network down")
        client = self._make_client()
        result = client.find_by_imdb_id("tt0111161")
        self.assertIsNone(result)

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_invalid_json_returns_none(self, mock_get, _mock_wait):
        mock_resp = MagicMock()
        mock_resp.json.side_effect = ValueError("invalid json")
        mock_resp.raise_for_status = MagicMock()
        mock_get.return_value = mock_resp
        client = self._make_client()
        self.assertIsNone(client.find_by_imdb_id("tt0111161"))

    @patch("cinesort.infra.omdb_client.OmdbClient._rate_limit_wait")
    @patch("requests.Session.get")
    def test_cache_persists_to_disk(self, mock_get, _mock_wait):
        mock_get.return_value = _make_mock_response(_make_omdb_payload())
        client1 = self._make_client()
        client1.find_by_imdb_id("tt0111161")
        # Recharge un client neuf : doit lire le cache disque
        client2 = self._make_client()
        result2 = client2.find_by_imdb_id("tt0111161")
        self.assertIsNotNone(result2)
        self.assertEqual(result2.title, "The Shawshank Redemption")
        # Le 2e client n'a fait aucun appel HTTP (cache)
        self.assertEqual(mock_get.call_count, 1)


class OmdbResultDataclassTests(unittest.TestCase):
    def test_immutable(self):
        result = OmdbResult(
            imdb_id="tt0111161",
            title="Movie",
            year=2020,
            runtime_min=120,
            genre="Drama",
            imdb_rating=8.0,
            imdb_votes=1000,
            awards="",
            plot="",
        )
        with self.assertRaises(Exception):
            result.title = "Other"


if __name__ == "__main__":
    unittest.main()

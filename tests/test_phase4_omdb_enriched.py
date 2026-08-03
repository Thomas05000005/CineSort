"""Tests Phase 4 — OmdbClient.test_connection enrichi avec quota + 6 etats.

Cible la spec docs/internal/design/refonte_2026_05_17/screens/03-settings-omdb.md
sections §2 (champs retournes) et §3 (etats du champ cle).

Etats verifies :
  - empty_key  : aucune cle saisie  -> ok=False, error_code='empty_key'
  - auth (401) : cle invalide       -> ok=False, error_code='auth'
  - quota (429): quota epuise       -> ok=False, error_code='quota'
  - timeout    : delai depasse      -> ok=False, error_code='timeout'
  - network    : erreur reseau      -> ok=False, error_code='network'
  - ok + quota : succes + headers   -> ok=True, quota_remaining/limit

Pattern : on patch `OmdbClient._session.get` pour controller la reponse HTTP.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import requests

from cinesort.infra.omdb_client import OmdbClient, _parse_quota_int

# --- Helpers ---


def _mk_response(status_code=200, json_payload=None, headers=None):
    """Construit un MagicMock requests.Response controllable."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = headers or {}
    resp.json.return_value = json_payload if json_payload is not None else {}
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = requests.HTTPError(
            f"HTTP {status_code}",
            response=resp,
        )
    return resp


def _shawshank_payload():
    return {
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


# --- Tests _parse_quota_int ---


class ParseQuotaIntTests(unittest.TestCase):
    def test_none(self):
        self.assertIsNone(_parse_quota_int(None))

    def test_empty_string(self):
        self.assertIsNone(_parse_quota_int(""))
        self.assertIsNone(_parse_quota_int("   "))

    def test_invalid(self):
        self.assertIsNone(_parse_quota_int("abc"))

    def test_negative_rejected(self):
        # Header malformé négatif → None plutôt que de tromper l'UI
        self.assertIsNone(_parse_quota_int("-5"))

    def test_positive_int(self):
        self.assertEqual(_parse_quota_int("247"), 247)
        self.assertEqual(_parse_quota_int(" 247 "), 247)
        self.assertEqual(_parse_quota_int("0"), 0)


# --- Tests test_connection ---


class TestConnectionEnrichedTests(unittest.TestCase):
    """Tests des 6 etats du test_connection (cf spec §3)."""

    def _make_client(self, api_key="VALIDKEY"):
        tmp = Path(tempfile.mkdtemp()) / "omdb_cache.json"
        return OmdbClient(api_key=api_key, cache_path=tmp, timeout_s=5.0)

    def test_empty_key_state(self):
        """État 1 : pas de cle → error_code='empty_key' + tous les champs quota None."""
        client = self._make_client(api_key="")
        result = client.test_connection()
        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "empty_key")
        self.assertIsNone(result["quota_remaining"])
        self.assertIsNone(result["quota_limit"])
        self.assertIsNone(result["quota_reset_at"])
        self.assertIn("vide", result["message"].lower())

    def test_ok_with_quota_headers(self):
        """État 3 : succes + headers X-RateLimit-* captés."""
        client = self._make_client()
        mock_resp = _mk_response(
            status_code=200,
            json_payload=_shawshank_payload(),
            headers={
                "X-RateLimit-Remaining": "247",
                "X-RateLimit-Limit": "1000",
                "X-RateLimit-Reset": "1715990400",
            },
        )
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        self.assertTrue(result["ok"])
        self.assertIsNone(result["error_code"])
        self.assertEqual(result["quota_remaining"], 247)
        self.assertEqual(result["quota_limit"], 1000)
        self.assertEqual(result["quota_reset_at"], "1715990400")
        self.assertEqual(result["sample_title"], "The Shawshank Redemption")
        self.assertEqual(result["sample_year"], 1994)

    def test_ok_without_quota_headers(self):
        """Succes meme sans header quota (OMDb les omet parfois)."""
        client = self._make_client()
        mock_resp = _mk_response(
            status_code=200,
            json_payload=_shawshank_payload(),
            headers={},  # pas de headers quota
        )
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        self.assertTrue(result["ok"])
        self.assertIsNone(result["quota_remaining"])
        self.assertIsNone(result["quota_limit"])
        self.assertIsNone(result["quota_reset_at"])

    def test_401_invalid_key(self):
        """État 4 : HTTP 401 → error_code='auth' + message 'Cle API invalide'."""
        client = self._make_client(api_key="BADKEY")
        mock_resp = _mk_response(
            status_code=401,
            json_payload={"Response": "False", "Error": "Invalid API key!"},
            headers={"X-RateLimit-Remaining": "0", "X-RateLimit-Limit": "1000"},
        )
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "auth")
        self.assertIn("invalide", result["message"].lower())
        # Headers quota peuvent être présents même en 401
        self.assertEqual(result["quota_remaining"], 0)
        self.assertEqual(result["quota_limit"], 1000)

    def test_200_invalid_key_via_body(self):
        """Variante OMDb : 200 + Response=False + Error='Invalid API key!' (cas réel)."""
        client = self._make_client(api_key="BADKEY")
        mock_resp = _mk_response(
            status_code=200,
            json_payload={"Response": "False", "Error": "Invalid API key!"},
            headers={},
        )
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "auth")
        self.assertIn("invalide", result["message"].lower())

    def test_429_quota_exceeded(self):
        """État 5 : HTTP 429 → error_code='quota' + message 'Quota depasse'."""
        client = self._make_client()
        mock_resp = _mk_response(
            status_code=429,
            json_payload={"Response": "False", "Error": "Request limit reached!"},
            headers={
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Limit": "1000",
                "X-RateLimit-Reset": "1716000000",
            },
        )
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "quota")
        self.assertIn("quota", result["message"].lower())
        self.assertEqual(result["quota_remaining"], 0)
        self.assertEqual(result["quota_limit"], 1000)
        self.assertEqual(result["quota_reset_at"], "1716000000")

    def test_200_quota_exceeded_via_body(self):
        """Variante OMDb : 200 + Response=False + Error='Request limit reached!'."""
        client = self._make_client()
        mock_resp = _mk_response(
            status_code=200,
            json_payload={"Response": "False", "Error": "Request limit reached!"},
            headers={},
        )
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "quota")
        self.assertIn("quota", result["message"].lower())

    def test_timeout(self):
        """État 6a : requests.Timeout → error_code='timeout'."""
        client = self._make_client()
        with patch.object(client._session, "get", side_effect=requests.Timeout("read timeout")):
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "timeout")
        self.assertIn("delai", result["message"].lower())
        self.assertIsNone(result["quota_remaining"])

    def test_network_connection_error(self):
        """État 6b : requests.ConnectionError → error_code='network'."""
        client = self._make_client()
        with patch.object(
            client._session,
            "get",
            side_effect=requests.ConnectionError("DNS lookup failed"),
        ):
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "network")
        self.assertIn("reseau", result["message"].lower())

    def test_http_500_generic(self):
        """Erreur 5xx → traitee comme network (pas auth, pas quota)."""
        client = self._make_client()
        mock_resp = _mk_response(
            status_code=500,
            json_payload={},
            headers={},
        )
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "network")
        self.assertIn("500", result["message"])

    def test_invalid_json_response(self):
        """Réponse OMDb avec JSON cassé → error_code='invalid_resp'."""
        client = self._make_client()
        mock_resp = _mk_response(status_code=200, json_payload=None, headers={})
        mock_resp.json.side_effect = ValueError("invalid json")
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        self.assertFalse(result["ok"])
        self.assertEqual(result["error_code"], "invalid_resp")

    def test_return_shape_contains_all_documented_fields(self):
        """Le payload de retour DOIT toujours contenir les champs documentés.

        Spec §2 :
          ok, message, sample_title, sample_year, quota_remaining,
          quota_limit, quota_reset_at, error_code
        """
        client = self._make_client()
        mock_resp = _mk_response(
            status_code=200,
            json_payload=_shawshank_payload(),
            headers={"X-RateLimit-Remaining": "10", "X-RateLimit-Limit": "1000"},
        )
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.test_connection()

        for field in ("ok", "message", "quota_remaining", "quota_limit", "quota_reset_at", "error_code"):
            self.assertIn(field, result, f"Champ manquant : {field}")


if __name__ == "__main__":
    unittest.main()

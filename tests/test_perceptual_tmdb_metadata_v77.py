"""GATE AUDIT 2026-06-10 (REAL 2/2) — _load_tmdb_metadata ne leve plus
AttributeError (api._tmdb_client() inexistant).

Avant : `api._tmdb_client()` -> AttributeError (hors du except) qui remontait
dans _video_task -> TOUTE l'analyse video perceptuelle echouait pour un film
avec tmdb_id. On construit desormais le client via _build_tmdb_client.
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cinesort.ui.api import perceptual_support


class _FakeApiNoTmdbClient:
    """api SANS methode _tmdb_client (comme le vrai CineSortApi)."""

    def __init__(self, settings: dict) -> None:
        self._settings = settings

    def _internal_settings(self) -> dict:
        return self._settings


def _row_with_tmdb(tmdb_id: int):
    return SimpleNamespace(candidates=[SimpleNamespace(tmdb_id=tmdb_id)])


class LoadTmdbMetadataTests(unittest.TestCase):
    def test_no_attribute_error_when_no_key(self) -> None:
        api = _FakeApiNoTmdbClient({"tmdb_api_key": "", "state_dir": "/tmp/x"})
        # Ne doit PAS lever AttributeError (l'ancien api._tmdb_client() levait).
        result = perceptual_support._load_tmdb_metadata(api, _row_with_tmdb(123))
        self.assertIsNone(result)

    def test_no_candidate_returns_none(self) -> None:
        api = _FakeApiNoTmdbClient({"tmdb_api_key": "k", "state_dir": "/tmp/x"})
        self.assertIsNone(perceptual_support._load_tmdb_metadata(api, SimpleNamespace(candidates=[])))

    def test_builds_client_with_real_key_and_returns_metadata(self) -> None:
        api = _FakeApiNoTmdbClient({"tmdb_api_key": "REAL_key", "state_dir": "/tmp/x"})
        client = MagicMock()
        client.get_movie_metadata_for_perceptual.return_value = {"genres": ["Sci-Fi"]}
        with patch("cinesort.infra.tmdb_client.TmdbClient", return_value=client) as cls:
            result = perceptual_support._load_tmdb_metadata(api, _row_with_tmdb(603))
        self.assertEqual(result, {"genres": ["Sci-Fi"]})
        _args, kwargs = cls.call_args
        self.assertEqual(kwargs["api_key"], "REAL_key")  # vraie cle, pas le masque
        client.get_movie_metadata_for_perceptual.assert_called_once_with(603)


if __name__ == "__main__":
    unittest.main()

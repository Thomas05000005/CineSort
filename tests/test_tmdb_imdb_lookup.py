"""Tests pour le lookup TMDb par IMDb ID et le fallback FR/EN."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.infra.tmdb_client import TmdbClient


class FindByImdbIdTests(unittest.TestCase):
    """Tests pour TmdbClient.find_by_imdb_id()."""

    def _make_client(self):
        return TmdbClient(api_key="test", cache_path=Path("/tmp/test_cache.json"), timeout_s=5)

    def test_find_by_imdb_id_found(self):
        """IMDb ID valide → retourne un TmdbResult."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "movie_results": [
                {
                    "id": 27205,
                    "title": "Inception",
                    "release_date": "2010-07-16",
                    "original_title": "Inception",
                    "popularity": 50,
                    "vote_count": 30000,
                    "vote_average": 8.4,
                    "poster_path": "/poster.jpg",
                }
            ],
        }
        mock_resp.raise_for_status = MagicMock()

        client = self._make_client()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.find_by_imdb_id("tt1375666")
        self.assertIsNotNone(result)
        self.assertEqual(result.id, 27205)
        self.assertEqual(result.title, "Inception")
        self.assertEqual(result.year, 2010)

    def test_find_by_imdb_id_not_found(self):
        """IMDb ID inexistant → None."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"movie_results": []}
        mock_resp.raise_for_status = MagicMock()

        client = self._make_client()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.find_by_imdb_id("tt9999999")
        self.assertIsNone(result)

    def test_find_by_imdb_id_invalid(self):
        """IMDb ID vide ou malforme → None sans crash."""
        client = self._make_client()
        self.assertIsNone(client.find_by_imdb_id(""))
        self.assertIsNone(client.find_by_imdb_id(None))
        self.assertIsNone(client.find_by_imdb_id("invalid"))

    def test_find_by_imdb_id_cached(self):
        """Le 2eme appel utilise le cache (pas de requete HTTP)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "movie_results": [
                {
                    "id": 100,
                    "title": "Test Cache",
                    "release_date": "2020-01-01",
                    "original_title": "Test Cache",
                    "popularity": 1,
                    "vote_count": 1,
                    "vote_average": 5,
                    "poster_path": None,
                }
            ],
        }
        mock_resp.raise_for_status = MagicMock()

        # Utiliser un ID unique pour eviter les collisions de cache entre tests
        client = self._make_client()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            r1 = client.find_by_imdb_id("tt8888888")
            calls_after_first = mock_get.call_count
            r2 = client.find_by_imdb_id("tt8888888")
            self.assertEqual(r1.id, r2.id)
            # Pas de nouvel appel HTTP pour le 2eme lookup
            self.assertEqual(mock_get.call_count, calls_after_first)


class FindByTmdbIdTests(unittest.TestCase):
    """P1.1.c : lookup TMDb direct par ID — utilisé pour cross-check NFO <tmdbid>."""

    def _make_client(self):
        return TmdbClient(api_key="test", cache_path=Path("/tmp/test_cache_tmdbid.json"), timeout_s=5)

    def test_find_by_tmdb_id_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 27205,
            "title": "Inception",
            "original_title": "Inception",
            "release_date": "2010-07-16",
            "popularity": 50,
            "vote_count": 30000,
            "vote_average": 8.4,
            "poster_path": "/poster.jpg",
        }
        mock_resp.raise_for_status = MagicMock()

        client = self._make_client()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.find_by_tmdb_id(27205)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.id, 27205)
        self.assertEqual(result.title, "Inception")
        self.assertEqual(result.year, 2010)

    def test_find_by_tmdb_id_accepts_string(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 603,
            "title": "The Matrix",
            "original_title": "The Matrix",
            "release_date": "1999-03-30",
            "popularity": 70,
            "vote_count": 25000,
            "vote_average": 8.2,
            "poster_path": None,
        }
        mock_resp.raise_for_status = MagicMock()

        client = self._make_client()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.find_by_tmdb_id("603")  # string forme NFO
        assert result is not None
        self.assertEqual(result.id, 603)
        self.assertEqual(result.year, 1999)

    def test_find_by_tmdb_id_invalid_inputs(self):
        client = self._make_client()
        self.assertIsNone(client.find_by_tmdb_id(""))
        self.assertIsNone(client.find_by_tmdb_id(None))
        self.assertIsNone(client.find_by_tmdb_id("not_a_number"))
        self.assertIsNone(client.find_by_tmdb_id(0))
        self.assertIsNone(client.find_by_tmdb_id(-1))

    def test_find_by_tmdb_id_not_found(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {}  # Pas de id → considéré comme introuvable
        mock_resp.raise_for_status = MagicMock()

        client = self._make_client()
        with patch.object(client._session, "get", return_value=mock_resp):
            self.assertIsNone(client.find_by_tmdb_id(9999999))

    def test_find_by_tmdb_id_cached(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 77777,
            "title": "Cache Test",
            "original_title": "Cache Test",
            "release_date": "2020-01-01",
            "popularity": 1,
            "vote_count": 1,
            "vote_average": 5,
            "poster_path": None,
        }
        mock_resp.raise_for_status = MagicMock()

        client = self._make_client()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            r1 = client.find_by_tmdb_id(77777)
            calls_first = mock_get.call_count
            r2 = client.find_by_tmdb_id(77777)
            assert r1 is not None and r2 is not None
            self.assertEqual(r1.id, r2.id)
            self.assertEqual(mock_get.call_count, calls_first)


class NfoImdbCandidateTests(unittest.TestCase):
    """Tests pour l'injection du candidat nfo_imdb dans le pipeline scan."""

    def test_nfo_without_imdb(self):
        """Un .nfo sans IMDb ID → comportement inchange (candidats NFO titre+annee)."""
        import cinesort.domain.core as core_mod

        nfo = core_mod.NfoInfo(title="Inception", originaltitle="Inception", year=2010, tmdbid=None, imdbid=None)
        cands = core_mod.build_candidates_from_nfo(nfo)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0].source, "nfo")

    def test_nfo_with_imdb_no_tmdb_client(self):
        """Un .nfo avec IMDb ID mais pas de client TMDb → pas de candidat nfo_imdb (pas de crash)."""
        import cinesort.domain.core as core_mod

        nfo = core_mod.NfoInfo(title="Inception", originaltitle="Inception", year=2010, tmdbid=None, imdbid="tt1375666")
        cands = core_mod.build_candidates_from_nfo(nfo)
        # Le lookup IMDb se fait dans plan_support.py, pas dans build_candidates_from_nfo
        self.assertEqual(len(cands), 1)


class FallbackEnUsTests(unittest.TestCase):
    """Tests pour le fallback en-US quand fr-FR retourne 0 resultat."""

    def test_fallback_en_us_triggered(self):
        """Si fr-FR retourne 0 resultat → retry en en-US."""
        call_count = {"n": 0}

        def side_effect(*args, **kwargs):
            call_count["n"] += 1
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.raise_for_status = MagicMock()
            params = kwargs.get("params", {})
            if params.get("language") == "en-US":
                mock_resp.json.return_value = {
                    "results": [
                        {
                            "id": 100,
                            "title": "Test EN",
                            "release_date": "2020-01-01",
                            "original_title": "Test EN",
                            "popularity": 1,
                            "vote_count": 1,
                            "vote_average": 5,
                            "poster_path": None,
                        },
                    ]
                }
            else:
                mock_resp.json.return_value = {"results": []}
            return mock_resp

        client = TmdbClient(api_key="test", cache_path=Path("/tmp/test_fallback.json"), timeout_s=5)
        import cinesort.domain.core as core_mod

        with patch.object(client._session, "get", side_effect=side_effect):
            cands = core_mod.build_candidates_from_tmdb(client, "Test Film", year=2020, language="fr-FR")
        # Doit avoir des candidats via le fallback en-US
        self.assertGreater(len(cands), 0)


if __name__ == "__main__":
    unittest.main()

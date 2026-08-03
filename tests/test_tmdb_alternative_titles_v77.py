"""VN-D.2 (Vague N batch 3) : tests TMDb alternative_titles.

Couvre :
- `TmdbClient.get_alternative_titles()` : fetch + cache + filtre country
- `_rescore_with_alternative_titles()` : fetch declenche uniquement si
  sim_best < 0.85 ; cross-langue FR/EN remonte le score a 1.0 sur match
  exact.

Logic audit L05 : "Le Voyage de Chihiro" vs TMDb "Spirited Away" / original
"Sen to Chihiro no Kamikakushi" doit retrouver son film via les alias TMDb
(alt-FR "Le Voyage de Chihiro").
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from cinesort.app.plan_support import (
    _ALT_TITLES_FETCH_THRESHOLD,
    _rescore_with_alternative_titles,
)
from cinesort.infra.tmdb_client import TmdbClient


def _make_client() -> TmdbClient:
    tmp = tempfile.TemporaryDirectory(prefix="cinesort_alt_titles_")
    cache = Path(tmp.name) / "tmdb_cache.json"
    client = TmdbClient(api_key="test", cache_path=cache, timeout_s=5.0)
    # Conserver le tmpdir pour eviter sa destruction en fin de test
    client._tmpdir = tmp  # type: ignore[attr-defined]
    return client


class GetAlternativeTitlesTests(unittest.TestCase):
    """Tests pour TmdbClient.get_alternative_titles()."""

    def test_returns_alternatives_from_api(self) -> None:
        """API retourne les titres -> list[{iso_3166_1, title, type}]."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "id": 129,
            "titles": [
                {"iso_3166_1": "FR", "title": "Le Voyage de Chihiro", "type": ""},
                {"iso_3166_1": "US", "title": "Spirited Away", "type": ""},
                {"iso_3166_1": "ES", "title": "El viaje de Chihiro", "type": ""},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = b"x"

        client = _make_client()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.get_alternative_titles(129)

        self.assertEqual(len(result), 3)
        titles = {it["title"] for it in result}
        self.assertIn("Le Voyage de Chihiro", titles)
        self.assertIn("Spirited Away", titles)
        self.assertEqual(result[0]["iso_3166_1"], "FR")

    def test_country_code_filter(self) -> None:
        """country_code='FR' -> ne retourne que les alias FR."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "titles": [
                {"iso_3166_1": "FR", "title": "Le Voyage de Chihiro", "type": ""},
                {"iso_3166_1": "US", "title": "Spirited Away", "type": ""},
            ],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = b"x"

        client = _make_client()
        with patch.object(client._session, "get", return_value=mock_resp):
            result = client.get_alternative_titles(129, country_code="FR")

        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Le Voyage de Chihiro")

    def test_invalid_movie_id_returns_empty(self) -> None:
        """movie_id<=0 ou None -> [] sans appel reseau."""
        client = _make_client()
        with patch.object(client._session, "get") as mock_get:
            self.assertEqual(client.get_alternative_titles(0), [])
            self.assertEqual(client.get_alternative_titles(-5), [])
            self.assertEqual(client.get_alternative_titles(None), [])  # type: ignore[arg-type]
            mock_get.assert_not_called()

    def test_uses_cache_on_second_call(self) -> None:
        """2eme appel -> pas de requete HTTP (cache persistent)."""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {
            "titles": [{"iso_3166_1": "FR", "title": "Test FR", "type": ""}],
        }
        mock_resp.raise_for_status = MagicMock()
        mock_resp.content = b"x"

        client = _make_client()
        with patch.object(client._session, "get", return_value=mock_resp) as mock_get:
            client.get_alternative_titles(42)
            client.get_alternative_titles(42)
            self.assertEqual(mock_get.call_count, 1)

    def test_api_error_returns_empty_list(self) -> None:
        """Echec reseau -> [] gracieux, pas d'exception."""
        import requests

        client = _make_client()
        with patch.object(client._session, "get", side_effect=requests.RequestException("boom")):
            self.assertEqual(client.get_alternative_titles(99), [])


class RescoreWithAlternativeTitlesTests(unittest.TestCase):
    """Tests pour _rescore_with_alternative_titles (la logique cross-langue)."""

    def test_high_sim_skips_fetch(self) -> None:
        """sim_best >= 0.85 -> pas de fetch, perf preservee."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_alternative_titles = MagicMock(return_value=[])

        sim, source = _rescore_with_alternative_titles(
            0.95,
            tmdb_id=129,
            folder_clean="spirited away",
            video_clean="spirited away",
            tmdb=mock_tmdb,
        )

        self.assertEqual(sim, 0.95)
        self.assertIsNone(source)
        mock_tmdb.get_alternative_titles.assert_not_called()

    def test_threshold_value(self) -> None:
        """Sanity check : le seuil documente est bien 0.85."""
        self.assertEqual(_ALT_TITLES_FETCH_THRESHOLD, 0.85)

    def test_low_sim_triggers_fetch_and_finds_alt(self) -> None:
        """sim_best < 0.85 + alias FR exact -> sim remonte a 1.0."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_alternative_titles = MagicMock(
            return_value=[
                {"iso_3166_1": "FR", "title": "Le Voyage de Chihiro", "type": ""},
                {"iso_3166_1": "US", "title": "Spirited Away", "type": ""},
            ]
        )

        sim, source = _rescore_with_alternative_titles(
            0.20,  # folder FR vs original JP/US tres faible
            tmdb_id=129,
            folder_clean="le voyage de chihiro",
            video_clean="le voyage de chihiro",
            tmdb=mock_tmdb,
        )

        self.assertGreaterEqual(sim, 0.99)
        self.assertEqual(source, "alt-FR")
        mock_tmdb.get_alternative_titles.assert_called_once_with(129)

    def test_low_sim_no_match_keeps_original(self) -> None:
        """sim_best bas + aucune alt ne matche -> garde sim_best (pas de degat)."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_alternative_titles = MagicMock(
            return_value=[
                {"iso_3166_1": "ES", "title": "Otra Pelicula", "type": ""},
                {"iso_3166_1": "DE", "title": "Anderer Film", "type": ""},
            ]
        )

        sim, source = _rescore_with_alternative_titles(
            0.40,
            tmdb_id=129,
            folder_clean="le voyage de chihiro",
            video_clean="le voyage de chihiro",
            tmdb=mock_tmdb,
        )

        self.assertEqual(sim, 0.40)
        self.assertIsNone(source)
        mock_tmdb.get_alternative_titles.assert_called_once()

    def test_no_tmdb_client_skips(self) -> None:
        """tmdb=None -> no-op, retourne sim_best original."""
        sim, source = _rescore_with_alternative_titles(
            0.30,
            tmdb_id=129,
            folder_clean="foo",
            video_clean="foo",
            tmdb=None,
        )
        self.assertEqual(sim, 0.30)
        self.assertIsNone(source)

    def test_invalid_tmdb_id_skips(self) -> None:
        """tmdb_id <= 0 -> no-op."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_alternative_titles = MagicMock(return_value=[])

        sim, source = _rescore_with_alternative_titles(
            0.30,
            tmdb_id=0,
            folder_clean="foo",
            video_clean="foo",
            tmdb=mock_tmdb,
        )
        self.assertEqual(sim, 0.30)
        self.assertIsNone(source)
        mock_tmdb.get_alternative_titles.assert_not_called()

    def test_empty_alternatives_keeps_sim(self) -> None:
        """Alternatives vides (film recent sans alias) -> sim inchange."""
        mock_tmdb = MagicMock()
        mock_tmdb.get_alternative_titles = MagicMock(return_value=[])

        sim, source = _rescore_with_alternative_titles(
            0.30,
            tmdb_id=42,
            folder_clean="film",
            video_clean="film",
            tmdb=mock_tmdb,
        )
        self.assertEqual(sim, 0.30)
        self.assertIsNone(source)


if __name__ == "__main__":
    unittest.main()

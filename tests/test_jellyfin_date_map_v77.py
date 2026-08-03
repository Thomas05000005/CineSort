"""GATE R2.1 (2026-06-11) — durcit le fix 0ad9c99 (timeline Jellyfin).

Le GATE precedent patchait integralement _get_jellyfin_date_map, donc la ligne
corrigee (get_all_movies au lieu de get_movies inexistant) n'etait jamais
executee. Ce test exerce la VRAIE fonction avec un faux JellyfinClient et echoue
si on reintroduit le mauvais nom de methode.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from cinesort.ui.api import library_timeline_support


class JellyfinDateMapTests(unittest.TestCase):
    def _settings(self):
        return {
            "jellyfin_enabled": True,
            "jellyfin_url": "http://jf:8096",
            "jellyfin_api_key": "REAL_jf_key",
            "jellyfin_user_id": "user1",
            "jellyfin_library_id": "lib1",
        }

    def test_uses_get_all_movies_and_builds_map(self) -> None:
        client = MagicMock()
        # Le vrai client n'a PAS get_movies ; il a get_all_movies.
        del client.get_movies
        client.get_all_movies.return_value = [
            {"tmdb_id": 27205, "date_created": "2020-01-02T00:00:00Z"},
            {"tmdb_id": 603, "date_created": "2021-05-06T00:00:00Z"},
        ]
        with patch.object(library_timeline_support, "JellyfinClient", return_value=client):
            out = library_timeline_support._get_jellyfin_date_map(MagicMock(), self._settings())
        client.get_all_movies.assert_called_once_with("user1", library_id="lib1")
        self.assertEqual(out["27205"], "2020-01-02T00:00:00Z")
        self.assertEqual(out["603"], "2021-05-06T00:00:00Z")

    def test_disabled_returns_empty(self) -> None:
        out = library_timeline_support._get_jellyfin_date_map(MagicMock(), {"jellyfin_enabled": False})
        self.assertEqual(out, {})

    def test_get_movies_would_fail(self) -> None:
        # Garde-fou anti-regression : un client qui n'a QUE get_movies (l'ancien
        # mauvais nom) -> AttributeError avalee -> map vide (fallback mtime).
        client = MagicMock()
        del client.get_all_movies  # seule get_movies existerait
        with patch.object(library_timeline_support, "JellyfinClient", return_value=client):
            out = library_timeline_support._get_jellyfin_date_map(MagicMock(), self._settings())
        self.assertEqual(out, {}, "sans get_all_movies, fallback gracieux (map vide)")


if __name__ == "__main__":
    unittest.main()

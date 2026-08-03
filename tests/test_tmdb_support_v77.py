"""GATE AUDIT 2026-06-10 (CRITICAL) — get_tmdb_posters / search_tmdb ne levent
plus AttributeError (api._normalize_user_path inexistant -> HTTP 500) et
construisent le TmdbClient avec la VRAIE cle (pas le masque -> 401).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api import tmdb_support


class TmdbSupportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_tmdbsup_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)
        (self.state_dir / "settings.json").write_text(
            json.dumps({"tmdb_api_key": "REAL_tmdb_key_xyz", "tmdb_enabled": True}),
            encoding="utf-8",
        )
        self.api = backend.CineSortApi()
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_get_tmdb_posters_no_attribute_error_and_real_key(self) -> None:
        client = MagicMock()
        client.get_movie_poster_thumb_url.return_value = "https://image.tmdb.org/t/p/w92/a.jpg"
        with patch.object(tmdb_support, "TmdbClient", return_value=client) as cls:
            res = tmdb_support.get_tmdb_posters(self.api, [123])
        self.assertTrue(res.get("ok"), res)  # plus de 500/AttributeError
        self.assertEqual(res["posters"]["123"], "https://image.tmdb.org/t/p/w92/a.jpg")
        # La VRAIE cle est passee au client, pas le masque
        _args, kwargs = cls.call_args
        self.assertEqual(kwargs["api_key"], "REAL_tmdb_key_xyz")

    def test_search_tmdb_no_attribute_error_and_real_key(self) -> None:
        client = MagicMock()
        client.search_movie.return_value = []
        with patch.object(tmdb_support, "TmdbClient", return_value=client) as cls:
            res = tmdb_support.search_tmdb(self.api, "Inception", year=2010)
        self.assertTrue(res.get("ok"), res)
        _args, kwargs = cls.call_args
        self.assertEqual(kwargs["api_key"], "REAL_tmdb_key_xyz")

    def test_get_tmdb_posters_no_key_returns_reason(self) -> None:
        (self.state_dir / "settings.json").write_text(json.dumps({"tmdb_enabled": True}), encoding="utf-8")
        res = tmdb_support.get_tmdb_posters(self.api, [123])
        self.assertTrue(res.get("ok"))
        self.assertEqual(res.get("reason"), "tmdb_not_configured")


if __name__ == "__main__":
    unittest.main()

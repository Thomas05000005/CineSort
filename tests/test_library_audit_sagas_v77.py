"""GATE AUDIT 2026-06-10 (REAL 2/2) — _fetch_collection_parts construit un
TmdbClient valide (cache_path present, cle dé-masquee).

Avant : TmdbClient(api_key=api_key) omettait le parametre requis cache_path ->
TypeError avale -> _fetch_collection_parts toujours None -> get_incomplete_sagas
toujours sagas:[] (feature 'sagas incompletes' 100% morte).
"""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from cinesort.ui.api import library_audit_support


class _FakeApi:
    def __init__(self, settings):
        self._settings = settings

    def _internal_settings(self):
        return self._settings


class LibraryAuditSagasTests(unittest.TestCase):
    def test_fetch_collection_parts_builds_client_with_cache_path(self) -> None:
        api = _FakeApi({"tmdb_api_key": "REAL_key", "state_dir": "/tmp/x"})
        resp = MagicMock()
        resp.json.return_value = {"parts": [
            {"id": 1, "title": "Part 1", "release_date": "2010-01-01"},
            {"id": 2, "title": "Part 2", "release_date": "2014-01-01"},
        ]}
        client = MagicMock()
        client.api_key = "REAL_key"
        client._http_get.return_value = resp
        with patch("cinesort.infra.tmdb_client.TmdbClient", return_value=client) as cls:
            out = library_audit_support._fetch_collection_parts(api, 99)
        self.assertIsNotNone(out, "ne doit plus retourner None (TypeError avant)")
        self.assertEqual(len(out), 2)
        self.assertEqual(out[0]["year"], 2010)
        # cache_path fourni + vraie cle
        _args, kwargs = cls.call_args
        self.assertIn("cache_path", kwargs)
        self.assertEqual(kwargs["api_key"], "REAL_key")

    def test_fetch_collection_parts_no_key_returns_none(self) -> None:
        api = _FakeApi({"tmdb_api_key": "", "state_dir": "/tmp/x"})
        self.assertIsNone(library_audit_support._fetch_collection_parts(api, 99))


if __name__ == "__main__":
    unittest.main()

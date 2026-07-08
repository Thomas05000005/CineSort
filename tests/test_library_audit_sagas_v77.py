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


class ResolveRowTmdbIdTests(unittest.TestCase):
    """Audit 2026-07-08 — `PlanRow` n'a pas de `tmdb_id` top-level : il doit
    etre resolu depuis le meilleur `Candidate` de score >= 0.7. Avant, le champ
    top-level (toujours absent) etait lu tel quel -> tmdb_id toujours None ->
    ownership par tmdb_id mort -> films possedes faussement listes 'manquants'.
    """

    def test_resolves_from_best_candidate(self) -> None:
        row = {
            "candidates": [
                {"tmdb_id": 120, "score": 0.95},
                {"tmdb_id": 999, "score": 0.60},
            ]
        }
        self.assertEqual(library_audit_support._resolve_row_tmdb_id(row), 120)

    def test_low_score_candidate_ignored(self) -> None:
        row = {"candidates": [{"tmdb_id": 999, "score": 0.5}]}
        self.assertIsNone(library_audit_support._resolve_row_tmdb_id(row))

    def test_top_level_wins_if_present(self) -> None:
        row = {"tmdb_id": 42, "candidates": [{"tmdb_id": 120, "score": 0.95}]}
        self.assertEqual(library_audit_support._resolve_row_tmdb_id(row), 42)

    def test_no_candidates_returns_none(self) -> None:
        self.assertIsNone(library_audit_support._resolve_row_tmdb_id({}))

    def test_load_plan_rows_populates_tmdb_id_from_candidate(self) -> None:
        """Bout-en-bout : un plan dont les rows n'ont que des candidats doit
        produire des rows avec un `tmdb_id` non-None (set d'ownership non vide)."""
        plan = {
            "ok": True,
            "rows": [
                {
                    "row_id": "r1",
                    "proposed_title": "The Fellowship of the Ring",
                    "proposed_year": 2001,
                    "tmdb_collection_id": 119,
                    "tmdb_collection_name": "The Lord of the Rings",
                    "candidates": [{"tmdb_id": 120, "score": 0.9}],
                }
            ],
        }
        api = SimpleNamespace(run=SimpleNamespace(get_plan=lambda _rid: plan))
        rows = library_audit_support._load_plan_rows_with_collection(api, "run1")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["tmdb_id"], 120)


if __name__ == "__main__":
    unittest.main()

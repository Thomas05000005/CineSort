"""GATE AUDIT 2026-06-13 (R5-H2) — enrich_tmdb_ids_by_title resout + persiste le
tmdb_id de films identifies NFO/nom (sans tmdb_id) par recherche titre+annee.

Repond au cas biblio 100% NFO : reactiver TMDb seul ne suffit pas (la recherche
TMDb est court-circuitee au scan quand un NFO a matche, plan_support_dedup.py:18).
Ce bouton resout le tmdb_id a la demande -> les jaquettes suivent.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.ui.api import tmdb_support


class _FakeResult:
    def __init__(self, id, poster_path):
        self.id = id
        self.poster_path = poster_path


class _FakeTmdb:
    def __init__(self, mapping):
        # mapping: title.lower() -> _FakeResult (ou [] si absent)
        self._mapping = mapping
        self.searched = []

    def search_movie(self, query, year=None, **kw):
        self.searched.append((query, year))
        res = self._mapping.get(str(query).strip().lower())
        return [res] if res else []

    def flush(self):
        pass


class _FakeRunPaths:
    def __init__(self, plan_jsonl):
        self.plan_jsonl = plan_jsonl


class EnrichTmdbByTitleTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_enrich_")
        self.run_dir = Path(self._tmp) / "run"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.plan = self.run_dir / "plan.jsonl"
        rows = [
            {
                "row_id": "S|aaa",
                "proposed_title": "12 Hommes en colere",
                "proposed_year": 1957,
                "proposed_source": "nfo",
                "confidence": 87,
            },
            {
                "row_id": "S|bbb",
                "proposed_title": "Inconnu Total",
                "proposed_year": 2099,
                "proposed_source": "name",
                "confidence": 65,
            },
            {
                "row_id": "S|ccc",
                "proposed_title": "Deja TMDb",
                "proposed_year": 2000,
                "proposed_source": "tmdb",
                "confidence": 90,
                "tmdb_id": 999,
            },
        ]
        with open(self.plan, "w", encoding="utf-8") as fp:
            for r in rows:
                fp.write(json.dumps(r, ensure_ascii=False) + "\n")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_api(self, tmdb, with_key=True):
        api = mock.MagicMock()
        api._internal_settings.return_value = {
            "tmdb_api_key": "abc123" if with_key else "",
            "state_dir": str(self.run_dir),
        }
        api._run_paths_for.return_value = _FakeRunPaths(self.plan)
        return api

    def _rows(self):
        return [json.loads(l) for l in open(self.plan, encoding="utf-8") if l.strip()]

    def test_resolves_and_persists_tmdb_id(self) -> None:
        tmdb = _FakeTmdb({"12 hommes en colere": _FakeResult(389, "/poster389.jpg")})
        api = self._make_api(tmdb)
        with mock.patch.object(tmdb_support, "_build_tmdb_client", return_value=(tmdb, None)):
            res = tmdb_support.enrich_tmdb_ids_by_title(api, "run1", ["S|aaa", "S|bbb"])
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(res.get("resolved"), 1)  # seul aaa a un match
        self.assertIn("S|aaa", res.get("posters") or {})
        self.assertIn("/poster389.jpg", res["posters"]["S|aaa"])
        # PERSISTE dans le plan.
        rows = {r["row_id"]: r for r in self._rows()}
        self.assertEqual(rows["S|aaa"].get("tmdb_id"), 389)
        # Pas de match pour bbb -> pas de tmdb_id.
        self.assertIsNone(rows["S|bbb"].get("tmdb_id"))

    def test_does_not_touch_identification_fields(self) -> None:
        tmdb = _FakeTmdb({"12 hommes en colere": _FakeResult(389, "/p.jpg")})
        api = self._make_api(tmdb)
        before = {r["row_id"]: dict(r) for r in self._rows()}
        with mock.patch.object(tmdb_support, "_build_tmdb_client", return_value=(tmdb, None)):
            tmdb_support.enrich_tmdb_ids_by_title(api, "run1", ["S|aaa"])
        after = {r["row_id"]: r for r in self._rows()}
        # titre/annee/source/confiance INCHANGES (seul tmdb_id ajoute).
        for k in ("proposed_title", "proposed_year", "proposed_source", "confidence"):
            self.assertEqual(after["S|aaa"][k], before["S|aaa"][k], k)

    def test_skips_rows_already_having_tmdb_id(self) -> None:
        tmdb = _FakeTmdb({"deja tmdb": _FakeResult(111, "/x.jpg")})
        api = self._make_api(tmdb)
        with mock.patch.object(tmdb_support, "_build_tmdb_client", return_value=(tmdb, None)):
            tmdb_support.enrich_tmdb_ids_by_title(api, "run1", ["S|ccc"])
        # ccc avait deja tmdb_id 999 -> ne doit PAS etre re-resolu/ecrase.
        rows = {r["row_id"]: r for r in self._rows()}
        self.assertEqual(rows["S|ccc"].get("tmdb_id"), 999)
        self.assertNotIn(("Deja TMDb", 2000), tmdb.searched)

    def test_no_key_returns_config_error(self) -> None:
        api = self._make_api(None, with_key=False)
        # _build_tmdb_client reel : sans cle -> err config.
        res = tmdb_support.enrich_tmdb_ids_by_title(api, "run1", ["S|aaa"])
        self.assertFalse(res.get("ok"))

    def test_empty_rowids_validation_error(self) -> None:
        tmdb = _FakeTmdb({})
        api = self._make_api(tmdb)
        with mock.patch.object(tmdb_support, "_build_tmdb_client", return_value=(tmdb, None)):
            res = tmdb_support.enrich_tmdb_ids_by_title(api, "run1", [])
        self.assertFalse(res.get("ok"))


if __name__ == "__main__":
    unittest.main()

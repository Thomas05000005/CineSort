"""GATE AUDIT 2026-06-10 (REAL 2/2) — round-trip des champs TV/sous-titres.

plan_row_from_jsonable (cache incremental) et row_from_json (rechargement
plan.jsonl apres restart) ne restauraient PAS les champs TV (tv_season,
tv_episode, ...) -> apply_tv_episode renommait l'episode en S00E00.
"""

from __future__ import annotations

import unittest

import cinesort.domain.core as core
from cinesort.app.plan_support_core import plan_row_from_jsonable, plan_row_to_jsonable
from cinesort.ui.api.run_data_support import row_from_json


def _tv_row() -> core.PlanRow:
    return core.PlanRow(
        row_id="r1",
        kind="tv_episode",
        folder="C:/TV",
        video="ep.mkv",
        proposed_title="Breaking Bad",
        proposed_year=2008,
        proposed_source="tmdb",
        confidence=90,
        confidence_label="high",
        candidates=[],
        tv_series_name="Breaking Bad",
        tv_season=2,
        tv_episode=7,
        tv_episode_title="Negro y Azul",
        tv_tmdb_series_id=1396,
        subtitle_count=2,
        subtitle_languages=["fr", "en"],
        subtitle_formats=["srt"],
        subtitle_missing_langs=["de"],
        subtitle_orphans=1,
    )


class TvFieldsRoundTripTests(unittest.TestCase):
    def test_plan_row_from_jsonable_restores_tv_fields(self) -> None:
        row = _tv_row()
        data = plan_row_to_jsonable(row)
        restored = plan_row_from_jsonable(data)
        self.assertIsNotNone(restored)
        self.assertEqual(restored.tv_season, 2)
        self.assertEqual(restored.tv_episode, 7)
        self.assertEqual(restored.tv_series_name, "Breaking Bad")
        self.assertEqual(restored.tv_episode_title, "Negro y Azul")
        self.assertEqual(restored.tv_tmdb_series_id, 1396)
        self.assertEqual(restored.subtitle_languages, ["fr", "en"])
        self.assertEqual(restored.subtitle_missing_langs, ["de"])

    def test_row_from_json_restores_tv_fields(self) -> None:
        row = _tv_row()
        data = plan_row_to_jsonable(row)
        restored = row_from_json(data)
        self.assertEqual(restored.tv_season, 2)
        self.assertEqual(restored.tv_episode, 7)
        self.assertEqual(restored.tv_series_name, "Breaking Bad")
        self.assertEqual(restored.tv_tmdb_series_id, 1396)

    def test_season_zero_preserved(self) -> None:
        # Saison 0 = specials : ne doit pas devenir None.
        row = _tv_row()
        row.tv_season = 0
        row.tv_episode = 0
        data = plan_row_to_jsonable(row)
        self.assertEqual(plan_row_from_jsonable(data).tv_season, 0)
        self.assertEqual(row_from_json(data).tv_season, 0)


if __name__ == "__main__":
    unittest.main()

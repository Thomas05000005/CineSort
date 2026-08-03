"""Revue R2 du bump _PLAN_CACHE_VERSION 4 -> 5 (HIGH-20, row_id blake2b).

Contexte `ignored_alerts` (defaut 1) : cette table (migration 023) est la SEULE
keyee sur row_id SANS run_id (UNIQUE(row_id, alert_code)), sans DELETE/prune/FK
CASCADE. Le bump change TOUS les row_id au prochain scan : les lignes legacy
deviennent orphelines. Decision actee (voir le commentaire de _PLAN_CACHE_VERSION
dans cinesort/app/plan_support_core.py) : on NE purge PAS ces orphelines (elles
sont inoffensives, fail-open ; les purger les rendrait irrecuperables sans rien
apporter). Le fix durable — re-keyer ignored_alerts sur film_id — est hors de ce
bump. Il n'y a donc AUCUNE migration de purge a tester ici.

Defaut 2 (LOW) — teste ci-dessous : `plan_row_from_jsonable` (cache incremental)
defaultait `kind` a "" alors que `row_from_json` (plan.jsonl, chemin d'apply)
defaulte a "single". Deux defauts differents pour le MEME champ, alors que
l'invariant destructif d'apply_core repose sur une egalite EXACTE a "single".
"""

from __future__ import annotations

import logging
import unittest

from cinesort.app.plan_support_core import plan_row_from_jsonable
from cinesort.ui.api.run_data_support import row_from_json


class PlanKindDefaultTests(unittest.TestCase):
    """plan_row_from_jsonable : meme defaut de `kind` que le chemin d'apply."""

    @staticmethod
    def _payload(**overrides) -> dict:
        data = {
            "row_id": "S|0123456789abcdef",
            "folder": "/lib/Film (2020)",
            "video": "Film.mkv",
            "proposed_title": "Film",
            "proposed_year": 2020,
            "candidates": [],
        }
        data.update(overrides)
        return data

    def test_missing_kind_defaults_to_single(self) -> None:
        row = plan_row_from_jsonable(self._payload())
        self.assertIsNotNone(row)
        self.assertEqual(row.kind, "single")

    def test_empty_kind_defaults_to_single(self) -> None:
        row = plan_row_from_jsonable(self._payload(kind=""))
        self.assertIsNotNone(row)
        self.assertEqual(row.kind, "single")

    def test_parity_with_plan_jsonl_deserializer(self) -> None:
        """Les 2 deserialiseurs doivent produire le MEME kind pour la meme donnee."""
        for payload in (self._payload(), self._payload(kind=""), self._payload(kind=None)):
            cached = plan_row_from_jsonable(payload)
            applied = row_from_json(payload)
            self.assertIsNotNone(cached)
            self.assertEqual(
                cached.kind,
                applied.kind,
                f"divergence de kind entre cache incremental et plan.jsonl : {payload!r}",
            )

    def test_known_kinds_pass_through_without_warning(self) -> None:
        logger = logging.getLogger("cinesort.app.plan_support_core")
        for kind in ("single", "collection", "tv_episode", "extra"):
            with self.assertNoLogs(logger, level="WARNING"):
                row = plan_row_from_jsonable(self._payload(kind=kind))
            self.assertEqual(row.kind, kind)

    def test_unknown_kind_logs_warning_and_is_preserved(self) -> None:
        with self.assertLogs("cinesort.app.plan_support_core", level="WARNING") as caught:
            row = plan_row_from_jsonable(self._payload(kind="season_pack"))
        self.assertEqual(row.kind, "season_pack")
        self.assertTrue(any("kind inconnu" in msg for msg in caught.output))


if __name__ == "__main__":
    unittest.main()

"""AUDIT ULTRA 2026-07-13 vague 2 — reconciliation des flags subtitle_missing.

H3 (HIGH-4) BADGE SIDEBAR 'Qualite' : get_sidebar_counters comptait tout row
ayant AU MOINS un warning_flag BRUT, sans soustraire les alertes ignorees NI
reconcilier subtitle_missing_<lang> contre les pistes muxees -> ~898 vs ~186 a
l'ecran. Doit compter sur les flags EFFECTIFS reconcilies.

H4 (HIGH-5) EXPORT / RAPPORT : _build_row_payload exportait warning_flags /
subtitle_missing BRUTS -> un faux subtitle_missing_fr sur les films au FR muxe,
en contradiction avec l'ecran Verification. Doit reconcilier avec le
quality_report DEJA dans le scope.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace


class _Row(SimpleNamespace):
    """PlanRow minimale pour _build_row_payload / get_sidebar_counters."""

    def __init__(self, **kw):
        base = dict(
            row_id="row-1",
            kind="single",
            folder="D:/Films/X",
            video="x.mkv",
            proposed_title="X",
            proposed_year=2020,
            proposed_source="tmdb",
            confidence=90,
            confidence_label="high",
            nfo_path="",
            subtitle_count=0,
            subtitle_languages=[],
            subtitle_missing_langs=[],
            subtitle_orphans=0,
            notes="",
            warning_flags=[],
        )
        base.update(kw)
        super().__init__(**base)


# ---------------------------------------------------------------------------
# H4 : _build_row_payload (fonction quasi pure, testee en direct)
# ---------------------------------------------------------------------------
class BuildRowPayloadReconcileTests(unittest.TestCase):
    def test_subtitle_missing_dropped_when_muxed_present(self) -> None:
        from cinesort.ui.api.dashboard_support import _build_row_payload

        row = _Row(
            warning_flags=["subtitle_missing_fr", "not_a_movie"],
            subtitle_missing_langs=["fr"],
            subtitle_languages=[],
        )
        quality = {
            "tier": "gold",
            "score": 80,
            "metrics": {"detected": {}, "subtitles_embedded": [{"language": "fre"}]},
        }
        payload, _ok, _tier, _partial = _build_row_payload("run-1", row, {}, quality)
        # Le FR muxe (fre) reconcilie le flag perime -> retire, mais not_a_movie reste.
        self.assertNotIn("subtitle_missing_fr", payload["warning_flags"])
        self.assertIn("not_a_movie", payload["warning_flags"])
        self.assertEqual(payload["subtitle_missing"], "")

    def test_flag_kept_when_language_really_absent(self) -> None:
        from cinesort.ui.api.dashboard_support import _build_row_payload

        row = _Row(warning_flags=["subtitle_missing_fr"], subtitle_missing_langs=["fr"], subtitle_languages=[])
        quality = {"tier": "silver", "metrics": {"detected": {}}}  # aucun subtitles_embedded
        payload, *_ = _build_row_payload("run-1", row, {}, quality)
        self.assertEqual(payload["warning_flags"], "subtitle_missing_fr")
        self.assertEqual(payload["subtitle_missing"], "fr")

    def test_no_quality_report_keeps_raw_flags(self) -> None:
        from cinesort.ui.api.dashboard_support import _build_row_payload

        row = _Row(warning_flags=["duplicate_quality"], subtitle_missing_langs=[])
        payload, *_ = _build_row_payload("run-1", row, {}, {})
        self.assertEqual(payload["warning_flags"], "duplicate_quality")


# ---------------------------------------------------------------------------
# H3 : get_sidebar_counters (fakes minimaux)
# ---------------------------------------------------------------------------
class _FakeRunPaths:  # noqa: D401 - marqueur inerte
    pass


class _FakeQualityRepo:
    def __init__(self, reports):
        self._reports = reports

    def list_quality_reports(self, *, run_id):
        return self._reports


class _FakeApplyRepo:
    def get_last_reversible_apply_batch(self, run_id):
        return None


class _FakeFilmModal:
    def __init__(self, ignored):
        self._ignored = ignored

    def list_ignored_alerts_bulk(self, row_ids):
        return {rid: set(codes) for rid, codes in self._ignored.items() if rid in row_ids}


class _FakeRunRepo:
    def __init__(self, run_row):
        self._run_row = run_row

    def get_latest_run(self):
        return self._run_row


class _FakeStore:
    def __init__(self, run_row, reports, ignored):
        self.run = _FakeRunRepo(run_row)
        self.quality = _FakeQualityRepo(reports)
        self.apply = _FakeApplyRepo()
        self.film_modal = _FakeFilmModal(ignored)


class _FakeSettingsFacade:
    def get_settings(self):
        return {"state_dir": str(Path.cwd())}


class _FakeApi:
    def __init__(self, store, rows):
        self.settings = _FakeSettingsFacade()
        self._store = store
        self._rows = rows

    def _get_or_create_infra(self, _state_dir):
        return self._store, None

    def _run_paths_for(self, _state_dir, _run_id, ensure_exists=False):
        return _FakeRunPaths()

    def _load_rows_from_plan_jsonl(self, _run_paths):
        return self._rows

    def _load_decisions_from_validation(self, _run_paths):
        return {}


class SidebarQualityBadgeReconcileTests(unittest.TestCase):
    def test_quality_badge_uses_effective_reconciled_flags(self) -> None:
        from cinesort.ui.api.dashboard_support import get_sidebar_counters

        rows = [
            # a) faux subtitle_missing_fr (FR muxe present) -> NE compte PAS
            _Row(row_id="a", proposed_title="A", proposed_year=2001, warning_flags=["subtitle_missing_fr"]),
            # b) vrai flag -> compte
            _Row(row_id="b", proposed_title="B", proposed_year=2002, warning_flags=["not_a_movie"]),
            # c) unique flag IGNORE par l'utilisateur -> NE compte PAS
            _Row(row_id="c", proposed_title="C", proposed_year=2003, warning_flags=["nfo_year_mismatch"]),
        ]
        reports = [{"row_id": "a", "metrics": {"subtitles_embedded": [{"language": "fre"}]}}]
        ignored = {"c": {"nfo_year_mismatch"}}
        run_row = {"run_id": "run-1", "state_dir": str(Path.cwd())}
        api = _FakeApi(_FakeStore(run_row, reports, ignored), rows)

        out = get_sidebar_counters(api)
        # Avant le fix : 3 (tout row avec un flag brut). Apres : 1 (seul "b").
        self.assertEqual(out["quality"], 1)

    def test_quality_badge_zero_when_all_reconciled_or_ignored(self) -> None:
        from cinesort.ui.api.dashboard_support import get_sidebar_counters

        rows = [
            _Row(row_id="a", proposed_title="A", proposed_year=2001, warning_flags=["subtitle_missing_fr"]),
        ]
        reports = [{"row_id": "a", "metrics": {"subtitles_embedded": [{"language": "fr"}]}}]
        run_row = {"run_id": "run-1", "state_dir": str(Path.cwd())}
        api = _FakeApi(_FakeStore(run_row, reports, {}), rows)
        self.assertEqual(get_sidebar_counters(api)["quality"], 0)


if __name__ == "__main__":
    unittest.main()

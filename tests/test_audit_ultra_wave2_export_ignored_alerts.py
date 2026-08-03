"""AUDIT ULTRA 2026-07-13 vague 2 — H4 (LOW) : l'export doit soustraire les
alertes IGNOREES, pas seulement reconcilier les subtitle_missing.

Defaut : _build_row_payload lisait row.warning_flags BRUTS. Une alerte qu'un
utilisateur a "Ignoree" (film_modal.ignored_alerts) restait dans l'export
JSON/CSV/HTML/NFO alors qu'elle avait disparu de l'ecran Verification (qui passe
par history_support._subtract_ignored_flags AVANT _enrich_plan_payload).

Fix : _build_row_payload accepte ``ignored_alerts`` (recupere en BULK par
build_run_report_payload via run_read_support.ignored_alerts_by_row) et les
soustrait AVANT la reconciliation sous-titres. L'export redevient le miroir exact
de l'ecran Verification.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace


class _Row(SimpleNamespace):
    """PlanRow minimale pour _build_row_payload / build_run_report_payload."""

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
# Niveau fonction : _build_row_payload(..., ignored_alerts=...)
# ---------------------------------------------------------------------------
class BuildRowPayloadIgnoredAlertsTests(unittest.TestCase):
    def test_ignored_alert_subtracted_from_export_flags(self) -> None:
        from cinesort.ui.api.dashboard_support import _build_row_payload

        row = _Row(warning_flags=["not_a_movie", "nfo_year_mismatch"])
        # L'utilisateur a "Ignore" nfo_year_mismatch -> ne doit plus etre exporte.
        payload, *_ = _build_row_payload("run-1", row, {}, {}, {"nfo_year_mismatch"})
        exported = payload["warning_flags"].split("|") if payload["warning_flags"] else []
        self.assertNotIn("nfo_year_mismatch", exported)
        self.assertIn("not_a_movie", exported)

    def test_none_keeps_all_flags(self) -> None:
        from cinesort.ui.api.dashboard_support import _build_row_payload

        row = _Row(warning_flags=["not_a_movie", "nfo_year_mismatch"])
        payload, *_ = _build_row_payload("run-1", row, {}, {}, None)
        self.assertEqual(payload["warning_flags"], "not_a_movie|nfo_year_mismatch")

    def test_subtraction_preserves_order_before_subtitle_reconcile(self) -> None:
        from cinesort.ui.api.dashboard_support import _build_row_payload

        # a) l'ignore est retire, b) l'ordre des flags restants est conserve,
        # c) le subtitle_missing_fr perime (FR muxe) est ensuite reconcilie.
        row = _Row(
            warning_flags=["duplicate_quality", "nfo_year_mismatch", "subtitle_missing_fr"],
            subtitle_missing_langs=["fr"],
        )
        quality = {"metrics": {"detected": {}, "subtitles_embedded": [{"language": "fre"}]}}
        payload, *_ = _build_row_payload("run-1", row, {}, quality, {"nfo_year_mismatch"})
        self.assertEqual(payload["warning_flags"], "duplicate_quality")
        self.assertEqual(payload["subtitle_missing"], "")


# ---------------------------------------------------------------------------
# Bout-en-bout : build_run_report_payload (cablage BULK de l'appelant)
# ---------------------------------------------------------------------------
class _FakeRunPaths(SimpleNamespace):
    pass


class _FakeQualityRepo:
    def list_quality_reports(self, *, run_id):
        return []


class _FakeFilmModal:
    def __init__(self, ignored):
        self._ignored = ignored

    def list_ignored_alerts_bulk(self, row_ids):
        return {rid: list(codes) for rid, codes in self._ignored.items() if rid in row_ids}


class _FakeStore:
    def __init__(self, ignored):
        self.quality = _FakeQualityRepo()
        self.film_modal = _FakeFilmModal(ignored)


class _FakeApi:
    def __init__(self, store, rows, run_paths):
        self._store = store
        self._rows = rows
        self._run_paths = run_paths
        self._state_dir = Path(".")

    def _get_run(self, _run_id):
        return None

    def _find_run_row(self, _run_id):
        return {"run_id": "run-1", "state_dir": str(Path.cwd()), "status": "DONE"}, self._store

    def _run_paths_for(self, _state_dir, _run_id, ensure_exists=False):
        return self._run_paths

    def _load_rows_from_plan_jsonl(self, _run_paths):
        return self._rows

    def _cfg_from_run_row(self, _run_row):
        return SimpleNamespace(root="D:/Films")

    def _load_decisions_from_validation(self, _run_paths):
        return {}

    def _normalize_decisions_for_rows(self, _rows, _decisions):
        return {}


class BuildRunReportPayloadMirrorsScreenTests(unittest.TestCase):
    def _make(self, ignored):
        tmp = Path.cwd() / "does_not_exist_xyz"
        run_paths = _FakeRunPaths(
            run_dir=tmp,
            plan_jsonl=tmp / "plan.jsonl",
            validation_json=tmp / "validation.json",
            summary_txt=tmp / "summary.txt",
            ui_log_txt=tmp / "ui.log",
        )
        rows = [
            _Row(row_id="A", proposed_title="A", warning_flags=["not_a_movie", "nfo_year_mismatch"]),
            _Row(row_id="B", proposed_title="B", warning_flags=["not_a_movie"]),
        ]
        api = _FakeApi(_FakeStore(ignored), rows, run_paths)
        return api

    def test_export_drops_ignored_alert_keeps_others(self) -> None:
        from cinesort.ui.api.dashboard_support import build_run_report_payload

        # A : nfo_year_mismatch a ete IGNORE -> disparait de l'export. B : intact.
        api = self._make({"A": {"nfo_year_mismatch"}})
        built, _paths = build_run_report_payload(api, "run-1")
        self.assertTrue(built.get("ok"), built)
        rows_by_id = {r["row_id"]: r for r in built["report"]["rows"]}

        flags_a = rows_by_id["A"]["warning_flags"].split("|") if rows_by_id["A"]["warning_flags"] else []
        flags_b = rows_by_id["B"]["warning_flags"].split("|") if rows_by_id["B"]["warning_flags"] else []
        self.assertNotIn("nfo_year_mismatch", flags_a)
        self.assertIn("not_a_movie", flags_a)
        # L'autre row (aucune alerte ignoree) reste inchangee.
        self.assertEqual(flags_b, ["not_a_movie"])

    def test_export_without_ignored_is_unchanged(self) -> None:
        from cinesort.ui.api.dashboard_support import build_run_report_payload

        api = self._make({})
        built, _paths = build_run_report_payload(api, "run-1")
        self.assertTrue(built.get("ok"), built)
        rows_by_id = {r["row_id"]: r for r in built["report"]["rows"]}
        self.assertEqual(rows_by_id["A"]["warning_flags"], "not_a_movie|nfo_year_mismatch")
        self.assertEqual(rows_by_id["B"]["warning_flags"], "not_a_movie")


if __name__ == "__main__":
    unittest.main()

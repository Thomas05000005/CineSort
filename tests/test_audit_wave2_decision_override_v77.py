"""AUDIT ULTRA 2026-07-13 vague 2 — decision historique + override TMDb.

H8 (HIGH-9) STATUT DU FILM DANS L'HISTORIQUE : films[].decision etait lu depuis
pr.get("decision") ou pr = asdict(PlanRow) qui n'a AUCUN champ `decision` -> ""
systematique. Doit venir de validation.json (tri-etat accepted/rejected/deferred).

H13 (HIGH-14) OVERRIDE TMDb PERDU : l'override manuel (film_tmdb_overrides) n'etait
overlaye ni dans get_plan (le seed Validation gardait l'annee perimee) ni sur la
DECISION a l'apply (title/year perimes materialises) -> mauvais titre/annee sur
disque. Doit etre overlaye dans _enrich_plan_payload ET dans _validate_apply.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


# ===========================================================================
# H8 : get_history_stats -> films[].decision depuis validation.json
# ===========================================================================
class _FakeRunPaths(SimpleNamespace):
    pass


class _FakeQualityRepo:
    def __init__(self, reports):
        self._reports = reports

    def list_quality_reports(self, *, run_id):
        return self._reports


class _FakeApplyRepo:
    def get_last_reversible_apply_batch(self, run_id):
        return None

    def list_apply_operations(self, *, batch_id):
        return []

    def list_duplicate_decisions(self, *, run_id):
        return []


class _FakeRunRepo:
    def list_errors(self, run_id):
        return []


class _FakeStoreH8:
    def __init__(self, reports):
        self.run = _FakeRunRepo()
        self.quality = _FakeQualityRepo(reports)
        self.apply = _FakeApplyRepo()


class _FakeRunFacadeH8:
    def __init__(self, plan_rows, decisions):
        self._plan_rows = plan_rows
        self._decisions = decisions

    def get_plan(self, run_id):
        return {"ok": True, "rows": self._plan_rows}

    def load_validation(self, run_id):
        return {"ok": True, "decisions": self._decisions}


class _FakeApiH8:
    def __init__(self, row, store, plan_rows, decisions, state_dir):
        self._row = row
        self._store = store
        self.run = _FakeRunFacadeH8(plan_rows, decisions)
        self._state_dir = state_dir

    def _is_valid_run_id(self, run_id):
        return bool(run_id)

    def _find_run_row(self, run_id):
        return (self._row, self._store)

    def _run_paths_for(self, _state_dir, _run_id, ensure_exists=False):
        # plan.jsonl inexistant -> count_plan_rows retombe sur le fallback stats.
        return _FakeRunPaths(plan_jsonl=Path(self._state_dir) / "nope.jsonl")


class HistoryDecisionFromValidationTests(unittest.TestCase):
    def _run(self, plan_rows, quality_reports, decisions):
        from cinesort.ui.api.history_support import get_history_stats

        rid = "20260101_100000_000"
        row = {
            "run_id": rid,
            "started_ts": 1000.0,
            "ended_ts": 1100.0,
            "status": "DONE",
            "state_dir": str(Path.cwd()),
            "total": len(plan_rows),
            "stats_json": json.dumps({"planned_rows": len(plan_rows)}),
        }
        api = _FakeApiH8(row, _FakeStoreH8(quality_reports), plan_rows, decisions, str(Path.cwd()))
        out = get_history_stats(api, rid)
        self.assertTrue(out.get("ok"), out)
        return {f["film_id"]: f for f in out["run"]["films"]}

    def test_decision_reflects_user_choice_not_tier(self) -> None:
        plan_rows = [
            {"row_id": "a", "proposed_title": "Film A", "proposed_year": 1975},
            {"row_id": "b", "proposed_title": "Film B", "proposed_year": 2020},
        ]
        quality_reports = [
            {"row_id": "a", "tier": "gold", "score": 90},  # bonne qualite MAIS rejete
            {"row_id": "b", "tier": "reject", "score": 20},  # mauvaise qualite MAIS accepte
        ]
        decisions = {
            "a": {"ok": False, "decision": "rejected", "title": "Film A", "year": 1975},
            "b": {"ok": True, "decision": "accepted", "title": "Film B", "year": 2020},
        }
        films = self._run(plan_rows, quality_reports, decisions)
        # Avant le fix : "" pour les deux (pr.get("decision") sur une PlanRow sans ce champ).
        self.assertEqual(films["a"]["decision"], "rejected")
        self.assertEqual(films["b"]["decision"], "accepted")

    def test_undecided_film_has_empty_decision(self) -> None:
        # Un film SANS decision explicite ne doit PAS etre classe (le front retombe
        # alors sur le tier). Garde-fou anti-regression : pas de fallback ok->rejected.
        plan_rows = [{"row_id": "a", "proposed_title": "Film A", "proposed_year": 1999}]
        quality_reports = [{"row_id": "a", "tier": "silver", "score": 60}]
        decisions = {"a": {"ok": False, "title": "Film A", "year": 1999}}  # pas de cle `decision`
        films = self._run(plan_rows, quality_reports, decisions)
        self.assertEqual(films["a"]["decision"], "")


# ===========================================================================
# H13 : override TMDb overlaye dans get_plan (_enrich_plan_payload)
# ===========================================================================
class _FakeFilmModal:
    def __init__(self, overrides):
        self._ov = overrides

    def get_tmdb_override(self, *, run_id, row_id):
        return self._ov.get(row_id)


class _FakeQualityEmpty:
    def list_quality_reports(self, *, run_id):
        return []


class _FakeStoreOverride:
    def __init__(self, overrides):
        self.film_modal = _FakeFilmModal(overrides)
        self.quality = _FakeQualityEmpty()


class _FakeSettingsFacade:
    def get_settings(self):
        return {"state_dir": str(Path.cwd())}


class _FakeApiEnrich:
    def __init__(self, store):
        self.settings = _FakeSettingsFacade()
        self._store = store

    def _get_or_create_infra(self, _state_dir):
        return self._store, None

    def _get_settings_impl(self):
        return {"auto_approve_threshold": 85}


class EnrichPlanOverridesTests(unittest.TestCase):
    def test_override_overlaid_in_enriched_payload(self) -> None:
        from cinesort.ui.api.history_support import _enrich_plan_payload

        overrides = {"a": {"tmdb_id": 999, "new_confidence": 92, "proposed_title": "The Thing", "proposed_year": 2011}}
        api = _FakeApiEnrich(_FakeStoreOverride(overrides))
        payload = [
            {"row_id": "a", "proposed_title": "The Thing", "proposed_year": 1982, "confidence": 65, "warning_flags": []}
        ]
        out = _enrich_plan_payload(api, "run-1", payload)
        self.assertEqual(out[0]["proposed_year"], 2011)  # avant : 1982 (perime)
        self.assertEqual(out[0]["confidence"], 92)
        self.assertEqual(out[0].get("chosen_tmdb_id"), 999)

    def test_no_override_is_noop(self) -> None:
        from cinesort.ui.api.history_support import _enrich_plan_payload

        api = _FakeApiEnrich(_FakeStoreOverride({}))
        payload = [
            {"row_id": "a", "proposed_title": "Dune", "proposed_year": 2021, "confidence": 88, "warning_flags": []}
        ]
        out = _enrich_plan_payload(api, "run-1", payload)
        self.assertEqual(out[0]["proposed_year"], 2021)


# ===========================================================================
# H13 : override TMDb overlaye sur la DECISION dans _validate_apply
# ===========================================================================
class _FakeStoreValidate:
    def __init__(self, overrides):
        self.film_modal = _FakeFilmModal(overrides)


class _FakeApiValidate:
    def __init__(self, ctx):
        self._ctx = ctx

    def _is_valid_run_id(self, run_id):
        return bool(run_id)

    def _run_context_for_apply(self, _run_id):
        return self._ctx

    def _load_decisions_from_validation(self, _run_paths):
        return {}

    def _merge_decisions(self, incoming, disk):
        merged = dict(disk or {})
        merged.update(incoming or {})
        return merged

    def _normalize_decisions_for_rows(self, rows, merged):
        from cinesort.ui.api.run_data_support import normalize_decisions_for_rows

        return normalize_decisions_for_rows(rows, merged)

    def log_api_exception(self, *a, **k):
        pass


class ValidateApplyOverrideTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_wave2_validate_"))

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_override_year_wins_over_stale_decision(self) -> None:
        from cinesort.ui.api.apply_support import _validate_apply

        rows = [SimpleNamespace(row_id="a", proposed_title="The Thing", proposed_year=1982)]
        run_paths = SimpleNamespace(validation_json=self._tmp / "validation.json")
        cfg = SimpleNamespace(root="D:/Films")
        ctx = (
            cfg,
            run_paths,
            rows,
            lambda *_: None,
            _FakeStoreValidate(
                {"a": {"tmdb_id": 999, "new_confidence": 90, "proposed_title": "The Thing", "proposed_year": 2011}}
            ),
        )
        api = _FakeApiValidate(ctx)
        # La decision UI seedee depuis le plan PERIME (annee 1982).
        incoming = {"a": {"ok": True, "title": "The Thing", "year": 1982}}

        res = _validate_apply(api, "run-1", incoming, dry_run=True, quarantine_unapproved=False)
        self.assertTrue(res.get("ok"), res)
        safe_decisions = res["_ctx"][5]
        # Avant le fix : 1982 (annee perimee materialisee). Apres : 2011 (override).
        self.assertEqual(int(safe_decisions["a"]["year"]), 2011)


if __name__ == "__main__":
    unittest.main()

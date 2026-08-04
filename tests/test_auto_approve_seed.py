"""[auto-approve] Seed READ-TIME des décisions de Validation (PHASE5_ARBITRAGES §2).

Les settings `auto_approve_enabled` / `auto_approve_threshold` étaient write-only
(aucun consommateur). Ils pré-remplissent désormais l'étape Validation : les films
dont la confiance ≥ seuil (et sans warning critique/intégrité, avec titre+année)
sont pré-marqués `accepted` DANS LE PAYLOAD affiché — jamais persistés. dry_run et
la confirmation d'apply restent intacts : rien n'atteint le disque tant que
l'utilisateur n'a pas fait un save_validation explicite.

Invariants :
  1. Prédicat is_auto_approvable = confiance≥seuil + titre + année + 0 critical/integrity.
  2. seed n'écrase JAMAIS une décision existante (utilisateur / disque).
  3. seed = no-op si auto_approve_enabled est faux.
  4. load_validation avec le flag actif NE PERSISTE PAS validation.json (read-only).
"""

from __future__ import annotations

import tempfile
import types
import unittest
from pathlib import Path

from cinesort.ui.api import history_support, run_data_support
from cinesort.ui.api.run_read_support import is_auto_approvable, seed_auto_approve_decisions


def _row(row_id: str, confidence: int, *, title: str = "Un Film", year: int = 2010, flags=None):
    return types.SimpleNamespace(
        row_id=row_id,
        confidence=confidence,
        proposed_title=title,
        proposed_year=year,
        warning_flags=list(flags or []),
    )


class _FakeSettingsApi:
    """api minimal exposant _get_settings_impl + _normalize_decisions_for_rows."""

    def __init__(self, enabled: bool, threshold: int = 85):
        self._settings = {"auto_approve_enabled": enabled, "auto_approve_threshold": threshold}

    def _get_settings_impl(self):
        return dict(self._settings)

    def _normalize_decisions_for_rows(self, rows, decisions):
        return run_data_support.normalize_decisions_for_rows(rows, decisions)


class IsAutoApprovableTests(unittest.TestCase):
    def test_high_confidence_ok(self):
        self.assertTrue(is_auto_approvable(_row("r1", 90), 85))

    def test_below_threshold_rejected(self):
        self.assertFalse(is_auto_approvable(_row("r1", 84), 85))

    def test_missing_title_or_year(self):
        self.assertFalse(is_auto_approvable(_row("r1", 99, title=""), 85))
        self.assertFalse(is_auto_approvable(_row("r1", 99, year=0), 85))

    def test_critical_or_integrity_warning_blocks(self):
        self.assertFalse(is_auto_approvable(_row("r1", 99, flags=["nfo_title_mismatch"]), 85))
        self.assertFalse(is_auto_approvable(_row("r1", 99, flags=["integrity_probe_failed"]), 85))


class SeedAutoApproveTests(unittest.TestCase):
    def test_disabled_is_noop(self):
        api = _FakeSettingsApi(enabled=False)
        existing = {"r1": {"ok": False}}
        out = seed_auto_approve_decisions(api, [_row("r1", 99), _row("r2", 99)], existing)
        self.assertEqual(out, existing)  # inchangé

    def test_enabled_premark_high_confidence(self):
        api = _FakeSettingsApi(enabled=True, threshold=85)
        rows = [_row("r1", 92), _row("r2", 40), _row("r3", 88, flags=["nfo_year_mismatch"])]
        out = seed_auto_approve_decisions(api, rows, {})
        self.assertEqual(out["r1"], {"ok": True, "decision": "accepted", "title": "Un Film", "year": 2010})
        self.assertNotIn("r2", out)  # basse confiance → pas pré-marqué
        self.assertNotIn("r3", out)  # warning critique → pas pré-marqué

    def test_never_overrides_existing_decision(self):
        api = _FakeSettingsApi(enabled=True, threshold=85)
        # r1 déjà rejeté par l'utilisateur, malgré haute confiance.
        existing = {"r1": {"ok": False, "decision": "rejected"}}
        out = seed_auto_approve_decisions(api, [_row("r1", 99)], existing)
        self.assertEqual(out["r1"], {"ok": False, "decision": "rejected"})


class LoadValidationSeedTests(unittest.TestCase):
    """load_validation applique l'overlay SANS persister validation.json."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_autoapprove_")
        self.validation_json = Path(self._tmp) / "validation.json"

    def _api(self, enabled: bool, rows):
        rs = types.SimpleNamespace(
            paths=types.SimpleNamespace(validation_json=self.validation_json),
            rows=rows,
        )
        api = _FakeSettingsApi(enabled=enabled)
        api._is_valid_run_id = lambda run_id: True
        api._get_run = lambda run_id: rs
        api._load_rows_from_plan_jsonl = lambda paths: rows
        return api

    def test_first_visit_premarks_without_persisting(self):
        rows = [_row("r1", 95), _row("r2", 30)]
        api = self._api(enabled=True, rows=rows)
        out = history_support.load_validation(api, "run1", normalize_user_path=lambda *a, **k: None)
        self.assertTrue(out["ok"])
        decisions = out["decisions"]
        self.assertTrue(decisions["r1"]["ok"])
        self.assertEqual(decisions["r1"].get("decision"), "accepted")
        self.assertFalse(decisions["r2"]["ok"])  # basse confiance → à revoir
        # NON-PERSISTANCE : le fichier ne doit PAS avoir été créé.
        self.assertFalse(self.validation_json.exists(), "validation.json persisté (apply direct !)")

    def test_first_visit_disabled_returns_empty(self):
        # Flag off : comportement inchangé (aucune décision, aucun fichier créé).
        api = self._api(enabled=False, rows=[_row("r1", 99)])
        out = history_support.load_validation(api, "run1", normalize_user_path=lambda *a, **k: None)
        self.assertEqual(out["decisions"], {})
        self.assertFalse(self.validation_json.exists())


if __name__ == "__main__":
    unittest.main()

"""M-2 audit QA 20260429 — tests auto-quarantine films corrompus.

Verifie que get_auto_approved_summary :
- Sans quarantine_corrupted, route les films integrity_invalid en
  manual_review (comportement legacy).
- Avec quarantine_corrupted=True, les route en auto_quarantine
  (sortis de manual_review et auto_approve).
- Les rows sans warning d'integrite restent traites normalement.
- Le setting `auto_quarantine_corrupted` est dans defaults (False).
"""

from __future__ import annotations

import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

from cinesort.ui.api.run_read_support import get_auto_approved_summary


def _row(
    row_id: str, *, confidence: int = 90, warnings: list = None, title: str = "Film", year: int = 2010
) -> SimpleNamespace:
    return SimpleNamespace(
        row_id=row_id,
        confidence=confidence,
        warning_flags=list(warnings or []),
        proposed_title=title,
        proposed_year=year,
    )


def _make_api(rows: list, valid: bool = True, done: bool = True):
    api = MagicMock()
    api._is_valid_run_id = MagicMock(return_value=valid)
    rs = SimpleNamespace(
        rows=rows,
        done=done,
        paths=None,
    )
    api._get_run = MagicMock(return_value=rs)
    api._load_rows_from_plan_jsonl = MagicMock(return_value=rows)
    return api


class AutoQuarantineCorruptedTests(unittest.TestCase):
    def test_legacy_behavior_corrupted_goes_to_manual(self) -> None:
        """Sans quarantine_corrupted, films corrompus -> manual_review."""
        rows = [
            _row("r1", confidence=90, warnings=[]),
            _row("r2", confidence=90, warnings=["integrity_header_invalid"]),
            _row("r3", confidence=90, warnings=["integrity_probe_failed"]),
            _row("r4", confidence=90, warnings=[]),
        ]
        api = _make_api(rows)
        result = get_auto_approved_summary(api, "run", threshold=80, enabled=True, quarantine_corrupted=False)
        self.assertTrue(result["ok"])
        # Tous high-confidence sont auto_approved sauf les corrompus qui
        # vont en manual_review (car has_critical=False mais integrity_warning
        # n'est pas dans critical_warnings, ils passent en auto-approve dans
        # le legacy ; mais maintenant on les exclut aussi sans setting)
        # Note : le code modifie exclut TOUJOURS les integrity_warnings de
        # l'auto-approve, c'est plus prudent.
        self.assertEqual(result["auto_approved"], 2)  # r1, r4
        self.assertEqual(result["manual_review"], 2)  # r2, r3
        self.assertEqual(result["auto_quarantine"], 0)
        self.assertIn("r1", result["auto_row_ids"])
        self.assertIn("r4", result["auto_row_ids"])

    def test_quarantine_corrupted_enabled(self) -> None:
        """Avec quarantine_corrupted=True, films corrompus -> auto_quarantine."""
        rows = [
            _row("r1", confidence=90, warnings=[]),
            _row("r2", confidence=90, warnings=["integrity_header_invalid"]),
            _row("r3", confidence=50, warnings=["integrity_probe_failed"]),
            _row("r4", confidence=90, warnings=[]),
            _row("r5", confidence=50, warnings=[]),  # low confidence -> manual
        ]
        api = _make_api(rows)
        result = get_auto_approved_summary(api, "run", threshold=80, enabled=True, quarantine_corrupted=True)
        self.assertEqual(result["auto_approved"], 2)  # r1, r4
        self.assertEqual(result["auto_quarantine"], 2)  # r2, r3 (peu importe confidence)
        self.assertEqual(result["manual_review"], 1)  # r5
        self.assertEqual(set(result["auto_quarantine_row_ids"]), {"r2", "r3"})

    def test_quarantine_corrupted_disabled_no_quarantine_ids(self) -> None:
        """Sans setting, auto_quarantine_row_ids reste vide meme avec films corrompus."""
        rows = [_row("r1", confidence=90, warnings=["integrity_header_invalid"])]
        api = _make_api(rows)
        result = get_auto_approved_summary(api, "run", quarantine_corrupted=False)
        self.assertEqual(result["auto_quarantine_row_ids"], [])
        self.assertEqual(result["auto_quarantine"], 0)

    def test_no_corruption_no_quarantine(self) -> None:
        """Si aucun film corrompu, auto_quarantine reste 0 meme avec setting on."""
        rows = [_row("r1", confidence=90, warnings=[]), _row("r2", confidence=90, warnings=[])]
        api = _make_api(rows)
        result = get_auto_approved_summary(api, "run", threshold=80, enabled=True, quarantine_corrupted=True)
        self.assertEqual(result["auto_quarantine"], 0)
        self.assertEqual(result["auto_approved"], 2)

    def test_returns_quarantine_corrupted_flag_in_response(self) -> None:
        """Le retour echo le flag quarantine_corrupted (utile pour debug UI)."""
        api = _make_api([])
        result = get_auto_approved_summary(api, "run", quarantine_corrupted=True)
        self.assertTrue(result["quarantine_corrupted"])

        result = get_auto_approved_summary(api, "run", quarantine_corrupted=False)
        self.assertFalse(result["quarantine_corrupted"])


class SettingsDefaultTests(unittest.TestCase):
    def test_setting_default_is_false(self) -> None:
        """auto_quarantine_corrupted est defaut False (preserve comportement)."""
        # v1.0.0-beta : Phase 15 a deplace les defaults litteraux dans la
        # table `_LITERAL_DEFAULTS` au lieu de `payload.setdefault(...)`.
        # On verifie directement le contrat via apply_settings_defaults().
        from cinesort.ui.api.settings_support import apply_settings_defaults

        payload = apply_settings_defaults(
            {},
            state_dir=Path("/tmp"),
            default_root="/r",
            default_state_dir_example="/r/state",
            default_collection_folder_name="_Collection",
            default_empty_folders_folder_name="_Vide",
            default_residual_cleanup_folder_name="_residuels",
            default_probe_backend="mediainfo",
            debug_enabled=False,
        )
        # Le defaut doit etre False (preservation comportement)
        self.assertIn("auto_quarantine_corrupted", payload)
        self.assertEqual(payload["auto_quarantine_corrupted"], False)


if __name__ == "__main__":
    unittest.main()

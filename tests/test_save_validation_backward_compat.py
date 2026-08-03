"""Vague P / VP-D : Backward compat ABSOLUE de `save_validation`.

AC-2 ROADMAP_VAGUE_P : signature API `save_validation()` retourne
`{ok: bool}` sur appel legacy (helper transparent `to_legacy_ok_bool`).

Ce test verifie que :
  1. Un payload legacy (uniquement `ok: bool`) continue de fonctionner.
  2. Un payload mixed (avec `decision` tri-etat) ne casse pas la shape.
  3. Aucune exception lorsque le store decisions n'est pas dispo
     (best-effort sur le mirror SQL).
  4. La shape de retour est TOUJOURS `{ok: bool, path: str}` ou
     `{ok: False, message: str, ...}` (le shape err_response).
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, ".")


def _make_paths(tmp: Path):
    """Stub RunPaths minimal pour run_flow_support.save_validation."""
    paths = MagicMock()
    paths.validation_json = tmp / "validation.json"
    paths.run_dir = tmp
    return paths


def _make_run_state(tmp: Path, rows=None):
    """Stub RunState minimal pour run_flow_support.save_validation."""
    rs = MagicMock()
    rs.paths = _make_paths(tmp)
    rs.rows = rows or []
    rs.log = MagicMock()
    rs.store = MagicMock()
    rs.store.decisions = None  # Pas de store decisions -> branche best-effort
    return rs


def _make_api(rs):
    """Stub CineSortApi minimal pour run_flow_support.save_validation."""
    api = MagicMock()
    api._get_run = MagicMock(return_value=rs)
    api._load_rows_from_plan_jsonl = MagicMock(return_value=[])
    # Identity passthrough : normalize_decisions_for_rows renvoie le dict tel quel.
    api._normalize_decisions_for_rows = MagicMock(side_effect=lambda rows, d: d)
    api._is_valid_run_id = MagicMock(return_value=True)
    return api


class SaveValidationBackwardCompatTests(unittest.TestCase):
    """Tests de backward compat ABSOLUE — AC-2 VP-D."""

    def setUp(self) -> None:
        self.tmp_root = Path(tempfile.mkdtemp(prefix="cinesort_save_val_compat_"))
        # validation.json doit pouvoir etre cree par atomic_write_json.

    def _call_save(self, api, run_id, decisions):
        from cinesort.ui.api import run_flow_support

        return run_flow_support.save_validation(api, run_id, decisions)

    def test_legacy_ok_true_returns_ok_true(self):
        """Payload legacy { ok: True } -> reponse { ok: True, path: ... }."""
        rs = _make_run_state(self.tmp_root)
        api = _make_api(rs)
        decisions = {
            "row-1": {"ok": True, "title": "Matrix", "year": 1999, "edited": False},
        }
        res = self._call_save(api, "run-1", decisions)
        self.assertTrue(res.get("ok"), f"Reponse legacy doit etre {{ok:True}}: {res}")
        self.assertIn("path", res)
        # Le JSON ecrit doit contenir le row-1 avec ok=True
        written = json.loads(rs.paths.validation_json.read_text(encoding="utf-8"))
        self.assertIn("row-1", written)
        self.assertEqual(written["row-1"].get("ok"), True)

    def test_legacy_ok_false_returns_ok_true_response(self):
        """Payload legacy { ok: False } -> la persistance reussit (ok=True envelope).

        Important : `ok` dans le payload est la decision, `ok` dans la
        reponse est le succes I/O. Ils sont independants.
        """
        rs = _make_run_state(self.tmp_root)
        api = _make_api(rs)
        decisions = {
            "row-1": {"ok": False, "title": "Matrix", "year": 1999, "edited": False},
        }
        res = self._call_save(api, "run-1", decisions)
        self.assertTrue(res.get("ok"))

    def test_tri_etat_decision_does_not_break_legacy_shape(self):
        """Payload mixte (legacy + decision) -> shape de retour preservee."""
        rs = _make_run_state(self.tmp_root)
        api = _make_api(rs)
        decisions = {
            "row-1": {
                "ok": False,
                "decision": "deferred",  # nouveau VP-D
                "title": "Matrix",
                "year": 1999,
            },
        }
        res = self._call_save(api, "run-1", decisions)
        self.assertTrue(res.get("ok"))
        self.assertIn("path", res)
        # Shape ABSOLUMENT preservee : pas de nouvelles cles obligatoires
        self.assertIsInstance(res.get("ok"), bool)

    def test_invalid_payload_returns_error_shape(self):
        rs = _make_run_state(self.tmp_root)
        api = _make_api(rs)
        # decisions = "garbage" (pas un dict)
        res = self._call_save(api, "run-1", "garbage")
        self.assertFalse(res.get("ok"))
        # Shape err_response : { ok: False, message: str, category: str }
        self.assertIn("message", res)

    def test_decisions_repo_absent_does_not_break(self):
        """Si store.decisions n'existe pas, save_validation reussit quand meme.

        Le mirror tri-etat -> SQL est best-effort (non bloquant).
        """
        rs = _make_run_state(self.tmp_root)
        rs.store = MagicMock(spec=[])  # spec vide = pas d'attribut decisions
        api = _make_api(rs)
        decisions = {"row-1": {"ok": True}}
        res = self._call_save(api, "run-1", decisions)
        self.assertTrue(res.get("ok"))

    def test_mirror_sql_called_with_tri_etat(self):
        """Si store.decisions existe, le mirror SQL est appele."""
        rs = _make_run_state(self.tmp_root)
        # Repo decisions stub : on capture les appels.
        rs.store.decisions = MagicMock()
        rs.store.decisions.set_decision = MagicMock(return_value={"ok": True})

        api = _make_api(rs)
        decisions = {
            "row-1": {"ok": True, "decision": "accepted", "tmdb_id": 603},
            "row-2": {"ok": False, "decision": "deferred", "tmdb_id": 42},
            "row-3": {"ok": False, "decision": "rejected"},
        }
        res = self._call_save(api, "run-1", decisions)
        self.assertTrue(res.get("ok"))
        # 3 appels au mirror SQL
        self.assertEqual(rs.store.decisions.set_decision.call_count, 3)

        # Verifier que chaque appel utilise la bonne decision
        calls = rs.store.decisions.set_decision.call_args_list
        decisions_passed = [c.args[2] for c in calls]
        self.assertIn("accepted", decisions_passed)
        self.assertIn("deferred", decisions_passed)
        self.assertIn("rejected", decisions_passed)

    def test_mirror_sql_legacy_payload_uses_from_legacy_ok_bool(self):
        """Payload legacy SANS `decision` -> projete via from_legacy_ok_bool."""
        rs = _make_run_state(self.tmp_root)
        rs.store.decisions = MagicMock()
        rs.store.decisions.set_decision = MagicMock(return_value={"ok": True})

        api = _make_api(rs)
        decisions = {
            "row-1": {"ok": True},  # -> accepted
            "row-2": {"ok": False},  # -> rejected
        }
        res = self._call_save(api, "run-1", decisions)
        self.assertTrue(res.get("ok"))

        calls = rs.store.decisions.set_decision.call_args_list
        decisions_passed = sorted(c.args[2] for c in calls)
        self.assertEqual(decisions_passed, ["accepted", "rejected"])

    def test_mirror_sql_exception_does_not_break_response(self):
        """Si la repo decisions levee une exception, save_validation reussit.

        AC-2 : la shape `{ok: True, path: ...}` est ABSOLUMENT preservee
        — le mirror SQL est best-effort.
        """
        import sqlite3

        rs = _make_run_state(self.tmp_root)
        rs.store.decisions = MagicMock()
        rs.store.decisions.set_decision = MagicMock(side_effect=sqlite3.OperationalError("disk I/O error"))

        api = _make_api(rs)
        decisions = {"row-1": {"ok": True}}
        res = self._call_save(api, "run-1", decisions)
        # Shape preservee meme si le mirror echoue.
        self.assertTrue(res.get("ok"))

    def test_save_validation_signature_no_apply_atomic_kwarg(self):
        """AC-5 : `save_validation` ne consomme PAS apply_atomic.

        VP-A `apply_atomic` est sur `apply()`, jamais sur `save_validation()`.
        """
        import inspect

        from cinesort.ui.api import run_flow_support

        sig = inspect.signature(run_flow_support.save_validation)
        self.assertNotIn("apply_atomic", sig.parameters)


# ---------------------------------------------------------------------------
# Helper tests
# ---------------------------------------------------------------------------


class MirrorDecisionsHelperTests(unittest.TestCase):
    """Tests directs du helper `_mirror_decisions_to_sql`."""

    def test_mirror_skips_when_store_none(self):
        from cinesort.ui.api.run_flow_support import _mirror_decisions_to_sql

        # Ne doit pas lever d'exception.
        _mirror_decisions_to_sql(None, "run-1", {"row-1": {"ok": True}}, None)

    def test_mirror_skips_when_decisions_attr_missing(self):
        from cinesort.ui.api.run_flow_support import _mirror_decisions_to_sql

        store = MagicMock(spec=[])
        _mirror_decisions_to_sql(None, "run-1", {"row-1": {"ok": True}}, store)

    def test_mirror_skips_invalid_payloads(self):
        from cinesort.ui.api.run_flow_support import _mirror_decisions_to_sql

        store = MagicMock()
        store.decisions = MagicMock()
        store.decisions.set_decision = MagicMock(return_value={"ok": True})

        decisions = {
            "row-1": "not_a_dict",
            "": {"ok": True},  # empty row_id ignored
            "row-2": {"ok": True},  # OK
        }
        _mirror_decisions_to_sql(None, "run-1", decisions, store)
        # Seul row-2 doit avoir ete persiste.
        self.assertEqual(store.decisions.set_decision.call_count, 1)

    def test_mirror_uses_tmdb_id_for_film_id(self):
        from cinesort.ui.api.run_flow_support import _mirror_decisions_to_sql

        store = MagicMock()
        store.decisions = MagicMock()
        store.decisions.set_decision = MagicMock(return_value={"ok": True})

        decisions = {
            "row-1": {"ok": True, "tmdb_id": 603},
        }
        _mirror_decisions_to_sql(None, "run-1", decisions, store)
        call = store.decisions.set_decision.call_args
        # film_id = "tmdb:603"
        self.assertEqual(call.args[0], "tmdb:603")

    def test_mirror_falls_back_to_row_id(self):
        from cinesort.ui.api.run_flow_support import _mirror_decisions_to_sql

        store = MagicMock()
        store.decisions = MagicMock()
        store.decisions.set_decision = MagicMock(return_value={"ok": True})

        decisions = {
            "row-1": {"ok": True},  # pas de tmdb_id
        }
        _mirror_decisions_to_sql(None, "run-1", decisions, store)
        call = store.decisions.set_decision.call_args
        # film_id = "row:row-1"
        self.assertEqual(call.args[0], "row:row-1")


if __name__ == "__main__":
    unittest.main()

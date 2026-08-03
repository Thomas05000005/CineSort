"""REVUE ADVERSAIRE PR#852 — un apply non annulable ne peut pas etre muet.

Rendre `close_apply_batch` tolerante a `sqlite3.Error` (F11) evite qu'un apply
REUSSI remonte en HTTP 500 et, en mode atomique, qu'un rollback destructif se
declenche a tort. Mais cette tolerance a un cout : l'apply repond desormais
`{"ok": True}` alors que le batch est reste `PENDING`. Or
`get_last_reversible_apply_batch` filtre `status='DONE'` : l'undo de cet apply
est perdu. L'utilisateur ne l'apprenait qu'en cliquant « Annuler », sur un
message generique sans aucun lien avec l'apply qu'on venait de lui annoncer
comme reussi.

Un WARN dans le journal technique n'est ni une information utilisateur, ni une
donnee exploitable par l'UI. Sur le chemin destructif (regle 3 de CLAUDE.md),
perdre l'annulation de 500 films DOIT etre une donnee de la reponse. Ces tests
assertent sur le PAYLOAD, jamais sur le log.
"""

from __future__ import annotations

import sqlite3
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from cinesort.domain import core as core_mod
from cinesort.ui.api import apply_support


class _CloseStore:
    """Store minimal : `close_apply_batch` leve `exc` (ou reussit si None)."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self.apply = self
        self.statuses: List[str] = []
        self._exc = exc

    def close_apply_batch(self, *, batch_id: str, status: str, summary: Dict[str, Any]) -> None:
        self.statuses.append(status)
        if self._exc is not None:
            raise self._exc

    def backup_now(self, *, trigger: str) -> None:
        return None


class _BodyHarness:
    """Monte le strict necessaire pour executer `_apply_changes_body`."""

    def __init__(self, store: Any) -> None:
        self.logs: List[Tuple[str, str]] = []
        self.store = store
        self.api = SimpleNamespace(
            _get_run=lambda _run_id: None,
            _app_version="test",
            _notify=SimpleNamespace(notify=lambda *a, **k: None),
            _dispatch_plugin_hook=lambda *a, **k: None,
            _dispatch_email=lambda *a, **k: None,
            log_api_exception=lambda *a, **k: None,
        )

    def _log(self, level: str, message: str) -> None:
        self.logs.append((level, message))

    def ctx(self) -> Dict[str, Any]:
        return {
            "ok": True,
            "_ctx": (
                SimpleNamespace(),  # cfg
                SimpleNamespace(),  # run_paths
                [],  # rows
                self._log,
                self.store,
                {},  # safe_decisions
                set(),  # decision_presence
            ),
        }


def _run_body(store: Any, *, batch_id: Optional[str] = "batch-42") -> Dict[str, Any]:
    harness = _BodyHarness(store)

    def _fake_execute(*_a: Any, **kwargs: Any) -> Any:
        kwargs["batch_state"][0] = batch_id
        kwargs["batch_state"][1] = 500
        return core_mod.ApplyResult(applied_count=500, considered_rows=500), batch_id, 500

    with (
        mock.patch.object(apply_support, "_validate_apply", return_value=harness.ctx()),
        mock.patch.object(apply_support, "_snapshot_jellyfin_watched", return_value=None),
        mock.patch.object(apply_support, "_execute_apply", side_effect=_fake_execute),
        mock.patch.object(apply_support, "_summarize_apply", return_value=None),
        mock.patch.object(apply_support, "_trigger_jellyfin_refresh", return_value=None),
        mock.patch.object(apply_support, "_trigger_plex_refresh", return_value=None),
    ):
        return apply_support._apply_changes_body(
            harness.api,
            "run-1",
            {},
            False,  # dry_run
            False,  # quarantine_unapproved
            cleanup_scope_label=lambda value: str(value),
            cleanup_status_label=lambda *a, **k: "",
            cleanup_reason_label=lambda value: str(value),
            apply_atomic=False,
        )


class CleanupApplyReportsFinalizationTests(unittest.TestCase):
    """`_cleanup_apply` doit REMONTER l'echec de finalisation, pas seulement le loguer."""

    def _call(self, store: Any) -> Any:
        return apply_support._cleanup_apply(
            core_mod.ApplyResult(applied_count=500, considered_rows=500),
            "batch-42",
            500,
            store=store,
            log_fn=lambda _level, _message: None,
            run_id="run-1",
            dry_run=False,
            rows=[],
        )

    def test_lock_db_remonte_journal_finalized_false(self) -> None:
        out = self._call(_CloseStore(sqlite3.OperationalError("database is locked")))

        self.assertFalse(out[4], "l'echec de cloture DONE doit etre remonte au caller, pas juste logue")

    def test_transition_refusee_remonte_aussi_false(self) -> None:
        out = self._call(_CloseStore(RuntimeError("transition refusee vers 'DONE'")))

        self.assertFalse(out[4], "une transition refusee ne produit pas un batch DONE non plus")

    def test_chemin_nominal_remonte_true(self) -> None:
        out = self._call(_CloseStore())

        self.assertTrue(out[4])


class ApplyPayloadAnnouncesUndoLossTests(unittest.TestCase):
    """Le coeur de l'objection : la reponse doit DIRE que l'undo est perdu."""

    def test_lock_db_sur_la_cloture_annonce_undo_indisponible(self) -> None:
        """500 films ranges, DB verrouillee : ok=True MAIS l'undo est annonce mort."""
        out = _run_body(_CloseStore(sqlite3.OperationalError("database is locked")))

        self.assertTrue(out.get("ok"), "un apply disque reussi ne doit pas remonter en echec")
        self.assertIs(out.get("journal_finalized"), False)
        self.assertIs(out.get("undo_available"), False)
        warning = str(out.get("journal_warning") or "")
        self.assertTrue(warning.strip(), f"la perte d'undo doit etre une DONNEE de la reponse : {out}")
        self.assertNotEqual(
            warning,
            "errors.undo_unavailable_after_apply",
            "la cle i18n doit etre resolue (message manquant dans locales/)",
        )

    def test_apply_sans_journal_annonce_undo_indisponible(self) -> None:
        """`insert_apply_batch` en echec -> apply_batch_id None -> aucun undo possible."""
        out = _run_body(_CloseStore(), batch_id=None)

        self.assertTrue(out.get("ok"))
        self.assertIsNone(out.get("apply_batch_id"))
        self.assertIs(out.get("undo_available"), False)
        self.assertTrue(str(out.get("journal_warning") or "").strip())

    def test_chemin_nominal_annonce_undo_disponible(self) -> None:
        """NON-REGRESSION : sans incident, la reponse annonce l'undo comme disponible."""
        store = _CloseStore()

        out = _run_body(store)

        self.assertEqual(store.statuses, ["DONE"])
        self.assertIs(out.get("journal_finalized"), True)
        self.assertIs(out.get("undo_available"), True)
        self.assertNotIn(
            "journal_warning",
            out,
            "aucun avertissement ne doit polluer un apply nominal",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

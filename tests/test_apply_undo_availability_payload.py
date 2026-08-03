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


class _RecordingNotify:
    """Centre de notifications minimal : enregistre les evenements publies.

    `raise_on` fait lever la publication d'un event_type precis, pour verifier
    qu'un centre de notifications casse ne fait pas echouer un apply REUSSI.
    """

    def __init__(self, *, raise_on: Optional[str] = None) -> None:
        self.calls: List[Tuple[str, str, str, str]] = []
        self._raise_on = raise_on

    def notify(self, event_type: str, title: str, body: str, level: str = "info") -> None:
        self.calls.append((str(event_type), str(title), str(body), str(level)))
        if self._raise_on is not None and str(event_type) == self._raise_on:
            raise RuntimeError("centre de notifications indisponible")

    def errors(self) -> List[Tuple[str, str, str, str]]:
        return [call for call in self.calls if call[3] == "error"]


class _BodyHarness:
    """Monte le strict necessaire pour executer `_apply_changes_body`."""

    def __init__(self, store: Any, notify: Optional[_RecordingNotify] = None) -> None:
        self.logs: List[Tuple[str, str]] = []
        self.store = store
        self.notify = notify or _RecordingNotify()
        self.api = SimpleNamespace(
            _get_run=lambda _run_id: None,
            _app_version="test",
            _notify=self.notify,
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


def _run_body_with_harness(
    store: Any,
    *,
    batch_id: Optional[str] = "batch-42",
    ops: int = 500,
    applied_count: int = 500,
    notify: Optional[_RecordingNotify] = None,
) -> Tuple[Dict[str, Any], _BodyHarness]:
    """Execute `_apply_changes_body` et rend AUSSI le harness (notifications).

    `ops` = nombre d'operations journalisees (0 quand `insert_apply_batch` a
    echoue : `record_apply_op` sort avant d'incrementer le compteur).
    `applied_count` = ce que l'apply a REELLEMENT fait sur disque, independant
    du journal.
    """
    harness = _BodyHarness(store, notify=notify)

    def _fake_execute(*_a: Any, **kwargs: Any) -> Any:
        kwargs["batch_state"][0] = batch_id
        kwargs["batch_state"][1] = int(ops)
        return (
            core_mod.ApplyResult(applied_count=int(applied_count), considered_rows=500),
            batch_id,
            int(ops),
        )

    with (
        mock.patch.object(apply_support, "_validate_apply", return_value=harness.ctx()),
        mock.patch.object(apply_support, "_snapshot_jellyfin_watched", return_value=None),
        mock.patch.object(apply_support, "_execute_apply", side_effect=_fake_execute),
        mock.patch.object(apply_support, "_summarize_apply", return_value=None),
        mock.patch.object(apply_support, "_trigger_jellyfin_refresh", return_value=None),
        mock.patch.object(apply_support, "_trigger_plex_refresh", return_value=None),
    ):
        out = apply_support._apply_changes_body(
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
    return out, harness


def _run_body(store: Any, **kwargs: Any) -> Dict[str, Any]:
    return _run_body_with_harness(store, **kwargs)[0]


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
        """`insert_apply_batch` en echec -> apply_batch_id None -> aucun undo possible.

        Cas du 2026-08-02, reproduit fidelement : sans batch, `record_apply_op`
        sort AVANT d'incrementer son compteur, donc `op_index` reste a 0 alors
        que 500 films ont bel et bien bouge. L'alerte ne doit donc PAS dependre
        du seul compteur d'operations journalisees.
        """
        out = _run_body(_CloseStore(), batch_id=None, ops=0, applied_count=500)

        self.assertTrue(out.get("ok"))
        self.assertIsNone(out.get("apply_batch_id"))
        self.assertIs(out.get("undo_available"), False)
        self.assertTrue(str(out.get("journal_warning") or "").strip())

    def test_batch_clos_done_mais_vide_n_annonce_pas_un_undo_fantome(self) -> None:
        """Zero operation journalisee : `undo_available: True` serait un mensonge."""
        out = _run_body(_CloseStore(), ops=0, applied_count=0)

        self.assertIs(out.get("journal_finalized"), True)
        self.assertIs(out.get("undo_available"), False, "rien n'a ete journalise, il n'y a rien a annuler")

    def test_apply_qui_n_a_rien_touche_ne_declenche_pas_de_fausse_alerte(self) -> None:
        """Un apply sans aucun deplacement n'a rien perdu, meme si la DB lache."""
        out, harness = _run_body_with_harness(
            _CloseStore(sqlite3.OperationalError("database is locked")),
            ops=0,
            applied_count=0,
        )

        self.assertNotIn("journal_warning", out, "crier au loup ici userait l'alerte")
        self.assertEqual(harness.notify.errors(), [])

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


class UndoLossReachesTheUserTests(unittest.TestCase):
    """Un champ de payload que personne n'affiche resterait un silence.

    Le centre de notifications est le seul canal qui SURVIT a la fermeture de
    l'ecran d'apply — et son miroir est inconditionnel (`NotifyService.notify`
    appelle le hook du centre avant tout filtrage de toasts desktop).
    """

    def test_perte_d_undo_publiee_dans_le_centre_de_notifications(self) -> None:
        out, harness = _run_body_with_harness(_CloseStore(sqlite3.OperationalError("database is locked")))

        errors = harness.notify.errors()
        self.assertEqual(len(errors), 1, f"une notification d'erreur attendue, obtenu {harness.notify.calls}")
        _event, title, body, _level = errors[0]
        self.assertTrue(title.strip())
        self.assertNotIn("notifications.title_undo_unavailable", title, "cle i18n non resolue")
        self.assertEqual(body, out.get("journal_warning"))

    def test_apply_nominal_ne_publie_aucune_alerte(self) -> None:
        _out, harness = _run_body_with_harness(_CloseStore())

        self.assertEqual(harness.notify.errors(), [])

    def test_centre_de_notifications_casse_ne_fait_pas_echouer_l_apply(self) -> None:
        """Refaire echouer un apply disque REUSSI serait re-creer le defaut F11."""
        out, _harness = _run_body_with_harness(
            _CloseStore(sqlite3.OperationalError("database is locked")),
            notify=_RecordingNotify(raise_on="error"),
        )

        self.assertTrue(out.get("ok"), f"la notification est best-effort : {out}")
        self.assertIs(out.get("undo_available"), False)
        self.assertTrue(str(out.get("journal_warning") or "").strip())


if __name__ == "__main__":
    unittest.main(verbosity=2)

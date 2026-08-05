"""F11 (suite) — `close_apply_batch` doit tolerer une erreur SQLite.

Finding : les deux tuples d'except autour de `close_apply_batch`
(`_cleanup_apply` et le handler d'erreur de `_apply_changes_body`) ne listaient
pas `sqlite3.Error`, qui n'herite PAS de `OSError`. Or ces appels ont lieu APRES
que tous les deplacements ont ete faits sur disque : c'est exactement le cas ou
l'invariant « un echec de journal n'empeche jamais un move » s'applique.

Le serveur REST etant un `ThreadingHTTPServer` qui sert le dashboard EN
PARALLELE de l'apply (plus les threads de fond quarantine/retention/perceptual),
un `database is locked` y est atteignable — tout comme un disque plein ou un
lecteur reseau tombe, qui produisent eux aussi des `sqlite3.OperationalError`.

Consequences mesurees avant correctif :
- l'exception s'echappait de `_cleanup_apply`, un apply REUSSI remontait en
  HTTP 500 generique et le batch restait PENDING (la reconciliation au boot ne
  remet jamais un PENDING en DONE, donc l'undo restait mort) ;
- en mode atomique (opt-in), le handler d'erreur rejouait `rollback_forward`
  A L'ENVERS sur un apply integralement reussi.
"""

from __future__ import annotations

import sqlite3
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple
from unittest import mock

from cinesort.domain import core as core_mod
from cinesort.ui.api import apply_support


class _LockedCloseStore:
    """Store minimal dont `close_apply_batch` echoue toujours en SQLite."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self.apply = self
        self.statuses: List[str] = []
        self._exc = exc or sqlite3.OperationalError("database is locked")

    def close_apply_batch(self, *, batch_id: str, status: str, summary: Dict[str, Any]) -> None:
        self.statuses.append(status)
        raise self._exc

    def backup_now(self, *, trigger: str) -> None:
        return None


class CleanupApplySqliteToleranceTests(unittest.TestCase):
    """`_cleanup_apply` absorbe sqlite3.Error comme elle absorbe deja OSError."""

    def _call(self, store: Any) -> Tuple[Any, List[Tuple[str, str]]]:
        logs: List[Tuple[str, str]] = []
        out = apply_support._cleanup_apply(
            core_mod.ApplyResult(applied_count=500, considered_rows=500),
            "batch-42",
            500,
            store=store,
            log_fn=lambda level, message: logs.append((level, message)),
            run_id="run-1",
            dry_run=False,
            rows=[],
        )
        return out, logs

    def test_tolere_database_is_locked(self) -> None:
        store = _LockedCloseStore()

        out, logs = self._call(store)

        self.assertEqual(store.statuses, ["DONE"], "la finalisation DONE doit avoir ete tentee")
        self.assertIsNotNone(out, "_cleanup_apply ne doit rien laisser echapper : l'apply disque est termine")
        self.assertTrue(
            any(level == "WARN" and "Journal apply non finalise" in message for level, message in logs),
            f"l'echec doit rester visible dans le journal d'apply : {logs}",
        )

    def test_tolere_corruption_de_base(self) -> None:
        store = _LockedCloseStore(sqlite3.DatabaseError("database disk image is malformed"))

        _out, logs = self._call(store)

        self.assertTrue(any(level == "WARN" for level, _m in logs))

    def test_une_erreur_de_programmation_reste_fatale(self) -> None:
        """Garde anti-sur-correction : pas d'`except Exception` deguise."""
        store = _LockedCloseStore(KeyError("champ manquant"))

        with self.assertRaises(KeyError):
            self._call(store)

    def test_succes_nominal_inchange(self) -> None:
        """NON-REGRESSION : sans erreur DB, le batch est bien clos en DONE."""

        class _OkStore:
            def __init__(self) -> None:
                self.apply = self
                self.statuses: List[str] = []

            def close_apply_batch(self, *, batch_id: str, status: str, summary: Dict[str, Any]) -> None:
                self.statuses.append(status)

        store = _OkStore()
        out, logs = self._call(store)

        self.assertEqual(store.statuses, ["DONE"])
        self.assertIsNotNone(out)
        self.assertFalse(
            [message for level, message in logs if level == "WARN"],
            "aucun WARN ne doit apparaitre sur le chemin nominal",
        )


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


class AtomicRollbackScopeTests(unittest.TestCase):
    """Le rollback atomique ne doit defaire QUE des deplacements incomplets."""

    def _run_body(
        self,
        *,
        store: Any,
        execute_exc: Optional[BaseException] = None,
        summarize_exc: Optional[BaseException] = None,
        apply_atomic: bool = True,
    ) -> Tuple[Dict[str, Any], mock.Mock, List[Tuple[str, str]]]:
        harness = _BodyHarness(store)
        rollback = mock.Mock(
            return_value={"ok": True, "rollback_status": "ROLLED_BACK_BY_ATOMIC", "counts": {"reverted": 500}}
        )

        def _fake_execute(*_a: Any, **kwargs: Any) -> Any:
            # Le batch est cree AVANT le moindre deplacement : il existe donc
            # deja quand l'apply casse en cours de route.
            kwargs["batch_state"][0] = "batch-42"
            kwargs["batch_state"][1] = 500
            if execute_exc is not None:
                raise execute_exc
            return core_mod.ApplyResult(applied_count=500, considered_rows=500), "batch-42", 500

        def _fake_summarize(*_a: Any, **_k: Any) -> None:
            if summarize_exc is not None:
                raise summarize_exc

        with (
            mock.patch.object(apply_support, "_validate_apply", return_value=harness.ctx()),
            mock.patch.object(apply_support, "_snapshot_jellyfin_watched", return_value=None),
            mock.patch.object(apply_support, "_execute_apply", side_effect=_fake_execute),
            mock.patch.object(apply_support, "_summarize_apply", side_effect=_fake_summarize),
            mock.patch.object(apply_support, "_trigger_jellyfin_refresh", return_value=None),
            mock.patch.object(apply_support, "_trigger_plex_refresh", return_value=None),
            mock.patch.object(apply_support, "_atomic_rollback_forward", rollback),
        ):
            out = apply_support._apply_changes_body(
                harness.api,
                "run-1",
                {},
                False,
                False,
                cleanup_scope_label=lambda value: str(value),
                cleanup_status_label=lambda *a, **k: "",
                cleanup_reason_label=lambda value: str(value),
                apply_atomic=apply_atomic,
            )
        return out, rollback, harness.logs

    def test_lock_db_sur_la_finalisation_ne_casse_plus_un_apply_reussi(self) -> None:
        """Le coeur du finding : 500 films ranges, DB verrouillee -> apply OK."""
        store = _LockedCloseStore()

        out, rollback, logs = self._run_body(store=store)

        self.assertTrue(out.get("ok"), f"un apply reussi ne doit pas remonter en echec : {out}")
        self.assertEqual(out.get("apply_batch_id"), "batch-42")
        rollback.assert_not_called()
        self.assertTrue(
            any(level == "WARN" and "Journal apply non finalise" in message for level, message in logs),
            f"le lock doit rester trace : {logs}",
        )

    def test_echec_posterieur_aux_deplacements_ne_declenche_pas_le_rollback(self) -> None:
        """Un echec APRES `_execute_apply` ne justifie pas de defaire l'apply."""
        store = _LockedCloseStore()

        out, rollback, logs = self._run_body(store=store, summarize_exc=OSError("summary.txt: disque plein"))

        self.assertFalse(out.get("ok"))
        rollback.assert_not_called()
        self.assertNotIn("atomic_rollback", out, "aucun rollback ne doit etre annonce a l'UI")
        self.assertTrue(
            any(level == "WARN" and "rollback NON declenche" in message for level, message in logs),
            f"la decision de ne pas rollbacker doit etre expliquee : {logs}",
        )

    def test_echec_pendant_les_deplacements_declenche_toujours_le_rollback(self) -> None:
        """NON-REGRESSION : le mode atomique garde tout son role."""

        class _OkStore:
            def __init__(self) -> None:
                self.apply = self
                self.statuses: List[str] = []

            def close_apply_batch(self, *, batch_id: str, status: str, summary: Dict[str, Any]) -> None:
                self.statuses.append(status)

            def backup_now(self, *, trigger: str) -> None:
                return None

        store = _OkStore()

        def _explode(*_a: Any, **kwargs: Any) -> Any:
            kwargs["batch_state"][0] = "batch-42"
            kwargs["batch_state"][1] = 250
            raise OSError("disque plein au 250e film")

        harness = _BodyHarness(store)
        rollback = mock.Mock(
            return_value={"ok": True, "rollback_status": "ROLLED_BACK_BY_ATOMIC", "counts": {"reverted": 250}}
        )
        with (
            mock.patch.object(apply_support, "_validate_apply", return_value=harness.ctx()),
            mock.patch.object(apply_support, "_snapshot_jellyfin_watched", return_value=None),
            mock.patch.object(apply_support, "_execute_apply", side_effect=_explode),
            mock.patch.object(apply_support, "_atomic_rollback_forward", rollback),
        ):
            out = apply_support._apply_changes_body(
                harness.api,
                "run-1",
                {},
                False,
                False,
                cleanup_scope_label=lambda value: str(value),
                cleanup_status_label=lambda *a, **k: "",
                cleanup_reason_label=lambda value: str(value),
                apply_atomic=True,
            )

        self.assertFalse(out.get("ok"))
        rollback.assert_called_once()
        self.assertEqual(out.get("atomic_rollback", {}).get("rollback_status"), "ROLLED_BACK_BY_ATOMIC")
        self.assertIn("ROLLED_BACK_BY_ATOMIC", store.statuses)

    def test_lock_db_sur_la_cloture_failed_ne_masque_plus_l_erreur_initiale(self) -> None:
        """Tuple :2878 — le lock ne doit pas s'echapper DEPUIS le handler d'erreur."""
        store = _LockedCloseStore()

        out, _rollback, logs = self._run_body(
            store=store,
            execute_exc=OSError("disque plein au 250e film"),
        )

        self.assertFalse(out.get("ok"))
        self.assertTrue(
            any(level == "WARN" and "Journal apply FAILED non finalise" in message for level, message in logs),
            f"le lock sur la cloture FAILED doit etre logue, pas propage : {logs}",
        )
        self.assertTrue(
            any(level == "ERROR" and "Echec application" in message for level, message in logs),
            f"l'erreur initiale doit rester visible : {logs}",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

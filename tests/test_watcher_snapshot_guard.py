"""Watcher — le snapshot baseline n'est grave QUE si un scan a reellement demarre.

Audit 2026-06-01 (#487 / #488). `FolderWatcher.run()` gravait
`self._previous_snapshot = current` AVANT d'appeler `_trigger_scan()`, qui peut
sortir sans rien lancer (roots inaccessibles, `start_plan` en echec, exception).
Le changement detecte sur disque etait alors perdu DEFINITIVEMENT : au poll
suivant `_has_changed(B, B)` est faux, donc plus aucun scan ne sera declenche
pour lui. Le commentaire de `run()` decrit exactement ce risque pour le cas
« scan deja en cours » sans l'appliquer au cas « scan pas demarre ».

Pourquoi ce fichier plutot que l'ancien `tests/test_watcher.py` :
celui-ci a ete supprime de main car un `raise unittest.SkipTest` module-level,
conditionne a l'existence de `web/index.html` (frontend legacy retire en PR
#257), neutralisait ses 294 lignes. De plus, ses cas « lifecycle » demarraient
un vrai thread avec `interval_s=0.1` puis `time.sleep(0.3)` — or
`__init__` plafonne l'intervalle a `max(10.0, interval_s)`, donc AUCUN poll
n'avait lieu et l'assertion de non-mutation du snapshot passait a vide.

Ces tests pilotent donc `run()` en synchrone, sans thread ni sleep, via un stub
de `threading.Event` qui laisse passer exactement un poll, et chacun verifie
qu'un poll a bien eu lieu avant d'asserter quoi que ce soit.
"""

from __future__ import annotations

import logging
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, FrozenSet, Optional
from unittest import mock

from cinesort.app.watcher import FolderWatcher, _has_changed, _snapshot_all

WATCHER_LOGGER = "cinesort.watcher"


class _ScriptedStopEvent:
    """Stub de `threading.Event` qui laisse passer EXACTEMENT un poll.

    `run()` prend son snapshot initial, puis boucle sur
    `is_set()` -> `wait(timeout=self._interval_s)` -> `is_set()` -> poll.

    - 1er `wait()` : execute `on_first_wait` (la mutation du disque a observer)
      puis retourne False -> un tour de boucle complet a lieu.
    - 2e `wait()`  : arme le flag et retourne True -> `break`.

    Aucun sleep, aucun thread : le test est deterministe et ne depend pas de
    `_interval_s` (plafonne a 10 s, ce qui rend tout test base sur un vrai
    thread + `time.sleep` structurellement vacant).
    """

    def __init__(self, on_first_wait: Optional[Callable[[], None]] = None) -> None:
        self._flag = False
        self._waits = 0
        self._on_first_wait = on_first_wait

    def set(self) -> None:
        self._flag = True

    def is_set(self) -> bool:
        return self._flag

    def wait(self, timeout: Optional[float] = None) -> bool:
        self._waits += 1
        if self._waits == 1:
            if self._on_first_wait is not None:
                self._on_first_wait()
            return False
        self._flag = True
        return True

    @property
    def polls(self) -> int:
        """Nombre de tours de boucle reellement executes."""
        return max(0, self._waits - 1)


def _make_api(start_plan_result: Optional[Dict[str, Any]] = None) -> mock.MagicMock:
    """API mockee : aucun run en cours, `start_plan` renvoie ce qu'on lui dit."""
    api = mock.MagicMock()
    api._runs = {}
    api._runs_lock = threading.Lock()
    api.settings.get_settings.return_value = {"roots": []}
    api.run.start_plan.return_value = start_plan_result or {"ok": True, "run_id": "test"}
    return api


class WatcherSnapshotGuardTests(unittest.TestCase):
    """Le snapshot ne doit avancer que quand un scan a effectivement demarre."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory(prefix="cinesort_watch_guard_")
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        (self.root / "Film A").mkdir()

    # -- helpers ------------------------------------------------------------

    def _run_one_poll(self, watcher: FolderWatcher) -> Any:
        """Execute un unique poll de `run()`, en creant « Film B » entre-temps.

        Retourne le contexte `assertLogs` pour inspection. Verifie au passage
        que le poll a REELLEMENT eu lieu et a detecte le changement — sans quoi
        toute assertion de non-mutation du snapshot serait vacante.
        """
        event = _ScriptedStopEvent(on_first_wait=lambda: (self.root / "Film B").mkdir())
        watcher._stop_event = event  # type: ignore[assignment]
        with self.assertLogs(WATCHER_LOGGER, level="INFO") as captured:
            watcher.run()
        self.assertEqual(event.polls, 1, "le stub doit laisser passer exactement un poll")
        self.assertTrue(
            any("change detected" in r.getMessage() for r in captured.records),
            "le poll n'a pas detecte l'apparition de « Film B » : le test serait vacant",
        )
        return captured

    def _snapshot_names(self, snapshot: Dict[str, FrozenSet[str]]) -> set[str]:
        return {entry.rsplit("|", 1)[0] for entry in snapshot.get(str(self.root), frozenset())}

    def _assert_change_still_pending(self, watcher: FolderWatcher) -> None:
        """Le changement doit rester re-detectable au poll suivant."""
        changed, _detail = _has_changed(watcher._previous_snapshot, _snapshot_all([self.root]))
        self.assertTrue(
            changed,
            "Aucun scan n'a demarre : le snapshot baseline doit rester en arriere pour que "
            "le changement soit re-detecte au prochain poll.",
        )
        self.assertNotIn("Film B", self._snapshot_names(watcher._previous_snapshot))

    # -- #487 : le snapshot n'avance pas si aucun scan n'a demarre ----------

    def test_snapshot_not_burned_when_roots_inaccessible(self) -> None:
        """NAS debranche : `_trigger_scan` sort avant `start_plan`, rien n'est grave."""
        api = _make_api()
        watcher = FolderWatcher(api, roots=[self.root])

        with mock.patch("cinesort.app.watcher.is_dir_accessible", return_value=False):
            self._run_one_poll(watcher)

        api.run.start_plan.assert_not_called()
        self._assert_change_still_pending(watcher)

    def test_snapshot_not_burned_when_start_plan_refuses(self) -> None:
        """`start_plan` renvoie ok=False : aucun scan lance, rien n'est grave."""
        api = _make_api({"ok": False, "message": "un run est deja en cours"})
        watcher = FolderWatcher(api, roots=[self.root])

        with mock.patch("cinesort.app.watcher.is_dir_accessible", return_value=True):
            self._run_one_poll(watcher)

        api.run.start_plan.assert_called_once()
        self._assert_change_still_pending(watcher)

    def test_snapshot_burned_when_scan_actually_starts(self) -> None:
        """Controle positif : scan demarre => le snapshot avance bien.

        Sans ce test, un correctif qui ne graverait JAMAIS le snapshot passerait
        les deux tests precedents et relancerait un scan a chaque poll.
        """
        api = _make_api({"ok": True, "run_id": "r1"})
        watcher = FolderWatcher(api, roots=[self.root])

        with mock.patch("cinesort.app.watcher.is_dir_accessible", return_value=True):
            self._run_one_poll(watcher)

        api.run.start_plan.assert_called_once()
        self.assertIn("Film B", self._snapshot_names(watcher._previous_snapshot))
        changed, _detail = _has_changed(watcher._previous_snapshot, _snapshot_all([self.root]))
        self.assertFalse(changed, "Le scan a demarre : le snapshot doit etre a jour.")

    # -- #488 : une exception inattendue ne tue pas le thread daemon --------

    def test_unexpected_exception_does_not_escape_the_watch_loop(self) -> None:
        """`RuntimeError` depuis l'API : `run()` ne doit rien laisser echapper.

        `run()` est le corps du thread daemon `cinesort-watcher` : toute
        exception qui en sort tue la surveillance en silence jusqu'au prochain
        redemarrage. L'`except (KeyError, TypeError, ValueError)` d'origine ne
        couvrait ni `AttributeError`, ni `OSError`, ni le `RuntimeError` que
        JobRunner leve quand un run est deja en cours.
        """
        api = _make_api()
        api.settings.get_settings.side_effect = RuntimeError("un run est deja en cours")
        watcher = FolderWatcher(api, roots=[self.root])

        with mock.patch("cinesort.app.watcher.is_dir_accessible", return_value=True):
            captured = self._run_one_poll(watcher)

        errors = [r for r in captured.records if r.levelno >= logging.ERROR]
        self.assertTrue(errors, "L'echec doit etre journalise, jamais avale en silence.")
        self.assertTrue(
            any(r.exc_info is not None for r in errors),
            "Le traceback doit etre preserve (logger.exception), sinon la panne est indiagnosticable.",
        )
        self._assert_change_still_pending(watcher)


if __name__ == "__main__":
    unittest.main()

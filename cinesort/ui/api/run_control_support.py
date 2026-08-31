"""Run Control endpoints (V8-01 spec 08 Traitement §5).

4 endpoints permettant a l'UI de piloter le cycle de vie d'un run en cours :

- pause_run(run_id)        : suspend un run actif (signaling + DB PAUSED)
- resume_run(run_id)       : reprend un run suspendu (signaling + DB RUNNING)
- save_for_later(run_id)   : pause + flag SAVED pour le retrouver dans l'historique
- list_pending_runs()      : liste les runs PAUSED / SAVED / AWAITING_VALIDATION

Cf docs/internal/design/refonte_2026_05_17/screens/08-traitement.md §4 et §5.

Architecture :
- Le signaling thread-safe est gere par `JobRunner` (pause_event, request_pause,
  request_resume, is_paused) — le job_fn est cooperatif et inspecte le flag.
- La persistance d'etat est dans `RunRepository.mark_run_paused` /
  `mark_run_resumed` / `list_pending_runs`.
- Ce module est la couche d'orchestration (validation + binding facade).
"""

from __future__ import annotations

import logging
import sqlite3
from typing import Any, Dict, List

from cinesort.domain.run_models import RunStatus
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api._validators import requires_valid_run_id

logger = logging.getLogger(__name__)

# Etats DB autorises a transiter vers PAUSED / SAVED.
_PAUSABLE_DB_STATES = frozenset(
    {
        RunStatus.PENDING.value,
        RunStatus.RUNNING.value,
        RunStatus.AWAITING_VALIDATION.value,
    }
)

# Etats DB autorises a transiter vers RUNNING via resume.
# H13 fix (hotfix2) : alignement strict avec la clause SQL de
# `RunRepository.mark_run_resumed` (`WHERE status IN ('PAUSED', 'SAVED')`).
# AWAITING_VALIDATION exige une action utilisateur explicite (validation
# du diff) et ne doit PAS etre repris via cet endpoint generic — sinon
# l'UI annoncait OK puis la DB refusait la transition (incoherence).
_RESUMABLE_DB_STATES = frozenset(
    {
        RunStatus.PAUSED.value,
        RunStatus.SAVED.value,
    }
)


@requires_valid_run_id
def pause_run(api: Any, run_id: str) -> Dict[str, Any]:
    """Suspend un run en cours (signaling + persistance PAUSED).

    Comportement :
    1. Cherche le run en memoire (RunState actif) -> signale le JobRunner
       via `request_pause`. Si le run est en memoire mais deja termine,
       on rejette.
    2. Persiste l'etat PAUSED via `RunRepository.mark_run_paused`. La
       transition n'est autorisee que depuis un etat actif (PENDING /
       RUNNING / AWAITING_VALIDATION).
    3. Retourne `{ok, run_id, status: "PAUSED"}` ou un `_err_response`.
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague G : wrap global pour eviter HTTP 500
    # sur cet endpoint critique de pilotage du run.
    try:
        logger.debug("api: pause_run run_id=%s", run_id)
        return _pause_or_save(api, run_id, saved=False, status_label=RunStatus.PAUSED.value)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("pause_run failed for run_id=%s", run_id)
        return {
            "ok": False,
            "error": "pause_run_failed",
            "message": str(exc),
            "user_message": "Impossible de mettre le run en pause.",
        }


@requires_valid_run_id
def resume_run(api: Any, run_id: str) -> Dict[str, Any]:
    """Reprend un run PAUSED ou SAVED -> RUNNING.

    Symetrique de pause_run :
    1. Persiste RUNNING via `RunRepository.mark_run_resumed` (rejette si
       le run n'est pas dans un etat resumable).
    2. Signale le JobRunner via `request_resume` pour effacer le flag de pause.
    3. Retourne `{ok, run_id, status: "RUNNING"}` ou `_err_response`.
    """
    # MEME FRONTIERE QUE `pause_run`, et pour la meme raison. Le dispatcher REST
    # a bien un filet global, donc l'absence de ce wrap ne faisait pas tomber le
    # serveur : elle rendait un « Erreur interne » generique la ou `pause_run`
    # donne une phrase utile. Sur trois endpoints de pilotage du meme run,
    # l'asymetrie de message est un defaut a elle seule.
    try:
        return _reprendre_le_run(api, run_id)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("resume_run failed for run_id=%s", run_id)
        return {
            "ok": False,
            "error": "resume_run_failed",
            "message": str(exc),
            "user_message": "Impossible de reprendre le run.",
        }


def _reprendre_le_run(api: Any, run_id: str) -> Dict[str, Any]:
    """Corps de `resume_run`, extrait pour que la frontiere reste lisible.

    NOM DELIBERE. `_resume_run_impl` aurait forme une paire homonyme avec
    `CineSortApi._resume_run_impl` — le suffixe `_X_impl` est reserve aux
    methodes de la god-class, et `tests/test_contract_facades.py` refuse
    toute NOUVELLE paire. `pause_run` suit la meme regle en deleguant a
    `_pause_or_save`."""
    logger.debug("api: resume_run run_id=%s", run_id)

    found = _find_store(api, run_id)
    if not found:
        return _err_response(
            "Run introuvable.",
            category="resource",
            level="warning",
            log_module=__name__,
            run_id=run_id,
        )
    store, current_status = found

    if current_status not in _RESUMABLE_DB_STATES:
        return _err_response(
            f"Run dans un etat non resumable ({current_status}).",
            category="state",
            level="info",
            log_module=__name__,
            run_id=run_id,
            status=current_status,
        )

    ok = store.run.mark_run_resumed(run_id)
    if not ok:
        return _err_response(
            "Impossible de reprendre le run (transition refusee).",
            category="state",
            level="warning",
            log_module=__name__,
            run_id=run_id,
        )

    # Signale le JobRunner pour debloquer le worker si encore en memoire.
    rs = api._get_run(run_id)
    if rs is not None:
        try:
            rs.runner.request_resume(run_id)
        # except Exception : on a deja persiste l'etat, le signaling est best-effort
        except Exception as exc:
            logger.warning("resume_run: signaling failure run_id=%s err=%s", run_id, exc)

    return {"ok": True, "run_id": run_id, "status": RunStatus.RUNNING.value}


@requires_valid_run_id
def save_for_later(api: Any, run_id: str) -> Dict[str, Any]:
    """Sauvegarde l'etat du run pour le reprendre plus tard (status=SAVED).

    Identique a `pause_run` mais marque `SAVED` au lieu de `PAUSED` pour
    distinguer un "operateur fait une pause cafe" d'un "operateur reviendra
    plus tard, libere le slot actif".
    """
    try:
        logger.debug("api: save_for_later run_id=%s", run_id)
        return _pause_or_save(api, run_id, saved=True, status_label=RunStatus.SAVED.value)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("save_for_later failed for run_id=%s", run_id)
        return {
            "ok": False,
            "error": "save_for_later_failed",
            "message": str(exc),
            "user_message": "Impossible de sauvegarder le run pour plus tard.",
        }


def list_pending_runs(api: Any) -> Dict[str, Any]:
    """Liste les runs en PAUSED / SAVED / AWAITING_VALIDATION.

    Agrege sur tous les `state_dir` connus de l'API (i.e. tous les
    SQLiteStore deja instancies) plus le state_dir courant. Pas de
    deduplication necessaire : un run_id est unique par state_dir et
    n'apparait pas dans plusieurs stores.

    Format :
        {ok: True, runs: [{run_id, status, created_at, total_rows,
                            last_activity_at}, ...]}
    """
    logger.debug("api: list_pending_runs")
    try:
        runs: List[Dict[str, Any]] = []
        seen: set[str] = set()

        # Pass 1 : tous les stores deja crees pour des state_dir vus.
        with api._runs_lock:
            stores = [store for store, _runner in api._infra_by_state_dir.values()]
        for store in stores:
            try:
                for row in store.run.list_pending_runs():
                    rid = row.get("run_id")
                    if rid and rid not in seen:
                        seen.add(rid)
                        runs.append(row)
            # `sqlite3.Error` n'herite PAS d'`OSError` : sans lui, une base
            # verrouillee remontait en HTTP 500 au lieu d'etre absorbee par ce
            # best-effort. Le meme defaut vit TROIS fois dans cette fonction.
            except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                logger.warning("list_pending_runs: store failure err=%s", exc)
                continue

        # Pass 2 : fallback sur le state_dir par defaut (cas premier appel
        # avant qu'un run actif ait peuple _infra_by_state_dir).
        default_store, _runner = api._get_or_create_infra(api._state_dir)
        if default_store not in stores:
            try:
                for row in default_store.run.list_pending_runs():
                    rid = row.get("run_id")
                    if rid and rid not in seen:
                        seen.add(rid)
                        runs.append(row)
            except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
                logger.warning("list_pending_runs: default store failure err=%s", exc)

        # Tri stable sur last_activity_at (DESC) pour avoir les plus recents en haut.
        runs.sort(key=lambda r: float(r.get("last_activity_at") or 0.0), reverse=True)
        return {"ok": True, "runs": runs}
    except (KeyError, OSError, sqlite3.Error, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# ---------- internals ----------


def _find_store(api: Any, run_id: str) -> Any:
    """Helper : retourne (store, current_status) ou None si run inconnu."""
    found = api._find_run_row(run_id)
    if not found:
        return None
    row, store = found
    return store, str(row.get("status") or "")


def _pause_or_save(api: Any, run_id: str, *, saved: bool, status_label: str) -> Dict[str, Any]:
    """Implementation commune a `pause_run` et `save_for_later`."""
    found = _find_store(api, run_id)
    if not found:
        return _err_response(
            "Run introuvable.",
            category="resource",
            level="warning",
            log_module=__name__,
            run_id=run_id,
        )
    store, current_status = found

    if current_status not in _PAUSABLE_DB_STATES:
        return _err_response(
            f"Run dans un etat non suspendable ({current_status}).",
            category="state",
            level="info",
            log_module=__name__,
            run_id=run_id,
            status=current_status,
        )

    # BUG-012 fix : persister l'etat DB d'abord pour eviter une incoherence ou
    # le worker est bloque par pause_event tandis que la DB voit toujours RUNNING
    # (si la transition DB etait refusee apres signaling). Symetrique a resume_run.
    ok = store.run.mark_run_paused(run_id, saved=saved)
    if not ok:
        return _err_response(
            "Impossible de suspendre le run (transition refusee).",
            category="state",
            level="warning",
            log_module=__name__,
            run_id=run_id,
        )

    # Signaling JobRunner apres persistance reussie (best-effort) pour que le
    # worker s'arrete sur la prochaine iteration. Si le run n'est plus en memoire
    # (apres redemarrage app), pas de signaling — l'etat DB est suffisant.
    #
    # HOTFIX3 fix : transmettre le flag `saved` au runner pour qu'il aligne le
    # snapshot memoire sur le meme target status que la DB (SAVED si
    # save_for_later, sinon PAUSED). Le fix C3 hotfix2 forcait inconditionnellement
    # snapshot=PAUSED, ce qui creait une nouvelle desync snapshot=PAUSED /
    # DB=SAVED dans le flux save_for_later.
    rs = api._get_run(run_id)
    if rs is not None:
        try:
            rs.runner.request_pause(run_id, saved=saved)
        # except Exception : le signaling est best-effort, l'etat DB est deja persiste
        except Exception as exc:
            logger.warning("pause_run: signaling failure run_id=%s err=%s", run_id, exc)

    return {"ok": True, "run_id": run_id, "status": status_label}

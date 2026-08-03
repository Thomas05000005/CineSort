"""Cron de retention pour l'historique des runs (spec 09 §5).

Decision Thomas : les runs sont conserves 90 jours par defaut, configurable
dans Paramètres > Avancé > Rétention historique (slider 7-365 j, ou "Jamais").

Comportement :
- Au boot de l'app : un thread daemon execute `cleanup_old_runs(N)` une fois,
  puis re-execute toutes les 24h tant que l'app tourne.
- Suppression silencieuse (pas de notification UI).
- Toute erreur est loggee en warning, le thread continue (resiliance maximale).

Pour desactiver la retention auto, passer `retention_days=0` (ou un truthy
falsy depuis les settings). Le thread n'est pas demarre.

Architecture :
- Module dans `cinesort.app` (orchestration) pour respecter les contracts
  d'import-linter (pas d'import `ui` depuis `domain`/`infra`/`app`).
- Le seul couplage avec `ui` se fait via l'instance `api` (CineSortApi)
  passee en parametre — pattern deja utilise par `_check_updates_in_background`
  et `_purge_tmdb_cache_in_background` dans app.py.
"""

from __future__ import annotations

import contextlib
import logging
import sqlite3
import threading
from typing import Any, Optional

_log = logging.getLogger(__name__)

# 24h en secondes. Externalise pour faciliter les tests.
_INTERVAL_S = 24.0 * 3600.0

# Delai initial avant le premier passage du cron. On laisse l'app finir
# son boot (init store, REST server, splash, ...) avant d'attaquer une
# transaction SQL potentiellement lourde.
_INITIAL_DELAY_S = 60.0


def _run_cleanup_once(api: Any, retention_days: int) -> None:
    """Execute un cycle de cleanup en isolant les erreurs.

    Loggue un info sur succes (avec compteur) ou un warning sur echec.
    """
    try:
        result = api.run.cleanup_old_runs(retention_days)
    # R8-024 (F2-d) : +sqlite3.Error. Un verrou DB transitoire (« database is locked »,
    # une OperationalError = DatabaseError, PAS un OSError) echappait au tuple, sortait de
    # _run_cleanup_once vers _worker -> le thread cron MOURAIT (retention definitivement morte).
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        _log.warning("cleanup_old_runs cron: appel echoue retention=%dj err=%s", retention_days, exc)
        return
    if not isinstance(result, dict) or not result.get("ok"):
        _log.warning(
            "cleanup_old_runs cron: reponse inattendue retention=%dj resp=%s",
            retention_days,
            result,
        )
        return
    deleted = int(result.get("deleted_count") or 0)
    _log.info(
        "cleanup_old_runs: deleted %d runs older than %d days",
        deleted,
        retention_days,
    )


def start_retention_cron(
    api: Any,
    *,
    retention_days: int = 90,
    initial_delay_s: float = _INITIAL_DELAY_S,
    interval_s: float = _INTERVAL_S,
) -> Optional[threading.Thread]:
    """Demarre le cron retention (thread daemon).

    Args:
        api: Instance CineSortApi (expose `api.run.cleanup_old_runs`).
        retention_days: Conservation en jours. <= 0 desactive le cron.
        initial_delay_s: Attente avant le premier cycle (defaut 60s).
        interval_s: Periode entre 2 cycles (defaut 24h).

    Returns:
        Le `threading.Thread` demarre, ou None si le cron est desactive
        (retention_days <= 0 ou erreur d'init).

    Le thread est marque daemon : il ne bloque pas la fermeture de l'app.
    Il s'arrete via l'evenement `api._retention_stop` si pose, sinon il
    boucle indefiniment.
    """
    try:
        days = int(retention_days)
    except (TypeError, ValueError):
        days = 90
    if days <= 0:
        _log.info("retention cron desactive (retention_days=%d <= 0)", days)
        return None

    # Evenement de stop optionnel. Pose-le sur api._retention_stop si tu veux
    # un shutdown propre depuis les tests/app.
    stop_event = getattr(api, "_retention_stop", None)
    if not isinstance(stop_event, threading.Event):
        stop_event = threading.Event()
        # api est immuable (rare, ex. namedtuple) — on garde l'event
        # local. Le thread reste killable via daemon=True.
        with contextlib.suppress(AttributeError):
            api._retention_stop = stop_event

    def _worker() -> None:
        # 1er passage apres initial_delay_s (pour ne pas frapper le boot).
        if stop_event.wait(initial_delay_s):
            return
        _run_cleanup_once(api, days)
        # Cycles suivants toutes les interval_s, jusqu'a stop_event.set().
        while not stop_event.is_set():
            if stop_event.wait(interval_s):
                return
            _run_cleanup_once(api, days)

    thread = threading.Thread(
        target=_worker,
        name="cinesort-retention-cleanup",
        daemon=True,
    )
    thread.start()
    _log.info(
        "retention cron demarre (retention=%dj, initial_delay=%ds, interval=%ds)",
        days,
        int(initial_delay_s),
        int(interval_s),
    )
    return thread


def trigger_now(api: Any, retention_days: int = 90) -> None:
    """Helper synchrone pour les tests : execute un cycle immediat sans thread.

    A utiliser uniquement dans les tests. En prod, `start_retention_cron`
    fait tout.
    """
    _run_cleanup_once(api, int(retention_days))


__all__ = ["start_retention_cron", "trigger_now"]

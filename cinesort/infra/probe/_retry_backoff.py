"""Retry exponentiel pour les probes externes (ffprobe / mediainfo).

ITER13 (loop/correction-2026-06, mecanisme RETRY_BACKOFF) :

Probleme adresse
----------------
`cinesort/infra/probe/tooling.py::default_runner` execute `tracked_run` une
seule fois. Si un appel echoue de maniere transitoire :
- `subprocess.TimeoutExpired` (NAS lent, contention I/O, 4K HEVC sur SMB)
- `BrokenPipeError` (pipe ferme entre Popen et lecture stdout)
- `OSError` reseau (UNC injoignable, share momentanement indisponible)

... l'echec est propage tel quel jusqu'au backend (`ffprobe_backend.py`,
`mediainfo_backend.py`), qui en plus n'attrape PAS `TimeoutExpired`, et tout
remonte au REST handler. Verdict ITER13 section 2 : un seul timeout casse
l'endpoint `quality/get_quality_report` (35.5s, payload incomplet, score
fallback fabrique au nom de release -> "score invente").

Solution
--------
Helper `retry_with_backoff(fn, ...)` qui :
1. Execute `fn()`.
2. Sur echec considere transitoire (cf `_is_transient`), attend
   `base_delay_s * 2^attempt` (cape a `max_delay_s`), puis re-essaie.
3. Borne `max_retries` (defaut 3). Apres epuisement, re-leve la derniere
   exception telle quelle (le caller doit savoir que c'est l'echec final).
4. Log VISIBLE de chaque tentative (`retry attempt N/M`) — exigence ITER13.

Garanties / non-garanties
-------------------------
- Retry **uniquement** sur erreurs transientes : `subprocess.TimeoutExpired`,
  `BrokenPipeError`, `ConnectionError` (Python builtin), et `OSError` reseau
  (UNC, errno EHOSTUNREACH/ENETUNREACH/ETIMEDOUT/EAGAIN). Les erreurs
  applicatives (subprocess rc != 0, JSON invalide, fichier corrompu) NE
  sont PAS retentees — c'est au caller de decider.
- Pas de retry sur `KeyboardInterrupt` / `SystemExit` : ces signaux doivent
  remonter immediatement pour arret administre du processus.
- Configurable via env `CINESORT_PROBE_RETRY_MAX` (defaut 3, max 10).
- Defaults raisonnables : 1s, 2s, 4s, 8s plafond (4 tentatives au total).
- Identification DECOUPLEE du probe (acquis racine C iter4) : ce module
  ne touche QUE l'execution du subprocess. Aucun import vers domain/app.

Couche
------
`cinesort/infra/probe/_retry_backoff.py` : reste dans `infra/probe/`, ne
depend que de `logging`, `os`, `time` (stdlib) et `subprocess` (typing).
Respecte le contract import-linter `infra_bounded` (pas d'import app/ui).
"""

from __future__ import annotations

import errno
import logging
import os
import subprocess
import time
from typing import Callable, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Defaults raisonnables (memo iter13 : pas un couperet unique).
DEFAULT_MAX_RETRIES = 3
DEFAULT_BASE_DELAY_S = 1.0
DEFAULT_MAX_DELAY_S = 8.0

# Borne haute pour eviter qu'un settings malveillant ne bloque l'app
# indefiniment (3 * 8s = 24s deja non-trivial).
MAX_RETRIES_HARD_CAP = 10

# OSError errnos consideres "reseau transitoire" (UNC injoignable, share
# momentanement indisponible). Les autres errnos (ENOENT, EACCES, EISDIR)
# sont des erreurs deterministes : ne pas retry.
_NETWORK_TRANSIENT_ERRNOS = frozenset(
    {
        errno.EAGAIN,
        errno.ETIMEDOUT,
        errno.EHOSTUNREACH,
        errno.ENETUNREACH,
        errno.ENETDOWN,
        errno.ECONNRESET,
        errno.ECONNABORTED,
        errno.EPIPE,
    }
)


def _resolve_max_retries(requested: Optional[int]) -> int:
    """Resolve `max_retries` en respectant les bornes + l'env.

    Priorite : argument explicite > env `CINESORT_PROBE_RETRY_MAX` > defaut.
    Clamp [0, MAX_RETRIES_HARD_CAP]. 0 = pas de retry, juste un essai.
    """
    if requested is not None:
        try:
            val = int(requested)
        except (TypeError, ValueError):
            val = DEFAULT_MAX_RETRIES
    else:
        env_raw = os.environ.get("CINESORT_PROBE_RETRY_MAX", "")
        try:
            val = int(env_raw) if env_raw else DEFAULT_MAX_RETRIES
        except (TypeError, ValueError):
            val = DEFAULT_MAX_RETRIES
    return max(0, min(MAX_RETRIES_HARD_CAP, val))


def _is_transient(exc: BaseException) -> bool:
    """True si l'exception correspond a un echec transitoire retentable.

    Cf module docstring pour la justification du perimetre.
    """
    # Erreurs administrees du processus : ne pas retry, remonter immediatement.
    if isinstance(exc, (KeyboardInterrupt, SystemExit, GeneratorExit)):
        return False
    # Timeout subprocess (NAS lent, gros HEVC) -> transitoire.
    if isinstance(exc, subprocess.TimeoutExpired):
        return True
    # Pipe ferme (subprocess termine de maniere abrupte) -> transitoire.
    if isinstance(exc, BrokenPipeError):
        return True
    # ConnectionError Python builtin (couvre ConnectionResetError,
    # ConnectionAbortedError, ConnectionRefusedError).
    if isinstance(exc, ConnectionError):
        return True
    # OSError : seulement si errno reseau transitoire connu. WinError 121
    # (semaphore timeout = NAS down) n'est pas mappe a un errno POSIX, on
    # le detecte via winerror sur Windows.
    if isinstance(exc, OSError):
        if exc.errno in _NETWORK_TRANSIENT_ERRNOS:
            return True
        winerror = getattr(exc, "winerror", None)
        if winerror in {
            53,   # ERROR_BAD_NETPATH (chemin reseau introuvable)
            64,   # ERROR_NETNAME_DELETED (nom reseau supprime)
            67,   # ERROR_BAD_NET_NAME
            121,  # ERROR_SEM_TIMEOUT (semaphore timeout, NAS lent/down)
            1231, # ERROR_NETWORK_UNREACHABLE
        }:
            return True
    return False


def _compute_delay(attempt: int, base_delay_s: float, max_delay_s: float) -> float:
    """Backoff exponentiel cape : base * 2^attempt, plafond `max_delay_s`."""
    delay = base_delay_s * (2.0 ** max(0, int(attempt)))
    return float(min(max_delay_s, max(0.0, delay)))


def retry_with_backoff(
    fn: Callable[[], T],
    *,
    label: str = "probe",
    max_retries: Optional[int] = None,
    base_delay_s: float = DEFAULT_BASE_DELAY_S,
    max_delay_s: float = DEFAULT_MAX_DELAY_S,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> T:
    """Execute `fn()` avec retry exponentiel sur echec transitoire.

    Args:
        fn: callable sans argument, son retour est propage tel quel.
        label: prefixe pour les logs (ex: "ffprobe", "mediainfo").
        max_retries: nombre max de retries (en plus de l'essai initial).
            None -> resout via env `CINESORT_PROBE_RETRY_MAX` puis defaut 3.
            0 -> pas de retry, juste un essai (utile pour tests).
        base_delay_s: delai de base (1s par defaut).
        max_delay_s: plafond du delai (8s par defaut, cf memo iter13).
        sleep_fn: injection pour tests (defaut `time.sleep`).

    Returns:
        Resultat de `fn()` si reussi (eventuellement apres retry).

    Raises:
        Re-leve la derniere exception apres epuisement des retries.
        Re-leve immediatement KeyboardInterrupt / SystemExit / GeneratorExit
        et toute exception non transitoire (cf `_is_transient`).
    """
    max_retries_eff = _resolve_max_retries(max_retries)
    total_attempts = max_retries_eff + 1
    last_exc: Optional[BaseException] = None
    for attempt in range(total_attempts):
        try:
            return fn()
        except BaseException as exc:  # noqa: BLE001 - on filtre via _is_transient
            if not _is_transient(exc):
                # Erreur non transitoire ou signal administre : remonte immediat.
                raise
            last_exc = exc
            remaining = total_attempts - attempt - 1
            if remaining <= 0:
                logger.warning(
                    "%s retry epuise apres %d/%d tentatives (derniere err: %s)",
                    label,
                    attempt + 1,
                    total_attempts,
                    type(exc).__name__,
                )
                raise
            delay = _compute_delay(attempt, base_delay_s, max_delay_s)
            logger.info(
                "%s retry attempt %d/%d apres %s, backoff %.1fs",
                label,
                attempt + 2,  # le prochain essai (1-indexed)
                total_attempts,
                type(exc).__name__,
                delay,
            )
            sleep_fn(delay)
    # Defensif : on ne devrait jamais arriver ici (le for-else raise au dernier).
    if last_exc is not None:
        raise last_exc  # pragma: no cover
    raise RuntimeError(f"{label} retry boucle invariant casse")  # pragma: no cover

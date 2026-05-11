"""Parallelisme pour l'analyse perceptuelle (§1 v7.5.0).

Orchestration de taches I/O-bound (ffmpeg) via ThreadPoolExecutor stdlib.
Le GIL est libere pendant subprocess.run, donc ThreadPool est optimal ici
(pas besoin de multiprocessing qui est plus lourd).
"""

from __future__ import annotations

import logging
import os
import threading
from concurrent.futures import ThreadPoolExecutor, Future
from typing import Any, Callable, Optional, TypeVar

from .constants import (
    BATCH_PARALLELISM_AUTO_CAP,
    BATCH_PARALLELISM_MAX_WORKERS,
    PARALLELISM_AUTO_FACTOR,
    PARALLELISM_MAX_WORKERS_DEEP_COMPARE,
    PARALLELISM_MAX_WORKERS_SINGLE_FILM,
    PARALLELISM_MIN_CPU_CORES,
)

logger = logging.getLogger(__name__)

T = TypeVar("T")

_VALID_MODES = ("auto", "max", "safe", "serial")
_VALID_INTENTS = ("single_film", "deep_compare")


def resolve_max_workers(
    mode: str,
    intent: str,
    cpu_count: Optional[int] = None,
) -> int:
    """Resout le nombre de workers selon mode et intent.

    Args:
        mode: "auto" | "max" | "safe" | "serial". Invalide -> fallback "auto".
        intent: "single_film" (2 workers max) | "deep_compare" (4 max).
        cpu_count: None = os.cpu_count(). Injection pour tests.

    Returns:
        Entier >= 1. Jamais 0.
    """
    normalized = (mode or "").strip().lower()
    if normalized not in _VALID_MODES:
        logger.warning("resolve_max_workers: mode invalide '%s', fallback 'auto'", mode)
        normalized = "auto"

    if intent not in _VALID_INTENTS:
        logger.warning("resolve_max_workers: intent invalide '%s', fallback 'single_film'", intent)
        intent = "single_film"

    cap = PARALLELISM_MAX_WORKERS_SINGLE_FILM if intent == "single_film" else PARALLELISM_MAX_WORKERS_DEEP_COMPARE

    if normalized == "serial":
        return 1

    cpu = cpu_count if cpu_count is not None else os.cpu_count()
    if cpu is None or cpu < 1:
        cpu = 1

    if normalized == "max":
        return cap

    if normalized == "safe":
        if cpu < PARALLELISM_MIN_CPU_CORES:
            return 1
        return min(2, cap)

    # auto
    if cpu < PARALLELISM_MIN_CPU_CORES:
        return 1
    auto = max(1, cpu // PARALLELISM_AUTO_FACTOR)
    return min(auto, cap)


def run_parallel_tasks(
    tasks: dict[str, Callable[[], T]],
    max_workers: int,
    timeout_per_task_s: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
) -> dict[str, tuple[bool, Any]]:
    """Execute N taches en parallele et retourne leurs resultats.

    Args:
        tasks: mapping {nom_tache: callable_zero_arg}.
        max_workers: taille du pool (>= 1).
        timeout_per_task_s: timeout par Future.result (None = pas de timeout).
        cancel_event: threading.Event pour annulation cooperative.

    Returns:
        Mapping {nom_tache: (succes, resultat_ou_exception)}.
        Taches annulees par cancel_event -> (False, CancelledError-like).
        Exceptions capturees et loggees, jamais propagees.
    """
    if not tasks:
        return {}

    workers = max(1, int(max_workers))
    results: dict[str, tuple[bool, Any]] = {}

    # Fast path: 1 worker ou 1 tache -> execution sequentielle (evite le pool)
    if workers <= 1 or len(tasks) == 1:
        for name, fn in tasks.items():
            if cancel_event is not None and cancel_event.is_set():
                results[name] = (False, _CancelledError("cancelled"))
                continue
            try:
                results[name] = (True, fn())
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                logger.warning("run_parallel_tasks: tache '%s' a echoue: %s", name, exc)
                results[name] = (False, exc)
        return results

    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="perceptual")
    futures: dict[str, Future] = {}
    try:
        for name, fn in tasks.items():
            futures[name] = executor.submit(fn)

        for name, fut in futures.items():
            if cancel_event is not None and cancel_event.is_set():
                fut.cancel()
                results[name] = (False, _CancelledError("cancelled"))
                continue
            try:
                value = fut.result(timeout=timeout_per_task_s)
                results[name] = (True, value)
            except TimeoutError as exc:
                logger.warning("run_parallel_tasks: tache '%s' timeout apres %ss", name, timeout_per_task_s)
                results[name] = (False, exc)
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                logger.warning("run_parallel_tasks: tache '%s' a echoue: %s", name, exc)
                results[name] = (False, exc)
    finally:
        cancel_futures = cancel_event is not None and cancel_event.is_set()
        executor.shutdown(wait=not cancel_futures, cancel_futures=cancel_futures)

    return results


class _CancelledError(RuntimeError):
    """Erreur interne indiquant une annulation cooperative."""


# ---------------------------------------------------------------------------
# V5-02 Polish Total v7.7.0 (R5-STRESS-5) — Parallelisme batch (inter-films)
# ---------------------------------------------------------------------------


def resolve_batch_workers(
    configured_workers: int,
    *,
    cpu_count: Optional[int] = None,
) -> int:
    """Resout le nombre de workers du batch perceptuel inter-films.

    Args:
        configured_workers: setting `perceptual_workers`.
            - 0 = auto = min(cpu_count(), BATCH_PARALLELISM_AUTO_CAP).
            - >= 1 = nombre force, clampe a [1, BATCH_PARALLELISM_MAX_WORKERS].
            - < 0 = invalide -> tombe sur auto.
        cpu_count: None = os.cpu_count() (injection pour tests).

    Returns:
        Entier >= 1 et <= BATCH_PARALLELISM_MAX_WORKERS. Jamais 0.
    """
    try:
        configured = int(configured_workers)
    except (TypeError, ValueError):
        configured = 0

    cpu = cpu_count if cpu_count is not None else os.cpu_count()
    if cpu is None or cpu < 1:
        cpu = 1

    if configured <= 0:
        # Auto : min(cpu, AUTO_CAP). Sur 4 cores -> 4, sur 16 cores -> 8.
        return max(1, min(cpu, BATCH_PARALLELISM_AUTO_CAP))

    return max(1, min(int(configured), BATCH_PARALLELISM_MAX_WORKERS))


def run_batch_parallel(
    items: list[Any],
    worker_fn: Callable[[Any], Any],
    *,
    max_workers: int,
    cancel_event: Optional[threading.Event] = None,
) -> list[tuple[bool, Any]]:
    """Execute `worker_fn(item)` pour chaque `item` en parallele, ordre preserve.

    Wrapper specialise pour le batch perceptuel : chaque element est un row_id
    (ou contexte equivalent) traite independamment. Le worker_fn est appele
    par-element, dans un ThreadPoolExecutor pour les taches subprocess-bound
    (ffmpeg libere le GIL pendant l'execution).

    Args:
        items: liste d'inputs (un par film).
        worker_fn: callable thread-safe qui accepte un item et retourne un
            resultat (ou leve une exception, capturee).
        max_workers: taille du pool. Si <= 1 ou len(items) <= 1, fast path
            sequentiel sans creer de pool.
        cancel_event: threading.Event pour annulation cooperative. Films non
            encore lances retournent (False, _CancelledError(...)).

    Returns:
        Liste de meme longueur que `items`, ordre preserve. Chaque element
        est `(succes: bool, resultat_ou_exception: Any)`.
    """
    if not items:
        return []

    workers = max(1, int(max_workers))
    n = len(items)
    results: list[tuple[bool, Any]] = [(False, None)] * n

    # Fast path : pas de pool si serial ou 1 seul film.
    if workers <= 1 or n <= 1:
        for i, item in enumerate(items):
            if cancel_event is not None and cancel_event.is_set():
                results[i] = (False, _CancelledError("cancelled"))
                continue
            try:
                results[i] = (True, worker_fn(item))
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                logger.warning("run_batch_parallel: item %d a echoue: %s", i, exc)
                results[i] = (False, exc)
        return results

    executor = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="perc-batch")
    futures: dict[Future, int] = {}
    try:
        for i, item in enumerate(items):
            if cancel_event is not None and cancel_event.is_set():
                results[i] = (False, _CancelledError("cancelled"))
                continue
            futures[executor.submit(worker_fn, item)] = i

        for fut, idx in futures.items():
            if cancel_event is not None and cancel_event.is_set():
                fut.cancel()
                results[idx] = (False, _CancelledError("cancelled"))
                continue
            try:
                results[idx] = (True, fut.result())
            except (OSError, ValueError, TypeError, KeyError, RuntimeError) as exc:
                logger.warning("run_batch_parallel: item %d a echoue: %s", idx, exc)
                results[idx] = (False, exc)
    finally:
        cancel_futures = cancel_event is not None and cancel_event.is_set()
        executor.shutdown(wait=not cancel_futures, cancel_futures=cancel_futures)

    return results

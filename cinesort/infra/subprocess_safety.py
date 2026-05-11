"""Securisation des subprocess (cleanup garanti + atexit) — finding R5-CRASH-2.

Probleme adresse
----------------
Avant ce module : si CineSort plantait au milieu d'une analyse perceptuelle
(exception non rattrapee dans le thread du JobRunner, KeyboardInterrupt, etc.),
les processus ffmpeg.exe lances via `subprocess.run(timeout=...)` pouvaient
rester zombies sur Windows (visibles dans Task Manager, consomment RAM/CPU).
`subprocess.run()` garantit le cleanup uniquement sur `TimeoutExpired`,
pas sur les autres exceptions levees pendant que le child tourne.

Solution
--------
1. `tracked_run()` : wrapper drop-in autour de `subprocess.run` qui :
   - cree un `Popen` enregistre dans un set global thread-safe ;
   - garantit `kill()` + `wait(timeout=1)` dans un `finally`, meme sur
     exception non rattrapee remontant du `communicate()` ;
   - desenregistre toujours le process avant le retour.
2. `tracked_popen()` : context manager equivalent pour les usages avances
   (Popen brut, streaming, pipe).
3. `_ACTIVE_PROCESSES` : registre global (set) protege par un lock.
4. `_cleanup_at_exit()` : enregistre via `atexit.register` au chargement
   du module — kill tout process encore vivant au shutdown gracieux.

Limitation OS
-------------
SIGKILL (kill -9 sur Linux) ou TerminateProcess externe sur Windows sont
NON gerables : le processus parent est tue immediatement par le noyau, sans
avoir la possibilite d'executer du code de cleanup. Les processus ffmpeg
enfants deviennent alors orphelins. Dans ce cas, l'OS finit generalement
par les recuperer (parent reassigne a init/wininit), mais cela peut prendre
quelques secondes a quelques minutes. Aucune solution n'existe en espace
utilisateur — il faudrait soit un job object Windows (CREATE_NEW_PROCESS_GROUP
+ AssignProcessToJobObject) soit un process supervisor externe.

Compatibilite
-------------
`tracked_run()` est un drop-in pour `subprocess.run()` : meme signature
(`args` + `**kwargs`), meme retour `CompletedProcess`, propage `TimeoutExpired`
identiquement. Les fonctions publiques de `ffmpeg_runner.py` conservent leur
signature exacte (aucune cassure pour les appelants).
"""

from __future__ import annotations

import atexit
import logging
import subprocess
import threading
from contextlib import contextmanager
from typing import Any, Iterator, Optional, Set

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------

# Delai max avant abandon du wait apres kill. 1s = compromis entre rapidite
# au shutdown (UI fige sinon) et delai pour OS de liberer les handles.
_KILL_WAIT_TIMEOUT_S: float = 1.0

# Delai max au cleanup atexit (par process). 0.5s = on ne bloque pas trop
# le shutdown si le child ne meurt pas immediatement.
_ATEXIT_WAIT_TIMEOUT_S: float = 0.5


# ---------------------------------------------------------------------------
# Registre global thread-safe
# ---------------------------------------------------------------------------

_ACTIVE_PROCESSES: Set[subprocess.Popen[Any]] = set()
_REGISTRY_LOCK = threading.Lock()


def _register(proc: subprocess.Popen[Any]) -> None:
    """Ajoute un process au registre global (thread-safe)."""
    with _REGISTRY_LOCK:
        _ACTIVE_PROCESSES.add(proc)


def _unregister(proc: subprocess.Popen[Any]) -> None:
    """Retire un process du registre global (thread-safe, no-op si absent)."""
    with _REGISTRY_LOCK:
        _ACTIVE_PROCESSES.discard(proc)


def active_process_count() -> int:
    """Nombre de processus actifs dans le registre (utile pour tests/debug)."""
    with _REGISTRY_LOCK:
        return len(_ACTIVE_PROCESSES)


def _kill_and_wait(proc: subprocess.Popen[Any], timeout_s: float) -> None:
    """Tue le process et attend timeout_s. Best-effort, log les erreurs."""
    if proc.poll() is not None:
        return  # deja termine
    try:
        proc.kill()
    except (OSError, ProcessLookupError) as exc:
        # Process deja mort entre poll() et kill() : OK.
        logger.debug("subprocess_safety: kill() ignored (%s)", exc)
        return
    try:
        proc.wait(timeout=timeout_s)
    except subprocess.TimeoutExpired:
        logger.warning(
            "subprocess_safety: process pid=%s n'a pas termine apres kill+wait(%.1fs)",
            getattr(proc, "pid", "?"),
            timeout_s,
        )
    except OSError as exc:
        logger.debug("subprocess_safety: wait() ignored (%s)", exc)


# ---------------------------------------------------------------------------
# Context manager Popen
# ---------------------------------------------------------------------------


@contextmanager
def tracked_popen(
    cmd: list[str],
    **kwargs: Any,
) -> Iterator[subprocess.Popen[Any]]:
    """Context manager autour de Popen avec cleanup garanti.

    Le process est enregistre dans le set global a l'entree, et garantit
    `kill()` + `wait(timeout=1)` a la sortie meme en cas d'exception.

    Reentrant : peut etre imbrique sans probleme (chaque process est trace
    independamment dans le set).

    Exemple::

        with tracked_popen([ffmpeg, "-i", "in.mp4", ...], stdout=PIPE) as p:
            stdout, stderr = p.communicate(timeout=30.0)
            rc = p.returncode

    Args:
        cmd: liste argv passee a Popen.
        **kwargs: tous les kwargs de subprocess.Popen (stdout, stderr,
            startupinfo, creationflags, env, cwd, etc.).

    Yields:
        L'objet Popen, deja enregistre dans le registre global.
    """
    proc = subprocess.Popen(cmd, **kwargs)
    _register(proc)
    try:
        yield proc
    finally:
        # Kill garanti meme si exception remontee depuis le with-block.
        # Si le process est deja termine normalement (returncode != None),
        # _kill_and_wait est un no-op.
        _kill_and_wait(proc, _KILL_WAIT_TIMEOUT_S)
        _unregister(proc)


# ---------------------------------------------------------------------------
# Drop-in pour subprocess.run
# ---------------------------------------------------------------------------


def tracked_run(
    cmd: list[str],
    *,
    timeout: Optional[float] = None,
    capture_output: bool = False,
    stdout: Any = None,
    stderr: Any = None,
    text: bool = False,
    encoding: Optional[str] = None,
    errors: Optional[str] = None,
    input: Optional[Any] = None,
    check: bool = False,
    **popen_kwargs: Any,
) -> subprocess.CompletedProcess[Any]:
    """Drop-in pour subprocess.run avec cleanup garanti.

    Replique fidelement la signature et le comportement de subprocess.run :
    propage TimeoutExpired identiquement (avec stdout/stderr partiel),
    retourne un CompletedProcess, supporte capture_output / text / encoding.

    Difference cle : meme si une exception non-TimeoutExpired remonte
    pendant `communicate()` (rare mais possible : MemoryError, KeyboardInterrupt,
    etc.), le child process est garanti d'etre tue + wait avant que
    l'exception ne se propage. C'est ce que `subprocess.run` ne fait pas
    en dehors du cas TimeoutExpired.

    Args:
        cmd: liste argv.
        timeout: timeout en secondes (None = pas de timeout).
        capture_output: shortcut pour stdout=PIPE, stderr=PIPE (parite run).
        stdout, stderr: redirections (PIPE, DEVNULL, fichier, ou None).
        text: decoder stdout/stderr en str.
        encoding, errors: parametres decodage si text=True.
        input: bytes/str a passer sur stdin.
        check: lever CalledProcessError si returncode != 0.
        **popen_kwargs: autres kwargs propages a Popen (startupinfo,
            creationflags, env, cwd, etc.).

    Returns:
        CompletedProcess avec returncode, stdout, stderr.

    Raises:
        subprocess.TimeoutExpired: si le timeout est depasse.
        subprocess.CalledProcessError: si check=True et returncode != 0.
        OSError: si le binaire est introuvable, etc.
    """
    # Parite avec subprocess.run : capture_output force PIPE.
    if capture_output:
        if stdout is not None or stderr is not None:
            raise ValueError("capture_output may not be used with stdout/stderr")
        stdout = subprocess.PIPE
        stderr = subprocess.PIPE

    # stdin doit etre PIPE si input fourni.
    stdin = popen_kwargs.pop("stdin", None)
    if input is not None:
        if stdin is not None:
            raise ValueError("stdin and input arguments may not both be used")
        stdin = subprocess.PIPE

    with tracked_popen(
        cmd,
        stdout=stdout,
        stderr=stderr,
        stdin=stdin,
        text=text,
        encoding=encoding,
        errors=errors,
        **popen_kwargs,
    ) as proc:
        try:
            stdout_data, stderr_data = proc.communicate(input=input, timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            # subprocess.run kill puis attend, et re-leve TimeoutExpired
            # avec stdout/stderr partiel attache. On reproduit ce contrat.
            proc.kill()
            try:
                stdout_data, stderr_data = proc.communicate()
            except (OSError, ValueError):
                stdout_data = stderr_data = None
            exc.stdout = stdout_data
            exc.stderr = stderr_data
            raise
        except BaseException:
            # KeyboardInterrupt, MemoryError, etc. : le finally du with
            # se charge du kill+wait. On laisse remonter.
            raise

    rc = proc.returncode
    completed = subprocess.CompletedProcess(cmd, rc, stdout_data, stderr_data)
    if check:
        completed.check_returncode()
    return completed


# ---------------------------------------------------------------------------
# Cleanup atexit
# ---------------------------------------------------------------------------


def _cleanup_at_exit() -> None:
    """Tue tous les processus encore actifs au shutdown gracieux.

    Appele automatiquement par atexit. Itere sur une copie du set pour
    eviter les modifications concurrentes (chaque kill peut declencher
    un unregister via tracked_popen).
    """
    with _REGISTRY_LOCK:
        snapshot = list(_ACTIVE_PROCESSES)
    if not snapshot:
        return
    logger.info(
        "subprocess_safety: cleanup atexit, %d process(es) actifs a tuer",
        len(snapshot),
    )
    for proc in snapshot:
        _kill_and_wait(proc, _ATEXIT_WAIT_TIMEOUT_S)
        _unregister(proc)


# Enregistrement automatique au chargement du module.
# Utile : meme si l'application n'instancie aucune classe, l'import du
# module suffit a brancher le cleanup.
atexit.register(_cleanup_at_exit)


__all__ = [
    "tracked_popen",
    "tracked_run",
    "active_process_count",
]

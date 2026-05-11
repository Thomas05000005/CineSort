"""M-1 audit QA 20260429 — operations FS avec timeout.

Probleme : `Path.exists()`, `Path.is_dir()`, `os.scandir()` font des syscalls
stat qui peuvent **hang indefiniment** quand un NAS SMB/CIFS ne repond plus
(host eteint, cable debranche, sleep). Le scan thread reste bloque sans
indication a l'utilisateur.

Solution : wrapper les operations FS critiques dans un thread daemon avec
timeout. Si le syscall ne repond pas en N secondes, on declare le chemin
inaccessible et on continue. Le thread leake (daemon, mourra avec le
process), mais le scan continue.

Pourquoi pas signal.alarm ? signal.SIGALRM n'existe pas sur Windows.
Pourquoi pas asyncio ? les syscalls bloquants ne sont pas annulables
proprement de toute facon. Le thread daemon est le pattern standard.
"""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any, Callable, Optional, Union

_logger = logging.getLogger(__name__)

# Timeout par defaut pour les checks FS — ajuste pour absorber les NAS
# legerement lents tout en detectant les hangs reels.
DEFAULT_FS_TIMEOUT_S = 10.0


def run_with_timeout(
    fn: Callable[[], Any],
    *,
    timeout_s: float = DEFAULT_FS_TIMEOUT_S,
    default: Any = None,
) -> Any:
    """Execute fn() dans un thread daemon avec timeout.

    Retourne le resultat de fn() si elle termine en moins de timeout_s,
    sinon retourne `default` (sans bloquer le caller). Le thread continue
    en arriere-plan si timeout, mais comme il est daemon il mourra avec
    le process.

    Tolere les exceptions dans fn() : retourne `default` + log warning.
    """
    result_box: list = [default]
    exc_box: list = [None]

    def _target() -> None:
        try:
            result_box[0] = fn()
        except Exception as exc:
            exc_box[0] = exc

    thread = threading.Thread(target=_target, daemon=True)
    thread.start()
    thread.join(timeout=max(0.1, float(timeout_s)))
    if thread.is_alive():
        # Timeout : on laisse le thread continuer (daemon)
        return default
    if exc_box[0] is not None:
        _logger.debug("run_with_timeout: exception ignoree: %s", exc_box[0])
        return default
    return result_box[0]


def is_path_accessible(
    path: Union[Path, str],
    *,
    timeout_s: float = DEFAULT_FS_TIMEOUT_S,
) -> bool:
    """Retourne True si le path existe ET le syscall stat repond en moins
    de timeout_s. False si timeout ou si Path.exists() retourne False.

    Sert a detecter les NAS debranches AVANT de lancer un scan complet
    qui ferait hang le thread.
    """
    p = Path(path)
    return bool(run_with_timeout(p.exists, timeout_s=timeout_s, default=False))


def is_dir_accessible(
    path: Union[Path, str],
    *,
    timeout_s: float = DEFAULT_FS_TIMEOUT_S,
) -> bool:
    """True si path existe ET est un dossier ET stat repond a temps."""
    p = Path(path)

    def _check() -> bool:
        return p.exists() and p.is_dir()

    return bool(run_with_timeout(_check, timeout_s=timeout_s, default=False))


def safe_path_exists(
    path: Union[Path, str],
    *,
    timeout_s: float = DEFAULT_FS_TIMEOUT_S,
) -> Optional[bool]:
    """Variante 3-etat : True (existe), False (n'existe pas), None (timeout).

    Permet au caller de differencier "absent" de "inaccessible/timeout"
    pour produire des messages d'erreur plus precis.
    """
    p = Path(path)
    sentinel = object()
    result = run_with_timeout(p.exists, timeout_s=timeout_s, default=sentinel)
    if result is sentinel:
        return None
    return bool(result)

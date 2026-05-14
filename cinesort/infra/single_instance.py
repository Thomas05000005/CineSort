"""Verrou inter-process pour empecher 2 instances CineSort sur le meme state_dir.

Cf issue #68 (audit-2026-05-12:e5f7) : sans verrou, 2 CineSort.exe lances en
parallele sur le meme LOCALAPPDATA peuvent ecrire dans la meme DB SQLite et
generer des moves contradictoires (meme fichier source -> 2 destinations).

Implementation pure stdlib (pas de dep externe) :
- Windows : msvcrt.locking(LK_NBLCK) sur un fichier .lock
- Unix : fcntl.lockf(LOCK_EX | LOCK_NB)

Le lock est automatiquement libere par l'OS quand le process meurt, meme sur
kill -9. Pas de stale lock possible si le process precedent a crashe.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

LOCK_FILENAME = ".cinesort.lock"

# Byte 0 est verrouille exclusivement (msvcrt.locking). On ecrit le PID au-dela
# pour que les autres processus puissent le lire sans toucher la zone locked.
_LOCK_BYTE_OFFSET = 0
_PID_WRITE_OFFSET = 16


class InstanceLock:
    """Lock file inter-process. Une seule instance par state_dir.

    Usage:
        lock = InstanceLock(state_dir)
        if not lock.acquire():
            sys.exit("Another CineSort instance is already running")
        try:
            ... main loop ...
        finally:
            lock.release()

    Ou comme context manager:
        with InstanceLock(state_dir) as lock:
            if not lock.acquired:
                sys.exit(...)
            ...
    """

    def __init__(self, state_dir: Path):
        self.state_dir = Path(state_dir)
        self.lock_path = self.state_dir / LOCK_FILENAME
        self._fd: Optional[int] = None
        self._acquired = False

    @property
    def acquired(self) -> bool:
        return self._acquired

    def acquire(self) -> bool:
        """Tente d'acquerir le lock. True si OK, False si une autre instance le detient.

        Sur le filesystem :
        - Cree (ou ouvre) le fichier .cinesort.lock dans state_dir
        - Tente un verrou exclusif non-bloquant sur le 1er byte
        - Sur succes : ecrit le PID pour diagnostics (visible par operateur)
        """
        if self._acquired:
            return True
        try:
            self.state_dir.mkdir(parents=True, exist_ok=True)
        except (OSError, PermissionError) as exc:
            logger.warning("InstanceLock: impossible de creer %s (%s)", self.state_dir, exc)
            return False

        try:
            # Cf CodeQL py/overly-permissive-file : 0o600 (owner read/write only)
            # suffit largement pour un lock file (lu uniquement par le meme user).
            self._fd = os.open(str(self.lock_path), os.O_RDWR | os.O_CREAT, 0o600)
        except (OSError, PermissionError) as exc:
            logger.warning("InstanceLock: impossible d'ouvrir %s (%s)", self.lock_path, exc)
            return False

        # Le fichier doit faire au moins _PID_WRITE_OFFSET+1 bytes pour qu'on
        # puisse locker byte 0 ET ecrire le PID a l'offset 16+ sans collision.
        # On ne touche au contenu QUE si le lock reussit (pas effacer le PID
        # d'un autre process avant d'echouer).
        if not self._try_lock():
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
            return False

        self._acquired = True
        try:
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.ftruncate(self._fd, 0)
            # Padding pour eloigner le PID de la zone locked (byte 0)
            padding = b"\x00" * _PID_WRITE_OFFSET
            pid_bytes = f"{os.getpid()}\n".encode("ascii")
            os.write(self._fd, padding + pid_bytes)
        except OSError as exc:
            logger.debug("InstanceLock: PID write failed (non-fatal): %s", exc)
        return True

    def _try_lock(self) -> bool:
        """Tente le verrou exclusif non-bloquant sur byte 0. OS-specifique."""
        if self._fd is None:
            return False
        if os.name == "nt":
            import msvcrt

            try:
                # msvcrt.locking lock 1 byte a la position courante. Sur un
                # file fraichement opened avec O_CREAT le contenu est vide,
                # donc on ftruncate a 1 byte mini pour creer le byte 0 lockable.
                os.lseek(self._fd, _LOCK_BYTE_OFFSET, os.SEEK_SET)
                with contextlib.suppress(OSError):
                    os.ftruncate(self._fd, max(1, os.fstat(self._fd).st_size))
                msvcrt.locking(self._fd, msvcrt.LK_NBLCK, 1)
                return True
            except OSError:
                return False
        else:
            import fcntl

            try:
                fcntl.lockf(self._fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                return True
            except OSError:
                return False

    def release(self) -> None:
        """Libere le lock. Idempotent."""
        if not self._acquired or self._fd is None:
            return
        try:
            if os.name == "nt":
                import msvcrt

                with contextlib.suppress(OSError):
                    os.lseek(self._fd, 0, os.SEEK_SET)
                    msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                with contextlib.suppress(OSError):
                    fcntl.lockf(self._fd, fcntl.LOCK_UN)
        finally:
            with contextlib.suppress(OSError):
                os.close(self._fd)
            self._fd = None
            self._acquired = False
            with contextlib.suppress(OSError):
                self.lock_path.unlink(missing_ok=True)

    def __enter__(self) -> "InstanceLock":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.release()

    def read_holder_pid(self) -> Optional[int]:
        """Lit le PID inscrit dans le fichier de lock (pour diagnostics).

        Retourne None si le fichier n'existe pas, est trop petit, ou contient
        des donnees invalides. Utile pour afficher "Une instance tourne deja
        (PID 12345)" a l'utilisateur.

        Implementation : ouvre un nouveau handle, seek a _PID_WRITE_OFFSET pour
        eviter la zone locked (byte 0). Sur Windows, lire byte 0 d'un fichier
        msvcrt.locking-locked echoue, mais lire >= byte 16 reussit.
        """
        try:
            with open(self.lock_path, "rb") as f:
                f.seek(_PID_WRITE_OFFSET)
                raw = f.read(32)
            content = raw.decode("ascii", errors="ignore").strip("\x00").strip()
            return int(content.splitlines()[0])
        except (OSError, ValueError, IndexError):
            return None

"""Mode planifie / Watch folder — surveillance des roots et scan automatique.

Thread daemon qui poll les dossiers racine toutes les N minutes.
Quand un changement est detecte (nouveau dossier, dossier supprime, mtime modifie),
un scan est declenche automatiquement via start_plan().
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

logger = logging.getLogger("cinesort.watcher")


def _snapshot_root(root: Path) -> FrozenSet[str]:
    """Snapshot leger d'un root : liste des dossiers de niveau 1 avec mtime.

    Ignore les dossiers commencant par '_' (buckets internes CineSort).
    Retourne un frozenset de 'nom|mtime_ns'.
    """
    entries: set[str] = set()
    try:
        with os.scandir(root) as scanner:
            for entry in scanner:
                if not entry.is_dir(follow_symlinks=False):
                    continue
                if entry.name.startswith("_"):
                    continue
                try:
                    stat = entry.stat()
                    entries.add(f"{entry.name}|{int(stat.st_mtime_ns)}")
                except (OSError, PermissionError):
                    entries.add(f"{entry.name}|0")
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return frozenset(entries)


def _snapshot_all(roots: List[Path]) -> Dict[str, FrozenSet[str]]:
    """Snapshot de tous les roots."""
    return {str(r): _snapshot_root(r) for r in roots}


def _has_changed(
    old: Dict[str, FrozenSet[str]],
    new: Dict[str, FrozenSet[str]],
) -> Tuple[bool, str]:
    """Compare deux snapshots. Retourne (changed, detail_message)."""
    if old == new:
        return False, ""
    details: list[str] = []
    all_roots = set(old) | set(new)
    for root in sorted(all_roots):
        old_set = old.get(root, frozenset())
        new_set = new.get(root, frozenset())
        if old_set != new_set:
            old_names = {e.rsplit("|", 1)[0] for e in old_set}
            new_names = {e.rsplit("|", 1)[0] for e in new_set}
            added = new_names - old_names
            removed = old_names - new_names
            modified = len(new_set - old_set) - len(added)
            parts: list[str] = []
            if added:
                parts.append(f"+{len(added)}")
            if removed:
                parts.append(f"-{len(removed)}")
            if modified > 0:
                parts.append(f"~{modified}")
            details.append(f"{root} ({', '.join(parts) or 'change'})")
    return True, "; ".join(details)


class FolderWatcher(threading.Thread):
    """Thread daemon de surveillance des dossiers racine."""

    def __init__(
        self,
        api: Any,
        *,
        interval_s: float = 300.0,
        roots: Optional[List[Path]] = None,
    ) -> None:
        super().__init__(name="cinesort-watcher", daemon=True)
        self._api = api
        self._interval_s = max(10.0, float(interval_s))
        self._roots = list(roots) if roots else []
        self._stop_event = threading.Event()
        self._previous_snapshot: Dict[str, FrozenSet[str]] = {}

    @property
    def is_active(self) -> bool:
        """True si le thread tourne et n'est pas en cours d'arret."""
        return self.is_alive() and not self._stop_event.is_set()

    def stop(self) -> None:
        """Demande l'arret propre du thread."""
        self._stop_event.set()
        self.join(timeout=5)
        logger.info("[watcher] stopped")

    def run(self) -> None:
        """Boucle principale : snapshot initial puis poll periodique."""
        logger.info(
            "[watcher] started, interval=%ds, roots=%s",
            int(self._interval_s),
            [str(r) for r in self._roots],
        )

        # Snapshot initial — pas de scan au premier poll
        self._previous_snapshot = _snapshot_all(self._roots)
        logger.debug("[watcher] initial snapshot: %d root(s)", len(self._previous_snapshot))

        while not self._stop_event.is_set():
            # Attendre l'intervalle (interruptible par stop)
            if self._stop_event.wait(timeout=self._interval_s):
                break  # stop() a ete appele

            if self._stop_event.is_set():
                break

            # Nouveau snapshot
            current = _snapshot_all(self._roots)
            changed, detail = _has_changed(self._previous_snapshot, current)

            if not changed:
                logger.debug("[watcher] poll: no change")
                continue

            logger.info("[watcher] change detected: %s", detail)
            self._previous_snapshot = current

            # Verifier qu'aucun scan n'est en cours
            if self._is_scan_running():
                logger.info("[watcher] scan skipped (already running)")
                continue

            # Declencher le scan
            self._trigger_scan(detail)

    def _is_scan_running(self) -> bool:
        """Verifie si un scan est deja en cours via l'API."""
        runs = getattr(self._api, "_runs", None)
        runs_lock = getattr(self._api, "_runs_lock", None)
        if not runs or not runs_lock:
            return False
        with runs_lock:
            for rs in runs.values():
                if getattr(rs, "running", False) and not getattr(rs, "done", False):
                    return True
        return False

    def _trigger_scan(self, detail: str) -> None:
        """Lance un scan automatique via start_plan.

        R5-CRIT-6 fix : valide que tous les roots sont accessibles AVANT de lancer
        le scan. Sinon, NAS deconnecte = snapshot vide = "100 dossiers disparus"
        detecte = scan auto declenche pour rien (faux positif).
        """
        # R5-CRIT-6 : pre-validation accessibility roots
        try:
            from cinesort.infra.fs_safety import is_dir_accessible

            inaccessible: List[str] = []
            for root in self._roots:
                try:
                    if not is_dir_accessible(root, timeout_s=5.0):
                        inaccessible.append(str(root))
                except (OSError, ValueError):
                    inaccessible.append(str(root))
            if inaccessible:
                logger.warning(
                    "[watcher] scan annule, %d root(s) inaccessible(s): %s",
                    len(inaccessible),
                    ", ".join(inaccessible[:3]),
                )
                return
        except ImportError:
            # fs_safety pas dispo, on continue (fallback comportement original)
            pass

        try:
            settings = self._api.get_settings()
            logger.info("[watcher] scan triggered")
            self._api._notify.notify(
                "scan_done",
                "Scan automatique",
                f"Changement detecte. Scan lance. ({detail})",
            )
            result = self._api.start_plan(settings)
            if result.get("ok"):
                logger.info("[watcher] scan started run_id=%s", result.get("run_id", "?"))
            else:
                logger.warning("[watcher] scan failed: %s", result.get("message", "?"))
        except (KeyError, TypeError, ValueError) as exc:
            logger.warning("[watcher] scan trigger error: %s", exc)

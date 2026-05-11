"""P2.3 : journal d'audit apply — traçabilité complète des décisions.

Pour un partage pro, l'utilisateur a besoin de pouvoir répondre à :
"Pourquoi ce fichier a été déplacé là ?" plusieurs jours/semaines après.

Complémentaire au journal SQLite (apply_operations) qui trace les moves
physiques mais sans contexte décisionnel. Le journal d'audit :

- Est persisté en JSONL (un JSON par ligne, append-only, parse facile).
- Vit dans le run_dir sous `apply_audit.jsonl`.
- Trace chaque décision avec row_id + type + raison + paths + metadata.
- Est thread-safe (écriture synchronisée par lock).

Événements tracés (champ `event`) :
    apply_start    : début du batch (batch_id, dry_run, nb_rows)
    row_decision   : chaque film — ok/reject/conflict/skip (décision UI)
    op_move_file   : MOVE_FILE exécuté (src, dst, reversible, sha1, size)
    op_move_dir    : MOVE_DIR (rename folder, src, dst)
    op_merge_dir   : dossier fusionné dans existant
    op_skip        : film skip (reason code)
    op_conflict    : conflit détecté + résolution (quarantine/duplicate)
    op_mkdir       : dossier cible créé
    apply_end      : fin du batch (counts finaux)

Usage minimaliste :
    auditor = ApplyAuditLogger.open_for_run(run_paths, batch_id="xyz")
    auditor.start(dry_run=False, total_rows=42)
    auditor.op_move_file(src=..., dst=..., row_id=..., sha1=..., size=...)
    auditor.skip(row_id=..., reason="duplicate", detail="...")
    auditor.end(counts={"moves": 40, "skipped": 2})
    auditor.close()
"""

from __future__ import annotations

import json
import logging
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional


_log = logging.getLogger(__name__)

AUDIT_FILENAME = "apply_audit.jsonl"


def audit_path_for_run(run_dir: Path) -> Path:
    """Retourne le chemin du fichier d'audit pour un run donné."""
    return Path(run_dir) / AUDIT_FILENAME


class ApplyAuditLogger:
    """Writer append-only JSONL. Thread-safe par lock.

    Les méthodes `_write_event` ne lèvent pas — un échec d'écriture est loggué
    mais ne fait pas planter l'apply (la BDD reste la source de vérité).
    """

    def __init__(self, path: Path, *, batch_id: str = "", run_id: str = "") -> None:
        self._path = Path(path)
        self._batch_id = str(batch_id)
        self._run_id = str(run_id)
        self._lock = threading.Lock()
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._fh = self._path.open("a", encoding="utf-8")
        except (OSError, PermissionError) as exc:
            _log.warning("apply_audit: impossible d'ouvrir %s : %s — audit désactivé", self._path, exc)
            self._fh = None

    @classmethod
    def open_for_run(cls, run_paths: Any, *, batch_id: str = "", run_id: str = "") -> "ApplyAuditLogger":
        """Construit un logger pour le run_dir extrait de `run_paths`."""
        run_dir = getattr(run_paths, "run_dir", None)
        if run_dir is None:
            run_dir = Path(".")
        return cls(
            audit_path_for_run(Path(run_dir)), batch_id=batch_id, run_id=run_id or getattr(run_paths, "run_id", "")
        )

    @property
    def path(self) -> Path:
        """Chemin absolu du fichier JSONL d'audit."""
        return self._path

    def _write_event(self, event: str, **data: Any) -> None:
        """Sérialise et écrit un événement JSON sur une ligne (no-op si fichier indisponible)."""
        if self._fh is None:
            return
        payload = {
            "ts": round(time.time(), 3),
            "run_id": self._run_id,
            "batch_id": self._batch_id,
            "event": str(event),
            **{k: v for k, v in data.items() if v is not None},
        }
        try:
            line = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
        except (TypeError, ValueError) as exc:
            _log.warning("apply_audit: payload non sérialisable pour event=%s : %s", event, exc)
            return
        with self._lock:
            try:
                self._fh.write(line + "\n")
                self._fh.flush()
            except (OSError, PermissionError) as exc:
                _log.warning("apply_audit: écriture échouée %s : %s", event, exc)

    # --- API publique ---

    def start(self, *, dry_run: bool, total_rows: int, quarantine_unapproved: bool = False) -> None:
        """Émet l'événement `apply_start` au début d'un batch d'apply."""
        self._write_event(
            "apply_start",
            dry_run=bool(dry_run),
            total_rows=int(total_rows),
            quarantine_unapproved=bool(quarantine_unapproved),
        )

    def end(self, *, counts: Optional[Dict[str, Any]] = None, status: str = "DONE") -> None:
        """Émet l'événement `apply_end` avec le statut final et les compteurs."""
        self._write_event("apply_end", status=str(status), counts=dict(counts or {}))

    def row_decision(
        self,
        *,
        row_id: str,
        ok: bool,
        title: Optional[str] = None,
        year: Optional[int] = None,
        reason: Optional[str] = None,
    ) -> None:
        """Trace la décision UI sur une ligne (acceptée ou rejetée + raison)."""
        self._write_event(
            "row_decision",
            row_id=str(row_id),
            ok=bool(ok),
            title=title,
            year=year,
            reason=reason,
        )

    def op_move_file(
        self,
        *,
        row_id: Optional[str] = None,
        src: str,
        dst: str,
        reversible: bool = True,
        sha1: Optional[str] = None,
        size: Optional[int] = None,
    ) -> None:
        """Trace une opération MOVE_FILE (src -> dst, sha1/size optionnels)."""
        self._write_event(
            "op_move_file",
            row_id=row_id,
            src=str(src),
            dst=str(dst),
            reversible=bool(reversible),
            sha1=sha1,
            size=size,
        )

    def op_move_dir(
        self,
        *,
        row_id: Optional[str] = None,
        src: str,
        dst: str,
        reversible: bool = True,
        sha1: Optional[str] = None,
        size: Optional[int] = None,
    ) -> None:
        """Trace une opération MOVE_DIR (rename de dossier collection ou racine)."""
        self._write_event(
            "op_move_dir",
            row_id=row_id,
            src=str(src),
            dst=str(dst),
            reversible=bool(reversible),
            sha1=sha1,
            size=size,
        )

    def op_mkdir(self, *, path: str) -> None:
        """Trace la création d'un dossier cible."""
        self._write_event("op_mkdir", path=str(path))

    def skip(
        self,
        *,
        row_id: Optional[str] = None,
        reason: str,
        detail: Optional[str] = None,
    ) -> None:
        """Trace un skip (raison + détail optionnel) sans déplacement."""
        self._write_event("op_skip", row_id=row_id, reason=str(reason), detail=detail)

    def conflict(
        self,
        *,
        row_id: Optional[str] = None,
        src: str,
        dst: str,
        conflict_type: str,
        resolution: str,
        resolved_path: Optional[str] = None,
    ) -> None:
        """Trace un conflit détecté + sa résolution (quarantine/duplicate/etc.)."""
        self._write_event(
            "op_conflict",
            row_id=row_id,
            src=str(src),
            dst=str(dst),
            conflict_type=str(conflict_type),
            resolution=str(resolution),
            resolved_path=resolved_path,
        )

    def error(self, *, context: str, message: str, row_id: Optional[str] = None) -> None:
        """Trace une erreur avec contexte (ex: phase, opération) + message."""
        self._write_event("error", row_id=row_id, context=str(context), message=str(message))

    def close(self) -> None:
        """Flush et ferme le fichier d'audit (idempotent, thread-safe)."""
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                    self._fh.close()
                except (OSError, ValueError):
                    pass
                self._fh = None

    def __enter__(self) -> "ApplyAuditLogger":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()


def read_apply_audit(
    run_dir: Path,
    *,
    batch_id: Optional[str] = None,
    limit: Optional[int] = None,
) -> list[Dict[str, Any]]:
    """Lit le journal d'audit JSONL et retourne une liste d'événements.

    Si `batch_id` est fourni, filtre sur ce batch. Ignore silencieusement les
    lignes JSON malformées.
    """
    path = audit_path_for_run(Path(run_dir))
    if not path.exists():
        return []
    out: list[Dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    event = json.loads(line)
                except (json.JSONDecodeError, ValueError):
                    continue
                if not isinstance(event, dict):
                    continue
                if batch_id and str(event.get("batch_id") or "") != str(batch_id):
                    continue
                out.append(event)
                if limit is not None and len(out) >= int(limit):
                    break
    except (OSError, PermissionError) as exc:
        _log.warning("apply_audit: lecture échouée %s : %s", path, exc)
    return out


__all__ = ["ApplyAuditLogger", "audit_path_for_run", "read_apply_audit", "AUDIT_FILENAME"]

"""Phase 4 spec 07 + spec 06 — Actions Library (mark_for_deletion, rescan, export).

Endpoints :
    mark_for_deletion(run_id, row_id)           — single (spec 06 Modal Film)
    mark_for_deletion_bulk(row_ids, run_id)     — bulk (spec 07 Bibliotheque)
    rescan_row(run_id, row_id)                  — single (spec 06)
    rescan_rows_bulk(row_ids, run_id)           — bulk (spec 07)
    export_films(row_ids, format, run_id)       — CSV / JSON

Persistance :
- Les marqueurs de suppression sont stockes dans un fichier
  `deletion_marks.json` dans le run_dir (cote du `validation.json`).
  Format : {"row_ids": ["abc", "def"], "marked_ts": {"abc": 1234567.0}}.
- Les exports sont ecrits dans `%LOCALAPPDATA%/CineSort/exports/`.
- Les rescans sont lances via JobRunner (job background).
"""

from __future__ import annotations

import csv
import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.infra import state
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.library_support import _build_library_rows, _resolve_run_id
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers persistance "deletion_marks.json"
# ---------------------------------------------------------------------------


def _deletion_marks_path(api: Any, run_id: str) -> Optional[Path]:
    """Resout le chemin du fichier deletion_marks.json pour ce run."""
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=True)
        return run_paths.run_dir / "deletion_marks.json"
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("_deletion_marks_path failed run_id=%s: %s", run_id, exc)
        return None


def _read_deletion_marks(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"row_ids": [], "marked_ts": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {"row_ids": [], "marked_ts": {}}
        row_ids = list(data.get("row_ids") or [])
        marked_ts = dict(data.get("marked_ts") or {})
        return {"row_ids": [str(r) for r in row_ids], "marked_ts": marked_ts}
    except (json.JSONDecodeError, OSError, TypeError, ValueError) as exc:
        logger.warning("_read_deletion_marks corrupted path=%s: %s", path, exc)
        return {"row_ids": [], "marked_ts": {}}


def _write_deletion_marks(path: Path, data: Dict[str, Any]) -> None:
    state.atomic_write_json(path, data)


def _persist_marks(api: Any, run_id: str, new_row_ids: List[str]) -> int:
    """Persiste les marqueurs. Retourne le nombre de rows nouvellement marques."""
    path = _deletion_marks_path(api, run_id)
    if path is None:
        raise RuntimeError("Impossible de resoudre le chemin de persistance.")
    current = _read_deletion_marks(path)
    existing = set(current["row_ids"])
    marked_ts: Dict[str, float] = current["marked_ts"]
    now = time.time()
    added = 0
    for rid in new_row_ids:
        rid_s = str(rid).strip()
        if not rid_s:
            continue
        if rid_s not in existing:
            existing.add(rid_s)
            added += 1
        marked_ts[rid_s] = now
    _write_deletion_marks(path, {"row_ids": sorted(existing), "marked_ts": marked_ts})
    return added


# ---------------------------------------------------------------------------
# Endpoint : mark_for_deletion (single + bulk)
# ---------------------------------------------------------------------------


def mark_for_deletion(
    api: Any,
    row_id: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Marque un seul film pour deplacement vers `_user_marked_for_deletion/` au prochain apply.

    Args:
        row_id: identifiant du film a marquer
        run_id: run cible (None = dernier run actif)

    Returns:
        {ok: bool, row_id: str, run_id: str} ou {ok: False, error: ...}
    """
    rid = str(row_id or "").strip()
    if not rid:
        return _err_response("row_id requis.", category="validation", level="info", log_module=__name__)
    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)
    try:
        _persist_marks(api, resolved, [rid])
        return {"ok": True, "row_id": rid, "run_id": resolved}
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def mark_for_deletion_bulk(
    api: Any,
    row_ids: List[str],
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Version bulk de mark_for_deletion.

    Args:
        row_ids: liste des row_ids a marquer (peut etre vide)
        run_id: run cible (None = dernier run actif)

    Returns:
        {ok: bool, count: int, failed: list[str], run_id: str}
        - count : nombre de rows nouvellement ajoutees (deja marquees ne comptent pas)
        - failed : row_ids ignores (vides ou invalides)
    """
    if not isinstance(row_ids, list):
        return _err_response(
            "row_ids doit etre une liste.",
            category="validation",
            level="info",
            log_module=__name__,
        )
    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)

    valid: List[str] = []
    failed: List[str] = []
    for raw in row_ids:
        rid_s = str(raw or "").strip()
        if rid_s:
            valid.append(rid_s)
        else:
            failed.append(str(raw))

    try:
        count = _persist_marks(api, resolved, valid)
        return {
            "ok": True,
            "count": count,
            "failed": failed,
            "run_id": resolved,
            "total_requested": len(row_ids),
        }
    except (OSError, RuntimeError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# ---------------------------------------------------------------------------
# Endpoint : rescan_rows_bulk (lance JobRunner)
# ---------------------------------------------------------------------------


def _build_rescan_job_fn(api: Any, run_id: str, row_ids: List[str]):
    """Build un job_fn compatible JobRunner pour rescanner N rows.

    Le job se contente, pour l'instant, d'iterer sur les rows et de logger.
    L'implementation reelle (probe + analyse + match TMDb) sera branchee
    ulterieurement quand le pipeline de rescan single-row sera disponible.
    """

    def job_fn(should_cancel) -> Dict[str, Any]:
        processed = 0
        skipped = 0
        for rid in row_ids:
            if should_cancel():
                break
            try:
                # Stub : marquer "rescan_pending" dans les notes du run (best-effort).
                logger.info("rescan_rows_bulk: rescanning row_id=%s run_id=%s", rid, run_id)
                processed += 1
            except (OSError, AttributeError, TypeError, ValueError) as exc:
                logger.warning("rescan failed row_id=%s: %s", rid, exc)
                skipped += 1
        return {
            "ok": True,
            "rescan": {
                "run_id": run_id,
                "processed": processed,
                "skipped": skipped,
                "requested": len(row_ids),
            },
        }

    return job_fn


def rescan_rows_bulk(
    api: Any,
    row_ids: List[str],
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Lance un job background pour relancer probe + analyse + match TMDb sur N rows.

    Returns:
        {ok: bool, job_id: str, count: int, run_id: str}
    """
    if not isinstance(row_ids, list):
        return _err_response(
            "row_ids doit etre une liste.",
            category="validation",
            level="info",
            log_module=__name__,
        )
    valid = [str(r).strip() for r in row_ids if str(r or "").strip()]
    if not valid:
        return _err_response("Aucun row_id valide.", category="validation", level="info", log_module=__name__)

    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)

    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        _store, runner = api._get_or_create_infra(state_dir)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    if runner is None:
        return _err_response("JobRunner indisponible.", category="state", level="warning", log_module=__name__)

    job_fn = _build_rescan_job_fn(api, resolved, valid)
    try:
        job_id = runner.start_job(
            job_fn=job_fn,
            root=str(state_dir),  # placeholder : rescan ne touche pas a la racine du scan
            state_dir=str(state_dir),
            config={"rescan_run_id": resolved, "rescan_row_ids": valid},
        )
    except RuntimeError as exc:
        # Un autre run est en cours
        return _err_response(str(exc), category="state", level="info", log_module=__name__)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    return {
        "ok": True,
        "job_id": job_id,
        "count": len(valid),
        "run_id": resolved,
    }


def rescan_row(
    api: Any,
    row_id: str,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Version single-row de rescan (spec 06). Equivalent a rescan_rows_bulk avec 1 element."""
    rid = str(row_id or "").strip()
    if not rid:
        return _err_response("row_id requis.", category="validation", level="info", log_module=__name__)
    return rescan_rows_bulk(api, [rid], run_id=run_id)


# ---------------------------------------------------------------------------
# Endpoint : export_films (CSV / JSON)
# ---------------------------------------------------------------------------


_EXPORT_FIELDS = (
    "row_id",
    "title",
    "year",
    "score_v2",
    "tier_v2",
    "path",
    "size_bytes",
    "duration_min",
    "codec",
    "resolution",
    "audio_languages",
    "subtitle_languages",
    "warnings",
)


def _exports_dir() -> Path:
    """Repertoire des exports : `%LOCALAPPDATA%/CineSort/exports/`."""
    base = state.default_state_dir() / "exports"
    base.mkdir(parents=True, exist_ok=True)
    return base


def _row_to_export_dict(row: Dict[str, Any]) -> Dict[str, Any]:
    """Filtre une row Library aux champs d'export selon spec 07."""
    return {
        "row_id": row.get("row_id"),
        "title": row.get("title"),
        "year": row.get("year"),
        "score_v2": row.get("score_v2"),
        "tier": row.get("tier_v2"),
        "path": row.get("path"),
        "size_bytes": row.get("size_bytes"),
        "duration_min": row.get("duration_min"),
        "codec": row.get("codec"),
        "resolution": row.get("resolution"),
        "audio_langs": list(row.get("audio_languages") or []),
        "subs_langs": list(row.get("subtitle_languages") or []),
        "warnings": list(row.get("warnings") or []),
    }


def _serialize_for_csv(value: Any) -> str:
    if isinstance(value, list):
        return "|".join(str(v) for v in value)
    if value is None:
        return ""
    return str(value)


def export_films(
    api: Any,
    row_ids: List[str],
    fmt: str = "csv",
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Export CSV/JSON des films selectionnes (spec 07 - 07.4.4).

    Args:
        row_ids: row_ids a exporter. Si vide, exporte tous les films du run.
        fmt: "csv" | "json"
        run_id: run cible (None = dernier)

    Returns:
        - format csv : {ok, file_path, count, format}
        - format json : {ok, films: [...], count, format} (direct dans la reponse)
          ET {ok, file_path} aussi pour persistance permanente
    """
    fmt_norm = str(fmt or "csv").strip().lower()
    if fmt_norm not in ("csv", "json"):
        return _err_response(f"Format inconnu: {fmt}", category="validation", level="info", log_module=__name__)
    if not isinstance(row_ids, list):
        return _err_response(
            "row_ids doit etre une liste.",
            category="validation",
            level="info",
            log_module=__name__,
        )

    resolved = _resolve_run_id(api, run_id)
    if not resolved:
        return _err_response("Aucun run actif.", category="resource", level="info", log_module=__name__)

    try:
        all_rows = _build_library_rows(api, resolved)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    if row_ids:
        wanted = {str(r).strip() for r in row_ids if str(r or "").strip()}
        selected = [r for r in all_rows if str(r.get("row_id") or "") in wanted]
    else:
        selected = list(all_rows)

    export_rows = [_row_to_export_dict(r) for r in selected]
    count = len(export_rows)

    try:
        exports_dir = _exports_dir()
        ts = time.strftime("%Y%m%d_%H%M%S")
        fname = f"library_export_{resolved}_{ts}.{fmt_norm}"
        file_path = exports_dir / fname

        if fmt_norm == "csv":
            with open(file_path, "w", encoding="utf-8", newline="") as fp:
                writer = csv.writer(fp)
                writer.writerow(
                    [
                        "row_id",
                        "title",
                        "year",
                        "score_v2",
                        "tier",
                        "path",
                        "size_bytes",
                        "duration_min",
                        "codec",
                        "resolution",
                        "audio_langs",
                        "subs_langs",
                        "warnings",
                    ]
                )
                for row in export_rows:
                    writer.writerow(
                        [
                            _serialize_for_csv(row.get(k))
                            for k in [
                                "row_id",
                                "title",
                                "year",
                                "score_v2",
                                "tier",
                                "path",
                                "size_bytes",
                                "duration_min",
                                "codec",
                                "resolution",
                                "audio_langs",
                                "subs_langs",
                                "warnings",
                            ]
                        ]
                    )
            return {
                "ok": True,
                "file_path": str(file_path),
                "count": count,
                "format": "csv",
                "run_id": resolved,
            }

        # JSON : ecrire le fichier ET retourner les films dans la reponse
        state.atomic_write_json(
            file_path,
            {
                "run_id": resolved,
                "exported_ts": time.time(),
                "count": count,
                "films": export_rows,
            },
        )
        return {
            "ok": True,
            "file_path": str(file_path),
            "films": export_rows,
            "count": count,
            "format": "json",
            "run_id": resolved,
        }
    except (OSError, PermissionError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

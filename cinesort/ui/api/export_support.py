"""Export portable de la bibliotheque CineSort (RGPD Art. 20).

Cf issue #95 (audit-2026-05-12:t4u6) : data portability — l'utilisateur doit
pouvoir exporter ses donnees dans un format lisible par d'autres outils,
sans dependance a CineSort.

Format JSON v1.0 : voir docs/EXPORT_FORMAT.md.

Privacy : les secrets DPAPI (tmdb_api_key, jellyfin_api_key, plex_token,
radarr_api_key, smtp_password, rest_api_token, ntfy_topic_secret) sont
EXCLUS de l'export. Les `*_url` et autres infos non-sensibles sont
conservees.
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Cf issue #95 : ces cles ne doivent JAMAIS apparaitre dans l'export.
# Tout le reste des settings est inclus pour permettre une re-import.
_SECRET_KEYS = frozenset(
    {
        "tmdb_api_key",
        "jellyfin_api_key",
        "plex_token",
        "radarr_api_key",
        "smtp_password",
        "ntfy_topic_secret",
        "rest_api_token",
        "omdb_api_key",
        "osdb_api_key",
    }
)

EXPORT_FORMAT_VERSION = "1.0"


def _sanitize_settings(settings: Dict[str, Any]) -> Dict[str, Any]:
    """Retire les secrets DPAPI/API keys d'un dict de settings."""
    out: Dict[str, Any] = {}
    for key, value in settings.items():
        if key in _SECRET_KEYS:
            # On conserve l'existence du champ avec valeur sentinelle mais
            # pas le contenu — permet de savoir qu'il y avait une cle sans
            # la divulguer.
            out[key] = "***REDACTED***" if value else ""
        else:
            out[key] = value
    return out


def _load_plan_rows(plan_jsonl_path: Path) -> List[Dict[str, Any]]:
    """Charge plan.jsonl en list de dicts."""
    rows: List[Dict[str, Any]] = []
    if not plan_jsonl_path.is_file():
        return rows
    try:
        with open(plan_jsonl_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError as exc:
        logger.warning("export: lecture %s echouee (%s)", plan_jsonl_path, exc)
    return rows


def _load_decisions(validation_json_path: Path) -> Dict[str, Dict[str, Any]]:
    """Charge validation.json (decisions user) en dict {row_id: decision}."""
    if not validation_json_path.is_file():
        return {}
    try:
        data = json.loads(validation_json_path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("export: lecture %s echouee (%s)", validation_json_path, exc)
    return {}


def export_full_library(api: Any) -> Dict[str, Any]:
    """Export portable de la bibliotheque (RGPD Art. 20).

    Retourne un dict serialisable JSON contenant :
    - version : EXPORT_FORMAT_VERSION
    - exported_at : ISO 8601 UTC
    - app_version : version CineSort
    - settings : sanitises (secrets retires)
    - runs : liste des runs avec metadata
    - films : pour le dernier run DONE, films + decisions + scores qualite

    Le caller (UI) peut ensuite serialiser en JSON et offrir le download.
    """
    try:
        state_dir = Path(getattr(api, "_state_dir", "")) if getattr(api, "_state_dir", None) else None
        if state_dir is None or not state_dir.is_dir():
            return {"ok": False, "message": "state_dir indisponible."}

        # 1. Settings sanitises
        try:
            settings_resp = api.get_settings()
            raw_settings = settings_resp.get("data", settings_resp) if isinstance(settings_resp, dict) else {}
            settings = _sanitize_settings(raw_settings) if isinstance(raw_settings, dict) else {}
        except (AttributeError, KeyError, TypeError) as exc:
            logger.warning("export: get_settings echoue (%s)", exc)
            settings = {}

        # 2. Liste des runs
        runs: List[Dict[str, Any]] = []
        last_done_run_id: str = ""
        try:
            store, _runner = api._get_or_create_infra(state_dir)
            runs_summary = store.get_runs_summary(limit=100)
            for r in runs_summary:
                runs.append(
                    {
                        "run_id": str(r.get("run_id") or ""),
                        "status": str(r.get("status") or ""),
                        "start_ts": float(r.get("start_ts") or 0),
                        "duration_s": float(r.get("duration_s") or 0),
                        "total_rows": int(r.get("total_rows") or 0),
                    }
                )
                if not last_done_run_id and str(r.get("status") or "") == "DONE":
                    last_done_run_id = str(r.get("run_id") or "")
        except (AttributeError, OSError) as exc:
            logger.warning("export: list runs echoue (%s)", exc)
            store = None

        # 3. Films du dernier run DONE (pour le portable detail) avec scores
        films: List[Dict[str, Any]] = []
        if last_done_run_id and store is not None:
            run_dir = state_dir / "runs" / f"tri_films_{last_done_run_id}"
            if not run_dir.is_dir():
                run_dir = state_dir / "runs" / last_done_run_id
            plan_rows = _load_plan_rows(run_dir / "plan.jsonl")
            decisions = _load_decisions(run_dir / "validation.json")

            for row in plan_rows:
                row_id = str(row.get("row_id") or "")
                dec = decisions.get(row_id) or {}
                # Quality score (best-effort, peut etre absent)
                qr_score: int | None = None
                qr_tier: str = ""
                try:
                    qr = store.get_quality_report(run_id=last_done_run_id, row_id=row_id)
                    if qr:
                        qr_score = int(qr.get("score") or 0)
                        qr_tier = str(qr.get("tier") or "")
                except (AttributeError, KeyError, TypeError, ValueError):
                    pass
                films.append(
                    {
                        "row_id": row_id,
                        "title": str(row.get("proposed_title") or ""),
                        "year": int(row.get("proposed_year") or 0),
                        "folder": str(row.get("folder") or ""),
                        "video": str(row.get("video") or ""),
                        "kind": str(row.get("kind") or ""),
                        "confidence": int(row.get("confidence") or 0),
                        "confidence_label": str(row.get("confidence_label") or ""),
                        "tmdb_collection_name": row.get("tmdb_collection_name"),
                        "edition": row.get("edition"),
                        "decision": {
                            "ok": bool(dec.get("ok")) if "ok" in dec else None,
                            "title": str(dec.get("title") or "") if "title" in dec else None,
                            "year": int(dec.get("year") or 0) if "year" in dec else None,
                        }
                        if dec
                        else None,
                        "quality_score": qr_score,
                        "quality_tier": qr_tier or None,
                    }
                )

        return {
            "ok": True,
            "version": EXPORT_FORMAT_VERSION,
            "exported_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "app_version": _read_app_version(),
            "last_done_run_id": last_done_run_id or None,
            "settings": settings,
            "runs": runs,
            "films": films,
            "film_count": len(films),
        }
    except (AttributeError, OSError, TypeError) as exc:
        logger.error("export_full_library failed: %s", exc)
        return {"ok": False, "message": f"Export echoue : {exc}"}


def _read_app_version() -> str:
    """Lit le fichier VERSION du repo (best-effort)."""
    try:
        version_path = Path(__file__).resolve().parents[3] / "VERSION"
        if version_path.is_file():
            return version_path.read_text(encoding="utf-8").strip()
    except OSError:
        pass
    return ""

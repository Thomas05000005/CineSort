from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

import cinesort.infra.state as state


def dashboard_cache_path(run_paths: state.RunPaths) -> Path:
    return run_paths.run_dir / "dashboard_cache.json"


def path_cache_signature(path: Path) -> Dict[str, Any]:
    try:
        stat_result = path.stat()
    except OSError:
        return {"exists": False, "size": 0, "mtime_ns": 0}
    return {"exists": True, "size": int(stat_result.st_size), "mtime_ns": int(stat_result.st_mtime_ns)}


def _auto_approve_threshold_signature(api: Any) -> int:
    """Seuil d'auto-approbation (settings) — composant de signature (M7).

    Sans lui, "Cas a verifier"/"Conflits" (dashboard_support.py:306-327, calcules
    A PARTIR de auto_approve_threshold) restent figes dans le cache pendant que la
    carte "Auto-approuvables" et la liste "a examiner" sont recalculees LIVE quand
    l'utilisateur change le seuil dans Parametres -> la partition depasse le total.
    Meme defaut (85) que dashboard_support.py:307 et run_read_support.py:305, sinon
    un settings illisible reintroduit la divergence.
    """
    from cinesort.domain.conversions import to_int

    try:
        return to_int(api._get_settings_impl().get("auto_approve_threshold"), 85)
    except Exception:  # noqa: BLE001 - settings illisibles -> meme defaut que le KPI
        return 85


def _ignored_alerts_signature(store: Any) -> Dict[str, Any]:
    """Empreinte GLOBALE de la table ignored_alerts — composant de signature (M17).

    "Ignorer une alerte" fait un simple INSERT dans la table `ignored_alerts`
    (film_modal.insert_ignored_alert), disjointe des tables agregees par les stats
    quality/perceptual/anomaly. Sans cette empreinte, la signature ne bouge pas et
    le KPI "Cas a verifier"/"Conflits" (qui soustrait les alertes ignorees en live,
    dashboard_support.py:313-327) reste fige apres un ignore. La table n'a pas de
    colonne run_id : empreinte globale -> au pire on sur-invalide le cache d'autres
    runs (sans danger). Le compteur est monotone (INSERT OR IGNORE seul, aucun
    un-ignore) donc count+max_ts suffit a detecter tout changement.
    """
    try:
        with store._managed_conn() as conn:  # type: ignore[attr-defined]
            cur = conn.execute("SELECT COUNT(*), MAX(ignored_at) FROM ignored_alerts")
            row = cur.fetchone()
    except Exception:  # noqa: BLE001 - table absente / DB illisible -> best-effort
        return {"count": 0, "max_ts": 0.0}
    if not row:
        return {"count": 0, "max_ts": 0.0}
    return {"count": int(row[0] or 0), "max_ts": float(row[1] or 0.0)}


def _duplicate_decisions_signature(store: Any, run_id: str) -> Dict[str, Any]:
    """Empreinte des decisions doublons du run — composant de signature (M18).

    duplicates_groups est calcule depuis la table duplicate_decisions
    (dashboard_support.py:571-579, store.apply.list_duplicate_decisions) puis mis en
    cache. "Garder A"/"Auto-decider" font upsert_duplicate_decision qui n'ecrit que
    dans cette table -> sans cette empreinte la signature ne bouge pas et le compteur
    reste fige. `decided_ts` est reecrit a chaque upsert (changement d'avis), donc
    count+max_ts capte les ajouts et re-decisions ; le digest (group_key + gagnant +
    perdants) capte tout changement de gagnant/perdants meme a count/ts constants.
    Empreinte scopee au run (la table a une colonne run_id). Types JSON-purs (int,
    float, listes de str) pour survivre au round-trip json de load_dashboard_cache.
    """
    try:
        decisions = store.apply.list_duplicate_decisions(run_id=run_id) or []
    except Exception:  # noqa: BLE001 - table absente / DB illisible -> best-effort
        return {"count": 0, "max_ts": 0.0, "digest": []}
    max_ts = 0.0
    digest: list = []
    for decision in decisions:
        if not isinstance(decision, dict):
            continue
        ts = float(decision.get("decided_ts") or 0.0)
        if ts > max_ts:
            max_ts = ts
        losers = decision.get("loser_row_ids") or []
        digest.append(
            [
                str(decision.get("group_key") or ""),
                str(decision.get("winner_row_id") or ""),
                "|".join(sorted(str(x) for x in losers)),
            ]
        )
    digest.sort()
    return {"count": len(digest), "max_ts": max_ts, "digest": digest}


def dashboard_cache_signature(
    api: Any,
    *,
    run_row: Dict[str, Any],
    run_paths: state.RunPaths,
    store: Any,
) -> Dict[str, Any]:
    run_id = str(run_row.get("run_id") or run_paths.run_id or "")
    return {
        # "version": 1 -> 2 : AUDIT 2026-07-13 (M7/M17/M18) ajoute 3 composants ;
        # le bump jette les dashboard_cache.json deja figes sur les disques existants.
        "version": 2,
        "run_id": run_id,
        "status": str(run_row.get("status") or ""),
        "started_ts": float(run_row.get("started_ts") or run_row.get("created_ts") or 0.0),
        "ended_ts": float(run_row.get("ended_ts") or 0.0),
        "stats_json": str(run_row.get("stats_json") or ""),
        "plan_jsonl": api._path_cache_signature(run_paths.plan_jsonl),
        "quality_reports": store.quality.get_quality_report_stats(run_id=run_id),
        "perceptual_reports": store.perceptual.get_perceptual_report_stats(run_id=run_id),
        "anomalies": store.anomaly.get_anomaly_stats(run_id=run_id),
        # AUDIT 2026-07-13 (M7/M17/M18) : le payload cache (review_queue_count,
        # conflicts_count, duplicates_groups) depend d'etats HORS
        # plan.jsonl/quality/perceptual/anomaly. Sans ces 3 composants, la signature
        # SOUS-invalide et le cache sert des compteurs figes. Sur-invalider = sans
        # danger, sous-invalider = le bug.
        "auto_approve_threshold": _auto_approve_threshold_signature(api),  # M7
        "ignored_alerts": _ignored_alerts_signature(store),  # M17
        "duplicate_decisions": _duplicate_decisions_signature(store, run_id),  # M18
    }


def load_dashboard_cache(
    api: Any,
    *,
    run_row: Dict[str, Any],
    run_paths: state.RunPaths,
    store: Any,
) -> Optional[Dict[str, Any]]:
    cache_path = api._dashboard_cache_path(run_paths)
    if not cache_path.exists():
        return None
    expected_signature = api._dashboard_cache_signature(run_row=run_row, run_paths=run_paths, store=store)
    try:
        raw = json.loads(cache_path.read_text(encoding="utf-8"))
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("signature") != expected_signature:
        return None
    payload = raw.get("payload")
    return payload if isinstance(payload, dict) else None


def write_dashboard_cache(
    api: Any,
    *,
    run_row: Dict[str, Any],
    run_paths: state.RunPaths,
    store: Any,
    payload: Dict[str, Any],
) -> None:
    cache_payload = {
        "signature": api._dashboard_cache_signature(run_row=run_row, run_paths=run_paths, store=store),
        "payload": payload,
    }
    state.atomic_write_json(api._dashboard_cache_path(run_paths), cache_payload)

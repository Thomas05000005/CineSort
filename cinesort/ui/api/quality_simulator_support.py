"""Simulateur de preset qualite (G5).

Recharge les rapports qualite d'un run (ou toute la bibliotheque), applique
un preset cible en memoire via les subscores deja calcules, et retourne un
rapport avant/apres detaille pour la UI (sans persister).
"""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import threading
import time
from typing import Any, Dict, List, Optional

from cinesort.domain import (
    quality_profile_from_preset,
    validate_quality_profile,
)
from cinesort.ui.api._responses import err as _err_response

logger = logging.getLogger(__name__)

# Cache partage entre tous les threads du REST server (ThreadingHTTPServer).
# Sans lock, l'eviction FIFO `_SIM_CACHE.pop(next(iter(_SIM_CACHE)))`
# peut crasher si un autre thread mute le dict pendant l'iteration
# (RuntimeError: dictionary changed size during iteration), et un
# clear_cache concurrent peut faire perdre l'entree qu'on vient d'inserer.
_SIM_CACHE: Dict[str, Dict[str, Any]] = {}
_SIM_CACHE_LIMIT = 20
_SIM_CACHE_LOCK = threading.Lock()

_TIER_ORDER = {
    # Nouveaux tiers (v7.2.0-dev, migration 011)
    "Reject": 0,
    "Bronze": 1,
    "Silver": 2,
    "Gold": 3,
    "Platinum": 4,
    # Retro-compat lecture : anciens noms acceptes pour les rapports non migres
    "Faible": 1,
    "Mauvais": 0,
    "Moyen": 2,
    "Bon": 3,
    "Premium": 4,
}


def run_simulation(
    api: Any,
    run_id: str = "latest",
    preset_id: str = "equilibre",
    overrides: Optional[Dict[str, Any]] = None,
    scope: str = "run",
) -> Dict[str, Any]:
    """Simule l'application d'un preset qualite sans toucher a la DB.

    Retourne {ok, before, after, delta, top_winners, top_losers, ...}.
    """
    try:
        preset_id = str(preset_id or "equilibre").strip().lower()
        scope = str(scope or "run").strip().lower()

        # Cache hit ?
        cache_key = _cache_key(run_id, preset_id, overrides, scope)
        with _SIM_CACHE_LOCK:
            cached = _SIM_CACHE.get(cache_key)
        if cached is not None:
            logger.debug("simulate: cache hit %s/%s", scope, preset_id)
            return {**cached, "cache_hit": True}

        # Resolve target profile
        target = _resolve_target_profile(preset_id, overrides)
        if target is None:
            return _err_response("Preset inconnu.", category="resource", level="info", log_module=__name__)

        # Baseline profile (actuellement actif)
        baseline = _get_active_profile(api)

        # Charge les reports
        reports = _load_reports_for_scope(api, run_id, scope)
        if not reports:
            return _err_response(
                "Aucun rapport qualite disponible dans ce scope.", category="state", level="info", log_module=__name__
            )

        # Recompute en memoire
        t0 = time.time()
        results = _recompute_in_memory(reports, baseline, target)
        elapsed_ms = int((time.time() - t0) * 1000)

        # Agrege le rapport
        report = _build_delta_report(results, baseline, target, elapsed_ms, run_id, scope, preset_id)
        report["ok"] = True
        report["cache_hit"] = False

        # Cache FIFO (sous lock pour eviter RuntimeError sur iter
        # concurrent dans un autre thread REST).
        with _SIM_CACHE_LOCK:
            if len(_SIM_CACHE) >= _SIM_CACHE_LIMIT:
                _SIM_CACHE.pop(next(iter(_SIM_CACHE)))
            _SIM_CACHE[cache_key] = report

        return report
    except (KeyError, OSError, TypeError, ValueError) as exc:
        logger.exception("simulate_quality_preset failed")
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


def save_custom_preset(api: Any, name: str, profile_json: Dict[str, Any]) -> Dict[str, Any]:
    """Persiste un profil custom nomme (slug(name) comme profile_id)."""
    try:
        name = str(name or "").strip()
        if not name:
            return _err_response("Nom requis.", category="validation", level="info", log_module=__name__)
        ok, errs, normalized = validate_quality_profile(profile_json)
        if not ok:
            return _err_response(
                "Profil invalide.", category="validation", level="info", log_module=__name__, errors=errs
            )

        slug = _slugify(name)
        normalized = copy.deepcopy(normalized)
        normalized["id"] = f"custom_{slug}"
        normalized["label"] = name

        # Utilise l'API existante save_quality_profile (le store accepte tout id valide).
        saved = api._save_active_quality_profile(normalized)
        _invalidate_cache()
        return {"ok": True, "preset_id": normalized["id"], "label": name, **saved}
    except (OSError, TypeError, ValueError) as exc:
        logger.exception("save_custom_preset failed")
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# ---------- helpers ----------------------------------------------------------


def _cache_key(run_id: str, preset_id: str, overrides: Any, scope: str) -> str:
    payload = json.dumps(
        {"r": run_id, "p": preset_id, "o": overrides or {}, "s": scope},
        sort_keys=True,
        default=str,
    )
    # MD5 utilise comme cache key (non securite-sensible). usedforsecurity=False
    # informe les linters (bandit B324, CodeQL py/weak-cryptographic-hash).
    return hashlib.md5(payload.encode("utf-8"), usedforsecurity=False).hexdigest()


def _invalidate_cache() -> None:
    with _SIM_CACHE_LOCK:
        _SIM_CACHE.clear()


def _resolve_target_profile(preset_id: str, overrides: Optional[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """Charge un preset catalog + applique overrides (weights/tiers/toggles)."""
    base = quality_profile_from_preset(preset_id)
    if not isinstance(base, dict):
        return None
    merged = copy.deepcopy(base)
    if overrides:
        _deep_merge(merged, overrides)
    ok, _errs, normalized = validate_quality_profile(merged)
    if not ok:
        return None
    # Preserve label/id si absents dans le merged
    normalized["label"] = base.get("label") or normalized.get("label") or preset_id
    normalized["id"] = base.get("id") or normalized.get("id") or preset_id
    return normalized


def _deep_merge(target: Dict[str, Any], src: Dict[str, Any]) -> None:
    for k, v in (src or {}).items():
        if isinstance(v, dict) and isinstance(target.get(k), dict):
            _deep_merge(target[k], v)
        else:
            target[k] = v


def _get_active_profile(api: Any) -> Dict[str, Any]:
    try:
        payload = api._active_quality_profile_payload()
        prof = payload.get("profile_json") or {}
        if "label" not in prof:
            prof = copy.deepcopy(prof)
            prof["label"] = "Actuel"
        return prof
    except (AttributeError, KeyError, OSError, TypeError):
        return {
            "id": "default",
            "label": "Par defaut",
            "weights": {"video": 60, "audio": 30, "extras": 10},
            "tiers": {"premium": 85, "bon": 68, "moyen": 54},
        }


def _load_reports_for_scope(api: Any, run_id: str, scope: str) -> List[Dict[str, Any]]:
    """Retourne une liste de quality_reports (chaque dict contient metrics.subscores)."""
    store = getattr(api, "_store", None)
    if store is None:
        return []

    if scope == "library":
        # Agrege sur tous les runs recents, dedup par row_id (garde le plus recent).
        runs = store.list_runs(limit=100) or []
        seen: Dict[str, Dict[str, Any]] = {}
        for r in runs:
            rid = r.get("run_id") or ""
            if not rid:
                continue
            for rep in store.list_quality_reports(run_id=rid) or []:
                key = rep.get("row_id") or ""
                if not key:
                    continue
                if key not in seen or rep.get("ts", 0) > seen[key].get("ts", 0):
                    seen[key] = rep
        return list(seen.values())

    # run courant
    rid = run_id if run_id and run_id != "latest" else _resolve_latest_run_id(api)
    if not rid:
        return []
    return store.list_quality_reports(run_id=rid) or []


def _resolve_latest_run_id(api: Any) -> Optional[str]:
    try:
        latest = api._store.get_latest_run()
        return latest.get("run_id") if isinstance(latest, dict) else None
    except (AttributeError, KeyError):
        return None


def _recompute_in_memory(
    reports: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    target: Dict[str, Any],
) -> List[Dict[str, Any]]:
    """Pour chaque report, reapplique les poids+tiers du target sur les subscores stockes."""
    base_weights = baseline.get("weights") or {"video": 60, "audio": 30, "extras": 10}
    base_tiers = baseline.get("tiers") or {"premium": 85, "bon": 68, "moyen": 54}
    target_weights = target.get("weights") or base_weights
    target_tiers = target.get("tiers") or base_tiers

    out = []
    for rep in reports:
        metrics = rep.get("metrics") or {}
        subs = metrics.get("subscores") or {}
        video = float(subs.get("video") or 0)
        audio = float(subs.get("audio") or 0)
        extras = float(subs.get("extras") or 0)

        score_before = int(rep.get("score") or 0)
        tier_before = rep.get("tier") or _tier_for(score_before, base_tiers)

        score_after = _apply_weights(video, audio, extras, target_weights)
        tier_after = _tier_for(score_after, target_tiers)

        detected = metrics.get("detected") or {}
        out.append(
            {
                "row_id": rep.get("row_id") or "",
                "title": detected.get("title") or metrics.get("title") or rep.get("row_id") or "Sans titre",
                "year": detected.get("year") or 0,
                "codec": (detected.get("video_codec") or "").lower(),
                "resolution": detected.get("resolution") or "",
                "score_before": score_before,
                "score_after": score_after,
                "delta": score_after - score_before,
                "tier_before": tier_before,
                "tier_after": tier_after,
            }
        )
    return out


def _apply_weights(video: float, audio: float, extras: float, weights: Dict[str, Any]) -> int:
    wv = int(weights.get("video") or 0)
    wa = int(weights.get("audio") or 0)
    we = int(weights.get("extras") or 0)
    total = max(1, wv + wa + we)
    raw = (video * wv + audio * wa + extras * we) / total
    return max(0, min(100, int(round(raw))))


def _tier_for(score: int, tiers: Dict[str, Any]) -> str:
    """Derive le tier depuis le score. Accepte les anciennes cles (premium/bon/moyen)
    en plus des nouvelles (platinum/gold/silver/bronze) pour retro-compat."""
    p = int(tiers.get("platinum") or tiers.get("premium") or 85)
    g = int(tiers.get("gold") or tiers.get("bon") or 68)
    s = int(tiers.get("silver") or tiers.get("moyen") or 54)
    br = int(tiers.get("bronze") or 30)
    if score >= p:
        return "Platinum"
    if score >= g:
        return "Gold"
    if score >= s:
        return "Silver"
    if score >= br:
        return "Bronze"
    return "Reject"


def _build_delta_report(
    results: List[Dict[str, Any]],
    baseline: Dict[str, Any],
    target: Dict[str, Any],
    elapsed_ms: int,
    run_id: str,
    scope: str,
    preset_id: str,
) -> Dict[str, Any]:
    n = len(results)
    before_tiers = _count_tiers(r["tier_before"] for r in results)
    after_tiers = _count_tiers(r["tier_after"] for r in results)
    avg_before = round(sum(r["score_before"] for r in results) / n, 1) if n else 0
    avg_after = round(sum(r["score_after"] for r in results) / n, 1) if n else 0

    # Winners / losers
    winners = sorted([r for r in results if r["delta"] > 0], key=lambda r: -r["delta"])[:10]
    losers = sorted([r for r in results if r["delta"] < 0], key=lambda r: r["delta"])[:10]

    # Distribution shift matrix
    shift: Dict[str, int] = {}
    for r in results:
        key = f"{r['tier_before']}>{r['tier_after']}"
        shift[key] = shift.get(key, 0) + 1

    # By codec / resolution
    by_codec = _group_avg_delta(results, "codec")
    by_res = _group_avg_delta(results, "resolution")

    # Deltas agreges (nouveaux noms + fallback pour les snapshots pre-migration 011)
    prem_delta = after_tiers.get("Platinum", after_tiers.get("Premium", 0)) - before_tiers.get(
        "Platinum", before_tiers.get("Premium", 0)
    )
    fail_delta = before_tiers.get("Reject", before_tiers.get("Faible", 0)) - after_tiers.get(
        "Reject", after_tiers.get("Faible", 0)
    )
    improved = sum(1 for r in results if _TIER_ORDER.get(r["tier_after"], 0) > _TIER_ORDER.get(r["tier_before"], 0))
    degraded = sum(1 for r in results if _TIER_ORDER.get(r["tier_after"], 0) < _TIER_ORDER.get(r["tier_before"], 0))
    unchanged = sum(1 for r in results if r["tier_before"] == r["tier_after"] and r["delta"] == 0)

    # Cf issue #107 : champ `warnings` etait toujours [] (contrat API trompeur).
    # On le remplit avec des warnings derives des deltas pour signaler les
    # situations a impact eleve avant que l'utilisateur applique le preset.
    warnings: List[str] = []
    if degraded > improved and (degraded - improved) >= max(5, n // 20):
        warnings.append(f"Plus de films degrades ({degraded}) qu'ameliores ({improved}) avec ce preset.")
    if prem_delta <= -5:
        warnings.append(f"{-prem_delta} films perdraient leur statut Premium.")
    if fail_delta >= 10:
        warnings.append(f"{fail_delta} films passeraient en Reject.")
    if abs(avg_after - avg_before) < 0.5 and n >= 20:
        warnings.append("Impact moyen quasi-nul (< 0.5 pts) : ce preset modifie peu votre bibliotheque.")

    return {
        "preset_id": preset_id,
        "preset_label": target.get("label") or preset_id,
        "scope": scope,
        "run_id": run_id,
        "films_count": n,
        "elapsed_ms": elapsed_ms,
        "before": {
            "avg_score": avg_before,
            "tiers": before_tiers,
            "profile_name": baseline.get("label") or "Actuel",
        },
        "after": {
            "avg_score": avg_after,
            "tiers": after_tiers,
            "profile_name": target.get("label") or preset_id,
        },
        "delta": {
            "avg_score_delta": round(avg_after - avg_before, 1),
            "premium_gained": max(0, prem_delta),
            "premium_lost": max(0, -prem_delta),
            "mauvais_reduced": max(0, fail_delta),
            "net_tier_improvement": improved,
            "net_tier_degradation": degraded,
            "unchanged_count": unchanged,
        },
        "top_winners": winners,
        "top_losers": losers,
        "distribution_shift": shift,
        "by_codec": by_codec,
        "by_resolution": by_res,
        "warnings": warnings,
        "apply_estimate": {
            "write_count": n,
            "ms_estimate": max(100, int(elapsed_ms * 1.2)),
            "requires_reprobe": 0,
        },
    }


def _count_tiers(iterable: Any) -> Dict[str, int]:
    """Compte les tiers observes. Accepte les anciens noms pour retro-compat."""
    out: Dict[str, int] = {"Platinum": 0, "Gold": 0, "Silver": 0, "Bronze": 0, "Reject": 0}
    for t in iterable:
        k = str(t or "Reject")
        out[k] = out.get(k, 0) + 1
    return out


def _group_avg_delta(results: List[Dict[str, Any]], key: str) -> Dict[str, Dict[str, Any]]:
    buckets: Dict[str, List[int]] = {}
    for r in results:
        k = str(r.get(key) or "unknown")
        buckets.setdefault(k, []).append(r["delta"])
    out: Dict[str, Dict[str, Any]] = {}
    for k, deltas in buckets.items():
        if not deltas:
            continue
        out[k] = {"avg_delta": round(sum(deltas) / len(deltas), 1), "count": len(deltas)}
    return out


def _slugify(name: str) -> str:
    import re

    s = str(name).strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")[:40] or "custom"


def clear_cache() -> None:
    """Invalide le cache de simulations (a appeler sur apply preset ou save profile)."""
    _invalidate_cache()

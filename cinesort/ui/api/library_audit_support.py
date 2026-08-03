"""Library Audit endpoints — Vue Qualite (spec 10).

Endpoints :
    get_films_by_decade(filters=None)   — distribution films par decennie
    get_incomplete_sagas()              — sagas TMDb avec films manquants

Cf docs/internal/design/refonte_2026_05_17/screens/10-qualite.md
"""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from cinesort.ui.api._responses import err as _err_response

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_latest_run_id(api: Any) -> Optional[str]:
    # B1-bis (revue Lot C-fix) : jumeau de library_support._resolve_run_id —
    # l'ancien list_runs(limit=1) prenait le run utilitaire d'un bulk
    # Re-scanner (sans plan) => '0 films' sur la vue. Delegation au resolveur
    # corrige (skip des runs utilitaires).
    from cinesort.ui.api import library_support

    return library_support._resolve_run_id(api, None)


def _decade_from_year(year: int) -> Optional[str]:
    """Retourne '1990' pour 1995, '2020' pour 2024. None si annee invalide."""
    y = int(year or 0)
    if y < 1880 or y > 2100:
        return None
    return str((y // 10) * 10)


def _resolve_row_tmdb_id(row_dict: Dict[str, Any]) -> Optional[int]:
    """Resoud le tmdb_id effectif d'une PlanRow.

    `PlanRow` n'expose PAS de `tmdb_id` top-level (seulement
    `tmdb_collection_id`) : le tmdb_id reel vit sur les `Candidate`. On lit donc
    le top-level d'abord (au cas ou), puis le meilleur candidat de score >= 0.7.
    Miroir de `library_support._resolve_tmdb_id`. Audit 2026-07-08.
    """
    tid_top = row_dict.get("tmdb_id")
    if tid_top:
        try:
            v = int(tid_top)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    best: Optional[int] = None
    best_score = -1.0
    for cand in row_dict.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        cid = cand.get("tmdb_id")
        if not cid:
            continue
        try:
            score = float(cand.get("score") or 0.0)
        except (TypeError, ValueError):
            score = 0.0
        if score < 0.7:
            continue
        if score > best_score:
            try:
                best = int(cid)
                best_score = score
            except (TypeError, ValueError):
                continue
    return best


# ---------------------------------------------------------------------------
# Endpoint 3 : get_films_by_decade
# ---------------------------------------------------------------------------


def compute_by_decade(api: Any, run_id: Optional[str] = None) -> Dict[str, int]:
    """Helper interne : retourne le dict {decade -> count} pour le run cible.

    Reutilisable par get_global_stats (enrichissement by_decade au top-level).
    """
    resolved_rid = run_id or _resolve_latest_run_id(api)
    if not resolved_rid:
        return {}

    try:
        from cinesort.ui.api import library_support

        rows = library_support._build_library_rows(api, resolved_rid)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("compute_by_decade cannot build rows: %s", exc)
        return {}

    distribution: Dict[str, int] = {}
    for r in rows:
        decade = _decade_from_year(int(r.get("year") or 0))
        if not decade:
            continue
        distribution[decade] = distribution.get(decade, 0) + 1

    return distribution


def get_films_by_decade(api: Any, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Distribution des films par decennie.

    Args:
        filters: filtres optionnels (genre, source, audio_language, tier_v2).
                 Applique sur le sous-ensemble avant agregation.

    Returns:
        {
            "ok": True,
            "run_id": "...",
            "by_decade": {"1930": 12, "1940": 45, ..., "2020": 134},
            "total": N,
        }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague G : wrap global pour eviter HTTP 500
    # sur cet endpoint d'agregation appele depuis le dashboard Bibliotheque.
    try:
        return _get_films_by_decade_impl(api, filters)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("get_films_by_decade failed for filters=%s", filters)
        return {
            "ok": False,
            "error": "films_by_decade_failed",
            "message": str(exc),
            "user_message": "Impossible de charger la distribution par decennie.",
        }


def _get_films_by_decade_impl(api: Any, filters: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Implementation reelle de get_films_by_decade, sans wrap global (Vague G)."""
    resolved_rid = _resolve_latest_run_id(api)
    if not resolved_rid:
        return {"ok": True, "run_id": None, "by_decade": {}, "total": 0}

    try:
        from cinesort.ui.api import library_support

        rows = library_support._build_library_rows(api, resolved_rid)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("get_films_by_decade cannot build rows: %s", exc)
        return _err_response(
            f"Impossible de charger la bibliotheque: {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    # Filtrage optionnel (reutilise la meme logique de matching que library_support)
    if filters:
        try:
            from cinesort.ui.api import library_support

            rows = [r for r in rows if library_support._row_matches(r, filters)]
        except (AttributeError, TypeError) as exc:
            logger.debug("get_films_by_decade filter error: %s", exc)

    distribution: Dict[str, int] = {}
    for r in rows:
        decade = _decade_from_year(int(r.get("year") or 0))
        if not decade:
            continue
        distribution[decade] = distribution.get(decade, 0) + 1

    return {
        "ok": True,
        "run_id": resolved_rid,
        "by_decade": distribution,
        "total": sum(distribution.values()),
    }


# ---------------------------------------------------------------------------
# Endpoint 2 : get_incomplete_sagas
# ---------------------------------------------------------------------------


def _collect_owned_by_collection(rows: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """Groupe les films possedes par collection TMDb.

    Cherche les rows avec tmdb_collection_id (ou tmdb_collection_name sans id)
    et les agrège.

    Returns:
        {collection_id: {name, owned_films: [...]}, ...}
    """
    # On accede au plan brut pour avoir tmdb_collection_id (pas dans _build_library_rows)
    grouped: Dict[Any, Dict[str, Any]] = {}
    for r in rows:
        cid = r.get("tmdb_collection_id")
        cname = r.get("tmdb_collection_name")
        if not cid and not cname:
            continue
        # Cle de regroupement : id si dispo, sinon name
        key: Any = int(cid) if cid else f"name:{cname}"
        bucket = grouped.setdefault(
            key,
            {
                "collection_id": int(cid) if cid else None,
                "name": str(cname or "").strip() or "Saga sans nom",
                "owned_films": [],
            },
        )
        bucket["owned_films"].append(
            {
                "row_id": str(r.get("row_id") or ""),
                "title": str(r.get("title") or ""),
                "year": int(r.get("year") or 0),
                "tmdb_id": int(r.get("tmdb_id") or 0) or None,
            }
        )
    return grouped


def _load_plan_rows_with_collection(api: Any, run_id: str) -> List[Dict[str, Any]]:
    """Charge le plan en preservant tmdb_collection_id/name + tmdb_id.

    `_build_library_rows` perd certains champs (tmdb_collection_id, tmdb_id) car
    il aggrege juste pour la library_facade. Ici on lit le plan brut.

    Le tmdb_id est resolu depuis les `Candidate` (`_resolve_row_tmdb_id`) car
    `PlanRow` n'a pas de champ `tmdb_id` top-level. Audit 2026-07-08.
    """
    try:
        plan = api.run.get_plan(run_id)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("_load_plan_rows_with_collection error: %s", exc)
        return []
    if not plan or not plan.get("ok"):
        return []
    raw_rows = plan.get("rows") or []
    out: List[Dict[str, Any]] = []
    for r in raw_rows:
        out.append(
            {
                "row_id": str(r.get("row_id") or ""),
                "title": r.get("proposed_title") or r.get("nfo_title") or "",
                "year": int(r.get("proposed_year") or 0),
                "tmdb_id": _resolve_row_tmdb_id(r),
                "tmdb_collection_id": r.get("tmdb_collection_id"),
                "tmdb_collection_name": r.get("tmdb_collection_name"),
            }
        )
    return out


def _fetch_collection_parts(api: Any, collection_id: int) -> Optional[List[Dict[str, Any]]]:
    """Recupere la liste des films d'une collection TMDb (parts).

    Retourne None si erreur reseau (sera gere par l'appelant).
    """
    try:
        # Eviter import dur de TmdbClient ici, le creer via api si possible.
        # On reutilise le client TMDb existant sur api si dispo.
        client = getattr(api, "_tmdb_client", None)
        if client is None:
            # AUDIT 2026-06-10 (REAL 2/2) : `getattr(api, "_tmdb_client")` est
            # toujours None (attribut inexistant) et TmdbClient(api_key=api_key)
            # OMETTAIT le parametre requis cache_path -> TypeError avale ->
            # _fetch_collection_parts retournait toujours None ->
            # get_incomplete_sagas retournait toujours sagas:[] (feature morte).
            # On construit le client correctement, avec cle dé-masquee + cache_path.
            import cinesort.infra.state as _state
            from cinesort.infra.tmdb_client import TmdbClient
            from cinesort.ui.api.settings_support import normalize_user_path

            settings = api._internal_settings()
            api_key = str(settings.get("tmdb_api_key") or "").strip()
            if not api_key:
                return None
            state_dir = normalize_user_path(settings.get("state_dir"), _state.default_state_dir())
            try:
                cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
            except (TypeError, ValueError):
                cache_ttl_days = 30
            client = TmdbClient(
                api_key=api_key,
                cache_path=state_dir / "tmdb_cache.json",
                timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
                cache_ttl_days=cache_ttl_days,
            )
        # Appel direct collection/{id}
        url = f"https://api.themoviedb.org/3/collection/{int(collection_id)}"
        params = {"api_key": getattr(client, "api_key", None), "language": "fr-FR"}
        resp = client._http_get(url, params=params)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, dict):
            return None
        parts = data.get("parts") or []
        out: List[Dict[str, Any]] = []
        for part in parts:
            if not isinstance(part, dict):
                continue
            rd = str(part.get("release_date") or "")
            year = int(rd[:4]) if len(rd) >= 4 and rd[:4].isdigit() else None
            out.append(
                {
                    "tmdb_id": int(part.get("id") or 0) or None,
                    "title": str(part.get("title") or ""),
                    "year": year,
                }
            )
        return out
    # except Exception large : best-effort, on retourne None
    except Exception as exc:  # noqa: BLE001
        logger.debug("_fetch_collection_parts error cid=%s: %s", collection_id, exc)
        return None


def get_incomplete_sagas(api: Any) -> Dict[str, Any]:
    """Liste les sagas TMDb avec films manquants dans la bibliotheque.

    Returns:
        {
            "ok": True,
            "run_id": "...",
            "sagas": [
                {
                    "collection_id": int,
                    "name": str,
                    "total_films_in_collection": int,
                    "owned_count": int,
                    "missing_count": int,
                    "missing_films": [{title, year, tmdb_id}, ...],
                    "owned_films": [{row_id, title, year, tmdb_id}, ...],
                },
                ...
            ],
            "total": N,
        }
    """
    resolved_rid = _resolve_latest_run_id(api)
    if not resolved_rid:
        return {"ok": True, "run_id": None, "sagas": [], "total": 0}

    plan_rows = _load_plan_rows_with_collection(api, resolved_rid)
    if not plan_rows:
        return {"ok": True, "run_id": resolved_rid, "sagas": [], "total": 0}

    grouped = _collect_owned_by_collection(plan_rows)

    sagas_out: List[Dict[str, Any]] = []
    for key, bucket in grouped.items():
        cid = bucket.get("collection_id")
        if not cid:
            # Pas d'ID TMDb -> impossible de fetcher la collection complete
            # On l'ignore (saga inutile sans verite TMDb)
            continue

        parts = _fetch_collection_parts(api, int(cid))
        # Si echec reseau ou cache absent : on skip cette saga
        if parts is None:
            continue

        owned_films = bucket.get("owned_films") or []
        owned_tmdb_ids = {int(f["tmdb_id"]) for f in owned_films if f.get("tmdb_id")}
        owned_title_year = {(str(f.get("title") or "").lower().strip(), int(f.get("year") or 0)) for f in owned_films}

        missing_films: List[Dict[str, Any]] = []
        for part in parts:
            pid = part.get("tmdb_id")
            ptitle = str(part.get("title") or "").lower().strip()
            pyear = int(part.get("year") or 0)
            # 1) match exact par tmdb_id
            if pid and int(pid) in owned_tmdb_ids:
                continue
            # 2) fallback title+year (cas ou tmdb_id pas dans le plan)
            if (ptitle, pyear) in owned_title_year:
                continue
            missing_films.append(
                {
                    "title": part.get("title"),
                    "year": part.get("year"),
                    "tmdb_id": part.get("tmdb_id"),
                }
            )

        if not missing_films:
            continue  # saga complete

        sagas_out.append(
            {
                "collection_id": int(cid),
                "name": bucket.get("name") or "",
                "total_films_in_collection": len(parts),
                "owned_count": len(owned_films),
                "missing_count": len(missing_films),
                "missing_films": missing_films,
                "owned_films": owned_films,
            }
        )

    # Tri par missing_count desc puis name asc
    sagas_out.sort(key=lambda s: (-int(s.get("missing_count") or 0), str(s.get("name") or "").lower()))

    return {
        "ok": True,
        "run_id": resolved_rid,
        "sagas": sagas_out,
        "total": len(sagas_out),
        "generated_ts": time.time(),
    }

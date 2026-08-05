"""Library Audit endpoints — Vue Qualite (spec 10).

Endpoints :
    get_films_by_decade(filters=None)   — distribution films par decennie
    get_incomplete_sagas()              — sagas TMDb avec films manquants

Cf docs/internal/design/refonte_2026_05_17/screens/10-qualite.md
"""

from __future__ import annotations

import contextlib
import logging
import time
from typing import Any, Dict, List, Optional

import cinesort.infra.state as _state
from cinesort.domain.core import windows_safe
from cinesort.ui.api import library_support
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.film_support import _resolve_chosen_tmdb_id
from cinesort.ui.api.library_actions_support import _build_tmdb_client_optional
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _resolve_latest_run_id(api: Any) -> Optional[str]:
    # B1-bis (revue Lot C-fix) : jumeau de library_support._resolve_run_id —
    # l'ancien list_runs(limit=1) prenait le run utilitaire d'un bulk
    # Re-scanner (sans plan) => '0 films' sur la vue. Delegation au resolveur
    # corrige (skip des runs utilitaires).
    return library_support._resolve_run_id(api, None)


def _decade_from_year(year: int) -> Optional[str]:
    """Retourne '1990' pour 1995, '2020' pour 2024. None si annee invalide."""
    y = int(year or 0)
    if y < 1880 or y > 2100:
        return None
    return str((y // 10) * 10)


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


def _matching_candidates(row: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Candidats de la row qui correspondent REELLEMENT a sa proposition.

    `PlanRow.candidates` n'est pas trie : `pick_best_candidate` classe une COPIE
    locale et `_build_resolved_row` reserialise la liste d'origine. Prendre
    `candidates[0]` a l'aveugle rendrait donc le tmdb_id d'un AUTRE film.
    On ne retient que les candidats dont (titre, annee) redonnent exactement
    `proposed_title` / `proposed_year`, tries par score decroissant.

    Une annee absente (0) n'est PAS un joker : `_build_unresolved_row` produit
    `proposed_year = 0` et des candidats sans annee, qui matcheraient alors sur
    le seul titre. `_build_resolved_row` exige `chosen.year`, donc toute row
    reellement resolue porte une annee — refuser 0 ne coute rien et ferme la
    porte a une revendication de possession sur une row non resolue.
    """

    def _key(value: Any) -> str:
        return windows_safe(str(value or "")).strip().casefold()

    wanted_title = _key(row.get("proposed_title"))
    if not wanted_title:
        return []
    try:
        wanted_year = int(row.get("proposed_year") or 0)
    except (TypeError, ValueError):
        return []
    if wanted_year <= 0:
        return []

    matching: List[Dict[str, Any]] = []
    for cand in row.get("candidates") or []:
        if not isinstance(cand, dict):
            continue
        if _key(cand.get("title")) != wanted_title:
            continue
        try:
            cand_year = int(cand.get("year") or 0)
        except (TypeError, ValueError):
            continue
        if cand_year != wanted_year:
            continue
        matching.append(cand)

    def _score(cand: Dict[str, Any]) -> float:
        try:
            return float(cand.get("score") or 0.0)
        except (TypeError, ValueError):
            return 0.0

    # `sorted` est stable : a score egal l'ordre du plan est conserve.
    return sorted(matching, key=_score, reverse=True)


def _plan_row_tmdb_id(row: Dict[str, Any]) -> Optional[int]:
    """Resout le tmdb_id d'une PlanRow serialisee, ou None.

    `PlanRow` (`cinesort/domain/core.py`) ne porte AUCUN `tmdb_id` top-level :
    le tmdb_id reel vit sur les `Candidate`. Le seul producteur de
    `row["tmdb_id"]` est `film_support.overlay_tmdb_override`, applique par
    `history_support._enrich_plan_payload` UNIQUEMENT quand l'utilisateur a
    choisi un candidat A LA MAIN (table `film_tmdb_overrides`). Pour tous les
    matchs automatiques — la quasi-totalite d'une bibliotheque — la clef est
    absente et `owned_tmdb_ids` restait vide : le match primaire des sagas etait
    mort, la completude reposait sur le seul repli (titre, annee).

    La priorite (`chosen_tmdb_id` > `tmdb_id` > candidat) reste celle du helper
    canonique du depot, `film_support._resolve_chosen_tmdb_id` : on ne duplique
    pas une variante, on lui restreint seulement les candidats offerts.
    """
    resolved = _resolve_chosen_tmdb_id(row, _matching_candidates(row))
    return int(resolved) if resolved > 0 else None


def _load_plan_rows_with_collection(api: Any, run_id: str) -> List[Dict[str, Any]]:
    """Charge le plan en preservant tmdb_collection_id/name + tmdb_id.

    `_build_library_rows` perd certains champs (tmdb_collection_id, tmdb_id) car
    il aggrege juste pour la library_facade. Ici on lit le plan brut.
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
                # #714 (meme famille) : le repli `r.get("nfo_title")` etait une
                # seconde clef fantome — `PlanRow` porte `nfo_path`, jamais
                # `nfo_title`, et aucun enrichissement ne la pose. Repli mort.
                "title": r.get("proposed_title") or "",
                "year": int(r.get("proposed_year") or 0),
                # #714 : `r.get("tmdb_id")` etait une clef FANTOME (absente du
                # dataclass PlanRow) -> owned_tmdb_ids toujours vide.
                "tmdb_id": _plan_row_tmdb_id(r),
                "tmdb_collection_id": r.get("tmdb_collection_id"),
                "tmdb_collection_name": r.get("tmdb_collection_name"),
            }
        )
    return out


def _build_tmdb_client(api: Any) -> Optional[Any]:
    """Construit UN client TMDb, destine a etre partage sur tout un appel.

    Issue #467 : `_fetch_collection_parts` construisait son propre client a
    CHAQUE saga. `TmdbClient.__init__` termine par `self._load_cache()`
    (tmdb_client.py:169), donc N sagas = N lectures integrales de
    `tmdb_cache.json` — et surtout N `CircuitBreaker` NEUFS
    (tmdb_client.py:166). Le breaker (seuil 10 echecs consecutifs) ne pouvait
    donc JAMAIS s'ouvrir : chaque saga repartait d'un compteur a zero et
    repayait ses 3 retries avec backoff. Un client unique redonne au breaker
    et au pool de connexions de la Session leur effet sur toute la boucle.

    Retourne None si la cle TMDb est absente ou si la construction echoue
    (best-effort : l'appelant traite None comme une absence de verite TMDb).

    AUDIT 2026-06-10 (REAL 2/2), conserve : le lookup `getattr(api,
    "_tmdb_client")` d'origine etait mort (aucun module ne pose cet attribut,
    verifie sur tout le depot) et `TmdbClient(api_key=api_key)` OMETTAIT le
    parametre requis `cache_path` -> TypeError avale -> `_fetch_collection_parts`
    retournait toujours None -> `get_incomplete_sagas` toujours `sagas: []`
    (feature 100% morte). La construction correcte est desormais celle,
    unique, de `_build_tmdb_client_optional`.
    """
    try:
        settings = api._internal_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), _state.default_state_dir())
        return _build_tmdb_client_optional(settings, state_dir)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.debug("_build_tmdb_client error: %s", exc)
        return None


def _fetch_collection_parts(
    api: Any,
    collection_id: int,
    *,
    client: Any = None,
) -> Optional[List[Dict[str, Any]]]:
    """Recupere la liste des films d'une collection TMDb (parts).

    Retourne None si erreur reseau (sera gere par l'appelant).

    Issue #467 : deux changements.
      - `client` peut etre fourni par l'appelant, pour qu'UN seul client serve
        toute la boucle des sagas (cf _build_tmdb_client).
      - le resultat passe par le cache TTL du client. Avant, l'appel tapait
        `client._http_get` DIRECTEMENT, court-circuitant `_cache_get` /
        `_cache_set` : le cache TMDb annonce par le reglage
        `tmdb_cache_ttl_days` n'a jamais servi pour cet endpoint, chaque
        ouverture de la vue « sagas incompletes » refaisait N appels reseau.
        La cle `collection_parts|{id}` n'est pas dans `_DETERMINISTIC_PREFIXES`
        (tmdb_client.py:63) : elle herite donc du TTL COURT, ce qui est voulu —
        une collection peut gagner un film.
    """
    try:
        tmdb = client if client is not None else _build_tmdb_client(api)
        if tmdb is None:
            return None
        cache_key = f"collection_parts|{int(collection_id)}"
        cached = tmdb._cache_get(cache_key)
        # La garde ne validait que le CONTENEUR : `isinstance(cached, list)`
        # acceptait `["corrompu"]`, et `get_incomplete_sagas` appelait ensuite
        # `part.get("title")` sur une chaine -> AttributeError, endpoint en
        # echec. Le commentaire promettait pourtant qu'une entree corrompue
        # « ne doit pas etre servie telle quelle » : il decrivait une intention
        # que le code ne tenait pas.
        #
        # On valide donc chaque ELEMENT contre la forme normalisee que le
        # chemin d'ecriture produit plus bas (`tmdb_id` / `title` / `year`).
        # Un cache malforme est traite comme ABSENT : on re-interroge TMDb.
        # C'est le bon sens de l'erreur — un miss de cache coute un appel
        # reseau, un endpoint en echec coute la fonctionnalite entiere.
        if _parts_cache_valide(cached):
            return cached
        # Appel direct collection/{id}
        url = f"https://api.themoviedb.org/3/collection/{int(collection_id)}"
        params = {"api_key": getattr(tmdb, "api_key", None), "language": "fr-FR"}
        resp = tmdb._http_get(url, params=params)
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
        tmdb._cache_set(cache_key, out)
        with contextlib.suppress(OSError, PermissionError):
            tmdb._save_cache_atomic()
        return out
    # except Exception large : best-effort, on retourne None
    except Exception as exc:  # noqa: BLE001
        logger.debug("_fetch_collection_parts error cid=%s: %s", collection_id, exc)
        return None


def _parts_cache_valide(cached: Any) -> bool:
    """Le cache porte-t-il bien une liste d'entrees a la forme attendue ?

    Forme normalisee produite par `_fetch_collection_parts` : des dicts portant
    `tmdb_id`, `title` et `year`. Une liste VIDE est valide — c'est le resultat
    legitime d'une collection sans partie manquante, et la refuser relancerait
    un appel TMDb a chaque consultation.
    """
    if not isinstance(cached, list):
        return False
    return all(isinstance(part, dict) and "title" in part and "year" in part for part in cached)


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

    # Issue #467 : UN SEUL client TMDb pour toute la boucle (avant : un par
    # saga, donc N chargements de tmdb_cache.json et N circuit breakers neufs).
    tmdb_client = _build_tmdb_client(api)

    sagas_out: List[Dict[str, Any]] = []
    for key, bucket in grouped.items():
        cid = bucket.get("collection_id")
        if not cid:
            # Pas d'ID TMDb -> impossible de fetcher la collection complete
            # On l'ignore (saga inutile sans verite TMDb)
            continue

        parts = _fetch_collection_parts(api, int(cid), client=tmdb_client)
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

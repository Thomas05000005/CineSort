from __future__ import annotations

import contextlib
import json
import logging
from typing import Any, Dict, List, Optional, Set

import cinesort.infra.state as state
from cinesort.domain.i18n_messages import t
from cinesort.infra.tmdb_client import TmdbClient
from cinesort.ui.api._responses import err as _err_response

# AUDIT 2026-06-10 (CRITICAL) : `api._normalize_user_path` n'existe pas (c'est un
# nom module-level dans cinesort_api, pas une methode d'instance) -> AttributeError
# non rattrapee -> HTTP 500 sur get_tmdb_posters / search_tmdb des qu'une cle TMDb
# est configuree. On utilise la vraie fonction module-level.
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)

#: Cap defensif sur le nombre d'ids resolus en un appel (cf le commentaire
#: detaille dans `get_tmdb_posters`). Borne un appel pathologique sans brider
#: l'usage normal : les resolutions warm coutent ~3 ms pour 2000 ids.
_POSTERS_MAX_IDS = 2000


def get_tmdb_posters(api: Any, tmdb_ids: List[int], size: str = "w92", force_refresh: bool = False) -> Dict[str, Any]:
    if not isinstance(tmdb_ids, list):
        return _err_response(
            t("errors.payload_tmdb_ids_invalid"), category="validation", level="info", log_module=__name__
        )
    try:
        ids: List[int] = []
        for item in tmdb_ids or []:
            try:
                value = int(item)
            except (ImportError, OSError, TypeError, ValueError):
                continue
            if value > 0:
                ids.append(value)
        # Fix audit 2026-05-25 (v1.5.5) Vague J : ancien cap [:20] truncait
        # silencieusement les batchs > 20 IDs (catastrophique pour
        # _build_library_rows qui appelle avec 853 IDs -> 833 silently dropped).
        # On garde un cap defensif mais large (2000) pour ne pas exploser TMDb
        # en cas d'appel pathologique. Les posters sont servis depuis le cache
        # local (tmdb_cache.json) donc le cout reel est minime apres le 1er run.
        #
        # Ultra-audit 2026-08 (N20) : le cap etait `sorted(set(ids))[:2000]`,
        # donc il gardait les 2000 PLUS PETITS tmdb_id. Les identifiants TMDb
        # croissent avec le temps : au-dela de 2000 films, les jaquettes
        # silencieusement perdues etaient TOUJOURS celles des films les plus
        # RECENTS, sur toutes les pages et a chaque appel. `_build_library_rows`
        # collecte les ids AVANT pagination (library_support.py:288-306), donc
        # une bibliotheque de 3000 films exposait le defaut en permanence.
        # On dedoublonne desormais en PRESERVANT L'ORDRE DE L'APPELANT : la
        # troncature suit l'ordre d'affichage (les premieres pages, celles que
        # l'utilisateur voit, sont servies) au lieu d'un critere arbitraire.
        seen: Set[int] = set()
        ordered: List[int] = []
        for value in ids:
            if value not in seen:
                seen.add(value)
                ordered.append(value)
        truncated = max(0, len(ordered) - _POSTERS_MAX_IDS)
        ids = ordered[:_POSTERS_MAX_IDS]
        if not ids:
            return {"ok": True, "posters": {}}

        settings = api._internal_settings()  # AUDIT: secrets en clair (tmdb_api_key) sinon 401
        api_key = str(settings.get("tmdb_api_key") or "").strip()
        if not api_key:
            # Audit 2026-06-08 : sans indicateur explicite, le frontend ne peut
            # pas distinguer 'TMDB non configure' de 'tmdb_id introuvable',
            # resultat = 100% des cartes affichent le clap generique sans
            # explication. On ajoute un `reason` pour que bibliotheque.js puisse
            # afficher une banniere/toast 'Configurez TMDB dans Parametres'.
            # Backward compat preservee : ok=True + posters={} inchange, le
            # champ `reason` est purement additif et ignore par les anciens
            # consommateurs.
            return {"ok": True, "posters": {}, "reason": "tmdb_not_configured"}

        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        # V5-03 polish v7.7.0 : propager le TTL configurable.
        try:
            cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
        except (TypeError, ValueError):
            cache_ttl_days = 30
        # Ultra-audit 2026-08 (N20) — le client est volontairement RECONSTRUIT a
        # chaque appel ; ne pas le memoiser sur le modele de
        # poster_proxy._build_or_get_tmdb_client sans traiter d'abord le point
        # ci-dessous.
        #
        # `TmdbClient._save_cache_atomic` (tmdb_client.py:328) serialise
        # `self._cache` EN ENTIER et fait `os.replace` : il ecrase le fichier, il
        # ne fusionne pas. Un client de longue duree ici ecraserait donc les
        # entrees ecrites entre-temps par le client memoise de poster_proxy, qui
        # vise le MEME tmdb_cache.json. Le client neuf relit le fichier a la
        # construction, donc il preserve ces entrees.
        # Gain mesure par la passe adversaire : ~45 ms par appel sur un cache de
        # 10 000 entrees. Ce n'est pas le prix d'un risque de purge de cache.
        tmdb = TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
            cache_ttl_days=cache_ttl_days,
        )
        posters: Dict[str, str] = {}
        for movie_id in ids:
            # E4 (verif totale 2026-07) : le bouton refresh jaquette envoie
            # force_refresh=true depuis 2026-05-24 mais le parametre n'existait
            # pas cote backend (TypeError => 400). E4-bis (revue) : bypass de
            # LECTURE du cache (pas de purge) — le fallback stale survit si
            # TMDb est injoignable.
            url = tmdb.get_movie_poster_thumb_url(movie_id, size=size or "w92", force_refresh=force_refresh)
            if url:
                posters[str(movie_id)] = url
        tmdb.flush()
        # Ultra-audit 2026-08 (N20) : la troncature n'est plus silencieuse. Champ
        # purement additif (les consommateurs existants l'ignorent), absent quand
        # rien n'est tronque pour ne pas alourdir la reponse du cas courant.
        if truncated:
            logger.info("get_tmdb_posters: %d ids au-dela du cap de %d ignores", truncated, _POSTERS_MAX_IDS)
            return {"ok": True, "posters": posters, "truncated": truncated}
        return {"ok": True, "posters": posters}
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)


# Spec 06 3.4 : poster size servi a l'UI pour la recherche manuelle TMDb.
# w185 = compromis lisibilite / poids (~15 Ko/poster) pour des vignettes
# 92 px x 138 px dans le sous-modal.
_SEARCH_POSTER_SIZE = "w185"
# Hard cap defensif : on n'envoie jamais > N resultats au front pour eviter
# d'inonder le DOM si TMDb retourne 20 hits sur une requete generique.
_SEARCH_MAX_RESULTS = 10


def _build_tmdb_client(api: Any):
    """Construit un TmdbClient depuis les settings (secrets EN CLAIR via
    _internal_settings, sinon cle masquee -> 401). Retourne (tmdb, None) ou
    (None, err_response) si la cle manque.
    """
    settings = api._internal_settings()
    api_key = str(settings.get("tmdb_api_key") or "").strip()
    if not api_key:
        return None, _err_response(
            "Cle TMDb non configuree (Parametres > Integrations).",
            category="config",
            level="info",
            log_module=__name__,
        )
    state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
    try:
        cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
    except (TypeError, ValueError):
        cache_ttl_days = 30
    tmdb = TmdbClient(
        api_key=api_key,
        cache_path=state_dir / "tmdb_cache.json",
        timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
        cache_ttl_days=cache_ttl_days,
    )
    return tmdb, None


def _poster_url_from_path(poster_path: Any, size: str = "w185") -> Optional[str]:
    path = str(poster_path or "").strip()
    if not path:
        return None
    if not path.startswith("/"):
        path = "/" + path
    return f"https://image.tmdb.org/t/p/{size}{path}"


def enrich_tmdb_ids_by_title(api: Any, run_id: str, row_ids: Any) -> Dict[str, Any]:
    """R5-H2 : resout le tmdb_id (+ jaquette) de films deja identifies (NFO/nom)
    SANS tmdb_id, par recherche TMDb titre+annee, et le PERSISTE dans le plan.

    N'altere PAS l'identification (proposed_title/year/source inchanges) : on ne
    fait qu'attacher le tmdb_id. Le poster suit automatiquement car le builder
    Library recupere les jaquettes par tmdb_id (get_tmdb_posters). Repond au cas
    biblio 100% NFO ou reactiver TMDb seul ne suffit pas (la recherche TMDb est
    court-circuitee au scan quand un NFO a matche).

    Returns: {ok, resolved, total, posters: {row_id: url}} ou err.
    """
    ids = {str(r) for r in (row_ids or []) if str(r).strip()}
    if not run_id or not str(run_id).strip():
        return _err_response("run_id requis.", category="validation", level="info", log_module=__name__)
    if not ids:
        return _err_response("Aucun row_id valide.", category="validation", level="info", log_module=__name__)

    tmdb, err = _build_tmdb_client(api)
    if err:
        return err

    try:
        settings = api._internal_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        run_paths = api._run_paths_for(state_dir, run_id, ensure_exists=False)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

    plan_jsonl = getattr(run_paths, "plan_jsonl", None)
    if plan_jsonl is None or not plan_jsonl.exists():
        return _err_response("Plan introuvable pour ce run.", category="resource", level="info", log_module=__name__)

    all_rows: List[Dict[str, Any]] = []
    try:
        with open(plan_jsonl, encoding="utf-8") as fp:
            for line in fp:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except (TypeError, ValueError):
                    continue
                if isinstance(data, dict):
                    all_rows.append(data)
    except (OSError, UnicodeDecodeError) as exc:
        # Plan verrouille (AV Windows) ou encodage corrompu -> erreur propre
        # plutot qu'un HTTP 500 (cet endpoint n'a pas de wrap global).
        return _err_response(f"Plan illisible: {exc}", category="runtime", level="error", log_module=__name__)

    posters: Dict[str, str] = {}
    # AUDIT 2026-06-14 (R6-H) : on renvoie aussi le tmdb_id resolu par row_id.
    # Sans ca, le client ne mettait pas a jour r.tmdb_id en memoire -> le rendu
    # (proxy /api/poster?id=tmdb_id) ne pouvait pas afficher la jaquette fraiche.
    resolved_ids: Dict[str, int] = {}
    resolved = 0
    changed = False
    for row in all_rows:
        rid = str(row.get("row_id") or "")
        if rid not in ids:
            continue
        existing = row.get("tmdb_id")
        try:
            if existing is not None and int(existing) > 0:
                continue  # deja un tmdb_id : rien a resoudre.
        except (TypeError, ValueError):
            pass
        title = str(row.get("proposed_title") or row.get("nfo_title") or "").strip()
        if not title:
            continue
        year = int(row.get("proposed_year") or 0) or None
        try:
            results = tmdb.search_movie(title, year=year)
        except (OSError, KeyError, TypeError, ValueError) as exc:
            logger.debug("enrich_tmdb: search '%s' (%s) a echoue: %s", title, year, exc)
            continue
        if not results:
            continue
        best = results[0]
        try:
            tid = int(best.id)
        except (TypeError, ValueError):
            continue
        if tid <= 0:
            continue
        row["tmdb_id"] = tid
        changed = True
        resolved += 1
        resolved_ids[rid] = tid
        url = _poster_url_from_path(getattr(best, "poster_path", None))
        if url:
            posters[rid] = url

    if changed:
        # Cette fonction tourne dans le thread daemon `tmdb-enrich-<run_id>`
        # lance en fin de scan (run_flow_support.py:634) : son `.tmp` en dur
        # etait le MEME chemin que celui de `_rematch_tmdb_and_update_plan`,
        # declenchable au meme instant depuis l'UI (#732). Cf write_plan_jsonl.
        # Un SEUL import differe pour les deux symboles : cf. la meme note dans
        # `library_actions_support._rematch_tmdb_and_update_plan` (cliquet
        # `test_lazy_imports_bounded`).
        from cinesort.ui.api.run_data_support import (  # noqa: PLC0415
            resync_run_state_rows,
            write_plan_jsonl,
        )

        write_plan_jsonl(plan_jsonl, all_rows)

        # AUDIT 2026-07-13 (HIGH-17) : toute reecriture de plan.jsonl doit
        # resynchroniser le snapshot memoire (prefere au fichier par get_plan /
        # apply / dashboard) et purger le cache dashboard, dont la signature est
        # calculee sur plan.jsonl (sinon cache empoisonne avec des rows perimees).
        resync_run_state_rows(api, run_id)

    with contextlib.suppress(OSError, AttributeError):
        tmdb.flush()

    return {"ok": True, "resolved": int(resolved), "total": len(ids), "posters": posters, "ids": resolved_ids}


def search_tmdb(
    api: Any,
    query: str,
    year: Optional[int] = None,
) -> Dict[str, Any]:
    """Spec 06 3.4 : recherche manuelle TMDb pour le Modal Film.

    Quand les candidats auto-detectes du film ne contiennent pas le bon
    match (titre exotique, faute de scan, etc.), l'utilisateur peut taper
    une requete libre et choisir un resultat -> appel de
    set_film_tmdb_candidate ensuite.

    Returns
    -------
    dict
        - {"ok": True, "results": [...], "query": str, "year": int|None, "count": int}
        - {"ok": False, "message": str} si validation/runtime echoue

    Chaque resultat contient :
        - tmdb_id (int)
        - title (str)
        - original_title (str|None)
        - year (int|None)
        - poster_url (str|None) - URL w185 prete a afficher
        - overview (str) - tronquee a 240 chars
        - vote_average (float|None)
        - vote_count (int|None)
        - popularity (float|None)
    """
    q = str(query or "").strip()
    if not q:
        return _err_response("Requete vide.", category="validation", level="info", log_module=__name__)
    if len(q) < 2:
        return _err_response(
            "Requete trop courte (2 caracteres minimum).",
            category="validation",
            level="info",
            log_module=__name__,
        )

    year_int: Optional[int] = None
    if year is not None and year != "":
        try:
            year_int = int(year)
            if year_int < 1870 or year_int > 2100:
                year_int = None
        except (TypeError, ValueError):
            year_int = None

    try:
        settings = api._internal_settings()  # AUDIT: secrets en clair (tmdb_api_key) sinon 401
        api_key = str(settings.get("tmdb_api_key") or "").strip()
        if not api_key:
            return _err_response(
                "Cle TMDb non configuree (Parametres).",
                category="config",
                level="info",
                log_module=__name__,
            )

        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        try:
            cache_ttl_days = int(settings.get("tmdb_cache_ttl_days") or 30)
        except (TypeError, ValueError):
            cache_ttl_days = 30
        tmdb = TmdbClient(
            api_key=api_key,
            cache_path=state_dir / "tmdb_cache.json",
            timeout_s=float(settings.get("tmdb_timeout_s") or 10.0),
            cache_ttl_days=cache_ttl_days,
        )

        raw = tmdb.search_movie(q, year=year_int, max_results=_SEARCH_MAX_RESULTS)
        results = []
        for r in raw:
            poster_url = None
            if r.poster_path:
                path = str(r.poster_path).strip()
                if path:
                    if not path.startswith("/"):
                        path = "/" + path
                    poster_url = f"https://image.tmdb.org/t/p/{_SEARCH_POSTER_SIZE}{path}"
            overview = ""
            # Tier 2 audit : _get_movie_detail_cached peut lever (HTTP, timeout,
            # rate limit). On degrade gracieusement plutot que de crasher toute
            # la recherche pour un detail manquant.
            try:
                detail = tmdb._get_movie_detail_cached(int(r.id))
            except (OSError, AttributeError, KeyError, TypeError, ValueError) as detail_exc:
                logger.debug("search_tmdb: detail fetch failed for tmdb_id=%s: %s", r.id, detail_exc)
                detail = None
            if isinstance(detail, dict):
                overview = str(detail.get("overview") or "")
            if overview and len(overview) > 240:
                overview = overview[:237].rstrip() + "..."
            results.append(
                {
                    "tmdb_id": int(r.id),
                    "title": r.title,
                    "original_title": r.original_title,
                    "year": r.year,
                    "poster_url": poster_url,
                    "overview": overview,
                    "vote_average": r.vote_average,
                    "vote_count": r.vote_count,
                    "popularity": r.popularity,
                }
            )
        tmdb.flush()
        # Issue #413 : quand TMDb est injoignable, le client sert le cache meme
        # EXPIRE. C'est le bon comportement, mais le rendre sans le dire fait
        # passer un echec reseau pour un succes : l'utilisateur choisit alors un
        # titre/poster potentiellement perime en croyant interroger TMDb.
        # `stale_cached_at` (epoch) date la plus recente de ces reponses de
        # secours ; il vaut None quand l'entree de cache n'en portait pas.
        stale_report = tmdb.stale_fallback_report()
        is_stale = int(stale_report.get("count") or 0) > 0
        return {
            "ok": True,
            "results": results,
            "query": q,
            "year": year_int,
            "count": len(results),
            "stale": is_stale,
            "stale_cached_at": stale_report.get("last_cached_at") if is_stale else None,
        }
    except (OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__)

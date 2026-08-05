"""Candidate scoring, multi-root scan and duplicate detection (VP-E refactor).

Concentre le pipeline de scoring/filtrage des candidats (NFO local, lookup
IMDb/TMDb cross-check, fallback recherche TMDb, runtime HARD filter) qui
alimente `_plan_item`, ainsi que la couche multi-roots et le calcul des
groupes de doublons sur les destinations planifiees.
"""

from __future__ import annotations

import contextlib
import logging
from collections import defaultdict
from dataclasses import fields as dc_fields
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import cinesort.app.apply_core as _apply_core_mod
import cinesort.domain.core as core_mod
from cinesort.domain import duplicate_support as _dup
from cinesort.domain.edition_helpers import strip_edition
from cinesort.domain.runtime_hard_filter import (
    DEFAULT_RUNTIME_HARD_THRESHOLD_MIN,
    WARN_RUNTIME_HARD_KEPT_DECLARED,
    evaluate_runtime_hard_filter,
)
from cinesort.domain.title_helpers import _norm_for_tokens, extract_provider_tags
from cinesort.infra.fs_safety import is_dir_accessible, safe_path_exists
from cinesort.infra.tmdb_client import TmdbClient

if TYPE_CHECKING:
    from cinesort.domain.core import Config, PlanRow, Stats

_log = logging.getLogger(__name__)


def _build_nfo_candidates(
    cfg: "Config",
    folder_name: str,
    video_name: str,
    *,
    nfo: Optional[Any],
    name_year: Optional[int],
    remaster_hint: bool,
    log: Callable[[str, str], None],
    log_ctx: str,
) -> Tuple[List[Any], Dict[str, Any]]:
    """Analyse la coherence du NFO et construit les candidats nfo_cands.

    Retourne (nfo_cands, nfo_state) ou nfo_state contient :
        nfo_ok, nfo_cov, nfo_seq, nfo_reject_reason, year_delta_reject, nfo_partial_match.
    """

    state = {
        "nfo_ok": False,
        "nfo_cov": 0.0,
        "nfo_seq": 0.0,
        "nfo_reject_reason": "",
        "year_delta_reject": False,
        "nfo_partial_match": False,  # P1.1.b : NFO matche folder XOR filename
    }
    nfo_cands: List[Any] = []
    if not (nfo and nfo.year and (nfo.title or nfo.originaltitle)):
        return nfo_cands, state

    consistency = core_mod.nfo_consistency_check(cfg, nfo, folder_name, video_name)
    state["nfo_ok"] = consistency.ok
    state["nfo_cov"] = consistency.cov
    state["nfo_seq"] = consistency.seq
    state["nfo_partial_match"] = consistency.ok and (consistency.folder_match != consistency.filename_match)
    if state["nfo_partial_match"]:
        which = "dossier" if consistency.folder_match else "fichier"
        log(
            "WARN",
            f"NFO partial match {log_ctx}: matche seulement le {which} "
            f"(folder_cov={consistency.folder_cov:.2f}, file_cov={consistency.filename_cov:.2f}). "
            "Fichier vidéo potentiellement remplacé — à vérifier.",
        )
    if not state["nfo_ok"]:
        soft_ok = core_mod.nfo_soft_consistent(
            name_year=name_year,
            nfo_year=nfo.year,
            cov=state["nfo_cov"],
            seq=state["nfo_seq"],
        )
        if soft_ok:
            state["nfo_ok"] = True
            state["nfo_reject_reason"] = (
                f"NFO accepte en mode tolerant (cov={state['nfo_cov']:.2f}, "
                f"seq={state['nfo_seq']:.2f}, annee coherente)."
            )
            log("INFO", f"NFO soft-match accept {log_ctx} cov={state['nfo_cov']:.2f} seq={state['nfo_seq']:.2f}")
        else:
            log("WARN", f"NFO mismatch -> ignore {log_ctx} cov={state['nfo_cov']:.2f} seq={state['nfo_seq']:.2f}")

    if state["nfo_ok"]:
        reject_year, year_msg = core_mod.should_reject_nfo_year(
            cfg,
            name_year=name_year,
            nfo_year=nfo.year,
            remaster_hint=remaster_hint,
            cov=state["nfo_cov"],
            seq=state["nfo_seq"],
        )
        if reject_year:
            state["year_delta_reject"] = True
            log("WARN", f"NFO year reject {log_ctx}: nfo={nfo.year} name={name_year}")
            state["nfo_reject_reason"] = year_msg
        else:
            if year_msg:
                state["nfo_reject_reason"] = year_msg
                log("INFO", f"NFO year relax {log_ctx}: {year_msg}")
            nfo_cands = core_mod.build_candidates_from_nfo(nfo)

    return nfo_cands, state


# VN-D.2 (Vague N batch 3) : seuil sim_best en-deca duquel on tente le fetch
# TMDb alternative_titles (cross-langue FR/EN/JP/etc).
_ALT_TITLES_FETCH_THRESHOLD = 0.85


def _rescore_with_alternative_titles(
    sim_best: float,
    *,
    tmdb_id: int,
    folder_clean: str,
    video_clean: str,
    tmdb: Optional[TmdbClient],
) -> Tuple[float, Optional[str]]:
    """Re-score sim_best en utilisant les alternative_titles TMDb si necessaire.

    VN-D.2 : matching cross-langue. Si sim_best < 0.85, fetch les
    `alternative_titles` et re-calcule la similarite contre chacune. Permet
    d'identifier "Le Voyage de Chihiro" comme alias de "Spirited Away".
    Retourne (sim_best mis a jour, source `alt-{iso}` ou None).
    """
    if sim_best >= _ALT_TITLES_FETCH_THRESHOLD:
        return sim_best, None
    if tmdb is None or not hasattr(tmdb, "get_alternative_titles"):
        return sim_best, None
    if tmdb_id <= 0:
        return sim_best, None

    try:
        alternatives = tmdb.get_alternative_titles(tmdb_id) or []
    except (AttributeError, TypeError, ValueError) as exc:
        _log.debug("alt_titles: fetch failed tmdb_id=%d — %s", tmdb_id, exc)
        return sim_best, None

    if not alternatives:
        return sim_best, None

    best = float(sim_best)
    best_iso: Optional[str] = None
    for alt in alternatives:
        if not isinstance(alt, dict):
            continue
        alt_title = str(alt.get("title") or "").strip()
        if not alt_title:
            continue
        sim_f = core_mod._title_similarity(folder_clean, alt_title) if folder_clean else 0.0
        sim_v = core_mod._title_similarity(video_clean, alt_title) if video_clean else 0.0
        sim_alt = max(sim_f, sim_v)
        if sim_alt > best:
            best = sim_alt
            best_iso = str(alt.get("iso_3166_1") or "??").upper() or "??"

    if best_iso is not None:
        _log.info(
            "alt_titles: tmdb_id=%d rescued sim=%.2f -> %.2f via alt-%s",
            tmdb_id,
            sim_best,
            best,
            best_iso,
        )
    return best, (f"alt-{best_iso}" if best_iso else None)


def _augment_candidates_from_nfo_imdb(
    cfg: "Config",
    nfo: Optional[Any],
    nfo_cands: List[Any],
    folder_name: str,
    video_name: str,
    *,
    name_year: Optional[int],
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    log_ctx: str,
) -> None:
    """Cross-check NFO IMDb ID via TMDb find. Ajoute un candidat nfo_imdb si OK.

    BUG CRITIQUE : un NFO pollue (copie par erreur) peut pointer vers un IMDb ID
    d'un film totalement different. On verifie la similarite entre le titre
    retourne par TMDb et le nom du dossier/fichier AVANT d'accepter le candidat.
    """
    if not (nfo and getattr(nfo, "imdbid", None) and tmdb and cfg.enable_tmdb):
        return

    try:
        imdb_result = tmdb.find_by_imdb_id(nfo.imdbid)
        if not (imdb_result and imdb_result.id):
            return
        imdb_title = imdb_result.title or ""
        imdb_original = getattr(imdb_result, "original_title", "") or ""
        folder_clean = core_mod.clean_title_guess(folder_name) or folder_name
        video_clean = core_mod.clean_title_guess(video_name) or video_name
        sim_folder = max(
            core_mod._title_similarity(folder_clean, imdb_title),
            core_mod._title_similarity(folder_clean, imdb_original) if imdb_original else 0.0,
        )
        sim_video = max(
            core_mod._title_similarity(video_clean, imdb_title),
            core_mod._title_similarity(video_clean, imdb_original) if imdb_original else 0.0,
        )
        sim_best = max(sim_folder, sim_video)
        # VN-D.2 : alt_titles cross-langue si sim_best < 0.85.
        sim_best, alt_source = _rescore_with_alternative_titles(
            sim_best,
            tmdb_id=int(imdb_result.id or 0),
            folder_clean=folder_clean,
            video_clean=video_clean,
            tmdb=tmdb,
        )
        year_ok = True
        year_delta = None
        if name_year is not None and imdb_result.year:
            year_delta = abs(int(imdb_result.year) - int(name_year))
            if year_delta > 2:
                year_ok = False
        accept = (sim_best >= 0.50) or (year_ok and year_delta is not None and year_delta <= 1 and sim_best >= 0.35)
        if accept:
            note_extra = f" via {alt_source}" if alt_source else ""
            nfo_imdb_cand = core_mod.Candidate(
                title=imdb_result.title,
                year=imdb_result.year,
                source="nfo_imdb",
                tmdb_id=imdb_result.id,
                poster_url=core_mod.tmdb_poster_thumb_url(getattr(imdb_result, "poster_path", None)),
                score=0.95,
                note=f"IMDb lookup {nfo.imdbid} → tmdb:{imdb_result.id}, sim={sim_best:.2f}{note_extra}",
            )
            nfo_cands.append(nfo_imdb_cand)
            _log.info(
                "scan: .nfo IMDb %s → tmdb:%d '%s' (sim=%.2f)",
                nfo.imdbid,
                imdb_result.id,
                imdb_result.title,
                sim_best,
            )
        else:
            log(
                "WARN",
                f"NFO IMDb lookup rejete {log_ctx}: "
                f"titre TMDb '{imdb_title}' ne correspond pas au dossier "
                f"(sim={sim_best:.2f}, delta_annee={year_delta}). NFO probablement pollue.",
            )
            _log.warning(
                "scan: .nfo IMDb %s rejete (sim=%.2f year_delta=%s) tmdb='%s' folder='%s'",
                nfo.imdbid,
                sim_best,
                year_delta,
                imdb_title,
                folder_name,
            )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        _log.debug("scan: echec IMDb lookup %s — %s", nfo.imdbid, exc)


def _augment_candidates_from_nfo_tmdb_id(
    cfg: "Config",
    nfo: Optional[Any],
    nfo_cands: List[Any],
    folder_name: str,
    video_name: str,
    *,
    name_year: Optional[int],
    nfo_ok: bool,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    log_ctx: str,
) -> None:
    """Cross-check NFO TMDb ID (P1.1.c, symetrique a IMDb lookup).

    Un NFO pollué peut contenir <tmdbid>27205</tmdbid> pointant sur un film
    totalement différent. On vérifie la similarité titre TMDb officiel vs nom
    de dossier/fichier AVANT d'accepter.
    """
    if not (nfo and getattr(nfo, "tmdbid", None) and tmdb and cfg.enable_tmdb):
        return

    try:
        tmdb_result = tmdb.find_by_tmdb_id(nfo.tmdbid)
        if not (tmdb_result and tmdb_result.id):
            return
        tmdb_title = tmdb_result.title or ""
        tmdb_original = getattr(tmdb_result, "original_title", "") or ""
        folder_clean = core_mod.clean_title_guess(folder_name) or folder_name
        video_clean = core_mod.clean_title_guess(video_name) or video_name
        sim_folder = max(
            core_mod._title_similarity(folder_clean, tmdb_title),
            core_mod._title_similarity(folder_clean, tmdb_original) if tmdb_original else 0.0,
        )
        sim_video = max(
            core_mod._title_similarity(video_clean, tmdb_title),
            core_mod._title_similarity(video_clean, tmdb_original) if tmdb_original else 0.0,
        )
        sim_best = max(sim_folder, sim_video)
        sim_best, alt_source = _rescore_with_alternative_titles(
            sim_best,
            tmdb_id=int(tmdb_result.id or 0),
            folder_clean=folder_clean,
            video_clean=video_clean,
            tmdb=tmdb,
        )
        year_ok = True
        year_delta = None
        if name_year is not None and tmdb_result.year:
            year_delta = abs(int(tmdb_result.year) - int(name_year))
            if year_delta > 2:
                year_ok = False
        accept = (sim_best >= 0.50) or (year_ok and year_delta is not None and year_delta <= 1 and sim_best >= 0.35)
        if accept:
            # GAP-NFO-TMDBID : le candidat 'nfo' de base porte desormais l'id
            # brut du NFO (propagation sans reseau) — il ne doit PAS bloquer
            # l'ajout du candidat 'nfo_tmdb' VERIFIE (score 0.93 + poster).
            already_have = any(
                getattr(c, "tmdb_id", None) == tmdb_result.id and str(getattr(c, "source", "")) != "nfo"
                for c in nfo_cands
            )
            if not already_have:
                note_extra = f" via {alt_source}" if alt_source else ""
                nfo_tmdb_cand = core_mod.Candidate(
                    title=tmdb_result.title,
                    year=tmdb_result.year,
                    source="nfo_tmdb",
                    tmdb_id=tmdb_result.id,
                    poster_url=core_mod.tmdb_poster_thumb_url(getattr(tmdb_result, "poster_path", None)),
                    score=0.93,
                    note=f"TMDb ID {nfo.tmdbid} verifie, sim={sim_best:.2f}{note_extra}",
                )
                nfo_cands.append(nfo_tmdb_cand)
                _log.info(
                    "scan: .nfo TMDb %s -> '%s' (sim=%.2f)",
                    nfo.tmdbid,
                    tmdb_result.title,
                    sim_best,
                )
        else:
            # GAP-NFO-TMDBID : l'id NFO propage sans verification par
            # build_candidates_from_nfo est refute par le cross-check TMDb
            # (NFO pollue) -> on le retire du candidat 'nfo' de base.
            for c in nfo_cands:
                if str(getattr(c, "source", "")) == "nfo" and getattr(c, "tmdb_id", None) is not None:
                    c.tmdb_id = None
            log(
                "WARN",
                f"NFO TMDb ID rejete {log_ctx}: "
                f"titre TMDb '{tmdb_title}' ne correspond pas au dossier "
                f"(sim={sim_best:.2f}, delta_annee={year_delta}). NFO probablement pollue.",
            )
            _log.warning(
                "scan: .nfo TMDb %s rejete (sim=%.2f year_delta=%s) tmdb='%s' folder='%s'",
                nfo.tmdbid,
                sim_best,
                year_delta,
                tmdb_title,
                folder_name,
            )
            if not nfo_ok:
                pass
            else:
                log(
                    "WARN",
                    f"NFO incoherent {log_ctx}: titre NFO matche dossier mais TMDb ID pointe sur '{tmdb_title}'.",
                )
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        _log.debug("scan: echec TMDb ID lookup %s — %s", nfo.tmdbid, exc)


def _augment_candidates_from_name_tags(
    cfg: "Config",
    nfo_cands: List[Any],
    folder_name: str,
    video_name: str,
    *,
    name_year: Optional[int],
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    log_ctx: str,
) -> None:
    """B02-TAGS-BRACKETS : cross-check des tags providers extraits du NOM.

    Si un dossier/fichier porte `{tmdb-27205}` ou `[imdbid-tt1375666]`, on
    resout l'ID via TMDb et on l'ajoute aux candidats AVEC le meme garde-fou
    de similarite titre que `_augment_candidates_from_nfo_tmdb_id` (anti
    NFO/nom pollue).

    Symetrique aux helpers NFO existants. Source = "name_tmdb" / "name_imdb"
    pour distinguer dans les logs et les notes.
    """
    if not (tmdb and cfg.enable_tmdb):
        return

    tags_folder = extract_provider_tags(folder_name)
    tags_video = extract_provider_tags(video_name)
    # Si rien dans le nom, rien a faire.
    if not (tags_folder.has_any or tags_video.has_any):
        return

    # Folder tags priment sur file tags (le dossier est canon pour les films).
    tmdb_id_tag: Optional[int] = tags_folder.tmdb_id or tags_video.tmdb_id
    imdb_id_tag: Optional[str] = tags_folder.imdb_id or tags_video.imdb_id

    # --- Resolution via TMDb ID direct ---
    if tmdb_id_tag is not None:
        try:
            tmdb_result = tmdb.find_by_tmdb_id(tmdb_id_tag)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            _log.debug("scan: echec name-tag TMDb lookup %s — %s", tmdb_id_tag, exc)
            tmdb_result = None
        if tmdb_result and tmdb_result.id:
            _accept_name_tag_candidate(
                cfg,
                nfo_cands,
                result=tmdb_result,
                folder_name=folder_name,
                video_name=video_name,
                name_year=name_year,
                tmdb=tmdb,
                source="name_tmdb",
                origin_id=str(tmdb_id_tag),
                base_score=0.94,  # > nfo_tmdb (0.93) car le tag est cote nom (intentionnel utilisateur).
                log=log,
                log_ctx=log_ctx,
            )

    # --- Resolution via IMDb ID (si pas deja resolu via TMDb ID) ---
    if imdb_id_tag and not any(getattr(c, "source", "") == "name_tmdb" for c in nfo_cands):
        try:
            imdb_result = tmdb.find_by_imdb_id(imdb_id_tag)
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            _log.debug("scan: echec name-tag IMDb lookup %s — %s", imdb_id_tag, exc)
            imdb_result = None
        if imdb_result and imdb_result.id:
            _accept_name_tag_candidate(
                cfg,
                nfo_cands,
                result=imdb_result,
                folder_name=folder_name,
                video_name=video_name,
                name_year=name_year,
                tmdb=tmdb,
                source="name_imdb",
                origin_id=imdb_id_tag,
                base_score=0.94,
                log=log,
                log_ctx=log_ctx,
            )


def _accept_name_tag_candidate(
    cfg: "Config",
    nfo_cands: List[Any],
    *,
    result: Any,
    folder_name: str,
    video_name: str,
    name_year: Optional[int],
    tmdb: Optional[TmdbClient],
    source: str,
    origin_id: str,
    base_score: float,
    log: Callable[[str, str], None],
    log_ctx: str,
) -> None:
    """Garde-fou anti-pollution : verifie sim_titre >= 0.50 avant d'ajouter.

    Meme logique que `_augment_candidates_from_nfo_tmdb_id` mais sourcing
    explicit `name_tmdb`/`name_imdb`. Factorise pour eviter la duplication.
    """
    del cfg  # reserve future hooks
    title = result.title or ""
    original = getattr(result, "original_title", "") or ""
    folder_clean = core_mod.clean_title_guess(folder_name) or folder_name
    video_clean = core_mod.clean_title_guess(video_name) or video_name
    sim_folder = max(
        core_mod._title_similarity(folder_clean, title),
        core_mod._title_similarity(folder_clean, original) if original else 0.0,
    )
    sim_video = max(
        core_mod._title_similarity(video_clean, title),
        core_mod._title_similarity(video_clean, original) if original else 0.0,
    )
    sim_best = max(sim_folder, sim_video)
    sim_best, alt_source = _rescore_with_alternative_titles(
        sim_best,
        tmdb_id=int(result.id or 0),
        folder_clean=folder_clean,
        video_clean=video_clean,
        tmdb=tmdb,
    )
    year_ok = True
    year_delta: Optional[int] = None
    if name_year is not None and result.year:
        year_delta = abs(int(result.year) - int(name_year))
        if year_delta > 2:
            year_ok = False
    accept = (sim_best >= 0.50) or (year_ok and year_delta is not None and year_delta <= 1 and sim_best >= 0.35)
    if not accept:
        log(
            "WARN",
            f"Tag provider rejete {log_ctx}: {source}={origin_id} -> titre TMDb '{title}' "
            f"ne correspond pas au dossier (sim={sim_best:.2f}, delta_annee={year_delta}). "
            "Tag probablement copie/colle errone.",
        )
        _log.warning(
            "scan: name-tag %s %s rejete (sim=%.2f year_delta=%s) tmdb='%s' folder='%s'",
            source,
            origin_id,
            sim_best,
            year_delta,
            title,
            folder_name,
        )
        return

    # Eviter doublon si le meme tmdb_id est deja dans la liste (NFO ou name-tag).
    already_have = any(getattr(c, "tmdb_id", None) == result.id for c in nfo_cands)
    if already_have:
        _log.debug(
            "scan: name-tag %s %s deja present via NFO, skip ajout",
            source,
            origin_id,
        )
        return

    note_extra = f" via {alt_source}" if alt_source else ""
    cand = core_mod.Candidate(
        title=result.title,
        year=result.year,
        source=source,
        tmdb_id=result.id,
        poster_url=core_mod.tmdb_poster_thumb_url(getattr(result, "poster_path", None)),
        score=base_score,
        note=f"Tag {source} {origin_id} verifie, sim={sim_best:.2f}{note_extra}",
    )
    nfo_cands.append(cand)
    _log.info(
        "scan: name-tag %s %s -> tmdb:%d '%s' (sim=%.2f)",
        source,
        origin_id,
        result.id,
        result.title,
        sim_best,
    )


def _build_tmdb_fallback_candidates(
    cfg: "Config",
    folder_name: str,
    video_name: str,
    *,
    is_collection: bool,
    name_year: Optional[int],
    nfo_cands: List[Any],
    year_delta_reject: bool,
    tmdb: Optional[TmdbClient],
    should_cancel: Optional[Callable[[], bool]],
) -> Tuple[List[Any], bool]:
    """Lance le TMDb fallback si necessaire. Retourne (tmdb_cands, tmdb_used)."""

    if not (tmdb and cfg.enable_tmdb):
        return [], False

    need = (not nfo_cands) or year_delta_reject or (not name_year)
    if not need:
        return [], False

    if core_mod._is_cancel_requested(should_cancel):
        return [], False

    # Collection: prefer video name first; single: prefer folder name first.
    if is_collection:
        queries = [
            core_mod.clean_title_guess(strip_edition(video_name)),
            core_mod.clean_title_guess(strip_edition(folder_name)),
        ]
    else:
        queries = [
            core_mod.clean_title_guess(strip_edition(folder_name)),
            core_mod.clean_title_guess(strip_edition(video_name)),
        ]
    tmdb_cands = core_mod.build_candidates_from_tmdb_fallback(
        tmdb,
        queries=queries,
        year=name_year,
        language=cfg.tmdb_language,
        should_cancel=should_cancel,
    )
    return tmdb_cands, True


def _resolve_file_runtime_min(
    nfo: Optional[Any],
    folder: Path,
    video: Path,
    *,
    store: Any = None,
    settings: Optional[Dict[str, Any]] = None,
) -> Tuple[Optional[float], Optional[str]]:
    """Retrouve la duree fichier en minutes ET sa source (probe MESURE vs NFO DECLARE).

    H5 : la duree MESUREE par le probe fait autorite sur la duree DECLAREE par
    le NFO. Un NFO peut annoncer un autre cut que le fichier reellement present
    (ex. NFO theatrical 95 min sur un fichier Extended de 142 min) ; se fier au
    NFO ferait exclure a tort de bons candidats TMDb par le filtre HARD.

    1. Cache probe (duree reellement mesuree). Pas de probe fresh -- on ne
       declenche pas de ffprobe lourd au stade scoring, on lit seulement le
       cache si dispo.
    2. Repli : nfo.runtime (duree declaree, zero cout, deja parse).

    Retourne (minutes, source) ou source vaut :
        - "measured"  : duree issue du cache probe (MESUREE, fait autorite).
        - "declared"  : duree issue du NFO (DECLAREE, non-autoritaire -> le
          filtre HARD ne doit JAMAIS exclure durement sur cette base).
        - None        : aucune duree disponible (pas de cache probe ET pas de
          NFO) -> le filtre HARD se desactive pour cette ligne.
    """
    # 1. Duree MESUREE (cache probe) -- fait autorite sur le NFO declare.
    if store is not None and hasattr(store, "get_probe_cache"):
        try:
            media_path = Path(folder) / video.name if not isinstance(video, Path) else video
            if safe_path_exists(media_path):
                cached = store.get_probe_cache(str(media_path))
                normalized = cached.get("normalized") if isinstance(cached, dict) else None
                if isinstance(normalized, dict):
                    duration_s = normalized.get("duration_s")
                    if duration_s and float(duration_s) > 0:
                        return float(duration_s) / 60.0, "measured"
        except (AttributeError, KeyError, TypeError, ValueError, OSError):
            pass  # cache illisible -> repli sur le NFO
        _ = settings  # reserve pour un probe fresh eventuel (non declenche ici)
    # 2. Repli : duree DECLAREE par le NFO.
    if nfo is not None:
        runtime = getattr(nfo, "runtime", None)
        try:
            value = float(runtime) if runtime else 0.0
        except (TypeError, ValueError):
            value = 0.0
        if value > 0:
            return value, "declared"
    return None, None


def _apply_runtime_hard_filter_to_tmdb_cands(
    tmdb_cands: List[Any],
    *,
    file_runtime_min: Optional[float],
    detected_edition: Optional[str],
    tmdb: Optional[TmdbClient],
    settings: Optional[Dict[str, Any]],
    log: Callable[[str, str], None],
    log_ctx: str = "",
    runtime_source: Optional[str] = None,
) -> Tuple[List[Any], bool]:
    """Filtre HARD : exclut les candidats TMDb dont la duree diverge trop.

    - delta > threshold sans edition flag, duree MESUREE (probe) -> EXCLU
    - delta > threshold AVEC edition flag -> conserve + warning
    - delta > threshold sans edition flag, duree DECLAREE (NFO) -> conserve +
      warning (H5 : une duree declaree n'a pas autorite pour exclure)
    - delta <= threshold -> conserve sans modification

    Args:
        runtime_source: "measured" (probe) ou "declared" (NFO), tel que retourne
            par `_resolve_file_runtime_min`. None ou "measured" -> la mesure fait
            autorite (comportement historique : exclusion dure). "declared" ->
            jamais d'exclusion dure, seulement un warning reconcilie par le probe.

    Retourne (kept_tmdb_cands, any_excluded).
    """
    runtime_measured = runtime_source != "declared"
    if not tmdb_cands or tmdb is None:
        return tmdb_cands, False

    settings = settings or {}
    enabled = bool(settings.get("runtime_hard_filter_enabled", True))
    if not enabled:
        return tmdb_cands, False
    try:
        threshold = int(settings.get("runtime_hard_threshold_min", DEFAULT_RUNTIME_HARD_THRESHOLD_MIN))
    except (TypeError, ValueError):
        threshold = DEFAULT_RUNTIME_HARD_THRESHOLD_MIN
    if threshold <= 0:
        return tmdb_cands, False

    if file_runtime_min is None or float(file_runtime_min) <= 0:
        return tmdb_cands, False

    kept: List[Any] = []
    any_excluded = False
    for cand in tmdb_cands:
        cand_tmdb_id = getattr(cand, "tmdb_id", None)
        if not cand_tmdb_id:
            kept.append(cand)
            continue
        try:
            cand_runtime = tmdb.get_movie_runtime(int(cand_tmdb_id))
        except (AttributeError, TypeError, ValueError):
            cand_runtime = None

        excluded, warning = evaluate_runtime_hard_filter(
            file_runtime_min=file_runtime_min,
            candidate_runtime_min=cand_runtime,
            edition_label=detected_edition,
            enabled=True,
            threshold_min=threshold,
            runtime_measured=runtime_measured,
        )
        if excluded:
            any_excluded = True
            delta = abs(float(file_runtime_min) - float(cand_runtime)) if cand_runtime is not None else None
            delta_str = f"{delta:.0f}" if delta is not None else "?"
            log(
                "INFO",
                f"VN-D.3 runtime HARD filter{(' ' + log_ctx) if log_ctx else ''}: "
                f"candidat exclu (tmdb_id={cand_tmdb_id}, titre={cand.title!r}, "
                f"runtime TMDb={cand_runtime} min, fichier={float(file_runtime_min):.0f} min, "
                f"delta={delta_str} min > seuil {threshold} min, pas d'edition flag)",
            )
            continue
        if warning:
            existing_note = getattr(cand, "note", "") or ""
            if warning not in existing_note:
                with contextlib.suppress(AttributeError, TypeError):
                    cand.note = (existing_note + f" [{warning}]").strip()
            if warning == WARN_RUNTIME_HARD_KEPT_DECLARED:
                reason = "duree DECLAREE (NFO) non-autoritaire, reconciliation probe attendue"
            else:
                reason = f"grace a edition flag {detected_edition!r}"
            log(
                "WARN",
                f"VN-D.3 runtime HARD filter{(' ' + log_ctx) if log_ctx else ''}: "
                f"candidat conserve ({reason}) "
                f"(tmdb_id={cand_tmdb_id}, titre={cand.title!r}, "
                f"runtime TMDb={cand_runtime} min, fichier={float(file_runtime_min):.0f} min)",
            )
        kept.append(cand)
    return kept, any_excluded


# =========================================================
# MULTI-ROOT SUPPORT
# =========================================================


def _merge_stats(target: "Stats", source: "Stats") -> None:
    """Additionne les compteurs de *source* dans *target* (in-place)."""
    for f in dc_fields(target):
        val = getattr(source, f.name)
        if isinstance(val, int):
            setattr(target, f.name, getattr(target, f.name) + val)
        elif isinstance(val, dict):
            merged = dict(getattr(target, f.name))
            for k, v in val.items():
                merged[k] = merged.get(k, 0) + int(v)
            setattr(target, f.name, merged)


def _detect_cross_root_duplicates(rows: List["PlanRow"]) -> int:
    """Detecte les doublons cross-root et ajoute un warning_flag. Retourne le nombre de doublons."""
    by_key: Dict[Tuple[str, int], List["PlanRow"]] = defaultdict(list)
    for row in rows:
        key = (str(row.proposed_title or "").strip().lower(), int(row.proposed_year or 0))
        if key[0]:
            by_key[key].append(row)

    dup_count = 0
    for key, group in by_key.items():
        roots_seen = {r.source_root for r in group if r.source_root}
        if len(roots_seen) < 2:
            continue
        for row in group:
            if "duplicate_cross_root" not in (row.warning_flags or []):
                if row.warning_flags is None:
                    row.warning_flags = []
                row.warning_flags.append("duplicate_cross_root")
                other_roots = [r for r in roots_seen if r != row.source_root]
                if other_roots:
                    row.notes = (row.notes or "") + f" | Aussi dans: {', '.join(other_roots)}"
                dup_count += 1
    return dup_count


def plan_multi_roots(
    roots: List[Path],
    *,
    build_cfg: Callable[[Path], "Config"],
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    progress: Callable[[int, int, str], None],
    should_cancel: Optional[Callable[[], bool]] = None,
    should_pause: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    run_id: str = "",
    subtitle_expected_languages: Optional[List[str]] = None,
) -> Tuple[List["PlanRow"], "Stats"]:
    """Scanne plusieurs roots sequentiellement et merge les resultats.

    - Chaque root est scanne via plan_library() avec son propre Config
    - Les rows recus sont annotes avec source_root
    - Les Stats sont additionnees
    - Les doublons cross-root sont detectes (warning_flag)
    - Un root inaccessible est skip avec un warning (pas d'erreur fatale)
    """
    # Import paresseux : plan_library vit dans plan_support_core qui n'a pas
    # de dependance circulaire sur ce module mais on garde le lazy pour eviter
    # un import-at-load-time inutile cote ui/api.
    from cinesort.app.plan_support_core import plan_library

    all_rows: List[core_mod.PlanRow] = []
    all_stats = core_mod.Stats()
    accessible_count = 0
    skipped_roots: List[str] = []

    for i, root in enumerate(roots):
        if should_cancel and should_cancel():
            log("WARN", "Analyse annulee.")
            break

        root_label = f"Root {i + 1}/{len(roots)}"
        # M-1 audit QA 20260429 : detection NAS debranche via timeout 10s.
        exists = safe_path_exists(root, timeout_s=10.0)
        if exists is None:
            log("WARN", f"{root_label} : {root} inaccessible apres 10s (NAS debranche ?), skip.")
            skipped_roots.append(str(root))
            continue
        if not exists:
            log("WARN", f"{root_label} : {root} inaccessible, skip.")
            skipped_roots.append(str(root))
            continue
        if not is_dir_accessible(root, timeout_s=5.0):
            log("WARN", f"{root_label} : {root} n'est pas un dossier accessible, skip.")
            skipped_roots.append(str(root))
            continue

        accessible_count += 1
        log("INFO", f"=== {root_label} : {root} ===")

        cfg = build_cfg(root)

        def multi_progress(idx: int, total: int, current: str, _root_label: str = root_label) -> None:
            progress(idx, total, f"[{_root_label}] {current}")

        rows_i, stats_i = plan_library(
            cfg,
            tmdb=tmdb,
            log=log,
            progress=multi_progress,
            should_cancel=should_cancel,
            should_pause=should_pause,
            scan_index=scan_index,
            run_id=run_id,
            subtitle_expected_languages=subtitle_expected_languages,
        )

        for row in rows_i:
            row.source_root = str(root)

        all_rows.extend(rows_i)
        _merge_stats(all_stats, stats_i)

    if len(roots) > 1:
        dup_count = _detect_cross_root_duplicates(all_rows)
        if dup_count > 0:
            log("INFO", f"Doublons cross-root detectes : {dup_count} film(s)")
        if skipped_roots:
            log("WARN", f"{len(skipped_roots)}/{len(roots)} root(s) inaccessible(s) : {', '.join(skipped_roots)}")
        log("INFO", f"Multi-root : {accessible_count}/{len(roots)} root(s) scannes, {len(all_rows)} film(s) total")

    return all_rows, all_stats


# ---------------------------------------------------------------------------
# Cf #83 etape 2 PR 4b : find_duplicate_targets COTE APP avec DI complete.
# ---------------------------------------------------------------------------


def find_duplicate_targets(
    cfg: "Config",
    rows: List["PlanRow"],
    decisions: Dict[str, Dict[str, object]],
    *,
    max_groups: int = 120,
) -> Dict[str, object]:
    """Detecte les groupes de doublons sur les destinations planifiees (#83 PR 4b).

    Pre-remplit les 7 helpers DI vers `domain.duplicate_support.find_duplicate_targets`.
    Tous les helpers viennent de :
    - `cinesort.app.apply_core` (is_managed_merge_file, files_identical_quick)
    - `cinesort.domain.duplicate_support` (movie_dir_title_year, movie_key,
      existing_movie_folder_index, planned_target_folder, is_under_collection_root,
      can_merge_single/collection_item_without_blocking, find_video_case_insensitive)
    - `cinesort.domain.core` (windows_safe, _norm_win_path, classify_sidecars
      pour le sub-helper)
    - `cinesort.domain.title_helpers` (_norm_for_tokens)
    """
    _apply_core = _apply_core_mod
    _norm_win_path = core_mod._norm_win_path
    classify_sidecars = core_mod.classify_sidecars
    windows_safe = core_mod.windows_safe

    def _movie_key(title: str, year: int, edition: Optional[str] = None) -> str:
        return _dup.movie_key(title, year, norm_for_tokens=_norm_for_tokens, edition=edition)

    def _existing_movie_folder_index(cfg_: Any) -> Dict[str, List[str]]:
        return _dup.existing_movie_folder_index(
            cfg_,
            movie_dir_title_year=_dup.movie_dir_title_year,
            movie_key=_movie_key,
        )

    def _is_under_collection_root(cfg_: Any, folder: Path) -> bool:
        return _dup.is_under_collection_root(cfg_, folder, norm_win_path=_norm_win_path)

    def _planned_target_folder(cfg_: Any, row: Any, title: str, year: int) -> Path:
        return _dup.planned_target_folder(
            cfg_,
            row,
            title,
            year,
            is_under_collection_root=_is_under_collection_root,
            windows_safe=windows_safe,
        )

    def _can_merge_single(cfg_: Any, src_dir: Path, dst_dir: Path) -> Tuple[bool, str]:
        return _dup.can_merge_single_without_blocking(
            cfg_,
            src_dir,
            dst_dir,
            is_managed_merge_file=_apply_core.is_managed_merge_file,
            files_identical_quick=_apply_core.files_identical_quick,
        )

    def _can_merge_collection_item(cfg_: Any, row: Any, target_dir: Path) -> Tuple[bool, str]:
        return _dup.can_merge_collection_item_without_blocking(
            cfg_,
            row,
            target_dir,
            find_video_case_insensitive=_dup.find_video_case_insensitive,
            classify_sidecars=lambda cfg_arg, folder_arg, video_arg: classify_sidecars(
                cfg_arg, folder_arg, video_arg, is_collection=True
            ),
            files_identical_quick=_apply_core.files_identical_quick,
        )

    return _dup.find_duplicate_targets(
        cfg.normalized() if hasattr(cfg, "normalized") else cfg,
        rows,
        decisions,
        max_groups=max_groups,
        existing_movie_folder_index=_existing_movie_folder_index,
        movie_key=_movie_key,
        planned_target_folder=_planned_target_folder,
        norm_win_path=_norm_win_path,
        can_merge_single_without_blocking=_can_merge_single,
        can_merge_collection_item_without_blocking=_can_merge_collection_item,
        windows_safe=windows_safe,
    )

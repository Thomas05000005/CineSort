"""Single-row planning pipeline (VP-E refactor, sous-lot VP-6).

Construit une `PlanRow` pour un fichier video (`_plan_item`) et ses variantes
publiques `_plan_single`, `_plan_collection_item`, `replan_single_row` ainsi
que le pipeline TV `_plan_tv_episode`. Le pipeline NFO/TMDb/runtime de scoring
des candidats vit dans `plan_support_dedup.py` ; les helpers de cache et de
serialisation viennent de `plan_support_core.py`.
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Tuple

import cinesort.domain.core as core_mod
from cinesort.app.plan_support_core import (
    _apply_year_missing_flag,
    _nfo_signature,
    _resolve_path_cached,
    plan_row_from_jsonable,
    plan_row_to_jsonable,
    resolve_incremental_quick_hash,
)
from cinesort.domain.edition_helpers import extract_edition
from cinesort.domain.integrity_check import check_header
from cinesort.domain.runtime_matching import score_runtime_delta
from cinesort.domain.scan_helpers import _NOT_A_MOVIE_THRESHOLD, not_a_movie_score
from cinesort.domain.subtitle_helpers import build_subtitle_report
from cinesort.domain.title_helpers import strip_provider_tags
from cinesort.domain.tv_helpers import parse_tv_info
from cinesort.infra.tmdb_client import TmdbClient

if TYPE_CHECKING:
    from cinesort.domain.core import Config, PlanRow

_log = logging.getLogger(__name__)


def _compute_row_id(prefix: str, folder: Path, video_name: str) -> str:
    """Identifiant stable d'une ligne de plan (`prefix|<64 bits hex>`).

    Le `row_id` sert de cle aux operations DESTRUCTIVES (deplacement des films
    marques pour suppression, losers de doublons, decisions d'apply) : il doit
    etre deterministe et assez large pour rendre les collisions negligeables.

    L'implementation precedente, `hash((str(folder), video.name)) & 0xFFFFFFFF`,
    etait randomisee par PYTHONHASHSEED et tronquee a 32 bits : ~0,3 % de
    collision anniversaire sur 5 000 films, re-tiree a chaque scan. Une collision
    fait resoudre un row_id marque vers le MAUVAIS PlanRow (les tables `by_row`
    d'apply_core sont construites en last-wins) -> un film jamais marque sort de
    la bibliotheque. blake2b/64 bits ramene cette probabilite a ~7e-13.
    """
    key = f"{folder}\x00{video_name}".encode("utf-8", "surrogatepass")
    return f"{prefix}|{hashlib.blake2b(key, digest_size=8).hexdigest()}"


def _try_lookup_row_cache(
    cfg: "Config",
    folder: Path,
    video: Path,
    *,
    kind: str,
    cfg_sig: str,
    scan_index: Optional[Any],
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]],
    row_cache_stats: Optional[Dict[str, int]],
) -> Optional["PlanRow"]:
    """Tente un hit dans le cache row v2. Retourne la PlanRow cachee ou None.

    Met a jour row_cache_stats (row_hits / row_misses) en place.

    AUDIT 2026-06-11 (R3e, gap[2]) : la cle de cache est (root_path, video_path,
    cfg_sig) SANS kind, mais un meme fichier bascule single<->collection quand on
    ajoute/retire une 2e video au dossier (les octets/NFO ne changent pas). Sans
    comparer `kind`, le check de validite passait et renvoyait la row stale du
    MAUVAIS kind (row_id prefix S vs C, collection_name, semantique de rename
    divergents). On compare donc le kind stocke au kind demande.
    """
    if not (cfg_sig and scan_index is not None and hasattr(scan_index, "get_incremental_row_cache")):
        return None

    try:
        video_stat = video.stat()
        v_size = int(video_stat.st_size)
        v_mtime = int(video_stat.st_mtime_ns)
        v_hash = resolve_incremental_quick_hash(
            video,
            scan_index=scan_index,
            run_hash_cache=run_hash_cache or {},
        )
        nfo_path_for_sig = core_mod.find_best_nfo_for_video(folder, video)
        nfo_sig = _nfo_signature(nfo_path_for_sig)

        cached = scan_index.get_incremental_row_cache(
            root_path=str(cfg.root),
            video_path=str(video),
            cfg_sig=cfg_sig,
        )
        if cached is not None:
            if (
                int(cached.get("video_size") or 0) == v_size
                and int(cached.get("video_mtime_ns") or 0) == v_mtime
                and str(cached.get("video_hash") or "") == v_hash
                and cached.get("nfo_sig") == nfo_sig
                and str(cached.get("kind") or "single") == str(kind or "single")
            ):
                row_obj = plan_row_from_jsonable(cached.get("row_json") or {})
                if row_obj is not None:
                    if row_cache_stats is not None:
                        row_cache_stats["row_hits"] = row_cache_stats.get("row_hits", 0) + 1
                    return row_obj
        if row_cache_stats is not None:
            row_cache_stats["row_misses"] = row_cache_stats.get("row_misses", 0) + 1
    except (FileNotFoundError, PermissionError, OSError):
        pass
    return None


def _resolve_folder_context(
    cfg: "Config",
    folder: Path,
    video: Path,
    *,
    is_collection: bool,
    cfg_root_resolved: Optional[Path] = None,
) -> Tuple[str, str, Optional[str]]:
    """Calcule folder_name, log_ctx et l'edition detectee pour cet item.

    PERF-2 (v7.8.0) : `cfg_root_resolved` est pre-calcule par l'appelant pour
    eviter `cfg.root.resolve()` par film (5-15ms SMB). Fallback transparent
    si non fourni.
    """
    # Pour un film pose directement a la racine, le "folder_name" serait la racine
    # elle-meme (ex: "Films" ou "D:\"), qui ne porte aucune info de titre. On se
    # rabat sur le stem du fichier video pour que l'extraction titre/annee et la
    # construction des candidats marchent comme pour un dossier film classique.
    if cfg_root_resolved is None:
        cfg_root_resolved_str = _resolve_path_cached(str(cfg.root))
    else:
        cfg_root_resolved_str = str(cfg_root_resolved)
    folder_resolved_str = _resolve_path_cached(str(folder))
    _folder_is_root = folder_resolved_str == cfg_root_resolved_str
    folder_name = Path(video.name).stem if _folder_is_root else folder.name
    log_ctx = f"(collection): {folder_name}/{video.name}" if is_collection else f"({folder_name})"

    detected_edition = extract_edition(folder_name) or extract_edition(video.name)
    return folder_name, log_ctx, detected_edition


def _disambiguate_candidates(
    cands: List[Any],
    *,
    nfo: Optional[Any],
    name_year: Optional[int],
    log: Callable[[str, str], None],
    log_ctx: str,
) -> Tuple[List[Any], bool]:
    """Desambiguise par contexte (P2.2) si plusieurs films partagent le titre.

    Retourne (cands_ajustes, title_ambiguous). Modifie les scores uniquement si
    ambiguite detectee (ex : Dune 1984 vs 2021).
    """
    from cinesort.domain.title_ambiguity import disambiguate_by_context

    ambig_context = {
        "name_year": name_year,
        "nfo_tmdb_id": (
            int(nfo.tmdbid) if nfo and getattr(nfo, "tmdbid", None) and str(nfo.tmdbid).strip().isdigit() else None
        ),
        "nfo_runtime": getattr(nfo, "runtime", None) if nfo else None,
    }
    cands, title_ambiguous, ambig_title = disambiguate_by_context(cands, ambig_context)
    if title_ambiguous:
        log(
            "WARN",
            f"Titres TMDb ambigus {log_ctx}: {ambig_title!r} existe dans plusieurs années. "
            "Désambiguïsation sur contexte.",
        )
    return cands, title_ambiguous


def _build_unresolved_row(
    folder: Path,
    video: Path,
    *,
    row_id: str,
    kind: str,
    is_collection: bool,
    folder_name: str,
    cands: List[Any],
    nfo: Optional[Any],
    nfo_path: Optional[Path],
    nfo_state: Dict[str, Any],
    name_year: Optional[int],
    name_year_reason: str,
    remaster_hint: bool,
    tmdb_used: bool,
    title_ambiguous: bool,
    detected_edition: Optional[str],
    log: Callable[[str, str], None],
) -> "PlanRow":
    """Construit une PlanRow pour le cas ou aucun candidat fiable n'a ete trouve."""

    if not is_collection:
        log("WARN", f"Cannot resolve single: {folder_name}")
    note = core_mod.build_plan_note(
        confidence=0,
        label="low",
        chosen=None,
        name_year=name_year,
        name_year_reason=name_year_reason,
        remaster_hint=remaster_hint,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        nfo_cov=nfo_state["nfo_cov"],
        nfo_seq=nfo_state["nfo_seq"],
        nfo_reject_reason=nfo_state["nfo_reject_reason"],
        tmdb_used=tmdb_used,
    )
    warning_flags = core_mod._warning_flags_from_analysis(
        chosen=None,
        name_year_reason=name_year_reason,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        nfo_partial_match=nfo_state["nfo_partial_match"],
        title_ambiguity=title_ambiguous,
    )
    # Alerte "Annee introuvable" DETERMINISTE au plan : proposed_year = name_year or 0.
    _apply_year_missing_flag(warning_flags, name_year or 0)
    note = f"{note} Impossible de determiner un titre+annee fiables."
    # F02 (revue adversaire R1) : le repli sur le nom de dossier BRUT laissait
    # fuiter les tags providers ("Avatar {tmdb-19995}") dans proposed_title, donc
    # dans la cle d'identite/dedup ET dans le nom de dossier propose a l'apply.
    # Cette voie est devenue nominale depuis que l'annee n'est plus extraite des
    # chiffres d'un tag : sans annee fiable, la row bascule ici.
    fallback_title = (
        (core_mod.clean_title_guess(video.name) or video.stem)
        if is_collection
        else (strip_provider_tags(folder_name).strip() or folder_name)
    )
    return core_mod.PlanRow(
        row_id=row_id,
        kind=kind,
        folder=str(folder),
        video=video.name,
        proposed_title=fallback_title,
        proposed_year=name_year or 0,
        proposed_source="unknown",
        confidence=0,
        confidence_label="low",
        candidates=cands,
        nfo_path=str(nfo_path) if nfo_path else None,
        notes=note,
        detected_year=int(name_year or 0),
        detected_year_reason=str(name_year_reason or ""),
        warning_flags=warning_flags,
        collection_name=folder.name if is_collection else None,
        edition=detected_edition,
        nfo_runtime=nfo.runtime if nfo else None,
    )


def _resolve_tmdb_collection(
    cfg: "Config",
    chosen: Any,
    folder_name: str,
    *,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
) -> Tuple[Optional[int], Optional[str]]:
    """Retourne (collection_id, collection_name) si fiable, sinon (None, None).

    FIX 6 : la collection doit partager au moins un mot significatif avec le
    nom du dossier source OU avec le titre du candidat. Sinon le collection
    boost est toxique (ex: 'Ca' -> Pirates des Caraibes).
    """
    import contextlib

    if not (tmdb is not None and chosen.tmdb_id):
        return None, None
    coll_id: Optional[int] = None
    coll_name: Optional[str] = None
    with contextlib.suppress(KeyError, TypeError, ValueError):
        coll_id, coll_name = tmdb.get_movie_collection(chosen.tmdb_id)
    if not coll_name:
        return coll_id, coll_name
    coll_tokens = {t for t in core_mod.tokens(coll_name) if len(t) >= 3}
    folder_tokens = set(core_mod.tokens(folder_name))
    title_tokens = set(core_mod.tokens(chosen.title or ""))
    if coll_tokens and not (coll_tokens & folder_tokens) and not (coll_tokens & title_tokens):
        _log.warning(
            "scan: collection TMDb '%s' rejetee (pas de mot commun avec dossier='%s' ni titre='%s')",
            coll_name,
            folder_name,
            chosen.title,
        )
        log(
            "WARN",
            f"Collection '{coll_name}' ignoree pour '{folder_name}' (aucun mot commun avec le nom source).",
        )
        return None, None
    return coll_id, coll_name


def _build_resolved_row(
    cfg: "Config",
    folder: Path,
    video: Path,
    chosen: Any,
    *,
    row_id: str,
    kind: str,
    is_collection: bool,
    folder_name: str,
    cands: List[Any],
    nfo: Optional[Any],
    nfo_path: Optional[Path],
    nfo_state: Dict[str, Any],
    name_year: Optional[int],
    name_year_reason: str,
    remaster_hint: bool,
    tmdb_used: bool,
    title_ambiguous: bool,
    detected_edition: Optional[str],
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
) -> "PlanRow":
    """Construit une PlanRow pour le cas ou un candidat fiable a ete choisi."""

    confidence, label = core_mod.compute_confidence(
        cfg,
        chosen,
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        tmdb_used=tmdb_used,
        nfo_partial_match=nfo_state["nfo_partial_match"],
    )
    proposed_title = core_mod.windows_safe(chosen.title)
    # BUG 3 : si le dossier courant est deja conforme (meme titre + annee que
    # le candidat), la confiance doit etre HIGH — aucune action ne sera prise
    # meme si la similarite textuelle TMDb < 0.60.
    is_already_conform = False
    if not is_collection and chosen.year:
        try:
            is_already_conform = core_mod._single_folder_is_conform(
                folder_name,
                chosen.title,
                int(chosen.year),
                naming_template=str(getattr(cfg, "naming_movie_template", "") or ""),
            )
        except (TypeError, ValueError, AttributeError):
            is_already_conform = False
    if is_already_conform and confidence < 85:
        confidence = 90
        label = "high"
    # Phase 6.1 : runtime cross-check NFO vs TMDb, edition-aware.
    # H5 : ici on n'a PAS acces au store/cache probe (pas de duree MESUREE au
    # stade scan), donc on score sur la duree DECLAREE par le NFO. Un NFO
    # annoncant un autre cut peut poser un runtime_mismatch a tort -- ce FAUX
    # positif est reconcilie post-plan par cross_check_rows_with_probe (Phase
    # 6.1.b), qui, lui, dispose du probe (duree reelle) et retire le flag si le
    # fichier colle a TMDb. Ne PAS supprimer ce flag ici : il reste la seule
    # couverture pour les fichiers dont le probe echoue en aval.
    runtime_warning: Optional[str] = None
    if nfo is not None and getattr(nfo, "runtime", None) and tmdb is not None and chosen.tmdb_id:
        try:
            tmdb_runtime = tmdb.get_movie_runtime(int(chosen.tmdb_id))
        except (AttributeError, TypeError, ValueError):
            tmdb_runtime = None
        if tmdb_runtime:
            bonus, runtime_warning = score_runtime_delta(
                file_runtime_min=float(nfo.runtime),
                tmdb_runtime_min=tmdb_runtime,
                edition_label=detected_edition,
            )
            confidence = max(0, min(100, confidence + bonus))
            if bonus >= 10:
                label = "high" if confidence >= 85 else label
            elif bonus < 0:
                label = "low" if confidence < 60 else label
    note = core_mod.build_plan_note(
        confidence=confidence,
        label=label,
        chosen=chosen,
        name_year=name_year,
        name_year_reason=name_year_reason,
        remaster_hint=remaster_hint,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        nfo_cov=nfo_state["nfo_cov"],
        nfo_seq=nfo_state["nfo_seq"],
        nfo_reject_reason=nfo_state["nfo_reject_reason"],
        tmdb_used=tmdb_used,
    )
    warning_flags = core_mod._warning_flags_from_analysis(
        chosen=chosen,
        name_year_reason=name_year_reason,
        nfo_present=bool(nfo),
        nfo_ok=nfo_state["nfo_ok"],
        year_delta_reject=nfo_state["year_delta_reject"],
        nfo_partial_match=nfo_state["nfo_partial_match"],
        title_ambiguity=title_ambiguous,
    )
    if runtime_warning and runtime_warning not in warning_flags:
        warning_flags.append(runtime_warning)
    # Alerte "Annee introuvable" DETERMINISTE au plan : proposed_year = int(chosen.year).
    _apply_year_missing_flag(warning_flags, int(chosen.year))
    coll_id, coll_name = _resolve_tmdb_collection(cfg, chosen, folder_name, tmdb=tmdb, log=log)
    return core_mod.PlanRow(
        row_id=row_id,
        kind=kind,
        folder=str(folder),
        video=video.name,
        proposed_title=proposed_title,
        proposed_year=int(chosen.year),
        proposed_source=chosen.source,
        confidence=confidence,
        confidence_label=label,
        candidates=cands,
        nfo_path=str(nfo_path) if nfo_path else None,
        notes=note,
        detected_year=int(name_year or 0),
        detected_year_reason=str(name_year_reason or ""),
        warning_flags=warning_flags,
        collection_name=folder.name if is_collection else None,
        tmdb_collection_id=coll_id,
        tmdb_collection_name=coll_name,
        edition=detected_edition,
        nfo_runtime=nfo.runtime if nfo else None,
    )


def _apply_subtitle_detection(
    folder: Path,
    video: Path,
    result_row: "PlanRow",
    *,
    subtitle_expected_languages: Optional[List[str]],
    normalized_probe: Optional[Dict[str, Any]] = None,
) -> None:
    """Enrichit la PlanRow avec les infos sous-titres + warning flags associes.

    Fix Vague F 2026-05-25 (v1.5.3) : si un `normalized_probe` est fourni
    (NormalizedProbe.to_dict() ou dict equivalent), ses pistes `subtitles`
    embarquees sont prises en compte -> plus de faux "subtitle_missing_fr"
    pour les MKV avec FR embarque.
    """
    if subtitle_expected_languages is None:
        return

    embedded_subs: Optional[List[Dict[str, Any]]] = None
    if isinstance(normalized_probe, dict):
        raw_subs = normalized_probe.get("subtitles")
        if isinstance(raw_subs, list):
            embedded_subs = raw_subs

    sub_report = build_subtitle_report(
        folder,
        video,
        subtitle_expected_languages,
        embedded_subtitles=embedded_subs,
    )
    result_row.subtitle_count = sub_report.count
    result_row.subtitle_languages = list(sub_report.languages)
    result_row.subtitle_formats = list(sub_report.formats)
    result_row.subtitle_missing_langs = list(sub_report.missing_languages)
    result_row.subtitle_orphans = sub_report.orphans
    for missing_lang in sub_report.missing_languages:
        flag = f"subtitle_missing_{missing_lang}"
        if flag not in result_row.warning_flags:
            result_row.warning_flags.append(flag)
    # F12 / arbitrage produit tranche le 2026-08-03 : langue attendue couverte
    # UNIQUEMENT par une piste forcee (= incrustations, pas de traduction des
    # dialogues). Flag DISTINCT de `subtitle_missing_<lang>` : la langue est bel
    # et bien detectee, donc un flag `missing` serait efface par les
    # reconciliations de lecture (run_read_support / duplicate_support /
    # library_support / dashboard_support). Voir subtitle_helpers.
    for forced_lang in sub_report.forced_only_languages:
        flag = f"subtitle_forced_only_{forced_lang}"
        if flag not in result_row.warning_flags:
            result_row.warning_flags.append(flag)
    if sub_report.orphans > 0 and "subtitle_orphan" not in result_row.warning_flags:
        result_row.warning_flags.append("subtitle_orphan")
    if sub_report.duplicate_languages and "subtitle_duplicate_lang" not in result_row.warning_flags:
        result_row.warning_flags.append("subtitle_duplicate_lang")


# F09 (revue post-merge 2026-07-18) : flags DERIVES du rapport sous-titres, en
# plus du prefixe `subtitle_missing_*`. Recenses par grep exhaustif : seul
# _apply_subtitle_detection (juste au-dessus) les POSE au stade plan ; les
# consommateurs aval (run_read_support, duplicate_support, history_support) ne
# font qu'en RETIRER a la lecture. La purge de refresh est donc bornee a ces 3
# familles et ne peut pas effacer le flag d'un autre producteur.
_SUBTITLE_DERIVED_FLAGS = frozenset({"subtitle_orphan", "subtitle_duplicate_lang"})

# F09 / revue adverse : flags que le chemin de SCAN A FROID pose APRES les flags
# sous-titres (_plan_item : _apply_subtitle_detection puis _apply_not_a_movie_detection
# puis _apply_integrity_check). Ils servent d'ancre pour reinserer les flags
# recalcules a leur position d'origine : sans cela une meme row n'a pas la meme
# serialisation selon qu'elle vient du cache row ou d'un scan a froid
# (plan.jsonl non idempotent, chips d'alerte dans un ordre different — le
# dashboard fait un '|'.join sans tri).
_POST_SUBTITLE_FLAGS = ("not_a_movie", "integrity_header_invalid")


def _is_subtitle_flag(flag: Any) -> bool:
    """True pour les flags produits par `_apply_subtitle_detection`.

    `subtitle_forced_only_*` (F12, 2026-08-03) DOIT y figurer : sans lui, un
    flag perime resterait colle a une row servie par le cache row v2 exactement
    comme le `subtitle_missing_*` de F09 (l'utilisateur remplace son
    '.fr.forced.srt' par un '.fr.srt' complet, l'alerte ne part jamais).
    """
    text = str(flag)
    return text.startswith(("subtitle_missing_", "subtitle_forced_only_")) or text in _SUBTITLE_DERIVED_FLAGS


def _refresh_subtitle_detection(
    folder: Path,
    video: Path,
    cached_row: "PlanRow",
    *,
    subtitle_expected_languages: Optional[List[str]],
) -> None:
    """Recalcule les infos sous-titres d'une row servie par le cache row v2.

    F09 : la cle de validite du cache row (taille/mtime/hash video + nfo_sig +
    kind + cfg_sig) ne reflete AUCUN fichier .srt voisin. Ajouter ou retirer un
    sous-titre externe laissait donc la row cachee avec ses anciens
    `subtitle_missing_*` / `subtitle_languages` — et persist_folder_cache
    refigeait ensuite cette row perimee sous la nouvelle folder_sig, rendant la
    staleness PERMANENTE.

    On ne touche PAS a la cle du cache (cela forcerait un recalcul NFO/TMDb
    complet, donc du reseau, pour un simple .srt ajoute) : on recalcule
    uniquement la partie sous-titres, qui ne coute qu'un `iterdir()` local.

    La purge des anciens flags AVANT recalcul est obligatoire :
    `_apply_subtitle_detection` ne fait qu'APPEND, un flag perime resterait
    colle. Si `subtitle_expected_languages is None` (detection desactivee), on
    ne touche a rien — parite exacte avec le chemin de scan.

    Revue adverse : purger puis laisser re-APPEND en fin de liste donnait a une
    meme row deux serialisations differentes selon qu'elle venait du cache row
    ou d'un scan a froid (['integrity_header_invalid', 'subtitle_missing_fr']
    contre ['subtitle_missing_fr', 'integrity_header_invalid']). On reinsere
    donc les flags recalcules a leur POSITION D'ORIGINE.
    """
    if subtitle_expected_languages is None:
        return
    existing_flags = list(getattr(cached_row, "warning_flags", None) or [])

    # Position, dans la liste PURGEE, ou le scan a froid aurait pose les flags
    # sous-titres : celle qu'ils occupaient deja, sinon juste avant le premier
    # flag que le scan a froid pose apres eux.
    insert_at: Optional[int] = None
    kept: List[Any] = []
    for flag in existing_flags:
        if _is_subtitle_flag(flag):
            if insert_at is None:
                insert_at = len(kept)
        else:
            kept.append(flag)
    if insert_at is None:
        insert_at = next(
            (idx for idx, flag in enumerate(kept) if str(flag) in _POST_SUBTITLE_FLAGS),
            len(kept),
        )

    # `list(kept)` et non `kept` : _apply_subtitle_detection append IN PLACE, et
    # un alias fausserait la decoupe `[kept_len:]` ci-dessous.
    kept_len = len(kept)
    cached_row.warning_flags = list(kept)
    cached_row.subtitle_count = 0
    cached_row.subtitle_languages = []
    cached_row.subtitle_formats = []
    cached_row.subtitle_missing_langs = []
    cached_row.subtitle_orphans = 0
    _apply_subtitle_detection(
        folder,
        video,
        cached_row,
        subtitle_expected_languages=subtitle_expected_languages,
    )
    # `_apply_subtitle_detection` n'a fait qu'APPEND (aucun flag sous-titre ne
    # restait dans `kept`) : la queue de la liste est exactement le recalcul.
    new_flags = cached_row.warning_flags[kept_len:]
    if new_flags:
        cached_row.warning_flags = kept[:insert_at] + new_flags + kept[insert_at:]


def _apply_not_a_movie_detection(video: Path, result_row: "PlanRow") -> None:
    """Pose le flag 'not_a_movie' si l'heuristique depasse le seuil."""

    try:
        video_size = video.stat().st_size if video.exists() else 0
    except (OSError, PermissionError):
        video_size = 0
    nam_score = not_a_movie_score(
        video_name=video.name,
        file_size=video_size,
        proposed_source=result_row.proposed_source,
        confidence=result_row.confidence,
        title=result_row.proposed_title,
    )
    if nam_score >= _NOT_A_MOVIE_THRESHOLD and "not_a_movie" not in result_row.warning_flags:
        result_row.warning_flags.append("not_a_movie")


def _apply_integrity_check(video: Path, result_row: "PlanRow") -> None:
    """Pose le flag 'integrity_header_invalid' si magic bytes invalides.

    Ne jamais bloquer le scan pour un check d'integrite (try/except large).
    """

    try:
        hdr_valid, _hdr_detail = check_header(video)
        if not hdr_valid and "integrity_header_invalid" not in result_row.warning_flags:
            result_row.warning_flags.append("integrity_header_invalid")
    except (OSError, PermissionError, FileNotFoundError, ValueError):
        pass  # ne jamais bloquer le scan pour un check d'integrite


def _store_row_cache(
    cfg: "Config",
    folder: Path,
    video: Path,
    nfo_path: Optional[Path],
    result_row: "PlanRow",
    *,
    kind: str,
    cfg_sig: str,
    run_id: str,
    scan_index: Optional[Any],
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]],
) -> None:
    """Persiste la PlanRow dans le cache row v2 (best-effort, jamais bloquant)."""
    if not (cfg_sig and scan_index is not None and hasattr(scan_index, "upsert_incremental_row_cache")):
        return
    try:
        v_stat = video.stat()
        v_hash = resolve_incremental_quick_hash(
            video,
            scan_index=scan_index,
            run_hash_cache=run_hash_cache or {},
        )
        scan_index.upsert_incremental_row_cache(
            root_path=str(cfg.root),
            video_path=str(video),
            video_size=int(v_stat.st_size),
            video_mtime_ns=int(v_stat.st_mtime_ns),
            video_hash=v_hash,
            folder_path=str(folder),
            nfo_sig=_nfo_signature(nfo_path),
            cfg_sig=cfg_sig,
            kind=kind,
            row_json=plan_row_to_jsonable(result_row),
            run_id=str(run_id),
        )
    except (FileNotFoundError, PermissionError, OSError):
        pass


def _plan_item(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    kind: str,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
    library_root: Optional[Path] = None,
) -> List["PlanRow"]:
    """Orchestre la construction d'une PlanRow pour un fichier video.

    kind : "single" (film standalone) ou "collection" (film dans une saga).
    Pour les episodes TV, voir _plan_tv_episode (pipeline distinct).

    Pipeline : cache lookup -> contexte folder/edition -> NFO + cross-checks
    IMDb/TMDb -> TMDb fallback -> disambiguation -> PlanRow -> enrichissements
    (sous-titres, non-film, integrite) -> cache store.

    AUDIT 2026-06-11 (R3e, gap[3]) : `library_root` (optionnel) est la VRAIE
    racine de bibliotheque, utilisee pour decider si le film est pose
    directement a la racine (folder_name = stem fichier) ou dans son propre
    dossier (folder_name = folder.name). En replan, le caller met cfg.root =
    dossier du film, donc sans cette racine explicite `_folder_is_root` serait
    toujours True -> folder_name = stem du fichier au lieu du dossier propre,
    rendant le replan NON idempotent. Defaut None -> comportement scan inchange
    (compare contre cfg.root).
    """
    # Import paresseux : plan_support_dedup importe ce module (replan_single_row
    # n'a aucune dependance dedup, mais _plan_item utilise le pipeline scoring).
    from cinesort.app.plan_support_dedup import (
        _apply_runtime_hard_filter_to_tmdb_cands,
        _augment_candidates_from_nfo_imdb,
        _augment_candidates_from_nfo_tmdb_id,
        _build_nfo_candidates,
        _build_tmdb_fallback_candidates,
        _resolve_file_runtime_min,
    )
    from cinesort.domain.runtime_hard_filter import WARN_RUNTIME_HARD_EXCLUDED

    is_collection = kind == "collection"
    row_id_prefix = "C" if is_collection else "S"
    row_id = _compute_row_id(row_id_prefix, folder, video.name)

    # --- Scan v2: per-video row cache lookup ---
    cached_row = _try_lookup_row_cache(
        cfg,
        folder,
        video,
        kind=kind,
        cfg_sig=cfg_sig,
        scan_index=scan_index,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
    )
    if cached_row is not None:
        # F09 : la row cachee est un objet FRAIS (plan_row_from_jsonable), donc
        # cette mutation n'est partagee avec personne. Voir
        # _refresh_subtitle_detection pour le detail du defaut corrige.
        _refresh_subtitle_detection(
            folder,
            video,
            cached_row,
            subtitle_expected_languages=subtitle_expected_languages,
        )
        return [cached_row]

    # AUDIT 2026-06-11 (R3e, gap[3]) : si une racine biblio explicite est
    # fournie (replan), on compare folder contre ELLE et non contre cfg.root
    # (qui vaut le dossier du film en replan) -> folder_name idempotent.
    _ctx_root_resolved = _resolve_path_cached(str(library_root)) if library_root is not None else None
    folder_name, log_ctx, detected_edition = _resolve_folder_context(
        cfg, folder, video, is_collection=is_collection, cfg_root_resolved=_ctx_root_resolved
    )

    name_year, name_year_reason, remaster_hint = core_mod.infer_name_year(folder_name, video.name)
    name_cands = core_mod.build_candidates_from_name(folder_name, video.name, preferred_year=name_year)

    if core_mod._is_cancel_requested(should_cancel):
        return []

    nfo_path = core_mod.find_best_nfo_for_video(folder, video)
    if core_mod._is_cancel_requested(should_cancel):
        return []
    nfo = core_mod.parse_movie_nfo(nfo_path) if nfo_path else None

    nfo_cands, nfo_state = _build_nfo_candidates(
        cfg,
        folder_name,
        video.name,
        nfo=nfo,
        name_year=name_year,
        remaster_hint=remaster_hint,
        log=log,
        log_ctx=log_ctx,
    )

    _augment_candidates_from_nfo_imdb(
        cfg,
        nfo,
        nfo_cands,
        folder_name,
        video.name,
        name_year=name_year,
        tmdb=tmdb,
        log=log,
        log_ctx=log_ctx,
    )

    _augment_candidates_from_nfo_tmdb_id(
        cfg,
        nfo,
        nfo_cands,
        folder_name,
        video.name,
        name_year=name_year,
        nfo_ok=nfo_state["nfo_ok"],
        tmdb=tmdb,
        log=log,
        log_ctx=log_ctx,
    )

    tmdb_cands, tmdb_used = _build_tmdb_fallback_candidates(
        cfg,
        folder_name,
        video.name,
        is_collection=is_collection,
        name_year=name_year,
        nfo_cands=nfo_cands,
        year_delta_reject=nfo_state["year_delta_reject"],
        tmdb=tmdb,
        should_cancel=should_cancel,
    )

    # VN-D.3 : runtime HARD filter sur les candidats TMDb.
    runtime_hard_excluded_flag: Optional[str] = None
    if tmdb_cands:
        file_runtime_min, runtime_source = _resolve_file_runtime_min(nfo, folder, video)
        if file_runtime_min is not None:
            tmdb_cands, _excluded_any = _apply_runtime_hard_filter_to_tmdb_cands(
                tmdb_cands,
                file_runtime_min=file_runtime_min,
                detected_edition=detected_edition,
                tmdb=tmdb,
                settings=getattr(cfg, "_runtime_filter_settings", None),
                log=log,
                log_ctx=log_ctx,
                runtime_source=runtime_source,
            )
            if _excluded_any:
                runtime_hard_excluded_flag = WARN_RUNTIME_HARD_EXCLUDED

    cands = []
    cands.extend(nfo_cands)
    cands.extend(tmdb_cands)
    cands.extend(name_cands)

    # Dedup final par tmdb_id (sinon nfo_imdb 0.95 / nfo_tmdb 0.93 / tmdb 0.85
    # peuvent toutes survivre avec le meme tmdb_id et doubler dans le modal).
    # On garde le score max pour preserver le ranking de pick_best_candidate.
    _seen_cands: dict = {}
    for _c in cands:
        _k = _c.tmdb_id if _c.tmdb_id else ((_c.title or "").strip().lower(), _c.year)
        _prev = _seen_cands.get(_k)
        if _prev is None or (_c.score or 0.0) > (_prev.score or 0.0):
            _seen_cands[_k] = _c
    cands = list(_seen_cands.values())

    cands, title_ambiguous = _disambiguate_candidates(
        cands,
        nfo=nfo,
        name_year=name_year,
        log=log,
        log_ctx=log_ctx,
    )

    chosen = core_mod.pick_best_candidate(cands)
    if not chosen or not chosen.year:
        result_row = _build_unresolved_row(
            folder,
            video,
            row_id=row_id,
            kind=kind,
            is_collection=is_collection,
            folder_name=folder_name,
            cands=cands,
            nfo=nfo,
            nfo_path=nfo_path,
            nfo_state=nfo_state,
            name_year=name_year,
            name_year_reason=name_year_reason,
            remaster_hint=remaster_hint,
            tmdb_used=tmdb_used,
            title_ambiguous=title_ambiguous,
            detected_edition=detected_edition,
            log=log,
        )
    else:
        result_row = _build_resolved_row(
            cfg,
            folder,
            video,
            chosen,
            row_id=row_id,
            kind=kind,
            is_collection=is_collection,
            folder_name=folder_name,
            cands=cands,
            nfo=nfo,
            nfo_path=nfo_path,
            nfo_state=nfo_state,
            name_year=name_year,
            name_year_reason=name_year_reason,
            remaster_hint=remaster_hint,
            tmdb_used=tmdb_used,
            title_ambiguous=title_ambiguous,
            detected_edition=detected_edition,
            tmdb=tmdb,
            log=log,
        )

    # VN-D.3 : pose le warning sur la PlanRow si au moins un candidat TMDb a
    # ete exclu par le runtime HARD filter (utile pour debug user en UI).
    if runtime_hard_excluded_flag and result_row is not None:
        flags = getattr(result_row, "warning_flags", None)
        if flags is None:
            result_row.warning_flags = [runtime_hard_excluded_flag]
        elif runtime_hard_excluded_flag not in flags:
            flags.append(runtime_hard_excluded_flag)

    _apply_subtitle_detection(folder, video, result_row, subtitle_expected_languages=subtitle_expected_languages)
    _apply_not_a_movie_detection(video, result_row)
    _apply_integrity_check(video, result_row)
    _store_row_cache(
        cfg,
        folder,
        video,
        nfo_path,
        result_row,
        kind=kind,
        cfg_sig=cfg_sig,
        run_id=run_id,
        scan_index=scan_index,
        run_hash_cache=run_hash_cache,
    )

    return [result_row]


def _plan_single(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> List["PlanRow"]:
    return _plan_item(
        cfg,
        folder,
        video,
        tmdb,
        log,
        kind="single",
        should_cancel=should_cancel,
        scan_index=scan_index,
        cfg_sig=cfg_sig,
        run_id=run_id,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
        subtitle_expected_languages=subtitle_expected_languages,
    )


def _plan_collection_item(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
    scan_index: Optional[Any] = None,
    cfg_sig: str = "",
    run_id: str = "",
    run_hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    row_cache_stats: Optional[Dict[str, int]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
) -> List["PlanRow"]:
    return _plan_item(
        cfg,
        folder,
        video,
        tmdb,
        log,
        kind="collection",
        should_cancel=should_cancel,
        scan_index=scan_index,
        cfg_sig=cfg_sig,
        run_id=run_id,
        run_hash_cache=run_hash_cache,
        row_cache_stats=row_cache_stats,
        subtitle_expected_languages=subtitle_expected_languages,
    )


def replan_single_row(
    cfg: "Config",
    folder: Path,
    video: Path,
    *,
    tmdb: Optional[TmdbClient] = None,
    kind: str = "single",
    log: Optional[Callable[[str, str], None]] = None,
    subtitle_expected_languages: Optional[List[str]] = None,
    library_root: Optional[Path] = None,
) -> Optional["PlanRow"]:
    """Spec 06 §3.6 : reconstruit une PlanRow pour 1 seul fichier video.

    Helper public reutilisant le pipeline `_plan_item` (NFO + cross-checks
    IMDb/TMDb -> TMDb fallback -> disambiguation -> resolved/unresolved row
    -> enrichissements sous-titres/integrite/not-a-movie). Aucune mise en
    cache (cfg_sig/scan_index volontairement vides) : on force un rescan
    a froid pour ce row.

    AUDIT 2026-06-11 (R3e, gap[3]) : `library_root` doit etre la racine de
    bibliotheque d'origine du scan (cf. caller `_rematch_tmdb_and_update_plan`).
    Le caller construit cfg avec root=dossier_du_film, donc sans cette racine
    explicite le folder_name serait derive du stem fichier au lieu du dossier
    propre -> replan non idempotent. Si None, on retombe sur cfg.root (compat).

    Returns:
        La nouvelle PlanRow (jamais cachee), ou None si le pipeline n'a
        rien produit (cas degenere : video inexistante, etc.).
    """
    if log is None:

        def log(level: str, msg: str) -> None:  # noqa: ARG001
            _log.debug("replan_single_row[%s] %s", level, msg)

    if kind not in ("single", "collection"):
        kind = "single"

    rows = _plan_item(
        cfg,
        folder,
        video,
        tmdb,
        log,
        kind=kind,
        should_cancel=None,
        scan_index=None,
        cfg_sig="",
        run_id="",
        run_hash_cache=None,
        row_cache_stats=None,
        subtitle_expected_languages=subtitle_expected_languages,
        library_root=library_root,
    )
    if not rows:
        return None
    return rows[0]


def _plan_tv_episode(
    cfg: "Config",
    folder: Path,
    video: Path,
    tmdb: Optional[TmdbClient],
    log: Callable[[str, str], None],
    *,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> List["PlanRow"]:
    """Build a PlanRow for a TV episode (kind='tv_episode')."""

    tv = parse_tv_info(folder, video)
    if tv is None:
        return []

    row_id = _compute_row_id("T", folder, video.name)
    series_name = tv.series_name
    season = tv.season
    episode = tv.episode
    year = tv.year
    tmdb_series_id: Optional[int] = None
    episode_title: Optional[str] = None
    source = "name"
    confidence = 45

    # TMDb TV lookup.
    if tmdb and cfg.enable_tmdb and series_name:
        if core_mod._is_cancel_requested(should_cancel):
            return []
        try:
            tv_results = tmdb.search_tv(series_name, year=year, language=cfg.tmdb_language)
            if tv_results:
                best = tv_results[0]
                tmdb_series_id = best.id
                series_name = best.name or series_name
                if best.first_air_date_year:
                    year = best.first_air_date_year
                source = "tmdb_tv"
                confidence = 65

                if season is not None and episode is not None and tmdb_series_id:
                    ep_title = tmdb.get_tv_episode_title(
                        tmdb_series_id,
                        season,
                        episode,
                        language=cfg.tmdb_language,
                    )
                    if ep_title:
                        episode_title = ep_title
                        confidence = 85
        except (FileNotFoundError, PermissionError, OSError):
            pass

    if season is not None and episode is not None:
        confidence = min(100, confidence + 10)
    confidence = max(0, min(100, confidence))
    label = "high" if confidence >= 80 else "med" if confidence >= 60 else "low"

    proposed_title = core_mod.windows_safe(series_name)
    note_parts = [f"Serie: {series_name}"]
    if season is not None:
        note_parts.append(f"S{season:02d}")
    if episode is not None:
        note_parts.append(f"E{episode:02d}")
    if episode_title:
        note_parts.append(f'"{episode_title}"')
    note_parts.append(f"source={source}")

    return [
        core_mod.PlanRow(
            row_id=row_id,
            kind="tv_episode",
            folder=str(folder),
            video=video.name,
            proposed_title=proposed_title,
            proposed_year=int(year or 0),
            proposed_source=source,
            confidence=confidence,
            confidence_label=label,
            candidates=[],
            notes=" | ".join(note_parts),
            detected_year=int(year or 0),
            detected_year_reason="tv_first_air_date" if source == "tmdb_tv" else "folder",
            warning_flags=[],
            tv_series_name=series_name,
            tv_season=season,
            tv_episode=episode,
            tv_episode_title=episode_title,
            tv_tmdb_series_id=tmdb_series_id,
        )
    ]

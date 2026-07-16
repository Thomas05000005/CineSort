"""§v7.6.0 Vague 3 — Library / Explorer backend.

Endpoints :
    get_library_filtered(run_id, filters, sort, page, page_size)
    get_smart_playlists()
    save_smart_playlist(name, filters)
    delete_smart_playlist(playlist_id)

Les Smart Playlists sont persistees dans settings.json sous la cle
`smart_playlists` (liste de dicts).
"""

from __future__ import annotations

import json
import logging
import sqlite3
import time
import uuid
from typing import Any, Dict, List, Optional

from cinesort.domain._fuzzy_normalize import normalize_for_fuzzy
from cinesort.domain.film_identity import compute_film_id, is_path_film_id
from cinesort.domain.i18n_messages import t
from cinesort.domain.librarian import row_unidentified as _row_unidentified
from cinesort.domain.tiers_helpers import reconcile_display_tier
from cinesort.infra import state
from cinesort.ui.api._responses import err as _err_response
from cinesort.ui.api.settings_support import normalize_user_path

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Utilitaires
# ---------------------------------------------------------------------------


_CODEC_NORMALIZE = {
    "h.264": "h264",
    "h264": "h264",
    "avc": "h264",
    "avc1": "h264",
    "h.265": "hevc",
    "h265": "hevc",
    "hevc": "hevc",
    "hvc1": "hevc",
    "hev1": "hevc",
    "av1": "av1",
    "vp9": "vp9",
    "mpeg2": "mpeg2",
    "mpeg2video": "mpeg2",
    "vc1": "vc1",
    "xvid": "xvid",
    "divx": "divx",
    "wmv": "wmv",
    "wmv3": "wmv",
}


def _normalize_codec(codec: Optional[str]) -> str:
    if not codec:
        return "unknown"
    return _CODEC_NORMALIZE.get(str(codec).strip().lower(), str(codec).strip().lower())


def _classify_resolution(width: int, height: int) -> str:
    w = int(width or 0)
    h = int(height or 0)
    if w >= 3800 or h >= 2100:
        return "4k"
    if w >= 1900 or h >= 1060:
        return "1080p"
    if w >= 1280 or h >= 680:
        return "720p"
    if w > 0:
        return "sd"
    return "unknown"


def _classify_hdr(probe_video: Dict[str, Any]) -> str:
    # Fix audit 2026-05-26 (v1.5.6) Vague L : metrics.detected utilise les cles
    # hdr_dolby_vision / hdr10_plus / hdr10 (cf quality_score.py:1331-1333). Les
    # anciennes cles has_dv / has_hdr10_plus / has_hdr10 / dv_profile ne sont pas
    # persistees dans metrics.detected. On accepte les deux schemas pour eviter
    # de casser un eventuel appelant qui passerait encore le NormalizedProbe brut.
    if not isinstance(probe_video, dict):
        return "sdr"
    if probe_video.get("hdr10_plus") or probe_video.get("has_hdr10_plus"):
        return "hdr10_plus"
    if probe_video.get("hdr_dolby_vision") or probe_video.get("has_dv"):
        profile = str(probe_video.get("dv_profile") or "").strip()
        if profile == "5":
            return "dv_p5"
        return "dv"
    if probe_video.get("hdr10") or probe_video.get("has_hdr10"):
        return "hdr10"
    return "sdr"


def _extract_row_warnings(perceptual_row: Optional[Dict[str, Any]]) -> List[str]:
    """Liste des flags de warnings a partir du global_score_v2_payload."""
    if not perceptual_row:
        return []
    payload = perceptual_row.get("global_score_v2_payload") or {}
    warnings_text: List[str] = payload.get("warnings") or []
    flags: List[str] = []
    for w in warnings_text:
        low = str(w).lower()
        if "dolby vision profile 5" in low or "dv5" in low:
            flags.append("dv_profile_5")
        if "maxcll" in low or "hdr10 sans" in low:
            flags.append("hdr_metadata_missing")
        if "runtime" in low or "extended cut" in low or "theatrical" in low:
            flags.append("runtime_mismatch")
        if "court" in low and "fichier" in low:
            flags.append("short_file")
        if "confidence" in low or "analyse partielle" in low:
            flags.append("low_confidence")
        if "desequilibre" in low:
            flags.append("category_imbalance")
        if "lossless" in low:
            flags.append("fake_lossless")
    # DNR partial / fake 4K : signaux domain directs
    if payload.get("adjustments_applied"):
        for adj in payload["adjustments_applied"]:
            if "dnr_partial" in adj:
                flags.append("dnr_partial")
            if "fake_4k" in adj:
                flags.append("fake_4k_confirmed")
    return sorted(set(flags))


def _build_display_tier_fields(
    perc: Optional[Dict[str, Any]],
    qual: Optional[Dict[str, Any]],
) -> Dict[str, str]:
    """VN-B.2 : retourne les champs tier reconcilies pour une row library.

    - display_tier : echelle V2 canonique (lowercase platinum/gold/silver/bronze/
      reject), single source of truth pour le badge UI.
    - tier_source : "perceptual" | "quality_v1" | "quality_v2" | "fallback",
      preserve pour debug et instrumentation.
    - tier_v2 : alias backward compat sur display_tier (memes valeurs, les
      anciens callers continuent de fonctionner sans changement).
    """
    perc_tier = (perc or {}).get("global_tier_v2") if perc else None
    qual_tier = (qual or {}).get("tier") if qual else None
    display_tier, tier_source = reconcile_display_tier(
        perc_tier_v2=perc_tier,
        qual_tier_v1=qual_tier,
        default="unknown",
    )
    return {
        "display_tier": display_tier,
        "tier_source": tier_source,
        # Backward compat : conserve l'ancien champ pour les callers existants.
        "tier_v2": display_tier,
    }


# ---------------------------------------------------------------------------
# Construction des rows enrichies
# ---------------------------------------------------------------------------


def _build_library_rows(api: Any, run_id: str) -> List[Dict[str, Any]]:
    """Construit la liste des rows Library enrichies (probe + perceptual V2)."""
    # Charger le plan
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("library_support cannot get store: %s", exc)
        return []

    # AUDIT 2026-07-13 (HIGH-18) : migration a la lecture des marquages legacy
    # (deletion_marks.json, ancien store bulk sans annulation possible) vers la
    # table DB film_marked_for_deletion — seul store que le modal Film sait
    # annuler (unmark_for_deletion) et lire (flag is_marked_for_deletion).
    # Point d'entree naturel : la vue Bibliotheque est le chemin par lequel on
    # ouvre le modal. No-op des que le fichier legacy a disparu.
    try:
        from cinesort.ui.api.library_actions_support import (  # noqa: PLC0415
            migrate_legacy_deletion_marks,
        )

        migrate_legacy_deletion_marks(api, run_id)
    # Revue adversaire 2026-07-13 (defaut 3) : + sqlite3.Error / RuntimeError,
    # sinon une DB verrouillee fait planter TOUTE la vue Bibliotheque.
    except (
        ImportError,
        OSError,
        AttributeError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        logger.warning("migration deletion_marks legacy ignoree run_id=%s: %s", run_id, exc)

    # Perceptual reports indexes par row_id
    try:
        perc_list = store.perceptual.list_perceptual_reports(run_id=run_id)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.warning("library_support cannot list perceptual reports: %s", exc)
        perc_list = []
    perc_by_row = {str(p.get("row_id", "")): p for p in perc_list}

    # Quality reports
    try:
        quality_list = store.quality.list_quality_reports(run_id=run_id)
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        logger.warning("library_support cannot list quality reports: %s", exc)
        quality_list = []
    quality_by_row = {str(q.get("row_id", "")): q for q in quality_list}

    # PlanRows
    plan_result = api.run.get_plan(run_id)
    if not plan_result or not plan_result.get("ok"):
        return []
    plan_rows = plan_result.get("rows") or []

    # R7-3 : overlay du choix manuel de candidat TMDb (film_tmdb_overrides) sur
    # chaque row -> la biblio reflete le match choisi (tmdb_id/titre/annee) et ne
    # revient plus au match auto au reload. No-op si aucun override.
    from cinesort.ui.api.film_support import overlay_tmdb_override
    for _r in plan_rows:
        overlay_tmdb_override(store, run_id, _r)

    # Fix audit 2026-05-25 (v1.5.4) Vague I (Bug 2) : pre-resolve poster URLs en
    # batch via integrations.get_tmdb_posters(). Avant : `r.get("poster_url")`
    # retournait toujours None car PlanRow n'a PAS de champ poster_url plat (le
    # poster vit sur les Candidate enfants, pas sur le row) -> les 853 cartes
    # affichaient toutes le placeholder clapper. Maintenant : on collecte tous
    # les tmdb_id non nuls, on appelle 1 fois get_tmdb_posters([...], "w342")
    # et on mappe poster par tmdb_id. Cache TMDb local evite la re-frappe HTTP
    # entre 2 appels. Films non identifies (tmdb_id=None) gardent leur
    # placeholder coté UI avec lien "Identifier manuellement".
    #
    # Fix audit 2026-05-25 (v1.5.5) Vague J : root cause des 853 cartes sans
    # poster. PlanRow.tmdb_id est TOUJOURS None apres scan (le linker ecrit le
    # tmdb_id sur les Candidate enfants, pas au top-level du row). Resultat
    # Vague I.D collectait tmdb_ids=[] -> aucun batch poster lance -> 853
    # placeholders. Fix : extraire tmdb_id depuis candidates[0] (best score) en
    # plus du top-level. Persiste en `chosen_tmdb_id` dans la row Library pour
    # exposer au frontend et permettre identification implicite.
    def _resolve_tmdb_id(row_dict: Dict[str, Any]) -> Optional[int]:
        """Resoud le tmdb_id effectif d'une PlanRow : top-level d'abord, puis
        candidat de meilleur score (>=0.7), sinon None."""
        tid_top = row_dict.get("tmdb_id")
        if tid_top:
            try:
                v = int(tid_top)
                if v > 0:
                    return v
            except (TypeError, ValueError):
                pass
        # Fallback : best candidate avec tmdb_id (la liste est deja ordonnee par
        # score desc cote linker domain).
        best: Optional[int] = None
        best_score = -1.0
        for cand in (row_dict.get("candidates") or []):
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
                # Confiance candidat insuffisante : on n'auto-resolve pas.
                continue
            if score > best_score:
                try:
                    best = int(cid)
                    best_score = score
                except (TypeError, ValueError):
                    continue
        return best

    # Map row_id -> tmdb_id resolu (pour eviter de recalculer dans la boucle out)
    resolved_tmdb_by_row: Dict[str, int] = {}
    tmdb_ids: List[int] = []
    for r in plan_rows:
        rid = str(r.get("row_id") or "")
        tid = _resolve_tmdb_id(r)
        if tid and tid > 0:
            resolved_tmdb_by_row[rid] = tid
            if tid not in tmdb_ids:
                tmdb_ids.append(tid)
    posters_by_tmdb: Dict[str, str] = {}
    if tmdb_ids:
        try:
            poster_res = api.integrations.get_tmdb_posters(tmdb_ids, "w342")
            if poster_res and poster_res.get("ok"):
                raw_map = poster_res.get("posters") or {}
                # Normaliser cles en str (l'API retourne str(int) deja, mais on
                # protege contre les eventuels int).
                posters_by_tmdb = {str(k): v for k, v in raw_map.items() if v}
        except (AttributeError, KeyError, TypeError, ValueError) as exc:
            logger.debug("library_support poster batch fetch error: %s", exc)

    out: List[Dict[str, Any]] = []
    for r in plan_rows:
        row_id = str(r.get("row_id") or "")
        perc = perc_by_row.get(row_id)
        qual = quality_by_row.get(row_id)

        # Extraire metadata probe (cote quality_reports ou plan row)
        metrics = (qual or {}).get("metrics") if qual else None
        if not isinstance(metrics, dict):
            metrics = {}
        # Fix audit 2026-05-26 (v1.5.6) Vague L (lib-1) : la vraie structure persistee
        # par compute_quality_score est metrics["detected"] (dict imbrique), PAS
        # metrics["video"] / metrics["audio"]. Cf cinesort/domain/quality_score.py
        # _build_quality_metrics_helper (lignes 1318-1372). Les cles correctes :
        #   detected.width / detected.height (int)
        #   detected.video_codec (str) — pas "codec"
        #   detected.duration_s (float)
        #   detected.audio_tracks_count + detected.languages (langues AUDIO ISO639)
        #   detected.audio_best_codec / detected.audio_best_channels
        #   detected.hdr_dolby_vision / detected.hdr10 / detected.hdr10_plus (bool)
        #   detected.file_size_bytes (estimation bitrate*duration, voir lib-2)
        # Avant ce fix : metrics.get("video") = None partout -> width/height/codec/
        # hdr = "unknown" sur 100% des films, et metrics.get("duration_s") = None
        # car duration_s est dans detected, pas top-level metrics.
        detected = metrics.get("detected") if isinstance(metrics, dict) else None
        if not isinstance(detected, dict):
            detected = {}
        probe_video = detected  # pour _classify_hdr (cles hdr10/hdr_dolby_vision)

        width = int(detected.get("width") or 0)
        height = int(detected.get("height") or 0)
        duration_s = float(detected.get("duration_s") or 0)

        # Phase 4 spec 07 : exposer audio_langs / subs_langs / subs_missing pour
        # compteurs chips + export.
        # Fix audit 2026-05-26 (v1.5.6) Vague L (lib-1) : les langues audio sont dans
        # detected.languages (liste de str ISO639-2/3 brutes, ex ["eng","fra"]). Avant :
        # on lisait metrics.audio (liste de dicts {language: ...}) qui n'a jamais
        # existe -> audio_languages = [] systematiquement, cassant le compteur chip
        # "audio_langs" et le filtre subtitle_languages.
        raw_audio_langs = detected.get("languages")
        audio_langs: List[str] = []
        if isinstance(raw_audio_langs, list):
            for lang in raw_audio_langs:
                lang_norm = str(lang or "").strip().lower()
                if lang_norm and lang_norm not in audio_langs:
                    audio_langs.append(lang_norm)

        # Fix audit 2026-05-25 (v1.5.4) Vague I : BUG 2 — la PlanRow ne capture pas
        # les pistes subtitle EMBARQUEES (scan sans probe). On enrichit ici depuis
        # `quality_reports.metrics.subtitles_embedded` (persiste par _probe_and_score
        # apres get_quality_report), pour aligner le compte "sans subs FR" entre la
        # vue Bibliotheque et le rapport Qualite. Si pas de quality_report disponible,
        # fallback transparent sur les langues externes detectees au scan.
        scan_subtitle_languages = [str(s).lower() for s in (r.get("subtitle_languages") or [])]
        embedded_subs_raw = metrics.get("subtitles_embedded") if isinstance(metrics, dict) else None
        embedded_langs: List[str] = []
        if isinstance(embedded_subs_raw, list):
            try:
                from cinesort.domain.subtitle_helpers import _normalize_iso639

                for track in embedded_subs_raw:
                    if not isinstance(track, dict):
                        continue
                    raw_lang = (track.get("language") or "").strip().lower()
                    if not raw_lang:
                        continue
                    # AUDIT 2026-06-11 (R4-P14) : conserver le code BRUT quand
                    # _normalize_iso639 ne le connait pas (hin, tam...) — sinon la
                    # piste disparait de la row et un film sous-titre hindi matche
                    # encore "Aucun" malgre le fix filtre (cause amont du residuel
                    # P3 confirme par la revue adversaire). Symetrique de
                    # _to_iso639_1. Les tags speciaux (forced/sdh...) sont ensuite
                    # neutralises au filtrage par _NON_LANG_CODES.
                    normalized = _normalize_iso639(raw_lang) or raw_lang
                    if normalized and normalized not in embedded_langs:
                        embedded_langs.append(normalized)
            except (ImportError, AttributeError, KeyError, TypeError, ValueError):
                embedded_langs = []
        # Union langues externes (PlanRow) + langues embarquees (quality_report metrics)
        merged_langs = list(scan_subtitle_languages)
        for lang in embedded_langs:
            if lang not in merged_langs:
                merged_langs.append(lang)
        subtitle_languages = merged_langs
        # Recalcul missing_langs en filtrant les langues finalement presentes
        scan_missing = [str(s).lower() for s in (r.get("subtitle_missing_langs") or [])]
        subtitle_missing_langs = [lang for lang in scan_missing if lang not in subtitle_languages]
        proposed_source = str(r.get("proposed_source") or "").strip().lower()
        confidence = int(r.get("confidence") or 0)

        # Fix audit 2026-05-25 (v1.5.4) Vague I (Bug 2) : resolve poster_url via
        # le batch posters_by_tmdb pre-calcule en haut de fonction. Fallback sur
        # le 1er candidat TMDb avec poster_url si tmdb_id direct absent (cas des
        # rows non encore identifies mais avec candidats suggeres).
        #
        # Fix audit 2026-05-25 (v1.5.5) Vague J : utilise tmdb_id RESOLU (top-level
        # OU best candidate) au lieu du seul top-level. Sans ca, 853/853 PlanRows
        # avaient tmdb_id=None donc poster_url=None malgre des candidats avec
        # tmdb_id valide.
        poster_url: Optional[str] = None
        resolved_tid = resolved_tmdb_by_row.get(row_id)
        if resolved_tid:
            poster_url = posters_by_tmdb.get(str(resolved_tid))
        if not poster_url:
            for cand in (r.get("candidates") or []):
                cand_poster = cand.get("poster_url") if isinstance(cand, dict) else None
                if cand_poster:
                    poster_url = cand_poster
                    break

        row = {
            "row_id": row_id,
            "title": r.get("proposed_title") or r.get("nfo_title") or "",
            "year": int(r.get("proposed_year") or 0),
            # AUDIT 2026-07-15 (M4) : expose `kind` pour que le comptage doublons
            # (_count_duplicates_and_sagas) puisse exclure les episodes TV, miroir
            # exact du detecteur reel (duplicate_support.find_duplicate_targets).
            "kind": str(r.get("kind") or ""),
            # Issue audit Tier 2 : tmdb_id absent ici cassait le match Jellyfin
            # DateCreated dans library_timeline_support (fallback toujours fs mtime).
            # Fix audit 2026-05-25 (v1.5.5) Vague J : expose le tmdb_id RESOLU
            # (top-level OU best candidate score>=0.7) pour que le frontend
            # affiche un poster + un libelle "identifie" plutot que "Identifier"
            # quand la confidence est forte. Sans ca : 836 films avec candidats
            # haute confiance affichaient quand meme le placeholder "Identifier"
            # parce que PlanRow.tmdb_id top-level reste None apres scan.
            "tmdb_id": resolved_tmdb_by_row.get(row_id) or r.get("tmdb_id"),
            "duration_s": duration_s,
            "duration_min": int(duration_s / 60) if duration_s > 0 else 0,
            # Fix audit 2026-05-26 (v1.5.6) Vague L (lib-1) : la cle persistee est
            # detected.video_codec (pas .codec). Cf quality_score.py:1329.
            "codec": _normalize_codec(detected.get("video_codec") or detected.get("codec")),
            "resolution": _classify_resolution(width, height),
            "width": width,
            "height": height,
            "hdr": _classify_hdr(probe_video),
            # VN-B.2 (Vague N batch 2) : reconciliation V1/V2 explicite via
            # cinesort.domain.tiers_helpers.reconcile_display_tier. Avant : fallback
            # `perc.global_tier_v2 OR qual.tier` melangeait 2 echelles incomparables
            # (V1 seuils 70/66/55/40 capitalized vs V2 seuils 90/80/65/50 lowercase),
            # exposant l'utilisateur a un Platinum V1 affiche comme "platinum" V2
            # alors qu'il serait Silver/Bronze V2 reel.
            #
            # Le tuple (display_tier, tier_source) est la single source of truth pour
            # le frontend (badge UI). On preserve tier_v2 pour backward compat
            # (legacy callers) mais display_tier doit etre privilegie.
            # Voir cinesort/domain/tiers_helpers.py::reconcile_display_tier docstring.
            **_build_display_tier_fields(perc, qual),
            "score_v2": (perc or {}).get("global_score_v2") or (qual or {}).get("score"),
            # Iter13 etape 4 (2026-06-10) : EXPOSER probe_quality pour signaler
            # explicitement a l'UI quand les metadonnees qualite sont indisponibles
            # (probe FAILED apres retry+breaker iter1-3). Sans ce flag, l'UI
            # affichait un score Silver-cap silencieux (degradation INVISIBLE) au
            # lieu d'un marqueur "Indisponible" honnete. Acquis racine C iter4 :
            # identification (titre/year/tmdb_id) reste DECOUPLEE du probe et
            # le film reste renommable meme avec probe FAILED.
            "probe_quality": str(metrics.get("probe_quality") or "UNKNOWN").upper(),
            "quality_unavailable": str(metrics.get("probe_quality") or "").upper() == "FAILED",
            "warnings": _extract_row_warnings(perc),
            "grain_era_v2": None,  # extrait du metrics si dispo
            "grain_nature": None,
            "added_ts": float(r.get("mtime") or 0),
            "path": r.get("source_path") or "",
            "poster_url": poster_url,
            # v7.6.0 Vague 7 : champs pour get_scoring_rollup
            "tmdb_collection_name": r.get("tmdb_collection_name"),
            "edition": r.get("edition"),
            # Phase 4 spec 07 : champs additionnels pour counters chips + export
            "audio_languages": audio_langs,
            "subtitle_languages": subtitle_languages,
            "subtitle_missing_langs": subtitle_missing_langs,
            "proposed_source": proposed_source,
            # AUDIT 2026-06-11 (R3) : source MEDIA (bluray/web/dvd/other) derivee du
            # nom video, pour le filtre Source du drawer (distincte de
            # proposed_source = source d'identification).
            "media_source": _media_source_label(r.get("video") or r.get("source_path") or ""),
            "confidence": confidence,
            # Fix audit 2026-05-26 (v1.5.6) Vague L (lib-2) : metrics["size_bytes"]
            # n'existe pas. La taille estimee est dans detected.file_size_bytes
            # (bitrate_kbps * duration_s, cf _estimate_file_size en domain/quality_score.py).
            # Avant : metrics.get("size_bytes") = None -> tous les size_bytes
            # provenaient uniquement de PlanRow.size_bytes (lui-meme souvent 0
            # tant que le scan FS n'a pas posé la stat), cassant le tri/filtre taille.
            "size_bytes": int(
                r.get("size_bytes")
                or detected.get("file_size_bytes")
                or 0
            ),
        }

        # Si grain dans metrics
        grain = metrics.get("grain") if isinstance(metrics, dict) else None
        if isinstance(grain, dict):
            gi = grain.get("grain_intelligence") or {}
            row["grain_era_v2"] = gi.get("film_era_v2")
            row["grain_nature"] = gi.get("nature")

        # AUDIT 2026-06-13 (R5-B) : exposer l'etat d'identification (source unique
        # = _row_unidentified) pour que la carte UI n'affiche "Identifier" QUE sur
        # les vrais non-identifies, pas sur les films NFO/nom sans tmdb_id.
        row["identified"] = not _row_unidentified(row)

        out.append(row)

    return out


# ---------------------------------------------------------------------------
# Filtrage
# ---------------------------------------------------------------------------

# AUDIT 2026-06-11 (R3) : les filtres du drawer avance (source/codec/resolution/
# langues/sous-titres) ne matchaient JAMAIS car les valeurs du drawer differaient
# du vocabulaire backend. On normalise au moment du match.

# Codec : backend _normalize_codec produit h264/hevc/av1/unknown ; drawer envoie
# h264/h265/av1/other.
_DRAWER_CODEC_ALIAS = {"h265": "hevc", "h264": "h264", "av1": "av1"}
_KNOWN_CODECS = {"h264", "hevc", "av1"}
# Resolution : backend _classify_resolution produit 4k/1080p/720p/sd/unknown ;
# drawer envoie 480p/720p/1080p/4k/other.
_DRAWER_RES_ALIAS = {"480p": "sd", "720p": "720p", "1080p": "1080p", "4k": "4k"}
_KNOWN_RES = {"4k", "1080p", "720p", "sd"}
# Source media : source_hint (release_name_parser) -> vocabulaire drawer.
_SOURCE_HINT_TO_DRAWER = {
    "bluray": "bluray", "remux": "bluray",
    "webdl": "web", "webrip": "web",
    "dvd": "dvd",
    "hdtv": "other", "cam": "other",
}
# AUDIT 2026-06-11 (R4-P5) : le drawer Qualite (qualite-filters-drawer.js) envoie
# des LIBELLES ('BluRay'/'WEB-DL'/'WEB-Rip'/'DVD'/'HDTV'/'Autre') sous la cle
# 'sources' (pluriel) ; le drawer Biblio envoie bluray/web/dvd/other sous
# 'source'. On normalise les libelles vers le vocabulaire backend.
_DRAWER_SOURCE_ALIAS = {
    "web-dl": "web", "web-rip": "web", "webdl": "web", "webrip": "web",
    "hdtv": "other", "autre": "other",
}


def _media_source_label(video_name: str) -> str:
    """Derive le label source media (bluray/web/dvd/other) depuis le nom du
    fichier video, pour le filtre Source du drawer (AUDIT 2026-06-11 R3 : avant,
    le filtre comparait a proposed_source = source d'IDENTIFICATION nfo/name/tmdb,
    jamais a la source media)."""
    name = str(video_name or "").strip()
    if not name:
        return ""
    try:
        from cinesort.domain.release_name_parser import parse_release_name  # noqa: PLC0415
        hint = str(parse_release_name(name).source_hint or "").strip().lower()
    except (ImportError, OSError, TypeError, ValueError):
        return ""
    return _SOURCE_HINT_TO_DRAWER.get(hint, "other" if hint else "")


# Codes ISO639 / tags de piste qui ne designent PAS une langue identifiable :
# exclus du comptage "multi"/"autre" (sinon eng+und ou eng+forced compteraient
# 2 langues) mais CONSERVES comme presence de piste (un film avec une piste
# 'und' ou 'forced' a bien de l'audio/des sous-titres -> ne matche pas "Aucun").
# Revue adversaire R4 (P3 v2) : ajoute mul + tags speciaux forced/sdh/cc/
# commentary (que _LANG_MAP mappe a '' et que le fallback brut reintroduisait
# comme fausses langues) + la plage ISO 639-2 usage local qaa..qtz (convention
# pistes commentaire), via _is_non_language_code (520 codes, pas de frozenset).
_NON_LANG_CODES = frozenset(
    {"und", "unknown", "zxx", "mis", "mul", "multi", "forced", "sdh", "cc", "commentary"}
)


def _is_non_language_code(code: str) -> bool:
    if code in _NON_LANG_CODES:
        return True
    # Plage ISO 639-2 reservee usage local : qaa..qtz.
    return len(code) == 3 and code.startswith("q") and "a" <= code[1] <= "t"


def _to_iso639_1(lang: str) -> str:
    """Normalise un code langue ISO639-2/3 (eng/fra/fre) en ISO639-1 (en/fr).

    AUDIT 2026-06-11 (R4-P3) : un code HORS _LANG_MAP (~25 langues : hin, tam,
    ukr...) retombait sur "" via _normalize_iso639 puis etait discard() par les
    filtres -> un film ['eng','hin'] ne matchait pas "multi" et un film ['hin']
    matchait "none". On conserve desormais le code brut (lowercased) quand la
    normalisation ne le connait pas : la piste reste comptee.
    """
    raw = str(lang or "").strip().lower()
    if not raw:
        return ""
    try:
        from cinesort.domain.subtitle_helpers import _normalize_iso639  # noqa: PLC0415
        return str(_normalize_iso639(raw) or "").strip().lower() or raw
    except (ImportError, OSError, TypeError, ValueError):
        return raw


def _row_matches(row: Dict[str, Any], filters: Dict[str, Any]) -> bool:
    """Applique tous les filtres actifs a une row. AND entre categories."""

    # Search texte (titre). AUDIT ULTRA 2026-07-13 (H15) : la comparaison etait
    # un substring brut sur .lower() -> "amelie" ne trouvait pas "Amelie"
    # (accent) car les titres TMDb sont stockes accentues (windows_safe force
    # NFC sans replier les accents). On replie les accents des DEUX cotes
    # (query ET titre) via normalize_for_fuzzy (lower + NFD + strip marques
    # combinantes + ponctuation), le meme helper que le fuzzy des doublons.
    q = normalize_for_fuzzy(str(filters.get("search") or ""))
    if q and q not in normalize_for_fuzzy(str(row.get("title") or "")):
        return False

    def _in_list(row_val: Any, filter_list: Any) -> bool:
        if not filter_list:
            return True
        return str(row_val or "").lower() in [str(v).lower() for v in filter_list]

    def _any_in_list(row_vals: Any, filter_list: Any) -> bool:
        """True si au moins un element de row_vals (liste) est dans filter_list."""
        if not filter_list:
            return True
        if not row_vals:
            return False
        wanted = {str(v).lower() for v in filter_list}
        return any(str(rv or "").lower() in wanted for rv in row_vals)

    # VN-B.2 : filtre par tier accepte les deux cles (tier_v2 legacy, display_tier
    # nouveau). row.display_tier == row.tier_v2 depuis la reconciliation, mais on
    # les supporte tous deux cote filtres entrants pour fluidifier la migration UI.
    tier_filter = filters.get("tier_v2") or filters.get("display_tier")
    if not _in_list(row.get("display_tier") or row.get("tier_v2"), tier_filter):
        return False
    # Codec : drawer h265 -> backend hevc ; "other" = hors {h264,hevc,av1}.
    codec_filter = filters.get("codec")
    if codec_filter:
        rc = str(row.get("codec") or "").strip().lower()
        wanted = {_DRAWER_CODEC_ALIAS.get(str(f).lower(), str(f).lower()) for f in codec_filter}
        ok = (rc in wanted) or ("other" in wanted and rc not in _KNOWN_CODECS)
        if not ok:
            return False
    # Resolution : drawer 480p -> backend sd ; "other" = hors {4k,1080p,720p,sd}.
    res_filter = filters.get("resolution")
    if res_filter:
        rr = str(row.get("resolution") or "").strip().lower()
        wanted = {_DRAWER_RES_ALIAS.get(str(f).lower(), str(f).lower()) for f in res_filter}
        ok = (rr in wanted) or ("other" in wanted and rr not in _KNOWN_RES)
        if not ok:
            return False
    if not _in_list(row.get("hdr"), filters.get("hdr")):
        return False
    if not _in_list(row.get("grain_era_v2"), filters.get("grain_era_v2")):
        return False
    if not _in_list(row.get("grain_nature"), filters.get("grain_nature")):
        return False
    # Source media (bluray/web/dvd/other) derivee du nom video, PAS proposed_source.
    # AUDIT 2026-06-11 (R4-P5) : accepte aussi la cle 'sources' (pluriel) du
    # drawer Qualite et normalise ses libelles (WEB-DL/WEB-Rip->web, HDTV/Autre
    # ->other). Avant, la cle pluriel n'etait jamais lue -> filtre mort.
    source_filter = filters.get("source") or filters.get("sources")
    if source_filter:
        media_src = row.get("media_source")
        if media_src is None:  # defensif : derive a la volee si absent du payload
            media_src = _media_source_label(row.get("video") or row.get("path") or "")
        wanted = {_DRAWER_SOURCE_ALIAS.get(str(f).lower(), str(f).lower()) for f in source_filter}
        ms = str(media_src or "").lower()
        ok = (ms in wanted) or ("other" in wanted and ms not in {"bluray", "web", "dvd"})
        if not ok:
            return False

    # Decennies (drawer Qualite, cle 'decades', values '1990' — tolere '1990s').
    # AUDIT 2026-06-11 (R4-P5) : jamais lu avant -> filtre mort. Un film sans
    # annee (year=0) est exclu quand le filtre est actif (aligne sur
    # compute_by_decade qui skip les annees invalides). NB : le filtre 'genres'
    # du meme drawer reste NON applicable ici — les rows n'embarquent pas les
    # genres TMDb (manque de donnees, pas de mapping possible) ; period_days est
    # consomme separement par quality/get_history.
    decades_filter = filters.get("decades")
    if decades_filter:
        year = int(row.get("year") or 0)
        decade = str((year // 10) * 10) if year > 0 else ""
        wanted = {str(f).strip().lower().rstrip("s") for f in decades_filter}
        if decade not in wanted:
            return False
    # Audio langues : normalise ISO639-1 (eng->en) + "multi" = >=2 vraies langues.
    # AUDIT 2026-06-11 (R4-P3) : "multi" compte les langues IDENTIFIABLES
    # distinctes (les codes non mappes type hin/tam sont conserves bruts par
    # _to_iso639_1, donc comptes) en excluant _NON_LANG_CODES (eng+und n'est
    # pas un film multi-langues).
    audio_filter = filters.get("audio_languages")
    if audio_filter:
        norm_row = {_to_iso639_1(l) for l in (row.get("audio_languages") or [])}
        norm_row.discard("")
        wanted = {str(f).lower() for f in audio_filter}
        real_langs = {l for l in norm_row if not _is_non_language_code(l)}
        # R4-P5 : 'Autre' (drawer Qualite) = au moins une vraie langue hors fr/en.
        ok = (
            bool(norm_row & wanted)
            or ("multi" in wanted and len(real_langs) >= 2)
            or (("autre" in wanted or "other" in wanted) and bool(real_langs - {"fr", "en"}))
        )
        if not ok:
            return False
    # Sous-titres : "none" = AUCUN sous-titre ; sinon normalise ISO639-1.
    sub_filter = filters.get("subtitle_languages")
    if sub_filter:
        norm_row = {_to_iso639_1(l) for l in (row.get("subtitle_languages") or [])}
        norm_row.discard("")
        wanted = {str(f).lower() for f in sub_filter}
        ok = bool(norm_row & wanted) or ("none" in wanted and not norm_row)
        if not ok:
            return False

    # Warnings : OR interne (au moins un warning du filtre present dans la row)
    wflags = filters.get("warnings")
    if wflags:
        row_warns = set(row.get("warnings") or [])
        if not any(str(w).lower() in row_warns for w in wflags):
            return False

    # Year range
    year = int(row.get("year") or 0)
    y_min = filters.get("year_min")
    y_max = filters.get("year_max")
    if y_min and year and year < int(y_min):
        return False
    if y_max and year and year > int(y_max):
        return False

    # Duration (en minutes)
    dur = int(row.get("duration_min") or 0)
    d_min = filters.get("duration_min")
    d_max = filters.get("duration_max")
    if d_min and dur and dur < int(d_min):
        return False
    if d_max and dur and dur > int(d_max):
        return False

    # Phase 5 spec 07 : size range (bytes) — convertit Go en bytes cote frontend
    size_b = int(row.get("size_bytes") or 0)
    s_min = filters.get("size_min")
    s_max = filters.get("size_max")
    if s_min and size_b and size_b < int(s_min):
        return False
    if s_max and size_b and size_b > int(s_max):
        return False

    # Phase 5 spec 07 : confidence range (0-100)
    conf = int(row.get("confidence") or 0)
    c_min = filters.get("confidence_min")
    c_max = filters.get("confidence_max")
    if c_min is not None and conf < int(c_min):
        return False
    if c_max is not None and conf > int(c_max):
        return False

    # Phase 5 spec 07 : added date range (added_ts epoch seconds)
    added = float(row.get("added_ts") or 0.0)
    a_min = filters.get("added_after")
    a_max = filters.get("added_before")
    if a_min is not None and added and added < float(a_min):
        return False
    if a_max is not None and added and added > float(a_max):
        return False

    # Phase 5 spec 07 : chips non-tier (subs_missing_fr / unidentified /
    # recently_modified / in_duplicates / sagas_incomplete). AND interne.
    chips = filters.get("chips") or []
    if chips:
        chip_set = {str(c).strip().lower() for c in chips if c}
        if "subs_missing_fr" in chip_set and not _row_subs_missing_fr(row):
            return False
        if "unidentified" in chip_set and not _row_unidentified(row):
            return False
        if "recently_modified" in chip_set and not _row_recently_modified(
            row,
            time.time(),
            _RECENTLY_MODIFIED_WINDOW_S,
        ):
            return False
        if "sagas_incomplete" in chip_set and not row.get("tmdb_collection_name"):
            return False
        # "in_duplicates" est evalue a l'echelle de la collection (cf
        # _filter_in_duplicates apres _row_matches) - on le laisse passer ici.

    return True


_SORT_KEY = {
    # M12 : cle sans accents (normalize_for_fuzzy = lower + NFD strip marques)
    # pour classer "Élan"/"Été" avec leur lettre de base, pas apres "z"
    # (point de code 'é'=0xE9 > 'z'=0x7A). Tie-break annee conserve.
    "title": lambda r: (normalize_for_fuzzy(str(r.get("title") or "")), r.get("year") or 0),
    "score_desc": lambda r: -(r.get("score_v2") or 0),
    "score_asc": lambda r: r.get("score_v2") or 0,
    "year_desc": lambda r: -(r.get("year") or 0),
    "year_asc": lambda r: r.get("year") or 0,
    "duration_desc": lambda r: -(r.get("duration_s") or 0),
    "duration_asc": lambda r: r.get("duration_s") or 0,
    "added_desc": lambda r: -(r.get("added_ts") or 0),
    "added_asc": lambda r: r.get("added_ts") or 0,
    # Phase 5 spec 07 : tri par taille fichier
    "size_desc": lambda r: -(r.get("size_bytes") or 0),
    "size_asc": lambda r: r.get("size_bytes") or 0,
}

# M13 : les tris "descendants" purement textuels reutilisent la cle ascendante
# avec reverse=True (inverse EXACT de l'ascendant). On evite ainsi la cle
# -ord bricolee qui inversait mal les paires prefixe ("Avatar" avant
# "Avatar 2"), tronquait a 50 caracteres et perdait le tie-break annee.
_SORT_REVERSE = {
    "title_desc": "title",
}


def _apply_sort(rows: List[Dict[str, Any]], sort: str) -> List[Dict[str, Any]]:
    sort = sort or "title"
    reverse = sort in _SORT_REVERSE
    key = _SORT_KEY.get(_SORT_REVERSE.get(sort, sort)) or _SORT_KEY["title"]
    try:
        return sorted(rows, key=key, reverse=reverse)
    except (TypeError, ValueError):
        return rows


def _rescan_target_run_id(run: Dict[str, Any]) -> Optional[str]:
    """LOTC-B1 : run utilitaire de bulk re-scan -> run_id cible, sinon None."""
    raw = run.get("config_json")
    cfg: Any = raw
    if isinstance(raw, str):
        if "rescan_run_id" not in raw:
            return None
        try:
            cfg = json.loads(raw)
        except ValueError:
            return None
    if isinstance(cfg, dict):
        target = cfg.get("rescan_run_id")
        if target:
            return str(target)
    return None


def _resolve_run_id(api: Any, run_id: Optional[str]) -> Optional[str]:
    if run_id:
        return str(run_id)
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        # LOTC-B1 : rescan_rows_bulk cree un run de tracking JobRunner SANS plan
        # propre ; resoudre "latest" sur lui rendait la bibliotheque vide pour
        # toute la session. On saute ces runs utilitaires (marqueur config
        # rescan_run_id) et, si la fenetre ne contient qu'eux, on retombe sur
        # le run qu'ils re-scannaient (qui porte le plan).
        runs = store.run.list_runs(limit=20)
        rescan_fallback: Optional[str] = None
        for run in runs or []:
            target = _rescan_target_run_id(run)
            if target:
                rescan_fallback = rescan_fallback or target
                continue
            rid = str(run.get("run_id") or "")
            if rid:
                return rid
        if rescan_fallback:
            return rescan_fallback
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.debug("_resolve_run_id error: %s", exc)
    return None


# ---------------------------------------------------------------------------
# API publique
# ---------------------------------------------------------------------------


def get_library_filtered(
    api: Any,
    run_id: Optional[str] = None,
    filters: Optional[Dict[str, Any]] = None,
    sort: str = "title",
    page: int = 1,
    page_size: int = 50,
) -> Dict[str, Any]:
    """Renvoie une liste paginee de films filtres + triés.

    Returns:
      {
        ok: bool,
        run_id: str,
        rows: list[dict],
        total: int,           # total apres filtrage
        page: int,
        pages: int,
        page_size: int,
        stats: {
          by_tier: {platinum, gold, silver, bronze, reject, unknown},
          ...
        }
      }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500
    # quand le run est obsolete / la base inaccessible / la facade leve.
    try:
        return _get_library_filtered_impl(api, run_id, filters, sort, page, page_size)
    except Exception as exc:  # noqa: BLE001 - boundary top-level pour endpoint UI
        logger.exception(
            "get_library_filtered failed for run_id=%s page=%s", run_id, page
        )
        return {
            "ok": False,
            "error": "library_load_failed",
            "message": str(exc),
            "user_message": (
                "Impossible de charger la bibliotheque (run obsolete ou base "
                "inaccessible). Relance un scan ou redemarre l'app."
            ),
            "rows": [],
            "total": 0,
            "page": int(page or 1),
            "pages": 0,
            "page_size": int(page_size or 50),
            "stats": {"by_tier": {}},
        }


def _get_library_filtered_impl(
    api: Any,
    run_id: Optional[str],
    filters: Optional[Dict[str, Any]],
    sort: str,
    page: int,
    page_size: int,
) -> Dict[str, Any]:
    """Implementation reelle de get_library_filtered, sans wrap global (Vague F)."""
    filters = filters or {}
    page = max(1, int(page or 1))
    page_size = max(1, min(500, int(page_size or 50)))

    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return {
            "ok": True,
            "run_id": None,
            "rows": [],
            "total": 0,
            "page": page,
            "pages": 0,
            "page_size": page_size,
            "stats": {"by_tier": {}},
        }

    all_rows = _build_library_rows(api, resolved_rid)
    filtered = [r for r in all_rows if _row_matches(r, filters)]

    # Phase 5 spec 07 : chip "in_duplicates" — necessite une evaluation cross-row.
    chips = filters.get("chips") or []
    if chips and "in_duplicates" in {str(c).strip().lower() for c in chips if c}:
        by_titleyear: Dict[tuple, int] = {}
        for r in filtered:
            key = (str(r.get("title") or "").strip().lower(), int(r.get("year") or 0))
            if key[0]:
                by_titleyear[key] = by_titleyear.get(key, 0) + 1
        filtered = [
            r
            for r in filtered
            if by_titleyear.get(
                (str(r.get("title") or "").strip().lower(), int(r.get("year") or 0)),
                0,
            )
            >= 2
        ]

    total = len(filtered)

    # Stats pour la sidebar (counts par tier). VN-B.2 : lecture sur display_tier
    # (single source of truth) avec fallback tier_v2 pour rows pre-VN-B.2.
    by_tier: Dict[str, int] = {}
    for r in filtered:
        t = str(r.get("display_tier") or r.get("tier_v2") or "unknown").lower()
        by_tier[t] = by_tier.get(t, 0) + 1

    sorted_rows = _apply_sort(filtered, sort)
    pages = max(1, (total + page_size - 1) // page_size)
    start = (page - 1) * page_size
    rows_page = sorted_rows[start : start + page_size]

    return {
        "ok": True,
        "run_id": resolved_rid,
        "rows": rows_page,
        "total": total,
        "page": page,
        "pages": pages,
        "page_size": page_size,
        "stats": {"by_tier": by_tier},
    }


# ---------------------------------------------------------------------------
# Smart Playlists (persistance settings.json)
# ---------------------------------------------------------------------------


def _get_playlists_from_settings(api: Any) -> List[Dict[str, Any]]:
    try:
        settings = api.settings.get_settings()
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        return []
    raw = settings.get("smart_playlists")
    if isinstance(raw, list):
        return raw
    return []


def _write_playlists_to_settings(api: Any, playlists: List[Dict[str, Any]]) -> bool:
    try:
        settings = api.settings.get_settings()
        settings["smart_playlists"] = playlists
        api.settings.save_settings(settings)
        return True
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("save smart_playlists failed: %s", exc)
        return False


def get_smart_playlists(api: Any) -> Dict[str, Any]:
    """Liste les smart playlists persistees."""
    playlists = _get_playlists_from_settings(api)
    # Ajouter les playlists predefinies suggestion
    predefined = [
        {
            "id": "_preset_reject",
            "name": "Films Reject a re-acquerir",
            "filters": {"tier_v2": ["reject"]},
            "preset": True,
        },
        {
            "id": "_preset_dnr",
            "name": "DNR partiel detecte",
            "filters": {"warnings": ["dnr_partial"]},
            "preset": True,
        },
        {
            "id": "_preset_platinum",
            "name": "Platinum recents (2020+)",
            "filters": {"tier_v2": ["platinum"], "year_min": 2020},
            "preset": True,
        },
    ]
    return {"ok": True, "playlists": predefined + list(playlists)}


def save_smart_playlist(
    api: Any,
    name: str,
    filters: Dict[str, Any],
    playlist_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Cree ou met a jour une smart playlist."""
    name = str(name or "").strip()
    if not name:
        return _err_response("Nom requis.", category="validation", level="info", log_module=__name__)
    if not isinstance(filters, dict):
        return _err_response("Filtres invalides.", category="validation", level="info", log_module=__name__)

    playlists = _get_playlists_from_settings(api)

    now = time.time()
    if playlist_id and not playlist_id.startswith("_preset_"):
        # Update
        updated = False
        for p in playlists:
            if p.get("id") == playlist_id:
                p["name"] = name
                p["filters"] = filters
                p["updated_ts"] = now
                updated = True
                break
        if not updated:
            return _err_response("Playlist introuvable.", category="resource", level="info", log_module=__name__)
    else:
        # Create
        new = {
            "id": f"sp_{uuid.uuid4().hex[:8]}",
            "name": name,
            "filters": filters,
            "created_ts": now,
            "updated_ts": now,
        }
        playlists.append(new)
        playlist_id = new["id"]

    if not _write_playlists_to_settings(api, playlists):
        return _err_response(t("errors.persistence_failed"), category="runtime", level="error", log_module=__name__)

    return {"ok": True, "playlist_id": playlist_id}


def delete_smart_playlist(api: Any, playlist_id: str) -> Dict[str, Any]:
    """Supprime une smart playlist custom (les presets ne peuvent etre supprimes)."""
    if not playlist_id or str(playlist_id).startswith("_preset_"):
        return _err_response("Playlist protegee.", category="permission", level="warning", log_module=__name__)

    playlists = _get_playlists_from_settings(api)
    before = len(playlists)
    playlists = [p for p in playlists if p.get("id") != playlist_id]
    if len(playlists) == before:
        return _err_response("Playlist introuvable.", category="resource", level="info", log_module=__name__)

    if not _write_playlists_to_settings(api, playlists):
        return _err_response(t("errors.persistence_failed"), category="runtime", level="error", log_module=__name__)

    return {"ok": True, "deleted_id": playlist_id}


# ---------------------------------------------------------------------------
# §v7.6.0 Vague 7 — Scoring rollup par realisateur / franchise
# ---------------------------------------------------------------------------


def get_scoring_rollup(
    api: Any,
    by: str = "franchise",
    limit: int = 20,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregation scoring par dimension (director, franchise, decade, codec).

    Args:
        by: "franchise" | "director" | "decade" | "codec" | "era_grain"
        limit: max groupes retournes (tries par count desc)
    Returns:
      {
        ok: bool,
        by: str,
        groups: [
          { group_name, count, avg_score, tier_distribution: {...}, top_film_ids: [...] }
        ]
      }
    """
    dim = str(by or "franchise").lower()
    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return {"ok": True, "by": dim, "groups": []}

    rows = _build_library_rows(api, resolved_rid)
    if not rows:
        return {"ok": True, "by": dim, "groups": []}

    buckets: Dict[str, Dict[str, Any]] = {}

    # Pour franchise/director, on doit les extraire des candidats TMDb (on simplifie avec titre)
    # Ici on utilise soit la collection TMDb, soit le director, soit la decade, etc.
    for r in rows:
        group_key = _extract_group_key(r, dim)
        if not group_key:
            continue
        bucket = buckets.setdefault(
            group_key,
            {
                "group_name": group_key,
                "count": 0,
                "score_sum": 0.0,
                "score_samples": 0,
                "tier_distribution": {
                    "platinum": 0,
                    "gold": 0,
                    "silver": 0,
                    "bronze": 0,
                    "reject": 0,
                    "unknown": 0,
                },
                "top_film_ids": [],
            },
        )
        bucket["count"] += 1
        score = r.get("score_v2")
        if score is not None:
            bucket["score_sum"] += float(score)
            bucket["score_samples"] += 1
        # VN-B.2 : lecture sur display_tier (single source of truth).
        tier = str(r.get("display_tier") or r.get("tier_v2") or "unknown").lower()
        if tier in bucket["tier_distribution"]:
            bucket["tier_distribution"][tier] += 1
        if len(bucket["top_film_ids"]) < 5:
            bucket["top_film_ids"].append(r.get("row_id"))

    # Finalize : moyenne + sort
    groups: List[Dict[str, Any]] = []
    for bucket in buckets.values():
        avg = round(bucket["score_sum"] / bucket["score_samples"], 1) if bucket["score_samples"] else None
        groups.append(
            {
                "group_name": bucket["group_name"],
                "count": bucket["count"],
                "avg_score": avg,
                "tier_distribution": bucket["tier_distribution"],
                "top_film_ids": bucket["top_film_ids"],
            }
        )

    # Tri par count desc, puis avg_score desc
    groups.sort(key=lambda g: (-int(g["count"]), -(g["avg_score"] or 0)))
    groups = groups[: max(1, min(100, int(limit or 20)))]

    return {"ok": True, "by": dim, "groups": groups, "run_id": resolved_rid}


# ---------------------------------------------------------------------------
# Phase 4 spec 07 — Compteurs par chip pour la vue Bibliotheque
# ---------------------------------------------------------------------------


_RECENTLY_MODIFIED_WINDOW_S = 7 * 24 * 3600  # 7 jours


def _row_subs_missing_fr(row: Dict[str, Any]) -> bool:
    """True si la row n'a pas de sous-titres FR (langue manquante ou liste subs vide)."""
    subs = set(row.get("subtitle_languages") or [])
    missing = set(row.get("subtitle_missing_langs") or [])
    # Soit "fr" est explicitement marque comme manquant, soit absent de la liste presente
    if any(lang.startswith("fr") for lang in missing):
        return True
    if not any(lang.startswith("fr") for lang in subs):
        return True
    return False


# AUDIT 2026-07-15 (M2) : `_row_unidentified` est desormais un ALIAS de la
# definition UNIQUE cinesort.domain.librarian.row_unidentified (importee en tete
# de module). La carte Accueil "films non identifies" (librarian, section D) et
# ce predicat rendaient un verdict OPPOSE sur le meme film (l'un ignorait
# tmdb_id / proposed_year et testait conf == 0). Une seule source de verite
# desormais, couvert par tests/test_identification_nfo_v77.py.


def _row_recently_modified(row: Dict[str, Any], now_ts: float, window_s: float) -> bool:
    ts = float(row.get("added_ts") or 0.0)
    if ts <= 0:
        return False
    return (now_ts - ts) <= window_s


def _count_duplicates_and_sagas(rows: List[Dict[str, Any]]) -> tuple[int, int]:
    """Compte les films "in_duplicates" (meme titre+annee >= 2) et "sagas_incomplete".

    Heuristique pour in_duplicates : groupes de >= 2 rows avec meme (title, year).
    Heuristique pour sagas_incomplete : films appartenant a une collection TMDb.
    """
    by_titleyear: Dict[tuple, int] = {}
    sagas_count = 0
    for r in rows:
        # AUDIT 2026-07-15 (M4) : un episode TV n'est PAS un doublon de film.
        # Miroir EXACT de duplicate_support.find_duplicate_targets (skip
        # kind == "tv_episode") : sans ce filtre, le chip "Dans doublons"
        # promettait des doublons que l'ecran Doublons ne montre jamais.
        # NB : on n'exclut QUE du comptage doublons ; le comptage sagas reste
        # inchange (une saga peut contenir des episodes).
        is_tv_episode = str(r.get("kind") or "") == "tv_episode"
        key = (str(r.get("title") or "").strip().lower(), int(r.get("year") or 0))
        if key[0] and not is_tv_episode:
            by_titleyear[key] = by_titleyear.get(key, 0) + 1
        if r.get("tmdb_collection_name"):
            sagas_count += 1

    in_duplicates = sum(c for c in by_titleyear.values() if c >= 2)
    return in_duplicates, sagas_count


def get_library_counters_by_chip(
    api: Any,
    filters: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Phase 4 spec 07 — Retourne les counts par chip pour la vue Bibliotheque.

    Les chips couvrent :
    - Tier qualite (6) : platinum, gold, silver, bronze, reject, unknown
    - Filtres problematiques (3) : subs_missing_fr, unidentified, recently_modified
    - Filtres structurels (2) : in_duplicates, sagas_incomplete

    Le filter `filters` est applique avant comptage (utile pour scope counters
    sur une sous-selection, ex: search="dune" -> counts dans le sous-ensemble).

    Returns:
      {
        ok: bool,
        run_id: str,
        total: int,
        counts: {
          platinum: int, gold: int, silver: int, bronze: int, reject: int, unknown: int,
          subs_missing_fr: int, unidentified: int, recently_modified: int,
          in_duplicates: int, sagas_incomplete: int,
        }
      }
    """
    filters = filters or {}
    resolved_rid = _resolve_run_id(api, run_id)
    if not resolved_rid:
        return {
            "ok": True,
            "run_id": None,
            "total": 0,
            "counts": {
                "platinum": 0,
                "gold": 0,
                "silver": 0,
                "bronze": 0,
                "reject": 0,
                "unknown": 0,
                "subs_missing_fr": 0,
                "unidentified": 0,
                "recently_modified": 0,
                "in_duplicates": 0,
                "sagas_incomplete": 0,
            },
        }

    all_rows = _build_library_rows(api, resolved_rid)
    # Appliquer filters EN AMONT pour scoper les counters (utile si search actif).
    scoped_rows = [r for r in all_rows if _row_matches(r, filters)]

    counts: Dict[str, int] = {
        "platinum": 0,
        "gold": 0,
        "silver": 0,
        "bronze": 0,
        "reject": 0,
        "unknown": 0,
        "subs_missing_fr": 0,
        "unidentified": 0,
        "recently_modified": 0,
        "in_duplicates": 0,
        "sagas_incomplete": 0,
    }

    now_ts = time.time()
    for row in scoped_rows:
        # VN-B.2 : lecture sur display_tier (single source of truth).
        tier = str(row.get("display_tier") or row.get("tier_v2") or "unknown").lower()
        if tier in counts:
            counts[tier] += 1
        else:
            counts["unknown"] += 1

        if _row_subs_missing_fr(row):
            counts["subs_missing_fr"] += 1
        if _row_unidentified(row):
            counts["unidentified"] += 1
        if _row_recently_modified(row, now_ts, _RECENTLY_MODIFIED_WINDOW_S):
            counts["recently_modified"] += 1

    in_dup, sagas = _count_duplicates_and_sagas(scoped_rows)
    counts["in_duplicates"] = in_dup
    counts["sagas_incomplete"] = sagas

    return {
        "ok": True,
        "run_id": resolved_rid,
        "total": len(scoped_rows),
        "counts": counts,
    }


# Spec 06 Modal Film — 3 endpoints d'actions sur un film
# ---------------------------------------------------------------------------


def _get_store(api: Any):
    """Helper : retourne le SQLiteStore via les facades, ou None si indispo."""
    try:
        settings = api.settings.get_settings()
        state_dir = normalize_user_path(settings.get("state_dir"), state.default_state_dir())
        store, _ = api._get_or_create_infra(state_dir)
        return store
    # R2 (revue Lot E round 2) : + sqlite3.Error (n'herite pas d'OSError) et
    # RuntimeError (rollback migration dans initialize()) — sinon le helper
    # "retourne None si indispo" laissait remonter les erreurs SQLite.
    except (OSError, AttributeError, KeyError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        logger.warning("library_support _get_store error: %s", exc)
        return None


def _find_plan_row(api: Any, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
    """Recherche une PlanRow dans le run, par row_id."""
    try:
        plan = api.run.get_plan(run_id)
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        return None
    if not plan or not plan.get("ok"):
        return None
    for r in plan.get("rows") or []:
        if str(r.get("row_id") or "") == str(row_id):
            return r
    return None


def _confidence_label_from_value(value: int) -> str:
    """Reproduit la grille de labels utilisee par compute_confidence.

    VN-C.1 (batch 2) : delegation au module canonique
    cinesort.domain.confidence_thresholds (source unique CONF_HIGH=85 /
    CONF_MEDIUM=60). Anciens seuils hardcode 85/60 ici => meme valeurs,
    mais maintenant pilotes depuis 1 endroit.
    """
    from cinesort.domain.confidence_thresholds import confidence_label  # noqa: PLC0415
    return confidence_label(value)


def _format_proposed_path(api: Any, run_id: str, title: str, year: int) -> str:
    """Reconstruit le 'proposed_path' relatif (sous-dossier) selon le template
    de renommage configure dans le run. Fallback : `Title (Year)/`.

    On garde simple : on ne reconstruit pas le path complet (ROOT inconnu sans
    cfg du run), on retourne juste le folder name + slash trailing, comme
    `proposed_path` est consomme cote frontend (diff avec current_path).
    """
    # Import lazy : module domain optionnel selon contexte UI/CLI/tests.
    try:
        from cinesort.domain import naming as _naming
    except ImportError:
        # Fallback ultra-simple
        return f"{title} ({int(year or 0)})/" if year else f"{title}/"
    template = ""
    try:
        settings = api.settings.get_settings()
        template = str(settings.get("naming_movie_template") or "")
    except (OSError, AttributeError, KeyError, TypeError, ValueError):
        template = ""
    ctx = {
        "title": str(title or ""),
        "year": str(int(year or 0)) if year else "",
        "edition": "",
        "edition-tag": "",
        "source-tag": "",
        "quality": "",
        "score": "",
    }
    try:
        folder = _naming.format_movie_folder(template, ctx)
    except (TypeError, ValueError, AttributeError, KeyError):
        folder = f"{title} ({int(year or 0)})" if year else str(title or "Film")
    return f"{folder}/"


def set_film_tmdb_candidate(
    api: Any,
    run_id: Optional[str],
    row_id: str,
    tmdb_id: int,
) -> Dict[str, Any]:
    """Spec 06 §3.4 : choisir un autre candidat TMDb pour un film.

    - Recherche le candidat dans `row.candidates[]` par tmdb_id
    - Recalcule la confidence depuis candidate.score (0..1) * 100
    - Construit le nouveau proposed_path depuis title + year
    - Persiste l'override en DB (table film_tmdb_overrides)
    - Reversible tant que l'apply n'est pas faite (clear_tmdb_override)

    Retourne :
        { ok, new_confidence, new_confidence_label, new_proposed_path,
          proposed_title, proposed_year, tmdb_id }
    """
    rid = _resolve_run_id(api, run_id)
    if not rid:
        return _err_response("Aucun run disponible.", category="state", level="info", log_module=__name__)
    try:
        tmdb_int = int(tmdb_id)
    except (TypeError, ValueError):
        return _err_response("tmdb_id invalide.", category="validation", level="info", log_module=__name__)
    if tmdb_int <= 0:
        return _err_response("tmdb_id invalide.", category="validation", level="info", log_module=__name__)

    row = _find_plan_row(api, rid, row_id)
    if not row:
        return _err_response(
            f"Film introuvable (row_id={row_id}).", category="resource", level="info", log_module=__name__
        )

    # Recherche du candidat
    chosen = None
    for c in row.get("candidates") or []:
        if int(c.get("tmdb_id") or 0) == tmdb_int:
            chosen = c
            break
    if chosen is None:
        return _err_response(
            f"Candidat TMDb {tmdb_int} introuvable parmi les candidats du film.",
            category="resource",
            level="info",
            log_module=__name__,
        )

    # Recalcul confidence : candidate.score (0..1) -> 0..100, plancher 30
    raw_score = chosen.get("score")
    try:
        score_pct = int(round(float(raw_score or 0.0) * 100))
    except (TypeError, ValueError):
        score_pct = 0
    new_confidence = max(30, min(100, score_pct))
    new_label = _confidence_label_from_value(new_confidence)

    proposed_title = str(chosen.get("title") or row.get("proposed_title") or "").strip()
    try:
        proposed_year = int(chosen.get("year") or row.get("proposed_year") or 0)
    except (TypeError, ValueError):
        proposed_year = 0

    new_proposed_path = _format_proposed_path(api, rid, proposed_title, proposed_year)

    # Persistance override
    store = _get_store(api)
    if store is None:
        return _err_response("Store SQLite indisponible.", category="runtime", level="error", log_module=__name__)
    try:
        store.film_modal.upsert_tmdb_override(
            run_id=rid,
            row_id=str(row_id),
            tmdb_id=tmdb_int,
            new_confidence=new_confidence,
            proposed_title=proposed_title,
            proposed_year=proposed_year,
        )
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(
            f"Persistance override echouee : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    # VP-G-LOCKS-001 (Fix #5 ROADMAP_VAGUE_P) : Identify manuel via Modal Film
    # provoque la transition path:<sha1> -> tmdb:<new_id>. Sans migration, les
    # locks poses avant Identify restent orphelins sur l'ancien path:<sha1>
    # et seront ecrases au prochain rescan/refresh. Pattern identique a
    # library_actions_support.py:340-361 (_rematch_tmdb_and_update_plan).
    try:
        old_film_id = compute_film_id(row)
        new_film_id = f"tmdb:{tmdb_int}"
        if old_film_id and old_film_id != new_film_id and is_path_film_id(old_film_id):
            repo = getattr(store, "field_locks", None)
            if repo is not None:
                try:
                    migrated = repo.migrate_locks(old_film_id, new_film_id)
                    if migrated:
                        logger.info(
                            "field_locks migrate %s -> %s : %d lock(s)",
                            old_film_id,
                            new_film_id,
                            migrated,
                        )
                except (OSError, AttributeError, TypeError, ValueError) as exc:
                    logger.warning("migrate_locks failed: %s", exc)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        logger.warning("field_locks migration failed (best-effort): %s", exc)

    return {
        "ok": True,
        "run_id": rid,
        "row_id": str(row_id),
        "tmdb_id": tmdb_int,
        "new_confidence": new_confidence,
        "new_confidence_label": new_label,
        "new_proposed_path": new_proposed_path,
        "proposed_title": proposed_title,
        "proposed_year": proposed_year,
    }


def clear_tmdb_override(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """AUDIT 2026-06-14 (R7-12) : annule l'override TMDb manuel (revient au match
    auto). Reversibilite promise par set_film_tmdb_candidate, jusqu'ici sans
    appelant de prod (methode repo orpheline)."""
    rid = _resolve_run_id(api, run_id)
    if not rid:
        return _err_response("Aucun run disponible.", category="state", level="info", log_module=__name__)
    store = _get_store(api)
    if store is None:
        return _err_response("Store SQLite indisponible.", category="runtime", level="error", log_module=__name__)
    try:
        res = store.film_modal.clear_tmdb_override(run_id=rid, row_id=str(row_id))
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        return _err_response(f"clear_tmdb_override echoue : {exc}", category="runtime", level="error", log_module=__name__)
    removed = bool(res.get("removed")) if isinstance(res, dict) else bool(res)
    return {"ok": True, "run_id": rid, "row_id": str(row_id), "removed": removed}


def unmark_for_deletion(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """AUDIT 2026-06-14 (R7-12) : annule le marquage pour suppression d'un film
    (avant : impossible -> il partait au bucket au prochain apply sans recours)."""
    rid = _resolve_run_id(api, run_id)
    if not rid:
        return _err_response("Aucun run disponible.", category="state", level="info", log_module=__name__)
    store = _get_store(api)
    if store is None:
        return _err_response("Store SQLite indisponible.", category="runtime", level="error", log_module=__name__)
    # AUDIT 2026-07-13 (HIGH-18) : un film marque par l'ancien mecanisme bulk
    # (deletion_marks.json) doit pouvoir etre demarque ici. On draine d'abord le
    # store legacy vers la DB, sinon le DELETE ci-dessous ne trouve rien et le
    # film repart quand meme au bucket au prochain apply.
    try:
        from cinesort.ui.api.library_actions_support import (  # noqa: PLC0415
            migrate_legacy_deletion_marks,
        )

        migrate_legacy_deletion_marks(api, rid)
    # Revue adversaire 2026-07-13 (defaut 3) : + sqlite3.Error / RuntimeError —
    # un demarquage ne doit pas remonter une exception SQLite brute a l'UI.
    except (
        ImportError,
        OSError,
        AttributeError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        logger.warning("migration deletion_marks legacy ignoree run_id=%s: %s", rid, exc)
    try:
        res = store.film_modal.unmark_for_deletion(run_id=rid, row_id=str(row_id))
    # Revue adversaire R3 2026-07-13 (defaut 3) : l'except du drain ci-dessus
    # couvrait sqlite3.Error/RuntimeError, mais PAS l'appel DB REEL de cette ligne
    # (sqlite3.Error n'herite pas d'OSError) -> DB verrouillee = HTTP 500.
    except (
        OSError,
        AttributeError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        return _err_response(f"unmark_for_deletion echoue : {exc}", category="runtime", level="error", log_module=__name__)
    removed = bool(res.get("removed")) if isinstance(res, dict) else bool(res)

    # Revue adversaire R3 2026-07-13 (defaut 4) : le drain ci-dessus est
    # best-effort et CONSERVE deletion_marks.json quand l'insertion DB echoue —
    # or l'apply honore l'UNION DB + legacy (apply_support.py:1584). Sans ce
    # retrait, un unmark repondait ok:True ("demarque" cote UI) alors que le film
    # repartait au bucket au prochain apply. Si on n'arrive pas a retirer la
    # marque legacy, on ne PRETEND PAS que le demarquage a reussi.
    legacy_cleared = False
    try:
        from cinesort.ui.api.library_actions_support import (  # noqa: PLC0415
            remove_legacy_deletion_mark,
        )

        legacy_cleared = remove_legacy_deletion_mark(api, rid, str(row_id))
    except (
        ImportError,
        OSError,
        AttributeError,
        KeyError,
        RuntimeError,
        TypeError,
        ValueError,
        sqlite3.Error,
    ) as exc:
        logger.warning("retrait deletion_marks legacy echoue run_id=%s: %s", rid, exc)
        legacy_cleared = False
    if not legacy_cleared:
        return _err_response(
            "Demarquage incomplet : la marque heritee (deletion_marks.json) n'a pas pu etre "
            "retiree, le film repartirait au bucket au prochain apply. Reessaie.",
            category="runtime",
            level="error",
            log_module=__name__,
        )
    return {"ok": True, "run_id": rid, "row_id": str(row_id), "removed": removed}


def mark_for_deletion(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """Spec 06 §3.7 : marque un film pour le bucket `_user_marked_for_deletion/`.

    - Persiste en DB (table film_marked_for_deletion)
    - Reversible via undo (clear / unmark_for_deletion)
    - Le deplacement effectif sera applique au prochain apply

    Retourne : { ok, marked, run_id, row_id, source_path, marked_at }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500.
    try:
        return _mark_for_deletion_impl(api, run_id, row_id)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("mark_for_deletion failed for run_id=%s row_id=%s", run_id, row_id)
        return {
            "ok": False,
            "error": "mark_for_deletion_failed",
            "message": str(exc),
            "user_message": "Impossible de marquer ce film. Verifie l'etat du run et reessaie.",
        }


def _mark_for_deletion_impl(api: Any, run_id: Optional[str], row_id: str) -> Dict[str, Any]:
    """Implementation reelle de mark_for_deletion, sans wrap global (Vague F)."""
    rid = _resolve_run_id(api, run_id)
    if not rid:
        return _err_response("Aucun run disponible.", category="state", level="info", log_module=__name__)

    row = _find_plan_row(api, rid, str(row_id))
    if not row:
        return _err_response(
            f"Film introuvable (row_id={row_id}).", category="resource", level="info", log_module=__name__
        )

    source_path = str(row.get("source_path") or row.get("folder") or "")

    store = _get_store(api)
    if store is None:
        return _err_response("Store SQLite indisponible.", category="runtime", level="error", log_module=__name__)
    try:
        res = store.film_modal.mark_for_deletion(
            run_id=rid,
            row_id=str(row_id),
            source_path=source_path,
        )
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(
            f"Persistance marquage echouee : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    return {
        "ok": True,
        "marked": True,
        "run_id": rid,
        "row_id": str(row_id),
        "source_path": source_path,
        "marked_at": float(res.get("marked_at") or 0.0),
    }


def mark_alert_ignored(api: Any, row_id: str, alert_code: str) -> Dict[str, Any]:
    """Spec 06 §3.3 : persiste "j'ai vu cette alerte, on continue".

    - Insert en DB (table ignored_alerts)
    - L'alerte disparait visuellement mais reste loggee pour stats globales
    - Idempotent : meme couple (row_id, alert_code) ne re-insere pas

    Retourne : { ok, ignored, row_id, alert_code, ignored_at }
    """
    # Fix audit 2026-05-25 (v1.5.3) Vague F : wrap global pour eviter HTTP 500.
    try:
        return _mark_alert_ignored_impl(api, row_id, alert_code)
    except Exception as exc:  # noqa: BLE001 - boundary top-level
        logger.exception("mark_alert_ignored failed for row_id=%s alert_code=%s", row_id, alert_code)
        return {
            "ok": False,
            "error": "mark_alert_ignored_failed",
            "message": str(exc),
            "user_message": "Impossible d'ignorer cette alerte. Reessaie dans quelques instants.",
        }


def _mark_alert_ignored_impl(api: Any, row_id: str, alert_code: str) -> Dict[str, Any]:
    """Implementation reelle de mark_alert_ignored, sans wrap global (Vague F)."""
    rid_s = str(row_id or "").strip()
    code_s = str(alert_code or "").strip()
    if not rid_s:
        return _err_response("row_id manquant.", category="validation", level="info", log_module=__name__)
    if not code_s:
        return _err_response("alert_code manquant.", category="validation", level="info", log_module=__name__)

    store = _get_store(api)
    if store is None:
        return _err_response("Store SQLite indisponible.", category="runtime", level="error", log_module=__name__)
    try:
        res = store.film_modal.insert_ignored_alert(rid_s, code_s)
    except (OSError, AttributeError, KeyError, TypeError, ValueError) as exc:
        return _err_response(
            f"Persistance alerte ignoree echouee : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    return {
        "ok": True,
        "ignored": True,
        "row_id": rid_s,
        "alert_code": code_s,
        "ignored_at": float(res.get("ignored_at") or 0.0),
        "already_ignored": not bool(res.get("inserted")),
    }


# ---------------------------------------------------------------------------
# Rollup interne (legacy)
# ---------------------------------------------------------------------------


def _extract_group_key(row: Dict[str, Any], dim: str) -> Optional[str]:
    """Extrait la cle de regroupement depuis une row enrichie."""
    if dim == "franchise":
        # Pour le moment on utilise le champ tmdb_collection_name si present
        coll = row.get("tmdb_collection_name")
        return str(coll).strip() if coll else None
    if dim == "director":
        # Non dispo directement dans build_library_rows, retourne None
        return None
    if dim == "decade":
        year = int(row.get("year") or 0)
        if year == 0:
            return None
        return f"{(year // 10) * 10}s"
    if dim == "codec":
        codec = str(row.get("codec") or "").strip()
        return codec.upper() if codec and codec != "unknown" else None
    if dim == "era_grain":
        era = row.get("grain_era_v2")
        return str(era) if era else None
    if dim == "resolution":
        res = str(row.get("resolution") or "").strip()
        return res.upper() if res and res != "unknown" else None
    return None


# ---------------------------------------------------------------------------
# Vague P / VP-G : Field locks UI endpoints (cablage final integration)
# ---------------------------------------------------------------------------
# Audit prealable VP-G (cf docs/internal/AUDIT_VP_G_LIB_VALIDATION_V5_LEGACY.md)
# a identifie 3 endpoints attendus par `web/dashboard/views/library/lib-validation.js`
# mais inexistants cote backend : `library/set_field_lock`,
# `library/clear_field_lock`, `library/list_field_locks`.
#
# Le repository `FieldLocksRepository` existe deja (cf
# `cinesort/infra/db/repositories/field_locks.py`). On ajoute juste la couche
# UI/facade pour exposer les routes via introspection
# `rest_server._get_api_methods` (pass 2 `/api/library/{method}`).
#
# Memo `feedback_cinesort_v76_ui` : endpoints dans `library_support.py`,
# pas dans un controller. Pas de duplication de logique : delegation au repo.


_VALID_LOCK_SOURCES = {
    "ui_lock",
    "manual_identify",
    "user_edit",
    "auto_match",
}


def _get_field_locks_repo_safe(api: Any):
    """Acces best-effort au FieldLocksRepository (sans crash si infra HS).

    Retourne None si infra non disponible ou si l'attribut `field_locks`
    n'existe pas sur le store (cas tests legers).
    """
    store = _get_store(api)
    if store is None:
        return None
    return getattr(store, "field_locks", None)


def set_field_lock(
    api: Any,
    film_id: str,
    field_name: str,
    locked_value: Any = None,
    source: str = "ui_lock",
) -> Dict[str, Any]:
    """Vague P / VP-G : pose un verrou sur un champ d'un film.

    Args:
        film_id: cle stable du film (`tmdb:<id>` ou `path:<sha1>`).
        field_name: nom du champ a verrouiller (ex. "title", "year").
        locked_value: valeur a verrouiller (serialisee JSON cote repo).
        source: origine du lock (`ui_lock` par defaut, audit only).

    Returns:
        `{ok: True, locked_at: float}` en cas de succes,
        `{ok: False, message: ..., user_message: ...}` sinon.
    """
    fid = str(film_id or "").strip()
    fname = str(field_name or "").strip()
    if not fid:
        return _err_response("film_id requis.", category="validation", level="info", log_module=__name__)
    if not fname:
        return _err_response("field_name requis.", category="validation", level="info", log_module=__name__)

    src = str(source or "ui_lock").strip().lower()
    if src not in _VALID_LOCK_SOURCES:
        src = "ui_lock"

    repo = _get_field_locks_repo_safe(api)
    if repo is None:
        return _err_response(
            "Store SQLite indisponible (field_locks).",
            category="runtime",
            level="error",
            log_module=__name__,
        )
    try:
        res = repo.set_lock(fid, fname, locked_value, source=src)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        return _err_response(
            f"Persistance lock echouee : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )
    if not res or not res.get("ok"):
        return _err_response(
            str((res or {}).get("reason") or "set_lock refuse"),
            category="validation",
            level="info",
            log_module=__name__,
        )
    return {
        "ok": True,
        "film_id": fid,
        "field_name": fname,
        "locked_at": float(res.get("locked_at") or 0.0),
        "source": src,
    }


def clear_field_lock(api: Any, film_id: str, field_name: str) -> Dict[str, Any]:
    """Vague P / VP-G : retire un verrou champ-par-champ.

    Returns:
        `{ok: True, removed: bool, film_id, field_name}` en cas de succes,
        `{ok: False, ...}` sinon. `removed=False` si aucun lock n'existait
        (idempotence OK, ce n'est pas une erreur).
    """
    fid = str(film_id or "").strip()
    fname = str(field_name or "").strip()
    if not fid:
        return _err_response("film_id requis.", category="validation", level="info", log_module=__name__)
    if not fname:
        return _err_response("field_name requis.", category="validation", level="info", log_module=__name__)

    repo = _get_field_locks_repo_safe(api)
    if repo is None:
        return _err_response(
            "Store SQLite indisponible (field_locks).",
            category="runtime",
            level="error",
            log_module=__name__,
        )
    try:
        res = repo.clear_lock(fid, fname)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        return _err_response(
            f"Suppression lock echouee : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )
    return {
        "ok": True,
        "removed": bool((res or {}).get("removed")),
        "film_id": fid,
        "field_name": fname,
    }


def list_field_locks(api: Any, film_id: str) -> Dict[str, Any]:
    """Vague P / VP-G : liste tous les verrous d'un film.

    Returns:
        `{ok: True, film_id, locks: [...]}` ou erreur.

    Chaque lock = `{field_name, locked_value, locked_at, source, run_id, row_id}`.
    """
    fid = str(film_id or "").strip()
    if not fid:
        return _err_response("film_id requis.", category="validation", level="info", log_module=__name__)

    repo = _get_field_locks_repo_safe(api)
    if repo is None:
        # Best-effort : si le store est HS, on renvoie liste vide plutot
        # qu'une erreur dure -> UI affiche "aucun lock" et ne bloque pas
        # l'utilisateur. Symetrie avec _list_locked_field_names dans
        # library_actions_support.
        logger.debug("list_field_locks : repo indisponible, retour liste vide")
        return {"ok": True, "film_id": fid, "locks": []}
    try:
        locks = repo.list_locks(fid)
    except (OSError, AttributeError, TypeError, ValueError) as exc:
        logger.warning("list_field_locks repo error film_id=%s: %s", fid, exc)
        return {"ok": True, "film_id": fid, "locks": []}
    return {"ok": True, "film_id": fid, "locks": list(locks or [])}

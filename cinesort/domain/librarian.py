"""Mode bibliothecaire — suggestions proactives pour la sante de la bibliotheque.

Analyse les PlanRows et quality reports pour generer des suggestions
d'amelioration triees par priorite.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set

# Fix audit 2026-05-26 (v1.5.6) Vague L (subs-1) : reutilise la normalisation de
# langue partagee pour que la detection "sans subs FR" cote Qualite/health
# (generate_suggestions) consomme EXACTEMENT la meme source de verite que la vue
# Bibliotheque (library_support._build_library_rows) : union des sous-titres
# externes (PlanRow.subtitle_languages) + pistes EMBARQUEES persistees dans
# quality_reports.metrics.subtitles_embedded. Avant, generate_suggestions
# ignorait les embedded -> divergence de comptage entre les 2 vues (BUG 2 Vague I
# faussement corrige).
from cinesort.domain.subtitle_helpers import _normalize_iso639

# Codecs video consideres comme obsoletes
_OBSOLETE_CODECS = frozenset({"mpeg4", "xvid", "divx", "wmv", "mpeg2", "mpeg1"})

# Priorites
_PRIORITY_HIGH = "high"
_PRIORITY_MEDIUM = "medium"
_PRIORITY_LOW = "low"

# Ordre de tri des priorites
_PRIORITY_ORDER = {_PRIORITY_HIGH: 0, _PRIORITY_MEDIUM: 1, _PRIORITY_LOW: 2}


# 164L : analyse de 6 categories de suggestions — lineaire, chaque
# bloc est independant. Proche du seuil 150L, pipeline de detection.
def generate_suggestions(
    rows: List[Any],
    quality_reports: List[Dict[str, Any]],
    settings: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Genere les suggestions bibliothecaire et le health score.

    Retourne un dict avec :
    - suggestions: liste triee par priorite puis count desc
    - health_score: 0-100 (% de films sans probleme)
    """
    if not rows:
        return {"suggestions": [], "health_score": 100}

    s = settings or {}
    expected_langs = s.get("subtitle_expected_languages") or ["fr"]
    if isinstance(expected_langs, str):
        expected_langs = [l.strip() for l in expected_langs.split(",") if l.strip()]
    # Fix audit 2026-05-26 (v1.5.6) Vague L (subs-3) : normaliser les langues
    # ATTENDUES via _LANG_MAP avant comparaison (symetrie). Une saisie
    # 'french'/'francais'/'fra'/'fre' doit matcher 'fr'. On garde une version
    # brute (pour l'affichage du libelle) et une version normalisee (pour la
    # comparaison). Les tags non resolvables retombent sur leur forme lower().
    expected_norm: List[str] = []
    for raw in expected_langs:
        norm = _normalize_iso639(raw) or str(raw).strip().lower()
        if norm and norm not in expected_norm:
            expected_norm.append(norm)

    # Index quality reports par row_id
    qr_by_id: Dict[str, Dict[str, Any]] = {}
    for qr in quality_reports or []:
        rid = str(qr.get("row_id") or "")
        if rid:
            qr_by_id[rid] = qr

    # Ensembles de row_ids par probleme (pour le health score)
    problem_ids: Set[str] = set()
    suggestions: List[Dict[str, Any]] = []

    # --- A. Codecs obsoletes ---
    obsolete_films: List[str] = []
    obsolete_codecs_seen: Set[str] = set()
    for qr in quality_reports or []:
        metrics = qr.get("metrics") if isinstance(qr.get("metrics"), dict) else {}
        detected = metrics.get("detected") or {}
        codec = str(detected.get("video_codec") or "").strip().lower()
        if codec in _OBSOLETE_CODECS:
            rid = str(qr.get("row_id") or "")
            title = str(detected.get("title") or rid)
            obsolete_films.append(title)
            obsolete_codecs_seen.add(codec)
            problem_ids.add(rid)
    if obsolete_films:
        codecs_label = ", ".join(sorted(obsolete_codecs_seen)).upper()
        suggestions.append(
            {
                "id": "codec_obsolete",
                "priority": _PRIORITY_HIGH,
                "message": f"{len(obsolete_films)} film(s) utilisent des codecs obsoletes ({codecs_label})",
                "count": len(obsolete_films),
                "details": obsolete_films[:5],
            }
        )

    # --- B. Doublons ---
    dup_films: List[str] = []
    for row in rows:
        flags = getattr(row, "warning_flags", None) or []
        if isinstance(flags, str):
            flags = flags.split("|")
        has_dup = any("duplicate" in str(f).lower() for f in flags)
        if has_dup:
            rid = str(getattr(row, "row_id", ""))
            title = str(getattr(row, "proposed_title", "") or rid)
            dup_films.append(title)
            problem_ids.add(rid)
    if dup_films:
        suggestions.append(
            {
                "id": "duplicates",
                "priority": _PRIORITY_HIGH,
                "message": f"{len(dup_films)} film(s) possiblement en double",
                "count": len(dup_films),
                "details": dup_films[:5],
            }
        )

    # --- C. Sous-titres manquants ---
    # Fix audit 2026-05-26 (v1.5.6) Vague L (subs-1) : MEME source de verite que
    # library_support._build_library_rows. On fusionne :
    #   - langues EXTERNES detectees au scan (PlanRow.subtitle_languages)
    #   - langues EMBARQUEES persistees dans quality_reports.metrics.subtitles_embedded
    # toutes normalisees via _normalize_iso639 ('fra'/'fre'/'french' -> 'fr').
    # Une langue attendue est "manquante" si elle n'est PAS dans cette union.
    # Avant : on lisait seulement PlanRow.subtitle_missing_langs (calcule au scan
    # SANS les pistes embarquees) -> divergence avec la vue Bibliotheque.
    missing_sub_films: List[str] = []
    for row in rows:
        rid = str(getattr(row, "row_id", ""))

        # Langues presentes : externes (PlanRow) ∪ embarquees (quality_report)
        present_langs: Set[str] = set()
        external = getattr(row, "subtitle_languages", None) or []
        if isinstance(external, str):
            external = external.split("|")
        for lang in external:
            norm = _normalize_iso639(lang) or str(lang).strip().lower()
            if norm:
                present_langs.add(norm)

        qr = qr_by_id.get(rid) or {}
        qr_metrics = qr.get("metrics") if isinstance(qr.get("metrics"), dict) else {}
        embedded = qr_metrics.get("subtitles_embedded")
        if isinstance(embedded, list):
            for track in embedded:
                if not isinstance(track, dict):
                    continue
                raw_lang = (track.get("language") or "").strip().lower()
                if not raw_lang:
                    continue
                norm = _normalize_iso639(raw_lang)
                if norm:
                    present_langs.add(norm)

        if any(lang not in present_langs for lang in expected_norm):
            title = str(getattr(row, "proposed_title", "") or rid)
            missing_sub_films.append(title)
            problem_ids.add(rid)
    if missing_sub_films:
        lang_label = ", ".join(expected_langs)
        suggestions.append(
            {
                "id": "missing_subtitles",
                "priority": _PRIORITY_MEDIUM,
                "message": f"{len(missing_sub_films)} film(s) sans sous-titres {lang_label}",
                "count": len(missing_sub_films),
                "details": missing_sub_films[:5],
            }
        )

    # --- D. Films non identifies ---
    unidentified_films: List[str] = []
    for row in rows:
        src = str(getattr(row, "proposed_source", "") or "").strip().lower()
        conf = int(getattr(row, "confidence", 0) or 0)
        if src in ("unknown", "") or conf == 0:
            rid = str(getattr(row, "row_id", ""))
            title = str(getattr(row, "proposed_title", "") or rid)
            unidentified_films.append(title)
            problem_ids.add(rid)
    if unidentified_films:
        suggestions.append(
            {
                "id": "unidentified",
                "priority": _PRIORITY_MEDIUM,
                "message": f"{len(unidentified_films)} film(s) non identifies par TMDb",
                "count": len(unidentified_films),
                "details": unidentified_films[:5],
            }
        )

    # --- E. Basse resolution (SD uniquement) ---
    low_res_films: List[str] = []
    for qr in quality_reports or []:
        metrics = qr.get("metrics") if isinstance(qr.get("metrics"), dict) else {}
        detected = metrics.get("detected") or {}
        res = str(detected.get("resolution") or "").strip().lower()
        if res in ("sd", ""):
            height = int(detected.get("height") or 0)
            if 0 < height < 680:
                rid = str(qr.get("row_id") or "")
                title = str(detected.get("title") or rid)
                low_res_films.append(title)
                problem_ids.add(rid)
    if low_res_films:
        suggestions.append(
            {
                "id": "low_resolution",
                "priority": _PRIORITY_LOW,
                "message": f"{len(low_res_films)} film(s) en resolution SD",
                "count": len(low_res_films),
                "details": low_res_films[:5],
            }
        )

    # --- F. Collections TMDb (informatif) ---
    collections: Dict[int, Dict[str, Any]] = {}
    for row in rows:
        cid = getattr(row, "tmdb_collection_id", None)
        cname = str(getattr(row, "tmdb_collection_name", "") or "").strip()
        if cid and cname:
            if cid not in collections:
                collections[cid] = {"name": cname, "count": 0}
            collections[cid]["count"] += 1
    if collections:
        total_in_sagas = sum(c["count"] for c in collections.values())
        suggestions.append(
            {
                "id": "collections_info",
                "priority": _PRIORITY_LOW,
                "message": f"{total_in_sagas} film(s) dans {len(collections)} saga(s) TMDb",
                "count": total_in_sagas,
                "details": [
                    f"{c['name']} ({c['count']})" for c in sorted(collections.values(), key=lambda x: -x["count"])
                ][:5],
            }
        )

    # --- Tri : priorite puis count desc ---
    suggestions.sort(key=lambda x: (_PRIORITY_ORDER.get(x["priority"], 9), -x["count"]))

    # --- Health score ---
    total_rows = len(rows)
    healthy = total_rows - len(problem_ids)
    health_score = round(100 * healthy / total_rows) if total_rows > 0 else 100

    return {"suggestions": suggestions, "health_score": health_score}

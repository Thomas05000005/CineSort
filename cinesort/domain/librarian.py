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
from cinesort.domain.confidence_thresholds import CONF_MEDIUM
from cinesort.domain.subtitle_helpers import _normalize_iso639

# Codecs video consideres comme obsoletes
_OBSOLETE_CODECS = frozenset({"mpeg4", "xvid", "divx", "wmv", "mpeg2", "mpeg1"})

# Priorites
_PRIORITY_HIGH = "high"
_PRIORITY_MEDIUM = "medium"
_PRIORITY_LOW = "low"

# Ordre de tri des priorites
_PRIORITY_ORDER = {_PRIORITY_HIGH: 0, _PRIORITY_MEDIUM: 1, _PRIORITY_LOW: 2}


def row_unidentified(row: Dict[str, Any]) -> bool:
    """True si le film n'a PAS pu etre identifie (titre+annee fiables).

    AUDIT 2026-07-15 (M2) : DEFINITION UNIQUE partagee. Avant, la carte Accueil
    "films non identifies" (librarian, section D) rendait un verdict OPPOSE au
    chip Bibliotheque (`identified` via ce predicat) sur le MEME film : elle
    ignorait `tmdb_id` ET `proposed_year` et utilisait `confidence == 0` au lieu
    du seuil CONF_MEDIUM. Les deux surfaces consomment desormais CE predicat.
    library_support._row_unidentified en est un alias (couvert par
    tests/test_identification_nfo_v77.py).

    AUDIT 2026-06-13 (R5-A) : l'ancienne version exigeait `tmdb_id > 0` EN
    PREMIER (`if tmdb_id_int <= 0: return True`). Or l'identification ne passe
    pas forcement par TMDb : un film resolu par fichier NFO ou par parsing du
    nom n'a AUCUN tmdb_id mais EST parfaitement identifie (titre + annee +
    confiance). Sur une biblio reelle 100% NFO (TMDb desactive), ce bug
    classait les 1027 films "non identifies" et affichait "Identifier" partout.
    Le tmdb_id ne sert qu'aux jaquettes / au match Jellyfin, PAS a decider de
    l'identification.

    Critere :
    - tmdb_id resolu (> 0) => identifie (raccourci suffisant).
    - sinon : identifie si proposed_source est fiable (nfo / name / tmdb /
      imdb ...), confiance >= CONF_MEDIUM (60) ET une annee est resolue.
    - non identifie si source unknown/vide, confiance < CONF_MEDIUM, ou annee absente.

    Le predicat accepte un dict (row Library expose `year`, PlanRow `proposed_year`).
    """
    tmdb_id = row.get("tmdb_id")
    try:
        if tmdb_id is not None and int(tmdb_id) > 0:
            return False  # tmdb_id resolu : identifie (raccourci).
    except (TypeError, ValueError):
        pass
    src = str(row.get("proposed_source") or "").strip().lower()
    if src in ("", "unknown"):
        return True
    if int(row.get("confidence") or 0) < CONF_MEDIUM:
        return True
    # La row Library expose `year`, la PlanRow `proposed_year` : on tolere les 2.
    year = int(row.get("proposed_year") or row.get("year") or 0)
    if year <= 0:
        return True
    return False


def resolve_tmdb_id(row: Any) -> Optional[int]:
    """Resoud le tmdb_id EFFECTIF d'une PlanRow : top-level d'abord, puis le
    candidat de meilleur score (>= 0.7) porteur d'un tmdb_id valide, sinon None.

    AUDIT 2026-07-15 (M2, suivi) : MIROIR EXACT du resolveur du chip Bibliotheque
    (library_support._build_library_rows._resolve_tmdb_id). La carte Accueil
    (generate_suggestions, section D) nourrissait row_unidentified avec
    `getattr(row, "tmdb_id")` BRUT. Or PlanRow.tmdb_id top-level est TOUJOURS None
    apres scan : le linker ecrit le tmdb_id sur les Candidate ENFANTS, pas au
    top-level du row (cf. commentaire library_support v1.5.5 Vague J). Le chip,
    lui, resolvait deja depuis les candidats -> le raccourci `tmdb_id > 0` de
    row_unidentified ne se declenchait JAMAIS cote Accueil et les 2 surfaces
    rendaient des verdicts OPPOSES sur les films identifies uniquement par un
    candidat (match TMDb auto sans NFO/nom fiable). On resout donc ICI, en
    DOMAINE, sans importer library_support (inversion de couche interdite).

    Seuil (0.7) et selection (meilleur score) alignes sur le resolveur du chip.
    Accepte des candidats dict (plan.jsonl) OU objets (core.Candidate).
    """
    tid_top = getattr(row, "tmdb_id", None)
    if tid_top:
        try:
            v = int(tid_top)
            if v > 0:
                return v
        except (TypeError, ValueError):
            pass
    # Fallback : meilleur candidat (score >= 0.7) porteur d'un tmdb_id. La liste
    # est deja ordonnee par score desc cote linker domain, mais on selectionne
    # explicitement le max pour ne dependre d'aucun ordre implicite.
    best: Optional[int] = None
    best_score = -1.0
    for cand in getattr(row, "candidates", None) or []:
        cid = cand.get("tmdb_id") if isinstance(cand, dict) else getattr(cand, "tmdb_id", None)
        if not cid:
            continue
        raw_score = cand.get("score") if isinstance(cand, dict) else getattr(cand, "score", None)
        try:
            score = float(raw_score or 0.0)
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
    # AUDIT 2026-07-15 (M2) : delegue au predicat UNIQUE row_unidentified (tmdb_id
    # + source + CONF_MEDIUM + annee), MEME source de verite que le chip
    # Bibliotheque (library_support._row_unidentified). Avant, ce bloc ignorait
    # tmdb_id et proposed_year et testait `conf == 0` -> verdict OPPOSE a la
    # Bibliotheque sur le meme film (ex: tmdb_id resolu + source vide, ou NFO a
    # confiance 45 / sans annee).
    unidentified_films: List[str] = []
    for row in rows:
        row_view = {
            # AUDIT 2026-07-15 (M2, suivi) : tmdb_id RESOLU depuis les candidats
            # (miroir du chip), PAS le top-level BRUT qui est TOUJOURS None apres
            # scan. Sans ca le raccourci `tmdb_id > 0` de row_unidentified restait
            # mort cote Accueil -> divergence avec le chip Bibliotheque sur les
            # films identifies uniquement par un candidat.
            "tmdb_id": resolve_tmdb_id(row),
            "proposed_source": getattr(row, "proposed_source", None),
            "confidence": getattr(row, "confidence", 0),
            "proposed_year": getattr(row, "proposed_year", 0),
        }
        if row_unidentified(row_view):
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

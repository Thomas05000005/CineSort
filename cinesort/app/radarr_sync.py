"""Synchronisation Radarr — matching, rapport, detection d'upgrade.

Compare la bibliotheque locale avec Radarr et identifie les films
candidats a un upgrade automatique.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

# Codecs obsoletes (meme liste que librarian.py)
_OBSOLETE_CODECS = frozenset({"mpeg4", "xvid", "divx", "wmv", "mpeg2", "mpeg1"})

# Score seuil pour proposer un upgrade
_UPGRADE_SCORE_THRESHOLD = 54

# Warnings d'encode que Radarr peut resoudre
_UPGRADE_ENCODE_FLAGS = frozenset({"upscale_suspect", "reencode_degraded"})


from cinesort.app._path_utils import normalize_path as _normalize_path


def _extract_local_tmdb_id(row: Any) -> Optional[int]:
    candidates = getattr(row, "candidates", None) or []
    for c in candidates:
        tid = getattr(c, "tmdb_id", None)
        if tid and isinstance(tid, int) and tid > 0:
            return tid
    return None


def build_radarr_report(
    local_rows: List[Any],
    radarr_movies: List[Dict[str, Any]],
    quality_reports: Dict[str, Dict[str, Any]],
    profiles: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare films locaux avec Radarr. Retourne le rapport enrichi."""
    from cinesort.app._fuzzy_utils import normalize_for_fuzzy

    # Index Radarr par tmdb_id
    radarr_by_tmdb: Dict[int, Dict[str, Any]] = {}
    radarr_by_path: Dict[str, Dict[str, Any]] = {}
    radarr_by_title_year: Dict[str, Dict[str, Any]] = {}
    # Cf issue #29 : pre-index Radarr par annee avec titres normalises pour
    # fuzzy vectorise. dict[year] -> list[(normalized_title, movie_dict)].
    radarr_by_year_normalized: Dict[int, List[tuple[str, Dict[str, Any]]]] = {}
    for m in radarr_movies:
        tid = int(m.get("tmdb_id") or 0)
        if tid > 0:
            radarr_by_tmdb[tid] = m
        p = _normalize_path(m.get("path") or "")
        if p:
            radarr_by_path[p] = m
        name = str(m.get("title") or "").strip().lower()
        year = int(m.get("year") or 0)
        if name and year:
            radarr_by_title_year[f"{name}|{year}"] = m
            norm = normalize_for_fuzzy(m.get("title") or "")
            if norm:
                radarr_by_year_normalized.setdefault(year, []).append((norm, m))

    profile_map = {int(p.get("id") or 0): str(p.get("name") or "") for p in profiles}

    matched: List[Dict[str, Any]] = []
    not_in_radarr: List[Dict[str, Any]] = []

    for row in local_rows:
        title = str(getattr(row, "proposed_title", "") or "")
        year = int(getattr(row, "proposed_year", 0) or 0)
        local_tmdb = _extract_local_tmdb_id(row)
        folder = str(getattr(row, "folder", "") or "")
        video = str(getattr(row, "video", "") or "")
        row_id = str(getattr(row, "row_id", "") or "")

        rm: Optional[Dict[str, Any]] = None
        # Niveau 1 : tmdb_id
        if local_tmdb and local_tmdb in radarr_by_tmdb:
            rm = radarr_by_tmdb[local_tmdb]
        # Niveau 2 : chemin
        if not rm:
            local_path = _normalize_path(os.path.join(folder, video)) if video else ""
            if local_path and local_path in radarr_by_path:
                rm = radarr_by_path[local_path]
        # Niveau 3 : titre+annee (exact puis fuzzy)
        if not rm and title and year:
            key = f"{title.strip().lower()}|{year}"
            if key in radarr_by_title_year:
                rm = radarr_by_title_year[key]
            else:
                # Fallback fuzzy vectorise (cf issue #29 : remplace boucle O(n*m)).
                # On utilise rapidfuzz.process.extractOne sur les titres pre-normalises
                # de l'annee, ce qui delegue la comparaison au C natif.
                from rapidfuzz import fuzz, process

                candidates = radarr_by_year_normalized.get(year, [])
                if candidates:
                    query_norm = normalize_for_fuzzy(title)
                    if query_norm:
                        norm_titles = [c[0] for c in candidates]
                        best = process.extractOne(
                            query_norm,
                            norm_titles,
                            scorer=fuzz.ratio,
                            score_cutoff=85,
                        )
                        if best is not None:
                            _, _, idx = best
                            rm = candidates[idx][1]

        if rm:
            pid = int(rm.get("quality_profile_id") or 0)
            matched.append(
                {
                    "row_id": row_id,
                    "title": title,
                    "year": year,
                    "radarr_id": int(rm.get("id") or 0),
                    "monitored": bool(rm.get("monitored")),
                    "has_file": bool(rm.get("has_file")),
                    "quality_name": str(rm.get("quality_name") or ""),
                    "profile_name": profile_map.get(pid, "?"),
                }
            )
        else:
            not_in_radarr.append({"row_id": row_id, "title": title, "year": year})

    # Films dans Radarr sans fichier
    wanted = [m for m in radarr_movies if not m.get("has_file") and m.get("monitored")]

    return {
        "total_local": len(local_rows),
        "total_radarr": len(radarr_movies),
        "matched": matched,
        "not_in_radarr": not_in_radarr,
        "wanted": [
            {"title": m.get("title", ""), "year": m.get("year", 0), "radarr_id": m.get("id", 0)} for m in wanted
        ],
        "matched_count": len(matched),
    }


def should_propose_upgrade(
    film_match: Dict[str, Any],
    quality_report: Optional[Dict[str, Any]],
) -> bool:
    """Determine si un upgrade Radarr devrait etre propose pour ce film.

    Criteres : monitored ET (score < 54 OU encode suspect OU codec obsolete).
    """
    if not film_match.get("monitored"):
        return False
    if not quality_report:
        return False

    score = int(quality_report.get("score") or 0)
    if score > 0 and score < _UPGRADE_SCORE_THRESHOLD:
        return True

    # Verifier les encode warnings
    metrics_raw = quality_report.get("metrics")
    metrics = metrics_raw if isinstance(metrics_raw, dict) else {}
    detected = metrics.get("detected") or {}
    codec = str(detected.get("codec") or "").strip().lower()
    if codec in _OBSOLETE_CODECS:
        return True

    # Verifier les flags d'encode du rapport
    reasons = quality_report.get("reasons") or []
    for reason in reasons:
        r = str(reason).lower()
        if "upscale" in r or "reencode" in r:
            return True

    return False


def get_upgrade_candidates(
    report: Dict[str, Any],
    quality_reports: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Retourne les films matches candidats a un upgrade."""
    candidates: List[Dict[str, Any]] = []
    for film in report.get("matched") or []:
        row_id = film.get("row_id", "")
        qr = quality_reports.get(row_id)
        if should_propose_upgrade(film, qr):
            candidates.append(
                {
                    **film,
                    "score": int(qr.get("score") or 0) if qr else 0,
                    "tier": str(qr.get("tier") or "") if qr else "",
                }
            )
    return candidates

"""Validation croisee Jellyfin — compare la bibliotheque locale avec Jellyfin.

Detecte les films manquants dans Jellyfin, les fantomes (dans Jellyfin mais plus
sur le disque), et les divergences de metadonnees (titre, annee).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from cinesort.app._path_utils import normalize_path as _normalize_path


def _extract_local_tmdb_id(row: Any) -> Optional[str]:
    """Extrait le tmdb_id depuis les candidates d'un PlanRow."""
    candidates = getattr(row, "candidates", None) or []
    for c in candidates:
        tid = getattr(c, "tmdb_id", None)
        if tid and int(tid) > 0:
            return str(tid)
    return None


def build_sync_report(
    local_rows: List[Any],
    jellyfin_movies: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare films locaux vs Jellyfin et produit un rapport de coherence.

    Matching 3 niveaux : chemin normalise → tmdb_id → titre+annee.
    """
    # Index Jellyfin par chemin normalise
    jf_by_path: Dict[str, Dict[str, Any]] = {}
    from cinesort.app._fuzzy_utils import normalize_for_fuzzy

    jf_by_tmdb: Dict[str, Dict[str, Any]] = {}
    jf_by_title_year: Dict[str, Dict[str, Any]] = {}
    # Cf issue #29 : pre-index Jellyfin par annee avec titres normalises
    # pour fuzzy vectorise dans la boucle d'identification.
    jf_by_year_normalized: Dict[int, List[tuple[str, Dict[str, Any]]]] = {}

    for movie in jellyfin_movies:
        norm_p = _normalize_path(movie.get("path") or "")
        if norm_p:
            jf_by_path[norm_p] = movie
        tid = movie.get("tmdb_id")
        if tid:
            jf_by_tmdb[str(tid)] = movie
        name = (movie.get("name") or "").strip().lower()
        year = int(movie.get("year") or 0)
        if name and year:
            jf_by_title_year[f"{name}|{year}"] = movie
            norm = normalize_for_fuzzy(movie.get("name") or "")
            if norm:
                jf_by_year_normalized.setdefault(year, []).append((norm, movie))

    matched: List[Dict[str, Any]] = []
    missing_in_jellyfin: List[Dict[str, Any]] = []
    metadata_mismatch: List[Dict[str, Any]] = []
    matched_jf_ids: Set[str] = set()

    for row in local_rows:
        folder = str(getattr(row, "folder", "") or "")
        video = str(getattr(row, "video", "") or "")
        local_title = str(getattr(row, "proposed_title", "") or "").strip()
        local_year = int(getattr(row, "proposed_year", 0) or 0)
        local_tmdb_id = _extract_local_tmdb_id(row)

        # Niveau 1 : match par chemin
        local_video_path = _normalize_path(os.path.join(folder, video)) if video else ""
        local_folder_norm = _normalize_path(folder)
        jf_match = None

        if local_video_path and local_video_path in jf_by_path:
            jf_match = jf_by_path[local_video_path]
        elif local_folder_norm:
            # Chercher un film Jellyfin dont le chemin contient le dossier local
            for p, m in jf_by_path.items():
                if p.startswith(local_folder_norm + "/") or p.startswith(local_folder_norm + "\\"):
                    jf_match = m
                    break

        # Niveau 2 : fallback tmdb_id
        if not jf_match and local_tmdb_id and local_tmdb_id in jf_by_tmdb:
            jf_match = jf_by_tmdb[local_tmdb_id]

        # Niveau 3 : fallback titre+annee (exact puis fuzzy)
        if not jf_match and local_title and local_year:
            key = f"{local_title.lower()}|{local_year}"
            if key in jf_by_title_year:
                jf_match = jf_by_title_year[key]
            else:
                # Fallback fuzzy vectorise (cf issue #29 : remplace boucle O(n*m)).
                # rapidfuzz.process.extractOne compare en C natif sur tous les
                # titres pre-normalises de l'annee.
                from rapidfuzz import fuzz, process

                candidates = jf_by_year_normalized.get(local_year, [])
                if candidates:
                    query_norm = normalize_for_fuzzy(local_title)
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
                            jf_match = candidates[idx][1]

        if jf_match:
            jf_id = jf_match.get("id", "")
            matched_jf_ids.add(jf_id)
            matched.append(
                {
                    "local_title": local_title,
                    "local_year": local_year,
                    "jellyfin_title": jf_match.get("name", ""),
                    "jellyfin_year": int(jf_match.get("year") or 0),
                    "jellyfin_id": jf_id,
                }
            )
            # Verifier les divergences de metadonnees
            jf_title = (jf_match.get("name") or "").strip()
            jf_year = int(jf_match.get("year") or 0)
            if jf_title and local_title and jf_title.lower() != local_title.lower():
                metadata_mismatch.append(
                    {
                        "local_title": local_title,
                        "jellyfin_title": jf_title,
                        "field": "title",
                        "jellyfin_id": jf_id,
                    }
                )
            if jf_year and local_year and jf_year != local_year:
                metadata_mismatch.append(
                    {
                        "local_title": local_title,
                        "local_year": local_year,
                        "jellyfin_year": jf_year,
                        "field": "year",
                        "jellyfin_id": jf_id,
                    }
                )
        else:
            missing_in_jellyfin.append(
                {
                    "title": local_title,
                    "year": local_year,
                    "local_path": folder,
                }
            )

    # Fantomes : films Jellyfin sans match local
    ghost_in_jellyfin: List[Dict[str, Any]] = []
    for movie in jellyfin_movies:
        jf_id = movie.get("id", "")
        if jf_id not in matched_jf_ids:
            ghost_in_jellyfin.append(
                {
                    "title": movie.get("name", ""),
                    "year": int(movie.get("year") or 0),
                    "jellyfin_id": jf_id,
                    "jellyfin_path": movie.get("path", ""),
                }
            )

    return {
        "total_local": len(local_rows),
        "total_jellyfin": len(jellyfin_movies),
        "matched": len(matched),
        "missing_in_jellyfin": missing_in_jellyfin,
        "ghost_in_jellyfin": ghost_in_jellyfin,
        "metadata_mismatch": metadata_mismatch,
    }

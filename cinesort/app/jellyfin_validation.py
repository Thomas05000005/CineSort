"""Validation croisee Jellyfin — compare la bibliotheque locale avec Jellyfin.

Detecte les films manquants dans Jellyfin, les fantomes (dans Jellyfin mais plus
sur le disque), et les divergences de metadonnees (titre, annee).
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional, Set

from cinesort.app._fuzzy_utils import normalize_for_fuzzy
from cinesort.app._path_utils import normalize_path as _normalize_path


def _extract_local_tmdb_id(row: Any) -> Optional[str]:
    """Extrait le tmdb_id depuis les candidates d'un PlanRow."""
    candidates = getattr(row, "candidates", None) or []
    for c in candidates:
        tid = getattr(c, "tmdb_id", None)
        if not tid:
            continue
        try:
            if int(tid) > 0:
                return str(tid)
        except (TypeError, ValueError):
            continue
    return None


def _match_under_folder(
    jf_by_path: Dict[str, List[int]],
    local_folder_norm: str,
    video_norm: str,
) -> Optional[int]:
    """Cherche l'item Jellyfin indexe SOUS le dossier local, sans ambiguite.

    Sert quand Jellyfin n'indexe pas le fichier video tel quel : rip BDMV /
    VIDEO_TS indexe par un fichier interne, remux dont l'extension a change...

    Issue #544 — deux garde-fous :

    1. La comparaison se fait sur une FRONTIERE DE SEGMENT (le `/` de garde) et
       jamais sur un simple prefixe de chaine : un dossier « …/Dune » ne peut
       pas capturer « …/Dune 2 ».
    2. Le premier candidat rencontre n'est plus retenu d'office. Si plusieurs
       medias Jellyfin vivent sous le dossier (saga dans un dossier commun,
       edition Theatrical + Director's Cut, film pose a la RACINE de la
       bibliotheque), on tente de departager par le nom du fichier video ; a
       defaut on ne matche PAS et on laisse la main aux niveaux tmdb_id puis
       titre+annee, bien plus surs. Attribuer les metadonnees d'un autre film
       coute plus cher que de le signaler absent : sur un chemin qui peut
       tromper, l'erreur va dans le sens restrictif.

    Rend l'index du film dans `jellyfin_movies`, ou None si aucun candidat
    certain.
    """
    prefix = local_folder_norm + "/"
    target = os.path.basename(video_norm) if video_norm else ""

    total = 0
    first_idx: Optional[int] = None
    named_count = 0
    named_idx: Optional[int] = None

    for p, indexes in jf_by_path.items():
        if not p.startswith(prefix):
            continue
        is_named = bool(target) and os.path.basename(p) == target
        for idx in indexes:
            total += 1
            if first_idx is None:
                first_idx = idx
            if is_named:
                named_count += 1
                if named_idx is None:
                    named_idx = idx
        # Sortie anticipee : des que l'ambiguite est acquise des deux cotes,
        # continuer a balayer ne changerait plus le verdict.
        if total > 1 and (named_count > 1 or not target):
            break

    if total == 1:
        return first_idx
    if named_count == 1:
        return named_idx
    return None


def build_sync_report(
    local_rows: List[Any],
    jellyfin_movies: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Compare films locaux vs Jellyfin et produit un rapport de coherence.

    Matching 3 niveaux : chemin normalise → tmdb_id → titre+annee.
    """
    # Index Jellyfin par chemin normalise. Les index portent la POSITION du film
    # dans `jellyfin_movies` et non le dict lui-meme : c'est cette position qui
    # sert ensuite a marquer les films apparies (cf. issue #452 plus bas).
    # `jf_by_path` est multi-valeur : deux items Jellyfin peuvent porter le meme
    # chemin (doublon d'indexation) — les ecraser rendrait l'appariement muet.
    jf_by_path: Dict[str, List[int]] = {}
    jf_by_tmdb: Dict[str, int] = {}
    jf_by_title_year: Dict[str, int] = {}
    # Cf issue #29 : pre-index Jellyfin par annee avec titres normalises
    # pour fuzzy vectorise dans la boucle d'identification.
    jf_by_year_normalized: Dict[int, List[tuple[str, int]]] = {}

    for jf_pos, movie in enumerate(jellyfin_movies):
        norm_p = _normalize_path(movie.get("path") or "")
        if norm_p:
            jf_by_path.setdefault(norm_p, []).append(jf_pos)
        tid = movie.get("tmdb_id")
        if tid:
            jf_by_tmdb[str(tid)] = jf_pos
        name = (movie.get("name") or "").strip().lower()
        year = int(movie.get("year") or 0)
        if name and year:
            jf_by_title_year[f"{name}|{year}"] = jf_pos
            norm = normalize_for_fuzzy(movie.get("name") or "")
            if norm:
                jf_by_year_normalized.setdefault(year, []).append((norm, jf_pos))

    matched: List[Dict[str, Any]] = []
    missing_in_jellyfin: List[Dict[str, Any]] = []
    metadata_mismatch: List[Dict[str, Any]] = []
    # Issue #452 : on marque les films apparies par leur POSITION, pas par leur
    # id. Un id Jellyfin vide ("" — Plex sans ratingKey, ou fallback
    # get_all_movies quand get_libraries echoue) entrait dans le set et
    # excluait ensuite TOUS les films sans id de la detection des fantomes.
    # La position identifie chaque film de facon certaine, meme sans id.
    matched_jf_indexes: Set[int] = set()

    for row in local_rows:
        folder = str(getattr(row, "folder", "") or "")
        video = str(getattr(row, "video", "") or "")
        local_title = str(getattr(row, "proposed_title", "") or "").strip()
        local_year = int(getattr(row, "proposed_year", 0) or 0)
        local_tmdb_id = _extract_local_tmdb_id(row)

        # Niveau 1 : match par chemin
        local_video_path = _normalize_path(os.path.join(folder, video)) if video else ""
        local_folder_norm = _normalize_path(folder)
        jf_idx: Optional[int] = None

        # 1a : chemin de FICHIER exact. Un chemin porte par plusieurs items
        # Jellyfin ne designe personne : on ne devine pas (issue #544).
        if local_video_path:
            exact = jf_by_path.get(local_video_path) or []
            if len(exact) == 1:
                jf_idx = exact[0]
        # 1b : media indexe SOUS le dossier local, si et seulement si le
        # candidat est unique ou departage par le nom du fichier video.
        if jf_idx is None and local_folder_norm:
            jf_idx = _match_under_folder(jf_by_path, local_folder_norm, local_video_path)

        # Niveau 2 : fallback tmdb_id
        if jf_idx is None and local_tmdb_id and local_tmdb_id in jf_by_tmdb:
            jf_idx = jf_by_tmdb[local_tmdb_id]

        # Niveau 3 : fallback titre+annee (exact puis fuzzy)
        if jf_idx is None and local_title and local_year:
            key = f"{local_title.lower()}|{local_year}"
            if key in jf_by_title_year:
                jf_idx = jf_by_title_year[key]
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
                            jf_idx = candidates[idx][1]

        if jf_idx is not None:
            jf_match = jellyfin_movies[jf_idx]
            jf_id = jf_match.get("id", "")
            matched_jf_indexes.add(jf_idx)
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

    # Fantomes : films Jellyfin sans match local. Issue #452 : le test porte sur
    # la POSITION, donc un film sans id est juge sur son appariement reel et non
    # sur une chaine vide partagee avec tous les autres films sans id.
    ghost_in_jellyfin: List[Dict[str, Any]] = []
    for ghost_pos, movie in enumerate(jellyfin_movies):
        if ghost_pos not in matched_jf_indexes:
            ghost_in_jellyfin.append(
                {
                    "title": movie.get("name", ""),
                    "year": int(movie.get("year") or 0),
                    "jellyfin_id": movie.get("id", ""),
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

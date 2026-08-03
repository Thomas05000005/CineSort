"""Vague P / VP-C : identite stable d'un film pour les field_locks.

Le challenge : un film n'a pas toujours d'id TMDb (pas encore matche, ou
match impossible). On a quand meme besoin d'une cle stable pour
verrouiller un champ (titre, annee, ...) AVANT le Identify manuel.

Strategie Jellyfin-style : deux formats de cle, transition explicite.
    - "tmdb:<id>"    : l'id TMDb canonique quand connu (preferred).
    - "path:<sha1>"  : sha1 du couple (folder, video) sinon.

Lors de la transition `path: -> tmdb:` (Identify manuel reussi ou
rematch automatique), `migrate_locks(old_film_id, new_film_id)` du
repository `field_locks` migre TOUS les locks de l'ancien id vers le
nouveau (fix #5 ROADMAP_VAGUE_P.md).

Module strictement domain (pas d'import de `app`, `infra`, `ui`) : valide
par import-linter en CI.
"""

from __future__ import annotations

import hashlib
from typing import Any, Mapping


def compute_film_id(row: Mapping[str, Any]) -> str:
    """Calcule la cle stable d'un film pour les field_locks.

    Args:
        row: dict-like avec au minimum `folder` + `video` (ou `video_filename`).
            Si `tmdb_id` ou `proposed_tmdb_id` est non vide / non zero,
            on prefere ce format "tmdb:<id>".

    Returns:
        - "tmdb:<id>" si un id TMDb est connu (tmdb_id ou proposed_tmdb_id).
        - "path:<sha1>" sinon, sha1 sur "<folder>|<video>".
        - "path:unknown" si la row est vide / illisible (cas pathologique).

    Idempotence garantie : meme row -> meme film_id, peu importe l'ordre
    des cles ou la presence de champs additionnels.
    """
    tmdb_id = _coerce_tmdb_id(row)
    if tmdb_id > 0:
        return f"tmdb:{tmdb_id}"

    folder = _safe_str(row.get("folder"))
    video = _safe_str(row.get("video")) or _safe_str(row.get("video_filename"))
    if not folder and not video:
        return "path:unknown"

    key = f"{folder}|{video}".encode("utf-8", errors="replace")
    # nosec B324 : sha1 ici n'est pas un hash de securite — c'est juste
    # une cle stable courte (40 hex chars) pour un index SQLite. Pas de
    # risque cryptographique.
    digest = hashlib.sha1(key, usedforsecurity=False).hexdigest()  # type: ignore[call-arg]
    return f"path:{digest}"


def is_tmdb_film_id(film_id: str) -> bool:
    """True si le film_id est au format `tmdb:<id>` (canonique)."""
    return isinstance(film_id, str) and film_id.startswith("tmdb:")


def is_path_film_id(film_id: str) -> bool:
    """True si le film_id est au format `path:<sha1>` (fallback)."""
    return isinstance(film_id, str) and film_id.startswith("path:")


def extract_tmdb_id(film_id: str) -> int:
    """Extrait l'id TMDb d'un film_id `tmdb:<id>`. Retourne 0 si invalide."""
    if not is_tmdb_film_id(film_id):
        return 0
    raw = film_id[len("tmdb:") :]
    try:
        return int(raw)
    except (TypeError, ValueError):
        return 0


def _coerce_tmdb_id(row: Mapping[str, Any]) -> int:
    """Recupere un id TMDb depuis row, priorisant tmdb_id sur proposed_tmdb_id.

    Tolere les variantes (str, int, None, float). 0 si pas d'id valide.
    """
    for key in ("tmdb_id", "proposed_tmdb_id"):
        raw = row.get(key)
        if raw is None:
            continue
        try:
            val = int(raw)
        except (TypeError, ValueError):
            continue
        if val > 0:
            return val
    return 0


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value).strip()
    except (TypeError, ValueError):
        return ""


__all__ = [
    "compute_film_id",
    "is_tmdb_film_id",
    "is_path_film_id",
    "extract_tmdb_id",
]

"""Synchronisation des statuts watched Jellyfin avant/apres apply.

Phase 2 : snapshot de l'etat vu/pas vu avant les renames, puis restauration
apres le refresh Jellyfin, en retrouvant les films par leur nouveau chemin.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List

from cinesort.app._path_utils import normalize_path as _normalize_path

_log = logging.getLogger(__name__)

# -- Constantes --------------------------------------------------------

_REINDEX_INITIAL_DELAY_S = 5.0
_REINDEX_RETRY_DELAY_S = 5.0
# H-11 audit QA 20260429 : passe de 2 a 5 retries pour absorber les
# Jellyfin lents a re-indexer (NAS reseau, gros catalogues). Avec backoff
# exponentiel on attend max 5+10+20+40+60 = 135s avant de declarer not_found.
_MAX_RETRIES = 5
# Cap pour eviter d'attendre 5 minutes par retry sur de tres longs delais
_MAX_RETRY_DELAY_S = 60.0


def _compute_retry_delay(attempt: int, base_delay_s: float) -> float:
    """H-11 : backoff exponentiel cap a _MAX_RETRY_DELAY_S.

    attempt=1 (1er retry apres echec initial) -> base
    attempt=2 -> base * 2
    attempt=3 -> base * 4
    ... cap a _MAX_RETRY_DELAY_S
    """
    if attempt < 1:
        return base_delay_s
    delay = base_delay_s * (2 ** (attempt - 1))
    return min(delay, _MAX_RETRY_DELAY_S)


# -- Dataclasses -------------------------------------------------------


@dataclass(frozen=True)
class WatchedInfo:
    """Etat watched d'un film a un instant donne."""

    played: bool
    play_count: int
    last_played_date: str


@dataclass
class RestoreResult:
    """Resume de la restauration des statuts watched."""

    restored: int = 0
    skipped: int = 0
    not_found: int = 0
    errors: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour serialisation JSON."""
        return {
            "restored": self.restored,
            "skipped": self.skipped,
            "not_found": self.not_found,
            "errors": self.errors,
            "details": self.details,
        }


# -- Helpers -----------------------------------------------------------


def _build_path_mapping(operations: List[Dict[str, Any]]) -> Dict[str, str]:
    """Construit le mapping ancien_chemin -> nouveau_chemin depuis les operations apply.

    Format des operations (depuis apply_operations SQLite) :
    - op_type : MOVE, RENAME, MOVE_FILE, etc.
    - src_path / dst_path : chemins source et destination
    - undo_status : PENDING (= reussi), DONE, FAILED
    """
    mapping: Dict[str, str] = {}
    for op in operations:
        op_type = (op.get("op_type") or "").upper()
        if op_type not in ("MOVE", "RENAME", "MOVE_FILE"):
            continue
        # undo_status PENDING = l'operation a ete faite avec succes (pas encore undo)
        undo_status = (op.get("undo_status") or "PENDING").upper()
        if undo_status not in ("PENDING",):
            continue
        src = op.get("src_path", "")
        dst = op.get("dst_path", "")
        if src and dst:
            mapping[_normalize_path(src)] = _normalize_path(dst)
    return mapping


# -- API publique ------------------------------------------------------


def snapshot_watched(client: Any, user_id: str) -> Dict[str, WatchedInfo]:
    """Capture l'etat watched de tous les films Jellyfin.

    Retourne un dict {chemin_normalise: WatchedInfo} pour les films marques comme vus.
    Seuls les films avec played=True sont inclus (optimisation).
    """
    try:
        # BUG 2 : utiliser le scan multi-library pour avoir tous les films
        movies = client.get_all_movies_from_all_libraries(user_id)
    # except Exception intentionnel : appel client tiers (JellyfinError herite de Exception)
    except Exception as exc:
        _log.warning("Jellyfin sync : echec snapshot watched — %s", exc)
        return {}

    snapshot: Dict[str, WatchedInfo] = {}
    for movie in movies:
        path = movie.get("path", "")
        played = movie.get("played", False)
        if not path or not played:
            continue
        norm = _normalize_path(path)
        snapshot[norm] = WatchedInfo(
            played=True,
            play_count=movie.get("play_count", 0),
            last_played_date=movie.get("last_played_date", ""),
        )

    _log.info("Jellyfin sync : snapshot — %d films marques comme vus", len(snapshot))
    return snapshot


def restore_watched(
    client: Any,
    user_id: str,
    snapshot: Dict[str, WatchedInfo],
    operations: List[Dict[str, Any]],
    *,
    initial_delay_s: float = _REINDEX_INITIAL_DELAY_S,
    retry_delay_s: float = _REINDEX_RETRY_DELAY_S,
    max_retries: int = _MAX_RETRIES,
) -> RestoreResult:
    """Restaure les statuts watched apres apply + refresh Jellyfin.

    1. Construit le mapping ancien_path -> nouveau_path
    2. Attend la re-indexation Jellyfin (delai initial)
    3. Recupere la liste des films avec leurs nouveaux chemins
    4. Match et restaure les statuts
    5. Retry si des films ne sont pas encore indexes
    """
    if not snapshot:
        return RestoreResult()

    path_mapping = _build_path_mapping(operations)
    if not path_mapping:
        _log.info("Jellyfin sync : aucune operation de deplacement, skip restore")
        return RestoreResult(skipped=len(snapshot))

    # Determiner quels films watched ont ete deplaces
    watched_moves: Dict[str, str] = {}  # new_path -> old_path
    for old_norm, new_norm in path_mapping.items():
        if old_norm in snapshot:
            watched_moves[new_norm] = old_norm

    if not watched_moves:
        _log.info("Jellyfin sync : aucun film vu parmi les deplaces, skip restore")
        return RestoreResult(skipped=len(snapshot))

    _log.info(
        "Jellyfin sync : %d films vus deplaces, attente re-indexation (%0.1fs)...",
        len(watched_moves),
        initial_delay_s,
    )

    result = RestoreResult()
    pending = dict(watched_moves)  # new_path -> old_path

    for attempt in range(1, max_retries + 1):
        # H-11 audit QA 20260429 : backoff exponentiel sur les retries
        # (initial_delay sur la 1re tentative, puis exp sur les suivantes).
        if attempt == 1:
            delay = initial_delay_s
        else:
            delay = _compute_retry_delay(attempt - 1, retry_delay_s)
        _log.debug(
            "Jellyfin sync : tentative %d/%d, attente %.1fs avant requete",
            attempt,
            max_retries,
            delay,
        )
        time.sleep(delay)

        # Recuperer la liste Jellyfin actuelle (multi-library pour BUG 2)
        try:
            current_movies = client.get_all_movies_from_all_libraries(user_id)
        except (ConnectionError, OSError, TimeoutError, ValueError) as exc:
            _log.warning("Jellyfin sync : echec recuperation films (tentative %d) — %s", attempt, exc)
            continue

        # Indexer par chemin normalise
        jellyfin_by_path: Dict[str, str] = {}  # norm_path -> item_id
        for movie in current_movies:
            p = _normalize_path(movie.get("path", ""))
            if p:
                jellyfin_by_path[p] = movie.get("id", "")

        # Tenter le match pour les pending
        still_pending: Dict[str, str] = {}
        for new_norm, old_norm in pending.items():
            item_id = jellyfin_by_path.get(new_norm, "")
            if not item_id:
                still_pending[new_norm] = old_norm
                continue

            # Film trouve, restaurer le statut watched
            ok = client.mark_played(user_id, item_id)
            if ok:
                result.restored += 1
                result.details.append(
                    {
                        "action": "restored",
                        "old_path": old_norm,
                        "new_path": new_norm,
                        "item_id": item_id,
                    }
                )
            else:
                result.errors += 1
                result.details.append(
                    {
                        "action": "error",
                        "old_path": old_norm,
                        "new_path": new_norm,
                        "item_id": item_id,
                        "reason": "mark_played failed",
                    }
                )

        pending = still_pending
        if not pending:
            break

        _log.info(
            "Jellyfin sync : tentative %d/%d — %d films non encore indexes",
            attempt,
            max_retries,
            len(pending),
        )

    # Films non retrouves apres toutes les tentatives
    for new_norm, old_norm in pending.items():
        result.not_found += 1
        result.details.append(
            {
                "action": "not_found",
                "old_path": old_norm,
                "new_path": new_norm,
                "reason": "film non retrouve dans Jellyfin apres re-indexation",
            }
        )

    _log.info(
        "Jellyfin sync : restore termine — %d restaures, %d non trouves, %d erreurs",
        result.restored,
        result.not_found,
        result.errors,
    )
    return result

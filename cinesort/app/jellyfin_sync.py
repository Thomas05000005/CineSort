"""Synchronisation des statuts watched Jellyfin avant/apres apply.

Phase 2 : snapshot de l'etat vu/pas vu avant les renames, puis restauration
apres le refresh Jellyfin, en retrouvant les films par leur nouveau chemin.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from cinesort.app._path_utils import normalize_path as _normalize_path

# LOTD-INT-01 : JellyfinError (herite IntegrationError) doit etre catchee par
# la boucle retry, sinon un 404/5xx transitoire abandonne toute la restauration.
from cinesort.infra.jellyfin_client import JellyfinError

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

# Types du journal apply qui deplacent UN FICHIER : le chemin change en entier,
# il se retrouve tel quel dans src_path/dst_path.
_FILE_MOVE_OP_TYPES = frozenset({"MOVE", "RENAME", "MOVE_FILE"})
# Types qui deplacent UN DOSSIER. C'est la voie NOMINALE du tri de films
# (apply_core.apply_single renomme le dossier, jamais le fichier video — cf.
# regle inviolable du projet). src_path/dst_path sont alors des DOSSIERS, alors
# que Jellyfin indexe les films par chemin de FICHIER : le chemin d'un film vu
# n'apparait jamais tel quel dans le journal, il doit etre RE-PREFIXE.
_DIR_MOVE_OP_TYPES = frozenset({"MOVE_DIR"})


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


@dataclass(frozen=True)
class _MoveOp:
    """Un deplacement du journal apply, normalise.

    `is_dir` distingue le deplacement d'un DOSSIER (les chemins qu'il contient
    doivent etre re-prefixes) de celui d'un FICHIER (egalite stricte).
    """

    is_dir: bool
    src: str
    dst: str


@dataclass
class RestoreResult:
    """Resume de la restauration des statuts watched.

    `counters_restored` et `counters_lost` (#535) sont des SOUS-ENSEMBLES de
    `restored` : le statut vu a ete re-affirme dans les deux cas, seul
    l'historique (nombre de lectures + date de derniere lecture) distingue une
    restauration complete d'une restauration partielle.
    """

    restored: int = 0
    skipped: int = 0
    not_found: int = 0
    errors: int = 0
    counters_restored: int = 0
    counters_lost: int = 0
    details: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        """Convertit en dict pour serialisation JSON."""
        return {
            "restored": self.restored,
            "skipped": self.skipped,
            "not_found": self.not_found,
            "errors": self.errors,
            "counters_restored": self.counters_restored,
            "counters_lost": self.counters_lost,
            "details": self.details,
        }


# -- Helpers -----------------------------------------------------------


def _build_move_sequence(operations: List[Dict[str, Any]]) -> List[_MoveOp]:
    """Extrait les deplacements REUSSIS d'un batch apply, dans l'ordre d'execution.

    Format des operations (depuis `apply.list_apply_operations`, deja triees par
    op_index croissant = ordre d'execution) :
    - op_type : MOVE_FILE, MOVE_DIR, QUARANTINE_*, MKDIR...
    - src_path / dst_path : chemins source et destination
    - undo_status : PENDING (= reussi, pas encore annule), DONE, FAILED

    L'ordre est CONSERVE : un meme film peut subir plusieurs deplacements dans
    un batch (renommage du dossier par apply_single, puis deplacement de ce
    dossier sous la racine Collection). Seul un rejeu SEQUENTIEL donne le
    chemin final ; un dict ancien->nouveau perdrait la composition.
    """
    sequence: List[_MoveOp] = []
    for op in operations:
        op_type = (op.get("op_type") or "").upper()
        is_dir = op_type in _DIR_MOVE_OP_TYPES
        if not is_dir and op_type not in _FILE_MOVE_OP_TYPES:
            continue
        # undo_status PENDING = l'operation a ete faite avec succes (pas encore undo)
        undo_status = (op.get("undo_status") or "PENDING").upper()
        if undo_status not in ("PENDING",):
            continue
        src = _normalize_path(op.get("src_path", ""))
        dst = _normalize_path(op.get("dst_path", ""))
        if src and dst:
            sequence.append(_MoveOp(is_dir=is_dir, src=src, dst=dst))
    return sequence


def _remap_path(path: str, sequence: List[_MoveOp]) -> Optional[str]:
    """Rejoue `sequence` sur un chemin de media Jellyfin.

    Rend le chemin FINAL si au moins une operation a touche ce media, sinon
    None (le film n'a pas bouge, ou il vit hors des racines de l'apply).

    Le critere est « touche », PAS « chemin different » : un renommage de
    casse seule (`apply_core._case_only_rename_with_rollback`) produit un
    MOVE_DIR dont src et dst se normalisent a l'identique. Le film a pourtant
    bien ete renomme sur disque, et sur un partage sensible a la casse Jellyfin
    peut le ré-indexer comme un NOUVEL item. On re-affirme donc son statut vu —
    `mark_played` est idempotent, le re-affirmer ne coute rien.
    """
    current = path
    touched = False
    for move in sequence:
        if current == move.src:
            # Deplacement direct du media (fichier, ou dossier quand Jellyfin
            # indexe un rip BDMV/VIDEO_TS par son dossier).
            current = move.dst
            touched = True
        elif move.is_dir and current.startswith(move.src + "/"):
            # Le media est SOUS un dossier deplace : re-prefixation. Le '/' de
            # garde evite qu'un dossier "…/inception" capture "…/inception 2".
            current = move.dst + current[len(move.src) :]
            touched = True
    return current if touched else None


# -- Restauration des compteurs de lecture (#535) ----------------------
#
# `mark_played` ne restaure QUE `played=True`. `play_count` et
# `last_played_date`, captures au snapshot, n'etaient jamais re-emis : un film
# vu 17 fois le 15/01 revenait a « 1 lecture, il y a quelques secondes ».
#
# UNE seule garde encadre le rattrapage : `_counters_are_lost`. Elle repond a
# « Jellyfin a-t-il REELLEMENT perdu l'historique ? » et couvre du meme coup le
# cas « il n'y avait rien a restaurer » (un film vu sans lecture ni date ne peut
# etre en retard sur rien). Une seconde garde « y a-t-il quelque chose a
# restaurer ? » serait strictement subsumee par celle-ci : sa mutation resterait
# VERTE faute de chemin qui l'emprunte seule — une garde qu'aucun test ne peut
# mettre en defaut est une garde qui ment.
#
# Sa raison d'etre : si le serveur a conserve l'item (renommage de casse seule,
# deplacement detecte), son historique est intact ; le re-ecrire n'apporterait
# rien tout en exposant le reste de son UserData (favori, note) a un ecrasement
# par un corps partiel. La comparaison se fait sur l'etat courant DEJA rapatrie
# par la boucle — aucun appel reseau supplementaire.


def _counters_are_lost(info: WatchedInfo, current_play_count: Any, current_last_played: Any) -> bool:
    """True si l'etat COURANT de l'item a perdu l'historique du snapshot.

    Deux motifs INDEPENDANTS, chacun suffisant :
    - le compteur de lectures a recule ;
    - la date de derniere lecture ne correspond plus a celle du snapshot.

    `current_*` viennent de la liste Jellyfin rapatriee en debut de tentative,
    donc AVANT le `mark_played` de cette tentative : on mesure bien l'etat
    laisse par la re-indexation, pas celui que l'on vient d'ecrire.
    """
    try:
        current_count = int(current_play_count or 0)
    except (TypeError, ValueError):
        current_count = 0
    if int(info.play_count or 0) > current_count:
        return True
    return bool(info.last_played_date) and str(current_last_played or "") != info.last_played_date


def _restore_counters(client: Any, user_id: str, item_id: str, info: WatchedInfo) -> bool:
    """Re-emet play_count + last_played_date sur un item. False si perdu.

    Un client sans `update_played_state` (serveur ancien, client duck-type)
    rend False : l'historique EST perdu, on le compte comme tel plutot que de
    laisser croire a une restauration complete.
    """
    updater = getattr(client, "update_played_state", None)
    if not callable(updater):
        _log.warning(
            "Jellyfin sync : client sans update_played_state — item %s restaure sans son historique",
            item_id,
        )
        return False
    try:
        return bool(
            updater(
                user_id,
                item_id,
                play_count=int(info.play_count or 0),
                last_played_date=str(info.last_played_date or ""),
            )
        )
    except JellyfinError as exc:
        _log.warning("Jellyfin sync : echec restauration historique item %s — %s", item_id, exc)
        return False


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

    1. Rejoue les deplacements du batch sur chaque chemin du snapshot
    2. Attend la re-indexation Jellyfin (delai initial)
    3. Recupere la liste des films avec leurs nouveaux chemins
    4. Match et restaure les statuts
    5. Retry si des films ne sont pas encore indexes
    """
    if not snapshot:
        return RestoreResult()

    if not client or not hasattr(client, "mark_played") or not hasattr(client, "get_all_movies_from_all_libraries"):
        _log.warning("jellyfin_sync.restore_watched: client invalide ou methodes manquantes, no-op")
        return RestoreResult(skipped=len(snapshot))

    move_sequence = _build_move_sequence(operations)
    if not move_sequence:
        _log.info("Jellyfin sync : aucune operation de deplacement, skip restore")
        return RestoreResult(skipped=len(snapshot))

    # Determiner quels films watched ont ete deplaces. On part du SNAPSHOT (des
    # chemins de fichier video) et non des operations : un MOVE_DIR ne cite que
    # des dossiers, donc son src_path n'est jamais une cle du snapshot.
    watched_moves: Dict[str, str] = {}  # new_path -> old_path
    for old_norm in snapshot:
        new_norm = _remap_path(old_norm, move_sequence)
        if new_norm is not None:
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
    # R8-080 : new_path -> item_id du dernier mark_played en echec (503/timeout).
    # Permet de compter en 'errors' (et non 'not_found') apres epuisement.
    mark_failed: Dict[str, str] = {}

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
        # LOTD-INT-01 : JellyfinError inclus, sinon l'exception s'echappe.
        except (OSError, ValueError, JellyfinError) as exc:
            _log.warning("Jellyfin sync : echec recuperation films (tentative %d) — %s", attempt, exc)
            continue

        # Indexer par chemin normalise. Issue #566 : plusieurs items Jellyfin
        # peuvent pointer le MEME chemin (doublon reste apres un refresh
        # interrompu, recovery de base, « Force Refresh All Metadata »). Le dict
        # simple ecrasait le premier id en silence — last-write-wins — et
        # `mark_played` repartait alors sur un seul item, possiblement celui qui
        # n'etait pas vu : l'utilisateur perdait le statut qu'il croyait
        # restaurer. On MERGE par cle metier (le chemin) au lieu d'ecraser, et
        # on re-affirme le statut sur TOUS les items du chemin — `mark_played`
        # est idempotent cote Jellyfin, le faire deux fois ne coute rien.
        jellyfin_by_path: Dict[str, List[str]] = {}  # norm_path -> [item_id]
        # #535 : etat COURANT des compteurs, item_id -> (play_count, last_played_date).
        # Preleve ici, donc avant tout mark_played de cette tentative.
        current_counters: Dict[str, Any] = {}
        duplicate_item_count = 0
        for movie in current_movies:
            p = _normalize_path(movie.get("path", ""))
            # Un id vide n'identifie aucun item : l'indexer ferait disparaitre
            # l'item valide qui partage ce chemin (cf. issue #452, meme famille).
            item_id = str(movie.get("id") or "")
            if not p or not item_id:
                continue
            current_counters[item_id] = (movie.get("play_count", 0), movie.get("last_played_date", ""))
            known = jellyfin_by_path.setdefault(p, [])
            if item_id in known:
                continue
            if known:
                duplicate_item_count += 1
            known.append(item_id)
        if duplicate_item_count:
            _log.warning(
                "Jellyfin sync : %d item(s) en doublon de chemin dans la bibliotheque "
                "— le statut vu sera re-affirme sur chacun",
                duplicate_item_count,
            )

        # Tenter le match pour les pending
        still_pending: Dict[str, str] = {}
        for new_norm, old_norm in pending.items():
            item_ids = jellyfin_by_path.get(new_norm) or []
            if not item_ids:
                # FIX #15 : le film a DISPARU de l'index a cette tentative. Si une
                # tentative anterieure avait laisse un mark_played en echec dans
                # mark_failed, cet item_id est desormais perime : on le purge pour
                # que l'etat le plus recent (absent) prime. Sinon le film serait
                # compte en 'errors' (mark_played failed) alors qu'il n'existe plus,
                # au lieu de not_found. Cas nominal R8-080 (film present a chaque
                # tentative) inchange : pop no-op quand la cle est absente.
                mark_failed.pop(new_norm, None)
                still_pending[new_norm] = old_norm
                continue

            # Film trouve, restaurer le statut watched sur TOUS les items qui
            # portent ce chemin (issue #566). Le chemin n'est considere restaure
            # que si AUCUN des marquages n'a echoue : un echec partiel reste en
            # attente et sera re-tente, il ne devient jamais un succes.
            first_failed_id = ""
            info = snapshot.get(old_norm)
            counters_needed = False
            counters_lost = False
            for item_id in item_ids:
                if not bool(client.mark_played(user_id, item_id)):
                    first_failed_id = first_failed_id or item_id
                    continue
                # #535 : `mark_played` a re-affirme le statut vu, mais il a aussi
                # remis le compteur a 1 et la date a maintenant. On rattrape
                # l'historique uniquement quand Jellyfin l'a reellement perdu.
                if info is None:
                    continue
                cur_count, cur_date = current_counters.get(item_id, (0, ""))
                if not _counters_are_lost(info, cur_count, cur_date):
                    continue
                counters_needed = True
                if not _restore_counters(client, user_id, item_id, info):
                    counters_lost = True
            if not first_failed_id:
                result.restored += 1
                # Un historique perdu ne remet PAS le chemin en attente : le
                # statut vu — l'essentiel — est restaure, et re-tenter 5 fois un
                # endpoint absent couterait 135 s pour rien. Il est compte et
                # remonte, jamais tu.
                if counters_lost:
                    counters_state = "lost"
                    result.counters_lost += 1
                elif counters_needed:
                    counters_state = "restored"
                    result.counters_restored += 1
                else:
                    counters_state = "not_needed"
                result.details.append(
                    {
                        "action": "restored",
                        "old_path": old_norm,
                        "new_path": new_norm,
                        "item_id": item_ids[0],
                        "item_ids": list(item_ids),
                        "counters": counters_state,
                    }
                )
            else:
                # R8-080 : echec possiblement transitoire (503/timeout). Le POST
                # est exclu du retry de session par design anti-double-effet,
                # donc on re-tente ICI a la tentative suivante (mark_played est
                # idempotent cote Jellyfin). Erreur definitive seulement apres
                # epuisement des tentatives (comptage en fin de fonction).
                still_pending[new_norm] = old_norm
                mark_failed[new_norm] = first_failed_id

        pending = still_pending
        if not pending:
            break

        _log.info(
            "Jellyfin sync : tentative %d/%d — %d films en attente (non indexes ou mark_played a re-tenter)",
            attempt,
            max_retries,
            len(pending),
        )

    # Films non restaures apres toutes les tentatives : distinguer echec
    # mark_played persistant (R8-080 : errors) et film jamais re-indexe (not_found).
    for new_norm, old_norm in pending.items():
        failed_item_id = mark_failed.get(new_norm, "")
        if failed_item_id:
            result.errors += 1
            result.details.append(
                {
                    "action": "error",
                    "old_path": old_norm,
                    "new_path": new_norm,
                    "item_id": failed_item_id,
                    "reason": "mark_played failed",
                }
            )
        else:
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
        "Jellyfin sync : restore termine — %d restaures (%d avec historique, %d sans), %d non trouves, %d erreurs",
        result.restored,
        result.counters_restored,
        result.counters_lost,
        result.not_found,
        result.errors,
    )
    return result

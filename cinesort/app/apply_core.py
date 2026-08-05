from __future__ import annotations

import hashlib
import logging
import os
import sqlite3
import time
import unicodedata
from contextvars import ContextVar
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, NamedTuple, Optional, Set, Tuple

import cinesort.domain.core as core_mod
from cinesort.app._dir_utils import is_reparse_point
from cinesort.app.cleanup import (
    _move_empty_top_level_dirs,
    _move_residual_top_level_dirs,
    preview_cleanup_residual_folders,
)
from cinesort.app.move_journal import RecordOpWithJournal, atomic_move
from cinesort.domain.naming import (
    build_naming_context,
    check_path_length_killswitch,
    format_movie_folder,
    format_tv_series_folder,
)

_logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cinesort.app.apply_audit import ApplyAuditLogger
    from cinesort.domain.core import ApplyExecutionContext, ApplyResult, Config, PlanRow


def _name_eq_fs(a: str, b: str) -> bool:
    """Compare two file names case-insensitively AND Unicode-normalized (NFC).

    Necessaire car un scan SMB depuis macOS retourne des noms en NFD alors que
    l'index/plan stocke peut-etre en NFC (ou vice versa). Sans normalisation,
    la comparaison .lower() rate le fichier et provoque un SKIP avec
    "video missing" (et compromet l'apply_rollback faute de src_sha1).
    """
    return (
        unicodedata.normalize("NFC", str(a or "")).casefold() == unicodedata.normalize("NFC", str(b or "")).casefold()
    )


# REGLE INVIOLABLE n1 : le nom du fichier video n'est JAMAIS reconstruit.
#
# Les helpers `_video_ext` / `_video_name_with_ext_case` (ITER7) rebatissaient
# le nom cible en `f"{video.stem}{suffix}"` avec un suffixe force en minuscules
# quand `cfg.lowercase_extensions` etait vrai (defaut). Un apply reel sur
# `Back.To.The.Future.1985.1080p.MKV` produisait `....mkv` : c'est un RENOMMAGE
# du fichier video, qui desynchronise le fichier de son torrent et casse le
# seeding. Le reglage a ete SUPPRIME (Domain, settings, UI) : il n'avait aucun
# autre effet — aucun nom de DOSSIER n'en dependait.
#
# Toute destination de fichier video se construit desormais avec `video.name`,
# c'est-a-dire l'octet-pour-octet du nom source.


def build_apply_context(
    cfg: "Config",
    rows: list["PlanRow"],
    *,
    dry_run: bool,
    quarantine_unapproved: bool,
    run_review_root: Optional[Path],
    decision_presence: Optional[Set[str]],
) -> "ApplyExecutionContext":
    """Construit le contexte d'exécution apply (cfg normalisée, buckets review, cache hash).

    Crée à la volée les sous-dossiers `_review/_conflicts`, `_conflicts_sidecars`,
    `_duplicates_identical`, `_duplicates_user_decided` (Phase 6 doublons) et
    `_leftovers` (sauf en dry_run).
    """
    cfg = cfg.normalized()
    res = core_mod.ApplyResult()
    res.total_rows = len(rows)
    res.considered_rows = len(rows)
    decision_keys = set(decision_presence or set())
    hash_cache: Dict[Tuple[str, int, int], str] = {}

    review_root = cfg.root / "_review"
    merge_review_root = run_review_root if run_review_root is not None else (cfg.root / "_review")
    conflicts_root = merge_review_root / "_conflicts"
    conflicts_sidecars_root = merge_review_root / "_conflicts_sidecars"
    duplicates_identical_root = merge_review_root / "_duplicates_identical"
    # Phase 6 doublons (spec 01-doublons.md §3.7) : losers post-decision UI.
    duplicates_user_decided_root = merge_review_root / "_duplicates_user_decided"
    # AUDIT 2026-06-14 (R7-4) : bucket des films marques pour suppression.
    marked_for_deletion_root = merge_review_root / "_user_marked_for_deletion"
    leftovers_root = merge_review_root / "_leftovers"

    if quarantine_unapproved and (not dry_run):
        review_root.mkdir(parents=True, exist_ok=True)
    if not dry_run:
        conflicts_root.mkdir(parents=True, exist_ok=True)
        conflicts_sidecars_root.mkdir(parents=True, exist_ok=True)
        duplicates_identical_root.mkdir(parents=True, exist_ok=True)
        duplicates_user_decided_root.mkdir(parents=True, exist_ok=True)
        leftovers_root.mkdir(parents=True, exist_ok=True)

    return core_mod.ApplyExecutionContext(
        cfg=cfg,
        res=res,
        decision_keys=decision_keys,
        hash_cache=hash_cache,
        review_root=review_root,
        conflicts_root=conflicts_root,
        conflicts_sidecars_root=conflicts_sidecars_root,
        duplicates_identical_root=duplicates_identical_root,
        duplicates_user_decided_root=duplicates_user_decided_root,
        marked_for_deletion_root=marked_for_deletion_root,
        leftovers_root=leftovers_root,
    )


def record_apply_op(
    record_op: Optional[Callable[[Dict[str, Any]], None]],
    *,
    op_type: str,
    src_path: Path,
    dst_path: Path,
    reversible: bool = True,
    row_id: str = "",
    src_sha1: Optional[str] = None,
    src_size: Optional[int] = None,
) -> bool:
    """Journalise une operation apply. Retourne False si l'enregistrement echoue.

    P1.2 : `src_sha1` et `src_size` optionnels — calcules par l'appelant avant
    le move pour permettre a l'undo de verifier que le fichier n'a pas ete
    remplace manuellement entre temps.
    """
    if record_op is None:
        return True
    try:
        payload: Dict[str, Any] = {
            "op_type": str(op_type or "MOVE"),
            "src_path": str(src_path),
            "dst_path": str(dst_path),
            "reversible": bool(reversible),
            "ts": float(time.time()),
            "row_id": str(row_id or ""),
        }
        if src_sha1:
            payload["src_sha1"] = str(src_sha1)
        if src_size is not None:
            payload["src_size"] = int(src_size)
        record_op(payload)
        return True
    except (TypeError, ValueError, OSError, sqlite3.Error) as e:
        # Fix audit 2026-05-25 (v1.5.3) Vague H : retrograde error->warning, erreur non-fatale
        # (l'op physique a deja reussi cote FS, on n'arrive juste pas a journaliser pour rollback)
        # F11 (2026-08-02) : sqlite3.Error n'herite PAS de OSError. Sans cette entree,
        # un "database is locked" avortait tout le batch APRES un move deja fait sur
        # disque (record_apply_op est appelee apres atomic_move) -> etat mixte sur le FS,
        # rows restantes jamais traitees, et move non journalise donc non annulable.
        _logger.warning("record_apply_op: echec journalisation %s src=%s: %s", op_type, src_path, e, exc_info=True)
        return False


def _case_only_rename_with_rollback(folder: Path, dst: Path) -> None:
    """Fix audit 2026-05-26 (v1.5.6) Vague L (test vacuous rollback) :
    helper extrait du _execute_apply pour permettre un test de COMPORTEMENT
    (assertLogs sur le warning de rollback echoue) au lieu d'un match de
    texte source.

    Sur Windows / case-insensitive FS, renommer "Film" -> "film" necessite
    un detour par un nom temporaire ".__tmp_ren" (sinon le FS considere
    folder == dst et refuse). Si le rename tmp->dst echoue, on tente le
    rollback tmp -> folder pour ne pas laisser le dossier dans un etat
    impossible a recuperer manuellement. Si MEME le rollback echoue, on
    LOG un warning (le dossier reste en .__tmp_ren et l'utilisateur doit
    intervenir) puis on re-raise l'exception originale.

    Raises:
        OSError / PermissionError : l'exception du 2e rename est toujours
        re-raisee (le caller decide de l'impact).
    """
    # Hotfix2 H1 (TOCTOU) : boucle bornee pour trouver un suffixe tmp libre
    # (l'ancien fallback ".__tmp_ren_2" plantait si un crash precedent laissait
    # tmp + tmp_2 sur disque). On essaie ".__tmp_ren", "_0", "_1", ... jusqu'a
    # 10 candidats puis on leve FileExistsError plutot que d'ecraser.
    tmp: Optional[Path] = None
    base_name = folder.name + ".__tmp_ren"
    for idx in range(10):
        candidate = folder.parent / (base_name if idx == 0 else f"{base_name}_{idx}")
        if not candidate.exists():
            tmp = candidate
            break
    if tmp is None:
        raise FileExistsError(
            f"_case_only_rename_with_rollback: aucun suffixe tmp libre pour {folder} "
            f"(essaye {base_name}, {base_name}_1..{base_name}_9)"
        )
    folder.rename(tmp)
    try:
        tmp.rename(dst)
    except (OSError, PermissionError):
        # Rollback : restaurer le nom original si le 2e rename echoue
        try:
            tmp.rename(folder)
        except OSError as rollback_err:
            # M4 : ne plus masquer silencieusement — le dossier reste en .__tmp_ren
            # Fix audit 2026-05-25 (v1.5.3) Vague H : retrograde error->warning, erreur non-fatale
            # (l'exception originale est re-raise apres : le caller decidera de l'impact)
            _logger.warning(
                "apply: rollback rename echoue %s -> %s: %s (dossier en etat .__tmp_ren)",
                tmp,
                folder,
                rollback_err,
            )
        raise


def is_managed_merge_file(cfg: "Config", path: Path) -> bool:
    """Indique si le fichier doit être pris en compte lors d'un merge (vidéo ou sidecar)."""
    ext = path.suffix.lower()
    return (ext in cfg.video_exts) or (ext in cfg.side_exts)


def is_sidecar_metadata(cfg: "Config", path: Path) -> bool:
    """Indique si `path` est un sidecar de métadonnées (nfo/srt/jpg/...) plutôt qu'une vidéo."""
    ext = path.suffix.lower()
    if ext in cfg.video_exts or ext in core_mod.VIDEO_EXTS_ALL:
        return False
    if ext in core_mod.SIDECAR_METADATA_EXTS:
        return True
    return path.name.lower() in core_mod.SIDECAR_METADATA_BASENAMES


def find_main_video_in_folder(folder: Path, cfg: "Config") -> Optional[Path]:
    """P1.2 : retourne le plus gros fichier video dans `folder` (non recursif).

    Utilise pour identifier le film principal a hasher lors d'un MOVE_DIR —
    les sidecars (nfo, srt, images) sont ignores. Retourne None si aucun video.
    """
    if not folder.is_dir():
        return None
    # Phase 6 v7.8.0 : utilise constante unifiee VIDEO_EXTS_ALL
    video_exts = set(cfg.video_exts) | core_mod.VIDEO_EXTS_ALL
    best: Optional[Path] = None
    best_size = 0
    try:
        for entry in folder.iterdir():
            if not entry.is_file():
                continue
            if entry.suffix.lower() not in video_exts:
                continue
            try:
                size = entry.stat().st_size
            except (OSError, PermissionError):
                continue
            if size > best_size:
                best = entry
                best_size = size
    except (OSError, PermissionError):
        return None
    return best


def sha1_quick(path: Path, *, max_seconds: float = 30.0) -> str:
    """Fast fingerprint: SHA-1 of the first 8 MB + last 8 MB (or full file if smaller).

    Fix audit 2026-05-25 (v1.5.3) Vague H : timeout pour eviter blocage indefini
    sur SMB lent / disque qui spin-down / NAS deconnecte. Si la lecture depasse
    ``max_seconds`` (defaut 30s, largement suffisant pour 16 MB sur LAN saine),
    on logue un warning et on retourne "" (interprete par les callers comme
    "pas de hash fiable" : ``files_identical_quick`` renverra False, donc on
    bascule sur le bucket conflits plutot que de bloquer toute la batch).
    Les autres OSError sont egalement capturees (NAS deconnecte en cours de
    lecture, ENOSPC sur cible, etc.).

    NB : la signature publique reste retro-compatible (``max_seconds`` est
    kwarg-only avec un defaut), les callers existants ne changent pas.
    """
    import time as _time_mod  # local pour eviter shadow du module ``time`` haut

    digest = hashlib.sha1(usedforsecurity=False)
    start = _time_mod.monotonic()
    chunk_8m = 8 * 1024 * 1024
    try:
        size = path.stat().st_size
        with path.open("rb") as file_obj:
            if size < (2 * chunk_8m):
                while True:
                    if _time_mod.monotonic() - start > max_seconds:
                        raise TimeoutError(f"sha1_quick timeout ({max_seconds}s) on {path}")
                    block = file_obj.read(1024 * 1024)
                    if not block:
                        break
                    digest.update(block)
            else:
                if _time_mod.monotonic() - start > max_seconds:
                    raise TimeoutError(f"sha1_quick timeout head ({max_seconds}s) on {path}")
                digest.update(file_obj.read(chunk_8m))
                file_obj.seek(max(0, size - chunk_8m))
                if _time_mod.monotonic() - start > max_seconds:
                    raise TimeoutError(f"sha1_quick timeout tail ({max_seconds}s) on {path}")
                digest.update(file_obj.read(chunk_8m))
    except (OSError, TimeoutError) as exc:
        _logger.warning("sha1_quick failed for %s: %s", path, exc)
        return ""
    return digest.hexdigest()


def quick_hash_cache_key(path: Path) -> Optional[Tuple[str, int, int]]:
    """Construit la clef de cache (path, size, mtime_ns) pour `sha1_quick_cached`.

    Renvoie None si `stat()` échoue (fichier disparu, permissions).
    """
    try:
        stat_result = path.stat()
    except (OSError, PermissionError):
        return None
    mtime_ns = int(getattr(stat_result, "st_mtime_ns", int(stat_result.st_mtime * 1_000_000_000)))
    return (str(path), int(stat_result.st_size), mtime_ns)


def sha1_quick_cached(path: Path, cache: Optional[Dict[Tuple[str, int, int], str]]) -> str:
    """Variante mémoïsée de `sha1_quick` (clef = path/size/mtime_ns)."""
    if cache is None:
        return sha1_quick(path)
    key = quick_hash_cache_key(path)
    if key is None:
        return sha1_quick(path)
    existing = cache.get(key)
    if existing:
        return existing
    value = sha1_quick(path)
    cache[key] = value
    return value


def files_identical_quick(
    src: Path,
    dst: Path,
    *,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
) -> bool:
    """Compare deux fichiers via taille + `sha1_quick` (False si lecture échoue)."""
    try:
        if src.stat().st_size != dst.stat().st_size:
            return False
        # Fix audit 2026-05-25 (v1.5.3) Vague H : sha1_quick peut maintenant
        # retourner "" si lecture echoue (timeout SMB, NAS deconnecte). Sans
        # cette garde, "" == "" -> True declencherait une fusion incorrecte
        # de deux fichiers dont on n'a pas pu verifier l'identite.
        src_hash = sha1_quick_cached(src, hash_cache)
        if not src_hash:
            return False
        dst_hash = sha1_quick_cached(dst, hash_cache)
        if not dst_hash:
            return False
        return src_hash == dst_hash
    except (OSError, PermissionError):
        return False


# Cap defensif sur les boucles unique_path / unique_path_dup pour eviter
# un busy-loop infini si le FS est verrouille ou si un attaquant local cree
# des collisions en boucle. 10000 attempts couvre tous les cas reels.
# Cf audit Claude 2026-05-21 (categorie 8 - busy-wait infinite loop).
_UNIQUE_PATH_MAX_ATTEMPTS = 10_000


def unique_path(base: Path) -> Path:
    """Retourne `base` ou la première variante `_2`, `_3`... non existante.

    RESERVE AUX DOSSIERS (`cleanup._move_dirs_to_bucket`). Ne JAMAIS l'appliquer
    a un chemin de fichier : la regle inviolable n1 interdit de renommer un
    fichier. Pour les bacs `_review`, utiliser `unique_bucket_path`.
    """
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    for idx in range(2, _UNIQUE_PATH_MAX_ATTEMPTS + 2):
        candidate = base.with_name(f"{stem}_{idx}{suffix}")
        if not candidate.exists():
            return candidate
    # Fallback ultime : timestamp ns pour casser toute collision adversariale.
    return base.with_name(f"{stem}_{time.time_ns()}{suffix}")


def unique_path_dup(base: Path) -> Path:
    """Retourne `base` ou la première variante `__DUP1`, `__DUP2`... non existante.

    RESERVE AUX DOSSIERS (bacs `_duplicates_user_decided` /
    `_user_marked_for_deletion`, ou l'entree deplacee est un dossier `single`).
    Ne JAMAIS l'appliquer a un chemin de fichier : cf. `unique_path`.
    """
    if not base.exists():
        return base
    stem = base.stem
    suffix = base.suffix
    for idx in range(1, _UNIQUE_PATH_MAX_ATTEMPTS + 1):
        candidate = base.with_name(f"{stem}__DUP{idx}{suffix}")
        if not candidate.exists():
            return candidate
    # Fallback ultime : timestamp ns.
    return base.with_name(f"{stem}__DUP{time.time_ns()}{suffix}")


def _bucket_dir_variant(head: str, idx: int, *, use_dup_suffix: bool) -> str:
    """Nom du DOSSIER de desambiguisation (`Rocky_2`, `Rocky__DUP1`, `_2`, `__DUP1`)."""
    return f"{head}__DUP{idx}" if use_dup_suffix else f"{head}_{idx}"


def unique_bucket_path(dst: Path, *, bucket_root: Path, use_dup_suffix: bool) -> Optional[Path]:
    """Chemin libre pour `dst` sous `bucket_root`, en desambiguisant un DOSSIER.

    REGLE INVIOLABLE n1 : `dst.name` est rendu INTACT. Quand la cible est deja
    prise, l'index (`_2`, `_3`... ou `__DUP1`, `__DUP2`...) est porte par le
    premier dossier situe sous `bucket_root` — celui qui identifie le groupe
    source (le dossier d'origine), pas par le fichier. Si `dst` est pose
    directement dans `bucket_root`, un dossier d'index est INSERE (`_2/nom.mkv`).

    Cause racine traitee : les bacs sont indexes par `folder.name` seul, donc
    deux dossiers sources homonymes visaient le meme sous-dossier ; l'ancien
    `unique_path()` resolvait la collision en renommant le FICHIER
    (`Rocky.1976.1080p.mkv` -> `Rocky.1976.1080p_2.mkv`).

    Retourne `None` quand aucune desambiguisation de dossier n'est possible
    (chemin hors de `bucket_root`, ou cap d'essais epuise). L'appelant DOIT
    alors abandonner le deplacement : sur un chemin destructif, on refuse
    plutot que d'ecraser silencieusement la cible.
    """
    if not dst.exists():
        return dst
    try:
        rel = dst.relative_to(bucket_root)
    except (ValueError, TypeError):
        return None
    if not rel.parts:
        return None
    if len(rel.parts) >= 2:
        head = rel.parts[0]
        tail = Path(*rel.parts[1:])
    else:
        # Fichier pose a la racine du bac : aucun dossier de groupe a indexer,
        # on en INSERE un plutot que de toucher au nom du fichier.
        head = ""
        tail = Path(rel.parts[0])
    start = 1 if use_dup_suffix else 2
    for idx in range(start, _UNIQUE_PATH_MAX_ATTEMPTS + start):
        candidate = bucket_root / _bucket_dir_variant(head, idx, use_dup_suffix=use_dup_suffix) / tail
        if not candidate.exists():
            return candidate
    return None


# F30 : ensemble des dossiers deja "crees" pendant un apply EN DRY-RUN.
#
# En apply reel, `path.exists()` dedoublonne naturellement : le 2e appel pour le
# meme dossier ne compte rien. En dry-run rien n'est cree, donc chaque appel
# recomptait le meme dossier -> `mkdirs` gonfle dans le bandeau "APPLY done" et
# lignes "MKDIR: <meme chemin>" dupliquees dans le log de preview (4 au lieu de 1
# pour une collection d'un film + 2 sous-titres, et duplication INTER-ROWS pour
# le dossier de saga partage par plusieurs films).
#
# Porte par un ContextVar plutot que par un parametre : cela evite de modifier la
# signature des 6 fonctions du chemin d'apply DESTRUCTIF pour un defaut de simple
# comptabilite. Valeur None hors apply_rows -> comportement strictement inchange.
#
# L'etat est APPARIE a l'ApplyResult de l'apply courant (revue adversaire R1).
# Sans cet appariement, un ContextVar laisse peuple par un apply precedent — le
# reset ne peut pas etre garanti sans envelopper les 640 lignes de apply_rows
# dans un try/finally — ferait qu'un futur appelant direct de mkdir_counted en
# dry-run consulterait un ensemble perime et ne compterait plus rien. Comme
# chaque apply_rows travaille sur un ApplyResult neuf, un etat perime ne peut
# jamais correspondre a l'objet courant : il est ignore par construction.
_MKDIR_SEEN_DRY_RUN: ContextVar[Optional[Tuple[Any, Set[str]]]] = ContextVar(
    "cinesort_mkdir_seen_dry_run", default=None
)


def _mkdir_seen_for(res: "ApplyResult") -> Optional[Set[str]]:
    """Ensemble des mkdir deja comptes pour CET apply, ou None si hors apply_rows."""
    state = _MKDIR_SEEN_DRY_RUN.get()
    if state is None or state[0] is not res:
        return None
    return state[1]


def mkdir_counted(
    path: Path,
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    record_op_fn: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Crée `path` (parents inclus) et incrémente `res.mkdirs` (no-op si existe ou dry_run).

    Hotfix2 H2 (TOCTOU) : on utilise un try/except FileExistsError sur le mkdir
    final (sans exist_ok) pour SAVOIR si on l'a vraiment cree (counted=True) ou
    si un autre process l'a cree entre temps (counted=False, pas de record_op).
    On cree d'abord les parents avec exist_ok=True (rien a journaliser pour eux,
    ce n'est pas le dossier dont on suit la creation pour le rollback).
    """
    if path.exists():
        return
    # F30 : en dry-run, `path.exists()` reste faux a chaque appel puisque rien
    # n'est cree — sans cette garde le meme dossier etait recompte et re-logue a
    # chaque fichier deplace. Strictement inactif en apply reel (ou un dossier
    # supprime en cours de batch doit pouvoir etre recree et recompte).
    seen_dry_run = _mkdir_seen_for(res) if dry_run else None
    mkdir_key = os.path.normcase(str(path)) if seen_dry_run is not None else ""
    if seen_dry_run is not None and mkdir_key in seen_dry_run:
        return
    log("INFO", f"MKDIR: {path}")
    if not dry_run:
        # Cree d'abord les parents (sans bruit, exist_ok=True) pour que le mkdir
        # final ne leve que FileExistsError sur la cible.
        parent = path.parent
        if not parent.exists():
            parent.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir(parents=False, exist_ok=False)
        except FileExistsError:
            # Autre process / autre thread a cree le dossier entre exists() et
            # mkdir(). Rien a faire : pas de record_op MKDIR (on ne pourra pas
            # le supprimer au rollback sans risquer de toucher au travail d'un
            # autre), et on n'incremente pas res.mkdirs (on ne l'a pas cree).
            _logger.debug("mkdir_counted: %s pre-existant (race), pas de record_op", path)
            return
        record_apply_op(
            record_op_fn,
            op_type="MKDIR",
            src_path=path,
            dst_path=path,
            reversible=False,
        )
    res.mkdirs += 1
    if seen_dry_run is not None:
        seen_dry_run.add(mkdir_key)


class _SafeWalk(NamedTuple):
    """Résultat d'une descente qui ne franchit AUCUN point d'analyse.

    `blocked` porte les chemins écartés (points d'analyse, dossiers illisibles) :
    l'appelant DOIT s'en servir pour ne pas transformer un refus en succès
    silencieux (compteur « dossier source supprimé », log de fin d'opération).
    """

    files: list[Path]
    dirs: list[Path]
    blocked: list[Path]


def _walk_without_crossing_reparse_points(root: Path) -> _SafeWalk:
    """Descente explicite sous `root` qui s'arrête sur tout point d'analyse.

    Issue #891 — `Path.rglob("*")` DESCEND dans une jonction NTFS (`mklink /J`) :
    `is_symlink()` y répond False, `is_dir()` True, et l'énumération traverse
    vers la cible. Sur les chemins destructifs de l'apply (balayage autour d'un
    film puis déplacement/suppression), cela faisait sortir de `cfg.root` sans
    qu'aucun chemin ne quitte `cfg.root` en apparence : `ensure_inside_root`
    était contourné, des octets d'un autre volume entraient dans la
    bibliothèque et un dossier hors racine était supprimé, le tout `errors=0`.

    Le scan, lui, DOIT continuer à traverser les jonctions (analyser est le but
    de l'app) : ce helper est réservé aux chemins destructifs, où l'erreur va
    dans le sens restrictif — un point d'analyse est écarté, jamais traversé.

    PRÉCONDITION : `root` lui-même n'est PAS testé ici (il serait énuméré via
    `iterdir`, donc traversé). L'appelant doit avoir vérifié
    `is_reparse_point(root)` en amont — c'est ce que font `merge_dir_safe` et
    `prune_empty_dirs`.
    """
    files: list[Path] = []
    dirs: list[Path] = []
    blocked: list[Path] = []
    pending: list[Path] = [root]
    while pending:
        current = pending.pop(0)
        try:
            entries = sorted(current.iterdir())
        except (OSError, ValueError) as exc:
            # Illisible = on ne sait pas ce qu'il y a dedans : on le signale au
            # lieu de le laisser passer pour vide (sens restrictif).
            _logger.debug("walk_no_reparse: enumeration impossible %s: %s", current, exc)
            blocked.append(current)
            continue
        children: list[Path] = []
        for entry in entries:
            if is_reparse_point(entry):
                blocked.append(entry)
                continue
            try:
                if entry.is_dir():
                    dirs.append(entry)
                    children.append(entry)
                elif entry.is_file():
                    files.append(entry)
            except (OSError, ValueError) as exc:
                _logger.debug("walk_no_reparse: type illisible %s: %s", entry, exc)
                blocked.append(entry)
        # Pré-ordre : les enfants du dossier courant avant ses frères restants.
        pending[:0] = children
    return _SafeWalk(files=files, dirs=dirs, blocked=blocked)


def prune_empty_dirs(root: Path) -> bool:
    """Supprime tous les sous-dossiers vides puis `root` lui-même si vide.

    Renvoie True si au moins un dossier a été supprimé. Les erreurs OS sont
    ignorées (skip silencieux).

    Issue #891 — aucun point d'analyse n'est traversé ni supprimé : ni `root`
    lui-même (sinon `iterdir` énumère la cible et des dossiers vides HORS
    bibliothèque sont supprimés), ni un sous-dossier (sinon `rmdir` détruit le
    point de montage lui-même dès que sa cible est vide).
    """
    if not root.exists() or not root.is_dir():
        return False
    if is_reparse_point(root):
        _logger.debug("prune_empty_dirs: racine = point d'analyse, refus: %s", root)
        return False
    removed_any = False
    for directory in sorted(
        _walk_without_crossing_reparse_points(root).dirs, key=lambda path: len(path.parts), reverse=True
    ):
        try:
            if not any(directory.iterdir()):
                directory.rmdir()
                removed_any = True
        except (OSError, PermissionError) as exc:
            _logger.debug("prune_empty_dirs: skip %s: %s", directory, exc)
    try:
        if root.exists() and root.is_dir() and (not any(root.iterdir())):
            root.rmdir()
            removed_any = True
    except (OSError, PermissionError) as exc:
        _logger.debug("prune_empty_dirs: skip root %s: %s", root, exc)
    return removed_any


def legacy_collection_root(cfg: "Config") -> Path:
    """Chemin de l'ancien dossier `Collection` (pré-renommage configurable)."""
    return cfg.root / "Collection"


def resolve_collection_folder_after_migration(cfg: "Config", folder: Path) -> Path:
    """Réécrit un chemin pointant sur l'ancien `Collection` vers le nouveau nom configuré.

    Renvoie `folder` inchangé s'il existe, si la migration n'est pas applicable
    ou si le nouveau chemin n'existe pas.
    """
    if folder.exists():
        return folder
    if not cfg.enable_collection_folder:
        return folder
    legacy_root = legacy_collection_root(cfg)
    target_root = cfg.root / cfg.collection_root_name
    if legacy_root.name.lower() == target_root.name.lower():
        return folder
    try:
        rel = folder.relative_to(legacy_root)
    except (ValueError, TypeError):
        return folder
    migrated = target_root / rel
    return migrated if migrated.exists() else folder


def migrate_legacy_collection_root(
    cfg: "Config",
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    leftovers_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Migre l'ancien dossier `Collection` vers le nom configuré (`collection_root_name`).

    No-op si désactivé, si l'ancien dossier n'existe pas ou si les noms coïncident.
    En cas de cible existante, fusionne via `merge_dir_safe` plutôt que d'écraser.
    """
    if not cfg.enable_collection_folder:
        return
    target_root = cfg.root / cfg.collection_root_name
    legacy_root = legacy_collection_root(cfg)
    if legacy_root.name.lower() == target_root.name.lower():
        return
    if not legacy_root.exists():
        return
    if not legacy_root.is_dir():
        log("WARN", f"MIGRATION Collection ignoree (pas un dossier): {legacy_root}")
        return
    core_mod.ensure_inside_root(cfg, target_root)

    if not target_root.exists():
        log("INFO", f"MIGRATION Collection -> {cfg.collection_root_name}: {legacy_root} -> {target_root}")
        if not dry_run:
            legacy_root.rename(target_root)
            record_apply_op(
                record_op,
                op_type="MOVE_DIR",
                src_path=legacy_root,
                dst_path=target_root,
                reversible=True,
            )
        return

    if not target_root.is_dir():
        log("WARN", f"MIGRATION Collection impossible (cible invalide): {target_root}")
        return

    log("INFO", f"MIGRATION MERGE Collection -> {cfg.collection_root_name}: {legacy_root} -> {target_root}")
    merge_dir_safe(
        cfg,
        legacy_root,
        target_root,
        dry_run=dry_run,
        log=log,
        res=res,
        conflicts_root=conflicts_root,
        conflicts_sidecars_root=conflicts_sidecars_root,
        duplicates_identical_root=duplicates_identical_root,
        leftovers_root=leftovers_root,
        hash_cache=hash_cache,
        record_op=record_op,
    )


def move_to_review_bucket(
    src_file: Path,
    *,
    src_anchor: Path,
    bucket_root: Path,
    bucket_name: str,
    include_anchor_name: bool,
    use_dup_suffix: bool,
    rel_override: Optional[Path],
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Optional[Path]:
    """Déplace `src_file` dans un sous-dossier de `_review` (conflits/duplicates/leftovers).

    Calcule le chemin destination en préservant la hiérarchie relative à `src_anchor`.
    En cas de collision, l'index de desambiguisation est porte par un DOSSIER
    (`unique_bucket_path`) : le nom du fichier est rendu intact, regle inviolable n1.

    Retourne le path final, ou `None` si le deplacement a ete ABANDONNE faute de
    desambiguisation possible — jamais un ecrasement silencieux. L'appelant ne
    doit compter ni move ni quarantaine dans ce cas.
    """
    if rel_override is not None:
        rel = rel_override
    else:
        try:
            rel = src_file.relative_to(src_anchor)
        except (ValueError, TypeError):
            rel = Path(src_file.name)
    if include_anchor_name:
        dst = bucket_root / core_mod.windows_safe(src_anchor.name) / rel
    else:
        dst = bucket_root / rel
    resolved = unique_bucket_path(dst, bucket_root=bucket_root, use_dup_suffix=use_dup_suffix)
    if resolved is None:
        # Sens restrictif : la source reste en place, on ne renomme pas le
        # fichier et on n'ecrase pas la cible. L'echec est BRUYANT.
        err = f"{bucket_name}: ABANDON, aucune desambiguisation de dossier possible pour {src_file} -> {dst}"
        log("ERROR", err)
        res.errors += 1
        try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
            res.error_messages.append(err)
        except AttributeError:  # noqa: BLE001 - retro-compat tests anciens (ApplyResult factice)
            pass
        return None
    dst = resolved
    msg = f"{bucket_name}: {src_file} -> {dst}"
    log("WARN" if bucket_name == "CONFLICT quarantined" else "INFO", msg)
    source_is_file = src_file.is_file()
    if not dry_run:
        dst.parent.mkdir(parents=True, exist_ok=True)
        op_type_str = "QUARANTINE_FILE" if source_is_file else "QUARANTINE_DIR"

        atomic_move(record_op, src=src_file, dst=dst, op_type=op_type_str)
        record_apply_op(
            record_op,
            op_type=op_type_str,
            src_path=src_file,
            dst_path=dst,
            reversible=True,
        )
    return dst


def safe_relative_context(cfg: "Config", path: Path) -> Path:
    """Construit un chemin relatif sûr (Windows-safe) à partir de la racine config."""
    try:
        rel = path.relative_to(cfg.root)
    except (ValueError, TypeError):
        rel = Path(core_mod.windows_safe(path.name))
    parts = [core_mod.windows_safe(part) for part in rel.parts if part not in {"", ".", ".."}]
    return Path(*parts) if parts else Path("_root")


def conflict_context(cfg: "Config", src_anchor: Path, dst_file: Path) -> Path:
    """Construit le sous-chemin `dst_ctx/__from__/src_ctx` utilisé pour bucketiser un conflit."""
    dst_ctx = safe_relative_context(cfg, dst_file.parent)
    src_ctx = safe_relative_context(cfg, src_anchor)
    return dst_ctx / "__from__" / src_ctx


def move_file_with_collision_policy(
    cfg: "Config",
    src_file: Path,
    dst_file: Path,
    *,
    src_anchor: Path,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> str:
    """Déplace `src_file` vers `dst_file` en appliquant la politique de collision.

    Renvoie un statut : `moved`, `conflict`, `duplicate_identical` ou
    `sidecar_conflict`. Calcule sha1+size avant le move pour les vidéos (P1.2/P1.3),
    journalise l'opération même en dry_run pour la preview UI.
    """
    core_mod.ensure_inside_root(cfg, dst_file)
    if dst_file.exists():
        ctx = conflict_context(cfg, src_anchor, dst_file)
        conflicts_ctx_root = conflicts_root / ctx
        sidecars_ctx_root = conflicts_sidecars_root / ctx
        duplicates_ctx_root = duplicates_identical_root / ctx
        if not dst_file.is_file():
            qdst_dir = move_to_review_bucket(
                src_file,
                src_anchor=src_anchor,
                bucket_root=conflicts_ctx_root,
                bucket_name="CONFLICT quarantined",
                include_anchor_name=False,
                use_dup_suffix=False,
                rel_override=None,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            # `None` = deplacement ABANDONNE (cf. move_to_review_bucket) : la source
            # est intacte, ne pas la compter comme mise en quarantaine.
            if qdst_dir is not None:
                res.conflicts_quarantined_count += 1
                res.quarantined += 1
            return "conflict"

        if files_identical_quick(src_file, dst_file, hash_cache=hash_cache):
            moved_to = move_to_review_bucket(
                src_file,
                src_anchor=src_anchor,
                bucket_root=duplicates_ctx_root,
                bucket_name="DUPLICATE_IDENTICAL moved to _review/_duplicates_identical",
                include_anchor_name=False,
                use_dup_suffix=True,
                rel_override=None,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            if moved_to is not None:
                log("INFO", f"DUPLICATE_IDENTICAL moved to _review/_duplicates_identical: {moved_to}")
                res.duplicates_identical_moved_count += 1
                res.duplicates_identical_deleted_count += 1
            return "duplicate_identical"

        if is_sidecar_metadata(cfg, src_file):
            try:
                hash8 = sha1_quick_cached(src_file, hash_cache)[:8]
            except (OSError, PermissionError):
                hash8 = "unknown000"
            sidecar_name = f"{src_file.stem}.incoming_{hash8}{src_file.suffix}"
            try:
                sidecar_rel = src_file.relative_to(src_anchor).with_name(sidecar_name)
            except (ValueError, TypeError):
                sidecar_rel = Path(sidecar_name)
            sidecar_dst = move_to_review_bucket(
                src_file,
                src_anchor=src_anchor,
                bucket_root=sidecars_ctx_root,
                bucket_name="SIDECAR CONFLICT kept both",
                include_anchor_name=False,
                use_dup_suffix=False,
                rel_override=sidecar_rel,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            if sidecar_dst is not None:
                log("INFO", f"SIDECAR CONFLICT kept both: {src_file} -> {sidecar_dst} (dst kept: {dst_file})")
                res.sidecar_conflicts_kept_both_count += 1
                res.conflicts_sidecars_quarantined_count += 1
            return "sidecar_conflict"

        qdst = move_to_review_bucket(
            src_file,
            src_anchor=src_anchor,
            bucket_root=conflicts_ctx_root,
            bucket_name="CONFLICT quarantined",
            include_anchor_name=False,
            use_dup_suffix=False,
            rel_override=None,
            dry_run=dry_run,
            log=log,
            res=res,
            record_op=record_op,
        )
        log("WARN", f"CONFLICT: {src_file} would overwrite {dst_file} -> {qdst}")
        if qdst is not None:
            res.conflicts_quarantined_count += 1
            res.quarantined += 1
        return "conflict"

    mkdir_counted(dst_file.parent, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)
    log("INFO", f"MOVE: {src_file} -> {dst_file}")

    # P1.2 + P1.3 : capturer sha1 + taille avant le move (seulement apply réel — pas en dry_run).
    src_sha1: Optional[str] = None
    src_size: Optional[int] = None
    if not dry_run:
        ext = src_file.suffix.lower()
        # Phase 6 v7.8.0 : VIDEO_EXTS_ALL au lieu du set hardcode (4eme copie eliminee)
        is_video = (ext in cfg.video_exts) or (ext in core_mod.VIDEO_EXTS_ALL)
        if is_video:
            try:
                src_size = src_file.stat().st_size
                src_sha1 = sha1_quick_cached(src_file, hash_cache)
            except (OSError, PermissionError) as exc:
                _logger.debug("P1.2: sha1 pre-apply echoue pour %s: %s", src_file, exc)
                src_sha1 = None
                src_size = None

        # Hotfix2 H4 (DATA LOSS) : double-check juste avant le move qu'aucune
        # collision n'est apparue entre le dst_file.exists() initial (l. 577)
        # et maintenant (fenetre TOCTOU sur SMB qui peut etre longue : mkdir,
        # sha1, hash_cache lookup...). Sans cette garde, shutil.move sur
        # Windows ECRASE silencieusement le fichier de destination si un autre
        # process / autre thread l'a cree entre temps = DATA LOSS reel.
        # Hotfix3 (mega-hotfix) : aligner la garde sur la check initiale (L610-631)
        # qui distingue file/dir via is_file(). Sans is_file() ici, si un dossier
        # est cree au meme path entre L610 et L725 (cas rare mais reel : worker
        # parallele creant dst_dir), on quarantine "race" au lieu de quarantine
        # "dst not file" : meme resultat (conflict), mais log incoherent et le
        # path conflicts_root/conflict_context() suppose un fichier en dst.
        if dst_file.exists():
            if not dst_file.is_file():
                log(
                    "WARN",
                    f"CONFLICT (race) detected pre-move (dst is not a file): {src_file} -> {dst_file}, quarantining",
                )
            else:
                log("WARN", f"CONFLICT (race) detected pre-move: {src_file} -> {dst_file}, quarantining")
            qdst = move_to_review_bucket(
                src_file,
                src_anchor=src_anchor,
                bucket_root=conflicts_root / conflict_context(cfg, src_anchor, dst_file),
                bucket_name="CONFLICT quarantined",
                include_anchor_name=False,
                use_dup_suffix=False,
                rel_override=None,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            log("WARN", f"CONFLICT (race): {src_file} would overwrite {dst_file} -> {qdst}")
            if qdst is not None:
                res.conflicts_quarantined_count += 1
                res.quarantined += 1
            return "conflict"

        atomic_move(
            record_op,
            src=src_file,
            dst=dst_file,
            op_type="MOVE_FILE",
            src_sha1=src_sha1,
            src_size=src_size,
        )

    # P1.3 : record l'op même en dry_run pour que la preview puisse la remonter à l'UI.
    record_apply_op(
        record_op,
        op_type="MOVE_FILE",
        src_path=src_file,
        dst_path=dst_file,
        reversible=True,
        src_sha1=src_sha1,
        src_size=src_size,
    )
    res.moves += 1
    return "moved"


def merge_dir_safe(
    cfg: "Config",
    src_dir: Path,
    dst_dir: Path,
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    leftovers_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Fusionne `src_dir` dans `dst_dir` fichier par fichier (sans écrasement destructif).

    Délègue chaque fichier à `move_file_with_collision_policy`, puis envoie les
    fichiers non gérés (non-vidéo/non-sidecar) dans `_review/_leftovers` et tente
    de purger l'arborescence source vidée.
    """
    if not src_dir.exists():
        core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
        log("WARN", f"MERGE source missing, skip: {src_dir}")
        return
    # Issue #891 : fusionner DEPUIS une jonction viderait un autre volume dans la
    # bibliotheque. Refus compte comme erreur : la fusion demandee n'a pas eu
    # lieu, elle ne doit pas etre maquillee en succes (`merges_count`).
    if is_reparse_point(src_dir):
        res.errors += 1
        message = (
            f"FUSION REFUSEE : '{src_dir}' est un point d'analyse (jonction NTFS / lien) "
            f"pointant hors de la bibliotheque. Rien n'a ete deplace."
        )
        _append_error_message(res, message)
        log("ERROR", f"MERGE source is a reparse point, refuse: {src_dir}")
        return
    if not dst_dir.exists():
        mkdir_counted(dst_dir, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)
    if not dst_dir.is_dir():
        res.errors += 1
        log("ERROR", f"MERGE target invalid (not directory): {dst_dir}")
        return

    log("INFO", f"MERGE_DIR: {src_dir} -> {dst_dir}")
    res.merges_count += 1

    # Issue #891 : descente explicite, `rglob` traverserait les jonctions.
    walk = _walk_without_crossing_reparse_points(src_dir)
    for blocked_path in walk.blocked:
        log("WARN", f"MERGE: point d'analyse NON traverse, laisse en place: {blocked_path}")
    all_files = walk.files
    handled_for_leftovers: Set[Path] = set()

    for src_file in all_files:
        if not is_managed_merge_file(cfg, src_file):
            continue
        rel = src_file.relative_to(src_dir)
        dst_file = dst_dir / rel
        status = move_file_with_collision_policy(
            cfg,
            src_file,
            dst_file,
            src_anchor=src_dir,
            dry_run=dry_run,
            log=log,
            res=res,
            conflicts_root=conflicts_root,
            conflicts_sidecars_root=conflicts_sidecars_root,
            duplicates_identical_root=duplicates_identical_root,
            hash_cache=hash_cache,
            record_op=record_op,
        )
        if status in {"moved", "conflict", "duplicate_identical", "sidecar_conflict"}:
            handled_for_leftovers.add(src_file)
        if status == "duplicate_identical":
            core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        elif status in {"conflict", "sidecar_conflict"}:
            core_mod._mark_skip(res, core_mod.SKIP_REASON_CONFLIT_QUARANTAINE)

    if dry_run:
        leftover_files = [path for path in all_files if path not in handled_for_leftovers]
        for leftover_file in leftover_files:
            try:
                rel = leftover_file.relative_to(src_dir)
            except (ValueError, TypeError):
                rel = Path(leftover_file.name)
            # Parite preview/reel : meme desambiguisation par DOSSIER que
            # move_to_review_bucket, sinon la preview annoncerait un nom de
            # fichier suffixe que l'apply reel ne produit plus.
            planned = unique_bucket_path(
                leftovers_root / core_mod.windows_safe(src_dir.name) / rel,
                bucket_root=leftovers_root,
                use_dup_suffix=False,
            )
            if planned is None:
                log("WARN", f"LEFTOVERS: aucune destination desambiguisable, {leftover_file} restera en place")
            else:
                log("INFO", f"LEFTOVERS planned: {leftover_file} -> {planned}")
        res.leftovers_moved_count += len(leftover_files)
        # Hotfix3 (mega-hotfix) : aligner la simulation dry_run sur le comportement
        # reel. En mode reel (L863-864 plus bas), source_dirs_deleted_count
        # s'incremente DES QUE prune_empty_dirs(src_dir) reussit, ce qui est le
        # cas chaque fois que tous les fichiers (manages ET non-manages) ont ete
        # deplaces. La simulation dry_run dit qu'on deplacerait tous les
        # leftover_files vers leftovers_root, donc src_dir se retrouverait vide
        # apres apply reel : on doit incrementer source_dirs_deleted_count, peu
        # importe qu'il y ait eu des leftovers ou non. L'ancien check
        # `len(leftover_files) == 0` sous-estimait le compteur en preview UI.
        #
        # Issue #891 : sauf si la descente a bute sur un point d'analyse. Il
        # restera dans `src_dir`, que l'apply reel ne pourra donc pas supprimer
        # (prune_empty_dirs refuse aussi de le traverser) : annoncer sa
        # suppression serait une promesse que l'apply ne tiendra pas.
        if walk.blocked:
            log("WARN", f"MERGE: source conservee (point d'analyse a l'interieur): {src_dir}")
        else:
            res.source_dirs_deleted_count += 1
        return

    remaining_files = _walk_without_crossing_reparse_points(src_dir).files
    for src_file in remaining_files:
        leftover_dst = move_to_review_bucket(
            src_file,
            src_anchor=src_dir,
            bucket_root=leftovers_root,
            bucket_name="LEFTOVERS moved",
            include_anchor_name=True,
            use_dup_suffix=False,
            rel_override=None,
            dry_run=dry_run,
            log=log,
            res=res,
            record_op=record_op,
        )
        # `None` = abandon : le fichier est reste en place, ne pas le compter.
        if leftover_dst is not None:
            res.leftovers_moved_count += 1

    if prune_empty_dirs(src_dir):
        res.source_dirs_deleted_count += 1


def _revert_moves(
    record_op: Optional[Callable[[Dict[str, Any]], None]],
    moved_pairs: list[Tuple[Path, Path]],
    log: Callable[[str, str], None],
    label: str,
) -> None:
    """R8-017 (F2-b) : annule (best-effort, ordre inverse) une liste de moves
    (dst effectif, src d'origine) déjà effectués pour un item, afin de laisser un
    état COHÉRENT après un échec mid-item. Même logique que les rollbacks intra-row
    de COLL-ATOMIC (F1) et TV (F2-a) — factorisée, pas une 3e variante.
    """
    for dst_done, src_orig in reversed(moved_pairs):
        try:
            if dst_done.exists() and not src_orig.exists():
                atomic_move(record_op, src=dst_done, dst=src_orig, op_type=f"ROLLBACK_{label}")
                record_apply_op(
                    record_op,
                    op_type=f"ROLLBACK_{label}",
                    src_path=dst_done,
                    dst_path=src_orig,
                    reversible=False,
                )
                log("WARN", f"ROLLBACK {label}: {dst_done} -> {src_orig}")
        except (OSError, PermissionError) as rb_exc:
            log("ERROR", f"ROLLBACK {label} ECHEC {dst_done} -> {src_orig}: {rb_exc}")


def _row_target_key(row: "PlanRow") -> Tuple[str, str, str]:
    """Cible REELLE d'une PlanRow pour une operation destructive.

    Deux rows qui partagent cette cle designent exactement les memes octets sur le
    disque : les deplacer via l'une ou l'autre donne le meme resultat.
    """
    folder = str(getattr(row, "folder", "") or "").casefold()
    video = str(getattr(row, "video", "") or "").casefold()
    kind = str(getattr(row, "kind", "") or "")
    return (folder, video, kind)


def _index_rows_by_id(
    rows: list["PlanRow"],
    *,
    log: Callable[[str, str], None],
    prefix: str,
) -> Tuple[Dict[str, "PlanRow"], Set[str]]:
    """Indexe les PlanRow par row_id pour les operations DESTRUCTIVES, en FAIL-CLOSED
    sur les collisions AMBIGUES.

    AUDIT 2026-07-13 [CRIT-2] : les deux index `by_row` etaient construits en
    `by_row[rid] = r` last-wins SILENCIEUX. Si deux PlanRow partagent un row_id
    (collision possible tant que des row_id legacy 32 bits circulent), le row_id
    choisi par l'utilisateur resolvait vers le MAUVAIS PlanRow -> un film JAMAIS
    marque sortait de la bibliotheque, et le film reellement vise y restait.

    RELECTURE R2 [D1] : un row_id duplique n'est pas forcement ambigu. Des rows
    STRICTEMENT IDENTIQUES (meme folder + meme video + meme kind) sont produites de
    facon ROUTINIERE par des roots imbriques (`validate_roots` n'emet qu'un WARNING,
    `plan_multi_roots` concatene sans dedup et `_compute_row_id` ne hashe pas le root)
    : chaque film du root enfant apparait alors deux fois avec le MEME row_id. Les
    declarer ambigues abandonnait l'operation destructive de l'utilisateur alors que
    la cible etait parfaitement determinee (et spammait un ERROR par doublon du plan
    ENTIER). On ne fail-close donc QUE si les rows en collision visent des cibles
    DIFFERENTES ; sinon on garde la premiere, sans bruit.

    Retourne `(by_row, ambiguous_row_ids)`.
    """
    by_row: Dict[str, "PlanRow"] = {}
    ambiguous_row_ids: Set[str] = set()
    for r in rows:
        _rid = getattr(r, "row_id", None)
        _rid_str = str(_rid) if _rid not in (None, "") else ""
        if not _rid_str:
            # BUG-009 (hotfix) : avant on filtrait silencieusement les row_id falsy
            # (None, "", 0). Un loser dont le row_id etait vide etait absorbe en
            # "row_id introuvable" sans signal clair -> on logge un WARN explicite.
            log("WARN", f"{prefix} PlanRow sans row_id (folder={getattr(r, 'folder', '?')}), ignore")
            continue
        if _rid_str in by_row:
            kept = by_row[_rid_str]
            if _row_target_key(r) == _row_target_key(kept):
                # Doublon EXACT (roots imbriques / plan concatene) : meme cible, aucune
                # ambiguite -> on garde la premiere, silencieusement.
                continue
            if _rid_str not in ambiguous_row_ids:
                ambiguous_row_ids.add(_rid_str)
                log(
                    "ERROR",
                    f"{prefix} row_id DUPLIQUE dans le plan: {_rid_str} "
                    f"(folder={getattr(r, 'folder', '?')} vs {getattr(kept, 'folder', '?')})",
                )
            continue
        by_row[_rid_str] = r
    return by_row, ambiguous_row_ids


def _locked_msg(name: str) -> str:
    """Message utilisateur pour un verrou fichier Windows (cas tres frequent).

    Extrait du handler per-row (F10) pour que la pre-passe collection et le
    nettoyage post-boucle, qui vivent HORS du try per-row, puissent produire
    exactement le meme message au lieu d'un '[WinError 32]' brut.
    """
    return (
        f"FICHIER VERROUILLE : '{name}' est ouvert dans un autre logiciel "
        f"(VLC ? lecteur video ? indexeur Windows ?). Ferme-le et relance l'apply "
        f"pour ce film."
    )


def _append_error_message(res: "ApplyResult", message: str) -> None:
    """Ajoute un message d'erreur utilisateur a `res` (remontee UI / summary.txt).

    RELECTURE R2 [D5] : une seule convention pour TOUS les appelants. Certains tests
    anciens passent un `res` duck-type sans `error_messages` ; un append nu ferait
    crasher tout l'apply (les branches fail-closed etaient hors du try/except OSError).
    """
    try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
        res.error_messages.append(message)
    except AttributeError:  # noqa: BLE001 - retro-compat tests anciens (res duck-type)
        pass


def move_duplicate_losers_to_user_decided(
    cfg: "Config",
    rows: list["PlanRow"],
    loser_row_ids: Set[str],
    *,
    duplicates_user_decided_root: Path,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Set[str]:
    """Phase 6 doublons (spec 01-doublons.md §3.7) : déplace les fichiers/dossiers
    "losers" d'une décision utilisateur vers `<root>/_review/_duplicates_user_decided/`.

    Doit être appelé AVANT la boucle d'apply principale : on retire les losers du
    plan en les déplaçant dans le bucket dédié, puis l'apply normal continue sur
    les winners. Les déplacements passent par `atomic_move` + `record_apply_op`
    pour rester réversibles via l'undo (même mécanisme que `_duplicates_identical/`).

    `loser_row_ids` : set des row_id dont la décision a marqué un autre row comme
    winner. Tolère un set vide (no-op).

    Retourne l'ensemble des row_id ABANDONNES (fail-closed sur row_id ambigu) :
    RIEN n'a bougé pour eux, l'appelant ne doit donc PAS les retirer de la boucle
    d'apply normale (RELECTURE R2 [D3]).
    """
    abandoned_row_ids: Set[str] = set()
    if not loser_row_ids:
        return abandoned_row_ids
    if not dry_run:
        duplicates_user_decided_root.mkdir(parents=True, exist_ok=True)

    # BUG-009 + AUDIT 2026-07-13 [CRIT-2] (fail-closed sur row_id dupliques) :
    # cf. _index_rows_by_id.
    by_row, ambiguous_row_ids = _index_rows_by_id(rows, log=log, prefix="DUPLICATE_LOSER")
    losers_seen: Set[str] = set()
    for rid in loser_row_ids:
        if rid in losers_seen:
            continue
        losers_seen.add(rid)
        # [CRIT-2] FAIL-CLOSED : row_id ambigu -> on ne peut pas savoir quel PlanRow
        # l'utilisateur visait. On ABANDONNE l'operation destructive pour ce row_id
        # (aucun deplacement) au lieu de resoudre vers le mauvais film.
        if str(rid) in ambiguous_row_ids:
            log(
                "ERROR",
                f"DUPLICATE_LOSER row_id {rid} AMBIGU (collision de row_id) -> "
                f"ABANDON, aucun fichier deplace pour ce row_id",
            )
            # RELECTURE R2 [D2] : un abandon est une ERREUR visible (res.errors),
            # sinon l'utilisateur lit "Erreurs : 0" alors que son action destructive
            # n'a PAS eu lieu. [D5] : append protege (une seule convention).
            res.errors += 1
            _append_error_message(
                res,
                f"DUPLICATE_LOSER {rid}: row_id duplique dans le plan, deplacement abandonne (fail-closed)",
            )
            abandoned_row_ids.add(str(rid))
            continue
        row = by_row.get(str(rid))
        if row is None:
            log("WARN", f"DUPLICATE_LOSER row_id introuvable, skip: {rid}")
            continue

        folder = Path(row.folder)
        video_name = str(row.video or "").strip()
        # Wrap record_op pour injecter le row_id (traçabilité Undo v5).
        # Hotfix3 (mega-hotfix) : binder `record_op` via default arg explicite
        # (pas seulement via fermeture) pour eviter une dependance sur la cellule
        # de fermeture si record_op etait rebind plus tard dans le scope englobant
        # (defensive contre refactor : la fermeture capturait la *cellule* du nom
        # `record_op`, le default arg capture *la valeur courante*).
        row_record_op = None
        if record_op is not None:
            _rid_str = str(row.row_id or "")
            _record_op_ref = record_op

            def _inject_row_id(
                payload: Dict[str, Any],
                _rid_str: str = _rid_str,
                _record_op_ref: Callable[[Dict[str, Any]], None] = _record_op_ref,
            ) -> None:
                if isinstance(payload, dict) and not payload.get("row_id"):
                    payload["row_id"] = _rid_str
                _record_op_ref(payload)

            # AUDIT 2026-06-10 (HIGH, REAL 2/2) : conserver journal_store/batch_id
            # de RecordOpWithJournal (sinon atomic_move -> shutil.move sans
            # journal write-ahead). Cf le meme fix dans la boucle apply par-row.
            row_record_op = RecordOpWithJournal(
                _inject_row_id,
                store=getattr(_record_op_ref, "journal_store", None),
                batch_id=getattr(_record_op_ref, "journal_batch_id", None),
            )

        # R8-017 (F2-b) : ISOLATION per-loser + ROLLBACK. Un loser verrouillé ne doit
        # PAS avorter tout le batch (asymétrie corrigée avec la boucle per-row L1650) ;
        # un loser collection à moitié déplacé est rollback (parité COLL-ATOMIC F1).
        # Comptage ATOMIQUE par loser : on n'ajoute à res qu'après succès complet du rid
        # (sinon un partiel/échec laissait un compteur faux).
        _moved_pairs: list[Tuple[Path, Path]] = []
        try:
            # AUDIT 2026-07-13 [CRIT-1] : granularité destructive. SEUL kind="single"
            # possède un dossier dédié ; "collection", "extra" (bonus_video,
            # plan_support_core.py:751) et "tv_episode" vivent dans un dossier PARTAGÉ
            # → déplacer SEULEMENT la vidéo + ses sidecars, jamais le dossier entier
            # (l'ancienne garde `== "collection"` laissait extra/tv_episode tomber sur
            # MOVE_DIR = film principal / série entière emportés). Sémantique alignée
            # sur quarantine_row (`if row.kind == "single"` → dossier entier, sinon
            # vidéo + sidecars).
            if row.kind != "single" and video_name:
                video = folder / video_name
                if not video.exists():
                    # tolère case-insensitive : iter le dossier
                    try:
                        matches = [p for p in folder.iterdir() if p.is_file() and _name_eq_fs(p.name, video_name)]
                        video = matches[0] if matches else video
                    except (OSError, PermissionError):
                        pass
                if not video.exists():
                    log("WARN", f"DUPLICATE_LOSER video manquant pour row {rid}, skip: {video}")
                    continue
                # Déplace la vidéo + sidecars associés
                sidecars = core_mod.classify_sidecars(cfg, folder, video, is_collection=True)
                for sidecar in sidecars:
                    if not sidecar.exists():
                        continue
                    moved_to = move_to_review_bucket(
                        sidecar,
                        src_anchor=folder,
                        bucket_root=duplicates_user_decided_root,
                        bucket_name="DUPLICATE_LOSER moved to _review/_duplicates_user_decided",
                        include_anchor_name=True,
                        use_dup_suffix=False,
                        rel_override=None,
                        dry_run=dry_run,
                        log=log,
                        res=res,
                        record_op=row_record_op,
                    )
                    if moved_to is not None and not dry_run:
                        _moved_pairs.append((Path(moved_to), sidecar))
                moved_to = move_to_review_bucket(
                    video,
                    src_anchor=folder,
                    bucket_root=duplicates_user_decided_root,
                    bucket_name="DUPLICATE_LOSER moved to _review/_duplicates_user_decided",
                    include_anchor_name=True,
                    use_dup_suffix=False,
                    rel_override=None,
                    dry_run=dry_run,
                    log=log,
                    res=res,
                    record_op=row_record_op,
                )
                if moved_to is not None and not dry_run:
                    _moved_pairs.append((Path(moved_to), video))
                # R8-018 : compteur DEDIE (≠ duplicates_identical) -> invariant
                # moved==deleted preserve + chemin de recuperation reel (_duplicates_user_decided).
                # RELECTURE R2 [D4] : on compte des FILMS (+1 par row), pas des FICHIERS.
                # L'ancien `+= _rid_count` ajoutait video + sidecars -> un episode avec 2
                # sous-titres s'affichait comme 3 "films deplaces" sous un libelle UI
                # "Films ... deplaces", et divergeait de la branche single (`+= 1`).
                # `moved_to is None` = deplacement de la VIDEO abandonne : ne pas
                # transformer cet echec en succes silencieux dans le bandeau.
                if moved_to is not None:
                    res.duplicates_user_decided_moved_count += 1
                continue

            # AUDIT 2026-07-13 [CRIT-1] garde-fou (défense en profondeur) : une row
            # non-"single" SANS video_name est une row corrompue, pas une autorisation
            # d'emporter un dossier partagé. On skip avec un WARN plutôt que de tomber
            # silencieusement sur MOVE_DIR.
            if row.kind != "single":
                log(
                    "WARN",
                    f"DUPLICATE_LOSER row {rid} kind={row.kind!r} sans video, "
                    f"skip (dossier partage jamais deplace en entier): {folder}",
                )
                continue

            # Cas "single" : déplace le dossier entier vers le bucket.
            if not folder.exists():
                log("WARN", f"DUPLICATE_LOSER dossier manquant pour row {rid}, skip: {folder}")
                continue
            target = duplicates_user_decided_root / core_mod.windows_safe(folder.name)
            # Anti-collision : suffixe __DUP1/2/... si déjà présent.
            target = unique_path_dup(target)
            log("INFO", f"DUPLICATE_LOSER moved to _review/_duplicates_user_decided: {folder} -> {target}")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_move(row_record_op, src=folder, dst=target, op_type="MOVE_DIR")
                record_apply_op(
                    row_record_op,
                    op_type="MOVE_DIR",
                    src_path=folder,
                    dst_path=target,
                    reversible=True,
                )
                _moved_pairs.append((target, folder))
            res.duplicates_user_decided_moved_count += 1  # R8-018 : compteur dedie
        except (OSError, PermissionError) as exc:
            # Isolation : le batch N'EST PAS avorté ; on rollback le partiel de ce
            # loser puis on enregistre l'erreur et on continue (parité per-row L1650).
            log("ERROR", f"DUPLICATE_LOSER echec row {rid} ({folder}); rollback + skip (batch non avorte): {exc}")
            _revert_moves(row_record_op, _moved_pairs, log, "DUPLICATE_LOSER")
            res.errors += 1
            _append_error_message(res, f"DUPLICATE_LOSER {getattr(folder, 'name', folder)}: {exc}")
            continue

    return abandoned_row_ids


def move_marked_for_deletion_to_bucket(
    cfg: "Config",
    rows: list["PlanRow"],
    marked_row_ids: Set[str],
    *,
    marked_for_deletion_root: Path,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Set[str]:
    """AUDIT 2026-06-14 (R7-4) : deplace les films marques pour suppression par
    l'utilisateur vers `<root>/_review/_user_marked_for_deletion/`.

    Miroir isole de move_duplicate_losers_to_user_decided (zero impact sur le
    chemin doublons). Appele AVANT la boucle apply principale ; les rows marquees
    sont ensuite exclues. Deplacements via atomic_move + record_apply_op ->
    reversibles par l'undo. No-op si set vide. Securite torrents : on DEPLACE
    (jamais de suppression definitive), l'utilisateur videra le bucket lui-meme.

    Retourne l'ensemble des row_id ABANDONNES (fail-closed sur row_id ambigu) :
    RIEN n'a bougé pour eux -> l'appelant ne doit PAS les exclure de l'apply normal
    (RELECTURE R2 [D3]).
    """
    abandoned_row_ids: Set[str] = set()
    if not marked_row_ids:
        return abandoned_row_ids
    if not dry_run:
        marked_for_deletion_root.mkdir(parents=True, exist_ok=True)

    # AUDIT 2026-07-13 [CRIT-2] : index fail-closed sur les row_id dupliques
    # (cf. _index_rows_by_id). Bucket vide par l'utilisateur -> une resolution
    # last-wins vers le mauvais PlanRow = perte definitive d'un film jamais marque.
    by_row, ambiguous_row_ids = _index_rows_by_id(rows, log=log, prefix="MARKED_FOR_DELETION")

    seen: Set[str] = set()
    for rid in marked_row_ids:
        if rid in seen:
            continue
        seen.add(rid)
        if str(rid) in ambiguous_row_ids:
            log(
                "ERROR",
                f"MARKED_FOR_DELETION row_id {rid} AMBIGU (collision de row_id) -> "
                f"ABANDON, aucun fichier deplace pour ce row_id",
            )
            # RELECTURE R2 [D2]/[D5] : abandon = erreur VISIBLE (res.errors) + append protege.
            res.errors += 1
            _append_error_message(
                res,
                f"MARKED_FOR_DELETION {rid}: row_id duplique dans le plan, deplacement abandonne (fail-closed)",
            )
            abandoned_row_ids.add(str(rid))
            continue
        row = by_row.get(str(rid))
        if row is None:
            log("WARN", f"MARKED_FOR_DELETION row_id introuvable, skip: {rid}")
            continue

        folder = Path(row.folder)
        video_name = str(row.video or "").strip()
        row_record_op = record_op
        if record_op is not None:
            _rid_str = str(row.row_id or "")
            _record_op_ref = record_op

            def _inject_row_id(
                payload: Dict[str, Any],
                _rid_str: str = _rid_str,
                _record_op_ref: Callable[[Dict[str, Any]], None] = _record_op_ref,
            ) -> None:
                if isinstance(payload, dict) and not payload.get("row_id"):
                    payload["row_id"] = _rid_str
                _record_op_ref(payload)

            row_record_op = RecordOpWithJournal(
                _inject_row_id,
                store=getattr(_record_op_ref, "journal_store", None),
                batch_id=getattr(_record_op_ref, "journal_batch_id", None),
            )

        bucket_label = "MARKED_FOR_DELETION moved to _review/_user_marked_for_deletion"

        # R8-017 (F2-b) : même isolation per-item + rollback que les losers (et que la
        # boucle per-row L1650). Un fichier marqué verrouillé n'avorte PAS le batch ;
        # un item collection à moitié déplacé est rollback. Comptage atomique par rid.
        _moved_pairs: list[Tuple[Path, Path]] = []
        try:
            # AUDIT 2026-07-13 [CRIT-1] : granularité destructive (bucket vidé par
            # l'utilisateur -> perte definitive). SEUL kind="single" possède un dossier
            # dédié ; "collection", "extra" (bonus_video) et "tv_episode" partagent leur
            # dossier avec d'autres vidéos NON marquées → déplacer SEULEMENT la vidéo
            # marquée + ses sidecars. Sémantique alignée sur quarantine_row.
            if row.kind != "single" and video_name:
                video = folder / video_name
                if not video.exists():
                    try:
                        matches = [p for p in folder.iterdir() if p.is_file() and _name_eq_fs(p.name, video_name)]
                        video = matches[0] if matches else video
                    except (OSError, PermissionError):
                        pass
                if not video.exists():
                    log("WARN", f"MARKED_FOR_DELETION video manquante pour row {rid}, skip: {video}")
                    continue
                sidecars = core_mod.classify_sidecars(cfg, folder, video, is_collection=True)
                for sidecar in sidecars:
                    if not sidecar.exists():
                        continue
                    moved_to = move_to_review_bucket(
                        sidecar,
                        src_anchor=folder,
                        bucket_root=marked_for_deletion_root,
                        bucket_name=bucket_label,
                        include_anchor_name=True,
                        use_dup_suffix=False,
                        rel_override=None,
                        dry_run=dry_run,
                        log=log,
                        res=res,
                        record_op=row_record_op,
                    )
                    if moved_to is not None and not dry_run:
                        _moved_pairs.append((Path(moved_to), sidecar))
                moved_to = move_to_review_bucket(
                    video,
                    src_anchor=folder,
                    bucket_root=marked_for_deletion_root,
                    bucket_name=bucket_label,
                    include_anchor_name=True,
                    use_dup_suffix=False,
                    rel_override=None,
                    dry_run=dry_run,
                    log=log,
                    res=res,
                    record_op=row_record_op,
                )
                if moved_to is not None and not dry_run:
                    _moved_pairs.append((Path(moved_to), video))
                # RELECTURE R2 [D4] : +1 par FILM (row), pas par FICHIER deplace.
                # Le libelle UI est "Films marques pour suppression deplaces" : compter
                # les sidecars gonflait le chiffre (1 episode + 2 srt = 3 "films").
                # `moved_to is None` = deplacement de la VIDEO abandonne : pas de succes
                # silencieux (le fichier est reste dans son dossier d'origine).
                if moved_to is not None:
                    res.marked_for_deletion_moved_count += 1
                continue

            # AUDIT 2026-07-13 [CRIT-1] garde-fou (défense en profondeur) : une row
            # non-"single" SANS video_name est corrompue -> jamais MOVE_DIR, on skip.
            if row.kind != "single":
                log(
                    "WARN",
                    f"MARKED_FOR_DELETION row {rid} kind={row.kind!r} sans video, "
                    f"skip (dossier partage jamais deplace en entier): {folder}",
                )
                continue

            # Cas single : deplacer le dossier entier.
            if not folder.exists():
                log("WARN", f"MARKED_FOR_DELETION dossier manquant pour row {rid}, skip: {folder}")
                continue
            target = unique_path_dup(marked_for_deletion_root / core_mod.windows_safe(folder.name))
            log("INFO", f"{bucket_label}: {folder} -> {target}")
            if not dry_run:
                target.parent.mkdir(parents=True, exist_ok=True)
                atomic_move(row_record_op, src=folder, dst=target, op_type="MOVE_DIR")
                record_apply_op(
                    row_record_op,
                    op_type="MOVE_DIR",
                    src_path=folder,
                    dst_path=target,
                    reversible=True,
                )
                _moved_pairs.append((target, folder))
            res.marked_for_deletion_moved_count += 1
        except (OSError, PermissionError) as exc:
            log("ERROR", f"MARKED_FOR_DELETION echec row {rid} ({folder}); rollback + skip (batch non avorte): {exc}")
            _revert_moves(row_record_op, _moved_pairs, log, "MARKED_FOR_DELETION")
            res.errors += 1
            _append_error_message(res, f"MARKED_FOR_DELETION {getattr(folder, 'name', folder)}: {exc}")
            continue

    return abandoned_row_ids


def move_collection_folder(
    cfg: "Config",
    folder: Path,
    *,
    dry_run: bool,
    log: Callable[[str, str], None],
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Path:
    """Déplace un dossier de film sous `<root>/<collection_root_name>/`.

    No-op si `enable_collection_folder` est désactivé, si déjà sous la racine
    Collection ou si la cible existe déjà. Renvoie le nouveau chemin (ou le
    même si pas déplacé).
    """
    if not cfg.enable_collection_folder:
        return folder
    if core_mod.is_under_collection_root(cfg, folder):
        return folder

    target = cfg.root / cfg.collection_root_name / core_mod.windows_safe(folder.name)
    core_mod.ensure_inside_root(cfg, target)

    if target.exists():
        log("WARN", f"Collection dest exists, skip move: {target}")
        return folder

    log("INFO", f"Move collection folder: {folder} -> {target}")
    if not dry_run:
        (cfg.root / cfg.collection_root_name).mkdir(parents=True, exist_ok=True)
        atomic_move(record_op, src=folder, dst=target, op_type="MOVE_DIR")
        record_apply_op(
            record_op,
            op_type="MOVE_DIR",
            src_path=folder,
            dst_path=target,
            reversible=True,
        )
    return target


# 259L : orchestrateur principal apply — boucle lineaire sur chaque row
# avec dispatch par kind (single/collection/tv). Decoupage non trivial
# sans perte de cohesion (cfg/dry_run/record_op/log_fn partagés).
def apply_rows(
    cfg: "Config",
    rows: list["PlanRow"],
    decisions: Dict[str, Dict[str, object]],
    *,
    dry_run: bool,
    quarantine_unapproved: bool,
    log: Callable[[str, str], None],
    run_review_root: Optional[Path] = None,
    decision_presence: Optional[Set[str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
    duplicate_loser_row_ids: Optional[Set[str]] = None,
    marked_for_deletion_row_ids: Optional[Set[str]] = None,
    progress_cb: Optional[Callable[[int, int, str], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    should_pause: Optional[Callable[[], bool]] = None,
    audit_logger: Optional["ApplyAuditLogger"] = None,
) -> "ApplyResult":
    """Execute the rename/move plan: process each approved row, handle merges, conflicts, quarantine, and cleanup.

    Phase 6 doublons (spec 01-doublons.md §3.7) : si `duplicate_loser_row_ids`
    est fourni, ces rows sont d'abord déplacés vers `_review/_duplicates_user_decided/`
    et exclus de la boucle apply normale.

    VN-E.3 : `should_pause` est interroge en debut de chaque iteration de la
    boucle principale `for row in rows`. La cancellation prevaut sur la pause.
    Si ni `should_cancel` ni `should_pause` n'est fourni, comportement legacy
    inchange (backward compat).

    VN-E.4 : `audit_logger` (optionnel) recoit 4 events par row :
    `row_decision` (debut), `op_skip` (skip detecte via delta res.skipped),
    `op_conflict` (conflit detecte via delta sur compteurs de conflits),
    `error` (exception attrapee). Backward compat : si None, comportement inchange.
    """
    _logger.info("apply: %d rows a traiter (dry_run=%s)", len(rows), dry_run)
    ctx = build_apply_context(
        cfg,
        rows,
        dry_run=dry_run,
        quarantine_unapproved=quarantine_unapproved,
        run_review_root=run_review_root,
        decision_presence=decision_presence,
    )
    cfg = ctx.cfg
    res = ctx.res
    # F30 : ensemble neuf, appari a CET ApplyResult. En apply reel on pose None
    # pour que la dedup ne puisse pas fuir d'un dry-run vers un apply destructif
    # (ou `path.exists()` reste le seul et unique dedoublonneur).
    _MKDIR_SEEN_DRY_RUN.set((res, set()) if dry_run else None)

    # Phase 6 doublons : déplacer les losers AVANT la boucle apply principale.
    losers_set: Set[str] = {str(r) for r in (duplicate_loser_row_ids or set()) if r}
    if losers_set and ctx.duplicates_user_decided_root is not None:
        abandoned = (
            move_duplicate_losers_to_user_decided(
                cfg,
                rows,
                losers_set,
                duplicates_user_decided_root=ctx.duplicates_user_decided_root,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            or set()
        )
        # Retirer les losers des rows à apply normalement.
        # RELECTURE R2 [D3] : SAUF les row_id ABANDONNES par le fail-closed (rien n'a
        # bouge pour eux). Les exclure quand meme laissait le film ni deplace ni
        # renomme/range : disparition silencieuse du travail attendu.
        excluded = losers_set - abandoned
        rows = [r for r in rows if str(getattr(r, "row_id", "")) not in excluded]

    # AUDIT 2026-06-14 (R7-4) : films marques pour suppression -> bucket dedie
    # AVANT la boucle apply, puis exclus (meme schema que les losers).
    marked_set: Set[str] = {str(r) for r in (marked_for_deletion_row_ids or set()) if r}
    if marked_set and ctx.marked_for_deletion_root is not None:
        abandoned_marked = (
            move_marked_for_deletion_to_bucket(
                cfg,
                rows,
                marked_set,
                marked_for_deletion_root=ctx.marked_for_deletion_root,
                dry_run=dry_run,
                log=log,
                res=res,
                record_op=record_op,
            )
            or set()
        )
        # [D3] : idem losers, les abandons fail-closed restent dans l'apply normal.
        excluded_marked = marked_set - abandoned_marked
        rows = [r for r in rows if str(getattr(r, "row_id", "")) not in excluded_marked]

    # F10 : la migration du dossier collection legacy vit HORS du try per-row.
    # Un PermissionError ici (dossier ouvert dans l'explorateur, fichier lu par
    # VLC) faisait remonter l'exception jusqu'au boundary de l'apply : batch clos
    # FAILED, message brut '[WinError 5]', resultat et resume perdus, et en mode
    # atomique le rollback annulait les rows deja reussies. On degrade desormais
    # comme le handler per-row : erreur comptee, message clair, apply poursuivi
    # (resolve_collection_folder_after_migration gere deja le cas "pas migre").
    try:
        migrate_legacy_collection_root(
            cfg,
            dry_run=dry_run,
            log=log,
            res=res,
            conflicts_root=ctx.conflicts_root,
            conflicts_sidecars_root=ctx.conflicts_sidecars_root,
            duplicates_identical_root=ctx.duplicates_identical_root,
            leftovers_root=ctx.leftovers_root,
            hash_cache=ctx.hash_cache,
            record_op=record_op,
        )
    except PermissionError as exc:
        res.errors += 1
        _append_error_message(res, _locked_msg(legacy_collection_root(cfg).name))
        log("ERROR", f"apply: migration Collection legacy impossible (verrou): {exc}")
    except OSError as exc:
        res.errors += 1
        _append_error_message(res, f"MIGRATION Collection: {exc}")
        log("ERROR", f"apply: migration Collection legacy echouee: {exc}")

    # F10 : rows dont la pre-passe collection a echoue -> on ne les retraite PAS
    # dans la boucle principale (fail-closed). Un shutil.move de DOSSIER interrompu
    # sur Windows laisse src ET dst peuples : empiler un 2e traitement dessus
    # aggraverait l'etat au lieu de le reparer.
    #
    # La memorisation se fait par DOSSIER, pas par row (revue adversaire R1) : un
    # dossier collection porte par definition PLUSIEURS rows, et le
    # `if str(original_folder) in ctx.folder_map: continue` ci-dessous s'execute
    # AVANT le try. Les rows suivantes du meme dossier sortaient donc par ce
    # continue sans jamais etre marquees, et etaient traitees normalement — elles
    # creaient un sous-dossier et y deplacaient leur video A L'INTERIEUR du
    # dossier dont la migration venait d'echouer.
    failed_prepass: Set[str] = set()
    failed_prepass_folders: Set[str] = set()

    for row in rows:
        if row.kind != "collection":
            continue
        original_folder = Path(row.folder)
        if original_folder.parent == cfg.root:
            ctx.touched_top_level_dirs.add(original_folder)

        old_folder = resolve_collection_folder_after_migration(cfg, original_folder)
        if str(original_folder) in ctx.folder_map:
            continue
        # F10 : cette pre-passe deplace des DOSSIERS entiers hors du try per-row.
        # Un verrou Windows y faisait avorter tout le batch avec un message brut.
        try:
            if cfg.enable_collection_folder and (not core_mod.is_under_collection_root(cfg, old_folder)):
                target = cfg.root / cfg.collection_root_name / core_mod.windows_safe(old_folder.name)
                core_mod.ensure_inside_root(cfg, target)
                if target.exists():
                    if target.is_dir():
                        merge_dir_safe(
                            cfg,
                            old_folder,
                            target,
                            dry_run=dry_run,
                            log=log,
                            res=res,
                            conflicts_root=ctx.conflicts_root,
                            conflicts_sidecars_root=ctx.conflicts_sidecars_root,
                            duplicates_identical_root=ctx.duplicates_identical_root,
                            leftovers_root=ctx.leftovers_root,
                            hash_cache=ctx.hash_cache,
                            record_op=record_op,
                        )
                        ctx.folder_map[str(original_folder)] = str(old_folder) if dry_run else str(target)
                        res.collection_moves += 1
                    else:
                        log("WARN", f"Collection destination invalid (file), skip merge: {target}")
                        ctx.folder_map[str(original_folder)] = str(old_folder)
                        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
                else:
                    # Appel local (fonction definie dans ce meme module) au lieu
                    # de passer par core_mod.move_collection_folder qui etait un
                    # re-export backward-compat — cf #83 phase A4.
                    new_folder = move_collection_folder(
                        cfg,
                        old_folder,
                        dry_run=dry_run,
                        log=log,
                        record_op=record_op,
                    )
                    if str(new_folder) != str(old_folder):
                        ctx.folder_map[str(original_folder)] = str(old_folder) if dry_run else str(new_folder)
                        res.collection_moves += 1
                    else:
                        ctx.folder_map[str(original_folder)] = str(old_folder)
            else:
                ctx.folder_map[str(original_folder)] = str(old_folder)
        except PermissionError as exc:
            res.errors += 1
            _append_error_message(res, _locked_msg(old_folder.name))
            log("ERROR", f"apply: pre-passe collection bloquee par un verrou ({old_folder.name}): {exc}")
            ctx.folder_map[str(original_folder)] = str(original_folder)
            failed_prepass.add(str(getattr(row, "row_id", "")))
            failed_prepass_folders.add(str(original_folder))
            continue
        except OSError as exc:
            res.errors += 1
            _append_error_message(res, f"COLLECTION {old_folder.name}: {exc}")
            log("ERROR", f"apply: pre-passe collection echouee ({old_folder.name}): {exc}")
            ctx.folder_map[str(original_folder)] = str(original_folder)
            failed_prepass.add(str(getattr(row, "row_id", "")))
            failed_prepass_folders.add(str(original_folder))
            continue

    def current_folder_path(folder_str: str) -> Path:
        """Retourne le chemin courant d'un folder en tenant compte des moves déjà appliqués."""
        return Path(ctx.folder_map.get(folder_str, folder_str))

    _apply_total = len(rows)
    # VN-E.3 : pause cooperative — sleep court entre 2 polls, cancellation
    # prevaut sur pause. No-op si should_pause/should_cancel non fournis.
    _pause_logged = {"v": False}

    def _wait_while_paused_apply() -> bool:
        """Return True si cancellation pendant pause -> sortir de la boucle."""
        if should_pause is None:
            return False
        try:
            if not bool(should_pause()):
                return False
        except Exception:  # noqa: BLE001
            return False
        if not _pause_logged["v"]:
            log("INFO", "apply: pause requested")
            _pause_logged["v"] = True
        while True:
            if should_cancel is not None:
                try:
                    if bool(should_cancel()):
                        return True
                except Exception:  # noqa: BLE001
                    pass
            try:
                still = bool(should_pause())
            except Exception:  # noqa: BLE001
                still = False
            if not still:
                _pause_logged["v"] = False
                log("INFO", "apply: pause released")
                return False
            time.sleep(0.5)

    for idx, row in enumerate(rows, start=1):
        # F10 (fail-closed) : la pre-passe collection a echoue pour cette row
        # (dossier verrouille, move interrompu). On ne la retraite PAS : sur
        # Windows un move de dossier interrompu laisse source ET destination
        # peuplees, un 2e traitement aggraverait l'etat au lieu de le reparer.
        if (failed_prepass and str(getattr(row, "row_id", "")) in failed_prepass) or (
            failed_prepass_folders and str(getattr(row, "folder", "")) in failed_prepass_folders
        ):
            core_mod._mark_skip(res, core_mod.SKIP_REASON_ERREUR_PRECEDENTE)
            # La progression doit AVANCER meme pour une row skippee : si les
            # dernieres rows du batch sont celles en echec, l'UI resterait
            # bloquee sous 100 % jusqu'a la fin du batch.
            if progress_cb is not None:
                try:
                    progress_cb(idx, _apply_total, str(getattr(row, "folder", "") or row.row_id))
                except Exception:  # noqa: BLE001 - callback exterieur, on swallow
                    _logger.debug("apply: progress_cb error (row skippee)", exc_info=True)
            continue
        # VN-E.3 : pause cooperative + cancel — sortir au plus tot.
        if _wait_while_paused_apply():
            break
        if should_cancel is not None:
            try:
                if bool(should_cancel()):
                    log("INFO", "apply: cancel requested")
                    break
            except Exception:  # noqa: BLE001
                pass
        # Notifier l'UI de la progression de l'apply (1 callback par row).
        # Defensif : ne jamais laisser une exception du callback casser le batch.
        if progress_cb is not None:
            try:
                progress_cb(
                    idx,
                    _apply_total,
                    str(getattr(row, "folder", "") or row.row_id),
                )
            except Exception:  # noqa: BLE001 - callback exterieur, on swallow
                _logger.debug("apply: progress_cb error", exc_info=True)

        dec = decisions.get(row.row_id, {})
        ok = bool(dec.get("ok", False))
        new_title = (dec.get("title") or row.proposed_title).strip()
        # BUG-009 (hotfix) : `int(dec.get("year") or row.proposed_year)` crashait
        # TypeError/ValueError quand l'UI renvoyait un year sous forme de string
        # non-numerique ("", "????", "abc") ou que proposed_year etait None
        # (PlanRow malforme depuis JSON externe). L'exception etait alors absorbee
        # par le catch global (ValueError, TypeError) -> SKIP_REASON_ERREUR_PRECEDENTE
        # sans message clair pour l'utilisateur. On secure le cast et on logge
        # explicitement quand la valeur est inutilisable.
        _raw_year = dec.get("year") or row.proposed_year or 0
        try:
            new_year = int(_raw_year)
        except (TypeError, ValueError):
            log(
                "WARN",
                f"YEAR_CAST row {row.row_id} : annee invalide ({_raw_year!r}), fallback 0",
            )
            new_year = 0

        folder = current_folder_path(row.folder)
        if folder.parent == cfg.root:
            ctx.touched_top_level_dirs.add(folder)

        # VN-E.4 : emit row_decision (UI accept/reject) - sortable par row_id.
        if audit_logger is not None:
            try:
                # Fix R6-05 : preserver le tri-etat `deferred` dans l'audit
                # row_decision. Sans cela les films reportes par l'utilisateur
                # apparaissent comme `user_rejected` dans apply_audit.jsonl,
                # ce qui fausse la tracabilite post-apply (cf apply_audit.py
                # objectif "pourquoi ce fichier a ete deplace la").
                _dec_reason = (
                    "user_approved"
                    if ok
                    else (
                        "user_deferred"
                        if dec.get("decision") == "deferred"
                        else "validation_absente"
                        if row.row_id not in ctx.decision_keys
                        else "user_rejected"
                    )
                )
                audit_logger.row_decision(
                    row_id=str(row.row_id),
                    ok=ok,
                    title=new_title or None,
                    year=int(new_year) if new_year else None,
                    reason=_dec_reason,
                )
            except Exception:  # noqa: BLE001 - audit ne doit jamais casser l'apply
                _logger.debug("apply: audit_logger.row_decision failed", exc_info=True)

        # VN-E.4 : snapshot des compteurs de skip/conflict pour detecter les
        # deltas post-row et emettre op_skip / op_conflict correspondants.
        _audit_pre_skipped = int(res.skipped)
        _audit_pre_skip_reasons = dict(res.skip_reasons) if audit_logger is not None else {}
        _audit_pre_conflicts = (
            int(res.conflicts_quarantined_count),
            int(res.sidecar_conflicts_kept_both_count),
            int(res.duplicates_identical_moved_count),
        )

        # Wrap record_op to inject row_id for Undo v5 traceability.
        # Hotfix3 (mega-hotfix) : binder `record_op` via default arg explicite
        # (pas seulement via fermeture) pour eviter une dependance sur la cellule
        # de fermeture si record_op etait rebind plus tard dans le scope englobant
        # (defensive contre refactor : la fermeture capturait la *cellule* du nom
        # `record_op`, le default arg capture *la valeur courante*).
        row_record_op = None
        if record_op is not None:
            _current_row_id = str(row.row_id or "")
            _record_op_ref = record_op

            def _inject_row_id(
                payload: Dict[str, Any],
                _current_row_id: str = _current_row_id,
                _record_op_ref: Callable[[Dict[str, Any]], None] = _record_op_ref,
            ) -> None:
                """Injecte `row_id` dans le payload pour la traçabilité Undo v5."""
                if isinstance(payload, dict) and not payload.get("row_id"):
                    payload["row_id"] = _current_row_id
                _record_op_ref(payload)

            # AUDIT 2026-06-10 (HIGH, REAL 2/2) : une fonction nue perdait les
            # attributs journal_store/journal_batch_id portes par
            # RecordOpWithJournal -> atomic_move retombait sur shutil.move SANS
            # journal write-ahead (protection CR-1 contre crash mi-move
            # silencieusement desactivee). On re-enrobe pour conserver ces
            # attributs tout en injectant row_id.
            row_record_op = RecordOpWithJournal(
                _inject_row_id,
                store=getattr(_record_op_ref, "journal_store", None),
                batch_id=getattr(_record_op_ref, "journal_batch_id", None),
            )

        try:
            if ok:
                pre_actions = (
                    res.renames,
                    res.moves,
                    res.mkdirs,
                    res.collection_moves,
                    res.quarantined,
                    res.merges_count,
                    res.duplicates_identical_moved_count,
                    res.conflicts_quarantined_count,
                    res.sidecar_conflicts_kept_both_count,
                    res.leftovers_moved_count,
                    res.source_dirs_deleted_count,
                )
                pre_skipped = res.skipped
                pre_errors = res.errors
                if row.kind == "tv_episode":
                    apply_tv_episode(
                        cfg,
                        folder,
                        row,
                        dry_run,
                        log,
                        res,
                        conflicts_root=ctx.conflicts_root,
                        conflicts_sidecars_root=ctx.conflicts_sidecars_root,
                        duplicates_identical_root=ctx.duplicates_identical_root,
                        hash_cache=ctx.hash_cache,
                        record_op=row_record_op,
                        new_title=new_title,
                        new_year=new_year,
                    )
                elif row.kind == "single":
                    apply_single(
                        cfg,
                        folder,
                        new_title,
                        new_year,
                        dry_run,
                        log,
                        res,
                        conflicts_root=ctx.conflicts_root,
                        conflicts_sidecars_root=ctx.conflicts_sidecars_root,
                        duplicates_identical_root=ctx.duplicates_identical_root,
                        leftovers_root=ctx.leftovers_root,
                        hash_cache=ctx.hash_cache,
                        record_op=row_record_op,
                        tmdb_collection_name=getattr(row, "tmdb_collection_name", None),
                        edition=getattr(row, "edition", None),
                        # Cf issue #78 : passer le nom du video deja resolu au
                        # scan pour eviter un iterdir+stat dans apply_single.
                        main_video_filename=getattr(row, "video", None) or None,
                    )
                else:
                    apply_collection_item(
                        cfg,
                        folder,
                        row.video,
                        new_title,
                        new_year,
                        dry_run,
                        log,
                        res,
                        conflicts_root=ctx.conflicts_root,
                        conflicts_sidecars_root=ctx.conflicts_sidecars_root,
                        duplicates_identical_root=ctx.duplicates_identical_root,
                        hash_cache=ctx.hash_cache,
                        dedup_seen_ops=ctx.dedup_seen_ops,
                        record_op=row_record_op,
                        edition=getattr(row, "edition", None),
                    )
                post_actions = (
                    res.renames,
                    res.moves,
                    res.mkdirs,
                    res.collection_moves,
                    res.quarantined,
                    res.merges_count,
                    res.duplicates_identical_moved_count,
                    res.conflicts_quarantined_count,
                    res.sidecar_conflicts_kept_both_count,
                    res.leftovers_moved_count,
                    res.source_dirs_deleted_count,
                )
                if post_actions != pre_actions:
                    res.applied_count += 1
                elif res.skipped == pre_skipped and res.errors == pre_errors:
                    core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
            else:
                if quarantine_unapproved:
                    quarantine_row(
                        cfg,
                        folder,
                        row,
                        dry_run,
                        log,
                        res,
                        ctx.review_root,
                        record_op=row_record_op,
                    )
                else:
                    if row.row_id not in ctx.decision_keys:
                        core_mod._mark_skip(res, core_mod.SKIP_REASON_VALIDATION_ABSENTE)
                    else:
                        core_mod._mark_skip(res, core_mod.SKIP_REASON_NON_VALIDE)
        except PermissionError as exc:
            # Fix audit 2026-05-25 (v1.5.3) Vague H : message clair Windows file lock.
            # Avant : le catch fourre-tout ci-dessous loguait seulement "fs_error" sans
            # indiquer a l'utilisateur que le film etait probablement ouvert dans VLC
            # (cas Windows tres frequent : fichier .mkv lu/probe par un autre process).
            # Le texte vit dans `_locked_msg` : la pre-passe collection et le
            # nettoyage post-boucle (F10) doivent produire le MEME message, sinon
            # les deux formulations divergent au fil des retouches.
            err_msg = _locked_msg(folder.name)
            res.errors += 1
            # Remonter le message a l'UI via ApplyResult.error_messages (cf core.py).
            try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
                res.error_messages.append(err_msg)
            except AttributeError:  # noqa: BLE001 - retro-compat tests anciens
                pass
            core_mod._mark_skip(res, core_mod.SKIP_REASON_ERREUR_PRECEDENTE)
            _logger.error(
                "apply: PermissionError row_id=%s folder=%s err=%s",
                getattr(row, "row_id", "?"),
                folder,
                exc,
            )
            log("ERROR", err_msg)
            # VN-E.4 : emit error event (PermissionError = Windows file lock)
            if audit_logger is not None:
                try:
                    audit_logger.error(
                        context="apply_row_permission_error",
                        message=f"PermissionError: {exc}",
                        row_id=str(getattr(row, "row_id", "") or ""),
                    )
                except Exception:  # noqa: BLE001
                    _logger.debug("apply: audit_logger.error failed", exc_info=True)
            continue
        except (FileNotFoundError, FileExistsError, OSError) as exc:
            # Sprint 2 audit P0 #5 : separer FS errors (attendues, log warning) des
            # state errors (bug logique, log error). Avant : tout etait swallow sans
            # contexte. Le run continue (res.errors++) car un seul film en echec
            # ne doit pas bloquer le reste du batch.
            res.errors += 1
            core_mod._mark_skip(res, core_mod.SKIP_REASON_ERREUR_PRECEDENTE)
            _logger.warning(
                "apply: fs_error row_id=%s folder=%s err=%s",
                getattr(row, "row_id", "?"),
                folder,
                exc,
            )
            log("ERROR", f"Erreur application ({row.row_id}) : {exc}")
            # VN-E.4 : emit error event (FS error attendu)
            if audit_logger is not None:
                try:
                    audit_logger.error(
                        context="apply_row_fs_error",
                        message=f"{type(exc).__name__}: {exc}",
                        row_id=str(getattr(row, "row_id", "") or ""),
                    )
                except Exception:  # noqa: BLE001
                    _logger.debug("apply: audit_logger.error failed", exc_info=True)
        except (ValueError, TypeError) as exc:
            # State error : indique un bug (row malformee, decision incompatible).
            # On logge en error pour visibilite mais on n'arrete pas le batch :
            # comme pour FS errors, on marque la row en erreur et on continue.
            res.errors += 1
            core_mod._mark_skip(res, core_mod.SKIP_REASON_ERREUR_PRECEDENTE)
            _logger.error(
                "apply: state_error row_id=%s folder=%s err=%s",
                getattr(row, "row_id", "?"),
                folder,
                exc,
                exc_info=exc,
            )
            log("ERROR", f"Erreur application ({row.row_id}) : {exc}")
            # VN-E.4 : emit error event (state error / bug logique)
            if audit_logger is not None:
                try:
                    audit_logger.error(
                        context="apply_row_state_error",
                        message=f"{type(exc).__name__}: {exc}",
                        row_id=str(getattr(row, "row_id", "") or ""),
                    )
                except Exception:  # noqa: BLE001
                    _logger.debug("apply: audit_logger.error failed", exc_info=True)

        # VN-E.4 : detection post-row des skips / conflicts emis pendant le row.
        # Compare counters pre/post pour identifier la raison dominante.
        if audit_logger is not None:
            try:
                _audit_post_conflicts = (
                    int(res.conflicts_quarantined_count),
                    int(res.sidecar_conflicts_kept_both_count),
                    int(res.duplicates_identical_moved_count),
                )
                _conflict_delta = tuple(_audit_post_conflicts[i] - _audit_pre_conflicts[i] for i in range(3))
                if _conflict_delta[0] > 0:
                    audit_logger.conflict(
                        row_id=str(row.row_id),
                        src=str(folder),
                        dst="",
                        conflict_type="file_conflict",
                        resolution="moved_to_review_conflicts",
                    )
                if _conflict_delta[1] > 0:
                    audit_logger.conflict(
                        row_id=str(row.row_id),
                        src=str(folder),
                        dst="",
                        conflict_type="sidecar_conflict",
                        resolution="kept_both",
                    )
                if _conflict_delta[2] > 0:
                    audit_logger.conflict(
                        row_id=str(row.row_id),
                        src=str(folder),
                        dst="",
                        conflict_type="duplicate_identical",
                        resolution="moved_to_duplicates_identical",
                    )
                # op_skip : emission au niveau row (delta skip_reasons)
                if int(res.skipped) > int(_audit_pre_skipped):
                    _new_reasons = {
                        k: int(res.skip_reasons.get(k, 0)) - int(_audit_pre_skip_reasons.get(k, 0))
                        for k in res.skip_reasons.keys()
                    }
                    _new_reasons = {k: v for k, v in _new_reasons.items() if v > 0}
                    for _reason, _count in _new_reasons.items():
                        audit_logger.skip(
                            row_id=str(row.row_id),
                            reason=str(_reason),
                            detail=f"count={_count}",
                        )
            except Exception:  # noqa: BLE001
                _logger.debug("apply: audit post-row delta emit failed", exc_info=True)

    cleanup_preview = preview_cleanup_residual_folders(cfg, ctx.touched_top_level_dirs)
    # F10 : le nettoyage post-boucle vit lui aussi hors du try per-row et deplace
    # des dossiers. Un verrou y faisait perdre le resultat ENTIER de l'apply
    # (rows deja traitees comprises). On le degrade en erreur comptee : le
    # diagnostic residuel et le resume restent produits.
    try:
        _move_residual_top_level_dirs(
            cfg,
            dry_run=dry_run,
            log=log,
            res=res,
            touched_top_level_dirs=ctx.touched_top_level_dirs,
            record_op=record_op,
        )
    except PermissionError as exc:
        res.errors += 1
        _append_error_message(res, f"NETTOYAGE RESIDUEL bloque par un verrou : {exc}")
        log("ERROR", f"apply: nettoyage residuel bloque par un verrou: {exc}")
    except OSError as exc:
        res.errors += 1
        _append_error_message(res, f"NETTOYAGE RESIDUEL : {exc}")
        log("ERROR", f"apply: nettoyage residuel echoue: {exc}")
    cleanup_preview["moved_count"] = int(res.cleanup_residual_folders_moved_count or 0)
    cleanup_preview["left_in_place_count"] = int(
        cleanup_preview.get("has_video_count", 0)
        + cleanup_preview.get("ambiguous_count", 0)
        + cleanup_preview.get("symlink_count", 0)
        + cleanup_preview.get("no_files_count", 0)
    )
    if not cfg.cleanup_residual_folders_enabled:
        cleanup_preview["status_post"] = "disabled"
        cleanup_preview["message_post"] = "Nettoyage résiduel désactivé."
    elif dry_run:
        cleanup_preview["status_post"] = "not_executed"
        cleanup_preview["message_post"] = (
            "Dry-run : nettoyage résiduel non exécuté. " + str(cleanup_preview.get("message") or "")
        ).strip()
    elif int(res.cleanup_residual_folders_moved_count or 0) > 0:
        cleanup_preview["status_post"] = "executed"
        cleanup_preview["message_post"] = (
            f"Nettoyage résiduel exécuté : {int(res.cleanup_residual_folders_moved_count or 0)} "
            f"dossier(s) déplacé(s) vers {cfg.cleanup_residual_folders_folder_name}."
        )
    else:
        cleanup_preview["status_post"] = "executed_no_move"
        cleanup_preview["message_post"] = (
            "Nettoyage résiduel exécuté sans déplacement. " + str(cleanup_preview.get("message") or "")
        ).strip()
    res.cleanup_residual_diagnostic = cleanup_preview
    # F10 : idem pour le deplacement des dossiers vides.
    try:
        _move_empty_top_level_dirs(
            cfg,
            dry_run=dry_run,
            log=log,
            res=res,
            touched_top_level_dirs=ctx.touched_top_level_dirs,
            record_op=record_op,
        )
    except PermissionError as exc:
        res.errors += 1
        _append_error_message(res, f"NETTOYAGE DOSSIERS VIDES bloque par un verrou : {exc}")
        log("ERROR", f"apply: nettoyage dossiers vides bloque par un verrou: {exc}")
    except OSError as exc:
        res.errors += 1
        _append_error_message(res, f"NETTOYAGE DOSSIERS VIDES : {exc}")
        log("ERROR", f"apply: nettoyage dossiers vides echoue: {exc}")
    _logger.info(
        "apply: termine — renames=%d moves=%d skipped=%d quarantined=%d errors=%d (dry_run=%s)",
        res.renames,
        res.moves,
        res.skipped,
        res.quarantined,
        res.errors,
        dry_run,
    )
    return res


def apply_single(
    cfg: "Config",
    folder: Path,
    title: str,
    year: int,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    *,
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    leftovers_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
    tmdb_collection_name: Optional[str] = None,
    edition: Optional[str] = None,
    main_video_filename: Optional[str] = None,
) -> None:
    """Renomme/déplace un dossier de film "single" vers `Titre (Année)` (option Edition).

    Si la cible existe déjà comme dossier, fusionne via `merge_dir_safe` plutôt
    que d'écraser. Si TMDb renvoie une collection (saga) et `enable_collection_folder`,
    place sous `<root>/<collection_root_name>/<saga>/`.
    """
    if not folder.exists():
        log("WARN", f"Single folder missing, skip: {folder}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return
    # ITER7 etape 3 : approvisionnement cfg.separator -> ctx["sep"] via
    # build_naming_context. Templates existants {title} ({year}) inchanges,
    # templates custom peuvent referencer {sep} (opt-in, STOP_FORK preserve).
    _naming_ctx = build_naming_context(
        title=title,
        year=year,
        edition=edition or "",
        separator=getattr(cfg, "separator", " "),
    )
    new_name = format_movie_folder(cfg.naming_movie_template, _naming_ctx)

    # Si collection TMDb + collection_folder_enabled → placer dans _Collection/Saga/
    # R8-085 : PAS de mkdir ici — un mkdir avant les gardes MAX_PATH/NOOP creait
    # un dossier saga vide orphelin meme quand la row etait ensuite skippee.
    _coll_name = (tmdb_collection_name or "").strip()
    coll_dir: Optional[Path] = None
    if _coll_name and cfg.enable_collection_folder:
        coll_dir = cfg.root / cfg.collection_root_name / core_mod.windows_safe(_coll_name)
        dst = coll_dir / new_name
    else:
        dst = folder.parent / new_name
    core_mod.ensure_inside_root(cfg, dst)

    # VQ-3 : kill-switch MAX_PATH Windows. Si le path cible > 259 chars on
    # skip proprement plutot que tenter le rename et generer un OSError
    # obscur (ou pire un rename partiel laissant le FS incoherent).
    # Fix item #15 2026-06-08 : on verifie le path du dossier renomme ET le path
    # du fichier interne le plus long (post-rename), car windows_safe tronque
    # le nom de dossier a 180 chars mais l'ajout du nom de fichier interne
    # (ex: "movie.mkv" ou un sidecar long) peut faire exceder MAX_PATH.
    # Sans ce check on laisse passer un rename qui generera un OSError obscur
    # au premier acces FS sur le fichier interne, ou un rename partiel.
    _longest_inner: str = ""
    try:
        for _p in folder.iterdir():
            if _p.name and len(_p.name) > len(_longest_inner):
                _longest_inner = _p.name
    except (OSError, PermissionError):
        _longest_inner = ""
    _candidate_inner_path = str(dst / _longest_inner) if _longest_inner else str(dst)
    _path_err = check_path_length_killswitch(str(dst)) or check_path_length_killswitch(_candidate_inner_path)
    if _path_err is not None:
        log("WARN", _path_err)
        try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
            res.error_messages.append(_path_err)
        except AttributeError:  # noqa: BLE001 - retro-compat tests anciens
            pass
        core_mod._mark_skip(res, core_mod.SKIP_REASON_PATH_TOO_LONG)
        return

    if core_mod._single_folder_is_conform(folder.name, title, year, naming_template=cfg.naming_movie_template):
        core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        return

    # Fix audit 2026-05-25 (v1.5.5) Vague J : guard explicite src == dst.
    # _single_folder_is_conform peut retourner False sur des cas subtils
    # (Unicode NFC vs NFD, espaces speciaux, template avec edition vide) alors
    # que folder.name == dst.name caractere par caractere. Sans ce guard, on
    # genere un faux rename "X -> X" dans la preview (et un rename inutile en
    # apply reel via le bloc tmp_ren pour case-change Windows).
    # NB : on compare les Path resolus pour gerer aussi les separateurs et
    # la casse Windows (folder.samefile() echouerait si dst n'existe pas).
    # Fix audit 2026-05-30 Vague J renforce : str(folder) == str(dst) ne capte
    # pas l'equivalence FS Windows/SMB (case-only, NFC vs NFD, NBSP vs space).
    # Le filesystem cible (Windows local + SMB share) traite ces variantes comme
    # le MEME chemin physique. Sans ce filet, on emet un faux rename qui
    # declenche une cascade merge_dir_safe -> MOVE_FILE inutiles dans la preview.
    def _fs_equivalent(a: Path, b: Path) -> bool:
        # Compare via PureWindowsPath normcase (lower) + NFC normalize des noms.
        norm_a = unicodedata.normalize("NFC", a.name).casefold()
        norm_b = unicodedata.normalize("NFC", b.name).casefold()
        if norm_a != norm_b:
            return False
        # Meme nom apres normalisation -> verifier qu'on est dans le meme parent.
        try:
            return core_mod._norm_win_path(a.parent) == core_mod._norm_win_path(b.parent)
        except (OSError, ValueError):
            return str(a.parent).casefold() == str(b.parent).casefold()

    if str(folder) == str(dst) or _fs_equivalent(folder, dst):
        log("INFO", f"NOOP rename: src equivalent dst on FS ({folder} ~= {dst})")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        return

    if dst.exists():
        if not dst.is_dir():
            log("WARN", f"Rename destination invalid (not directory), skip: {dst}")
            core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
            return
        core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
        merge_dir_safe(
            cfg,
            folder,
            dst,
            dry_run=dry_run,
            log=log,
            res=res,
            conflicts_root=conflicts_root,
            conflicts_sidecars_root=conflicts_sidecars_root,
            duplicates_identical_root=duplicates_identical_root,
            leftovers_root=leftovers_root,
            hash_cache=hash_cache,
            record_op=record_op,
        )
        return

    log("INFO", f"RENAME: {folder} -> {dst}")

    # R8-085 A+B : mkdir saga APRES toutes les gardes (MAX_PATH, NOOP conforme,
    # equivalence FS, merge) et via mkdir_counted — chaque niveau cree est
    # journalise en op MKDIR pour que l'undo supprime les dossiers redevenus
    # vides (restauration a l'identique). Le parent (<root>/_Collection) est
    # journalise separement car mkdir_counted ne trace que le dernier segment.
    if coll_dir is not None and not coll_dir.exists():
        if not coll_dir.parent.exists():
            mkdir_counted(coll_dir.parent, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)
        mkdir_counted(coll_dir, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)

    moved_from = folder
    moved_to = dst
    src_sha1: Optional[str] = None
    src_size: Optional[int] = None

    if not dry_run:
        # P1.2 : capturer le hash du fichier video principal AVANT le rename.
        # Cf issue #78 : si le caller a deja le nom du fichier video (depuis
        # PlanRow.video au scan), on evite le iterdir+stat de
        # find_main_video_in_folder — coute 50-500s sur 5000 films SMB.
        main_video: Optional[Path] = None
        if main_video_filename:
            candidate = folder / main_video_filename
            if candidate.is_file():
                main_video = candidate
        if main_video is None:
            main_video = find_main_video_in_folder(folder, cfg)
        if main_video is not None:
            try:
                src_size = main_video.stat().st_size
                src_sha1 = sha1_quick_cached(main_video, hash_cache)
            except (OSError, PermissionError) as exc:
                _logger.debug("P1.2: sha1 pre-apply (MOVE_DIR) echoue pour %s: %s", main_video, exc)
                src_sha1 = None
                src_size = None

        if folder.name.lower() == dst.name.lower():
            # Fix audit 2026-05-26 (v1.5.6) Vague L : extraction en helper
            # _case_only_rename_with_rollback pour tester le COMPORTEMENT de
            # rollback (assertLogs sur logger.warning) au lieu de matcher le
            # texte du source code.
            _case_only_rename_with_rollback(folder, dst)
        else:
            # Hotfix2 H5 (DATA LOSS) : guard explicite avant rename pour eviter
            # ecrasement silencieux. dst.exists() etait verifie l. 1619 mais la
            # fenetre TOCTOU jusqu'ici peut etre longue (sha1 du main_video sur
            # SMB). Sur POSIX, Path.rename() ECRASE silencieusement la cible si
            # elle existe ; sur Windows ca leve FileExistsError mais le
            # comportement SMB est variable. On force une erreur explicite et
            # cohrente plutot que de perdre des donnees.
            if dst.exists():
                raise FileExistsError(f"apply_single: destination apparue pendant l'apply (race condition) : {dst}")
            folder.rename(dst)

    # P1.3 : record l'op même en dry_run pour la preview UI
    record_apply_op(
        record_op,
        op_type="MOVE_DIR",
        src_path=moved_from,
        dst_path=moved_to,
        reversible=True,
        src_sha1=src_sha1,
        src_size=src_size,
    )
    res.renames += 1


def apply_collection_item(
    cfg: "Config",
    folder: Path,
    video_name: str,
    title: str,
    year: int,
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    *,
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    dedup_seen_ops: Optional[Set[Tuple[str, str, str]]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
    edition: Optional[str] = None,
) -> None:
    """Déplace un film d'une collection (multi-films par dossier) dans son sous-dossier dédié.

    Crée `folder/Titre (Année)/`, déplace la vidéo + sidecars associés en
    appliquant la politique de collision. Le set `dedup_seen_ops` évite de
    refaire le même move au sein d'un batch.
    """
    if not folder.exists():
        log("WARN", f"Collection folder missing, skip: {folder}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
        return

    video = core_mod._find_video_case_insensitive(folder, video_name)
    if not video:
        video = folder / video_name

    if not video.exists():
        merged_video = None
        try:
            merged_video = next(
                (path for path in folder.rglob("*") if path.is_file() and _name_eq_fs(path.name, str(video_name))),
                None,
            )
        except (OSError, PermissionError):
            merged_video = None
        log("WARN", f"Video missing, skip: {folder}/{video_name}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED if merged_video else core_mod.SKIP_REASON_AUTRE)
        return

    # ITER7 etape 3 : approvisionnement cfg.separator (cf. site apply_single).
    _naming_ctx = build_naming_context(
        title=title,
        year=year,
        edition=edition or "",
        separator=getattr(cfg, "separator", " "),
    )
    sub_name = format_movie_folder(cfg.naming_movie_template, _naming_ctx)
    sub_dir = folder / sub_name
    core_mod.ensure_inside_root(cfg, sub_dir)

    # VQ-3 : kill-switch MAX_PATH Windows. Verifier le path du sous-dossier
    # ET le path final video (sub_dir/video.name) car c'est ce dernier qui
    # peut exceder 260 chars meme si sub_dir reste valide.
    # Regle inviolable n1 : `video.name` tel quel, jamais reconstruit.
    _candidate_video_path = sub_dir / video.name
    _path_err = check_path_length_killswitch(str(_candidate_video_path))
    if _path_err is not None:
        log("WARN", _path_err)
        try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
            res.error_messages.append(_path_err)
        except AttributeError:  # noqa: BLE001 - retro-compat tests anciens
            pass
        core_mod._mark_skip(res, core_mod.SKIP_REASON_PATH_TOO_LONG)
        return

    if not sub_dir.exists():
        mkdir_counted(sub_dir, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)

    # R8-001 (F1, PERTE DE DONNEES) : atomicite intra-row.
    # Un item de collection deplace ses sidecars PUIS sa video. Si une etape echoue
    # (ex. .mkv verrouille -> PermissionError dans atomic_move), l'ancien code laissait
    # les sidecars deja deplaces + la video en source = item A MOITIE applique, sans
    # rollback ; et le ledger dedup, marque AVANT le move, faisait skipper l'item au
    # retry => demi-application PERMANENTE (irrecuperable). Cf baseline COLL-ATOMIC.
    # Fix : (A) on suit les moves reellement effectues et on les ANNULE si une etape
    # echoue (etat tout-ou-rien) ; (B) on ne marque le ledger dedup QU'APRES le succes
    # complet de chaque move (sinon le retry skipperait un item partiel).
    moved_for_rollback: list[Tuple[Path, Path]] = []  # (dst effectif, src d'origine)
    dedup_added_this_item: list[Tuple[str, str, str]] = []

    def _commit_dedup(key: Optional[Tuple[str, str, str]]) -> None:
        if key is not None and dedup_seen_ops is not None:
            dedup_seen_ops.add(key)
            dedup_added_this_item.append(key)

    def _rollback_partial_item() -> None:
        # Restaure un etat COHERENT : remet en source (ordre inverse) chaque fichier
        # reellement deplace par cet item. Best-effort : un echec de revert est logge
        # mais n'interrompt pas les autres reverts.
        for dst_done, src_orig in reversed(moved_for_rollback):
            try:
                if dst_done.exists() and not src_orig.exists():
                    atomic_move(
                        record_op,
                        src=dst_done,
                        dst=src_orig,
                        op_type="ROLLBACK_COLLECTION_MOVE",
                    )
                    record_apply_op(
                        record_op,
                        op_type="ROLLBACK_COLLECTION_MOVE",
                        src_path=dst_done,
                        dst_path=src_orig,
                        reversible=False,
                    )
                    res.moves = max(0, res.moves - 1)
                    log("WARN", f"ROLLBACK collection (atomicite intra-row): {dst_done} -> {src_orig}")
            except (OSError, PermissionError) as rb_exc:
                log("ERROR", f"ROLLBACK collection ECHEC {dst_done} -> {src_orig}: {rb_exc}")
        # (B) un retry doit re-traiter l'item : retirer du ledger les cles ajoutees ici.
        if dedup_seen_ops is not None:
            for k in dedup_added_this_item:
                dedup_seen_ops.discard(k)

    try:
        for sidecar in core_mod.classify_sidecars(cfg, folder, video, is_collection=True):
            dst = sub_dir / sidecar.name
            op_key: Optional[Tuple[str, str, str]] = None
            if dedup_seen_ops is not None:
                op_key = (
                    str(core_mod._norm_win_path(sidecar)),
                    str(core_mod._norm_win_path(dst)),
                    "collection_sidecar",
                )
                if op_key in dedup_seen_ops:
                    log("INFO", f"SKIP_DEDUP collection_sidecar: {sidecar} -> {dst}")
                    core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
                    continue
            status = move_file_with_collision_policy(
                cfg,
                sidecar,
                dst,
                src_anchor=folder,
                dry_run=dry_run,
                log=log,
                res=res,
                conflicts_root=conflicts_root,
                conflicts_sidecars_root=conflicts_sidecars_root,
                duplicates_identical_root=duplicates_identical_root,
                hash_cache=hash_cache,
                record_op=record_op,
            )
            _commit_dedup(op_key)  # (B) ledger marque seulement apres move reussi
            if status == "moved" and not dry_run:
                moved_for_rollback.append((dst, sidecar))
            if status == "duplicate_identical":
                core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
            elif status in {"conflict", "sidecar_conflict"}:
                core_mod._mark_skip(res, core_mod.SKIP_REASON_CONFLIT_QUARANTAINE)

        # Regle inviolable n1 : nom de fichier video preserve a l'identique.
        dst_video = sub_dir / video.name
        vid_key: Optional[Tuple[str, str, str]] = None
        if dedup_seen_ops is not None:
            vid_key = (str(core_mod._norm_win_path(video)), str(core_mod._norm_win_path(dst_video)), "collection_video")
            if vid_key in dedup_seen_ops:
                log("INFO", f"SKIP_DEDUP collection_video: {video} -> {dst_video}")
                core_mod._mark_skip(res, core_mod.SKIP_REASON_MERGED)
                return
        status = move_file_with_collision_policy(
            cfg,
            video,
            dst_video,
            src_anchor=folder,
            dry_run=dry_run,
            log=log,
            res=res,
            conflicts_root=conflicts_root,
            conflicts_sidecars_root=conflicts_sidecars_root,
            duplicates_identical_root=duplicates_identical_root,
            hash_cache=hash_cache,
            record_op=record_op,
        )
        _commit_dedup(vid_key)  # (B) ledger marque seulement apres move video reussi
        if status == "moved" and not dry_run:
            moved_for_rollback.append((dst_video, video))
        if status == "duplicate_identical":
            core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        elif status in {"conflict", "sidecar_conflict"}:
            core_mod._mark_skip(res, core_mod.SKIP_REASON_CONFLIT_QUARANTAINE)
    except (OSError, PermissionError) as exc:
        # Echec mid-item : restaurer l'etat coherent (rollback), liberer le ledger,
        # puis RE-LEVER pour que la boucle per-row (apply_core.py:~1650) enregistre
        # l'erreur "FICHIER VERROUILLE" et poursuive le batch (resilience per-row).
        log("ERROR", f"apply_collection_item: echec move, rollback intra-row ({folder.name}): {exc}")
        _rollback_partial_item()
        raise


def apply_tv_episode(
    cfg: "Config",
    folder: Path,
    row: "PlanRow",
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    *,
    conflicts_root: Path,
    conflicts_sidecars_root: Path,
    duplicates_identical_root: Path,
    hash_cache: Optional[Dict[Tuple[str, int, int], str]] = None,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
    new_title: Optional[str] = None,
    new_year: Optional[int] = None,
) -> None:
    """Rename/move a TV episode into Série (année)/Saison NN/S01E01 - Titre.ext structure.

    R8-F2-a : mis à PARITÉ avec le chemin film (apply_single/apply_collection_item).
    Les moves vidéo + sidecars passent par `move_file_with_collision_policy` (sha1/size,
    politique de collision + comparaison contenu, ops journalisées même en dry_run,
    mkdir compté) ; les sidecars sont réalignés sur le stem cible (SxxExx - Titre) ;
    le kill-switch MAX_PATH vérifie aussi les sidecars internes ; l'item est atomique
    intra-row (rollback des fichiers déjà déplacés si une étape échoue).
    (`new_title`/`new_year` : édition UI titre/année — câblés F2-a gate 7.)
    """
    # Garde-fou destructif : `row.video` vide -> `folder / ""` == folder (verifie),
    # donc `.exists()` est True et le chemin "video manquante" ci-dessous ne se
    # declenche PAS. Le DOSSIER se retrouve alors passe a
    # move_file_with_collision_policy() qui ne teste jamais `src.is_file()` :
    # atomic_move() deplace le dossier COMPLET vers `Saison NN/SxxExx - Titre.ext`.
    # PlanRow.video est documente "can be empty" (domain/core.py) -> refuser plutot
    # que tenter le move.
    if not row.video:
        log("WARN", f"TV episode video field empty: {folder}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return

    video = folder / row.video
    if not video.exists():
        try:
            matches = [p for p in folder.iterdir() if p.is_file() and _name_eq_fs(p.name, row.video)]
            video = matches[0] if matches else video
        except (PermissionError, OSError) as exc:
            # Revue PR#561 (sourcery-ai) : sans ce log, un NAS qui refuse
            # l'enumeration (permission denied, share tombe) est rapporte a
            # l'identique d'un dossier ou la video est reellement absente. Le
            # skip est le meme dans les deux cas, mais le diagnostic ne l'est
            # pas : on nomme la cause pour ne pas envoyer l'utilisateur
            # chercher un fichier qui est en fait la.
            log("WARN", f"TV episode listing failed: {folder} ({type(exc).__name__}: {exc})")
    if not video.exists():
        log("WARN", f"TV episode video missing: {video}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return

    # GATE 7 (TV-UIEDIT) : honorer l'édition UI titre/année de la décision (parité
    # apply_single, qui reçoit new_title/new_year de `dec`). Sans ça, une correction
    # de série/année saisie en validation sur un épisode TV était silencieusement
    # ignorée (l'apply nommait depuis row.proposed_*). new_title pilote l'identifiant
    # de la série (le dossier) ; new_year l'année. Fallback sur row.* si non fourni.
    _eff_series = (new_title or "").strip() or str(row.tv_series_name or row.proposed_title or "")
    year = int(new_year) if (new_year is not None and int(new_year or 0) > 0) else int(row.proposed_year or 0)
    season = int(row.tv_season or 0)
    episode = int(row.tv_episode or 0)
    ep_title = str(row.tv_episode_title or "").strip()

    # Build target path: root / Série (année) / Saison NN / <nom source>
    # ITER7 etape 3 : approvisionnement cfg.separator (cf. site apply_single).
    _naming_ctx = build_naming_context(
        title=_eff_series,
        year=year,
        tv_series_name=_eff_series,
        tv_season=season,
        tv_episode=episode,
        tv_episode_title=ep_title,
        separator=getattr(cfg, "separator", " "),
    )
    series_folder_name = format_tv_series_folder(cfg.naming_tv_template, _naming_ctx)
    season_folder_name = f"Saison {season:02d}" if season else "Saison 00"

    # REGLE INVIOLABLE n1 : un episode est RANGE, jamais RENOMME.
    #
    # L'ancien code batissait `S01E01 - Titre.ext` : un apply reel transformait
    # `Breaking.Bad.S01E01.1080p.BluRay.x264-GROUP.mkv` en `S01E01.mkv`, ce qui
    # desynchronise le fichier de son torrent (seeding casse) ET detruit
    # l'information de release (source, encodeur, resolution). Le template TV ne
    # s'applique donc qu'au DOSSIER (`Serie (annee)/Saison NN/`) ; le nom du
    # fichier est celui de la source, octet pour octet.
    target_filename = video.name

    target_dir = cfg.root / series_folder_name / season_folder_name
    target_file = target_dir / target_filename
    core_mod.ensure_inside_root(cfg, target_file)

    # NOOP : l'episode est DEJA a sa place. Cette garde n'existait pas tant que
    # la cible etait un nom fabrique (`SxxExx - Titre.ext`), qui ne pouvait
    # pratiquement jamais coincider avec la source. La cible etant maintenant
    # `target_dir / video.name`, un 2e apply sur une bibliotheque deja rangee
    # donne `src == dst` — et sans cette garde
    # `move_file_with_collision_policy` verrait `dst.exists()` puis
    # `files_identical_quick(src, src) == True` et deplacerait chaque episode
    # vers `_review/_duplicates_identical`. Comparaison FS-equivalente
    # (casse/NFC Windows), pas une egalite de chaines.
    if core_mod._norm_win_path(target_file) == core_mod._norm_win_path(video):
        log("INFO", f"TV NOOP: episode deja range, rien a faire: {video}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        return

    # Les sidecars gardent EUX AUSSI leur nom source. L'ancien realignement sur
    # le stem cible (`SxxExx - Titre`) n'existait que parce que la video etait
    # renommee : le stem video ne bougeant plus, il n'y a plus rien a realigner
    # et un sidecar reste apparie a sa video par construction.
    sidecar_targets: list[Tuple[Path, Path]] = []
    try:
        for sc in core_mod.classify_sidecars(cfg, folder, video, is_collection=True):
            if not sc.exists():
                continue
            sidecar_targets.append((sc, target_dir / sc.name))
    except (PermissionError, OSError) as exc:
        log("WARN", f"TV sidecar scan failed for {folder}: {exc}")

    # GATE 3 (TV-MAXPATH) : kill-switch MAX_PATH sur la vidéo ET chaque sidecar réaligné
    # (le sidecar le plus long peut dépasser 260 même si target_file passe).
    _candidate_paths = [str(target_file)] + [str(d) for (_, d) in sidecar_targets]
    _path_err: Optional[str] = None
    for _cp in _candidate_paths:
        _path_err = check_path_length_killswitch(_cp)
        if _path_err is not None:
            break
    if _path_err is not None:
        log("WARN", _path_err)
        try:  # noqa: SIM105 - contextlib.suppress ferait perdre la justification du catch
            res.error_messages.append(_path_err)
        except AttributeError:  # noqa: BLE001 - retro-compat tests anciens
            pass
        core_mod._mark_skip(res, core_mod.SKIP_REASON_PATH_TOO_LONG)
        return

    # GATE 4 (TV3/SIDECOLL) : plus de skip NOOP naïf sur target_file.exists() — la
    # comparaison de contenu + la politique de collision/quarantaine sont déléguées à
    # move_file_with_collision_policy (un 2e épisode différent visant la même cible
    # n'est plus laissé silencieusement en source).
    log("INFO", f"TV MOVE: {video} -> {target_file}")

    # GATE 8 (parité COLL-ATOMIC post-F1) : atomicité intra-row. On suit les moves
    # réellement effectués et on les ANNULE si une étape échoue, puis on re-lève pour
    # que la boucle per-row enregistre l'erreur (FICHIER VERROUILLE) et poursuive.
    moved_for_rollback: list[Tuple[Path, Path]] = []

    def _rollback_partial_tv() -> None:
        for dst_done, src_orig in reversed(moved_for_rollback):
            try:
                if dst_done.exists() and not src_orig.exists():
                    atomic_move(record_op, src=dst_done, dst=src_orig, op_type="ROLLBACK_TV_MOVE")
                    record_apply_op(
                        record_op,
                        op_type="ROLLBACK_TV_MOVE",
                        src_path=dst_done,
                        dst_path=src_orig,
                        reversible=False,
                    )
                    res.moves = max(0, res.moves - 1)
                    log("WARN", f"ROLLBACK TV (atomicite intra-row): {dst_done} -> {src_orig}")
            except (OSError, PermissionError) as rb_exc:
                log("ERROR", f"ROLLBACK TV ECHEC {dst_done} -> {src_orig}: {rb_exc}")

    def _move_status(src_path: Path, dst_path: Path) -> str:
        # GATES 2/4/5/6 portées d'un coup : sha1/size sur l'op, politique de collision +
        # comparaison contenu, op journalisée même en dry_run, mkdir compté.
        return move_file_with_collision_policy(
            cfg,
            src_path,
            dst_path,
            src_anchor=folder,
            dry_run=dry_run,
            log=log,
            res=res,
            conflicts_root=conflicts_root,
            conflicts_sidecars_root=conflicts_sidecars_root,
            duplicates_identical_root=duplicates_identical_root,
            hash_cache=hash_cache,
            record_op=record_op,
        )

    try:
        # Vidéo (asset principal) d'abord.
        status = _move_status(video, target_file)
        if status == "moved" and not dry_run:
            moved_for_rollback.append((target_file, video))
        elif status == "duplicate_identical":
            core_mod._mark_skip(res, core_mod.SKIP_REASON_NOOP_DEJA_CONFORME)
        elif status in {"conflict", "sidecar_conflict"}:
            core_mod._mark_skip(res, core_mod.SKIP_REASON_CONFLIT_QUARANTAINE)

        # Sidecars réalignés (GATE 1) — collision/échec gérés par la politique
        # (GATE 4 + H3-02 : plus de `except: pass` qui avalait les échecs).
        for sc, dst_sc in sidecar_targets:
            s_status = _move_status(sc, dst_sc)
            if s_status == "moved" and not dry_run:
                moved_for_rollback.append((dst_sc, sc))
            elif s_status in {"conflict", "sidecar_conflict", "duplicate_identical"}:
                core_mod._mark_skip(res, core_mod.SKIP_REASON_CONFLIT_QUARANTAINE)
    except (OSError, PermissionError) as exc:
        log("ERROR", f"apply_tv_episode: echec move, rollback intra-row ({folder.name}): {exc}")
        _rollback_partial_tv()
        raise

    # GATE 5/TV-DRYRUN counter : res.moves est désormais incrémenté par
    # move_file_with_collision_policy par move réel (vidéo + chaque sidecar), y compris
    # en dry_run pour la preview — on retire l'ancien `res.moves += 1` inconditionnel
    # qui comptait l'épisode même quand rien n'était déplacé.


def quarantine_row(
    cfg: "Config",
    folder: Path,
    row: "PlanRow",
    dry_run: bool,
    log: Callable[[str, str], None],
    res: "ApplyResult",
    review_root: Path,
    record_op: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> None:
    """Place le contenu d'une ligne non approuvée en quarantaine sous `_review/`.

    Pour un single, déplace tout le dossier ; pour un item de collection,
    déplace la vidéo + ses sidecars dans un sous-dossier dédié. No-op si la
    cible existe déjà ou si la source a disparu.
    """
    if not folder.exists():
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return

    if row.kind == "single":
        target = review_root / core_mod.windows_safe(Path(row.folder).name)
        core_mod.ensure_inside_root(cfg, target)
        if target.exists():
            core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
            return
        log("INFO", f"QUARANTINE folder: {folder} -> {target}")
        if not dry_run:
            atomic_move(record_op, src=folder, dst=target, op_type="QUARANTINE_DIR")
            record_apply_op(
                record_op,
                op_type="QUARANTINE_DIR",
                src_path=folder,
                dst_path=target,
                reversible=True,
            )
        res.quarantined += 1
        return

    video = folder / row.video
    if not video.exists():
        # Symetrique de apply_tv_episode (meme module) : protege contre folder disparu
        # (move concurrent, TOCTOU depuis le `folder.exists()` du debut) ou permission
        # denied -> sinon le plantage tue l'apply en plein batch de quarantaine et perd
        # toutes les rows non traitees.
        # NB : la comparaison reste `_name_eq_fs` (casefold + NFC, cf. main) et non
        # `.lower()` : sur un scan SMB macOS les noms remontent en NFD.
        try:
            matches = [path for path in folder.iterdir() if path.is_file() and _name_eq_fs(path.name, row.video)]
        except (OSError, PermissionError) as exc:
            # Revue PR#561 (sourcery-ai) : ne pas rendre l'echec FS
            # indiscernable d'un « aucune video trouvee ». La suite skippe la
            # row SANS aucun log (contrairement a apply_tv_episode) : sans
            # cette trace, un share tombe en plein batch de quarantaine se lit
            # comme une bibliotheque vide.
            log("WARN", f"QUARANTINE listing failed: {folder} ({type(exc).__name__}: {exc})")
            matches = []
        video = matches[0] if matches else video
    if not video.exists():
        log("WARN", f"QUARANTINE video missing: {video}")
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)
        return

    base = review_root / core_mod.windows_safe(Path(row.folder).name) / core_mod.windows_safe(video.stem)
    core_mod.ensure_inside_root(cfg, base)
    if not base.exists():
        mkdir_counted(base, dry_run=dry_run, log=log, res=res, record_op_fn=record_op)

    for sidecar in core_mod.classify_sidecars(cfg, folder, video, is_collection=True):
        dst = base / sidecar.name
        if dst.exists():
            continue
        log("INFO", f"QUARANTINE MOVE: {sidecar} -> {dst}")
        if not dry_run:
            atomic_move(record_op, src=sidecar, dst=dst, op_type="QUARANTINE_FILE")
            record_apply_op(
                record_op,
                op_type="QUARANTINE_FILE",
                src_path=sidecar,
                dst_path=dst,
                reversible=True,
            )
        res.quarantined += 1

    # Regle inviolable n1 : nom de fichier video preserve a l'identique.
    dst_video = base / video.name
    if not dst_video.exists():
        log("INFO", f"QUARANTINE MOVE: {video} -> {dst_video}")
        if not dry_run:
            atomic_move(record_op, src=video, dst=dst_video, op_type="QUARANTINE_FILE")
            record_apply_op(
                record_op,
                op_type="QUARANTINE_FILE",
                src_path=video,
                dst_path=dst_video,
                reversible=True,
            )
        res.quarantined += 1
    else:
        core_mod._mark_skip(res, core_mod.SKIP_REASON_AUTRE)

"""VQ-2 QUARANTAINE-TTL — TTL filesystem du bucket `_review` + viewer + purge.

Audit ROADMAP_VAGUE_N item VQ-2 : le bucket `_review` (root/_review/...) recoit
en continu :
- les rows non-approuvees (`quarantine_unapproved=True`) au top-level
- les conflits (sous-dossier `_conflicts`)
- les sidecars conflits (sous-dossier `_conflicts_sidecars`)
- les doublons identiques (`_duplicates_identical`)
- les doublons decides UI (`_duplicates_user_decided`)
- les leftovers (`_leftovers`)

Avant ce module : aucun TTL FS (seul l'historique runs DB en avait un via
`retention_cleanup`). Le bucket gonflait indefiniment. Aucune UI pour
visualiser ou vider.

Ce module fournit :
- `REVIEW_FOLDER_NAME` : constante centrale (litteral `_review` repete dans
  apply_core.py x6, cleanup.py x2, reset_support.py x1).
- `list_review_bucket_files(cfg)` : inventaire du contenu (pour viewer UI).
- `purge_review_bucket(cfg, ttl_days, *, dry_run)` : suppression des fichiers
  > TTL. ttl_days=0 desactive le TTL (no-op).
- `purge_review_bucket_all(cfg)` : vider integralement le bucket (action UI
  "Vider maintenant", protege par dangerConfirmModal cote UI).
- `start_quarantine_ttl_cron(api, ...)` : daemon thread identique a
  `retention_cleanup.start_retention_cron` (re-utilise pattern, voir spec 09).

Architecture (verrouillee import-linter) :
- Module dans `cinesort.app` (orchestration), pas dans `domain`.
- Pas d'import `ui` (couplage uniquement via instance `api` runtime).
- Pas de modification du contrat de Config existant : on lit `ttl_days` depuis
  les settings via le helper, sans nouveau champ frozen sur Config.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional

_log = logging.getLogger(__name__)

if TYPE_CHECKING:
    from cinesort.domain.core import Config

# Constante centrale, utilisable par cleanup.py / apply_core.py / reset_support.py
# pour eliminer les litteraux `_review` epars (audit VQ-2 point (d)).
REVIEW_FOLDER_NAME = "_review"

# Sous-dossiers du bucket _review qui contiennent du contenu purgeable par TTL.
# Volontairement EXCLU : `_duplicates_user_decided` (decisions UI explicites,
# l'utilisateur les a deplaces lui-meme — on ne purge pas ses choix).
TTL_SUBDIRS = (
    "_conflicts",
    "_conflicts_sidecars",
    "_duplicates_identical",
    "_leftovers",
)

# Defaut TTL (jours). Aligne avec UI : settings.quarantaine_ttl_days = 30.
DEFAULT_TTL_DAYS = 30

# AUDIT 2026-06-10 (CRITICAL, REAL 2/2) : le TTL se basait sur st_mtime, or
# apply deplace les fichiers via atomic_move/shutil.move qui PRESERVE le mtime
# d'origine. Un film encode/telecharge il y a des mois etait donc purge des le
# 1er cycle apres sa mise en quarantaine (perte de donnees). On date desormais
# l'ENTREE en quarantaine via un manifest "premiere observation" : tant qu'un
# fichier n'a pas ete vu par list/purge, son TTL ne court pas ; a la 1re
# observation on enregistre `now`, et le TTL court a partir de la. A la
# migration, tous les fichiers presents repartent a `now` (jamais purges
# retroactivement).
_TTL_MANIFEST_NAME = ".cinesort_ttl_manifest.json"

# Cron : 24h en secondes (idem retention_cleanup), externalise pour tests.
_INTERVAL_S = 24.0 * 3600.0
_INITIAL_DELAY_S = 60.0


def review_root(cfg: "Config") -> Path:
    """Chemin canonique du bucket `_review` pour une cfg donnee."""
    return Path(cfg.root) / REVIEW_FOLDER_NAME


def _ttl_manifest_path(root: Path) -> Path:
    """Chemin du manifest d'arrivee (premiere observation) du bucket."""
    return root / _TTL_MANIFEST_NAME


def _load_ttl_manifest(root: Path) -> Dict[str, float]:
    """Charge le manifest {rel_posix: first_seen_ts}. Tolerant : {} si absent/corrompu."""
    path = _ttl_manifest_path(root)
    try:
        if not path.is_file():
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        _log.warning("ttl manifest: lecture %s echec : %s", path, exc)
        return {}
    if not isinstance(data, dict):
        return {}
    out: Dict[str, float] = {}
    for rel, ts in data.items():
        try:
            out[str(rel)] = float(ts)
        except (TypeError, ValueError):
            continue
    return out


def _save_ttl_manifest(root: Path, manifest: Dict[str, float]) -> None:
    """Ecrit le manifest (best-effort, ne leve jamais)."""
    path = _ttl_manifest_path(root)
    tmp = path.with_name(f"{path.name}.tmp.{os.getpid()}.{threading.get_ident()}")
    try:
        # R8-029 (F2-d) : ecriture ATOMIQUE (tmp sibling + os.replace) au lieu d'un
        # write_text direct. Avant, un crash ou un write concurrent (viewer + cron daemon,
        # last-writer-wins) en plein write TRONQUAIT/corrompait ttl_manifest.json -> la
        # comptabilite TTL devenait fausse. os.replace dans le meme dossier est atomique.
        tmp.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
    except (OSError, TypeError, ValueError) as exc:
        _log.warning("ttl manifest: ecriture %s echec : %s", path, exc)
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def _sync_arrival_manifest(root: Path, *, persist: bool, now: Optional[float] = None) -> Dict[str, float]:
    """Synchronise le manifest avec le contenu reel du bucket.

    - Tout fichier present mais absent du manifest recoit `first_seen = now`
      (1re observation -> son TTL commence ici, pas a son mtime).
    - Les entrees pointant vers des fichiers disparus sont retirees.
    - `persist=False` (dry_run / lecture) : calcule en memoire sans ecrire.

    Retourne le mapping {rel_posix: first_seen_ts} a jour.
    """
    ts_now = time.time() if now is None else now
    manifest = _load_ttl_manifest(root)
    present: Dict[str, float] = {}
    for fp in _iter_review_files(root):
        try:
            rel = fp.relative_to(root).as_posix()
        except ValueError:
            continue
        present[rel] = manifest.get(rel, ts_now)
    changed = present.keys() != manifest.keys()
    if persist and changed:
        _save_ttl_manifest(root, present)
    return present


def _iter_review_files(root: Path) -> List[Path]:
    """Liste tous les fichiers (recursifs) sous `root`. Tolerant aux erreurs FS.

    Exclut le manifest TTL interne (ce n'est pas du contenu quarantaine).
    """
    out: List[Path] = []
    if not root.exists() or not root.is_dir():
        return out
    try:
        for item in root.rglob("*"):
            try:
                if item.is_file() and item.name != _TTL_MANIFEST_NAME:
                    out.append(item)
            except (OSError, PermissionError):
                continue
    except (OSError, PermissionError) as exc:
        _log.warning("iter review files: %s erreur %s", root, exc)
    return out


def list_review_bucket_files(cfg: "Config", *, limit: int = 500) -> Dict[str, Any]:
    """Inventaire du bucket `_review` pour le viewer UI (route /quarantine_viewer).

    Retourne :
        {
            "ok": True,
            "review_root": str(path),
            "exists": bool,
            "files_count": int,           # total
            "total_size_bytes": int,      # somme
            "files": [                    # tronque a `limit` entrees
                {"path": str, "rel": str, "size": int, "mtime": float,
                 "age_days": float, "subdir": str}
            ],
            "by_subdir": {                # compteurs par sous-dossier connu
                "_top_quarantine": {"count": int, "size": int},
                "_conflicts": ...,
                ...
            }
        }
    Sortie tronquee a `limit` entrees triees par mtime DESC (plus recents en haut).
    """
    root = review_root(cfg)
    payload: Dict[str, Any] = {
        "ok": True,
        "review_root": str(root),
        "exists": bool(root.exists() and root.is_dir()),
        "files_count": 0,
        "total_size_bytes": 0,
        "files": [],
        "by_subdir": {},
    }
    if not payload["exists"]:
        return payload

    now = time.time()
    files = _iter_review_files(root)
    payload["files_count"] = len(files)

    # Ancre la date d'entree en quarantaine de chaque fichier (1re observation).
    # Le viewer est un point d'entree naturel : on persiste pour que le TTL
    # parte de l'ouverture de l'ecran et pas du 1er cron.
    arrivals = _sync_arrival_manifest(root, persist=True, now=now)

    by_subdir: Dict[str, Dict[str, int]] = {}
    entries: List[Dict[str, Any]] = []
    total_size = 0
    for fp in files:
        try:
            st = fp.stat()
        except (OSError, PermissionError):
            continue
        size = int(st.st_size)
        mtime = float(st.st_mtime)
        total_size += size
        try:
            rel = fp.relative_to(root).as_posix()
        except ValueError:
            rel = fp.name
        # age_days = temps passe EN QUARANTAINE (depuis l'arrivee), pas l'age
        # du fichier (mtime, preserve par move) — voir AUDIT 2026-06-10.
        arrival = arrivals.get(rel, mtime)
        # Le premier composant identifie le sous-dossier (ou "_top_quarantine"
        # si le fichier est directement sous _review/).
        parts = rel.split("/", 1)
        subdir = parts[0] if len(parts) > 1 else "_top_quarantine"
        bucket = by_subdir.setdefault(subdir, {"count": 0, "size": 0})
        bucket["count"] += 1
        bucket["size"] += size
        entries.append(
            {
                "path": str(fp),
                "rel": rel,
                "size": size,
                "mtime": mtime,
                "arrival_ts": arrival,
                "age_days": max(0.0, (now - arrival) / 86400.0),
                "subdir": subdir,
            }
        )
    payload["total_size_bytes"] = total_size
    payload["by_subdir"] = by_subdir

    # Tri par arrivee DESC (entre le plus recemment en quarantaine en haut),
    # tronque a `limit`.
    entries.sort(key=lambda d: d["arrival_ts"], reverse=True)
    payload["files"] = entries[: max(0, int(limit))]
    return payload


def _purge_target_roots(cfg: "Config") -> List[Path]:
    """Liste des roots concernes par le TTL : `_review/<sub>` pour chaque TTL_SUBDIRS."""
    root = review_root(cfg)
    return [root / sub for sub in TTL_SUBDIRS]


def _purge_dir_recursive(
    target: Path,
    *,
    cutoff_ts: float,
    dry_run: bool,
    arrival_of: Optional[Callable[[Path], float]] = None,
) -> Dict[str, int]:
    """Supprime recursivement les fichiers entres avant cutoff_ts sous `target`.

    `arrival_of(item)` donne la date d'entree en quarantaine du fichier (manifest
    de 1re observation). Si None, fallback sur st_mtime (utilise par purge_all,
    dont le cutoff futur supprime tout de toute facon).

    Retourne {"deleted": N, "bytes_freed": N, "errors": N, "considered": N}.
    Les dossiers vides post-purge sont supprimes (sauf `target` lui-meme).
    """
    stats = {"deleted": 0, "bytes_freed": 0, "errors": 0, "considered": 0}
    if not target.exists() or not target.is_dir():
        return stats

    # 1) Suppression des fichiers
    for item in target.rglob("*"):
        try:
            if not item.is_file():
                continue
            stats["considered"] += 1
            st = item.stat()
            entered_ts = arrival_of(item) if arrival_of is not None else st.st_mtime
            if entered_ts > cutoff_ts:
                continue
            size = int(st.st_size)
            if dry_run:
                stats["deleted"] += 1
                stats["bytes_freed"] += size
                continue
            try:
                item.unlink()
                stats["deleted"] += 1
                stats["bytes_freed"] += size
            except (OSError, PermissionError) as exc:
                stats["errors"] += 1
                _log.warning("purge: unlink %s echec : %s", item, exc)
        except (OSError, PermissionError) as exc:
            stats["errors"] += 1
            _log.warning("purge: stat/iter %s echec : %s", item, exc)

    # 2) Suppression des dossiers vides (post-purge), bottom-up. Ne supprime
    #    PAS `target` lui-meme (on garde la structure pour les futurs apply).
    if not dry_run:
        try:
            all_dirs = sorted(
                (p for p in target.rglob("*") if p.is_dir()),
                key=lambda p: len(p.parts),
                reverse=True,
            )
            for d in all_dirs:
                with contextlib.suppress(OSError):
                    d.rmdir()  # echoue silencieusement si non vide
        except (OSError, PermissionError) as exc:
            _log.warning("purge: cleanup dirs %s echec : %s", target, exc)

    return stats


def purge_review_bucket(
    cfg: "Config",
    ttl_days: int = DEFAULT_TTL_DAYS,
    *,
    dry_run: bool = False,
) -> Dict[str, Any]:
    """Purge les fichiers du bucket `_review` plus vieux que `ttl_days` jours.

    `ttl_days <= 0` : no-op (retourne ok=True, deleted=0). Permet de
    desactiver le TTL via settings sans casser l'appelant.

    Cible : `_review/_conflicts`, `_review/_conflicts_sidecars`,
    `_review/_duplicates_identical`, `_review/_leftovers`. Le top-level
    `_review/<row>/...` (rows non-approuvees apres apply) est aussi purge —
    on parcourt TOUT le bucket sauf `_duplicates_user_decided` (decisions
    UI explicites).
    """
    try:
        days = int(ttl_days)
    except (TypeError, ValueError):
        days = DEFAULT_TTL_DAYS

    payload: Dict[str, Any] = {
        "ok": True,
        "ttl_days": days,
        "dry_run": bool(dry_run),
        "deleted": 0,
        "bytes_freed": 0,
        "errors": 0,
        "considered": 0,
        "by_subdir": {},
    }
    if days <= 0:
        payload["disabled"] = True
        return payload

    root = review_root(cfg)
    if not root.exists() or not root.is_dir():
        payload["no_bucket"] = True
        return payload

    now = time.time()
    cutoff_ts = now - (days * 86400.0)

    # Date d'entree en quarantaine de chaque fichier (manifest 1re observation).
    # En dry_run on ne persiste pas, mais le calcul est identique au reel.
    arrivals = _sync_arrival_manifest(root, persist=not dry_run, now=now)

    def _arrival_of(item: Path) -> float:
        try:
            rel = item.relative_to(root).as_posix()
        except ValueError:
            return now
        return arrivals.get(rel, now)

    # 1) Sous-dossiers cible (TTL_SUBDIRS)
    for sub in TTL_SUBDIRS:
        target = root / sub
        sub_stats = _purge_dir_recursive(
            target, cutoff_ts=cutoff_ts, dry_run=dry_run, arrival_of=_arrival_of
        )
        payload["by_subdir"][sub] = sub_stats
        payload["deleted"] += sub_stats["deleted"]
        payload["bytes_freed"] += sub_stats["bytes_freed"]
        payload["errors"] += sub_stats["errors"]
        payload["considered"] += sub_stats["considered"]

    # 2) Top-level quarantine rows : `_review/<folder>/...` mais en EXCLUANT
    #    les sous-dossiers connus (_conflicts/_leftovers/...) deja traites,
    #    et `_duplicates_user_decided` (decisions UI a preserver).
    excluded = set(TTL_SUBDIRS) | {"_duplicates_user_decided"}
    top_stats = {"deleted": 0, "bytes_freed": 0, "errors": 0, "considered": 0}
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name not in excluded:
                sub_stats = _purge_dir_recursive(
                    child, cutoff_ts=cutoff_ts, dry_run=dry_run, arrival_of=_arrival_of
                )
                top_stats["deleted"] += sub_stats["deleted"]
                top_stats["bytes_freed"] += sub_stats["bytes_freed"]
                top_stats["errors"] += sub_stats["errors"]
                top_stats["considered"] += sub_stats["considered"]
                # Supprimer le dossier top-level lui meme s'il est vide post-purge
                if not dry_run:
                    with contextlib.suppress(OSError):
                        child.rmdir()
            elif child.is_file() and child.name != _TTL_MANIFEST_NAME:
                # Fichiers libres au top-level (rare mais possible)
                try:
                    top_stats["considered"] += 1
                    if _arrival_of(child) <= cutoff_ts:
                        size = int(child.stat().st_size)
                        if dry_run:
                            top_stats["deleted"] += 1
                            top_stats["bytes_freed"] += size
                        else:
                            try:
                                child.unlink()
                                top_stats["deleted"] += 1
                                top_stats["bytes_freed"] += size
                            except (OSError, PermissionError):
                                top_stats["errors"] += 1
                except (OSError, PermissionError):
                    top_stats["errors"] += 1
    except (OSError, PermissionError) as exc:
        _log.warning("purge: iter top-level _review %s echec : %s", root, exc)

    payload["by_subdir"]["_top_quarantine"] = top_stats
    payload["deleted"] += top_stats["deleted"]
    payload["bytes_freed"] += top_stats["bytes_freed"]
    payload["errors"] += top_stats["errors"]
    payload["considered"] += top_stats["considered"]

    # Nettoie le manifest des fichiers supprimes : sans cela, une row reutilisant
    # plus tard le meme chemin relatif heriterait de l'ancienne date d'arrivee et
    # serait purgee immediatement (re-introduction du bug). No-op en dry_run.
    if not dry_run:
        _sync_arrival_manifest(root, persist=True, now=now)

    _log.info(
        "purge_review_bucket: deleted=%d bytes_freed=%d ttl=%dj dry_run=%s",
        payload["deleted"],
        payload["bytes_freed"],
        days,
        dry_run,
    )
    return payload


def purge_review_bucket_all(cfg: "Config", *, dry_run: bool = False) -> Dict[str, Any]:
    """Vide INTEGRALEMENT le bucket `_review` (sauf `_duplicates_user_decided`).

    Appelle par l'UI "Vider le bucket maintenant" (action protegee par
    dangerConfirmModal cote front : countdown 3s si >50 fichiers).

    Note : on preserve `_duplicates_user_decided` (decisions UI explicites
    Phase 6 doublons). Tout le reste passe au broyeur.
    """
    # Equivalent a purge avec ttl_days=0... mais on veut tout supprimer, pas
    # rien supprimer. On force cutoff_ts = futur (now + 1 jour) pour matcher
    # TOUS les fichiers.
    payload: Dict[str, Any] = {
        "ok": True,
        "ttl_days": 0,
        "dry_run": bool(dry_run),
        "deleted": 0,
        "bytes_freed": 0,
        "errors": 0,
        "considered": 0,
        "by_subdir": {},
        "purge_mode": "all",
    }
    root = review_root(cfg)
    if not root.exists() or not root.is_dir():
        payload["no_bucket"] = True
        return payload

    cutoff_ts = time.time() + 86400.0  # tout est plus vieux que demain

    for sub in TTL_SUBDIRS:
        target = root / sub
        sub_stats = _purge_dir_recursive(target, cutoff_ts=cutoff_ts, dry_run=dry_run)
        payload["by_subdir"][sub] = sub_stats
        payload["deleted"] += sub_stats["deleted"]
        payload["bytes_freed"] += sub_stats["bytes_freed"]
        payload["errors"] += sub_stats["errors"]
        payload["considered"] += sub_stats["considered"]

    excluded = set(TTL_SUBDIRS) | {"_duplicates_user_decided"}
    top_stats = {"deleted": 0, "bytes_freed": 0, "errors": 0, "considered": 0}
    try:
        for child in root.iterdir():
            if child.is_dir() and child.name not in excluded:
                sub_stats = _purge_dir_recursive(child, cutoff_ts=cutoff_ts, dry_run=dry_run)
                top_stats["deleted"] += sub_stats["deleted"]
                top_stats["bytes_freed"] += sub_stats["bytes_freed"]
                top_stats["errors"] += sub_stats["errors"]
                top_stats["considered"] += sub_stats["considered"]
                if not dry_run:
                    with contextlib.suppress(OSError):
                        child.rmdir()
            elif child.is_file():
                try:
                    top_stats["considered"] += 1
                    size = int(child.stat().st_size)
                    if dry_run:
                        top_stats["deleted"] += 1
                        top_stats["bytes_freed"] += size
                    else:
                        try:
                            child.unlink()
                            top_stats["deleted"] += 1
                            top_stats["bytes_freed"] += size
                        except (OSError, PermissionError):
                            top_stats["errors"] += 1
                except (OSError, PermissionError):
                    top_stats["errors"] += 1
    except (OSError, PermissionError) as exc:
        _log.warning("purge_all: iter top-level _review echec : %s", exc)

    payload["by_subdir"]["_top_quarantine"] = top_stats
    payload["deleted"] += top_stats["deleted"]
    payload["bytes_freed"] += top_stats["bytes_freed"]
    payload["errors"] += top_stats["errors"]
    payload["considered"] += top_stats["considered"]

    # Resynchronise le manifest sur ce qui reste (les fichiers purges sont retires).
    if not dry_run:
        _sync_arrival_manifest(root, persist=True)

    _log.info(
        "purge_review_bucket_all: deleted=%d bytes_freed=%d dry_run=%s",
        payload["deleted"],
        payload["bytes_freed"],
        dry_run,
    )
    return payload


def _run_purge_once(api: Any, ttl_days: int) -> None:
    """Execute un cycle de purge en isolant les erreurs (utilise par le cron)."""
    try:
        # On passe par l'api facade pour respecter l'inversion d'imports :
        # le cron tourne en thread daemon, il n'importe pas la cfg directement
        # — c'est `api` qui sait construire le cfg courant via les settings.
        result = api.run.purge_quarantine_bucket(ttl_days)
    # R8-024 (F2-d) : +sqlite3.Error -> un verrou DB transitoire ne tue plus le thread
    # cron de purge TTL (qui restait mort definitivement = croissance non bornee).
    except (AttributeError, OSError, RuntimeError, TypeError, ValueError, sqlite3.Error) as exc:
        _log.warning("purge_quarantine cron: appel echoue ttl=%dj err=%s", ttl_days, exc)
        return
    if not isinstance(result, dict) or not result.get("ok"):
        _log.warning(
            "purge_quarantine cron: reponse inattendue ttl=%dj resp=%s",
            ttl_days,
            result,
        )
        return
    deleted = int(result.get("deleted") or 0)
    _log.info(
        "purge_quarantine: deleted %d files older than %d days",
        deleted,
        ttl_days,
    )


def start_quarantine_ttl_cron(
    api: Any,
    *,
    ttl_days: int = DEFAULT_TTL_DAYS,
    initial_delay_s: float = _INITIAL_DELAY_S,
    interval_s: float = _INTERVAL_S,
) -> Optional[threading.Thread]:
    """Demarre le cron quarantine TTL (thread daemon).

    Strictement parallele a `retention_cleanup.start_retention_cron` mais cible
    le filesystem `_review` au lieu de l'historique runs DB.

    Args:
        api: Instance CineSortApi (expose `api.run.purge_quarantine_bucket`).
        ttl_days: TTL en jours. <= 0 desactive le cron.
        initial_delay_s: Attente avant le premier cycle (defaut 60s).
        interval_s: Periode entre 2 cycles (defaut 24h).

    Returns:
        Le `threading.Thread` demarre, ou None si TTL desactive.
    """
    try:
        days = int(ttl_days)
    except (TypeError, ValueError):
        days = DEFAULT_TTL_DAYS
    if days <= 0:
        _log.info("quarantine ttl cron desactive (ttl_days=%d <= 0)", days)
        return None

    stop_event = getattr(api, "_quarantine_ttl_stop", None)
    if not isinstance(stop_event, threading.Event):
        stop_event = threading.Event()
        with contextlib.suppress(AttributeError):
            api._quarantine_ttl_stop = stop_event

    def _worker() -> None:
        if stop_event.wait(initial_delay_s):
            return
        _run_purge_once(api, days)
        while not stop_event.is_set():
            if stop_event.wait(interval_s):
                return
            _run_purge_once(api, days)

    thread = threading.Thread(
        target=_worker,
        name="cinesort-quarantine-ttl",
        daemon=True,
    )
    thread.start()
    _log.info(
        "quarantine ttl cron demarre (ttl=%dj, initial_delay=%ds, interval=%ds)",
        days,
        int(initial_delay_s),
        int(interval_s),
    )
    return thread


def trigger_now(api: Any, ttl_days: int = DEFAULT_TTL_DAYS) -> None:
    """Helper synchrone pour tests : execute un cycle immediat sans thread."""
    _run_purge_once(api, int(ttl_days))


__all__ = [
    "REVIEW_FOLDER_NAME",
    "TTL_SUBDIRS",
    "DEFAULT_TTL_DAYS",
    "review_root",
    "list_review_bucket_files",
    "purge_review_bucket",
    "purge_review_bucket_all",
    "start_quarantine_ttl_cron",
    "trigger_now",
]

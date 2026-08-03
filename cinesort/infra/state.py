from __future__ import annotations

import contextlib
import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

APP_NAME = "CineSort"
_DEBUG_ENV_VALUES = {"1", "true", "yes", "on", "debug"}


def _debug_enabled() -> bool:
    return str(os.environ.get("CINESORT_DEBUG", "")).strip().lower() in _DEBUG_ENV_VALUES


def _debug_log_state(state_dir: Path, message: str) -> None:
    if not _debug_enabled():
        return
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    try:
        p = state_dir / "debug_state.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {message}\n")
    except OSError:
        # Best-effort debug logging : mkdir / open / write peuvent lever OSError
        # (PermissionError, FileNotFoundError, etc., qui en derivent). Les
        # ImportError / KeyError / TypeError / ValueError historiques ici
        # n'avaient pas de cause plausible et masquaient des bugs reels.
        return


def default_state_dir() -> Path:
    """
    Local PC (evite ecritures reseau).
    """
    base = os.environ.get("LOCALAPPDATA", ".")
    return Path(base) / APP_NAME


@dataclass(frozen=True)
class RunPaths:
    run_id: str
    run_dir: Path
    plan_jsonl: Path
    ui_log_txt: Path
    summary_txt: Path
    validation_json: Path


def new_run(state_dir: Path, run_id: str) -> RunPaths:
    runs = state_dir / "runs"
    run_dir = runs / f"tri_films_{run_id}"
    run_dir.mkdir(parents=True, exist_ok=True)

    return RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def read_text_safe(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except (OSError, PermissionError):
        return ""


def write_text_safe(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


# ---------------------------------------------------------------------------
# Ecriture atomique ET durable — helper UNIQUE du depot
# ---------------------------------------------------------------------------
# Issues #511/#820 (state), #622/#732 (tmdb), #692 (probe disk_cache), #712
# (poster_proxy), #787 (updater), #822 (export nfo).
#
# Le depot possedait les DEUX bonnes moities de l'invariant, mais jamais au
# meme endroit : `omdb_client._save_cache_atomic` faisait flush+fsync+controle
# de taille avec un nom de `.tmp` FIXE ; `state.atomic_write_json` et
# `probe/disk_cache.upsert_disk_cache` faisaient le nom de `.tmp` UNIQUE sans
# aucun fsync. Chaque nouveau site recopiait une moitie au hasard. Ce module
# porte desormais le couple canonique ; tout nouvel ecrivain doit passer par
# `atomic_write_bytes` / `atomic_write_text` / `atomic_write_json` plutot que
# de reimplementer une troisieme variante.

# Infixe commun a TOUS les fichiers temporaires d'ecriture atomique. Permet aux
# purges de cache de reconnaitre (et donc de nettoyer) un orphelin de crash :
# avec un nom unique, un `.tmp` abandonne n'est plus jamais reutilise ni ecrase,
# il faut donc pouvoir l'identifier.
ATOMIC_TMP_INFIX = ".tmp."

# Politique de retentative d'`os.replace`, MESUREE par PR#718 sur 32 threads
# concurrents (`poster_proxy` sous ThreadingHTTPServer) : 19/32 echecs sans
# retentative, 0/32 avec ce backoff, pire cas 6 tentatives. Budget total
# ~0,41 s, soit MOINS que les 0,75 s de l'ancienne politique (5 x 50 ms
# lineaire) tout en persistant deux fois plus longtemps.
_ATOMIC_REPLACE_MAX_ATTEMPTS = 12
_ATOMIC_REPLACE_BACKOFF_BASE_S = 0.002
_ATOMIC_REPLACE_BACKOFF_CAP_S = 0.05


class AtomicWriteError(OSError):
    """Echec d'une ecriture atomique. Le fichier cible est laisse INCHANGE.

    Herite d'OSError pour rester attrapable par les `except OSError` deja en
    place chez les appelants (caches best-effort).
    """


def atomic_tmp_path(target: Path) -> Path:
    """Chemin de `.tmp` UNIQUE, voisin de `target` (meme repertoire => meme
    device, condition de l'atomicite d'`os.replace`).

    Unicite par (pid, thread, nanoseconde, uuid) : deux ecrivains concurrents ne
    peuvent pas se voler leur fichier intermediaire ni promouvoir le contenu de
    l'autre (CWE-362).
    """
    stamp = f"{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.{uuid.uuid4().hex[:8]}"
    return target.with_name(f"{target.name}{ATOMIC_TMP_INFIX}{stamp}")


def is_atomic_tmp_name(name: str) -> bool:
    """True si `name` est un temporaire produit par `atomic_tmp_path`."""
    return ATOMIC_TMP_INFIX in name


def _replace_with_retry(tmp: Path, target: Path) -> None:
    """Bascule `tmp` -> `target`, en encaissant la contention Windows.

    R8-026 (F2-d) : sur Windows, `os.replace` leve `PermissionError`
    (WinError 5/32) quand un autre acteur tient la cible ouverte — un lecteur
    (poller de l'UI, 2e onglet) ou un autre ECRIVAIN qui bascule au meme
    instant. Sans retentative, l'ecriture est PERDUE : la cible garde son
    ancienne valeur et l'appelant croit avoir ecrit.

    L'atomicite n'est jamais en cause (`os.replace` reste atomique, il n'y a
    pas de contenu melange) : c'est un probleme de DISPONIBILITE de la cible.

    La politique vient de PR#718, qui l'a MESUREE sur le site le plus
    concurrent du depot (`poster_proxy`, sous `ThreadingHTTPServer`) :
    32 threads sur la meme cible donnent **19 echecs sur 32 sans retentative**
    et **0 sur 32** avec ce backoff, pire cas observe 6 tentatives.

    Elle remplace un backoff lineaire de 5 x 50 ms, qui etait moins bon des
    deux cotes : trop lent au cas courant (50 ms d'attente pour une collision
    qui se resout en 2 ms) et trop court au cas charge (5 tentatives < les 6
    du pire cas mesure, donc des pertes d'ecriture sous charge).

    Trois proprietes comptent, et aucune n'est decorative :
    - depart a 2 ms : la quasi-totalite des collisions se resout au 1er retry ;
    - croissance exponentielle plafonnee a 50 ms : on ne bloque jamais un
      handler HTTP indefiniment (budget total ~0,41 s sur 12 tentatives,
      soit MOINS que les 0,75 s de l'ancienne politique sur 5) ;
    - jitter derive de l'identifiant de thread : sans lui, N threads reveilles
      par le meme backoff se retelescopent a chaque tour.
    """
    replace_exc: Optional[PermissionError] = None
    for attempt in range(_ATOMIC_REPLACE_MAX_ATTEMPTS):
        try:
            os.replace(tmp, target)
            return
        except PermissionError as exc:
            replace_exc = exc
            if attempt == _ATOMIC_REPLACE_MAX_ATTEMPTS - 1:
                break
            delay = min(_ATOMIC_REPLACE_BACKOFF_CAP_S, _ATOMIC_REPLACE_BACKOFF_BASE_S * (2**attempt))
            time.sleep(delay + (threading.get_ident() % 8) * 0.0005)
    if replace_exc is not None:
        raise replace_exc


def atomic_write_bytes(p: Path, data: bytes, *, mkdir: bool = True) -> None:
    """Ecrit `data` dans `p` de facon atomique ET durable.

    Les DEUX invariants, ensemble :

    1. **Nom de `.tmp` unique** (pid/thread/ns/uuid) : deux ecrivains
       concurrents — threads d'un `ThreadingHTTPServer`, thread daemon de purge
       au boot, 2e instance — ne partagent plus le meme fichier intermediaire.
    2. **flush + `os.fsync` + verification de la taille ecrite** avant
       `os.replace` : un crash systeme entre l'ecriture et le rename ne peut
       plus promouvoir un fichier vide ou tronque en version officielle.

    En cas d'echec, `p` est laisse INCHANGE et une `OSError` est levee
    (`AtomicWriteError` pour une taille incoherente). Le `.tmp` est nettoye.
    """
    if mkdir:
        p.parent.mkdir(parents=True, exist_ok=True)
    tmp = atomic_tmp_path(p)
    try:
        with open(tmp, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())  # force l'ecriture sur disque AVANT le rename
        written = tmp.stat().st_size
        if written == 0 or written != len(data):
            raise AtomicWriteError(f"ecriture atomique incomplete pour {p.name}: {written}/{len(data)} octets")
        _replace_with_retry(tmp, p)
    finally:
        # Best-effort cleanup : tmp.exists() / tmp.unlink() ne peuvent lever
        # qu'OSError (PermissionError, FileNotFoundError en derivent). Apres un
        # os.replace reussi, le tmp n'existe plus : ce bloc est un no-op.
        with contextlib.suppress(OSError):
            if tmp.exists():
                tmp.unlink()


def atomic_write_text(p: Path, text: str, *, encoding: str = "utf-8", mkdir: bool = True) -> None:
    """Variante texte d'`atomic_write_bytes` (memes invariants)."""
    atomic_write_bytes(p, text.encode(encoding), mkdir=mkdir)


def atomic_write_json(p: Path, obj: Any, *, indent: Optional[int] = 2, mkdir: bool = True) -> None:
    """Variante JSON d'`atomic_write_bytes` (memes invariants).

    `indent=None` produit la forme compacte utilisee par les gros caches.
    """
    atomic_write_text(p, json.dumps(obj, ensure_ascii=False, indent=indent), mkdir=mkdir)


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


_PRESERVED_REVIEW_DIRNAME = "_preserved_review"


def clean_old_runs(state_dir: Path, keep_last: int = 10) -> None:
    runs = state_dir / "runs"
    if not runs.exists():
        return
    # R8-002 (F1, PERTE DE DONNEES) : la retention-runs supprimait les vieux run_dirs
    # entiers (shutil.rmtree), DETRUISANT au passage <run_dir>/_review qui contient les
    # ORIGINAUX quarantines de l'apply (buckets conflict/duplicate/leftover, cf
    # apply_support: run_review_root). Ces originaux etaient perdus AVANT revue
    # utilisateur, quel que soit le TTL quarantaine configure. Garde-fou : on NE detruit
    # JAMAIS une quarantaine NON REVUE -> on PRESERVE tout <run_dir>/_review contenant
    # des fichiers, en le relocant sous runs/_preserved_review/ (exclu de la retention),
    # avant de supprimer le reste du run_dir.
    preserved_root = runs / _PRESERVED_REVIEW_DIRNAME
    items = sorted(
        [d for d in runs.iterdir() if d.is_dir() and d.name != _PRESERVED_REVIEW_DIRNAME],
        key=lambda x: x.name,
        reverse=True,
    )
    for d in items[keep_last:]:
        try:
            review = d / "_review"
            if review.is_dir() and any(p.is_file() for p in review.rglob("*")):
                preserved_root.mkdir(parents=True, exist_ok=True)
                dest = preserved_root / d.name
                if dest.exists():
                    suffix = 1
                    while (preserved_root / f"{d.name}__{suffix}").exists():
                        suffix += 1
                    dest = preserved_root / f"{d.name}__{suffix}"
                shutil.move(str(review), str(dest))
                _debug_log_state(
                    state_dir,
                    f"clean_old_runs PRESERVE quarantaine non revue: {review} -> {dest}",
                )
            shutil.rmtree(d)
        except OSError as exc:
            _debug_log_state(state_dir, f"clean_old_runs warning path={d} error={exc}")

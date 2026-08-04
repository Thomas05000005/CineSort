from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

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


class RunDirectoryConflictError(FileExistsError):
    """Le dossier `runs/tri_films_<run_id>` est deja pris.

    Herite de `FileExistsError` (donc d'`OSError`) pour que les boundaries
    existantes qui filtrent OSError continuent de la traiter proprement.
    """


def create_run_dir(run_dir: Path, *, exclusive: bool) -> None:
    """Cree le dossier d'un run sans jamais ecraser silencieusement l'existant.

    Deux modes :

    - `exclusive=True` : RESERVATION ATOMIQUE. Le `mkdir` est fait sans
      `exist_ok`, donc c'est le systeme de fichiers lui-meme qui arbitre la
      course (EEXIST comme signal). C'est le seul mode qui protege le DISQUE :
      le dossier de run est cree AVANT l'insertion en base, une garde purement
      cote base arriverait trop tard.
    - `exclusive=False` : compat des flux qui rouvrent un run EXISTANT (apply,
      diagnostics, historique). On tolere un dossier deja la, mais on refuse
      quand meme d'en faire un point de creation s'il est deja PEUPLE lorsque
      l'appelant a la semantique « nouveau run » (cf. `new_run`).
    """
    if exclusive:
        run_dir.parent.mkdir(parents=True, exist_ok=True)
        try:
            run_dir.mkdir()
        except FileExistsError as exc:
            raise RunDirectoryConflictError(
                f"Le dossier de run {run_dir} existe deja : run_id deja utilise, "
                "creation refusee pour ne pas ecraser un plan existant."
            ) from exc
        return
    run_dir.mkdir(parents=True, exist_ok=True)


def new_run(state_dir: Path, run_id: str, *, exclusive: bool = False) -> RunPaths:
    runs = state_dir / "runs"
    run_dir = runs / f"tri_films_{run_id}"
    if exclusive:
        create_run_dir(run_dir, exclusive=True)
    else:
        # Sans reservation atomique, on refuse au moins de reutiliser un dossier
        # deja PEUPLE : c'est exactement le scenario ou le second run ecrasait
        # le plan.jsonl du premier sans rien signaler.
        if run_dir.is_dir() and any(run_dir.iterdir()):
            raise RunDirectoryConflictError(
                f"Le dossier de run {run_dir} existe deja et contient des donnees "
                "(plan, logs ou quarantaine) : refus de le reutiliser pour un nouveau run."
            )
        create_run_dir(run_dir, exclusive=False)

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


def atomic_write_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = f"{p.name}.tmp.{os.getpid()}.{threading.get_ident()}.{time.time_ns()}.{uuid.uuid4().hex[:8]}"
    tmp = p.with_name(tmp_name)
    try:
        # Durabilite (audit 2026-07-30 #820) : flush + fsync AVANT os.replace. os.replace
        # est atomique cote entree de repertoire, mais sans fsync les donnees du tmp peuvent
        # ne pas etre sur le disque au moment du crash -> fichier destination tronque/0-octet.
        # Meme garantie que poster_proxy._atomic_write.
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=2))
            f.flush()
            os.fsync(f.fileno())
        # R8-026 (F2-d) : retry court sur os.replace. Sur Windows, os.replace leve
        # PermissionError (WinError 5/32) quand un lecteur concurrent (poller UI, 2e onglet)
        # tient le fichier destination ouvert -> le write etait PERDU (l'ancienne valeur restait).
        # Boucle bornee (5x, backoff ~50ms) ; l'atomicite n'est PAS affectee (os.replace reste
        # atomique, jamais de JSON corrompu). On re-leve apres epuisement des tentatives.
        _replace_exc: Optional[PermissionError] = None
        for _attempt in range(5):
            try:
                os.replace(tmp, p)
                _replace_exc = None
                break
            except PermissionError as exc:
                _replace_exc = exc
                time.sleep(0.05 * (_attempt + 1))
        if _replace_exc is not None:
            raise _replace_exc
    finally:
        # Best-effort cleanup : tmp.exists() / tmp.unlink() ne peuvent lever
        # qu'OSError (PermissionError, FileNotFoundError en derivent). Les
        # KeyError / TypeError / ValueError / JSONDecodeError historiques ici
        # n'avaient pas de cause plausible sur ces 2 syscalls.
        try:
            if tmp.exists():
                tmp.unlink()
        except OSError:
            pass


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

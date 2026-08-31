#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
observe.py — Outillage d'observation reutilisable CineSort (Section 0.6).

Lance l'application (EXE prefere si dispo, sinon `python app.py --dev`) en mode
CDP (Chrome DevTools Protocol) et passe sur chaque vue dashboard pour capturer :

    docs/internal/observe/<YYYY-MM-DD_HHMMSS>/<view>/
        screenshot.png      — capture pleine fenetre
        network.json        — fetch+xhr + statuts HTTP + violations CSP
        console.log         — messages console (error + warning + info)
        violations_csp.json — sous-ensemble specifique CSP (analyse posters)

Egalement :
    docs/internal/observe/<timestamp>/cinesort.log.tail.txt
        — 50 dernieres lignes scrubbees du log app (issues/.../logs/cinesort.log)
    docs/internal/observe/<timestamp>/summary.json
        — recapitulatif machine-lisible des vues + erreurs majeures + CSP

Marqueurs :
    [FIGE]          — invariants verifies (chemins, ports, structure)
    [HYPOTHESE]     — defaut applique en l'absence de signal explicite
    [OPERATIONNEL]  — etape executee live (lancement, navigation, capture)

AUCUNE PUBLICATION. AUCUN FIX SOURCE. Scrubbe les cles/secrets.

================================================================================
GATE FRAICHEUR ETAT (etape 5 diag 2026-06-08) — `--fresh`
================================================================================

Le diag DIAG_OBSERVE_FRESHNESS_2026-06-08.md a demontre que les mesures observe.py
peuvent etre polluees par 3 sources de staleness :

    H1 staleness EXE pre-fix
        => `dist/CineSort.exe` peut etre anterieur au code source courant
        (verifie 2026-06-08 : EXE 11:56 vs fix ii.b commit `7df3af3e`).
    H2 staleness DB / runs derives
        => `%LOCALAPPDATA%\\CineSort\\db\\cinesort.sqlite` + `runs\\tri_films_*`
        accumulent un etat residuel.
    H4 staleness WebView2 userdata
        => `%LOCALAPPDATA%\\CineSort\\webview\\EBWebView` conserve
        sessionStorage / localStorage / Cache HTTP / cookies.

Le flag `--fresh` declenche AVANT le lancement de l'app :
    a. force mode `python app.py --dev` (jamais l'EXE pre-fix) ;
    b. reset etat derive du PERIMETRE `--library` (DB + runs/tri_films_*),
       protege les donnees utilisateur reelles (`\\\\OMV\\Media` etc.) ET toute
       autre bibliotheque, meme si son chemin porte `test_library` ;
       sauvegarde prealable : `cinesort.sqlite.bak_BEFORE_FRESH_<ts>` avec ses
       sidecars `-wal`/`-shm`, et `runs.bak_BEFORE_FRESH_<ts>/` pour les
       dossiers de run ;
    c. purge WebView2 userdata (`webview/EBWebView` du LOCALAPPDATA cible),
       en ne tuant que les hotes WebView2 rattaches a ce state.

`--dry-run` combine a `--fresh` SIMULE la gate : `freshness_gate.json` liste
`would_delete_run_ids` / `would_delete_run_dirs` sans rien detruire.

Le flag n'a JAMAIS d'effet sur :
    - settings.json (etat operateur, garde la cle TMDb, le token REST, ...) ;
    - omdb_cache.json / tmdb_cache.json (caches partages indexes par titre) ;
    - les donnees utilisateur reelles hors scope test_library.

Protocole complet : `docs/internal/observe_protocol.md`.

Mode manuel : sans `--fresh`, executer les 3 pre-etapes a la main (voir
observe_protocol.md section "Procedure GATE manuelle").

================================================================================

Usage :
    python scripts/observe.py --library test_library --modes dashboard
    python scripts/observe.py --library test_library --modes dashboard,desktop
    python scripts/observe.py --output docs/internal/observe/2026-06-08_T1
    python scripts/observe.py --library test_library --fresh   # gate H1+H2+H4
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shutil
import socket
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Constantes [FIGE]
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DIST_EXE = PROJECT_ROOT / "dist" / "CineSort.exe"
APP_PY = PROJECT_ROOT / "app.py"
DEFAULT_CDP_PORT = 9223  # different de 9222 (utilise par e2e tests)
DEFAULT_OUTPUT_PARENT = PROJECT_ROOT / "docs" / "internal" / "observe"

# Routes dashboard a observer. [FIGE] depuis app.js registerRoute.
# Format : (view_label_pour_dossier, hash_a_naviguer)
# Sub-vues dashboard : traitement#step-* (workflow 5 etapes), parametres#*.
DASHBOARD_VIEWS: list[tuple[str, str]] = [
    ("accueil", "#/accueil"),
    ("traitement", "#/traitement"),
    ("traitement_step_analyse", "#/traitement#step-analyse"),
    ("traitement_step_verification", "#/traitement#step-verification"),
    ("traitement_step_validation", "#/traitement#step-validation"),
    ("traitement_step_doublons", "#/traitement#step-doublons"),
    ("traitement_step_apply", "#/traitement#step-apply"),
    ("bibliotheque", "#/bibliotheque"),
    ("qualite", "#/qualite"),
    ("historique", "#/historique"),
    ("jellyfin", "#/parametres#integrations-jellyfin"),
    ("parametres", "#/parametres"),
    ("parametres_sources", "#/parametres#sources"),
    ("parametres_integrations", "#/parametres#integrations"),
    ("parametres_retention", "#/parametres#retention"),
    ("aide", "#/aide"),
    ("doublons", "#/doublons"),
]


# ---------------------------------------------------------------------------
# Scrub helpers [FIGE] — protection cles/secrets (token, paths utilisateur)
# ---------------------------------------------------------------------------

# Patterns conservateurs : token bearer, query ntoken=, JWT-like, paths persos.
_RE_BEARER = re.compile(r"(Bearer\s+)[A-Za-z0-9_\-\.]+", re.IGNORECASE)
_RE_NTOKEN_QS = re.compile(r"([?&]ntoken=)[^&\s\"']+", re.IGNORECASE)
_RE_TOKEN_FIELD = re.compile(
    r"(\"(?:rest_api_token|api_key|tmdb_api_key|jellyfin_api_key|password)\"\s*:\s*\")[^\"]+(\")",
    re.IGNORECASE,
)
# Chemin utilisateur, forme antislash. Le texte a scrubber arrive sous DEUX
# formes : NATIVE (`C:\Users\bob`, le tail de cinesort.log, les messages
# d'exception) et DEJA ECHAPPEE (`C:\\Users\\bob`, les payloads JSON de
# network.json). L'ancien motif `r"C:\\\\Users\\\\[^\\\\\"]+"` portait QUATRE
# antislashs reels entre `C:` et `Users`, donc en exigeait DEUX du moteur : il
# ne mordait que sur la seconde forme, et laissait passer en clair tout chemin
# Windows natif — l'exact contraire de ce que promet l'en-tete de section.
# Sa substitution reposait de surcroit UN seul antislash la ou la source en
# portait deux, ce qui rendait la ligne JSON indecodable (`\U` n'est pas une
# echappement JSON valide). On capture donc le separateur TEL QU'IL EST et on
# le repose a l'identique.
_RE_USER_HOME = re.compile(r"(C:)(\\{1,2})(Users)(\\{1,2})([^\\/\"]+)", re.IGNORECASE)
_RE_USER_HOME_FW = re.compile(r"C:/Users/[^/\"]+", re.IGNORECASE)


def _redact_user_home(match: re.Match[str]) -> str:
    """Remplace le nom d'utilisateur en conservant l'echappement d'origine."""
    return f"{match.group(1)}{match.group(2)}{match.group(3)}{match.group(4)}<USER>"


def scrub(text: str) -> str:
    """Scrubbe les valeurs sensibles d'une chaine. Sur."""
    if not text:
        return text
    out = text
    out = _RE_BEARER.sub(r"\1<REDACTED>", out)
    out = _RE_NTOKEN_QS.sub(r"\1<REDACTED>", out)
    out = _RE_TOKEN_FIELD.sub(r"\1<REDACTED>\2", out)
    out = _RE_USER_HOME.sub(_redact_user_home, out)
    out = _RE_USER_HOME_FW.sub("C:/Users/<USER>", out)
    return out


# ---------------------------------------------------------------------------
# Perimetre : comparaison de CHEMINS, jamais de sous-chaines [FIGE]
# ---------------------------------------------------------------------------
#
# `--library` a longtemps ete un simple INTERRUPTEUR : la garde verifiait
# `"test_library" in str(lib_abs).lower()`, puis les suppressions repartaient
# du litteral `'%test_library%'`. Deux consequences mesurees :
#   - `--library .../test_library_A` detruisait AUSSI `.../test_library_B` ;
#   - `LIKE '%test_library%'` traite `_` comme un joker SQL, donc `testXlibrary`
#     tombait dans le meme filet.
# Le perimetre est desormais le chemin resolu de `--library`, compare segment
# par segment.

#: Caracteres qui ferment legitimement un chemin cite dans un journal.
_SCOPE_BOUNDARY = "/\"' \t\r\n,;:)]}>|"

#: Champs de `plan.jsonl` qui portent un chemin exploitable.
_RUN_PLAN_PATH_FIELDS = (
    "root_path",
    "folder_path",
    "src_path",
    "dst_path",
    "src",
    "dst",
    "path",
    "source",
    "target",
)


def _norm_path_for_scope(value: Any) -> str:
    """Forme canonique d'un chemin pour comparaison (casse + separateur)."""
    return str(value).replace("\\", "/").rstrip("/").lower()


def _path_in_scope(candidate: Any, scope_norm: str) -> bool:
    """True si `candidate` EST le perimetre, ou vit dedans (frontiere de segment)."""
    if not scope_norm or not isinstance(candidate, str) or not candidate:
        return False
    norm = _norm_path_for_scope(candidate)
    return norm == scope_norm or norm.startswith(scope_norm + "/")


def _text_mentions_scope(text: str, scope_norm: str) -> bool:
    """True si `text` cite le chemin COMPLET du perimetre, frontiere comprise.

    Sans la frontiere, `.../test_library_A` matcherait `.../test_library_AB`.
    """
    if not scope_norm or not text:
        return False
    hay = text.replace("\\", "/").lower()
    start = 0
    while True:
        idx = hay.find(scope_norm, start)
        if idx < 0:
            return False
        end = idx + len(scope_norm)
        if end >= len(hay) or hay[end] in _SCOPE_BOUNDARY:
            return True
        start = idx + 1


def _read_head(path: Path, size: int = 256 * 1024) -> str:
    """Lit la tete d'un fichier en texte tolerant. Vide si illisible."""
    try:
        with open(path, "rb") as fh:
            return fh.read(size).decode("utf-8", errors="replace")
    except OSError:
        return ""


def _plan_jsonl_in_scope(plan: Path, scope_norm: str) -> bool:
    """Relit `plan.jsonl` comme du JSON et confronte ses chemins au perimetre."""
    for raw in _read_head(plan).splitlines():
        line = raw.strip()
        if not line.startswith("{"):
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue  # derniere ligne tronquee par la lecture partielle
        if not isinstance(row, dict):
            continue
        if any(_path_in_scope(row.get(key), scope_norm) for key in _RUN_PLAN_PATH_FIELDS):
            return True
    return False


def _run_dir_in_scope(run_dir: Path, scope_norm: str) -> bool:
    """Le run PORTE-t-il sur le perimetre ?

    Le declencheur historique etait `b"test_library" in chunk.lower()` sur
    `plan.jsonl` OU `ui_log.txt` OU `summary.txt` : aucune analyse de chemin,
    aucune frontiere de mot. Or `ui_log.txt` est un JOURNAL — une ligne qui
    NOMME la bibliotheque d'un autre run suffisait a faire detruire celui-ci.
    """
    plan = run_dir / "plan.jsonl"
    if plan.is_file() and _plan_jsonl_in_scope(plan, scope_norm):
        return True
    for name in ("ui_log.txt", "summary.txt"):
        marker = run_dir / name
        if marker.is_file() and _text_mentions_scope(_read_head(marker), scope_norm):
            return True
    return False


# ---------------------------------------------------------------------------
# Helpers process / port
# ---------------------------------------------------------------------------

#: Nom d'image de l'hote WebView2. JAMAIS passe a `taskkill /IM` : ce nom est
#: partage par Teams, Outlook, et toute application WebView2 de la machine.
_WEBVIEW2_IMAGE = "msedgewebview2.exe"


def _webview2_pids_in_scope(scope_dir: Path) -> tuple[list[int], str | None]:
    """PIDs des hotes WebView2 dont la ligne de commande vise `scope_dir`.

    `taskkill /F /IM msedgewebview2.exe` cible par NOM D'IMAGE, sans filtre de
    PID ni de proprietaire, et `/F` interdit toute demande de sauvegarde : tout
    hote WebView2 de la machine est emporte, pas seulement celui du run.
    On resout donc les PID par leur `--user-data-dir`, qui porte le state cible.

    Returns:
        (pids, erreur) — `erreur` non nulle si l'inventaire n'a pas pu etre fait.
    """
    scope_norm = _norm_path_for_scope(scope_dir)
    query = (
        f"Get-CimInstance Win32_Process -Filter \"Name='{_WEBVIEW2_IMAGE}'\" | "
        "Select-Object ProcessId,CommandLine | ConvertTo-Json -Compress"
    )
    try:
        cp = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", query],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return [], scrub(str(exc))
    raw = (cp.stdout or "").strip()
    if not raw:
        return [], None
    try:
        data = json.loads(raw)
    except ValueError as exc:
        return [], f"inventaire WebView2 illisible: {exc}"
    if isinstance(data, dict):
        data = [data]
    if not isinstance(data, list):
        return [], "inventaire WebView2 de forme inattendue"
    pids: list[int] = []
    for proc in data:
        if not isinstance(proc, dict):
            continue
        # Frontiere de segment obligatoire : sans elle, un state voisin
        # `<...>/CineSort2` tomberait dans le perimetre de `<...>/CineSort`.
        if not _text_mentions_scope(str(proc.get("CommandLine") or ""), scope_norm):
            continue
        with contextlib.suppress(TypeError, ValueError):
            pids.append(int(proc.get("ProcessId")))
    return pids, None


def _taskkill(args: list[str]) -> tuple[bool, str | None]:
    """`taskkill` best-effort. rc==128 (« process not found ») = cas normal."""
    try:
        cp = subprocess.run(
            ["taskkill", *args],
            capture_output=True,
            timeout=10,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        return False, scrub(str(exc))
    return cp.returncode == 0, None


def _kill_webview2_in_scope(scope_dir: Path) -> dict[str, Any]:
    """Tue les seuls hotes WebView2 rattaches a `scope_dir`."""
    outcome: dict[str, Any] = {"pids": [], "killed": {}, "errors": []}
    pids, err = _webview2_pids_in_scope(scope_dir)
    if err:
        outcome["errors"].append(f"{_WEBVIEW2_IMAGE}: {err}")
    outcome["pids"] = pids
    for pid in pids:
        ok, kill_err = _taskkill(["/F", "/PID", str(pid)])
        outcome["killed"][str(pid)] = ok
        if kill_err:
            outcome["errors"].append(f"{_WEBVIEW2_IMAGE}#{pid}: {kill_err}")
    return outcome


def _wait_for_port(host: str, port: int, timeout_s: int = 60) -> bool:
    """Attend qu'un port TCP accepte une connexion. [OPERATIONNEL]"""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            s = socket.create_connection((host, port), timeout=1)
            s.close()
            return True
        except (ConnectionRefusedError, OSError):
            time.sleep(1)
    return False


def _detect_app_command(prefer_exe: bool = True) -> tuple[list[str], str]:
    """Retourne (cmd, mode_label).

    [HYPOTHESE] prefere EXE existant, sinon `python app.py --dev`.

    [HARNESS DIAG 2026-06-08 etape 2a] Force temporairement `python app.py --dev`
    car le dist/CineSort.exe (date 2026-06-08 11:56) est anterieur au fix ii.b
    (commit 7df3af3e). Sans ce switch, observe.py mesure un binaire pre-fix et
    masque l'effet de la correction. A retirer apres rebuild EXE et fin du
    diag observe-freshness. Branche: loop/correction-2026-06.
    """
    # [HARNESS DIAG] Bypass force mode dev. Variables d'env :
    #   - CINESORT_OBSERVE_FORCE_DEV=1 force python app.py --dev (gate freshness).
    #   - CINESORT_OBSERVE_USE_EXE=1 restaure le comportement EXE-prefere.
    if os.environ.get("CINESORT_OBSERVE_FORCE_DEV") == "1":
        return ([sys.executable, str(APP_PY), "--dev"], "dev")
    if os.environ.get("CINESORT_OBSERVE_USE_EXE") == "1":
        if prefer_exe and DIST_EXE.is_file():
            return ([str(DIST_EXE)], "exe")
    return ([sys.executable, str(APP_PY), "--dev"], "dev")


def _make_state_dir_isolated(out_dir: Path) -> Path:
    """Cree un state_dir isole pour ne pas polluer %LOCALAPPDATA%/CineSort.

    [HYPOTHESE] : on isole pour observation reproductible. Si l'utilisateur
    veut observer son etat reel, il peut passer --use-local-state (TODO).
    """
    state = out_dir / "_state"
    state.mkdir(parents=True, exist_ok=True)
    return state


# ---------------------------------------------------------------------------
# GATE FRAICHEUR (etape 5 verrouillage piege) [OPERATIONNEL]
# ---------------------------------------------------------------------------
#
# Pre-etapes appliquees automatiquement avec --fresh. Chaque fonction est
# IDEMPOTENTE et NE TOUCHE PAS aux donnees utilisateur reelles : elle agit
# uniquement sur le LOCALAPPDATA cible (par defaut le state isole observe.py,
# ou %LOCALAPPDATA% si --use-local-state est fourni).


def _purge_webview2_userdata(localappdata: Path, *, dry_run: bool = False) -> dict[str, Any]:
    """Supprime `<LOCALAPPDATA>\\CineSort\\webview\\` (cache WebView2 evergreen).

    Idempotent : si le dossier n'existe pas, retourne ok=True purged=False.
    Ne touche PAS aux autres dossiers (db, runs, logs, settings.json).

    En `dry_run`, mesure et ANNONCE sans rien supprimer ni tuer.

    [HARNESS DIAG 2026-06-08 etape 2c+5] traite H4 staleness userdata.
    """
    target = localappdata / "CineSort" / "webview"
    result: dict[str, Any] = {
        "ok": True,
        "target": str(target),
        "purged": False,
        "bytes_freed": 0,
        "dry_run": bool(dry_run),
    }
    try:
        if not target.exists():
            result["note"] = "absent (rien a purger)"
            return result
        # Mesure taille avant.
        total = 0
        try:
            for p in target.rglob("*"):
                if p.is_file():
                    with contextlib.suppress(OSError):
                        total += p.stat().st_size
        except OSError:
            pass
        result["bytes_freed"] = total
        if dry_run:
            result["would_purge"] = True
            return result
        # Best effort kill des SEULS hotes WebView2 du state cible (jamais /IM).
        result["webview2_kill"] = _kill_webview2_in_scope(localappdata / "CineSort")
        # Suppression recursive.
        shutil.rmtree(target, ignore_errors=True)
        result["purged"] = not target.exists()
        if not result["purged"]:
            result["ok"] = False
            result["error"] = "purge incomplete (handles ouverts ?)"
    except Exception as exc:
        result["ok"] = False
        result["error"] = scrub(str(exc))
    return result


def _backup_db_with_sidecars(db_path: Path, ts: str) -> tuple[Path, list[str]]:
    """Copie la DB **et ses sidecars WAL** avant tout DELETE.

    TOUS les profils du produit imposent `journal_mode=WAL`
    (`cinesort/infra/db/pragma_profile.py`). En WAL, les pages ecrites depuis
    le dernier checkpoint vivent dans `cinesort.sqlite-wal`, pas dans le
    `.sqlite`. Copier le seul fichier principal — ce que faisait le
    `shutil.copy2(db_path, backup)` d'origine — produit donc une sauvegarde
    ANTERIEURE a tout ce que la session courante a ecrit : la promesse
    « backup auto » de l'aide de `--fresh` etait tenue sur le nom du fichier,
    pas sur son contenu.

    Le suffixe des sidecars est colle au nom du backup (`<backup>-wal`,
    `<backup>-shm`) : c'est la seule forme que SQLite saura reprendre.
    """
    backup = db_path.with_suffix(f".sqlite.bak_BEFORE_FRESH_{ts}")
    shutil.copy2(db_path, backup)
    sidecars: list[str] = []
    for suffix in ("-wal", "-shm"):
        side = db_path.with_name(db_path.name + suffix)
        if not side.is_file():
            continue
        dst = backup.with_name(backup.name + suffix)
        shutil.copy2(side, dst)
        sidecars.append(str(dst))
    return backup, sidecars


def _probe_cache_rowids_in_scope(cur: sqlite3.Cursor, scope_norm: str) -> list[int]:
    """rowids de `probe_cache` dont le chemin vit dans le perimetre.

    Le filtre d'origine etait `LOWER(path) LIKE '%test_library%'` : hors
    perimetre (toute bibliotheque portant le marqueur y passait) ET trop large
    (`_` est un joker SQL, donc `testXlibrary` matchait aussi).
    """
    try:
        cur.execute("SELECT rowid, path FROM probe_cache")
    except sqlite3.Error:
        return []
    return [rid for rid, path in cur.fetchall() if _path_in_scope(path, scope_norm)]


def _delete_scope_rows(cur: sqlite3.Cursor, run_ids: list[str], scope_norm: str) -> dict[str, int]:
    """Supprime les lignes du perimetre. `foreign_keys` DOIT etre ON (cf. appelant)."""
    deleted: dict[str, int] = {}
    if run_ids:
        placeholders = ",".join("?" for _ in run_ids)
        cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
        for tbl in [r[0] for r in cur.fetchall()]:
            try:
                cur.execute(f"PRAGMA table_info({tbl})")
                cols = [c[1] for c in cur.fetchall()]
                if "run_id" in cols:
                    cur.execute(f"DELETE FROM {tbl} WHERE run_id IN ({placeholders})", run_ids)
                    if cur.rowcount > 0:
                        deleted[tbl] = cur.rowcount
            except sqlite3.Error:
                continue
    rowids = _probe_cache_rowids_in_scope(cur, scope_norm)
    purged = 0
    for start in range(0, len(rowids), 500):
        block = rowids[start : start + 500]
        placeholders = ",".join("?" for _ in block)
        cur.execute(f"DELETE FROM probe_cache WHERE rowid IN ({placeholders})", block)
        purged += max(cur.rowcount, 0)
    if purged:
        deleted["probe_cache_by_path"] = purged
    return deleted


def _reset_db_scope(
    db_path: Path,
    scope_norm: str,
    result: dict[str, Any],
    *,
    dry_run: bool,
    ts: str,
) -> list[str]:
    """Purge les lignes DB du perimetre. Retourne les run_ids concernes."""
    try:
        conn = sqlite3.connect(str(db_path))
        try:
            # `PRAGMA foreign_keys` est OFF par defaut en SQLite, alors que le
            # produit l'active systematiquement (infra/db/connection.py) et que
            # `021_fk_cascade.sql` pose expres
            # `apply_operations.batch_id -> apply_batches(batch_id) ON DELETE
            # CASCADE`. Sans ce pragma, supprimer `apply_batches` (porteuse de
            # run_id) laissait `apply_operations` — qui n'a PAS de colonne
            # run_id — orpheline dans le journal d'undo.
            conn.execute("PRAGMA foreign_keys = ON")
            cur = conn.cursor()
            cur.execute("SELECT run_id, root FROM runs")
            run_ids = [rid for rid, root in cur.fetchall() if _path_in_scope(root, scope_norm)]
            result["would_delete_run_ids"] = list(run_ids)
            result["run_ids_scope"] = list(run_ids)
            if dry_run:
                result["db_rows_deleted"] = {}
                conn.rollback()
                return run_ids
            backup, sidecars = _backup_db_with_sidecars(db_path, ts)
            result["backup"] = str(backup)
            result["backup_sidecars"] = sidecars
            result["db_rows_deleted"] = _delete_scope_rows(cur, run_ids, scope_norm)
            conn.commit()
            return run_ids
        finally:
            conn.close()
    except Exception as exc:
        result["ok"] = False
        result["error_db"] = scrub(str(exc))
        return []


def _reset_runs_scope(
    runs_dir: Path,
    scope_run_ids: set[str],
    scope_norm: str,
    result: dict[str, Any],
    *,
    dry_run: bool,
    ts: str,
) -> None:
    """Sauvegarde puis supprime les dossiers de run du perimetre.

    L'aide de `--fresh` annonce « reset DB+runs scope test_library (backup
    auto) ». La sauvegarde n'existait que dans la branche DB : la branche
    runs/ appelait `shutil.rmtree(run_dir, ignore_errors=True)` avec ZERO
    sauvegarde. Chaque dossier est donc desormais COPIE d'abord, et n'est
    detruit que si la copie a reussi.
    """
    backup_root = runs_dir.parent / f"runs.bak_BEFORE_FRESH_{ts}"
    would: list[str] = []
    deleted_runs = 0
    errors: list[str] = []
    for run_dir in sorted(runs_dir.glob("tri_films_*")):
        if not run_dir.is_dir():
            continue
        run_id = run_dir.name[len("tri_films_") :]
        if run_id not in scope_run_ids and not _run_dir_in_scope(run_dir, scope_norm):
            continue
        would.append(run_dir.name)
        if dry_run:
            continue
        try:
            shutil.copytree(run_dir, backup_root / run_dir.name, dirs_exist_ok=True)
        except (OSError, shutil.Error) as exc:
            # Pas de destruction sans sauvegarde : c'est la promesse de l'aide.
            errors.append(f"{run_dir.name}: {scrub(str(exc))}")
            continue
        shutil.rmtree(run_dir, ignore_errors=True)
        if not run_dir.exists():
            deleted_runs += 1
    result["would_delete_run_dirs"] = would
    result["runs_deleted"] = deleted_runs
    if errors:
        result["ok"] = False
        result["runs_backup_errors"] = errors
    if not dry_run and backup_root.is_dir():
        result["runs_backup"] = str(backup_root)


def _reset_test_library_state(
    localappdata: Path,
    library: Path | None,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Reset etat derive scope `--library`.

    Cible (et RIEN d'autre) :
        - runs `tri_films_*` dont le plan porte sur la bibliotheque ciblee ;
        - lignes DB SQLite (runs/quality_reports/probe_cache/...) liees.

    PROTEGE :
        - donnees utilisateur reelles (\\\\OMV\\Media, etc.) preservees ;
        - toute AUTRE bibliotheque, meme si son chemin porte `test_library` ;
        - settings.json / omdb_cache.json / tmdb_cache.json non touches ;
        - backup `cinesort.sqlite.bak_BEFORE_FRESH_<ts>` (+ sidecars `-wal` /
          `-shm`) et `runs.bak_BEFORE_FRESH_<ts>/` crees avant tout DELETE.

    [HARNESS DIAG 2026-06-08 etape 2b+5] traite H2 staleness DB/runs derives.

    Si la DB n'existe pas (premier run, isolation propre) -> no-op ok=True.
    Si la library n'est pas test_library (ou non resolvable) -> aucun reset.
    En `dry_run`, rien n'est supprime : le rapport porte `would_delete_*`.
    """
    result: dict[str, Any] = {
        "ok": True,
        "scope": str(library) if library else None,
        "dry_run": bool(dry_run),
        "runs_deleted": 0,
        "db_rows_deleted": {},
        "backup": None,
        "backup_sidecars": [],
        "would_delete_run_ids": [],
        "would_delete_run_dirs": [],
        "skipped_reasons": [],
    }
    db_path = localappdata / "CineSort" / "db" / "cinesort.sqlite"
    runs_dir = localappdata / "CineSort" / "runs"

    if not db_path.is_file() and not runs_dir.is_dir():
        result["skipped_reasons"].append("etat derive absent (premier run)")
        return result

    # Resolution scope : seul un chemin contenant 'test_library' est reset, et
    # le chemin RESOLU devient le perimetre reel des suppressions.
    scope_marker: str | None = None
    if library is not None:
        try:
            lib_abs = library.resolve()
            if "test_library" in str(lib_abs).lower():
                scope_marker = str(lib_abs)
            else:
                result["skipped_reasons"].append("library hors scope test_library, donnees utilisateur PROTEGEES")
        except OSError as exc:
            result["skipped_reasons"].append(f"library non resolvable: {exc}")

    if not scope_marker:
        return result

    scope_norm = _norm_path_for_scope(scope_marker)
    result["scope_resolved"] = scope_marker
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")

    scope_run_ids: set[str] = set()
    if db_path.is_file():
        scope_run_ids = set(_reset_db_scope(db_path, scope_norm, result, dry_run=dry_run, ts=ts))

    if runs_dir.is_dir():
        try:
            _reset_runs_scope(runs_dir, scope_run_ids, scope_norm, result, dry_run=dry_run, ts=ts)
        except Exception as exc:
            result["ok"] = False
            result["error_runs"] = scrub(str(exc))

    return result


def _rebuild_exe_if_needed() -> dict[str, Any]:
    """No-op informatif : signale juste si l'EXE est anterieur au HEAD git.

    On NE rebuilde PAS automatiquement (15 min, lock release).
    En mode --fresh on force `python app.py --dev` (cf. _detect_app_command +
    CINESORT_OBSERVE_FORCE_DEV=1) ; ce helper sert uniquement de trace au summary.

    [HARNESS DIAG 2026-06-08 etape 2a+5] traite H1 staleness EXE pre-fix.
    """
    result: dict[str, Any] = {
        "ok": True,
        "exe_present": DIST_EXE.is_file(),
        "exe_mtime": None,
        "head_commit_ts": None,
        "is_stale": None,
        "action": "force_dev_mode",
    }
    if DIST_EXE.is_file():
        with contextlib.suppress(OSError):
            result["exe_mtime"] = datetime.fromtimestamp(DIST_EXE.stat().st_mtime).isoformat(timespec="seconds")
    try:
        out = subprocess.run(
            ["git", "log", "-1", "--format=%cI"],
            cwd=str(PROJECT_ROOT),
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
        if out.returncode == 0:
            result["head_commit_ts"] = out.stdout.strip()
            if result["exe_mtime"] and result["head_commit_ts"]:
                # Comparaison ISO lexicographique suffit.
                result["is_stale"] = result["exe_mtime"] < result["head_commit_ts"]
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass
    return result


def _kill_residual_processes(localappdata: Path) -> dict[str, Any]:
    """Pre-etape A0 : kill best-effort des process residuels d'un run anterieur.

    [HARNESS REMEDIATION ITER8B C1 2026-06-09] Le bilan ITER8B Section 2.1 a
    documente que la pre-etape kill systematique de `CineSort.exe`,
    `python.exe` et `msedgewebview2.exe` etait appliquee MANUELLEMENT entre
    chaque checkout pour eviter la pollution inter-runs (process lock sur
    WebView2 userdata residuel, summary.json + screenshots ABSENTS sur les 17
    vues lors de la capture ITER8_NONREG_GLOBAL initiale).

    On internalise cette pre-etape dans le harness pour rendre l'isolation
    inter-runs automatique : un run observe.py --fresh ne dependra plus d'un
    nettoyage operateur manuel.

    Idempotent + best-effort + silencieux : taskkill /F /IM <exe> retourne
    code 128 si aucun process ne tourne (cas normal premier run).

    NE TUE PAS le process Python courant (observe.py) lui-meme :
        - `python.exe` n'est cible que par PID different (filtre /FI "PID ne ...")
          plus complique a fiabiliser cross-shell ; on prefere ne PAS tuer python
          pour eviter le suicide.
        - On cible donc UNIQUEMENT `CineSort.exe` (l'EXE PyInstaller) et
          `msedgewebview2.exe` (WebView2). Le risque de double subprocess
          `python app.py --dev` orphelin est negligeable (chaque run lance son
          propre subprocess et le tue en fin de capture via _start_app).

    `msedgewebview2.exe` n'est PLUS tue par nom d'image : ce nom est partage
    par Teams, Outlook et toute application WebView2 de la machine, et `/F`
    interdit la sauvegarde. Les hotes sont resolus par PID via leur
    `--user-data-dir`, qui pointe le state du run (cf. `_kill_webview2_in_scope`).

    Args:
        localappdata: racine du state cible (`<localappdata>/CineSort` sert de
            perimetre pour la resolution des PID WebView2).

    Returns:
        dict { ok: bool, killed: { exe: bool, ... }, errors: [...] }
    """
    result: dict[str, Any] = {
        "ok": True,
        "killed": {},
        "errors": [],
    }
    # rc==0 : au moins un process tue ; rc==128 : "process not found" (cas normal).
    ok, err = _taskkill(["/F", "/IM", "CineSort.exe"])
    result["killed"]["CineSort.exe"] = ok
    if err:
        result["errors"].append(f"CineSort.exe: {err}")
    scoped = _kill_webview2_in_scope(localappdata / "CineSort")
    result["webview2_pids"] = scoped["pids"]
    for pid, killed in scoped["killed"].items():
        result["killed"][f"{_WEBVIEW2_IMAGE}#{pid}"] = killed
    result["errors"].extend(scoped["errors"])
    return result


def run_freshness_gate(
    out_dir: Path,
    library: Path | None,
    use_local_state: bool,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Orchestre les pre-etapes freshness avant lancement observe.

    [OPERATIONNEL] s'execute si l'utilisateur a fourni `--fresh`.

    Sequence :
        A0. kill process residuels (CineSort.exe + hotes WebView2 DU RUN).
        A.  H1 staleness EXE (informatif + force dev mode).
        B.  H2 reset DB + runs scope `--library`.
        C.  H4 purge WebView2 userdata.

    Avec `dry_run`, la sequence est SIMULEE : rien n'est tue, rien n'est
    supprime, et le rapport porte ce qui SERAIT supprime (`would_delete_*`).
    Auparavant `--dry-run` se contentait de DESACTIVER l'etape destructrice :
    il n'existait donc aucun moyen de previsualiser l'effet de `--fresh`.

    Returns :
        gate_report dict serialise dans <out_dir>/freshness_gate.json.
    """
    if use_local_state:
        # On opere sur le LOCALAPPDATA reel de l'utilisateur.
        local_appdata = Path(os.environ.get("LOCALAPPDATA", str(Path.home())))
        scope_note = "LOCALAPPDATA reel (--use-local-state)"
    else:
        # On opere sur le state isole d'observe.py (cree par _make_state_dir_isolated
        # plus tard ; ici on agit en pre-bootstrap, donc cible "_state").
        local_appdata = out_dir / "_state"
        local_appdata.mkdir(parents=True, exist_ok=True)
        scope_note = "state isole observe.py (_state)"

    report: dict[str, Any] = {
        "ok": True,
        "dry_run": bool(dry_run),
        "scope_note": scope_note,
        "localappdata_target": str(local_appdata),
        "library": str(library) if library else None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    print(
        f"[observe.fresh] [OPERATIONNEL] gate localappdata={local_appdata} library={library} dry_run={bool(dry_run)}",
        file=sys.stderr,
    )

    # Pre-etape A0 : kill process residuels (CineSort.exe + msedgewebview2.exe).
    # [HARNESS REMEDIATION ITER8B C1 2026-06-09] Evite l'incident inter-runs
    # documente dans BILAN_ITER8B_2026-06-08.md Sections 2.1+3.5 :
    # process lock sur WebView2 userdata residuel -> summary.json + screenshots
    # ABSENTS sur les 17 vues (capture ITER8_NONREG_GLOBAL initiale).
    if dry_run:
        report["a0_kill_residual"] = {"ok": True, "simule": True, "killed": {}, "errors": []}
    else:
        report["a0_kill_residual"] = _kill_residual_processes(local_appdata)
    # Pre-etape A : EXE staleness check (informatif + force dev mode plus tard).
    report["h1_exe"] = _rebuild_exe_if_needed()
    # Pre-etape B : reset DB+runs scope --library.
    report["h2_state"] = _reset_test_library_state(local_appdata, library, dry_run=dry_run)
    if not report["h2_state"].get("ok"):
        report["ok"] = False
    # Pre-etape C : purge WebView2 userdata.
    report["h4_webview2"] = _purge_webview2_userdata(local_appdata, dry_run=dry_run)
    if not report["h4_webview2"].get("ok"):
        report["ok"] = False

    report["ended_at"] = datetime.now().isoformat(timespec="seconds")
    try:
        (out_dir / "freshness_gate.json").write_text(
            json.dumps(report, indent=2, ensure_ascii=False, default=str),
            encoding="utf-8",
        )
    except OSError as exc:
        print(f"[observe.fresh] WARN ecriture gate report echouee: {exc}", file=sys.stderr)

    state = report["h2_state"]
    if dry_run:
        print(
            f"[observe.fresh] [OPERATIONNEL] gate SIMULE ok={report['ok']} "
            f"runs_a_supprimer={state.get('would_delete_run_dirs')} "
            f"run_ids_a_supprimer={state.get('would_delete_run_ids')}",
            file=sys.stderr,
        )
        return report
    print(
        f"[observe.fresh] [OPERATIONNEL] gate ok={report['ok']} "
        f"runs_del={state.get('runs_deleted')} "
        f"db_del={sum(state.get('db_rows_deleted', {}).values())} "
        f"webview_purged={report['h4_webview2'].get('purged')}",
        file=sys.stderr,
    )
    return report


def _scrub_log_tail(log_path: Path, n_lines: int = 50) -> str:
    """Lit les n dernieres lignes du log, applique scrub. [OPERATIONNEL]"""
    if not log_path.is_file():
        return f"<absent: {log_path}>"
    try:
        # Lecture binaire en queue pour eviter de tout charger.
        size = log_path.stat().st_size
        chunk = min(size, 256 * 1024)
        with open(log_path, "rb") as f:
            f.seek(max(0, size - chunk))
            data = f.read()
        try:
            text = data.decode("utf-8", errors="replace")
        except Exception:
            text = data.decode("latin-1", errors="replace")
        lines = text.splitlines()[-n_lines:]
        return scrub("\n".join(lines))
    except OSError as exc:
        return f"<erreur lecture: {exc}>"


# ---------------------------------------------------------------------------
# Observer principal (mode dashboard via CDP+Playwright)
# ---------------------------------------------------------------------------


def observe_dashboard(
    out_dir: Path,
    library: Path | None,
    cdp_port: int,
    prefer_exe: bool,
    headless_timeout: int = 90,
) -> dict[str, Any]:
    """Lance l'app + navigue chaque vue. Retourne un summary dict.

    [OPERATIONNEL] : capture screenshot/network/console par vue.
    """
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        return {
            "ok": False,
            "error": "playwright non installe (pip install playwright)",
            "views": [],
        }

    cmd, mode_label = _detect_app_command(prefer_exe=prefer_exe)
    env = os.environ.copy()
    env["CINESORT_E2E"] = "1"
    env["CINESORT_CDP_PORT"] = str(cdp_port)
    # [GATE 1a iter4] Permet de cibler le LOCALAPPDATA reel (run existant
    # apres start_plan REST) sans casser le mode isole par defaut.
    use_real_localappdata = os.environ.get("CINESORT_OBSERVE_USE_REAL_LOCALAPPDATA") == "1"
    if use_real_localappdata:
        # Garde le LOCALAPPDATA reel inherited (pas d'override).
        target_state = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "CineSort"
        state_dir = target_state  # juste pour le journal/manifeste
        target_state.mkdir(parents=True, exist_ok=True)
    else:
        # Isole le state pour ne pas casser la config courante de l'utilisateur.
        state_dir = _make_state_dir_isolated(out_dir)
        env["LOCALAPPDATA"] = str(state_dir.parent)  # CineSort cree state_dir/CineSort
        # Pre-cree state cible attendu (LOCALAPPDATA/CineSort).
        target_state = state_dir.parent / "CineSort"
        target_state.mkdir(parents=True, exist_ok=True)

    # Si une biblio test est fournie, on ecrit un settings.json minimaliste qui
    # pointe vers elle.
    # [FIGE] B ETAPE 2 fix harness 2026-06-08 : resoudre chemin absolu et
    # detecter les sous-racines (RootA/RootB/... au 1er niveau) pour les
    # enregistrer explicitement dans roots. Sinon le scan rate les films
    # car settings.get('roots') contenait une chaine relative non resolue
    # vs cwd app. [HYPOTHESE] sous-racines = dirs au 1er niveau contenant
    # un sous-dossier 'Movies' ou 'Shows'; fallback : library elle-meme.
    if library is not None and library.exists() and not use_real_localappdata:
        library_abs = library.resolve()
        settings_path = target_state / "settings.json"
        if not settings_path.exists():
            try:
                detected_roots: list[str] = []
                for child in sorted(library_abs.iterdir()):
                    if not child.is_dir():
                        continue
                    if (child / "Movies").is_dir() or (child / "Shows").is_dir():
                        detected_roots.append(str(child))
                if not detected_roots:
                    detected_roots = [str(library_abs)]
                seed = {
                    "root": detected_roots[0],
                    "roots": detected_roots,
                    "state_dir": str(target_state),
                    "tmdb_enabled": False,
                    "auto_check_updates": False,
                    "rest_api_port": 8650,
                }
                settings_path.write_text(
                    json.dumps(seed, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            except OSError as exc:
                print(f"[observe] settings seed echoue: {exc}", file=sys.stderr)

    print(
        f"[observe] [OPERATIONNEL] lancement app mode={mode_label} cdp={cdp_port}",
        file=sys.stderr,
    )
    proc = subprocess.Popen(
        cmd,
        cwd=str(PROJECT_ROOT),
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    summary: dict[str, Any] = {
        "ok": False,
        "mode": mode_label,
        "cdp_port": cdp_port,
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "views": [],
        "views_with_broken_posters": [],
        "console_errors_major": [],
    }

    try:
        if not _wait_for_port("127.0.0.1", cdp_port, timeout_s=headless_timeout):
            summary["error"] = f"port CDP {cdp_port} indisponible apres {headless_timeout}s"
            return summary

        with sync_playwright() as pw:
            browser = pw.chromium.connect_over_cdp(f"http://127.0.0.1:{cdp_port}")
            if not browser.contexts:
                summary["error"] = "aucun contexte CDP retourne par pywebview"
                return summary
            ctx = browser.contexts[0]
            if not ctx.pages:
                summary["error"] = "aucune page CDP retournee par pywebview"
                return summary
            # [GATE 1a iter4] Pas pages[0] : peut etre DevTools quand
            # CINESORT_DEBUG=1. On cible explicitement la page dashboard.
            page = None
            for p in ctx.pages:
                try:
                    if "/dashboard" in (p.url or ""):
                        page = p
                        break
                except Exception:
                    continue
            if page is None:
                page = ctx.pages[0]
            summary["selected_page_url"] = scrub(page.url or "")

            # Attendre que le dashboard ait amorce __APP_READY__ (best effort).
            try:
                page.wait_for_function(
                    "() => window.__APP_READY__ === true || document.readyState === 'complete'",
                    timeout=30_000,
                )
            except Exception as exc:
                summary["app_ready_warning"] = scrub(str(exc))

            for label, hash_target in DASHBOARD_VIEWS:
                view_dir = out_dir / label
                view_dir.mkdir(parents=True, exist_ok=True)
                view_summary: dict[str, Any] = {
                    "label": label,
                    "hash": hash_target,
                    "network": [],
                    "console": [],
                    "csp_violations": [],
                }

                # Listeners locaux a la vue.
                network_records: list[dict[str, Any]] = []
                console_records: list[dict[str, Any]] = []
                csp_violations: list[dict[str, Any]] = []
                # [FIGE 0.7.1] Detection durcie posters : separer image_requests
                # (uniquement requetes vers image.tmdb.org ou /api/poster) du
                # bruit reseau general.
                image_requests: list[dict[str, Any]] = []

                def _is_poster_url(url: str) -> bool:
                    if not url:
                        return False
                    lower = url.lower()
                    return "image.tmdb.org" in lower or "/api/poster" in lower

                def _on_response(resp, _bucket=network_records, _img=image_requests):
                    try:
                        url = scrub(resp.url)
                        rec = {
                            "url": url,
                            "status": resp.status,
                            "method": resp.request.method,
                            "resource_type": resp.request.resource_type,
                        }
                        _bucket.append(rec)
                        # [FIGE 0.7.1] Capture explicite des requetes poster.
                        if _is_poster_url(resp.url):
                            _img.append(
                                {
                                    "url": url,
                                    "status": resp.status,
                                    "ok": 200 <= resp.status < 400,
                                }
                            )
                    except Exception:
                        pass

                def _on_requestfailed(req, _img=image_requests):
                    # [FIGE 0.7.1] Capture echecs reseau (CSP, DNS, etc.).
                    try:
                        if not _is_poster_url(req.url):
                            return
                        failure = ""
                        try:
                            f = req.failure
                            failure = f.get("errorText", "") if isinstance(f, dict) else str(f or "")
                        except Exception:
                            failure = "<unknown>"
                        _img.append(
                            {
                                "url": scrub(req.url),
                                "status": None,
                                "ok": False,
                                "failure": scrub(failure),
                            }
                        )
                    except Exception:
                        pass

                def _on_console(msg, _bucket=console_records, _csp=csp_violations):
                    try:
                        text = scrub(msg.text)
                        entry = {"type": msg.type, "text": text}
                        _bucket.append(entry)
                        # Detection CSP violation heuristique (msg type "error" +
                        # mot-cle CSP / Content Security Policy / Refused to).
                        lower = text.lower()
                        if (
                            "content security policy" in lower
                            or "refused to load" in lower
                            or "violates the following" in lower
                            or "csp" in lower
                        ):
                            _csp.append(entry)
                    except Exception:
                        pass

                def _on_pageerror(err, _bucket=console_records):
                    with contextlib.suppress(Exception):
                        _bucket.append({"type": "pageerror", "text": scrub(str(err))})

                page.on("response", _on_response)
                page.on("requestfailed", _on_requestfailed)
                page.on("console", _on_console)
                page.on("pageerror", _on_pageerror)

                # [FIGE 0.7.1] Instrumentation CSP cote page AVANT navigation :
                # init bucket window.__cspV + listener securitypolicyviolation.
                # Sera relu apres montage de la vue via evaluate().
                csp_init_snippet = r"""
                () => {
                    try {
                        if (!window.__cspV) {
                            window.__cspV = [];
                            window.addEventListener("securitypolicyviolation", (e) => {
                                try {
                                    window.__cspV.push({
                                        blockedURI: e.blockedURI || "",
                                        violatedDirective: e.violatedDirective || "",
                                        sourceFile: e.sourceFile || "",
                                    });
                                } catch (_) {}
                            });
                        }
                    } catch (_) {}
                    return true;
                }
                """
                with contextlib.suppress(Exception):
                    page.evaluate(csp_init_snippet)

                # Verdict par vue [FIGE 0.7.1]
                posters_expected = 0
                posters_rendered = 0
                csp_events_page: list[dict[str, Any]] = []

                try:
                    # Navigation hash : on assigne location.hash et on attend.
                    page.evaluate(
                        "(h) => { window.location.hash = h.replace(/^#/,''); }",
                        hash_target,
                    )
                    # Laisser le router monter la vue + faire ses fetchs.
                    page.wait_for_timeout(2500)

                    # [FIGE 0.7.1] Comptage img poster + background-image +
                    # collecte des CSP events page (window.__cspV).
                    poster_probe_snippet = r"""
                    () => {
                        const isPoster = (u) => {
                            if (!u) return false;
                            return /image\.tmdb\.org|\/api\/poster/i.test(u);
                        };
                        // Tag <img>
                        const imgs = Array.from(document.querySelectorAll("img"));
                        const posterImgs = imgs.filter((i) => isPoster(i.currentSrc || i.src));
                        let renderedImgs = 0;
                        for (const i of posterImgs) {
                            if (i.complete && i.naturalWidth > 0) renderedImgs += 1;
                        }
                        // background-image (heuristique : tout element avec
                        // background-image dont l'URL ressemble a un poster).
                        let bgExpected = 0;
                        let bgRendered = 0;
                        try {
                            const all = document.querySelectorAll("*");
                            for (const el of all) {
                                const bg = getComputedStyle(el).backgroundImage;
                                if (!bg || bg === "none") continue;
                                // Extraire url(...)
                                const m = bg.match(/url\(["']?([^"')]+)["']?\)/);
                                if (!m) continue;
                                const u = m[1];
                                if (!isPoster(u)) continue;
                                bgExpected += 1;
                                // Verifier via Resource Timing si la ressource
                                // a ete chargee (transferSize > 0 ou decodedBodySize > 0).
                                try {
                                    const entries = performance.getEntriesByName(u, "resource");
                                    if (entries && entries.length > 0) {
                                        const e0 = entries[entries.length - 1];
                                        if ((e0.transferSize || 0) > 0
                                            || (e0.decodedBodySize || 0) > 0) {
                                            bgRendered += 1;
                                        }
                                    }
                                } catch (_) {}
                            }
                        } catch (_) {}
                        const csp = Array.isArray(window.__cspV)
                            ? window.__cspV.slice()
                            : [];
                        // Reset pour ne pas accumuler entre vues.
                        try { window.__cspV = []; } catch (_) {}
                        return {
                            posterImgsCount: posterImgs.length,
                            renderedImgsCount: renderedImgs,
                            bgExpected: bgExpected,
                            bgRendered: bgRendered,
                            csp: csp,
                        };
                    }
                    """
                    try:
                        probe = page.evaluate(poster_probe_snippet) or {}
                        posters_expected = int(probe.get("posterImgsCount") or 0) + int(probe.get("bgExpected") or 0)
                        posters_rendered = int(probe.get("renderedImgsCount") or 0) + int(probe.get("bgRendered") or 0)
                        raw_csp = probe.get("csp") or []
                        if isinstance(raw_csp, list):
                            for ev in raw_csp:
                                if isinstance(ev, dict):
                                    csp_events_page.append(
                                        {
                                            "blockedURI": scrub(str(ev.get("blockedURI") or "")),
                                            "violatedDirective": str(ev.get("violatedDirective") or ""),
                                            "sourceFile": scrub(str(ev.get("sourceFile") or "")),
                                        }
                                    )
                    except Exception as exc:
                        view_summary["poster_probe_error"] = scrub(str(exc))

                    # Screenshot complet de la fenetre. [OPERATIONNEL]
                    ss_path = view_dir / "screenshot.png"
                    try:
                        page.screenshot(path=str(ss_path), full_page=True)
                        view_summary["screenshot"] = str(ss_path.relative_to(out_dir))
                    except Exception as exc:
                        view_summary["screenshot_error"] = scrub(str(exc))

                except Exception as exc:
                    view_summary["nav_error"] = scrub(str(exc))
                finally:
                    # Detacher les listeners pour eviter cross-contamination.
                    try:
                        page.remove_listener("response", _on_response)
                        page.remove_listener("requestfailed", _on_requestfailed)
                        page.remove_listener("console", _on_console)
                        page.remove_listener("pageerror", _on_pageerror)
                    except Exception:
                        pass

                # Persistance des journaux par vue.
                try:
                    (view_dir / "network.json").write_text(
                        json.dumps(
                            {
                                "fetches": network_records,
                                "violations_csp_heuristique": csp_violations,
                                "image_requests": image_requests,
                            },
                            indent=2,
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    view_summary["network_write_error"] = scrub(str(exc))

                try:
                    log_lines = []
                    for rec in console_records:
                        log_lines.append(f"[{rec.get('type', '?')}] {rec.get('text', '')}")
                    (view_dir / "console.log").write_text(
                        "\n".join(log_lines) + ("\n" if log_lines else ""),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    view_summary["console_write_error"] = scrub(str(exc))

                try:
                    # [FIGE 0.7.1] On combine les violations CSP heuristiques
                    # (depuis console.log) et les events reels captures via
                    # window.__cspV (securitypolicyviolation listener).
                    (view_dir / "violations_csp.json").write_text(
                        json.dumps(
                            {
                                "console_heuristic": csp_violations,
                                "events_page": csp_events_page,
                            },
                            indent=2,
                            ensure_ascii=False,
                        ),
                        encoding="utf-8",
                    )
                except OSError as exc:
                    view_summary["csp_write_error"] = scrub(str(exc))

                # [FIGE 0.7.1] Verdict par vue durci.
                posters_failed = max(0, posters_expected - posters_rendered)
                # Considere aussi comme failed les image_requests en echec
                # (status >= 400 ou failure renseigne) — peuvent porter sur des
                # URLs non encore rendues (preload, retry) mais sont quand meme
                # des signaux. On en augmente le compte sans doubler les img.
                failed_requests = [
                    r for r in image_requests if (r.get("ok") is False) or (r.get("status") and int(r["status"]) >= 400)
                ]
                # Raisons collectees pour traçabilite.
                reasons: list[str] = []
                for ev in csp_events_page:
                    d = ev.get("violatedDirective", "")
                    b = ev.get("blockedURI", "")
                    if d or b:
                        reasons.append(f"CSP {d} blockedURI={b}")
                for v in csp_violations:
                    t = v.get("text", "")
                    if t:
                        reasons.append(f"console: {t[:200]}")
                for fr in failed_requests:
                    reasons.append(
                        f"image {fr.get('url', '')} status={fr.get('status')} failure={fr.get('failure', '')}"
                    )

                if posters_expected == 0:
                    verdict = "POSTERS_ABSENTS"
                elif posters_failed == 0 and not failed_requests:
                    verdict = "POSTERS_OK"
                else:
                    verdict = "POSTERS_KO"

                view_summary["posters_expected"] = posters_expected
                view_summary["posters_rendered"] = posters_rendered
                view_summary["posters_failed"] = posters_failed
                view_summary["csp_violations"] = csp_events_page
                view_summary["image_requests"] = image_requests
                view_summary["verdict"] = verdict
                if reasons and verdict == "POSTERS_KO":
                    view_summary["reasons"] = reasons[:25]

                # [FIGE] Backward compat : on garde l'ancien flag
                # broken_posters_detected pour ne pas casser d'eventuels
                # consommateurs externes du summary.json.
                broken_posters = verdict == "POSTERS_KO"
                view_summary["broken_posters_detected"] = broken_posters
                if broken_posters:
                    summary["views_with_broken_posters"].append(label)

                # Erreurs majeures (type "error" ou pageerror).
                for rec in console_records:
                    if rec.get("type") in {"error", "pageerror"}:
                        line = f"{label}: [{rec['type']}] {rec.get('text', '')}"
                        summary["console_errors_major"].append(line)

                view_summary["counts"] = {
                    "network": len(network_records),
                    "console": len(console_records),
                    "csp_violations": len(csp_violations),
                    "csp_events_page": len(csp_events_page),
                    "image_requests": len(image_requests),
                }
                summary["views"].append(view_summary)

            browser.close()
            summary["ok"] = True
    except Exception as exc:
        summary["error"] = scrub(str(exc))
    finally:
        # Arret propre du process app.
        try:
            proc.terminate()
            try:
                proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                proc.kill()
        except Exception:
            pass

    summary["ended_at"] = datetime.now().isoformat(timespec="seconds")
    return summary


# ---------------------------------------------------------------------------
# Mode desktop (capture fenetre native via mss/PID handle) — methode standardisee
# ---------------------------------------------------------------------------


def observe_desktop_window(out_dir: Path, pid_hint: int | None = None) -> dict[str, Any]:
    """Capture la fenetre native CineSort via mss (fallback monitor 0 si pas de
    PID handle). [HYPOTHESE] : sans handle natif, on capture le monitor principal.

    Methode standardisee documentee :
        - prefere pywebview debug=True + devtools (mode dev) qui expose CDP ;
        - sinon fallback mss capture sur la fenetre via PID handle Win32
          (FindWindowEx + GetWindowRect) ; si indisponible, monitor 0.
    """
    result: dict[str, Any] = {"ok": False}
    try:
        import mss  # type: ignore
    except ImportError:
        result["error"] = "mss non installe (pip install mss)"
        return result

    desktop_dir = out_dir / "_desktop_capture"
    desktop_dir.mkdir(parents=True, exist_ok=True)

    try:
        with mss.mss() as sct:
            monitor = sct.monitors[0]  # entier desktop virtuel
            shot = sct.grab(monitor)
            from mss.tools import to_png  # type: ignore

            png_path = desktop_dir / "desktop_full.png"
            to_png(shot.rgb, shot.size, output=str(png_path))
            result["ok"] = True
            result["screenshot"] = str(png_path)
    except Exception as exc:
        result["error"] = scrub(str(exc))

    if pid_hint is not None:
        result["pid_hint"] = pid_hint
    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="observe.py",
        description="Observation reutilisable CineSort (capture multi-vues).",
    )
    parser.add_argument(
        "--library",
        type=Path,
        default=None,
        help="Chemin biblio test (seed settings.json). Optionnel.",
    )
    parser.add_argument(
        "--modes",
        type=str,
        default="dashboard",
        help="Modes separes par virgule : dashboard,desktop,both.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Dossier de sortie. Defaut : docs/internal/observe/<timestamp>/.",
    )
    parser.add_argument(
        "--timestamp",
        type=str,
        default=None,
        help="Timestamp YYYY-MM-DD_HHMMSS (sinon genere maintenant).",
    )
    parser.add_argument(
        "--cdp-port",
        type=int,
        default=DEFAULT_CDP_PORT,
        help=f"Port CDP (defaut {DEFAULT_CDP_PORT}).",
    )
    parser.add_argument(
        "--prefer-dev",
        action="store_true",
        help="Force `python app.py --dev` meme si dist/CineSort.exe existe.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Ne lance pas l'app, ecrit juste la structure + un manifeste. "
            "Avec --fresh, SIMULE la gate : freshness_gate.json liste ce qui "
            "serait supprime (would_delete_run_ids / would_delete_run_dirs) "
            "sans rien detruire ni tuer."
        ),
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Active le GATE FRAICHEUR avant lancement : "
            "(a) force python app.py --dev, "
            "(b) reset DB+runs du perimetre --library (backup auto : DB + "
            "sidecars -wal/-shm, et copie des dossiers de run), "
            "(c) purge WebView2 userdata. "
            "Voir docs/internal/observe_protocol.md."
        ),
    )
    parser.add_argument(
        "--use-local-state",
        action="store_true",
        help=(
            "Avec --fresh : agit sur %%LOCALAPPDATA%%\\CineSort reel "
            "au lieu du state isole observe.py. "
            "ATTENTION : ne touche que le scope test_library, mais les "
            "donnees utilisateur reelles sont preservees par defaut."
        ),
    )
    return parser.parse_args(argv)


def _resolve_modes(value: str) -> set[str]:
    modes = {m.strip().lower() for m in (value or "").split(",") if m.strip()}
    if "both" in modes:
        modes.discard("both")
        modes.update({"dashboard", "desktop"})
    return modes


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)

    ts = args.timestamp or datetime.now().strftime("%Y-%m-%d_%H%M%S")
    out_dir = args.output or (DEFAULT_OUTPUT_PARENT / ts)
    out_dir.mkdir(parents=True, exist_ok=True)

    modes = _resolve_modes(args.modes) or {"dashboard"}
    print(f"[observe] [OPERATIONNEL] timestamp={ts} out={out_dir} modes={sorted(modes)}", file=sys.stderr)

    manifest: dict[str, Any] = {
        "timestamp": ts,
        "out_dir": str(out_dir),
        "modes": sorted(modes),
        "library": str(args.library) if args.library else None,
        "cdp_port": args.cdp_port,
        "dry_run": bool(args.dry_run),
        "fresh": bool(args.fresh),
        "use_local_state": bool(args.use_local_state),
    }

    summary: dict[str, Any] = {
        "manifest": manifest,
        "dashboard": None,
        "desktop": None,
        "freshness_gate": None,
    }

    # GATE FRAICHEUR : pre-etapes avant lancement (etape 5 du diag).
    # `--dry-run` SIMULE la gate (rapport `would_delete_*`) au lieu de la sauter :
    # sans cela, `--fresh` n'etait pas previsualisable — soit on ne voyait rien,
    # soit on detruisait pour de vrai.
    if args.fresh:
        gate_report = run_freshness_gate(
            out_dir=out_dir,
            library=args.library,
            use_local_state=args.use_local_state,
            dry_run=bool(args.dry_run),
        )
        summary["freshness_gate"] = gate_report
        if not args.dry_run:
            # Force le mode dev dans l'env du subprocess app (cf. _detect_app_command).
            os.environ["CINESORT_OBSERVE_FORCE_DEV"] = "1"

    if args.dry_run:
        (out_dir / "manifest.json").write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        print("[observe] [OPERATIONNEL] dry-run termine.", file=sys.stderr)
        return 0

    if "dashboard" in modes:
        summary["dashboard"] = observe_dashboard(
            out_dir=out_dir,
            library=args.library,
            cdp_port=args.cdp_port,
            prefer_exe=not args.prefer_dev,
        )

    if "desktop" in modes:
        summary["desktop"] = observe_desktop_window(out_dir=out_dir)

    # Tail cinesort.log (state isole d'abord, sinon LOCALAPPDATA standard).
    candidates = [
        out_dir / "_state" / "CineSort" / "logs" / "cinesort.log",
        Path(os.environ.get("LOCALAPPDATA", ".")) / "CineSort" / "logs" / "cinesort.log",
    ]
    tail_text = ""
    for c in candidates:
        if c.is_file():
            tail_text = _scrub_log_tail(c, n_lines=50)
            summary["cinesort_log_source"] = str(c)
            break
    (out_dir / "cinesort.log.tail.txt").write_text(
        tail_text or "<aucun log cinesort.log trouve>",
        encoding="utf-8",
    )

    (out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    # Resume console.
    dash = summary.get("dashboard") or {}
    if isinstance(dash, dict):
        print(
            f"[observe] [OPERATIONNEL] dashboard ok={dash.get('ok')} "
            f"views={len(dash.get('views') or [])} "
            f"broken_posters={dash.get('views_with_broken_posters')}",
            file=sys.stderr,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

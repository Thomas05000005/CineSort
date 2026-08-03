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
    b. reset etat derive scope test_library (DB + runs/tri_films_*),
       protege les donnees utilisateur reelles (`\\\\OMV\\Media` etc.) ;
    c. purge WebView2 userdata (`webview/EBWebView` du LOCALAPPDATA cible).

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
import socket
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
_RE_USER_HOME = re.compile(r"C:\\\\Users\\\\[^\\\\\"]+", re.IGNORECASE)
_RE_USER_HOME_FW = re.compile(r"C:/Users/[^/\"]+", re.IGNORECASE)


def scrub(text: str) -> str:
    """Scrubbe les valeurs sensibles d'une chaine. Sur."""
    if not text:
        return text
    out = text
    out = _RE_BEARER.sub(r"\1<REDACTED>", out)
    out = _RE_NTOKEN_QS.sub(r"\1<REDACTED>", out)
    out = _RE_TOKEN_FIELD.sub(r"\1<REDACTED>\2", out)
    out = _RE_USER_HOME.sub(r"C:\\Users\\<USER>", out)
    out = _RE_USER_HOME_FW.sub("C:/Users/<USER>", out)
    return out


# ---------------------------------------------------------------------------
# Helpers process / port
# ---------------------------------------------------------------------------


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


def _purge_webview2_userdata(localappdata: Path) -> dict[str, Any]:
    """Supprime `<LOCALAPPDATA>\\CineSort\\webview\\` (cache WebView2 evergreen).

    Idempotent : si le dossier n'existe pas, retourne ok=True purged=False.
    Ne touche PAS aux autres dossiers (db, runs, logs, settings.json).

    [HARNESS DIAG 2026-06-08 etape 2c+5] traite H4 staleness userdata.
    """
    target = localappdata / "CineSort" / "webview"
    result: dict[str, Any] = {
        "ok": True,
        "target": str(target),
        "purged": False,
        "bytes_freed": 0,
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
        # Best effort kill des process WebView2 lies (silencieux).
        with contextlib.suppress(FileNotFoundError, subprocess.TimeoutExpired, OSError):
            subprocess.run(
                ["taskkill", "/F", "/IM", "msedgewebview2.exe"],
                capture_output=True,
                timeout=10,
                check=False,
            )
        # Suppression recursive.
        import shutil

        shutil.rmtree(target, ignore_errors=True)
        result["purged"] = not target.exists()
        if not result["purged"]:
            result["ok"] = False
            result["error"] = "purge incomplete (handles ouverts ?)"
    except Exception as exc:
        result["ok"] = False
        result["error"] = scrub(str(exc))
    return result


def _reset_test_library_state(
    localappdata: Path,
    library: Path | None,
) -> dict[str, Any]:
    """Reset etat derive scope test_library.

    Cible :
        - runs `tri_films_*` qui referencent test_library
        - lignes DB SQLite (runs/quality_reports/probe_cache/...) liees

    PROTEGE :
        - donnees utilisateur reelles (\\\\OMV\\Media, etc.) preservees ;
        - settings.json / omdb_cache.json / tmdb_cache.json non touches ;
        - backup `cinesort.sqlite.bak_BEFORE_FRESH_<ts>` cree avant tout DELETE.

    [HARNESS DIAG 2026-06-08 etape 2b+5] traite H2 staleness DB/runs derives.

    Si la DB n'existe pas (premier run, isolation propre) -> no-op ok=True.
    Si la library n'est pas test_library (ou non resolvable) -> skip reset DB,
    purge seulement les runs orphelins eventuels.
    """
    result: dict[str, Any] = {
        "ok": True,
        "scope": str(library) if library else None,
        "runs_deleted": 0,
        "db_rows_deleted": {},
        "backup": None,
        "skipped_reasons": [],
    }
    db_path = localappdata / "CineSort" / "db" / "cinesort.sqlite"
    runs_dir = localappdata / "CineSort" / "runs"

    if not db_path.is_file() and not runs_dir.is_dir():
        result["skipped_reasons"].append("etat derive absent (premier run)")
        return result

    # Resolution scope : seul un chemin contenant 'test_library' est reset.
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

    # Etape DB.
    if db_path.is_file() and scope_marker:
        try:
            import sqlite3

            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            backup = db_path.with_suffix(f".sqlite.bak_BEFORE_FRESH_{ts}")
            import shutil

            shutil.copy2(db_path, backup)
            result["backup"] = str(backup)
            conn = sqlite3.connect(str(db_path))
            try:
                cur = conn.cursor()
                # 1. Identifier les run_ids lies a test_library
                # (run.root LIKE OU plan.jsonl evoque le scope).
                cur.execute(
                    "SELECT run_id FROM runs WHERE LOWER(root) LIKE ?",
                    ("%test_library%",),
                )
                run_ids = [r[0] for r in cur.fetchall()]
                deleted: dict[str, int] = {}
                if run_ids:
                    placeholders = ",".join("?" for _ in run_ids)
                    # Inventorier tables avec colonne run_id.
                    cur.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    tables = [r[0] for r in cur.fetchall()]
                    for tbl in tables:
                        try:
                            cur.execute(f"PRAGMA table_info({tbl})")
                            cols = [c[1] for c in cur.fetchall()]
                            if "run_id" in cols:
                                cur.execute(
                                    f"DELETE FROM {tbl} WHERE run_id IN ({placeholders})",
                                    run_ids,
                                )
                                if cur.rowcount > 0:
                                    deleted[tbl] = cur.rowcount
                        except sqlite3.Error:
                            continue
                # probe_cache : DELETE par path LIKE
                try:
                    cur.execute(
                        "DELETE FROM probe_cache WHERE LOWER(path) LIKE ?",
                        ("%test_library%",),
                    )
                    if cur.rowcount > 0:
                        deleted["probe_cache_by_path"] = cur.rowcount
                except sqlite3.Error:
                    pass
                conn.commit()
                result["db_rows_deleted"] = deleted
                result["run_ids_scope"] = run_ids
            finally:
                conn.close()
        except Exception as exc:
            result["ok"] = False
            result["error_db"] = scrub(str(exc))

    # Etape runs/.
    if runs_dir.is_dir() and scope_marker:
        try:
            import shutil

            deleted_runs = 0
            for run_dir in runs_dir.glob("tri_films_*"):
                if not run_dir.is_dir():
                    continue
                # Detecter les runs lies a test_library via plan.jsonl ou ui_log.txt.
                marker_found = False
                for marker_file in ("plan.jsonl", "ui_log.txt", "summary.txt"):
                    f = run_dir / marker_file
                    if not f.is_file():
                        continue
                    try:
                        # Lecture economique : 64 KB suffisent pour reperer le marker.
                        with open(f, "rb") as fh:
                            chunk = fh.read(64 * 1024)
                        if b"test_library" in chunk.lower():
                            marker_found = True
                            break
                    except OSError:
                        continue
                if marker_found:
                    try:
                        shutil.rmtree(run_dir, ignore_errors=True)
                        if not run_dir.exists():
                            deleted_runs += 1
                    except OSError:
                        pass
            result["runs_deleted"] = deleted_runs
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


def _kill_residual_processes() -> dict[str, Any]:
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

    Returns:
        dict { ok: bool, killed: { exe: bool, ... }, errors: [...] }
    """
    result: dict[str, Any] = {
        "ok": True,
        "killed": {},
        "errors": [],
    }
    # Liste figee : EXE livrable + WebView2. PAS python.exe (suicide-risk).
    targets = ["CineSort.exe", "msedgewebview2.exe"]
    for exe in targets:
        try:
            cp = subprocess.run(
                ["taskkill", "/F", "/IM", exe],
                capture_output=True,
                timeout=10,
                check=False,
            )
            # rc==0 : au moins un process tue ; rc==128 : "process not found" (cas normal).
            result["killed"][exe] = cp.returncode == 0
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            result["killed"][exe] = False
            result["errors"].append(f"{exe}: {scrub(str(exc))}")
    return result


def run_freshness_gate(
    out_dir: Path,
    library: Path | None,
    use_local_state: bool,
) -> dict[str, Any]:
    """Orchestre les pre-etapes freshness avant lancement observe.

    [OPERATIONNEL] s'execute si l'utilisateur a fourni `--fresh`.

    Sequence :
        A0. kill process residuels (CineSort.exe + msedgewebview2.exe).
        A.  H1 staleness EXE (informatif + force dev mode).
        B.  H2 reset DB + runs scope test_library.
        C.  H4 purge WebView2 userdata.

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
        "scope_note": scope_note,
        "localappdata_target": str(local_appdata),
        "library": str(library) if library else None,
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    print(
        f"[observe.fresh] [OPERATIONNEL] gate localappdata={local_appdata} library={library}",
        file=sys.stderr,
    )

    # Pre-etape A0 : kill process residuels (CineSort.exe + msedgewebview2.exe).
    # [HARNESS REMEDIATION ITER8B C1 2026-06-09] Evite l'incident inter-runs
    # documente dans BILAN_ITER8B_2026-06-08.md Sections 2.1+3.5 :
    # process lock sur WebView2 userdata residuel -> summary.json + screenshots
    # ABSENTS sur les 17 vues (capture ITER8_NONREG_GLOBAL initiale).
    report["a0_kill_residual"] = _kill_residual_processes()
    # Pre-etape A : EXE staleness check (informatif + force dev mode plus tard).
    report["h1_exe"] = _rebuild_exe_if_needed()
    # Pre-etape B : reset DB+runs scope test_library.
    report["h2_state"] = _reset_test_library_state(local_appdata, library)
    if not report["h2_state"].get("ok"):
        report["ok"] = False
    # Pre-etape C : purge WebView2 userdata.
    report["h4_webview2"] = _purge_webview2_userdata(local_appdata)
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

    print(
        f"[observe.fresh] [OPERATIONNEL] gate ok={report['ok']} "
        f"runs_del={report['h2_state'].get('runs_deleted')} "
        f"db_del={sum(report['h2_state'].get('db_rows_deleted', {}).values())} "
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
        help="Ne lance pas l'app, ecrit juste la structure + un manifeste.",
    )
    parser.add_argument(
        "--fresh",
        action="store_true",
        help=(
            "Active le GATE FRAICHEUR avant lancement : "
            "(a) force python app.py --dev, "
            "(b) reset DB+runs scope test_library (backup auto), "
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
    if args.fresh and not args.dry_run:
        gate_report = run_freshness_gate(
            out_dir=out_dir,
            library=args.library,
            use_local_state=args.use_local_state,
        )
        summary["freshness_gate"] = gate_report
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

"""Runtime and run-store helpers for the pywebview API facade.

CineSortApi remains the public bridge exposed to the stable UI. This module
owns the in-memory run registry, the state_dir-scoped infra cache, and the
lookup helpers that bind runtime runs back to persisted rows.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import platform
import re
import sys
import time
import uuid
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import cinesort.infra.state as state
from cinesort.app import JobRunner
from cinesort.app.move_reconciliation import reconcile_at_boot
from cinesort.infra.db import SQLiteStore, db_path_for_state_dir
from cinesort.ui.api.docs_whitelist import DOCS_WHITELIST, get_doc_path, list_doc_ids
from cinesort.ui.api.notifications_support import add_notification

_logger = logging.getLogger(__name__)

# CR-1 audit QA 20260429 : la reconciliation au boot ne doit s'executer qu'une
# seule fois par state_dir (la 1re creation de l'infra). Cache memoire pour
# la session courante, reset si la CineSortApi est recree (tests).
_RECONCILED_STATE_DIRS: set = set()


def reset_reconciliation_cache_for_tests() -> None:
    """Permet aux tests d'isoler la reconciliation entre runs."""
    _RECONCILED_STATE_DIRS.clear()


def state_dir_key(state_dir: Path) -> str:
    try:
        return str(state_dir.resolve()).lower()
    except (ImportError, OSError, TypeError, ValueError):
        return str(state_dir).lower()


def run_paths_for(state_dir: Path, run_id: str, *, ensure_exists: bool) -> state.RunPaths:
    run_dir = state_dir / "runs" / f"tri_films_{run_id}"
    if ensure_exists:
        run_dir.mkdir(parents=True, exist_ok=True)
    return state.RunPaths(
        run_id=run_id,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def _publish_integrity_notification_if_any(api: Any, store: SQLiteStore) -> None:
    """V2-11 audit QA 20260504 : publie une notification UI persistante si
    l'integrity_check au boot a detecte une corruption.

    Trois cas distincts produisent un titre et un niveau differents :
    - "restored" : DB restauree avec succes (info, rassurant).
    - "restore_failed" : restore tente mais echoue (error, action requise).
    - "corrupt_no_backup" : aucun backup disponible (error, action requise).

    L'API `add_notification` du module notifications_support cree la
    notification dans le NotificationStore en memoire (cap 200), visible
    dans le notification center du dashboard au prochain refresh.

    Tolerant : toute erreur d'import ou de publication est ignoree pour ne
    pas bloquer le boot.
    """
    event = getattr(store, "integrity_event", None)
    if not event or not isinstance(event, dict):
        return
    status = str(event.get("status") or "")
    if not status:
        return
    raw = str(event.get("raw") or "")
    backup_used = event.get("backup_used")
    if status == "restored":
        title = "Base de donnees restauree automatiquement"
        body = (
            "Une corruption a ete detectee au demarrage et la base a ete restauree "
            f"depuis le backup le plus recent. Detail : {raw[:200]}"
        )
        level = "warning"
    elif status == "restore_failed":
        title = "Echec restauration base de donnees"
        body = (
            "Corruption detectee au demarrage. La tentative de restauration "
            f"automatique depuis le backup a echoue. Detail : {raw[:200]}"
        )
        level = "error"
    elif status == "corrupt_no_backup":
        title = "Base de donnees corrompue"
        body = (
            "Une corruption a ete detectee au demarrage mais aucun backup n'est "
            "disponible. Verifiez vos sauvegardes manuelles ou contactez le support. "
            f"Detail : {raw[:200]}"
        )
        level = "error"
    else:
        return

    try:
        add_notification(
            api,
            event_type="db_integrity",
            title=title,
            body=body,
            level=level,
            category="system",
            data={
                "integrity_status": status,
                "raw": raw,
                "backup_used": backup_used,
                "ts": event.get("ts"),
            },
        )
        _logger.warning("V2-11: notification UI publiee (%s): %s", status, title)
    except Exception as exc:
        _logger.warning("V2-11: publication notification echouee: %s", exc)


def get_or_create_infra(
    api: Any,
    state_dir: Path,
    *,
    env_truthy_fn: Callable[[str], bool],
) -> Tuple[SQLiteStore, JobRunner]:
    key = state_dir_key(state_dir)

    def _sqlite_debug(msg: str) -> None:
        if not env_truthy_fn("CINESORT_DEBUG"):
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            api._append_text(state_dir / "debug_sqlite.log", f"[{ts}] {msg}\n")
        except (OSError, TypeError, ValueError):
            return

    with api._runs_lock:
        existing = api._infra_by_state_dir.get(key)
        if existing:
            store_existing, _runner_existing = existing
            version = store_existing.initialize()
            _sqlite_debug(f"SQLite initialized at {store_existing.db_path}, schema version={version}")
            return existing

    store = SQLiteStore(
        db_path_for_state_dir(state_dir),
        busy_timeout_ms=8000,
        debug_logger=_sqlite_debug,
    )
    version = store.initialize()
    _sqlite_debug(f"SQLite initialized at {store.db_path}, schema version={version}")

    # V2-11 audit QA 20260504 : si l'integrity_check a detecte une corruption,
    # publier une notification UI persistante (consommee par le notification
    # center au prochain affichage). Independant de la reconciliation, car
    # peut arriver meme sans pending_moves.
    _publish_integrity_notification_if_any(api, store)

    # CR-1 audit QA 20260429 : reconciliation des moves orphelins au 1er boot
    # de chaque state_dir. Si un crash a interrompu un apply precedent, on
    # examine apply_pending_moves et on classifie/cleanup chaque entree.
    if key not in _RECONCILED_STATE_DIRS:
        try:
            notify = getattr(api, "_notify", None)
            report = reconcile_at_boot(store, notify=notify)
            if report.get("examined", 0) > 0:
                _logger.info(
                    "reconcile_at_boot: %d entree(s) examinee(s), %d completed, %d rolled_back, %d duplicated, %d lost",
                    report["examined"],
                    report.get("completed", 0),
                    report.get("rolled_back", 0),
                    len(report.get("duplicated", [])),
                    len(report.get("lost", [])),
                )
        except Exception as exc:
            _logger.warning("reconcile_at_boot: erreur ignoree (boot continue): %s", exc)
        # R5-CRASH-1 fix : nettoyer les runs orphelins (status='RUNNING' sans
        # processus actif). Si l'app a crash mid-scan, le run reste RUNNING
        # en BDD pour toujours. On les marque FAILED avec message de crash.
        try:
            with store._managed_conn() as conn:  # type: ignore[attr-defined]
                cursor = conn.execute(
                    "SELECT run_id FROM runs WHERE status = ?",
                    ("RUNNING",),
                )
                orphan_run_ids = [row[0] for row in cursor.fetchall()]
                if orphan_run_ids:
                    conn.execute(
                        "UPDATE runs SET status = ?, error_message = COALESCE(error_message, ?) WHERE status = ?",
                        ("FAILED", "Crash detecte au boot (run orphelin)", "RUNNING"),
                    )
                    _logger.warning(
                        "Boot cleanup: %d run(s) orphelin(s) marques FAILED: %s",
                        len(orphan_run_ids),
                        ", ".join(orphan_run_ids[:5]),
                    )
        except Exception as exc:
            _logger.warning("orphan runs cleanup: ignored (%s)", exc)
        _RECONCILED_STATE_DIRS.add(key)

    def _jobrunner_debug(msg: str) -> None:
        if not env_truthy_fn("CINESORT_DEBUG"):
            return
        ts = time.strftime("%Y-%m-%d %H:%M:%S")
        try:
            api._append_text(state_dir / "debug_jobrunner.log", f"[{ts}] {msg}\n")
        except (OSError, TypeError, ValueError):
            return

    runner = JobRunner(store, debug_logger=_jobrunner_debug)

    with api._runs_lock:
        already = api._infra_by_state_dir.get(key)
        if already:
            return already
        api._infra_by_state_dir[key] = (store, runner)
        return store, runner


def get_run(api: Any, run_id: str) -> Optional[Any]:
    with api._runs_lock:
        purge_terminal_runs_locked(api, max_keep=getattr(api, "_max_terminal_runs_in_memory", 50))
        return api._runs.get(run_id)


def purge_terminal_runs_locked(api: Any, *, max_keep: int) -> None:
    terminal: List[Tuple[float, str]] = []
    for rid, rs in api._runs.items():
        if rs.running:
            continue
        snap = rs.runner.get_status(rid)
        if snap and not snap.done:
            continue
        ts = float((snap.ended_ts if snap else None) or rs.started_ts or 0.0)
        terminal.append((ts, rid))

    safe_max_keep = max(1, int(max_keep or 1))
    if len(terminal) <= safe_max_keep:
        return

    terminal.sort(key=lambda item: item[0], reverse=True)
    keep = {rid for _, rid in terminal[:safe_max_keep]}
    for _, rid in terminal[safe_max_keep:]:
        if rid not in keep:
            api._runs.pop(rid, None)


def generate_run_id() -> str:
    return time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"


def generate_unique_run_id(api: Any, store: SQLiteStore) -> str:
    for _ in range(100):
        run_id = generate_run_id()
        with api._runs_lock:
            if run_id in api._runs:
                continue
        if store.run.get_run(run_id) is not None:
            continue
        return run_id
    # fallback ultime : uuid4 pour eviter blocage definitif
    return f"{generate_run_id()}-{uuid.uuid4().hex[:8]}"


def find_run_row(api: Any, run_id: str) -> Optional[Tuple[Dict[str, Any], SQLiteStore]]:
    with api._runs_lock:
        stores = [store for store, _runner in api._infra_by_state_dir.values()]
    for store in stores:
        row = store.run.get_run(run_id)
        if row:
            return row, store

    default_store, _runner = api._get_or_create_infra(api._state_dir)
    row = default_store.run.get_run(run_id)
    if row:
        return row, default_store
    return None


# =========================================================================
# Phase 4 / spec 12-aide.md : 4 endpoints "Aide".
# =========================================================================

# Regex strip ANSI : sequences ESC[...m, ESC[...K, ESC[...J, etc.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

# Cap defensif sur le nombre de lignes retournees par get_recent_logs.
_MAX_LOG_LINES = 1000

# Cap defensif sur la taille en bytes lue depuis le log (10 MB -> ~ 50k lignes).
_MAX_LOG_BYTES = 10 * 1024 * 1024


def _strip_ansi(text: str) -> str:
    """Supprime les sequences d'echappement ANSI (couleurs, mouvement curseur)."""
    return _ANSI_RE.sub("", text)


def _repo_root() -> Path:
    """Retourne la racine du repo (parent de `cinesort/`)."""
    return Path(__file__).resolve().parents[3]


def _logs_dir() -> Path:
    """Chemin standard du dossier logs (%LOCALAPPDATA%/CineSort/logs)."""
    base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    return Path(base) / "CineSort" / "logs"


def _settings_file_path(api: Any) -> Path:
    """Chemin du fichier settings.json pour le state_dir courant."""
    state_dir = Path(getattr(api, "_state_dir", state.default_state_dir()))
    return state_dir / "settings.json"


def _safe_isoformat_now() -> str:
    """Retourne le timestamp ISO 8601 UTC actuel (sans micro-secondes)."""
    return _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()


def _safe_read_settings_for_diag(api: Any) -> Dict[str, Any]:
    """Lit les settings de facon defensive pour le diagnostic.

    On evite tout import top-level pour ne pas creer de cycle ; on appelle
    directement le module settings_support si disponible, sinon dict vide.
    """
    try:
        from cinesort.ui.api import settings_support as _ss

        return _ss.read_settings(Path(getattr(api, "_state_dir", state.default_state_dir())))
    except Exception as exc:
        _logger.debug("diag: read_settings echec ignore: %s", exc)
        return {}


def _detect_probe_versions(api: Any, settings: Dict[str, Any]) -> Tuple[str, str]:
    """Retourne (ffprobe_version, mediainfo_version) ou chaines vides."""
    try:
        from cinesort.infra.probe import detect_probe_tools

        state_dir = Path(getattr(api, "_state_dir", state.default_state_dir()))
        result = detect_probe_tools(
            settings=settings or {},
            state_dir=state_dir,
            check_versions=True,
            scan_winget_packages=False,
        )
        tools = result.get("tools", {}) if isinstance(result, dict) else {}
        ff = str((tools.get("ffprobe") or {}).get("version") or "")
        mi = str((tools.get("mediainfo") or {}).get("version") or "")
        return ff, mi
    except Exception as exc:
        _logger.debug("diag: detect_probe_tools echec ignore: %s", exc)
        return "", ""


def _integration_configured(value: Any) -> bool:
    """Indique si une integration semble configuree (champ non vide)."""
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return bool(str(value).strip())


def _build_integrations_status(settings: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Retourne un mapping {integration: {configured: bool}} pour le diag.

    On ne fait PAS de test reseau ici (couteux + bloquant). Seulement une
    inspection des champs settings (presence d'URL ou de cle).
    """
    s = settings or {}
    return {
        "tmdb": {"configured": _integration_configured(s.get("tmdb_api_key"))},
        "jellyfin": {
            "configured": _integration_configured(s.get("jellyfin_url"))
            and _integration_configured(s.get("jellyfin_api_key")),
            "url": str(s.get("jellyfin_url") or ""),
        },
        "plex": {
            "configured": _integration_configured(s.get("plex_url")) and _integration_configured(s.get("plex_token")),
            "url": str(s.get("plex_url") or ""),
        },
        "radarr": {
            "configured": _integration_configured(s.get("radarr_url"))
            and _integration_configured(s.get("radarr_api_key")),
            "url": str(s.get("radarr_url") or ""),
        },
        "omdb": {"configured": _integration_configured(s.get("omdb_api_key"))},
    }


def _read_build_date() -> str:
    """Date de build approximative : mtime du fichier VERSION en ISO date."""
    try:
        version_file = _repo_root() / "VERSION"
        if version_file.exists():
            mtime = version_file.stat().st_mtime
            return _dt.datetime.fromtimestamp(mtime, tz=_dt.timezone.utc).date().isoformat()
    except (OSError, ValueError):
        pass
    return ""


def _library_counts(api: Any) -> Tuple[int, int]:
    """Retourne (total_films, total_scored) ou (0, 0) si indispo.

    Cf spec 12-aide.md : `lib_total` et `lib_scored` pour la section diagnostic.
    """
    try:
        state_dir = Path(getattr(api, "_state_dir", state.default_state_dir()))
        # Volontairement defensif : pas de creation d'infra si elle n'existe pas
        with api._runs_lock:
            existing = api._infra_by_state_dir.get(state_dir_key(state_dir))
        if not existing:
            return 0, 0
        store, _runner = existing
        # Compter films distincts dans library_items + ceux ayant un score
        try:
            with store._managed_conn() as conn:  # type: ignore[attr-defined]
                cur = conn.execute("SELECT COUNT(*) AS cnt FROM library_items")
                row = cur.fetchone()
                lib_total = int((row["cnt"] if row else 0) or 0)
                cur = conn.execute("SELECT COUNT(DISTINCT library_item_id) AS cnt FROM quality_reports")
                row = cur.fetchone()
                lib_scored = int((row["cnt"] if row else 0) or 0)
                return lib_total, lib_scored
        except Exception as exc:
            _logger.debug("diag: library_counts SQL echec ignore: %s", exc)
            return 0, 0
    except Exception as exc:
        _logger.debug("diag: library_counts echec ignore: %s", exc)
        return 0, 0


def _last_run_info(api: Any) -> Tuple[str, str]:
    """Retourne (last_run_id, last_run_status) ou ("", "")."""
    try:
        state_dir = Path(getattr(api, "_state_dir", state.default_state_dir()))
        with api._runs_lock:
            existing = api._infra_by_state_dir.get(state_dir_key(state_dir))
        if not existing:
            return "", ""
        store, _runner = existing
        rows = store.run.list_runs(limit=1)
        if not rows:
            return "", ""
        row = rows[0]
        return str(row.get("run_id") or ""), str(row.get("status") or "")
    except Exception as exc:
        _logger.debug("diag: last_run_info echec ignore: %s", exc)
        return "", ""


def get_diagnostic(api: Any) -> Dict[str, Any]:
    """Retourne le diagnostic complet pour le bouton "Copier diagnostic".

    Cf docs/internal/design/refonte_2026_05_17/screens/12-aide.md (section 4).

    Structure de la reponse :
        {ok: bool, diagnostic: {version, build_date, python_version, platform,
         db_schema_version, ffprobe_version, mediainfo_version,
         integrations: {tmdb, jellyfin, plex, radarr, omdb},
         roots: [...], lib_total, lib_scored, log_path, settings_path,
         last_run_id, last_run_status, timestamp}}
    """
    settings = _safe_read_settings_for_diag(api)

    # db_schema_version : on essaie de lire la valeur via le store, sinon ""
    db_schema_version: str = ""
    try:
        state_dir = Path(getattr(api, "_state_dir", state.default_state_dir()))
        with api._runs_lock:
            existing = api._infra_by_state_dir.get(state_dir_key(state_dir))
        if existing:
            store, _runner = existing
            try:
                with store._managed_conn() as conn:  # type: ignore[attr-defined]
                    cur = conn.execute("PRAGMA user_version")
                    row = cur.fetchone()
                    if row:
                        db_schema_version = f"v{int(row[0])}"
            except Exception as exc:
                _logger.debug("diag: PRAGMA user_version echec ignore: %s", exc)
    except Exception as exc:
        _logger.debug("diag: db_schema_version resolve echec ignore: %s", exc)

    ffprobe_version, mediainfo_version = _detect_probe_versions(api, settings)
    integrations = _build_integrations_status(settings)
    lib_total, lib_scored = _library_counts(api)
    last_run_id, last_run_status = _last_run_info(api)

    roots_raw = settings.get("roots") if isinstance(settings, dict) else []
    if isinstance(roots_raw, list):
        roots: List[str] = [str(r) for r in roots_raw if str(r).strip()]
    elif roots_raw:
        roots = [str(roots_raw)]
    else:
        roots = []

    version = str(getattr(api, "_app_version", "") or "unknown")

    log_path = str(_logs_dir() / "cinesort.log")
    settings_path = str(_settings_file_path(api))

    diagnostic: Dict[str, Any] = {
        "version": version,
        "build_date": _read_build_date(),
        "python_version": sys.version.split()[0],
        "platform": f"{platform.system()} {platform.release()} ({platform.machine()})",
        "db_schema_version": db_schema_version,
        "ffprobe_version": ffprobe_version,
        "mediainfo_version": mediainfo_version,
        "integrations": integrations,
        "roots": roots,
        "lib_total": lib_total,
        "lib_scored": lib_scored,
        "log_path": log_path,
        "settings_path": settings_path,
        "last_run_id": last_run_id,
        "last_run_status": last_run_status,
        "timestamp": _safe_isoformat_now(),
    }

    return {"ok": True, "diagnostic": diagnostic}


def get_recent_logs(api: Any, limit: int = 100) -> Dict[str, Any]:
    """Lit les N dernieres lignes du log courant.

    Args:
        api: Instance CineSortApi (non utilisee, garde la signature uniforme).
        limit: Nombre de lignes a retourner (cap a 1000).

    Returns:
        {ok: True, lines: [...], log_path: str}
        ou {ok: False, error: str, category: str} si erreur.
    """
    # Cap defensif (cf consigne mission).
    try:
        n = int(limit)
    except (TypeError, ValueError):
        n = 100
    n = max(1, min(n, _MAX_LOG_LINES))

    log_file = _logs_dir() / "cinesort.log"
    if not log_file.is_file():
        return {
            "ok": True,
            "lines": [],
            "log_path": str(log_file),
            "warning": "Fichier log introuvable (rien a afficher).",
        }

    try:
        # Lecture partielle si fichier gros : on ne lit pas plus de _MAX_LOG_BYTES
        size = log_file.stat().st_size
        with open(log_file, "rb") as f:
            if size > _MAX_LOG_BYTES:
                f.seek(size - _MAX_LOG_BYTES)
                # Skip the (potentially partial) first line.
                f.readline()
            raw = f.read()
        text = raw.decode("utf-8", errors="replace")
        lines = text.splitlines()
        # On garde les N dernieres lignes APRES strip ANSI.
        tail = lines[-n:] if len(lines) > n else lines
        cleaned = [_strip_ansi(line) for line in tail]
        return {"ok": True, "lines": cleaned, "log_path": str(log_file)}
    except OSError as exc:
        _logger.warning("get_recent_logs: erreur lecture %s: %s", log_file, exc)
        return {
            "ok": False,
            "error": f"Impossible de lire le log : {exc}",
            "category": "runtime",
        }


def _resolve_doc_safe(doc_id: str) -> Optional[Path]:
    """Resoud un doc_id whiteliste en chemin absolu, ou None si invalide.

    Validations cumulatives :
    1. doc_id doit etre dans la whitelist (refus si inconnu)
    2. La chaine ne doit jamais contenir `..` ou `~` (defense en profondeur)
    3. Le chemin resolu doit etre contenu dans le dossier `docs/` du repo
    4. Le fichier doit exister et etre un fichier regulier
    """
    rel = get_doc_path(doc_id)
    if rel is None:
        return None
    # Defense en profondeur (la whitelist ne contient deja pas `..` mais on
    # protege contre une eventuelle erreur de configuration).
    if ".." in rel or rel.startswith("/") or rel.startswith("\\"):
        return None
    repo = _repo_root()
    docs_root = (repo / "docs").resolve()
    try:
        candidate = (repo / rel).resolve()
    except (OSError, RuntimeError):
        return None
    # Verifie que candidate est dans docs_root.
    try:
        candidate.relative_to(docs_root)
    except ValueError:
        return None
    if not candidate.is_file():
        return None
    return candidate


def get_doc(api: Any, file: str) -> Dict[str, Any]:
    """Retourne le contenu markdown brut d'un document whiteliste.

    Args:
        api: Instance CineSortApi (non utilisee, signature uniforme).
        file: doc_id logique (ex. "user-guide"). Tout chemin contenant `..`
            ou tout doc_id inconnu est rejete avec category="validation".

    Returns:
        {ok: True, content: str, doc_id: str, available: [...]} si OK
        {ok: False, error: str, category: "validation", available: [...]} sinon.
    """
    doc_id_raw = str(file or "").strip()
    if not doc_id_raw:
        return {
            "ok": False,
            "error": "Identifiant de document manquant.",
            "category": "validation",
            "available": list_doc_ids(),
        }
    # Rejet defense en profondeur : path traversal frontal.
    if (
        ".." in doc_id_raw
        or "/" in doc_id_raw
        or "\\" in doc_id_raw
        or doc_id_raw.startswith("~")
        or "\x00" in doc_id_raw
    ):
        return {
            "ok": False,
            "error": "Identifiant de document invalide (caracteres interdits).",
            "category": "validation",
            "available": list_doc_ids(),
        }
    doc_id = doc_id_raw.lower()
    path = _resolve_doc_safe(doc_id)
    if path is None:
        return {
            "ok": False,
            "error": f"Document inconnu : {doc_id!r}.",
            "category": "validation",
            "available": list_doc_ids(),
        }
    try:
        content = path.read_text(encoding="utf-8")
    except OSError as exc:
        _logger.warning("get_doc: lecture echec %s: %s", path, exc)
        return {
            "ok": False,
            "error": f"Lecture impossible : {exc}",
            "category": "runtime",
            "available": list_doc_ids(),
        }
    return {
        "ok": True,
        "doc_id": doc_id,
        "content": content,
        "available": list_doc_ids(),
    }


def _extract_title(lines: List[str]) -> str:
    """Extrait le premier H1 markdown comme titre, ou retourne ""."""
    for line in lines[:50]:
        striped = line.strip()
        if striped.startswith("# "):
            return striped[2:].strip()
    return ""


def search_docs(api: Any, query: str) -> Dict[str, Any]:
    """Recherche full-text dans tous les documents whitelistes.

    Implementation simple : pour chaque ligne contenant la query (case
    insensible), retourne le snippet avec ±2 lignes de contexte. Limite a
    50 resultats au total pour eviter les payloads enormes.

    Args:
        api: Instance CineSortApi (non utilisee, signature uniforme).
        query: Chaine recherchee. Si vide, retourne {ok: True, results: []}.

    Returns:
        {ok: True, results: [{doc_id, title, snippet, line_number}, ...]}
    """
    q_raw = str(query or "").strip()
    if not q_raw:
        return {"ok": True, "results": [], "query": ""}
    # Cap defensif sur la longueur du query pour bloquer un regex DoS si on
    # changeait l'impl vers de la regex. Ici on reste sur du substring match.
    q = q_raw.lower()[:200]

    results: List[Dict[str, Any]] = []
    max_results = 50
    snippet_context = 2

    for doc_id in list_doc_ids():
        if len(results) >= max_results:
            break
        path = _resolve_doc_safe(doc_id)
        if path is None:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            _logger.debug("search_docs: lecture %s ignoree (%s)", path, exc)
            continue
        title = _extract_title(lines) or doc_id
        for idx, line in enumerate(lines):
            if q in line.lower():
                start = max(0, idx - snippet_context)
                end = min(len(lines), idx + snippet_context + 1)
                snippet = "\n".join(lines[start:end])
                results.append(
                    {
                        "doc_id": doc_id,
                        "title": title,
                        "snippet": snippet,
                        "line_number": idx + 1,
                    }
                )
                if len(results) >= max_results:
                    break

    return {"ok": True, "results": results, "query": q_raw}


__all__ = [
    # Helpers existants (preserve)
    "DOCS_WHITELIST",
    "find_run_row",
    "generate_run_id",
    "generate_unique_run_id",
    "get_diagnostic",
    "get_doc",
    "get_or_create_infra",
    "get_recent_logs",
    "get_run",
    "purge_terminal_runs_locked",
    "reset_reconciliation_cache_for_tests",
    "run_paths_for",
    "search_docs",
    "state_dir_key",
]

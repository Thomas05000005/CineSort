from __future__ import annotations

import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from cinesort.ui.api.cinesort_api import CineSortApi
import contextlib

DEV_MODE_ENV_VAR = "DEV_MODE"
TRUTHY_VALUES = {"1", "true", "yes", "on"}
DEV_ONLY_UI_VARIANTS = {"preview"}


def resource_path(rel: str) -> str:
    """
    Support PyInstaller:
    - en dev: chemin relatif au fichier
    - en exe: dans sys._MEIPASS
    """
    if hasattr(sys, "_MEIPASS"):
        base = Path(getattr(sys, "_MEIPASS"))  # type: ignore[attr-defined]
    else:
        base = Path(__file__).resolve().parent
    return str(base / rel)


def _is_truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in TRUTHY_VALUES


def is_dev_mode(argv: list[str] | None = None, env: dict[str, str] | None = None) -> bool:
    args = list(argv if argv is not None else sys.argv[1:])
    environ = env if env is not None else os.environ

    for arg in args:
        if arg == "--dev":
            return True
        if arg.startswith("--dev="):
            return _is_truthy(arg.split("=", 1)[1])
    return _is_truthy(environ.get(DEV_MODE_ENV_VAR, ""))


def requested_ui_variant(argv: list[str] | None = None, env: dict[str, str] | None = None) -> str:
    args = list(argv if argv is not None else sys.argv[1:])
    environ = env if env is not None else os.environ

    requested = "stable"
    for idx, arg in enumerate(args):
        if arg == "--ui" and idx + 1 < len(args):
            requested = args[idx + 1].strip().lower()
            break
        if arg.startswith("--ui="):
            requested = arg.split("=", 1)[1].strip().lower()
            break
    else:
        requested = str(environ.get("CINESORT_UI", "")).strip().lower() or "stable"

    if requested in {"next", "preview"}:
        return requested
    return "stable"


def resolve_ui_variant(argv: list[str] | None = None, env: dict[str, str] | None = None) -> str:
    requested = requested_ui_variant(argv, env)
    if requested == "next":
        return "stable"
    if requested in DEV_ONLY_UI_VARIANTS and not is_dev_mode(argv, env):
        return "stable"
    return requested


def resolve_ui_policy_notice(argv: list[str] | None = None, env: dict[str, str] | None = None) -> str | None:
    requested = requested_ui_variant(argv, env)
    if requested == "next":
        return "UI 'next' archivee. Repli automatique vers l'UI stable."
    if requested in DEV_ONLY_UI_VARIANTS and not is_dev_mode(argv, env):
        return (
            f"UI '{requested}' reservee au mode dev. "
            f"Repli automatique vers l'UI stable. Activez --dev ou {DEV_MODE_ENV_VAR}=1 pour y acceder."
        )
    return None


def resolve_ui_entrypoint(ui_variant: str) -> tuple[str, str]:
    """Retourne (chemin_local_fallback, titre).

    Note : en mode normal, pywebview charge en fait l'URL du dashboard servi par
    le serveur REST local (http://127.0.0.1:PORT/dashboard/). Le chemin local
    retourne ici n'est utilise qu'en fallback (mode preview ou si le serveur
    REST ne demarre pas).
    """
    if str(ui_variant or "").strip().lower() == "preview":
        return (
            "web/index_preview.html",
            "CineSort [UI Preview] - Tri & normalisation de bibliotheque films",
        )
    return (
        "web/dashboard/index.html",
        "CineSort - Tri & normalisation de bibliotheque films",
    )


def _startup_error(message: str, exc: Exception | None = None) -> None:
    lines = [f"[{datetime.now().isoformat(timespec='seconds')}] {message}"]
    if exc is not None:
        lines.append("")
        lines.append(traceback.format_exc())

    state_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "CineSort"
    state_dir.mkdir(parents=True, exist_ok=True)
    crash_path = state_dir / "startup_crash.txt"
    crash_path.write_text("\n".join(lines), encoding="utf-8")

    # Suppress MessageBox in test runs (unittest loaded) to avoid screen pollution
    # when tests exercise main() via mocks. The crash file is still written for diagnostics.
    if "unittest" in sys.modules or os.environ.get("CINESORT_TESTING") == "1":
        print(message)
        print(f"Details: {crash_path}")
        return

    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(  # type: ignore[attr-defined]
            None,
            f"{message}\n\nDetails: {crash_path}",
            "CineSort - Erreur de demarrage",
            0x10,
        )
    except Exception:
        # Best-effort only: keep fallback stdout for shell launch.
        print(message)
        print(f"Details: {crash_path}")


def _is_api_mode() -> bool:
    """Check if --api flag is present in argv."""
    return "--api" in sys.argv[1:]


def _parse_api_port() -> int:
    """Parse --port N from argv, default 8642."""
    args = sys.argv[1:]
    for idx, arg in enumerate(args):
        if arg == "--port" and idx + 1 < len(args):
            try:
                return max(1024, min(65535, int(args[idx + 1])))
            except ValueError:
                pass
        if arg.startswith("--port="):
            try:
                return max(1024, min(65535, int(arg.split("=", 1)[1])))
            except ValueError:
                pass
    return 8642


def _parse_api_public() -> bool:
    """Return True if --public is present in argv (expose REST on 0.0.0.0)."""
    return "--public" in sys.argv[1:]


def _check_updates_in_background(api: CineSortApi, settings: dict | None = None) -> None:
    """V3-12 — Lance un check MAJ silencieux en thread daemon.

    Respecte les settings ``auto_check_updates`` (alias ``update_check_enabled``)
    et ``update_github_repo``. N'echoue jamais bruyamment au boot : toute
    erreur est loggee en warning et le boot continue normalement.
    """
    import logging as _logging
    import threading as _threading

    _log = _logging.getLogger("cinesort.updater.boot")

    def _worker() -> None:
        try:
            s = settings or api.get_settings()
            enabled = s.get("auto_check_updates")
            if enabled is None:
                enabled = s.get("update_check_enabled", True)
            if not enabled:
                _log.debug("V3-12 : check MAJ desactive par les reglages")
                return
            repo = str(s.get("update_github_repo") or "").strip()
            if not repo:
                _log.debug("V3-12 : pas de depot GitHub configure, check skip")
                return
            from cinesort.app.updater import check_for_update_async, default_cache_path

            cache_path = default_cache_path(api._state_dir)
            info = check_for_update_async(api._app_version, repo, cache_path=cache_path)
            if info:
                _log.info("V3-12 : nouvelle version disponible — %s", info.latest_version)
        except (OSError, RuntimeError, ValueError) as exc:
            _log.warning("V3-12 : check MAJ au boot a echoue : %s", exc)

    _threading.Thread(target=_worker, name="cinesort-update-check", daemon=True).start()


def _purge_tmdb_cache_in_background(api: CineSortApi, settings: dict | None = None) -> None:
    """V5-03 polish v7.7.0 (R5-STRESS-4) — purge auto cache TMDb au boot.

    Lance la purge des entrees expirees dans un thread daemon non-bloquant.
    Lit le TTL depuis le setting `tmdb_cache_ttl_days` (defaut 30).
    Log le compteur d'entrees purgees / preservees / total.
    Toute erreur est loggee en warning et le boot continue normalement.
    """
    import logging as _logging
    import threading as _threading

    _log = _logging.getLogger("cinesort.tmdb.purge")

    def _worker() -> None:
        try:
            s = settings or api.get_settings()
            try:
                ttl_days = int(s.get("tmdb_cache_ttl_days") or 30)
            except (TypeError, ValueError):
                ttl_days = 30

            from cinesort.infra.tmdb_client import purge_expired_tmdb_cache

            state_dir = getattr(api, "_state_dir", None)
            if state_dir is None:
                _log.debug("V5-03 : state_dir indisponible, purge skip")
                return
            cache_path = Path(state_dir) / "tmdb_cache.json"
            result = purge_expired_tmdb_cache(cache_path, ttl_days=ttl_days)
            if result.get("error"):
                _log.warning(
                    "V5-03 : purge cache TMDb erreur — %s (path=%s)",
                    result["error"],
                    cache_path,
                )
                return
            _log.info(
                "V5-03 : purge cache TMDb (TTL %dj) — checked=%d purged=%d preserved_legacy=%d",
                ttl_days,
                result.get("checked", 0),
                result.get("purged", 0),
                result.get("preserved_legacy", 0),
            )
        except (OSError, RuntimeError, ValueError) as exc:
            _log.warning("V5-03 : purge cache TMDb au boot a echoue : %s", exc)

    _threading.Thread(target=_worker, name="cinesort-tmdb-purge", daemon=True).start()


def _start_watcher(api: CineSortApi, settings: dict | None = None) -> None:
    """Start the folder watcher if enabled in settings."""
    from cinesort.app.watcher import FolderWatcher

    s = settings or api.get_settings()
    if not s.get("watch_enabled"):
        return
    roots_raw = s.get("roots") or ([s.get("root")] if s.get("root") else [])
    roots = [Path(r) for r in roots_raw if r and Path(r).is_dir()]
    if not roots:
        return
    interval_min = max(1, min(60, int(s.get("watch_interval_minutes") or 5)))
    watcher = FolderWatcher(api, interval_s=interval_min * 60, roots=roots)
    api._watcher = watcher
    watcher.start()
    print(f"[WATCH] Veille active ({interval_min} min), {len(roots)} root(s)", file=sys.stderr)


def _start_rest_server(api: CineSortApi, settings: dict | None = None) -> object | None:
    """Start the REST server. Toujours demarre pour le pywebview desktop.

    - Si rest_api_enabled=False : bind uniquement sur 127.0.0.1 (acces local pywebview uniquement).
    - Si rest_api_enabled=True : bind sur 0.0.0.0 (acces LAN distant + pywebview local).
    Le token est toujours genere automatiquement au premier lancement.
    """
    from cinesort.infra.rest_server import RestApiServer

    s = settings or api.get_settings()
    token = str(s.get("rest_api_token") or "").strip()
    # Auto-persistance : `apply_settings_defaults` genere un token aleatoire si
    # absent du settings.json, mais ne le persiste pas (= NOUVEAU token a chaque
    # appel get_settings, ce qui casse le bypass login pywebview car le serveur
    # REST utilise un token, l'URL pywebview en utilise un autre). Pour eviter
    # ce mismatch, on persiste immediatement le token courant si le settings.json
    # le contient vide.
    try:
        import json as _json
        from pathlib import Path as _Path

        settings_path = _Path(api._state_dir) / "settings.json" if hasattr(api, "_state_dir") else None
        if settings_path and settings_path.is_file():
            raw = _json.loads(settings_path.read_text(encoding="utf-8"))
            if not str(raw.get("rest_api_token") or "").strip() and token:
                api.save_settings({**s, "rest_api_token": token})
                print("[REST] Token persiste dans settings.json (auto-gen).", file=sys.stderr)
    except Exception as exc:
        print(f"[REST] Avertissement persistance token: {exc}", file=sys.stderr)
    port = int(s.get("rest_api_port") or 8642)
    is_public = bool(s.get("rest_api_enabled"))
    host = "0.0.0.0" if is_public else "127.0.0.1"
    server = RestApiServer(
        api,
        port=port,
        token=token,
        cors_origin=str(s.get("rest_api_cors_origin") or ""),
        https_enabled=bool(s.get("rest_api_https_enabled")),
        cert_path=str(s.get("rest_api_cert_path") or ""),
        key_path=str(s.get("rest_api_key_path") or ""),
        host=host,
    )
    try:
        server.start()
    except RuntimeError as exc:
        # M1 : HTTPS demande mais cert/key invalide — ne pas fallback silencieux
        print(f"[REST] Serveur REST non demarre: {exc}", file=sys.stderr)
        return None
    proto = "https" if server._is_https else "http"
    # H-4 audit QA 20260428 : si exposition LAN demandee mais retrogradee
    # (token < 32 chars), l'utilisateur doit le savoir clairement.
    effective_host = server.host
    if getattr(server, "lan_demoted", False):
        print(
            f"[REST] AVERTISSEMENT: {server.lan_demotion_reason}",
            file=sys.stderr,
        )
        scope = "local only (LAN demande mais retrograde par securite)"
    else:
        scope = "LAN" if is_public else "local only"
    print(f"[REST] API demarree sur {proto}://{effective_host}:{port} ({scope})", file=sys.stderr)
    return server


def main_api() -> None:
    """Standalone REST API mode (no GUI)."""
    import logging as _logging_api

    from cinesort.infra.log_context import (
        install_log_context_filter,
        resolve_log_level,
    )
    from cinesort.infra.log_scrubber import install_global_scrubber, install_rotating_log
    from cinesort.infra.rest_server import RestApiServer

    # H-3 audit QA 20260428 : scrub avant de creer l'API (idempotent
    # si main() l'a deja fait).
    install_global_scrubber()
    # V3-04 polish v7.7.0 : injecter run_id + request_id dans tous les logs.
    install_log_context_filter()

    # V3-04 : niveau de log configurable. Valeur lue depuis env vars
    # CINESORT_LOG_LEVEL > CINESORT_DEBUG > defaut INFO. Le setting
    # `log_level` du settings.json est applique plus loin une fois l'API creee.
    boot_level = resolve_log_level(None)
    _logging_api.basicConfig(level=boot_level, format="%(message)s")
    if str(os.environ.get("CINESORT_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on", "debug"}:
        print("[LOG] Mode debug active (CINESORT_DEBUG=1) — niveau DEBUG", file=sys.stderr)

    state_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "CineSort"
    install_rotating_log(state_dir / "logs", level=boot_level)

    api = CineSortApi()
    settings = api.get_settings()

    # V3-04 polish v7.7.0 : appliquer le log_level depuis settings.json (sauf
    # si une env var l'a deja override).
    effective_level = resolve_log_level(settings.get("log_level"))
    _logging_api.getLogger().setLevel(effective_level)

    # V6-01 Polish Total v7.7.0 : charger la locale depuis settings.json. Defaut
    # FR si manquant ou invalide. Le module i18n_messages valide en interne.
    try:
        from cinesort.domain.i18n_messages import set_locale as _i18n_set_locale

        _i18n_set_locale(str(settings.get("locale") or "fr"))
    except (ImportError, AttributeError) as _i18n_exc:
        # Tolerant : si le module i18n a un probleme au boot, on continue avec
        # le defaut FR (le module a deja un fallback interne).
        _logging_api.getLogger("cinesort.boot").debug("i18n boot skipped: %s", _i18n_exc)

    port = _parse_api_port()
    token = str(settings.get("rest_api_token") or "").strip()

    if not token:
        print("[REST] Aucun token configure dans les reglages. Utilisez l'UI pour en definir un.", file=sys.stderr)
        raise SystemExit(1)

    is_public = _parse_api_public()
    host = "0.0.0.0" if is_public else "127.0.0.1"
    server = RestApiServer(
        api,
        port=port,
        token=token,
        cors_origin=str(settings.get("rest_api_cors_origin") or ""),
        https_enabled=bool(settings.get("rest_api_https_enabled")),
        cert_path=str(settings.get("rest_api_cert_path") or ""),
        key_path=str(settings.get("rest_api_key_path") or ""),
        host=host,
    )
    proto = (
        "https" if server._https_enabled and Path(str(settings.get("rest_api_cert_path") or "")).is_file() else "http"
    )
    # H-4 audit QA 20260428 : signaler la retrogradation LAN si elle a eu lieu.
    effective_host = server.host
    if getattr(server, "lan_demoted", False):
        print(
            f"[REST] AVERTISSEMENT: {server.lan_demotion_reason}",
            file=sys.stderr,
        )
        scope = "localhost only (LAN demande mais retrograde par securite)"
    else:
        scope = "LAN public" if is_public else "localhost only"
    print(f"[REST] CineSort API standalone sur {proto}://{effective_host}:{port} ({scope})", file=sys.stderr)
    if is_public:
        print(
            "[REST] AVERTISSEMENT : l'API est accessible depuis le reseau local. Assurez-vous d'avoir un token fort.",
            file=sys.stderr,
        )
    else:
        print("[REST] Astuce : ajoutez --public pour autoriser l'acces depuis le LAN.", file=sys.stderr)
    print("[REST] Ctrl+C pour arreter.", file=sys.stderr)

    # V5-03 polish v7.7.0 (R5-STRESS-4) : purge auto cache TMDb au boot.
    _purge_tmdb_cache_in_background(api, settings)

    server.start()
    try:
        server.join()
    except KeyboardInterrupt:
        print("\n[REST] Arret...", file=sys.stderr)
        server.stop()
        # V2-10 audit QA 20260504 : PRAGMA optimize avant arret en mode --api.
        if api and hasattr(api, "_infra_by_state_dir"):
            for _key, (store, _runner) in list(api._infra_by_state_dir.items()):
                try:
                    store.close()
                except Exception as _exc:  # noqa: BLE001
                    print(f"[REST] store.close() ignored: {_exc}", file=sys.stderr)


def _update_splash(splash_window: object, step: int, text: str, percent: int) -> None:
    """Met a jour la progression du splash. Silencieux si le splash est deja ferme."""
    # Echapper les caracteres dangereux pour l'interpolation JS dans une string entre apostrophes
    safe_text = str(text).replace("\\", "\\\\").replace("'", "\\'")
    try:
        splash_window.evaluate_js(f"updateProgress({step}, '{safe_text}', {percent})")  # type: ignore[union-attr]
    except Exception:
        pass  # splash peut etre deja ferme


def _check_dpapi_availability() -> None:
    """Warn loudly if Windows DPAPI is unavailable.

    CineSort is Windows-only. Sans DPAPI (Linux, WSL, Windows corrompu), les
    secrets TMDb/Jellyfin refusent de persister (comportement securise) mais
    l'utilisateur perd les integrations. On log un warning visible pour que
    l'absence de DPAPI ne soit pas silencieuse.
    """
    from cinesort.infra.local_secret_store import protection_available

    if not protection_available():
        banner = "\n".join(
            [
                "!" * 72,
                "AVERTISSEMENT SECURITE : Windows DPAPI indisponible.",
                "Les cles TMDb, Jellyfin, et autres secrets protegeables NE SERONT PAS",
                "stockees. Les integrations fonctionneront uniquement en session (memoire).",
                "Cette build de CineSort est concue pour Windows. Lancer sous Linux/WSL",
                "n'est pas supporte.",
                "!" * 72,
            ]
        )
        print(banner, file=sys.stderr)


def main() -> None:
    # H-3 audit QA 20260428 : installer le scrubber AVANT toute creation
    # d'API/logger pour capturer les premiers logs de boot eux-memes.
    # H-6 audit QA 20260429 : installer aussi un RotatingFileHandler pour
    # eviter que les logs ne grandissent indefiniment (50 MB x 5 backups).
    # V3-04 polish v7.7.0 : installer LogContextFilter (run_id + request_id)
    # et resoudre le niveau de log via env vars / settings.
    import logging as _logging_main

    from cinesort.infra.log_context import (
        install_log_context_filter,
        resolve_log_level,
    )
    from cinesort.infra.log_scrubber import install_global_scrubber, install_rotating_log

    install_global_scrubber()
    install_log_context_filter()

    boot_level = resolve_log_level(None)
    _logging_main.basicConfig(level=boot_level, format="%(message)s")
    if str(os.environ.get("CINESORT_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on", "debug"}:
        print("[LOG] Mode debug active (CINESORT_DEBUG=1) — niveau DEBUG", file=sys.stderr)

    state_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "CineSort"
    install_rotating_log(state_dir / "logs", level=boot_level)

    _check_dpapi_availability()

    if _is_api_mode():
        main_api()
        return

    try:
        import webview  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        _startup_error("Dependance manquante: pywebview. Rebuild avec build_windows.bat (venv + dependencies).")
        raise SystemExit(1)

    import logging as _logging
    import time as _time

    _log = _logging.getLogger("cinesort.startup")
    rest_server = None
    api: CineSortApi | None = None
    splash = None

    try:
        # --- 0. Mode E2E : activer le remote debugging CDP ---
        if os.environ.get("CINESORT_E2E") == "1":
            webview.settings["REMOTE_DEBUGGING_PORT"] = int(os.environ.get("CINESORT_CDP_PORT", "9222"))
            _log.info("Mode E2E actif : CDP port %s", webview.settings["REMOTE_DEBUGGING_PORT"])

        # --- 0b. Creer l'API en premier (necessaire pour js_api) ---
        api = CineSortApi()

        # --- 1. Creer le splash HTML (visible immediatement) ---
        splash_url = Path(resource_path("web/splash.html")).resolve().as_uri()
        splash = webview.create_window(
            "CineSort",
            url=splash_url,
            frameless=True,
            width=520,
            height=320,
            on_top=True,
            resizable=False,
            text_select=False,
        )

        # --- 2. Demarrer le serveur REST IMMEDIATEMENT (avant pywebview) ---
        # Le pywebview charge le dashboard depuis ce serveur local.
        # Le serveur bind sur 127.0.0.1 si rest_api_enabled=False (desktop local seul)
        # ou sur 0.0.0.0 si rest_api_enabled=True (LAN distant).
        settings_early = api.get_settings()

        # V3-04 polish v7.7.0 : appliquer log_level depuis settings.json (si
        # une env var n'a pas deja override).
        try:
            effective_level = resolve_log_level(settings_early.get("log_level"))
            _logging_main.getLogger().setLevel(effective_level)
        except (TypeError, ValueError, AttributeError) as _exc:
            _log.warning("V3-04: application log_level depuis settings echouee: %s", _exc)

        # V6-01 Polish Total v7.7.0 : charger la locale depuis settings.json
        # avant le boot UI. Tolerant : fallback FR si module ou setting absent.
        try:
            from cinesort.domain.i18n_messages import set_locale as _i18n_set_locale

            _i18n_set_locale(str(settings_early.get("locale") or "fr"))
        except (ImportError, AttributeError) as _i18n_exc:
            _log.debug("V6-01: i18n boot skipped: %s", _i18n_exc)

        rest_server = _start_rest_server(api, settings_early)
        api._rest_server = rest_server
        # Re-lire les settings au cas ou _start_rest_server a auto-genere et persiste
        # un nouveau token (cf fix : token vide -> auto-gen + save). Indispensable
        # pour que la construction de main_url ci-dessous trouve le bon token.
        settings_early = api.get_settings()

        # --- 3. Determiner l'URL a charger : dashboard local ou fallback legacy ---
        ui_variant = resolve_ui_variant()
        policy_notice = resolve_ui_policy_notice()
        if policy_notice:
            print(f"[INFO] {policy_notice}", file=sys.stderr)
        index_rel, title = resolve_ui_entrypoint(ui_variant)

        if rest_server is not None and ui_variant != "preview":
            # Mode normal : pywebview charge le dashboard via HTTP local.
            # On passe le token en query string (?ntoken=XXX) pour un bypass immediat du login.
            # Le JS dashboard le detecte au boot, le stocke dans localStorage et purge l'URL.
            from urllib.parse import quote

            port = getattr(rest_server, "_port", 8642)
            proto = "https" if getattr(rest_server, "_is_https", False) else "http"
            _desktop_dashboard_token = str(settings_early.get("rest_api_token") or "")
            if _desktop_dashboard_token:
                main_url = f"{proto}://127.0.0.1:{port}/dashboard/?ntoken={quote(_desktop_dashboard_token)}&native=1"
                # DEBUG : afficher l'URL injectee (token tronque pour lisibilite)
                print(
                    f"[REST] main_url = {proto}://127.0.0.1:{port}/dashboard/?ntoken={_desktop_dashboard_token[:8]}...&native=1",
                    file=sys.stderr,
                )
            else:
                main_url = f"{proto}://127.0.0.1:{port}/dashboard/?native=1"
                print("[REST] AVERTISSEMENT : main_url SANS ntoken (token vide dans settings_early)", file=sys.stderr)
        else:
            # Fallback : charger l'index local (mode preview ou serveur REST mort)
            index = resource_path(index_rel)
            main_url = Path(index).resolve().as_uri()
            _desktop_dashboard_token = ""

        main_window = webview.create_window(
            title,
            url=main_url,
            js_api=api,
            width=1250,
            height=820,
            min_size=(1000, 700),
            hidden=True,
        )

        # --- 3. Fonction de startup (tourne dans le thread webview) ---
        def _startup() -> None:
            try:
                _log.info("splash: etape 1 — Initialisation")
                _update_splash(splash, 1, "Initialisation...", 10)
                _time.sleep(0.15)

                _log.info("splash: etape 2 — Chargement des reglages")
                _update_splash(splash, 2, "Chargement des reglages...", 25)
                settings = api.get_settings()
                _time.sleep(0.1)

                _log.info("splash: etape 3 — Base de donnees")
                _update_splash(splash, 3, "Connexion base de donnees...", 40)
                _time.sleep(0.1)

                _log.info("splash: etape 4 — Interface")
                _update_splash(splash, 4, "Preparation de l'interface...", 60)
                # Connecter la fenetre et le service de notifications
                api._window = main_window
                api._notify.set_window(main_window)
                # R5-CRIT-1 : demarrer le drain timer pour livrer les notifs queued
                # depuis les threads background (job_runner scan/apply/undo).
                # Sans ce timer, les notifs scan_done/apply_done/etc. restent dans
                # la queue indefiniment et l'utilisateur ne voit rien.
                try:
                    api._notify.start_drain_timer(0.5)
                except (AttributeError, RuntimeError) as exc:
                    _log.warning("drain_timer start failed: %s", exc)
                # R5-CRASH-3 : atexit cleanup pour eviter tray icon Win32 orphelin
                # si crash brutal (kill -9 reste insurmonté mais SIGTERM ok).
                import atexit as _atexit

                _atexit.register(lambda: api._notify.shutdown())

                # Version dans le splash
                try:
                    version = getattr(api, "_app_version", "")
                    if version:
                        splash.evaluate_js(f"setVersion('v{version}')")  # type: ignore[union-attr]
                except Exception:
                    pass

                _log.info("splash: etape 5 — Serveur API (deja actif)")
                _update_splash(splash, 5, "Serveur API actif...", 75)

                if settings.get("watch_enabled"):
                    _log.info("splash: etape 6 — Surveillance dossiers")
                    _update_splash(splash, 6, "Demarrage surveillance dossiers...", 90)
                    _start_watcher(api, settings)

                # V3-12 : check MAJ silencieux en arriere-plan (auto_check_updates).
                _check_updates_in_background(api, settings)

                # V5-03 polish v7.7.0 (R5-STRESS-4) : purge auto cache TMDb expire
                # en arriere-plan (non-bloquant). Evite l'accumulation orphelins.
                _purge_tmdb_cache_in_background(api, settings)

                # Injecter le token dans le localStorage du dashboard avant l'affichage
                # pour bypass automatique de la page login (mode desktop natif).
                # Le dashboard utilise les cles 'cinesort.dashboard.token' et 'cinesort.dashboard.persist'.
                if _desktop_dashboard_token:
                    try:
                        safe_tk = _desktop_dashboard_token.replace("\\", "\\\\").replace("'", "\\'")
                        inject_js = (
                            "try {"
                            f"  localStorage.setItem('cinesort.dashboard.token', '{safe_tk}');"
                            "  localStorage.setItem('cinesort.dashboard.persist', '1');"
                            f"  sessionStorage.setItem('cinesort.dashboard.token', '{safe_tk}');"
                            "  window.__CINESORT_NATIVE__ = true;"
                            "} catch (e) { console.warn('token inject fail', e); }"
                        )
                        main_window.evaluate_js(inject_js)
                        _log.info("splash: token injecte dans localStorage (mode natif)")
                    except Exception as exc:
                        _log.warning("splash: injection token echouee — %s", exc)

                _log.info("splash: etape finale — Pret")
                _update_splash(splash, 7, "Pret !", 100)
                _time.sleep(0.4)

                # Afficher la fenetre principale et detruire le splash
                main_window.show()
                _log.info("splash: fenetre principale affichee, splash detruit")
                with contextlib.suppress(Exception):
                    splash.destroy()

            except Exception as exc:
                _log.error("splash: erreur startup — %s", exc)
                # En cas d'erreur, montrer quand meme la fenetre principale
                try:
                    if api:
                        api._window = main_window
                        api._notify.set_window(main_window)
                    main_window.show()
                except Exception:
                    pass
                with contextlib.suppress(Exception):
                    splash.destroy()

        # private_mode=False : autorise localStorage/sessionStorage persistants
        # (sinon le token bypass login est purge au reload, login obligatoire).
        # storage_path : isole le storage CineSort dans %LOCALAPPDATA%/CineSort/webview.
        _storage_dir = Path(os.environ.get("LOCALAPPDATA", ".")) / "CineSort" / "webview"
        _storage_dir.mkdir(parents=True, exist_ok=True)
        webview.start(
            _startup,
            debug=False,
            private_mode=False,
            storage_path=str(_storage_dir),
        )

    except Exception as exc:
        _startup_error("Erreur inattendue au demarrage de CineSort.", exc)
        raise
    finally:
        if api and api._watcher and api._watcher.is_alive():
            api._watcher.stop()
        if api:
            api._notify.shutdown()
        # V2-10 audit QA 20260504 : PRAGMA optimize sur tous les SQLiteStore
        # actifs avant l'arret. Reduit la fragmentation et met a jour les
        # statistiques de l'optimiseur. Best effort, ne bloque pas le shutdown.
        if api and hasattr(api, "_infra_by_state_dir"):
            try:
                for _key, (store, _runner) in list(api._infra_by_state_dir.items()):
                    try:
                        store.close()
                    except Exception as _exc:  # noqa: BLE001 — shutdown must continue
                        _log.warning("store.close() at shutdown failed (ignored): %s", _exc)
            except Exception as _exc:  # noqa: BLE001
                _log.warning("V2-10: parcours stores au shutdown echoue: %s", _exc)
        if rest_server and hasattr(rest_server, "stop"):
            rest_server.stop()


if __name__ == "__main__":
    main()

from __future__ import annotations

import contextlib
import os
import sys
import traceback
from datetime import datetime
from pathlib import Path

from cinesort.infra.state import default_state_dir
from cinesort.ui.api.cinesort_api import CineSortApi

DEV_MODE_ENV_VAR = "DEV_MODE"
TRUTHY_VALUES = {"1", "true", "yes", "on"}


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

    if requested == "next":
        return requested
    return "stable"


def resolve_ui_variant(argv: list[str] | None = None, env: dict[str, str] | None = None) -> str:
    if requested_ui_variant(argv, env) == "next":
        return "stable"
    return "stable"


def resolve_ui_policy_notice(argv: list[str] | None = None, env: dict[str, str] | None = None) -> str | None:
    if requested_ui_variant(argv, env) == "next":
        return "UI 'next' archivee. Repli automatique vers l'UI stable."
    return None


def resolve_ui_entrypoint(ui_variant: str) -> tuple[str, str]:
    """Retourne (chemin_local_fallback, titre).

    Note : en mode normal, pywebview charge l'URL du dashboard servi par le
    serveur REST local (http://127.0.0.1:PORT/dashboard/). Le chemin local
    retourne ici n'est utilise qu'en fallback si le serveur REST ne demarre pas.
    """
    return (
        "web/dashboard/index.html",
        "CineSort - Tri & normalisation de bibliotheque films",
    )


def _startup_error(message: str, exc: Exception | None = None) -> None:
    lines = [f"[{datetime.now().isoformat(timespec='seconds')}] {message}"]
    if exc is not None:
        lines.append("")
        lines.append(traceback.format_exc())

    state_dir = default_state_dir()
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
            s = settings or api.settings.get_settings()
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
            s = settings or api.settings.get_settings()
            try:
                ttl_days = int(s.get("tmdb_cache_ttl_days") or 30)
            except (TypeError, ValueError):
                ttl_days = 30

            from cinesort.infra.tmdb_client import purge_expired_tmdb_cache

            state_dir = getattr(api, "_state_dir", None)
            if state_dir is None:
                _log.debug("V5-03 : state_dir indisponible, purge skip")
                return
            # Balayage des `.tmp` d'ecriture atomique orphelins, AVANT la purge
            # (et avant tout `return` d'erreur de celle-ci : c'est ce balayage
            # qui rend le disque, il ne doit pas dependre du succes du reste).
            #
            # Un `.tmp` de nom UNIQUE n'est jamais reecrase : chaque crash en
            # laisse un DEFINITIF, la ou l'ancien `.tmp` fixe etait recycle et
            # bornait donc le residu a un seul. `<state_dir>/tmdb_cache.json`
            # pese 20 a 100 Mo et est reecrit toutes les 2 s pendant un scan :
            # sans ce balayage, chaque kill coute un fichier de cette taille, a
            # vie. Recursif : `cache/posters/` (aucun pruner) et `runs/` sont
            # sous `state_dir`.
            from cinesort.infra.state import sweep_atomic_tmp_orphans

            swept = sweep_atomic_tmp_orphans(Path(state_dir), recursive=True)
            if swept:
                _log.info("V5-03 : %d fichier(s) .tmp orphelin(s) balaye(s) sous %s", swept, state_dir)

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

    s = settings or api.settings.get_settings()
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

    s = settings or api.settings.get_settings()
    # Fix audit 2026-05-24 : token atomique.
    # Avant : `s.get("rest_api_token")` pouvait differer entre 2 lectures
    # consecutives (apply_settings_defaults regenere un nouveau token aleatoire
    # a chaque appel s'il est vide dans settings.json sans le persister) ->
    # le serveur REST utilisait un token, le main_url un autre, bypass login
    # casse silencieusement.
    #
    # Maintenant : verifier le settings.json brut. Si le token y est vide,
    # on persiste IMMEDIATEMENT le token de `s` (ainsi tout get_settings ulterieur
    # renvoie la meme valeur). Si non vide, on reutilise celui du disque pour
    # eviter toute divergence.
    # DEBUG VERBOSE 2026-06-08 : trace exhaustif si CINESORT_DEBUG actif. Cible
    # le bug auth persistant apres 4 hotfixes (_mask_secrets / _safeBearer /
    # utf-8-sig / native_boot). Logue codepoints char-par-char du token AVANT
    # url-encode pour identifier tout caractere > 0x7F qui casse _safeBearer.
    _DEBUG_TOKEN = str(os.environ.get("CINESORT_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on", "debug"}

    def _dbg_codepoints(label: str, value: str) -> None:
        """Logue codepoint-par-codepoint un token, signale tout > 0x7F."""
        if not _DEBUG_TOKEN:
            return
        try:
            length = len(value)
            cps = [f"U+{ord(c):04X}" for c in value]
            non_ascii = [(i, c, ord(c)) for i, c in enumerate(value) if ord(c) > 0x7F]
            print(f"[DEBUG-TOKEN] {label} len={length}", file=sys.stderr)
            print(f"[DEBUG-TOKEN] {label} codepoints={cps}", file=sys.stderr)
            if non_ascii:
                for i, c, o in non_ascii:
                    print(
                        f"[DEBUG-TOKEN] {label} NON-ASCII pos={i} char={c!r} U+{o:04X}",
                        file=sys.stderr,
                    )
            else:
                print(f"[DEBUG-TOKEN] {label} 100% ASCII OK", file=sys.stderr)
        except Exception as _dbg_exc:  # noqa: BLE001 — debug only
            print(f"[DEBUG-TOKEN] {label} dump failed: {_dbg_exc}", file=sys.stderr)

    # [SEC-2] Le token REST est chiffre au repos (enveloppe rest_api_token_secret
    # dans settings.json). On resout le token CLAIR via _internal_settings() qui
    # DECHIFFRE l'enveloppe. Surtout PAS via une lecture brute de settings.json
    # (le clair n'y est plus depuis SEC-2 -> lecture vide) ni via `s` (get_settings
    # MASQUE le token en "••••••••"). Sinon le serveur demarrait avec le masque de
    # 8 puces -> len 8 < MIN_LAN_TOKEN_LENGTH (32) -> bind LAN retrograde en
    # 127.0.0.1 -> appareils distants coupes + 401 systematique sur le dashboard.
    # NB : _internal_settings() -> read_settings() tolere deja le BOM (utf-8-sig).
    try:
        token = str(api._internal_settings().get("rest_api_token") or "").strip()
    except Exception as exc:
        token = ""
        print(f"[REST] Avertissement lecture token: {exc}", file=sys.stderr)
    # Garde-fou defensif : ne JAMAIS demarrer avec le masque (contournerait la
    # protection MIN_LAN_TOKEN_LENGTH avec un secret public de 8 puces).
    from cinesort.ui.api.settings_support import _SECRET_MASK as _MASK

    if token == _MASK:
        token = ""
    if not token:
        # Aucun token configure (tout 1er lancement, avant tout save) : en generer
        # un et le persister (chiffre au repos par SEC-2 lors du save) pour que
        # tout get_settings ulterieur renvoie la meme valeur. On echo `s`
        # (masque) : _unmask_secrets_for_save restaure les autres secrets depuis
        # le disque, seul rest_api_token change vers une vraie valeur claire.
        import secrets as _secrets

        token = _secrets.token_urlsafe(24)
        try:
            api.settings.save_settings({**s, "rest_api_token": token})
            print("[REST] Token REST genere et persiste (1er lancement).", file=sys.stderr)
        except Exception as exc:
            print(f"[REST] Avertissement persistance token: {exc}", file=sys.stderr)
    _dbg_codepoints("token FINAL passe a RestApiServer", token)
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
    except (OSError, RuntimeError) as exc:
        # R5-finding-1 : OSError = port deja utilise (WinError 10048 / EADDRINUSE).
        # M1 : RuntimeError = HTTPS demande mais cert/key invalide.
        import errno

        if isinstance(exc, OSError) and getattr(exc, "errno", None) in (errno.EADDRINUSE, 10048):
            msg = (
                f"Le port REST {port} est deja utilise par un autre processus. "
                "Fermez CineSort dans une autre session Windows ou modifiez "
                "'rest_api_port' dans settings.json."
            )
        else:
            msg = f"Serveur REST non demarre: {exc}"
        print(f"[REST] {msg}", file=sys.stderr)
        _startup_error(msg)
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
        install_repeated_exception_dedup,
        resolve_log_level,
    )
    from cinesort.infra.log_scrubber import install_global_scrubber, install_rotating_log
    from cinesort.infra.rest_server import RestApiServer

    # H-3 audit QA 20260428 : scrub avant de creer l'API (idempotent
    # si main() l'a deja fait).
    install_global_scrubber()
    # V3-04 polish v7.7.0 : injecter run_id + request_id dans tous les logs.
    install_log_context_filter()
    # Fix audit 2026-05-25 (v1.5.3) Vague H : evite le spam de meme exception (>5/min)
    install_repeated_exception_dedup(max_per_minute=5)

    # V3-04 : niveau de log configurable. Valeur lue depuis env vars
    # CINESORT_LOG_LEVEL > CINESORT_DEBUG > defaut INFO. Le setting
    # `log_level` du settings.json est applique plus loin une fois l'API creee.
    boot_level = resolve_log_level(None)
    _logging_api.basicConfig(level=boot_level, format="%(message)s")
    # AUDIT 2026-06-10 : re-synchroniser le scrubber APRES basicConfig pour
    # couvrir le StreamHandler console qu'il vient de creer (un filtre de logger
    # ne s'applique pas aux records propagees vers ce handler).
    install_global_scrubber()
    if str(os.environ.get("CINESORT_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on", "debug"}:
        print("[LOG] Mode debug active (CINESORT_DEBUG=1) — niveau DEBUG", file=sys.stderr)

    state_dir = default_state_dir()
    install_rotating_log(state_dir / "logs", level=boot_level)

    api = CineSortApi()
    settings = api.settings.get_settings()

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
    # [SEC-2] rest_api_token est chiffre au repos et get_settings() le MASQUE.
    # Le boot headless doit lire le token CLAIR via _internal_settings()
    # (dechiffre) : sinon `token` valait le masque "••••••••" (bearer = constante
    # publique devinable) et le garde `if not token` etait MORT (masque truthy).
    # Contrairement au chemin desktop, le mode --api NE genere PAS de token : il
    # exige un token deja configure (via l'UI) et refuse de demarrer sinon.
    token = str(api._internal_settings().get("rest_api_token") or "").strip()
    from cinesort.ui.api.settings_support import _SECRET_MASK as _MASK

    if token == _MASK:
        token = ""
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

    # Spec 09 §5 (Historique) : cron retention 90j en mode standalone REST.
    try:
        from cinesort.app.retention_cleanup import start_retention_cron

        retention_days_api = int(settings.get("history_retention_days") or 90)
        start_retention_cron(api, retention_days=retention_days_api)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as _ret_exc:
        print(f"[REST] spec 09 retention cron init echouee: {_ret_exc}", file=sys.stderr)

    # VQ-2 QUARANTAINE-TTL : cron TTL du bucket FS `_review` (defaut 30j, 0 OFF).
    try:
        from cinesort.app.quarantine_ttl import (
            DEFAULT_TTL_DAYS as _Q_DEFAULT_TTL,
        )
        from cinesort.app.quarantine_ttl import (
            start_quarantine_ttl_cron,
        )

        quarantaine_ttl_api = int(settings.get("quarantaine_ttl_days") or _Q_DEFAULT_TTL)
        start_quarantine_ttl_cron(api, ttl_days=quarantaine_ttl_api)
    except (ImportError, OSError, RuntimeError, TypeError, ValueError) as _qttl_exc:
        print(f"[REST] vq-2 quarantine ttl cron init echouee: {_qttl_exc}", file=sys.stderr)

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
    """Met a jour la progression du splash. Silencieux si le splash est deja ferme.

    Cf issue #64 : json.dumps echappe correctement TOUS les chars dangereux
    (\\n, </script>, U+2028 LINE SEPARATOR, U+2029 PARAGRAPH SEPARATOR) alors
    que l'escape manuel precedent ne couvrait que \\ et '. Resultat : un text
    contenant un retour ligne cassait la string JS et permettait injection.
    """
    import json

    try:
        splash_window.evaluate_js(  # type: ignore[union-attr]
            f"updateProgress({step}, {json.dumps(str(text))}, {percent})"
        )
    except Exception:
        pass  # splash peut etre deja ferme


def _configure_webview2_runtime() -> None:
    """V3.1 SCAFFOLDING — Configure WebView2 pour utiliser le runtime bundle si dispo.

    Quand le build a embarque le runtime "Fixed Version" via le spec
    (CINESORT_BUNDLE_WEBVIEW2=1 ; cf CineSort.spec section V3.1), le repertoire
    `webview2_fixed/` est extrait sous `sys._MEIPASS` au demarrage de l'EXE
    onefile. On expose alors son chemin via les variables d'environnement
    standards WebView2 (`WEBVIEW2_BROWSER_EXECUTABLE_FOLDER`) et on isole les
    donnees utilisateur dans `%LOCALAPPDATA%/CineSort/webview2_userdata`.

    Si le bundle est absent (build standard, comportement historique),
    on ne touche a aucune variable d'env -> WebView2 retombe sur le
    runtime Evergreen installe par Microsoft Edge (backward-compat ABSOLUE).
    Aucune erreur n'est levee dans ce chemin.
    """
    try:
        bundle_root = Path(resource_path("webview2_fixed"))
    except Exception:
        return
    if not bundle_root.is_dir():
        return

    # Sanity-check : msedgewebview2.exe doit etre present a la racine du bundle.
    if not (bundle_root / "msedgewebview2.exe").is_file():
        print(
            "[WEBVIEW2] Bundle present mais msedgewebview2.exe manquant - fallback Evergreen.",
            file=sys.stderr,
        )
        return

    # WEBVIEW2_BROWSER_EXECUTABLE_FOLDER : utilise par la loader API
    # CreateCoreWebView2EnvironmentWithOptions cote WebView2 SDK pour pointer
    # sur un runtime fixe (cf doc Microsoft Edge WebView2 distribution modes).
    os.environ.setdefault(
        "WEBVIEW2_BROWSER_EXECUTABLE_FOLDER",
        str(bundle_root),
    )
    # Donnees utilisateur (cache, cookies, IndexedDB) — isolees du profil global
    # pour eviter conflit avec un Edge installe. Doit etre ECRIVABLE (pas dans
    # sys._MEIPASS qui est read-only).
    userdata_dir = default_state_dir() / "webview2_userdata"
    try:
        userdata_dir.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    os.environ.setdefault("WEBVIEW2_USER_DATA_FOLDER", str(userdata_dir))
    print(
        f"[WEBVIEW2] Runtime Fixed bundle actif: {bundle_root}",
        file=sys.stderr,
    )


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
    # Fix audit 2026-05-25 (v1.5.3) Vague H : requis pour PyInstaller +
    # ProcessPoolExecutor. Safety net : si un module quelconque (current ou futur)
    # spawn un subprocess via multiprocessing dans le bundle frozen, freeze_support()
    # evite que l'enfant ne re-execute main() en boucle infinie (fork-bomb classique
    # sur Windows). Doit etre appele au TOUT debut, avant toute init lourde.
    import multiprocessing

    multiprocessing.freeze_support()

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
    # AUDIT 2026-06-10 : re-synchroniser le scrubber APRES basicConfig (couvre le
    # StreamHandler console cree par basicConfig).
    install_global_scrubber()
    if str(os.environ.get("CINESORT_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on", "debug"}:
        print("[LOG] Mode debug active (CINESORT_DEBUG=1) — niveau DEBUG", file=sys.stderr)

    state_dir = default_state_dir()
    install_rotating_log(state_dir / "logs", level=boot_level)

    _check_dpapi_availability()

    # V3.1 SCAFFOLDING — Si le build a embarque le runtime WebView2 Fixed
    # Version, expose le chemin via les env vars standards AVANT d'importer
    # `webview` (les loaders WebView2 lisent l'env au premier
    # CreateCoreWebView2Environment). En l'absence de bundle, no-op silencieux
    # -> repli automatique sur le runtime Evergreen installe.
    _configure_webview2_runtime()

    # Cf issue #68 : verrou inter-process avant toute initialisation lourde.
    # Empeche 2 CineSort.exe simultanees sur le meme state_dir (corruption DB
    # via apply_rows concurrents). Le lock est libere automatiquement par l'OS
    # a la mort du process — pas de stale lock meme apres kill -9.
    # Fix audit 2026-05-25 (v1.5.3) Vague H : InstanceLock confirme avant
    # SQLite (CineSortApi() plus bas declenche SQLiteStore.initialize()).
    # L'ordre acquire() -> CineSortApi() ne doit PAS etre modifie : inverser
    # casserait la garantie anti-corruption multi-instance.
    from cinesort.infra.single_instance import InstanceLock

    instance_lock = InstanceLock(state_dir)
    if not instance_lock.acquire():
        other_pid = instance_lock.read_holder_pid()
        pid_msg = f" (PID {other_pid})" if other_pid else ""
        _startup_error(
            f"Une autre instance de CineSort tourne deja{pid_msg}.\n"
            "Fermer l'autre fenetre, ou supprimer manuellement le fichier "
            f"{instance_lock.lock_path} si l'instance precedente a crashe.",
        )
        raise SystemExit(2)

    if _is_api_mode():
        try:
            main_api()
        finally:
            instance_lock.release()
        return

    try:
        import webview  # type: ignore[import-not-found]
    except ModuleNotFoundError:
        _startup_error("Dependance manquante: pywebview. Rebuild avec build_windows.bat (venv + dependencies).")
        raise SystemExit(1) from None

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
        # Fix audit 2026-05-25 (v1.5.4) : splash AGRANDI pour masquer la main
        # window noire pendant que WebView2 initialise (20s typique avant que
        # events.loaded ne firing). Avant : splash 520x320 et main 1250x820 ->
        # l'utilisateur voyait la main noire DEPASSER autour du splash centre.
        # Le contenu du splash (logo+barre) reste centre grace au flex CSS et au
        # max-width:440px applique sur .splash dans web/splash.html. on_top=True
        # garantit que le splash reste au premier plan tant que pas detruit.
        splash_url = Path(resource_path("web/splash.html")).resolve().as_uri()
        splash = webview.create_window(
            "CineSort",
            url=splash_url,
            frameless=True,
            width=1400,
            height=900,
            on_top=True,
            resizable=False,
            text_select=False,
        )

        # --- 2. Demarrer le serveur REST IMMEDIATEMENT (avant pywebview) ---
        # Le pywebview charge le dashboard depuis ce serveur local.
        # Le serveur bind sur 127.0.0.1 si rest_api_enabled=False (desktop local seul)
        # ou sur 0.0.0.0 si rest_api_enabled=True (LAN distant).
        settings_early = api.settings.get_settings()

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
        settings_early = api.settings.get_settings()

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
            # CAUSE RACINE 2026-06-07 : api.settings.get_settings() passe par
            # get_settings_payload() -> _mask_secrets() qui remplace rest_api_token
            # par 8 bullets U+2022. URL-encoded en %E2%80%A2 x8, le frontend les
            # decode, _URLSAFE_TOKEN_RE = /^[A-Za-z0-9_\-]{1,128}$/ rejette,
            # setToken() ne stocke rien -> 401 systematiques + saturation rate-limit
            # (ce dernier desormais corrige par exemption localhost, mais le token
            # absent doit etre fixe a la source).
            # FIX : on utilise rest_server._token, deja resolu (et clair) dans
            # _start_rest_server via lecture brute settings.json en utf-8-sig.
            # Defense en profondeur : strip + suppression d'eventuel BOM U+FEFF.
            _desktop_dashboard_token = str(getattr(rest_server, "_token", "") or "")
            # Defense en profondeur : strip whitespace + suppression d'un eventuel
            # BOM UTF-8 (U+FEFF / ZWNBSP) qui pourrait survivre a la lecture brute
            # si settings.json a ete sauve par PowerShell sans -Encoding utf8.
            _desktop_dashboard_token = _desktop_dashboard_token.strip().replace("﻿", "")
            # DEBUG VERBOSE 2026-06-08 : dump codepoints du token tel quel
            # APRES recuperation depuis rest_server._token + strip. Permet de
            # detecter une corruption survenue entre _start_rest_server et ici.
            _DEBUG_NB = str(os.environ.get("CINESORT_DEBUG") or "").strip().lower() in {
                "1",
                "true",
                "yes",
                "on",
                "debug",
            }
            if _DEBUG_NB:
                try:
                    cps = [f"U+{ord(c):04X}" for c in _desktop_dashboard_token]
                    non_ascii = [(i, c, ord(c)) for i, c in enumerate(_desktop_dashboard_token) if ord(c) > 0x7F]
                    print(
                        f"[DEBUG-NTOKEN] _desktop_dashboard_token len={len(_desktop_dashboard_token)} codepoints={cps}",
                        file=sys.stderr,
                    )
                    for i, c, o in non_ascii:
                        print(
                            f"[DEBUG-NTOKEN] NON-ASCII pos={i} char={c!r} U+{o:04X}",
                            file=sys.stderr,
                        )
                except Exception as _dbg_exc:  # noqa: BLE001 — debug only
                    print(f"[DEBUG-NTOKEN] dump failed: {_dbg_exc}", file=sys.stderr)
            if _desktop_dashboard_token:
                _encoded_token = quote(_desktop_dashboard_token)
                main_url = f"{proto}://127.0.0.1:{port}/dashboard/?ntoken={_encoded_token}&native=1"
                # ITER15 5.2 : reduire verbosite — l'URL main_url avec ntoken
                # tronque est un detail de boot natif normal, pas une condition
                # d'erreur. Logge uniquement en mode CINESORT_DEBUG. Le bypass
                # loopback rend de toute facon l'absence de token benigne en
                # local. GARDE-FOU : ne change pas la matrice auth iter5/iter14.
                if _DEBUG_NB:
                    print(
                        f"[REST] main_url = {proto}://127.0.0.1:{port}/dashboard/?ntoken={_desktop_dashboard_token[:8]}...&native=1",
                        file=sys.stderr,
                    )
                    print(
                        f"[DEBUG-NTOKEN] url-encoded ntoken={_encoded_token!r} "
                        f"(len_raw={len(_desktop_dashboard_token)} len_encoded={len(_encoded_token)})",
                        file=sys.stderr,
                    )
                    # Detecter si l'encodage a transforme un % qui revele BOM/non-ASCII
                    if "%" in _encoded_token:
                        print(
                            f"[DEBUG-NTOKEN] ATTENTION : ntoken contient %-escapes "
                            f"(probable codepoint > 0x7F encode) -> {_encoded_token}",
                            file=sys.stderr,
                        )
            else:
                main_url = f"{proto}://127.0.0.1:{port}/dashboard/?native=1"
                # ITER15 5.2 + 5.4 : token vide reste une condition d'erreur (en
                # mode web/LAN, l'utilisateur ne peut pas se connecter ; en mode
                # natif, le bypass loopback peut sauver mais reste un signal
                # anormal). On migre vers logger.error pour beneficier du
                # scrubber et de la categorisation centralisee (deja preparee
                # iter5). ITER15 5.4 enrichit le contexte diagnostic (proto,
                # port, native, type) pour faciliter le tri post-mortem.
                # GARDE-FOU : ne change pas la matrice auth iter5/iter14.
                import logging as _logging_nb

                _logger_nb = _logging_nb.getLogger("cinesort.app.native_boot")
                _token_type = type(_desktop_dashboard_token).__name__
                _logger_nb.error(
                    "REST main_url sans ntoken — auth web/LAN impossible, "
                    "bypass loopback requis pour mode natif "
                    "[diag: proto=%s port=%s token_type=%s token_falsy=%r native=1]",
                    proto,
                    port,
                    _token_type,
                    not _desktop_dashboard_token,
                )
        else:
            # Fallback : charger l'index local (mode preview ou serveur REST mort)
            index = resource_path(index_rel)
            main_url = Path(index).resolve().as_uri()
            _desktop_dashboard_token = ""

        # Note 2026-05-20 fix ecran noir : main_window N EST PLUS hidden=True.
        # Avec hidden=True, pywebview/WebView2 retardait l initialisation reelle
        # du HWND tant que show() n etait pas appele, et evaluate_js levait
        # "Main window failed to start" meme apres show() (l init async n etait
        # pas terminee). Resultat : token + native flag jamais injectes -> noir.
        # Sans hidden, la window est initialisee des create_window et evaluate_js
        # fonctionne tout de suite. Le splash frameless reste sur on_top pour
        # masquer le boot visuel.
        # Fix audit 2026-05-25 (v1.5.4) : background_color cohérent avec le
        # thème luxe (#0a0a0f matche le gradient du splash) au lieu du blanc/
        # noir par défaut. Si jamais la main window deborde du splash pendant
        # le chargement WebView2, l'utilisateur voit du dark cohérent, pas du
        # noir choquant.
        main_window = webview.create_window(
            title,
            url=main_url,
            js_api=api,
            width=1250,
            height=820,
            min_size=(1000, 700),
            background_color="#0a0a0f",
        )

        # Fix 2026-05-24 ecran noir post-v1.3.0 :
        # On utilise main_window.events.loaded comme signal de synchronisation
        # propre, au lieu d'un retry aveugle sleep(0.4)+evaluate_js. L'event est
        # firing par pywebview/WebView2 quand le dashboard a fini de charger,
        # garantissant que le bus JS-Python est pret avant toute manipulation.
        #
        # NB : l'inject_js precedent etait REDONDANT avec l'IIFE _detectNativeBoot
        # (web/dashboard/app.js:75-112) qui lit deja `?ntoken=...&native=1` depuis
        # l'URL et fait tout le bootstrap (setToken, localStorage native, force
        # hash #/accueil, etc.). On le supprime completement.
        import threading as _threading_evt

        _loaded_event = _threading_evt.Event()

        def _on_main_loaded() -> None:
            _loaded_event.set()
            _log.info("main_window: dashboard charge (events.loaded firing)")

        try:
            main_window.events.loaded += _on_main_loaded
        except Exception as _evt_exc:
            # Fix audit 2026-05-24 : si l'attachement events.loaded echoue
            # (backend pywebview incompatible, etc.), le _loaded_event.wait()
            # plus loin attendrait 20s inutilement puis declencherait l'auto-purge
            # alors que l'app peut tres bien fonctionner via l'URL ntoken seule.
            # On set immediatement l'event pour eviter ce faux positif :
            # l'IIFE _detectNativeBoot du frontend fera tout le bootstrap natif.
            _log.warning(
                "main_window: impossible d'attacher events.loaded (%s) - fallback URL ntoken",
                _evt_exc,
            )
            _loaded_event.set()

        # --- 3. Fonction de startup (tourne dans le thread webview) ---
        def _startup() -> None:
            try:
                _log.info("splash: etape 1 — Initialisation")
                _update_splash(splash, 1, "Initialisation...", 10)
                _time.sleep(0.15)

                _log.info("splash: etape 2 — Chargement des reglages")
                _update_splash(splash, 2, "Chargement des reglages...", 25)
                settings = api.settings.get_settings()
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

                # Version dans le splash (issue #64 : json.dumps pour echappement sur)
                try:
                    version = getattr(api, "_app_version", "")
                    if version:
                        import json as _json

                        splash.evaluate_js(f"setVersion({_json.dumps(f'v{version}')})")  # type: ignore[union-attr]
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

                # Spec 09 §5 (Historique) : cron retention 90j par defaut, demarre
                # un thread daemon qui purge les vieux runs toutes les 24h.
                # Configurable via setting `history_retention_days` (defaut 90,
                # 0 desactive).
                try:
                    from cinesort.app.retention_cleanup import start_retention_cron

                    retention_days = int(settings.get("history_retention_days") or 90)
                    start_retention_cron(api, retention_days=retention_days)
                except (ImportError, OSError, RuntimeError, TypeError, ValueError) as _ret_exc:
                    _log.warning("spec 09: retention cron init echouee — %s", _ret_exc)

                # VQ-2 QUARANTAINE-TTL : cron TTL bucket FS `_review`
                # (defaut 30j, 0 desactive). Le cron tourne toutes les 24h.
                try:
                    from cinesort.app.quarantine_ttl import (
                        DEFAULT_TTL_DAYS as _Q_DEFAULT_TTL,
                    )
                    from cinesort.app.quarantine_ttl import (
                        start_quarantine_ttl_cron,
                    )

                    quarantaine_ttl = int(settings.get("quarantaine_ttl_days") or _Q_DEFAULT_TTL)
                    start_quarantine_ttl_cron(api, ttl_days=quarantaine_ttl)
                except (ImportError, OSError, RuntimeError, TypeError, ValueError) as _qttl_exc:
                    _log.warning("vq-2: quarantine ttl cron init echouee — %s", _qttl_exc)

                # Fix 2026-05-24 ecran noir post-v1.3.0 :
                # Le bootstrap natif (token, mode native, force #/accueil) est
                # entierement gere par l'IIFE _detectNativeBoot dans
                # web/dashboard/app.js:75-112 qui lit `?ntoken=XXX&native=1`
                # depuis l'URL. Plus aucun evaluate_js ici - on attend
                # juste events.loaded comme signal de chargement reussi.
                _log.info("splash: etape finale — Pret")
                # Fix audit 2026-05-24 (v1.5.1) : message honnete - le splash
                # restait visible avec "Pret !" pendant 5-30s d'attente
                # events.loaded (cache WebView2 a chauffer apres update EXE),
                # main_window noire pendant ce temps -> user voit "2 fenetres
                # et la grande reste noire" avec un message qui ment.
                # Si events.loaded firing rapidement (cache chaud), aucun delai
                # visible. Si lent, le user comprend que ca charge encore.
                _update_splash(splash, 7, "Chargement du dashboard...", 100)

                # Attendre que le dashboard ait fini de charger (soft 60s).
                # Si timeout : cache WebView2 corrompu -> auto-purge + exit propre.
                # 60s est large : tests reels montrent qu'apres purge cache,
                # WebView2 met 20-30s a reconstruire son profil (CSP, ServiceWorker,
                # IndexedDB origins). Mesure : ~3s avec cache propre, ~21s apres
                # purge, parfois 30-45s sur premieres ouvertures post-update.
                if not _loaded_event.wait(timeout=60):
                    _log.error("main_window: events.loaded n'a pas firing dans 60s -> auto-purge cache WebView2")
                    try:
                        import shutil as _shutil

                        _eb_dir = default_state_dir() / "webview" / "EBWebView"
                        if _eb_dir.exists():
                            _shutil.rmtree(str(_eb_dir), ignore_errors=True)
                            _log.info("main_window: cache EBWebView purge (%s)", _eb_dir)
                    except Exception as _purge_exc:
                        _log.warning("main_window: purge cache echouee — %s", _purge_exc)
                    try:
                        _update_splash(
                            splash,
                            7,
                            "Cache WebView2 corrompu - relancez l'application",
                            100,
                        )
                    except Exception:
                        pass
                    _time.sleep(3.0)
                    # Fix audit 2026-05-24 : main_window.destroy() declenche la fin
                    # de webview.start() qui retourne au main(), permettant au
                    # finally L808-833 de liberer InstanceLock, fermer REST,
                    # arreter notify, fermer stores. Le precedent os._exit(1)
                    # bypass-ait tout ce cleanup -> lock orphelin au prochain run.
                    with contextlib.suppress(Exception):
                        splash.destroy()
                    with contextlib.suppress(Exception):
                        main_window.destroy()
                    return  # quitte _startup; webview event loop terminera proprement

                _log.info("splash: fenetre principale chargee, splash detruit")
                with contextlib.suppress(Exception):
                    splash.destroy()

            except Exception as exc:
                _log.error("splash: erreur startup — %s", exc)
                # En cas d'erreur, garantir que la fenetre principale est visible
                try:
                    if api:
                        api._window = main_window
                        api._notify.set_window(main_window)
                except Exception:
                    pass
                with contextlib.suppress(Exception):
                    splash.destroy()

        # private_mode=False : autorise localStorage/sessionStorage persistants
        # (sinon le token bypass login est purge au reload, login obligatoire).
        # storage_path : isole le storage CineSort dans %LOCALAPPDATA%/CineSort/webview.
        _storage_dir = default_state_dir() / "webview"
        _storage_dir.mkdir(parents=True, exist_ok=True)
        # VN-A.5 : DevTools (F12) actif uniquement en mode developpeur. Triggers :
        #   - env CINESORT_DEBUG=1/true/yes/on
        #   - env DEV_MODE=1 ou flag CLI --dev (cf is_dev_mode)
        #   - flag file %APPDATA%/CineSort/debug.flag present
        # En prod (sans aucun de ces triggers), F12 est inerte -> evite que
        # l'utilisateur final tombe sur les internes WebView2 par accident.
        _debug_flag_file = Path(os.environ.get("APPDATA", ".")) / "CineSort" / "debug.flag"
        _devtools_enabled = (
            str(os.environ.get("CINESORT_DEBUG") or "").strip().lower() in {"1", "true", "yes", "on", "debug"}
            or is_dev_mode()
            or _debug_flag_file.exists()
        )
        if _devtools_enabled:
            _log.info("DevTools active (mode developpeur detecte)")
        webview.start(
            _startup,
            debug=_devtools_enabled,
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
        # Cf issue #68 : liberer le verrou inter-process en dernier (apres
        # arret du REST et fermeture des stores). Garantit qu'au prochain
        # lancement le lock est dispo.
        try:
            instance_lock.release()
        except Exception as _exc:  # noqa: BLE001 — shutdown must continue
            _log.warning("instance_lock release failed (ignored): %s", _exc)


if __name__ == "__main__":
    main()

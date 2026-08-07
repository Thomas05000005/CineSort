"""V3-09 — Reset all user data (avec backup de securite).

Phase 4 backend-parametres-endpoints (spec 11 §5 Reset) :
Ajout de `reset_settings(scope)` (par categorie) et `reset_database()` (wipe DB
seulement, avec backup).
"""

from __future__ import annotations

import contextlib
import logging
import os
import shutil
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from cinesort.domain.i18n_messages import t
from cinesort.ui.api import settings_support as _settings_support
from cinesort.ui.api._responses import err as _err_response

logger = logging.getLogger(__name__)


# Mapping scope -> liste de cles settings a reset.
# Aligne sur spec 11 §2 (10 categories) + scope "all".
# Note : "profils-qualite" ne reset PAS la DB du profil actif, juste
# settings.active_quality_profile_id + settings.custom_quality_profiles
# (le reset complet du profil store passe par reset_quality_profile).
_RESET_SCOPE_KEYS: Dict[str, List[str]] = {
    "sources": ["root", "roots", "root_example"],
    "analyse": [
        "probe_backend",
        "mediainfo_path",
        "ffprobe_path",
        "probe_timeout_s",
        "probe_workers",
        "probe_parallelism_enabled",
        "incremental_scan_enabled",
        "quarantine_unapproved",
        "auto_quarantine_corrupted",
        "perceptual_enabled",
        "perceptual_auto_on_scan",
        "perceptual_auto_on_quality",
        "perceptual_timeout_per_film_s",
        "perceptual_frames_count",
        "perceptual_skip_percent",
        "perceptual_dark_weight",
        "perceptual_audio_deep",
        "perceptual_audio_segment_s",
        "perceptual_comparison_frames",
        "perceptual_comparison_timeout_s",
        "perceptual_parallelism_mode",
        "perceptual_parallelism_enabled",
        "perceptual_workers",
        "perceptual_audio_fingerprint_enabled",
        "perceptual_scene_detection_enabled",
        "perceptual_audio_spectral_enabled",
        "perceptual_ssim_self_ref_enabled",
        "perceptual_hdr10_plus_detection_enabled",
        "perceptual_interlacing_detection_enabled",
        "perceptual_crop_detection_enabled",
        "perceptual_judder_detection_enabled",
        "perceptual_grain_intelligence_enabled",
        "perceptual_audio_mel_enabled",
        "perceptual_lpips_enabled",
        "subtitle_detection_enabled",
        "subtitle_expected_languages",
    ],
    "nommage": [
        "naming_preset",
        "naming_movie_template",
        "naming_tv_template",
    ],
    "bibliotheque": [
        "collection_folder_enabled",
        "collection_folder_name",
        "enable_tv_detection",
        "move_empty_folders_enabled",
        "empty_folders_folder_name",
        "empty_folders_scope",
        "cleanup_residual_folders_enabled",
        "cleanup_residual_folders_folder_name",
        "cleanup_residual_folders_scope",
        "cleanup_residual_include_nfo",
        "cleanup_residual_include_images",
        "cleanup_residual_include_subtitles",
        "cleanup_residual_include_texts",
    ],
    "integrations": [
        # TMDb
        "tmdb_enabled",
        "tmdb_timeout_s",
        "tmdb_cache_ttl_days",
        # Jellyfin
        "jellyfin_enabled",
        "jellyfin_url",
        "jellyfin_user_id",
        "jellyfin_refresh_on_apply",
        "jellyfin_sync_watched",
        "jellyfin_timeout_s",
        # Plex
        "plex_enabled",
        "plex_url",
        "plex_library_id",
        "plex_refresh_on_apply",
        "plex_timeout_s",
        # Radarr
        "radarr_enabled",
        "radarr_url",
        "radarr_timeout_s",
        # OMDb
        "omdb_enabled",
        "omdb_min_confidence_for_call",
    ],
    "notifications": [
        "notifications_enabled",
        "notifications_scan_triggered",
        "notifications_scan_done",
        "notifications_apply_done",
        "notifications_undo_done",
        "notifications_errors",
        "email_enabled",
        "email_smtp_host",
        "email_smtp_port",
        "email_smtp_user",
        "email_smtp_tls",
        "email_to",
        "email_on_scan",
        "email_on_apply",
        "plugins_enabled",
        "plugins_timeout_s",
    ],
    "serveur": [
        "rest_api_enabled",
        "rest_api_port",
        "rest_api_cors_origin",
        "rest_api_https_enabled",
        "rest_api_cert_path",
        "rest_api_key_path",
        # Pas de reset du rest_api_token (sera regenere par apply_settings_defaults)
    ],
    "apparence": [
        "theme",
        "animation_level",
        "effect_speed",
        "glow_intensity",
        "light_intensity",
        "locale",
    ],
    "profils-qualite": [
        "active_quality_profile_id",
        "custom_quality_profiles",
    ],
    "avance": [
        "expert_mode",
        "onboarding_completed",
        "update_check_enabled",
        "update_check_channel",
        "update_github_repo",
        "watch_enabled",
        "watch_interval_minutes",
        "log_level",
        "composite_score_version",
        "auto_approve_enabled",
        "auto_approve_threshold",
        "dry_run_apply",
    ],
}


def _valid_reset_scopes() -> List[str]:
    return ["all", *_RESET_SCOPE_KEYS.keys()]


def _resolve_state_dir(api: Any) -> Optional[Path]:
    """Recupere le state_dir de l'API.

    Supporte les deux conventions :
    - methode `_get_state_dir()` (utilisee par les fakes de tests)
    - attribut `_state_dir` (utilise par CineSortApi en production)
    """
    if hasattr(api, "_get_state_dir"):
        try:
            value = api._get_state_dir()
        except (AttributeError, OSError, TypeError, ValueError) as exc:
            logger.warning("reset_support: _get_state_dir a echoue (%s), fallback _state_dir", exc)
            value = None
        if value:
            return Path(value)
    if hasattr(api, "_state_dir"):
        value = getattr(api, "_state_dir", None)
        if value:
            return Path(value)
    return None


def reset_all_user_data(api: Any, confirmation_text: str) -> dict:
    """V3-09 — Reinitialise toutes les donnees utilisateur.

    Etapes :
    1. Verifier que confirmation_text == "RESET"
    2. Creer un backup ZIP du dossier user-data complet
    3. Supprimer : DB SQLite, settings.json, runs/, cache TMDb, perceptual reports
    4. Preserver : logs (utiles pour debug si reset cause un probleme)

    Returns:
        {ok: bool, backup_path?: str, removed?: list[str], error?: str}
    """
    if confirmation_text != "RESET":
        return _err_response(
            "Confirmation invalide (attendu 'RESET')",
            category="validation",
            level="info",
            log_module=__name__,
            key="error",
        )

    state_path = _resolve_state_dir(api)
    if state_path is None or not state_path.exists():
        return _err_response(
            "Dossier user-data introuvable", category="state", level="info", log_module=__name__, key="error"
        )

    backup_stem = state_path.parent / f"cinesort_backup_before_reset_{int(time.time())}"
    backup_path = backup_stem.with_suffix(".zip")

    try:
        # 1. Backup securite : ZIP complet du dossier user-data
        logger.info("V3-09 : creation backup avant reset -> %s", backup_path)
        shutil.make_archive(str(backup_stem), "zip", root_dir=str(state_path))

        # 2. Suppression selective (preserve logs/)
        removed: list[str] = []
        for item in state_path.iterdir():
            if item.name == "logs":
                continue
            if item.is_dir():
                shutil.rmtree(item, ignore_errors=True)
            else:
                try:
                    item.unlink(missing_ok=True)
                except OSError:
                    continue
            removed.append(item.name)

        logger.warning(
            "V3-09 : reset complet effectue (%d items supprimes). Backup : %s",
            len(removed),
            backup_path,
        )
        return {
            "ok": True,
            "backup_path": str(backup_path),
            "removed": removed,
        }
    except (OSError, shutil.Error) as exc:
        logger.exception("V3-09 : echec reset")
        return _err_response(str(exc), category="runtime", level="error", log_module=__name__, key="error")


def get_user_data_size(api: Any) -> dict:
    """V3-09 — Retourne la taille du dossier user-data (pour affichage UI)."""
    state_path = _resolve_state_dir(api)
    if state_path is None or not state_path.exists():
        return {"size_mb": 0, "items": 0}

    total = 0
    items = 0
    for f in state_path.rglob("*"):
        if f.is_file():
            try:
                total += f.stat().st_size
                items += 1
            except OSError:
                continue
    return {
        "size_mb": round(total / (1024 * 1024), 2),
        "items": items,
    }


# ---------------------------------------------------------------------------
# Phase 4 backend-parametres-endpoints (spec 11 §5 Reset)
# ---------------------------------------------------------------------------


def _build_default_settings(api: Any) -> Dict[str, Any]:
    """Construit le payload settings 100 % par defaut (sans aucune valeur user).

    Utilise `apply_settings_defaults({}, ...)` avec les memes constantes que
    `_get_settings_impl`.
    """
    # #779 : `cinesort_api` reste differe — c'est un VRAI cycle, il importe
    # `reset_support` en tete (cinesort_api.py:82). `settings_support`, lui, est
    # remonte en tete : aucune arete de retour vers `reset_support`, et
    # l'argument « blast radius » qui figurait ici etait faux — `cinesort_api.py`
    # importe DEJA les deux modules en tete (lignes 82 et 88), donc les deux sont
    # charges au boot quoi qu'il arrive.
    from cinesort.ui.api import cinesort_api as _api_mod

    state_dir = _resolve_state_dir(api) or Path(os.environ.get("LOCALAPPDATA", ".")) / "CineSort"
    return _settings_support.apply_settings_defaults(
        {},
        state_dir=state_dir,
        default_root=getattr(_api_mod, "DEFAULT_ROOT", str(Path.home() / "Videos" / "Movies")),
        default_state_dir_example=getattr(_api_mod, "DEFAULT_STATE_DIR_EXAMPLE", str(state_dir)),
        default_collection_folder_name=getattr(_api_mod, "DEFAULT_COLLECTION_FOLDER_NAME", "Collections"),
        default_empty_folders_folder_name=getattr(_api_mod, "DEFAULT_EMPTY_FOLDERS_FOLDER_NAME", "_empty"),
        default_residual_cleanup_folder_name=getattr(_api_mod, "DEFAULT_RESIDUAL_CLEANUP_FOLDER_NAME", "_review"),
        default_probe_backend=getattr(_api_mod, "DEFAULT_PROBE_BACKEND", "auto"),
        debug_enabled=False,
    )


def reset_settings(api: Any, scope: str = "all", *, dry_run: bool = True) -> Dict[str, Any]:
    """Reinitialise les settings (totalement ou par categorie).

    Cf spec 11 §5 Reset. Scope :
      - "all" : reset complet vers les defauts
      - "sources" / "analyse" / "nommage" / "bibliotheque" / "integrations" /
        "notifications" / "serveur" / "apparence" / "profils-qualite" / "avance"

    `dry_run` VAUT True PAR DEFAUT. Cette methode est exposee en
    `POST /api/settings/reset_settings` et n'a AUCUN argument obligatoire : un
    appel au corps vide reinitialisait donc l'integralite des reglages
    (`scope="all"`). Sur une frontiere destructive, l'omission doit produire
    l'APERCU, jamais l'effet. L'appelant dont le travail EST de reinitialiser
    le dit explicitement — c'est un parametre visible en revue, plus un defaut
    invisible.

    Retourne {ok, reset_keys: [...], scope, dry_run}. En apercu, `reset_keys`
    porte EXACTEMENT ce que l'application aurait remis a zero.
    """
    scope_norm = str(scope or "all").strip().lower()
    if scope_norm not in _valid_reset_scopes():
        return _err_response(
            f"Scope inconnu : {scope!r}. Valides : {_valid_reset_scopes()}",
            category="validation",
            level="info",
            log_module=__name__,
        )

    try:
        defaults = _build_default_settings(api)
    except (ImportError, OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(
            f"Echec construction defaults : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    # Si scope = all, on persiste tout le payload defauts
    if scope_norm == "all":
        if dry_run:
            return {
                "ok": True,
                "scope": "all",
                "reset_keys": sorted(defaults.keys()),
                "dry_run": True,
            }
        try:
            api.settings.save_settings(defaults)
        except (AttributeError, OSError, KeyError, TypeError, ValueError) as exc:
            return _err_response(
                f"Echec sauvegarde defaults : {exc}",
                category="runtime",
                level="error",
                log_module=__name__,
            )
        return {
            "ok": True,
            "scope": "all",
            "reset_keys": sorted(defaults.keys()),
            "dry_run": False,
        }

    # Scope cible : on lit les settings courants et on remplace cle par cle
    try:
        current = api.settings.get_settings() or {}
    except (AttributeError, OSError, TypeError, ValueError) as exc:
        return _err_response(
            f"Echec lecture settings : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    keys = _RESET_SCOPE_KEYS.get(scope_norm, [])
    reset_keys: List[str] = []
    patched = dict(current)
    for key in keys:
        if key in defaults:
            patched[key] = defaults[key]
            reset_keys.append(key)
        else:
            # Cle sans default litteral : on la retire pour qu'apply_settings_defaults
            # remette la valeur derivee au prochain get_settings.
            patched.pop(key, None)
            reset_keys.append(key)

    if dry_run:
        return {
            "ok": True,
            "scope": scope_norm,
            "reset_keys": reset_keys,
            "dry_run": True,
        }

    try:
        api.settings.save_settings(patched)
    except (AttributeError, OSError, KeyError, TypeError, ValueError) as exc:
        return _err_response(
            f"Echec sauvegarde scope {scope_norm} : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    return {
        "ok": True,
        "scope": scope_norm,
        "reset_keys": reset_keys,
        "dry_run": False,
    }


def _resolve_db_path(api: Any) -> Optional[Path]:
    """Retrouve le chemin canonique du fichier SQLite dans le state_dir.

    AUDIT 2026-06-10 (REAL 2/2) : retournait `state_dir/cinesort.db` alors que la
    vraie DB est `state_dir/db/cinesort.sqlite` (db_path_for_state_dir). db_path
    .exists() etait donc toujours False -> reset_database retournait ok=True
    "Aucune DB existante a supprimer" : le wipe DB promis par l'UI ne se
    produisait JAMAIS, sans erreur visible.
    """
    state_path = _resolve_state_dir(api)
    if state_path is None:
        return None
    from cinesort.infra.db import db_path_for_state_dir  # noqa: PLC0415

    return db_path_for_state_dir(state_path)


def reset_database(api: Any, *, dry_run: bool = True) -> Dict[str, Any]:
    """Wipe complet de la DB SQLite (films, runs, perceptual, scores, etc.).

    Backup automatique avant suppression vers
    `<state_dir>/db/backups/wipe_<timestamp>.bak`.

    IRREVERSIBLE cote DB mais le backup permet une restauration manuelle.
    Les settings.json et logs/ sont preserves.

    `dry_run` VAUT True PAR DEFAUT. C'est la methode la plus destructive de
    toute la surface REST, elle est exposee en
    `POST /api/settings/reset_database`, et elle n'a AUCUN argument obligatoire :
    un appel au corps vide effacait donc toute la bibliotheque de l'utilisateur.

    Retourne {ok, backup_path, removed_db_path, dry_run}. En apercu, la reponse
    porte en plus `db_size_bytes` et le chemin de sauvegarde QUI SERAIT ecrit,
    et RIEN n'est touche : ni backup, ni fermeture de connexion, ni suppression.
    """
    state_path = _resolve_state_dir(api)
    if state_path is None:
        return _err_response(
            "Dossier user-data introuvable.",
            category="state",
            level="warning",
            log_module=__name__,
        )

    db_path = _resolve_db_path(api)
    if db_path is None:
        return _err_response(
            "Chemin DB introuvable.",
            category="state",
            level="warning",
            log_module=__name__,
        )

    if not db_path.exists():
        # Pas de DB a supprimer : on retourne ok=True avec backup_path=""
        return {
            "ok": True,
            "backup_path": "",
            "removed_db_path": str(db_path),
            "message": t("danger_zone.no_database_to_delete"),
        }

    if dry_run:
        # Apercu STRICT : on ne cree meme pas le dossier de sauvegarde. La seule
        # I/O est un `stat` en lecture — un apercu qui ecrirait sur le disque ne
        # serait plus un apercu.
        taille = 0
        with contextlib.suppress(OSError):
            taille = int(db_path.stat().st_size)
        return {
            "ok": True,
            "dry_run": True,
            "backup_path": "",
            "removed_db_path": "",
            "db_path": str(db_path),
            "db_size_bytes": taille,
            "backup_dir": str(state_path / "db" / "backups"),
        }

    backup_dir = state_path / "db" / "backups"
    try:
        backup_dir.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        return _err_response(
            f"Impossible de creer le dossier de backup : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

    timestamp = int(time.time())
    backup_path = backup_dir / f"wipe_{timestamp}.bak"

    # On essaie d'utiliser sqlite3 backup API (cf cinesort/infra/db) si on peut,
    # sinon copy2 (la DB est rarement ecrite pendant un reset, c'est suffisant).
    try:
        # 1) Tentative : fermer les connexions de l'API si disponibles
        if hasattr(api, "_close_infra"):
            try:
                api._close_infra()
            except (AttributeError, OSError, TypeError) as exc:
                logger.warning("reset_database: _close_infra a echoue (%s), continue.", exc)

        # 2) Backup par copie
        shutil.copy2(str(db_path), str(backup_path))
        logger.info("reset_database: backup cree -> %s", backup_path)

        # 3) Suppression
        db_path.unlink()
        # Supprime aussi les fichiers WAL/SHM associes
        for suffix in ("-wal", "-shm"):
            ancillary = db_path.with_name(db_path.name + suffix)
            with contextlib.suppress(OSError):
                ancillary.unlink(missing_ok=True)

        logger.warning(
            "reset_database: DB supprimee %s, backup conserve : %s",
            db_path,
            backup_path,
        )
        return {
            "ok": True,
            "backup_path": str(backup_path),
            "removed_db_path": str(db_path),
            "dry_run": False,
        }
    except (OSError, shutil.Error) as exc:
        logger.exception("reset_database: echec")
        return _err_response(
            f"Echec reset DB : {exc}",
            category="runtime",
            level="error",
            log_module=__name__,
        )

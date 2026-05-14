from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import cinesort.domain.core as core
import cinesort.infra.state as state
from cinesort.domain.i18n_messages import t
from cinesort.infra.tmdb_client import TmdbClient
from cinesort.domain.conversions import to_bool, to_float, to_int
from cinesort.ui.api._responses import err
from cinesort.infra.local_secret_store import (
    SECRET_PROTECTION_NONE,
    SECRET_PROTECTION_UNAVAILABLE,
    WINDOWS_DPAPI_CURRENT_USER,
    protect_secret,
    unprotect_secret,
)

logger = logging.getLogger(__name__)

TMDB_KEY_SECRET_FIELD = "tmdb_api_key_secret"
TMDB_KEY_PROTECTION_LEGACY = "plaintext_legacy"
TMDB_KEY_PURPOSE = "tmdb_api_key"

JELLYFIN_KEY_SECRET_FIELD = "jellyfin_api_key_secret"
JELLYFIN_KEY_PURPOSE = "jellyfin_api_key"

# S4 audit : etendre DPAPI aux secrets qui etaient stockes en clair (Plex token,
# Radarr API key, SMTP password). Chaque secret a sa propre purpose/entropy pour
# l'isolation cryptographique.
PLEX_TOKEN_SECRET_FIELD = "plex_token_secret"
PLEX_TOKEN_PURPOSE = "plex_token"

RADARR_KEY_SECRET_FIELD = "radarr_api_key_secret"
RADARR_KEY_PURPOSE = "radarr_api_key"

SMTP_PASSWORD_SECRET_FIELD = "email_smtp_password_secret"
SMTP_PASSWORD_PURPOSE = "email_smtp_password"

# Audit ID-J-001 : backup auto + rotation 5 sur settings.json (V1-M10).
# Chaque write_settings cree un .bak.YYYYMMDD-HHMMSS prealable, puis purge
# au-dela des 5 plus recents. Protection contre erreurs utilisateur (vidage
# champ critique, custom rules JSON casse) et corruption disque.
DEFAULT_SETTINGS_BACKUP_COUNT = 5
SETTINGS_BACKUP_PREFIX = ".bak."


def _backup_settings_before_write(settings_path: Path) -> Optional[Path]:
    """Cree un backup horodate de settings.json avant ecriture.

    Retourne le path du backup cree, ou None si pas applicable
    (settings.json absent, JSON corrompu, ou copie echouee).
    """
    if not settings_path.exists():
        return None
    try:
        # Verifie que le settings actuel est lisible (evite cascade backup d'un fichier corrompu)
        json.loads(settings_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None
    # Microsecondes pour rester unique meme si plusieurs writes dans la meme
    # seconde (sinon les backups s'ecrasent et la rotation perd des fichiers).
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup_path = settings_path.parent / f"{settings_path.name}{SETTINGS_BACKUP_PREFIX}{ts}"
    try:
        shutil.copy2(settings_path, backup_path)
        return backup_path
    except OSError:
        return None


def _rotate_settings_backups(settings_path: Path, keep: int = DEFAULT_SETTINGS_BACKUP_COUNT) -> int:
    """Garde les `keep` derniers backups, supprime les plus anciens.

    Retourne le nombre de backups supprimes.
    """
    pattern = f"{settings_path.name}{SETTINGS_BACKUP_PREFIX}*"
    backups = sorted(
        settings_path.parent.glob(pattern),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    deleted = 0
    for old in backups[keep:]:
        try:
            old.unlink()
            deleted += 1
        except OSError:
            pass
    return deleted


def _extract_protected_secret(
    data: Dict[str, Any],
    *,
    secret_field: str,
    legacy_field: str,
    purpose: str,
) -> Tuple[str, str, str]:
    """Lecture generique d'un secret DPAPI depuis le payload settings.

    Retourne (valeur_clair, scheme, warning). Le scheme est soit
    WINDOWS_DPAPI_CURRENT_USER, soit TMDB_KEY_PROTECTION_LEGACY (en clair,
    migration automatique au prochain write), soit SECRET_PROTECTION_NONE (vide).
    """
    secret_payload = data.get(secret_field)
    if isinstance(secret_payload, dict):
        scheme = str(secret_payload.get("scheme") or "").strip().lower()
        blob_b64 = str(secret_payload.get("blob_b64") or "").strip()
        if scheme == WINDOWS_DPAPI_CURRENT_USER and blob_b64:
            ok, value, error = unprotect_secret(blob_b64, purpose=purpose)
            if ok:
                return value, WINDOWS_DPAPI_CURRENT_USER, ""
            return "", WINDOWS_DPAPI_CURRENT_USER, f"Secret protege illisible ({purpose}): {error}"

    legacy = str(data.get(legacy_field) or "").strip()
    if legacy:
        return legacy, TMDB_KEY_PROTECTION_LEGACY, ""
    return "", SECRET_PROTECTION_NONE, ""


def _persist_protected_secret(
    payload: Dict[str, Any],
    *,
    legacy_field: str,
    secret_field: str,
    purpose: str,
) -> Tuple[bool, str]:
    """Chiffre le secret du payload s'il est non-vide. Consomme le champ legacy.

    Effet de bord sur `payload` : retire le champ legacy et installe le blob
    chiffre dans `secret_field` en cas de succes.

    Retourne (persisted, warning_message).
    """
    raw = str(payload.pop(legacy_field, "") or "").strip()
    payload.pop(secret_field, None)
    if not raw:
        return False, ""
    ok, blob_b64, error = protect_secret(raw, purpose=purpose)
    if ok and blob_b64:
        payload[secret_field] = {
            "scheme": WINDOWS_DPAPI_CURRENT_USER,
            "blob_b64": blob_b64,
        }
        return True, ""
    return False, f"Protection indisponible ({purpose}): {error}" if error else f"Protection indisponible ({purpose})."


def _normalize_jellyfin_url(url: str) -> str:
    """Normalise l'URL Jellyfin (strip, trailing slash, prefix http)."""
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url


def _normalize_lang_list(raw: Any) -> List[str]:
    """Normalise une liste de codes langue depuis le payload settings."""
    if isinstance(raw, list):
        return [str(l).strip().lower() for l in raw if str(l).strip()]
    if isinstance(raw, str) and raw.strip():
        return [l.strip().lower() for l in raw.split(",") if l.strip()]
    return ["fr"]


def clamp_year(value: int) -> int:
    if 1900 <= value <= 2100:
        return value
    return 0


def normalize_user_path(value: Any, default: Path) -> Path:
    """Normalise un chemin user-fourni (expanduser + expandvars).

    Cf issue #73 (audit-2026-05-12:a4b6) : si la requete vient d'un client REST
    distant, on n'expand PAS les variables d'environnement (%USERPROFILE%,
    %TEMP%, %APPDATA%) qui exposeraient le filesystem du serveur. expanduser
    reste actif (~ → home directory) car non-amplifiant. Pour le caller local
    (desktop natif), comportement inchange.
    """
    from cinesort.infra.log_context import is_remote_request

    raw = str(value or "").strip().strip('"').strip("'")
    if not raw:
        return Path(default)
    if is_remote_request():
        # Pas d'expandvars cote REST distant — empeche path manipulation
        # via env vars du serveur.
        return Path(os.path.expanduser(raw))
    expanded = os.path.expandvars(os.path.expanduser(raw))
    return Path(expanded)


def normalize_probe_backend(value: Any, *, default_backend: str = "auto") -> str:
    normalized = str(value or default_backend).strip().lower()
    if normalized not in {"auto", "mediainfo", "ffprobe", "none"}:
        return default_backend
    return normalized


# V4-05 (Polish Total v7.7.0) : valeurs autorisees pour `composite_score_version`.
# Tout autre input retombe sur 1 (V1 reste defaut, decision non negociable).
COMPOSITE_SCORE_VERSIONS: Tuple[int, ...] = (1, 2)
DEFAULT_COMPOSITE_SCORE_VERSION: int = 1

# V6-01 Polish Total v7.7.0 (R4-I18N-4) : locales supportees pour le setting
# `locale`. Source unique de verite cote backend (la liste cote frontend est
# gardee en miroir dans web/dashboard/core/i18n.js).
SUPPORTED_LOCALES: Tuple[str, ...] = ("fr", "en")
DEFAULT_LOCALE: str = "fr"


def _normalize_locale(value: Any) -> str:
    """Clamp `locale` a {"fr", "en"}, fallback "fr" si invalide.

    Tolere None, casse aleatoire ("FR", "En"), espaces. Toute autre valeur
    (vide, langue non supportee, type invalide) -> defaut FR. Symetrique avec
    le frontend (cf web/dashboard/core/i18n.js _readStoredLocale).
    """
    if value is None:
        return DEFAULT_LOCALE
    if isinstance(value, bool):
        return DEFAULT_LOCALE
    try:
        normalized = str(value).strip().lower()
    except (TypeError, ValueError):
        return DEFAULT_LOCALE
    if normalized in SUPPORTED_LOCALES:
        return normalized
    return DEFAULT_LOCALE


def _normalize_composite_score_version(value: Any) -> int:
    """Clamp `composite_score_version` a {1, 2}, fallback 1 si invalide.

    Accepte int ou string ("1"/"2"/"v1"/"v2") pour tolerer les payloads UI
    et les anciennes configs deja persistees. Toute autre valeur (None, 3,
    "abc", float NaN, ...) retombe sur le defaut 1.
    """
    if value is None:
        return DEFAULT_COMPOSITE_SCORE_VERSION
    try:
        if isinstance(value, bool):
            # bool est une sous-classe d'int : on rejette pour eviter True->1 silencieux
            return DEFAULT_COMPOSITE_SCORE_VERSION
        if isinstance(value, str):
            cleaned = value.strip().lower().lstrip("v")
            if not cleaned:
                return DEFAULT_COMPOSITE_SCORE_VERSION
            candidate = int(cleaned)
        else:
            candidate = int(value)
    except (TypeError, ValueError):
        return DEFAULT_COMPOSITE_SCORE_VERSION
    if candidate in COMPOSITE_SCORE_VERSIONS:
        return candidate
    return DEFAULT_COMPOSITE_SCORE_VERSION


def settings_path(state_dir: Path) -> Path:
    return Path(state_dir) / "settings.json"


def extract_tmdb_key_from_settings_payload(data: Dict[str, Any]) -> Tuple[str, str, str]:
    secret_payload = data.get(TMDB_KEY_SECRET_FIELD)
    if isinstance(secret_payload, dict):
        scheme = str(secret_payload.get("scheme") or "").strip().lower()
        blob_b64 = str(secret_payload.get("blob_b64") or "").strip()
        if scheme == WINDOWS_DPAPI_CURRENT_USER and blob_b64:
            ok, value, error = unprotect_secret(blob_b64, purpose=TMDB_KEY_PURPOSE)
            if ok:
                return value, WINDOWS_DPAPI_CURRENT_USER, ""
            return "", WINDOWS_DPAPI_CURRENT_USER, f"Cle TMDb protegee illisible pour cet utilisateur Windows: {error}"

    legacy = str(data.get("tmdb_api_key") or "").strip()
    if legacy:
        return (
            legacy,
            TMDB_KEY_PROTECTION_LEGACY,
            "Cle TMDb legacy en clair detectee. Enregistrer les parametres la migrera vers le stockage protege Windows.",
        )
    return "", SECRET_PROTECTION_NONE, ""


def extract_jellyfin_key_from_settings_payload(data: Dict[str, Any]) -> Tuple[str, str, str]:
    """Extrait la clé API Jellyfin depuis le payload settings (DPAPI ou legacy)."""
    secret_payload = data.get(JELLYFIN_KEY_SECRET_FIELD)
    if isinstance(secret_payload, dict):
        scheme = str(secret_payload.get("scheme") or "").strip().lower()
        blob_b64 = str(secret_payload.get("blob_b64") or "").strip()
        if scheme == WINDOWS_DPAPI_CURRENT_USER and blob_b64:
            ok, value, error = unprotect_secret(blob_b64, purpose=JELLYFIN_KEY_PURPOSE)
            if ok:
                return value, WINDOWS_DPAPI_CURRENT_USER, ""
            return "", WINDOWS_DPAPI_CURRENT_USER, f"Cle Jellyfin protegee illisible: {error}"

    legacy = str(data.get("jellyfin_api_key") or "").strip()
    if legacy:
        return legacy, TMDB_KEY_PROTECTION_LEGACY, ""
    return "", SECRET_PROTECTION_NONE, ""


def read_settings(state_dir: Path) -> Dict[str, Any]:
    path = settings_path(state_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return {}
        secret_value, protection, warning = extract_tmdb_key_from_settings_payload(data)
        data.pop(TMDB_KEY_SECRET_FIELD, None)
        data["tmdb_api_key"] = secret_value
        data["tmdb_key_protection"] = protection
        if warning:
            data["tmdb_key_warning"] = warning
        else:
            data.pop("tmdb_key_warning", None)

        jf_value, jf_protection, jf_warning = extract_jellyfin_key_from_settings_payload(data)
        data.pop(JELLYFIN_KEY_SECRET_FIELD, None)
        data["jellyfin_api_key"] = jf_value
        data["jellyfin_key_protection"] = jf_protection
        if jf_warning:
            data["jellyfin_key_warning"] = jf_warning
        else:
            data.pop("jellyfin_key_warning", None)

        # S4 audit : Plex / Radarr / SMTP password — lecture DPAPI avec fallback legacy
        for legacy_field, secret_field, purpose, protection_key, warning_key in (
            ("plex_token", PLEX_TOKEN_SECRET_FIELD, PLEX_TOKEN_PURPOSE, "plex_token_protection", "plex_token_warning"),
            (
                "radarr_api_key",
                RADARR_KEY_SECRET_FIELD,
                RADARR_KEY_PURPOSE,
                "radarr_key_protection",
                "radarr_key_warning",
            ),
            (
                "email_smtp_password",
                SMTP_PASSWORD_SECRET_FIELD,
                SMTP_PASSWORD_PURPOSE,
                "email_smtp_password_protection",
                "email_smtp_password_warning",
            ),
        ):
            value, scheme, warning = _extract_protected_secret(
                data,
                secret_field=secret_field,
                legacy_field=legacy_field,
                purpose=purpose,
            )
            data.pop(secret_field, None)
            data[legacy_field] = value
            data[protection_key] = scheme
            if warning:
                data[warning_key] = warning
            else:
                data.pop(warning_key, None)

        _migrate_root_to_roots(data)
        return data
    except (OSError, KeyError, TypeError, ValueError) as exc:
        logger.warning("Lecture settings ignoree (json invalide) path=%s err=%s", path, exc)
        return {}


def _migrate_root_to_roots(data: Dict[str, Any]) -> None:
    """Migration backward-compat : si roots absent, creer depuis root."""
    if "roots" not in data:
        legacy_root = str(data.get("root") or "").strip()
        data["roots"] = [legacy_root] if legacy_root else []
    roots = data.get("roots")
    if not isinstance(roots, list):
        roots = [str(roots)] if roots else []
        data["roots"] = roots
    # Garantir root = roots[0] pour backward compat
    data["roots"] = [str(r).strip() for r in roots if str(r).strip()]
    if data["roots"]:
        data["root"] = data["roots"][0]
    elif not data.get("root"):
        data["root"] = ""


def validate_roots(roots: list) -> Dict[str, Any]:
    """Valide une liste de roots. Retourne {roots, warnings, errors}."""
    import os

    clean: list = []
    seen: set = set()
    warnings: list = []

    for raw in roots:
        r = str(raw or "").strip()
        if not r:
            continue
        norm = os.path.normpath(r).lower()
        if norm in seen:
            warnings.append(f"Doublon ignore : {r}")
            continue
        seen.add(norm)
        clean.append(r)

    # Detection roots imbriques
    sorted_norms = sorted(seen)
    for i, a in enumerate(sorted_norms):
        for b in sorted_norms[i + 1 :]:
            if b.startswith(a + os.sep) or b.startswith(a + "/"):
                warnings.append("Imbrication detectee : un root est sous-dossier d'un autre")
                break

    # Verifier accessibilite
    accessible = []
    disconnected = []
    for r in clean:
        if Path(r).exists() and Path(r).is_dir():
            accessible.append(r)
        else:
            disconnected.append(r)
            warnings.append(f"Root inaccessible : {r}")

    return {
        "roots": clean,
        "accessible": accessible,
        "disconnected": disconnected,
        "warnings": warnings,
    }


def read_saved_root_candidates(*state_dirs: Path) -> str:
    for state_dir in state_dirs:
        try:
            data = read_settings(state_dir)
        except (OSError, PermissionError, ValueError):
            data = {}
        root_raw = str(data.get("root") or "").strip()
        if root_raw:
            return root_raw
    return ""


def read_saved_roots_candidates(*state_dirs: Path) -> list:
    """Lit les roots depuis les settings. Retourne la liste ou [] si absent."""
    for state_dir in state_dirs:
        try:
            data = read_settings(state_dir)
        except (KeyError, OSError, PermissionError, TypeError, ValueError):
            data = {}
        _migrate_root_to_roots(data)
        roots = data.get("roots", [])
        if roots:
            return roots
    return []


def write_settings(state_dir: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(data)
    secret_value = str(payload.pop("tmdb_api_key", "") or "").strip()
    payload.pop("tmdb_key_protection", None)
    payload.pop("tmdb_key_warning", None)
    payload.pop(TMDB_KEY_SECRET_FIELD, None)
    remember_key = to_bool(payload.get("remember_key"), False)

    protection = SECRET_PROTECTION_NONE
    warning = ""
    persisted = False

    if remember_key and secret_value:
        ok, blob_b64, error = protect_secret(secret_value, purpose=TMDB_KEY_PURPOSE)
        if ok and blob_b64:
            payload[TMDB_KEY_SECRET_FIELD] = {
                "scheme": WINDOWS_DPAPI_CURRENT_USER,
                "blob_b64": blob_b64,
            }
            protection = WINDOWS_DPAPI_CURRENT_USER
            persisted = True
        else:
            payload["remember_key"] = False
            protection = SECRET_PROTECTION_UNAVAILABLE
            warning = (
                "Protection locale Windows indisponible: la cle TMDb n'a pas ete enregistree."
                if not error
                else f"Protection locale Windows indisponible: {error}"
            )
    else:
        payload["remember_key"] = False if not secret_value else remember_key

    # --- Jellyfin API key (DPAPI) ---
    jf_secret = str(payload.pop("jellyfin_api_key", "") or "").strip()
    payload.pop("jellyfin_key_protection", None)
    payload.pop("jellyfin_key_warning", None)
    payload.pop(JELLYFIN_KEY_SECRET_FIELD, None)
    jf_persisted = False
    jf_warning = ""

    if jf_secret:
        ok_jf, blob_jf, err_jf = protect_secret(jf_secret, purpose=JELLYFIN_KEY_PURPOSE)
        if ok_jf and blob_jf:
            payload[JELLYFIN_KEY_SECRET_FIELD] = {
                "scheme": WINDOWS_DPAPI_CURRENT_USER,
                "blob_b64": blob_jf,
            }
            jf_persisted = True
        else:
            jf_warning = (
                f"Protection Jellyfin indisponible: {err_jf}" if err_jf else "Protection Jellyfin indisponible."
            )

    # --- S4 audit : Plex token / Radarr API key / SMTP password (DPAPI) ---
    # Pour chaque secret, on consomme la cle legacy en clair et on la remplace
    # par un blob chiffre. Si DPAPI indisponible, le secret n'est PAS persiste
    # (comportement aligne avec TMDb/Jellyfin : pas de fallback plaintext).
    plex_persisted, plex_warning = _persist_protected_secret(
        payload,
        legacy_field="plex_token",
        secret_field=PLEX_TOKEN_SECRET_FIELD,
        purpose=PLEX_TOKEN_PURPOSE,
    )
    payload.pop("plex_token_protection", None)
    payload.pop("plex_token_warning", None)

    radarr_persisted, radarr_warning = _persist_protected_secret(
        payload,
        legacy_field="radarr_api_key",
        secret_field=RADARR_KEY_SECRET_FIELD,
        purpose=RADARR_KEY_PURPOSE,
    )
    payload.pop("radarr_key_protection", None)
    payload.pop("radarr_key_warning", None)

    smtp_persisted, smtp_warning = _persist_protected_secret(
        payload,
        legacy_field="email_smtp_password",
        secret_field=SMTP_PASSWORD_SECRET_FIELD,
        purpose=SMTP_PASSWORD_PURPOSE,
    )
    payload.pop("email_smtp_password_protection", None)
    payload.pop("email_smtp_password_warning", None)

    # Audit ID-J-001 (V1-M10) : backup auto + rotation avant ecriture.
    target_path = settings_path(state_dir)
    _backup_settings_before_write(target_path)
    _rotate_settings_backups(target_path)

    state.atomic_write_json(target_path, payload)
    return {
        "tmdb_key_persisted": persisted,
        "tmdb_key_protection": protection,
        "tmdb_key_warning": warning,
        "jellyfin_key_persisted": jf_persisted,
        "jellyfin_key_warning": jf_warning,
        "plex_token_persisted": plex_persisted,
        "plex_token_warning": plex_warning,
        "radarr_key_persisted": radarr_persisted,
        "radarr_key_warning": radarr_warning,
        "email_smtp_password_persisted": smtp_persisted,
        "email_smtp_password_warning": smtp_warning,
    }


# Phase 15 v7.8.0 : table declarative des defaults litteraux.
#
# 100 entrees (key, default_value) qui remplacent autant de
# `payload.setdefault(key, value)` lineaires. L'ordre est preserve par rapport
# a l'historique pour faciliter le diff. Les defaults necessitant un parametre
# de la fonction, une transformation, ou un fallback sur la valeur existante
# restent en code dans `apply_settings_defaults`.
#
# Format : (key, default_value).
# Pour les listes : la valeur sera deep-copiee a chaque appel pour eviter le
# partage de la default mutable entre payloads (piege classique).
_LITERAL_DEFAULTS: Tuple[Tuple[str, Any], ...] = (
    # --- TMDb ---
    ("tmdb_enabled", True),
    ("tmdb_timeout_s", 10.0),
    # V5-03 polish v7.7.0 (R5-STRESS-4) : TTL cache TMDb (defaut 30j, min 1, max 365)
    ("tmdb_cache_ttl_days", 30),
    # --- Collection + cleanup folder names ---
    ("collection_folder_enabled", True),
    ("move_empty_folders_enabled", False),
    ("empty_folders_scope", "root_all"),
    ("cleanup_residual_folders_enabled", False),
    ("cleanup_residual_folders_scope", "touched_only"),
    ("cleanup_residual_include_nfo", True),
    ("cleanup_residual_include_images", True),
    ("cleanup_residual_include_subtitles", True),
    ("cleanup_residual_include_texts", True),
    # --- Probe paths + parallelism ---
    ("mediainfo_path", ""),
    ("ffprobe_path", ""),
    # V5-04 (R5-STRESS-1) probe parallelism : 0 = auto (min(cpu_count(), 8))
    ("probe_workers", 0),
    ("probe_parallelism_enabled", True),
    ("incremental_scan_enabled", False),
    ("quarantine_unapproved", False),
    ("dry_run_apply", True),
    ("auto_approve_enabled", False),
    ("auto_approve_threshold", 85),
    # M-2 audit QA 20260429 : auto-quarantine films corrompus
    ("auto_quarantine_corrupted", False),
    ("onboarding_completed", False),
    ("enable_tv_detection", False),
    # V3-02 — Mode expert (cache options techniques aux debutants)
    ("expert_mode", False),
    # --- Jellyfin ---
    ("jellyfin_enabled", False),
    ("jellyfin_url", ""),
    ("jellyfin_user_id", ""),
    ("jellyfin_refresh_on_apply", True),
    ("jellyfin_sync_watched", True),
    ("jellyfin_timeout_s", 10.0),
    # --- Plex ---
    ("plex_enabled", False),
    ("plex_url", ""),
    ("plex_token", ""),
    ("plex_library_id", ""),
    ("plex_refresh_on_apply", True),
    ("plex_timeout_s", 10.0),
    # --- Radarr ---
    ("radarr_enabled", False),
    ("radarr_url", ""),
    ("radarr_api_key", ""),
    ("radarr_timeout_s", 10.0),
    # --- Notifications ---
    ("notifications_enabled", False),
    ("notifications_scan_triggered", True),  # cf #108 : watcher detecte un changement
    ("notifications_scan_done", True),
    ("notifications_apply_done", True),
    ("notifications_undo_done", True),
    ("notifications_errors", True),
    # --- Updates (ID-V1-M13 + V3-12) ---
    ("update_check_enabled", True),
    ("update_check_channel", "stable"),
    ("update_last_check_ts", 0.0),
    ("update_github_repo", ""),
    # --- REST API (token gere a part : genere si vide) ---
    ("rest_api_enabled", False),
    ("rest_api_port", 8642),
    ("rest_api_cors_origin", ""),
    ("rest_api_https_enabled", False),
    ("rest_api_cert_path", ""),
    ("rest_api_key_path", ""),
    # --- Watcher ---
    ("watch_enabled", False),
    ("watch_interval_minutes", 5),
    # --- Plugins ---
    ("plugins_enabled", False),
    ("plugins_timeout_s", 30),
    # --- Email reports ---
    ("email_enabled", False),
    ("email_smtp_host", ""),
    ("email_smtp_port", 587),
    ("email_smtp_user", ""),
    ("email_smtp_password", ""),
    ("email_smtp_tls", True),
    ("email_to", ""),
    ("email_on_scan", True),
    ("email_on_apply", True),
    # --- Subtitles ---
    ("subtitle_detection_enabled", True),
    ("subtitle_expected_languages", ["fr"]),
    # --- Naming ---
    ("naming_preset", "default"),
    ("naming_movie_template", "{title} ({year})"),
    ("naming_tv_template", "{series} ({year})"),
    # --- Analyse perceptuelle ---
    ("perceptual_enabled", False),
    ("perceptual_auto_on_scan", False),
    ("perceptual_auto_on_quality", True),
    ("perceptual_timeout_per_film_s", 120),
    ("perceptual_frames_count", 10),
    ("perceptual_skip_percent", 5),
    ("perceptual_dark_weight", 1.5),
    ("perceptual_audio_deep", True),
    ("perceptual_audio_segment_s", 30),
    ("perceptual_comparison_frames", 20),
    ("perceptual_comparison_timeout_s", 600),
    ("perceptual_parallelism_mode", "auto"),
    # V5-02 (R5-STRESS-5) parallelisme batch inter-films
    ("perceptual_parallelism_enabled", True),
    ("perceptual_workers", 0),
    ("perceptual_audio_fingerprint_enabled", True),
    ("perceptual_scene_detection_enabled", True),
    ("perceptual_audio_spectral_enabled", True),
    ("perceptual_ssim_self_ref_enabled", True),
    ("perceptual_hdr10_plus_detection_enabled", True),
    ("perceptual_interlacing_detection_enabled", True),
    ("perceptual_crop_detection_enabled", True),
    ("perceptual_judder_detection_enabled", False),
    ("perceptual_grain_intelligence_enabled", True),
    ("perceptual_audio_mel_enabled", True),
    ("perceptual_lpips_enabled", True),
    # --- Apparence ---
    ("theme", "studio"),
    ("animation_level", "moderate"),
    ("effect_speed", 50),
    ("glow_intensity", 30),
    ("light_intensity", 20),
)


def apply_settings_defaults(
    data: Dict[str, Any],
    *,
    state_dir: Path,
    default_root: str,
    default_state_dir_example: str,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
    default_probe_backend: str,
    debug_enabled: bool,
) -> Dict[str, Any]:
    """Applique tous les defaults manquants sur le payload settings.

    Phase 15 v7.8.0 : 180L de `payload.setdefault(...)` -> 50L code + table
    declarative `_LITERAL_DEFAULTS`. Comportement strictement preserve : les
    100 defaults litteraux passent par la table, les 13 cas derives/computes
    (locale, log_level, composite_score_version, rest_api_token, secrets DPAPI,
    remember_key, alias update flags) restent en code car ils dependent
    d'une transformation ou d'un fallback sur la valeur existante.
    """
    payload = dict(data)
    # Param-derived defaults (depend des arguments de la fonction)
    payload.setdefault("root", default_root)
    _migrate_root_to_roots(payload)
    payload.setdefault("state_dir", str(state_dir))
    payload.setdefault("root_example", default_root)
    payload.setdefault("state_dir_example", default_state_dir_example)
    payload.setdefault("collection_folder_name", default_collection_folder_name)
    payload.setdefault("empty_folders_folder_name", default_empty_folders_folder_name)
    payload.setdefault("cleanup_residual_folders_folder_name", default_residual_cleanup_folder_name)
    payload.setdefault("probe_backend", default_probe_backend)

    # Table declarative : ~100 defaults litteraux. Deep-copie les listes pour
    # eviter le partage de mutable default entre payloads (piege Python).
    for key, value in _LITERAL_DEFAULTS:
        payload.setdefault(key, list(value) if isinstance(value, list) else value)

    # Jellyfin secrets : preserver les valeurs deja presentes (DPAPI), sinon defaut.
    payload.setdefault("jellyfin_api_key", payload.get("jellyfin_api_key", ""))
    payload.setdefault(
        "jellyfin_key_protection",
        payload.get("jellyfin_key_protection") or SECRET_PROTECTION_NONE,
    )
    payload.setdefault("jellyfin_key_warning", payload.get("jellyfin_key_warning", ""))

    # V3-12 : ``auto_check_updates`` est un alias plus clair de ``update_check_enabled``
    payload.setdefault("auto_check_updates", payload.get("update_check_enabled", True))

    # BUG 1 : generer un token REST aleatoire au premier lancement plutot que vide
    if not str(payload.get("rest_api_token") or "").strip():
        import secrets as _secrets

        payload["rest_api_token"] = _secrets.token_urlsafe(24)

    # V6-01 (R4-I18N-4) : locale clamp via _normalize_locale a {"fr", "en"}, defaut "fr"
    payload["locale"] = _normalize_locale(payload.get("locale"))

    # V4-05 (R4-PERC-7 / H16) : composite_score_version normalise (V1 par defaut)
    payload["composite_score_version"] = _normalize_composite_score_version(payload.get("composite_score_version"))

    # V3-04 (R4-LOG-3) : log_level normalise (DEBUG/INFO/WARNING/ERROR/CRITICAL)
    from cinesort.infra.log_context import normalize_log_level_setting

    payload["log_level"] = normalize_log_level_setting(payload.get("log_level"))

    payload.setdefault("debug_enabled", debug_enabled)

    # TMDb secrets : preserve existing values, derive remember_key
    payload.setdefault("tmdb_api_key", payload.get("tmdb_api_key", ""))
    payload.setdefault(
        "tmdb_key_protection",
        payload.get("tmdb_key_protection") or SECRET_PROTECTION_NONE,
    )
    payload.setdefault("remember_key", bool(str(payload.get("tmdb_api_key") or "").strip()))
    payload.setdefault("tmdb_key_warning", payload.get("tmdb_key_warning", ""))
    return payload


def build_cfg_from_settings(
    settings: Dict[str, Any],
    *,
    root: Path,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
) -> core.Config:
    collection_folder_name = (
        str(settings.get("collection_folder_name") or default_collection_folder_name).strip()
        or default_collection_folder_name
    )
    empty_folders_folder_name = (
        str(settings.get("empty_folders_folder_name") or default_empty_folders_folder_name).strip()
        or default_empty_folders_folder_name
    )
    empty_scope = str(settings.get("empty_folders_scope") or "root_all").strip().lower()
    if empty_scope not in {"touched_only", "root_all"}:
        empty_scope = "root_all"
    residual_folder_name = (
        str(settings.get("cleanup_residual_folders_folder_name") or default_residual_cleanup_folder_name).strip()
        or default_residual_cleanup_folder_name
    )
    residual_scope = str(settings.get("cleanup_residual_folders_scope") or "touched_only").strip().lower()
    if residual_scope not in {"touched_only", "root_all"}:
        residual_scope = "touched_only"
    return core.Config(
        root=root,
        enable_collection_folder=to_bool(settings.get("collection_folder_enabled"), True),
        collection_root_name=collection_folder_name,
        empty_folders_folder_name=empty_folders_folder_name,
        move_empty_folders_enabled=to_bool(settings.get("move_empty_folders_enabled"), False),
        empty_folders_scope=empty_scope,
        cleanup_residual_folders_enabled=to_bool(settings.get("cleanup_residual_folders_enabled"), False),
        cleanup_residual_folders_folder_name=residual_folder_name,
        cleanup_residual_folders_scope=residual_scope,
        cleanup_residual_include_nfo=to_bool(settings.get("cleanup_residual_include_nfo"), True),
        cleanup_residual_include_images=to_bool(settings.get("cleanup_residual_include_images"), True),
        cleanup_residual_include_subtitles=to_bool(settings.get("cleanup_residual_include_subtitles"), True),
        cleanup_residual_include_texts=to_bool(settings.get("cleanup_residual_include_texts"), True),
        enable_tmdb=to_bool(settings.get("tmdb_enabled"), True),
        incremental_scan_enabled=to_bool(settings.get("incremental_scan_enabled"), False),
        enable_tv_detection=to_bool(settings.get("enable_tv_detection"), False),
        naming_movie_template=str(settings.get("naming_movie_template") or "{title} ({year})"),
        naming_tv_template=str(settings.get("naming_tv_template") or "{series} ({year})"),
    )


def build_cfg_from_run_row(
    row: Dict[str, Any],
    *,
    default_root: str,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
) -> core.Config:
    cfg_json: Dict[str, Any] = {}
    try:
        parsed = json.loads(str(row.get("config_json") or "{}"))
        if isinstance(parsed, dict):
            cfg_json = parsed
    except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
        cfg_json = {}
    return build_cfg_from_settings(
        cfg_json,
        root=normalize_user_path(row.get("root"), Path(default_root)),
        default_collection_folder_name=default_collection_folder_name,
        default_empty_folders_folder_name=default_empty_folders_folder_name,
        default_residual_cleanup_folder_name=default_residual_cleanup_folder_name,
    )


def resolve_payload_state_dir(settings: Dict[str, Any], *, default_state_dir: Path) -> Tuple[Path, bool]:
    state_dir_present = "state_dir" in settings
    state_dir = normalize_user_path(settings.get("state_dir"), default_state_dir)
    return state_dir, state_dir_present


def resolve_root_from_payload(
    settings: Dict[str, Any],
    *,
    state_dir: Path,
    state_dir_present: bool,
    current_state_dir: Path,
    default_root: str,
    missing_message: str,
) -> Tuple[Optional[Path], Optional[str]]:
    root_present = "root" in settings
    root_value = settings.get("root")
    if root_present and not str(root_value or "").strip():
        return None, "Le dossier ROOT ne peut pas etre vide."
    if root_present:
        return normalize_user_path(root_value, Path(default_root)), None

    candidates = [state_dir]
    if not state_dir_present:
        candidates.append(current_state_dir)
    saved_root = read_saved_root_candidates(*candidates)
    if not saved_root:
        return None, missing_message
    return normalize_user_path(saved_root, Path(default_root)), None


def resolve_roots_from_payload(
    settings: Dict[str, Any],
    *,
    state_dir: Path,
    state_dir_present: bool,
    current_state_dir: Path,
    default_root: str,
    missing_message: str,
) -> Tuple[Optional[List[Path]], Optional[str]]:
    """Resout la liste des roots depuis le payload. Retourne (roots, error)."""
    # Priorite 1 : roots explicite dans le payload
    roots_raw = settings.get("roots")
    if isinstance(roots_raw, list) and roots_raw:
        roots = [normalize_user_path(r, Path(default_root)) for r in roots_raw if str(r or "").strip()]
        if roots:
            return roots, None

    # Priorite 2 : root unique (backward compat)
    root_present = "root" in settings
    root_value = settings.get("root")
    if root_present and str(root_value or "").strip():
        return [normalize_user_path(root_value, Path(default_root))], None
    if root_present and not str(root_value or "").strip():
        return None, "Le dossier ROOT ne peut pas etre vide."

    # Priorite 3 : lire depuis les settings sauvegardes
    candidates = [state_dir]
    if not state_dir_present:
        candidates.append(current_state_dir)
    saved_roots = read_saved_roots_candidates(*candidates)
    if saved_roots:
        return [normalize_user_path(r, Path(default_root)) for r in saved_roots if str(r or "").strip()], None

    saved_root = read_saved_root_candidates(*candidates)
    if saved_root:
        return [normalize_user_path(saved_root, Path(default_root))], None

    return None, missing_message


# Champs secrets masques dans la reponse get_settings (jamais envoyes en clair au frontend).
# BUG 1 : rest_api_token RETIRE de la liste — c'est le PROPRE token de l'utilisateur,
# il doit pouvoir le voir pour le donner a ses autres appareils. Le masquer n'apporte
# rien : le token est deja stocke en clair dans settings.json sur la meme machine.
_SECRET_MASK = "\u2022\u2022\u2022\u2022\u2022\u2022\u2022\u2022"  # 8 bullets
# SEC-H2 (Phase 1 remediation v7.8.0) : tmdb_api_key et jellyfin_api_key ajoutees
# a la liste. Avant ce fix, POST /api/get_settings retournait ces 2 cles en clair,
# permettant a un attaquant LAN avec token Bearer de pivoter vers Jellyfin admin.
# L'UI frontend continue de fonctionner via le pattern _has_<field>: bool + masque
# (l'utilisateur re-saisit la cle pour la modifier).
_SECRET_FIELDS = (
    "tmdb_api_key",
    "jellyfin_api_key",
    "plex_token",
    "radarr_api_key",
    "email_smtp_password",
)


def _mask_secrets(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Masque les secrets avant envoi au frontend. Ajoute _has_<field> pour chaque secret."""
    for field in _SECRET_FIELDS:
        value = str(payload.get(field) or "").strip()
        payload[f"_has_{field}"] = bool(value)
        if value:
            payload[field] = _SECRET_MASK
    return payload


def _unmask_secrets_for_save(incoming: Dict[str, Any], existing: Dict[str, Any]) -> None:
    """Si le frontend renvoie le masque, on garde la valeur existante."""
    for field in _SECRET_FIELDS:
        val = str(incoming.get(field) or "").strip()
        if val == _SECRET_MASK:
            # L'utilisateur n'a pas modifie — conserver la valeur existante
            incoming[field] = str(existing.get(field) or "").strip()


def get_settings_payload(
    *,
    state_dir: Path,
    default_root: str,
    default_state_dir_example: str,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
    default_probe_backend: str,
    debug_enabled: bool,
) -> Dict[str, Any]:
    state_dir.mkdir(parents=True, exist_ok=True)
    data = read_settings(state_dir)
    payload = apply_settings_defaults(
        data,
        state_dir=state_dir,
        default_root=default_root,
        default_state_dir_example=default_state_dir_example,
        default_collection_folder_name=default_collection_folder_name,
        default_empty_folders_folder_name=default_empty_folders_folder_name,
        default_residual_cleanup_folder_name=default_residual_cleanup_folder_name,
        default_probe_backend=default_probe_backend,
        debug_enabled=debug_enabled,
    )
    return _mask_secrets(payload)


_VALID_NAMING_PRESETS = {"default", "plex", "jellyfin", "quality", "custom"}


def _apply_naming_preset(to_save: Dict[str, Any], raw_settings: Dict[str, Any]) -> None:
    """Normalise le preset de renommage et applique les templates correspondants."""
    from cinesort.domain.naming import PRESETS, validate_template

    preset = str(raw_settings.get("naming_preset") or "default").strip().lower()
    if preset not in _VALID_NAMING_PRESETS:
        preset = "default"

    to_save["naming_preset"] = preset

    if preset != "custom":
        # Preset selectionne → ecraser les templates par les valeurs du preset
        profile = PRESETS.get(preset, PRESETS["default"])
        to_save["naming_movie_template"] = profile.movie_template
        to_save["naming_tv_template"] = profile.tv_template
    else:
        # Custom → garder les templates saisis par l'utilisateur, valider
        movie_tpl = str(raw_settings.get("naming_movie_template") or "{title} ({year})").strip()
        tv_tpl = str(raw_settings.get("naming_tv_template") or "{series} ({year})").strip()

        ok_m, _ = validate_template(movie_tpl)
        ok_t, _ = validate_template(tv_tpl)

        to_save["naming_movie_template"] = movie_tpl if ok_m else "{title} ({year})"
        to_save["naming_tv_template"] = tv_tpl if ok_t else "{series} ({year})"


# --- Helpers de section pour save_settings_payload ---
# Audit ID-CODE-001 (V2-01) : la fonction save_settings_payload faisait F=74
# (>80 chemins). Decoupee en helpers prives _save_section_<group> (CC<15 chacun)
# pour rester maintenable a 2000 users : chaque section = un helper testable
# isolement, save_settings_payload devient un dispatcher de ~30 lignes (B=8).


def _normalize_enum(value: Any, allowed: Tuple[str, ...], default: str) -> str:
    """Normalise une valeur enum (lower/strip) ou retourne `default` si hors liste."""
    s = str(value or "").strip().lower()
    return s if s in allowed else default


def _save_section_tmdb(payload: Dict[str, Any]) -> Dict[str, Any]:
    # V5-03 polish v7.7.0 (R5-STRESS-4) : tmdb_cache_ttl_days clamp [1, 365].
    ttl_days = to_int(payload.get("tmdb_cache_ttl_days"), 30)
    ttl_days = max(1, min(365, ttl_days))
    return {
        "tmdb_enabled": to_bool(payload.get("tmdb_enabled"), True),
        "tmdb_timeout_s": to_float(payload.get("tmdb_timeout_s"), 10.0),
        "tmdb_cache_ttl_days": ttl_days,
    }


def _save_section_cleanup(
    payload: Dict[str, Any],
    *,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
) -> Dict[str, Any]:
    return {
        "collection_folder_enabled": to_bool(payload.get("collection_folder_enabled"), True),
        "collection_folder_name": str(payload.get("collection_folder_name") or default_collection_folder_name).strip()
        or default_collection_folder_name,
        "empty_folders_folder_name": str(
            payload.get("empty_folders_folder_name") or default_empty_folders_folder_name
        ).strip()
        or default_empty_folders_folder_name,
        "move_empty_folders_enabled": to_bool(payload.get("move_empty_folders_enabled"), False),
        "empty_folders_scope": str(payload.get("empty_folders_scope") or "root_all").strip().lower(),
        "cleanup_residual_folders_enabled": to_bool(payload.get("cleanup_residual_folders_enabled"), False),
        "cleanup_residual_folders_folder_name": str(
            payload.get("cleanup_residual_folders_folder_name") or default_residual_cleanup_folder_name
        ).strip()
        or default_residual_cleanup_folder_name,
        "cleanup_residual_folders_scope": str(payload.get("cleanup_residual_folders_scope") or "touched_only")
        .strip()
        .lower(),
        "cleanup_residual_include_nfo": to_bool(payload.get("cleanup_residual_include_nfo"), True),
        "cleanup_residual_include_images": to_bool(payload.get("cleanup_residual_include_images"), True),
        "cleanup_residual_include_subtitles": to_bool(payload.get("cleanup_residual_include_subtitles"), True),
        "cleanup_residual_include_texts": to_bool(payload.get("cleanup_residual_include_texts"), True),
    }


def _save_section_probe(payload: Dict[str, Any], *, default_probe_backend: str) -> Dict[str, Any]:
    # M1 : timeout ffprobe/mediainfo configurable (defaut 30s, min 5s, max 300s).
    # Utile pour les NAS SMB lents ou les gros fichiers 4K qui depassent 30s.
    # V5-04 : `probe_workers` int [0..16] (0=auto), `probe_parallelism_enabled` bool.
    workers_raw = to_int(payload.get("probe_workers"), 0)
    return {
        "probe_backend": normalize_probe_backend(payload.get("probe_backend"), default_backend=default_probe_backend),
        "mediainfo_path": str(payload.get("mediainfo_path") or "").strip(),
        "ffprobe_path": str(payload.get("ffprobe_path") or "").strip(),
        "probe_timeout_s": max(5.0, min(300.0, to_float(payload.get("probe_timeout_s"), 30.0))),
        "probe_workers": max(0, min(16, workers_raw)),
        "probe_parallelism_enabled": to_bool(payload.get("probe_parallelism_enabled"), True),
    }


def _save_section_scan_flags(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "incremental_scan_enabled": to_bool(payload.get("incremental_scan_enabled"), False),
        "quarantine_unapproved": to_bool(payload.get("quarantine_unapproved"), False),
        "dry_run_apply": to_bool(payload.get("dry_run_apply"), True),
        "auto_approve_enabled": to_bool(payload.get("auto_approve_enabled"), False),
        "auto_approve_threshold": max(70, min(100, int(payload.get("auto_approve_threshold") or 85))),
        # M-2 : auto-quarantine films corrompus (integrity warnings)
        "auto_quarantine_corrupted": to_bool(payload.get("auto_quarantine_corrupted"), False),
        "onboarding_completed": to_bool(payload.get("onboarding_completed"), False),
        "enable_tv_detection": to_bool(payload.get("enable_tv_detection"), False),
        # V3-02 — Mode expert (affiche les settings avances). Coerce en bool pour
        # accepter aussi bien True/False JS que "true"/"false" string.
        "expert_mode": to_bool(payload.get("expert_mode"), False),
    }


def _save_section_jellyfin(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "jellyfin_enabled": to_bool(payload.get("jellyfin_enabled"), False),
        "jellyfin_url": _normalize_jellyfin_url(str(payload.get("jellyfin_url") or "").strip()),
        "jellyfin_user_id": str(payload.get("jellyfin_user_id") or "").strip(),
        "jellyfin_refresh_on_apply": to_bool(payload.get("jellyfin_refresh_on_apply"), True),
        "jellyfin_sync_watched": to_bool(payload.get("jellyfin_sync_watched"), True),
        "jellyfin_timeout_s": max(1.0, min(60.0, to_float(payload.get("jellyfin_timeout_s"), 10.0))),
    }


def _save_section_plex(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "plex_enabled": to_bool(payload.get("plex_enabled"), False),
        "plex_url": str(payload.get("plex_url") or "").strip().rstrip("/"),
        "plex_token": str(payload.get("plex_token") or "").strip(),
        "plex_library_id": str(payload.get("plex_library_id") or "").strip(),
        "plex_refresh_on_apply": to_bool(payload.get("plex_refresh_on_apply"), True),
        "plex_timeout_s": max(1.0, min(60.0, to_float(payload.get("plex_timeout_s"), 10.0))),
    }


def _save_section_radarr(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "radarr_enabled": to_bool(payload.get("radarr_enabled"), False),
        "radarr_url": str(payload.get("radarr_url") or "").strip().rstrip("/"),
        "radarr_api_key": str(payload.get("radarr_api_key") or "").strip(),
        "radarr_timeout_s": max(1.0, min(60.0, to_float(payload.get("radarr_timeout_s"), 10.0))),
    }


def _save_section_notifications(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "notifications_enabled": to_bool(payload.get("notifications_enabled"), False),
        "notifications_scan_triggered": to_bool(payload.get("notifications_scan_triggered"), True),
        "notifications_scan_done": to_bool(payload.get("notifications_scan_done"), True),
        "notifications_apply_done": to_bool(payload.get("notifications_apply_done"), True),
        "notifications_undo_done": to_bool(payload.get("notifications_undo_done"), True),
        "notifications_errors": to_bool(payload.get("notifications_errors"), True),
    }


def _save_section_rest_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    # R5-CFG-1 : token validation deleguee a rest_server.MIN_LAN_TOKEN_LENGTH=32
    # qui retrograde transparent vers 127.0.0.1 si bind 0.0.0.0 demande avec
    # token court. Pas de double validation pour preserver les tests legacy
    # qui utilisent des tokens custom courts en mode local-only.
    return {
        "rest_api_enabled": to_bool(payload.get("rest_api_enabled"), False),
        "rest_api_port": max(1024, min(65535, int(payload.get("rest_api_port") or 8642))),
        "rest_api_token": str(payload.get("rest_api_token") or "").strip(),
        "rest_api_cors_origin": str(payload.get("rest_api_cors_origin") or "").strip(),
        "rest_api_https_enabled": to_bool(payload.get("rest_api_https_enabled"), False),
        "rest_api_cert_path": str(payload.get("rest_api_cert_path") or "").strip(),
        "rest_api_key_path": str(payload.get("rest_api_key_path") or "").strip(),
    }


def _save_section_watch(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "watch_enabled": to_bool(payload.get("watch_enabled"), False),
        "watch_interval_minutes": max(1, min(60, int(payload.get("watch_interval_minutes") or 5))),
    }


def _save_section_plugins(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "plugins_enabled": to_bool(payload.get("plugins_enabled"), False),
        "plugins_timeout_s": max(5, min(120, int(payload.get("plugins_timeout_s") or 30))),
    }


def _save_section_email(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "email_enabled": to_bool(payload.get("email_enabled"), False),
        "email_smtp_host": str(payload.get("email_smtp_host") or "").strip(),
        "email_smtp_port": max(1, min(65535, int(payload.get("email_smtp_port") or 587))),
        "email_smtp_user": str(payload.get("email_smtp_user") or "").strip(),
        "email_smtp_password": str(payload.get("email_smtp_password") or ""),
        "email_smtp_tls": to_bool(payload.get("email_smtp_tls"), True),
        "email_to": str(payload.get("email_to") or "").strip(),
        "email_on_scan": to_bool(payload.get("email_on_scan"), True),
        "email_on_apply": to_bool(payload.get("email_on_apply"), True),
    }


def _save_section_subtitles(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "subtitle_detection_enabled": to_bool(payload.get("subtitle_detection_enabled"), True),
        "subtitle_expected_languages": _normalize_lang_list(payload.get("subtitle_expected_languages")),
    }


def _save_section_perceptual(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "perceptual_enabled": to_bool(payload.get("perceptual_enabled"), False),
        "perceptual_auto_on_scan": to_bool(payload.get("perceptual_auto_on_scan"), False),
        "perceptual_auto_on_quality": to_bool(payload.get("perceptual_auto_on_quality"), True),
        "perceptual_timeout_per_film_s": max(30, min(600, int(payload.get("perceptual_timeout_per_film_s") or 120))),
        "perceptual_frames_count": max(5, min(50, int(payload.get("perceptual_frames_count") or 10))),
        "perceptual_skip_percent": max(0, min(20, int(payload.get("perceptual_skip_percent") or 5))),
        "perceptual_dark_weight": max(1.0, min(3.0, to_float(payload.get("perceptual_dark_weight"), 1.5))),
        "perceptual_audio_deep": to_bool(payload.get("perceptual_audio_deep"), True),
        "perceptual_audio_segment_s": max(10, min(120, int(payload.get("perceptual_audio_segment_s") or 30))),
        "perceptual_comparison_frames": max(10, min(100, int(payload.get("perceptual_comparison_frames") or 20))),
        "perceptual_comparison_timeout_s": max(
            120, min(1800, int(payload.get("perceptual_comparison_timeout_s") or 600))
        ),
        "perceptual_parallelism_mode": _normalize_enum(
            payload.get("perceptual_parallelism_mode"), ("auto", "max", "safe", "serial"), "auto"
        ),
        # V5-02 Polish Total v7.7.0 (R5-STRESS-5) : settings batch parallelism.
        # `perceptual_workers` clampe a [0, 16] (0 = auto). `perceptual_parallelism_enabled`
        # est un bool (defaut True) qui agit comme kill-switch global du pool batch.
        "perceptual_parallelism_enabled": to_bool(payload.get("perceptual_parallelism_enabled"), True),
        "perceptual_workers": max(0, min(16, _coerce_workers_int(payload.get("perceptual_workers")))),
        "perceptual_audio_fingerprint_enabled": to_bool(payload.get("perceptual_audio_fingerprint_enabled"), True),
        "perceptual_scene_detection_enabled": to_bool(payload.get("perceptual_scene_detection_enabled"), True),
        "perceptual_audio_spectral_enabled": to_bool(payload.get("perceptual_audio_spectral_enabled"), True),
        "perceptual_ssim_self_ref_enabled": to_bool(payload.get("perceptual_ssim_self_ref_enabled"), True),
        "perceptual_hdr10_plus_detection_enabled": to_bool(
            payload.get("perceptual_hdr10_plus_detection_enabled"), True
        ),
        "perceptual_interlacing_detection_enabled": to_bool(
            payload.get("perceptual_interlacing_detection_enabled"), True
        ),
        "perceptual_crop_detection_enabled": to_bool(payload.get("perceptual_crop_detection_enabled"), True),
        "perceptual_judder_detection_enabled": to_bool(payload.get("perceptual_judder_detection_enabled"), False),
        "perceptual_grain_intelligence_enabled": to_bool(payload.get("perceptual_grain_intelligence_enabled"), True),
        "perceptual_audio_mel_enabled": to_bool(payload.get("perceptual_audio_mel_enabled"), True),
        "perceptual_lpips_enabled": to_bool(payload.get("perceptual_lpips_enabled"), True),
        # V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) : toggle V1/V2 normalise
        # a la sauvegarde (clamp {1,2}, fallback 1). Le defaut applique en lecture
        # via `apply_settings_defaults` couvre les configs existantes.
        "composite_score_version": _normalize_composite_score_version(payload.get("composite_score_version")),
    }


def _coerce_workers_int(value: Any) -> int:
    """Convertit `perceptual_workers` en int, fallback 0 (auto) si invalide.

    V5-02 Polish Total v7.7.0 : tolere None, "", "auto", strings numeriques,
    bool (rejete car bool est sous-classe d'int). Toute valeur invalide -> 0.
    """
    if value is None:
        return 0
    if isinstance(value, bool):
        # bool sous-classe d'int : on rejette pour eviter True->1 silencieux.
        return 0
    if isinstance(value, str):
        cleaned = value.strip().lower()
        if not cleaned or cleaned == "auto":
            return 0
        try:
            return int(cleaned)
        except ValueError:
            return 0
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _coerce_appearance_int(payload: Dict[str, Any], key: str, default: int) -> int:
    """Recupere un slider appearance en preservant la semantique d'origine.

    Original : `payload[key] if key in payload and payload[key] is not None else default`.
    Cle absente OU valeur None → default. Sinon int(value) (peut lever ValueError).
    """
    if key in payload and payload[key] is not None:
        return int(payload[key])
    return default


def _save_section_appearance(payload: Dict[str, Any], *, debug_enabled: bool) -> Dict[str, Any]:
    # V3-04 polish v7.7.0 : persiste log_level normalise (DEBUG/INFO/...).
    from cinesort.infra.log_context import normalize_log_level_setting

    return {
        "theme": _normalize_enum(payload.get("theme"), ("cinema", "studio", "luxe", "neon"), "luxe"),
        "animation_level": _normalize_enum(
            payload.get("animation_level"), ("subtle", "moderate", "intense"), "moderate"
        ),
        "effect_speed": max(1, min(100, _coerce_appearance_int(payload, "effect_speed", 50))),
        "glow_intensity": max(0, min(100, _coerce_appearance_int(payload, "glow_intensity", 30))),
        "light_intensity": max(0, min(100, _coerce_appearance_int(payload, "light_intensity", 20))),
        "effects_mode": _normalize_enum(payload.get("effects_mode"), ("restraint", "balanced", "intense"), "restraint"),
        "debug_enabled": to_bool(payload.get("debug_enabled"), debug_enabled),
        "log_level": normalize_log_level_setting(payload.get("log_level")),
        # V6-01 Polish Total v7.7.0 (R4-I18N-4) : locale persistee. Validation
        # via _normalize_locale (clamp fr/en, fallback fr). Au save, l'API
        # appelle aussi i18n_messages.set_locale() pour activer le changement
        # cote backend immediatement (cf cinesort_api.save_settings).
        "locale": _normalize_locale(payload.get("locale")),
    }


def _normalize_scopes(to_save: Dict[str, Any]) -> None:
    """Force les scopes cleanup vers une valeur valide."""
    if to_save["empty_folders_scope"] not in {"touched_only", "root_all"}:
        to_save["empty_folders_scope"] = "root_all"
    if to_save["cleanup_residual_folders_scope"] not in {"touched_only", "root_all"}:
        to_save["cleanup_residual_folders_scope"] = "touched_only"


def _apply_tmdb_key_persistence(
    to_save: Dict[str, Any], settings: Dict[str, Any], existing_settings: Dict[str, Any]
) -> None:
    """Applique remember_key + tmdb_api_key selon le payload + l'existant."""
    existing_tmdb_key = str(existing_settings.get("tmdb_api_key") or "").strip()
    remember_key = to_bool(settings.get("remember_key"), bool(existing_tmdb_key))
    to_save["remember_key"] = remember_key
    if not remember_key:
        to_save["tmdb_api_key"] = ""
        return
    if "tmdb_api_key" in settings:
        to_save["tmdb_api_key"] = str(settings.get("tmdb_api_key") or "").strip()
    else:
        to_save["tmdb_api_key"] = existing_tmdb_key


def _apply_jellyfin_key_persistence(
    to_save: Dict[str, Any], settings: Dict[str, Any], existing_settings: Dict[str, Any]
) -> None:
    """Persiste jellyfin_api_key (incoming si present, existant sinon)."""
    existing_jf_key = str(existing_settings.get("jellyfin_api_key") or "").strip()
    if "jellyfin_api_key" in settings:
        to_save["jellyfin_api_key"] = str(settings.get("jellyfin_api_key") or "").strip()
    else:
        to_save["jellyfin_api_key"] = existing_jf_key


def _build_save_result(state_dir: Path, write_meta: Dict[str, Any]) -> Dict[str, Any]:
    """Construit le dict resultat retourne au frontend apres write_settings."""
    result: Dict[str, Any] = {
        "ok": True,
        "state_dir": str(state_dir),
        "tmdb_key_persisted": bool(write_meta.get("tmdb_key_persisted")),
        "tmdb_key_protection": str(write_meta.get("tmdb_key_protection") or SECRET_PROTECTION_NONE),
        "jellyfin_key_persisted": bool(write_meta.get("jellyfin_key_persisted")),
    }
    if write_meta.get("tmdb_key_warning"):
        result["tmdb_key_warning"] = str(write_meta.get("tmdb_key_warning") or "")
    if write_meta.get("jellyfin_key_warning"):
        result["jellyfin_key_warning"] = str(write_meta.get("jellyfin_key_warning") or "")
    return result


# Audit ID-CODE-001 (V2-01) : ex-F=74, decoupe en helpers _save_section_*.
# Ce dispatcher orchestre la normalisation/validation de 50+ cles de settings.
def save_settings_payload(
    settings: Dict[str, Any],
    *,
    current_state_dir: Path,
    default_root: str,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
    default_probe_backend: str,
    debug_enabled: bool,
) -> Tuple[Path, Dict[str, Any]]:
    if not isinstance(settings, dict):
        return current_state_dir, {"ok": False, "message": t("errors.payload_settings_invalid")}

    state_dir, state_dir_present = resolve_payload_state_dir(settings, default_state_dir=current_state_dir)
    existing_settings = read_settings(state_dir)
    # Restaurer les secrets masques par get_settings_payload (ne pas ecraser avec le masque)
    _unmask_secrets_for_save(settings, existing_settings)
    roots_paths, roots_error = resolve_roots_from_payload(
        settings,
        state_dir=state_dir,
        state_dir_present=state_dir_present,
        current_state_dir=current_state_dir,
        default_root=default_root,
        missing_message=t("errors.root_required_save"),
    )
    if roots_error:
        return state_dir, {"ok": False, "message": roots_error}
    assert roots_paths is not None
    root_path = roots_paths[0] if roots_paths else Path(default_root)
    state_dir.mkdir(parents=True, exist_ok=True)

    to_save: Dict[str, Any] = {
        "root": str(root_path),
        "roots": [str(r) for r in roots_paths],
        "state_dir": str(state_dir),
    }
    to_save.update(_save_section_tmdb(settings))
    to_save.update(
        _save_section_cleanup(
            settings,
            default_collection_folder_name=default_collection_folder_name,
            default_empty_folders_folder_name=default_empty_folders_folder_name,
            default_residual_cleanup_folder_name=default_residual_cleanup_folder_name,
        )
    )
    to_save.update(_save_section_probe(settings, default_probe_backend=default_probe_backend))
    to_save.update(_save_section_scan_flags(settings))
    to_save.update(_save_section_jellyfin(settings))
    to_save.update(_save_section_plex(settings))
    to_save.update(_save_section_radarr(settings))
    to_save.update(_save_section_notifications(settings))
    to_save.update(_save_section_rest_api(settings))
    to_save.update(_save_section_watch(settings))
    to_save.update(_save_section_plugins(settings))
    to_save.update(_save_section_email(settings))
    to_save.update(_save_section_subtitles(settings))
    to_save.update(_save_section_perceptual(settings))
    to_save.update(_save_section_appearance(settings, debug_enabled=debug_enabled))

    # Profils de renommage : normaliser preset + templates
    _apply_naming_preset(to_save, settings)
    _normalize_scopes(to_save)
    _apply_tmdb_key_persistence(to_save, settings, existing_settings)
    _apply_jellyfin_key_persistence(to_save, settings, existing_settings)

    write_meta = write_settings(state_dir, to_save)
    return state_dir, _build_save_result(state_dir, write_meta)


def test_tmdb_key(
    api_key: str,
    state_dir: str,
    timeout_s: float = 10.0,
    *,
    default_state_dir: Path,
    tmdb_client_cls: Any = TmdbClient,
) -> Dict[str, Any]:
    resolved_api_key = str(api_key or "").strip()
    if not resolved_api_key:
        return err(t("errors.tmdb_key_empty"), category="validation", level="info")
    resolved_state_dir = normalize_user_path(state_dir, default_state_dir)
    cache = resolved_state_dir / "tmdb_cache.json"
    try:
        tmdb = tmdb_client_cls(api_key=resolved_api_key, cache_path=cache, timeout_s=float(timeout_s))
        ok_val, msg = tmdb.validate_key()
        tmdb.flush()
        return {"ok": bool(ok_val), "message": msg}
    except (OSError, TypeError, ValueError) as exc:
        return err(f"TMDb connection failed: {exc}", category="runtime", level="error")


def test_jellyfin_connection(
    url: str,
    api_key: str,
    timeout_s: float = 10.0,
    *,
    jellyfin_client_cls: Any = None,
) -> Dict[str, Any]:
    """Teste la connexion Jellyfin et retourne les infos serveur/utilisateur/bibliothèques."""
    # Import tardif pour éviter les imports circulaires au chargement du module
    if jellyfin_client_cls is None:
        from cinesort.infra.jellyfin_client import JellyfinClient

        jellyfin_client_cls = JellyfinClient

    url = _normalize_jellyfin_url(url)
    api_key = str(api_key or "").strip()
    if not url:
        return err(t("errors.jellyfin_url_empty"), category="validation", level="info")
    if not api_key:
        return err(t("errors.jellyfin_key_empty"), category="validation", level="info")

    try:
        client = jellyfin_client_cls(url, api_key, timeout_s=float(timeout_s))
        result = client.validate_connection()
        if not result.get("ok"):
            return err(
                result.get("error", t("errors.connection_failed")),
                category="runtime",
                level="warning",
            )

        # Enrichir avec les bibliothèques
        user_id = result.get("user_id", "")
        libraries = []
        movies_count = 0
        if user_id:
            try:
                libraries = client.get_libraries(user_id)
                movies_count = client.get_movies_count(user_id)
            except (ConnectionError, KeyError, OSError, TimeoutError, TypeError, ValueError) as exc:
                logger.debug("Jellyfin: erreur récupération bibliothèques: %s", exc)

        return {
            "ok": True,
            "server_name": result.get("server_name", ""),
            "version": result.get("version", ""),
            "user_id": user_id,
            "user_name": result.get("user_name", ""),
            "is_admin": result.get("is_admin", False),
            "libraries": libraries,
            "movies_count": movies_count,
        }
    except (ConnectionError, KeyError, OSError, TimeoutError, TypeError, ValueError) as exc:
        return err(f"Jellyfin connection failed: {exc}", category="runtime", level="error")


# Audit ID-J-001 (V1-M10) : API publique pour gestion UI des backups settings.
def list_settings_backups(state_dir: Path) -> List[Dict[str, Any]]:
    """Liste les backups disponibles avec metadata, plus recents en premier."""
    target_path = settings_path(state_dir)
    pattern = f"{target_path.name}{SETTINGS_BACKUP_PREFIX}*"
    out: List[Dict[str, Any]] = []
    for p in sorted(target_path.parent.glob(pattern), key=lambda x: x.stat().st_mtime, reverse=True):
        st = p.stat()
        out.append({"path": str(p), "name": p.name, "mtime": st.st_mtime, "size": st.st_size})
    return out


def restore_settings_backup(state_dir: Path, backup_filename: str) -> bool:
    """Restaure un backup specifique. Retourne True si succes.

    Garde-fou path traversal : `backup_filename` doit etre un nom simple
    (pas de separateur) et matcher le prefixe `settings.json.bak.`.
    """
    if "/" in backup_filename or "\\" in backup_filename or ".." in backup_filename:
        return False
    target_path = settings_path(state_dir)
    expected_prefix = target_path.name + SETTINGS_BACKUP_PREFIX
    if not backup_filename.startswith(expected_prefix):
        return False
    backup_path = target_path.parent / backup_filename
    if not backup_path.exists():
        return False
    try:
        # Backup l'actuel avant restore (au cas ou)
        _backup_settings_before_write(target_path)
        _rotate_settings_backups(target_path)
        shutil.copy2(backup_path, target_path)
        return True
    except OSError:
        return False

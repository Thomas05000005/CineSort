from __future__ import annotations

import copy
import json
import logging
import os
import re
import secrets
import shutil
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

import cinesort.domain.core as core
import cinesort.infra.state as state
from cinesort.app.updater import is_valid_github_repo
from cinesort.domain.conversions import to_bool, to_float, to_int
from cinesort.domain.i18n_messages import t
from cinesort.domain.naming import PRESETS, validate_template

# Fix audit 2026-05-26 (v1.5.6) Vague L : jellyfin-1 — JellyfinError doit etre
# importe pour etre catche dans test_jellyfin_connection (sinon l'exception
# s'echappe et le caller voit un crash plutot qu'un message utilisateur).
from cinesort.infra.jellyfin_client import JellyfinClient, JellyfinError
from cinesort.infra.local_secret_store import (
    SECRET_PROTECTION_NONE,
    SECRET_PROTECTION_UNAVAILABLE,
    WINDOWS_DPAPI_CURRENT_USER,
    protect_secret,
)
from cinesort.infra.log_context import is_remote_request, normalize_log_level_setting
from cinesort.infra.security import secret_storage as _secret_storage
from cinesort.infra.tmdb_client import TmdbClient
from cinesort.ui.api._responses import err

logger = logging.getLogger(__name__)

# Hotfix sentinel : pattern `int(payload.get(k) or DEFAULT)` ecrase 0 (et "" ou None)
# par DEFAULT. Or l'utilisateur peut legitimement vouloir 0 (ex: perceptual_skip_percent).
# `_coerce_int_with_default(value, default)` distingue absence/erreur (-> default)
# de valeur entiere convertible (y compris 0).
_MISSING = object()


# Fix lost-update : verrou par state_dir pour serialiser read-modify-write de
# save_settings_payload. Deux appels paralleles (UI Parametres + endpoint REST
# /api/save_settings) lisaient le meme existing_settings et le dernier write
# ecrasait silencieusement les modifications du premier. Le dict est protege
# par _SETTINGS_WRITE_LOCKS_GUARD pour eviter une race a la creation du Lock
# lui-meme. Pattern aligne sur cinesort_api._state_dir_lock.
_SETTINGS_WRITE_LOCKS: Dict[str, "threading.Lock"] = {}
_SETTINGS_WRITE_LOCKS_GUARD = threading.Lock()


def _get_settings_write_lock(state_dir: Path) -> "threading.Lock":
    """Retourne (et cree si necessaire) le Lock dedie a un state_dir donne."""
    key = str(state_dir)
    with _SETTINGS_WRITE_LOCKS_GUARD:
        lock = _SETTINGS_WRITE_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _SETTINGS_WRITE_LOCKS[key] = lock
        return lock


def _coerce_int_with_default(value: Any, default: int) -> int:
    """Convertit value en int en preservant la valeur 0 (vs `x or default` qui l'ecrase).

    - None, "", _MISSING -> default
    - "0", 0, 0.0 -> 0 (legitime)
    - ValueError/TypeError -> default
    """
    if value is None or value is _MISSING:
        return default
    if isinstance(value, bool):
        # bool est int : on rejette pour eviter True->1 / False->0 silencieux
        return default
    if isinstance(value, str):
        cleaned = value.strip()
        if not cleaned:
            return default
        try:
            return int(cleaned)
        except (TypeError, ValueError):
            try:
                return int(float(cleaned))
            except (TypeError, ValueError):
                return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


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

# Phase 6.2 : OMDb API key (cross-check IMDb pour identification).
OMDB_KEY_SECRET_FIELD = "omdb_api_key_secret"
OMDB_KEY_PURPOSE = "omdb_api_key"

# [SEC-2] Bearer token de l'API REST locale. Auparavant stocke EN CLAIR dans
# settings.json (seul secret non chiffre) : un settings.json exfiltre donnait
# l'acces API LAN. Desormais chiffre au repos sous l'enveloppe {scheme, blob_b64}
# comme les autres secrets. read_settings dechiffre -> `rest_api_token` clair en
# memoire (consomme par le boot serveur REST, reveal_rest_token, hot-reload) ;
# write_settings re-chiffre ; _mask_secrets masque au GET frontend.
REST_TOKEN_SECRET_FIELD = "rest_api_token_secret"
REST_TOKEN_PURPOSE = "rest_api_token"

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
        # Hotfix BOM : utf-8-sig tolere un BOM en tete (sinon json.loads echoue silencieusement
        # et l'on saute le backup d'un fichier pourtant valide, masquant une corruption ulterieure).
        json.loads(settings_path.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, OSError):
        return None
    # Microsecondes pour rester unique meme si plusieurs writes dans la meme
    # seconde (sinon les backups s'ecrasent et la rotation perd des fichiers).
    # Sur Windows, la granularite du timer systeme est ~15 ms, donc plusieurs
    # `datetime.now()` rapproches peuvent retourner les memes microsecondes :
    # on resout les collisions de nom en ajoutant un suffixe `-N`.
    ts = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    base_name = f"{settings_path.name}{SETTINGS_BACKUP_PREFIX}{ts}"
    backup_path = settings_path.parent / base_name
    counter = 1
    while backup_path.exists():
        backup_path = settings_path.parent / f"{base_name}-{counter}"
        counter += 1
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
    # Cle secondaire `p.name` : sur Windows, st_mtime peut etre identique pour
    # plusieurs fichiers crees a < 15 ms d'intervalle. Le nom contient le
    # timestamp formate (et l'eventuel suffixe `-N`), donc l'ordre lexico
    # decroissant des noms correspond a l'ordre temporel quand les mtimes
    # collisionnent. Sans cette cle, la rotation pouvait supprimer le mauvais
    # fichier (ordre non-deterministe).
    backups = sorted(
        settings_path.parent.glob(pattern),
        key=lambda p: (p.stat().st_mtime, p.name),
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


# [SEC-3] Migration DPAPI legacy -> DPAPI-NG. Les 5 secrets (TMDb, Jellyfin,
# Plex, Radarr, SMTP) etaient chiffres via `protect_secret`/`unprotect_secret`
# (DPAPI CurrentUser legacy). On route desormais par la couche NG
# (`secret_storage`), qui : (1) chiffre TOUJOURS en NG a l'ecriture ; (2) lit
# indifferemment un blob NG (magic) ou legacy (fallback transparent) a la
# lecture. L'enveloppe de stockage {scheme, blob_b64} est INCHANGEE : le champ
# `scheme` reste WINDOWS_DPAPI_CURRENT_USER (marqueur "protege DPAPI"), NG vs
# legacy se distinguant par le magic du blob. Retro-compat totale : un
# settings.json existant (blobs legacy) reste lisible ; la migration effective
# se fait au prochain SAVE (chemin d'ecriture -> NG). Signatures identiques aux
# helpers legacy pour un swap 1:1 des sites d'appel.


def _protect_secret_ng(raw: str, *, purpose: str) -> Tuple[bool, str, str]:
    """Chiffre `raw` en DPAPI-NG. Repli legacy si NG indisponible.

    Retourne (ok, blob_b64, error), meme contrat que `protect_secret`.
    """
    try:
        return True, _secret_storage.save_secret(purpose, raw), ""
    except _secret_storage.SecretStorageError:
        # NG indisponible (Windows tres ancien sans ncrypt) : on ne regresse pas
        # la protection — repli sur DPAPI legacy (toujours present via crypt32).
        return protect_secret(raw, purpose=purpose)


def _unprotect_secret_ng(blob_b64: str, *, purpose: str) -> Tuple[bool, str, str]:
    """Dechiffre un blob NG OU legacy (retro-compat). (ok, value, error).

    `secret_storage.load_secret` gere le routage NG/legacy. La re-ecriture en NG
    du blob (migration disque) intervient au prochain SAVE, pas ici (les
    extracteurs de lecture ne mutent pas settings.json).
    """
    try:
        result = _secret_storage.load_secret(purpose, blob_b64)
        return True, result.value, ""
    except _secret_storage.SecretStorageError as exc:
        return False, "", str(exc)


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
            ok, value, error = _unprotect_secret_ng(blob_b64, purpose=purpose)
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

    Hotfix DPAPI : si `_orig_<secret_field>` existe (blob chiffre legitime que
    read_settings n'a pas pu dechiffrer), on le reinjecte au lieu d'ecraser
    par une chaine vide. Ainsi un cycle read->save sans modification ne perd
    pas le secret.

    Retourne (persisted, warning_message).
    """
    raw = str(payload.pop(legacy_field, "") or "").strip()
    payload.pop(secret_field, None)
    orig_blob = payload.pop(f"_orig_{secret_field}", None)
    if not raw:
        # Pas de nouvelle valeur claire : on preserve l'eventuel blob original
        if isinstance(orig_blob, dict):
            payload[secret_field] = orig_blob
        return False, ""
    ok, blob_b64, error = _protect_secret_ng(raw, purpose=purpose)
    if ok and blob_b64:
        payload[secret_field] = {
            "scheme": WINDOWS_DPAPI_CURRENT_USER,
            "blob_b64": blob_b64,
        }
        return True, ""
    # Chiffrement KO : preserve l'original si on en avait un (sinon le secret est perdu)
    if isinstance(orig_blob, dict):
        payload[secret_field] = orig_blob
    return False, f"Protection indisponible ({purpose}): {error}" if error else f"Protection indisponible ({purpose})."


def _normalize_jellyfin_url(url: str) -> str:
    """Normalise l'URL Jellyfin (strip, trailing slash, prefix http)."""
    url = (url or "").strip().rstrip("/")
    if url and not url.startswith(("http://", "https://")):
        url = f"http://{url}"
    return url


def _normalize_lang_list(raw: Any) -> List[str]:
    """Normalise une liste de codes langue depuis le payload settings.

    AUDIT 2026-06-11 (R4-P11) : le hint UI dit "Separees par ;" mais le split
    n'acceptait que la virgule -> "fr;en" persistait ['fr;en'] (token poubelle,
    warnings subtitle_missing faux). On accepte ';' ET ','.
    """
    if isinstance(raw, list):
        return [str(l).strip().lower() for l in raw if str(l).strip()]
    if isinstance(raw, str) and raw.strip():
        return [l.strip().lower() for l in re.split(r"[;,]", raw) if l.strip()]
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
# VN-B.1 (Vague N batch 2) : V2 devient la source de verite unique.
# - Defaut bascule de 1 -> 2 : nouveau scoring expose le vocabulaire
#   Platinum/Gold/Silver/Bronze/Reject de v7.5.0.
# - V1 reste accepte uniquement comme kill-switch de rollback explicite
#   (settings.composite_score_version=1) pour les utilisateurs qui voudraient
#   l'ancien vocabulaire reference/excellent/bon/mediocre/degrade le temps
#   d'un re-scan. Tout autre input invalide retombe sur le defaut (V2).
COMPOSITE_SCORE_VERSIONS: Tuple[int, ...] = (1, 2)
DEFAULT_COMPOSITE_SCORE_VERSION: int = 2

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
    """Clamp `composite_score_version` a {1, 2}, fallback V2 si invalide.

    VN-B.1 : depuis Vague N batch 2, V2 est la source de verite par defaut.
    V1 reste accepte comme kill-switch de rollback explicite (vocabulaire
    legacy reference/excellent/bon/mediocre/degrade).

    Accepte int ou string ("1"/"2"/"v1"/"v2") pour tolerer les payloads UI
    et les anciennes configs deja persistees. Toute autre valeur (None, 3,
    "abc", float NaN, ...) retombe sur le defaut V2.
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
            ok, value, error = _unprotect_secret_ng(blob_b64, purpose=TMDB_KEY_PURPOSE)
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
            ok, value, error = _unprotect_secret_ng(blob_b64, purpose=JELLYFIN_KEY_PURPOSE)
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
        # Hotfix BOM : utf-8-sig tolere un eventuel BOM (Notepad/PowerShell sous
        # Windows en ajoutent souvent). utf-8 strict levait UnicodeDecodeError
        # et toute la config etait perdue silencieusement.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if not isinstance(data, dict):
            return {}
        # Hotfix DPAPI : on PRESERVE les blobs chiffres originaux dans des
        # champs _orig_* si le dechiffrement echoue, pour permettre a
        # write_settings de les reinjecter tels quels (sinon ecrasement
        # destructif du blob legitime au prochain save).
        orig_tmdb_blob = data.get(TMDB_KEY_SECRET_FIELD)
        secret_value, protection, warning = extract_tmdb_key_from_settings_payload(data)
        data.pop(TMDB_KEY_SECRET_FIELD, None)
        data["tmdb_api_key"] = secret_value
        data["tmdb_key_protection"] = protection
        if warning:
            data["tmdb_key_warning"] = warning
            # DPAPI a echoue mais le blob etait valide : conserver pour write_settings
            if isinstance(orig_tmdb_blob, dict):
                data["_orig_tmdb_api_key_secret"] = orig_tmdb_blob
        else:
            data.pop("tmdb_key_warning", None)

        orig_jf_blob = data.get(JELLYFIN_KEY_SECRET_FIELD)
        jf_value, jf_protection, jf_warning = extract_jellyfin_key_from_settings_payload(data)
        data.pop(JELLYFIN_KEY_SECRET_FIELD, None)
        data["jellyfin_api_key"] = jf_value
        data["jellyfin_key_protection"] = jf_protection
        if jf_warning:
            data["jellyfin_key_warning"] = jf_warning
            if isinstance(orig_jf_blob, dict):
                data["_orig_jellyfin_api_key_secret"] = orig_jf_blob
        else:
            data.pop("jellyfin_key_warning", None)

        # S4 audit : Plex / Radarr / SMTP password — lecture DPAPI avec fallback legacy
        # Phase 6.2 : OMDb API key — meme pattern DPAPI
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
            (
                "omdb_api_key",
                OMDB_KEY_SECRET_FIELD,
                OMDB_KEY_PURPOSE,
                "omdb_key_protection",
                "omdb_key_warning",
            ),
        ):
            orig_blob = data.get(secret_field)
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
                # Preserve blob chiffre si DPAPI a echoue
                if isinstance(orig_blob, dict):
                    data[f"_orig_{secret_field}"] = orig_blob
            else:
                data.pop(warning_key, None)

        # [SEC-2] rest_api_token : dechiffrer l'enveloppe -> valeur claire en
        # memoire. Retro-compat : un settings.json d'avant SEC-2 porte un
        # `rest_api_token` EN CLAIR sans enveloppe -> on le laisse tel quel (il
        # sera migre, valeur INCHANGEE, au prochain write_settings).
        rest_secret = data.get(REST_TOKEN_SECRET_FIELD)
        if isinstance(rest_secret, dict):
            data.pop(REST_TOKEN_SECRET_FIELD, None)
            scheme = str(rest_secret.get("scheme") or "").strip().lower()
            blob_b64 = str(rest_secret.get("blob_b64") or "").strip()
            if scheme == WINDOWS_DPAPI_CURRENT_USER and blob_b64:
                ok_rt, value_rt, _err_rt = _unprotect_secret_ng(blob_b64, purpose=REST_TOKEN_PURPOSE)
                if ok_rt:
                    data["rest_api_token"] = value_rt
                else:
                    # Blob illisible (reinstall Windows / changement de profil) :
                    # ne pas ecraser par du vide -> preserver le blob pour un
                    # futur re-essai ; token clair vide (auth distante a
                    # re-generer). apply_settings_defaults en generera un neuf.
                    data["rest_api_token"] = ""
                    data["_orig_rest_api_token_secret"] = rest_secret

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
        except (OSError, ValueError):
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
        except (KeyError, OSError, TypeError, ValueError):
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
    # Hotfix DPAPI : si la lecture precedente a echoue a dechiffrer, on a un
    # blob original preserve dans `_orig_*` qui doit etre reinjecte tel quel
    # plutot que d'etre ecrase par une chaine vide (data-loss).
    orig_tmdb_blob = payload.pop("_orig_tmdb_api_key_secret", None)
    remember_key = to_bool(payload.get("remember_key"), False)

    protection = SECRET_PROTECTION_NONE
    warning = ""
    persisted = False

    if remember_key and secret_value:
        ok, blob_b64, error = _protect_secret_ng(secret_value, purpose=TMDB_KEY_PURPOSE)
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
            # Preserve blob legitime ininterpretable plutot que de l'effacer
            if isinstance(orig_tmdb_blob, dict):
                payload[TMDB_KEY_SECRET_FIELD] = orig_tmdb_blob
    else:
        payload["remember_key"] = False if not secret_value else remember_key
        # Aucune cle clair fournie mais on avait un blob illisible : conserver
        if not secret_value and isinstance(orig_tmdb_blob, dict):
            payload[TMDB_KEY_SECRET_FIELD] = orig_tmdb_blob

    # --- Jellyfin API key (DPAPI) ---
    jf_secret = str(payload.pop("jellyfin_api_key", "") or "").strip()
    payload.pop("jellyfin_key_protection", None)
    payload.pop("jellyfin_key_warning", None)
    payload.pop(JELLYFIN_KEY_SECRET_FIELD, None)
    orig_jf_blob = payload.pop("_orig_jellyfin_api_key_secret", None)
    jf_persisted = False
    jf_warning = ""

    if jf_secret:
        ok_jf, blob_jf, err_jf = _protect_secret_ng(jf_secret, purpose=JELLYFIN_KEY_PURPOSE)
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
            if isinstance(orig_jf_blob, dict):
                payload[JELLYFIN_KEY_SECRET_FIELD] = orig_jf_blob
    elif isinstance(orig_jf_blob, dict):
        payload[JELLYFIN_KEY_SECRET_FIELD] = orig_jf_blob

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

    # Phase 6.2 : OMDb API key (DPAPI)
    omdb_persisted, omdb_warning = _persist_protected_secret(
        payload,
        legacy_field="omdb_api_key",
        secret_field=OMDB_KEY_SECRET_FIELD,
        purpose=OMDB_KEY_PURPOSE,
    )
    payload.pop("omdb_key_protection", None)
    payload.pop("omdb_key_warning", None)

    # [SEC-2] rest_api_token : chiffrer au repos (jamais ecrit en clair sur
    # disque). La valeur claire vient de _save_section_rest_api (echo unmask).
    # Repli sur stockage clair UNIQUEMENT si DPAPI est totalement indisponible
    # (NG + legacy KO -> plateforme non-Windows) : la cible etant Windows, le
    # token est toujours chiffre en prod ; on ne casse pas l'auth ailleurs.
    rest_token = str(payload.pop("rest_api_token", "") or "").strip()
    payload.pop(REST_TOKEN_SECRET_FIELD, None)
    orig_rest_blob = payload.pop("_orig_rest_api_token_secret", None)
    if rest_token:
        ok_rt, blob_rt, _err_rt = _protect_secret_ng(rest_token, purpose=REST_TOKEN_PURPOSE)
        if ok_rt and blob_rt:
            payload[REST_TOKEN_SECRET_FIELD] = {
                "scheme": WINDOWS_DPAPI_CURRENT_USER,
                "blob_b64": blob_rt,
            }
        else:
            payload["rest_api_token"] = rest_token  # repli clair (non-Windows)
    elif isinstance(orig_rest_blob, dict):
        # Aucune valeur claire (blob illisible a la lecture) : preserver le blob
        # d'origine plutot que de perdre definitivement le secret.
        payload[REST_TOKEN_SECRET_FIELD] = orig_rest_blob

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
        "omdb_key_persisted": omdb_persisted,
        "omdb_key_warning": omdb_warning,
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
    # --- Profils qualite personnalises (bibliotheque durable) ---
    # Cf. `_save_section_quality_profiles` : ces deux cles n'etaient reclamees
    # par aucune section d'ecriture, donc jamais persistees.
    ("custom_quality_profiles", []),
    ("active_quality_profile_id", ""),
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
    # VO-B-CONFIG : scan_max_workers tri-etat auto/manuel. Default "auto" +
    # value=1 garde la backward compat stricte si l'utilisateur n'a jamais
    # touche au setting (la resolution effective passe par
    # resolve_effective_scan_max_workers qui delegue a VO-A detect_storage).
    ("scan_max_workers_mode", "auto"),
    ("scan_max_workers_value", 1),
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
    # Cf issue #92 quick win #6 : default = apply done + errors uniquement,
    # le reste off. Reduit le spam pour le power user qui scan souvent.
    # L'utilisateur peut activer les autres via Settings -> Notifications.
    ("notifications_enabled", False),
    ("notifications_scan_triggered", False),  # cf #108 : watcher detecte un changement
    ("notifications_scan_done", False),
    ("notifications_apply_done", True),
    ("notifications_undo_done", False),
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
    # Fix audit 2026-05-25 (v1.5.4) Vague I : BUG 1 — declenche le calcul des
    # scores qualite V1 (tier) automatiquement en background apres chaque scan.
    # Sans ce flag les rows restent "Non identifie" tant que l'utilisateur ne
    # clique pas sur "Re-calculer les scores" dans la page Qualite.
    ("auto_recompute_quality_on_scan", True),
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
    # AUDIT 2026-06-11 (R4-P10) : "lowercase_extensions" a vecu ici. RETIRE :
    # le reglage ne servait qu'a renommer le fichier video (.MKV -> .mkv), ce
    # qu'interdit la regle inviolable n1. Ne pas le reintroduire.
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
    # Fix audit 2026-05-24 : default theme etait "studio" ici mais "luxe" dans
    # _save_section_appearance (fallback _normalize_enum). Incoherence : un user
    # qui clear le theme via API recevait "luxe", mais un nouveau settings.json
    # avait "studio". Aligne sur "luxe" (default UI documente).
    ("theme", "luxe"),
    ("animation_level", "moderate"),
    ("effect_speed", 50),
    ("glow_intensity", 30),
    ("light_intensity", 20),
    # --- Phase 6.2 : OMDb cross-check ---
    ("omdb_enabled", False),
    ("omdb_api_key", ""),
    # Seuil : appel OMDb seulement si confidence TMDb < ce seuil (default 90)
    ("omdb_min_confidence_for_call", 90),
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
        payload["rest_api_token"] = secrets.token_urlsafe(24)

    # V6-01 (R4-I18N-4) : locale clamp via _normalize_locale a {"fr", "en"}, defaut "fr"
    payload["locale"] = _normalize_locale(payload.get("locale"))

    # V4-05 (R4-PERC-7 / H16) : composite_score_version normalise.
    # VN-B.1 (Vague N batch 2) : V2 par defaut. Les configs existantes sans
    # champ explicite migrent silencieusement vers V2 (lecture unique de
    # source de verite, plus de vocabulaire mixte reference/platinum cote UI).
    payload["composite_score_version"] = _normalize_composite_score_version(payload.get("composite_score_version"))

    # V3-04 (R4-LOG-3) : log_level normalise (DEBUG/INFO/WARNING/ERROR/CRITICAL)
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


def normalize_video_exts_setting(raw: Any) -> Set[str]:
    """Normalise la saisie « Extensions video acceptees » en set `.ext`.

    Tolere une liste ou une chaine `;`/`,`-separee (le champ UI est un `text`,
    mais `settings.json` peut avoir ete edite a la main), avec ou sans point de
    tete, casse quelconque. Les entrees vides ou reduites a des points sont
    droppees. Retourne un set vide si rien d'exploitable — l'appelant decide
    alors du repli.
    """
    if raw is None:
        return set()
    if isinstance(raw, str):
        items: Iterable[Any] = re.split(r"[;,\s]+", raw)
    elif isinstance(raw, (list, tuple, set, frozenset)):
        items = list(raw)
    else:
        return set()
    out: Set[str] = set()
    for item in items:
        ext = str(item or "").strip().lower().lstrip(".").strip()
        if not ext:
            continue
        out.add(f".{ext}")
    return out


def resolve_video_exts(raw_video_exts: Any) -> Set[str]:
    """Set d'extensions video EFFECTIF du scan, depuis la saisie utilisateur.

    Defaut (aucune saisie) : `VIDEO_EXTS_DEFAULT | VIDEO_EXTS_ALL` — c'est
    l'union historique posee par SCAN-1 pour la parite avec `apply_core`
    (`.iso` par exemple n'est que dans VIDEO_EXTS_ALL).

    Saisie EXPLICITE : elle fait AUTORITE, sans union. L'union etait appliquee
    dans les deux cas, ce qui rendait le reglage ADDITIF au lieu de RESTRICTIF —
    mesure du 2026-08-03 sur un bac a sable de 5 films : `.avi` retire de la
    liste, les deux dossiers `.avi` restaient planifies et comptaient dans les
    5 renommages de dossier du dry-run. Un champ nomme « Extensions video
    ACCEPTEES » qui ne sait pas refuser une extension est un perimetre en
    trompe-l'oeil.

    Garde anti-bibliotheque-vide : une saisie qui ne normalise vers RIEN
    (champ vide, `";;;"`, `"..."`) retombe sur le defaut. Vider le champ =
    revenir aux extensions par defaut, jamais « n'accepter aucune video ».

    NB : on ne retombe volontairement PAS sur `file_extensions` (la cle du champ
    UI) quand `video_exts` est absente. `_save_section_sources` ecrit les deux
    ensemble depuis R4-P12 ; une install anterieure n'ayant que `file_extensions`
    porte une valeur qui n'a JAMAIS filtre quoi que ce soit, et la restreindre
    d'un coup au premier scan post-mise-a-jour serait la surprise que ce lot
    cherche precisement a eviter.
    """
    default_exts = set(core.VIDEO_EXTS_DEFAULT) | set(core.VIDEO_EXTS_ALL)
    explicit = normalize_video_exts_setting(raw_video_exts)
    if not explicit:
        return default_exts
    if explicit != default_exts:
        logger.info(
            "scan: extensions video RESTREINTES par les reglages -> %s",
            ";".join(sorted(explicit)),
        )
    return explicit


def resolve_incremental_scan_enabled(requested: bool, excluded_patterns: Tuple[str, ...]) -> bool:
    """`incremental_scan_enabled` effectif, desarme si des patterns sont actifs.

    `cfg_signature_for_incremental` (app/plan_support_core.py) enumere les
    reglages qui CHANGENT la sortie du plan : toute cle absente de sa charge
    utile peut etre modifiee sans invalider les caches incrementaux. Les
    patterns d'exclusion n'y figurent pas. Sans garde, la sequence « scan
    incremental, puis ajout d'un pattern, puis re-scan » donnerait un cache
    DOSSIER intact (`_try_apply_folder_cache`) qui rejoue les lignes d'AVANT
    l'exclusion : le perimetre serait de nouveau muet, exactement le defaut que
    ce lot corrige.

    On desarme donc le cache incremental tant que des patterns sont actifs.
    C'est le sens SUR (un scan complet est lent, jamais faux) et c'est
    journalise, pas silencieux. Correctif durable, hors du perimetre de ce
    module : ajouter `excluded_patterns` a la charge utile de
    `cfg_signature_for_incremental` — ajouter une cle a ce payload suffit a
    changer le sha1, donc a invalider le cache une seule fois (meme raisonnement
    que F08, cf. le commentaire de `_PLAN_CACHE_VERSION`).
    """
    if requested and excluded_patterns:
        logger.info(
            "scan: cache incremental desarme — %d pattern(s) d'exclusion actif(s) "
            "ne sont pas couverts par la signature de cache",
            len(excluded_patterns),
        )
        return False
    return bool(requested)


def build_cfg_from_settings(
    settings: Dict[str, Any],
    *,
    root: Path,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
    state_dir: Optional[Path] = None,
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
    # Perimetre du pipeline destructif (revue 2026-08-03) : les deux reglages
    # sont lus ICI, dans la fonction qui construit le Config du scan, pour rester
    # visibles du contrat M3 (tests/test_contract_settings.py n'accepte une
    # lecture de settings_support que dans ses CONSUMER_FUNCS).
    video_exts = resolve_video_exts(settings.get("video_exts"))
    excluded_patterns = core.normalize_excluded_patterns(settings.get("excluded_patterns"))
    incremental_scan_enabled = resolve_incremental_scan_enabled(
        to_bool(settings.get("incremental_scan_enabled"), False),
        excluded_patterns,
    )
    # VO-B-CONFIG : determine scan_max_workers effectif depuis le payload.
    # - mode="manual" -> on prend value clampe [1..64]
    # - mode="auto"  + state_dir fourni -> resolution via
    #     `_detect_storage_profile(state_dir)` + `_auto_scan_max_workers_for_storage`
    #     pour que l'UI Settings (qui affiche `effective: 4|8`) corresponde au
    #     reel des scans (PRAGMA-02 fix).
    # - mode="auto" sans state_dir (code-path build depuis run_row, settings
    #     absents...) -> retombe sur 1 (sequentiel strict) pour preserver la
    #     backward compat.
    cfg_mode = _normalize_scan_max_workers_mode(settings.get("scan_max_workers_mode"))
    cfg_value = _normalize_scan_max_workers_value(settings.get("scan_max_workers_value"))
    if cfg_mode == "manual":
        cfg_scan_workers = cfg_value
    elif state_dir is not None:
        # Mode auto + contexte state_dir : aligne sur l'UI (auto_suggestion).
        try:
            detected = _detect_storage_profile(state_dir)
            cfg_scan_workers = _auto_scan_max_workers_for_storage(detected)
        except (OSError, ValueError, TypeError):
            cfg_scan_workers = _DEFAULT_SCAN_MAX_WORKERS_VALUE
    else:
        cfg_scan_workers = _DEFAULT_SCAN_MAX_WORKERS_VALUE
    # Cluster settings iter6 — naming_preset resync au call site :
    # `_apply_naming_preset` (L1239-1261) reecrit `naming_movie_template` /
    # `naming_tv_template` UNIQUEMENT au save. Si `settings.json` est edite
    # hors UI ou via migration en ecrivant `naming_preset="plex"` sans
    # resynchroniser les templates, `build_cfg_from_settings` lisait alors
    # les anciens templates -> preset utilisateur silencieusement avale.
    # Resync deterministe ici : preset != "custom" -> on prend les templates
    # du preset (source de verite identique a `_apply_naming_preset`),
    # preset == "custom" ou absent -> on garde les templates persistes.
    cfg_naming_preset = str(settings.get("naming_preset") or "").strip().lower()
    if cfg_naming_preset in _VALID_NAMING_PRESETS and cfg_naming_preset != "custom":
        _preset_profile = PRESETS.get(cfg_naming_preset) or PRESETS["default"]
        cfg_movie_template = _preset_profile.movie_template
        cfg_tv_template = _preset_profile.tv_template
    else:
        cfg_movie_template = str(settings.get("naming_movie_template") or "{title} ({year})")
        cfg_tv_template = str(settings.get("naming_tv_template") or "{series} ({year})")
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
        video_exts=video_exts,
        excluded_patterns=excluded_patterns,
        enable_tmdb=to_bool(settings.get("tmdb_enabled"), True),
        incremental_scan_enabled=incremental_scan_enabled,
        enable_tv_detection=to_bool(settings.get("enable_tv_detection"), False),
        scan_max_workers=cfg_scan_workers,
        naming_movie_template=cfg_movie_template,
        naming_tv_template=cfg_tv_template,
        # ITER7 etape 3 : approvisionnement separator Domain (drop silencieux
        # historique au save). Le coerce-and-default est aussi applique cote
        # _save_section_naming (settings_support.py:1611-1613) mais on duplique
        # la garde ici pour resister aux settings.json edites a la main.
        separator=(
            str(settings.get("separator") or " ")
            if str(settings.get("separator") or " ") in {".", " ", "_", "-"}
            else " "
        ),
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
# SEC-H3 (fix) : rest_api_token EST de nouveau masque ci-dessous. Le commentaire
# historique "BUG 1" justifiait son retrait au motif que l'utilisateur doit pouvoir
# voir son propre token pour le partager a ses appareils. Probleme : un attaquant
# avec acces transitoire (token LAN temporaire, XSS via CSP style-src 'unsafe-inline',
# log accidentel) peut exfiltrer le Bearer en UN SEUL appel a /api/settings/get_settings,
# contournant tout futur kill-switch. La revelation explicite doit passer par un endpoint
# dedie (reveal_rest_token) avec confirmation UI et restriction localhost (is_remote_request).
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
    # Phase 6.2 : OMDb API key (cross-check IMDb)
    "omdb_api_key",
    # SEC-H3 : Bearer token de l'API REST locale. Re-ajoute apres avoir ete
    # retire par erreur (BUG 1). La revelation explicite doit passer par
    # l'endpoint dedie POST /api/settings/reveal_rest_token (localhost only).
    "rest_api_token",
)


def _mask_secrets(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Masque les secrets avant envoi au frontend. Ajoute _has_<field> pour chaque secret."""
    for field in _SECRET_FIELDS:
        value = str(payload.get(field) or "").strip()
        payload[f"_has_{field}"] = bool(value)
        if value:
            payload[field] = _SECRET_MASK
    # [SEC-2 FIX-3] Ne jamais exposer les blobs `_orig_*` (enveloppes chiffrees
    # preservees par read_settings quand un dechiffrement echoue) sur la surface
    # GET externe : internes de persistance, pas des champs UI. Machine-bound
    # donc inutiles ailleurs, mais on n'expose aucun materiel secret au frontend.
    for key in [k for k in payload if k.startswith("_orig_")]:
        payload.pop(key, None)
    return payload


def _unmask_secrets_for_save(incoming: Dict[str, Any], existing: Dict[str, Any]) -> None:
    """Si le frontend renvoie le masque, on garde la valeur existante."""
    for field in _SECRET_FIELDS:
        val = str(incoming.get(field) or "").strip()
        if val == _SECRET_MASK:
            # L'utilisateur n'a pas modifie — conserver la valeur existante
            incoming[field] = str(existing.get(field) or "").strip()


def get_confidence_thresholds_payload() -> Dict[str, Any]:
    """VN-C.1 (batch 2) : seuils de confidence partages backend+frontend.

    Source unique : cinesort/domain/confidence_thresholds.py. Le dashboard
    consomme cet endpoint au demarrage et garde les valeurs en cache
    module-level (web/dashboard/core/api.js -> fetchConfidenceThresholds).
    """
    from cinesort.domain.confidence_thresholds import get_confidence_thresholds  # noqa: PLC0415

    return {
        "ok": True,
        "thresholds": get_confidence_thresholds(),
    }


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
        # Audit 2026-06-18 : clamp [1.0, 60.0] aligne sur jellyfin/plex/radarr (cf #602).
        "tmdb_timeout_s": max(1.0, min(60.0, to_float(payload.get("tmdb_timeout_s"), 10.0))),
        "tmdb_cache_ttl_days": ttl_days,
    }


def _save_section_cleanup(
    payload: Dict[str, Any],
    *,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
) -> Dict[str, Any]:
    # Fix audit 2026-05-25 (v1.5.3) Vague F : alias UI collection_folder -> backend collection_folder_name.
    # L'UI envoie historiquement la cle "collection_folder" mais le backend lit
    # "collection_folder_name", donc le champ etait silencieusement ecrase par
    # le defaut (_Collection) a chaque save.
    collection_folder_value = payload.get("collection_folder")
    if collection_folder_value is None:
        collection_folder_value = payload.get("collection_folder_name")
    collection_folder_name = (
        str(collection_folder_value or default_collection_folder_name).strip() or default_collection_folder_name
    )
    return {
        "collection_folder_enabled": to_bool(payload.get("collection_folder_enabled"), True),
        "collection_folder_name": collection_folder_name,
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


def _save_section_scan_max_workers(payload: Dict[str, Any]) -> Dict[str, Any]:
    """VO-B-CONFIG : persiste scan_max_workers_mode + scan_max_workers_value.

    Si les cles sont absentes du payload, on ne les renvoie PAS (le dispatcher
    fera un dict.update qui ne touchera pas l'existant ; les defaults seront
    appliques au prochain `apply_settings_defaults`). Cela respecte la
    memoire user "BACKWARD COMPAT" : un client qui ne connait pas le setting
    ne doit pas le reinitialiser silencieusement.
    """
    out: Dict[str, Any] = {}
    if "scan_max_workers_mode" in payload:
        out["scan_max_workers_mode"] = _normalize_scan_max_workers_mode(payload.get("scan_max_workers_mode"))
    if "scan_max_workers_value" in payload:
        out["scan_max_workers_value"] = _normalize_scan_max_workers_value(payload.get("scan_max_workers_value"))
    return out


def _save_section_scan_flags(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "incremental_scan_enabled": to_bool(payload.get("incremental_scan_enabled"), False),
        "quarantine_unapproved": to_bool(payload.get("quarantine_unapproved"), False),
        "dry_run_apply": to_bool(payload.get("dry_run_apply"), True),
        "auto_approve_enabled": to_bool(payload.get("auto_approve_enabled"), False),
        "auto_approve_threshold": max(
            70, min(100, _coerce_int_with_default(payload.get("auto_approve_threshold", _MISSING), 85))
        ),
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


def _save_section_omdb(payload: Dict[str, Any]) -> Dict[str, Any]:
    # Fix audit 2026-05-24 : ce helper manquait du dispatcher save_settings_payload,
    # ce qui faisait que omdb_api_key etait silencieusement droppee a chaque save.
    # Toute la plomberie DPAPI etait correcte (read_settings/write_settings), juste
    # le dispatcher de save n'incluait pas la section.
    return {
        "omdb_enabled": to_bool(payload.get("omdb_enabled"), False),
        "omdb_api_key": str(payload.get("omdb_api_key") or "").strip(),
        "omdb_min_confidence_for_call": max(0, min(100, to_int(payload.get("omdb_min_confidence_for_call"), 90))),
    }


def _save_section_notifications(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "notifications_enabled": to_bool(payload.get("notifications_enabled"), False),
        # Cf issue #92 quick win #6 : defauts conservateurs (apply + errors only)
        "notifications_scan_triggered": to_bool(payload.get("notifications_scan_triggered"), False),
        "notifications_scan_done": to_bool(payload.get("notifications_scan_done"), False),
        "notifications_apply_done": to_bool(payload.get("notifications_apply_done"), True),
        "notifications_undo_done": to_bool(payload.get("notifications_undo_done"), False),
        "notifications_errors": to_bool(payload.get("notifications_errors"), True),
    }


def _save_section_rest_api(payload: Dict[str, Any]) -> Dict[str, Any]:
    # R5-CFG-1 : token validation deleguee a rest_server.MIN_LAN_TOKEN_LENGTH=32
    # qui retrograde transparent vers 127.0.0.1 si bind 0.0.0.0 demande avec
    # token court. Pas de double validation pour preserver les tests legacy
    # qui utilisent des tokens custom courts en mode local-only.
    return {
        "rest_api_enabled": to_bool(payload.get("rest_api_enabled"), False),
        "rest_api_port": max(1024, min(65535, to_int(payload.get("rest_api_port"), 8642))),
        "rest_api_token": str(payload.get("rest_api_token") or "").strip(),
        "rest_api_cors_origin": str(payload.get("rest_api_cors_origin") or "").strip(),
        "rest_api_https_enabled": to_bool(payload.get("rest_api_https_enabled"), False),
        "rest_api_cert_path": str(payload.get("rest_api_cert_path") or "").strip(),
        "rest_api_key_path": str(payload.get("rest_api_key_path") or "").strip(),
    }


def _save_section_watch(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "watch_enabled": to_bool(payload.get("watch_enabled"), False),
        "watch_interval_minutes": max(
            1, min(60, _coerce_int_with_default(payload.get("watch_interval_minutes", _MISSING), 5))
        ),
    }


def _save_section_plugins(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "plugins_enabled": to_bool(payload.get("plugins_enabled"), False),
        "plugins_timeout_s": max(5, min(120, _coerce_int_with_default(payload.get("plugins_timeout_s", _MISSING), 30))),
    }


def _appliquer_les_sections(
    to_save: Dict[str, Any],
    settings: Dict[str, Any],
    *,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
    default_probe_backend: str,
    debug_enabled: bool,
) -> None:
    """Recopie dans `to_save` tout ce que les sections savent lire.

    C'EST ICI QUE SE DECIDE CE QUI EST PERSISTE, ET NULLE PART AILLEURS.
    `to_save` part de l'existant ; une cle que AUCUNE section ci-dessous ne
    reclame n'est jamais recopiee — elle disparait en silence, et
    `save_settings` rend quand meme `ok: True`. C'est une liste blanche par
    omission, et son oubli est un defaut recurrent : le commentaire de la
    section `naming` en garde la trace (« 3 sections ajoutees pour persister
    16 champs UI qui etaient silencieusement droppes »), et
    `_save_section_quality_profiles` est le meme oubli, decouvert plus tard.

    AJOUTER UNE CLE DE REGLAGE, C'EST AJOUTER SA SECTION ICI.
    """
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
    # VO-B-CONFIG : scan_max_workers mode + value (tri-etat auto/manuel)
    to_save.update(_save_section_scan_max_workers(settings))
    to_save.update(_save_section_scan_flags(settings))
    to_save.update(_save_section_jellyfin(settings))
    to_save.update(_save_section_plex(settings))
    to_save.update(_save_section_radarr(settings))
    to_save.update(_save_section_omdb(settings))
    # Fix audit 2026-05-24 (v1.5.0) : 3 sections ajoutees pour persister 16 champs UI
    # qui etaient silencieusement droppes (meme bug pattern que OMDb).
    to_save.update(_save_section_naming(settings))
    to_save.update(_save_section_sources(settings))
    to_save.update(_save_section_advanced(settings))
    to_save.update(_save_section_notifications(settings))
    to_save.update(_save_section_rest_api(settings))
    to_save.update(_save_section_watch(settings))
    to_save.update(_save_section_plugins(settings))
    to_save.update(_save_section_quality_profiles(settings))
    to_save.update(_save_section_email(settings))
    to_save.update(_save_section_subtitles(settings))
    to_save.update(_save_section_perceptual(settings))
    to_save.update(_save_section_appearance(settings, debug_enabled=debug_enabled))


def _save_section_quality_profiles(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Bibliotheque durable des profils qualite personnalises.

    POURQUOI CETTE SECTION EXISTE. `to_save` part de l'existant puis chaque
    `_save_section_*` reclame SES cles : c'est une liste blanche par omission.
    Une cle qu'aucune section ne reclame n'est jamais recopiee — elle disparait
    silencieusement, et `save_settings` rend quand meme `ok: True`.

    Ces deux cles-la n'etaient reclamees par personne. Mesure, sur un state_dir
    neuf, en relisant le settings.json ECRIT :

        custom_quality_profiles   -> ABSENTE du fichier
        active_quality_profile_id -> ABSENTE du fichier
        locale (temoin)           -> "en", ecrite

    Consequences en chaine, toutes silencieuses :

      - `quality.save_profile` rendait `{"ok": true, "profile_id": ...}` et ne
        persistait RIEN ;
      - `quality.set_active_profile` repondait ensuite « Profil inconnu » pour le
        profil qu'on venait de « sauvegarder » ;
      - `settings.reset_database` detruisait le profil actif — seule copie, elle
        vivait en base — sans rien restaurer ni avertir (mesure : poids video
        70 -> 60, le defaut).

    `profiles_support_crud.py` et `reset_support.py` lisent et ecrivent pourtant
    ces deux cles depuis toujours : c'est la section d'ecriture qui manquait, pas
    les lecteurs.

    Les entrees non-dict sont ecartees plutot que de faire echouer la
    sauvegarde ENTIERE des reglages : un profil malforme ne doit pas emporter
    avec lui les 118 autres cles.
    """
    # CLE ABSENTE = SILENCE, PAS EFFACEMENT. Une premiere version de cette
    # section ecrivait les deux cles inconditionnellement. Mesure, sur un
    # state_dir reel, apres avoir cree un profil :
    #
    #     save_settings({"theme": "luxe"})  ->  ok: True
    #     custom_quality_profiles           ->  []      <- EFFACEE
    #     active_quality_profile_id         ->  ""      <- EFFACE
    #
    # C'etait grave : l'ecran Parametres fige les reglages a son ouverture, puis
    # les re-POSTe EN BLOC a chaque champ modifie (sauvegarde differee). Un
    # profil cree depuis cet ecran disparaissait donc a la frappe suivante, sous
    # un « Sauvegarde a HH:MM:SS ». Et tout client REST qui poste une charge
    # utile partielle detruisait la bibliotheque.
    #
    # L'ironie est instructive : le MEME lot ajoutait `_chemin_demande`
    # (probe_support.py) pour corriger exactement cette forme de defaut sur les
    # chemins d'outils. Corriger un motif a un endroit ne le corrige pas
    # ailleurs — c'est l'idiome des sections voisines (`_save_section_naming`,
    # `_save_section_sources`, `_save_section_advanced`) qu'il fallait suivre.
    out: Dict[str, Any] = {}
    if "custom_quality_profiles" in payload:
        brut = payload.get("custom_quality_profiles")
        # Les entrees non-dict sont ecartees plutot que de faire echouer la
        # sauvegarde ENTIERE : un profil malforme ne doit pas emporter les
        # ~118 autres cles de reglages.
        out["custom_quality_profiles"] = (
            [copy.deepcopy(e) for e in brut if isinstance(e, dict)] if isinstance(brut, list) else []
        )
    if "active_quality_profile_id" in payload:
        out["active_quality_profile_id"] = str(payload.get("active_quality_profile_id") or "")
    return out


def _save_section_email(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "email_enabled": to_bool(payload.get("email_enabled"), False),
        "email_smtp_host": str(payload.get("email_smtp_host") or "").strip(),
        "email_smtp_port": max(1, min(65535, _coerce_int_with_default(payload.get("email_smtp_port", _MISSING), 587))),
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
        # Fix audit 2026-05-25 (v1.5.4) Vague I : BUG 1 — declenche le calcul
        # auto des scores qualite apres scan (default True).
        "auto_recompute_quality_on_scan": to_bool(payload.get("auto_recompute_quality_on_scan"), True),
    }


def _save_section_perceptual(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "perceptual_enabled": to_bool(payload.get("perceptual_enabled"), False),
        "perceptual_auto_on_scan": to_bool(payload.get("perceptual_auto_on_scan"), False),
        "perceptual_auto_on_quality": to_bool(payload.get("perceptual_auto_on_quality"), True),
        "perceptual_timeout_per_film_s": max(
            30, min(600, _coerce_int_with_default(payload.get("perceptual_timeout_per_film_s", _MISSING), 120))
        ),
        "perceptual_frames_count": max(
            5, min(50, _coerce_int_with_default(payload.get("perceptual_frames_count", _MISSING), 10))
        ),
        "perceptual_skip_percent": max(
            0, min(20, _coerce_int_with_default(payload.get("perceptual_skip_percent", _MISSING), 5))
        ),
        "perceptual_dark_weight": max(1.0, min(3.0, to_float(payload.get("perceptual_dark_weight"), 1.5))),
        "perceptual_audio_deep": to_bool(payload.get("perceptual_audio_deep"), True),
        "perceptual_audio_segment_s": max(
            10, min(120, _coerce_int_with_default(payload.get("perceptual_audio_segment_s", _MISSING), 30))
        ),
        "perceptual_comparison_frames": max(
            10, min(100, _coerce_int_with_default(payload.get("perceptual_comparison_frames", _MISSING), 20))
        ),
        "perceptual_comparison_timeout_s": max(
            120, min(1800, _coerce_int_with_default(payload.get("perceptual_comparison_timeout_s", _MISSING), 600))
        ),
        "perceptual_parallelism_mode": _normalize_enum(
            payload.get("perceptual_parallelism_mode"), ("auto", "max", "safe", "serial"), "auto"
        ),
        # V5-02 Polish Total v7.7.0 (R5-STRESS-5) : settings batch parallelism.
        # `perceptual_workers` clampe a [0, 16] (0 = auto). `perceptual_parallelism_enabled`
        # est un bool (defaut True) qui agit comme kill-switch global du pool batch.
        "perceptual_parallelism_enabled": to_bool(payload.get("perceptual_parallelism_enabled"), True),
        # AUDIT 2026-06-11 (R4-P1, corrige R3/191b916) : la cle du champ UI est
        # desormais la CANONIQUE perceptual_workers (parametres.js, section
        # perceptual). Le fallback R3 sur l'alias perceptual_workers_count etait
        # MORT dans le flux UI reel : l'UI POST l'objet settings ENTIER (echo du
        # GET qui contient toujours perceptual_workers via _LITERAL_DEFAULTS),
        # donc la canonique perimee primait sur la saisie alias. L'alias reste
        # accepte en fallback pour les payloads partiels (REST legacy)
        # UNIQUEMENT quand la canonique est absente. Clamp [0..16] (0=auto).
        "perceptual_workers": max(
            0, min(16, _coerce_workers_int(payload.get("perceptual_workers", payload.get("perceptual_workers_count"))))
        ),
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


def _save_section_naming(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fix audit 2026-05-24 : section Nommage manquait totalement du dispatcher.
    6 champs (`naming_template`, `windows_safe`, `lowercase_extensions`, `separator`,
    `naming_movie_template`, `naming_tv_template`) etaient silencieusement droppes
    a chaque save. Meme pattern que bug OMDb. Il n'en reste que 3 : les 3 autres
    ont depuis ete retires (fantomes, ou violation de la regle inviolable n1).

    Note : `_apply_naming_preset` (deja appele dans le dispatcher) gere uniquement
    la mecanique du preset selecteur ; ce helper gere les champs templates + regles.
    """
    out: Dict[str, Any] = {}
    # R8-071 (F5) : "naming_template" (général) RETIRÉ — fantôme jamais lu par le pipeline
    # de nommage (canoniques = naming_movie_template / naming_tv_template).
    if "naming_movie_template" in payload:
        out["naming_movie_template"] = str(payload.get("naming_movie_template") or "").strip()
    if "naming_tv_template" in payload:
        out["naming_tv_template"] = str(payload.get("naming_tv_template") or "").strip()
    # R8-101 (filet F5) : "windows_safe" RETIRÉ — fantôme. windows_safe() est appliquée
    # inconditionnellement (aucun gate settings) -> échappement Windows toujours actif.
    # "lowercase_extensions" RETIRE : le seul effet du toggle etait de renommer
    # le FICHIER VIDEO (.MKV -> .mkv), interdit par la regle inviolable n1. Une
    # cle deja presente dans un settings.json existant n'est PAS effacee (le
    # merge read-modify-write de _save_settings_payload_locked part de
    # l'existant) : elle devient simplement inerte.
    if "separator" in payload:
        sep = str(payload.get("separator") or " ")
        out["separator"] = sep if sep in {".", " ", "_", "-"} else " "
    return out


def _save_section_sources(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fix audit 2026-05-24 : exclusions et extensions personnalisees etaient
    silencieusement droppees a chaque save.
    """
    out: Dict[str, Any] = {}
    if "excluded_patterns" in payload:
        raw = payload.get("excluded_patterns")
        if isinstance(raw, (list, tuple, str)):
            # Revue « perimetre destructif » 2026-08-03 : on persiste desormais
            # la forme CANONIQUE (minuscules, `/`, sans doublon) produite par
            # `core.normalize_excluded_patterns` — celle-la meme que
            # `build_cfg_from_settings` applique au scan. Le persiste et
            # l'effectif ne peuvent donc plus diverger, et les patterns non
            # discriminants (`*`, `**/*`, `*.*`...) sont refuses ICI aussi :
            # l'utilisateur voit immediatement, au retour du GET, que sa saisie
            # n'a pas ete retenue, au lieu de croire sa bibliotheque protegee.
            out["excluded_patterns"] = list(core.normalize_excluded_patterns(raw))
    if "file_extensions" in payload:
        raw = payload.get("file_extensions")
        # AUDIT 2026-06-11 (R4-P12) : split ';' ET ',' (le hint UI dit ';') —
        # ".mkv;.xyz" persistait ['mkv;.xyz'] (token poubelle). Et la cle
        # file_extensions n'avait AUCUN consommateur : le moteur lit video_exts
        # (build_cfg_from_settings). On ecrit donc AUSSI video_exts (format
        # '.ext') pour que le champ UI "Extensions video acceptees" ait un effet
        # sur le scan. Depuis 2026-08-03 cet effet est RESTRICTIF (plus d'union
        # avec VIDEO_EXTS_ALL quand la saisie existe) : cf. `resolve_video_exts`.
        exts: List[str] = []
        if isinstance(raw, list):
            exts = [str(e).strip().lower().lstrip(".") for e in raw if str(e).strip()]
        elif isinstance(raw, str):
            exts = [e.strip().lower().lstrip(".") for e in re.split(r"[;,]", raw) if e.strip()]
        if isinstance(raw, (list, str)):
            out["file_extensions"] = exts
            out["video_exts"] = [f".{e}" for e in exts]
    return out


def _save_section_advanced(payload: Dict[str, Any]) -> Dict[str, Any]:
    """Fix audit 2026-05-24 : retention, updater, parallelism advanced settings
    etaient silencieusement droppees.
    """
    out: Dict[str, Any] = {}
    if "history_retention_days" in payload:
        out["history_retention_days"] = max(0, min(3650, to_int(payload.get("history_retention_days"), 90)))
    # "retention_days" RETIRE (2026-08-03) — reglage FANTOME : persiste, jamais lu.
    # Le seul cron de retention (app.py:495 et 1004 -> retention_cleanup) lit
    # `history_retention_days` ci-dessus ; aucun code ne lisait `retention_days`.
    # Le champ UI promettait "conservation des analyses perceptuelles et scores
    # qualite" : cette purge n'existe pas, et la cabler par simple anciennete
    # detruirait le cache probe vivant d'une bibliotheque stable (re-probe complet
    # SMB/NAS). Le reglage est donc supprime plutot qu'invente.
    # VQ-2 QUARANTAINE-TTL : TTL filesystem du bucket _review (defaut 30j, 0 = OFF).
    # Bornage [0, 3650] aligne sur history_retention_days. Le cron tourne 24h via
    # `cinesort.app.quarantine_ttl.start_quarantine_ttl_cron`, demarre depuis app.py.
    if "quarantaine_ttl_days" in payload:
        out["quarantaine_ttl_days"] = max(0, min(3650, to_int(payload.get("quarantaine_ttl_days"), 30)))
    if "auto_check_updates" in payload:
        out["auto_check_updates"] = to_bool(payload.get("auto_check_updates"), True)
    if "update_check_enabled" in payload:
        out["update_check_enabled"] = to_bool(payload.get("update_check_enabled"), True)
    if "update_github_repo" in payload:
        repo = str(payload.get("update_github_repo") or "").strip()
        # SSRF defense (#240) : un `owner/repo` hors format part sinon tel quel
        # dans l'URL de l'API GitHub.
        #
        # Issue #556 : le motif etait recopie ici, avec pour seul garde-fou un
        # commentaire disant qu'il devait rester identique a celui de
        # `app/updater`. C'est desormais le validateur de l'updater lui-meme
        # qui tranche — un seul endroit ou changer la regle. `ui -> app` est
        # autorise par les contrats d'architecture (seul `app -> ui` est
        # interdit).
        #
        # La chaine VIDE reste acceptee : c'est la valeur par defaut du reglage
        # et le seul moyen, pour l'utilisateur, de revenir au depot integre.
        if not repo or is_valid_github_repo(repo):
            out["update_github_repo"] = repo
        else:
            # Trace du rejet. On ne remonte deliberement PAS d'erreur bloquante
            # jusqu'a l'UI : la vue Parametres enregistre en continu (debounce
            # 500 ms, parametres.js `_scheduleSave`), donc chaque frappe
            # intermediaire — "owner" avant la barre oblique — declencherait un
            # refus de TOUT l'enregistrement. Cf. la reserve de la PR.
            logger.debug("settings: update_github_repo ignore, format owner/repo attendu (%r)", repo)
    # R8-068 (F5) : "worker_count" RETIRÉ — toggle inerte, aucune opération ne le lit
    # (parallélisme réel piloté par perceptual_workers_count + le mode de scan).
    # AUDIT 2026-06-11 (R3) : perceptual_workers(_count) est gere par
    # _save_section_perceptual (clamp canonique [0..16], lit l'alias UI). On ne le
    # traite plus ici (l'ancien clamp [1..32] etait incoherent ET ecrase ensuite).
    if "desktop_notifications_enabled" in payload:
        out["desktop_notifications_enabled"] = to_bool(payload.get("desktop_notifications_enabled"), False)
    # R8-067 (F5) : "animations_enabled" RETIRÉ — fantôme cosmétique jamais consommé
    # (intensité pilotée par animation_level).
    if "cleanup_orphans" in payload:
        out["cleanup_orphans"] = to_bool(payload.get("cleanup_orphans"), False)
    if "cleanup_empty_folders" in payload:
        out["cleanup_empty_folders"] = to_bool(payload.get("cleanup_empty_folders"), False)
    # R8-065-lang (F5) : "subtitle_lang_priority" RETIRÉ — fantôme write-only jamais lu par
    # le pipeline sous-titres (la clé consommée est subtitle_expected_languages).
    return out


def _save_section_appearance(payload: Dict[str, Any], *, debug_enabled: bool) -> Dict[str, Any]:
    # V3-04 polish v7.7.0 : persiste log_level normalise (DEBUG/INFO/...).
    return {
        "theme": _normalize_enum(payload.get("theme"), ("cinema", "studio", "luxe", "neon"), "luxe"),
        "animation_level": _normalize_enum(
            payload.get("animation_level"), ("subtle", "moderate", "intense"), "moderate"
        ),
        "effect_speed": max(1, min(100, _coerce_appearance_int(payload, "effect_speed", 50))),
        "glow_intensity": max(0, min(100, _coerce_appearance_int(payload, "glow_intensity", 30))),
        "light_intensity": max(0, min(100, _coerce_appearance_int(payload, "light_intensity", 20))),
        # R8-072 (F5) : "effects_mode" RETIRÉ — fantôme cosmétique sans contrôle UI ; app.js
        # posait data-effects mais AUCUN CSS ne le consomme (0 effet visuel).
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
    # Une cle APPORTEE par ce payload vaut intention de la retenir.
    #
    # Le defaut se calculait sur le seul existant. Sur un profil NEUF il valait
    # donc False, et une cle fraichement saisie etait jetee des le premier
    # enregistrement (`to_save["tmdb_api_key"] = ""`) sans un mot : l'utilisateur
    # retrouvait un champ vide sans savoir pourquoi.
    #
    # La normalisation en LECTURE fait pourtant deja ce raisonnement
    # (`payload.setdefault("remember_key", bool(tmdb_api_key))`, plus haut dans
    # ce fichier). Les deux cotes divergeaient ; ils s'accordent maintenant.
    #
    # Ce n'est QUE le defaut : un `remember_key: false` explicite reste
    # souverain, et continue d'effacer la cle. Ne pas transformer ceci en
    # `or bool(cle_entrante)` applique APRES `to_bool` — ce serait ecraser le
    # choix de l'utilisateur, pas combler son silence.
    cle_entrante = str(settings.get("tmdb_api_key") or "").strip()
    remember_key = to_bool(settings.get("remember_key"), bool(existing_tmdb_key) or bool(cle_entrante))
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


def _build_save_result(
    state_dir: Path,
    write_meta: Dict[str, Any],
    *,
    rest_api_token_changed: bool = False,
    rest_api_token_new: str = "",
) -> Dict[str, Any]:
    """Construit le dict resultat retourne au frontend apres write_settings.

    B05-401-INCOHERENT (Fix A — couche persistence) : on remonte au caller
    deux meta-infos qui lui permettent de hot-swap le token REST en place
    sans relire `existing_settings` (la persistence connait deja l'ancien
    et le nouveau, autant les exposer). Cf cinesort_api._save_settings_impl
    qui consomme `rest_api_token_changed` pour appeler
    `RestApiServer.update_auth_token(new_token)` apres save.

    Backward compat absolue : ces deux cles sont OPTIONNELLES, le frontend
    et les tests existants qui ne les connaissent pas continuent de fonctionner
    inchanges (lecture via `.get()` cote callers).
    """
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
    # B05-401-INCOHERENT : signale au caller (cinesort_api._save_settings_impl)
    # qu'il doit hot-swap le token Bearer sur le handler REST en memoire. Cle
    # ajoutee inconditionnellement (False si pas de changement) pour rendre la
    # detection explicite cote caller (pas de KeyError ni de defaut implicite).
    result["rest_api_token_changed"] = bool(rest_api_token_changed)
    if rest_api_token_changed:
        # On expose la nouvelle valeur SEULEMENT en cas de changement, pour
        # eviter de fuir le token dans tous les logs/traces de save. Le caller
        # qui n'a pas besoin du changement ne voit jamais le token.
        result["rest_api_token_new"] = str(rest_api_token_new or "")
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
    # Fix lost-update : serialise read_settings/normalize/write_settings par
    # state_dir. Sans ce verrou, deux saves paralleles peuvent lire le meme
    # snapshot et le dernier write ecrase silencieusement le premier. Le lock
    # est resolu AVANT d'acquerir le verrou pour eviter de tenir le guard
    # global pendant les IO.
    _settings_write_lock = _get_settings_write_lock(state_dir)
    with _settings_write_lock:
        return _save_settings_payload_locked(
            settings,
            state_dir=state_dir,
            state_dir_present=state_dir_present,
            current_state_dir=current_state_dir,
            default_root=default_root,
            default_collection_folder_name=default_collection_folder_name,
            default_empty_folders_folder_name=default_empty_folders_folder_name,
            default_residual_cleanup_folder_name=default_residual_cleanup_folder_name,
            default_probe_backend=default_probe_backend,
            debug_enabled=debug_enabled,
        )


def _save_settings_payload_locked(
    settings: Dict[str, Any],
    *,
    state_dir: Path,
    state_dir_present: bool,
    current_state_dir: Path,
    default_root: str,
    default_collection_folder_name: str,
    default_empty_folders_folder_name: str,
    default_residual_cleanup_folder_name: str,
    default_probe_backend: str,
    debug_enabled: bool,
) -> Tuple[Path, Dict[str, Any]]:
    """Section critique de save_settings_payload, executee sous _settings_write_lock."""
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

    # Hotfix : on PART de l'existant (merge read-modify-write) puis on ecrase
    # avec les sections normalisees. Sinon toute cle non couverte par un
    # `_save_section_*` (preferences UI futures, settings annexes, blobs
    # `_orig_*` injectes par read_settings) etait silencieusement effacee a
    # chaque save (reconstruction from-scratch destructive).
    # Note : on retire les champs derives masque (-> read_settings les
    # reinjecte) et les protection/warning qui doivent etre re-derives par
    # write_settings.
    to_save: Dict[str, Any] = dict(existing_settings)
    for derived in (
        "tmdb_key_protection",
        "tmdb_key_warning",
        "jellyfin_key_protection",
        "jellyfin_key_warning",
        "plex_token_protection",
        "plex_token_warning",
        "radarr_key_protection",
        "radarr_key_warning",
        "email_smtp_password_protection",
        "email_smtp_password_warning",
        "omdb_key_protection",
        "omdb_key_warning",
    ):
        to_save.pop(derived, None)
    to_save["root"] = str(root_path)
    to_save["roots"] = [str(r) for r in roots_paths]
    to_save["state_dir"] = str(state_dir)
    _appliquer_les_sections(
        to_save,
        settings,
        default_collection_folder_name=default_collection_folder_name,
        default_empty_folders_folder_name=default_empty_folders_folder_name,
        default_residual_cleanup_folder_name=default_residual_cleanup_folder_name,
        default_probe_backend=default_probe_backend,
        debug_enabled=debug_enabled,
    )

    # Profils de renommage : normaliser preset + templates
    _apply_naming_preset(to_save, settings)
    _normalize_scopes(to_save)
    _apply_tmdb_key_persistence(to_save, settings, existing_settings)
    _apply_jellyfin_key_persistence(to_save, settings, existing_settings)

    # B05-401-INCOHERENT (Fix A — couche persistence) : on compare l'ancien et le
    # nouveau token REST APRES toute la normalisation (le helper _save_section_rest_api
    # strip le token, donc on compare des valeurs deja normalisees pour eviter les
    # faux positifs sur whitespace). La detection est exposee dans le result via
    # `_build_save_result` pour que cinesort_api._save_settings_impl puisse appeler
    # `RestApiServer.update_auth_token(new_token)` sans relire existing_settings.
    old_token = str(existing_settings.get("rest_api_token") or "").strip()
    new_token = str(to_save.get("rest_api_token") or "").strip()
    rest_api_token_changed = old_token != new_token

    write_meta = write_settings(state_dir, to_save)
    return state_dir, _build_save_result(
        state_dir,
        write_meta,
        rest_api_token_changed=rest_api_token_changed,
        rest_api_token_new=new_token if rest_api_token_changed else "",
    )


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
    if jellyfin_client_cls is None:
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
            # Fix audit 2026-05-26 (v1.5.6) Vague L : jellyfin-1 — JellyfinError
            # (levee par get_libraries/get_movies_count sur 401/403/5xx, cf
            # jellyfin_client.py:109-112) n'etait pas catchee, donc une auth
            # KO sur ces endpoints s'echappait jusqu'au caller. On l'ajoute au
            # tuple pour degrader gracieusement (libraries=[], movies_count=0)
            # et retourner ok=True avec les infos serveur deja recuperees.
            try:
                libraries = client.get_libraries(user_id)
                movies_count = client.get_movies_count(user_id)
            except (JellyfinError, KeyError, OSError, TypeError, ValueError) as exc:
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
    # Fix audit 2026-05-26 (v1.5.6) Vague L : jellyfin-1 — meme correction au
    # niveau du bloc except principal. Si client.validate_connection() leve
    # JellyfinError (cas typique : URL malformee qui passe la normalisation mais
    # echoue cote serveur, ou erreur reseau bas niveau remontee comme
    # JellyfinError), on retourne un err() proprement plutot que de laisser
    # l'exception remonter au caller (qui afficherait une stacktrace dans l'UI).
    except (JellyfinError, KeyError, OSError, TypeError, ValueError) as exc:
        return err(f"Jellyfin connection failed: {exc}", category="runtime", level="error")


# Audit ID-J-001 (V1-M10) : API publique pour gestion UI des backups settings.
def list_settings_backups(state_dir: Path) -> List[Dict[str, Any]]:
    """Liste les backups disponibles avec metadata, plus recents en premier."""
    target_path = settings_path(state_dir)
    pattern = f"{target_path.name}{SETTINGS_BACKUP_PREFIX}*"
    out: List[Dict[str, Any]] = []
    # Cle secondaire `p.name` : voir `_rotate_settings_backups` pour la
    # justification (collisions de mtimes a < 15 ms sur Windows).
    for p in sorted(target_path.parent.glob(pattern), key=lambda x: (x.stat().st_mtime, x.name), reverse=True):
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


# =============================================================================
# VO-A UI : Advanced PRAGMA settings (storage profile tri-etat + locking_mode)
# =============================================================================
#
# Phase VO-A (Vague O) expose un endpoint dedie aux PRAGMA SQLite avances qui
# influencent les perfs DB selon le type de stockage :
#   - "auto"      : detection automatique au boot (defaut, comportement v7.x)
#   - "local_ssd" : profil tunne pour SSD local (WAL agressif, cache eleve)
#   - "nas_smb"   : profil prudent pour stockage reseau (WAL conservateur,
#                   synchronous=FULL pour eviter corruption sur deconnexion SMB)
#
# Le toggle "locking_mode_exclusive" est destructif (aucun autre processus ne
# peut lire la DB en parallele) et doit donc passer par dangerConfirmModal
# cote UI avec countdown 3s (memoire user actions dangereuses).
#
# Les valeurs sont stockees dans settings.json sous :
#   - storage_profile_override : "auto" | "local_ssd" | "nas_smb"
#   - sqlite_locking_mode_exclusive : bool
#
# Le profil "actif" est calcule depuis l'override (si != auto) ou la detection.

# PRAGMA-04 fix : exposer les 4 profils backend (PROFILES dans
# infra/db/pragma_profile.py) au lieu de seulement 2. Sans ca, les utilisateurs
# sur HDD ou NAS lent ne peuvent pas choisir un profil dedie (override edit
# manuel settings.json est silencieusement remappe sur "auto").
_VALID_STORAGE_PROFILES: Tuple[str, ...] = (
    "auto",
    "local_ssd",
    "local_hdd",
    "nas_smb",
    "nas_smb_slow",
)
_DEFAULT_STORAGE_PROFILE: str = "auto"


def _detect_storage_profile(state_dir: Path) -> str:
    """Detecte le type de stockage du state_dir (heuristique simple).

    Retourne "local_ssd" ou "nas_smb". Sur Windows, on regarde le type de
    drive via GetDriveType. Fallback "local_ssd" si la detection echoue
    (pas grave : c'est juste pour pre-cocher le profil dans l'UI).
    """
    try:
        path_str = str(state_dir).replace("\\", "/")
        # Heuristique : UNC path ou lettre de drive distant
        if path_str.startswith("//") or path_str.startswith("\\\\"):
            return "nas_smb"
        # Windows : interroger GetDriveTypeW si disponible
        if os.name == "nt":
            try:
                import ctypes  # noqa: PLC0415

                drive = str(state_dir.resolve()).split(":")[0] + ":\\"
                drive_type = ctypes.windll.kernel32.GetDriveTypeW(drive)
                # 4 = DRIVE_REMOTE (SMB/CIFS)
                if drive_type == 4:
                    return "nas_smb"
            except (OSError, AttributeError, ImportError):
                pass
    except (OSError, ValueError):
        pass
    return "local_ssd"


def _normalize_storage_profile(value: Any) -> str:
    """Clamp le profil de stockage a {"auto","local_ssd","nas_smb"}, defaut "auto"."""
    if value is None or isinstance(value, bool):
        return _DEFAULT_STORAGE_PROFILE
    try:
        normalized = str(value).strip().lower()
    except (TypeError, ValueError):
        return _DEFAULT_STORAGE_PROFILE
    if normalized in _VALID_STORAGE_PROFILES:
        return normalized
    return _DEFAULT_STORAGE_PROFILE


# =============================================================================
# VO-B Config : scan_max_workers (tri-etat auto / manuel N)
# =============================================================================
#
# Phase VO-B-CONFIG : expose un setting `scan_max_workers` qui pilote la
# parallelisation Phase 1 de `_filter_dossiers_phase`. Synergie avec VO-A :
# en mode "auto", la detection storage (local_ssd / nas_smb) determine le
# nombre de workers ; en mode manuel, l'utilisateur force une valeur N >= 1.
#
# Stockage settings.json :
#   - scan_max_workers_mode : "auto" | "manual"  (default "auto")
#   - scan_max_workers_value : int [1..64]       (default 1, utilise si mode=manual)
#
# Backward compat stricte (memoire user) : si la cle est absente OU mode="manual"
# avec value=1, le comportement reste strictement sequentiel (cf.
# `resolve_scan_max_workers` dans cinesort/app/_local_candidate.py qui plafonne
# a 32 et retombe sur 1 si invalide).
#
# La memoire user impose une garantie supplementaire ici : la facade doit pouvoir
# retourner la VALEUR EFFECTIVE (resolve_effective_scan_max_workers) pour que
# `build_cfg_from_settings` injecte un entier coherent dans `Config.scan_max_workers`.

_SCAN_MAX_WORKERS_MIN: int = 1
_SCAN_MAX_WORKERS_MAX: int = 64
_VALID_SCAN_MAX_WORKERS_MODES: Tuple[str, ...] = ("auto", "manual")
_DEFAULT_SCAN_MAX_WORKERS_MODE: str = "auto"
_DEFAULT_SCAN_MAX_WORKERS_VALUE: int = 1


def _normalize_scan_max_workers_mode(value: Any) -> str:
    """Clamp `scan_max_workers_mode` a {"auto","manual"}, defaut "auto"."""
    if value is None or isinstance(value, bool):
        return _DEFAULT_SCAN_MAX_WORKERS_MODE
    try:
        normalized = str(value).strip().lower()
    except (TypeError, ValueError):
        return _DEFAULT_SCAN_MAX_WORKERS_MODE
    if normalized in _VALID_SCAN_MAX_WORKERS_MODES:
        return normalized
    return _DEFAULT_SCAN_MAX_WORKERS_MODE


def _normalize_scan_max_workers_value(value: Any) -> int:
    """Clamp `scan_max_workers_value` a [1..64], defaut 1 si invalide."""
    if value is None or isinstance(value, bool):
        return _DEFAULT_SCAN_MAX_WORKERS_VALUE
    try:
        n = int(value)
    except (TypeError, ValueError):
        return _DEFAULT_SCAN_MAX_WORKERS_VALUE
    if n < _SCAN_MAX_WORKERS_MIN:
        return _SCAN_MAX_WORKERS_MIN
    if n > _SCAN_MAX_WORKERS_MAX:
        return _SCAN_MAX_WORKERS_MAX
    return n


def _auto_scan_max_workers_for_storage(storage_type: str) -> int:
    """VO-B/VO-A synergie : choix workers selon le type de stockage detecte.

    - local_ssd : 8 workers (I/O scandir/stat parallelisable sans saturer SSD).
    - nas_smb   : 4 workers (latence reseau eleve, gain limite >4, on prefere
                  prudence pour eviter de saturer le partage SMB).
    - autre     : 1 worker (fallback prudent, comportement sequentiel).
    """
    s = str(storage_type or "").strip().lower()
    if s == "local_ssd":
        return 8
    if s == "nas_smb":
        return 4
    return 1


def resolve_effective_scan_max_workers(state_dir: Path) -> int:
    """Resout la valeur effective de scan_max_workers a injecter dans Config.

    - Si mode = "auto" : utilise `_detect_storage_profile(state_dir)` (VO-A
      synergie) puis mappe vers un nombre de workers via
      `_auto_scan_max_workers_for_storage`.
    - Si mode = "manual" : retourne `scan_max_workers_value` clampe [1..64].
    - Si settings absents / corrompus : retourne 1 (sequentiel strict).
    """
    try:
        data = read_settings(state_dir)
    except (OSError, ValueError, TypeError):
        return _DEFAULT_SCAN_MAX_WORKERS_VALUE
    mode = _normalize_scan_max_workers_mode(data.get("scan_max_workers_mode"))
    if mode == "manual":
        return _normalize_scan_max_workers_value(data.get("scan_max_workers_value"))
    # mode = "auto" : delegation VO-A detect_storage_type via _detect_storage_profile.
    detected = _detect_storage_profile(state_dir)
    return _auto_scan_max_workers_for_storage(detected)


def get_scan_max_workers_payload(state_dir: Path) -> Dict[str, Any]:
    """VO-B-CONFIG : retourne l'etat actuel du setting scan_max_workers.

    Returns:
        {
            "ok": True,
            "mode": "auto" | "manual",
            "value": int,                # valeur manuelle saisie (defaut 1)
            "effective": int,            # valeur effectivement appliquee (mode resolu)
            "storage_detected": str,     # auto-detection VO-A
            "auto_suggestion": int,      # workers proposes si mode=auto
            "min": 1,
            "max": 64,
        }
    """
    try:
        data = read_settings(state_dir)
    except (OSError, ValueError, TypeError):
        data = {}
    mode = _normalize_scan_max_workers_mode(data.get("scan_max_workers_mode"))
    value = _normalize_scan_max_workers_value(data.get("scan_max_workers_value"))
    detected = _detect_storage_profile(state_dir)
    auto_suggestion = _auto_scan_max_workers_for_storage(detected)
    effective = auto_suggestion if mode == "auto" else value
    return {
        "ok": True,
        "mode": mode,
        "value": value,
        "effective": effective,
        "storage_detected": detected,
        "auto_suggestion": auto_suggestion,
        "min": _SCAN_MAX_WORKERS_MIN,
        "max": _SCAN_MAX_WORKERS_MAX,
    }


def set_scan_max_workers_payload(
    state_dir: Path,
    mode: str,
    value: Any = None,
) -> Dict[str, Any]:
    """VO-B-CONFIG : persiste le setting scan_max_workers et retourne l'etat.

    Args:
        state_dir: dossier state.
        mode: "auto" | "manual". Invalide -> erreur.
        value: int [1..64], requis et utilise UNIQUEMENT si mode="manual".
            Pour mode="auto", peut etre None (ignore).

    Returns:
        Meme forme que `get_scan_max_workers_payload` + `write_result`.
        En cas d'erreur de validation : { "ok": False, "message": ... }.
    """
    raw_mode = str(mode or "").strip().lower()
    if raw_mode not in _VALID_SCAN_MAX_WORKERS_MODES:
        return err(
            f"Mode scan_max_workers invalide : {mode!r}. "
            f"Valeurs autorisees : {', '.join(_VALID_SCAN_MAX_WORKERS_MODES)}.",
            category="validation",
            level="info",
        )

    if raw_mode == "manual":
        # En manuel, on exige une valeur explicite int. On rejette bool, None,
        # strings non-numeriques pour eviter qu'un payload UI casse retombe
        # silencieusement sur 1 (comportement non-evident pour le user).
        if value is None or isinstance(value, bool):
            return err(
                "Mode manuel : la valeur scan_max_workers_value est requise (int 1..64).",
                category="validation",
                level="info",
            )
        try:
            n = int(value)
        except (TypeError, ValueError):
            return err(
                f"Mode manuel : valeur scan_max_workers_value invalide ({value!r}). "
                f"Attendu : entier dans [{_SCAN_MAX_WORKERS_MIN}..{_SCAN_MAX_WORKERS_MAX}].",
                category="validation",
                level="info",
            )
        if n < _SCAN_MAX_WORKERS_MIN or n > _SCAN_MAX_WORKERS_MAX:
            return err(
                f"Mode manuel : valeur scan_max_workers_value hors plage "
                f"({n}). Attendu : entier dans "
                f"[{_SCAN_MAX_WORKERS_MIN}..{_SCAN_MAX_WORKERS_MAX}].",
                category="validation",
                level="info",
            )
        normalized_value = n
    else:
        # mode = auto : valeur conservee si presente et valide, sinon defaut 1.
        normalized_value = _normalize_scan_max_workers_value(value)

    # Lecture / merge / ecriture (read_settings retourne les secrets dechiffres,
    # write_settings rechiffrera correctement les autres champs).
    data = read_settings(state_dir)
    data["scan_max_workers_mode"] = raw_mode
    data["scan_max_workers_value"] = normalized_value
    try:
        write_result = write_settings(state_dir, data)
    except (OSError, ValueError, TypeError) as exc:
        return err(
            f"Echec de la sauvegarde de scan_max_workers : {exc}",
            category="runtime",
            level="error",
        )

    detected = _detect_storage_profile(state_dir)
    auto_suggestion = _auto_scan_max_workers_for_storage(detected)
    effective = auto_suggestion if raw_mode == "auto" else normalized_value

    return {
        "ok": True,
        "mode": raw_mode,
        "value": normalized_value,
        "effective": effective,
        "storage_detected": detected,
        "auto_suggestion": auto_suggestion,
        "min": _SCAN_MAX_WORKERS_MIN,
        "max": _SCAN_MAX_WORKERS_MAX,
        "write_result": write_result,
    }


def get_advanced_pragma_settings_payload(state_dir: Path) -> Dict[str, Any]:
    """VO-A : retourne l'etat des PRAGMA SQLite avances.

    Returns:
        {
            "ok": True,
            "profile_active": "auto" | "local_ssd" | "nas_smb",  # profil effectif
            "profile_override": "auto" | "local_ssd" | "nas_smb",  # choix user
            "available_profiles": [{"v": ..., "l": ...}, ...],
            "storage_detected": "local_ssd" | "nas_smb",  # heuristique
            "locking_mode_exclusive": bool,  # toggle EXCLUSIVE
        }
    """
    data = read_settings(state_dir)
    override = _normalize_storage_profile(data.get("storage_profile_override"))
    detected = _detect_storage_profile(state_dir)
    profile_active = detected if override == "auto" else override
    locking_exclusive = to_bool(data.get("sqlite_locking_mode_exclusive"), False)
    return {
        "ok": True,
        "profile_active": profile_active,
        "profile_override": override,
        "available_profiles": [
            {"v": "auto", "l": "Auto (detection)"},
            {"v": "local_ssd", "l": "SSD local (perf max)"},
            {"v": "local_hdd", "l": "HDD local (mecanique)"},
            {"v": "nas_smb", "l": "NAS / SMB (securise)"},
            {"v": "nas_smb_slow", "l": "NAS lent (Wi-Fi / vieux SMB)"},
        ],
        "storage_detected": detected,
        "locking_mode_exclusive": locking_exclusive,
    }


def set_advanced_pragma_settings_payload(
    state_dir: Path,
    profile_name: str,
    locking_mode_exclusive: bool = False,
) -> Dict[str, Any]:
    """VO-A : applique les PRAGMA SQLite avances et persiste dans settings.json.

    Args:
        state_dir: dossier state
        profile_name: "auto" | "local_ssd" | "nas_smb"
        locking_mode_exclusive: True = activer locking_mode=EXCLUSIVE (dangereux,
            empeche toute lecture concurrente). Defaut False.

    Returns:
        { "ok": bool, "profile_active": str, "locking_mode_exclusive": bool,
          "message": str (si erreur) }
    """
    normalized_profile = _normalize_storage_profile(profile_name)
    if str(profile_name or "").strip().lower() not in _VALID_STORAGE_PROFILES:
        return err(
            f"Profil de stockage invalide : {profile_name!r}. "
            f"Valeurs autorisees : {', '.join(_VALID_STORAGE_PROFILES)}.",
            category="validation",
            level="info",
        )

    locking_bool = bool(locking_mode_exclusive)

    # Lire / merger / ecrire (write_settings recommence le pipeline DPAPI sur
    # les autres champs : on reinjecte tous les champs sensibles tels qu'ils
    # etaient pour ne rien casser. read_settings retourne deja les secrets
    # dechiffres, donc write_settings va les rechiffrer correctement).
    data = read_settings(state_dir)
    data["storage_profile_override"] = normalized_profile
    data["sqlite_locking_mode_exclusive"] = locking_bool
    try:
        write_result = write_settings(state_dir, data)
    except (OSError, ValueError, TypeError) as exc:
        return err(
            f"Echec de la sauvegarde des PRAGMA avances : {exc}",
            category="runtime",
            level="error",
        )

    detected = _detect_storage_profile(state_dir)
    profile_active = detected if normalized_profile == "auto" else normalized_profile

    return {
        "ok": True,
        "profile_active": profile_active,
        "profile_override": normalized_profile,
        "locking_mode_exclusive": locking_bool,
        "storage_detected": detected,
        "write_result": write_result,
    }

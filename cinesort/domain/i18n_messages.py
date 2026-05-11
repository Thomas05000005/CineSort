"""Infrastructure i18n backend (V6-01, Polish Total v7.7.0).

Module de lookup de messages traduits, lu depuis ``locales/<locale>.json`` au
chargement. Convention de cle : ``category.subcategory.detail`` (ex.
``settings.tmdb.api_key_label``). Interpolation : ``{{var}}`` est remplace par
``params['var']`` cote appel.

Compatibilite 100% : si une cle est manquante, ``t(key)`` retourne ``key`` (pas
de crash). Les agents V6-02/03/04/05/06 peuvent donc commencer a appeler
``t("key.inexistante")`` avant d'avoir extrait toutes les strings.

Zero dependance externe (stdlib JSON suffit).
"""

from __future__ import annotations

import json
import logging
import re
import sys
import threading
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional

logger = logging.getLogger(__name__)

# Locales supportees. Toute valeur hors de ce set est rejetee par `set_locale`.
SUPPORTED_LOCALES: FrozenSet[str] = frozenset({"fr", "en"})
DEFAULT_LOCALE: str = "fr"

# Pattern d'interpolation : `{{name}}` -> remplace par params['name']. Compatible
# avec le pattern frontend (web/dashboard/core/i18n.js). Le nom autorise l'usage
# des caracteres ASCII alphanumeriques + underscore + tiret pour matcher des cles
# usuelles (count, run_id, file-name).
_INTERPOLATION_RE = re.compile(r"\{\{\s*([A-Za-z0-9_\-]+)\s*\}\}")

# Etat module : protege par lock pour permettre des switch concurrents (rare mais
# possible si UI desktop + REST changent locale en parallele).
_LOCK = threading.RLock()
_MESSAGES: Dict[str, Dict[str, Any]] = {}
_CURRENT_LOCALE: str = DEFAULT_LOCALE
_LOADED: bool = False


def _resolve_locales_dir() -> Path:
    """Retourne le repertoire ``locales/`` cote dev ou dans le bundle PyInstaller.

    Strategy identique a ``rest_server._resolve_dashboard_root`` : on essaie
    d'abord ``sys._MEIPASS/locales`` (bundle), puis ``<projet>/locales`` (dev),
    enfin un fallback sur ``Path.cwd() / 'locales'``.
    """
    base_meipass = Path(getattr(sys, "_MEIPASS", ""))
    if base_meipass != Path("") and (base_meipass / "locales").is_dir():
        return (base_meipass / "locales").resolve()
    project_root = Path(__file__).resolve().parents[2]
    candidate = project_root / "locales"
    if candidate.is_dir():
        return candidate.resolve()
    return (Path.cwd() / "locales").resolve()


def _load_locale_file(locale: str) -> Dict[str, Any]:
    """Charge le JSON d'une locale donnee. Retourne `{}` si fichier absent/invalide.

    Pas de raise : on prefere une locale vide (qui retombe sur fallback `key`)
    plutot que crasher l'app au boot.
    """
    locales_dir = _resolve_locales_dir()
    path = locales_dir / f"{locale}.json"
    if not path.is_file():
        logger.warning("i18n: locale file missing: %s", path)
        return {}
    try:
        text = path.read_text(encoding="utf-8")
        data = json.loads(text)
        if not isinstance(data, dict):
            logger.warning("i18n: locale file %s is not a JSON object (got %s)", path, type(data).__name__)
            return {}
        return data
    except (OSError, json.JSONDecodeError) as exc:
        logger.warning("i18n: cannot load locale file %s: %s", path, exc)
        return {}


def _ensure_loaded() -> None:
    """Charge fr + en au premier appel. Idempotent."""
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        for loc in SUPPORTED_LOCALES:
            _MESSAGES[loc] = _load_locale_file(loc)
        _LOADED = True


def _lookup_dotted(messages: Dict[str, Any], key: str) -> Optional[str]:
    """Resout une cle ``a.b.c`` en parcourant les sous-dicts.

    Retourne None si une etape est absente OU si la valeur finale n'est pas une
    chaine. Le module i18n ne sert que des messages texte (pas de listes ni
    d'objets) — pour cela, l'appelant doit charger directement le JSON.
    """
    node: Any = messages
    for part in key.split("."):
        if not isinstance(node, dict):
            return None
        node = node.get(part)
        if node is None:
            return None
    if isinstance(node, str):
        return node
    return None


def _interpolate(template: str, params: Dict[str, Any]) -> str:
    """Remplace ``{{var}}`` dans ``template`` par ``str(params['var'])``.

    Variables manquantes : laissees telles quelles (``{{var}}`` dans la sortie),
    pour que l'oubli soit visible plutot que silencieux.
    """
    if not params:
        return template

    def _sub(match: "re.Match[str]") -> str:
        name = match.group(1)
        if name in params:
            return str(params[name])
        return match.group(0)

    return _INTERPOLATION_RE.sub(_sub, template)


def t(key: str, **params: Any) -> str:
    """Retourne le message traduit pour ``key`` dans la locale active.

    - ``key`` introuvable -> retourne ``key`` (fallback, jamais de crash).
    - ``params`` interpole les variables ``{{var}}`` du template.
    - Locale active determinee par `set_locale` ; defaut `fr`.

    Exemples:
        >>> t("common.cancel")  # -> "Annuler"
        >>> t("settings.saved_at", time="12:34")  # -> "Sauvegarde a 12:34"
        >>> t("missing.key")  # -> "missing.key"
    """
    _ensure_loaded()
    if not isinstance(key, str) or not key:
        return ""
    with _LOCK:
        locale = _CURRENT_LOCALE
        # Lookup locale courante
        msgs = _MESSAGES.get(locale) or {}
        template = _lookup_dotted(msgs, key)
        # Fallback sur la locale par defaut si la cle existe en FR mais pas dans
        # la locale active. Permet de livrer EN incomplet sans casser l'UI.
        if template is None and locale != DEFAULT_LOCALE:
            default_msgs = _MESSAGES.get(DEFAULT_LOCALE) or {}
            template = _lookup_dotted(default_msgs, key)
        if template is None:
            return key
    return _interpolate(template, params)


def set_locale(locale: str) -> None:
    """Change la locale active. Rejette silencieusement les locales non supportees.

    Pour signaler une valeur invalide cote API, l'appelant doit valider AVANT
    d'appeler cette fonction (cf. ``cinesort_api.set_locale`` qui leve une
    erreur explicite). Cette fonction n'echoue pas pour rester robuste au boot
    (settings.json corrompu = on garde la locale par defaut).
    """
    global _CURRENT_LOCALE
    _ensure_loaded()
    normalized = str(locale or "").strip().lower()
    if normalized not in SUPPORTED_LOCALES:
        logger.warning("i18n: ignored invalid locale '%s', kept '%s'", locale, _CURRENT_LOCALE)
        return
    with _LOCK:
        if normalized != _CURRENT_LOCALE:
            logger.info("i18n: locale changed %s -> %s", _CURRENT_LOCALE, normalized)
        _CURRENT_LOCALE = normalized


def get_locale() -> str:
    """Retourne la locale active (defaut: fr)."""
    with _LOCK:
        return _CURRENT_LOCALE


def get_available_locales() -> List[str]:
    """Retourne la liste triee des locales disponibles."""
    return sorted(SUPPORTED_LOCALES)


def reload_messages() -> None:
    """Force le rechargement des fichiers JSON (utile pour les tests).

    Reinitialise aussi la locale active a DEFAULT_LOCALE pour un etat propre.
    """
    global _LOADED, _CURRENT_LOCALE
    with _LOCK:
        _MESSAGES.clear()
        _LOADED = False
        _CURRENT_LOCALE = DEFAULT_LOCALE
    _ensure_loaded()


__all__ = [
    "DEFAULT_LOCALE",
    "SUPPORTED_LOCALES",
    "t",
    "set_locale",
    "get_locale",
    "get_available_locales",
    "reload_messages",
]

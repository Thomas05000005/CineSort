"""Helpers de construction de reponses API + logging structure.

Cf issue #103 (audit-2026-05-13:logoff) : 250 sites retournaient
`{"ok": False, "message": ...}` sans logger. Diagnostic des bugs
utilisateur (\"le bouton XYZ marche pas\") impossible.

Strategie : helper `err()` qui :
1. Logge automatiquement avec un tag categorie pour filtering
2. Construit le dict de reponse standard
3. Permet d'ajouter des champs custom (run_id, row_id, ...)

Niveaux de log recommandes :
- debug   : validations d'input attendues frequemment (run_id vide, etc.)
- info    : pre-conditions metier echouees (feature desactivee, plan pas pret)
- warning : ressources introuvables, etat invalide (run inconnu)
- error   : echec d'operation systeme (DB locked, FS error)

Migration progressive : on n'oblige pas tous les call-sites a passer par
ce helper. Cf #103 phase 2+ pour le reste.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

# Niveaux supportes (mapping str -> int pour log.log()).
_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "error": logging.ERROR,
}

# Categories conventionnelles. Pas une enum stricte pour rester souple,
# mais ces valeurs sont privilegiees pour faciliter le grep/filter.
KNOWN_CATEGORIES = frozenset(
    {
        "validation",  # input vide/manquant/mauvais type
        "state",  # pre-condition metier echouee (feature off, plan not ready)
        "resource",  # ressource introuvable (file/run/row)
        "permission",  # operation refusee (local-only, lock detenu)
        "config",  # configuration invalide (key/url/path)
        "runtime",  # erreur d'execution (DB, FS, network)
    }
)


def err(
    message: str,
    *,
    category: str = "validation",
    level: str = "warning",
    key: str = "message",
    log_module: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Construit un return `{"ok": False}` et logge en meme temps.

    Args:
        message: Phrase FR montree a l'utilisateur.
        category: Tag pour filtering logs (validation, state, resource, ...).
        level: debug|info|warning|error.
        key: Cle du champ contenant le message (defaut: "message"). Quelques
            endpoints historiques (demo, reset, log_dir) renvoient `"error"`
            au lieu de `"message"` ; ce parametre evite de casser leur
            contrat JSON cote frontend.
        log_module: Nom du logger (defaut: "cinesort.ui.api"). Permet d'utiliser
            le logger du module appelant pour conserver le contexte module.
        **extra: kwargs supplementaires fusionnes dans la reponse
            (ex: run_id="...", row_id="..."). Pas loggues automatiquement
            pour eviter de fuiter des identifiants sensibles — le caller
            doit les ajouter explicitement au message si necessaire.

    Returns:
        {"ok": False, <key>: message, **extra}  (par defaut <key>="message")
    """
    logger = logging.getLogger(log_module or "cinesort.ui.api")
    log_level = _LEVELS.get(level.lower(), logging.WARNING)
    logger.log(log_level, "api err [%s]: %s", category, message)
    return {"ok": False, key: message, **extra}


def ok(**fields: Any) -> Dict[str, Any]:
    """Construit un return `{"ok": True, **fields}` (sucre syntaxique).

    Pas de log emis sur le happy path — les operations qui meritent un log
    info/debug le font deja explicitement.
    """
    return {"ok": True, **fields}


def safe_integration_error(
    exc: BaseException,
    *,
    category: str = "resource",
    log_module: Optional[str] = None,
    **extra: Any,
) -> Dict[str, Any]:
    """Retourne un message generique cote client + logge l'exception complete cote serveur.

    Sprint 2 audit P0 #4 : plusieurs sites (Jellyfin / Plex / Radarr / OMDb) renvoyaient
    `_err_response(str(exc))` au client, ce qui pouvait fuiter des chemins locaux,
    URLs internes, tokens partiellement encodes, ou stack traces vers le JS.

    Strategie : on logge l'exception complete avec `exc_info=True` (visible dans
    les logs serveur pour diagnostic), mais on ne renvoie au client qu'un message
    generique localise.

    Args:
        exc: Exception capturee.
        category: Tag pour filtering logs et reponse JSON.
        log_module: Nom du logger (defaut: "cinesort.ui.api").
        **extra: champs additionnels fusionnes dans la reponse (ex: run_id=...).

    Returns:
        Dict `{"ok": False, "message": <message localise>, **extra}`.
    """
    # Import local pour eviter une dependance circulaire au chargement
    # (_responses est importe tres tot, i18n_messages charge des fichiers JSON).
    from cinesort.domain.i18n_messages import t as _translate

    logger = logging.getLogger(log_module or "cinesort.ui.api")
    logger.warning(
        "integration_error [%s]: %s",
        category,
        exc.__class__.__name__,
        exc_info=exc,
    )
    safe_message = _translate("errors.integration_failed")
    return {"ok": False, "message": safe_message, **extra}

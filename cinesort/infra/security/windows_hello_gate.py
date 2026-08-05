"""Scaffold Windows Hello gate pour actions dangereuses (interface only).

STATUS : DESACTIVE PAR DEFAUT. Cette interface est un scaffold prepare
pour une future iteration (V2.4 / V2.5). Aucun appel UI ne doit en
dependre encore : tous les `require_user_presence` retournent
`Decision.NOT_REQUIRED` tant que le feature flag n'est pas active.

OBJECTIF
========
Gating biometrique (Windows Hello) des actions dangereuses CineSort :
- Suppression definitive de fichiers (> 50 elements).
- Reset complet de la base.
- Re-marquage massif.
- Export/import settings (futur).

Combine avec la regle UI existante "modale + delai 3s si > 50" :
- Modale de confirmation s'affiche TOUJOURS (regle inchangee).
- Windows Hello prompt s'ajoute APRES la confirmation, si feature flag
  ON ET si le compte utilisateur a Hello configure.
- Si Hello indisponible (PC sans capteur, compte local sans PIN
  Hello), on retombe sur la modale + delai 3s seuls (pas de blocage
  fonctionnel).

API
===
- `is_supported()` : True si l'OS expose WinRT UserConsentVerifier.
- `is_enabled()` : True si feature flag activee ET supported.
- `require_user_presence(reason)` : prompt Hello bloquant. Retourne
  Decision.{VERIFIED, DENIED, NOT_REQUIRED, UNAVAILABLE}.

L'implementation reelle utilisera vraisemblablement :
- `winrt-Windows.Security.Credentials.UI` (UserConsentVerifier),
  via `winsdk` pip package OU `winrt-runtime` natif.
- Repli ctypes sur `Windows.Security.Credentials.UI.dll` si pas de
  binding Python disponible.

REFERENCE
=========
https://learn.microsoft.com/en-us/uwp/api/windows.security.credentials.ui.userconsentverifier

BACKWARD COMPAT
===============
Tant que `is_enabled()` retourne False, `require_user_presence` retourne
`NOT_REQUIRED` : aucun changement de comportement pour les callers
existants. Ils peuvent deja consommer cette API en toute securite.
"""

from __future__ import annotations

import enum
import os
from dataclasses import dataclass
from typing import Final

# Feature flag : doit etre explicitement active pour utiliser Hello.
# Defaut "0" tant que l'implementation reelle n'est pas livree.
ENV_HELLO_ENABLED: Final[str] = "CINESORT_WINDOWS_HELLO"


class Decision(enum.Enum):
    """Resultat d'une verification de presence utilisateur.

    Attributes:
        VERIFIED: L'utilisateur a passe Windows Hello (biometrie / PIN).
        DENIED: L'utilisateur a annule ou Hello a refuse.
        NOT_REQUIRED: Feature flag OFF -> le caller doit poursuivre
            sans prompt supplementaire (comportement V2.3).
        UNAVAILABLE: Hello pas configure sur ce compte -> meme effet
            que NOT_REQUIRED cote caller (poursuivre avec modale +
            delai 3s seulement).
    """

    VERIFIED = "verified"
    DENIED = "denied"
    NOT_REQUIRED = "not_required"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class GateResult:
    """Resultat structure d'une verification.

    Attributes:
        decision: Voir `Decision`.
        message: Message optionnel pour log / UI (jamais affiche sans
            mediation, peut contenir un code d'erreur OS).
    """

    decision: Decision
    message: str = ""

    @property
    def allowed(self) -> bool:
        """True si le caller peut poursuivre l'action dangereuse."""
        return self.decision in (
            Decision.VERIFIED,
            Decision.NOT_REQUIRED,
            Decision.UNAVAILABLE,
        )


def is_supported() -> bool:
    """True si l'OS hote peut potentiellement utiliser Windows Hello.

    Verifie uniquement la plateforme (Windows). Ne tente pas de charger
    UserConsentVerifier ici (cout d'import WinRT non justifie tant que
    le feature flag est OFF).
    """
    return os.name == "nt"


def is_enabled() -> bool:
    """True si feature flag ON et plateforme compatible."""
    if not is_supported():
        return False
    return os.environ.get(ENV_HELLO_ENABLED, "0") == "1"


def require_user_presence(reason: str) -> GateResult:
    """Demande une verification Windows Hello bloquante.

    Args:
        reason: Texte affiche dans le prompt Hello (ex. "Confirmer la
            suppression de 142 fichiers"). Sera tronque par l'OS si
            trop long.

    Returns:
        GateResult : utiliser `.allowed` pour decider.

    NOTE : tant que `is_enabled()` retourne False, retourne
    NOT_REQUIRED sans effectuer aucun appel OS. Les callers peuvent
    deja integrer ce point d'entree des V2.3 sans risque.
    """
    if not is_enabled():
        return GateResult(decision=Decision.NOT_REQUIRED, message="Feature flag off")

    # ---- Scaffold seulement ----
    # Quand on activera Hello, le code reel ira ici :
    #
    # from winsdk.windows.security.credentials.ui import (
    #     UserConsentVerifier, UserConsentVerifierAvailability,
    #     UserConsentVerificationResult,
    # )
    # availability = await UserConsentVerifier.check_availability_async()
    # if availability != UserConsentVerifierAvailability.AVAILABLE:
    #     return GateResult(Decision.UNAVAILABLE, str(availability))
    # outcome = await UserConsentVerifier.request_verification_async(reason)
    # if outcome == UserConsentVerificationResult.VERIFIED:
    #     return GateResult(Decision.VERIFIED)
    # return GateResult(Decision.DENIED, str(outcome))
    #
    # Tant que pas implemente, on signale clairement UNAVAILABLE pour
    # forcer un fallback sur la modale + delai 3s. Le caller voit
    # `allowed=True` (UNAVAILABLE est tolerant) => pas de blocage.
    del reason  # placeholder
    return GateResult(
        decision=Decision.UNAVAILABLE,
        message="Windows Hello non implemente (scaffold V2.3).",
    )


__all__ = [
    "Decision",
    "ENV_HELLO_ENABLED",
    "GateResult",
    "is_enabled",
    "is_supported",
    "require_user_presence",
]

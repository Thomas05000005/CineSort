"""Hierarchie d'exceptions commune aux clients d'integration tiers.

Phase 1 (BUG-1) remediation v7.8.0 : avant ce module, chaque client
(JellyfinClient, PlexClient, RadarrClient) definissait son `XxxError(Exception)`
heritant directement d'`Exception`. Pour catcher "n'importe quel echec d'un
client tiers", le code etait force d'ecrire `except Exception` annote
`# intentional : XxxError herite de Exception` — anti-pattern qui masque
les vrais bugs (TypeError, ValueError du code metier).

Avec ce module :

    try:
        ...
    except IntegrationError as exc:
        ...  # capture Jellyfin/Plex/Radarr/Omdb/Opensubtitles

Les classes specifiques (`JellyfinError` etc.) sont conservees dans leur
client respectif pour l'usage cible (`except JellyfinError`).

Compatibilite : `IntegrationError` herite d'`Exception`, donc le code legacy
qui catche `Exception` continue de fonctionner identiquement.
"""

from __future__ import annotations


class IntegrationError(Exception):
    """Erreur generique d'un client d'integration tier (Jellyfin/Plex/Radarr/...).

    Toutes les exceptions specifiques aux clients (JellyfinError, PlexError,
    RadarrError, OmdbError, OpensubtitlesError) doivent heriter de cette
    classe pour permettre un catch uniforme :

        try:
            jellyfin_client.refresh_library(...)
            plex_client.refresh_library(...)
        except IntegrationError as exc:
            log("WARN", f"Refresh tier echoue: {exc}")
    """

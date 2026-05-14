"""IntegrationsFacade : bounded context Integrations externes (issue #84 PR 1 pilote).

Methodes prevues a terme (11) :
    - Jellyfin (3) : test_jellyfin_connection, get_jellyfin_libraries,
                     get_jellyfin_sync_report
    - Plex (3) : test_plex_connection, get_plex_libraries, get_plex_sync_report
    - Radarr (3) : test_radarr_connection, get_radarr_status, request_radarr_upgrade
    - TMDb (2) : test_tmdb_key, get_tmdb_posters

PR 1 (pilote) : test_jellyfin_connection.
"""

from __future__ import annotations

from typing import Any, Dict

from cinesort.ui.api.facades._base import _BaseFacade


class IntegrationsFacade(_BaseFacade):
    """Bounded context Integrations : Jellyfin, Plex, Radarr, TMDb."""

    def test_jellyfin_connection(
        self,
        url: str = "",
        api_key: str = "",
        timeout_s: float = 10.0,
    ) -> Dict[str, Any]:
        """Test la connexion Jellyfin et retourne infos serveur + user + bibliotheques.

        Delegation vers CineSortApi.test_jellyfin_connection (backward-compat).
        """
        return self._api.test_jellyfin_connection(url=url, api_key=api_key, timeout_s=timeout_s)

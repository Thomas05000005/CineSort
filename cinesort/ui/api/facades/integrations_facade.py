"""IntegrationsFacade : bounded context Integrations externes (issue #84 PR 5 — migration complete).

Cf docs/internal/REFACTOR_PLAN_84.md.

12 methodes du bounded context Integrations :
    - TMDb (2) : test_tmdb_key, get_tmdb_posters
    - Jellyfin (3) : test_jellyfin_connection, get_jellyfin_libraries,
                     get_jellyfin_sync_report
    - Plex (3) : test_plex_connection, get_plex_libraries, get_plex_sync_report
    - Radarr (3) : test_radarr_connection, get_radarr_status, request_radarr_upgrade
    - Email (1) : test_email_report

Strategie Strangler Fig + Adapter pattern :
- Les 11 methodes existent EN PARALLELE sur CineSortApi (preserve backward-compat)
- Cette facade delegue simplement vers self._api.X
- Les nouveaux call sites peuvent utiliser api.integrations.X(...)
- Les anciens call sites (api.X(...)) continuent de fonctionner
"""

from __future__ import annotations

from typing import Any, Dict, List

from cinesort.ui.api.facades._base import _BaseFacade


class IntegrationsFacade(_BaseFacade):
    """Bounded context Integrations : Jellyfin, Plex, Radarr, TMDb."""

    # ---------- TMDb (2) ----------

    def test_tmdb_key(self, api_key: str, state_dir: str, timeout_s: float = 10.0) -> Dict[str, Any]:
        """Test la cle TMDb et retourne les capacites.

        Cf CineSortApi.test_tmdb_key pour la doc complete.
        """
        return self._api._test_tmdb_key_impl(api_key, state_dir, timeout_s)

    def get_tmdb_posters(
        self, tmdb_ids: List[int], size: str = "w92", force_refresh: bool = False
    ) -> Dict[str, Any]:
        """Recupere les URL posters TMDb pour une liste d'IDs.

        E4 : force_refresh=True bypass le cache local (refresh jaquette).
        Cf CineSortApi.get_tmdb_posters pour la doc complete.
        """
        return self._api._get_tmdb_posters_impl(tmdb_ids, size, force_refresh=force_refresh)

    def enrich_tmdb_ids_by_title(self, run_id: str, row_ids: Any) -> Dict[str, Any]:
        """R5-H2 : resout + persiste le tmdb_id de films identifies sans tmdb_id
        (NFO/nom) par recherche titre+annee, pour recuperer leurs jaquettes.

        Returns: {ok, resolved, total, posters: {row_id: url}}.
        """
        return self._api._enrich_tmdb_ids_by_title_impl(run_id, row_ids)

    # ---------- Jellyfin (3) ----------

    def test_jellyfin_connection(
        self,
        url: str = "",
        api_key: str = "",
        timeout_s: float = 10.0,
    ) -> Dict[str, Any]:
        """Test la connexion au serveur Jellyfin.

        Cf CineSortApi.test_jellyfin_connection pour la doc complete.
        """
        return self._api._test_jellyfin_connection_impl(url=url, api_key=api_key, timeout_s=timeout_s)

    def get_jellyfin_libraries(self) -> Dict[str, Any]:
        """Retourne les bibliotheques Jellyfin configurees.

        Cf CineSortApi.get_jellyfin_libraries pour la doc complete.
        """
        return self._api._get_jellyfin_libraries_impl()

    def get_jellyfin_sync_report(self, run_id: str = "") -> Dict[str, Any]:
        """Rapport de sync Jellyfin pour un run (ou dernier run).

        Cf CineSortApi.get_jellyfin_sync_report pour la doc complete.
        """
        return self._api._get_jellyfin_sync_report_impl(run_id)

    def refresh_jellyfin_library_now(self) -> Dict[str, Any]:
        """Cf #92 quick win #1 : declenche un refresh Jellyfin a la demande.

        Cf CineSortApi._refresh_jellyfin_library_now_impl pour la doc complete.
        """
        return self._api._refresh_jellyfin_library_now_impl()

    # ---------- Plex (3) ----------

    def test_plex_connection(
        self,
        url: str = "",
        token: str = "",
        timeout_s: float = 10.0,
    ) -> Dict[str, Any]:
        """Test la connexion au serveur Plex.

        Cf CineSortApi.test_plex_connection pour la doc complete.
        """
        return self._api._test_plex_connection_impl(url=url, token=token, timeout_s=timeout_s)

    def get_plex_libraries(
        self,
        url: str = "",
        token: str = "",
        timeout_s: float = 10.0,
    ) -> Dict[str, Any]:
        """Retourne les bibliotheques Plex configurees.

        Cf CineSortApi.get_plex_libraries pour la doc complete.
        """
        return self._api._get_plex_libraries_impl(url=url, token=token, timeout_s=timeout_s)

    def get_plex_sync_report(self, run_id: str = "") -> Dict[str, Any]:
        """Rapport de sync Plex pour un run (ou dernier run).

        Cf CineSortApi.get_plex_sync_report pour la doc complete.
        """
        return self._api._get_plex_sync_report_impl(run_id)

    def refresh_plex_library_now(self) -> Dict[str, Any]:
        """Cf #92 quick win #1 : declenche un refresh Plex a la demande.

        Cf CineSortApi._refresh_plex_library_now_impl pour la doc complete.
        """
        return self._api._refresh_plex_library_now_impl()

    # ---------- Radarr (3) ----------

    def test_radarr_connection(
        self,
        url: str = "",
        api_key: str = "",
        timeout_s: float = 10.0,
    ) -> Dict[str, Any]:
        """Test la connexion au serveur Radarr.

        Cf CineSortApi.test_radarr_connection pour la doc complete.
        """
        return self._api._test_radarr_connection_impl(url=url, api_key=api_key, timeout_s=timeout_s)

    def get_radarr_status(self, run_id: str = "") -> Dict[str, Any]:
        """Statut Radarr pour un run (films trouves vs absents).

        Cf CineSortApi.get_radarr_status pour la doc complete.
        """
        return self._api._get_radarr_status_impl(run_id)

    def request_radarr_upgrade(self, radarr_movie_id: int) -> Dict[str, Any]:
        """Declenche un upgrade Radarr pour un film.

        Cf CineSortApi.request_radarr_upgrade pour la doc complete.
        """
        return self._api._request_radarr_upgrade_impl(radarr_movie_id)

    # ---------- OMDb (1) — Phase 6.2 cross-check IMDb ----------

    def test_omdb_connection(self, api_key: str = "", timeout_s: float = 10.0) -> Dict[str, Any]:
        """Teste la cle OMDb (cross-check IMDb pour identification).

        Cf CineSortApi._test_omdb_connection_impl pour la doc complete.
        """
        return self._api._test_omdb_connection_impl(api_key=api_key, timeout_s=timeout_s)

    # ---------- Email (1) — Rapports SMTP ----------

    def test_email_report(self) -> Dict[str, Any]:
        """Envoie un email test avec des donnees mock pour valider la config SMTP.

        Cf CineSortApi._test_email_report_impl pour la doc complete.
        """
        return self._api._test_email_report_impl()

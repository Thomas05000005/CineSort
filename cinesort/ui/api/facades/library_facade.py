"""LibraryFacade : bounded context Library & Films (issue #84 PR 6 — migration complete).

Cf docs/internal/REFACTOR_PLAN_84.md.

9 methodes du bounded context Library :
    - Library filtree + agregats (5) : get_library_filtered, get_smart_playlists,
                                       save_smart_playlist, delete_smart_playlist,
                                       get_scoring_rollup
    - Film standalone + history (3) : get_film_full, get_film_history,
                                      list_films_with_history
    - Export RGPD (1) : export_full_library

Strategie Strangler Fig + Adapter pattern :
- Les 9 methodes existent EN PARALLELE sur CineSortApi (preserve backward-compat)
- Cette facade delegue simplement vers self._api.X
- Les nouveaux call sites peuvent utiliser api.library.X(...)
- Les anciens call sites (api.X(...)) continuent de fonctionner

Note PR 6 : la signature de get_library_filtered a ete corrigee pour matcher
exactement la signature du CineSortApi (le pilote de PR 1 avait des defaults
divergents qui auraient introduit une regression silencieuse).
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from cinesort.ui.api.facades._base import _BaseFacade


class LibraryFacade(_BaseFacade):
    """Bounded context Library : films, validation, edition, history, exports."""

    # ---------- Library filtree + agregats (5) ----------

    def get_library_filtered(
        self,
        run_id: Optional[str] = None,
        filters: Optional[Dict[str, Any]] = None,
        sort: str = "title",
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 3 : library filtree, triee, paginee.

        Cf CineSortApi.get_library_filtered pour la doc complete.
        """
        return self._api._get_library_filtered_impl(
            run_id=run_id,
            filters=filters,
            sort=sort,
            page=page,
            page_size=page_size,
        )

    def get_smart_playlists(self) -> Dict[str, Any]:
        """v7.6.0 Vague 3 : liste des smart playlists (presets + custom).

        Cf CineSortApi.get_smart_playlists pour la doc complete.
        """
        return self._api._get_smart_playlists_impl()

    def save_smart_playlist(
        self,
        name: str,
        filters: Dict[str, Any],
        playlist_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 3 : cree ou met a jour une smart playlist custom.

        Cf CineSortApi.save_smart_playlist pour la doc complete.
        """
        return self._api._save_smart_playlist_impl(name, filters, playlist_id)

    def delete_smart_playlist(self, playlist_id: str) -> Dict[str, Any]:
        """v7.6.0 Vague 3 : supprime une smart playlist custom.

        Cf CineSortApi.delete_smart_playlist pour la doc complete.
        """
        return self._api._delete_smart_playlist_impl(playlist_id)

    def get_scoring_rollup(
        self,
        by: str = "franchise",
        limit: int = 20,
        run_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """v7.6.0 Vague 7 : scoring agrege par dimension (franchise / decade / codec / era_grain).

        Cf CineSortApi.get_scoring_rollup pour la doc complete.
        """
        return self._api._get_scoring_rollup_impl(by=by, limit=limit, run_id=run_id)

    # ---------- Film standalone + history (3) ----------

    def get_film_full(self, row_id: str, run_id: Optional[str] = None) -> Dict[str, Any]:
        """v7.6.0 Vague 4 : toutes les infos d'un film pour la page standalone.

        Cf CineSortApi.get_film_full pour la doc complete.
        """
        return self._api._get_film_full_impl(row_id, run_id)

    def get_film_history(self, film_id: str) -> Dict[str, Any]:
        """Timeline complete d'un film a travers tous les runs.

        Cf CineSortApi.get_film_history pour la doc complete.
        """
        return self._api._get_film_history_impl(film_id)

    def list_films_with_history(self, limit: int = 50) -> Dict[str, Any]:
        """Liste des films du dernier run avec resume d'historique.

        Cf CineSortApi.list_films_with_history pour la doc complete.
        """
        return self._api._list_films_with_history_impl(limit)

    # ---------- Export RGPD (1) ----------

    def export_full_library(self) -> Dict[str, Any]:
        """RGPD Art. 20 — export portable de toute la bibliotheque.

        Cf CineSortApi.export_full_library pour la doc complete.
        """
        return self._api._export_full_library_impl()

    # ---------- Dashboard podiums + timeline (2) ----------

    def get_library_podiums(self, run_id: Optional[str] = None, limit: int = 10) -> Dict[str, Any]:
        """Top N release groups + codecs + sources pour le run cible.

        Cf cinesort.ui.api.library_podiums_support.get_library_podiums.
        """
        from cinesort.ui.api import library_podiums_support

        return library_podiums_support.get_library_podiums(self._api, run_id=run_id, limit=limit)

    def get_library_timeline(self, months: int = 12, run_id: Optional[str] = None) -> Dict[str, Any]:
        """Films ajoutes par mois (timeline N mois) via Jellyfin DateCreated + fallback mtime.

        Cf cinesort.ui.api.library_timeline_support.get_library_timeline.
        """
        from cinesort.ui.api import library_timeline_support

        return library_timeline_support.get_library_timeline(self._api, months=months, run_id=run_id)

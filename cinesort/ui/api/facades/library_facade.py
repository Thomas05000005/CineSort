"""LibraryFacade : bounded context Library & Films (issue #84 PR 1 pilote).

Methodes prevues a terme (5) :
    get_library_filtered, get_film_full, get_film_history,
    list_films_with_history, export_full_library

PR 1 (pilote) : get_library_filtered.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from cinesort.ui.api.facades._base import _BaseFacade


class LibraryFacade(_BaseFacade):
    """Bounded context Library : films, validation, edition, history, exports."""

    def get_library_filtered(
        self,
        run_id: str = "latest",
        filters: Optional[Dict[str, Any]] = None,
        sort: Optional[Dict[str, Any]] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> Dict[str, Any]:
        """Retourne la bibliotheque triee, filtree, paginee (v7.6.0 Vague 3).

        Delegation vers CineSortApi.get_library_filtered (backward-compat).
        """
        return self._api.get_library_filtered(
            run_id=run_id,
            filters=filters,
            sort=sort,
            page=page,
            page_size=page_size,
        )

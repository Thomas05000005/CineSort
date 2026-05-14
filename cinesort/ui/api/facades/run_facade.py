"""RunFacade : bounded context Run Flow (issue #84 PR 1 pilote).

Methodes prevues a terme (7) :
    start_plan, get_status, get_plan, export_run_report,
    cancel_run, build_apply_preview, list_apply_history

Cette PR (pilote) implemente UNE methode : start_plan. Les 6 autres seront
ajoutees dans PR 2 (refactor: full RunFacade migration). Pendant ce temps,
toutes les anciennes methodes sur CineSortApi continuent de fonctionner.
"""

from __future__ import annotations

from typing import Any, Dict

from cinesort.ui.api.facades._base import _BaseFacade


class RunFacade(_BaseFacade):
    """Bounded context Run : cycle de vie des scans + plans + apply preview."""

    def start_plan(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Demarre un scan+plan en thread background.

        Delegation vers CineSortApi.start_plan (preserve backward-compat).
        Cf docs/internal/REFACTOR_PLAN_84.md PR 1.
        """
        return self._api.start_plan(settings)

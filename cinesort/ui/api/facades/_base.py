"""Base class pour les façades CineSortApi (issue #84 phase pilote).

Strategie Strangler Fig + Facade :
- 5 façades par bounded context (Run, Settings, Quality, Integrations, Library)
- Backward-compat 100% : les anciennes methodes directes de CineSortApi
  coexistent avec les facades pendant la migration
- Adapter pattern : chaque facade recoit l'instance CineSortApi en injection
  et delegue les appels aux *_support modules existants

Cf docs/internal/REFACTOR_PLAN_84.md pour le plan complet en 10 PRs.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from cinesort.ui.api.cinesort_api import CineSortApi


class _BaseFacade:
    """Composition wrapper qui delegue les appels au CineSortApi parent.

    Args:
        api: Instance CineSortApi parent. La facade delegue les helpers
            internes (_get_run, _is_valid_run_id, _state_dir, etc.) au
            via self._api.X. Pour les tests, peut etre une stub class.
    """

    def __init__(self, api: "CineSortApi") -> None:
        self._api = api

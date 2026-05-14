"""Facades pour decouper CineSortApi par bounded context (issue #84).

Cf docs/internal/REFACTOR_PLAN_84.md pour le plan complet.

Strategie : Strangler Fig + Facade pattern. Les facades sont ajoutees EN
PARALLELE des anciennes methodes directes (adapter pattern). Backward-compat
100% jusqu'a la PR 10 (cleanup final).

Usage :
    api = CineSortApi()
    api.run.start_plan(payload)         # nouvelle voie
    api.start_plan(payload)              # ancienne voie (preserve)
"""

from __future__ import annotations

from cinesort.ui.api.facades._base import _BaseFacade
from cinesort.ui.api.facades.integrations_facade import IntegrationsFacade
from cinesort.ui.api.facades.library_facade import LibraryFacade
from cinesort.ui.api.facades.quality_facade import QualityFacade
from cinesort.ui.api.facades.run_facade import RunFacade
from cinesort.ui.api.facades.settings_facade import SettingsFacade

__all__ = [
    "_BaseFacade",
    "IntegrationsFacade",
    "LibraryFacade",
    "QualityFacade",
    "RunFacade",
    "SettingsFacade",
]

"""SettingsFacade : bounded context Configuration (issue #84 PR 1 pilote).

Methodes prevues a terme (3+) :
    get_settings, save_settings, set_locale
    (possiblement aussi : reset_all_user_data, get_user_data_size, restart_api_server)

PR 1 (pilote) : get_settings.
"""

from __future__ import annotations

from typing import Any, Dict

from cinesort.ui.api.facades._base import _BaseFacade


class SettingsFacade(_BaseFacade):
    """Bounded context Settings : config user (profile, integrations, locale)."""

    def get_settings(self) -> Dict[str, Any]:
        """Charge la configuration utilisateur depuis settings.json.

        Delegation vers CineSortApi.get_settings (preserve backward-compat).
        """
        return self._api.get_settings()

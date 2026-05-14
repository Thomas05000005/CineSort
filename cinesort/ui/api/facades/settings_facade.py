"""SettingsFacade : bounded context Configuration (issue #84 PR 3 — migration complete).

Cf docs/internal/REFACTOR_PLAN_84.md.

6 methodes du bounded context Settings :
    - get_settings : charge la config user (settings.json)
    - save_settings : persiste settings + applique side effects
    - set_locale : change la locale active (fr|en)
    - restart_api_server : reload du serveur REST
    - reset_all_user_data : V3-09 reset complet + backup ZIP
    - get_user_data_size : taille actuelle du user-data (pour Danger Zone UI)

Strategie Strangler Fig + Adapter pattern :
- Les 6 methodes existent EN PARALLELE sur CineSortApi (preserve backward-compat)
- Cette facade delegue simplement vers self._api.X
- Les nouveaux call sites peuvent utiliser api.settings.X(...)
- Les anciens call sites (api.X(...)) continuent de fonctionner
"""

from __future__ import annotations

from typing import Any, Dict

from cinesort.ui.api.facades._base import _BaseFacade


class SettingsFacade(_BaseFacade):
    """Bounded context Settings : config user (profile, integrations, locale)."""

    def get_settings(self) -> Dict[str, Any]:
        """Charge la configuration utilisateur depuis settings.json.

        Cf CineSortApi.get_settings pour la doc complete.
        """
        return self._api.get_settings()

    def save_settings(self, settings: Dict[str, Any]) -> Dict[str, Any]:
        """Persiste les settings + applique side effects (state_dir, locale, etc).

        Cf CineSortApi.save_settings pour la doc complete.
        """
        return self._api.save_settings(settings)

    def set_locale(self, locale: str) -> Dict[str, Any]:
        """Change la locale active (fr|en) et active immediatement le backend i18n.

        Cf CineSortApi.set_locale pour la doc complete.
        """
        return self._api.set_locale(locale)

    def restart_api_server(self) -> Dict[str, Any]:
        """Arrete et relance le serveur REST avec les settings actuels.

        Cf CineSortApi.restart_api_server pour la doc complete.
        """
        return self._api.restart_api_server()

    def reset_all_user_data(self, confirmation: str = "") -> Dict[str, Any]:
        """V3-09 — Reset toutes les donnees user (avec backup ZIP automatique).

        Cf CineSortApi.reset_all_user_data pour la doc complete.
        """
        return self._api.reset_all_user_data(confirmation)

    def get_user_data_size(self) -> Dict[str, Any]:
        """V3-09 — Taille actuelle du user-data (pour affichage UI Danger Zone).

        Cf CineSortApi.get_user_data_size pour la doc complete.
        """
        return self._api.get_user_data_size()

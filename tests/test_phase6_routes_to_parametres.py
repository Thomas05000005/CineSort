"""Tests Phase 6 (spec 11 Paramètres §11) : redirection des liens externes vers
`/parametres#integrations-<service>` plutôt que la vue legacy `/settings`.

Contexte
--------
L'audit Phase 6 a identifié 4 fichiers du dashboard qui pointaient encore
vers `#/settings` (legacy) au lieu de la nouvelle vue refondue `/parametres`
avec deep-link sur la bonne catégorie / section :

- ``web/dashboard/views/radarr.js``       -> ``#/parametres#integrations-radarr``
- ``web/dashboard/views/plex.js``         -> ``#/parametres#integrations-plex``
- ``web/dashboard/views/jellyfin.js``     -> ``#/parametres#integrations-jellyfin``
- ``web/dashboard/views/demo-wizard.js``  -> ``#/parametres#sources`` (banniere demo)
- ``web/dashboard/views/qij.js``          -> ``#/parametres#integrations-<id>`` (bouton
  Paramètres dans la carte d'intégration QIJ)

Ces tests verrouillent la migration en :
1. Verifiant que les 4 fichiers ne contiennent plus aucun `#/settings`.
2. Verifiant que le bon deep-link `#/parametres#<categorie>...` est present.
3. Verifiant que ``parametres.js`` parse bien le fragment d'URL au boot et
   ecoute ``hashchange`` (deep-link dynamique).
"""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DASH = _ROOT / "web" / "dashboard"

_RADARR_JS = _DASH / "views" / "radarr.js"
_PLEX_JS = _DASH / "views" / "plex.js"
_JELLYFIN_JS = _DASH / "views" / "jellyfin.js"
_DEMO_WIZARD_JS = _DASH / "views" / "demo-wizard.js"
_PARAMETRES_JS = _DASH / "views" / "parametres.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


class NoLegacySettingsLinkTests(unittest.TestCase):
    """Aucun des 4 fichiers ne doit plus contenir de lien `#/settings`."""

    def test_radarr_view_has_no_settings_link(self) -> None:
        content = _read(_RADARR_JS)
        self.assertNotIn(
            "#/settings",
            content,
            "radarr.js ne doit plus pointer vers la vue legacy /settings",
        )

    def test_plex_view_has_no_settings_link(self) -> None:
        content = _read(_PLEX_JS)
        self.assertNotIn(
            "#/settings",
            content,
            "plex.js ne doit plus pointer vers la vue legacy /settings",
        )

    def test_jellyfin_view_has_no_settings_link(self) -> None:
        content = _read(_JELLYFIN_JS)
        self.assertNotIn(
            "#/settings",
            content,
            "jellyfin.js ne doit plus pointer vers la vue legacy /settings",
        )

    def test_demo_wizard_banner_has_no_settings_link(self) -> None:
        content = _read(_DEMO_WIZARD_JS)
        # On verifie uniquement la banniere (href HTML), pas le navigateTo("/settings")
        # qui reste tolere comme alias rétrocompat geré par le router.
        self.assertNotIn(
            'href="#/settings"',
            content,
            "demo-wizard.js ne doit plus inserer de lien HTML vers #/settings",
        )

    # R8-046 (F5) : test_qij_view_has_no_settings_link RETIRÉ — views/qij.js supprimé
    # (vue morte, split QIJ->qualite). qualite.js n'expose pas de lien intégrations ;
    # l'invariant deep-link /parametres#integrations reste couvert par radarr/plex/jellyfin.


class DeepLinkPresenceTests(unittest.TestCase):
    """Chaque fichier doit pointer vers la bonne catégorie / section."""

    def test_radarr_links_to_integrations_radarr(self) -> None:
        content = _read(_RADARR_JS)
        self.assertIn(
            "#/parametres#integrations-radarr",
            content,
            "radarr.js doit deep-linker vers la section Radarr des intégrations",
        )

    def test_plex_links_to_integrations_plex(self) -> None:
        content = _read(_PLEX_JS)
        self.assertIn(
            "#/parametres#integrations-plex",
            content,
            "plex.js doit deep-linker vers la section Plex des intégrations",
        )

    def test_jellyfin_links_to_integrations_jellyfin(self) -> None:
        content = _read(_JELLYFIN_JS)
        self.assertIn(
            "#/parametres#integrations-jellyfin",
            content,
            "jellyfin.js doit deep-linker vers la section Jellyfin des intégrations",
        )

    def test_demo_wizard_links_to_parametres(self) -> None:
        content = _read(_DEMO_WIZARD_JS)
        # La banniere demo invite a configurer les vrais dossiers : catégorie "sources".
        self.assertIn(
            "#/parametres#sources",
            content,
            "demo-wizard.js doit deep-linker la bannière vers /parametres#sources",
        )

    # R8-046 (F5) : test_qij_button_links_to_integrations_dynamic RETIRÉ — views/qij.js
    # supprimé (vue morte). Le deep-link dynamique /parametres#integrations-<id> reste
    # couvert par radarr/plex/jellyfin ci-dessus.


class ParametresFragmentSupportTests(unittest.TestCase):
    """parametres.js doit parser le fragment et reagir aux hashchange."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _read(_PARAMETRES_JS)

    def test_parses_hash_fragment_function_exists(self) -> None:
        self.assertIn(
            "_parseHashFragment",
            self.js,
            "parametres.js doit exposer un parser de fragment d'URL",
        )

    def test_applies_hash_fragment_at_boot(self) -> None:
        self.assertIn(
            "_applyHashFragment",
            self.js,
            "parametres.js doit appliquer le fragment d'URL au boot",
        )

    def test_listens_to_hashchange(self) -> None:
        self.assertIn(
            'addEventListener("hashchange"',
            self.js,
            "parametres.js doit ecouter hashchange pour deep-link dynamique",
        )

    def test_unmount_removes_hashchange_listener(self) -> None:
        self.assertIn(
            'removeEventListener("hashchange"',
            self.js,
            "unmountParametres doit retirer le listener hashchange (anti-leak)",
        )

    def test_scrolls_pending_section(self) -> None:
        self.assertIn(
            "_flushPendingScroll",
            self.js,
            "parametres.js doit scroller la section ciblée par le fragment",
        )

    def test_section_id_data_attribute_used_for_scroll(self) -> None:
        # Le scroll cible un selecteur data-section-id="<id>"
        self.assertIn('data-section-id="', self.js)


if __name__ == "__main__":
    unittest.main()

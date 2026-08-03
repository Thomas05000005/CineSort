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

_APP_JS = _DASH / "app.js"
_DEMO_WIZARD_JS = _DASH / "views" / "demo-wizard.js"
_PARAMETRES_JS = _DASH / "views" / "parametres.js"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


# Phase 5 (purge verif totale) : views/radarr|plex|jellyfin.js SUPPRIMES (vues
# mortes). La redirection /radarr|/plex|/jellyfin -> #/parametres#integrations-<x>
# vit desormais DANS le router (app.js). Les tests lisent app.js = le vrai contrat.


class DeepLinkRedirectTests(unittest.TestCase):
    """Les routes legacy integrations redirigent vers /parametres#integrations-<x>."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.app = _read(_APP_JS)

    def test_radarr_route_redirects_to_integrations_radarr(self) -> None:
        self.assertIn("#/parametres#integrations-radarr", self.app)
        self.assertNotIn('registerRoute("/radarr", { view: "view-settings"', self.app)

    def test_plex_route_redirects_to_integrations_plex(self) -> None:
        self.assertIn("#/parametres#integrations-plex", self.app)

    def test_jellyfin_route_redirects_to_integrations_jellyfin(self) -> None:
        self.assertIn("#/parametres#integrations-jellyfin", self.app)

    def test_demo_wizard_links_to_parametres(self) -> None:
        content = _read(_DEMO_WIZARD_JS)
        self.assertIn(
            "#/parametres#sources",
            content,
            "demo-wizard.js doit deep-linker la bannière vers /parametres#sources",
        )
        self.assertNotIn(
            'href="#/settings"',
            content,
            "demo-wizard.js ne doit plus inserer de lien HTML vers #/settings",
        )


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

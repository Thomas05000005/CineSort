"""Tests Phase 2-B : Routing FR + Sidebar refondue selon spec 04 Shell 3 zones.

Couvre :
- Nouvelles routes FR canoniques dans app.js (/accueil, /traitement, /bibliotheque,
  /qualite, /historique, /parametres, /aide)
- Anciennes routes conservees en alias rétrocompat
- Sidebar : ancienne entree "qij" remplacee par 2 entrees distinctes "quality"
  + "history" (spec 04 §2.4 : QIJ splitté)
- Separateur visuel entre les 5 vues principales et Paramètres/Aide
- Mapping inverse route URL -> id sidebar (highlight l'item actif)
- Traductions i18n : nouvelles cles sidebar.nav.quality et sidebar.nav.history
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_APP_JS = _ROOT / "web" / "dashboard" / "app.js"
_SIDEBAR_JS = _ROOT / "web" / "dashboard" / "components" / "sidebar-v5.js"
_ROUTER_JS = _ROOT / "web" / "dashboard" / "core" / "router.js"
_FR_JSON = _ROOT / "locales" / "fr.json"
_EN_JSON = _ROOT / "locales" / "en.json"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FrenchCanonicalRoutesTests(unittest.TestCase):
    """Les 7 routes FR canoniques doivent etre enregistrees dans app.js."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_accueil_registered(self) -> None:
        self.assertIn('registerRoute("/accueil"', self.js)

    def test_traitement_registered(self) -> None:
        self.assertIn('registerRoute("/traitement"', self.js)

    def test_bibliotheque_registered(self) -> None:
        self.assertIn('registerRoute("/bibliotheque"', self.js)

    def test_qualite_registered(self) -> None:
        self.assertIn('registerRoute("/qualite"', self.js)

    def test_historique_registered(self) -> None:
        self.assertIn('registerRoute("/historique"', self.js)

    def test_parametres_registered(self) -> None:
        self.assertIn('registerRoute("/parametres"', self.js)

    def test_aide_registered(self) -> None:
        self.assertIn('registerRoute("/aide"', self.js)


class LegacyAliasRoutesTests(unittest.TestCase):
    """Les anciennes routes doivent rester pour la rétrocompat (bookmarks)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_home_alias_kept(self) -> None:
        self.assertIn('registerRoute("/home"', self.js)

    def test_library_alias_kept(self) -> None:
        self.assertIn('registerRoute("/library"', self.js)

    def test_processing_alias_kept(self) -> None:
        self.assertIn('registerRoute("/processing"', self.js)

    def test_settings_alias_kept(self) -> None:
        self.assertIn('registerRoute("/settings"', self.js)

    def test_help_alias_kept(self) -> None:
        self.assertIn('registerRoute("/help"', self.js)

    def test_status_alias_kept(self) -> None:
        self.assertIn('registerRoute("/status"', self.js)


class SidebarItemsTests(unittest.TestCase):
    """Spec 04 §2.4 : QIJ splitté en Qualité + Historique (entrees distinctes)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _SIDEBAR_JS.read_text(encoding="utf-8")

    def test_quality_item_present(self) -> None:
        self.assertIn('id: "quality"', self.js)
        self.assertIn('labelKey: "sidebar.nav.quality"', self.js)

    def test_history_item_present(self) -> None:
        self.assertIn('id: "history"', self.js)
        self.assertIn('labelKey: "sidebar.nav.history"', self.js)

    def test_separator_between_principals_and_settings(self) -> None:
        # _separator doit etre present pour la spec 04 §2 layout.
        self.assertIn('id: "_separator"', self.js)

    def test_separator_renders_as_divider_html(self) -> None:
        self.assertIn('class="v5-sidebar-separator"', self.js)
        self.assertIn('role="separator"', self.js)

    def test_nav_order_follows_spec(self) -> None:
        # Spec 04 §2.1 : home -> processing -> library -> quality -> history ->
        # separator -> settings -> help.
        ordered_ids = ["home", "processing", "library", "quality", "history", "_separator", "settings", "help"]
        positions = []
        for item_id in ordered_ids:
            pos = self.js.find(f'id: "{item_id}"')
            self.assertNotEqual(pos, -1, f"item {item_id} manquant dans NAV_ITEMS")
            positions.append(pos)
        self.assertEqual(positions, sorted(positions), "ordre des items NAV_ITEMS doit suivre la spec 04")


class SidebarRouteAliasTests(unittest.TestCase):
    """Le mapping sidebar id -> URL doit pointer vers les nouvelles routes FR."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_home_maps_to_accueil(self) -> None:
        self.assertIn('home: "/accueil"', self.js)

    def test_processing_maps_to_traitement(self) -> None:
        self.assertIn('processing: "/traitement"', self.js)

    def test_library_maps_to_bibliotheque(self) -> None:
        self.assertIn('library: "/bibliotheque"', self.js)

    def test_quality_maps_to_qualite(self) -> None:
        self.assertIn('quality: "/qualite"', self.js)

    def test_history_maps_to_historique(self) -> None:
        self.assertIn('history: "/historique"', self.js)

    def test_settings_maps_to_parametres(self) -> None:
        self.assertIn('settings: "/parametres"', self.js)

    def test_help_maps_to_aide(self) -> None:
        self.assertIn('help: "/aide"', self.js)


class RouteToSidebarReverseMappingTests(unittest.TestCase):
    """_ROUTE_TO_SIDEBAR_ID doit couvrir les routes FR ET les anciennes."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _APP_JS.read_text(encoding="utf-8")

    def test_french_routes_mapped(self) -> None:
        for fr, sidebar_id in [
            ("accueil", "home"),
            ("traitement", "processing"),
            ("bibliotheque", "library"),
            ("qualite", "quality"),
            ("historique", "history"),
            ("parametres", "settings"),
            ("aide", "help"),
        ]:
            self.assertIn(f'{fr}: "{sidebar_id}"', self.js, f"mapping {fr} -> {sidebar_id} manquant")

    def test_legacy_routes_mapped(self) -> None:
        # Anciennes routes doivent aussi resoudre (pour highlight la sidebar).
        for legacy, sidebar_id in [
            ("home", "home"),
            ("status", "home"),
            ("processing", "processing"),
            ("library", "library"),
            ("quality", "quality"),
            ("settings", "settings"),
            ("help", "help"),
        ]:
            self.assertIn(f'{legacy}: "{sidebar_id}"', self.js, f"mapping legacy {legacy} -> {sidebar_id} manquant")


class RouterTitlesTests(unittest.TestCase):
    """Le router doit fournir des titres pour les nouvelles routes FR."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _ROUTER_JS.read_text(encoding="utf-8")

    def test_accueil_has_title(self) -> None:
        self.assertIn('"/accueil"', self.js)
        self.assertIn('"Accueil"', self.js)

    def test_traitement_has_title(self) -> None:
        self.assertIn('"/traitement"', self.js)
        self.assertIn('"Traitement"', self.js)

    def test_bibliotheque_has_title(self) -> None:
        self.assertIn('"/bibliotheque"', self.js)
        self.assertIn('"Bibliothèque"', self.js)

    def test_qualite_has_title(self) -> None:
        self.assertIn('"/qualite"', self.js)
        self.assertIn('"Qualité"', self.js)

    def test_historique_has_title(self) -> None:
        self.assertIn('"/historique"', self.js)
        self.assertIn('"Historique"', self.js)

    def test_parametres_has_title(self) -> None:
        self.assertIn('"/parametres"', self.js)
        self.assertIn('"Paramètres"', self.js)

    def test_aide_has_title(self) -> None:
        self.assertIn('"/aide"', self.js)
        self.assertIn('"Aide"', self.js)


class I18nTranslationsTests(unittest.TestCase):
    """Les cles i18n pour quality + history doivent etre presentes (FR + EN)."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.fr = json.loads(_FR_JSON.read_text(encoding="utf-8"))
        cls.en = json.loads(_EN_JSON.read_text(encoding="utf-8"))

    def test_fr_quality_label(self) -> None:
        # Spec drift typo : fr.json a corrige "Qualite" -> "Qualité" (orthographe FR correcte).
        self.assertEqual(self.fr["sidebar"]["nav"]["quality"], "Qualité")

    def test_fr_history_label(self) -> None:
        self.assertEqual(self.fr["sidebar"]["nav"]["history"], "Historique")

    def test_en_quality_label(self) -> None:
        self.assertEqual(self.en["sidebar"]["nav"]["quality"], "Quality")

    def test_en_history_label(self) -> None:
        self.assertEqual(self.en["sidebar"]["nav"]["history"], "History")


class SeparatorCssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_separator_class_defined(self) -> None:
        self.assertIn(".v5-sidebar-separator", self.css)

    def test_separator_uses_border_token(self) -> None:
        # Le separateur doit utiliser un token border pour s'adapter aux thèmes.
        start = self.css.find(".v5-sidebar-separator")
        end = self.css.find("}", start)
        block = self.css[start:end]
        self.assertIn("var(--border-1)", block)


if __name__ == "__main__":
    unittest.main()

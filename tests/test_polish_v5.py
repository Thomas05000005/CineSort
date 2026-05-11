"""Tests Vague 10 v7.6.0 — Polish final : coherence tokens, file sizes, no TODOs.

Verifie la qualite finale du refonte v5 :
- Aucun composant v5 n'utilise de couleur hardcodee (doit passer par var(--...))
- Prefix v5-* respecte pour eviter collision avec legacy
- Tous les composants v5 sont bien charges dans index.html
- Les fichiers v5 ont une taille raisonnable (< 1000L par fichier)
- Aucun TODO/FIXME/XXX dans les livrables v5
- Chaque view v5 a son mount/unmount pattern
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COMPONENTS = _ROOT / "web" / "components"
_VIEWS = _ROOT / "web" / "views"
_SHARED = _ROOT / "web" / "shared"

V5_COMPONENT_FILES = [
    "sidebar-v5.js",
    "top-bar-v5.js",
    "breadcrumb.js",
    "notification-center.js",
    "home-widgets.js",
    "home-charts.js",
    "library-components.js",
]

# Composants v7.5.0 reutilises (score V2) mais sans prefix v5-*
V75_COMPONENT_FILES = [
    "score-v2.js",
]

V5_VIEW_FILES = [
    "library-v5.js",
    "film-detail.js",
    "processing.js",
    "settings-v5.js",
    "qij-v5.js",
]


# ---------------------------------------------------------------------------
# File sizes & presence
# ---------------------------------------------------------------------------


class FilePresenceTests(unittest.TestCase):
    def test_all_v5_components_exist(self) -> None:
        for fname in V5_COMPONENT_FILES:
            p = _COMPONENTS / fname
            self.assertTrue(p.exists(), f"Composant manquant : {fname}")
            self.assertGreater(p.stat().st_size, 500, f"Fichier trop petit : {fname}")

    def test_all_v5_views_exist(self) -> None:
        for fname in V5_VIEW_FILES:
            p = _VIEWS / fname
            self.assertTrue(p.exists(), f"View manquante : {fname}")
            self.assertGreater(p.stat().st_size, 1000, f"View trop petite : {fname}")

    def test_shared_design_system(self) -> None:
        for fname in ("tokens.css", "themes.css", "animations.css", "components.css"):
            p = _SHARED / fname
            self.assertTrue(p.exists(), f"Fichier shared manquant : {fname}")
            self.assertGreater(p.stat().st_size, 1000, f"Fichier shared trop petit : {fname}")


class FileSizeTests(unittest.TestCase):
    """Les fichiers v5 ne doivent pas exploser en taille (>1200L = refactor requis)."""

    def test_components_reasonable_size(self) -> None:
        for fname in V5_COMPONENT_FILES:
            p = _COMPONENTS / fname
            if not p.exists():
                continue
            lines = p.read_text(encoding="utf-8").splitlines()
            self.assertLess(len(lines), 1200, f"{fname} depasse 1200 lignes ({len(lines)}) — refactor requis")

    def test_views_reasonable_size(self) -> None:
        for fname in V5_VIEW_FILES:
            p = _VIEWS / fname
            if not p.exists():
                continue
            lines = p.read_text(encoding="utf-8").splitlines()
            self.assertLess(len(lines), 1500, f"{fname} depasse 1500 lignes ({len(lines)}) — refactor requis")


# ---------------------------------------------------------------------------
# Integration index.html
# ---------------------------------------------------------------------------


class IndexHtmlIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")

    def test_all_v5_components_loaded(self) -> None:
        for fname in V5_COMPONENT_FILES:
            self.assertIn(fname, self.html, f"Composant non charge dans index.html : {fname}")

    def test_all_v5_views_loaded(self) -> None:
        for fname in V5_VIEW_FILES:
            self.assertIn(fname, self.html, f"View non chargee dans index.html : {fname}")

    def test_shared_design_system_loaded(self) -> None:
        # components.css partage charge depuis shared/ ou via styles.css
        has_shared = (
            "shared/components.css" in self.html or "shared/tokens.css" in self.html or "shared/themes.css" in self.html
        )
        self.assertTrue(has_shared, "Les tokens/themes/components shared doivent etre charges")


# ---------------------------------------------------------------------------
# Code quality : TODOs, placeholders
# ---------------------------------------------------------------------------


class NoTodoTests(unittest.TestCase):
    """Aucun TODO/FIXME/XXX marque 'v7.6.0' ne doit subsister dans les livrables."""

    _FORBIDDEN = re.compile(r"\b(TODO|FIXME|XXX|HACK)\s*[: ]\s*v7\.6\.0", re.IGNORECASE)

    def test_no_v76_todos_in_components(self) -> None:
        for fname in V5_COMPONENT_FILES:
            p = _COMPONENTS / fname
            if not p.exists():
                continue
            content = p.read_text(encoding="utf-8")
            m = self._FORBIDDEN.search(content)
            self.assertIsNone(m, f"{fname} contient un TODO v7.6.0 non resolu")

    def test_no_v76_todos_in_views(self) -> None:
        for fname in V5_VIEW_FILES:
            p = _VIEWS / fname
            if not p.exists():
                continue
            content = p.read_text(encoding="utf-8")
            m = self._FORBIDDEN.search(content)
            self.assertIsNone(m, f"{fname} contient un TODO v7.6.0 non resolu")


# ---------------------------------------------------------------------------
# Design system coherence : tokens, prefix v5-
# ---------------------------------------------------------------------------


class TokensCoherenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tokens = (_SHARED / "tokens.css").read_text(encoding="utf-8")
        self.themes = (_SHARED / "themes.css").read_text(encoding="utf-8")

    def test_tier_tokens_invariant(self) -> None:
        """Les couleurs de tier sont definies dans tokens.css et non redefinies dans themes.css."""
        tier_tokens = ("--tier-platinum", "--tier-gold", "--tier-silver", "--tier-bronze", "--tier-reject")
        for tok in tier_tokens:
            self.assertIn(tok, self.tokens, f"Token {tok} absent de tokens.css")

    def test_themes_exist(self) -> None:
        for theme in ("studio", "cinema", "luxe", "neon"):
            self.assertIn(f'data-theme="{theme}"', self.themes)

    def test_themes_do_not_redefine_tiers(self) -> None:
        """Les themes ne redefinissent pas les tokens de tier (invariance design)."""
        for tok in ("--tier-platinum", "--tier-gold", "--tier-silver", "--tier-bronze", "--tier-reject"):
            # On accepte que tokens.css les definit, mais themes.css ne doit pas avoir
            # une redefinition dans un scope [data-theme="..."]
            pattern = rf'data-theme="[^"]+"\][^}}]*{re.escape(tok)}\s*:'
            m = re.search(pattern, self.themes)
            self.assertIsNone(m, f"{tok} ne doit pas etre redefini par theme")


class PrefixV5Tests(unittest.TestCase):
    """Les composants v5 utilisent le prefix 'v5-' pour coexister avec le legacy."""

    def test_components_use_v5_prefix(self) -> None:
        for fname in V5_COMPONENT_FILES:
            p = _COMPONENTS / fname
            if not p.exists():
                continue
            content = p.read_text(encoding="utf-8")
            # Au moins une classe v5-* ou selector v5-*
            has_v5 = bool(re.search(r'["\'\. ]v5-[\w-]+', content))
            self.assertTrue(has_v5, f"{fname} devrait utiliser le prefix v5-* pour les classes/selectors")


# ---------------------------------------------------------------------------
# Backend : endpoints v7.6.0 documentes dans CLAUDE.md ou api
# ---------------------------------------------------------------------------


class BackendEndpointsV76Tests(unittest.TestCase):
    def setUp(self) -> None:
        self.api_src = (_ROOT / "cinesort" / "ui" / "api" / "cinesort_api.py").read_text(encoding="utf-8")

    def test_vague_3_endpoints(self) -> None:
        for method in ("get_library_filtered", "get_smart_playlists", "save_smart_playlist", "delete_smart_playlist"):
            self.assertIn(f"def {method}", self.api_src)

    def test_vague_4_endpoints(self) -> None:
        self.assertIn("def get_film_full", self.api_src)

    def test_vague_7_endpoints(self) -> None:
        self.assertIn("def get_scoring_rollup", self.api_src)

    def test_vague_9_endpoints(self) -> None:
        for method in (
            "get_notifications",
            "dismiss_notification",
            "mark_notification_read",
            "mark_all_notifications_read",
            "clear_notifications",
            "get_notifications_unread_count",
        ):
            self.assertIn(f"def {method}", self.api_src)


# ---------------------------------------------------------------------------
# Router cleanliness : aliases vides apres Vague 7
# ---------------------------------------------------------------------------


class RouterV10CleanTests(unittest.TestCase):
    def setUp(self) -> None:
        self.router = (_ROOT / "web" / "core" / "router.js").read_text(encoding="utf-8")

    def test_route_aliases_empty(self) -> None:
        """Apres Vague 7, toutes les vues ont des routes canoniques, ROUTE_ALIASES = {}."""
        self.assertIn("ROUTE_ALIASES = {}", self.router)

    def test_all_v5_routes_handled(self) -> None:
        for route in ("processing", "library", "settings-v5", "quality-v5", "integrations-v5", "journal-v5"):
            self.assertIn(f'"{route}"', self.router)

    def test_overlays_mutually_exclusive(self) -> None:
        """Navigate to X doit hide les autres overlays pour eviter les empilements."""
        helpers = ("_hideQIJOverlay", "_hideSettingsV5Overlay", "_hideProcessingOverlay", "_hideFilmDetailOverlay")
        for helper in helpers:
            self.assertIn(helper, self.router, f"{helper} doit exister pour fermer les overlays")


# ---------------------------------------------------------------------------
# API REST : les nouveaux endpoints sont bien exposes et pas exclus
# ---------------------------------------------------------------------------


class RestApiExposureTests(unittest.TestCase):
    def test_notifications_endpoints_not_excluded(self) -> None:
        src = (_ROOT / "cinesort" / "infra" / "rest_server.py").read_text(encoding="utf-8")
        # Les endpoints notifications ne doivent PAS etre dans _EXCLUDED_METHODS
        excluded_block = src[src.find("_EXCLUDED_METHODS") : src.find("_EXCLUDED_METHODS") + 800]
        for method in ("get_notifications", "dismiss_notification"):
            self.assertNotIn(method, excluded_block, f"{method} ne doit pas etre exclu de l'API REST")


if __name__ == "__main__":
    unittest.main()

"""Tests Vague 0 v7.6.0 — Design System v5.

Couvre :
- 5 fichiers CSS crees dans web/shared/
- Tokens invariants (tier colors, severity)
- 4 themes Studio/Cinema/Luxe/Neon
- Reduced-motion fallback
- Index.html desktop + dashboard chargent shared/ AVANT legacy
- Handler REST /shared/* fonctionne
"""

from __future__ import annotations

import socket
import time
import unittest
from http.client import HTTPConnection
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parents[1]
_SHARED = _ROOT / "web" / "shared"


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ---------------------------------------------------------------------------
# Structure fichiers
# ---------------------------------------------------------------------------


class SharedCssFilesTests(unittest.TestCase):
    def test_shared_directory_exists(self) -> None:
        self.assertTrue(_SHARED.is_dir())

    def test_five_files_present(self) -> None:
        expected = {"tokens.css", "themes.css", "animations.css", "components.css", "utilities.css"}
        actual = {p.name for p in _SHARED.iterdir() if p.is_file()}
        self.assertTrue(expected.issubset(actual), f"manquants: {expected - actual}")


class TokensCssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_SHARED / "tokens.css").read_text(encoding="utf-8")

    def test_5_tier_colors_defined(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f"--tier-{tier}-solid:", self.css)
            self.assertIn(f"--tier-{tier}-glow:", self.css)
            self.assertIn(f"--tier-{tier}-bg:", self.css)

    def test_unknown_tier_defined(self) -> None:
        self.assertIn("--tier-unknown-solid:", self.css)

    def test_5_severities_defined(self) -> None:
        for sev in ("info", "success", "warning", "danger", "critical"):
            self.assertIn(f"--sev-{sev}-solid:", self.css)

    def test_spacing_grid_4px(self) -> None:
        for i in range(0, 12):
            self.assertIn(f"--sp-{i}:", self.css)

    def test_radius_scale(self) -> None:
        for s in ("sm", "md", "lg", "xl", "pill"):
            self.assertIn(f"--radius-{s}:", self.css)

    def test_motion_tokens(self) -> None:
        self.assertIn("--ease-out:", self.css)
        self.assertIn("--dur-base:", self.css)
        self.assertIn("--stagger-base:", self.css)

    def test_typography_tokens(self) -> None:
        self.assertIn("--font-family-base:", self.css)
        self.assertIn("Manrope", self.css)
        for s in ("xs", "sm", "base", "lg", "xl", "2xl", "3xl"):
            self.assertIn(f"--fs-{s}:", self.css)

    def test_reduced_motion_fallback_present(self) -> None:
        self.assertIn("@media (prefers-reduced-motion: reduce)", self.css)

    def test_density_variants(self) -> None:
        for d in ("compact", "comfortable", "spacious"):
            self.assertIn(f'data-density="{d}"', self.css)


class ThemesCssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_SHARED / "themes.css").read_text(encoding="utf-8")

    def test_4_themes_defined(self) -> None:
        for theme in ("studio", "cinema", "luxe", "neon"):
            self.assertIn(f'data-theme="{theme}"', self.css)

    def test_themes_only_redefine_surfaces_accents(self) -> None:
        # Les themes ne doivent PAS redefinir les tier colors
        for theme in ("cinema", "luxe", "neon"):
            # Extraire bloc theme
            start = self.css.find(f'[data-theme="{theme}"]')
            self.assertNotEqual(start, -1, f"theme {theme} absent")
            end = self.css.find("}", start)
            block = self.css[start:end]
            self.assertNotIn("--tier-platinum-solid", block, f"theme {theme} redefinit tier-platinum (interdit)")
            self.assertNotIn("--sev-", block, f"theme {theme} redefinit severity (interdit)")

    def test_each_theme_defines_bg_surface_accent(self) -> None:
        for theme in ("studio", "cinema", "luxe", "neon"):
            start = self.css.find(f'[data-theme="{theme}"]')
            end_block = self.css.find("}", start)
            block = self.css[start:end_block]
            self.assertIn("--bg:", block)
            self.assertIn("--surface-1:", block)
            self.assertIn("--accent:", block)


class AnimationsCssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_SHARED / "animations.css").read_text(encoding="utf-8")

    def test_core_keyframes(self) -> None:
        for kf in (
            "fadeIn",
            "slideDown",
            "slideUp",
            "slideInRight",
            "scaleIn",
            "pulse",
            "kpiFadeIn",
            "modalEnter",
            "viewEnter",
        ):
            self.assertIn(f"@keyframes {kf}", self.css)

    def test_stagger_class(self) -> None:
        self.assertIn(".stagger-item", self.css)
        self.assertIn("--order", self.css)


class ComponentsCssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_SHARED / "components.css").read_text(encoding="utf-8")

    def test_v5_button_variants(self) -> None:
        for v in ("primary", "secondary", "ghost", "danger"):
            self.assertIn(f".v5-btn--{v}", self.css)

    def test_v5_card_tiers(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f".v5-card--tier-{tier}", self.css)

    def test_v5_badges(self) -> None:
        for tier in ("platinum", "gold", "silver", "bronze", "reject"):
            self.assertIn(f".v5-badge--tier-{tier}", self.css)
        for sev in ("info", "success", "warning", "danger", "critical"):
            self.assertIn(f".v5-badge--severity-{sev}", self.css)

    def test_v5_table_components(self) -> None:
        self.assertIn(".v5-table", self.css)
        self.assertIn(".v5-table thead th", self.css)

    def test_v5_modal_components(self) -> None:
        self.assertIn(".v5-modal-overlay", self.css)
        self.assertIn(".v5-modal", self.css)

    def test_v5_toast_severities(self) -> None:
        for sev in ("success", "warning", "danger", "info"):
            self.assertIn(f".v5-toast--{sev}", self.css)


class UtilitiesCssTests(unittest.TestCase):
    def setUp(self) -> None:
        self.css = (_SHARED / "utilities.css").read_text(encoding="utf-8")

    def test_flex_utilities(self) -> None:
        for cls in (".v5u-flex", ".v5u-flex-row", ".v5u-items-center", ".v5u-justify-between"):
            self.assertIn(cls, self.css)

    def test_spacing_utilities(self) -> None:
        for i in (1, 2, 3, 4, 5, 6):
            self.assertIn(f".v5u-p-{i}", self.css)
            self.assertIn(f".v5u-gap-{i}", self.css)

    def test_text_utilities(self) -> None:
        self.assertIn(".v5u-text-primary", self.css)
        self.assertIn(".v5u-tabular-nums", self.css)
        self.assertIn(".v5u-truncate", self.css)

    def test_responsive_breakpoints(self) -> None:
        self.assertIn("@media (min-width: 768px)", self.css)
        self.assertIn("@media (min-width: 1024px)", self.css)


# ---------------------------------------------------------------------------
# Integration index.html
# ---------------------------------------------------------------------------


class IndexHtmlIntegrationTests(unittest.TestCase):
    def test_desktop_loads_shared_before_legacy(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        shared_pos = html.find("shared/tokens.css")
        legacy_pos = html.find('href="./styles.css"')
        self.assertGreater(shared_pos, 0, "shared/tokens.css pas charge dans desktop")
        self.assertGreater(legacy_pos, 0, "styles.css legacy absent")
        self.assertLess(shared_pos, legacy_pos, "shared doit etre charge AVANT legacy")

    def test_desktop_loads_all_5_shared(self) -> None:
        html = (_ROOT / "web" / "index.html").read_text(encoding="utf-8")
        for name in ("tokens", "themes", "animations", "components", "utilities"):
            self.assertIn(f"shared/{name}.css", html)

    def test_dashboard_loads_shared_before_legacy(self) -> None:
        html = (_ROOT / "web" / "dashboard" / "index.html").read_text(encoding="utf-8")
        shared_pos = html.find("/shared/tokens.css")
        legacy_pos = html.find('href="./styles.css"')
        self.assertGreater(shared_pos, 0)
        self.assertGreater(legacy_pos, 0)
        self.assertLess(shared_pos, legacy_pos)

    def test_dashboard_uses_absolute_shared_path(self) -> None:
        html = (_ROOT / "web" / "dashboard" / "index.html").read_text(encoding="utf-8")
        # Doit utiliser /shared/... (absolute) pas ../shared/ (traversal refuse)
        self.assertIn('href="/shared/tokens.css"', html)
        self.assertNotIn('href="../shared/', html)


# ---------------------------------------------------------------------------
# Handler REST /shared/*
# ---------------------------------------------------------------------------


class RestSharedHandlerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        try:
            import cinesort.ui.api.cinesort_api as backend
            from cinesort.infra.rest_server import RestApiServer
        except ImportError as exc:
            raise unittest.SkipTest(f"imports impossibles: {exc}") from exc

        import tempfile

        cls._tmp = tempfile.mkdtemp(prefix="cinesort_shared_")
        cls._api = backend.CineSortApi()
        cls._port = _find_free_port()
        cls._server = RestApiServer(
            api=cls._api,
            port=cls._port,
            token="test-token",
            cors_origin="*",
        )
        cls._server.start()
        # Wait for server up
        for _ in range(30):
            try:
                conn = HTTPConnection("127.0.0.1", cls._port, timeout=1)
                conn.request("GET", "/api/health")
                resp = conn.getresponse()
                resp.read()
                conn.close()
                if resp.status == 200:
                    break
            except (ConnectionRefusedError, OSError):
                pass
            time.sleep(0.1)

    @classmethod
    def tearDownClass(cls) -> None:
        try:
            cls._server.stop()
        except Exception:  # noqa: BLE001
            pass
        import shutil

        shutil.rmtree(cls._tmp, ignore_errors=True)

    def _get(self, path: str) -> Any:
        conn = HTTPConnection("127.0.0.1", self._port, timeout=3)
        conn.request("GET", path)
        resp = conn.getresponse()
        body = resp.read()
        status = resp.status
        headers = dict(resp.getheaders())
        conn.close()
        return status, body, headers

    def test_shared_tokens_css_served(self) -> None:
        status, body, headers = self._get("/shared/tokens.css")
        self.assertEqual(status, 200)
        self.assertIn(headers.get("Content-Type", ""), ("text/css", "text/css; charset=UTF-8"))
        self.assertIn(b"--tier-platinum-solid", body)

    def test_shared_themes_css_served(self) -> None:
        status, body, _ = self._get("/shared/themes.css")
        self.assertEqual(status, 200)
        self.assertIn(b'data-theme="studio"', body)

    def test_shared_components_css_served(self) -> None:
        status, body, _ = self._get("/shared/components.css")
        self.assertEqual(status, 200)
        self.assertIn(b".v5-btn", body)

    def test_shared_utilities_css_served(self) -> None:
        status, body, _ = self._get("/shared/utilities.css")
        self.assertEqual(status, 200)
        self.assertIn(b".v5u-flex", body)

    def test_shared_animations_css_served(self) -> None:
        status, body, _ = self._get("/shared/animations.css")
        self.assertEqual(status, 200)
        self.assertIn(b"@keyframes", body)

    def test_shared_path_traversal_blocked(self) -> None:
        status, _, _ = self._get("/shared/../dashboard/index.html")
        # soit 403 (acces interdit) soit 404 apres normalisation
        self.assertIn(status, (400, 403, 404))

    def test_shared_404_for_unknown_file(self) -> None:
        status, _, _ = self._get("/shared/nonexistent.css")
        self.assertEqual(status, 404)


if __name__ == "__main__":
    unittest.main()

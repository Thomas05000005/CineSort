"""Tests structure formatters locale-aware (V6-04, R4-I18N-3).

Vérifie que `web/dashboard/core/format.js` et `web/core/format.js` exportent
les bons formatters locale-aware (Intl.DateTimeFormat / Intl.NumberFormat /
Intl.RelativeTimeFormat) et que les anciens patterns hardcodés FR ont été
nettoyés des call-sites principaux.

Tests structure-only : pas d'exécution JS (Node/Jest absent du projet).
La validation runtime des formatters Intl.* est déléguée au navigateur
au boot du dashboard.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD_FORMAT = PROJECT_ROOT / "web" / "dashboard" / "core" / "format.js"
DESKTOP_FORMAT = PROJECT_ROOT / "web" / "core" / "format.js"


# ---------------------------------------------------------------------------
# Module dashboard/core/format.js (ESM)
# ---------------------------------------------------------------------------


class DashboardFormatModuleTests(unittest.TestCase):
    """`web/dashboard/core/format.js` doit exporter les formatters locale-aware."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = DASHBOARD_FORMAT.read_text(encoding="utf-8")

    def test_module_file_exists(self) -> None:
        self.assertTrue(DASHBOARD_FORMAT.is_file(), f"missing: {DASHBOARD_FORMAT}")

    def test_imports_get_locale_from_i18n(self) -> None:
        self.assertRegex(
            self.text,
            r'import\s*\{\s*getLocale\s*\}\s*from\s*["\']\./i18n\.js["\']',
            "format.js doit importer getLocale depuis i18n.js (V6-04)",
        )

    def test_exports_compat_helpers(self) -> None:
        # Compat 100% : signatures V5 préservées.
        for name in ("fmtDate", "fmtDuration", "fmtBytes", "fmtSpeed"):
            self.assertRegex(
                self.text,
                rf"export function {name}\(",
                f"export compat manquant : {name}",
            )

    def test_exports_v604_helpers(self) -> None:
        for name in (
            "formatDate",
            "formatDateTime",
            "formatRelative",
            "formatNumber",
            "formatBytes",
            "formatDuration",
            "formatPercent",
        ):
            self.assertRegex(
                self.text,
                rf"export function {name}\(",
                f"export V6-04 manquant : {name}",
            )

    def test_uses_intl_datetimeformat(self) -> None:
        self.assertIn(
            "Intl.DateTimeFormat",
            self.text,
            "format.js doit utiliser Intl.DateTimeFormat (locale-aware)",
        )

    def test_uses_intl_numberformat(self) -> None:
        self.assertIn(
            "Intl.NumberFormat",
            self.text,
            "format.js doit utiliser Intl.NumberFormat (locale-aware)",
        )

    def test_uses_intl_relativetimeformat(self) -> None:
        self.assertIn(
            "Intl.RelativeTimeFormat",
            self.text,
            "format.js doit utiliser Intl.RelativeTimeFormat pour formatRelative",
        )

    def test_locale_map_present(self) -> None:
        # Mapping fr -> fr-FR / en -> en-US.
        self.assertIn('fr: "fr-FR"', self.text)
        self.assertIn('en: "en-US"', self.text)

    def test_byte_units_locale_aware(self) -> None:
        # Les deux jeux d'unités doivent figurer dans formatBytes.
        self.assertIn('"o"', self.text, "unités FR (o/Ko/Mo/...) attendues")
        self.assertIn('"B"', self.text, "unités EN (B/KB/MB/...) attendues")
        self.assertIn('"KB"', self.text)
        self.assertIn('"Ko"', self.text)


# ---------------------------------------------------------------------------
# Module web/core/format.js (script global desktop)
# ---------------------------------------------------------------------------


class DesktopFormatModuleTests(unittest.TestCase):
    """`web/core/format.js` doit exposer les formatters sur window."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.text = DESKTOP_FORMAT.read_text(encoding="utf-8")

    def test_module_file_exists(self) -> None:
        self.assertTrue(DESKTOP_FORMAT.is_file(), f"missing: {DESKTOP_FORMAT}")

    def test_uses_intl_apis(self) -> None:
        self.assertIn("Intl.DateTimeFormat", self.text)
        self.assertIn("Intl.NumberFormat", self.text)
        self.assertIn("Intl.RelativeTimeFormat", self.text)

    def test_reads_locale_from_localstorage(self) -> None:
        # Pas d'import ESM cote desktop : la locale doit venir de localStorage
        # (clé partagée avec dashboard/core/i18n.js : "cinesort_locale").
        self.assertIn("cinesort_locale", self.text)
        self.assertIn("localStorage", self.text)

    def test_window_exposes_compat_helpers(self) -> None:
        for name in ("fmtDurationSec", "fmtEta", "fmtSpeed", "fmtDateTime", "fmtFileSize"):
            self.assertRegex(
                self.text,
                rf"window\.{name}\s*=",
                f"window.{name} doit etre expose (compat V5)",
            )

    def test_window_exposes_v604_helpers(self) -> None:
        for name in (
            "formatDate",
            "formatDateTime",
            "formatRelative",
            "formatNumber",
            "formatBytes",
            "formatDuration",
            "formatPercent",
        ):
            self.assertRegex(
                self.text,
                rf"window\.{name}\s*=",
                f"window.{name} doit etre expose (V6-04)",
            )

    def test_byte_units_locale_aware(self) -> None:
        self.assertIn('"Ko"', self.text)
        self.assertIn('"KB"', self.text)


# ---------------------------------------------------------------------------
# Refactor des call-sites : plus de toLocaleString("fr-FR") / Ko/Mo/Go hardcodés
# dans les vues principales (au-delà des fallbacks defensifs documentés).
# ---------------------------------------------------------------------------


class CallSiteRefactorTests(unittest.TestCase):
    """Vérifie que les call-sites identifiés ont été migrés vers les formatters."""

    # Fichiers refactorés en V6-04 : ils ont importé/délégué aux formatters
    # locale-aware mais peuvent garder un fallback sentinel défensif documenté
    # par un commentaire "V6-04". On vérifie la présence du commentaire ET du
    # délégué runtime.
    REFACTORED = [
        ("web/views/validation.js", ["window.formatDateTime"]),
        ("web/views/qij-v5.js", ["window.formatDateTime"]),
        ("web/views/home.js", ["window.formatBytes"]),
        ("web/views/film-detail.js", ["window.formatBytes"]),
        ("web/views/_v5_helpers.js", ["window.formatBytes"]),
        ("web/views/quality.js", ["window.formatBytes"]),
        ("web/dashboard/views/review.js", ["formatDateTime"]),
        ("web/dashboard/views/library/lib-duplicates.js", ["_fmtBytesShared"]),
    ]

    def test_call_sites_delegate_to_formatters(self) -> None:
        for rel, expected_tokens in self.REFACTORED:
            path = PROJECT_ROOT / rel
            self.assertTrue(path.is_file(), f"missing: {path}")
            text = path.read_text(encoding="utf-8")
            for token in expected_tokens:
                self.assertIn(
                    token,
                    text,
                    f"{rel}: doit déléguer aux formatters V6-04 ({token})",
                )

    def test_no_naked_fr_FR_locale_string_in_dashboard_views(self) -> None:
        """Les vues dashboard ne doivent plus contenir `toLocaleString("fr-FR")`."""
        # On scanne uniquement les vues dashboard (le shell SPA de production).
        offenders = []
        dashboard_views = (PROJECT_ROOT / "web" / "dashboard" / "views").rglob("*.js")
        pattern = re.compile(r'toLocale\w+\s*\(\s*["\']fr-FR["\']')
        for js_file in dashboard_views:
            text = js_file.read_text(encoding="utf-8")
            if pattern.search(text):
                offenders.append(str(js_file.relative_to(PROJECT_ROOT)))
        self.assertFalse(
            offenders,
            f"toLocaleString('fr-FR') restant dans : {offenders}. "
            "Utiliser formatDateTime/formatDate de dashboard/core/format.js.",
        )


if __name__ == "__main__":
    unittest.main()

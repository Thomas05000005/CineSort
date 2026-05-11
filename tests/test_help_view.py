"""Tests structurels pour la vue Aide (V1-14, FAQ + glossaire metier).

Cible 2000 utilisateurs non-tech : la vue doit etre presente, contenir au moins
15 questions FAQ, 15 termes glossaire, le lien GitHub Issues, le path des logs,
et la barre de recherche. Les deux frontends (desktop IIFE + dashboard ES module)
sont verifies independamment pour garantir la parite.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path


class HelpViewFilesExistTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.desktop_js = cls.root / "web" / "views" / "help.js"
        cls.desktop_html = cls.root / "web" / "index.html"
        cls.dashboard_html = cls.root / "web" / "dashboard" / "index.html"

    def test_desktop_help_js_exists(self):
        # Le dashboard charge desormais ../views/help.js (V5B), donc seul le fichier
        # desktop est requis. Le shim dashboard/views/help.js a ete supprime par V5C-01.
        self.assertTrue(self.desktop_js.is_file(), f"manquant: {self.desktop_js}")


class HelpViewDesktopContentTests(unittest.TestCase):
    """Vue Aide desktop v5 : ES module exporte initHelp (V5bis-07).

    Les anciennes assertions IIFE (`(function ()` + `window.HelpView`) ont ete
    remplacees par `tests/test_help_v5_ported.py` qui valide le port ES module.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.js = (cls.root / "web" / "views" / "help.js").read_text(encoding="utf-8")
        cls.html = (cls.root / "web" / "index.html").read_text(encoding="utf-8")

    def test_faq_count_at_least_15(self):
        items = re.findall(r"\bq:\s*\"", self.js)
        self.assertGreaterEqual(len(items), 15, f"FAQ doit avoir >=15 questions, a {len(items)}")

    def test_glossary_count_at_least_15(self):
        items = re.findall(r"\bterm:\s*\"", self.js)
        self.assertGreaterEqual(len(items), 15, f"Glossaire doit avoir >=15 termes, a {len(items)}")

    def test_glossary_covers_core_business_terms(self):
        for term in ["Tier", "Dry-run", "Quarantine", "Perceptual", "LPIPS", "Chromaprint", "NFO"]:
            self.assertIn(f'"{term}"', self.js, f"glossaire incomplet : {term} absent")

    def test_faq_covers_core_pain_points(self):
        keywords = ["dry-run", "Jellyfin", "antivirus", "tier", "annuler", "ffmpeg"]
        for kw in keywords:
            self.assertIn(kw, self.js, f"FAQ ne couvre pas: {kw}")

    def test_github_issues_link_present(self):
        self.assertIn("/issues", self.js)
        self.assertIn("github.com", self.js)

    def test_logs_path_visible(self):
        self.assertIn("LOCALAPPDATA", self.js)
        self.assertIn("cinesort.log", self.js)

    def test_search_input_id(self):
        self.assertIn("helpSearchInput", self.js)

    def test_html_view_section_present(self):
        self.assertIn('id="view-help"', self.html)
        self.assertIn('aria-labelledby="tab-help"', self.html)

    def test_html_sidebar_button_present(self):
        self.assertIn('data-view="help"', self.html)
        self.assertIn('id="tab-help"', self.html)
        self.assertIn('data-testid="nav-help"', self.html)

    def test_html_help_script_loaded(self):
        self.assertIn('"./views/help.js"', self.html)


@unittest.skip("V5C-01: dashboard/views/help.js supprime — la vue Aide dashboard charge desormais ../views/help.js (couvert par HelpViewDesktopContentTests + test_help_v5_ported)")
class HelpViewDashboardContentTests(unittest.TestCase):
    """Vue Aide dashboard distant : ES module, route /help."""

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.js = (cls.root / "web" / "dashboard" / "views" / "help.js").read_text(encoding="utf-8")
        cls.html = (cls.root / "web" / "dashboard" / "index.html").read_text(encoding="utf-8")
        cls.app = (cls.root / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        self.assertIn("export function initHelp", self.js)
        self.assertIn('from "../core/dom.js"', self.js)

    def test_faq_count_at_least_15(self):
        items = re.findall(r"\bq:\s*\"", self.js)
        self.assertGreaterEqual(len(items), 15, f"FAQ doit avoir >=15 questions, a {len(items)}")

    def test_glossary_count_at_least_15(self):
        items = re.findall(r"\bterm:\s*\"", self.js)
        self.assertGreaterEqual(len(items), 15, f"Glossaire doit avoir >=15 termes, a {len(items)}")

    def test_glossary_covers_core_business_terms(self):
        for term in ["Tier", "Dry-run", "Quarantine", "Perceptual", "LPIPS", "Chromaprint", "NFO"]:
            self.assertIn(f'"{term}"', self.js, f"glossaire incomplet : {term} absent")

    def test_github_issues_link_present(self):
        self.assertIn("/issues", self.js)
        self.assertIn("github.com", self.js)

    def test_logs_path_visible(self):
        self.assertIn("LOCALAPPDATA", self.js)
        self.assertIn("cinesort.log", self.js)

    def test_search_input_id(self):
        self.assertIn("helpSearchInput", self.js)

    def test_route_registered_in_app_js(self):
        # V5B-01 : route /help avec init: initHelp (sans appel inline document.getElementById)
        self.assertIn('registerRoute("/help"', self.app)
        self.assertIn("init: initHelp", self.app)

    def test_app_imports_init_help(self):
        # V5B-01 : help.js v5 vit dans web/views/, importe via "../views/help.js"
        self.assertIn('import { initHelp } from "../views/help.js"', self.app)

    def test_html_view_container(self):
        # V5B-01 : helpContent supprime, vue v5 monte directement dans #view-help
        self.assertIn('id="view-help"', self.html)

    @unittest.skip("V5B-01: sidebar v5 rendue dynamiquement par sidebar-v5.js, plus de data-route/data-testid statiques dans index.html")
    def test_html_sidebar_link(self):
        pass


@unittest.skip("V5C-01: dashboard/views/help.js supprime — desktop et dashboard partagent desormais le meme web/views/help.js (parite triviale)")
class HelpViewParityTests(unittest.TestCase):
    """Le contenu (FAQ + glossaire) doit etre aligne entre desktop et dashboard.

    On compare le nombre de questions et le set de termes du glossaire — les
    libelles peuvent diverger legerement mais le coeur metier doit matcher.
    """

    @classmethod
    def setUpClass(cls):
        cls.root = Path(__file__).resolve().parents[1]
        cls.desktop_js = (cls.root / "web" / "views" / "help.js").read_text(encoding="utf-8")
        cls.dashboard_js = (cls.root / "web" / "dashboard" / "views" / "help.js").read_text(encoding="utf-8")

    def test_same_faq_count(self):
        d = len(re.findall(r"\bq:\s*\"", self.desktop_js))
        w = len(re.findall(r"\bq:\s*\"", self.dashboard_js))
        self.assertEqual(d, w, f"FAQ desktop ({d}) != dashboard ({w})")

    def test_same_glossary_count(self):
        d = len(re.findall(r"\bterm:\s*\"", self.desktop_js))
        w = len(re.findall(r"\bterm:\s*\"", self.dashboard_js))
        self.assertEqual(d, w, f"Glossaire desktop ({d}) != dashboard ({w})")

    def test_glossary_terms_match(self):
        d_terms = set(re.findall(r'\bterm:\s*"([^"]+)"', self.desktop_js))
        w_terms = set(re.findall(r'\bterm:\s*"([^"]+)"', self.dashboard_js))
        self.assertEqual(
            d_terms, w_terms, f"divergence: desktop-only={d_terms - w_terms}, dashboard-only={w_terms - d_terms}"
        )


if __name__ == "__main__":
    unittest.main()

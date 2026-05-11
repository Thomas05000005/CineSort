"""V4-04 — Verifie la completude du README et la presence des screenshots."""

from __future__ import annotations

import unittest
from pathlib import Path


_PROJECT_ROOT = Path(__file__).resolve().parents[1]


class ReadmeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.readme = (_PROJECT_ROOT / "README.md").read_text(encoding="utf-8")

    def test_essential_sections(self):
        for section in [
            "Quick Start",
            "Captures",
            "Fonctionnalit",  # Fonctionnalites/Fonctionnalités
            "Stack technique",
            "FAQ",
            "Licence",
        ]:
            self.assertIn(section, self.readme, f"Section manquante : {section}")

    def test_has_badges(self):
        # Au moins 3 badges shields.io (license, python, tests)
        self.assertGreaterEqual(self.readme.count("img.shields.io"), 3)

    def test_has_screenshots(self):
        # Au moins 4 references a docs/screenshots
        self.assertGreaterEqual(self.readme.count("docs/screenshots/"), 4)

    def test_links_to_community_files(self):
        for f in ["CONTRIBUTING.md", "CODE_OF_CONDUCT.md", "SECURITY.md", "LICENSE"]:
            self.assertIn(f, self.readme, f"Lien manquant : {f}")

    def test_no_lorem_ipsum(self):
        for placeholder in ["lorem ipsum", "TODO:", "FIXME"]:
            self.assertNotIn(
                placeholder.lower(),
                self.readme.lower(),
                f"Placeholder non remplace : {placeholder}",
            )

    def test_screenshots_exist(self):
        screenshots_dir = _PROJECT_ROOT / "docs" / "screenshots"
        self.assertTrue(screenshots_dir.is_dir(), "docs/screenshots/ manquant")
        pngs = list(screenshots_dir.glob("*.png"))
        self.assertGreaterEqual(len(pngs), 4, f"Trop peu de screenshots : {len(pngs)}")


if __name__ == "__main__":
    unittest.main()

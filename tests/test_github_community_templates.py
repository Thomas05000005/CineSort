"""V4-03 — Vérifie l'existence et la validité des fichiers community GitHub."""

from __future__ import annotations
import unittest
from pathlib import Path


REQUIRED_FILES = [
    ".github/ISSUE_TEMPLATE/bug_report.yml",
    ".github/ISSUE_TEMPLATE/feature_request.yml",
    ".github/ISSUE_TEMPLATE/question.yml",
    ".github/ISSUE_TEMPLATE/config.yml",
    ".github/PULL_REQUEST_TEMPLATE.md",
    "CONTRIBUTING.md",
    "CODE_OF_CONDUCT.md",
    "SECURITY.md",
]


class CommunityTemplatesTests(unittest.TestCase):
    def test_all_required_files_present(self):
        for f in REQUIRED_FILES:
            with self.subTest(file=f):
                self.assertTrue(Path(f).is_file(), f"Manquant: {f}")

    def test_yaml_files_valid_yaml(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("PyYAML non installé (CI a yaml)")

        for f in REQUIRED_FILES:
            if f.endswith(".yml"):
                with self.subTest(file=f):
                    content = Path(f).read_text(encoding="utf-8")
                    parsed = yaml.safe_load(content)
                    self.assertIsNotNone(parsed)
                    self.assertIsInstance(parsed, dict)

    def test_contributing_has_essential_sections(self):
        content = Path("CONTRIBUTING.md").read_text(encoding="utf-8")
        for section in ["Setup", "Conventions", "Tests", "Pull Requests", "Licence"]:
            self.assertIn(section, content, f"CONTRIBUTING manque section: {section}")

    def test_security_has_contact(self):
        content = Path("SECURITY.md").read_text(encoding="utf-8")
        self.assertTrue(
            "PLACEHOLDER" in content or "advisories/new" in content,
            "SECURITY.md doit indiquer comment signaler une vulnérabilité",
        )

    def test_code_of_conduct_french(self):
        content = Path("CODE_OF_CONDUCT.md").read_text(encoding="utf-8")
        self.assertIn("engagement", content.lower())
        self.assertIn("Contributor Covenant", content)


if __name__ == "__main__":
    unittest.main()

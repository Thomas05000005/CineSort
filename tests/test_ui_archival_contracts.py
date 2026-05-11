from __future__ import annotations

import unittest
from pathlib import Path


class UiArchivalContractsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.root = Path(__file__).resolve().parents[1]
        cls.archive_root = cls.root / "docs" / "internal" / "archive" / "ui_next_20260319"
        cls.prototype_root = cls.archive_root / "prototype_web"
        cls.archived_files = [
            "index_next.html",
            "app_next.js",
            "styles_next.css",
            "ui_next_apply.js",
            "ui_next_quality.js",
            "ui_next_shell.js",
            "ui_next_validation.js",
        ]

    def test_active_web_runtime_no_longer_contains_next_variant(self) -> None:
        for filename in self.archived_files:
            self.assertFalse((self.root / "web" / filename).exists(), filename)

    def test_archived_next_prototype_is_preserved_for_reference(self) -> None:
        readme = (self.archive_root / "README.md").read_text(encoding="utf-8")
        for filename in self.archived_files:
            self.assertTrue((self.prototype_root / filename).exists(), filename)
        self.assertTrue((self.archive_root / "ui_next_contracts_snapshot.py.txt").exists())
        self.assertIn("l'UI stable devient l'unique source de verite runtime", readme)
        self.assertIn("non maintenu activement", readme)


if __name__ == "__main__":
    unittest.main()

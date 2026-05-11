"""V4-06 — Test structurel : valide que les artifacts (script + checklist) existent."""

from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


class V4_06ArtifactsTests(unittest.TestCase):
    def test_checklist_exists(self):
        self.assertTrue(
            (ROOT / "docs/internal/audit_v7_8_0/results/v4-06-devices-checklist.md").is_file(),
            "checklist humaine V4-06 manquante",
        )

    def test_script_exists(self):
        self.assertTrue(
            (ROOT / "tests/visual/test_responsive_viewports.py").is_file(),
            "script Playwright V4-06 manquant",
        )


if __name__ == "__main__":
    unittest.main()

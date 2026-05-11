"""V4-07 - Tests structurels des artefacts a11y."""

import unittest
from pathlib import Path


class V4_07ArtifactsTests(unittest.TestCase):
    def test_nvda_checklist_exists(self):
        self.assertTrue(Path("docs/internal/audit_v7_8_0/results/v4-07-nvda-checklist.md").is_file())

    def test_axe_test_exists(self):
        self.assertTrue(Path("tests/test_axe_dashboard.py").is_file())


if __name__ == "__main__":
    unittest.main()

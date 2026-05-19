from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


class RuntimeUiPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        root = Path(__file__).resolve().parents[1]
        spec = importlib.util.spec_from_file_location("cinesort_app_runtime_policy", root / "app.py")
        module = importlib.util.module_from_spec(spec)
        assert spec is not None and spec.loader is not None
        spec.loader.exec_module(module)
        cls.app_module = module

    def test_stable_is_default_without_dev_mode(self) -> None:
        self.assertFalse(self.app_module.is_dev_mode([], {}))
        self.assertEqual(self.app_module.requested_ui_variant([], {}), "stable")
        self.assertEqual(self.app_module.resolve_ui_variant([], {}), "stable")
        self.assertIsNone(self.app_module.resolve_ui_policy_notice([], {}))

    def test_next_falls_back_to_stable(self) -> None:
        self.assertEqual(self.app_module.requested_ui_variant(["--ui", "next"], {}), "next")
        self.assertEqual(self.app_module.requested_ui_variant([], {"CINESORT_UI": "next"}), "next")

        self.assertEqual(self.app_module.resolve_ui_variant(["--ui", "next"], {}), "stable")
        self.assertEqual(self.app_module.resolve_ui_variant([], {"CINESORT_UI": "next"}), "stable")

        self.assertIn(
            "Repli automatique vers l'UI stable",
            self.app_module.resolve_ui_policy_notice(["--ui", "next"], {}) or "",
        )

    def test_next_is_archived_even_in_explicit_dev_mode(self) -> None:
        self.assertTrue(self.app_module.is_dev_mode(["--dev"], {}))
        self.assertTrue(self.app_module.is_dev_mode([], {"DEV_MODE": "1"}))
        self.assertEqual(self.app_module.resolve_ui_variant(["--ui", "next", "--dev"], {}), "stable")
        self.assertEqual(self.app_module.resolve_ui_variant([], {"CINESORT_UI": "next", "DEV_MODE": "1"}), "stable")
        self.assertIn("archivee", self.app_module.resolve_ui_policy_notice(["--ui", "next", "--dev"], {}) or "")
        self.assertIn(
            "archivee",
            self.app_module.resolve_ui_policy_notice([], {"CINESORT_UI": "next", "DEV_MODE": "1"}) or "",
        )

    def test_unknown_variant_falls_back_to_stable(self) -> None:
        self.assertEqual(self.app_module.requested_ui_variant(["--ui=preview"], {}), "stable")
        self.assertEqual(self.app_module.resolve_ui_variant(["--ui=preview"], {}), "stable")
        self.assertIsNone(self.app_module.resolve_ui_policy_notice(["--ui=preview"], {}))

    def test_entrypoint_always_points_to_dashboard(self) -> None:
        expected = ("web/dashboard/index.html", "CineSort - Tri & normalisation de bibliotheque films")
        self.assertEqual(self.app_module.resolve_ui_entrypoint("stable"), expected)
        self.assertEqual(self.app_module.resolve_ui_entrypoint("next"), expected)
        self.assertEqual(self.app_module.resolve_ui_entrypoint("preview"), expected)


if __name__ == "__main__":
    unittest.main()

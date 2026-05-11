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

    def test_next_and_preview_fallback_to_stable_without_dev_mode(self) -> None:
        self.assertEqual(self.app_module.requested_ui_variant(["--ui", "next"], {}), "next")
        self.assertEqual(self.app_module.requested_ui_variant(["--ui=preview"], {}), "preview")
        self.assertEqual(self.app_module.requested_ui_variant([], {"CINESORT_UI": "next"}), "next")
        self.assertEqual(self.app_module.requested_ui_variant([], {"CINESORT_UI": "preview"}), "preview")

        self.assertEqual(self.app_module.resolve_ui_variant(["--ui", "next"], {}), "stable")
        self.assertEqual(self.app_module.resolve_ui_variant(["--ui=preview"], {}), "stable")
        self.assertEqual(self.app_module.resolve_ui_variant([], {"CINESORT_UI": "next"}), "stable")
        self.assertEqual(self.app_module.resolve_ui_variant([], {"CINESORT_UI": "preview"}), "stable")

        self.assertIn(
            "Repli automatique vers l'UI stable",
            self.app_module.resolve_ui_policy_notice(["--ui", "next"], {}) or "",
        )
        self.assertIn(
            "UI 'preview' reservee au mode dev",
            self.app_module.resolve_ui_policy_notice(["--ui=preview"], {}) or "",
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

    def test_preview_remains_the_only_dev_variant(self) -> None:
        self.assertEqual(self.app_module.resolve_ui_variant(["--ui=preview", "--dev"], {}), "preview")
        self.assertEqual(
            self.app_module.resolve_ui_variant([], {"CINESORT_UI": "preview", "DEV_MODE": "1"}),
            "preview",
        )
        self.assertIsNone(self.app_module.resolve_ui_policy_notice([], {"CINESORT_UI": "preview", "DEV_MODE": "1"}))

    def test_entrypoint_titles_follow_resolved_variant(self) -> None:
        # UI unifiee : le mode stable pointe desormais vers web/dashboard/index.html
        # (chemin fallback uniquement ; en realite pywebview charge http://127.0.0.1:PORT/dashboard/).
        self.assertEqual(
            self.app_module.resolve_ui_entrypoint("stable"),
            ("web/dashboard/index.html", "CineSort - Tri & normalisation de bibliotheque films"),
        )
        self.assertEqual(
            self.app_module.resolve_ui_entrypoint("next"),
            ("web/dashboard/index.html", "CineSort - Tri & normalisation de bibliotheque films"),
        )
        self.assertEqual(
            self.app_module.resolve_ui_entrypoint("preview"),
            ("web/index_preview.html", "CineSort [UI Preview] - Tri & normalisation de bibliotheque films"),
        )


if __name__ == "__main__":
    unittest.main()

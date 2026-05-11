"""V5bis-04 — Vérifie processing.js porté en ES module.

Tests structurels : confirme que la conversion IIFE -> ES module est faite,
que les 11 sites window.pywebview.api sont migrés vers apiPost, et que
les features V5A (V2-03 draft, V3-06 drawer, V2-07 EmptyState, V2-08
Skeleton, V2-04 allSettled) sont préservées.
"""

from __future__ import annotations

import unittest
from pathlib import Path


class ProcessingV5PortedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/processing.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        self.assertIn("export async function initProcessing", self.src)

    def test_no_iife(self):
        self.assertNotIn("window.ProcessingV5", self.src)

    def test_no_pywebview_api(self):
        self.assertNotIn("window.pywebview.api", self.src)

    def test_helpers_imported(self):
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_apipost_imported(self):
        self.assertIn("apiPost", self.src)

    def test_v2_03_draft_preserved(self):
        self.assertIn("DRAFT_KEY_PREFIX", self.src)
        self.assertIn("_scheduleDraftSave", self.src)
        self.assertIn("_checkAndOfferRestore", self.src)
        self.assertIn("localStorage", self.src)

    def test_v3_06_drawer_preserved(self):
        self.assertIn("v5ProcessingInspectorDrawer", self.src)

    def test_v2_07_emptystate_preserved(self):
        self.assertIn("buildEmptyState", self.src)

    def test_v2_08_skeleton_preserved(self):
        self.assertIn("_renderSkeletonForStep", self.src)

    def test_v2_04_allsettled_preserved(self):
        self.assertIn("Promise.allSettled", self.src)

    def test_three_steps_present(self):
        self.assertIn("_initScanStep", self.src)
        self.assertIn("_initReviewStep", self.src)
        self.assertIn("_initApplyStep", self.src)

    def test_emptystate_imported_from_dashboard(self):
        self.assertIn('from "../dashboard/components/empty-state.js"', self.src)

    def test_apipost_calls_use_kwargs(self):
        # apiPost utilise des kwargs (objet) — pas de positional args
        self.assertIn('apiPost("get_status"', self.src)
        self.assertIn('apiPost("start_plan"', self.src)
        self.assertIn('apiPost("load_validation"', self.src)
        self.assertIn('apiPost("save_validation"', self.src)
        self.assertIn('apiPost("apply"', self.src)
        self.assertIn('apiPost("cancel_run"', self.src)
        self.assertIn('apiPost("get_settings"', self.src)
        self.assertIn('apiPost("get_dashboard"', self.src)


if __name__ == "__main__":
    unittest.main()

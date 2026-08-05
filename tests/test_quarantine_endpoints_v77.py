"""GATE AUDIT 2026-06-10 (CRITICAL) — les 3 endpoints quarantaine construisent
la cfg correctement (plus de build_cfg_failed).

Avant : _build_cfg_from_settings_payload(settings) etait appele avec UN seul arg
alors que 4 kwargs keyword-only sont requis -> TypeError -> {ok:False,
build_cfg_failed} -> viewer + "Vider maintenant" morts ET le cron TTL ne purgeait
jamais (fix TTL rendu inoperant).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend


class QuarantineEndpointsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_quar_ep_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.api = backend.CineSortApi()
        self.api.settings.save_settings({"root": str(self.root), "state_dir": str(self.state_dir)})
        self.api._state_dir = self.state_dir  # type: ignore[attr-defined]

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_list_quarantine_no_build_cfg_failed(self) -> None:
        res = self.api._list_quarantine_bucket_impl()
        self.assertTrue(res.get("ok"), res)
        self.assertNotIn("build_cfg_failed", str(res.get("error", "")))

    def test_purge_quarantine_dry_run_no_build_cfg_failed(self) -> None:
        res = self.api._purge_quarantine_bucket_impl(ttl_days=30, dry_run=True)
        self.assertTrue(res.get("ok"), res)
        self.assertNotIn("build_cfg_failed", str(res.get("error", "")))

    def test_purge_all_dry_run_no_build_cfg_failed(self) -> None:
        res = self.api._purge_quarantine_bucket_all_impl(dry_run=True)
        self.assertTrue(res.get("ok"), res)

    def test_build_quarantine_cfg_returns_config_with_review_root(self) -> None:
        cfg = self.api._build_quarantine_cfg()
        self.assertEqual(Path(cfg.root), self.root)


if __name__ == "__main__":
    unittest.main()

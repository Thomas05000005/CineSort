"""V3-05 — Tests du mode démo wizard.

Couvre :
- structure des données (DEMO_FILMS : 15 films, tiers équilibrés)
- callables exportés (is_demo_active, start_demo_mode, stop_demo_mode)
- cycle de vie complet : start → is_active=True → 15 quality_reports → plan.jsonl → stop → tout supprimé
- présence des hooks frontend (wizard.js, app.js, styles.css)
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend
from cinesort.ui.api import demo_support


class DemoModeStaticTests(unittest.TestCase):
    """Vérifie la forme statique du module — pas besoin de DB."""

    def test_demo_films_count(self) -> None:
        self.assertEqual(len(demo_support.DEMO_FILMS), 15)

    def test_demo_tiers_balanced(self) -> None:
        tiers = {f["tier"] for f in demo_support.DEMO_FILMS}
        self.assertGreaterEqual(len(tiers), 4, f"4 tiers attendus, vu : {tiers}")
        self.assertIn("Premium", tiers)
        self.assertIn("Bon", tiers)
        self.assertIn("Moyen", tiers)
        self.assertIn("Mauvais", tiers)

    def test_demo_films_have_required_fields(self) -> None:
        required = {
            "title",
            "year",
            "tmdb_id",
            "tier",
            "score",
            "resolution",
            "video_codec",
            "audio_codec",
            "channels",
            "bitrate",
        }
        for film in demo_support.DEMO_FILMS:
            missing = required - set(film.keys())
            self.assertFalse(missing, f"Champs manquants dans {film.get('title')} : {missing}")

    def test_callables_exposed(self) -> None:
        self.assertTrue(callable(demo_support.is_demo_active))
        self.assertTrue(callable(demo_support.start_demo_mode))
        self.assertTrue(callable(demo_support.stop_demo_mode))


class DemoModeBackendCycleTests(unittest.TestCase):
    """Cycle complet start → stop sur une vraie DB SQLite temporaire."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_demo_")
        self.state_dir = Path(self._tmp) / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

        self.api = backend.CineSortApi()
        saved = self.api.save_settings(
            {
                "root": str(Path(self._tmp) / "fake_root"),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(saved.get("ok"), saved)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_initially_inactive(self) -> None:
        self.assertFalse(self.api.is_demo_mode_active().get("active"))

    def test_start_creates_run_quality_reports_and_plan_jsonl(self) -> None:
        result = self.api.start_demo_mode()
        self.assertTrue(result.get("ok"), result)
        self.assertEqual(result.get("count"), 15)
        run_id = result["run_id"]
        self.assertTrue(run_id.startswith("demo_"))

        # is_active doit refléter l'état
        self.assertTrue(self.api.is_demo_mode_active().get("active"))

        # 15 quality_reports persistés
        store, _ = self.api._get_or_create_infra(self.state_dir)
        reports = store.list_quality_reports(run_id=run_id)
        self.assertEqual(len(reports), 15)
        tiers_in_db = {r["tier"] for r in reports}
        self.assertEqual(tiers_in_db, {"Premium", "Bon", "Moyen", "Mauvais"})

        # plan.jsonl écrit avec 15 lignes JSON valides
        plan_path = self.state_dir / "runs" / f"tri_films_{run_id}" / "plan.jsonl"
        self.assertTrue(plan_path.is_file(), plan_path)
        lines = [ln for ln in plan_path.read_text(encoding="utf-8").splitlines() if ln.strip()]
        self.assertEqual(len(lines), 15)
        for ln in lines:
            row = json.loads(ln)
            self.assertIn("row_id", row)
            self.assertIn("proposed_title", row)

        # Run marqué DONE avec is_demo dans config_json
        run_row = store.get_run(run_id)
        self.assertIsNotNone(run_row)
        self.assertEqual(run_row.get("status"), "DONE")
        cfg = json.loads(run_row.get("config_json") or "{}")
        self.assertTrue(cfg.get("is_demo"))

    def test_start_twice_is_rejected(self) -> None:
        first = self.api.start_demo_mode()
        self.assertTrue(first.get("ok"))
        second = self.api.start_demo_mode()
        self.assertFalse(second.get("ok"))
        self.assertIn("démo", str(second.get("error", "")))

    def test_stop_removes_run_quality_reports_and_run_dir(self) -> None:
        start = self.api.start_demo_mode()
        run_id = start["run_id"]
        run_dir = self.state_dir / "runs" / f"tri_films_{run_id}"
        self.assertTrue(run_dir.is_dir())

        stop = self.api.stop_demo_mode()
        self.assertTrue(stop.get("ok"), stop)
        self.assertGreaterEqual(stop.get("removed", 0), 1)

        # is_active doit être False
        self.assertFalse(self.api.is_demo_mode_active().get("active"))

        # Quality reports supprimés
        store, _ = self.api._get_or_create_infra(self.state_dir)
        self.assertEqual(len(store.list_quality_reports(run_id=run_id)), 0)
        # Run supprimé
        self.assertIsNone(store.get_run(run_id))
        # Dossier run_dir supprimé
        self.assertFalse(run_dir.exists())


class DemoModeFrontendStructureTests(unittest.TestCase):
    """Vérifie la présence des hooks frontend (statique)."""

    @classmethod
    def setUpClass(cls) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        cls.wizard_js = (repo_root / "web" / "dashboard" / "views" / "demo-wizard.js").read_text(encoding="utf-8")
        cls.app_js = (repo_root / "web" / "dashboard" / "app.js").read_text(encoding="utf-8")
        cls.styles_css = (repo_root / "web" / "dashboard" / "styles.css").read_text(encoding="utf-8")

    def test_wizard_exports(self) -> None:
        self.assertIn("export async function showDemoWizardIfFirstRun", self.wizard_js)
        self.assertIn("export async function renderDemoBanner", self.wizard_js)

    def test_wizard_calls_api(self) -> None:
        self.assertIn('apiPost("start_demo_mode")', self.wizard_js)
        self.assertIn('apiPost("stop_demo_mode")', self.wizard_js)
        self.assertIn('apiPost("is_demo_mode_active")', self.wizard_js)

    def test_app_js_imports_wizard(self) -> None:
        self.assertIn("demo-wizard.js", self.app_js)
        self.assertIn("_initDemoMode", self.app_js)

    def test_styles_present(self) -> None:
        self.assertIn(".demo-wizard-overlay", self.styles_css)
        self.assertIn(".demo-wizard-card", self.styles_css)
        self.assertIn(".demo-banner", self.styles_css)


if __name__ == "__main__":
    unittest.main()

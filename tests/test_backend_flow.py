from __future__ import annotations

import shutil
import tempfile
import unittest
from unittest import mock
from pathlib import Path

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class CineSortApiFlowTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_test_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Keep tests lightweight by lowering minimum video size.
        # Issue #86 : mock.patch.object pour auto-restore safe meme si exception
        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_plan_validation_apply_full_flow(self) -> None:
        single = self.root / "Inception.2010.1080p"
        _create_file(single / "Inception.2010.1080p.mkv")

        collection = self.root / "Matrix Saga"
        _create_file(collection / "The.Matrix.1999.1080p.mkv")
        _create_file(collection / "The.Matrix.Reloaded.2003.1080p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)

        run_id = start["run_id"]
        status = _wait_done(api, run_id)
        self.assertIsNone(status.get("error"), status.get("error"))

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertGreaterEqual(len(rows), 3)
        self.assertTrue(any((row.get("notes") or "").strip() for row in rows))

        # Send intentionally dirty values; backend should normalize safely.
        decisions = {}
        for row in rows:
            decisions[row["row_id"]] = {"ok": True, "title": "  ", "year": "not-a-year"}
        first_row_id = rows[0]["row_id"]
        decisions[first_row_id]["ok"] = False

        sv = api.save_validation(run_id, decisions)
        self.assertTrue(sv.get("ok"), sv)

        lv = api.load_validation(run_id)
        self.assertTrue(lv.get("ok"), lv)
        saved = lv.get("decisions", {})
        self.assertTrue(saved)
        for row in rows:
            d = saved[row["row_id"]]
            self.assertIn("ok", d)
            self.assertIn("title", d)
            self.assertIn("year", d)
            self.assertIsInstance(d["year"], int)

        dup = api.check_duplicates(run_id, decisions)
        self.assertTrue(dup.get("ok"), dup)
        self.assertIn("total_groups", dup)

        dry = api.apply(run_id, decisions, True, False)
        self.assertTrue(dry.get("ok"), dry)
        dry_result = dry["result"]
        self.assertEqual(dry_result["errors"], 0, dry_result)
        self.assertGreaterEqual(dry_result["collection_moves"], 1, dry_result)
        self.assertGreaterEqual(dry_result["moves"], 1, dry_result)
        self.assertGreaterEqual(int((dry_result.get("skip_reasons") or {}).get("skip_non_valide", 0)), 1, dry_result)

        real = api.apply(run_id, decisions, False, True)
        self.assertTrue(real.get("ok"), real)
        result = real["result"]
        self.assertEqual(result["errors"], 0, result)
        summary_txt = self.state_dir / "runs" / f"tri_films_{run_id}" / "summary.txt"
        self.assertTrue(summary_txt.exists(), summary_txt)
        summary_text = summary_txt.read_text(encoding="utf-8")
        self.assertIn("=== RESUME APPLICATION ===", summary_text)
        self.assertIn("SITUATION APPLICATION", summary_text)
        self.assertIn("CE QUI N'A PAS ETE APPLIQUE", summary_text)
        self.assertIn("NETTOYAGE ET RANGEMENT", summary_text)
        self.assertIn("A RETENIR AVANT LA SUITE", summary_text)
        self.assertIn("Dossiers vides deplaces (_Vide)", summary_text)
        self.assertIn("Dossiers residuels deplaces (_Dossier Nettoyage)", summary_text)
        self.assertEqual(summary_text.count("=== RESUME APPLICATION ==="), 1)
        self.assertIn("Fusions realisees", summary_text)
        self.assertIn("Duplicats identiques deplaces", summary_text)
        self.assertIn("Conflits isoles en _review", summary_text)
        self.assertIn("Conflits sidecars gardes des deux cotes", summary_text)

    def test_start_plan_reports_missing_root(self) -> None:
        api = CineSortApi()
        bad_root = self.root / "__missing__"
        start = api.run.start_plan(
            {
                "root": str(bad_root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertFalse(start.get("ok"), start)
        self.assertIn("ROOT", str(start.get("message", "")))

    def test_analysis_summary_clarifies_ignored_entries_vs_observed_extensions(self) -> None:
        noise = self.root / "Noise.Only"
        noise.mkdir(parents=True, exist_ok=True)
        (noise / "note.txt").write_text("x", encoding="utf-8")
        (noise / "poster.jpg").write_bytes(b"\x00")
        (noise / "info.nfo").write_text("<movie/>", encoding="utf-8")
        _create_file(self.root / "Movie.2020" / "Movie.2020.mkv")

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        _wait_done(api, start["run_id"])

        summary_txt = self.state_dir / "runs" / f"tri_films_{start['run_id']}" / "summary.txt"
        self.assertTrue(summary_txt.exists(), summary_txt)
        summary_text = summary_txt.read_text(encoding="utf-8")
        self.assertIn("SITUATION ANALYSE", summary_text)
        self.assertIn("Cas probablement surs :", summary_text)
        self.assertIn("Cas a verifier :", summary_text)
        self.assertIn("ENTREES IGNOREES", summary_text)
        self.assertIn("Entrees ignorees pendant analyse :", summary_text)
        self.assertIn("CE QUI EST A VERIFIER EN PRIORITE", summary_text)
        self.assertIn(
            "FICHIERS ANNEXES / NON SUPPORTES OBSERVES",
            summary_text,
        )
        self.assertIn("- .txt:", summary_text)
        self.assertIn("- .jpg:", summary_text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

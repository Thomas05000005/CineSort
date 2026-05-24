"""Tests Phase 6 — Carte "Annulation post-apply" (Spec 08 §3.5).

Verifie le contrat backend qui alimente la carte UI dans views/traitement.js :
- run/get_dashboard expose `pending_undo` (batch_id, apply_ts, deadline_ts,
  expired, reversible_count) apres un apply reel.
- run/get_dashboard renvoie `pending_undo=None` quand il n'y a pas d'apply
  reversible (avant apply, ou apres undo).
- run/undo_last_apply_preview expose `apply_ts` et un echantillon
  `samples` (max 20) consommable par la modale UI.
- La deadline 24h est calculee (apply_ts + 86400) et `expired` bascule a True
  quand on simule un apply > 24h.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


class UndoCardDashboardContractTests(unittest.TestCase):
    """Spec 08 §3.5 : contrat dashboard + undo preview consommes par
    la carte "Annulation possible" de la vue Traitement."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cs_undo_card_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p_min = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min.start()
        self.addCleanup(_p_min.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed_run_and_apply(self, api: CineSortApi) -> str:
        src_folder = self.root / "Old.Name.2010.1080p"
        _create_file(src_folder / "Old.Name.2010.1080p.mkv")
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        _wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertTrue(rows)
        decisions = {
            row["row_id"]: {
                "ok": True,
                "title": row.get("proposed_title"),
                "year": row.get("proposed_year"),
            }
            for row in rows
        }
        applied = api._apply_impl(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)
        return run_id

    def test_dashboard_exposes_pending_undo_after_real_apply(self) -> None:
        api = CineSortApi()
        run_id = self._seed_run_and_apply(api)

        dash = api.run.get_dashboard(run_id)
        self.assertTrue(dash.get("ok"), dash)
        pending = dash.get("pending_undo")
        self.assertIsNotNone(pending, "pending_undo doit etre present apres apply reel")
        self.assertTrue(pending.get("batch_id"))
        self.assertGreater(float(pending.get("apply_ts") or 0), 0.0)
        self.assertGreater(float(pending.get("deadline_ts") or 0), 0.0)
        # deadline = apply_ts + 24h, donc deadline > apply_ts d'environ 86400s.
        delta = float(pending["deadline_ts"]) - float(pending["apply_ts"])
        self.assertAlmostEqual(delta, 24 * 3600, delta=1.0)
        self.assertEqual(int(pending.get("deadline_seconds_total") or 0), 24 * 3600)
        self.assertGreaterEqual(int(pending.get("reversible_count") or 0), 1)
        self.assertFalse(pending.get("expired"))

    def test_dashboard_pending_undo_is_none_without_real_apply(self) -> None:
        """Avant apply reel : pending_undo doit etre None (carte cachee)."""
        api = CineSortApi()
        src_folder = self.root / "DryRun.Movie.2011.1080p"
        _create_file(src_folder / "DryRun.Movie.2011.1080p.mkv")
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        run_id = str(start["run_id"])
        _wait_done(api, run_id)

        dash = api.run.get_dashboard(run_id)
        self.assertTrue(dash.get("ok"), dash)
        # Cle presente mais valeur None : front affiche rien.
        self.assertIn("pending_undo", dash)
        self.assertIsNone(dash.get("pending_undo"))

    def test_dashboard_pending_undo_none_after_undo(self) -> None:
        """Apres undo execute : plus de batch reversible -> pending_undo=None."""
        api = CineSortApi()
        run_id = self._seed_run_and_apply(api)

        dash_before = api.run.get_dashboard(run_id)
        self.assertIsNotNone(dash_before.get("pending_undo"))

        restored = api._undo_last_apply_impl(run_id, False)
        self.assertTrue(restored.get("ok"), restored)

        dash_after = api.run.get_dashboard(run_id)
        self.assertTrue(dash_after.get("ok"), dash_after)
        self.assertIsNone(dash_after.get("pending_undo"))

    def test_dashboard_pending_undo_marks_expired_after_24h(self) -> None:
        """Si apply_ts > 24h : pending_undo.expired=True (delai depasse)."""
        api = CineSortApi()
        run_id = self._seed_run_and_apply(api)

        # On force le temps a +25h pour simuler un depassement de delai.
        future = time.time() + 25 * 3600
        with mock.patch("cinesort.ui.api.dashboard_support.time.time", return_value=future):
            dash = api.run.get_dashboard(run_id)
        self.assertTrue(dash.get("ok"), dash)
        pending = dash.get("pending_undo")
        self.assertIsNotNone(pending)
        self.assertTrue(pending.get("expired"), pending)
        self.assertEqual(int(pending.get("remaining_seconds") or 0), 0)

    def test_undo_preview_exposes_apply_ts_and_samples(self) -> None:
        """run/undo_last_apply_preview doit fournir apply_ts + samples
        consommes par la modale "Prévisualiser annulation"."""
        api = CineSortApi()
        run_id = self._seed_run_and_apply(api)

        preview = api._undo_last_apply_preview_impl(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertTrue(preview.get("can_undo"), preview)

        # Nouveau champ apply_ts (timestamp de l'apply reel).
        self.assertIn("apply_ts", preview)
        self.assertGreater(float(preview["apply_ts"] or 0), 0.0)

        # Nouveau champ samples (max 20) : liste de dicts current_path/restore_path.
        samples = preview.get("samples")
        self.assertIsInstance(samples, list)
        self.assertGreaterEqual(len(samples), 1)
        self.assertLessEqual(len(samples), 20)
        first = samples[0]
        self.assertIn("op_type", first)
        self.assertIn("current_path", first)
        self.assertIn("restore_path", first)
        self.assertTrue(str(first["current_path"]))
        self.assertTrue(str(first["restore_path"]))


if __name__ == "__main__":
    unittest.main()

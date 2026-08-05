"""Issue #491 — le compte a rebours affiche et le refus backend disent la MEME chose.

La promesse « annulation possible pendant 24 h » (Spec 08 §3.5) etait portee par
DEUX constantes distinctes valant la meme chose par convention : celle de
`dashboard_support` alimente `deadline_seconds_total`, donc le compte a rebours
de la vue Traitement ; celle d'`apply_support` decide du HTTP 410. Rien
n'imposait leur egalite : changer la politique d'un seul cote donnait une
interface qui annonce « encore 3 h » face a un backend qui refuse deja — ou un
bouton masque alors que le backend accepterait encore.

Ce test ne compare pas deux constantes entre elles (ce serait tautologique une
fois fusionnees) : il PART de la valeur annoncee a l'interface et verifie que
c'est bien a cette seconde-la que le backend bascule. Il rougit donc des qu'un
des deux cotes derive, quelle que soit la maniere dont la derive est ecrite.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api import apply_support, dashboard_support
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done

# Marge autour de l'echeance. Assez large pour absorber la seconde qui s'ecoule
# entre l'apply et la lecture du batch, assez fine pour qu'un ecart de politique
# (12 h, 48 h, 7 j) tombe toujours du mauvais cote.
_MARGE_S = 600.0


class UndoDeadlineSourceUniqueTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo491_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _apply_one(self):
        src = self.root / "Dead.Line.2021.1080p"
        src.mkdir(parents=True, exist_ok=True)
        (src / "Dead.Line.2021.1080p.mkv").write_bytes(b"x" * 8)
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
        run_id = str(start["run_id"])
        _wait_done(api, run_id)
        rows = api.run.get_plan(run_id).get("rows", [])
        self.assertTrue(rows)
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title"), "year": r.get("proposed_year")} for r in rows
        }
        self.assertTrue(api._apply_impl(run_id, decisions, False, False).get("ok"))
        _row, store = api._find_run_row(run_id)
        batch = store.apply.get_last_reversible_apply_batch(run_id)
        return api, store, run_id, rows[0]["row_id"], float(batch["started_ts"])

    def _echeance_annoncee_a_l_interface(self, store, run_id) -> float:
        pending = dashboard_support._build_pending_undo_payload(store, run_id)
        self.assertIsNotNone(pending, "la carte « Annulation possible » doit exister apres un apply")
        total = float(pending["deadline_seconds_total"])
        self.assertGreater(total, 0.0)
        return total

    def test_avant_l_echeance_annoncee_le_backend_ne_considere_pas_l_undo_expire(self) -> None:
        api, store, run_id, _row_id, apply_ts = self._apply_one()
        total = self._echeance_annoncee_a_l_interface(store, run_id)
        with mock.patch.object(apply_support.time, "time", return_value=apply_ts + total - _MARGE_S):
            preview = api.run.undo_last_apply_preview(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertIs(
            preview.get("expired"),
            False,
            "l'interface annonce du temps restant : le backend ne doit pas se croire expire",
        )

    def test_apres_l_echeance_annoncee_le_backend_se_declare_expire(self) -> None:
        api, store, run_id, _row_id, apply_ts = self._apply_one()
        total = self._echeance_annoncee_a_l_interface(store, run_id)
        with mock.patch.object(apply_support.time, "time", return_value=apply_ts + total + _MARGE_S):
            preview = api.run.undo_last_apply_preview(run_id)
        self.assertTrue(preview.get("ok"), preview)
        self.assertIs(preview.get("expired"), True)

    def test_apres_l_echeance_annoncee_l_undo_selectif_reel_est_refuse_en_410(self) -> None:
        api, store, run_id, row_id, apply_ts = self._apply_one()
        total = self._echeance_annoncee_a_l_interface(store, run_id)
        with mock.patch.object(apply_support.time, "time", return_value=apply_ts + total + _MARGE_S):
            refused = api._undo_selected_rows_impl(run_id, [row_id], dry_run=False)
        self.assertFalse(refused.get("ok"), refused)
        self.assertEqual(refused.get("http_status"), 410, refused)

    def test_apres_l_echeance_annoncee_l_undo_complet_reel_est_refuse_en_410(self) -> None:
        api, store, run_id, _row_id, apply_ts = self._apply_one()
        total = self._echeance_annoncee_a_l_interface(store, run_id)
        with mock.patch.object(apply_support.time, "time", return_value=apply_ts + total + _MARGE_S):
            refused = api._undo_last_apply_impl(run_id, dry_run=False)
        self.assertFalse(refused.get("ok"), refused)
        self.assertEqual(refused.get("http_status"), 410, refused)


if __name__ == "__main__":
    unittest.main()

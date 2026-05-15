"""P1.2 : tests pour preverify_undo_operations + undo atomic.

Trois surfaces testées :
1. `preverify_undo_operations` (fonction pure) : classe correctement les ops.
2. `_execute_undo_ops` en mode atomic : abandon si hash mismatch.
3. End-to-end : apply réel + remplacement manuel + undo refusé atomiquement.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from unittest import mock
from pathlib import Path

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from cinesort.ui.api.apply_support import preverify_undo_operations


class PreverifyUndoOperationsPureTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_preverify_")
        self.base = Path(self._tmp)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_op(self, id_: int, dst: Path, sha1: str | None = None, size: int | None = None) -> dict:
        return {
            "id": id_,
            "op_type": "MOVE_FILE",
            "src_path": str(self.base / "src" / dst.name),
            "dst_path": str(dst),
            "reversible": 1,
            "undo_status": "PENDING",
            "src_sha1": sha1,
            "src_size": size,
        }

    def test_missing_destination_classified(self):
        op = self._make_op(1, self.base / "missing.mkv", sha1="abc123", size=100)
        report = preverify_undo_operations([op])
        self.assertEqual(len(report["missing"]), 1)
        self.assertEqual(len(report["safe"]), 0)

    def test_legacy_no_hash_classified(self):
        # Op pré-P1.2 : pas de sha1/size persisté
        target = self.base / "legacy.mkv"
        target.write_bytes(b"content")
        op = self._make_op(2, target, sha1=None, size=None)
        report = preverify_undo_operations([op])
        self.assertEqual(len(report["legacy_no_hash"]), 1)
        self.assertEqual(len(report["safe"]), 0)

    def test_safe_when_hash_matches(self):
        from cinesort.app.apply_core import sha1_quick

        target = self.base / "match.mkv"
        target.write_bytes(b"identique" * 100)
        expected_sha1 = sha1_quick(target)
        expected_size = target.stat().st_size
        op = self._make_op(3, target, sha1=expected_sha1, size=expected_size)
        report = preverify_undo_operations([op])
        self.assertEqual(len(report["safe"]), 1)
        self.assertEqual(len(report["hash_mismatch"]), 0)

    def test_hash_mismatch_on_size(self):
        target = self.base / "resized.mkv"
        target.write_bytes(b"nouveau contenu different")
        # size stockée volontairement différente
        op = self._make_op(4, target, sha1="deadbeef", size=9999999)
        report = preverify_undo_operations([op])
        self.assertEqual(len(report["hash_mismatch"]), 1)
        self.assertIn("taille", report["hash_mismatch"][0]["preverify_reason"])

    def test_hash_mismatch_on_sha1(self):
        from cinesort.app.apply_core import sha1_quick

        target = self.base / "changed.mkv"
        target.write_bytes(b"original" * 100)
        real_sha1 = sha1_quick(target)
        real_size = target.stat().st_size
        # Stocke une sha1 bidon (mais la bonne size pour passer le check taille)
        op = self._make_op(5, target, sha1="0" * 40, size=real_size)
        self.assertNotEqual(real_sha1, "0" * 40)  # sanity
        report = preverify_undo_operations([op])
        self.assertEqual(len(report["hash_mismatch"]), 1)
        self.assertIn("empreinte", report["hash_mismatch"][0]["preverify_reason"])

    def test_mixed_classification(self):
        from cinesort.app.apply_core import sha1_quick

        # 1 safe, 1 legacy, 1 missing, 1 mismatch
        ok = self.base / "ok.mkv"
        ok.write_bytes(b"safe_content")
        legacy = self.base / "legacy.mkv"
        legacy.write_bytes(b"legacy_content")
        mismatch = self.base / "bad.mkv"
        mismatch.write_bytes(b"modifie_par_user")

        ops = [
            self._make_op(10, ok, sha1=sha1_quick(ok), size=ok.stat().st_size),
            self._make_op(11, legacy, sha1=None, size=None),
            self._make_op(12, self.base / "gone.mkv", sha1="abc", size=100),
            self._make_op(13, mismatch, sha1="0" * 40, size=mismatch.stat().st_size),
        ]
        report = preverify_undo_operations(ops)
        self.assertEqual(len(report["safe"]), 1)
        self.assertEqual(len(report["legacy_no_hash"]), 1)
        self.assertEqual(len(report["missing"]), 1)
        self.assertEqual(len(report["hash_mismatch"]), 1)


class UndoAtomicEndToEndTests(unittest.TestCase):
    """Scénario réel : apply + modification fichier + undo atomique refusé."""

    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo_atomic_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        # Issue #86 : mock.patch.object pour auto-restore safe meme si exception
        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _wait_done(self, api: CineSortApi, run_id: str, timeout_s: float = 10.0) -> None:
        deadline = time.time() + timeout_s
        while time.time() < deadline:
            last = api.run.get_status(run_id, 0)
            if last.get("done"):
                return
            time.sleep(0.05)
        self.fail(f"Timeout waiting run completion run_id={run_id}")

    def test_atomic_undo_refuses_when_destination_file_replaced(self):
        # 1. Créer un film à la racine
        folder = self.root / "Inception.2010.1080p"
        folder.mkdir(parents=True)
        vid = folder / "Inception.2010.1080p.mkv"
        vid.write_bytes(b"VERSION_ORIGINALE" * 1024)

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = start["run_id"]
        self._wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertTrue(rows, plan)
        decisions = {r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]} for r in rows}

        # 2. Appliquer pour de vrai
        result = api.apply(
            run_id=run_id,
            dry_run=False,
            decisions=decisions,
            quarantine_unapproved=False,
        )
        self.assertTrue(result.get("ok"), result)

        # 3. Trouver l'op principale (MOVE_DIR du dossier contenant le vidéo)
        found = api._find_run_row(run_id)
        self.assertIsNotNone(found)
        _, store = found
        batch = store.get_last_reversible_apply_batch(run_id)
        self.assertIsNotNone(batch)
        ops = store.list_apply_operations(batch_id=batch["batch_id"])
        video_op = next(
            (op for op in ops if op["op_type"] in ("MOVE_FILE", "MOVE_DIR") and op.get("src_sha1")),
            None,
        )
        self.assertIsNotNone(video_op, f"Pas d'op avec src_sha1 dans {ops}")
        self.assertTrue(video_op["src_sha1"], "Le sha1 devrait être capturé par P1.2")

        # 4. Simuler un remplacement manuel du fichier vidéo à l'intérieur
        final_dst = Path(video_op["dst_path"])
        self.assertTrue(final_dst.exists())
        if video_op["op_type"] == "MOVE_DIR":
            # Trouver le vidéo à l'intérieur et le remplacer
            videos = list(final_dst.glob("*.mkv")) + list(final_dst.glob("*.mp4"))
            self.assertTrue(videos, f"Pas de vidéo dans {final_dst}")
            videos[0].write_bytes(b"CONTENU_DIFFERENT_UTILISATEUR" * 512)
        else:
            final_dst.write_bytes(b"CONTENU_DIFFERENT_UTILISATEUR" * 512)

        # 5. Tenter un undo atomique : doit être refusé
        undo_res = api.undo_last_apply(run_id=run_id, dry_run=False, atomic=True)
        self.assertFalse(undo_res.get("ok"))
        self.assertEqual(undo_res.get("status"), "ABORTED_HASH_MISMATCH")
        self.assertIn("preverify", undo_res)
        self.assertGreaterEqual(undo_res["preverify"]["hash_mismatch_count"], 1)
        # Le dossier modifié doit TOUJOURS être à sa destination (pas bougé par l'undo)
        self.assertTrue(final_dst.exists())

        # 6. Undo best-effort : le fichier modifié est skip, pas d'erreur globale
        undo_res2 = api.undo_last_apply(run_id=run_id, dry_run=False, atomic=False)
        # aboutit : ok=True (undo_selective/standard), status peut être partial
        self.assertIn(undo_res2.get("status"), ("UNDONE_DONE", "UNDONE_PARTIAL"))


if __name__ == "__main__":
    unittest.main()

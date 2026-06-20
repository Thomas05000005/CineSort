"""Fix audit 2026-05-25 (v1.5.3) Vague F : verifier que la preview apply
n'induit JAMAIS l'utilisateur a penser que le fichier video est renomme.

apply_core.py ne renomme JAMAIS les fichiers video (contrainte projet :
"JAMAIS modifier le titre des films"). Seul le dossier parent est
renomme/deplace. Ce test verifie que la preview structuree expose :
  - video_filename identique entre src et dst
  - action_summary classifie correctement (folder_rename pour MOVE_DIR)
  - folder_old_name / folder_new_name distinguent l'avant/apres dossier
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import wait_run_done as _wait_done


class ApplyPreviewNoVideoRenameTests(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.mkdtemp(prefix="cinesort_no_rename_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self):
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _make_single_film(self) -> tuple[CineSortApi, str, list]:
        folder = self.root / "Inception.2010.1080p.BluRay"
        folder.mkdir(parents=True)
        (folder / "Inception.2010.1080p.BluRay.mkv").write_bytes(b"x" * 2048)

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
            }
        )
        self.assertTrue(start.get("ok"))
        run_id = start["run_id"]
        _wait_done(api, run_id)
        plan = api.run.get_plan(run_id)
        return api, run_id, plan.get("rows", [])

    def test_video_filename_preserved_in_preview_ops(self):
        """Pour un film "single", chaque op preview doit avoir video_filename
        identique en src/dst (ou vide pour MOVE_DIR), JAMAIS un renommage."""
        api, run_id, rows = self._make_single_film()
        self.assertTrue(rows)
        decisions = {
            r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]}
            for r in rows
        }
        preview = api.run.build_apply_preview(run_id, decisions)
        self.assertTrue(preview.get("ok"), preview)
        self.assertTrue(preview.get("films"))

        for film in preview["films"]:
            for op in film["ops"]:
                # Tous les nouveaux champs doivent exister
                self.assertIn("folder_old_name", op)
                self.assertIn("folder_new_name", op)
                self.assertIn("video_filename", op)
                self.assertIn("action_summary", op)
                # Retro-compat preservee
                self.assertIn("src_path", op)
                self.assertIn("dst_path", op)
                # Cle invariante : un MOVE_FILE conserve toujours le nom
                # du fichier (sauf series TV, mais le film simple ici n'est
                # pas une serie).
                if op["op_type"] == "MOVE_FILE":
                    src_name = Path(op["src_path"]).name
                    dst_name = Path(op["dst_path"]).name
                    self.assertEqual(
                        src_name,
                        dst_name,
                        f"VIOLATION : fichier video renomme {src_name} -> {dst_name}",
                    )
                    self.assertEqual(op["video_filename"], src_name)
                    self.assertIn(
                        op["action_summary"],
                        ("video_move", "folder_rename_and_video_move"),
                    )
                elif op["op_type"] == "MOVE_DIR":
                    # Un MOVE_DIR doit etre classe comme folder_rename
                    self.assertEqual(op["action_summary"], "folder_rename")

    def test_action_summary_folder_rename_when_only_move_dir(self):
        """Cas typique : un film dont seul le dossier est renomme doit
        produire au moins une op classifiee `folder_rename`."""
        api, run_id, rows = self._make_single_film()
        decisions = {
            r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]}
            for r in rows
        }
        preview = api.run.build_apply_preview(run_id, decisions)
        all_summaries = [
            op["action_summary"]
            for film in preview["films"]
            for op in film["ops"]
        ]
        # Au moins une operation doit etre un folder_rename
        self.assertIn(
            "folder_rename",
            all_summaries,
            f"Attendu folder_rename dans {all_summaries}",
        )

    def test_preview_does_not_modify_filesystem(self):
        """Re-verifier la garantie no-op : la preview ne doit modifier
        ni le fichier video ni son nom sur disque."""
        api, run_id, rows = self._make_single_film()
        decisions = {
            r["row_id"]: {"ok": True, "title": r["proposed_title"], "year": r["proposed_year"]}
            for r in rows
        }
        before = sorted(p.name for p in self.root.rglob("*"))
        _ = api.run.build_apply_preview(run_id, decisions)
        after = sorted(p.name for p in self.root.rglob("*"))
        self.assertEqual(before, after)
        # Le fichier .mkv original est toujours la, intact
        self.assertTrue(
            (self.root / "Inception.2010.1080p.BluRay" / "Inception.2010.1080p.BluRay.mkv").exists()
        )


if __name__ == "__main__":
    unittest.main()

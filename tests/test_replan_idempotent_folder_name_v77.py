"""GATE AUDIT 2026-06-11 (R3e, gap[3]) — replan idempotent sur folder_name.

Avant : _resolve_folder_context calcule
`folder_name = Path(video.name).stem if _folder_is_root else folder.name`.
Le caller replan (_rematch_tmdb_and_update_plan) construit cfg avec
root=dossier_du_film, donc en replan `_folder_is_root` est TOUJOURS True ->
folder_name = stem du fichier au lieu du dossier propre. Inputs differents
pour infer_name_year/build_candidates -> match potentiellement different ->
NON idempotent vs le scan initial (ou cfg.root = racine biblio != folder).

Apres : replan_single_row accepte `library_root` (la vraie racine du scan) et
la propage jusqu'a _resolve_folder_context ; `_folder_is_root` est evalue
contre cette racine -> folder_name = folder.name (idempotent avec le scan).

Discriminant : un film 'MonFilm (1995)' dont la VIDEO n'a pas d'annee dans son
nom ('rip_final.mkv'). folder.name porte 1995, le stem fichier ne porte rien.
detected_year vaut donc 1995 (folder.name) ou 0 (stem) selon le bug.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app.plan_support_replan import replan_single_row


class ReplanIdempotentFolderNameTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_replan_idem_")
        self.lib_root = Path(self._tmp)  # racine biblio
        self.folder = self.lib_root / "MonFilm (1995)"  # dossier propre du film
        self.folder.mkdir(parents=True, exist_ok=True)
        self.video = self.folder / "rip_final.mkv"  # stem SANS annee
        self.video.write_bytes(b"x" * 4096)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _scan_detected_year(self) -> int:
        # Reference 'scan' : cfg.root = racine biblio (!= folder) -> folder_name
        # = folder.name. Pas besoin de library_root (folder != cfg.root).
        cfg = core.Config(root=self.lib_root, enable_tmdb=False)
        row = replan_single_row(cfg, self.folder, self.video, kind="single")
        self.assertIsNotNone(row)
        return int(row.detected_year)

    def test_replan_with_library_root_is_idempotent(self) -> None:
        scan_year = self._scan_detected_year()
        self.assertEqual(scan_year, 1995, "baseline scan : folder.name porte 1995")

        # Replan facon caller : cfg.root = dossier du film, + library_root explicite.
        cfg = core.Config(root=self.folder, enable_tmdb=False)
        row = replan_single_row(
            cfg, self.folder, self.video, kind="single", library_root=self.lib_root
        )
        self.assertIsNotNone(row)
        self.assertEqual(
            int(row.detected_year),
            scan_year,
            "replan AVEC library_root doit retrouver folder.name -> meme detected_year que le scan",
        )

    def test_replan_without_library_root_loses_folder_name(self) -> None:
        # Documente le bug : sans library_root, cfg.root==folder -> stem fichier
        # -> annee perdue (regression historique). Ce test verrouille que le fix
        # ne s'appuie PAS sur un comportement par defaut deja correct.
        cfg = core.Config(root=self.folder, enable_tmdb=False)
        row = replan_single_row(cfg, self.folder, self.video, kind="single")
        self.assertIsNotNone(row)
        self.assertEqual(
            int(row.detected_year),
            0,
            "sans library_root (cfg.root==folder), folder_name tombe sur le stem "
            "sans annee -> detected_year=0 (comportement bugue d'origine)",
        )


if __name__ == "__main__":
    unittest.main()

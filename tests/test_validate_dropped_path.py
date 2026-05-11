"""M-7 audit QA 20260429 — tests validate_dropped_path durci.

Verifie que :
- Path vide -> refus.
- Path inexistant -> refus.
- Path fichier (pas dossier) -> refus.
- Path UNC special \\\\?\\ ou \\\\.\\ -> refus (M-7).
- Path symlink -> refus (M-7).
- Path dossier valide -> ok + path resolu.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

import cinesort.ui.api.cinesort_api as backend


class ValidateDroppedPathTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_drop_")
        self.tmp = Path(self._tmp)
        self.api = backend.CineSortApi()

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_empty_path_refused(self) -> None:
        result = self.api.validate_dropped_path("")
        self.assertFalse(result["ok"])
        self.assertIn("vide", result["message"].lower())

    def test_whitespace_only_refused(self) -> None:
        result = self.api.validate_dropped_path("   ")
        self.assertFalse(result["ok"])

    def test_missing_path_refused(self) -> None:
        ghost = str(self.tmp / "ghost_folder_xyz")
        result = self.api.validate_dropped_path(ghost)
        self.assertFalse(result["ok"])
        self.assertIn("introuvable", result["message"].lower())

    def test_file_refused(self) -> None:
        f = self.tmp / "file.txt"
        f.write_text("hello")
        result = self.api.validate_dropped_path(str(f))
        self.assertFalse(result["ok"])
        self.assertIn("dossier", result["message"].lower())

    def test_valid_dir_accepted(self) -> None:
        result = self.api.validate_dropped_path(str(self.tmp))
        self.assertTrue(result["ok"], result)
        self.assertIn("path", result)
        # Le path retourne doit etre resolu (absolu)
        self.assertTrue(Path(result["path"]).is_absolute())

    def test_unc_special_namespace_refused(self) -> None:
        """M-7 : \\\\?\\C:\\Users ou \\\\.\\C:\\Users sont des UNC speciaux."""
        result = self.api.validate_dropped_path("\\\\?\\C:\\Users\\Test")
        self.assertFalse(result["ok"])
        self.assertIn("UNC special", result["message"])

        result = self.api.validate_dropped_path("\\\\.\\C:\\Users\\Test")
        self.assertFalse(result["ok"])
        self.assertIn("UNC special", result["message"])

    def test_unc_special_with_forward_slashes_refused(self) -> None:
        """Variante avec / : //?/C:/... est aussi refuse apres normalisation."""
        result = self.api.validate_dropped_path("//?/C:/Users/Test")
        self.assertFalse(result["ok"])
        self.assertIn("UNC special", result["message"])

    @unittest.skipIf(sys.platform == "win32", "symlinks non supportes facilement sur Windows non-elev")
    def test_symlink_refused_unix(self) -> None:
        """M-7 : les symlinks peuvent pointer ailleurs, refuse."""
        target = self.tmp / "real_dir"
        target.mkdir()
        link = self.tmp / "link"
        os.symlink(str(target), str(link))
        result = self.api.validate_dropped_path(str(link))
        self.assertFalse(result["ok"])
        self.assertIn("symboliques", result["message"].lower())

    def test_normal_unc_share_not_blocked(self) -> None:
        """Les UNC normaux \\\\server\\share NE sont PAS bloques par M-7
        (cas legitime NAS partage). Mais ils echoueront sur exists() en
        absence de network — on verifie juste que le check UNC special
        ne les rejette pas a tort."""
        # On ne peut pas tester un vrai \\server\share sans reseau, mais
        # on peut verifier qu'on ne tombe PAS sur le message "UNC special"
        result = self.api.validate_dropped_path("\\\\fakeserver\\share")
        self.assertFalse(result["ok"])
        self.assertNotIn("UNC special", result.get("message", ""))


if __name__ == "__main__":
    unittest.main()

"""V5bis-02 — Verifie library-v5.js porte (IIFE -> ES module + REST apiPost)."""

from __future__ import annotations

import unittest
from pathlib import Path


class LibraryV5PortedTests(unittest.TestCase):
    """Tests structurels du port library-v5.js (V5bis-02)."""

    @classmethod
    def setUpClass(cls):
        cls.src = Path("web/views/library-v5.js").read_text(encoding="utf-8")

    def test_es_module_export(self):
        """initLibrary est exporte comme fonction async."""
        self.assertIn("export async function initLibrary", self.src)

    def test_no_more_iife_global(self):
        """L'IIFE et l'expose global window.LibraryV5 sont supprimes."""
        self.assertNotIn("window.LibraryV5", self.src)

    def test_imports_helpers(self):
        """Le module importe depuis _v5_helpers.js."""
        self.assertIn('from "./_v5_helpers.js"', self.src)

    def test_no_pywebview_api(self):
        """Plus aucun appel direct a window.pywebview.api."""
        self.assertNotIn("window.pywebview.api", self.src)

    def test_apiPost_used(self):
        """apiPost est utilise pour get_library_filtered."""
        self.assertIn("apiPost", self.src)
        self.assertIn("get_library_filtered", self.src)

    def test_v2_04_allsettled(self):
        """V2-04 : Promise.allSettled est preserve (resilience playlists/library)."""
        self.assertIn("Promise.allSettled", self.src)

    def test_smart_playlists_crud(self):
        """V5A : CRUD smart playlists preserve."""
        self.assertIn("get_smart_playlists", self.src)
        self.assertIn("save_smart_playlist", self.src)
        self.assertIn("delete_smart_playlist", self.src)

    def test_v2_08_skeleton(self):
        """V2-08 : appel a renderSkeleton preserve pour le loading state."""
        self.assertIn("renderSkeleton", self.src)

    def test_view_mode_toggle_preserved(self):
        """Toggle table/grid preserve."""
        self.assertIn('data-view-mode="table"', self.src)
        self.assertIn('data-view-mode="grid"', self.src)

    def test_localstorage_persist(self):
        """3 cles localStorage preservees (viewMode/filters/sort)."""
        self.assertIn("cinesort.library.viewMode", self.src)
        self.assertIn("cinesort.library.filters", self.src)
        self.assertIn("cinesort.library.sort", self.src)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Verif totale 2026-07 : _detect_cloud_sync_folder compare par SEGMENT, pas
par sous-chaine (l'ancien `marker in path_str` matchait D:\\xbox -> "Box")."""

import unittest
from pathlib import Path

from cinesort.infra.db.sqlite_store import _detect_cloud_sync_folder


class DetectCloudSyncFolderTests(unittest.TestCase):
    def test_no_false_positive_substring(self):
        # Les faux positifs de l'ancienne detection par sous-chaine.
        for p in (r"D:\xbox\films\c.sqlite", r"D:\mega games\c.sqlite", r"D:\Boxing\c.sqlite"):
            self.assertIsNone(_detect_cloud_sync_folder(Path(p)), p)

    def test_onedrive_family_detected(self):
        for p in (
            r"C:\Users\x\OneDrive\c.sqlite",
            r"C:\Users\x\OneDrive - Personal\c.sqlite",
            r"C:\Users\x\OneDriveCommercial\c.sqlite",
        ):
            self.assertEqual(_detect_cloud_sync_folder(Path(p)), "OneDrive", p)

    def test_exact_segment_providers(self):
        self.assertEqual(_detect_cloud_sync_folder(Path(r"C:\a\Dropbox\c.sqlite")), "Dropbox")
        self.assertEqual(_detect_cloud_sync_folder(Path(r"D:\Box\c.sqlite")), "Box")
        self.assertEqual(_detect_cloud_sync_folder(Path(r"C:\a\Google Drive\c.sqlite")), "Google Drive")

    def test_normal_path_is_none(self):
        self.assertIsNone(_detect_cloud_sync_folder(Path(r"D:\Films\CineSort\data.sqlite")))


if __name__ == "__main__":
    unittest.main()

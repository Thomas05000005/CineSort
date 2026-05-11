"""V1-M10 (audit ID-J-001) — Backup auto settings.json + rotation 5.

Couvre : creation backup, skip si JSON invalide, rotation a 5, listing trie
recent-first, restauration, garde-fou path traversal.
"""

from __future__ import annotations

import shutil
import tempfile
import time
import unittest
from pathlib import Path

from cinesort.ui.api.settings_support import (
    DEFAULT_SETTINGS_BACKUP_COUNT,
    SETTINGS_BACKUP_PREFIX,
    _backup_settings_before_write,
    _rotate_settings_backups,
    list_settings_backups,
    restore_settings_backup,
    settings_path,
)


class SettingsBackupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_settings_backup_")
        self.state_dir = Path(self._tmp)
        self.settings = settings_path(self.state_dir)
        self.settings.write_text('{"key":"v1"}', encoding="utf-8")

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_backup_creates_file(self) -> None:
        backup = _backup_settings_before_write(self.settings)
        self.assertIsNotNone(backup)
        assert backup is not None  # narrow pour mypy/lecture
        self.assertTrue(backup.exists())
        self.assertEqual(backup.read_text(encoding="utf-8"), '{"key":"v1"}')
        self.assertTrue(backup.name.startswith("settings.json" + SETTINGS_BACKUP_PREFIX))

    def test_backup_returns_none_if_settings_absent(self) -> None:
        self.settings.unlink()
        backup = _backup_settings_before_write(self.settings)
        self.assertIsNone(backup)

    def test_backup_skipped_if_invalid_json(self) -> None:
        self.settings.write_text("not valid json {", encoding="utf-8")
        backup = _backup_settings_before_write(self.settings)
        self.assertIsNone(backup)

    def test_rotation_keeps_5(self) -> None:
        # Cree 7 backups successifs.
        for i in range(7):
            self.settings.write_text(f'{{"v":{i}}}', encoding="utf-8")
            _backup_settings_before_write(self.settings)
            time.sleep(0.01)  # garantir mtime distinct + timestamp HHMMSS unique
            _rotate_settings_backups(self.settings, keep=DEFAULT_SETTINGS_BACKUP_COUNT)
        backups = list(self.state_dir.glob("settings.json" + SETTINGS_BACKUP_PREFIX + "*"))
        self.assertEqual(len(backups), DEFAULT_SETTINGS_BACKUP_COUNT)

    def test_rotation_returns_deleted_count(self) -> None:
        for i in range(8):
            self.settings.write_text(f'{{"v":{i}}}', encoding="utf-8")
            _backup_settings_before_write(self.settings)
            time.sleep(0.01)
        deleted = _rotate_settings_backups(self.settings, keep=3)
        self.assertEqual(deleted, 5)

    def test_list_backups_sorted_recent_first(self) -> None:
        for i in range(3):
            self.settings.write_text(f'{{"v":{i}}}', encoding="utf-8")
            _backup_settings_before_write(self.settings)
            time.sleep(0.01)
        listed = list_settings_backups(self.state_dir)
        self.assertEqual(len(listed), 3)
        self.assertGreaterEqual(listed[0]["mtime"], listed[1]["mtime"])
        self.assertGreaterEqual(listed[1]["mtime"], listed[2]["mtime"])
        self.assertIn("name", listed[0])
        self.assertIn("size", listed[0])

    def test_restore_backup(self) -> None:
        self.settings.write_text('{"key":"v1"}', encoding="utf-8")
        backup = _backup_settings_before_write(self.settings)
        assert backup is not None
        self.settings.write_text('{"key":"v2"}', encoding="utf-8")
        ok = restore_settings_backup(self.state_dir, backup.name)
        self.assertTrue(ok)
        self.assertEqual(self.settings.read_text(encoding="utf-8"), '{"key":"v1"}')

    def test_restore_rejects_path_traversal(self) -> None:
        self.assertFalse(restore_settings_backup(self.state_dir, "../../etc/passwd"))
        self.assertFalse(restore_settings_backup(self.state_dir, "..\\windows\\system32\\config"))
        self.assertFalse(restore_settings_backup(self.state_dir, "settings.json.bak.../evil"))

    def test_restore_rejects_unknown_prefix(self) -> None:
        # Fichier sans le prefixe attendu -> refus.
        rogue = self.state_dir / "settings.json.attack"
        rogue.write_text('{"x":1}', encoding="utf-8")
        self.assertFalse(restore_settings_backup(self.state_dir, "settings.json.attack"))

    def test_restore_returns_false_if_backup_missing(self) -> None:
        self.assertFalse(restore_settings_backup(self.state_dir, "settings.json.bak.20990101-000000"))


if __name__ == "__main__":
    unittest.main()

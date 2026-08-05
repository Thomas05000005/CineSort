"""Tests du chemin REEL de `reset_support.reset_all_user_data` (route
`settings/reset_all_user_data`).

Contexte (ultra-audit 2026-08, finding N34) : l'endpoint est enregistre
inconditionnellement par le serveur REST, il supprime la base, `settings.json`
et `runs/`, et les SEULS tests qui le mentionnaient patchaient
`_reset_all_user_data_impl` EN ENTIER (tests/test_cinesort_api_facades.py:250).
Une mutation supprimant a la fois la porte de confirmation et le backup ZIP
laissait donc la CI verte.

Ces tests appellent la VRAIE fonction sur un `state_dir` temporaire peuple et
observent le SYSTEME DE FICHIERS, pas une preview : ils constatent des
suppressions reelles. Trois invariants sont couverts separement, pour qu'une
mutation d'une seule des trois defenses rougisse quand meme :

1. la porte de confirmation (texte strictement "RESET") ;
2. le backup ZIP cree AVANT toute suppression, et reellement lisible ;
3. la preservation de `logs/` (utile pour diagnostiquer un reset rate).
"""

from __future__ import annotations

import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, ".")

from cinesort.ui.api import reset_support


class _FakeApi:
    """Stub minimal : `reset_all_user_data` n'a besoin que du state_dir."""

    def __init__(self, state_dir: Path) -> None:
        self._state_dir = state_dir

    def _get_state_dir(self) -> str:
        return str(self._state_dir)


class ResetAllUserDataRealTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        # Le backup ZIP est ecrit dans le PARENT du state_dir : on isole donc
        # le state_dir dans un sous-dossier pour que le ZIP reste dans le tmp.
        self.parent = Path(self.tmp.name)
        self.state_dir = self.parent / "CineSort"
        self.state_dir.mkdir(parents=True)
        self.api = _FakeApi(self.state_dir)
        self._populate()

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _populate(self) -> None:
        (self.state_dir / "logs").mkdir()
        (self.state_dir / "logs" / "app.log").write_text("trace", encoding="utf-8")
        (self.state_dir / "runs").mkdir()
        (self.state_dir / "runs" / "r1.json").write_text('{"run": 1}', encoding="utf-8")
        (self.state_dir / "cinesort.db").write_bytes(b"SQLite format 3\x00CONTENU")
        (self.state_dir / "settings.json").write_text('{"root": "D:/Films"}', encoding="utf-8")

    def _snapshot(self) -> set:
        return {p.name for p in self.state_dir.iterdir()}

    def _zips_in_parent(self) -> list:
        return sorted(p for p in self.parent.iterdir() if p.suffix == ".zip")

    # -- 1) porte de confirmation ------------------------------------------

    def test_wrong_confirmation_tokens_delete_nothing(self) -> None:
        """Tout texte != 'RESET' doit laisser le disque STRICTEMENT intact."""
        before = self._snapshot()
        self.assertEqual(before, {"logs", "runs", "cinesort.db", "settings.json"})
        for token in ("", "CONFIRM", "reset", "Reset", " RESET", "RESET ", "RESETTT"):
            with self.subTest(token=token):
                out = reset_support.reset_all_user_data(self.api, token)
                self.assertFalse(out.get("ok"), out)
                self.assertIn("error", out)
                # Le systeme de fichiers n'a pas bouge : ni suppression, ni ZIP.
                self.assertEqual(self._snapshot(), before)
                self.assertEqual(self._zips_in_parent(), [])
                self.assertTrue((self.state_dir / "cinesort.db").exists())
                self.assertTrue((self.state_dir / "settings.json").exists())
                self.assertTrue((self.state_dir / "runs" / "r1.json").exists())

    def test_confirmation_is_not_a_substring_match(self) -> None:
        """Une phrase CONTENANT 'RESET' ne suffit pas a declencher."""
        out = reset_support.reset_all_user_data(self.api, "je veux RESET tout")
        self.assertFalse(out.get("ok"), out)
        self.assertTrue((self.state_dir / "cinesort.db").exists())
        self.assertEqual(self._zips_in_parent(), [])

    # -- 2) backup ZIP ------------------------------------------------------

    def test_backup_zip_written_and_readable_before_deletion(self) -> None:
        out = reset_support.reset_all_user_data(self.api, "RESET")
        self.assertTrue(out.get("ok"), out)

        backup = Path(str(out.get("backup_path") or ""))
        self.assertTrue(backup.exists(), f"Backup absent : {backup}")
        self.assertGreater(backup.stat().st_size, 0, "Backup vide")
        self.assertEqual(backup.suffix, ".zip")

        # Le ZIP est un vrai ZIP relisible et contient le CONTENU d'avant reset.
        with zipfile.ZipFile(backup) as zf:
            self.assertIsNone(zf.testzip(), "Archive corrompue")
            names = set(zf.namelist())
            self.assertIn("cinesort.db", names)
            self.assertIn("settings.json", names)
            self.assertIn("runs/r1.json", names)
            self.assertIn("logs/app.log", names)
            self.assertEqual(zf.read("cinesort.db"), b"SQLite format 3\x00CONTENU")
            self.assertEqual(zf.read("settings.json").decode("utf-8"), '{"root": "D:/Films"}')

    # -- 3) suppression reelle + preservation de logs/ ----------------------

    def test_user_data_really_deleted_and_logs_preserved(self) -> None:
        out = reset_support.reset_all_user_data(self.api, "RESET")
        self.assertTrue(out.get("ok"), out)

        # Suppression REELLE (pas une preview) : les fichiers ont disparu.
        self.assertFalse((self.state_dir / "cinesort.db").exists())
        self.assertFalse((self.state_dir / "settings.json").exists())
        self.assertFalse((self.state_dir / "runs").exists())

        # logs/ survit AVEC son contenu.
        self.assertTrue((self.state_dir / "logs" / "app.log").exists())
        self.assertEqual((self.state_dir / "logs" / "app.log").read_text(encoding="utf-8"), "trace")
        self.assertEqual(self._snapshot(), {"logs"})

        removed = set(out.get("removed") or [])
        self.assertEqual(removed, {"cinesort.db", "settings.json", "runs"})
        self.assertNotIn("logs", removed)

    def test_missing_state_dir_is_refused(self) -> None:
        api = _FakeApi(self.parent / "absent")
        out = reset_support.reset_all_user_data(api, "RESET")
        self.assertFalse(out.get("ok"), out)
        self.assertEqual(self._zips_in_parent(), [])


if __name__ == "__main__":
    unittest.main()

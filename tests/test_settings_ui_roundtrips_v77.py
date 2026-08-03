"""GATE AUDIT 2026-06-11 (R4-P9/P10/P11/P12) — round-trips settings UI repares.

Findings refute:P1 de la revue adversaire (meme pattern que R4-P1) :
- P9  collection_folder : la cle UI n'etait jamais renvoyee par le GET -> champ
  retombant sur le placeholder alors que la valeur etait persistee. La cle du
  champ devient la canonique collection_folder_name.
- P10 lowercase_extensions : CONSOMME par build_cfg_from_settings (defaut True)
  mais absent du GET -> toggle affichant OFF alors que l'effectif est ON.
  Ajoute a _LITERAL_DEFAULTS.
- P11 subtitle_expected_languages : hint UI "Separees par ;" mais split
  virgule seule -> "fr;en" persistait ['fr;en'] (warnings sous-titres faux).
- P12 file_extensions : split virgule (hint ';') ET aucun consommateur (le
  moteur lit video_exts que rien n'ecrivait) -> reglage fantome. Le save ecrit
  desormais video_exts (format '.ext'). NB : depuis le lot « perimetre
  destructif » du 2026-08-03, l'effet de video_exts est RESTRICTIF (l'union
  avec VIDEO_EXTS_ALL ne s'applique plus qu'en l'ABSENCE de saisie) — cf.
  tests/test_perimetre_destructif_20260803.py.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path

from cinesort.ui.api.cinesort_api import CineSortApi

_REPO_ROOT = Path(__file__).resolve().parent.parent
_PARAMETRES_JS = _REPO_ROOT / "web" / "dashboard" / "views" / "parametres.js"


class SettingsUiRoundtripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_ui_rt_")
        self._root = Path(self._tmp) / "root"
        self._sd = Path(self._tmp) / "state"
        self._root.mkdir()
        self._sd.mkdir()
        self.api = CineSortApi()
        self.api._state_dir = self._sd

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _save_full(self, **edits):
        full = self.api.settings.get_settings()
        full["root"] = str(self._root)
        full["state_dir"] = str(self._sd)
        full.update(edits)
        saved = self.api.settings.save_settings(full)
        self.assertTrue(saved.get("ok"), saved)
        return self.api.settings.get_settings()

    # --- P9 : collection_folder_name ---

    def test_collection_field_key_is_canonical(self) -> None:
        src = _PARAMETRES_JS.read_text(encoding="utf-8")
        m = re.search(r'key:\s*"(collection_folder[a-z_]*)"[^\n]*Nom du dossier collections', src)
        self.assertIsNotNone(m, "champ collections introuvable dans parametres.js")
        self.assertEqual(m.group(1), "collection_folder_name")

    def test_collection_folder_roundtrip_visible(self) -> None:
        after = self._save_full(collection_folder_name="_MesSagas")
        self.assertEqual(after.get("collection_folder_name"), "_MesSagas")
        self.assertIn("collection_folder_name", after, "round-trip affichage")

    # --- P10 : lowercase_extensions ---

    def test_lowercase_extensions_present_in_fresh_get(self) -> None:
        fresh = self.api.settings.get_settings()
        self.assertIn(
            "lowercase_extensions",
            fresh,
            "consomme par build_cfg (defaut True) : doit etre expose au GET, "
            "sinon le toggle UI affiche OFF alors que l'effectif est ON",
        )
        self.assertTrue(fresh.get("lowercase_extensions"))

    def test_lowercase_extensions_off_roundtrip(self) -> None:
        after = self._save_full(lowercase_extensions=False)
        self.assertFalse(after.get("lowercase_extensions"))

    # --- P11 : subtitle_expected_languages split ';' ---

    def test_expected_languages_semicolon_split(self) -> None:
        after = self._save_full(subtitle_expected_languages="fr;en")
        self.assertEqual(
            after.get("subtitle_expected_languages"),
            ["fr", "en"],
            "le hint UI dit 'Separees par ;' : fr;en ne doit PAS persister ['fr;en']",
        )

    def test_expected_languages_comma_still_works(self) -> None:
        after = self._save_full(subtitle_expected_languages="fr,en")
        self.assertEqual(after.get("subtitle_expected_languages"), ["fr", "en"])

    # --- P12 : file_extensions alimente video_exts ---

    def test_file_extensions_semicolon_and_feeds_video_exts(self) -> None:
        after = self._save_full(file_extensions=".mkv;.xyz")
        self.assertEqual(after.get("file_extensions"), ["mkv", "xyz"])
        self.assertIn(
            ".xyz",
            after.get("video_exts") or [],
            "file_extensions doit alimenter video_exts (la cle CONSOMMEE par le "
            "moteur de scan) — sinon le champ UI est un reglage fantome",
        )


if __name__ == "__main__":
    unittest.main()

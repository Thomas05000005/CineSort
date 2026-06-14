"""GATE AUDIT 2026-06-14 (R6-D) — affichage du comparateur de doublons.

- Nom de fichier "?" : les items de groupe exposent `source_folder` (pas
  `folder`) -> _filename_from_row retombait sur "?". Doit accepter source_folder.
- Taille en octets bruts dans la table criteres ("1610612736") -> doit etre
  lisible (Go/Mo).
"""

from __future__ import annotations

import re
import unittest

from cinesort.domain.duplicate_compare import compare_by_criteria
from cinesort.ui.api.run_flow_support import _filename_from_row


class ComparatorDisplayTests(unittest.TestCase):
    def test_filename_from_source_folder(self) -> None:
        # Item de groupe : ni 'video' ni 'folder', mais 'source_folder'.
        name = _filename_from_row({"source_folder": r"D:\Films\B\Inception (2010)", "row_id": "x"})
        self.assertEqual(name, "Inception (2010)")

    def test_filename_prefers_video(self) -> None:
        name = _filename_from_row({"video": "movie.mkv", "source_folder": r"D:\x\y"})
        self.assertEqual(name, "movie.mkv")

    def test_filename_unknown_when_empty(self) -> None:
        self.assertEqual(_filename_from_row({}), "?")

    def test_size_criterion_is_human_readable(self) -> None:
        # 3600s * 8 Mbps / 8 = 3.6e9 octets ~ 3.4 Go (estimation bitrate x duree).
        probe = {"duration_s": 3600, "video": {"bitrate": 8_000_000}}
        crits = compare_by_criteria(probe, probe)
        size_crit = next((c for c in crits if c.name == "file_size"), None)
        self.assertIsNotNone(size_crit, "critere file_size attendu")
        # Ne doit PAS etre une suite de chiffres bruts.
        self.assertFalse(re.fullmatch(r"\d+", size_crit.value_a or ""),
                         f"taille en octets bruts: {size_crit.value_a!r}")
        self.assertRegex(size_crit.value_a, r"(o|Ko|Mo|Go|To)$")


if __name__ == "__main__":
    unittest.main()

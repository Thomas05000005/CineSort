"""F22 — plan_conflict doit se juger sur des chemins NORMALISES (NTFS est
insensible a la casse), pas sur les chaines brutes.

Bug d'origine (revue post-merge 2026-07-18, F22) :
`cinesort.domain.duplicate_support.find_duplicate_targets` comparait
`len(set(plan_targets)) < len(plan_targets)` sur les chemins BRUTS, alors que
le groupement (movie_key) est insensible a la casse et que la ligne suivante
utilisait deja `norm_win_path` pour `target_norms`. Deux rows du meme groupe
visant '...\\SEVEN (1995)' et '...\\Seven (1995)' — le MEME dossier NTFS —
sortaient donc avec plan_conflict=False : faux negatif dans le filtre
« conflits » de l'ecran Doublons.

fail-before / pass-after : (a) plan_conflict False -> True.
NON-REGRESSION : (b) deux parents distincts -> plan_conflict reste False
(empeche de transformer le flag en constante True).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core


class DuplicatesPlanConflictNormcaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="dupes_normcase_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=False).normalized()

    def _row(self, row_id: str, folder: Path, title: str) -> core.PlanRow:
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "movie.mkv").write_bytes(b"data-" + row_id.encode("ascii"))
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title=title,
            proposed_year=1995,
            proposed_source="tmdb",
            confidence=90,
            confidence_label="high",
            candidates=[],
        )

    def _run(self, rows: list) -> dict:
        decisions = {r.row_id: {"ok": True, "title": r.proposed_title, "year": r.proposed_year} for r in rows}
        return plan_support.find_duplicate_targets(self._cfg(), rows, decisions)

    def test_case_divergent_titles_same_target_is_plan_conflict(self) -> None:
        rows = [
            self._row("r1", self.root / "Films" / "SEVEN.1995.1080p", "SEVEN"),
            self._row("r2", self.root / "Films" / "Se7en.1995.720p", "Seven"),
        ]

        data = self._run(rows)

        self.assertEqual(data["total_groups"], 1)
        self.assertTrue(
            bool(data["groups"][0]["plan_conflict"]),
            "'SEVEN (1995)' et 'Seven (1995)' dans le meme parent = le MEME dossier NTFS -> collision de destination.",
        )

    def test_distinct_parents_no_plan_conflict(self) -> None:
        # NON-REGRESSION : meme identite, cibles REELLEMENT differentes.
        rows = [
            self._row("r1", self.root / "A" / "SEVEN.1995.1080p", "SEVEN"),
            self._row("r2", self.root / "B" / "Se7en.1995.720p", "Seven"),
        ]

        data = self._run(rows)

        self.assertEqual(data["total_groups"], 1)
        self.assertFalse(
            bool(data["groups"][0]["plan_conflict"]),
            "Deux parents distincts -> pas de collision de destination.",
        )


if __name__ == "__main__":
    unittest.main()

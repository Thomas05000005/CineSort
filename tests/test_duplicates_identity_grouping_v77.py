"""GATE AUDIT 2026-06-14 (R6-A) — doublons groupes par IDENTITE (titre+annee).

Choix utilisateur "1 liste par identite" :
- deux films de meme identite (titre+annee) DOIVENT former un groupe meme si
  leurs dossiers de destination different (doublons cross-racine que l'ancienne
  condition `has_plan_dupe` ratait -> symptome "65 detectes / 5 affiches") ;
- les episodes TV (kind == "tv_episode") NE doivent PAS etre traites comme des
  doublons de film (ils partagent titre+annee mais sont des fichiers distincts).

Tests fail-before/pass-after :
- avant R6-A : cross-racine -> 0 groupe ; tv_episode -> 1 groupe (a tort).
- apres R6-A : cross-racine -> 1 groupe (scope cross_root) ; tv_episode -> 0.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core


class DuplicatesIdentityGroupingTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="dupes_identity_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True).normalized()

    def _single(self, row_id: str, folder: Path, title: str, year: int, source_root: str = "") -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title=title,
            proposed_year=year,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[],
            source_root=(source_root or None),
        )

    def _tv(self, row_id: str, folder: Path, title: str, year: int, ep: int) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind="tv_episode",
            folder=str(folder),
            video=f"S01E0{ep}.mkv",
            proposed_title=title,
            proposed_year=year,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[],
            tv_series_name=title,
            tv_season=1,
            tv_episode=ep,
        )

    def test_cross_root_same_identity_is_grouped(self) -> None:
        # Deux copies "Movie (2020)" dans deux racines distinctes -> destinations
        # differentes (root/A/... vs root/B/...) mais MEME identite.
        a = self.root / "A" / "Movie (2020)"
        b = self.root / "B" / "Movie (2020)"
        rows = [
            self._single("r1", a, "Movie", 2020, source_root=str(self.root / "A")),
            self._single("r2", b, "Movie", 2020, source_root=str(self.root / "B")),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Movie", "year": 2020},
            "r2": {"ok": True, "title": "Movie", "year": 2020},
        }
        data = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)
        self.assertEqual(data["total_groups"], 1, "Les copies cross-racine doivent former 1 groupe par identite.")
        grp = data["groups"][0]
        self.assertEqual(len(grp["rows"]), 2)
        self.assertEqual(grp.get("scope"), "cross_root", "Racines differentes -> portee cross_root.")

    def test_tv_episodes_not_grouped(self) -> None:
        # Deux episodes de la meme serie, meme dossier : pas un doublon de film.
        folder = self.root / "Show S01"
        rows = [
            self._tv("e1", folder, "Show", 2020, 1),
            self._tv("e2", folder, "Show", 2020, 2),
        ]
        decisions = {
            "e1": {"ok": True, "title": "Show", "year": 2020},
            "e2": {"ok": True, "title": "Show", "year": 2020},
        }
        data = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)
        self.assertEqual(data["total_groups"], 0, "Les episodes TV ne doivent pas etre detectes comme doublons.")


if __name__ == "__main__":
    unittest.main()

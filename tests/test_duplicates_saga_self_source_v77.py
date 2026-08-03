"""REGRESSION M8 (relecture B2) — un single-saga DEJA range sous sa source
conforme ne doit PAS se signaler LUI-MEME comme doublon au re-scan.

Contexte : depuis le fix M8, la cible planifiee d'un single dont TMDb expose une
saga (tmdb_collection_name) + enable_collection_folder est REDIRIGEE vers
    <root>/<_Collection>/<saga>/<Title (Year)>
qui DIVERGE du dossier SOURCE deja conforme (<root>/<Title (Year)>).

`existing_movie_folder_index` indexe ce dossier source (nom conforme). Comme
source_norm != aucun target_norm, `matched_target` restait False et la garde
`existing_norm not in target_norms` ajoutait la PROPRE source du film a
`existing_elsewhere` -> un groupe doublon a 1 item citant sa propre source.

fail-before/pass-after :
- avant le fix : total_groups == 1 (faux positif) ;
- apres le fix : total_groups == 0 (la source du film relocalise est exclue).

Le 2e test garde un VRAI doublon saga (2 copies meme identite) pour verifier
qu'on ne masque pas les vrais doublons (plan_conflict conserve).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core


class DuplicatesSagaSelfSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="dupes_saga_self_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True).normalized()

    def _single_saga(
        self,
        row_id: str,
        folder: Path,
        title: str,
        year: int,
        saga: str,
    ) -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title=title,
            proposed_year=year,
            proposed_source="tmdb",
            confidence=90,
            confidence_label="high",
            candidates=[],
            tmdb_collection_name=saga,
        )

    def _make_conform_folder(self, name: str) -> Path:
        folder = self.root / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "movie.mkv").write_bytes(b"data")
        return folder

    def test_single_saga_already_at_source_is_not_self_duplicate(self) -> None:
        # Le film est deja range et conforme a la racine : <root>/Alien (1979).
        # enable_collection_folder redirige sa cible vers _Collection/Alien
        # Collection/... -> divergence source vs target, mais AUCUN doublon reel.
        folder = self._make_conform_folder("Alien (1979)")
        rows = [self._single_saga("r1", folder, "Alien", 1979, "Alien Collection")]
        decisions = {"r1": {"ok": True, "title": "Alien", "year": 1979}}

        data = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)

        self.assertEqual(
            data["total_groups"],
            0,
            "Un single-saga deja range sous sa source conforme ne doit pas se "
            "signaler lui-meme comme doublon (regression M8).",
        )

    def test_two_real_saga_copies_still_detected(self) -> None:
        # DEUX copies distinctes de la meme identite saga -> vrai doublon.
        # Elles visent la MEME cible _Collection/Alien Collection/Alien (1979)
        # -> groupe emis + plan_conflict. Ne pas sur-corriger (masquer un vrai).
        a = self._make_conform_folder("Alien (1979)")
        b_parent = self.root / "Backups"
        b_parent.mkdir(parents=True, exist_ok=True)
        b = b_parent / "Alien (1979)"
        b.mkdir(parents=True, exist_ok=True)
        (b / "movie.mkv").write_bytes(b"data2")

        rows = [
            self._single_saga("r1", a, "Alien", 1979, "Alien Collection"),
            self._single_saga("r2", b, "Alien", 1979, "Alien Collection"),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Alien", "year": 1979},
            "r2": {"ok": True, "title": "Alien", "year": 1979},
        }

        data = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)

        self.assertEqual(
            data["total_groups"],
            1,
            "Deux vraies copies saga de meme identite doivent former 1 groupe.",
        )
        grp = data["groups"][0]
        self.assertEqual(len(grp["rows"]), 2)
        self.assertTrue(
            bool(grp.get("plan_conflict")),
            "Deux copies visant la meme cible _Collection -> plan_conflict.",
        )


if __name__ == "__main__":
    unittest.main()

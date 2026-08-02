"""F18 — existing_movie_folder_index doit indexer les films ranges SOUS le
dossier collections (profondeur 3 : <root>/_Collection/<saga>/<Titre (Annee)>).

Bug d'origine (revue post-merge 2026-07-18, F18) : la boucle de
`cinesort.domain.duplicate_support.existing_movie_folder_index` (a) skippait
tout dossier niveau-1 prefixe '_' — dont `collection_root_name` = '_Collection'
par defaut — et (b) n'indexait que 2 niveaux, alors que
`planned_target_folder` (miroir de apply_core.apply_single) vise
<root>/_Collection/<saga>/<nom> en profondeur 3. Consequence : une copie deja
rangee sous la saga etait invisible du detecteur de doublons ; la collision
n'emergeait qu'a l'apply (merge_dir_safe), silencieusement.

fail-before / pass-after :
 - (a) total_groups == 0 avant, 1 apres (existing_paths cite bien _Collection) ;
 - (b) mergeable_count == 0 avant, 1 apres (copies binairement identiques) ;
 - (c) NON-REGRESSION : les autres buckets '_' (_review/_duplicates_user_decided)
   ne doivent JAMAIS etre indexes -> total_groups == 0 avant ET apres.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core


class DuplicatesCollectionRootDepth3Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="dupes_coll_depth3_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    # -- helpers ---------------------------------------------------------

    def _cfg(self, **overrides) -> core.Config:
        base = {"root": self.root, "enable_collection_folder": True}
        base.update(overrides)
        return core.Config(**base).normalized()

    def _make_movie_dir(self, relative: str, payload: bytes) -> Path:
        folder = self.root / relative
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "movie.mkv").write_bytes(payload)
        return folder

    def _row(self, folder: Path) -> core.PlanRow:
        return core.PlanRow(
            row_id="r1",
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title="Avatar",
            proposed_year=2009,
            proposed_source="tmdb",
            confidence=90,
            confidence_label="high",
            candidates=[],
            tmdb_collection_name="Avatar Collection",
        )

    def _run(self, folder: Path, cfg: core.Config | None = None) -> dict:
        rows = [self._row(folder)]
        decisions = {"r1": {"ok": True, "title": "Avatar", "year": 2009}}
        return plan_support.find_duplicate_targets(cfg or self._cfg(), rows, decisions)

    # -- tests -----------------------------------------------------------

    def test_existing_copy_under_collection_root_is_detected(self) -> None:
        self._make_movie_dir("_Collection/Avatar Collection/Avatar (2009)", b"old-copy")
        new_folder = self._make_movie_dir("Downloads/Avatar (2009)", b"new-and-different")

        data = self._run(new_folder)

        self.assertEqual(
            data["total_groups"],
            1,
            "La copie deja rangee sous <root>/_Collection/<saga>/ doit etre vue "
            "comme un exemplaire existant (profondeur 3).",
        )
        existing_paths = data["groups"][0]["existing_paths"]
        self.assertTrue(existing_paths, "existing_paths ne doit pas etre vide")
        self.assertIn("_Collection", existing_paths[0])

    def test_identical_copy_under_collection_root_is_mergeable(self) -> None:
        self._make_movie_dir("_Collection/Avatar Collection/Avatar (2009)", b"same-bytes")
        new_folder = self._make_movie_dir("Downloads/Avatar (2009)", b"same-bytes")

        data = self._run(new_folder)

        self.assertEqual(
            data["mergeable_count"],
            1,
            "Deux copies binairement identiques vers la meme cible saga -> "
            "fusion sure signalee a l'utilisateur.",
        )

    def test_review_bucket_is_never_indexed(self) -> None:
        # NON-REGRESSION (garde anti-sur-correction) : _review contient de VRAIES
        # copies mises de cote par l'utilisateur ; les indexer creerait des
        # conflits fantomes. Vert AVANT et APRES le correctif.
        self._make_movie_dir("_review/_duplicates_user_decided/Avatar (2009)", b"parked")
        new_folder = self._make_movie_dir("Downloads/Avatar (2009)", b"new-and-different")

        data = self._run(new_folder)

        self.assertEqual(
            data["total_groups"],
            0,
            "Le bucket _review ne doit jamais alimenter l'index des dossiers existants.",
        )

    def test_collection_root_non_indexe_quand_la_fonctionnalite_est_desactivee(self) -> None:
        # F18 (revue R1) : la transparence du dossier collections ne vaut que si
        # la fonctionnalite est ACTIVE. Avec enable_collection_folder=False,
        # planned_target_folder ne vise JAMAIS <root>/_Collection/... (cf.
        # duplicate_support.planned_target_folder L164/L169) : _Collection
        # redevient un bucket interne, saute par le scan (scan_helpers.py:311,
        # skip inconditionnel) et contenant de vraies copies parquees.
        # L'indexer fabrique un conflit fantome — un groupe a UN SEUL row citant
        # une cible que rien ne planifie, sur lequel l'UI Doublons propose
        # pourtant un bouton « Garder A » qui ne deplacera rien (cf. F28).
        self._make_movie_dir("_Collection/Avatar Collection/Avatar (2009)", b"parked")
        new_folder = self._make_movie_dir("Downloads/Avatar (2009)", b"new-and-different")

        data = self._run(new_folder, cfg=self._cfg(enable_collection_folder=False))

        self.assertEqual(
            data["total_groups"],
            0,
            "Collections desactivees : <root>/_Collection est un bucket interne, "
            "aucune cible planifiee ne pointe dedans -> ne pas l'indexer.",
        )

    def test_dossier_niveau1_homonyme_sans_underscore_reste_indexe(self) -> None:
        # NON-REGRESSION / garde anti-sur-correction : quand collection_root_name
        # n'a PAS de prefixe '_' et que la fonctionnalite est desactivee, le
        # dossier est un dossier utilisateur ORDINAIRE — il doit continuer a etre
        # parcouru sur 2 niveaux comme n'importe quel dossier niveau-1.
        # VERT avant ET apres le correctif.
        self._make_movie_dir("Collections/Avatar (2009)", b"ordinary-folder")
        new_folder = self._make_movie_dir("Downloads/Avatar (2009)", b"new-and-different")

        data = self._run(
            new_folder,
            cfg=self._cfg(enable_collection_folder=False, collection_root_name="Collections"),
        )

        self.assertEqual(data["total_groups"], 1)
        self.assertIn("Collections", data["groups"][0]["existing_paths"][0])


if __name__ == "__main__":
    unittest.main()

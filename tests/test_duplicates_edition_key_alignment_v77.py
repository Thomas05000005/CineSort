"""AUDIT 2026-07-15 (H11) — asymetrie EDITION dans la detection de doublons.

Bug : la cle d'identite de groupement (find_duplicate_targets) incluait TOUJOURS
l'edition (`movie_key(..., edition=row.edition)`), alors que :
 - `existing_movie_folder_index` indexe les dossiers disque "Titre (Annee)" SANS
   edition (movie_dir_title_year ne parse que ce format) ;
 - avec le template de nommage par DEFAUT "{title} ({year})", le dossier PRODUIT
   par planned_target_folder ne contient PAS l'edition.

Consequences (template par defaut) :
 - la detection "cible deja existante" etait MORTE pour toute row avec edition
   detectee (la cle inception|2010|director's cut ne matchait jamais l'index
   inception|2010) ;
 - deux editions differentes du meme film visent le MEME dossier mais n'etaient
   plus vues comme un conflit (cles distinctes).

Fix : l'edition n'entre dans la cle QUE si le dossier reellement produit par le
template la porte (derive de la MEME chaine de rendu que planned_target_folder).

fail-before / pass-after :
 - test 1 & 2 : total_groups == 0 avant (detection morte), == 1 apres ;
 - test 3 & 4 (template AVEC {edition}) : garde de non-regression, la separation
   par edition et le conflit intra-edition restent corrects.

CONTRAINTE PRODUIT : le fix ne touche QUE l'identite/nommage de DOSSIER, jamais
le fichier video (row.video n'est ni lu ni ecrit ici).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core


class DuplicatesEditionKeyAlignmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="dupes_edition_")
        self.base = Path(self._tmp)
        self.root = self.base / "root"
        self.staging = self.base / "staging"
        self.root.mkdir(parents=True, exist_ok=True)
        self.staging.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self, template: str = "{title} ({year})") -> core.Config:
        return core.Config(root=self.root, naming_movie_template=template).normalized()

    def _single(
        self,
        row_id: str,
        folder: Path,
        title: str,
        year: int,
        edition: str | None,
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
            edition=edition,
        )

    def _mkfolder(self, parent: Path, name: str) -> Path:
        folder = parent / name
        folder.mkdir(parents=True, exist_ok=True)
        (folder / "movie.mkv").write_bytes(b"data")
        return folder

    # --- Template PAR DEFAUT (sans {edition}) : l'edition NE doit PAS scinder ---

    def test_default_template_existing_folder_detected_despite_edition(self) -> None:
        # Un exemplaire est deja range et conforme dans la bibliotheque.
        existing = self._mkfolder(self.root, "Inception (2010)")
        # Nouvelle row du MEME film, edition detectee, source AILLEURS (hors root).
        src = self._mkfolder(self.staging, "Inception.2010.1080p")
        rows = [self._single("r1", src, "Inception", 2010, "Director's Cut")]
        decisions = {"r1": {"ok": True, "title": "Inception", "year": 2010}}

        data = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)

        # AVANT le fix : cle inception|2010|director's cut != index inception|2010
        #   -> exemplaire existant invisible -> 0 groupe.
        # APRES : cle inception|2010 -> l'exemplaire existant est signale.
        self.assertEqual(
            data["total_groups"],
            1,
            "Template par defaut : l'exemplaire deja present doit etre detecte "
            "malgre l'edition (la cle ne doit pas inclure l'edition absente du dossier).",
        )
        existing_paths = [Path(p) for p in data["groups"][0]["existing_paths"]]
        self.assertIn(
            existing,
            existing_paths,
            "Le dossier bibliotheque existant doit figurer dans existing_paths.",
        )

    def test_default_template_two_editions_collide_as_conflict(self) -> None:
        # Deux editions differentes, memes title/year : avec le template par
        # defaut elles visent le MEME dossier -> vrai conflit de plan.
        src_a = self._mkfolder(self.staging, "Inception.DirectorsCut")
        src_b = self._mkfolder(self.staging, "Inception.Extended")
        rows = [
            self._single("r1", src_a, "Inception", 2010, "Director's Cut"),
            self._single("r2", src_b, "Inception", 2010, "Extended"),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Inception", "year": 2010},
            "r2": {"ok": True, "title": "Inception", "year": 2010},
        }

        data = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)

        # AVANT : deux cles distinctes -> 0 groupe, collision de dossier ignoree.
        # APRES : cle commune inception|2010 -> 1 groupe + plan_conflict.
        self.assertEqual(
            data["total_groups"],
            1,
            "Deux editions visant le meme dossier (template sans {edition}) doivent former un conflit.",
        )
        grp = data["groups"][0]
        self.assertEqual(len(grp["rows"]), 2)
        self.assertTrue(
            bool(grp.get("plan_conflict")),
            "Deux editions -> meme cible -> plan_conflict.",
        )

    # --- Template AVEC {edition} : les editions vont dans des dossiers SEPARES ---

    def test_edition_template_keeps_distinct_editions_separate(self) -> None:
        cfg = self._cfg("{title} ({year}) {edition}")
        src_a = self._mkfolder(self.staging, "Inception.DirectorsCut")
        src_b = self._mkfolder(self.staging, "Inception.Extended")
        rows = [
            self._single("r1", src_a, "Inception", 2010, "Director's Cut"),
            self._single("r2", src_b, "Inception", 2010, "Extended"),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Inception", "year": 2010},
            "r2": {"ok": True, "title": "Inception", "year": 2010},
        }

        data = plan_support.find_duplicate_targets(cfg, rows, decisions)

        # Le template encode l'edition -> dossiers SEPARES -> PAS un doublon.
        self.assertEqual(
            data["total_groups"],
            0,
            "Template avec {edition} : deux editions distinctes ne doivent pas etre fusionnees en doublon.",
        )

    def test_edition_template_same_edition_still_conflicts(self) -> None:
        cfg = self._cfg("{title} ({year}) {edition}")
        src_a = self._mkfolder(self.staging, "Inception.DC.1")
        src_b = self._mkfolder(self.staging, "Inception.DC.2")
        rows = [
            self._single("r1", src_a, "Inception", 2010, "Director's Cut"),
            self._single("r2", src_b, "Inception", 2010, "Director's Cut"),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Inception", "year": 2010},
            "r2": {"ok": True, "title": "Inception", "year": 2010},
        }

        data = plan_support.find_duplicate_targets(cfg, rows, decisions)

        # Meme edition -> meme dossier "Inception (2010) Director's Cut" -> conflit.
        self.assertEqual(
            data["total_groups"],
            1,
            "Template avec {edition} : deux fois la MEME edition -> conflit conserve.",
        )
        self.assertTrue(bool(data["groups"][0].get("plan_conflict")))


if __name__ == "__main__":
    unittest.main()

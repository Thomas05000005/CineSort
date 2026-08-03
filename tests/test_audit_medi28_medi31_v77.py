"""GATE AUDIT 2026-07-13 — MEDI-28 (cible planifiee != ecrite) + MEDI-31
(section Alertes de l'ecran Doublons morte).

MEDI-28 : planned_target_folder (cinesort/domain/duplicate_support.py) codait en
dur `Title (Year)` et, pour un single, `Path(row.folder).parent/nom` — ignorant
(a) le template de nommage + edition et (b) la redirection saga `_Collection`
qu'apply_core.apply_single applique REELLEMENT. Consequence : chemins 'target'
faux + `plan_conflict` FAUX NEGATIF (deux copies d'une saga visent la MEME cible
_Collection a l'apply mais des parents differents dans l'ecran). Le fix miroite
apply_single (template + saga).

MEDI-31 : le payload de check_duplicates ne serialisait pas `warning_flags` ->
doublons.js allFlags=[] -> la section Alertes n'affichait JAMAIS d'alerte. Le fix
serialise les flags RECONCILIES (les faux `subtitle_missing_<lang>` dont la langue
est presente cote row sont retires ; les autres flags conserves) SANS muter la row
partagee.

Tests fail-before / pass-after.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.domain import duplicate_support as dup


def _single(
    row_id: str,
    folder: Path,
    title: str,
    year: int,
    *,
    tmdb_collection_name: str | None = None,
    edition: str | None = None,
    warning_flags: list[str] | None = None,
    subtitle_languages: list[str] | None = None,
    source_root: str | None = None,
) -> core.PlanRow:
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
        tmdb_collection_name=tmdb_collection_name,
        edition=edition,
        warning_flags=list(warning_flags or []),
        subtitle_languages=list(subtitle_languages or []),
        source_root=source_root,
    )


class Medi28PlannedTargetFolderTests(unittest.TestCase):
    """planned_target_folder DOIT etre STRICTEMENT la cible qu'apply_single ecrira."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="medi28_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self, **kw) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True, **kw).normalized()

    def _planned(self, cfg: core.Config, row: core.PlanRow, title: str, year: int) -> Path:
        def _is_under(cfg_, folder):
            return dup.is_under_collection_root(cfg_, folder, norm_win_path=core._norm_win_path)

        return dup.planned_target_folder(
            cfg,
            row,
            title,
            year,
            is_under_collection_root=_is_under,
            windows_safe=core.windows_safe,
        )

    def test_single_saga_redirected_to_collection(self) -> None:
        # apply_single: tmdb_collection_name + enable_collection_folder ->
        # <root>/<_Collection>/<saga>/Title (Year). AVANT le fix : parent/Title (Year).
        cfg = self._cfg()
        src = self.root / "src" / "Alien 1979 REMUX"
        row = _single("r1", src, "Alien", 1979, tmdb_collection_name="Alien Collection")
        target = self._planned(cfg, row, "Alien", 1979)
        self.assertEqual(
            target,
            cfg.root / "_Collection" / "Alien Collection" / "Alien (1979)",
            "Un single d'une saga TMDb doit viser _Collection/<saga>/ comme apply_single.",
        )

    def test_single_custom_template_matches_apply(self) -> None:
        # Template custom -> planned_target_folder DOIT appliquer le template (comme
        # apply_single via format_movie_folder), pas le format code en dur.
        cfg = self._cfg(naming_movie_template="{title} - {year}")
        src = self.root / "src" / "Movie source"
        row = _single("r1", src, "Movie", 2020)
        target = self._planned(cfg, row, "Movie", 2020)
        self.assertEqual(
            target,
            Path(row.folder).parent / "Movie - 2020",
            "Le template custom doit etre applique (AVANT le fix : 'Movie (2020)').",
        )

    def test_single_year_zero_matches_apply(self) -> None:
        # year=0 (annee inconnue) : apply_single/format_movie_folder nettoie la
        # parenthese orpheline -> 'Ghost' (et non 'Ghost (0)').
        cfg = self._cfg()
        src = self.root / "src" / "Ghost"
        row = _single("r1", src, "Ghost", 0)
        target = self._planned(cfg, row, "Ghost", 0)
        self.assertEqual(target, Path(row.folder).parent / "Ghost")

    def test_saga_collision_makes_plan_conflict_true(self) -> None:
        # Deux copies d'une meme saga, parents differents. AVANT le fix : cibles
        # calculees = parentA/Alien (1979) vs parentB/Alien (1979) -> has_plan_dupe
        # False -> plan_conflict FAUX NEGATIF alors qu'a l'apply les DEUX visent la
        # MEME _Collection/Alien Collection/Alien (1979) (collision reelle).
        cfg = self._cfg()
        a = self.root / "A" / "Alien 1979 REMUX"
        b = self.root / "B" / "Alien 1979 BluRay"
        rows = [
            _single("r1", a, "Alien", 1979, tmdb_collection_name="Alien Collection"),
            _single("r2", b, "Alien", 1979, tmdb_collection_name="Alien Collection"),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Alien", "year": 1979},
            "r2": {"ok": True, "title": "Alien", "year": 1979},
        }
        data = plan_support.find_duplicate_targets(cfg, rows, decisions)
        self.assertEqual(data["total_groups"], 1)
        grp = data["groups"][0]
        self.assertTrue(
            grp["plan_conflict"],
            "Deux copies d'une saga visant la meme cible _Collection doivent lever "
            "plan_conflict (collision reelle a l'apply).",
        )


class Medi31DoublonsWarningFlagsTests(unittest.TestCase):
    """Le payload de check_duplicates DOIT porter warning_flags (RECONCILIES)."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="medi31_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True).normalized()

    def _two_flagged(self, flags: list[str], subs: list[str] | None = None):
        a = self.root / "A" / "Inception (2010)"
        b = self.root / "B" / "Inception (2010)"
        rows = [
            _single("r1", a, "Inception", 2010, warning_flags=flags, subtitle_languages=subs),
            _single("r2", b, "Inception", 2010),
        ]
        decisions = {
            "r1": {"ok": True, "title": "Inception", "year": 2010},
            "r2": {"ok": True, "title": "Inception", "year": 2010},
        }
        return rows, decisions

    def test_warning_flags_serialized_in_group_rows(self) -> None:
        # AVANT le fix : la cle 'warning_flags' est ABSENTE des items -> allFlags=[]
        # -> section Alertes toujours vide.
        rows, decisions = self._two_flagged(["integrity_header_invalid", "nfo_title_mismatch"])
        data = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)
        self.assertEqual(data["total_groups"], 1)
        items = data["groups"][0]["rows"]
        for it in items:
            self.assertIn("warning_flags", it, "Chaque item doit exposer warning_flags.")
        self.assertEqual(
            items[0]["warning_flags"],
            ["integrity_header_invalid", "nfo_title_mismatch"],
            "Les flags non-sous-titres doivent etre conserves a l'identique.",
        )
        self.assertEqual(items[1]["warning_flags"], [], "Row sans flag -> liste vide.")

    def test_warning_flags_reconciled_drops_false_subtitle_missing(self) -> None:
        # subtitle_missing_fr FAUX (la row connait deja une piste 'fr') -> retire ;
        # integrity_header_invalid conserve. Prouve RECONCILIES != bruts.
        rows, decisions = self._two_flagged(["subtitle_missing_fr", "integrity_header_invalid"], subs=["fr"])
        data = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)
        items = data["groups"][0]["rows"]
        self.assertEqual(
            items[0]["warning_flags"],
            ["integrity_header_invalid"],
            "Le subtitle_missing_fr perime (fr present) doit etre reconcilie/retire.",
        )

    def test_find_duplicate_targets_does_not_mutate_row_flags(self) -> None:
        # La row est PARTAGEE (endpoint de lecture) : la serialisation ne doit pas
        # muter row.warning_flags (cf. H12 / test_duplicates_no_row_mutation_v77).
        rows, decisions = self._two_flagged(["subtitle_missing_fr", "integrity_header_invalid"], subs=["fr"])
        before = list(rows[0].warning_flags)
        plan_support.find_duplicate_targets(self._cfg(), rows, decisions)
        self.assertEqual(
            rows[0].warning_flags,
            before,
            "warning_flags de la row partagee doit rester INCHANGE apres lecture.",
        )


if __name__ == "__main__":
    unittest.main()

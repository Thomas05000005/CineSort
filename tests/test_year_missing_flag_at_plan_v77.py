"""AUDIT 2026-07-13 (vague 2) — restauration DETERMINISTE de l'alerte
"Annee introuvable" (flag `year_missing`) au moment du PLAN.

Contexte : le fix H12 a retire la SEULE source du flag `year_missing` (une
mutation NON DETERMINISTE des warning_flags PARTAGES a la lecture de
check_duplicates, cf. duplicate_support). Depuis, l'alerte "Annee introuvable"
(web/dashboard/core/alert-labels.js, membre de _CONFLICT_FLAGS) etait MORTE :
plus jamais produite.

Fix : les builders de PlanRow (plan_support_replan._build_unresolved_row /
_build_resolved_row) posent `year_missing` quand la row n'a pas d'annee
UTILISABLE, avec une definition alignee A L'IDENTIQUE sur `has_year` de
run_read_support.is_auto_approvable_flags -> year_missing <=> NOT has_year.

Fail-before / pass-after :
- avant le fix : aucun builder ne pose `year_missing` (grep : aucune source en
  prod), donc une PlanRow SANS annee n'a pas le flag -> assertIn -> ECHEC.
- apres : le flag est pose (une seule fois) et persiste dans le dict serialise
  vers plan.jsonl (plan_row_to_jsonable via asdict).
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.domain.core as core
from cinesort.app.plan_support_core import plan_row_to_jsonable
from cinesort.app.plan_support_replan import _build_resolved_row, _build_unresolved_row
from cinesort.ui.api.run_read_support import _CONFLICT_FLAGS

# Forme minimale de nfo_state attendue par les builders (cf.
# plan_support_dedup._build_nfo_candidates).
_NFO_STATE = {
    "nfo_ok": False,
    "nfo_cov": 0.0,
    "nfo_seq": 0.0,
    "nfo_reject_reason": "",
    "year_delta_reject": False,
    "nfo_partial_match": False,
}


def _noop_log(_level: str, _msg: str) -> None:
    return None


class YearMissingFlagAtPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="year_missing_plan_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root).normalized()

    def _unresolved(self, name_year):
        folder = self.root / "Ghost Movie"
        return _build_unresolved_row(
            folder,
            Path("movie.mkv"),
            row_id="r1",
            kind="single",
            is_collection=False,
            folder_name="Ghost Movie",
            cands=[],
            nfo=None,
            nfo_path=None,
            nfo_state=dict(_NFO_STATE),
            name_year=name_year,
            name_year_reason="",
            remaster_hint=False,
            tmdb_used=False,
            title_ambiguous=False,
            detected_edition=None,
            log=_noop_log,
        )

    def _resolved(self, year):
        chosen = core.Candidate(title="The Matrix", year=year, source="tmdb", score=0.9)
        folder = self.root / "The Matrix"
        return _build_resolved_row(
            self._cfg(),
            folder,
            Path("movie.mkv"),
            chosen,
            row_id="r2",
            kind="single",
            is_collection=False,
            folder_name="The Matrix",
            cands=[chosen],
            nfo=None,
            nfo_path=None,
            nfo_state=dict(_NFO_STATE),
            name_year=year,
            name_year_reason="folder",
            remaster_hint=False,
            tmdb_used=True,
            title_ambiguous=False,
            detected_edition=None,
            tmdb=None,
            log=_noop_log,
        )

    # ---- (a) row SANS annee -> flag pose, une seule fois, persiste -----------
    def test_unresolved_without_year_gets_year_missing(self) -> None:
        row = self._unresolved(name_year=None)  # proposed_year = 0 -> annee inutilisable
        self.assertEqual(row.proposed_year, 0)
        self.assertIn(
            "year_missing",
            row.warning_flags,
            "une PlanRow sans annee utilisable doit porter l'alerte 'year_missing'.",
        )
        # (a) ecrit UNE SEULE fois (pas de doublon).
        self.assertEqual(
            row.warning_flags.count("year_missing"),
            1,
            "'year_missing' ne doit apparaitre qu'une seule fois.",
        )
        # persiste dans plan.jsonl (dict serialise via asdict).
        payload = plan_row_to_jsonable(row)
        self.assertIn("year_missing", payload["warning_flags"])
        # coherence : year_missing est bien un flag de conflit (bloque l'auto-appro).
        self.assertIn("year_missing", _CONFLICT_FLAGS)

    # ---- (b) row AVEC annee valide -> pas de flag ---------------------------
    def test_unresolved_with_year_has_no_year_missing(self) -> None:
        row = self._unresolved(name_year=2001)  # proposed_year = 2001 -> utilisable
        self.assertEqual(row.proposed_year, 2001)
        self.assertNotIn(
            "year_missing",
            row.warning_flags,
            "une PlanRow avec annee valide ne doit PAS recevoir 'year_missing'.",
        )
        self.assertNotIn("year_missing", plan_row_to_jsonable(row)["warning_flags"])

    def test_resolved_with_year_has_no_year_missing(self) -> None:
        row = self._resolved(year=1999)
        self.assertEqual(row.proposed_year, 1999)
        self.assertNotIn(
            "year_missing",
            row.warning_flags,
            "un candidat resolu avec annee >= 1900 ne doit PAS recevoir 'year_missing'.",
        )
        self.assertNotIn("year_missing", plan_row_to_jsonable(row)["warning_flags"])

    # ---- alignement EXACT sur has_year (run_read_support) --------------------
    def test_definition_mirrors_has_year(self) -> None:
        from cinesort.app.plan_support_core import _apply_year_missing_flag, _has_usable_year
        from cinesort.ui.api.run_read_support import is_auto_approvable_flags

        for py in (None, 0, "", 1899, 1900, 1994, 2100):
            with self.subTest(proposed_year=py):
                # has_year tel qu'il gouverne l'auto-approbation.
                has_year = is_auto_approvable_flags(
                    flags=set(),
                    confidence=100,
                    proposed_title="Titre",
                    proposed_year=py,
                    threshold=0,
                )
                # year_missing <=> NOT has_year (meme frontiere : >= 1900).
                self.assertEqual(_has_usable_year(py), has_year)
                flags: list[str] = []
                _apply_year_missing_flag(flags, py)
                self.assertEqual(("year_missing" in flags), not has_year)

    def test_apply_is_idempotent(self) -> None:
        from cinesort.app.plan_support_core import _apply_year_missing_flag

        flags: list[str] = []
        _apply_year_missing_flag(flags, 0)
        _apply_year_missing_flag(flags, 0)
        self.assertEqual(flags.count("year_missing"), 1)


if __name__ == "__main__":
    unittest.main()

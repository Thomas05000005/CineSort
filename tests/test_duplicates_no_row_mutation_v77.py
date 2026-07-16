"""GATE AUDIT 2026-07-13 (H12) — check_duplicates ne mute pas les PlanRow.

find_duplicate_targets alimente l'endpoint de LECTURE run/check_duplicates. Les
PlanRow qu'il recoit sont PARTAGES (run_flow_support : `rows = rs.rows`, la meme
liste memoire que get_plan / get_dashboard). L'ancien code faisait
`row.warning_flags.append("year_missing")` sur ces objets partages -> un simple
appel de lecture polluait durablement warning_flags, gonflant le KPI 'Conflits'
(_CONFLICT_FLAGS contient 'year_missing') et faisant basculer
is_auto_approvable_flags, selon l'ordre de visite des ecrans.

Tests fail-before/pass-after :
- avant H12 : le 1er appel ajoute 'year_missing' a row.warning_flags -> assert
  d'absence -> ECHEC.
- apres H12 : warning_flags reste inchange, meme apres 2 appels consecutifs ; la
  decision de doublon (regroupement par titre seul, year=0) reste correcte.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.ui.api.run_read_support import _CONFLICT_FLAGS


class DuplicatesNoRowMutationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="dupes_no_mut_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _cfg(self) -> core.Config:
        return core.Config(root=self.root, enable_collection_folder=True).normalized()

    def _single_no_year(self, row_id: str, folder: Path, title: str) -> core.PlanRow:
        # proposed_year=0 -> annee hors 1900..2100 -> branche "year invalide".
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title=title,
            proposed_year=0,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[],
        )

    def test_check_duplicates_never_mutates_warning_flags(self) -> None:
        # Deux copies du meme film SANS annee exploitable (year=0).
        a = self.root / "A" / "Ghost Movie"
        b = self.root / "B" / "Ghost Movie"
        rows = [
            self._single_no_year("r1", a, "Ghost Movie"),
            self._single_no_year("r2", b, "Ghost Movie"),
        ]
        # decisions ok=True SANS year -> fallback sur proposed_year=0 -> invalide.
        decisions = {
            "r1": {"ok": True, "title": "Ghost Movie"},
            "r2": {"ok": True, "title": "Ghost Movie"},
        }

        # warning_flags vierges avant lecture.
        for row in rows:
            self.assertEqual(row.warning_flags, [])

        # DEUX appels consecutifs de l'endpoint de lecture.
        data1 = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)
        data2 = plan_support.find_duplicate_targets(self._cfg(), rows, decisions)

        # (1) L'objet PARTAGE n'est jamais mute : 'year_missing' n'apparait pas,
        #     et le KPI Conflits (via _CONFLICT_FLAGS) reste stable a 0.
        for row in rows:
            self.assertNotIn(
                "year_missing",
                row.warning_flags,
                "check_duplicates ne doit PAS injecter 'year_missing' dans les "
                "warning_flags partages (pollution KPI Conflits).",
            )
            self.assertEqual(
                row.warning_flags, [], "warning_flags doit rester inchange."
            )
            self.assertEqual(
                set(row.warning_flags) & set(_CONFLICT_FLAGS),
                set(),
                "aucun flag de conflit ne doit etre ajoute par un endpoint de lecture.",
            )

        # (2) La decision de doublon reste correcte : year=0 -> regroupement par
        #     titre seul -> 1 groupe d'identite (le comportement metier survit au
        #     retrait de la mutation).
        self.assertEqual(
            data1["total_groups"], 1, "les 2 copies sans annee doivent former 1 groupe."
        )
        self.assertEqual(
            data2["total_groups"],
            data1["total_groups"],
            "le resultat doit etre stable/idempotent entre deux lectures.",
        )


if __name__ == "__main__":
    unittest.main()

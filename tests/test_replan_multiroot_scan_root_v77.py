"""GATE AUDIT 2026-06-11 (R4-P4) — le replan choisit le root qui CONTIENT le film.

Regression R3e/3 (d4a4ded) confirmee par la verification totale (NB-REPLAN-1) :
runs.root ne stocke que roots[0] (run_flow_support 'root principal pour
compat'). En scan MULTI-ROOTS, le caller replan passait roots[0] comme
library_root pour TOUS les films : pour un film pose directement a la racine
d'un root SECONDAIRE R2, _folder_is_root devenait False (R2 != R1) ->
folder_name = nom du dossier R2 (ex 'SecondRoot') au lieu du stem video utilise
au scan -> titre/match faux au re-match TMDb.

Fix : _resolve_scan_root_for_replan choisit parmi runs.root + config_json.roots
le candidat qui est folder_path lui-meme ou un de ses ancetres ; aucun -> None
(compat pre-R3e : cfg.root==folder -> stem, correct).
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

import cinesort.domain.core as core
from cinesort.app.plan_support_replan import replan_single_row
from cinesort.ui.api.library_actions_support import _resolve_scan_root_for_replan


class _FakeApi:
    def __init__(self, root: str, config: dict) -> None:
        self._row = {"root": root, "config_json": json.dumps(config)}

    def _find_run_row(self, run_id: str):
        return (self._row, SimpleNamespace())


class ResolveScanRootTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_multiroot_")
        self.r1 = Path(self._tmp) / "FirstRoot"
        self.r2 = Path(self._tmp) / "SecondRoot"
        self.r1.mkdir(parents=True)
        self.r2.mkdir(parents=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _api(self) -> _FakeApi:
        return _FakeApi(str(self.r1), {"roots": [str(self.r1), str(self.r2)]})

    def test_film_at_secondary_root_resolves_to_r2(self) -> None:
        """Coeur de NB-REPLAN-1 : folder = R2 (film a la racine du root
        secondaire) doit resoudre R2, PAS roots[0]=R1."""
        got = _resolve_scan_root_for_replan(self._api(), "run1", self.r2)
        self.assertIsNotNone(got)
        self.assertEqual(Path(got).resolve(), self.r2.resolve())

    def test_film_in_secondary_root_subfolder_resolves_to_r2(self) -> None:
        sub = self.r2 / "Movie (2010)"
        sub.mkdir()
        got = _resolve_scan_root_for_replan(self._api(), "run1", sub)
        self.assertIsNotNone(got)
        self.assertEqual(Path(got).resolve(), self.r2.resolve())

    def test_film_in_primary_root_resolves_to_r1(self) -> None:
        sub = self.r1 / "Movie (2010)"
        sub.mkdir()
        got = _resolve_scan_root_for_replan(self._api(), "run1", sub)
        self.assertEqual(Path(got).resolve(), self.r1.resolve())

    def test_unrelated_folder_resolves_none(self) -> None:
        other = Path(self._tmp) / "Elsewhere"
        other.mkdir()
        self.assertIsNone(_resolve_scan_root_for_replan(self._api(), "run1", other))

    def test_single_root_compat_runs_root_only(self) -> None:
        api = _FakeApi(str(self.r1), {"root": str(self.r1)})
        sub = self.r1 / "Movie (2010)"
        sub.mkdir()
        got = _resolve_scan_root_for_replan(api, "run1", sub)
        self.assertEqual(Path(got).resolve(), self.r1.resolve())

    def test_missing_run_resolves_none(self) -> None:
        class _NoRun:
            def _find_run_row(self, run_id):
                return None

        self.assertIsNone(_resolve_scan_root_for_replan(_NoRun(), "runX", self.r1))


class ReplanEffectMultiRootTests(unittest.TestCase):
    """Effet bout-en-bout : le film a la racine du root secondaire garde son stem."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_multiroot_e2e_")
        self.r1 = Path(self._tmp) / "FirstRoot"
        self.r2 = Path(self._tmp) / "SecondRoot"
        self.r1.mkdir(parents=True)
        self.r2.mkdir(parents=True)
        self.video = self.r2 / "Inception 2010.mkv"
        self.video.write_bytes(b"x" * 4096)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_replan_with_resolved_root_keeps_stem(self) -> None:
        api = _FakeApi(str(self.r1), {"roots": [str(self.r1), str(self.r2)]})
        scan_root = _resolve_scan_root_for_replan(api, "run1", self.r2)
        # Caller reel : cfg.root = folder (dossier du film) = R2 ici.
        cfg = core.Config(root=self.r2, enable_tmdb=False)
        row = replan_single_row(
            cfg, self.r2, self.video, kind="single", library_root=scan_root
        )
        self.assertIsNotNone(row)
        # folder == root resolu -> _folder_is_root True -> stem ('Inception 2010'),
        # PAS le nom du dossier racine ('SecondRoot') comme avec roots[0]=R1.
        self.assertEqual(int(row.detected_year), 2010)
        self.assertNotIn("SecondRoot", str(row.proposed_title))

    def test_replan_with_stale_primary_root_shows_old_bug(self) -> None:
        """Documente le bug d'origine : avec roots[0]=R1 force (l'ancien caller),
        le titre herite du nom du dossier racine secondaire."""
        cfg = core.Config(root=self.r2, enable_tmdb=False)
        row = replan_single_row(
            cfg, self.r2, self.video, kind="single", library_root=self.r1
        )
        self.assertIsNotNone(row)
        # folder_name = 'SecondRoot' (nom du dossier racine) contamine le titre
        # propose ; l'annee reste extraite du nom de FICHIER (infer_name_year
        # lit aussi video.name), c'est bien le titre qui trahit le bug.
        self.assertIn(
            "SecondRoot",
            str(row.proposed_title),
            "library_root etranger (R1) : le titre doit refleter le bug "
            "d'origine (folder_name = nom du dossier racine secondaire)",
        )


if __name__ == "__main__":
    unittest.main()

"""Issue #805 — l'overlay TMDb de l'apply ne fabrique aucun attribut fantome.

`_execute_apply` recopiait l'override manuel sur la PlanRow avec, en tete de
boucle, `_r.tmdb_id = int(_ov["tmdb_id"])`. `PlanRow` est un dataclass SANS
champ `tmdb_id` et sans `__slots__` : Python acceptait l'affectation en creant
un attribut d'instance que plus personne ne relit — `apply_core` ne contient pas
une seule occurrence de `tmdb_id`, et les lecteurs existants visent `Candidate`.

Le motif est le meme que celui du MagicMock qui invente l'attribut absent : rien
ne casse, rien ne previent, et le code laisse croire pendant des mois que
l'identite choisie a la main voyage jusqu'au renommage.

Ce fichier verrouille l'invariant a la source : apres un passage REEL dans
`_execute_apply` avec un override en base, les rows transmises a l'apply ne
portent QUE les champs declares du dataclass. La verification est generique — un
futur `_r.nimporte_quoi = ...` sur ce chemin la fait echouer aussi.

Deux precautions, sans lesquelles ce fichier ne prouverait rien :

- le store est un stub ECRIT A LA MAIN, pas un `MagicMock`. Un MagicMock rend un
  objet pour `store.film_modal.get_tmdb_override(...)`, donc `if not _ov` serait
  faux et l'overlay tournerait sur un override fantoche : le test passerait meme
  si la lecture reelle etait cassee ;
- le test assert AUSSI que le titre et l'annee ont bien ete overlayes. Sans
  cette assertion, une boucle d'overlay entierement supprimee laisserait
  l'absence d'attribut fantome... trivialement vraie. C'est la difference entre
  un invariant tenu et un chemin jamais emprunte.
"""

from __future__ import annotations

import dataclasses
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

import cinesort.domain.core as core
from cinesort.infra import state
from cinesort.ui.api import apply_support, library_actions_support

RUN_ID = "r_805_overlay"
ROW_ID = "row-blade-runner"


class _StubDuplicateRepo:
    def list_duplicate_decisions(self, *, run_id: str) -> List[Dict[str, Any]]:
        return []


class _StubFilmModalRepo:
    """Repo film_modal minimal : rend l'override UNIQUEMENT pour `ROW_ID`.

    Le `run_id` recu est memorise : un overlay qui interrogerait la table avec
    un autre run passerait a cote de l'override en production sans qu'aucune
    assertion sur la row ne le signale.
    """

    def __init__(self, override: Optional[Dict[str, Any]]) -> None:
        self._override = override
        self.seen: List[tuple] = []

    def get_tmdb_override(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        self.seen.append((run_id, row_id))
        if row_id != ROW_ID:
            return None
        return dict(self._override) if self._override else None

    def list_marked_for_deletion(self, *, run_id: str) -> List[Dict[str, Any]]:
        return []


class _StubStore:
    def __init__(self, override: Optional[Dict[str, Any]]) -> None:
        self.apply = _StubDuplicateRepo()
        self.film_modal = _StubFilmModalRepo(override)


def _run_paths(state_dir: Path) -> state.RunPaths:
    run_dir = state_dir / "runs" / f"tri_films_{RUN_ID}"
    run_dir.mkdir(parents=True, exist_ok=True)
    return state.RunPaths(
        run_id=RUN_ID,
        run_dir=run_dir,
        plan_jsonl=run_dir / "plan.jsonl",
        ui_log_txt=run_dir / "ui_log.txt",
        summary_txt=run_dir / "summary.txt",
        validation_json=run_dir / "validation.json",
    )


def _row(row_id: str) -> core.PlanRow:
    return core.PlanRow(
        row_id=row_id,
        kind="single",
        folder="",
        video="movie.mkv",
        proposed_title="Blade Runner",
        proposed_year=1982,
        proposed_source="name",
        confidence=42,
        confidence_label="low",
        candidates=[],
    )


class ApplyOverlayTmdbNoPhantomAttrTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_805_"))
        self.addCleanup(self._cleanup)

    def _cleanup(self) -> None:
        import shutil

        shutil.rmtree(self._tmp, ignore_errors=True)

    def _execute(self, override: Optional[Dict[str, Any]]) -> List[core.PlanRow]:
        """Passe REELLEMENT par `_execute_apply` et rend les rows vues par l'apply."""
        captured: List[core.PlanRow] = []

        def _fake_apply_rows(cfg_arg: Any, rows_arg: Any, decisions_arg: Any, **kwargs: Any) -> Any:
            captured.extend(list(rows_arg))
            res = core.ApplyResult()
            res.total_rows = len(list(rows_arg))
            return res

        cfg = core.Config(root=str(self._tmp / "films"))
        rows = [_row(ROW_ID)]
        store = _StubStore(override)
        with (
            patch.object(apply_support, "_apply_rows_fn", side_effect=_fake_apply_rows),
            patch.object(apply_support._plan_support_mod, "find_duplicate_targets", return_value=None),
            patch.object(library_actions_support, "migrate_legacy_deletion_marks", return_value=[]),
        ):
            apply_support._execute_apply(
                cfg,
                rows,
                {},
                None,
                dry_run=True,
                quarantine_unapproved=False,
                log_fn=lambda _lvl, _msg: None,
                run_paths=_run_paths(self._tmp / "state"),
                store=store,
                api=SimpleNamespace(_app_version="test"),
                run_id=RUN_ID,
                batch_state=[None, 0],
            )
        self.assertTrue(captured, "l'apply n'a recu aucune row : le harnais ne prouve rien")
        self.assertIn(
            (RUN_ID, ROW_ID),
            store.film_modal.seen,
            "la table film_tmdb_overrides n'a pas ete interrogee pour ce (run_id, row_id) : "
            "l'overlay n'a pas ete emprunte, le reste du test serait vide de sens",
        )
        return captured

    def test_overlay_applique_titre_et_annee_sans_creer_d_attribut_hors_dataclass(self) -> None:
        override = {
            "tmdb_id": 78,
            "proposed_title": "Blade Runner 2049",
            "proposed_year": 2017,
        }
        rows = self._execute(override)
        row = rows[0]

        # 1. Le chemin est bien emprunte (sinon l'assertion 2 serait triviale).
        self.assertEqual(row.proposed_title, "Blade Runner 2049", "l'overlay du titre n'a pas eu lieu")
        self.assertEqual(row.proposed_year, 2017, "l'overlay de l'annee n'a pas eu lieu")

        # 2. Aucun attribut hors des champs declares du dataclass.
        declared = {f.name for f in dataclasses.fields(core.PlanRow)}
        phantom = sorted(set(vars(row)) - declared)
        self.assertEqual(
            phantom,
            [],
            "l'apply a pose sur la PlanRow un ou plusieurs attributs absents du "
            f"dataclass ({phantom}) : ils ne sont relus par personne "
            "(`dataclasses.asdict` les ignore aussi a la serialisation du plan) "
            "et font croire a une donnee propagee jusqu'au renommage",
        )

    def test_sans_override_la_row_reste_intacte(self) -> None:
        """Contre-test : sans override, ni overlay ni attribut ajoute."""
        rows = self._execute(None)
        row = rows[0]

        self.assertEqual(row.proposed_title, "Blade Runner", "une row sans override a ete modifiee")
        self.assertEqual(row.proposed_year, 1982)
        declared = {f.name for f in dataclasses.fields(core.PlanRow)}
        self.assertEqual(sorted(set(vars(row)) - declared), [])


if __name__ == "__main__":
    unittest.main()

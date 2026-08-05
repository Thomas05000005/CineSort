r"""REVUE 2026-08-03 — la pre-passe collection ne doit JAMAIS toucher a la racine.

Les films poses en vrac DIRECTEMENT a la racine produisent des rows
kind='collection' dont `folder` est la racine elle-meme (plan_support_core,
flag 'root_level_source' + avertissement produit "Racine en vrac : N films a la
racine seront ranges..."). Avec `enable_collection_folder` (actif PAR DEFAUT),
la pre-passe d'apply_rows tentait de deplacer cette racine sous
`<root>/<_Collection>/<nom de la racine>` — la cible etant un DESCENDANT de la
source. Les deux issues etaient cassees :

  * cible absente  -> move_collection_folder -> shutil.Error "Cannot move a
    directory into itself" : apply bloque a l'identique a chaque relance, un
    dossier `_Collection` VIDE reste a la racine, films jamais ranges ;
  * cible deja presente -> merge_dir_safe deplacait la racine ENTIERE fichier
    par fichier : `root.exists()` devenait False et TOUTES les videos (y
    compris des films etrangers a la racine) partaient dans
    `_review/_leftovers/...`, avec un apply retournant errors=0 (succes vert).

Le GATE existant (tests/test_apply_preview_root_film_v77.py) ne teste QUE la
preview : ces tests-ci exercent l'APPLY REEL (facade de prod + apply_rows).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.app.apply_core as apply_core
import cinesort.domain.core as core
import cinesort.domain.duplicate_support as dup
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import cleanup_test_tree
from tests._helpers import wait_run_done as _wait_done


def _collection_row(row_id: str, folder: Path, video: str, title: str, year: int) -> core.PlanRow:
    return core.PlanRow(
        row_id=row_id,
        kind="collection",
        folder=str(folder),
        video=video,
        proposed_title=title,
        proposed_year=year,
        proposed_source="name",
        confidence=70,
        confidence_label="med",
        candidates=[core.Candidate(title=title, year=year, source="name", score=0.7)],
        collection_name=folder.name,
    )


class RootFilmsRealApplyTests(unittest.TestCase):
    """APPLY REEL de bout en bout via la facade de prod, config par defaut."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_root_apply_")
        self.root = Path(self._tmp) / "Films"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        patcher = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def test_real_apply_sorts_root_films_and_never_moves_the_root(self) -> None:
        (self.root / "Inception 2010.mkv").write_bytes(b"x" * 4096)
        (self.root / "Matrix 1999.mkv").write_bytes(b"y" * 4096)

        api = CineSortApi()
        start = api.run.start_plan({"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False})
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        _wait_done(api, run_id)
        rows = api.run.get_plan(run_id).get("rows", [])
        self.assertEqual(len(rows), 2, rows)
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title"), "year": r.get("proposed_year")} for r in rows
        }

        # APPLY REEL (dry_run=False) : c'est lui que la preview ne couvrait pas.
        payload = api.run.apply(run_id, decisions, False, False)
        result = payload.get("result") or {}

        self.assertEqual(int(result.get("errors") or 0), 0, result.get("error_messages"))
        self.assertEqual(int(result.get("skipped") or 0), 0, result.get("skipped_reasons"))
        self.assertGreaterEqual(int(result.get("moves") or 0), 2, result)
        # La racine ne bouge pas et n'est pas rangee sous elle-meme.
        self.assertTrue(self.root.exists(), "la racine de la bibliotheque a disparu")
        self.assertFalse(
            (self.root / "_Collection").exists(),
            "aucun dossier _Collection ne doit etre cree pour des films de la racine",
        )
        # Films ranges sur place, NOM DE FICHIER VIDEO INCHANGE (regle inviolable).
        self.assertTrue((self.root / "Inception (2010)" / "Inception 2010.mkv").is_file())
        self.assertTrue((self.root / "Matrix (1999)" / "Matrix 1999.mkv").is_file())

    def test_second_real_apply_is_not_permanently_blocked(self) -> None:
        """Le defaut d'origine se re-jouait a l'identique a chaque relance."""
        (self.root / "Inception 2010.mkv").write_bytes(b"x" * 4096)

        api = CineSortApi()
        start = api.run.start_plan({"root": str(self.root), "state_dir": str(self.state_dir), "tmdb_enabled": False})
        run_id = str(start["run_id"])
        _wait_done(api, run_id)
        rows = api.run.get_plan(run_id).get("rows", [])
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title"), "year": r.get("proposed_year")} for r in rows
        }
        first = api.run.apply(run_id, decisions, False, False).get("result") or {}
        self.assertEqual(int(first.get("errors") or 0), 0, first.get("error_messages"))
        self.assertTrue((self.root / "Inception (2010)" / "Inception 2010.mkv").is_file())


class MoveCollectionFolderRootGuardTests(unittest.TestCase):
    """Garde LOCALE de move_collection_folder (derniere ligne de defense).

    Le predicat `is_under_collection_root` est neutralise dans ces tests pour
    exercer la garde de move_collection_folder elle-meme, et elle seule.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_movecoll_")
        self.root = Path(self._tmp) / "Films"
        self.root.mkdir(parents=True, exist_ok=True)
        self.logs: list[tuple[str, str]] = []

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _cfg(self) -> core.Config:
        return core.Config(
            root=self.root, enable_collection_folder=True, collection_root_name="_Collection"
        ).normalized()

    def test_refuses_to_move_the_library_root_into_its_own_subfolder(self) -> None:
        (self.root / "Inception 2010.mkv").write_bytes(b"x" * 4096)
        cfg = self._cfg()

        with mock.patch.object(core, "is_under_collection_root", return_value=False):
            new_folder = apply_core.move_collection_folder(cfg, self.root, dry_run=False, log=self._log, record_op=None)

        self.assertEqual(new_folder, self.root, "la racine ne doit pas etre deplacee")
        self.assertTrue(self.root.exists())
        self.assertTrue((self.root / "Inception 2010.mkv").is_file())
        self.assertFalse((self.root / "_Collection").exists(), "meme le mkdir de _Collection doit etre evite")

    def test_still_moves_a_regular_collection_folder(self) -> None:
        """NON-REGRESSION : la fonctionnalite collection reste intacte."""
        saga = self.root / "Saga Source"
        saga.mkdir(parents=True, exist_ok=True)
        (saga / "MovieA.2001.mkv").write_bytes(b"a" * 4096)
        cfg = self._cfg()

        new_folder = apply_core.move_collection_folder(cfg, saga, dry_run=False, log=self._log, record_op=None)

        self.assertEqual(new_folder, self.root / "_Collection" / "Saga Source")
        self.assertTrue((self.root / "_Collection" / "Saga Source" / "MovieA.2001.mkv").is_file())
        self.assertFalse(saga.exists())


class PrepassRootGuardTests(unittest.TestCase):
    """Branche merge_dir_safe de la pre-passe : la destructrice.

    Predicat `is_under_collection_root` neutralise : seule la garde de la
    pre-passe d'apply_rows est exercee.
    """

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_prepass_root_")
        self.root = Path(self._tmp) / "Films"
        self.state_dir = Path(self._tmp) / "state"
        self.run_review_root = self.state_dir / "runs" / "tri_films_test" / "_review"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.logs: list[tuple[str, str]] = []

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _log(self, level: str, msg: str) -> None:
        self.logs.append((level, msg))

    def _cfg(self) -> core.Config:
        return core.Config(
            root=self.root, enable_collection_folder=True, collection_root_name="_Collection"
        ).normalized()

    def _leftover_videos(self) -> list[Path]:
        return [p for p in self.state_dir.rglob("*.mkv")]

    def test_never_merges_the_library_root_when_target_already_exists(self) -> None:
        (self.root / "Inception 2010.mkv").write_bytes(b"x" * 4096)
        # Le film deja range n'a rien a voir avec la racine : il etait emporte.
        (self.root / "Alien (1979)").mkdir(parents=True, exist_ok=True)
        (self.root / "Alien (1979)" / "alien.mkv").write_bytes(b"z" * 4096)
        # PRE-CONDITION du scenario destructeur : <root>/_Collection/<nom racine>.
        (self.root / "_Collection" / self.root.name).mkdir(parents=True, exist_ok=True)

        row = _collection_row("C|root", self.root, "Inception 2010.mkv", "Inception", 2010)
        decisions = {"C|root": {"ok": True, "title": "Inception", "year": 2010}}

        with mock.patch.object(core, "is_under_collection_root", return_value=False):
            result = apply_core.apply_rows(
                self._cfg(),
                [row],
                decisions,
                dry_run=False,
                quarantine_unapproved=False,
                log=self._log,
                run_review_root=self.run_review_root,
            )

        self.assertTrue(self.root.exists(), "la RACINE ENTIERE a ete deplacee")
        self.assertEqual(result.merges_count, 0, "la racine ne doit jamais etre mergee dans _Collection")
        self.assertEqual(result.errors, 0, result.error_messages)
        self.assertTrue((self.root / "Inception (2010)" / "Inception 2010.mkv").is_file())
        self.assertTrue((self.root / "Alien (1979)" / "alien.mkv").is_file(), "film etranger emporte")
        self.assertEqual(self._leftover_videos(), [], "des videos ont fini hors de la bibliotheque")

    def test_still_moves_a_regular_collection_folder_under_collection_root(self) -> None:
        """NON-REGRESSION : un vrai dossier multi-films reste range sous _Collection."""
        saga = self.root / "Saga Source"
        saga.mkdir(parents=True, exist_ok=True)
        (saga / "MovieA.2001.mkv").write_bytes(b"a" * 4096)

        row = _collection_row("C|saga", saga, "MovieA.2001.mkv", "Movie A", 2001)
        decisions = {"C|saga": {"ok": True, "title": "Movie A", "year": 2001}}

        result = apply_core.apply_rows(
            self._cfg(),
            [row],
            decisions,
            dry_run=False,
            quarantine_unapproved=False,
            log=self._log,
            run_review_root=self.run_review_root,
        )

        self.assertEqual(result.errors, 0, result.error_messages)
        self.assertEqual(result.collection_moves, 1)
        self.assertTrue((self.root / "_Collection" / "Saga Source" / "Movie A (2001)" / "MovieA.2001.mkv").is_file())


class IsUnderCollectionRootRootCaseTests(unittest.TestCase):
    """Predicat domaine : la racine n'est JAMAIS a rediriger sous _Collection."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_pred_root_")
        self.root = Path(self._tmp) / "Films"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _cfg(self) -> core.Config:
        return core.Config(
            root=self.root, enable_collection_folder=True, collection_root_name="_Collection"
        ).normalized()

    def test_library_root_is_never_redirected(self) -> None:
        cfg = self._cfg()
        self.assertTrue(core.is_under_collection_root(cfg, self.root))

    def test_regular_subfolders_keep_their_answer(self) -> None:
        """NON-REGRESSION : le contrat historique du predicat est inchange."""
        cfg = self._cfg()
        self.assertTrue(core.is_under_collection_root(cfg, self.root / "_Collection" / "Saga"))
        self.assertFalse(core.is_under_collection_root(cfg, self.root / "Saga"))

    def test_planned_target_for_a_root_row_matches_what_apply_writes(self) -> None:
        """MEDI-28 : la cible PLANIFIEE doit etre celle qu'apply ecrira."""
        cfg = self._cfg()
        row = _collection_row("C|root", self.root, "Inception 2010.mkv", "Inception", 2010)

        target = dup.planned_target_folder(
            cfg,
            row,
            "Inception",
            2010,
            is_under_collection_root=lambda cfg_, folder: dup.is_under_collection_root(
                cfg_, folder, norm_win_path=core._norm_win_path
            ),
            windows_safe=core.windows_safe,
        )

        self.assertEqual(target, self.root / "Inception (2010)")


if __name__ == "__main__":
    unittest.main()

"""Gardes unitaires R8-085 A+B (Lot D-fix 2026-07) — mkdir saga apres les gardes.

Fixe le contrat corrige de apply_single (cinesort/app/apply_core.py) :
  A. film saga DEJA conforme (skip NOOP) -> AUCUN dossier _Collection/<Saga>
     cree (avant le fix, coll_dir.mkdir s'executait AVANT les gardes) ;
  A'. cible saga > MAX_PATH (skip path_too_long) -> AUCUN dossier cree ;
  B. move saga reel -> les niveaux crees (_Collection PUIS _Collection/<Saga>)
     sont journalises en ops MKDIR (mkdir_counted), pour que l'undo puisse
     supprimer les orphelins vides ;
  B'. _undo_mkdir_ops (cinesort/ui/api/apply_support.py) rmdir les dossiers
     MKDIR journalises redevenus vides (plus profonds d'abord) et NE touche
     JAMAIS un dossier non vide.

Chaine complete correspondante : tests/test_lotd_chain_apply_undo.py
(gardes nominatives [R8-085] redevenues passantes).
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import cinesort.domain.core as core
from cinesort.app.apply_core import apply_single
from cinesort.ui.api.apply_support import _undo_mkdir_ops


def _noop_log(_level: str, _msg: str) -> None:
    pass


def _mk_movie_dir(root: Path, folder: str, video: str) -> Path:
    d = root / folder
    d.mkdir(parents=True, exist_ok=True)
    (d / video).write_bytes(b"x" * 2048)
    return d


class SagaMkdirAfterGuardsTests(unittest.TestCase):
    """R8-085 A : pas de dossier saga orphelin quand une garde skippe la row."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_r8085_")
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name) / "root"
        self.root.mkdir()
        self.cfg = core.Config(root=self.root).normalized()
        patcher = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        patcher.start()
        self.addCleanup(patcher.stop)

    def _buckets(self) -> Dict[str, Path]:
        review = self.root / "_review"
        return {
            "conflicts_root": review / "_conflicts",
            "conflicts_sidecars_root": review / "_conflicts_sidecars",
            "duplicates_identical_root": review / "_duplicates_identical",
            "leftovers_root": review / "_leftovers",
        }

    def test_noop_conform_film_creates_no_collection_dir(self) -> None:
        folder = _mk_movie_dir(self.root, "Saga Movie (2020)", "Saga Movie (2020).mkv")
        res = core.ApplyResult()
        apply_single(
            self.cfg,
            folder,
            "Saga Movie",
            2020,
            False,
            _noop_log,
            res,
            tmdb_collection_name="Test Saga",
            **self._buckets(),
        )
        self.assertEqual(res.renames, 0, res)
        self.assertFalse(
            (self.root / "_Collection").exists(),
            "R8-085 A : dossier saga orphelin cree pour un film conforme skippe",
        )

    def test_max_path_skip_creates_no_collection_dir(self) -> None:
        folder = _mk_movie_dir(self.root, "Long.Movie.2020", "Long.Movie.2020.mkv")
        res = core.ApplyResult()
        apply_single(
            self.cfg,
            folder,
            "T" * 240,  # cible > MAX_PATH -> kill-switch VQ-3 doit skipper
            2020,
            False,
            _noop_log,
            res,
            tmdb_collection_name="S" * 120,
            **self._buckets(),
        )
        self.assertEqual(res.renames, 0, res)
        self.assertFalse(
            (self.root / "_Collection").exists(),
            "R8-085 A : dossier saga orphelin cree malgre le skip MAX_PATH",
        )

    def test_real_saga_move_journalizes_each_created_level(self) -> None:
        folder = _mk_movie_dir(self.root, "Saga.Two.2021", "Saga.Two.2021.mkv")
        res = core.ApplyResult()
        ops: List[Dict[str, Any]] = []
        apply_single(
            self.cfg,
            folder,
            "Saga Two",
            2021,
            False,
            _noop_log,
            res,
            record_op=ops.append,
            tmdb_collection_name="Test Saga",
            **self._buckets(),
        )
        coll_root = self.root / "_Collection"
        coll_dir = coll_root / "Test Saga"
        self.assertTrue((coll_dir / "Saga Two (2021)").is_dir(), ops)
        mkdir_ops = [o for o in ops if o.get("op_type") == "MKDIR"]
        self.assertEqual(
            [o["dst_path"] for o in mkdir_ops],
            [str(coll_root), str(coll_dir)],
            "R8-085 B : chaque niveau cree doit etre journalise (parent d'abord)",
        )
        self.assertEqual(res.mkdirs, 2, res)

    def test_dry_run_saga_move_touches_nothing(self) -> None:
        folder = _mk_movie_dir(self.root, "Saga.Dry.2022", "Saga.Dry.2022.mkv")
        res = core.ApplyResult()
        apply_single(
            self.cfg,
            folder,
            "Saga Dry",
            2022,
            True,
            _noop_log,
            res,
            tmdb_collection_name="Test Saga",
            **self._buckets(),
        )
        self.assertFalse(
            (self.root / "_Collection").exists(),
            "[R8-085-preview] dry-run ne doit RIEN creer sur disque",
        )


class _StubApplyRepo:
    def __init__(self, ops: List[Dict[str, Any]]) -> None:
        self._ops = ops
        self.marked: List[Dict[str, Any]] = []

    def list_apply_operations(self, batch_id: str) -> List[Dict[str, Any]]:
        return list(self._ops)

    def mark_apply_operation_undo_status(self, *, op_id: int, undo_status: str, error_message: Any) -> None:
        self.marked.append({"op_id": op_id, "undo_status": undo_status})


class _StubStore:
    def __init__(self, ops: List[Dict[str, Any]]) -> None:
        self.apply = _StubApplyRepo(ops)


class UndoMkdirOpsTests(unittest.TestCase):
    """R8-085 B : l'undo supprime les dossiers MKDIR vides, garde les occupes."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_r8085_undo_")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)

    def _op(self, op_id: int, path: Path) -> Dict[str, Any]:
        return {"id": op_id, "op_type": "MKDIR", "src_path": str(path), "dst_path": str(path)}

    def test_empty_mkdir_dirs_removed_deepest_first(self) -> None:
        parent = self.base / "_Collection"
        child = parent / "Test Saga"
        child.mkdir(parents=True)
        store = _StubStore([self._op(1, parent), self._op(2, child)])
        removed = _undo_mkdir_ops(store, "batch-1", _noop_log)
        self.assertEqual(removed, 2)
        self.assertFalse(parent.exists(), "orphelins saga non nettoyes par l'undo")
        self.assertEqual([m["undo_status"] for m in store.apply.marked], ["DONE", "DONE"])

    def test_non_empty_dir_is_never_removed(self) -> None:
        parent = self.base / "_Collection"
        child = parent / "Autre Saga"
        child.mkdir(parents=True)
        (child / "Autre Film (2020)").mkdir()  # autre film encore range dedans
        store = _StubStore([self._op(1, parent), self._op(2, child)])
        removed = _undo_mkdir_ops(store, "batch-2", _noop_log)
        self.assertEqual(removed, 0)
        self.assertTrue((child / "Autre Film (2020)").is_dir(), "contenu detruit par l'undo")
        self.assertEqual(store.apply.marked, [], "op non vide marquee a tort")

    def test_missing_dir_is_tolerated(self) -> None:
        store = _StubStore([self._op(1, self.base / "disparu")])
        self.assertEqual(_undo_mkdir_ops(store, "batch-3", _noop_log), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)

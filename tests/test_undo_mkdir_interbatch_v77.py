"""FIX #9 (Lot D-fix 2026-07) — orphelin saga INTER-BATCH a l'undo.

Contexte : `mkdir_counted` (apply_core.py) ne rejournalise PAS un dossier saga
`_Collection/<Saga>/` deja existant. Quand un 2e apply reutilise le dossier cree
par un 1er apply, l'op MKDIR qui le "possede" reste dans le 1er batch. L'ancien
`_undo_mkdir_ops` ne balayait que les MKDIR du batch en cours d'annulation :

  batch 1 : cree `_Collection/<Saga>` (MKDIR journalise) + range FilmA dedans ;
  batch 2 : range FilmB dans le MEME dossier (aucun MKDIR journalise) ;
  undo batch 1 : FilmA restaure, mais le dossier reste occupe par FilmB -> MKDIR
                 batch 1 ne peut pas rmdir -> reste PENDING ;
  undo batch 2 : FilmB restaure -> dossier VIDE, mais l'ancien code ne regardait
                 que les MKDIR du batch 2 (aucun) -> `_Collection/<Saga>` orphelin
                 VIDE a jamais.

Le fix balaye les MKDIR PENDING de TOUS les batches du run (via `run_id`) et
rmdir les dossiers redevenus vides, les plus PROFONDS d'abord, sans JAMAIS
toucher un dossier non vide (undo selectif preserve).

Deux niveaux de preuve :
  * unitaires deterministes sur `_undo_mkdir_ops` (stub multi-batch) ;
  * end-to-end via `CineSortApi` (2 applies -> 2 batches reutilisant la meme
    saga -> undo selectif du 1er puis du 2e -> aucun orphelin sur disque).

Chaine complementaire (regression) : tests/test_lotd_chain_apply_undo.py (5/5).

Execution : .venv/Scripts/python.exe -X utf8 -m pytest \
    tests/test_undo_mkdir_interbatch_v77.py -q
"""

from __future__ import annotations

import re
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.apply_support import _undo_mkdir_ops
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import create_file as _create_file
from tests._helpers import wait_run_done as _wait_done


def _noop_log(_level: str, _msg: str) -> None:
    pass


_TRAILING_YEAR_RE = re.compile(r"^(?P<head>.+?)[\s._-]+(?P<yr>19\d{2}|20\d{2})$")


# ---------------------------------------------------------------------------
# Stub multi-batch : reproduit le contrat reel du store apply
#   - list_apply_batches_for_run(*, run_id, limit) -> plus recent d'abord
#   - list_apply_operations(*, batch_id)
#   - mark_apply_operation_undo_status(*, op_id, undo_status, error_message)
# ---------------------------------------------------------------------------


class _MultiBatchApplyRepo:
    def __init__(self, ops_by_batch: Dict[str, List[Dict[str, Any]]]) -> None:
        # insertion order = ordre chronologique (batch 1 puis batch 2 ...)
        self._ops_by_batch = ops_by_batch
        self.marked: List[Dict[str, Any]] = []

    def list_apply_batches_for_run(self, *, run_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        batch_ids = list(self._ops_by_batch.keys())
        out = [{"batch_id": bid, "run_id": run_id} for bid in reversed(batch_ids)]
        # R2 : miroir du contrat reel — limit<=0 = TOUS les batches (balayage
        # d'integrite non borne), sinon troncature.
        return out if int(limit) <= 0 else out[: int(limit)]

    def list_apply_operations(self, *, batch_id: str) -> List[Dict[str, Any]]:
        return list(self._ops_by_batch.get(batch_id, []))

    def mark_apply_operation_undo_status(self, *, op_id: int, undo_status: str, error_message: Any = None) -> None:
        self.marked.append({"op_id": int(op_id), "undo_status": undo_status})
        # Refleter le statut dans l'op pour que le filtre PENDING tienne entre appels.
        for ops in self._ops_by_batch.values():
            for op in ops:
                if int(op.get("id") or 0) == int(op_id):
                    op["undo_status"] = undo_status


class _LegacyApplyRepo:
    """Store legacy SANS list_apply_batches_for_run (fallback batch unique)."""

    def __init__(self, ops: List[Dict[str, Any]]) -> None:
        self._ops = ops
        self.marked: List[Dict[str, Any]] = []

    def list_apply_operations(self, *, batch_id: str) -> List[Dict[str, Any]]:
        return list(self._ops)

    def mark_apply_operation_undo_status(self, *, op_id: int, undo_status: str, error_message: Any = None) -> None:
        self.marked.append({"op_id": int(op_id), "undo_status": undo_status})


class _Store:
    def __init__(self, repo: Any) -> None:
        self.apply = repo


def _mkdir_op(op_id: int, path: Path, *, undo_status: str = "PENDING") -> Dict[str, Any]:
    return {
        "id": op_id,
        "op_type": "MKDIR",
        "src_path": str(path),
        "dst_path": str(path),
        "undo_status": undo_status,
    }


def _move_op(op_id: int, src: Path, dst: Path) -> Dict[str, Any]:
    return {
        "id": op_id,
        "op_type": "MOVE_DIR",
        "src_path": str(src),
        "dst_path": str(dst),
        "undo_status": "PENDING",
    }


class UndoMkdirInterBatchUnitTests(unittest.TestCase):
    """FIX #9 au niveau de `_undo_mkdir_ops` (deterministe, sans FS externe)."""

    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory(prefix="cinesort_fix9_")
        self.addCleanup(self._tmp.cleanup)
        self.base = Path(self._tmp.name)
        self.coll = self.base / "_Collection"
        self.saga = self.coll / "Test Saga"

    def _two_batch_store(self, saga_op_status: str = "PENDING") -> _Store:
        """batch-1 possede les MKDIR (_Collection puis Test Saga) ; batch-2 n'a
        qu'un MOVE (il a REUTILISE la saga -> aucun MKDIR journalise)."""
        batch1 = [_mkdir_op(1, self.coll), _mkdir_op(2, self.saga, undo_status=saga_op_status)]
        batch2 = [_move_op(10, self.base / "FilmB", self.saga / "FilmB (2021)")]
        return _Store(_MultiBatchApplyRepo({"batch-1": batch1, "batch-2": batch2}))

    def test_interbatch_orphan_removed_when_undoing_second_batch(self) -> None:
        """Coeur du fix : undo du batch 2 (sans MKDIR propre) supprime quand meme
        la saga vide dont le MKDIR vit dans le batch 1, grace au balayage run-wide."""
        self.saga.mkdir(parents=True)  # les deux films deja restaures -> vide
        store = self._two_batch_store()

        removed = _undo_mkdir_ops(store, "batch-2", _noop_log, run_id="run-1")

        self.assertEqual(removed, 2, "les deux niveaux saga vides doivent etre supprimes")
        self.assertFalse(self.coll.exists(), "orphelin saga inter-batch NON nettoye")
        # Plus profond d'abord : Test Saga (op 2) avant _Collection (op 1).
        self.assertEqual([m["op_id"] for m in store.apply.marked], [2, 1])
        self.assertTrue(all(m["undo_status"] == "DONE" for m in store.apply.marked))

    def test_without_run_id_orphan_persists(self) -> None:
        """Preuve que le fix est porteur : sans run_id (ancien comportement), le
        balayage se limite au batch 2 (aucun MKDIR) -> l'orphelin reste."""
        self.saga.mkdir(parents=True)
        store = self._two_batch_store()

        removed = _undo_mkdir_ops(store, "batch-2", _noop_log)  # pas de run_id

        self.assertEqual(removed, 0)
        self.assertTrue(self.saga.exists(), "sans le fix l'orphelin doit rester (regression guard)")
        self.assertEqual(store.apply.marked, [])

    def test_selective_undo_never_removes_occupied_saga(self) -> None:
        """Undo selectif preserve : annuler le batch 1 pendant que FilmB (batch 2)
        occupe encore la saga ne doit RIEN supprimer, meme en scan run-wide."""
        self.saga.mkdir(parents=True)
        occupied = self.saga / "FilmB (2021)"
        occupied.mkdir()
        store = self._two_batch_store()

        removed = _undo_mkdir_ops(store, "batch-1", _noop_log, run_id="run-1")

        self.assertEqual(removed, 0)
        self.assertTrue(occupied.is_dir(), "contenu d'un autre film detruit par l'undo")
        self.assertEqual(store.apply.marked, [], "MKDIR occupe marque a tort")

    def test_already_done_mkdir_ops_ignored(self) -> None:
        """Une op MKDIR deja DONE (dossier supprime lors d'un undo precedent) est
        filtree : pas de reprise, pas de crash."""
        store = self._two_batch_store(saga_op_status="DONE")  # saga deja soldee
        # _Collection subsiste et est vide (op 1 encore PENDING) ; la saga a disparu.
        self.coll.mkdir(parents=True)

        removed = _undo_mkdir_ops(store, "batch-2", _noop_log, run_id="run-1")

        # Seul _Collection (PENDING, vide) est retire ; l'op saga DONE est ignoree.
        self.assertEqual(removed, 1)
        self.assertFalse(self.coll.exists())
        self.assertEqual([m["op_id"] for m in store.apply.marked], [1])

    def test_fallback_when_store_lacks_batch_lister(self) -> None:
        """Store legacy sans list_apply_batches_for_run : on retombe proprement sur
        le seul batch_id (comportement historique R8-085 B)."""
        self.saga.mkdir(parents=True)
        repo = _LegacyApplyRepo([_mkdir_op(1, self.coll), _mkdir_op(2, self.saga)])
        store = _Store(repo)

        # run_id fourni mais inutilisable -> fallback batch_id.
        removed = _undo_mkdir_ops(store, "batch-legacy", _noop_log, run_id="run-1")

        self.assertEqual(removed, 2)
        self.assertFalse(self.coll.exists())


# ---------------------------------------------------------------------------
# End-to-end : 2 applies -> 2 batches reutilisant la meme saga -> undo du 2e
# ne laisse pas d'orphelin (chemin reel undo_selected_rows -> _undo_mkdir_ops).
# ---------------------------------------------------------------------------


class UndoMkdirInterBatchE2ETests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_fix9_e2e_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _settings(self) -> Dict[str, object]:
        return {
            "root": str(self.root),
            "state_dir": str(self.state_dir),
            "tmdb_enabled": False,
            "collection_folder_enabled": True,
            "probe_backend": "none",
        }

    def _inject_saga(self, run_id: str, saga: str) -> None:
        import json

        matches = list((self.state_dir / "runs").glob(f"*{run_id}*/plan.jsonl"))
        self.assertTrue(matches, f"plan.jsonl introuvable pour run {run_id}")
        plan_path = matches[0]
        lines = []
        for line in plan_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            d = json.loads(line)
            d["tmdb_collection_name"] = saga
            lines.append(json.dumps(d, ensure_ascii=False))
        plan_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    def _decision(self, row: Dict[str, Any]) -> Dict[str, Any]:
        return {"ok": True, "title": row.get("proposed_title"), "year": row.get("proposed_year")}

    def _folder_name(self, row: Dict[str, Any]) -> str:
        """Nom de dossier attendu par le template par defaut `{title} ({year})`.

        Regle « fix double-annee disque » (cinesort/domain/naming.py::_apply_template,
        commentaire L368-373) : quand le template contient `{year}`, le titre perd son
        annee de QUEUE si elle egale l'annee du couple, pour ne pas produire
        "Le Havre 2011 (2011)". Le `proposed_title` STOCKE reste intact (cle de
        dedoublonnage / seed torrents, cf. core.py::build_candidates_from_name L874) :
        la fixture "Saga.One.2019.1080p" donne proposed_title="Saga One 2019" et un
        dossier disque "Saga One (2019)". Regle REIMPLEMENTEE ici volontairement (et
        non importee de la prod) : le test doit rougir si le renommage disque
        reintroduit "Saga One 2019 (2019)".
        """
        title = str(row.get("proposed_title") or "")
        year = row.get("proposed_year")
        match = _TRAILING_YEAR_RE.match(title.strip())
        if match is not None and year is not None and int(match.group("yr")) == int(year):
            title = match.group("head").strip(" -_.") or title
        return f"{title} ({year})"

    def test_e2e_two_batches_same_saga_undo_leaves_no_orphan(self) -> None:
        src_a = self.root / "Saga.One.2019.1080p"
        src_b = self.root / "Saga.Two.2021.1080p"
        _create_file(src_a / "Saga.One.2019.1080p.mkv")
        _create_file(src_b / "Saga.Two.2021.1080p.mkv")

        api = CineSortApi()
        start = api.run.start_plan(self._settings())
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        _wait_done(api, run_id)

        plan = api.run.get_plan(run_id)
        self.assertTrue(plan.get("ok"), plan)
        rows = plan.get("rows", [])
        self.assertEqual(len(rows), 2, rows)
        self._inject_saga(run_id, "Test Saga")

        # API fraiche : relit le plan.jsonl (avec la saga) en mode DB-only.
        api2 = CineSortApi()
        self.assertTrue(api2.settings.save_settings(self._settings()).get("ok"))

        row_a = next(r for r in rows if "One" in str(r["folder"]))
        row_b = next(r for r in rows if "Two" in str(r["folder"]))

        # ---- batch 1 : seulement FilmA -> cree _Collection/Test Saga (MKDIR) ---
        applied1 = api2.run.apply(run_id, {str(row_a["row_id"]): self._decision(row_a)}, False, False)
        self.assertTrue(applied1.get("ok"), applied1)
        self.assertEqual(int((applied1.get("result") or {}).get("renames") or 0), 1, applied1)
        batch1 = str(applied1.get("apply_batch_id") or "")
        self.assertTrue(batch1, applied1)

        saga_dir = self.root / "_Collection" / "Test Saga"
        self.assertTrue((saga_dir / self._folder_name(row_a)).is_dir(), "FilmA non range sous la saga")

        # ---- batch 2 : seulement FilmB -> REUTILISE la saga (aucun MKDIR) ------
        applied2 = api2.run.apply(run_id, {str(row_b["row_id"]): self._decision(row_b)}, False, False)
        self.assertTrue(applied2.get("ok"), applied2)
        self.assertEqual(int((applied2.get("result") or {}).get("renames") or 0), 1, applied2)
        batch2 = str(applied2.get("apply_batch_id") or "")
        self.assertTrue(batch2 and batch2 != batch1, (batch1, batch2))

        store, _runner = api2._get_or_create_infra(self.state_dir)
        b2_mkdir = [o for o in store.apply.list_apply_operations(batch_id=batch2) if str(o.get("op_type")) == "MKDIR"]
        self.assertEqual(b2_mkdir, [], "premisse du bug : le 2e batch NE doit PAS rejournaliser la saga")
        self.assertTrue((saga_dir / self._folder_name(row_b)).is_dir(), "FilmB non range sous la saga")

        # ---- undo du batch 1 D'ABORD : FilmA restaure, saga encore occupee -----
        undo1 = api2._undo_selected_rows_impl(run_id, [str(row_a["row_id"])], dry_run=False, batch_id=batch1)
        self.assertTrue(undo1.get("ok"), undo1)
        self.assertTrue(src_a.is_dir(), "FilmA non restaure")
        self.assertTrue(saga_dir.exists(), "saga supprimee alors que FilmB l'occupe encore (undo selectif casse)")

        # ---- undo du batch 2 : FilmB restaure -> saga VIDE -> aucun orphelin ---
        undo2 = api2._undo_selected_rows_impl(run_id, [str(row_b["row_id"])], dry_run=False, batch_id=batch2)
        self.assertTrue(undo2.get("ok"), undo2)
        self.assertTrue(src_b.is_dir(), "FilmB non restaure")

        # FIX #9 : plus aucun `_Collection/` orphelin vide apres le 2e undo.
        self.assertFalse(
            (self.root / "_Collection").exists(),
            "FIX #9 : dossier saga inter-batch reste orphelin vide apres l'undo du 2e batch",
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)

"""`build_undo_by_row_preview` : une seule lecture des operations du batch.

Ultra-audit 2026-08 (N25) : la boucle par film appelait
`list_apply_operations_by_row` UNE FOIS PAR ROW. Chaque appel du repository
ouvre deux connexions SQLite neuves (verification du schema + requete), soit
2N connexions pour N films — mesure adversaire : 165 s sur un batch de 5000
films, contre 88 ms pour la requete unique suivie d'un regroupement Python.

Ces tests utilisent un VRAI `SQLiteStore` (donc la vraie semantique SQL, y
compris `row_id IS NULL` regroupe sous `__legacy__`) et comptent les
ouvertures de connexion reelles en instrumentant `connect_sqlite`.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional
from unittest import mock

sys.path.insert(0, ".")

from cinesort.infra.db import sqlite_store as sqlite_store_module
from cinesort.infra.db.sqlite_store import SQLiteStore
from cinesort.ui.api import apply_support


class _FakeRunState:
    def __init__(self) -> None:
        self.rows: List[Any] = []


class _FakeApi:
    """Stub minimal : seul le store compte pour ce chemin."""

    def __init__(self, store: SQLiteStore, state_dir: Path) -> None:
        self._store = store
        self._state_dir = state_dir

    def _is_valid_run_id(self, run_id: Any) -> bool:
        return bool(str(run_id or "").strip())

    def _find_run_row(self, run_id: str):
        return ({"run_id": run_id, "state_dir": str(self._state_dir)}, self._store)

    def _get_run(self, run_id: str) -> Optional[_FakeRunState]:
        return None

    def _run_paths_for(self, state_dir: Any, run_id: str, ensure_exists: bool = True) -> Dict[str, Any]:
        return {"run_dir": str(self._state_dir)}

    def _load_rows_from_plan_jsonl(self, run_paths: Any) -> List[Any]:
        raise FileNotFoundError("pas de plan.jsonl dans ce test")


class UndoByRowPreviewQueryBudgetTests(unittest.TestCase):
    RUN_ID = "run_n25"

    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_n25_"))
        self.store = SQLiteStore(self._tmp / "test.sqlite", busy_timeout_ms=5000)
        self.store.initialize()
        self.api = _FakeApi(self.store, self._tmp)
        self.batch_id = self._seed_batch(rows=12, ops_per_row=2)

    def tearDown(self) -> None:
        try:
            self.store.close()
        except Exception:  # noqa: BLE001 — best effort de teardown
            pass
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed_batch(self, *, rows: int, ops_per_row: int) -> str:
        bid = self.store.apply.insert_apply_batch(
            run_id=self.RUN_ID,
            dry_run=False,
            quarantine_unapproved=False,
            status="PENDING",
        )
        idx = 0
        for i in range(rows):
            for k in range(ops_per_row):
                self.store.apply.append_apply_operation(
                    batch_id=bid,
                    op_index=idx,
                    op_type="MOVE" if k == 0 else "MOVE_DIR",
                    src_path=str(self._tmp / f"src_{i}_{k}"),
                    dst_path=str(self._tmp / f"dst_{i}_{k}"),
                    reversible=True,
                    row_id=f"R{i}",
                )
                idx += 1
        # Une operation heritee sans row_id (row_id NULL -> groupe __legacy__).
        self.store.apply.append_apply_operation(
            batch_id=bid,
            op_index=idx,
            op_type="MOVE",
            src_path=str(self._tmp / "src_legacy"),
            dst_path=str(self._tmp / "dst_legacy"),
            reversible=True,
            row_id=None,
        )
        self.store.apply.close_apply_batch(batch_id=bid, status="DONE", summary={})
        return bid

    # -- budget de requetes -------------------------------------------------

    def test_operations_are_read_once_for_the_whole_batch(self) -> None:
        """Le cout ne doit PAS croitre avec le nombre de films du batch."""
        calls: Dict[str, int] = {"by_row": 0, "batch": 0}
        real_by_row = type(self.store.apply).list_apply_operations_by_row
        real_batch = type(self.store.apply).list_apply_operations

        def spy_by_row(repo, **kwargs):
            calls["by_row"] += 1
            return real_by_row(repo, **kwargs)

        def spy_batch(repo, **kwargs):
            calls["batch"] += 1
            return real_batch(repo, **kwargs)

        with (
            mock.patch.object(type(self.store.apply), "list_apply_operations_by_row", spy_by_row),
            mock.patch.object(type(self.store.apply), "list_apply_operations", spy_batch),
        ):
            out = apply_support.build_undo_by_row_preview(self.api, self.RUN_ID)

        self.assertTrue(out.get("ok"), out)
        self.assertEqual(len(out.get("rows") or []), 13)  # 12 films + __legacy__
        self.assertEqual(
            calls["by_row"],
            0,
            "regression N25 : lecture des operations film par film (N+1)",
        )
        self.assertEqual(calls["batch"], 1, "les operations doivent etre lues en UNE requete")

    def test_connection_count_is_independent_of_batch_size(self) -> None:
        """Compte les ouvertures REELLES de connexion SQLite (2 par requete repo)."""

        def _count_connections() -> int:
            opened = {"n": 0}
            real_connect = sqlite_store_module.connect_sqlite

            def spy(*args, **kwargs):
                opened["n"] += 1
                return real_connect(*args, **kwargs)

            with mock.patch.object(sqlite_store_module, "connect_sqlite", spy):
                out = apply_support.build_undo_by_row_preview(self.api, self.RUN_ID)
            self.assertTrue(out.get("ok"), out)
            return opened["n"]

        small = _count_connections()
        # Meme batch, 5x plus de films : le nombre de connexions ne doit pas suivre.
        self.batch_id = self._seed_batch(rows=60, ops_per_row=2)
        big = _count_connections()
        self.assertLessEqual(
            big,
            small + 2,
            f"le cout suit le nombre de films (N+1) : {small} connexions a 12 films, {big} a 60",
        )

    # -- equivalence fonctionnelle -----------------------------------------

    def test_per_row_operations_match_the_row_scoped_query(self) -> None:
        """Le regroupement Python doit rendre EXACTEMENT ce que rendait la requete par row."""
        out = apply_support.build_undo_by_row_preview(self.api, self.RUN_ID)
        self.assertTrue(out.get("ok"), out)
        for row in out["rows"]:
            rid = row["row_id"]
            expected = self.store.apply.list_apply_operations_by_row(batch_id=self.batch_id, row_id=rid)
            got = row["operations"]
            self.assertEqual(len(got), len(expected), f"row {rid}")
            self.assertEqual(
                [op["id"] for op in got],
                [op["id"] for op in expected],
                f"ordre ou contenu different pour {rid}",
            )
            self.assertEqual(row["ops_total"], len(expected), f"row {rid}")

    def test_legacy_row_without_row_id_keeps_its_operations(self) -> None:
        """La ligne heritee (row_id NULL) ne doit pas perdre ses operations."""
        out = apply_support.build_undo_by_row_preview(self.api, self.RUN_ID)
        legacy = next((r for r in out["rows"] if r["row_id"] == "__legacy__"), None)
        self.assertIsNotNone(legacy, "groupe __legacy__ absent")
        self.assertEqual(len(legacy["operations"]), 1)
        self.assertTrue(legacy["operations"][0]["src_path"].endswith("src_legacy"))
        self.assertTrue(legacy["can_undo"])

    def test_no_row_is_empty(self) -> None:
        """Filet anti-regroupement-casse : aucun film ne doit perdre ses ops."""
        out = apply_support.build_undo_by_row_preview(self.api, self.RUN_ID)
        for row in out["rows"]:
            self.assertGreater(
                len(row["operations"]),
                0,
                f"le film {row['row_id']} a perdu ses operations au regroupement",
            )


if __name__ == "__main__":
    unittest.main()

"""Issue #593 — `undo_selected_rows` : le chemin dry_run testait
`r["row_id"] in row_ids` sur une LISTE.

Deux consequences, toutes deux corrigees par la meme hoisting du set :

1. COMPLEXITE : O(N*M) (N lignes de preview x M row_ids). Le chemin non-dry_run
   avait deja `set(str(r) for r in row_ids)` ; l'asymetrie n'avait aucune raison
   d'etre.
2. CONTRAT : le dry_run ne coercait PAS en `str`, contrairement au chemin reel.
   Un client REST qui envoie des row_ids non-`str` (le corps est decode par
   `json.loads`) obtenait donc un APERCU annoncant 0 ligne, puis une annulation
   REELLE de N lignes. Sur un chemin destructif, l'apercu doit dire la verite.

Les tests exercent la VRAIE chaine (scan -> apply -> undo), pas un helper isole.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

import cinesort.domain.core as core
from cinesort.ui.api.cinesort_api import CineSortApi
from tests._helpers import cleanup_test_tree
from tests._helpers import wait_run_done as _wait_done


def _create_file(path: Path, size: int = 4) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)


class _StrLikeRowId:
    """row_id non-`str` dont `str()` vaut le vrai row_id.

    Modelise ce qu'un client REST peut envoyer apres `json.loads` (un nombre,
    typiquement). Le chemin reel le resout via `str(r)` ; le dry_run doit faire
    exactement pareil.
    """

    def __init__(self, value: str) -> None:
        self._value = value

    def __str__(self) -> str:  # pragma: no cover - trivial
        return self._value


class _ProbeCountingList(list):
    """Liste qui compte les tests d'appartenance `x in liste`.

    Sonde de COMPLEXITE : avec le correctif, le preview construit un set une
    seule fois et n'interroge jamais la liste -> 0 sonde. Sans lui, il y a une
    sonde lineaire par ligne de preview.
    """

    def __init__(self, items) -> None:
        super().__init__(items)
        self.contains_calls = 0

    def __contains__(self, item) -> bool:
        self.contains_calls += 1
        return super().__contains__(item)


class UndoSelectedRowsSetTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="cinesort_undo593_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True, exist_ok=True)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        _p = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p.start()
        self.addCleanup(_p.stop)

    def tearDown(self) -> None:
        cleanup_test_tree(self._tmp)

    def _apply_films(self, count: int):
        for i in range(count):
            src = self.root / f"Film.Numero.{2001 + i}.1080p"
            _create_file(src / f"Film.Numero.{2001 + i}.1080p.mkv")
        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                "collection_folder_enabled": True,
            }
        )
        self.assertTrue(start.get("ok"), start)
        run_id = str(start["run_id"])
        _wait_done(api, run_id)
        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertEqual(len(rows), count, plan)
        decisions = {
            r["row_id"]: {"ok": True, "title": r.get("proposed_title"), "year": r.get("proposed_year")} for r in rows
        }
        applied = api._apply_impl(run_id, decisions, False, False)
        self.assertTrue(applied.get("ok"), applied)
        return api, run_id, [str(r["row_id"]) for r in rows]

    # ------------------------------------------------------------- contrat
    def test_dry_run_coerce_les_row_ids_comme_le_chemin_reel(self) -> None:
        """L'apercu doit selectionner la MEME ligne que l'undo reel annulerait."""
        api, run_id, row_ids = self._apply_films(2)
        target = row_ids[0]

        dry = api._undo_selected_rows_impl(run_id, [_StrLikeRowId(target)], dry_run=True)
        self.assertTrue(dry.get("ok"), dry)
        selected = dry.get("selected_rows") or []
        self.assertEqual(
            [str(r["row_id"]) for r in selected],
            [target],
            "l'apercu doit annoncer la ligne que l'undo reel va annuler "
            f"(apercu obtenu : {[r.get('row_id') for r in selected]})",
        )

        # Preuve de l'asymetrie : le chemin REEL, lui, a toujours resolu ce
        # row_id. Un apercu vide suivi d'une annulation effective serait un
        # mensonge sur un chemin destructif.
        real = api._undo_selected_rows_impl(run_id, [_StrLikeRowId(target)], dry_run=False)
        self.assertTrue(real.get("ok"), real)
        self.assertIn(real.get("status"), {"UNDONE_DONE", "UNDONE_PARTIAL"}, real)

    # --------------------------------------------------------- complexite
    def test_dry_run_ne_sonde_pas_row_ids_en_lineaire(self) -> None:
        api, run_id, row_ids = self._apply_films(2)
        probe = _ProbeCountingList(row_ids)

        dry = api._undo_selected_rows_impl(run_id, probe, dry_run=True)
        self.assertTrue(dry.get("ok"), dry)
        self.assertEqual(len(dry.get("selected_rows") or []), 2, dry)
        self.assertEqual(
            probe.contains_calls,
            0,
            "le preview doit tester l'appartenance sur un SET construit une fois, "
            f"pas sonder la liste ligne par ligne ({probe.contains_calls} sondes observees)",
        )

    def test_nonreg_row_ids_str_selectionnent_toujours(self) -> None:
        """Non-regression : le cas nominal (row_ids deja `str`) est inchange."""
        api, run_id, row_ids = self._apply_films(2)
        dry = api._undo_selected_rows_impl(run_id, [row_ids[1]], dry_run=True)
        self.assertTrue(dry.get("ok"), dry)
        self.assertEqual([str(r["row_id"]) for r in dry.get("selected_rows") or []], [row_ids[1]])


if __name__ == "__main__":
    unittest.main()

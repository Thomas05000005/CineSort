"""Issue #515 (volet 2) — un run RUNNING orphelin est repris au boot suivant.

Le worker garantit deja la sortie de RUNNING dans son `finally`
(`JobRunner._ensure_run_left_running`, PR #920). Mais ce filet ne peut rien
quand la base est injoignable au moment ou il s'execute : il l'ecrit lui-meme,
« le nettoyage des runs orphelins au boot la reprendra ». Ce balayage existe
depuis R5-CRASH-1 (`cinesort/ui/api/runtime_support.py`, dans
`get_or_create_infra`) — mais rien ne le testait, donc rien ne signalerait sa
disparition. Or c'est LUI le dernier recours : sans lui, un crash brutal de
l'application (coupure de courant, kill du process) laisse une ligne `runs` sur
RUNNING que plus aucun code n'atteindra, et la timeline affiche un traitement
eternellement en cours.

Le boot est REEL ici : `_get_or_create_infra` est appele comme au demarrage de
l'application, pas via un helper interne extrait pour la circonstance. Un test
qui appellerait directement une fonction de nettoyage ne dirait rien du fait
qu'elle est effectivement CABLEE au boot.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Optional

from cinesort.infra.db.sqlite_store import SQLiteStore, db_path_for_state_dir
from cinesort.ui.api import cinesort_api as backend
from cinesort.ui.api import runtime_support


class OrphanRunsBootCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_orphan_runs_515_"))
        self.state_dir = self._tmp / "state"
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        runtime_support._RECONCILED_STATE_DIRS.clear()
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _seed_run(self, run_id: str, *, status: str) -> None:
        """Pose une ligne `runs` dans l'etat demande, puis ferme le store.

        L'etat est pose par les methodes de la repo quand elles existent : un
        UPDATE direct court-circuiterait leurs invariants et le scenario ne
        ressemblerait plus a ce que produit un vrai run.
        """
        store = SQLiteStore(db_path_for_state_dir(self.state_dir), busy_timeout_ms=5000)
        store.initialize()
        store.run.insert_run_pending(
            run_id=run_id,
            root=str(self._tmp / "films"),
            state_dir=str(self.state_dir),
            config={},
        )
        if status == "RUNNING":
            store.run.mark_run_running(run_id)
        elif status == "PAUSED":
            store.run.mark_run_running(run_id)
            store.run.mark_run_paused(run_id)
        elif status == "DONE":
            store.run.mark_run_running(run_id)
            store.run.mark_run_done(run_id, stats={})
        elif status != "PENDING":
            raise AssertionError(f"statut de scenario non prevu: {status}")
        store.close()

    def _boot(self) -> None:
        """Boot reel : meme chemin que le demarrage de l'application."""
        runtime_support._RECONCILED_STATE_DIRS.clear()
        api = backend.CineSortApi()
        store, _runner = api._get_or_create_infra(self.state_dir)  # type: ignore[attr-defined]
        store.close()

    def _run_row(self, run_id: str) -> Optional[Dict[str, Any]]:
        store = SQLiteStore(db_path_for_state_dir(self.state_dir), busy_timeout_ms=5000)
        try:
            return store.run.get_run(run_id)
        finally:
            store.close()

    def test_un_run_reste_running_apres_un_crash_est_marque_failed_au_boot(self) -> None:
        self._seed_run("run-zombie", status="RUNNING")
        self.assertEqual(self._run_row("run-zombie")["status"], "RUNNING", "amorcage casse")

        self._boot()

        row = self._run_row("run-zombie")
        self.assertEqual(
            row["status"],
            "FAILED",
            "le run est reste RUNNING apres un boot complet : plus aucun code ne "
            "le terminera, la timeline affichera un traitement eternel",
        )
        self.assertTrue(
            str(row.get("error_message") or ""),
            "un run force en FAILED sans message n'explique rien a l'utilisateur",
        )

    def test_le_balayage_epargne_les_autres_etats(self) -> None:
        """Contre-test : le balayage ne repeint pas l'historique en FAILED.

        Un run RUNNING est pose EXPRES a cote des trois autres. Sans lui, le
        `if orphan_run_ids:` du balayage court-circuite l'UPDATE et ce test
        serait vert quel que soit son filtre — il ne prouverait rien. Mesure
        faite : avec des scenarios a un seul run non-RUNNING, remplacer
        `WHERE status = 'RUNNING'` par `WHERE status != 'FAILED'` restait VERT.
        Ce n'etait pas un mutant equivalent, c'etait un test qui n'empruntait
        pas le chemin.

        PAUSED est le cas le plus couteux : un run mis de cote par
        l'utilisateur, repeint en FAILED, ne serait plus reprenable apres un
        simple redemarrage.
        """
        self._seed_run("run-zombie", status="RUNNING")
        self._seed_run("run-fini", status="DONE")
        self._seed_run("run-en-pause", status="PAUSED")
        self._seed_run("run-pending", status="PENDING")

        self._boot()

        self.assertEqual(self._run_row("run-zombie")["status"], "FAILED", "l'orphelin n'a pas ete repris")
        self.assertEqual(self._run_row("run-fini")["status"], "DONE")
        self.assertEqual(self._run_row("run-en-pause")["status"], "PAUSED")
        self.assertEqual(self._run_row("run-pending")["status"], "PENDING")


if __name__ == "__main__":
    unittest.main()

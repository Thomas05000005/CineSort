"""F19 — la pagination des logs de run doit survivre au trim de retention.

Bug d'origine (revue post-merge 2026-07-18, F19) : `RunState.log`
(cinesort/ui/api/_run_state.py) tronquait `self.logs` aux MAX_RUN_LOG_ITEMS
derniers items (index RELATIFS) tandis que `_get_status_impl`
(cinesort/ui/api/run_flow_support.py) paginait avec des index ABSOLUS
(`rs.logs[last_log_index:]` puis `next_log_index = last_log_index + len(logs)`).
Des que le run depassait 5000 lignes, `next_log_index` se figeait a 5000 et
toutes les requetes suivantes retournaient `logs: []` : le panneau logs de
l'ecran Traitement gelait DEFINITIVEMENT (traitement.js pagine cumulativement,
sans reset).

fail-before / pass-after : apres 5000+1000 lignes paginees puis 100 lignes de
plus, le client doit recevoir la fin du flux ('ligne 6099') et un
next_log_index coherent (6100). ROUGE avant : logs == [] et next_log_index
fige a 5000.

NON-REGRESSION : sans trim (100 lignes, pagination par 30), la reception doit
rester exacte et sans doublon (VERT avant ET apres).
"""

from __future__ import annotations

import shutil
import tempfile
import threading
import unittest
from pathlib import Path
from typing import Any, Dict, List
from unittest import mock

import cinesort.infra.state as state
from cinesort.ui.api import run_flow_support
from cinesort.ui.api._run_state import MAX_RUN_LOG_ITEMS, RunState


class RunStatusLogPaginationTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cs_logs_pagination_"))
        self.paths = state.new_run(self._tmp, "run1")
        self.rs = RunState(
            self.paths,
            mock.MagicMock(),
            runner=mock.MagicMock(),
            store=mock.MagicMock(),
        )
        # Le run est en cours : _get_status_impl ne doit pas tenter de recompter
        # plan.jsonl (branche `done and not running`).
        snap = mock.MagicMock()
        snap.running = True
        snap.done = False
        snap.error = None
        snap.cancel_requested = False
        snap.status.value = "RUNNING"
        self.rs.runner.get_status.return_value = snap
        self.rs.running = True

        self.api = mock.MagicMock()
        self.api._get_run.return_value = self.rs

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _poll(self, idx: int) -> Dict[str, Any]:
        return run_flow_support._get_status_impl(self.api, "run1", last_log_index=idx)

    def test_pagination_survit_au_trim_5000(self) -> None:
        total_first = MAX_RUN_LOG_ITEMS + 1000  # 6000
        received: List[str] = []
        idx = 0

        for i in range(total_first):
            self.rs.log("INFO", f"ligne {i}")
            if (i + 1) % 500 == 0:
                data = self._poll(idx)
                received.extend(item["msg"] for item in data["logs"])
                idx = int(data["next_log_index"])

        for i in range(total_first, total_first + 100):
            self.rs.log("INFO", f"ligne {i}")

        data = self._poll(idx)
        self.assertTrue(
            data["logs"],
            "Le flux de logs doit repartir apres le trim de retention (sinon le panneau Traitement est gele a vie).",
        )
        self.assertEqual(data["logs"][-1]["msg"], "ligne 6099")
        self.assertEqual(data["next_log_index"], 6100)

    def test_pas_de_trim_pagination_inchangee(self) -> None:
        # NON-REGRESSION : sous le seuil de retention, la pagination historique
        # (index absolus == index de liste) doit etre STRICTEMENT preservee :
        # reception exacte, dans l'ordre, sans doublon ni trou.
        received: List[str] = []
        idx = 0
        for i in range(100):
            self.rs.log("INFO", f"L{i}")
            if (i + 1) % 30 == 0:
                data = self._poll(idx)
                received.extend(item["msg"] for item in data["logs"])
                idx = int(data["next_log_index"])
        data = self._poll(idx)
        received.extend(item["msg"] for item in data["logs"])

        self.assertEqual(received, [f"L{i}" for i in range(100)])
        self.assertEqual(data["next_log_index"], 100)


class RunStatusLogOffsetFallbackTests(unittest.TestCase):
    """F19 (revue R1) — le repli sur `logs_offset` doit tester le TYPE.

    Le commentaire du correctif annoncait un « getattr defensif : compat
    RunState mocke / serialise sans le champ », mais
    `int(getattr(rs, 'logs_offset', 0) or 0)` ne couvrait PAS ce cas : sur un
    `unittest.mock.MagicMock`, getattr ne leve pas et ne retombe pas sur le
    defaut — il rend un MagicMock truthy dont `int()` vaut 1. Le filet annonce
    introduisait donc un decalage silencieux de 1 (start = last_log_index - 1 :
    une ligne RE-EMISE a chaque poll ; next_log_index = 1 + len(rs.logs) :
    off-by-one permanent) au lieu de NEUTRALISER l'offset.
    """

    def setUp(self) -> None:
        # rs entierement mocke, avec une liste .logs REELLE : la forme exacte que
        # le commentaire pretendait couvrir.
        self.rs = mock.MagicMock()
        self.rs.lock = threading.RLock()
        self.rs.logs = [{"ts": "00:00:00", "level": "INFO", "msg": f"L{i}"} for i in range(5)]
        self.rs.idx = 3
        self.rs.total = 10
        self.rs.current_folder = "dossier"
        self.rs.running = True
        self.rs.done = False
        self.rs.error = None
        self.rs.started_ts = 1000.0
        self.rs.progress_samples = []
        self.rs.speed_ewma = 0.0
        self.rs.apply_running = False
        self.rs.apply_done = False
        snap = mock.MagicMock()
        snap.running = True
        snap.done = False
        snap.error = None
        snap.cancel_requested = False
        snap.status.value = "RUNNING"
        self.rs.runner.get_status.return_value = snap

        self.api = mock.MagicMock()
        self.api._get_run.return_value = self.rs

    def _poll(self, idx: int) -> Dict[str, Any]:
        return run_flow_support._get_status_impl(self.api, "run1", last_log_index=idx)

    def test_offset_non_entier_est_neutralise(self) -> None:
        self.assertNotIsInstance(
            self.rs.logs_offset,
            int,
            "pre-condition : sur un rs mocke, l'attribut EXISTE et n'est pas un int.",
        )

        first = self._poll(0)
        self.assertEqual([item["msg"] for item in first["logs"]], [f"L{i}" for i in range(5)])
        self.assertEqual(
            first["next_log_index"],
            5,
            "next_log_index doit valoir len(rs.logs), pas 1 + len(rs.logs).",
        )

        second = self._poll(int(first["next_log_index"]))
        self.assertEqual(
            [item["msg"] for item in second["logs"]],
            [],
            "Rien de neuf entre deux polls : aucune ligne ne doit etre re-emise.",
        )
        self.assertEqual(second["next_log_index"], 5)

    def test_offset_entier_reel_reste_honore(self) -> None:
        # NON-REGRESSION : un offset ENTIER (le cas de production, pose par le
        # trim de retention de RunState.log) doit continuer a decaler la fenetre.
        # VERT avant ET apres le correctif.
        self.rs.logs_offset = 700

        data = self._poll(702)

        self.assertEqual([item["msg"] for item in data["logs"]], [f"L{i}" for i in range(2, 5)])
        self.assertEqual(data["next_log_index"], 705)


if __name__ == "__main__":
    unittest.main()

"""#594 — les workers background perdaient le `run_id` de leurs logs.

`threading.Thread` ne copie PAS le contexte `contextvars` du parent : c'est
ecrit noir sur blanc dans `cinesort/infra/log_context.py` (« Les sous-threads
spawnes par un worker doivent appeler `set_run_id` manuellement »). Trois
workers daemon l'ignoraient — `_recompute_worker`, `_run_perceptual_job`,
`_run_perceptual_batch_job` — et toutes leurs lignes sortaient avec `[run=-]`,
y compris celles qui rapportent un ECHEC par film. Un job de re-scoring dure
plusieurs minutes en concurrence avec le reste de l'application : sans run_id,
ces lignes ne se rattachent a rien.

Le resultat de ces workers, lui, EST attendu : le front poll
`get_recompute_job_status` (`web/dashboard/views/qualite.js:1025`) et
`get_perceptual_job_status` (`bibliotheque.js:1653`, `doublons.js:1139`), et
chaque worker possede deja un garde-fou `except Exception` qui bascule le job
en `failed`/`error`. Ce lot ne touche donc pas au statut — il rend seulement
diagnosticables les lignes qui l'expliquent.

Points de vigilance verrouilles ici :

* on part des POINTS D'ENTREE reels (`recompute_all_scores`,
  `queue_perceptual_analyses`, `queue_perceptual_batch`), pas des workers
  prives : c'est l'appelant qui construit le thread et lui passe le run_id ;
* l'enrichissement est observe comme en production, via un
  `LogContextFilter` attache au HANDLER (cf. `log_scrubber.attach_filter_to_handler`)
  et evalue dans le thread emetteur ;
* le `request_id` doit rester ABSENT : la requete REST a deja rendu sa reponse
  quand le thread demarre. Le propager afficherait une valeur fausse.
"""

from __future__ import annotations

import logging
import threading
import time
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from cinesort.infra.log_context import (
    LogContextFilter,
    clear_request_id,
    clear_run_id,
    set_request_id,
)
from cinesort.ui.api import perceptual_support, quality_audit_support

RUN_ID = "20260805_worker_ctx"
OTHER_RUN_ID = "20260805_worker_ctx_bis"

_JOB_DEADLINE_S = 30.0


class _CapturingHandler(logging.Handler):
    """Handler de test cable comme en prod : LogContextFilter sur le HANDLER.

    `logging.Handler.handle()` applique les filters du handler AVANT `emit`,
    dans le thread qui emet — donc `record.run_id` refletera le ContextVar
    du worker, pas celui du thread de test.
    """

    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: List[logging.LogRecord] = []
        self._lock_records = threading.Lock()
        self.addFilter(LogContextFilter())

    def emit(self, record: logging.LogRecord) -> None:
        with self._lock_records:
            self.records.append(record)

    def run_ids_for(self, needle: str) -> List[str]:
        with self._lock_records:
            return [str(getattr(r, "run_id", "?")) for r in self.records if needle in r.getMessage()]

    def request_ids_for(self, needle: str) -> List[str]:
        with self._lock_records:
            return [str(getattr(r, "request_id", "?")) for r in self.records if needle in r.getMessage()]


class _WorkerLogContextCase(unittest.TestCase):
    """Socle commun : capture des logs d'un module + nettoyage des ContextVars."""

    module_logger_name = ""

    def setUp(self) -> None:
        clear_run_id()
        clear_request_id()
        self.handler = _CapturingHandler()
        self.logger = logging.getLogger(self.module_logger_name)
        self._prev_level = self.logger.level
        self.logger.setLevel(logging.DEBUG)
        self.logger.addHandler(self.handler)

    def tearDown(self) -> None:
        self.logger.removeHandler(self.handler)
        self.logger.setLevel(self._prev_level)
        clear_run_id()
        clear_request_id()

    def _wait_until(self, predicate: Any, what: str) -> None:
        """Attend une CONDITION (jamais une duree) ; le delai n'est qu'un garde-fou."""
        deadline = time.monotonic() + _JOB_DEADLINE_S
        while time.monotonic() < deadline:
            if predicate():
                return
            time.sleep(0.01)
        self.fail(f"{what} n'est jamais arrive en {_JOB_DEADLINE_S:.0f} s")


# ---------------------------------------------------------------------------
# recompute_all_scores -> _recompute_worker
# ---------------------------------------------------------------------------


def _fake_api_for_recompute(tmp_state_dir: str, row_ids: List[str]) -> Any:
    """Stub d'API minimal. Il FOURNIT l'entree, il ne fabrique pas la condition.

    La condition testee — `record.run_id` — est posee par le code de
    production dans le worker ; aucun element de ce stub ne la produit.
    `get_quality_report` leve OSError pour emprunter la branche d'echec par
    film, qui est precisement celle dont les lignes etaient orphelines.
    """
    store = SimpleNamespace(run=SimpleNamespace(list_runs=lambda limit=20: [{"run_id": RUN_ID}]))
    return SimpleNamespace(
        settings=SimpleNamespace(
            get_settings=lambda: {
                "state_dir": tmp_state_dir,
                # coupe la branche perceptuelle auto : hors sujet ici
                "perceptual_auto_on_quality": False,
            }
        ),
        _get_or_create_infra=lambda _state_dir: (store, None),
        run=SimpleNamespace(
            get_plan=lambda _rid: {
                "ok": True,
                "rows": [{"row_id": r} for r in row_ids],
            }
        ),
        quality=SimpleNamespace(
            get_quality_report=lambda *_a, **_k: (_ for _ in ()).throw(OSError("probe indisponible"))
        ),
    )


class RecomputeWorkerCarriesTheRunIdTests(_WorkerLogContextCase):
    module_logger_name = "cinesort.ui.api.quality_audit_support"

    def _run_job(self, tmp_state_dir: str, row_ids: List[str]) -> Dict[str, Any]:
        api = _fake_api_for_recompute(tmp_state_dir, row_ids)
        res = quality_audit_support.recompute_all_scores(api)
        self.assertTrue(res.get("ok"), f"le job doit demarrer : {res}")
        job_id = str(res["job_id"])
        self._wait_until(
            lambda: quality_audit_support.get_recompute_job_status(api, job_id).get("status") in ("done", "failed"),
            f"le job {job_id}",
        )
        return quality_audit_support.get_recompute_job_status(api, job_id)

    def test_per_film_failures_logged_by_the_worker_carry_the_run_id(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory(prefix="cinesort_594_") as tmp:
            status = self._run_job(tmp, ["row-a", "row-b"])

        self.assertEqual(status["errors"], 2, "les 2 films doivent etre comptes en echec")
        run_ids = self.handler.run_ids_for("recompute_worker error row_id=")
        self.assertEqual(len(run_ids), 2, "une ligne d'echec par film")
        self.assertEqual(
            set(run_ids),
            {RUN_ID},
            "les lignes du worker doivent porter le run_id du job, pas la sentinelle '-'",
        )

    def test_the_worker_does_not_inherit_a_stale_request_id(self) -> None:
        """Garde anti-valeur-fausse : la requete REST est finie, son id ne suit pas.

        Le thread parent (ici : le thread de test, qui joue le dispatch REST)
        porte un request_id. Le worker demarre APRES la reponse HTTP ; lui
        attribuer cet identifiant ferait croire que la requete a emis des
        lignes des minutes plus tard.
        """
        import tempfile

        set_request_id("deadbeef")
        with tempfile.TemporaryDirectory(prefix="cinesort_594_") as tmp:
            self._run_job(tmp, ["row-a"])

        req_ids = self.handler.request_ids_for("recompute_worker error row_id=")
        self.assertEqual(req_ids, ["-"], "le request_id de la requete terminee ne doit pas etre reporte")


# ---------------------------------------------------------------------------
# queue_perceptual_analyses -> _run_perceptual_job (paires)
# ---------------------------------------------------------------------------


class PerceptualPairJobCarriesThePairRunIdTests(_WorkerLogContextCase):
    module_logger_name = "cinesort.ui.api.perceptual_support"

    def _drain(self, api: Any, job_id: str) -> Dict[str, Any]:
        self._wait_until(
            lambda: (
                perceptual_support.get_perceptual_job_status(api, job_id).get("status")
                in ("done", "error", "cancelled")
            ),
            f"le job perceptuel {job_id}",
        )
        return perceptual_support.get_perceptual_job_status(api, job_id)

    def test_each_pair_is_logged_under_its_own_run_id(self) -> None:
        """`_normalize_pairs` n'impose aucun run_id commun : chaque paire a le sien.

        Prendre `pairs[0]["run_id"]` pour tout le job attribuerait a un run des
        lignes appartenant a un autre — une valeur fausse, pas une absence.
        """
        seen: List[tuple] = []

        def _fake_compare(_api: Any, run_id: str, row_a: str, _row_b: str, _options: Any) -> Dict[str, Any]:
            # Le stub OBSERVE depuis l'interieur du worker ; il ne pose aucun
            # ContextVar. Retirer `set_run_id` de la production rend ce test rouge.
            perceptual_support.logger.info("compare_perceptual sonde row=%s", row_a)
            seen.append((run_id, row_a))
            return {"ok": True}

        pairs = [
            {"run_id": RUN_ID, "row_a": "A1", "row_b": "A2"},
            {"run_id": OTHER_RUN_ID, "row_a": "B1", "row_b": "B2"},
        ]
        api = SimpleNamespace()
        with patch.object(perceptual_support, "compare_perceptual", _fake_compare):
            res = perceptual_support.queue_perceptual_analyses(api, pairs, {})
            self.assertTrue(res.get("ok"), f"le job doit demarrer : {res}")
            status = self._drain(api, str(res["job_id"]))

        self.assertEqual(status["status"], "done")
        self.assertEqual(len(seen), 2, "les deux paires doivent avoir ete traitees")
        self.assertEqual(self.handler.run_ids_for("compare_perceptual sonde row=A1"), [RUN_ID])
        self.assertEqual(self.handler.run_ids_for("compare_perceptual sonde row=B1"), [OTHER_RUN_ID])

    def test_job_level_lines_are_not_attributed_to_the_last_pair(self) -> None:
        """Les lignes du garde-fou decrivent le JOB, pas un run : elles restent a '-'.

        Estampiller le garde-fou avec le run_id de la derniere paire traitee
        serait plus trompeur que la sentinelle : le plantage peut n'avoir aucun
        rapport avec ce run-la.
        """

        def _boom(_api: Any, _run_id: str, _row_a: str, _row_b: str, _options: Any) -> Dict[str, Any]:
            # RuntimeError : hors du catch etroit de la boucle -> garde-fou large.
            raise RuntimeError("plantage inattendu")

        pairs = [{"run_id": RUN_ID, "row_a": "A1", "row_b": "A2"}]
        api = SimpleNamespace()
        with patch.object(perceptual_support, "compare_perceptual", _boom):
            res = perceptual_support.queue_perceptual_analyses(api, pairs, {})
            status = self._drain(api, str(res["job_id"]))

        self.assertEqual(status["status"], "error", "le garde-fou doit finaliser le job")
        self.assertEqual(self.handler.run_ids_for("a echoue"), ["-"])


# ---------------------------------------------------------------------------
# queue_perceptual_batch -> _run_perceptual_batch_job (un seul run_id)
# ---------------------------------------------------------------------------


class PerceptualBatchJobCarriesTheRunIdTests(_WorkerLogContextCase):
    module_logger_name = "cinesort.ui.api.perceptual_support"

    def test_the_whole_batch_thread_is_stamped_with_the_run_id(self) -> None:
        def _fake_batch(
            _api: Any,
            _run_id: str,
            row_ids: List[str],
            _options: Optional[Dict[str, Any]] = None,
            progress_cb: Any = None,
        ) -> Dict[str, Any]:
            perceptual_support.logger.info("analyze_perceptual_batch sonde n=%d", len(row_ids))
            if progress_cb:
                progress_cb(len(row_ids), len(row_ids))
            return {"ok": True, "total": len(row_ids), "results": [], "errors": []}

        api = SimpleNamespace()
        with patch.object(perceptual_support, "analyze_perceptual_batch", _fake_batch):
            res = perceptual_support.queue_perceptual_batch(api, RUN_ID, ["r1", "r2"], {})
            self.assertTrue(res.get("ok"), f"le job doit demarrer : {res}")
            job_id = str(res["job_id"])
            self._wait_until(
                lambda: perceptual_support.get_perceptual_job_status(api, job_id).get("status") in ("done", "error"),
                f"le batch perceptuel {job_id}",
            )

        self.assertEqual(self.handler.run_ids_for("analyze_perceptual_batch sonde"), [RUN_ID])


if __name__ == "__main__":
    unittest.main()

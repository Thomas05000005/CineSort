"""Regle inviolable n4, deux gardes d'OBSERVABILITE qui tombaient avec la base.

`sqlite3.Error` n'herite PAS de `OSError`. Les deux sites corriges ici ne sont
pas destructifs : ils OBSERVENT (journaliser une erreur d'API, recalculer des
scores). Sur un tel chemin, l'ajout de `sqlite3.Error` est le geste que
`tests/test_sqlite_error_hors_oserror_cliquet.py` documente comme correct — il ne
transforme aucun echec en succes silencieux, il rend au contraire ATTEIGNABLES
deux annonces d'echec qui ne pouvaient pas se produire.

1. `CineSortApi.log_api_exception` est la frontiere d'erreur de TOUTE l'API
   (21 sites d'appel, dont l'apply et le tableau de bord). Ses deux acces a la
   base — `_find_run_row` (lecture) puis `store.run.insert_error` (ECRITURE) —
   ne rattrapaient pas `sqlite3.Error`. Un « database is locked » s'echappait
   donc de la fonction qui journalise les erreurs, et emportait avec lui :

     - le `return _err_response(...)` que l'appelant execute APRES elle (le
       message precis — « plan corrompu : N lignes illisibles » — est remplace
       par un 500 generique) ;
     - l'inscription en base de l'erreur d'origine ;
     - la notification au CENTRE DE NOTIFICATIONS et le hook `post_error`,
       qui vivent tous deux APRES le bloc fautif.

   L'ironie est mesurable dans `dashboard_support.get_dashboard`, dont le
   commentaire dit que son `except Exception` existe pour « run obsolete + DB
   locked » : sa reponse degradee etait justement perdue quand la base
   verrouillait.

2. `quality_audit_support._recompute_worker` isole chaque film (« on continue en
   cas d'erreur sur un film »). `get_quality_report` PERSISTE son rapport : un
   verrou transitoire sur UN film echappait au filet per-film, remontait au
   `except Exception` de fin de fonction et faisait passer le job ENTIER en
   `failed`. Les films suivants n'etaient jamais rescores, alors que l'ecran
   Qualite sait deja afficher « X/N OK, E echec(s) » depuis `errors`.
"""

from __future__ import annotations

import sqlite3
import unittest
from types import SimpleNamespace
from typing import Any, Dict, List

from cinesort.ui.api import quality_audit_support
from cinesort.ui.api.cinesort_api import CineSortApi


class _StoreQuiVerrouille:
    """Store minimal dont `run.insert_error` echoue toujours en SQLite."""

    def __init__(self, exc: BaseException | None = None) -> None:
        self.run = self
        self.appels: List[Dict[str, Any]] = []
        self._exc = exc or sqlite3.OperationalError("database is locked")

    def insert_error(self, **kwargs: Any) -> None:
        self.appels.append(kwargs)
        raise self._exc


class _StoreOk:
    def __init__(self) -> None:
        self.run = self
        self.appels: List[Dict[str, Any]] = []

    def insert_error(self, **kwargs: Any) -> None:
        self.appels.append(kwargs)


def _faux_api(*, find_run_row_exc: BaseException | None = None) -> SimpleNamespace:
    """`self` minimal pour executer le VRAI corps de `log_api_exception`.

    On n'instancie PAS `CineSortApi` : sa construction resout l'etat reel
    (`%LOCALAPPDATA%/CineSort`, cf. `tests/_etat_reel_guard.py`). On appelle donc
    la methode NON LIEE sur ce faux `self` — le corps execute est celui de la
    production, ce qui est justement ce que la regle « injecter la panne a la
    couche de PRODUCTION » demande.
    """
    notifications: List[tuple] = []
    hooks: List[tuple] = []

    def _find_run_row(_rid: str) -> Any:
        if find_run_row_exc is not None:
            raise find_run_row_exc
        return None

    faux = SimpleNamespace(
        _sanitize_log_extra=lambda extra: dict(extra or {}),
        # Non-`Path` : court-circuite la lecture de settings.json (aucune E/S).
        _get_state_dir=lambda: None,
        _is_valid_run_id=lambda rid: bool(str(rid or "").strip()),
        _find_run_row=_find_run_row,
        _debug_enabled=lambda _settings: False,
        _debug_log=lambda **_kwargs: None,
        _notify=SimpleNamespace(notify=lambda *a, **k: notifications.append((a, k))),
        _dispatch_plugin_hook=lambda *a, **k: hooks.append((a, k)),
    )
    faux.notifications = notifications
    faux.hooks = hooks
    return faux


class LogApiExceptionToleranceSqliteTests(unittest.TestCase):
    """La frontiere d'erreur de l'API ne doit jamais lever elle-meme."""

    def _appeler(self, faux: SimpleNamespace, store: Any) -> None:
        CineSortApi.log_api_exception(
            faux,
            "apply",
            ValueError("plan corrompu : 3 lignes illisibles"),
            run_id="20260821_120000_000_000",
            extra={"phase": "load_context"},
            store=store,
        )

    def test_ecriture_verrouillee_ne_sort_pas_de_la_frontiere(self) -> None:
        """Le coeur du finding : `insert_error` verrouille -> aucune exception."""
        faux = _faux_api()
        store = _StoreQuiVerrouille()

        with self.assertLogs("cinesort.ui.api.cinesort_api", level="WARNING") as journaux:
            self._appeler(faux, store)

        self.assertEqual(len(store.appels), 1, "l'ecriture doit avoir ete TENTEE")
        self.assertTrue(
            any("API_EXCEPTION_PERSIST_FAILED" in ligne for ligne in journaux.output),
            f"l'echec de persistance doit rester visible : {journaux.output}",
        )

    def test_le_canal_qui_atteint_l_utilisateur_survit_au_verrou(self) -> None:
        """Asserter ce que SEUL le correctif produit : le centre de notifications
        et le hook `post_error` vivent APRES le bloc fautif. Sans le correctif ils
        n'etaient jamais atteints."""
        faux = _faux_api()

        self._appeler(faux, _StoreQuiVerrouille())

        self.assertEqual(len(faux.notifications), 1, "la notification critique doit partir malgre le verrou")
        self.assertEqual(len(faux.hooks), 1, "le hook post_error doit etre dispatche malgre le verrou")

    def test_corruption_de_base_toleree_aussi(self) -> None:
        faux = _faux_api()

        self._appeler(faux, _StoreQuiVerrouille(sqlite3.DatabaseError("database disk image is malformed")))

        self.assertEqual(len(faux.notifications), 1)

    def test_resolution_du_run_verrouillee_ne_sort_pas_non_plus(self) -> None:
        """`_find_run_row` interroge `store.run.get_run` sur chaque store connu."""
        faux = _faux_api(find_run_row_exc=sqlite3.OperationalError("database is locked"))

        self._appeler(faux, _StoreOk())

        self.assertEqual(len(faux.notifications), 1, "un verrou sur la RESOLUTION du run ne doit rien emporter")

    def test_une_erreur_de_programmation_reste_fatale(self) -> None:
        """Garde anti-sur-correction : pas d'`except Exception` deguise."""
        faux = _faux_api()

        with self.assertRaises(AttributeError):
            self._appeler(faux, _StoreQuiVerrouille(AttributeError("surface de store renommee")))

    def test_chemin_nominal_inchange(self) -> None:
        """NON-REGRESSION : sans verrou, l'erreur est bien inscrite en base."""
        faux = _faux_api()
        store = _StoreOk()

        self._appeler(faux, store)

        self.assertEqual(len(store.appels), 1)
        self.assertEqual(store.appels[0]["step"], "apply")
        self.assertEqual(store.appels[0]["code"], "ValueError")
        self.assertEqual(len(faux.notifications), 1)


class RecomputeWorkerToleranceSqliteTests(unittest.TestCase):
    """Un verrou sur UN film ne doit pas faire tomber le job ENTIER."""

    def setUp(self) -> None:
        self.job_id = "recompute_test_sqlite"
        with quality_audit_support._RECOMPUTE_JOBS_LOCK:
            quality_audit_support._RECOMPUTE_JOBS[self.job_id] = {
                "job_id": self.job_id,
                "run_id": "run-1",
                "status": "pending",
                "progress": 0,
                "total": 3,
                "errors": 0,
                "started_ts": 0.0,
                "ended_ts": None,
                "error": None,
            }
        self.addCleanup(self._nettoyer)

    def _nettoyer(self) -> None:
        with quality_audit_support._RECOMPUTE_JOBS_LOCK:
            quality_audit_support._RECOMPUTE_JOBS.pop(self.job_id, None)

    def _api(self, exc: BaseException) -> SimpleNamespace:
        vus: List[str] = []

        def _get_quality_report(_run_id: str, row_id: str, _opts: Dict[str, Any]) -> Dict[str, Any]:
            vus.append(row_id)
            if row_id == "r2":
                raise exc
            return {"ok": True}

        api = SimpleNamespace(
            quality=SimpleNamespace(get_quality_report=_get_quality_report),
            # Toggle perceptuel absent -> la branche post-boucle ne lance rien.
            settings=SimpleNamespace(get_settings=lambda: {"perceptual_auto_on_quality": False}),
        )
        api.vus = vus
        return api

    def _etat(self) -> Dict[str, Any]:
        with quality_audit_support._RECOMPUTE_JOBS_LOCK:
            return dict(quality_audit_support._RECOMPUTE_JOBS[self.job_id])

    def test_verrou_sur_un_film_ne_tue_pas_le_job(self) -> None:
        api = self._api(sqlite3.OperationalError("database is locked"))

        quality_audit_support._recompute_worker(api, self.job_id, "run-1", ["r1", "r2", "r3"])

        etat = self._etat()
        self.assertEqual(api.vus, ["r1", "r2", "r3"], "les films SUIVANTS doivent etre traites")
        self.assertEqual(etat["status"], "done", f"le job ne doit plus tomber en failed : {etat}")
        self.assertEqual(etat["errors"], 1, "l'echec doit rester COMPTE, pas efface")
        self.assertEqual(etat["progress"], 3)

    def test_une_erreur_de_programmation_fait_toujours_echouer_le_job(self) -> None:
        """Garde anti-sur-correction : le filet per-film reste etroit."""
        api = self._api(AttributeError("facade quality renommee"))

        quality_audit_support._recompute_worker(api, self.job_id, "run-1", ["r1", "r2", "r3"])

        etat = self._etat()
        self.assertEqual(etat["status"], "failed", f"une erreur de programmation doit rester fatale : {etat}")
        self.assertEqual(api.vus, ["r1", "r2"], "le job s'arrete au film fautif")

    def test_chemin_nominal_inchange(self) -> None:
        """NON-REGRESSION : sans verrou, 3 films, zero erreur."""

        def _ok(_run_id: str, _row_id: str, _opts: Dict[str, Any]) -> Dict[str, Any]:
            return {"ok": True}

        api = SimpleNamespace(
            quality=SimpleNamespace(get_quality_report=_ok),
            settings=SimpleNamespace(get_settings=lambda: {"perceptual_auto_on_quality": False}),
        )

        quality_audit_support._recompute_worker(api, self.job_id, "run-1", ["r1", "r2", "r3"])

        etat = self._etat()
        self.assertEqual(etat["status"], "done")
        self.assertEqual(etat["errors"], 0)
        self.assertEqual(etat["progress"], 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)

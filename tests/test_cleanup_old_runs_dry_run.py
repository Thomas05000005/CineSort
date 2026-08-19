"""Issue #1022 — `cleanup_old_runs` etait la SEULE frontiere destructive sans apercu.

Toutes ses jumelles ont `dry_run=True` par defaut — `purge_quarantine_bucket`,
`purge_review_bucket_all`, `reset_quality_profile`, `reset_all_user_data`. Ce
defaut n'est pas un confort : il vient du durcissement des purges, ou un POST au
corps vide supprimait. `cleanup_old_runs` y avait echappe.

Le seul appelant qui doive REELLEMENT supprimer est le cron de retention, et il
le declare desormais explicitement plutot que de dependre d'un defaut — sinon
faire passer la route en apercu ETEIGNAIT la retention en silence, ce qui est
exactement la famille « un correctif peut eteindre une garde ».

Second volet, plus discret : `sqlite3.Error` N'HERITE PAS de `OSError` (regle
inviolable n4). Les deux `except` de la boucle ne le nommaient pas, donc un
verrou transitoire (`database is locked`) sortait de la fonction et abandonnait
les stores suivants — une passe entiere perdue pour un run.
"""

from __future__ import annotations

import sqlite3
import unittest
from typing import Any, Dict, List
from unittest import mock

from cinesort.ui.api import history_support


class _FauxRunRepo:
    """Repository de run minimal, qui COMPTE les suppressions reelles."""

    def __init__(self, run_ids: List[str], leve_sur: str | None = None) -> None:
        self._run_ids = list(run_ids)
        self._leve_sur = leve_sur
        self.supprimes: List[str] = []

    def list_runs_older_than(self, cutoff_ts: float) -> List[str]:  # noqa: ARG002
        return list(self._run_ids)

    def delete_run(self, rid: str) -> None:
        if rid == self._leve_sur:
            raise sqlite3.OperationalError("database is locked")
        self.supprimes.append(rid)


class _FauxStore:
    def __init__(self, repo: _FauxRunRepo) -> None:
        self.run = repo


class _FauxApi:
    def __init__(self, store: _FauxStore) -> None:
        self._store = store
        self._state_dir = "/tmp/etat"
        self._runs_lock = mock.MagicMock()
        self._runs_lock.__enter__ = lambda *_a: None
        self._runs_lock.__exit__ = lambda *_a: False
        self._infra_by_state_dir: Dict[str, Any] = {"d": (store, None)}

    def _get_or_create_infra(self, _state_dir: Any) -> Any:
        return self._store, None


class DryRunEstLeDefautTests(unittest.TestCase):
    """ROUGE avant le correctif : la fonction ne prenait pas `dry_run`."""

    def _api(self, **kw: Any) -> tuple[_FauxApi, _FauxRunRepo]:
        repo = _FauxRunRepo(["r1", "r2", "r3"], **kw)
        return _FauxApi(_FauxStore(repo)), repo

    def test_sans_argument_rien_n_est_supprime(self):
        """Le defaut est l'APERCU : un appel nu ne doit rien detruire."""
        api, repo = self._api()
        res = history_support.cleanup_old_runs(api, retention_days=90)
        self.assertEqual(repo.supprimes, [], "un appel par defaut a SUPPRIME des runs")
        self.assertTrue(res["dry_run"], "la reponse doit annoncer l'apercu")

    def test_l_apercu_annonce_ce_qui_serait_supprime(self):
        """Un apercu qui rend 0 serait inutilisable : l'utilisateur doit voir
        la liste AVANT de confirmer."""
        api, _repo = self._api()
        res = history_support.cleanup_old_runs(api, retention_days=90)
        self.assertEqual(res["deleted_count"], 3)
        self.assertEqual(sorted(res["deleted_run_ids"]), ["r1", "r2", "r3"])

    def test_dry_run_false_supprime_reellement(self):
        """Contre-test : l'apercu ne doit pas devenir une impasse."""
        api, repo = self._api()
        res = history_support.cleanup_old_runs(api, retention_days=90, dry_run=False)
        self.assertEqual(sorted(repo.supprimes), ["r1", "r2", "r3"])
        self.assertFalse(res["dry_run"])
        self.assertEqual(res["deleted_count"], 3)


class UnRunVerrouilleNEmportePasLesAutresTests(unittest.TestCase):
    """`sqlite3.Error` n'herite pas de `OSError` — regle inviolable n4."""

    def test_un_verrou_sur_un_run_laisse_purger_les_autres(self):
        """ROUGE avant le correctif : l'OperationalError echappait au tuple,
        sortait de la fonction, et les runs suivants n'etaient jamais traites."""
        repo = _FauxRunRepo(["r1", "r2", "r3"], leve_sur="r2")
        api = _FauxApi(_FauxStore(repo))
        res = history_support.cleanup_old_runs(api, retention_days=90, dry_run=False)
        self.assertEqual(sorted(repo.supprimes), ["r1", "r3"], "r3 doit etre purge malgre l'echec sur r2")
        self.assertEqual(res["deleted_count"], 2, "le compte rendu ne doit pas mentir sur r2")
        self.assertTrue(res["ok"], "un verrou transitoire n'est pas un echec global")


class LeCronDeclareSonIntentionTests(unittest.TestCase):
    """Faire passer la route en apercu ne doit PAS eteindre la retention."""

    def test_le_cron_passe_dry_run_false(self):
        """C'est la famille « un correctif peut eteindre une garde » : sans cet
        appel explicite, le durcissement de la route aurait arrete la purge
        automatique en silence."""
        from cinesort.app import retention_cleanup

        vus: Dict[str, Any] = {}

        class _FauxRunFacade:
            def cleanup_old_runs(self, retention_days: int, dry_run: bool = True) -> Dict[str, Any]:
                vus["retention_days"] = retention_days
                vus["dry_run"] = dry_run
                return {"ok": True, "deleted_count": 0, "deleted_run_ids": [], "retention_days": retention_days}

        faux = mock.Mock()
        faux.run = _FauxRunFacade()
        retention_cleanup._run_cleanup_once(faux, 90)
        self.assertEqual(vus.get("retention_days"), 90)
        self.assertIs(vus.get("dry_run"), False, "le cron doit demander une suppression REELLE")


if __name__ == "__main__":
    unittest.main()

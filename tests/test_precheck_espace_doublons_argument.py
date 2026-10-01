"""Le pre-check d'espace du SECOND volume n'a JAMAIS vu un seul doublon ecarte.

`_validate_apply` construit les `bucket_keys` passees a
`check_disk_space_for_apply` : les row_id dont le film part dans un BAC sous
`<run_dir>/_review`, donc sur le volume du `state_dir` (en pratique
`%LOCALAPPDATA%`) et PAS sur celui de la bibliotheque.

LE DEFAUT. La source « doublons ecartes » appelait
`_resolve_duplicate_loser_row_ids(merged_decisions, log_fn)`. `merged_decisions`
est un `Dict[str, Dict]` indexe par `row_id` (`cinesort_api._merge_decisions`),
alors que cette fonction attend une SEQUENCE de decisions de doublons :

    usable = [dec for dec in (decisions or []) if isinstance(dec, dict)]

Iterer un dict rend ses CLES — des `str`. Aucune n'est un `dict`, donc `usable`
sortait vide et la fonction rendait **toujours** `set()`.

CE QUE CA COUTE. Le bloc du second volume de `check_disk_space_for_apply` est
garde par `if state_dir is not None and bucket_keys:`. Un apply dont les seuls
fichiers partant en bac sont des doublons perdants — le cas NOMINAL d'un
produit dont la detection de doublons est la fonction phare — arrivait donc avec
`bucket_keys` VIDE : le volume qui recoit les fichiers n'etait pas verifie du
tout. C'est la panne que H-2 / #989 existe pour empecher, et le message d'erreur
de cette garde promet pourtant de couvrir « les doublons ecartes ».

POURQUOI AUCUN GARDE NE POUVAIT LE VOIR. `tests/test_disk_space_second_volume.py`
porte cet invariant depuis le 2026-08-06 et il est juste — mais il appelle
`check_disk_space_for_apply` avec des `bucket_keys` FOURNIES A LA MAIN. Il
eprouve la DECISION, jamais le PRODUCTEUR de son argument. C'est la regle
« tester la decision ne dit RIEN du site d'appel » de `CLAUDE.md` : il faut
executer le VRAI corps de la fonction appelante et eprouver ses ARGUMENTS.

Ces tests-ci executent donc `_validate_apply` en apply REEL (`dry_run=False`,
seul mode ou le pre-check tourne) et capturent ce qui arrive reellement a
`check_disk_space_for_apply`.
"""

from __future__ import annotations

import shutil
import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from cinesort.ui.api import apply_support


class _FauxApplyRepo:
    """Le repo `store.apply`, cote decisions de doublons.

    `list_duplicate_decisions` rend ce que la BASE contient : une LISTE de
    dicts, chacun portant `winner_row_id` / `loser_row_ids` / `decided_ts`.
    C'est exactement ce que `_execute_apply` lui passe deja pour ROUTER les
    perdants vers le bucket — l'autre site d'appel, celui qui etait correct.
    """

    def __init__(self, decisions: List[Dict[str, Any]]) -> None:
        self._decisions = decisions
        self.vu_run_id: Any = None

    def list_duplicate_decisions(self, *, run_id):
        self.vu_run_id = run_id
        return list(self._decisions)


class _FauxFilmModal:
    def __init__(self, marques: List[Dict[str, Any]]) -> None:
        self._marques = marques

    def get_tmdb_override(self, *, run_id, row_id):
        return None

    def list_marked_for_deletion(self, *, run_id):
        return list(self._marques)


class _FauxStore:
    def __init__(self, decisions_doublons, marques) -> None:
        self.apply = _FauxApplyRepo(decisions_doublons)
        self.film_modal = _FauxFilmModal(marques)


class _FauxApi:
    def __init__(self, ctx) -> None:
        self._ctx = ctx

    def _is_valid_run_id(self, run_id):
        return bool(run_id)

    def _run_context_for_apply(self, _run_id):
        return self._ctx

    def _load_decisions_from_validation(self, _run_paths):
        return {}

    def _merge_decisions(self, incoming, disk):
        # Meme FORME que la production : un dict indexe par row_id. C'est
        # precisement cette forme qui etait passee au resolveur de doublons.
        merged = dict(disk or {})
        merged.update(incoming or {})
        return merged

    def _normalize_decisions_for_rows(self, rows, merged):
        from cinesort.ui.api.run_data_support import normalize_decisions_for_rows

        return normalize_decisions_for_rows(rows, merged)

    def log_api_exception(self, *a, **k):
        pass


class _Capture:
    """Doublure de `check_disk_space_for_apply` qui retient ses arguments."""

    def __init__(self) -> None:
        self.appels: List[Dict[str, Any]] = []

    def __call__(self, cfg, rows, approved_keys, *, state_dir=None, bucket_keys=None):
        self.appels.append(
            {
                "approved_keys": set(approved_keys or ()),
                "state_dir": state_dir,
                "bucket_keys": set(bucket_keys or ()),
            }
        )
        return True, {"message": "OK (doublure de test)"}


class PrecheckEspaceBucketKeysTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = Path(tempfile.mkdtemp(prefix="cinesort_precheck_bac_"))
        self.addCleanup(shutil.rmtree, self._tmp, ignore_errors=True)

    def _lancer(self, *, decisions_doublons, marques=(), approuves=("perdant", "gagnant")):
        """Execute le VRAI corps de `_validate_apply` en apply REEL."""
        rows = [
            SimpleNamespace(row_id="gagnant", proposed_title="Heat", proposed_year=1995, folder=str(self._tmp)),
            SimpleNamespace(row_id="perdant", proposed_title="Heat", proposed_year=1995, folder=str(self._tmp)),
        ]
        run_paths = SimpleNamespace(
            validation_json=self._tmp / "validation.json",
            run_dir=self._tmp / "run",
        )
        cfg = SimpleNamespace(root=self._tmp / "biblio")
        store = _FauxStore(list(decisions_doublons), list(marques))
        api = _FauxApi((cfg, run_paths, rows, lambda *_: None, store))
        incoming = {rid: {"ok": True, "title": "Heat", "year": 1995} for rid in approuves}

        capture = _Capture()
        reel = apply_support.check_disk_space_for_apply
        apply_support.check_disk_space_for_apply = capture
        try:
            res = apply_support._validate_apply(
                api,
                "run-1",
                incoming,
                dry_run=False,
                quarantine_unapproved=False,
            )
        finally:
            apply_support.check_disk_space_for_apply = reel
        return res, capture, store

    # --- ANCRAGE : sans ces deux assertions, les tests ci-dessous seraient vacants.

    def test_le_precheck_est_bien_atteint_en_apply_reel(self) -> None:
        """Si `_validate_apply` sortait en erreur avant le pre-check, un test qui
        n'asserte que sur `bucket_keys` passerait sur une liste d'appels VIDE."""
        res, capture, _store = self._lancer(
            decisions_doublons=[{"winner_row_id": "gagnant", "loser_row_ids": ["perdant"], "decided_ts": 100.0}]
        )
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(len(capture.appels), 1, "le pre-check d'espace n'a pas ete appele")

    def test_la_base_est_bien_interrogee_sur_le_run(self) -> None:
        """Second ancrage : le resolveur recoit la lecture DB, et sur le bon run."""
        _res, _capture, store = self._lancer(
            decisions_doublons=[{"winner_row_id": "gagnant", "loser_row_ids": ["perdant"], "decided_ts": 100.0}]
        )
        self.assertEqual(
            store.apply.vu_run_id,
            "run-1",
            "`list_duplicate_decisions` n'a pas ete interrogee : la source des doublons n'est pas la base",
        )

    # --- LE DEFAUT

    def test_un_doublon_perdant_est_impute_au_volume_des_bacs(self) -> None:
        """LE test du correctif. Avant : `bucket_keys` vide, donc le bloc du
        second volume entierement saute — aucune verification du disque qui
        recoit le fichier."""
        _res, capture, _store = self._lancer(
            decisions_doublons=[{"winner_row_id": "gagnant", "loser_row_ids": ["perdant"], "decided_ts": 100.0}]
        )
        self.assertIn(
            "perdant",
            capture.appels[0]["bucket_keys"],
            "le doublon perdant n'est pas impute au volume des bacs : le pre-check du "
            "second volume ne verra jamais sa taille",
        )

    def test_le_gagnant_n_est_PAS_impute(self) -> None:
        """Contre-epreuve : le gagnant va a sa destination normale, sur le volume
        de la bibliotheque. L'imputer facturerait deux fois le meme volume."""
        _res, capture, _store = self._lancer(
            decisions_doublons=[{"winner_row_id": "gagnant", "loser_row_ids": ["perdant"], "decided_ts": 100.0}]
        )
        self.assertNotIn("gagnant", capture.appels[0]["bucket_keys"])

    def test_sans_aucun_doublon_le_bloc_reste_inactif(self) -> None:
        """Contre-test indispensable : le correctif ne doit pas inventer de
        `bucket_keys`. Sans lui, « le perdant est impute » serait satisfait par
        n'importe quel ensemble non vide."""
        _res, capture, _store = self._lancer(decisions_doublons=[])
        self.assertEqual(capture.appels[0]["bucket_keys"], set())

    def test_les_marques_pour_suppression_restent_imputes(self) -> None:
        """Non-regression : la seconde source fonctionnait deja, le correctif ne
        la remplace pas."""
        _res, capture, _store = self._lancer(
            decisions_doublons=[],
            marques=[{"row_id": "perdant"}],
        )
        self.assertIn("perdant", capture.appels[0]["bucket_keys"])

    def test_les_deux_sources_se_cumulent(self) -> None:
        _res, capture, _store = self._lancer(
            decisions_doublons=[{"winner_row_id": "gagnant", "loser_row_ids": ["perdant"], "decided_ts": 100.0}],
            marques=[{"row_id": "gagnant"}],
        )
        self.assertEqual(capture.appels[0]["bucket_keys"], {"perdant", "gagnant"})

    def test_un_row_non_approuve_n_est_pas_impute(self) -> None:
        """`_validate_apply` filtre `bucket_keys` sur les approuves : un film non
        approuve ne bougera pas, donc il ne consomme rien sur ce volume."""
        _res, capture, _store = self._lancer(
            decisions_doublons=[{"winner_row_id": "gagnant", "loser_row_ids": ["perdant"], "decided_ts": 100.0}],
            approuves=("gagnant",),
        )
        self.assertNotIn("perdant", capture.appels[0]["bucket_keys"])

    def test_une_base_indisponible_ne_bloque_pas_l_apply(self) -> None:
        """Best-effort assume : le pre-check est un garde, pas une condition. Une
        lecture impossible doit ramener au comportement d'avant, jamais refuser
        un apply legitime."""

        class _RepoVerrouille:
            def list_duplicate_decisions(self, *, run_id):
                raise sqlite3.OperationalError("database is locked")

        res, capture, store = self._lancer(decisions_doublons=[])
        self.assertTrue(res.get("ok"), res)
        store.apply = _RepoVerrouille()
        # Deuxieme passage, repo verrouille : l'ensemble sort partiel, pas d'exception.
        self.assertEqual(
            apply_support._row_ids_partant_en_bac(store, "run-1", lambda *_: None),
            set(),
        )
        self.assertEqual(len(capture.appels), 1)


class LaFormeDeLArgumentTests(unittest.TestCase):
    """Caracterisation du MECANISME : vert avant comme apres le correctif.

    Ces deux assertions ne prouvent pas le correctif — elles documentent
    pourquoi l'ancien argument ne pouvait pas marcher, pour qu'un futur
    refactor ne le remette pas « parce que les deux ont l'air d'etre des
    decisions ».
    """

    def test_un_dict_indexe_par_row_id_rend_toujours_un_ensemble_vide(self) -> None:
        decisions_de_validation = {
            "perdant": {"ok": True, "title": "Heat", "year": 1995},
            "gagnant": {"ok": True, "title": "Heat", "year": 1995},
        }
        self.assertEqual(
            apply_support._resolve_duplicate_loser_row_ids(decisions_de_validation, lambda *_: None),
            set(),
            "iterer un dict rend ses CLES : aucune n'est un dict, le filtre d'entree vide tout",
        )

    def test_une_liste_de_decisions_de_doublons_rend_les_perdants(self) -> None:
        self.assertEqual(
            apply_support._resolve_duplicate_loser_row_ids(
                [{"winner_row_id": "gagnant", "loser_row_ids": ["perdant"], "decided_ts": 1.0}],
                lambda *_: None,
            ),
            {"perdant"},
        )


if __name__ == "__main__":
    unittest.main()

"""Revue post-merge 2026-08-02 — arbitrage laisse ouvert par F07.

SYMPTOME : le badge « ✓ Décidé » d'un groupe de doublons devient INVISIBLE des
que la cle de groupe DERIVE. `_group_key_for` (run_flow_support.py) vaut
`titre.lower()|annee` derive de la decision de Validation ; si l'utilisateur
corrige ensuite l'annee ou le titre, la cle change,
`_annotate_groups_with_decisions` ne retrouve plus la decision persistee et le
groupe repasse « non decide » — alors que la decision EXISTE toujours en base et
sera bien honoree a l'apply (`_resolve_duplicate_loser_row_ids` ne lit que des
row_ids, jamais la cle). Consequences reelles :
  * l'utilisateur ne voit plus sa decision et ne peut plus la reprendre ;
  * « Auto-decider tous » (doublons.js saute les groupes `winner_decided`)
    ECRASE silencieusement son choix.

CORRECTIF : index de REPLI par ENSEMBLE de row_ids arbitres
(frozenset({winner} | losers)), consulte UNIQUEMENT quand la cle ne matche
aucun groupe.

Absence de faux positif — les deux garanties sont testees ici, pas seulement
documentees :
  * egalite d'ENSEMBLE EXACT (recouvrement partiel -> aucun rattachement) ;
  * `find_duplicate_targets` PARTITIONNE les rows (1 row -> 1 seul groupe), donc
    deux groupes ne peuvent pas exposer le meme ensemble de row_ids
    (test_groupes_partitionnent_les_row_ids, sur le VRAI moteur de groupement).

Lancer, depuis la racine du depot :
  ./.venv/Scripts/python.exe -X utf8 -m pytest \
      tests/test_revue_post_merge_f07_badge_decide_cle_derivee.py -q
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, Iterable, List

import cinesort.app.plan_support as plan_support
import cinesort.domain.core as core
from cinesort.ui.api.apply_support import _resolve_duplicate_loser_row_ids
from cinesort.ui.api.run_flow_support import _annotate_groups_with_decisions

RUN_ID = "r_f07_badge"


# ── Harnais ──────────────────────────────────────────────────────────


class _StubApplyRepo:
    def __init__(self, decisions: Iterable[Dict[str, Any]]) -> None:
        self._decisions = [dict(d) for d in decisions]
        self.seen_run_ids: List[str] = []

    def list_duplicate_decisions(self, *, run_id: str) -> List[Dict[str, Any]]:
        self.seen_run_ids.append(str(run_id))
        # Contrat du vrai repo (repositories/apply.py) : ORDER BY decided_ts DESC.
        return [dict(d) for d in sorted(self._decisions, key=lambda d: d["decided_ts"], reverse=True)]


class _StubStore:
    def __init__(self, decisions: Iterable[Dict[str, Any]]) -> None:
        self.apply = _StubApplyRepo(decisions)


def _group(title: str, year: int, row_ids: Iterable[str]) -> Dict[str, Any]:
    """Groupe au format emis par find_duplicate_targets (sans group_key : le
    dict de groupe n'en porte AUCUN, d'ou le fallback titre|annee)."""
    return {
        "title": title,
        "year": year,
        "rows": [{"row_id": rid, "kind": "single"} for rid in row_ids],
    }


def _decision(group_key: str, winner: str, losers: Iterable[str], decided_ts: float) -> Dict[str, Any]:
    return {
        "run_id": RUN_ID,
        "group_key": group_key,
        "winner_row_id": winner,
        "loser_row_ids": list(losers),
        "decided_ts": decided_ts,
        "notes": None,
    }


def _annotate(groups: List[Dict[str, Any]], decisions: Iterable[Dict[str, Any]]) -> _StubStore:
    """Annote `groups` EN PLACE et rend le store, pour inspecter l'appel au repo."""
    store = _StubStore(decisions)
    _annotate_groups_with_decisions({"groups": groups}, RUN_ID, store)
    return store


# ── Le defaut : la cle derive, le badge disparait ────────────────────


class BadgeSurvitALaDeriveDeCleTests(unittest.TestCase):
    def test_annee_corrigee_le_badge_reste_visible(self) -> None:
        """ROUGE avant le correctif : l'annee corrigee 2005 -> 2006 tue la cle."""
        groups = [_group("Le Grand Voyage", 2006, ["r1", "r2"])]
        decisions = [_decision("le grand voyage|2005", winner="r1", losers=["r2"], decided_ts=1000.0)]

        store = _annotate(groups, decisions)

        self.assertEqual(store.apply.seen_run_ids, [RUN_ID], "Les decisions sont relues pour CE run.")
        grp = groups[0]
        self.assertTrue(grp.get("winner_decided"), "Decision persistee -> badge « Decide » attendu malgre la derive.")
        self.assertEqual(grp.get("winner_row_id"), "r1")
        self.assertEqual(grp.get("winner_side"), "a", "r1 est la 1ere row -> cote A.")
        self.assertTrue(grp.get("winner_decision_stale_key"), "Rattachement par row_ids -> marqueur de cle morte.")
        self.assertEqual(grp.get("winner_decision_group_key"), "le grand voyage|2005")

    def test_titre_corrige_le_badge_reste_visible(self) -> None:
        """Meme defaut par l'autre moitie de la cle (le titre)."""
        groups = [_group("Le Grand Voyage", 2005, ["r1", "r2"])]
        decisions = [_decision("le gran voyage|2005", winner="r2", losers=["r1"], decided_ts=1000.0)]

        _annotate(groups, decisions)

        self.assertTrue(groups[0].get("winner_decided"))
        self.assertEqual(groups[0].get("winner_row_id"), "r2")
        self.assertEqual(groups[0].get("winner_side"), "b")

    def test_le_badge_annonce_ce_que_l_apply_fera(self) -> None:
        """Le badge doit designer le MEME gagnant que la reconciliation d'apply.

        C'est tout l'interet du repli : sans lui l'UI affiche « non decide »
        pendant qu'apply deplace bel et bien le perdant.
        """
        groups = [_group("Le Grand Voyage", 2006, ["r1", "r2"])]
        decisions = [_decision("le grand voyage|2005", winner="r1", losers=["r2"], decided_ts=1000.0)]

        _annotate(groups, decisions)

        losers = _resolve_duplicate_loser_row_ids(decisions, lambda _lvl, _msg: None)
        self.assertEqual(losers, {"r2"}, "Pre-requis : apply honore bien la decision malgre la cle morte.")
        winner = groups[0].get("winner_row_id")
        self.assertTrue(groups[0].get("winner_decided"), "L'UI doit voir la decision qu'apply va appliquer.")
        self.assertEqual(winner, "r1")
        self.assertNotIn(winner, losers, "Le gagnant affiche ne doit pas etre un perdant.")


# ── Non-regressions (VERTES des deux cotes du correctif) ─────────────


class PasDeFauxPositifTests(unittest.TestCase):
    def test_cle_courante_prioritaire_sur_le_repli(self) -> None:
        """Chemin nominal inchange : la cle qui matche gagne sur toute cle morte.

        C'est aussi la moitie « annulable » de l'arbitrage : badge revenu,
        l'utilisateur reprend la main en cliquant Garder B. `mark_duplicate_winner`
        reposte la cle COURANTE -> nouvelle ligne (la PK est (run_id, group_key)),
        la ligne morte survit, et c'est la recence qui tranche a l'apply.
        """
        groups = [_group("Le Grand Voyage", 2006, ["r1", "r2"])]
        decisions = [
            _decision("le grand voyage|2005", winner="r1", losers=["r2"], decided_ts=1000.0),
            _decision("le grand voyage|2006", winner="r2", losers=["r1"], decided_ts=2000.0),
        ]

        _annotate(groups, decisions)

        self.assertEqual(groups[0].get("winner_row_id"), "r2", "La decision de la cle COURANTE prime.")
        self.assertEqual(groups[0].get("winner_side"), "b")
        self.assertNotIn("winner_decision_stale_key", groups[0], "Cle matchee -> repli non consulte.")
        losers = _resolve_duplicate_loser_row_ids(decisions, lambda _l, _m: None)
        self.assertEqual(losers, {"r1"}, "L'apply suit la reprise, pas la decision morte.")

    def test_recouvrement_partiel_aucun_rattachement(self) -> None:
        """Ensemble EXACT : {r1,r3} ne se rattache pas au groupe {r1,r2}."""
        groups = [_group("Le Grand Voyage", 2006, ["r1", "r2"])]
        decisions = [_decision("autre titre|1999", winner="r1", losers=["r3"], decided_ts=1000.0)]

        _annotate(groups, decisions)

        self.assertNotIn("winner_decided", groups[0], "Recouvrement partiel -> aucun badge.")

    def test_groupe_elargi_aucun_rattachement(self) -> None:
        """Le groupe a gagne une 3e copie : la decision n'arbitre plus tout le groupe."""
        groups = [_group("Le Grand Voyage", 2006, ["r1", "r2", "r3"])]
        decisions = [_decision("le grand voyage|2005", winner="r1", losers=["r2"], decided_ts=1000.0)]

        _annotate(groups, decisions)

        self.assertNotIn("winner_decided", groups[0], "Membres differents -> pas de badge (choix conservateur).")

    def test_decision_sans_perdant_pas_de_badge_par_repli(self) -> None:
        """Une decision sans perdant n'arbitre RIEN et est deja ignoree a l'apply
        (_resolve_duplicate_loser_row_ids) : la rattacher afficherait un badge
        mensonger. Cf F28, `no_op` de mark_duplicate_winner."""
        groups = [_group("Le Grand Voyage", 2006, ["r1"])]
        decisions = [_decision("le grand voyage|2005", winner="r1", losers=[], decided_ts=1000.0)]

        _annotate(groups, decisions)

        self.assertNotIn("winner_decided", groups[0])
        self.assertEqual(_resolve_duplicate_loser_row_ids(decisions, lambda _l, _m: None), set())

    def test_aucune_decision_aucun_champ_ajoute(self) -> None:
        groups = [_group("Le Grand Voyage", 2006, ["r1", "r2"])]

        _annotate(groups, [])

        self.assertEqual(groups[0].get("rows")[0].get("row_id"), "r1")
        self.assertNotIn("winner_decided", groups[0])

    def test_store_sans_repo_ne_leve_pas(self) -> None:
        data: Dict[str, Any] = {"groups": [_group("Le Grand Voyage", 2006, ["r1", "r2"])]}
        _annotate_groups_with_decisions(data, RUN_ID, None)
        self.assertNotIn("winner_decided", data["groups"][0])


class ReplicaDeLaReconciliationApplyTests(unittest.TestCase):
    def test_deux_cles_mortes_la_plus_recente_gagne(self) -> None:
        """Annee corrigee DEUX fois : deux cles mortes pour le meme ensemble.

        Le repli doit trancher comme apply (recence), sinon le badge annonce un
        gagnant que l'apply contredirait.
        """
        groups = [_group("Le Grand Voyage", 2007, ["r1", "r2"])]
        decisions = [
            _decision("le grand voyage|2005", winner="r1", losers=["r2"], decided_ts=1000.0),
            _decision("le grand voyage|2006", winner="r2", losers=["r1"], decided_ts=2000.0),
        ]

        _annotate(groups, decisions)

        self.assertEqual(groups[0].get("winner_row_id"), "r2", "La decision la plus RECENTE gagne.")
        losers = _resolve_duplicate_loser_row_ids(decisions, lambda _l, _m: None)
        self.assertEqual(losers, {"r1"})
        self.assertNotIn(groups[0].get("winner_row_id"), losers)


# ── La premisse du repli, prouvee sur le VRAI moteur de groupement ───


class GroupesPartitionnentLesRowsTests(unittest.TestCase):
    """`find_duplicate_targets` empile chaque row dans UN SEUL bucket
    `planned_idx[movie_key]` : deux groupes ne peuvent donc jamais partager un
    row_id, ni a fortiori exposer le meme ENSEMBLE de row_ids. C'est ce qui rend
    l'index de repli non ambigu."""

    def setUp(self) -> None:
        self._tmp = tempfile.mkdtemp(prefix="f07_partition_")
        self.root = Path(self._tmp) / "root"
        self.root.mkdir(parents=True, exist_ok=True)

    def tearDown(self) -> None:
        shutil.rmtree(self._tmp, ignore_errors=True)

    def _single(self, row_id: str, folder: Path, title: str, year: int, source_root: str = "") -> core.PlanRow:
        return core.PlanRow(
            row_id=row_id,
            kind="single",
            folder=str(folder),
            video="movie.mkv",
            proposed_title=title,
            proposed_year=year,
            proposed_source="name",
            confidence=70,
            confidence_label="med",
            candidates=[],
            source_root=(source_root or None),
        )

    def test_groupes_partitionnent_les_row_ids(self) -> None:
        rows = [
            self._single("r1", self.root / "A" / "Movie (2020)", "Movie", 2020, str(self.root / "A")),
            self._single("r2", self.root / "B" / "Movie (2020)", "Movie", 2020, str(self.root / "B")),
            self._single("r3", self.root / "A" / "Autre (2020)", "Autre", 2020, str(self.root / "A")),
            self._single("r4", self.root / "B" / "Autre (2020)", "Autre", 2020, str(self.root / "B")),
        ]
        decisions = {r.row_id: {"ok": True, "title": r.proposed_title, "year": r.proposed_year} for r in rows}
        cfg = core.Config(root=self.root, enable_collection_folder=True).normalized()

        data = plan_support.find_duplicate_targets(cfg, rows, decisions)

        self.assertEqual(data["total_groups"], 2, "Deux identites distinctes -> deux groupes.")
        seen: Dict[str, int] = {}
        for idx, grp in enumerate(data["groups"]):
            for item in grp["rows"]:
                rid = str(item["row_id"])
                self.assertNotIn(rid, seen, f"row {rid} present dans 2 groupes -> repli par row_ids ambigu !")
                seen[rid] = idx
        self.assertEqual(sorted(seen), ["r1", "r2", "r3", "r4"])
        sets = [frozenset(str(i["row_id"]) for i in g["rows"]) for g in data["groups"]]
        self.assertEqual(len(set(sets)), len(sets), "Deux groupes ne doivent pas exposer le meme ensemble de rows.")


if __name__ == "__main__":
    unittest.main()

"""Revue R2 vague 3 — 2 defauts de relecture.

D (backend) : _compute_active_insights utilisait run_ids[0] pour l'insight
"Reject" alors que le reste de get_global_stats est passe a latest_scan_rid
(qui exclut les runs utilitaires de bulk-rescan). Apres un re-scan groupe,
run_ids[0] = run parasite (0 perceptual_report) -> l'insight Reject disparait.

B (frontend, verifie ici par assertion sur la source) : le compteur
_renderApplyStep testait `r.decision === "approved"` (minuscule) alors qu'un
bulk-approve pose "APPROVED" (majuscule) -> sous-comptage. Il doit lire la
SOURCE DE VERITE _decisionsState (st.ok), pas la chaine r.decision.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from cinesort.ui.api import dashboard_support


class _FakePerceptual:
    def __init__(self, by_run):
        self._by_run = by_run
        self.warnings_calls = []

    def list_perceptual_reports(self, run_id=None):
        return self._by_run.get(run_id, [])

    def count_v2_warnings_flag(self, flag=None, run_ids=None):
        """Enregistre le PERIMETRE demande — c'est lui que le test inspecte."""
        self.warnings_calls.append(list(run_ids or []))
        total = 0
        for rid in run_ids or []:
            for report in self._by_run.get(rid, []):
                if str(flag or "") in (report.get("adjustments_applied") or ""):
                    total += 1
        return total


class _FakeStore:
    def __init__(self, by_run):
        self.perceptual = _FakePerceptual(by_run)


class ActiveInsightsUsesLatestScanRunTests(unittest.TestCase):
    """D : l'insight Reject suit latest_scan_rid, pas run_ids[0] (le parasite)."""

    def _reject_insight(self, insights):
        return next(
            (i for i in insights if str(i.get("type")) in ("quality_reject", "new_rejects")),
            None,
        )

    def test_reject_insight_follows_latest_scan_rid_not_run_ids0(self):
        real_scan = "20260101_100000"
        rescan_parasite = "20260102_120000"  # plus recent, en tete de run_ids
        store = _FakeStore(
            {
                real_scan: [{"global_tier_v2": "reject"}, {"global_tier_v2": "reject"}],
                rescan_parasite: [],  # le run de rescan n'a aucun report
            }
        )
        # run_ids[0] = le parasite (ordre anti-chronologique), latest_scan_rid = le vrai scan
        insights = dashboard_support._compute_active_insights(
            api=None,
            store=store,
            run_ids=[rescan_parasite, real_scan],
            settings={},
            librarian_data=None,
            latest_scan_rid=real_scan,
        )
        ins = self._reject_insight(insights)
        self.assertIsNotNone(ins, "l'insight Reject doit etre present (2 reject sur le vrai scan)")
        self.assertEqual(int(ins.get("count")), 2)

    def test_without_latest_scan_rid_falls_back_to_run_ids0(self):
        # Retro-compat : si latest_scan_rid n'est pas fourni, comportement d'avant.
        store = _FakeStore({"R1": [{"global_tier_v2": "reject"}]})
        insights = dashboard_support._compute_active_insights(
            api=None, store=store, run_ids=["R1"], settings={}, librarian_data=None
        )
        self.assertIsNotNone(self._reject_insight(insights))


class DnrInsightScopedToLatestScanTests(unittest.TestCase):
    """Audit 2026-08-08 — le jumeau du defaut D, sur l'insight « DNR partiel ».

    L'insight Reject ci-dessus a ete scope au dernier scan, et
    `_compute_v2_tier_distribution` l'a ete aussi (R6-F). L'insight DNR est reste
    le SEUL site de `_compute_active_insights` a consommer `run_ids` entier, soit
    les 20 derniers runs : chaque re-scan re-ecrit une ligne
    `perceptual_reports` par film, donc un meme film etait annonce une fois par
    scan. Le libelle dit « N films », et le clic renvoie vers la Bibliotheque du
    dernier run : le nombre annonce et la liste obtenue divergeaient.
    """

    def _dnr_insight(self, insights):
        return next((i for i in insights if str(i.get("type")) == "dnr_partial"), None)

    def test_dnr_insight_counts_latest_scan_only(self):
        real_scan = "20260101_100000"
        older_scan = "20251231_090000"
        # Le MEME film (une ligne par run) porte le flag dans les deux scans.
        film = {"adjustments_applied": "-6 perceptual_visual (dnr_partial)"}
        store = _FakeStore({real_scan: [film], older_scan: [film]})

        insights = dashboard_support._compute_active_insights(
            api=None,
            store=store,
            run_ids=[real_scan, older_scan],
            settings={},
            librarian_data=None,
            latest_scan_rid=real_scan,
        )

        self.assertEqual(
            store.perceptual.warnings_calls,
            [[real_scan]],
            "le comptage DNR doit porter sur le DERNIER scan, pas sur les 20 derniers runs",
        )
        ins = self._dnr_insight(insights)
        self.assertIsNotNone(ins, "l'insight DNR doit etre present (1 film sur le dernier scan)")
        self.assertEqual(int(ins.get("count")), 1, "un film re-scane reste UN film")

    def test_dnr_insight_falls_back_to_first_run_without_latest(self):
        # Retro-compat : sans latest_scan_rid, on retombe sur le run le plus
        # recent de `run_ids`, jamais sur la liste entiere.
        store = _FakeStore({"R1": [{"adjustments_applied": "-6 perceptual_visual (dnr_partial)"}], "R2": []})
        dashboard_support._compute_active_insights(
            api=None, store=store, run_ids=["R1", "R2"], settings={}, librarian_data=None
        )
        self.assertEqual(store.perceptual.warnings_calls, [["R1"]])


class RenderApplyCounterReadsDecisionStateTests(unittest.TestCase):
    """B : le compteur _renderApplyStep lit _decisionsState, pas la chaine r.decision."""

    def setUp(self):
        self.src = (Path(__file__).resolve().parents[1] / "web" / "dashboard" / "views" / "traitement.js").read_text(
            encoding="utf-8"
        )

    def test_counter_reads_decision_state_map(self):
        i = self.src.index("function _renderApplyStep")
        block = self.src[i : i + 800]
        # doit consulter _decisionsState.get(...) pour le compteur "approved"
        self.assertIn("_decisionsState.get(String(r.row_id", block)
        self.assertIn("st ? st.ok : _defaultDecisionOk(r)", block)
        # et NE DOIT PLUS utiliser l'ancien one-liner base sur la chaine r.decision
        # (forme presente uniquement dans du code, pas dans le commentaire).
        self.assertNotIn("rows.filter((r) => r.decision ===", block)


if __name__ == "__main__":
    unittest.main()

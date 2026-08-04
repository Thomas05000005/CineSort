"""P4.1 : tests pour cinesort/domain/calibration.py + endpoint submit_score_feedback.

Couvre : tier_ordinal, compute_tier_delta, analyze_feedback_bias,
suggest_weight_adjustment, et l'endpoint complet via CineSortApi.
"""

from __future__ import annotations

import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from cinesort.domain.calibration import (
    analyze_feedback_bias,
    compute_tier_delta,
    suggest_weight_adjustment,
    tier_ordinal,
)


class TierOrdinalTests(unittest.TestCase):
    def test_canonical_tiers(self):
        self.assertEqual(tier_ordinal("Reject"), 0)
        self.assertEqual(tier_ordinal("Bronze"), 1)
        self.assertEqual(tier_ordinal("Silver"), 2)
        self.assertEqual(tier_ordinal("Gold"), 3)
        self.assertEqual(tier_ordinal("Platinum"), 4)

    def test_case_insensitive(self):
        self.assertEqual(tier_ordinal("gold"), 3)
        self.assertEqual(tier_ordinal("PLATINUM"), 4)

    def test_legacy_aliases(self):
        self.assertEqual(tier_ordinal("Premium"), tier_ordinal("Platinum"))
        self.assertEqual(tier_ordinal("Bon"), tier_ordinal("Gold"))
        self.assertEqual(tier_ordinal("Moyen"), tier_ordinal("Silver"))
        self.assertEqual(tier_ordinal("Mauvais"), tier_ordinal("Reject"))

    def test_unknown_returns_minus_one(self):
        self.assertEqual(tier_ordinal("Unknown"), -1)
        self.assertEqual(tier_ordinal(""), -1)


class ComputeTierDeltaTests(unittest.TestCase):
    def test_accord(self):
        self.assertEqual(compute_tier_delta("Gold", "Gold"), 0)

    def test_user_higher(self):
        self.assertEqual(compute_tier_delta("Silver", "Gold"), 1)
        self.assertEqual(compute_tier_delta("Bronze", "Platinum"), 3)

    def test_user_lower(self):
        self.assertEqual(compute_tier_delta("Platinum", "Silver"), -2)
        self.assertEqual(compute_tier_delta("Gold", "Bronze"), -2)

    def test_unknown_returns_zero(self):
        self.assertEqual(compute_tier_delta("Gold", "Unknown"), 0)


class AnalyzeFeedbackBiasTests(unittest.TestCase):
    def test_empty_returns_neutral(self):
        r = analyze_feedback_bias([])
        self.assertEqual(r["total_feedbacks"], 0)
        self.assertEqual(r["bias_direction"], "neutral")
        self.assertEqual(r["bias_strength"], "none")

    def test_all_accord(self):
        fbs = [{"tier_delta": 0} for _ in range(10)]
        r = analyze_feedback_bias(fbs)
        self.assertEqual(r["accord_pct"], 100.0)
        self.assertEqual(r["bias_direction"], "neutral")

    def test_underscore_bias(self):
        fbs = [{"tier_delta": 1} for _ in range(10)] + [{"tier_delta": 2} for _ in range(5)]
        r = analyze_feedback_bias(fbs)
        self.assertGreater(r["mean_delta"], 0)
        self.assertEqual(r["bias_direction"], "underscore")
        self.assertIn(r["bias_strength"], ("moderate", "strong"))

    def test_overscore_bias(self):
        fbs = [{"tier_delta": -1} for _ in range(8)] + [{"tier_delta": -2} for _ in range(5)]
        r = analyze_feedback_bias(fbs)
        self.assertLess(r["mean_delta"], 0)
        self.assertEqual(r["bias_direction"], "overscore")

    def test_weak_bias_not_strong(self):
        fbs = [{"tier_delta": 1}, {"tier_delta": 0}, {"tier_delta": 0}, {"tier_delta": 0}]
        r = analyze_feedback_bias(fbs)
        self.assertEqual(r["bias_strength"], "weak")

    def test_category_bias_counts(self):
        fbs = [
            {"tier_delta": 1, "category_focus": "audio"},
            {"tier_delta": 1, "category_focus": "audio"},
            {"tier_delta": 1, "category_focus": "video"},
            {"tier_delta": 1, "category_focus": None},
        ]
        r = analyze_feedback_bias(fbs)
        self.assertEqual(r["category_bias"]["audio"], 2)
        self.assertEqual(r["category_bias"]["video"], 1)
        self.assertEqual(r["category_bias"]["extras"], 0)


class SuggestWeightAdjustmentTests(unittest.TestCase):
    def test_no_suggestion_if_weak_bias(self):
        bias = {
            "bias_direction": "neutral",
            "bias_strength": "none",
            "category_bias": {"video": 0, "audio": 0, "extras": 0},
            "total_feedbacks": 0,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        self.assertIsNone(r)

    def test_underscore_audio_increases_audio_weight(self):
        # Bias underscore + catégorie audio pointée → audio weight augmente
        bias = {
            "bias_direction": "underscore",
            "bias_strength": "moderate",
            "category_bias": {"video": 1, "audio": 5, "extras": 0},
            "total_feedbacks": 6,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        self.assertIsNotNone(r)
        assert r is not None
        self.assertEqual(r["focus_category"], "audio")
        self.assertGreater(r["to"]["audio"], r["from"]["audio"])
        # Somme conservée
        self.assertEqual(sum(r["to"].values()), sum(r["from"].values()))

    def test_overscore_video_decreases_video_weight(self):
        bias = {
            "bias_direction": "overscore",
            "bias_strength": "strong",
            "category_bias": {"video": 8, "audio": 1, "extras": 0},
            "total_feedbacks": 9,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        assert r is not None
        self.assertEqual(r["focus_category"], "video")
        self.assertLess(r["to"]["video"], r["from"]["video"])

    def test_no_category_pointed_returns_none(self):
        bias = {
            "bias_direction": "underscore",
            "bias_strength": "moderate",
            "category_bias": {"video": 0, "audio": 0, "extras": 0},
            "total_feedbacks": 5,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        self.assertIsNone(r)

    def test_rationale_contains_explanation(self):
        bias = {
            "bias_direction": "underscore",
            "bias_strength": "moderate",
            "category_bias": {"video": 0, "audio": 5, "extras": 0},
            "total_feedbacks": 5,
        }
        r = suggest_weight_adjustment(bias, {"video": 60, "audio": 30, "extras": 10})
        assert r is not None
        self.assertIn("audio", r["rationale"].lower())
        self.assertIn("5", r["rationale"])

    def test_extreme_weights_invariant_sum_or_none(self):
        # Cas pathologique : poids extremes (focus presque sature, autres au plancher).
        # L'avant-correctif drift de la somme (91 -> 92) car le clamp [1, 90] sur le
        # dernier ajustement masquait l'impossibilite. La fonction doit soit retourner
        # un suggestion qui conserve la somme, soit None (configuration insatisfiable).
        bias = {
            "bias_direction": "underscore",
            "bias_strength": "strong",
            "category_bias": {"video": 5, "audio": 0, "extras": 0},
            "total_feedbacks": 5,
        }
        weights = {"video": 89, "audio": 1, "extras": 1}
        r = suggest_weight_adjustment(bias, weights)
        if r is not None:
            self.assertEqual(sum(r["to"].values()), sum(weights.values()))

    def test_normal_weights_invariant_holds(self):
        # Cas nominal : la somme doit toujours etre conservee.
        bias = {
            "bias_direction": "overscore",
            "bias_strength": "moderate",
            "category_bias": {"video": 5, "audio": 0, "extras": 0},
            "total_feedbacks": 5,
        }
        weights = {"video": 60, "audio": 30, "extras": 10}
        r = suggest_weight_adjustment(bias, weights)
        assert r is not None
        self.assertEqual(sum(r["to"].values()), sum(weights.values()))


class SubmitFeedbackIntegrationTests(unittest.TestCase):
    """End-to-end : créer un run, soumettre feedback, lire calibration report."""

    def setUp(self):
        import cinesort.domain.core as core

        self._tmp = tempfile.mkdtemp(prefix="cinesort_calib_")
        self.root = Path(self._tmp) / "root"
        self.state_dir = Path(self._tmp) / "state"
        self.root.mkdir(parents=True)
        self.state_dir.mkdir(parents=True)
        # Issue #86 : mock.patch.object pour auto-restore safe meme si exception
        _p_min_video = mock.patch.object(core, "MIN_VIDEO_BYTES", 1)
        _p_min_video.start()
        self.addCleanup(_p_min_video.stop)

    def tearDown(self):

        shutil.rmtree(self._tmp, ignore_errors=True)

    def test_submit_feedback_without_quality_report_fails(self):
        """Sans rapport qualite pour (run_id, row_id), l'endpoint refuse ; avec, il accepte.

        COURSE CORRIGEE (echec CI intermittent "AssertionError: True is not false").
        La fin du scan declenche un recalcul qualite EN TACHE DE FOND
        (`auto_recompute_quality_on_scan`, defaut True — cf run_flow_support,
        bloc lance APRES `rs.done = True`). Ce job ecrit un quality_report pour
        chaque film du plan. Mesure locale : le rapport apparait 0,4 a 1,1 s
        apres que `done` passe a True, et jusqu'a plusieurs secondes quand la
        machine est chargee (suite complete, CI). L'ancienne version de ce test
        soumettait le feedback ~0,1 s apres `done` : elle ne constatait donc pas
        une absence, elle gagnait une course. Des que le job de fond arrivait le
        premier — ce qui est le cas sur les runners de CI — le rapport EXISTAIT,
        l'endpoint acceptait a juste titre, et l'assertion tombait.

        Correctif : on coupe le declencheur de fond pour MAITRISER l'etat, on
        verifie explicitement que la table est vide pour ce couple, puis on
        prouve par CONTRASTE que le refus vient bien de cette absence (la meme
        requete passe des qu'un rapport existe), et non d'un run_id ou d'un
        row_id que l'endpoint aurait rejete en amont.

        La coupure est doublee d'un espion sur `recompute_all_scores` : sans lui,
        un retour du declencheur (toggle ignore, ou cle perdue dans le payload
        au fil d'un refactor) ne se verrait PAS — verifie par mutation, le test
        restait vert 6 fois sur 6 avec le toggle force a True. L'espion rend ce
        retour DETERMINISTE a detecter, et garantit qu'aucun ecrivain de
        quality_reports ne tourne pendant la fenetre d'observation.
        """
        from cinesort.ui.api import quality_audit_support
        from cinesort.ui.api.cinesort_api import CineSortApi

        folder = self.root / "Film.2020"
        folder.mkdir()
        (folder / "movie.mkv").write_bytes(b"x" * 2048)

        _p_recompute = mock.patch.object(
            quality_audit_support,
            "recompute_all_scores",
            side_effect=lambda *_a, **_k: {"ok": False, "message": "desactive par le test"},
        )
        recompute_spy = _p_recompute.start()
        self.addCleanup(_p_recompute.stop)

        api = CineSortApi()
        start = api.run.start_plan(
            {
                "root": str(self.root),
                "state_dir": str(self.state_dir),
                "tmdb_enabled": False,
                # Coupe le SEUL ecrivain de quality_reports de ce scenario.
                "auto_recompute_quality_on_scan": False,
            }
        )
        import time as _time

        run_id = start["run_id"]
        store, _runner = api._get_or_create_infra(self.state_dir)

        # Barriere DETERMINISTE : `rs.done` est positionne AU MILIEU du job de
        # plan (il reste tout le bloc post-scan a derouler derriere), alors que
        # le statut terminal en base n'est ecrit qu'apres le RETOUR du job
        # (job_runner._run_worker -> mark_run_done). Attendre DONE en base, et
        # pas seulement `done`, garantit qu'aucun travail de fin de scan ne
        # reste en vol quand on constate l'etat de la table quality_reports.
        _deadline = _time.monotonic() + 60.0
        _status = ""
        while _time.monotonic() < _deadline:
            _status = str((store.run.get_run(run_id) or {}).get("status") or "")
            if _status in ("DONE", "FAILED", "CANCELLED"):
                break
            _time.sleep(0.05)
        self.assertEqual(_status, "DONE", f"le scan doit se terminer en DONE (statut={_status!r})")
        # Le declencheur de fond est evalue AVANT ce statut terminal : si le
        # toggle avait ete ignore, l'espion l'aurait deja enregistre ici.
        self.assertFalse(
            recompute_spy.called,
            "le scan a lance un recalcul qualite de fond malgre "
            "auto_recompute_quality_on_scan=False : l'etat observe plus bas "
            "ne serait plus maitrise (course restauree)",
        )

        plan = api.run.get_plan(run_id)
        rows = plan.get("rows", [])
        self.assertTrue(rows)
        row_id = rows[0]["row_id"]

        # Pre-condition EXPLICITE : c'est bien une absence, pas un "pas encore la".
        self.assertIsNone(
            store.quality.get_quality_report(run_id=run_id, row_id=row_id),
            "pre-condition : aucun quality_report ne doit exister pour ce film "
            "(auto_recompute_quality_on_scan est desactive pour ce run)",
        )

        r = api.quality.submit_score_feedback(run_id=run_id, row_id=row_id, user_tier="Gold")
        self.assertFalse(r.get("ok"), "sans rapport qualite, le feedback doit etre refuse")

        # Contraste : seul le rapport manquait. On l'ecrit, la MEME requete passe.
        store.quality.upsert_quality_report(
            run_id=run_id,
            row_id=row_id,
            score=72,
            tier="Gold",
            reasons=[],
            metrics={},
            profile_id="CinemaLux_v1",
            profile_version=1,
        )
        r2 = api.quality.submit_score_feedback(run_id=run_id, row_id=row_id, user_tier="Silver")
        self.assertTrue(r2.get("ok"), f"avec rapport qualite, le feedback doit passer : {r2}")
        self.assertEqual(r2.get("computed_tier"), "Gold")
        self.assertEqual(r2.get("computed_score"), 72)
        self.assertEqual(r2.get("tier_delta"), -1)

    def test_invalid_run_id(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        r = api.quality.submit_score_feedback(run_id="not_a_valid_id", row_id="x", user_tier="Gold")
        self.assertFalse(r.get("ok"))

    def test_missing_row_id(self):
        from cinesort.ui.api.cinesort_api import CineSortApi

        api = CineSortApi()
        r = api.quality.submit_score_feedback(run_id="20260101_120000_000", row_id="", user_tier="Gold")
        self.assertFalse(r.get("ok"))


if __name__ == "__main__":
    unittest.main()

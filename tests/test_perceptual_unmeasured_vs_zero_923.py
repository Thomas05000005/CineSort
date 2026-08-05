"""#923 — « mesure a 0 » n'est pas « non mesure » (score perceptuel video).

`run_filter_graph` rend `[]` des que ffmpeg sort en rc != 0
(video_analysis.py:117-122). `_aggregate_filter_metrics` teste `if f_blocks:`
et n'ecrase donc rien : `blockiness_mean` et `blur_mean` gardent le 0.0 du
dataclass. Or 0.0 est la MEILLEURE valeur possible — `_score_blockiness(0.0)`
et `_score_blur(0.0)` rendent 95/100. Un fichier dont l'analyse a ECHOUE
decrochait donc des notes de reference sur des criteres jamais mesures, et
`compute_visual_score` (V1) alimente `global_score`, sur lequel
`comparison.compare_two_files` departage les doublons : le fichier corrompu —
precisement celui dont l'analyse echoue — pouvait battre une copie saine.

Deux precautions dans ce fichier :

* la condition testee (echec des filtres) n'est PAS mockee : on fait echouer
  `run_ffmpeg_text`, c'est-a-dire ffmpeg, et c'est le vrai `run_filter_graph`
  qui decide de rendre `[]`. Un mock de `run_filter_graph` fabriquerait la
  condition au lieu de l'observer ;
* on exerce le SITE D'APPEL (`_execute_perceptual_analysis`), pas seulement les
  fonctions du domaine : le pipeline reel doit produire le rapport degrade.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from cinesort.domain.perceptual.comparison import build_comparison_report, compare_criterion
from cinesort.domain.perceptual.composite_score import compute_visual_score, detect_cross_verdicts
from cinesort.domain.perceptual.composite_score_v2 import build_video_subscores
from cinesort.domain.perceptual.models import GrainAnalysis, VideoPerceptual
from cinesort.domain.perceptual.video_analysis import _compute_visual_score, analyze_video_frames

# Sortie `metadata=mode=print` REELLE (meme format que test_perceptual_video_analysis).
# Qualite mediocre mais parfaitement mesuree : blockiness 30, blur 0.05.
_STDERR_MEDIOCRE = "".join(
    f"[Parsed_metadata_4 @ 0x1] frame:{i} pts:{i * 512} pts_time:{i * 0.04}\n"
    "[Parsed_metadata_4 @ 0x1] lavfi.signalstats.YMIN=16\n"
    "[Parsed_metadata_4 @ 0x1] lavfi.signalstats.YAVG=100\n"
    "[Parsed_metadata_4 @ 0x1] lavfi.signalstats.YMAX=235\n"
    "[Parsed_metadata_4 @ 0x1] lavfi.signalstats.SATAVG=42\n"
    "[Parsed_metadata_4 @ 0x1] lavfi.block=30.0\n"
    "[Parsed_metadata_4 @ 0x1] lavfi.blur=0.05\n"
    for i in range(6)
)

# Meme sortie, mais les filtres ont VRAIMENT mesure 0.0 partout (image parfaite).
_STDERR_PERFECT = _STDERR_MEDIOCRE.replace("lavfi.block=30.0", "lavfi.block=0.0").replace(
    "lavfi.blur=0.05", "lavfi.blur=0.0"
)


def _frames(count: int = 6, size: int = 64) -> List[Dict[str, Any]]:
    """Frames pixel exploitables (entree du calcul, pas la condition testee)."""
    return [
        {
            "pixels": [(i * 7 + p * 13) % 256 for p in range(size * size)],
            "width": size,
            "height": size,
            "y_avg": 110.0,
            "timestamp": 10.0 * i,
        }
        for i in range(count)
    ]


def _ctx() -> tuple:
    """Contexte minimal accepte par `_execute_perceptual_analysis` (video seule)."""
    settings = {
        "perceptual_parallelism_mode": "serial",
        "perceptual_ssim_self_ref_enabled": False,
        "perceptual_interlacing_detection_enabled": False,
        "perceptual_crop_detection_enabled": False,
        "perceptual_judder_detection_enabled": False,
        "perceptual_hdr10_plus_detection_enabled": False,
        "perceptual_grain_intelligence_enabled": False,
    }
    store = MagicMock()
    row = MagicMock()
    row.candidates = []
    row.proposed_year = 2015
    media_path = MagicMock(exists=lambda: True, __str__=lambda self: "x.mkv")
    normalized = {"duration_s": 7200.0, "audio_tracks": []}  # pas d'audio : tache video seule
    video_info = {"width": 1920, "height": 1080, "bit_depth": 8, "fps": 24.0}
    return (settings, "ffmpeg.exe", store, {}, row, media_path, normalized, video_info)


def _run_pipeline(rc: int, stderr: str) -> Dict[str, Any]:
    """Execute le vrai pipeline perceptuel avec un ffmpeg de filtres scripte.

    `rc != 0` reproduit l'echec d'analyse : c'est `run_filter_graph` lui-meme
    qui en deduit `[]`.
    """
    from cinesort.domain.perceptual import video_analysis as va
    from cinesort.ui.api import perceptual_support as ps

    api = MagicMock()
    api._tmdb_client.return_value = None
    api._perceptual_cancel_event = None

    with (
        patch.object(ps, "extract_representative_frames", lambda *a, **k: _frames()),
        patch.object(va, "run_ffmpeg_text", lambda *a, **k: (rc, "", stderr)),
        patch.object(ps, "_load_tmdb_metadata", lambda *a, **k: None),
    ):
        out = ps._execute_perceptual_analysis(api, "run1", "row1", _ctx())

    assert out.get("ok"), out
    return out["perceptual"]


class TestFilterFailureIsNotAPerfectScore(unittest.TestCase):
    """Le pipeline reel ne doit pas noter ce qu'il n'a pas mesure."""

    def test_failed_analysis_is_reported_as_unmeasured(self) -> None:
        perc = _run_pipeline(rc=1, stderr="x.mkv: Invalid data found when processing input\n")
        video = perc["video_perceptual"]
        self.assertFalse(video["blockiness"]["measured"], "blockiness jamais mesuree, doit etre annoncee ainsi")
        self.assertFalse(video["blur"]["measured"])
        self.assertFalse(video["temporal_consistency"]["measured"])
        # L'analyse pixel, elle, a bien tourne : la distinction est par critere.
        self.assertTrue(video["banding"]["measured"])
        self.assertLess(
            float(video["visual_confidence"]),
            1.0,
            "un critere non mesure doit ABAISSER la confiance",
        )

    def test_measured_zero_keeps_its_reference_score(self) -> None:
        """Symetrique : 0.0 VRAIMENT mesure reste une note de reference."""
        perc = _run_pipeline(rc=0, stderr=_STDERR_PERFECT)
        video = perc["video_perceptual"]
        self.assertEqual(video["blockiness"]["mean"], 0.0)
        self.assertTrue(video["blockiness"]["measured"], "0.0 mesure n'est pas 0.0 par defaut")
        self.assertTrue(video["blur"]["measured"])
        self.assertEqual(float(video["visual_confidence"]), 1.0)


class TestCorruptFileNeverWinsTheDuplicateDuel(unittest.TestCase):
    """Bout en bout : de l'echec ffmpeg jusqu'a la recommandation d'archivage.

    Les deux rapports sortent du VRAI pipeline, avec les memes frames pixel :
    seul l'echec des filtres les distingue. C'est le scenario de l'issue — le
    fichier corrompu est precisement celui dont l'analyse echoue.
    """

    def setUp(self) -> None:
        self.failed = _run_pipeline(rc=1, stderr="x.mkv: Invalid data found when processing input\n")
        self.healthy = _run_pipeline(rc=0, stderr=_STDERR_MEDIOCRE)

    def test_premise_the_unmeasured_file_still_scores_higher(self) -> None:
        """Garde-fou du test suivant : sans cette premisse il ne prouverait rien.

        Moins un fichier est mesure, plus son score converge vers les criteres
        « faciles » et remonte. Exclure les criteres non mesures du calcul ne
        suffit donc PAS a renverser le classement : c'est au point de decision
        que la protection doit agir.
        """
        self.assertGreater(int(self.failed["global_score"]), int(self.healthy["global_score"]))

    def test_no_archive_recommendation_for_the_unmeasured_file(self) -> None:
        report = build_comparison_report(self.failed, self.healthy, [], "corrompu.mkv", "sain.mkv")
        self.assertTrue(report["inconclusive"])
        self.assertNotEqual(report["winner"], "a", "le fichier non mesure ne doit pas etre declare superieur")
        self.assertIn("incomplete", report["winner_label"])
        self.assertIn("Relancer l'analyse", report["recommendation"])

    def test_unmeasured_criteria_win_nothing(self) -> None:
        report = build_comparison_report(self.failed, self.healthy, [], "corrompu.mkv", "sain.mkv")
        won_by_a = {c["criterion"] for c in report["criteria"] if c["winner"] == "a"}
        self.assertNotIn("Artefacts (blockiness)", won_by_a)
        self.assertNotIn("Nettete (blur)", won_by_a)

    def test_two_measured_files_still_get_a_verdict(self) -> None:
        """Le verdict normal ne doit pas disparaitre quand tout est mesure."""
        perfect = _run_pipeline(rc=0, stderr=_STDERR_PERFECT)
        report = build_comparison_report(perfect, self.healthy, [], "net.mkv", "mediocre.mkv")
        self.assertFalse(report["inconclusive"])
        self.assertEqual(report["winner"], "a")
        won_by_a = {c["criterion"] for c in report["criteria"] if c["winner"] == "a"}
        self.assertIn("Artefacts (blockiness)", won_by_a)


_MEASURABLE = ("blockiness", "blur", "banding", "effective_bits", "temporal")


def _all_zero(**overrides: Any) -> VideoPerceptual:
    """VideoPerceptual dont les 5 criteres valent 0.0 et sont MESURES.

    Le contraste est isole au maximum : entre ce temoin et sa variante
    `<critere>_measured=False`, la seule difference est le STATUT de mesure,
    jamais la valeur. Tout ecart de score vient donc de la garde testee.
    """
    kwargs: Dict[str, Any] = {f"{m}_measured": True for m in _MEASURABLE}
    kwargs.update(overrides)
    return VideoPerceptual(**kwargs)


class TestEachCriterionIsExcludedIndividually(unittest.TestCase):
    """Une garde par critere : chacune doit peser sur la note, seule.

    Sans un cas par critere, muter une seule garde laisserait la batterie
    verte — le mutant ne serait pas equivalent, le test serait manquant.
    """

    def test_v1_score_moves_when_a_criterion_is_not_measured(self) -> None:
        grain = GrainAnalysis(score=0)
        reference = compute_visual_score(_all_zero(), grain)
        self.assertEqual(reference, 66)  # temoin : les 5 criteres mesures a 0.0
        expected = {"blockiness": 56, "blur": 59, "banding": 61, "effective_bits": 78, "temporal": 63}
        for metric, score in expected.items():
            with self.subTest(metric=metric):
                got = compute_visual_score(_all_zero(**{f"{metric}_measured": False}), grain)
                self.assertEqual(got, score, f"{metric} non mesure doit sortir de la ponderation")
                self.assertNotEqual(got, reference)

    def test_intermediate_score_and_confidence_move_too(self) -> None:
        """Le score intermediaire alimente V2 via `_score_from_visual`."""
        reference = _all_zero()
        _compute_visual_score(reference, 1.0, 0)
        self.assertEqual((reference.visual_score, reference.visual_confidence), (68, 1.0))
        expected = {
            "blockiness": (59, 0.706),
            "blur": (62, 0.765),
            "banding": (64, 0.824),
            "effective_bits": (76, 0.824),
            "temporal": (76, 0.882),
        }
        for metric, (score, coverage) in expected.items():
            with self.subTest(metric=metric):
                result = _all_zero(**{f"{metric}_measured": False})
                _compute_visual_score(result, 1.0, 0)
                self.assertEqual(result.visual_score, score)
                self.assertAlmostEqual(float(result.visual_confidence or 0.0), coverage, places=3)


class TestVisualScoreExcludesUnmeasuredCriteria(unittest.TestCase):
    """compute_visual_score (V1) — celui qui alimente global_score."""

    def _video(self, **kw: Any) -> VideoPerceptual:
        base: Dict[str, Any] = {"banding_mean": 4.0, "effective_bits_mean": 7.5}
        base.update(kw)
        return VideoPerceptual(**base)

    def test_unmeasured_criteria_do_not_inflate_the_score(self) -> None:
        unmeasured = self._video()  # block/blur/temporal a 0.0 sans mesure
        measured_zero = self._video(
            blockiness_measured=True,
            blur_measured=True,
            temporal_measured=True,
        )
        self.assertLess(
            compute_visual_score(unmeasured, None),
            compute_visual_score(measured_zero, None),
            "les memes 0.0 doivent valoir moins quand ils ne sont pas mesures",
        )

    def test_a_nonzero_value_counts_as_measured(self) -> None:
        """Une valeur non nulle ne peut venir que d'une mesure : pas de regression
        pour les objets construits sans les drapeaux."""
        poor = VideoPerceptual(blockiness_mean=80.0, blur_mean=0.15, banding_mean=30.0, effective_bits_mean=6.0)
        for metric in ("blockiness", "blur", "banding", "effective_bits"):
            self.assertTrue(poor.is_measured(metric), metric)
        self.assertLess(compute_visual_score(poor, None), 50)

    def test_unknown_metric_name_raises(self) -> None:
        with self.assertRaises(KeyError):
            VideoPerceptual().is_measured("blockines")  # faute de frappe volontaire


class TestUnmeasuredLowersV2Confidence(unittest.TestCase):
    """La confiance V2 ne doit plus dependre des seules frames pixel."""

    def test_confidence_falls_when_filters_never_ran(self) -> None:
        analyzed = analyze_video_frames(_frames(), [], 8, "bt709", width=64, height=64)
        self.assertGreaterEqual(analyzed.frames_analyzed, 5)  # les frames pixel, elles, sont la
        subs, _ = build_video_subscores(analyzed, None, None, None)
        visual = next(s for s in subs if s.name == "perceptual_visual")
        self.assertLess(visual.confidence, 1.0)

    def test_confidence_stays_full_when_everything_was_measured(self) -> None:
        filters = [
            {"blockiness": 12.0, "blur": 0.02, "y_avg": 100, "sat_avg": 40, "tout": 0.01, "vrep": 0.005}
            for _ in range(6)
        ]
        analyzed = analyze_video_frames(_frames(), filters, 8, "bt709", width=64, height=64)
        subs, _ = build_video_subscores(analyzed, None, None, None)
        visual = next(s for s in subs if s.name == "perceptual_visual")
        self.assertEqual(visual.confidence, 1.0)


class TestPixelMetricsMeasuredAtZero(unittest.TestCase):
    """Cote analyse PIXEL, il faut FORCER le 0.0 pour exercer les drapeaux.

    Sur une image variee, banding et profondeur effective sont non nuls et la
    regle « valeur non nulle = mesuree » suffirait a les couvrir : les drapeaux
    ne seraient jamais mis a l'epreuve. Des frames uniformes produisent un
    banding de 0.0 ET un bit depth effectif de 0.0 (log2(1 niveau distinct)) —
    deux vraies mesures qui valent exactement la valeur de repli.
    """

    def _flat_analysis(self) -> Any:
        flat = [{"pixels": [128] * (32 * 32), "width": 32, "height": 32, "y_avg": 128.0} for _ in range(5)]
        filters = [
            {"blockiness": 1.0, "blur": 0.001, "y_avg": 128, "sat_avg": 40, "tout": 0.0, "vrep": 0.0} for _ in range(5)
        ]
        return analyze_video_frames(flat, filters, 8, "bt709", width=32, height=32)

    def test_zero_banding_and_zero_bits_are_measured(self) -> None:
        result = self._flat_analysis()
        self.assertEqual(result.banding_mean, 0.0)
        self.assertEqual(result.effective_bits_mean, 0.0)
        self.assertTrue(result.is_measured("banding"))
        self.assertTrue(result.is_measured("effective_bits"))

    def test_those_zeros_still_feed_the_score(self) -> None:
        """Une mesure a 0.0 doit continuer d'alimenter la note (95 pour banding,
        25 pour la profondeur effective) — sinon on aurait echange un biais
        contre un autre."""
        result = self._flat_analysis()
        without_pixel_metrics = analyze_video_frames([], [{"blockiness": 1.0, "blur": 0.001}] * 5, 8, "bt709")
        self.assertNotEqual(result.visual_score, without_pixel_metrics.visual_score)
        self.assertEqual(result.visual_confidence, 1.0)
        self.assertLess(float(without_pixel_metrics.visual_confidence or 0.0), 1.0)


class TestCompareCriterionIgnoresUnmeasuredSides(unittest.TestCase):
    """`higher_is_better=False` + valeur de repli 0.0 = victoire automatique."""

    def test_unmeasured_side_cannot_win(self) -> None:
        crit = compare_criterion(0.0, 30.0, "Artefacts (blockiness)", higher_is_better=False, measured_a=False)
        self.assertEqual(crit["winner"], "tie")
        self.assertFalse(crit["measured_a"])

    def test_measured_zero_still_wins(self) -> None:
        crit = compare_criterion(0.0, 30.0, "Artefacts (blockiness)", higher_is_better=False, measured_a=True)
        self.assertEqual(crit["winner"], "a")


class TestHistoricalReportsWithoutTheMeasuredKey(unittest.TestCase):
    """Les rapports deja en base n'ont ni `measured` ni `visual_confidence`.

    Ils doivent rester exploitables SANS re-scan, et le 0.0 ambigu doit y etre
    traite comme partout ailleurs : non mesure.
    """

    def _legacy(self, block: float, blur: float, score: int) -> Dict[str, Any]:
        return {
            "global_score": score,
            "video_perceptual": {
                "blockiness": {"mean": block},
                "blur": {"mean": blur},
                "banding": {"mean_score": 3.0},
                "effective_bit_depth": {"mean_bits": 8.0},
                "local_variance": {"mean_variance": 500.0},
            },
        }

    def test_legacy_zero_wins_nothing(self) -> None:
        report = build_comparison_report(
            self._legacy(0.0, 0.0, 74),
            self._legacy(30.0, 0.05, 68),
            [],
            "ancien_non_mesure.mkv",
            "ancien_mesure.mkv",
        )
        won_by_a = {c["criterion"] for c in report["criteria"] if c["winner"] == "a"}
        self.assertNotIn("Artefacts (blockiness)", won_by_a)
        self.assertNotIn("Nettete (blur)", won_by_a)

    def test_legacy_measured_values_still_compare(self) -> None:
        report = build_comparison_report(
            self._legacy(2.0, 0.005, 80),
            self._legacy(30.0, 0.05, 68),
            [],
            "a.mkv",
            "b.mkv",
        )
        won_by_a = {c["criterion"] for c in report["criteria"] if c["winner"] == "a"}
        self.assertIn("Artefacts (blockiness)", won_by_a)
        self.assertEqual(report["winner"], "a")


class TestMasteringVerdictRequiresMeasurements(unittest.TestCase):
    """Un verdict POSITIF ne doit pas naitre d'une analyse absente."""

    def _video(self, measured: bool) -> VideoPerceptual:
        # Tout a 0.0 (l'echec d'analyse), mais le bit depth effectif, lui, mesure.
        return VideoPerceptual(
            effective_bits_mean=9.8,
            effective_bits_measured=True,
            blockiness_measured=measured,
            blur_measured=measured,
            banding_measured=measured,
        )

    def _ids(self, video: VideoPerceptual) -> List[str]:
        return [v["id"] for v in detect_cross_verdicts(video, GrainAnalysis(), None)]

    def test_no_mastering_verdict_without_measurements(self) -> None:
        self.assertNotIn("excellent_mastering", self._ids(self._video(measured=False)))

    def test_mastering_verdict_still_emitted_when_measured(self) -> None:
        self.assertIn("excellent_mastering", self._ids(self._video(measured=True)))


if __name__ == "__main__":
    unittest.main()

"""Lot « verdicts audio/video : branches mortes et etiquettes fausses ».

Couvre quatre defauts distincts, chacun teste par le point d'entree REEL qui
l'expose (pas par le helper prive) :

- #807 : la table de rangs partagee collapsait DTS-HD HRA (LOSSY) sur le rang et
         le label de DTS-HD MA (LOSSLESS).
- #808 : `sorted(x)[len(x) // 2]` n'est pas une mediane sur un nombre pair.
- #830 : `temporal_stddev` ne portait que l'ecart-type de blockiness — un
         doublon exact de `blockiness_stddev` — donc la variabilite de FLOU
         entre frames n'entrait dans aucun score persiste.
- #826 : `_bitrate_label` tronquait en Mbps entier, si bien que le comparateur
         de doublons designait un gagnant que ses deux etiquettes disaient egales.

#470 (Dolby Vision Profile 8.4 classe `hlg`) n'est PAS teste ici : il est deja
corrige sur main et couvert par tests/test_hdr_dolby_vision_profile_84_470.py.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, List

from cinesort.domain.audio_analysis import analyze_audio
from cinesort.domain.duplicate_compare import compare_by_criteria
from cinesort.domain.perceptual.audio_perceptual import select_best_audio_track
from cinesort.domain.perceptual.composite_score import compute_visual_score
from cinesort.domain.perceptual.video_analysis import analyze_video_frames

# ---------------------------------------------------------------------------
# #807 — DTS-HD HRA (lossy) etiquete « DTS-HD MA » (lossless) au rang gold
# ---------------------------------------------------------------------------


class DtsHdHraIsLossyTests(unittest.TestCase):
    """Le badge audio ne doit plus promouvoir un flux HRA au rang du lossless."""

    def test_hra_badge_is_not_labelled_dts_hd_ma(self) -> None:
        report = analyze_audio([{"codec": "dts-hd hra", "channels": 6, "language": "fre"}])
        self.assertEqual(report["best_format"], "DTS-HD HRA")
        self.assertEqual(report["badge_label"], "DTS-HD HRA 5.1")
        # rang 2 -> silver, comme `dts` : c'est deja ce que quality_score
        # applique a HRA (_AUDIO_CANONICAL_RANK_ALIAS['dts-hd hra'] = 'dts').
        self.assertEqual(report["badge_tier"], "silver")

    def test_hra_ranks_below_a_lossless_track_of_the_same_file(self) -> None:
        """Un HRA ne doit plus battre une piste FLAC (lossless) du meme fichier."""
        report = analyze_audio(
            [
                {"codec": "dts-hd hra", "channels": 6, "language": "fre"},
                {"codec": "flac", "channels": 6, "language": "eng"},
            ]
        )
        self.assertEqual(report["best_format"], "FLAC")

    def test_hra_unhyphenated_spelling_is_also_lossy(self) -> None:
        """`dtshd hra` : meme verdict que `dts-hd hra` (les deux orthographes
        cohabitent dans la table, comme deja `dts-hd` / `dtshd`)."""
        report = analyze_audio([{"codec": "dtshd hra", "channels": 6, "language": "fre"}])
        self.assertEqual(report["best_format"], "DTS-HD HRA")
        self.assertEqual(report["badge_tier"], "silver")

    def test_ma_remains_lossless_gold(self) -> None:
        """Non-regression : DTS-HD MA garde son rang 4 / tier gold."""
        report = analyze_audio([{"codec": "dts-hd ma", "channels": 8, "language": "fre"}])
        self.assertEqual(report["best_format"], "DTS-HD MA")
        self.assertEqual(report["badge_tier"], "gold")

    def test_plain_dts_hd_without_variant_stays_ma(self) -> None:
        """Non-regression : `dts-hd` nu (variante inconnue) garde le defaut historique."""
        report = analyze_audio([{"codec": "dts-hd", "channels": 6, "language": "fre"}])
        self.assertEqual(report["best_format"], "DTS-HD MA")
        self.assertEqual(report["badge_tier"], "gold")


class SelectBestAudioTrackHraTests(unittest.TestCase):
    """Chemin REEL le plus expose : `select_best_audio_track` matche aussi le TITRE.

    ffprobe range la variante DTS dans `profile`, pas dans `codec` — mais le tag
    `title` du conteneur, lui, porte tres souvent « DTS-HD HRA 5.1 ». C'est par
    la que le rang 4 (celui du lossless) etait attribue a un flux lossy.
    """

    def test_flac_beats_a_track_titled_dts_hd_hra(self) -> None:
        tracks: List[Dict[str, Any]] = [
            {"index": 0, "codec": "dts", "title": "DTS-HD HRA 5.1", "channels": 6},
            {"index": 1, "codec": "flac", "title": "FLAC 5.1", "channels": 6},
        ]
        best = select_best_audio_track(tracks)
        assert best is not None
        self.assertEqual(best["index"], 1)

    def test_track_titled_dts_hd_ma_still_wins_over_flac(self) -> None:
        """Non-regression : le lossless MA garde sa priorite sur FLAC."""
        tracks: List[Dict[str, Any]] = [
            {"index": 0, "codec": "dts", "title": "DTS-HD MA 7.1", "channels": 8},
            {"index": 1, "codec": "flac", "title": "FLAC 5.1", "channels": 6},
        ]
        best = select_best_audio_track(tracks)
        assert best is not None
        self.assertEqual(best["index"], 0)


# ---------------------------------------------------------------------------
# Helpers video
# ---------------------------------------------------------------------------


def _filters(blockiness: List[float], blur: List[float]) -> List[Dict[str, Any]]:
    """Resultats de filtre ffmpeg minimaux, un par frame echantillonnee."""
    return [
        {
            "y_avg": 100.0,
            "sat_avg": 40.0,
            "tout": 0.01,
            "vrep": 0.005,
            "blockiness": bk,
            "blur": bl,
        }
        for bk, bl in zip(blockiness, blur)
    ]


# ---------------------------------------------------------------------------
# #808 — mediane sur un nombre PAIR d'elements
# ---------------------------------------------------------------------------


class EvenLengthMedianTests(unittest.TestCase):
    """Sur 4 keyframes, `sorted[len // 2]` rendait le 3e element, pas la mediane."""

    def test_blockiness_and_blur_medians_average_the_two_central_values(self) -> None:
        result = analyze_video_frames(
            [],
            _filters([10.0, 20.0, 30.0, 100.0], [0.01, 0.02, 0.03, 0.10]),
            8,
            "bt709",
        )
        # mediane(10, 20, 30, 100) = (20 + 30) / 2 = 25 ; l'ancien calcul rendait 30.
        self.assertAlmostEqual(result.blockiness_median, 25.0, places=6)
        # mediane(0.01, 0.02, 0.03, 0.10) = 0.025 ; l'ancien calcul rendait 0.03.
        self.assertAlmostEqual(result.blur_median, 0.025, places=6)

    def test_odd_length_median_unchanged(self) -> None:
        """Non-regression : sur un nombre impair, la mediane est l'element central."""
        result = analyze_video_frames([], _filters([10.0, 20.0, 90.0], [0.01, 0.02, 0.09]), 8, "bt709")
        self.assertAlmostEqual(result.blockiness_median, 20.0, places=6)
        self.assertAlmostEqual(result.blur_median, 0.02, places=6)


# ---------------------------------------------------------------------------
# #830 — la composante temporelle ignorait la variabilite de flou
# ---------------------------------------------------------------------------


class TemporalConsistencyUsesBlurTests(unittest.TestCase):
    """Deux runs a blockiness IDENTIQUE et blur MOYEN identique, un seul varie."""

    # blockiness constante -> ecart-type de blockiness NUL dans les deux runs.
    _BLOCKS = [20.0, 20.0, 20.0, 20.0]
    # moyennes de blur egales (0.5) : seuls s_temporal peut differer entre les
    # deux runs, tous les autres termes du score visuel sont identiques.
    _BLUR_STABLE = [0.5, 0.5, 0.5, 0.5]
    _BLUR_ERRATIC = [0.0, 1.0, 0.0, 1.0]

    def test_temporal_metric_is_not_a_duplicate_of_blockiness_stddev(self) -> None:
        result = analyze_video_frames([], _filters(self._BLOCKS, self._BLUR_ERRATIC), 8, "bt709")
        # La blockiness ne bouge pas d'une frame a l'autre...
        self.assertAlmostEqual(result.blockiness_stddev, 0.0, places=6)
        # ... mais le flou, si : la metrique temporelle doit le refleter.
        self.assertGreater(result.temporal_stddev, 0.0)

    def test_erratic_blur_lowers_the_persisted_visual_score(self) -> None:
        stable = analyze_video_frames([], _filters(self._BLOCKS, self._BLUR_STABLE), 8, "bt709")
        erratic = analyze_video_frames([], _filters(self._BLOCKS, self._BLUR_ERRATIC), 8, "bt709")

        # Garde-fou : les deux runs ne different QUE par la variabilite du flou.
        self.assertAlmostEqual(stable.blur_mean, erratic.blur_mean, places=6)
        self.assertAlmostEqual(stable.blockiness_mean, erratic.blockiness_mean, places=6)
        self.assertAlmostEqual(stable.banding_mean, erratic.banding_mean, places=6)
        self.assertAlmostEqual(stable.effective_bits_mean, erratic.effective_bits_mean, places=6)

        # compute_visual_score est le calcul AUTORITAIRE (build_perceptual_result),
        # celui dont le resultat est persiste en base.
        self.assertLess(compute_visual_score(erratic), compute_visual_score(stable))


# ---------------------------------------------------------------------------
# #826 — troncature du debit dans le comparateur de doublons
# ---------------------------------------------------------------------------


def _probe(bitrate_bps: int) -> Dict[str, Any]:
    return {
        "video": {"codec": "hevc", "width": 1920, "height": 1080, "bitrate": bitrate_bps},
        "audio_tracks": [{"codec": "eac3", "channels": 6, "language": "fre"}],
    }


class BitrateLabelPrecisionTests(unittest.TestCase):
    def test_two_distinct_bitrates_do_not_display_the_same_label(self) -> None:
        criteria = compare_by_criteria(_probe(8_500_000), _probe(8_000_000))
        bitrate = next(c for c in criteria if c.name == "bitrate")
        # Le critere designe A gagnant : ses deux etiquettes ne peuvent pas etre egales.
        self.assertEqual(bitrate.winner, "a")
        self.assertNotEqual(bitrate.value_a, bitrate.value_b)
        self.assertEqual(bitrate.value_a, "8.5 Mbps")
        self.assertEqual(bitrate.value_b, "8.0 Mbps")

    def test_sub_mbps_bitrates_keep_the_kbps_unit(self) -> None:
        """Non-regression : sous 1 Mbps l'unite reste kbps (invariant R8-099)."""
        criteria = compare_by_criteria(_probe(800_000), _probe(400_000))
        bitrate = next(c for c in criteria if c.name == "bitrate")
        self.assertEqual(bitrate.value_a, "800 kbps")
        self.assertEqual(bitrate.value_b, "400 kbps")


if __name__ == "__main__":
    unittest.main()

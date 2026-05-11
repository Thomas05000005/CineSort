"""Tests comparaison qualite doublons — cinesort/domain/duplicate_compare.py.

Couvre :
- Resolution : 1080p vs 720p → A gagne
- HDR : HDR10 vs SDR → A gagne
- Codec video : HEVC vs x264 → A gagne
- Audio codec : TrueHD vs AC3 → A gagne
- Audio canaux : 7.1 vs 5.1 → A gagne
- Bitrate : meme codec, A plus haut → A gagne ; codecs differents → skip
- Egalite parfaite → tie
- Probe manquante : criteres connus seulement
- Deux probes manquantes → tie
- 3 fichiers → rank_duplicates ordonne
- Score pondere correct
- Seuil tie ±5 points
- Edge : taille 0, probe vide
"""

from __future__ import annotations

import unittest

from cinesort.domain.duplicate_compare import (
    ComparisonResult,
    CriterionResult,
    compare_by_criteria,
    compare_duplicates,
    determine_winner,
    rank_duplicates,
)


def _probe(
    *, height=0, codec="", hdr10=False, dv=False, hdr10p=False, bitrate=0, audio_codec="", channels=0, duration_s=0
):
    """Helper pour creer un probe minimal."""
    return {
        "video": {
            "height": height,
            "codec": codec,
            "bitrate": bitrate,
            "hdr10": hdr10,
            "hdr10_plus": hdr10p,
            "hdr_dolby_vision": dv,
        },
        "audio_tracks": [{"codec": audio_codec, "channels": channels}] if audio_codec else [],
        "duration_s": duration_s,
    }


class ResolutionCompareTests(unittest.TestCase):
    """Resolution : 1080p vs 720p → A gagne."""

    def test_1080_vs_720(self) -> None:
        r = compare_duplicates(_probe(height=1080, codec="hevc"), _probe(height=720, codec="hevc"))
        self.assertEqual(r.winner, "a")
        self.assertGreater(r.total_score_a, r.total_score_b)

    def test_4k_vs_1080(self) -> None:
        r = compare_duplicates(_probe(height=2160, codec="hevc"), _probe(height=1080, codec="hevc"))
        self.assertEqual(r.winner, "a")

    def test_same_resolution(self) -> None:
        criteria = compare_by_criteria(_probe(height=1080), _probe(height=1080))
        res_criterion = next(c for c in criteria if c.name == "resolution")
        self.assertEqual(res_criterion.winner, "tie")
        self.assertEqual(res_criterion.points_delta, 0)


class HdrCompareTests(unittest.TestCase):
    """HDR : HDR10 vs SDR → A gagne."""

    def test_hdr10_vs_sdr(self) -> None:
        r = compare_duplicates(_probe(height=1080, hdr10=True), _probe(height=1080))
        # HDR donne 20 points d'avance → A gagne
        self.assertEqual(r.winner, "a")

    def test_dv_vs_hdr10(self) -> None:
        r = compare_duplicates(
            _probe(height=1080, dv=True),
            _probe(height=1080, hdr10=True),
        )
        self.assertEqual(r.winner, "a")

    def test_sdr_vs_sdr(self) -> None:
        criteria = compare_by_criteria(_probe(height=1080), _probe(height=1080))
        hdr = next(c for c in criteria if c.name == "hdr")
        self.assertEqual(hdr.winner, "tie")


class VideoCodecCompareTests(unittest.TestCase):
    """Codec video : HEVC vs x264 → A gagne."""

    def test_hevc_vs_h264(self) -> None:
        r = compare_duplicates(
            _probe(height=1080, codec="hevc"),
            _probe(height=1080, codec="h264"),
        )
        self.assertEqual(r.winner, "a")

    def test_av1_vs_hevc(self) -> None:
        r = compare_duplicates(
            _probe(height=1080, codec="av1"),
            _probe(height=1080, codec="hevc"),
        )
        self.assertEqual(r.winner, "a")


class AudioCompareTests(unittest.TestCase):
    """Audio : TrueHD 7.1 vs AC3 5.1 → A gagne."""

    def test_truehd_vs_ac3(self) -> None:
        r = compare_duplicates(
            _probe(height=1080, audio_codec="truehd", channels=8),
            _probe(height=1080, audio_codec="ac3", channels=6),
        )
        self.assertEqual(r.winner, "a")

    def test_same_codec_more_channels(self) -> None:
        r = compare_duplicates(
            _probe(height=1080, audio_codec="ac3", channels=8),
            _probe(height=1080, audio_codec="ac3", channels=6),
        )
        self.assertEqual(r.winner, "a")


class BitrateCompareTests(unittest.TestCase):
    """Bitrate : meme codec + A plus haut → A gagne. Codecs differents → skip."""

    def test_same_codec_higher_bitrate(self) -> None:
        criteria = compare_by_criteria(
            _probe(height=1080, codec="hevc", bitrate=20000000),
            _probe(height=1080, codec="hevc", bitrate=5000000),
        )
        br = next(c for c in criteria if c.name == "bitrate")
        self.assertEqual(br.winner, "a")
        self.assertGreater(br.points_delta, 0)

    def test_different_codec_skip_bitrate(self) -> None:
        """Codecs differents → bitrate unknown, pas de points."""
        criteria = compare_by_criteria(
            _probe(height=1080, codec="hevc", bitrate=5000000),
            _probe(height=1080, codec="h264", bitrate=20000000),
        )
        br = next(c for c in criteria if c.name == "bitrate")
        self.assertEqual(br.winner, "unknown")
        self.assertEqual(br.points_delta, 0)


class EqualityTests(unittest.TestCase):
    """Egalite parfaite → tie."""

    def test_identical_probes(self) -> None:
        p = _probe(height=1080, codec="hevc", hdr10=True, audio_codec="truehd", channels=8)
        r = compare_duplicates(p, p)
        self.assertEqual(r.winner, "tie")
        self.assertIn("equivalente", r.recommendation.lower())

    def test_tie_threshold(self) -> None:
        """Delta ≤ 5 points = tie."""
        # Seule difference : bitrate (5 pts max) avec meme codec
        r = compare_duplicates(
            _probe(height=1080, codec="hevc", bitrate=20000000, audio_codec="ac3", channels=6),
            _probe(height=1080, codec="hevc", bitrate=10000000, audio_codec="ac3", channels=6),
        )
        self.assertEqual(r.winner, "tie")  # 5 pts = seuil exact → tie


class ProbeManquanteTests(unittest.TestCase):
    """Gestion des probes manquantes."""

    def test_one_probe_missing(self) -> None:
        """Une probe manquante → criteres connus seulement, A gagne par defaut si il a des donnees."""
        r = compare_duplicates(
            _probe(height=1080, codec="hevc", audio_codec="truehd", channels=8),
            None,
        )
        # A a des donnees concretes (canaux 8 vs 0) → A gagne
        self.assertEqual(r.winner, "a")

    def test_both_probes_missing(self) -> None:
        r = compare_duplicates(None, None)
        self.assertEqual(r.winner, "tie")

    def test_partial_probe(self) -> None:
        """Probe avec seulement la resolution → seul ce critere compte."""
        r = compare_duplicates(
            _probe(height=2160),
            _probe(height=720),
        )
        self.assertEqual(r.winner, "a")


class RankDuplicatesTests(unittest.TestCase):
    """3+ fichiers → rank_duplicates ordonne par score decroissant."""

    def test_rank_3_files(self) -> None:
        files = [
            {"id": "c", "probe": _probe(height=720, codec="h264")},
            {"id": "a", "probe": _probe(height=2160, codec="hevc", hdr10=True)},
            {"id": "b", "probe": _probe(height=1080, codec="hevc")},
        ]
        ranked = rank_duplicates(files)
        self.assertEqual(ranked[0]["id"], "a")  # 4K HEVC HDR → meilleur
        self.assertEqual(ranked[1]["id"], "b")  # 1080p HEVC
        self.assertEqual(ranked[2]["id"], "c")  # 720p H264

    def test_rank_has_score(self) -> None:
        files = [{"id": "x", "probe": _probe(height=1080, codec="hevc")}]
        ranked = rank_duplicates(files)
        self.assertIn("rank_score", ranked[0])
        self.assertGreater(ranked[0]["rank_score"], 0)

    def test_rank_empty_list(self) -> None:
        self.assertEqual(rank_duplicates([]), [])


class ScoreWeightTests(unittest.TestCase):
    """Verification des ponderations."""

    def test_resolution_outweighs_codec(self) -> None:
        """4K x264 > 720p HEVC (resolution 30pts > codec 15pts)."""
        r = compare_duplicates(
            _probe(height=2160, codec="h264"),
            _probe(height=720, codec="hevc"),
        )
        self.assertEqual(r.winner, "a")

    def test_hdr_outweighs_single_audio_criterion(self) -> None:
        """HDR10 + meme audio > SDR + meme audio (HDR 20pts net)."""
        r = compare_duplicates(
            _probe(height=1080, hdr10=True, audio_codec="ac3", channels=6),
            _probe(height=1080, audio_codec="ac3", channels=6),
        )
        self.assertEqual(r.winner, "a")


class ComparisonResultStructureTests(unittest.TestCase):
    """Structure du ComparisonResult."""

    def test_result_has_all_fields(self) -> None:
        r = compare_duplicates(
            _probe(height=1080, codec="hevc"),
            _probe(height=720, codec="h264"),
        )
        self.assertIsInstance(r, ComparisonResult)
        self.assertIn(r.winner, {"a", "b", "tie"})
        self.assertIsInstance(r.criteria, list)
        self.assertGreaterEqual(len(r.criteria), 7)
        self.assertIsInstance(r.recommendation, str)

    def test_criteria_names(self) -> None:
        r = compare_duplicates(_probe(height=1080), _probe(height=720))
        names = {c.name for c in r.criteria}
        self.assertEqual(
            names, {"resolution", "hdr", "video_codec", "audio_codec", "audio_channels", "bitrate", "file_size"}
        )

    def test_size_savings(self) -> None:
        r = compare_duplicates(
            _probe(height=1080, codec="hevc", bitrate=15000000, duration_s=7200),
            _probe(height=720, codec="h264", bitrate=4000000, duration_s=7200),
        )
        # Le perdant (B) a environ 4000000*7200/8 = 3.6 Go
        self.assertGreater(r.size_savings, 0)


class EdgeCaseTests(unittest.TestCase):
    """Edge cases."""

    def test_empty_probe(self) -> None:
        r = compare_duplicates({}, {})
        self.assertEqual(r.winner, "tie")

    def test_probe_with_zero_height(self) -> None:
        r = compare_duplicates(_probe(height=0), _probe(height=1080))
        # height 0 → resolution unknown pour A → critere skippe → tie
        self.assertEqual(r.winner, "tie")

    def test_determine_winner_tie_exact(self) -> None:
        """Delta exactement au seuil = tie."""
        from cinesort.domain.duplicate_compare import _TIE_THRESHOLD

        criteria = [CriterionResult("test", "Test", "a", "b", "a", _TIE_THRESHOLD)]
        winner, _ = determine_winner(criteria)
        self.assertEqual(winner, "tie")

    def test_determine_winner_just_above(self) -> None:
        from cinesort.domain.duplicate_compare import _TIE_THRESHOLD

        criteria = [CriterionResult("test", "Test", "a", "b", "a", _TIE_THRESHOLD + 1)]
        winner, _ = determine_winner(criteria)
        self.assertEqual(winner, "a")


if __name__ == "__main__":
    unittest.main()

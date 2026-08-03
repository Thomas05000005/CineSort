"""F16 : le bitrate VIDEO du probe est TOUJOURS en bits/s.

Bug d'origine (reproduit a HEAD 529fcd0) : ``_normalize_video_bitrate_kbps``
gardait l'heuristique "n > 500000 => bps, sinon deja kbps" alors que la couche
probe normalise TOUT en bits/s (``_normalize_ffprobe.py:93`` et
``_normalize_mediainfo.py:84`` -> ``conversions.to_optional_bitrate``), et que
les name-hints ne remplissent jamais ``video.bitrate``.

Consequence mesuree sur un 1080p a 450 kb/s REELS (= 450000 bps) :
  - "+18 Debit excellent pour 1080p (450000 kb/s >= 8000 kb/s)" au lieu du
    malus -18 "Debit trop faible" ;
  - metrics.detected.file_size_bytes = 303 750 000 000 (303 GB) au lieu de
    ~304 MB ; meme x1000 sur bitrate_kbps et les custom rules file_size_gb.

Meme classe de defaut que R8-038 (audio, deja corrige) et R8-099
(duplicate_compare, deja corrige).
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import (
    _normalize_audio_bitrate_kbps,
    _normalize_bitrate_kbps,
    _normalize_video_bitrate_kbps,
    compute_quality_score,
    default_quality_profile,
)


def _probe_1080p(bitrate_bps: int):
    return {
        "probe_quality": "FULL",
        "duration_s": 5400.0,
        "video": {
            "width": 1920,
            "height": 1080,
            "codec": "hevc",
            "bitrate": bitrate_bps,
            "bit_depth": 8,
        },
        "audio_tracks": [{"codec": "aac", "channels": 2, "bitrate": 128_000, "language": "fre"}],
        "sources": {},
    }


class NormalizeVideoBitrateBpsTests(unittest.TestCase):
    """L'entree est en bps : division INCONDITIONNELLE par 1000."""

    def test_bitrate_video_toujours_bps(self):
        # 450 kb/s reels d'un WEB tres compresse.
        self.assertEqual(_normalize_video_bitrate_kbps(450_000), 450)
        # Seuil 1080p nominal.
        self.assertEqual(_normalize_video_bitrate_kbps(8_000_000), 8000)
        # 4K UHD REMUX legitime (140 Mb/s).
        self.assertEqual(_normalize_video_bitrate_kbps(140_000_000), 140_000)

    def test_valeurs_sous_le_kbps_rendent_none(self):
        # < 500 bps : arrondi a 0 kb/s. On rend None ("debit non detecte")
        # et surtout PAS 0, qui serait lu comme un debit MESURE nul.
        self.assertIsNone(_normalize_video_bitrate_kbps(400))
        self.assertIsNone(_normalize_video_bitrate_kbps(1))

    def test_alias_backward_compat_suit_la_variante_video(self):
        self.assertIs(_normalize_bitrate_kbps, _normalize_video_bitrate_kbps)
        self.assertEqual(_normalize_bitrate_kbps(140_000_000), 140_000)

    def test_parite_avec_le_chemin_audio(self):
        # Les deux normaliseurs partagent desormais le meme invariant bps.
        for raw in (192_000, 1_509_000, 9_000_000):
            with self.subTest(raw=raw):
                self.assertEqual(
                    _normalize_video_bitrate_kbps(raw),
                    _normalize_audio_bitrate_kbps(raw),
                )


class LowBitrate1080pTests(unittest.TestCase):
    def test_450kbps_reel_donne_malus_et_taille_realiste(self):
        res = compute_quality_score(
            normalized_probe=_probe_1080p(450_000),
            profile=default_quality_profile(),
            folder_name="Film (2020)",
            release_name="Film.2020.1080p.WEB.x265-GRP.mkv",
        )
        reasons = res["reasons"]
        self.assertTrue(
            any("Debit trop faible" in r for r in reasons),
            f"reasons={reasons}",
        )
        self.assertFalse(any("Debit excellent" in r for r in reasons), f"reasons={reasons}")
        self.assertEqual(res["metrics"]["detected"]["bitrate_kbps"], 450)
        # 5400 s x 450 kb/s ~ 304 Mo, pas 304 Go.
        self.assertLess(res["metrics"]["detected"]["file_size_bytes"], 1_000_000_000)


class BitrateNonRegressionTests(unittest.TestCase):
    """Assertions qui doivent rester VERTES des deux cotes de la mutation."""

    def test_entrees_invalides_inchangees(self):
        self.assertIsNone(_normalize_video_bitrate_kbps(None))
        self.assertIsNone(_normalize_video_bitrate_kbps(0))
        self.assertIsNone(_normalize_video_bitrate_kbps(0.0))
        self.assertIsNone(_normalize_video_bitrate_kbps(-1))
        self.assertIsNone(_normalize_video_bitrate_kbps(-50_000))
        self.assertIsNone(_normalize_video_bitrate_kbps("garbage"))
        self.assertIsNone(_normalize_video_bitrate_kbps(""))

    def test_valeurs_deja_au_dessus_du_seuil_legacy_inchangees(self):
        # Ces valeurs etaient DEJA divisees par l'ancienne heuristique
        # (> 500000) : le correctif ne doit rien y changer.
        self.assertEqual(_normalize_video_bitrate_kbps(8_000_000), 8000)
        self.assertEqual(_normalize_video_bitrate_kbps(50_000_000), 50_000)
        self.assertEqual(_normalize_video_bitrate_kbps("8000000"), 8000)

    def test_1080p_a_10_mbps_reste_bien_note(self):
        res = compute_quality_score(
            normalized_probe=_probe_1080p(10_000_000),
            profile=default_quality_profile(),
            folder_name="Film (2020)",
            release_name="Film.2020.1080p.BluRay.x265-GRP.mkv",
        )
        self.assertEqual(res["metrics"]["detected"]["bitrate_kbps"], 10_000)
        self.assertFalse(
            any("Debit trop faible" in r for r in res["reasons"]),
            f"reasons={res['reasons']}",
        )


if __name__ == "__main__":
    unittest.main()

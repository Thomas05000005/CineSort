"""F13 : les sous-scores exposes doivent rester dans [0, 100].

Bug d'origine (reproduit a HEAD 529fcd0) : les clamps existent UNIQUEMENT a
l'interieur de ``_score_video`` / ``_score_audio`` / ``_score_extras``. Les
mutations qui suivent (compensations probe FAILED/PARTIAL, bonus Atmos deduit
du nom, helpers ere / encode_warnings / commentary / genre) ne sont jamais
re-clampees. Resultat mesure :
  - 480p 2023 h264 900 kb/s + [upscale_suspect, reencode_degraded] + Action
    -> metrics.subscores.video = -4.0 et narrative "la video le point a
       surveiller (-4/100)" ;
  - 2160p DV 90 Mb/s film 1965 (bonus patrimoine +8) -> subscores.video = 102.0,
    pondere tel quel par _apply_weights.

Contrat viole : explain_score.py:5 ("chacun 0..100 apres clamp").
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import (
    compute_quality_score,
    default_quality_profile,
)


def _probe(video, audio_tracks=None, quality="FULL", duration=5400.0):
    return {
        "probe_quality": quality,
        "duration_s": duration,
        "video": dict(video),
        "audio_tracks": [dict(a) for a in (audio_tracks or [])],
        "sources": {},
    }


_SD_480P = {"width": 854, "height": 480, "codec": "h264", "bitrate": 900_000, "bit_depth": 8}
_UHD_DV = {
    "width": 3840,
    "height": 2160,
    "codec": "hevc",
    "bitrate": 90_000_000,
    "bit_depth": 10,
    "hdr_dolby_vision": True,
}
_HD_1080P = {"width": 1920, "height": 1080, "codec": "h264", "bitrate": 10_000_000, "bit_depth": 8}
_AAC_STEREO = [{"codec": "aac", "channels": 2, "bitrate": 128_000, "language": "fre"}]
_TRUEHD = [{"codec": "truehd atmos", "channels": 8, "bitrate": 4_000_000, "language": "eng"}]


class SubscoreClampTests(unittest.TestCase):
    def test_video_subscore_jamais_negatif(self):
        res = compute_quality_score(
            normalized_probe=_probe(_SD_480P, _AAC_STEREO),
            profile=default_quality_profile(),
            folder_name="Film (2023)",
            release_name="Film.2023.480p.WEBRip.x264-GRP.mkv",
            film_year=2023,
            encode_warnings=["upscale_suspect", "reencode_degraded"],
            tmdb_genres=["Action"],
        )
        self.assertGreaterEqual(res["metrics"]["subscores"]["video"], 0)
        # La narrative ne doit plus afficher de sous-score negatif "(-4/100)".
        # NB : la cle reelle est 'narrative' (il n'existe AUCUNE cle
        # 'narrative_rich' dans la sortie de compute_quality_score).
        narrative = str(res["explanation"]["narrative"])
        self.assertNotIn("(-", narrative, f"narrative={narrative}")
        # Meme garde cote explanation.categories (consomme par l'UI explain).
        self.assertGreaterEqual(res["explanation"]["categories"]["video"]["subscore"], 0)

    def test_video_subscore_jamais_au_dessus_de_100(self):
        res = compute_quality_score(
            normalized_probe=_probe(_UHD_DV, _TRUEHD),
            profile=default_quality_profile(),
            folder_name="Film (1965)",
            release_name="Film.1965.2160p.UHD.BluRay.REMUX.DV.TrueHD.7.1-GRP.mkv",
            film_year=1965,
            tmdb_genres=["Action"],
        )
        self.assertLessEqual(res["metrics"]["subscores"]["video"], 100)
        self.assertLessEqual(res["explanation"]["categories"]["video"]["subscore"], 100)

    def test_tous_les_subscores_dans_les_bornes(self):
        for label, kwargs in (
            (
                "sd_penalise",
                dict(
                    normalized_probe=_probe(_SD_480P, _AAC_STEREO),
                    film_year=2023,
                    encode_warnings=["upscale_suspect", "reencode_degraded", "4k_light"],
                    tmdb_genres=["Action"],
                    release_name="Film.2023.480p.WEBRip.x264-GRP.mkv",
                ),
            ),
            (
                "uhd_patrimoine",
                dict(
                    normalized_probe=_probe(_UHD_DV, _TRUEHD),
                    film_year=1965,
                    tmdb_genres=["Action"],
                    release_name="Film.1965.2160p.REMUX.DV.TrueHD.7.1-GRP.mkv",
                ),
            ),
        ):
            with self.subTest(cas=label):
                res = compute_quality_score(profile=default_quality_profile(), folder_name="Film", **kwargs)
                for name, value in res["metrics"]["subscores"].items():
                    self.assertGreaterEqual(value, 0, f"{label}.{name} = {value}")
                    self.assertLessEqual(value, 100, f"{label}.{name} = {value}")


class SubscoreClampNonRegressionTests(unittest.TestCase):
    """Assertions qui doivent rester VERTES des deux cotes de la mutation."""

    def test_subscores_en_plage_inchanges(self):
        # 1080p nominal : aucun sous-score hors bornes -> le re-clamp ne doit
        # RIEN changer (ni valeur, ni arrondi, ni type int deja en plage).
        res = compute_quality_score(
            normalized_probe=_probe(_HD_1080P, _AAC_STEREO),
            profile=default_quality_profile(),
            folder_name="Film (2015)",
            release_name="Film.2015.1080p.BluRay.x264-GRP.mkv",
        )
        subs = res["metrics"]["subscores"]
        # Valeurs mesurees a HEAD, identiques avant et apres le correctif
        # (aucun sous-score hors bornes sur ce fichier).
        self.assertEqual(subs, {"video": 56.0, "audio": 10, "extras": 90})
        self.assertEqual(res["score"], 46)
        self.assertEqual(res["tier"], "Bronze")

    def test_score_final_reste_borne(self):
        res = compute_quality_score(
            normalized_probe=_probe(_UHD_DV, _TRUEHD),
            profile=default_quality_profile(),
            folder_name="Film (1965)",
            release_name="Film.1965.2160p.REMUX.DV.TrueHD.7.1-GRP.mkv",
            film_year=1965,
        )
        self.assertGreaterEqual(res["score"], 0)
        self.assertLessEqual(res["score"], 100)


if __name__ == "__main__":
    unittest.main()

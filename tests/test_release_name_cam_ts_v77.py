"""GATE AUDIT 2026-06-10 (REAL 2/2) — l'extension de fichier `.ts` (MPEG-TS) ne
doit PAS etre detectee comme CAM/TeleSync.

Le caller passe le nom AVEC extension (str(row.video)). Avant le fix, `\bTS\b`
matchait l'extension `.ts` -> is_cam=True -> tier cape Bronze + facteur -30
"Captation degradee (TS)" sur tout fichier .ts sain. Un vrai token TS de release
est en milieu de nom, jamais l'extension finale.
"""

from __future__ import annotations

import unittest

from cinesort.domain.release_name_parser import parse_release_name


class ReleaseNameCamTsTests(unittest.TestCase):
    def test_ts_extension_not_cam(self) -> None:
        info = parse_release_name("Inception.2010.1080p.BluRay.x264-GRP.ts")
        self.assertFalse(info.is_cam, "l'extension .ts ne doit pas declencher CAM")
        self.assertNotEqual(info.source_hint, "cam")

    def test_plain_ts_file_not_cam(self) -> None:
        info = parse_release_name("MonFilm.ts")
        self.assertFalse(info.is_cam)

    def test_ts_extension_not_cam_source_hint(self) -> None:
        # GATE R2.3 : l'extension .ts ne doit PAS non plus forcer source_hint='cam'
        # via _PATTERNS_SOURCE (residu non couvert par le 1er fix 889d07a).
        self.assertNotEqual(parse_release_name("MonFilm.ts").source_hint, "cam")
        self.assertEqual(parse_release_name("Inception.2010.1080p.BluRay.x264-GRP.ts").source_hint, "bluray")
        self.assertEqual(parse_release_name("Film.2020.HDTV.ts").source_hint, "hdtv")
        # un vrai TS mid-name reste source 'cam'
        self.assertEqual(parse_release_name("Movie.2024.TS.x264-GRP.mkv").source_hint, "cam")

    def test_real_ts_token_midname_still_cam(self) -> None:
        # Un vrai TeleSync au milieu du nom reste detecte.
        info = parse_release_name("SomeMovie.2024.TS.x264-GRP.mkv")
        self.assertTrue(info.is_cam)
        self.assertEqual(info.cam_token, "ts")

    def test_hdts_still_cam(self) -> None:
        info = parse_release_name("SomeMovie.2024.HDTS.mkv")
        self.assertTrue(info.is_cam)

    def test_legit_cam_token_still_detected(self) -> None:
        info = parse_release_name("SomeMovie.2024.HDCAM.x264.mkv")
        self.assertTrue(info.is_cam)
        self.assertEqual(info.cam_token, "cam")


if __name__ == "__main__":
    unittest.main()

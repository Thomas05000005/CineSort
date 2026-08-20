# -*- coding: utf-8 -*-
"""Les canaux audio colles au codec (`DDP5.1`, `TrueHD7.1`) doivent etre lus.

Le defaut
---------
`_PATTERN_CHANNELS` ouvrait sur `\\b`. Dans `DDP5.1`, le caractere qui precede
le `5` est le `P` — une lettre — donc il n'y a AUCUNE frontiere de mot a cet
endroit et le motif ne matchait rien. Or `DDP5.1` / `DD5.1` / `TrueHD7.1` /
`AAC2.0` sont les formes les plus repandues des releases web.

Mesure avant correctif, sur 25 noms representatifs (cas negatifs inclus) :
16/25. Apres : 25/25, sans qu'aucun nom reconnu avant ne cesse de l'etre — le
jeu de matches du nouveau motif est un SUR-ENSEMBLE strict de l'ancien.

Ou ca fait mal
--------------
`audio_channels_hint` n'a que trois lecteurs, tous dans `quality_score`, tous
sur le chemin de repli par le NOM — celui qui sert justement quand le probe est
FAILED ou PARTIAL. Un `DDP5.1` y recevait une piste de synthese a **2 canaux**
(defaut « lossy => stereo »), et la compensation `probe_quality == "FAILED"`
retombait sur `+12` au lieu de `+18`. Le film etait score comme un stereo.

Ce fichier assert donc les DEUX bouts : le hint, et la piste reellement
synthetisee en aval.
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import _merge_probe_with_name_hints
from cinesort.domain.release_name_parser import parse_release_name


class CanauxCollesAuCodecTests(unittest.TestCase):
    def _canaux(self, nom: str) -> str:
        return parse_release_name(nom).audio_channels_hint

    def test_formes_collees_reconnues(self) -> None:
        cas = [
            ("Dune.2021.2160p.WEB-DL.DV.DDP5.1.H265-GRP.mkv", "5.1"),
            ("Dune.Part.Two.2024.2160p.WEB-DL.DDP5.1.Atmos.H.265-FLUX.mkv", "5.1"),
            ("Movie.2020.1080p.BluRay.DD5.1.x264-GRP.mkv", "5.1"),
            ("Movie.2018.1080p.BluRay.DTS5.1.x264-GRP.mkv", "5.1"),
            ("Movie.2020.2160p.UHD.BluRay.TrueHD7.1.Atmos.x265-GRP.mkv", "7.1"),
            ("Movie.2020.1080p.WEBRip.DDP2.0.x264-GRP.mkv", "2.0"),
            ("Movie.2020.1080p.WEBRip.AAC2.0.x264-GRP.mkv", "2.0"),
        ]
        for nom, attendu in cas:
            with self.subTest(nom=nom):
                self.assertEqual(self._canaux(nom), attendu)

    def test_formes_espacees_ou_pointees_inchangees(self) -> None:
        """Non-regression : ce que l'ancien motif trouvait deja."""
        cas = [
            ("12 Angry Men (1957) 2160p DV HDR BluRay DTS-HD MA 1.0 x265-GROUP.mkv", "1.0"),
            ("Inception (2010) 1080p BluRay x264 DTS-HD MA 5.1-FraMeSToR.mkv", "5.1"),
            ("Movie (2020) 720p WEB-DL x264 AAC 2.0-RARBG.mkv", "2.0"),
            ("Dune.Part.Two.2024.2160p.UHD.BluRay.x265.10bit.HDR.TrueHD.Atmos.7.1-SWTYBLZ.mkv", "7.1"),
            ("Movie.2018.2160p.BluRay.EAC3.5.1.Atmos-GRP.mkv", "5.1"),
        ]
        for nom, attendu in cas:
            with self.subTest(nom=nom):
                self.assertEqual(self._canaux(nom), attendu)

    def test_la_piste_la_plus_riche_gagne(self) -> None:
        """Deux pistes listees : la principale, pas la premiere rencontree."""
        self.assertEqual(self._canaux("Movie.2020.1080p.BluRay.AC3.2.0.DTS.5.1-GRP.mkv"), "5.1")
        self.assertEqual(self._canaux("Movie.2020.2160p.UHD.BluRay.DDP2.0.TrueHD.7.1.Atmos-GRP.mkv"), "7.1")
        self.assertEqual(self._canaux("Movie.2020.2160p.BluRay.DTS-HD.MA.5.1.DDP2.0-GRP.mkv"), "5.1")

    def test_aucun_couple_invente_sur_un_nombre_plus_long(self) -> None:
        """La queue d'un nombre n'est pas un couple de canaux."""
        cas = [
            "Movie.2012.1080p.BluRay.x264-GRP.mkv",  # contient '2.1'
            "Movie.5.10.2020.1080p.x264-GRP.mkv",  # contient '5.1'
            "2012.2009.1080p.BluRay.x264-GRP.mkv",
            "Movie.2021.2160p.WEB.H.265.10bit-GRP.mkv",
            "Blade.Runner.2049.2017.2160p.UHD.BluRay.x265-GRP.mkv",
            "Se7en.1995.1080p.BluRay.DTS-HD.MA.x264-GRP.mkv",
        ]
        for nom in cas:
            with self.subTest(nom=nom):
                self.assertEqual(self._canaux(nom), "")

    def test_la_piste_synthetisee_en_aval_porte_bien_six_canaux(self) -> None:
        """L'effet reel : sans le correctif, `DDP5.1` donnait une piste STEREO.

        On traverse le VRAI consommateur (`_merge_probe_with_name_hints`), pas
        seulement le hint : c'est lui qui fabrique la piste sur laquelle tout le
        sous-score audio est ensuite calcule.
        """
        infos = parse_release_name("Dune.2021.2160p.WEB-DL.DV.DDP5.1.H265-GRP.mkv")
        probe = {"video": {}, "audio_tracks": [], "probe_quality": "FAILED"}
        enrichi, combles = _merge_probe_with_name_hints(probe, infos)

        self.assertIn("audio_track_synth", combles, "la piste de synthese doit avoir ete creee")
        pistes = enrichi["audio_tracks"]
        self.assertEqual(len(pistes), 1)
        self.assertEqual(
            pistes[0]["channels"],
            6,
            "un DDP5.1 doit synthetiser 6 canaux ; 2 signifie que le hint de canaux est reste vide.",
        )


if __name__ == "__main__":
    unittest.main()

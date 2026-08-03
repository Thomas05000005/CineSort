"""F33 - "MA" ALL-CAPS ne doit plus etre strippe hors de son contexte.

L'alternative `(?-i:MA|HRA)` de _AUDIO_RESIDUE_RE ne protegeait que le
title-case "Ma" : toute release ALL-CAPS etait MUTILEE
("MA.2019.1080p.BluRay.x264-GRP" -> "2019", query TMDb purement numerique).

Le strip est desormais CONTEXTUEL, avec les deux seuls contextes reels :
  - _DTS_HD_MASTER_RE : "DTS-HD MA" / "DTS-HD HRA" (audio) ;
  - _WEB_SOURCE_MA_RE : "MA WEB-DL" / "MA WEBRip" (source Movies Anywhere).
Les deux s'appliquent AVANT _NOISE_RE, qui mangerait le contexte ("dts",
"web-dl") et laisserait un "MA" orphelin : les tests DTS/WEB ci-dessous sont
donc aussi le garde d'ordre du correctif.
"""

from __future__ import annotations

import unittest

from cinesort.domain.scene_parser import parse_scene_title


class AllCapsMaTitleTests(unittest.TestCase):
    def test_ma_alone_not_stripped(self):
        self.assertEqual(parse_scene_title("MA.2019.1080p.BluRay.x264-GRP.mkv"), "MA 2019")

    def test_ma_loute_not_mutilated(self):
        self.assertEqual(parse_scene_title("MA.LOUTE.2016.1080p.BluRay.x264-GRP.mkv"), "MA LOUTE 2016")

    def test_ma_vie_de_courgette_all_caps(self):
        self.assertEqual(
            parse_scene_title("MA.VIE.DE.COURGETTE.2016.1080p.BluRay.x264-GRP.mkv"),
            "MA VIE DE COURGETTE 2016",
        )

    def test_hra_alone_not_stripped(self):
        self.assertEqual(parse_scene_title("HRA.2019.1080p.BluRay.x264-GRP.mkv"), "HRA 2019")

    def test_ma_title_from_web_source_not_mutilated(self):
        """Le film "Ma" en WEB-DL : "MA" est suivi de l'ANNEE, pas de "WEB"."""
        self.assertEqual(parse_scene_title("MA.2019.1080p.WEB-DL.DDP5.1.H264-GRP.mkv"), "MA 2019")


class ContextualMaStillStrippedTests(unittest.TestCase):
    """Non-regression : les vrais tags MA restent strippes.

    Doit rester VERT des deux cotes de la mutation.
    """

    def test_dts_hd_ma_dotted(self):
        self.assertEqual(
            parse_scene_title("Movie.2015.1080p.BluRay.DTS-HD.MA.5.1.x264-Tigole.mkv"),
            "Movie 2015",
        )

    def test_dts_hdma_glued(self):
        self.assertEqual(
            parse_scene_title("Octopussy.1983.MULTi.2160p.WEBDL.DTS-HDMA.5.1.H265-AZAZE.mkv"),
            "Octopussy 1983",
        )

    def test_dts_hd_ma_spaced(self):
        self.assertEqual(
            parse_scene_title("Asterix et le domaine des dieux (2014) VOF HDLight DTS HD-MA 5.1 x265-MS.mkv"),
            "Asterix et le domaine des dieux",
        )

    def test_dts_hd_hra(self):
        self.assertEqual(
            parse_scene_title("Movie.2020.1080p.DTS-HD.HRA.5.1.x264-GRP.mkv"),
            "Movie 2020",
        )

    def test_movies_anywhere_web_dl_source_tag(self):
        self.assertEqual(
            parse_scene_title("Avatar.The.Way.of.Water.2022.1080p.MA.WEB-DL.DDP5.1.Atmos.H.264-FLUX"),
            "Avatar The Way of Water 2022",
        )

    def test_movies_anywhere_webrip_source_tag(self):
        self.assertEqual(parse_scene_title("Movie.2021.1080p.MA.WEBRip.x264-GRP.mkv"), "Movie 2021")

    def test_title_case_ma_preserved(self):
        """Garde historique AUDIT 2026-06-10 : "Ma Vie de Courgette"."""
        self.assertEqual(parse_scene_title("Ma Vie de Courgette (2016).mkv"), "Ma Vie de Courgette")

    def test_web_lookahead_requires_word_boundary(self):
        """Le mot "WEBSTER" ne doit pas activer le strip du tag source."""
        self.assertEqual(
            parse_scene_title("MA WEBSTER 2019 1080p BluRay x264-GRP.mkv"),
            "MA WEBSTER 2019",
        )

    def test_ma_en_tete_de_titre_jamais_mange_par_le_lookahead_web(self):
        """Le tag source exige une RESOLUTION avant lui, jamais un debut de nom.

        Defaut trouve en revue adversaire : le lookahead sur "web" seul suffisait
        a effacer un "MA" en tete de titre. `MA.WEB.2019...` rendait "WEB 2019" —
        le titre du film etait mutile, exactement la classe de defaut que ce
        finding devait supprimer, reintroduite par une autre porte.

        Regle du projet : une heuristique qui PEUT mutiler un titre doit etre
        ancree jusqu'a devenir non ambigue, ou abandonnee. Ici l'ancrage sur la
        resolution rend le cas impossible.
        """
        for nom in (
            "MA.WEB.2019.1080p.BluRay.x264-GRP.mkv",
            "MA.WEB-DL.2019.1080p.x264-GRP.mkv",
            "MA.WEBRip.2019.720p.x264-GRP.mkv",
        ):
            titre = parse_scene_title(nom)
            self.assertTrue(
                titre.startswith("MA"),
                f"titre mutile pour {nom!r} : {titre!r} — le 'MA' du titre a ete pris pour un tag source",
            )

    def test_tag_source_toujours_strippe_apres_une_resolution(self):
        """NON-REGRESSION : le vrai tag Movies Anywhere reste bien retire."""
        self.assertEqual(
            parse_scene_title("Movie.2021.2160p.MA.WEB-DL.DDP5.1.Atmos.HDR.H265-FLUX.mkv"),
            "Movie 2021",
        )


if __name__ == "__main__":
    unittest.main()

"""`DV` suivi d'un token commencant par `D` n'etait pas detecte.

Le motif etait :

    r"\\bDV\\b(?![A-Za-z0-9])(?!\\.?\\s*[Dd])"

Le second lookahead se voulait un garde « pas DVD ». Il n'en etait pas un :
dans `DVD`, `DVDRip`, `DVDScr` ou `HDV`, le caractere qui suit `DV` est un
caractere de mot, donc il n'y a AUCUNE frontiere a cet endroit et `\\bDV\\b` ne
matche deja pas. Ce que le lookahead ecartait reellement, c'est `DV` suivi d'un
separateur puis d'un `D` — soit `DV.DDP5.1`, `DV.DTS-HD.MA`, `DV DD5.1`, les
formes les plus repandues du nom de release 4K.

POURQUOI PERSONNE NE L'A VU : le seul test qui couvrait ce motif
(`test_quality_score_with_name_parsing.py::test_parse_uhd_dv_hdr_bluray_dts_hd_x265`)
utilise « 2160p **DV HDR** BluRay ». Le token suivant commence par `H`, donc le
lookahead reussit et la detection marche. Le test verrouillait le seul cas
favorable.

CE QUE CA COUTE : `quality_score._merge_probe_with_name_hints` ne pose
`video["hdr_dolby_vision"]` que si `hdr_hint == "dv"`, et uniquement quand le
probe n'expose AUCUN flag HDR — c'est-a-dire le seul cas ou ce parser sert
(probe PARTIAL/FAILED). Le film perdait donc tout l'apport HDR de son score.
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import _merge_probe_with_name_hints
from cinesort.domain.release_name_parser import parse_release_name


class DvSuiviDunTokenEnDTests(unittest.TestCase):
    def test_dv_suivi_de_ddp(self) -> None:
        info = parse_release_name("Dune.2021.2160p.WEB-DL.DV.DDP5.1.H265-GRP.mkv")
        self.assertEqual(info.hdr_hint, "dv")

    def test_dv_suivi_de_dts_hd(self) -> None:
        info = parse_release_name("Heat.1995.2160p.REMUX.DV.DTS-HD.MA.5.1-FraMeSToR.mkv")
        self.assertEqual(info.hdr_hint, "dv")

    def test_dv_suivi_de_dd_avec_un_espace(self) -> None:
        """Le lookahead tolerait `\\s*` : la forme a espaces echouait aussi."""
        info = parse_release_name("Movie (2021) 2160p BluRay DV DD5.1 x265-GRP.mkv")
        self.assertEqual(info.hdr_hint, "dv")

    def test_dv_suivi_dun_token_non_D_marche_toujours(self) -> None:
        """Le seul cas que l'ancien test couvrait — il ne doit pas regresser."""
        info = parse_release_name("12 Angry Men (1957) 2160p DV HDR BluRay DTS-HD MA 1.0 x265-GROUP.mkv")
        self.assertEqual(info.hdr_hint, "dv")


class PasDeFauxPositifSurLaFamilleDvdTests(unittest.TestCase):
    """Contre-epreuves : `\\bDV\\b` doit continuer d'exclure la famille DVD.

    C'est l'affirmation sur laquelle repose le retrait du lookahead. Si elle
    etait fausse, le correctif introduirait un faux positif « Dolby Vision » sur
    des DVDRip — l'inverse exact du but.
    """

    def test_dvdrip_nest_pas_du_dolby_vision(self) -> None:
        info = parse_release_name("Le.Grand.Bleu.1988.DVDRip.XviD.AC3-GRP.avi")
        self.assertEqual(info.hdr_hint, "")

    def test_dvd_seul_nest_pas_du_dolby_vision(self) -> None:
        info = parse_release_name("Movie.2003.DVD.x264-GRP.mkv")
        self.assertEqual(info.hdr_hint, "")

    def test_dvdscr_nest_pas_du_dolby_vision(self) -> None:
        info = parse_release_name("Movie.2003.DVDSCR.XviD-GRP.avi")
        self.assertEqual(info.hdr_hint, "")

    def test_hdv_nest_pas_du_dolby_vision(self) -> None:
        info = parse_release_name("Movie.2003.HDV.1080i-GRP.mkv")
        self.assertEqual(info.hdr_hint, "")


class ConsequenceSurLeScoringTests(unittest.TestCase):
    """La sortie que SEUL le correctif produit : le flag pose sur le probe.

    Asserter sur `hdr_hint` seul ne prouverait pas l'effet utilisateur — c'est
    `_merge_probe_with_name_hints` qui transforme le hint en signal de score.
    """

    def _probe_failed(self) -> dict:
        return {
            "probe_quality": "FAILED",
            "probe_quality_reasons": ["ffprobe a echoue."],
            "video": {},
            "audio_tracks": [],
            "sources": {},
        }

    def test_le_flag_dolby_vision_est_pose_sur_un_probe_failed(self) -> None:
        info = parse_release_name("Dune.2021.2160p.WEB-DL.DV.DDP5.1.H265-GRP.mkv")
        enrichi, combles = _merge_probe_with_name_hints(self._probe_failed(), info)

        self.assertTrue(
            enrichi["video"].get("hdr_dolby_vision"),
            "le nom porte DV mais le probe enrichi n'a pas le flag Dolby Vision",
        )
        self.assertIn("hdr_dolby_vision", combles)

    def test_un_dvdrip_ne_recoit_PAS_le_flag(self) -> None:
        info = parse_release_name("Le.Grand.Bleu.1988.DVDRip.XviD.AC3-GRP.avi")
        enrichi, combles = _merge_probe_with_name_hints(self._probe_failed(), info)

        self.assertFalse(enrichi["video"].get("hdr_dolby_vision"))
        self.assertNotIn("hdr_dolby_vision", combles)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Section 8 perceptuelle : une mesure qui n'a pas eu lieu ne s'annonce pas « propre ».

Le defaut
---------
`detect_judder` rendait `judder_none` sur ses QUATRE modes d'echec : chemin ou
outil manquant, duree inconnue, ffmpeg en echec (timeout / OSError /
returncode inattendu), et zero frame classee. Or `judder_none` n'est pas une
abstention, c'est un verdict FAVORABLE : il affirme que mpdecimate a tourne et
n'a rien trouve.

Les deux analyses SŒURS du meme module repondaient deja correctement sur le
meme mode d'echec — `_parse_idet_stderr` rend `unknown`, `classify_crop` rend
`unknown`. Le judder etait l'exception, et son propre test le disait sans le
voir : il s'appelait `test_timeout_returns_none` (« rend NONE ») et asserait
`judder_none` (« aucun judder »). La confusion vivait dans le nom du test.

Le second defaut, plus large
----------------------------
Les DEFAUTS du dataclass `VideoPerceptual` valaient `progressive`,
`full_frame` et `judder_none` : trois verdicts favorables portes par un objet
que personne n'a encore rempli. Les trois sondes sont optionnelles
(`perceptual_judder_detection_enabled` vaut meme `False` par defaut) et leur
resultat n'est recopie que `if ok` — ces defauts sont donc ce que porte le
rapport de la majorite des films. Tous les autres verdicts du meme dataclass
disaient deja `unknown` (`upscale_verdict`, `fake_4k_verdict_fft`,
`fake_4k_verdict_combined`, `GrainAnalysis.verdict`).

Meme famille que #923 (« mesure a 0 » n'est pas « non mesure »), #827
(confiance d'un verdict IMAX negatif), #804 (confiance fake 4K) et #1208
(un format HDR non reconnu note comme du SDR).

Ce que ces tests eprouvent, et dans quel ordre
-----------------------------------------------
1. les quatre modes d'echec de `detect_judder`, la panne injectee au niveau de
   `tracked_run` — c'est-a-dire la ou la production la subit, pas sur un faux
   `_run_ffmpeg_filter` qui fabriquerait la condition ;
2. le CONTRE-TEST : une mesure REELLE sans judder doit continuer de rendre
   `judder_none`. Sans lui, un correctif qui rendrait toujours « non mesure »
   passerait les quatre premiers tests en detruisant l'autre moitie de
   l'information ;
3. le SITE D'APPEL : le pipeline reel (`_execute_perceptual_analysis`), sondes
   de la section 8 coupees, doit produire un payload qui dit « non mesure ».
   Tester le dataclass seul ne dirait rien de ce que l'ecran recoit. Le
   harnais de #923 est REUTILISE, pas recopie : le recopier le ferait deriver.
4. un garde de DERIVE : les defauts du dataclass SONT les constantes que le
   module d'analyse rend. Remettre une chaine litterale d'un seul cote rougit.
"""

from __future__ import annotations

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from cinesort.domain.perceptual.constants import JUDDER_UNKNOWN, SECTION8_UNKNOWN
from cinesort.domain.perceptual.metadata_analysis import CropSegment, classify_crop, detect_judder
from cinesort.domain.perceptual.models import VideoPerceptual
from tests.test_perceptual_unmeasured_vs_zero_923 import _STDERR_MEDIOCRE, _run_pipeline

_TRACKED_RUN = "cinesort.domain.perceptual.metadata_analysis.tracked_run"


def _completed(stderr: str = "", returncode: int = 0) -> MagicMock:
    cp = MagicMock()
    cp.stdout = ""
    cp.stderr = stderr
    cp.returncode = returncode
    return cp


def _mpdecimate_stderr(drop: int, keep: int) -> str:
    """Sortie mpdecimate REELLE : une ligne par frame classee."""
    lignes = ["[Parsed_mpdecimate_0 @ 0x1] drop pts:512 pts_time:0.02"] * drop
    lignes += ["[Parsed_mpdecimate_0 @ 0x1] keep pts:512 pts_time:0.02"] * keep
    return "\n".join(lignes)


class DetectJudderNAffirmeRienSansMesureTests(unittest.TestCase):
    """Les quatre sorties sans mesure rendent `judder_unknown`."""

    def test_timeout_ffmpeg(self) -> None:
        with patch(_TRACKED_RUN, side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=30)):
            info = detect_judder("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.verdict, JUDDER_UNKNOWN)

    def test_oserror_ffmpeg(self) -> None:
        with patch(_TRACKED_RUN, side_effect=OSError("ffmpeg introuvable")):
            info = detect_judder("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.verdict, JUDDER_UNKNOWN)

    def test_returncode_inattendu(self) -> None:
        """`_run_ffmpeg_filter` tolere 0 et 1 ; au-dela il rend None."""
        with patch(_TRACKED_RUN, return_value=_completed(stderr="boom", returncode=69)):
            info = detect_judder("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.verdict, JUDDER_UNKNOWN)

    def test_aucune_frame_classee(self) -> None:
        """ffmpeg a repondu, mais aucune ligne drop/keep : rien n'a ete mesure."""
        with patch(_TRACKED_RUN, return_value=_completed(stderr="Output file is empty\n")):
            info = detect_judder("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.verdict, JUDDER_UNKNOWN)
        self.assertEqual(info.drop_count, 0)
        self.assertEqual(info.keep_count, 0)

    def test_duree_inconnue(self) -> None:
        """Sans duree, aucun segment n'est choisi — et ffmpeg n'est pas lance.

        Le `side_effect` sert d'assertion : s'il etait appele, l'AssertionError
        n'est rattrapee par aucun `except` de `_run_ffmpeg_filter` et le test
        echoue au lieu de passer pour la mauvaise raison.
        """
        with patch(_TRACKED_RUN, side_effect=AssertionError("ffmpeg ne doit pas etre lance")):
            info = detect_judder("ffmpeg", "x.mkv", 0.0)
        self.assertEqual(info.verdict, JUDDER_UNKNOWN)


class LaMesureReelleGardeSesVerdictsTests(unittest.TestCase):
    """CONTRE-TEST : le correctif ne doit pas tout repeindre en « non mesure »."""

    def test_mesure_sans_judder_reste_judder_none(self) -> None:
        with patch(_TRACKED_RUN, return_value=_completed(stderr=_mpdecimate_stderr(drop=0, keep=100))):
            info = detect_judder("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.verdict, "judder_none")
        self.assertEqual(info.keep_count, 100)

    def test_mesure_avec_judder_lourd_reste_judder_heavy(self) -> None:
        with patch(_TRACKED_RUN, return_value=_completed(stderr=_mpdecimate_stderr(drop=40, keep=60))):
            info = detect_judder("ffmpeg", "x.mkv", 7200.0)
        self.assertEqual(info.verdict, "judder_heavy")

    def test_crop_mesure_reste_full_frame(self) -> None:
        """Pendant pour le recadrage : seul le DEFAUT du dataclass changeait.

        `classify_crop` rendait deja `unknown` sans segment, et doit continuer
        de rendre `full_frame` quand le segment median couvre toute l'image.
        """
        segment = CropSegment(start_s=0.0, crop_w=1920, crop_h=1080, crop_x=0, crop_y=0, aspect_ratio=1.777)
        self.assertEqual(classify_crop([segment], 1920, 1080).verdict, "full_frame")
        self.assertEqual(classify_crop([], 1920, 1080).verdict, SECTION8_UNKNOWN)


class LesDefautsDuRapportDisentNonMesureTests(unittest.TestCase):
    """Un `VideoPerceptual` que personne n'a rempli n'affirme aucun verdict."""

    def test_defauts_du_dataclass(self) -> None:
        video = VideoPerceptual()
        self.assertEqual(video.interlace_type, SECTION8_UNKNOWN)
        self.assertEqual(video.crop_verdict, SECTION8_UNKNOWN)
        self.assertEqual(video.judder_verdict, JUDDER_UNKNOWN)

    def test_payload_serialise(self) -> None:
        """C'est `to_dict` qui atteint le client, pas les attributs."""
        payload = VideoPerceptual().to_dict()
        self.assertEqual(payload["interlacing"]["type"], SECTION8_UNKNOWN)
        self.assertEqual(payload["crop"]["verdict"], SECTION8_UNKNOWN)
        self.assertEqual(payload["judder"]["verdict"], JUDDER_UNKNOWN)

    def test_aucun_verdict_favorable_ne_subsiste_par_defaut(self) -> None:
        """Ancrage sur les valeurs EXACTES d'avant : un retour en arriere doit
        etre rouge, pas seulement « different »."""
        payload = VideoPerceptual().to_dict()
        self.assertNotEqual(payload["interlacing"]["type"], "progressive")
        self.assertNotEqual(payload["crop"]["verdict"], "full_frame")
        self.assertNotEqual(payload["judder"]["verdict"], "judder_none")


class LeSiteDAppelTransmetLeNonMesureTests(unittest.TestCase):
    """Le pipeline REEL, sondes section 8 coupees, ne doit rien affirmer.

    Les trois reglages sont a `False` dans le contexte du harnais : `meta_tasks`
    est donc vide et aucune des trois valeurs n'est ecrite. Ce test dit ce que
    l'utilisateur recoit alors, ce qu'aucune assertion sur le dataclass seul ne
    peut dire.
    """

    def test_sondes_coupees_le_payload_dit_non_mesure(self) -> None:
        perc = _run_pipeline(rc=0, stderr=_STDERR_MEDIOCRE)
        video = perc["video_perceptual"]
        self.assertEqual(video["interlacing"]["type"], SECTION8_UNKNOWN)
        self.assertEqual(video["crop"]["verdict"], SECTION8_UNKNOWN)
        self.assertEqual(video["judder"]["verdict"], JUDDER_UNKNOWN)
        # Le rapport a bien ete produit : le test ne passe pas parce que le
        # pipeline aurait echoue avant d'arriver la.
        self.assertTrue(video["banding"]["measured"])


class LesDeuxSourcesNePeuventPasDivergerTests(unittest.TestCase):
    """Garde de DERIVE entre le verdict rendu et le defaut du dataclass.

    Les deux valeurs vivent dans `constants` et sont importees des deux cotes.
    Remettre une chaine litterale d'un seul cote rend ce test rouge.
    """

    def test_le_defaut_est_la_constante(self) -> None:
        champs = {f.name: f.default for f in VideoPerceptual.__dataclass_fields__.values()}
        self.assertEqual(champs["judder_verdict"], JUDDER_UNKNOWN)
        self.assertEqual(champs["interlace_type"], SECTION8_UNKNOWN)
        self.assertEqual(champs["crop_verdict"], SECTION8_UNKNOWN)

    def test_le_verdict_rendu_est_la_constante(self) -> None:
        with patch(_TRACKED_RUN, side_effect=OSError("nope")):
            rendu = detect_judder("ffmpeg", "x.mkv", 7200.0).verdict
        self.assertEqual(rendu, JUDDER_UNKNOWN)
        self.assertEqual(classify_crop([], 1920, 1080).verdict, SECTION8_UNKNOWN)


if __name__ == "__main__":
    unittest.main()

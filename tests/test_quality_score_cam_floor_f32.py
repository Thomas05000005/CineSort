"""F32 : le plancher CAM doit survivre a la compensation probe FAILED.

Bug d'origine (reproduit a HEAD 529fcd0) : le plancher dur CAM/TS/Screener
(video_sub / audio_sub capes a 14) est pose AVANT la compensation probe FAILED
(+28 video, +32 audio lossless multicanal, +24 extras, -5 incertitude), qui n'a
aucune garde ``cam_detected`` et n'est jamais re-capee. Mesure :

    'Film.2026.CAM.2160p.REMUX.TrueHD.7.1.x265-GRP.mkv' + probe FAILED
        -> video 37.0 / audio 46.0, score 44, tier Bronze
    'Film.2026.CAM.XviD-GRP.mkv' (CAM honnete) + probe FAILED
        -> score 21, tier Reject

Le nom menteur valait donc 2x le plancher voulu, et remontait meme le tier de
Reject a Bronze - alors que le code affirme "peu importe les tokens premium
menteurs" (quality_score.py:1974-1977).
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import (
    compute_quality_score,
    default_quality_profile,
)

_CAM_CEILING = 14


def _failed_probe():
    return {"probe_quality": "FAILED", "video": {}, "audio_tracks": [], "sources": {}}


def _score(release_name: str):
    return compute_quality_score(
        normalized_probe=_failed_probe(),
        profile=default_quality_profile(),
        folder_name="Film (2026)",
        release_name=release_name,
    )


_CAM_MENTEUSE = "Film.2026.CAM.2160p.REMUX.TrueHD.7.1.x265-GRP.mkv"
_CAM_HONNETE = "Film.2026.CAM.XviD-GRP.mkv"
_NON_CAM = "Film.2026.2160p.BluRay.REMUX.TrueHD.7.1.x265-GRP.mkv"


class CamFloorSurvivesProbeCompensationTests(unittest.TestCase):
    def test_cam_avec_tokens_premium_reste_au_plancher(self):
        res = _score(_CAM_MENTEUSE)
        subs = res["metrics"]["subscores"]
        self.assertLessEqual(subs["video"], _CAM_CEILING, f"subscores={subs}")
        self.assertLessEqual(subs["audio"], _CAM_CEILING, f"subscores={subs}")

    def test_cam_menteuse_ne_depasse_pas_cam_honnete(self):
        menteuse = _score(_CAM_MENTEUSE)
        honnete = _score(_CAM_HONNETE)
        self.assertLessEqual(
            menteuse["score"] - honnete["score"],
            6,
            f"menteuse={menteuse['score']} honnete={honnete['score']}",
        )
        self.assertEqual(menteuse["tier"], honnete["tier"])

    def test_cam_menteuse_ne_remonte_pas_le_tier(self):
        # Le tier ne doit plus passer de Reject a Bronze grace aux tokens.
        self.assertEqual(_score(_CAM_MENTEUSE)["tier"], "Reject")


class CamFloorNonRegressionTests(unittest.TestCase):
    """Assertions qui doivent rester VERTES des deux cotes de la mutation."""

    def test_non_cam_probe_failed_garde_sa_compensation(self):
        # Seul le chemin CAM change : un REMUX legitime au probe FAILED
        # conserve sa compensation et son cap Silver.
        res = _score(_NON_CAM)
        self.assertGreater(res["metrics"]["subscores"]["video"], _CAM_CEILING)
        self.assertIn(res["tier"], ("Silver", "Bronze"))

    def test_cam_reste_plafonnee_a_bronze_ou_pire(self):
        # cap_tier CAM (quality_score.py:2192) reste l'autorite finale.
        for name in (_CAM_MENTEUSE, _CAM_HONNETE):
            with self.subTest(release=name):
                self.assertIn(_score(name)["tier"], ("Bronze", "Reject"))

    def test_extras_reste_hors_plancher(self):
        # Arbitrage produit explicite : extras mesure les metadonnees et le
        # nommage, pas la qualite image/son -> il n'est PAS plafonne.
        self.assertGreater(_score(_CAM_MENTEUSE)["metrics"]["subscores"]["extras"], _CAM_CEILING)


# Revue adversaire R1 (MEDIUM) : le re-plancher amplifiait un FAUX POSITIF du
# detecteur. `release_name_parser._PATTERNS_CAM` matche `\bCAM\b`, `\bTS\b`,
# `\bTC\b`, `\bWP\b`, `\bSCR\b` sur le nom COMPLET : un titre d'un seul mot
# court declenche is_cam=True. Le film Netflix "Cam" (2018) existe reellement.
# Avec un probe FAILED, un vrai UHD REMUX basculait de Bronze a Reject.
_TITRE_CAM_UHD = "Cam.2018.2160p.UHD.BluRay.REMUX.HDR.TrueHD.7.1.Atmos.x265-FraMeSToR.mkv"


class CamFauxPositifTitreEnTeteTests(unittest.TestCase):
    def test_titre_cam_en_tete_ne_declenche_pas_le_re_plancher(self):
        res = _score(_TITRE_CAM_UHD)
        subs = res["metrics"]["subscores"]
        self.assertGreater(subs["video"], _CAM_CEILING, f"subscores={subs}")
        self.assertGreater(subs["audio"], _CAM_CEILING, f"subscores={subs}")

    def test_titre_cam_en_tete_ne_bascule_pas_en_reject(self):
        self.assertEqual(_score(_TITRE_CAM_UHD)["tier"], "Bronze")

    def test_autres_abreviations_ambigues_en_tete(self):
        for name in (
            "Ts.2019.2160p.UHD.BluRay.REMUX.TrueHD.7.1-GRP.mkv",
            "Tc.2019.2160p.UHD.BluRay.REMUX.TrueHD.7.1-GRP.mkv",
            "Wp.2020.2160p.UHD.BluRay.REMUX.TrueHD.7.1-GRP.mkv",
            "Scr.2021.2160p.UHD.BluRay.REMUX.TrueHD.7.1-GRP.mkv",
        ):
            with self.subTest(release=name):
                self.assertGreater(_score(name)["metrics"]["subscores"]["video"], _CAM_CEILING)


class CamFauxPositifNonRegressionTests(unittest.TestCase):
    """Le durcissement ne doit RIEN relacher sur les vraies captations.

    Ces assertions doivent rester VERTES des deux cotes de la mutation.
    """

    def test_token_cam_apres_le_titre_reste_plafonne(self):
        # Position != 0 : marqueur de release legitime, F32 s'applique.
        subs = _score(_CAM_MENTEUSE)["metrics"]["subscores"]
        self.assertLessEqual(subs["video"], _CAM_CEILING, f"subscores={subs}")
        self.assertLessEqual(subs["audio"], _CAM_CEILING, f"subscores={subs}")

    def test_forme_longue_non_ambigue_en_tete_reste_plafonnee(self):
        # 'CAMRIP' / 'HDTS' / 'SCREENER' ne sont pas des titres de film : meme
        # en tete de nom, ils declenchent le plancher.
        for name in (
            "Camrip.2018.2160p.UHD.BluRay.REMUX.TrueHD.7.1-GRP.mkv",
            "Hdts.2018.2160p.UHD.BluRay.REMUX.TrueHD.7.1-GRP.mkv",
            "Screener.2018.2160p.UHD.BluRay.REMUX.TrueHD.7.1-GRP.mkv",
        ):
            with self.subTest(release=name):
                self.assertLessEqual(_score(name)["metrics"]["subscores"]["video"], _CAM_CEILING)

    def test_titre_cam_ET_vrai_marqueur_reste_plafonne(self):
        # Une vraie CAM du film "Cam" : 2e occurrence hors tete -> plancher.
        subs = _score("Cam.2018.CAM.XviD-GRP.mkv")["metrics"]["subscores"]
        self.assertLessEqual(subs["video"], _CAM_CEILING, f"subscores={subs}")

    def test_le_cap_de_tier_bronze_reste_l_autorite_finale(self):
        # Le durcissement ne touche NI le facteur -30, NI _cap_tier : meme le
        # faux positif reste plafonne a Bronze (il n'atteint jamais Silver+).
        for name in (_TITRE_CAM_UHD, _CAM_MENTEUSE, _CAM_HONNETE):
            with self.subTest(release=name):
                res = _score(name)
                self.assertIn(res["tier"], ("Bronze", "Reject"))
                self.assertTrue(
                    any("Captation degradee" in r for r in res["reasons"]),
                    f"le facteur CAM doit rester emis : {res['reasons']}",
                )


if __name__ == "__main__":
    unittest.main()

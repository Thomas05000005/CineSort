"""Lot « zones/score » : ce que le moteur ANNONCE doit etre ce qu'il FAIT.

Sept constats d'audit confirmes sur ``cinesort/domain/quality_score.py``. Le
denominateur commun : un chiffre (ou un fait) est PUBLIE — dans ``factors``,
dans ``reasons``, dans ``metrics.detected`` — sans que rien ne garantisse qu'il
correspond a ce qui a ete mesure, ni a ce qui a ete applique.

Chaque classe ci-dessous porte le mecanisme, pas seulement le symptome.
"""

from __future__ import annotations

import unittest

from cinesort.domain.encode_analysis import analyze_encode_quality
from cinesort.domain.quality_score import (
    _score_video,
    compute_quality_score,
    default_quality_profile,
)

# ---------------------------------------------------------------------------
# Fabriques de probes
# ---------------------------------------------------------------------------


def _probe_1080p_sans_audio() -> dict:
    """Video mesuree, AUCUNE piste audio : le terrain du fallback par le nom."""
    return {
        "probe_quality": "FULL",
        "video": {
            "codec": "avc",
            "width": 1920,
            "height": 1080,
            "bitrate": 1_200_000,
            "bit_depth": 8,
        },
        "audio_tracks": [],
        "sources": {},
    }


def _profil_hierarchie_active() -> dict:
    prof = default_quality_profile()
    prof["tier_hierarchy"]["enabled"] = True
    return prof


def _deltas(res: dict, categorie: str) -> list:
    """Deltas annonces d une categorie, SANS troncature.

    La version d origine faisait `int(...)`. Or `_apply_cam_subscore_floor`
    emet DELIBEREMENT un delta fractionnaire quand la chute ne tombe pas juste
    (`delta = int(chute) if float(chute).is_integer() else chute`,
    quality_score.py:1704) — c est le cas des que le multiplicateur de genre a
    deplace le sous-score avant l ecrasement.

    Tronquer ici annulait donc exactement la precision que la production prend
    soin de garder : un -0.5 annonce devenait 0, et l assertion passait alors
    que l explication restait numeriquement fausse. Le test ne pouvait plus
    detecter l ecart qu il existe pour mesurer.
    """
    return [float(f.get("delta") or 0) for f in res["explanation"]["factors"] if f.get("category") == categorie]


# ---------------------------------------------------------------------------
# IDX 0 (CRITIQUE) — la garde « nom menteur » existe pour le HDR, pas l'AUDIO
# ---------------------------------------------------------------------------


class FloorAudioHierarchieSurNomMenteurTests(unittest.TestCase):
    """`hdr_is_probe` (quality_score.py:2630) neutralise le floor HDR quand le
    flag vient du nom de release (correctif trash-r6-001). La dimension AUDIO
    n'a aucun equivalent : `_hierarchy_audio_codec_token(best_audio)` est
    passe tel quel, alors que `best_audio` peut etre la piste SYNTHETISEE par
    `_merge_probe_with_name_hints` — donc deduite du seul nom de fichier.
    """

    def test_nom_menteur_truehd_atmos_ne_promeut_pas_le_tier(self):
        res = compute_quality_score(
            normalized_probe=_probe_1080p_sans_audio(),
            profile=_profil_hierarchie_active(),
            release_name="Film.2020.1080p.WEB-DL.TrueHD.Atmos.7.1.x264-MENTEUR",
        )
        raisons_hierarchie = [r for r in res["reasons"] if "Hierarchie qualite floor (audio)" in r]
        self.assertEqual(
            raisons_hierarchie,
            [],
            "le floor audio a ete arme par un codec que le probe n'a JAMAIS vu "
            f"(tier={res['tier']}, raisons={raisons_hierarchie})",
        )

    def test_reference_le_meme_nom_sans_hierarchie_reste_bas(self):
        """Temoin : sans hierarchie, ce fichier est un Reject. C'est l'ampleur
        de la promotion que le floor arme par le nom accordait."""
        prof = default_quality_profile()
        res = compute_quality_score(
            normalized_probe=_probe_1080p_sans_audio(),
            profile=prof,
            release_name="Film.2020.1080p.WEB-DL.TrueHD.Atmos.7.1.x264-MENTEUR",
        )
        self.assertIn(res["tier"], ("Reject", "Bronze"))

    def test_une_piste_truehd_atmos_REELLEMENT_mesuree_arme_toujours_le_floor(self):
        """La garde ne doit pas eteindre le floor : mesuree, la piste compte.

        Sans cette moitie, le correctif serait indiscernable d'une suppression
        pure et simple de la dimension audio.
        """
        probe = _probe_1080p_sans_audio()
        probe["audio_tracks"] = [
            {"codec": "truehd", "is_atmos": True, "channels": 8, "bitrate": 4_000_000, "language": "en"},
        ]
        res = compute_quality_score(
            normalized_probe=probe,
            profile=_profil_hierarchie_active(),
            release_name="Film.2020.1080p.BluRay.x264-HONNETE",
        )
        self.assertTrue(
            any("Hierarchie qualite floor (audio)" in r for r in res["reasons"]),
            f"floor audio perdu sur une piste MESUREE (reasons={res['reasons']})",
        )
        self.assertEqual(res["tier"], "Gold")


# ---------------------------------------------------------------------------
# IDX 1 (MAJEUR) — le bloc resolution applique +34/+24/+14/+4, annonce autre
# ---------------------------------------------------------------------------


class ResolutionAnnoncePasCeQuElleAppliqueTests(unittest.TestCase):
    """`_score_video` ajoute +34/+24/+14/+4 a `video_sub` et publie +16/+11,
    +10/+7, +5, -6 via `add_reason`. Ces deltas alimentent `factors`,
    `reasons` et `explanation.weighted_delta`. Pour la SD, le SIGNE est
    inverse : +4 applique, -6 annonce.

    L'invariant teste est celui que la campagne « Hotfix coherence 2026-06-04 »
    a retabli partout ailleurs dans ce meme helper : la somme des deltas
    annonces, ajoutee a la base 8.0, doit redonner le sous-score video.
    """

    def _sub_et_somme(self, video: dict, release_name: str = "") -> tuple:
        reasons: list = []
        factors: list = []
        vr = _score_video(
            video,
            default_quality_profile(),
            folder_name="",
            release_name=release_name,
            reasons=reasons,
            factors=factors,
        )
        return float(vr["sub"]), 8.0 + sum(int(f["delta"]) for f in factors)

    def test_1080p_mesure(self):
        sub, somme = self._sub_et_somme(
            {"codec": "avc", "width": 1920, "height": 1080, "bitrate": 9_000_000, "bit_depth": 8}
        )
        self.assertEqual(sub, somme, "les deltas annonces ne reconstituent pas video_sub (1080p)")

    def test_2160p_mesure(self):
        sub, somme = self._sub_et_somme(
            {"codec": "hevc", "width": 3840, "height": 2160, "bitrate": 21_000_000, "bit_depth": 10}
        )
        self.assertEqual(sub, somme, "les deltas annonces ne reconstituent pas video_sub (2160p)")

    def test_720p(self):
        sub, somme = self._sub_et_somme(
            {"codec": "avc", "width": 1280, "height": 720, "bitrate": 4_000_000, "bit_depth": 8}
        )
        self.assertEqual(sub, somme, "les deltas annonces ne reconstituent pas video_sub (720p)")

    def test_SD_le_signe_est_inverse(self):
        sub, somme = self._sub_et_somme(
            {"codec": "avc", "width": 720, "height": 480, "bitrate": 1_500_000, "bit_depth": 8}
        )
        self.assertEqual(
            sub,
            somme,
            "la SD annonce une PENALITE (-6) la ou le code accorde un BONUS (+4)",
        )

    def test_resolution_deduite_du_nom(self):
        sub, somme = self._sub_et_somme(
            {"codec": "hevc", "width": 0, "height": 0, "bitrate": 21_000_000, "bit_depth": 10},
            release_name="Film.2020.2160p.WEB-DL.x265-GRP",
        )
        self.assertEqual(sub, somme, "les deltas annonces ne reconstituent pas video_sub (nom)")


# ---------------------------------------------------------------------------
# IDX 2 (MAJEUR) — le nombre de canaux est INVENTE puis publie comme detecte
# ---------------------------------------------------------------------------


class CanauxInventesTests(unittest.TestCase):
    """`_merge_probe_with_name_hints` synthetise une piste quand le probe n'en
    rend aucune, et choisit `6 if audio_is_lossless else 2` en l'absence de
    tout token de canaux dans le nom. Cette valeur, qui ne vient NI du
    fichier NI du nom, ressort en `metrics.detected.audio_best_channels`,
    alimente le bonus « Canaux 5.1 » et le champ `audio_channels` des regles
    utilisateur (custom_rules.py:38). La piste fantome est de plus comptee en
    `metrics.detected.audio_tracks_count`.
    """

    def _res_sans_token_de_canaux(self) -> dict:
        return compute_quality_score(
            normalized_probe=_probe_1080p_sans_audio(),
            profile=default_quality_profile(),
            release_name="Film.2020.1080p.BluRay.DTS-HD.MA.x264-GRP",
        )

    def test_les_canaux_ne_sont_pas_inventes(self):
        det = self._res_sans_token_de_canaux()["metrics"]["detected"]
        self.assertEqual(
            det["audio_best_channels"],
            0,
            "un 5.1 que personne n'a mesure ni meme nomme est publie comme detecte",
        )

    def test_aucun_bonus_de_canaux_nest_annonce(self):
        res = self._res_sans_token_de_canaux()
        self.assertEqual(
            [r for r in res["reasons"] if "Canaux" in r],
            [],
            "un bonus de canaux est accorde sur une valeur fabriquee",
        )

    def test_la_piste_fantome_nest_pas_comptee_comme_detectee(self):
        det = self._res_sans_token_de_canaux()["metrics"]["detected"]
        self.assertEqual(det["audio_tracks_count"], 0, "la piste synthetique est comptee comme mesuree")

    def test_la_provenance_audio_est_declaree(self):
        """Symetrie avec `sources.video.codec = 'name_fallback'` : rien ne
        signalait cote audio que tout venait du nom."""
        src = self._res_sans_token_de_canaux()["metrics"]["sources"]
        self.assertEqual(str((src.get("audio") or {}).get("codec") or ""), "name_fallback")
        self.assertEqual(str((src.get("audio") or {}).get("channels") or ""), "unknown")

    def test_un_token_de_canaux_present_dans_le_nom_reste_lu(self):
        """Contre-epreuve : ce qui est ECRIT dans le nom n'est pas invente."""
        res = compute_quality_score(
            normalized_probe=_probe_1080p_sans_audio(),
            profile=default_quality_profile(),
            release_name="Film.2020.1080p.BluRay.DTS-HD.MA.5.1.x264-GRP",
        )
        det = res["metrics"]["detected"]
        self.assertEqual(det["audio_best_channels"], 6)
        src = res["metrics"]["sources"]
        self.assertEqual(str((src.get("audio") or {}).get("channels") or ""), "name_fallback")


# ---------------------------------------------------------------------------
# IDX 3 (MAJEUR) — la CAM annonce -30 et ECRASE en realite a 14.0
# ---------------------------------------------------------------------------


class CamAnnonceUnChiffreFixePourUnEcrasementTests(unittest.TestCase):
    """La detection CAM ne retranche pas 30 : elle ECRASE `video_sub` ET
    `audio_sub` a `_CAM_SUBSCORE_CEILING = 14.0`. Le facteur publie est un
    -30 constant, range en categorie `video` ; la chute AUDIO, elle, n'est
    annoncee par aucun facteur ni aucune raison.
    """

    def _res_cam(self) -> dict:
        probe = {
            "probe_quality": "FULL",
            "video": {
                "codec": "hevc",
                "width": 3840,
                "height": 2160,
                "bitrate": 40_000_000,
                "bit_depth": 10,
                "hdr10": True,
            },
            "audio_tracks": [
                {"codec": "truehd", "is_atmos": True, "channels": 8, "bitrate": 4_000_000, "language": "en"},
            ],
            "sources": {},
        }
        return compute_quality_score(
            normalized_probe=probe,
            profile=default_quality_profile(),
            release_name="Film.2020.CAM.2160p.REMUX.TrueHD.Atmos.7.1.HEVC-GRP",
        )

    def test_le_sous_score_video_annonce_est_celui_qui_est_applique(self):
        res = self._res_cam()
        self.assertEqual(res["metrics"]["subscores"]["video"], 14.0)
        self.assertAlmostEqual(
            8.0 + sum(_deltas(res, "video")),
            14.0,
            places=6,
            msg="les facteurs video n'expliquent pas l'ecrasement CAM",
        )

    def test_la_chute_audio_est_annoncee(self):
        res = self._res_cam()
        self.assertEqual(res["metrics"]["subscores"]["audio"], 14.0)
        self.assertAlmostEqual(
            12.0 + sum(_deltas(res, "audio")),
            14.0,
            places=6,
            msg="l'audio tombe de plus de 20 points sans qu'aucun facteur ne le dise",
        )


# ---------------------------------------------------------------------------
# IDX 7 (MAJEUR) — deux verites pour le codec de la meilleure piste
# ---------------------------------------------------------------------------


class DoubleComptageAtmosTests(unittest.TestCase):
    """La garde anti-double-comptage du bonus « Atmos detecte dans le nom »
    (quality_score.py:2428) interroge le champ BRUT `best_audio['codec']`,
    alors que `_score_audio` (:1303) a deja bonifie la piste via l'etiquette
    CANONIQUE `_canonical_audio_codec` — laquelle derive l'Atmos de
    `is_atmos` / `profile`, pas de `codec`. Sur un probe ffprobe reel
    (`codec='truehd'`, `is_atmos=True`), la garde ne voit rien et le +3 du nom
    s'ajoute a un bonus qui comptait deja l'Atmos.
    """

    def test_atmos_porte_par_is_atmos_neutralise_le_bonus_du_nom(self):
        probe = {
            "probe_quality": "FULL",
            "video": {"codec": "hevc", "width": 3840, "height": 2160, "bitrate": 40_000_000, "bit_depth": 10},
            "audio_tracks": [
                {"codec": "truehd", "is_atmos": True, "channels": 8, "bitrate": 4_000_000, "language": "en"},
            ],
            "sources": {},
        }
        res = compute_quality_score(
            normalized_probe=probe,
            profile=default_quality_profile(),
            release_name="Film.2020.2160p.BluRay.REMUX.TrueHD.Atmos.7.1.HEVC-GRP",
        )
        self.assertEqual(
            [r for r in res["reasons"] if "Atmos detecte dans le nom" in r],
            [],
            "l'Atmos deja compte par l'etiquette canonique est bonifie une seconde fois",
        )

    def test_atmos_absent_du_probe_donne_toujours_le_bonus_du_nom(self):
        """Contre-epreuve : la garde ne doit pas tuer le cas qu'elle sert."""
        probe = {
            "probe_quality": "FULL",
            "video": {"codec": "hevc", "width": 3840, "height": 2160, "bitrate": 40_000_000, "bit_depth": 10},
            "audio_tracks": [
                {"codec": "truehd", "channels": 8, "bitrate": 4_000_000, "language": "en"},
            ],
            "sources": {},
        }
        res = compute_quality_score(
            normalized_probe=probe,
            profile=default_quality_profile(),
            release_name="Film.2020.2160p.BluRay.REMUX.TrueHD.Atmos.7.1.HEVC-GRP",
        )
        self.assertTrue(
            any("Atmos detecte dans le nom" in r for r in res["reasons"]),
            "le bonus Atmos du nom a disparu alors que le probe ne le porte pas",
        )


# ---------------------------------------------------------------------------
# IDX 4 (MINEUR) — la taille EXACTE est disponible, on publie une estimation
# ---------------------------------------------------------------------------


class TailleFichierExacteTests(unittest.TestCase):
    """`_estimate_file_size` recalcule `duration_s * bitrate_video / 8` alors
    que le dict recu porte `container_size_bytes`, alimente depuis
    `format.size` de ffprobe (infra/probe/_normalize_ffprobe.py:174). L'ecart
    n'est pas cosmetique : le debit utilise est celui de la VIDEO seule, donc
    la taille publiee ignore l'audio et les sous-titres.
    """

    def test_la_taille_lue_par_ffprobe_prime_sur_l_estimation(self):
        probe = {
            "probe_quality": "FULL",
            "video": {"codec": "hevc", "width": 3840, "height": 2160, "bitrate": 20_000_000, "bit_depth": 10},
            "audio_tracks": [{"codec": "eac3", "channels": 6, "bitrate": 640_000, "language": "en"}],
            "sources": {},
            "duration_s": 7200.0,
            "container_size_bytes": 21_000_000_000,
        }
        res = compute_quality_score(normalized_probe=probe, profile=default_quality_profile())
        self.assertEqual(
            res["metrics"]["detected"]["file_size_bytes"],
            21_000_000_000,
            "la taille EXACTE lue par ffprobe est ignoree au profit d'une estimation video-seule",
        )

    def test_sans_taille_conteneur_l_estimation_reste(self):
        probe = {
            "probe_quality": "FULL",
            "video": {"codec": "hevc", "width": 3840, "height": 2160, "bitrate": 20_000_000, "bit_depth": 10},
            "audio_tracks": [{"codec": "eac3", "channels": 6, "bitrate": 640_000, "language": "en"}],
            "sources": {},
            "duration_s": 7200.0,
        }
        res = compute_quality_score(normalized_probe=probe, profile=default_quality_profile())
        self.assertEqual(res["metrics"]["detected"]["file_size_bytes"], int(7200.0 * 20_000 * 1000 / 8))


# ---------------------------------------------------------------------------
# IDX 16 (MINEUR) — le malus grain lit un canal qui ne peut pas le porter
# ---------------------------------------------------------------------------


class GrainInatteignableParEncodeWarningsTests(unittest.TestCase):
    """`has_grain_g` (quality_score.py:1801) cherche la sous-chaine « grain »
    dans `encode_warnings`. Le SEUL producteur de cette liste cote appelant de
    `compute_quality_score` est `analyze_encode_quality`
    (ui/api/quality_report_support.py:212), dont le vocabulaire complet est
    ferme. Ce test EPINGLE ce vocabulaire : tant qu'aucun de ses flags ne
    porte « grain », le `grain_malus` de `genre_rules` est inatteignable en
    production, et le jour ou un flag est ajoute, ce test le signale au lieu
    de laisser le cablage se faire (ou ne pas se faire) en silence.
    """

    def test_le_vocabulaire_de_analyze_encode_quality_est_ferme(self):
        vus: set = set()
        for width, height in ((3840, 2160), (1920, 1080), (1280, 720), (720, 480), (0, 0)):
            for codec in ("hevc", "h264", "avc", "av1", ""):
                for bitrate in (0, 300, 1500, 6000, 12_000, 30_000):
                    vus.update(
                        analyze_encode_quality(
                            {"width": width, "height": height, "video_codec": codec, "bitrate_kbps": bitrate}
                        )
                    )
        self.assertEqual(vus, {"upscale_suspect", "4k_light", "reencode_degraded"})
        self.assertEqual(
            [f for f in vus if "grain" in f],
            [],
            "un flag grain existe desormais : cabler has_heavy_grain au lieu de le laisser inerte",
        )


if __name__ == "__main__":
    unittest.main()


class LeHelperDeMESUREDoitMesurerTests(unittest.TestCase):
    """Le harnais lui-meme, signale par une revue automatique sur la PR.

    `_deltas` tronquait par `int()`. Or `_apply_cam_subscore_floor` emet
    DELIBEREMENT un delta fractionnaire quand la chute ne tombe pas juste
    (`quality_score.py:1704`). Un `-0.5` annonce devenait donc `0`, et les deux
    assertions « l'annonce explique le sous-score » passaient alors que
    l'explication restait numeriquement fausse.

    Un instrument de mesure qui arrondit ce qu'il vient mesurer ne mesure plus.
    """

    def test_un_delta_fractionnaire_survit_a_la_lecture(self) -> None:
        faux = {
            "explanation": {
                "factors": [
                    {"category": "video", "delta": -0.5, "label": "chute CAM partielle"},
                    {"category": "video", "delta": -8, "label": "entier"},
                    {"category": "audio", "delta": -1.25, "label": "autre categorie"},
                ]
            }
        }
        self.assertEqual(_deltas(faux, "video"), [-0.5, -8.0])
        self.assertAlmostEqual(sum(_deltas(faux, "video")), -8.5, places=6)

    def test_la_somme_ne_perd_pas_la_fraction(self) -> None:
        """Sans ce garde, `int()` rendrait -8 et l'ecart de 0.5 disparaitrait."""
        faux = {"explanation": {"factors": [{"category": "video", "delta": -0.5}]}}
        self.assertNotEqual(sum(_deltas(faux, "video")), 0, "la fraction a ete tronquee")

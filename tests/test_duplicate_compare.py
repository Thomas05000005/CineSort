"""Tests comparaison qualite doublons — cinesort/domain/duplicate_compare.py.

Couvre :
- Resolution : 1080p vs 720p → A gagne
- HDR : HDR10 vs SDR → A gagne
- Codec video : HEVC vs x264 → A gagne
- Audio codec : TrueHD vs AC3 → A gagne
- Audio canaux : 7.1 vs 5.1 → A gagne
- Bitrate : meme codec, A plus haut → A gagne ; codecs differents → skip
- Egalite parfaite → tie
- Probe manquante : criteres connus seulement (aucun connu -> tie, cf. #20)
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


class CodecHorsTableTests(unittest.TestCase):
    """Un codec ABSENT de la table ne doit pas etre traite comme le PIRE.

    `_video_codec_rank_value` faisait `_VIDEO_CODEC_RANK.get(codec, 0)` sur une
    table de dix etiquettes (av1, hevc, h265, x265, h264, x264, avc, mpeg4,
    xvid, divx). Tout autre codec REEL tombait donc a 0, soit SOUS xvid et divx
    qui valent 1.

    Codecs concernes, mesures le 2026-08-29 : vc1 (Blu-ray), mpeg2video (DVD),
    vp9, prores, wmv3, msmpeg4v3 — tous rendus 0.

    CONSEQUENCE MESUREE, avec un probe construit par `_build_pseudo_probe`
    (run_flow_support.py, le SEUL producteur de probes du comparateur) :

        A = Blu-ray VC-1  1080p 25,0 Mbps  21,0 Go
        B = DivX          1080p  1,5 Mbps   1,3 Go

        Resolution   1080p / 1080p        egalite     0
        Codec video  ?     / xvid         B         -15
        Bitrate      25,0  / 1,5 Mbps     unknown     0
        Taille       21,0  / 1,3 Go       egalite     0   (informatif par design)
        --> verdict global : « Garder B, archiver A »

    Le produit recommandait donc d'archiver le Blu-ray au profit du DivX, en
    AFFICHANT les deux debits juste a cote de sa recommandation. Et ce verdict
    est applicable en masse via « Auto-decider tous », qui deplace les perdants
    en `_review/_duplicates_user_decided/` a l'apply.

    Le remede n'invente aucun rang : « je ne connais pas ce codec » et « ce
    codec est le pire » sont deux affirmations differentes. La fonction rendait
    deja `None` pour un codec VIDE — l'inconnu recoit le meme traitement, et
    `_compare_criterion` le rend alors `unknown` a 0 point, chemin deja exerce.

    NE PAS « corriger » aussi le saut du bitrate entre codecs differents : il
    est DELIBERE et garde par `test_different_codec_skip_bitrate`. Comparer
    5 Mbps de HEVC a 20 Mbps de h264 n'a pas de sens.
    """

    HORS_TABLE = ("vc1", "mpeg2video", "vp9", "prores", "wmv3", "msmpeg4v3")

    def test_un_codec_hors_table_ne_perd_pas_contre_xvid(self) -> None:
        for codec in self.HORS_TABLE:
            with self.subTest(codec=codec):
                criteres = compare_by_criteria(
                    _probe(height=1080, codec=codec, bitrate=25000000),
                    _probe(height=1080, codec="xvid", bitrate=1500000),
                )
                c = next(x for x in criteres if x.name == "video_codec")
                self.assertEqual(
                    c.winner,
                    "unknown",
                    f"`{codec}` inconnu doit rendre un verdict inconnu, pas une defaite",
                )
                self.assertEqual(c.points_delta, 0)

    def test_le_bluray_vc1_n_est_plus_archive_au_profit_du_divx(self) -> None:
        """Le cas complet : le verdict global ne doit plus designer le DivX."""
        r = compare_duplicates(
            _probe(height=1080, codec="vc1", bitrate=25000000, audio_codec="dts", channels=6),
            _probe(height=1080, codec="mpeg4", bitrate=1500000, audio_codec="dts", channels=6),
        )
        self.assertNotEqual(r.winner, "b", "le DivX ne doit plus gagner contre un Blu-ray VC-1")

    def test_les_codecs_connus_gardent_leur_rang(self) -> None:
        """CONTRE-TEST : rendre l'inconnu neutre ne doit pas neutraliser le connu.

        Vert avant comme apres. Si ce test rougit, le remede est alle trop loin
        et a desarme le critere pour tout le monde.
        """
        criteres = compare_by_criteria(
            _probe(height=1080, codec="hevc"),
            _probe(height=1080, codec="xvid"),
        )
        c = next(x for x in criteres if x.name == "video_codec")
        self.assertEqual(c.winner, "a")
        self.assertGreater(c.points_delta, 0)

    def test_un_codec_vide_reste_inconnu(self) -> None:
        """CONTRE-TEST : le comportement deja correct du codec ABSENT est preserve."""
        criteres = compare_by_criteria(
            _probe(height=1080, codec=""),
            _probe(height=1080, codec="hevc"),
        )
        c = next(x for x in criteres if x.name == "video_codec")
        self.assertEqual(c.winner, "unknown")


class CodecAudioHorsTableTests(unittest.TestCase):
    """Meme invariant que `CodecHorsTableTests`, sur le rang AUDIO.

    `_video_codec_rank_value` distingue « inconnu » de « pire » depuis le
    2026-08-29. `_audio_codec_rank_value`, vingt lignes plus bas dans le MEME
    fichier, gardait `.get(..., 0)` sur son repli par alias : tout codec dont
    l'etiquette canonique n'est ni une cle de `AUDIO_CODEC_RANK` ni un de ses
    alias tombait a 0, soit SOUS l'AAC et le MP3 (rang 1).

    Le depot affirmait pourtant le contraire par ecrit — la docstring de
    `ProbeManquanteTests` de ce fichier enumere « `_hdr_rank_value`,
    `_video_codec_rank_value`, `_audio_codec_rank_value` rendent None ». C'etait
    vrai du codec ABSENT, faux du codec hors table.

    Cas interne au depot, et il se lit sans connaitre aucune bibliotheque :
    `codec_ranks.est_lossless` declare `mlp` SANS PERTE (:171), tandis que les
    deux tables de rang l'ignorent — le meme codec valait donc « lossless » d'un
    cote et « pire que l'AAC » de l'autre. `codec_ranks` signale lui-meme cet
    ecart comme « a instruire » (:148-152).

    Le remede n'invente aucun rang : donner une place a `mlp` reste un arbitrage
    produit. Il rend `unknown` a 0 point, chemin deja exerce par le codec vide.
    """

    HORS_TABLE = ("mlp", "mlp fba", "vorbis", "wmav2", "alac")

    def test_un_codec_audio_hors_table_ne_perd_pas_contre_aac(self) -> None:
        for codec in self.HORS_TABLE:
            with self.subTest(codec=codec):
                criteres = compare_by_criteria(
                    _probe(height=1080, codec="hevc", audio_codec=codec, channels=6),
                    _probe(height=1080, codec="hevc", audio_codec="aac", channels=6),
                )
                c = next(x for x in criteres if x.name == "audio_codec")
                self.assertEqual(
                    c.winner,
                    "unknown",
                    f"`{codec}` inconnu doit rendre un verdict inconnu, pas une defaite",
                )
                self.assertEqual(c.points_delta, 0)

    def test_le_verdict_global_ne_designe_plus_l_aac(self) -> None:
        """Le cas complet : seul l'audio discrimine, donc le verdict bascule.

        Avant, `audio_codec` valait -15 (poids plein) pour un seul seuil de tie a
        5 : le comparateur recommandait « Garder B, archiver A », et
        « Auto-decider tous » l'appliquait en masse.
        """
        r = compare_duplicates(
            _probe(height=1080, codec="hevc", bitrate=25000000, audio_codec="mlp", channels=6),
            _probe(height=1080, codec="hevc", bitrate=25000000, audio_codec="aac", channels=6),
        )
        self.assertNotEqual(r.winner, "b", "un codec audio inconnu ne doit plus faire perdre le fichier")

    def test_les_codecs_audio_connus_gardent_leur_rang(self) -> None:
        """CONTRE-TEST : rendre l'inconnu neutre ne doit pas neutraliser le connu.

        Vert avant comme apres. Si ce test rougit, le remede est alle trop loin
        et a desarme le critere pour tout le monde.
        """
        criteres = compare_by_criteria(
            _probe(height=1080, codec="hevc", audio_codec="truehd", channels=6),
            _probe(height=1080, codec="hevc", audio_codec="aac", channels=6),
        )
        c = next(x for x in criteres if x.name == "audio_codec")
        self.assertEqual(c.winner, "a")
        self.assertGreater(c.points_delta, 0)

    def test_les_etiquettes_composees_gardent_leur_alias(self) -> None:
        """CONTRE-TEST : le repli par alias reste actif (il ne rend PAS None).

        `dts:x` et `ac-3` n'ont pas de cle propre dans `AUDIO_CODEC_RANK` : ils
        passent par `_AUDIO_CANONICAL_RANK_ALIAS`. Une lecture trop large du
        remede supprimerait ce repli avec le defaut.
        """
        criteres = compare_by_criteria(
            _probe(height=1080, codec="hevc", audio_codec="dts:x", channels=6),
            _probe(height=1080, codec="hevc", audio_codec="ac-3", channels=6),
        )
        c = next(x for x in criteres if x.name == "audio_codec")
        self.assertEqual(c.winner, "a", "dts:x (alias -> dts-hd ma) doit battre ac-3 (alias -> ac3)")

    def test_un_codec_audio_vide_reste_inconnu(self) -> None:
        """CONTRE-TEST : le comportement deja correct du codec ABSENT est preserve."""
        criteres = compare_by_criteria(
            _probe(height=1080, codec="hevc", audio_codec="", channels=6),
            _probe(height=1080, codec="hevc", audio_codec="aac", channels=6),
        )
        c = next(x for x in criteres if x.name == "audio_codec")
        self.assertEqual(c.winner, "unknown")


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
        """Une probe entierement absente -> TOUS les criteres s'abstiennent, donc tie.

        Ce test attendait `winner == "a"` et son propre commentaire disait
        pourquoi : « A a des donnees concretes (canaux 8 vs 0) ». C'etait le
        constat #20 de l'ultra-audit 2026-08-31 ecrit en assertion. Les CINQ
        autres criteres s'abstenaient deja face a une probe absente
        (`_hdr_rank_value`, `_video_codec_rank_value`, `_audio_codec_rank_value`
        rendent None ; le bitrate a sa branche `unknown`) : seul le critere des
        canaux tranchait, et uniquement parce que son site d'appel coercait
        `int(... or 0)` AVANT `_compare_criterion`, transformant une absence de
        mesure en la PIRE valeur possible.

        Le verdict honnete d'une comparaison ou l'on ne sait RIEN de B est
        « Qualite equivalente, garder les deux ». L'inverse envoyait B en
        _review/_duplicates_user_decided/ au premier « Auto-decider tous ».
        (Aucun impact production : `run_flow_support._enrich_one_group` refuse
        deja d'appeler le comparateur quand une probe est None.)
        """
        r = compare_duplicates(
            _probe(height=1080, codec="hevc", audio_codec="truehd", channels=8),
            None,
        )
        self.assertEqual(r.winner, "tie")
        self.assertTrue(
            all(c.winner in {"unknown", "tie"} for c in r.criteria),
            [(c.name, c.winner, c.points_delta) for c in r.criteria],
        )
        canaux = next(c for c in r.criteria if c.name == "audio_channels")
        self.assertEqual((canaux.value_a, canaux.value_b), ("7.1", "?"))
        self.assertEqual(canaux.points_delta, 0)

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


class PerceptualScoreSymmetryTests(unittest.TestCase):
    """Issue #598 : delta perceptual doit etre symetrique entre A et B.

    Avant fix : (pa - pb) // 5 utilisait floor division (rounds vers -inf),
    donc -1 // 5 == -1 (winner=b) mais 1 // 5 == 0 (winner=tie).
    Apres fix : int((pa - pb) / 5) truncate vers 0, symetrique.
    """

    def _probe_pair(self):
        return _probe(height=1080, codec="hevc"), _probe(height=1080, codec="hevc")

    def test_small_diff_in_favor_of_a_is_tie(self) -> None:
        pa_probe, pb_probe = self._probe_pair()
        r = compare_duplicates(pa_probe, pb_probe, perceptual_score_a=100, perceptual_score_b=99)
        perc = next(c for c in r.criteria if c.name == "perceptual")
        self.assertEqual(perc.winner, "tie")
        self.assertEqual(perc.points_delta, 0)

    def test_small_diff_in_favor_of_b_is_tie(self) -> None:
        """Symetrique avec le precedent (regression pour le fix de #598)."""
        pa_probe, pb_probe = self._probe_pair()
        r = compare_duplicates(pa_probe, pb_probe, perceptual_score_a=99, perceptual_score_b=100)
        perc = next(c for c in r.criteria if c.name == "perceptual")
        self.assertEqual(perc.winner, "tie")
        self.assertEqual(perc.points_delta, 0)

    def test_4_points_diff_is_still_tie_on_both_sides(self) -> None:
        pa_probe, pb_probe = self._probe_pair()
        r_pos = compare_duplicates(pa_probe, pb_probe, perceptual_score_a=100, perceptual_score_b=96)
        r_neg = compare_duplicates(pa_probe, pb_probe, perceptual_score_a=96, perceptual_score_b=100)
        self.assertEqual(next(c for c in r_pos.criteria if c.name == "perceptual").points_delta, 0)
        self.assertEqual(next(c for c in r_neg.criteria if c.name == "perceptual").points_delta, 0)

    def test_5_points_diff_gives_symmetric_signed_delta(self) -> None:
        pa_probe, pb_probe = self._probe_pair()
        r_pos = compare_duplicates(pa_probe, pb_probe, perceptual_score_a=100, perceptual_score_b=95)
        r_neg = compare_duplicates(pa_probe, pb_probe, perceptual_score_a=95, perceptual_score_b=100)
        self.assertEqual(next(c for c in r_pos.criteria if c.name == "perceptual").points_delta, 1)
        self.assertEqual(next(c for c in r_neg.criteria if c.name == "perceptual").points_delta, -1)


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

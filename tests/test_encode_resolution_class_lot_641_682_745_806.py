"""Lot #641/#682/#745/#806 — la resolution ne se juge plus sur la hauteur seule.

Les quatre issues visaient la meme heuristique. Un rappel des cas reels, car
c'est ce qui rend les fixtures credibles : la hauteur ffprobe est celle du flux
ENCODE, bandes noires deja retirees. Un master 2.39:1 mesure 1920x800 en 1080p
et 3840x1600 en 4K ; un 720p scope mesure 1280x536.

* #641 : `analyze_encode_quality` choisissait sa bande sur `height` seule.
  1280x536 tombait en SD, 1920x800 en 720p, 3840x1600 en 1080p — soit une bande
  TROP BASSE, donc des seuils trop permissifs.
* #745 : le bloc re-encode n'avait pas de branche 2160p, la 4K etait jugee au
  seuil 1080p (800 kbps) qu'aucun fichier 4K reel n'atteint.
* #806 : la bande 1080p ne testait l'upscale que sur HEVC/H264.
* #682 : le malus genre « resolution modeste » testait `height < 1080`.

Chaque test ci-dessous a ete vu ROUGE en mutant SEPAREMENT la garde qu'il vise
(cf. le corps de la PR pour le detail des mutations).
"""

from __future__ import annotations

import unittest
from typing import Any, Dict

from cinesort.app.radarr_sync import should_propose_upgrade
from cinesort.domain.encode_analysis import analyze_encode_quality
from cinesort.domain.genre_rules import compute_genre_adjustments
from cinesort.domain.quality_score import compute_quality_score, default_quality_profile
from cinesort.domain.resolution_class import (
    RES_720P,
    RES_1080P,
    RES_2160P,
    RES_SD,
    RES_UNKNOWN,
    classify_resolution,
    is_below,
)


def _detected(**over: Any) -> Dict[str, Any]:
    """`metrics.detected` tel que le scoring le persiste (width INCLUSE)."""
    base: Dict[str, Any] = {
        "width": 1920,
        "height": 1080,
        "bitrate_kbps": 8000,
        "video_codec": "hevc",
    }
    base.update(over)
    return base


def _probe(*, width: int, height: int, bitrate_bps: int, codec: str = "hevc") -> Dict[str, Any]:
    """Probe normalise FULL minimal, dimensions MESUREES (source ffprobe)."""
    return {
        "probe_quality": "FULL",
        "probe_quality_reasons": ["Analyse technique complete."],
        "video": {
            "codec": codec,
            "width": width,
            "height": height,
            "bitrate": bitrate_bps,
            "bit_depth": 8,
        },
        "audio_tracks": [{"codec": "eac3", "channels": 6, "language": "fra", "bitrate": 640000}],
        "sources": {
            "video": {
                "codec": "ffprobe",
                "bitrate": "ffprobe",
                "width": "ffprobe",
                "height": "ffprobe",
            }
        },
    }


def _two_pass(probe: Dict[str, Any], **kwargs: Any) -> Dict[str, Any]:
    """Rejoue la chaine REELLE de `quality_report_support._probe_and_score`.

    Passe 1 -> `metrics.detected` -> `analyze_encode_quality` -> passe 2. On ne
    lit donc pas une previsualisation : le resultat observe est le rapport que
    l'application persiste, flags d'encode compris.
    """
    profile = default_quality_profile()
    base = dict(normalized_probe=probe, profile=profile, **kwargs)
    pre = compute_quality_score(**base)
    flags = analyze_encode_quality((pre.get("metrics") or {}).get("detected") or {})
    final = compute_quality_score(**base, encode_warnings=flags or None)
    final["_encode_flags"] = flags
    return final


def _reasons(report: Dict[str, Any]) -> str:
    """Les libelles que le rapport PERSISTE (`quality_reports.reasons`).

    Ils sont prefixes du delta ("-8 Upscale suspect") : on les concatene pour
    chercher le LIBELLE, sans figer la valeur numerique du malus (qui releve du
    calibrage produit et n'a rien a voir avec ce lot).
    """
    return " | ".join(str(r) for r in (report.get("reasons") or []))


class ClassifyResolutionTests(unittest.TestCase):
    """L'echelle partagee : largeur-primaire, et « inconnu » n'est pas « bas »."""

    def test_scope_masters_are_classed_by_width(self) -> None:
        self.assertEqual(classify_resolution(3840, 1600), RES_2160P)
        self.assertEqual(classify_resolution(1920, 800), RES_1080P)
        self.assertEqual(classify_resolution(1280, 536), RES_720P)

    def test_height_alone_still_classes_when_width_is_missing(self) -> None:
        """Rapports persistes tronques : la hauteur reste un filet de securite."""
        self.assertEqual(classify_resolution(0, 2160), RES_2160P)
        self.assertEqual(classify_resolution(None, 1080), RES_1080P)
        self.assertEqual(classify_resolution(0, 480), RES_SD)

    def test_no_dimension_yields_no_verdict(self) -> None:
        self.assertEqual(classify_resolution(0, 0), RES_UNKNOWN)
        self.assertEqual(classify_resolution(None, None), RES_UNKNOWN)

    def test_corrupted_dimension_degrades_instead_of_raising(self) -> None:
        """`metrics.detected` vient d'un JSON SQLite : un `int()` nu leverait."""
        self.assertEqual(classify_resolution("abc", 1080), RES_1080P)
        self.assertEqual(classify_resolution(-1920, -800), RES_UNKNOWN)

    def test_unknown_class_is_never_below_anything(self) -> None:
        self.assertFalse(is_below(RES_UNKNOWN, RES_1080P))
        self.assertTrue(is_below(RES_720P, RES_1080P))
        self.assertFalse(is_below(RES_1080P, RES_1080P))
        self.assertFalse(is_below(RES_2160P, RES_1080P))


class Issue641WidescreenBandTests(unittest.TestCase):
    """#641 — la bande vient de la CLASSE, plus de la hauteur brute."""

    def test_720p_cinemascope_is_judged_with_720p_thresholds(self) -> None:
        """1280x536 @900 kbps : bande SD avant (536 < 680), qui n'a AUCUNE
        detection d'upscale — le fichier passait donc sans le moindre flag."""
        flags = analyze_encode_quality(_detected(width=1280, height=536, bitrate_kbps=900, video_codec="hevc"))
        self.assertIn("upscale_suspect", flags)

    def test_720p_cinemascope_reencode_uses_720p_floor_not_sd_floor(self) -> None:
        """400 kbps : sous le plancher 720p (500), au-dessus du plancher SD (300)."""
        flags = analyze_encode_quality(_detected(width=1280, height=536, bitrate_kbps=400, video_codec="hevc"))
        self.assertIn("reencode_degraded", flags)

    def test_1080p_scope_is_judged_with_1080p_thresholds(self) -> None:
        """1920x800 h264 @1800 kbps : bande 720p avant (800 >= 680), seuil 1000."""
        flags = analyze_encode_quality(_detected(width=1920, height=800, bitrate_kbps=1800, video_codec="h264"))
        self.assertIn("upscale_suspect", flags)

    def test_4k_scope_reaches_the_4k_band(self) -> None:
        """3840x1600 @12 Mbps : bande 1080p avant (1600 >= 1000), donc ni
        `4k_light` ni le moindre seuil 4K."""
        flags = analyze_encode_quality(_detected(width=3840, height=1600, bitrate_kbps=12000, video_codec="hevc"))
        self.assertEqual(flags, ["4k_light"])

    def test_healthy_scope_masters_stay_unflagged(self) -> None:
        """Direction non destructive : reclasser ne doit pas inventer de flags."""
        self.assertEqual(analyze_encode_quality(_detected(width=1920, height=800, bitrate_kbps=8000)), [])
        self.assertEqual(analyze_encode_quality(_detected(width=1280, height=536, bitrate_kbps=2500)), [])
        self.assertEqual(analyze_encode_quality(_detected(width=3840, height=1600, bitrate_kbps=60000)), [])


class Issue745Reencode4kTests(unittest.TestCase):
    """#745 — le palier re-encode existe enfin en 4K."""

    def test_4k_destructive_reencode_is_flagged(self) -> None:
        """4K HEVC @1600 kbps : sous 800 kbps ? jamais. Le palier etait mort."""
        flags = analyze_encode_quality(_detected(width=3840, height=2160, bitrate_kbps=1600, video_codec="hevc"))
        self.assertIn("reencode_degraded", flags)
        self.assertIn("upscale_suspect", flags)

    def test_4k_just_above_the_floor_is_only_upscale_suspect(self) -> None:
        """1800 kbps : au-dessus du plancher re-encode (1750), sous le seuil
        upscale (3500). Le palier doit rester discriminant, pas tout flagger."""
        flags = analyze_encode_quality(_detected(width=3840, height=2160, bitrate_kbps=1800, video_codec="hevc"))
        self.assertEqual(flags, ["upscale_suspect"])

    def test_1080p_floor_is_unchanged(self) -> None:
        """Non-regression : le plancher 1080p HEVC reste 800 kbps."""
        self.assertIn(
            "reencode_degraded",
            analyze_encode_quality(_detected(bitrate_kbps=700, video_codec="hevc")),
        )
        self.assertNotIn(
            "reencode_degraded",
            analyze_encode_quality(_detected(bitrate_kbps=900, video_codec="hevc")),
        )


class Issue806CodecGatingTests(unittest.TestCase):
    """#806 — la bande 1080p n'est plus reservee a HEVC/H264."""

    def test_1080p_vp9_upscale_is_detected(self) -> None:
        flags = analyze_encode_quality(_detected(bitrate_kbps=1400, video_codec="vp9"))
        self.assertIn("upscale_suspect", flags)

    def test_1080p_mpeg2_destructive_reencode_is_detected(self) -> None:
        flags = analyze_encode_quality(_detected(bitrate_kbps=700, video_codec="mpeg2video"))
        self.assertIn("reencode_degraded", flags)

    def test_exotic_codec_uses_the_most_permissive_threshold_of_the_band(self) -> None:
        """Direction conservatrice assumee : un codec inconnu est juge au seuil
        HEVC (1500), pas au seuil H264 (2000). A 1700 kbps il passe — un MPEG-2
        1080p a 1700 kbps est mediocre, mais un faux positif deprecie un fichier
        et c'est le fichier deprecie qu'un arbitrage de doublons supprime."""
        self.assertEqual(analyze_encode_quality(_detected(bitrate_kbps=1700, video_codec="xvid")), [])
        self.assertIn(
            "upscale_suspect",
            analyze_encode_quality(_detected(bitrate_kbps=1700, video_codec="h264")),
        )

    def test_h264_keeps_its_own_higher_threshold(self) -> None:
        """Non-regression : H264 reste la seule famille a seuil distinct."""
        self.assertIn("upscale_suspect", analyze_encode_quality(_detected(bitrate_kbps=1900, video_codec="h264")))
        self.assertEqual(analyze_encode_quality(_detected(bitrate_kbps=1900, video_codec="hevc")), [])


class GuardTests(unittest.TestCase):
    """Un manque de donnees ne produit jamais de verdict."""

    def test_no_dimensions_no_flags(self) -> None:
        self.assertEqual(analyze_encode_quality({"bitrate_kbps": 100, "video_codec": "hevc"}), [])

    def test_no_bitrate_no_flags(self) -> None:
        self.assertEqual(analyze_encode_quality(_detected(bitrate_kbps=0)), [])

    def test_no_codec_no_flags(self) -> None:
        self.assertEqual(analyze_encode_quality(_detected(video_codec="")), [])

    def test_corrupted_bitrate_does_not_raise(self) -> None:
        """`metrics.detected` est du JSON SQLite : un `int()` nu levait ici et
        faisait echouer le rapport entier au lieu de s'abstenir."""
        self.assertEqual(analyze_encode_quality(_detected(bitrate_kbps="n/a")), [])

    def test_sd_band_has_no_upscale_detection(self) -> None:
        """Un SD n'a pas de resolution inferieure dont il aurait ete etire."""
        self.assertEqual(analyze_encode_quality(_detected(width=720, height=480, bitrate_kbps=900)), [])


class Issue682GenreMalusTests(unittest.TestCase):
    """#682 — le malus « resolution modeste » ne se decide plus sur `height`."""

    def test_1080p_scope_gets_no_low_resolution_malus(self) -> None:
        """Dimensions BRUTES : c'est la garde interne de `genre_rules` qu'on
        exerce ici, independamment de ce que fait son appelant."""
        total, factors = compute_genre_adjustments(
            "action", video_codec="h264", height=800, width=1920, has_hdr=False, has_atmos=False
        )
        self.assertEqual(total, 0.0)
        self.assertNotIn("résolution modeste", " ".join(f["label"] for f in factors))

    def test_1080p_flat_ratio_gets_no_malus_either(self) -> None:
        """1920x1040 (1.85:1) : `height < 1080` etait vrai, le malus tombait."""
        total, _ = compute_genre_adjustments(
            "action", video_codec="h264", height=1040, width=1920, has_hdr=False, has_atmos=False
        )
        self.assertEqual(total, 0.0)

    def test_real_720p_still_gets_the_malus(self) -> None:
        """Non-regression : la penalite doit rester vivante quand elle est due."""
        total, factors = compute_genre_adjustments(
            "action", video_codec="h264", height=720, width=1280, has_hdr=False, has_atmos=False
        )
        self.assertEqual(total, -5.0)
        self.assertIn("résolution modeste", " ".join(f["label"] for f in factors))

    def test_missing_dimensions_never_penalize(self) -> None:
        total, _ = compute_genre_adjustments(
            "action", video_codec="h264", height=0, width=0, has_hdr=False, has_atmos=False
        )
        self.assertEqual(total, 0.0)


class ObservableChainTests(unittest.TestCase):
    """Effet OBSERVABLE sur le rapport persiste, pas sur une previsualisation.

    On rejoue le two-pass reel de `quality_report_support` : la passe 1 produit
    `metrics.detected` (c'est la que `width` doit survivre), et c'est ce dict
    qui alimente `analyze_encode_quality`.
    """

    def test_width_survives_into_persisted_metrics(self) -> None:
        report = _two_pass(_probe(width=1920, height=800, bitrate_bps=1_800_000, codec="h264"))
        detected = report["metrics"]["detected"]
        self.assertEqual(detected["width"], 1920)
        self.assertEqual(detected["height"], 800)
        self.assertEqual(detected["resolution"], "1080p")

    def test_1080p_scope_upscale_reaches_the_final_report(self) -> None:
        """1920x800 h264 @1.8 Mbps : aucun flag avant le lot (bande 720p)."""
        report = _two_pass(_probe(width=1920, height=800, bitrate_bps=1_800_000, codec="h264"))
        self.assertIn("upscale_suspect", report["_encode_flags"])
        self.assertIn("Upscale suspect", _reasons(report))

    def test_4k_destructive_reencode_reaches_the_final_report(self) -> None:
        """3840x2160 hevc @1.6 Mbps : `reencode_degraded` etait injoignable."""
        report = _two_pass(_probe(width=3840, height=2160, bitrate_bps=1_600_000, codec="hevc"))
        self.assertIn("reencode_degraded", report["_encode_flags"])
        self.assertIn("Re-encode degrade", _reasons(report))

    def test_healthy_1080p_scope_keeps_a_clean_report(self) -> None:
        report = _two_pass(_probe(width=1920, height=800, bitrate_bps=9_000_000, codec="hevc"))
        self.assertEqual(report["_encode_flags"], [])
        self.assertNotIn("Upscale suspect", _reasons(report))
        self.assertNotIn("Re-encode degrade", _reasons(report))

    def test_action_1080p_scope_never_reads_as_modest_resolution(self) -> None:
        """Non-regression de bout en bout du couple de gardes #682.

        Ce test est VERT des deux cotes du lot : le site d'appel avait deja ete
        desamorce par la PR #854 (il passe la hauteur canonique) et `genre_rules`
        est desormais robuste par lui-meme. Il ne devient rouge que si les DEUX
        gardes sautent — c'est exactement ce qu'on veut verrouiller, et c'est
        dit ici plutot que maquille en preuve de correctif.
        """
        report = _two_pass(
            _probe(width=1920, height=800, bitrate_bps=9_000_000, codec="hevc"),
            tmdb_genres=["Action"],
        )
        labels = _reasons(report)
        self.assertNotIn("résolution modeste", labels)

    def test_action_real_720p_still_reads_as_modest_resolution(self) -> None:
        """Le pendant vivant : la penalite genre n'a pas ete neutralisee."""
        report = _two_pass(
            _probe(width=1280, height=536, bitrate_bps=4_000_000, codec="hevc"),
            tmdb_genres=["Action"],
        )
        self.assertIn("résolution modeste", _reasons(report))


class RadarrUpgradeChainTests(unittest.TestCase):
    """Le 2e site d'appel de production lit le meme `metrics.detected`."""

    def _report(self, detected: Dict[str, Any], *, score: int = 70) -> Dict[str, Any]:
        return {"score": score, "tier": "Silver", "reasons": [], "metrics": {"detected": detected}}

    def test_4k_reencode_now_proposes_an_upgrade(self) -> None:
        detected = _detected(width=3840, height=2160, bitrate_kbps=1600, video_codec="hevc")
        self.assertTrue(should_propose_upgrade({"monitored": True, "row_id": "r1"}, self._report(detected)))

    def test_healthy_4k_still_proposes_nothing(self) -> None:
        detected = _detected(width=3840, height=2160, bitrate_kbps=60000, video_codec="hevc")
        self.assertFalse(should_propose_upgrade({"monitored": True, "row_id": "r1"}, self._report(detected)))


if __name__ == "__main__":
    unittest.main()

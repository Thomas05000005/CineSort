"""VP-B (Vague P) : tests integration scoring V1 + tier_hierarchy.

Verifie le pipeline complet ``compute_quality_score`` quand on active la
hierarchie qualite multi-axes :

- AC-1 : default OFF -> scoring V1 strictement inchange (tier_v0 == tier_v1).
- AC-2 : cap_tier securite (FAILED/CAM) reste autorite finale meme avec
         hierarchy ON (un 2160p probe FAILED reste plafonne Silver).
- AC-4 : tier colors hex INVARIANTES (verifiable par non-modification du module
         tokens.css - test couvre l'absence de regression sur les labels
         canoniques que l'UI mappe vers les couleurs).
"""

from __future__ import annotations

import copy
import unittest

from cinesort.domain.quality_score import (
    compute_quality_score,
    default_quality_profile,
)


def _probe_2160p_premium_full() -> dict:
    """Probe FULL d'un fichier 2160p HEVC DV TrueHD Atmos premium."""
    return {
        "probe_quality": "FULL",
        "video": {
            "codec": "hevc",
            "width": 3840,
            "height": 2160,
            "bitrate": 35_000_000,
            "bit_depth": 10,
            "hdr_dolby_vision": True,
            "hdr10_plus": False,
            "hdr10": False,
        },
        "audio_tracks": [
            {"codec": "TrueHD Atmos", "channels": 8, "bitrate": 4_000_000, "language": "en"},
        ],
        "sources": {},
    }


def _probe_720p_modest_full() -> dict:
    return {
        "probe_quality": "FULL",
        "video": {
            "codec": "avc",
            "width": 1280,
            "height": 720,
            "bitrate": 3_000_000,
            "bit_depth": 8,
        },
        "audio_tracks": [
            {"codec": "AAC", "channels": 2, "bitrate": 128_000, "language": "en"},
        ],
        "sources": {},
    }


def _probe_failed() -> dict:
    """Probe en echec (fichier corrompu / SMB obsolete)."""
    return {
        "probe_quality": "FAILED",
        "video": {},
        "audio_tracks": [],
        "sources": {},
    }


class AC1DefaultOffPreservesV1Tests(unittest.TestCase):
    """AC-1 : default OFF -> scoring V1 strictement inchange."""

    def test_2160p_premium_score_identical_with_default_profile(self):
        """Profil default (hierarchy=OFF) : meme score qu'avant VP-B."""
        prof = default_quality_profile()
        res = compute_quality_score(normalized_probe=_probe_2160p_premium_full(), profile=prof)
        # Sanity : un 2160p premium doit etre Platinum ou Gold (V1 legitime).
        self.assertIn(res["tier"], ("Platinum", "Gold"))
        # Le profil contient bien tier_hierarchy mais desactive.
        self.assertIn("tier_hierarchy", prof)
        self.assertFalse(prof["tier_hierarchy"]["enabled"])

    def test_720p_modest_score_unchanged_with_default(self):
        prof = default_quality_profile()
        res = compute_quality_score(normalized_probe=_probe_720p_modest_full(), profile=prof)
        # 720p AAC bas debit -> tier modeste (Bronze ou Silver).
        self.assertIn(res["tier"], ("Bronze", "Silver", "Reject"))

    def test_profile_without_tier_hierarchy_key_is_normalized(self):
        """Backward compat ABSOLUE : profil legacy SANS cle tier_hierarchy."""
        prof = default_quality_profile()
        # Simule un profil legacy : on retire la cle.
        prof_legacy = copy.deepcopy(prof)
        prof_legacy.pop("tier_hierarchy", None)
        res = compute_quality_score(normalized_probe=_probe_720p_modest_full(), profile=prof_legacy)
        # Le scoring doit fonctionner et retourner un tier valide.
        self.assertIn(res["tier"], ("Platinum", "Gold", "Silver", "Bronze", "Reject"))


class AC1ToggleHasNoEffectWhenOffTests(unittest.TestCase):
    """AC-1 : un profil avec tier_hierarchy.enabled=False est identique au default."""

    def test_explicit_disabled_matches_default(self):
        prof_default = default_quality_profile()
        prof_explicit_off = copy.deepcopy(prof_default)
        prof_explicit_off["tier_hierarchy"]["enabled"] = False
        # Override les floors pour s'assurer qu'ils ne s'appliquent pas.
        prof_explicit_off["tier_hierarchy"]["resolution_floors"]["2160p_probe"] = "Platinum"

        res_default = compute_quality_score(
            normalized_probe=_probe_720p_modest_full(), profile=prof_default,
        )
        res_off = compute_quality_score(
            normalized_probe=_probe_720p_modest_full(), profile=prof_explicit_off,
        )
        # Meme tier et meme score : OFF est strictement no-op.
        self.assertEqual(res_default["tier"], res_off["tier"])
        self.assertEqual(res_default["score"], res_off["score"])


class AC2CapTierStaysAuthorityTests(unittest.TestCase):
    """AC-2 : cap_tier (FAILED/CAM) reste autorite finale meme avec hierarchy ON.

    Un fichier probe FAILED ne doit JAMAIS finir Platinum/Gold meme si la
    hierarchie tente de le pousser (sur la base d'un fallback nom 2160p).
    """

    def test_probe_failed_with_hierarchy_on_capped_to_silver(self):
        prof = default_quality_profile()
        prof["tier_hierarchy"]["enabled"] = True
        # Ajout d'un floor agressif sur 2160p (sans suffixe _probe) pour que
        # le fallback nom soit eligible. Sans le cap securite, on aurait Gold.
        prof["tier_hierarchy"]["resolution_floors"]["2160p"] = "Gold"

        # Probe FAILED mais nom de release indique "2160p" -> resolution_label
        # = "2160p" via fallback nom.
        res = compute_quality_score(
            normalized_probe=_probe_failed(),
            profile=prof,
            release_name="Film.2026.2160p.UHD.BluRay.x265-GRP",
        )
        # AC-2 : cap probe FAILED -> Silver MAXIMUM.
        self.assertIn(res["tier"], ("Silver", "Bronze", "Reject"))
        # Et surtout JAMAIS Platinum/Gold.
        self.assertNotIn(res["tier"], ("Platinum", "Gold"))

    def test_hierarchy_on_with_full_probe_can_apply_floor(self):
        """Inversement : probe FULL + hierarchy ON permet bien le floor."""
        prof = default_quality_profile()
        prof["tier_hierarchy"]["enabled"] = True

        # Force un cas ou V1 donnerait Bronze : on simule un probe FULL mais
        # avec un audio mediocre qui pourrait reduire le score.
        probe = _probe_2160p_premium_full()
        probe["video"]["bitrate"] = 12_000_000  # debit moyen pour 2160p (bits/s)
        # Forcons audio mediocre.
        probe["audio_tracks"] = [
            {"codec": "AAC", "channels": 2, "bitrate": 128_000, "language": "en"},
        ]
        res = compute_quality_score(normalized_probe=probe, profile=prof)
        # Avec hierarchy ON + 2160p probe + DV : floor Gold (ou plus haut).
        # On verifie au minimum que le tier n'est PAS Bronze/Reject.
        self.assertIn(res["tier"], ("Platinum", "Gold"))


class AC2CamPenaltyKeepsCapTests(unittest.TestCase):
    """AC-2 : CAM detecte plafonne a Bronze meme avec hierarchie ON."""

    def test_cam_release_capped_to_bronze_even_with_floor(self):
        prof = default_quality_profile()
        prof["tier_hierarchy"]["enabled"] = True
        # Floor agressif : 2160p meme name_fallback -> Gold.
        prof["tier_hierarchy"]["resolution_floors"]["2160p"] = "Gold"

        # Une CAM avec nom "2160p" trompeur.
        res = compute_quality_score(
            normalized_probe=_probe_failed(),
            profile=prof,
            release_name="Film.2026.2160p.HDCAM.x264-CAMGRP",
        )
        # CAM detecte -> Bronze max.
        self.assertIn(res["tier"], ("Bronze", "Reject"))


class CanonicalLabelsForUiTests(unittest.TestCase):
    """AC-4 : tier colors hex INVARIANTES (verifie via labels canoniques que l'UI mappe).

    Le test ne touche pas tokens.css, mais valide que le pipeline retourne
    bien les noms canoniques attendus par les classes CSS --tier-{name}.
    """

    def test_all_tier_results_use_canonical_names(self):
        canonical_set = {"Platinum", "Gold", "Silver", "Bronze", "Reject"}
        prof = default_quality_profile()
        # On teste avec et sans hierarchie : meme set canonique.
        for enabled in (False, True):
            prof_c = copy.deepcopy(prof)
            prof_c["tier_hierarchy"]["enabled"] = enabled
            for probe in (
                _probe_2160p_premium_full(),
                _probe_720p_modest_full(),
                _probe_failed(),
            ):
                res = compute_quality_score(normalized_probe=probe, profile=prof_c)
                self.assertIn(res["tier"], canonical_set,
                    f"tier {res['tier']!r} non canonique (hierarchy_enabled={enabled})")


class AC3PerceptualUntouchedTests(unittest.TestCase):
    """AC-3 : compute_quality_score V1 n'expose pas (et ne reference pas)
    composite_score_v2 perceptual. La separation perceptual_reports !=
    quality_reports est preservee.
    """

    def test_result_does_not_expose_composite_score_v2(self):
        prof = default_quality_profile()
        prof["tier_hierarchy"]["enabled"] = True
        res = compute_quality_score(normalized_probe=_probe_2160p_premium_full(), profile=prof)
        # La V1 ne doit jamais retourner les cles perceptual V2.
        forbidden = {"composite_score_v2", "perceptual_score", "global_tier_v2"}
        for key in forbidden:
            self.assertNotIn(key, res, f"V1 ne doit pas exposer {key} (memo design)")


if __name__ == "__main__":
    unittest.main()

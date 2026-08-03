"""MEGA-HOTFIX bug (1) : couverture quality_score hotfix2 (R1 + R5 + C5).

Verifie les trois correctifs apportes a `cinesort.domain.quality_score` lors
du cycle hotfix2 Vague R :

- R1-BUG-019 : `_score_extras` doit traiter `probe_quality="UNKNOWN"` comme
  NEUTRE (ni bonus +6, ni penalite -10 / -18). Avant le fix, "UNKNOWN"
  tombait dans la branche `else` (FAILED) et perdait la compensation
  reservee a "FAILED" strict en aval.
- R5 / hotfix coherence : `_clamp_0_100` doit appliquer une cascade
  precise (clamp puis arrondi) et garantir des entiers 0..100 monotones.
- C5 / detection bps : `_normalize_video_bitrate_kbps` et
  `_normalize_audio_bitrate_kbps` doivent detecter les valeurs en bps
  selon des seuils dedies (>500 000 pour video, >10 000 pour audio). En
  dessous, la valeur est consideree comme deja en kbps.

Ces tests garantissent qu'aucune regression n'introduise a nouveau les
faux positifs hotfix1 (cap Silver sur callers legacy, mauvaise detection
de bitrate sur 4K UHD REMUX, faux bonus audio).
"""

from __future__ import annotations

import unittest

from cinesort.domain.quality_score import (
    _clamp_0_100,
    _normalize_audio_bitrate_kbps,
    _normalize_bitrate_kbps,
    _normalize_video_bitrate_kbps,
    _score_extras,
)

# ============================================================
# R1-BUG-019 : UNKNOWN doit etre NEUTRE dans _score_extras
# ============================================================


class ScoreExtrasUnknownNeutralTests(unittest.TestCase):
    """`probe_quality="UNKNOWN"` doit etre neutre (ni bonus, ni penalite)."""

    def _toggles(self, **overrides):
        base = {
            "include_metadata": False,
            "include_naming": False,
            "include_subtitles": False,
        }
        base.update(overrides)
        return base

    def _baseline(self) -> int:
        # Aucune metadata, aucune naming, aucun bonus/penalite -> 70 (extras_sub
        # initial dans _score_extras, voir docstring l. 1003).
        reasons: list = []
        factors: list = []
        return _score_extras(
            "",
            self._toggles(),
            folder_name="",
            expected_title="",
            expected_year=0,
            subtitle_info=None,
            reasons=reasons,
            factors=factors,
        )

    def test_unknown_score_equals_baseline_70(self) -> None:
        reasons: list = []
        factors: list = []
        score = _score_extras(
            "UNKNOWN",
            self._toggles(),
            folder_name="",
            expected_title="",
            expected_year=0,
            subtitle_info=None,
            reasons=reasons,
            factors=factors,
        )
        # Aucune modification du sous-score base 70 -> tier neutre.
        self.assertEqual(score, 70, "UNKNOWN doit etre neutre (pas de modif sub)")
        # Aucune raison ni aucun factor ajoute par la branche UNKNOWN.
        self.assertEqual(reasons, [], "Aucune raison ajoutee pour UNKNOWN")
        self.assertEqual(factors, [], "Aucun factor ajoute pour UNKNOWN")

    def test_unknown_score_strictly_higher_than_failed(self) -> None:
        # FAILED penalise -18 -> sub = 52. UNKNOWN ne penalise pas -> 70.
        reasons_failed: list = []
        factors_failed: list = []
        failed = _score_extras(
            "FAILED",
            self._toggles(),
            folder_name="",
            expected_title="",
            expected_year=0,
            subtitle_info=None,
            reasons=reasons_failed,
            factors=factors_failed,
        )
        unknown = _score_extras(
            "UNKNOWN",
            self._toggles(),
            folder_name="",
            expected_title="",
            expected_year=0,
            subtitle_info=None,
            reasons=[],
            factors=[],
        )
        self.assertGreater(unknown, failed, "UNKNOWN > FAILED (UNKNOWN neutre)")
        # FAILED doit ajouter au moins une raison/factor (-10 / -18).
        self.assertTrue(reasons_failed, "FAILED doit avoir au moins une raison")
        self.assertTrue(factors_failed, "FAILED doit avoir au moins un factor")

    def test_unknown_score_strictly_lower_than_full(self) -> None:
        reasons: list = []
        factors: list = []
        full = _score_extras(
            "FULL",
            self._toggles(),
            folder_name="",
            expected_title="",
            expected_year=0,
            subtitle_info=None,
            reasons=reasons,
            factors=factors,
        )
        unknown = _score_extras(
            "UNKNOWN",
            self._toggles(),
            folder_name="",
            expected_title="",
            expected_year=0,
            subtitle_info=None,
            reasons=[],
            factors=[],
        )
        self.assertLess(unknown, full, "UNKNOWN < FULL (FULL beneficie de +20 bonus)")

    def test_unknown_strict_metadata_mode_skipped(self) -> None:
        """En mode include_metadata=True, UNKNOWN ne doit pas etre penalise."""
        reasons: list = []
        factors: list = []
        unknown_strict = _score_extras(
            "UNKNOWN",
            self._toggles(include_metadata=True),
            folder_name="",
            expected_title="",
            expected_year=0,
            subtitle_info=None,
            reasons=reasons,
            factors=factors,
        )
        # UNKNOWN passe par le warning - aucune penalite strict.
        # Sub = 70 (initial), 0 modif -> 70.
        self.assertEqual(unknown_strict, 70)
        self.assertEqual(reasons, [])
        self.assertEqual(factors, [])


# ============================================================
# R5 / coherence : _clamp_0_100 cascade (clamp puis round)
# ============================================================


class ClampZeroHundredCascadeTests(unittest.TestCase):
    def test_clamps_negative_to_zero(self) -> None:
        self.assertEqual(_clamp_0_100(-1.0), 0)
        self.assertEqual(_clamp_0_100(-99.9), 0)
        self.assertEqual(_clamp_0_100(-1e9), 0)

    def test_clamps_above_100_to_100(self) -> None:
        self.assertEqual(_clamp_0_100(101.0), 100)
        self.assertEqual(_clamp_0_100(1000.0), 100)
        self.assertEqual(_clamp_0_100(1e9), 100)

    def test_passthrough_within_range_as_int_round(self) -> None:
        self.assertEqual(_clamp_0_100(0.0), 0)
        self.assertEqual(_clamp_0_100(0.4), 0)
        self.assertEqual(_clamp_0_100(0.6), 1)
        # banker rounding (Python round(half-to-even)) : 0.5 -> 0
        # On verifie juste un ordre coherent, sans imposer la convention.
        self.assertIn(_clamp_0_100(50.5), {50, 51})
        self.assertEqual(_clamp_0_100(99.6), 100)
        self.assertEqual(_clamp_0_100(100.0), 100)

    def test_returns_int_type_always(self) -> None:
        # Plusieurs callers (_apply_weights, _score_video etc.) attendent int.
        for v in [-10.5, 0.0, 50.5, 100.0, 200.0, 99.999]:
            with self.subTest(value=v):
                self.assertIsInstance(_clamp_0_100(v), int)

    def test_monotone_within_range(self) -> None:
        # Strict monotonie sur entiers attendus.
        prev = _clamp_0_100(10.0)
        for v in range(11, 90):
            cur = _clamp_0_100(float(v))
            self.assertGreaterEqual(cur, prev)
            prev = cur

    def test_clamp_handles_float_special_values(self) -> None:
        # max() / min() avec float positif/negatif normal : pas de NaN attendu,
        # mais on s'assure que les valeurs extremes ne crashent pas.
        self.assertEqual(_clamp_0_100(float("inf")), 100)
        self.assertEqual(_clamp_0_100(float("-inf")), 0)


# ============================================================
# C5 / detection bps : video vs audio (seuils dedies)
# ============================================================


class NormalizeBitrateVideoTests(unittest.TestCase):
    """`_normalize_video_bitrate_kbps` : seuil bps = 500 000 (= 500 Mbps)."""

    def test_none_returns_none(self) -> None:
        self.assertIsNone(_normalize_video_bitrate_kbps(None))

    def test_zero_returns_none(self) -> None:
        self.assertIsNone(_normalize_video_bitrate_kbps(0))
        self.assertIsNone(_normalize_video_bitrate_kbps(0.0))

    def test_negative_returns_none(self) -> None:
        self.assertIsNone(_normalize_video_bitrate_kbps(-1))
        self.assertIsNone(_normalize_video_bitrate_kbps(-50000))

    # ------------------------------------------------------------------
    # F16 (revue post-merge 2026-07-18) — l'ENTREE est TOUJOURS en bits/s.
    #
    # Ces tests encodaient l'heuristique « n > 500000 -> bps, sinon deja kbps ».
    # Cette heuristique est fausse : la couche probe est le seul producteur de
    # `video.bitrate` et normalise tout via conversions.to_optional_bitrate, qui
    # rend des bits/s. Un 4K REMUX a 140 Mbps arrive donc a 140_000_000, jamais
    # a 140_000 ; et 140_000 signifie bel et bien 140 kb/s.
    # C'est exactement la meme correction que R8-038 avait deja faite cote audio.
    # ------------------------------------------------------------------

    def test_4k_uhd_remux_conserve_en_bps(self) -> None:
        # 4K UHD REMUX a 140 Mbps : la probe stocke 140_000_000 bps.
        self.assertEqual(_normalize_video_bitrate_kbps(140_000_000), 140000)
        self.assertEqual(_normalize_video_bitrate_kbps(120_000_000), 120000)

    def test_division_inconditionnelle_bps_vers_kbps(self) -> None:
        self.assertEqual(_normalize_video_bitrate_kbps(500001), 500)
        # 8 000 000 (8 Mbps en bps) -> 8000 kbps.
        self.assertEqual(_normalize_video_bitrate_kbps(8000000), 8000)
        # 50 000 000 (50 Mbps en bps) -> 50000 kbps.
        self.assertEqual(_normalize_video_bitrate_kbps(50000000), 50000)

    def test_valeurs_sous_l_ancien_seuil_sont_aussi_des_bps(self) -> None:
        # Le coeur du finding : 450 kb/s reels (450_000 bps) etaient lus comme
        # 450_000 kb/s -> "+18 Debit excellent" au lieu du malus -18.
        self.assertEqual(_normalize_video_bitrate_kbps(450_000), 450)
        self.assertEqual(_normalize_video_bitrate_kbps(200_000), 200)
        self.assertEqual(_normalize_video_bitrate_kbps(5_000_000), 5000)
        self.assertEqual(_normalize_video_bitrate_kbps(18_000_000), 18000)

    def test_string_input_parsed(self) -> None:
        # Compat _to_float - les valeurs string doivent etre parsees.
        self.assertEqual(_normalize_video_bitrate_kbps("5000000"), 5000)
        self.assertEqual(_normalize_video_bitrate_kbps("8000000"), 8000)

    def test_string_garbage_returns_none(self) -> None:
        # _to_float retourne -1.0 si non parsable -> None.
        self.assertIsNone(_normalize_video_bitrate_kbps("garbage"))
        self.assertIsNone(_normalize_video_bitrate_kbps(""))

    def test_backward_compat_alias(self) -> None:
        # `_normalize_bitrate_kbps` doit etre alias de la variante video.
        self.assertIs(_normalize_bitrate_kbps, _normalize_video_bitrate_kbps)
        # Verification semantique via une valeur 4K UHD REMUX (140 Mbps en bps).
        self.assertEqual(_normalize_bitrate_kbps(140_000_000), 140000)


class NormalizeBitrateAudioTests(unittest.TestCase):
    """`_normalize_audio_bitrate_kbps` : R8-038 (F4) — le bitrate audio est TOUJOURS
    en bits/s (invariant probe : ffprobe/mediainfo via to_optional_bitrate). Donc
    division INCONDITIONNELLE /1000 (bps -> kbps). L'ancien seuil > 10000 « en dessous
    = déjà kbps » testait un domaine d'entrée PHANTOM (le probe ne produit jamais un
    192 nu pour 192 kbps : il produit 192000) et masquait le bug R8-038 (8 kbps
    dégradé = 8000 bps lu comme 8000 kbps -> inversion de signe du score)."""

    def test_none_zero_negative_returns_none(self) -> None:
        self.assertIsNone(_normalize_audio_bitrate_kbps(None))
        self.assertIsNone(_normalize_audio_bitrate_kbps(0))
        self.assertIsNone(_normalize_audio_bitrate_kbps(-1))

    def test_aac_192kbps_bps_to_kbps(self) -> None:
        # 192 kbps stereo AAC -> ffprobe bit_rate=192000 bps -> 192 kbps.
        self.assertEqual(_normalize_audio_bitrate_kbps(192000), 192)

    def test_dts_1509kbps_bps_to_kbps(self) -> None:
        # DTS lossy ~1509 kbps -> 1509000 bps -> 1509 kbps.
        self.assertEqual(_normalize_audio_bitrate_kbps(1509000), 1509)

    def test_truehd_9000kbps_bps_to_kbps(self) -> None:
        # Plafond TrueHD ~9000 kbps -> 9000000 bps -> 9000 kbps.
        self.assertEqual(_normalize_audio_bitrate_kbps(9000000), 9000)

    def test_degraded_low_bps_divided(self) -> None:
        # R8-038 : flux dégradé ~8 kbps = 8000 bps -> 8 kbps (AVANT : 8000 « kbps »
        # -> per_channel énorme -> bonus +4 au lieu du malus -3). 6000 bps -> 6 kbps.
        self.assertEqual(_normalize_audio_bitrate_kbps(8000), 8)
        self.assertEqual(_normalize_audio_bitrate_kbps(6000), 6)

    def test_bps_to_kbps_division(self) -> None:
        self.assertEqual(_normalize_audio_bitrate_kbps(10001), 10)
        self.assertEqual(_normalize_audio_bitrate_kbps(192000), 192)
        self.assertEqual(_normalize_audio_bitrate_kbps(6000000), 6000)

    def test_video_et_audio_partagent_le_meme_invariant(self) -> None:
        """F16 : les deux chemins lisent des bits/s et divisent inconditionnellement.

        Le « path separe » du memo C5 reposait sur l'idee qu'une valeur video
        sous 500 000 etait deja en kbps. C'est faux : la probe rend toujours des
        bits/s. Les deux normalisations sont donc desormais alignees.
        """
        self.assertEqual(_normalize_video_bitrate_kbps(140000), 140)
        self.assertEqual(_normalize_audio_bitrate_kbps(140000), 140)


if __name__ == "__main__":
    unittest.main()

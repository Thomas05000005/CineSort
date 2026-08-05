"""#470 — Dolby Vision Profile 8.4 (couche de base HLG) classe `hlg`.

`detect_hdr_type` testait HLG avant Dolby Vision. Un fichier DV 8.4 satisfait
les DEUX conditions (transfer `arib-std-b67` + DOVI configuration record) : le
`return "hlg"` premature gagnait, le fichier tombait a 75 au lieu de 100.

Le correctif ne se contente PAS d'inverser les deux branches : le detecteur DV
historique (`_side_data_contains(..., _SIDE_DATA_DV_MARKERS)`) concatene toutes
les valeurs de chaque side_data et cherche la sous-chaine "dovi"/"dolby vision".
Le placer en premier aurait DEPLACE le faux positif — un vrai HLG dont un champ
libre mentionne `dovi_tool` serait devenu `dolby_vision` (100 au lieu de 75, une
erreur plus grave que celle corrigee). On teste donc en premier le signal
STRUCTURE : `extract_dv_configuration`, qui exige `side_data_type` == DOVI
configuration record. Strictement plus etroit que le marqueur textuel.
"""

from __future__ import annotations

import unittest

from cinesort.domain.perceptual.constants import HDR_QUALITY_SCORE
from cinesort.domain.perceptual.hdr_analysis import analyze_hdr_from_frame_data, detect_hdr_type

# side_data ffprobe reel d'un DV Profile 8.4 : couche de base HLG + RPU,
# compat_id 4 = "HLG compatible" (cf. constants.DV_PROFILE_LABELS["8.4"]).
_DV_84_SIDE_DATA = [
    {
        "side_data_type": "DOVI configuration record",
        "dv_version_major": 1,
        "dv_version_minor": 0,
        "dv_profile": 8,
        "dv_level": 6,
        "rpu_present_flag": 1,
        "el_present_flag": 0,
        "bl_present_flag": 1,
        "dv_bl_signal_compatibility_id": 4,
    }
]


class DolbyVisionProfile84Tests(unittest.TestCase):
    def test_dv_84_with_hlg_base_layer_is_dolby_vision(self) -> None:
        self.assertEqual(
            detect_hdr_type("bt2020", "arib-std-b67", _DV_84_SIDE_DATA),
            "dolby_vision",
        )

    def test_dv_84_scored_as_dolby_vision_through_the_real_analyzer(self) -> None:
        """Chaine reelle : analyze_hdr_from_frame_data -> detect_hdr_type -> score."""
        info = analyze_hdr_from_frame_data(
            {
                "color_primaries": "bt2020",
                "color_transfer": "arib-std-b67",
                "color_space": "bt2020nc",
                "side_data_list": _DV_84_SIDE_DATA,
            }
        )
        self.assertEqual(info.hdr_type, "dolby_vision")
        self.assertEqual(info.quality_score, HDR_QUALITY_SCORE["dolby_vision"])

    def test_dv_81_hdr10_base_layer_unchanged(self) -> None:
        """Non-regression : le cas deja correct (base PQ) reste `dolby_vision`."""
        side = [
            {
                "side_data_type": "DOVI configuration record",
                "dv_profile": 8,
                "dv_bl_signal_compatibility_id": 1,
                "rpu_present_flag": 1,
            }
        ]
        self.assertEqual(detect_hdr_type("bt2020", "smpte2084", side), "dolby_vision")


class NoFalsePositiveDisplacementTests(unittest.TestCase):
    """La priorite DV ne doit pas capturer un HLG ordinaire."""

    def test_hlg_with_free_text_mentioning_dovi_stays_hlg(self) -> None:
        # Aucun DOVI configuration record : "dovi" n'apparait que dans un champ
        # libre. Le marqueur textuel matcherait, le signal structure non.
        side = [
            {
                "side_data_type": "Mastering display metadata",
                "encoder": "remuxed with dovi_tool 2.1.2",
                "max_luminance": "10000000/10000",
                "min_luminance": "50/10000",
            }
        ]
        self.assertEqual(detect_hdr_type("bt2020", "arib-std-b67", side), "hlg")

    def test_plain_hlg_without_side_data_stays_hlg(self) -> None:
        self.assertEqual(detect_hdr_type("bt2020", "arib-std-b67", []), "hlg")
        self.assertEqual(detect_hdr_type("bt2020", "hlg", []), "hlg")

    def test_textual_only_dv_marker_still_detected_after_hlg(self) -> None:
        """Le marqueur TEXTUEL reste actif apres la branche HLG.

        Ici "dolby vision" n'est present que dans une valeur libre, pas dans
        `side_data_type` : le detecteur structure ne matche pas. Le transfer
        n'etant pas HLG, la branche textuelle conserve son verdict historique —
        le nouveau test structure n'a RETIRE aucune detection.
        """
        side = [{"side_data_type": "Unknown side data", "detail": "dolby vision rpu payload"}]
        self.assertEqual(detect_hdr_type("bt2020", "smpte2084", side), "dolby_vision")


if __name__ == "__main__":
    unittest.main()

"""Tests de regression pour le split de normalize.py (Vague M, M-04).

Verifie que :
1. Tous les helpers prives historiques restent accessibles depuis
   cinesort.infra.probe.normalize (re-export).
2. Les sous-modules privees existent et exposent les bonnes fonctions.
3. La signature publique normalize_probe est preservee.
4. Le module facade ne re-implemente plus la logique : il delegue uniquement.
"""

from __future__ import annotations

import inspect
import unittest


class TestNormalizeSplitImports(unittest.TestCase):
    """Garantit que le split en sous-modules est transparent pour les consommateurs."""

    def test_facade_reexports_all_private_helpers(self) -> None:
        """normalize.py doit re-exporter les helpers attendus par les tests existants."""
        from cinesort.infra.probe.normalize import (
            _bool_from_text,
            _detect_atmos_dtsx,
            _determine_quality,
            _duration_seconds_from_mediainfo,
            _extract_bit_depth,
            _extract_ffprobe,
            _extract_mediainfo,
            _extract_tracks,
            _ffprobe_video_dict,
            _merge_flag,
            _merge_probes,
            _pick_value,
            _ratio_to_fps,
            _to_bitrate_int,
            _to_float,
            _to_int,
            normalize_probe,
        )

        for fn in (
            _bool_from_text,
            _detect_atmos_dtsx,
            _determine_quality,
            _duration_seconds_from_mediainfo,
            _extract_bit_depth,
            _extract_ffprobe,
            _extract_mediainfo,
            _extract_tracks,
            _ffprobe_video_dict,
            _merge_flag,
            _merge_probes,
            _pick_value,
            _ratio_to_fps,
            _to_bitrate_int,
            _to_float,
            _to_int,
            normalize_probe,
        ):
            self.assertTrue(callable(fn), f"{fn} doit etre callable")

    def test_submodules_exist(self) -> None:
        """Les 4 sous-modules privees doivent etre importables."""
        from cinesort.infra.probe import (
            _normalize_ffprobe,
            _normalize_helpers,
            _normalize_mediainfo,
            _normalize_merge,
        )

        self.assertTrue(hasattr(_normalize_helpers, "_to_int"))
        self.assertTrue(hasattr(_normalize_helpers, "_to_float"))
        self.assertTrue(hasattr(_normalize_helpers, "_to_bitrate_int"))
        self.assertTrue(hasattr(_normalize_helpers, "_extract_bit_depth"))
        self.assertTrue(hasattr(_normalize_mediainfo, "_extract_mediainfo"))
        self.assertTrue(hasattr(_normalize_ffprobe, "_extract_ffprobe"))
        self.assertTrue(hasattr(_normalize_ffprobe, "_ffprobe_video_dict"))
        self.assertTrue(hasattr(_normalize_ffprobe, "_detect_atmos_dtsx"))
        self.assertTrue(hasattr(_normalize_merge, "_merge_probes"))
        self.assertTrue(hasattr(_normalize_merge, "_determine_quality"))
        self.assertTrue(hasattr(_normalize_merge, "_extract_tracks"))

    def test_normalize_probe_signature_unchanged(self) -> None:
        """La signature publique normalize_probe doit rester strictement keyword-only.

        Les callers (cinesort.infra.probe.service.ProbeService) passent tous
        les arguments par nom. Tout changement casserait l'integration.
        """
        from cinesort.infra.probe.normalize import normalize_probe

        sig = inspect.signature(normalize_probe)
        params = sig.parameters
        expected = {
            "media_path",
            "raw_mediainfo",
            "raw_ffprobe",
            "backend",
            "messages",
        }
        self.assertEqual(set(params.keys()), expected)
        for name, p in params.items():
            self.assertEqual(
                p.kind,
                inspect.Parameter.KEYWORD_ONLY,
                f"Le parametre {name} doit etre keyword-only",
            )

    def test_facade_is_thin(self) -> None:
        """La facade ne doit plus contenir la logique d'extraction massive."""
        import cinesort.infra.probe.normalize as nm

        src = inspect.getsource(nm)
        # Le module facade doit etre minimal : pas de re.compile (les regex sont
        # dans les sous-modules), pas de 700+ LOC.
        self.assertNotIn("_GROUPED_NUMBER_RE", src)
        self.assertNotIn("HDR_Format_String", src)  # logique mediainfo
        self.assertLess(len(src.splitlines()), 200, "facade doit rester < 200 LOC")

    def test_helpers_delegate_to_domain_conversions(self) -> None:
        """Les helpers _to_int/_to_float/_to_bitrate_int/_bool_from_text doivent
        deleguer aux helpers canoniques de cinesort.domain.conversions (dedup)."""
        from cinesort.domain import conversions
        from cinesort.infra.probe import _normalize_helpers

        # Verifie que les fonctions Optional existent dans le module canonique
        self.assertTrue(hasattr(conversions, "to_optional_int"))
        self.assertTrue(hasattr(conversions, "to_optional_float"))
        self.assertTrue(hasattr(conversions, "to_optional_bitrate"))
        self.assertTrue(hasattr(conversions, "to_optional_bool"))

        # Verifie que les helpers du module probe delegueent (memes resultats)
        for raw, expected in [
            ("3 840", 3840),
            ("12,500,000", 12500000),
            ("invalid", None),
        ]:
            self.assertEqual(
                _normalize_helpers._to_int(raw),
                conversions.to_optional_int(raw),
                f"_to_int divergent pour {raw!r}",
            )
            self.assertEqual(_normalize_helpers._to_int(raw), expected)


if __name__ == "__main__":
    unittest.main()

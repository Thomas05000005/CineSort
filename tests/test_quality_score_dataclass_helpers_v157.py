"""Phase 3 audit 2026-05-26 (v1.5.7) : tests non-vacuous pour les bugs
quality_score helpers + call sites qui n'acceptaient pas un NormalizedProbe
@dataclass natif.

Cinq bugs cibles :
  1. compute_quality_score -> _apply_custom_rules_helper (call site ligne 1802)
     transmettait le parametre brut, edition/duration_s/tmdb_in_collection lues
     comme None/0/False -> les regles custom user ne matchaient JAMAIS.
  2. compute_quality_score -> _build_quality_metrics_helper (call site ligne 1852)
     idem : detected.duration_s et detected.file_size_bytes etaient 0.
  3. _build_invalid_profile_result (ligne 1011-1013) : isinstance(probe, dict)
     False sur dataclass -> probe_quality='FAILED' hard-code meme avec FULL.
  4. _merge_probe_with_name_hints (ligne 1451-1463) : isinstance(probe, dict)
     False sur dataclass -> WIPE TOUT + re-deduction du nom. Signature exacte
     du bug v1.5.6.
  5. _estimate_file_size (ligne 971-979) : helper directement reutilisable,
     retourne 0 silencieusement sur dataclass.

Mutation testing : on patche dataclasses.is_dataclass pour qu'il retourne False,
le code re-tombe dans la branche `else -> {}` historique -> les assertions
critiques cassent. Preuve collee dans la sortie du subagent.
"""
from __future__ import annotations

import unittest
from unittest.mock import patch

from cinesort.domain.probe_models import NormalizedProbe, PROBE_QUALITY_FULL
from cinesort.domain import quality_score as qs
from cinesort.domain.release_name_parser import parse_release_name


# ---------------------------------------------------------------------------
# Bug 1 + 2 : compute_quality_score call sites (lignes 1802 / 1852)
# ---------------------------------------------------------------------------
class ComputeQualityScoreCustomRulesDurationDataclassTests(unittest.TestCase):
    """Bug 1 : sans le fix, applied_rule_ids reste vide pour une regle ciblant
    duration_s quand on passe un NormalizedProbe dataclass au call site."""

    def _profile_with_duration_rule(self):
        prof = qs.default_quality_profile()
        prof["custom_rules"] = [
            {
                "id": "long_film_bonus",
                "enabled": True,
                "priority": 1,
                "match": "all",
                "conditions": [
                    {"field": "duration_s", "op": ">", "value": 6000},
                ],
                "action": {
                    "type": "score_delta",
                    "value": 15,
                    "reason": "Film long >100min",
                },
            }
        ]
        return prof

    def _build_full_probe_2h_dataclass(self) -> NormalizedProbe:
        return NormalizedProbe(
            path="/movies/Inception.mkv",
            duration_s=7200.0,
            probe_quality=PROBE_QUALITY_FULL,
            video={
                "codec": "hevc",
                "width": 3840,
                "height": 2160,
                "bitrate": 58_000_000,
                "bit_depth": 10,
                "hdr_dolby_vision": True,
                "hdr10": True,
            },
            audio_tracks=[
                {
                    "codec": "truehd",
                    "channels": 8,
                    "channel_layout": "7.1",
                    "language": "fra",
                    "bitrate": 6_000_000,
                }
            ],
        )

    def test_custom_rule_on_duration_applies_with_dataclass_probe(self):
        """Bug 1 : NormalizedProbe dataclass + regle custom sur duration_s ->
        applied_rule_ids doit contenir 'long_film_bonus' (avant le fix : [])."""
        probe = self._build_full_probe_2h_dataclass()
        prof = self._profile_with_duration_rule()
        result = qs.compute_quality_score(
            normalized_probe=probe,
            profile=prof,
            release_name="",
        )
        self.assertIn(
            "long_film_bonus",
            result["metrics"]["applied_rule_ids"],
            "BUG: la regle duration_s>6000 n'a pas matche alors que duration_s=7200. "
            f"applied_rule_ids={result['metrics']['applied_rule_ids']} reasons={result['reasons']}",
        )
        # Reason en clair
        self.assertTrue(
            any("Film long >100min" in r for r in result["reasons"]),
            f"reason 'Film long >100min' absente: {result['reasons']}",
        )

    def test_metrics_detected_duration_and_filesize_from_dataclass(self):
        """Bug 2 : detected.duration_s = 7200, file_size_bytes > 0 quand on passe
        un NormalizedProbe dataclass (avant fix : 0 et 0)."""
        probe = self._build_full_probe_2h_dataclass()
        prof = qs.default_quality_profile()
        result = qs.compute_quality_score(
            normalized_probe=probe,
            profile=prof,
            release_name="",
        )
        detected = result["metrics"]["detected"]
        self.assertEqual(
            float(detected["duration_s"]),
            7200.0,
            f"BUG: detected.duration_s={detected['duration_s']} attendu 7200.0 (dataclass mal lu)",
        )
        # bitrate ~58000 kbps reel, duree 7200 -> ~52e9 bytes
        self.assertGreater(
            int(detected["file_size_bytes"]),
            0,
            f"BUG: file_size_bytes={detected['file_size_bytes']} doit etre > 0",
        )


# ---------------------------------------------------------------------------
# Bug 3 : _build_invalid_profile_result garde probe_quality du dataclass
# ---------------------------------------------------------------------------
class BuildInvalidProfileResultDataclassTests(unittest.TestCase):
    def test_dataclass_full_probe_preserves_probe_quality(self):
        """Bug 3 : profil invalide + dataclass FULL -> metrics.probe_quality='FULL'
        (avant fix : 'FAILED' hard-code car isinstance(dataclass, dict) False)."""
        np = NormalizedProbe(path="/tmp/x.mkv", probe_quality="FULL")
        out = qs._build_invalid_profile_result({}, np, ["bad"])
        self.assertEqual(
            out["metrics"]["probe_quality"],
            "FULL",
            f"BUG: probe_quality={out['metrics']['probe_quality']!r} attendu 'FULL'",
        )


# ---------------------------------------------------------------------------
# Bug 4 : _merge_probe_with_name_hints ne WIPE plus le probe dataclass
# ---------------------------------------------------------------------------
class MergeProbeWithNameHintsDataclassTests(unittest.TestCase):
    def test_dataclass_probe_video_preserved_not_wiped(self):
        """Bug 4 : NormalizedProbe avec video.codec='hevc' deja present + nom
        avec hints -> codec doit RESTER, PAS etre re-deduit du nom.
        Avant fix : wipe-and-replace (probe={}) puis remplissage.
        """
        np = NormalizedProbe(
            path="/x.mkv",
            video={
                "codec": "hevc",
                "width": 3840,
                "height": 2160,
                "bit_depth": 10,
            },
        )
        ni = parse_release_name("Inception.2010.2160p.UHD.BluRay.x265-GRP")
        merged, filled = qs._merge_probe_with_name_hints(np, ni)
        # codec doit etre preserve (hevc/h265), bit_depth doit rester 10
        self.assertEqual(
            merged.get("video", {}).get("codec"),
            "hevc",
            f"BUG: codec={merged.get('video', {}).get('codec')!r} attendu 'hevc' "
            f"(probe etait WIPE et re-deduit du nom). filled={filled}",
        )
        self.assertEqual(
            merged.get("video", {}).get("bit_depth"),
            10,
            f"BUG: bit_depth={merged.get('video', {}).get('bit_depth')} attendu 10",
        )
        # codec NE doit PAS etre dans filled_from_name (deja present dans probe)
        self.assertNotIn(
            "codec",
            filled,
            f"BUG: codec marque comme filled depuis le nom: filled={filled}",
        )
        self.assertNotIn(
            "bit_depth",
            filled,
            f"BUG: bit_depth marque comme filled depuis le nom: filled={filled}",
        )


# ---------------------------------------------------------------------------
# Bug 5 : _estimate_file_size accepte dataclass natif
# ---------------------------------------------------------------------------
class EstimateFileSizeDataclassTests(unittest.TestCase):
    def test_dataclass_with_duration_returns_nonzero(self):
        """Bug 5 : NormalizedProbe(duration_s=7200) + bitrate=10000kbps ->
        9_000_000_000 bytes (avant fix : 0 silencieusement)."""
        np = NormalizedProbe(path="/x", duration_s=7200.0)
        out = qs._estimate_file_size(np, 10000)
        # 7200 * 10000 * 1000 / 8 = 9_000_000_000
        self.assertEqual(
            out,
            9_000_000_000,
            f"BUG: _estimate_file_size={out} attendu 9_000_000_000 (dataclass mal lu)",
        )


# ---------------------------------------------------------------------------
# MUTATION TESTING : patch is_dataclass = False
# ---------------------------------------------------------------------------
class MutationProofTests(unittest.TestCase):
    """Preuve non-vacuous : si on stub _is_dc (is_dataclass) pour qu'il retourne
    False, le code re-tombe sur la branche `isinstance(dict) ? : {}` historique.
    Toutes les preuves ci-dessous DOIVENT casser sous mutation.
    """

    def test_mutation_estimate_file_size_returns_zero_when_isdc_stubbed(self):
        """Sous mutation (is_dataclass -> False) : _estimate_file_size retombe a 0."""
        np = NormalizedProbe(path="/x", duration_s=7200.0)
        with patch.object(qs, "_is_dc", return_value=False):
            out = qs._estimate_file_size(np, 10000)
        # Sous mutation -> on doit retomber a 0 (preuve que le fix est efficace)
        self.assertEqual(
            out,
            0,
            "MUTATION PROOF: sans is_dataclass, _estimate_file_size doit retomber a 0",
        )

    def test_mutation_invalid_profile_falls_back_to_failed(self):
        """Sous mutation : _build_invalid_profile_result perd la valeur 'FULL'.
        Le normaliseur retourne {} -> .get("probe_quality") -> None -> str(None)='None'.
        Le seul invariant : on n'a plus 'FULL'.
        """
        np = NormalizedProbe(path="/x", probe_quality="FULL")
        with patch.object(qs, "_is_dc", return_value=False):
            out = qs._build_invalid_profile_result({}, np, ["bad"])
        self.assertNotEqual(
            out["metrics"]["probe_quality"],
            "FULL",
            "MUTATION PROOF: sans is_dataclass, probe_quality NE doit PAS rester 'FULL'",
        )

    def test_mutation_merge_wipes_probe_video_codec(self):
        """Sous mutation : _merge_probe_with_name_hints WIPE et re-deduit du nom."""
        np = NormalizedProbe(
            path="/x.mkv",
            video={"codec": "hevc", "width": 3840, "height": 2160, "bit_depth": 10},
        )
        ni = parse_release_name("Inception.2010.2160p.UHD.BluRay.x265-GRP")
        with patch.object(qs, "_is_dc", return_value=False):
            merged, filled = qs._merge_probe_with_name_hints(np, ni)
        # Sous mutation : codec absent du probe initial -> re-deduit du nom -> filled
        self.assertIn(
            "codec",
            filled,
            "MUTATION PROOF: sans is_dataclass, le codec doit etre re-rempli depuis le nom",
        )


if __name__ == "__main__":
    unittest.main()

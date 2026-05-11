"""Tests V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) — toggle Composite Score V1/V2.

Decision actee : V1 reste le defaut, V2 est activable via le setting
`composite_score_version` (1 | 2). Pas de re-scoring automatique : les anciens
scores restent V1 jusqu'a un nouveau scan/analyse perceptuelle.

Couvre :
- Defaut V1 : `apply_settings_defaults` injecte 1 si setting absent.
- Switch V2 : payload UI int=2 ou string "2" -> normalise a 2.
- Fallback : valeurs invalides (None, 99, "abc", True, [], {}) -> 1.
- Backward compat : config existante sans `composite_score_version` n'erreur pas.
- Backend dispatch : enrich_quality_report_with_perceptual respecte le toggle.
- Coexistence : V1 et V2 cohabitent en BDD (le perceptual report contient
  global_score V1 + global_score_v2 separe), le toggle choisit lequel sert
  comme score principal expose.
"""

from __future__ import annotations

import unittest
from pathlib import Path
from typing import Any, Dict
from unittest import mock

from cinesort.ui.api.perceptual_support import (
    _build_settings_dict,
    enrich_quality_report_with_perceptual,
)
from cinesort.ui.api.settings_support import (
    COMPOSITE_SCORE_VERSIONS,
    DEFAULT_COMPOSITE_SCORE_VERSION,
    _normalize_composite_score_version,
    _save_section_perceptual,
    apply_settings_defaults,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _defaults_kwargs(state_dir: Path) -> Dict[str, Any]:
    """Kwargs minimaux pour invoquer apply_settings_defaults."""
    return {
        "state_dir": state_dir,
        "default_root": str(state_dir),
        "default_state_dir_example": str(state_dir),
        "default_collection_folder_name": "_Collection",
        "default_empty_folders_folder_name": "_Vide",
        "default_residual_cleanup_folder_name": "_Residuels",
        "default_probe_backend": "auto",
        "debug_enabled": False,
    }


# ---------------------------------------------------------------------------
# Normalisation _normalize_composite_score_version
# ---------------------------------------------------------------------------


class TestNormalizeCompositeScoreVersion(unittest.TestCase):
    """Validation/clamp du toggle. Defaut = 1 (V1 reste defaut, decision actee)."""

    def test_default_is_v1(self) -> None:
        """V1 reste defaut documente."""
        self.assertEqual(DEFAULT_COMPOSITE_SCORE_VERSION, 1)
        self.assertIn(1, COMPOSITE_SCORE_VERSIONS)
        self.assertIn(2, COMPOSITE_SCORE_VERSIONS)

    def test_int_1_returns_1(self) -> None:
        self.assertEqual(_normalize_composite_score_version(1), 1)

    def test_int_2_returns_2(self) -> None:
        self.assertEqual(_normalize_composite_score_version(2), 2)

    def test_string_1_returns_1(self) -> None:
        """Le DOM <select> retourne toujours une string."""
        self.assertEqual(_normalize_composite_score_version("1"), 1)

    def test_string_2_returns_2(self) -> None:
        self.assertEqual(_normalize_composite_score_version("2"), 2)

    def test_string_v2_returns_2(self) -> None:
        """Tolerance prefixe 'v' (parfois saisi par les users)."""
        self.assertEqual(_normalize_composite_score_version("v2"), 2)
        self.assertEqual(_normalize_composite_score_version("V1"), 1)

    def test_none_returns_default(self) -> None:
        """Setting absent -> defaut V1 (backward compat)."""
        self.assertEqual(_normalize_composite_score_version(None), 1)

    def test_empty_string_returns_default(self) -> None:
        self.assertEqual(_normalize_composite_score_version(""), 1)
        self.assertEqual(_normalize_composite_score_version("   "), 1)

    def test_invalid_int_returns_default(self) -> None:
        """Hors domaine {1,2} -> fallback V1."""
        self.assertEqual(_normalize_composite_score_version(0), 1)
        self.assertEqual(_normalize_composite_score_version(3), 1)
        self.assertEqual(_normalize_composite_score_version(99), 1)
        self.assertEqual(_normalize_composite_score_version(-1), 1)

    def test_invalid_string_returns_default(self) -> None:
        self.assertEqual(_normalize_composite_score_version("abc"), 1)
        self.assertEqual(_normalize_composite_score_version("v3"), 1)

    def test_bool_returns_default(self) -> None:
        """bool est sous-classe d'int en Python : on rejette pour eviter
        True->1 silencieux qui masquerait un bug de payload UI."""
        self.assertEqual(_normalize_composite_score_version(True), 1)
        self.assertEqual(_normalize_composite_score_version(False), 1)

    def test_unhashable_returns_default(self) -> None:
        self.assertEqual(_normalize_composite_score_version([]), 1)
        self.assertEqual(_normalize_composite_score_version({}), 1)
        self.assertEqual(_normalize_composite_score_version([2]), 1)

    def test_float_int_like_returns_clamped(self) -> None:
        """1.0 / 2.0 acceptes (float convertibles), 1.5 tronque a 1 -> valide."""
        self.assertEqual(_normalize_composite_score_version(1.0), 1)
        self.assertEqual(_normalize_composite_score_version(2.0), 2)
        # 1.9 -> int(1.9)=1 -> dans le domaine -> 1 (fallback indirect)
        self.assertEqual(_normalize_composite_score_version(1.9), 1)


# ---------------------------------------------------------------------------
# Defaults : apply_settings_defaults injecte V1 si absent
# ---------------------------------------------------------------------------


class TestApplySettingsDefaults(unittest.TestCase):
    """Verifie que les configs existantes (sans `composite_score_version`)
    continuent a fonctionner avec V1 par defaut."""

    def test_default_injected_when_missing(self) -> None:
        """Config legacy sans le setting -> V1 injecte (pas de KeyError)."""
        with mock.patch("cinesort.infra.log_context.normalize_log_level_setting", return_value="INFO"):
            payload = apply_settings_defaults({}, **_defaults_kwargs(Path(".")))
        self.assertEqual(payload["composite_score_version"], 1)

    def test_existing_v2_preserved(self) -> None:
        """Si l'utilisateur a deja activate V2, on preserve."""
        with mock.patch("cinesort.infra.log_context.normalize_log_level_setting", return_value="INFO"):
            payload = apply_settings_defaults({"composite_score_version": 2}, **_defaults_kwargs(Path(".")))
        self.assertEqual(payload["composite_score_version"], 2)

    def test_invalid_value_falls_back(self) -> None:
        """Settings.json corrompu/manuel -> V1 silencieux (pas de crash)."""
        with mock.patch("cinesort.infra.log_context.normalize_log_level_setting", return_value="INFO"):
            payload = apply_settings_defaults({"composite_score_version": "garbage"}, **_defaults_kwargs(Path(".")))
        self.assertEqual(payload["composite_score_version"], 1)


# ---------------------------------------------------------------------------
# Save section : payload UI normalise a la sauvegarde
# ---------------------------------------------------------------------------


class TestSaveSectionPerceptual(unittest.TestCase):
    """_save_section_perceptual normalise le toggle envoye par le frontend."""

    def test_save_string_2_persists_int_2(self) -> None:
        """Le DOM envoie "2" string, on persiste 2 int."""
        section = _save_section_perceptual({"composite_score_version": "2"})
        self.assertEqual(section["composite_score_version"], 2)
        self.assertIsInstance(section["composite_score_version"], int)

    def test_save_int_1_persists_int_1(self) -> None:
        section = _save_section_perceptual({"composite_score_version": 1})
        self.assertEqual(section["composite_score_version"], 1)

    def test_save_missing_persists_default(self) -> None:
        """Payload UI sans le champ (vue legacy) -> defaut V1."""
        section = _save_section_perceptual({})
        self.assertEqual(section["composite_score_version"], 1)

    def test_save_invalid_persists_default(self) -> None:
        section = _save_section_perceptual({"composite_score_version": "v99"})
        self.assertEqual(section["composite_score_version"], 1)


# ---------------------------------------------------------------------------
# Backend dispatch : _build_settings_dict propage le toggle
# ---------------------------------------------------------------------------


class TestBuildSettingsDictDispatch(unittest.TestCase):
    """Le settings_dict perceptuel embarque le toggle pour le dispatch."""

    def test_default_dispatch_v1(self) -> None:
        """Settings sans toggle -> dispatch V1."""
        d = _build_settings_dict({"perceptual_enabled": True})
        self.assertEqual(d["composite_score_version"], 1)

    def test_explicit_v2(self) -> None:
        d = _build_settings_dict({"perceptual_enabled": True, "composite_score_version": 2})
        self.assertEqual(d["composite_score_version"], 2)

    def test_string_v2_normalized(self) -> None:
        d = _build_settings_dict({"perceptual_enabled": True, "composite_score_version": "2"})
        self.assertEqual(d["composite_score_version"], 2)

    def test_invalid_falls_back_v1(self) -> None:
        d = _build_settings_dict({"perceptual_enabled": True, "composite_score_version": 99})
        self.assertEqual(d["composite_score_version"], 1)


# ---------------------------------------------------------------------------
# enrich_quality_report_with_perceptual : routage V1 vs V2
# ---------------------------------------------------------------------------


class TestEnrichQualityReportDispatch(unittest.TestCase):
    """Selon `composite_score_version`, on expose V1 (defaut) ou V2 dans
    le payload perceptual du quality_report."""

    def _store_with_v1_and_v2(self) -> Any:
        store = mock.MagicMock()
        store.get_perceptual_report.return_value = {
            "global_score": 72,
            "global_tier": "bon",
            "visual_score": 70,
            "audio_score": 75,
            "global_score_v2": 88,
            "global_tier_v2": "gold",
        }
        return store

    def test_default_uses_v1(self) -> None:
        """Pas de kwarg -> V1 (defaut backward-compat avec call sites legacy)."""
        store = self._store_with_v1_and_v2()
        result: Dict[str, Any] = {}
        enrich_quality_report_with_perceptual(store, "run1", "row1", result)
        self.assertIn("perceptual", result)
        self.assertEqual(result["perceptual"]["global_score"], 72)
        self.assertEqual(result["perceptual"]["global_tier"], "bon")
        self.assertEqual(result["perceptual"]["composite_score_version"], 1)

    def test_explicit_v1(self) -> None:
        store = self._store_with_v1_and_v2()
        result: Dict[str, Any] = {}
        enrich_quality_report_with_perceptual(store, "run1", "row1", result, composite_score_version=1)
        self.assertEqual(result["perceptual"]["global_score"], 72)
        self.assertEqual(result["perceptual"]["composite_score_version"], 1)

    def test_v2_promotes_v2_score(self) -> None:
        """Toggle V2 -> on promeut V2 comme score principal."""
        store = self._store_with_v1_and_v2()
        result: Dict[str, Any] = {}
        enrich_quality_report_with_perceptual(store, "run1", "row1", result, composite_score_version=2)
        self.assertEqual(result["perceptual"]["global_score"], 88)
        self.assertEqual(result["perceptual"]["global_tier"], "gold")
        self.assertEqual(result["perceptual"]["composite_score_version"], 2)

    def test_v2_fallback_to_v1_when_v2_missing(self) -> None:
        """V2 active mais cache historique sans V2 -> fallback V1 (pas d'erreur)."""
        store = mock.MagicMock()
        store.get_perceptual_report.return_value = {
            "global_score": 72,
            "global_tier": "bon",
            "visual_score": 70,
            "audio_score": 75,
            # global_score_v2 absent (legacy row pre v7.5.0 ou calcul V2 echoue)
        }
        result: Dict[str, Any] = {}
        enrich_quality_report_with_perceptual(store, "run1", "row1", result, composite_score_version=2)
        self.assertEqual(result["perceptual"]["global_score"], 72)
        self.assertEqual(result["perceptual"]["global_tier"], "bon")
        self.assertEqual(result["perceptual"]["composite_score_version"], 1)

    def test_no_perceptual_report(self) -> None:
        """Pas de cache perceptuel -> pas d'enrichissement (silencieux)."""
        store = mock.MagicMock()
        store.get_perceptual_report.return_value = None
        result: Dict[str, Any] = {}
        enrich_quality_report_with_perceptual(store, "run1", "row1", result, composite_score_version=2)
        self.assertNotIn("perceptual", result)


# ---------------------------------------------------------------------------
# Coexistence : V1 et V2 cohabitent (pas de breaking change)
# ---------------------------------------------------------------------------


class TestCoexistence(unittest.TestCase):
    """Verifie que basculer V1 <-> V2 ne casse rien et n'efface aucun cache."""

    def test_switch_v1_to_v2_preserves_v1_cache(self) -> None:
        """Toggle V2 doit lire `global_score_v2` SANS supprimer `global_score`
        du cache (le store retourne les deux, on choisit lequel exposer)."""
        store = mock.MagicMock()
        store.get_perceptual_report.return_value = {
            "global_score": 72,
            "global_tier": "bon",
            "visual_score": 70,
            "audio_score": 75,
            "global_score_v2": 88,
            "global_tier_v2": "gold",
        }
        # Premier appel V1
        result_v1: Dict[str, Any] = {}
        enrich_quality_report_with_perceptual(store, "run1", "row1", result_v1, composite_score_version=1)
        # Deuxieme appel V2
        result_v2: Dict[str, Any] = {}
        enrich_quality_report_with_perceptual(store, "run1", "row1", result_v2, composite_score_version=2)
        # Les deux ont reussi sans erreur, scores differents
        self.assertEqual(result_v1["perceptual"]["global_score"], 72)
        self.assertEqual(result_v2["perceptual"]["global_score"], 88)
        # Le cache n'a pas ete touche (3 lectures = 2 appels enrich -> 2 calls,
        # plus rien si le getter retourne meme dict)
        self.assertGreaterEqual(store.get_perceptual_report.call_count, 2)


if __name__ == "__main__":
    unittest.main()

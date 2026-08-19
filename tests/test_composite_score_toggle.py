"""Tests V4-05 (Polish Total v7.7.0, R4-PERC-7 / H16) — toggle Composite Score V1/V2.

VN-B.1 (Vague N batch 2) : V2 devient le defaut. V1 reste accepte comme
kill-switch de rollback explicite (`composite_score_version=1`). Cf
audit Vague N : avoir 2 sources de verite paralleles (v1+v2) faisait fuiter
2 vocabulaires tiers cote UI (reference/excellent vs platinum/gold).

Couvre :
- Defaut V2 : `apply_settings_defaults` injecte 2 si setting absent
  (vocabulaire Platinum/Gold/Silver/Bronze/Reject).
- Kill-switch V1 : payload UI int=1 ou string "1" -> normalise a 1
  (rollback explicite vers vocabulaire reference/excellent/bon).
- Fallback : valeurs invalides (None, 99, "abc", True, [], {}) -> 2.
- Backward compat : config existante sans `composite_score_version` migre
  silencieusement vers V2 (la cle composite reste lisible apres re-scan).
- Backend dispatch : enrich_quality_report_with_perceptual respecte le toggle.
- Coexistence : V1 et V2 cohabitent en BDD (le perceptual report contient
  global_score legacy + global_score_v2), le toggle choisit lequel sert
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
    """Validation/clamp du toggle. VN-B.1 : defaut bascule sur V2."""

    def test_default_is_v2(self) -> None:
        """V2 est defaut documente (Vague N batch 2)."""
        self.assertEqual(DEFAULT_COMPOSITE_SCORE_VERSION, 2)
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
        """Setting absent -> defaut V2 (VN-B.1 : migration silencieuse)."""
        self.assertEqual(_normalize_composite_score_version(None), 2)

    def test_empty_string_returns_default(self) -> None:
        self.assertEqual(_normalize_composite_score_version(""), 2)
        self.assertEqual(_normalize_composite_score_version("   "), 2)

    def test_invalid_int_returns_default(self) -> None:
        """Hors domaine {1,2} -> fallback V2 (defaut)."""
        self.assertEqual(_normalize_composite_score_version(0), 2)
        self.assertEqual(_normalize_composite_score_version(3), 2)
        self.assertEqual(_normalize_composite_score_version(99), 2)
        self.assertEqual(_normalize_composite_score_version(-1), 2)

    def test_invalid_string_returns_default(self) -> None:
        self.assertEqual(_normalize_composite_score_version("abc"), 2)
        self.assertEqual(_normalize_composite_score_version("v3"), 2)

    def test_bool_returns_default(self) -> None:
        """bool est sous-classe d'int en Python : on rejette pour eviter
        True->1 silencieux qui masquerait un bug de payload UI. Defaut V2."""
        self.assertEqual(_normalize_composite_score_version(True), 2)
        self.assertEqual(_normalize_composite_score_version(False), 2)

    def test_unhashable_returns_default(self) -> None:
        self.assertEqual(_normalize_composite_score_version([]), 2)
        self.assertEqual(_normalize_composite_score_version({}), 2)
        self.assertEqual(_normalize_composite_score_version([2]), 2)

    def test_float_int_like_returns_clamped(self) -> None:
        """1.0 / 2.0 acceptes (float convertibles), 1.5 tronque a 1 -> valide."""
        self.assertEqual(_normalize_composite_score_version(1.0), 1)
        self.assertEqual(_normalize_composite_score_version(2.0), 2)
        # 1.9 -> int(1.9)=1 -> dans le domaine -> 1 (kill-switch rollback)
        self.assertEqual(_normalize_composite_score_version(1.9), 1)


# ---------------------------------------------------------------------------
# Defaults : apply_settings_defaults injecte V1 si absent
# ---------------------------------------------------------------------------


class TestApplySettingsDefaults(unittest.TestCase):
    """Verifie que les configs existantes (sans `composite_score_version`)
    migrent silencieusement vers V2 (VN-B.1).

    Ces quatre tests portaient un
    `mock.patch("cinesort.infra.log_context.normalize_log_level_setting")`
    qui ne s'appliquait PAS : `settings_support` importe la fonction PAR VALEUR
    (`from ... import normalize_log_level_setting`), donc il garde sa propre
    reference et le patch du module source ne l'atteint jamais.

    Mesure avant de retirer : les quatre tests passent SANS le mock, et la
    fonction est un normalisateur de chaine pur — il ne masquait donc aucun
    effet de bord. Un mock qui n'agit pas est pire qu'absent : il fait croire
    a une isolation qui n'existe pas.
    """

    def test_default_injected_when_missing(self) -> None:
        """Config legacy sans le setting -> V2 injecte (pas de KeyError)."""
        payload = apply_settings_defaults({}, **_defaults_kwargs(Path(".")))
        self.assertEqual(payload["composite_score_version"], 2)

    def test_existing_v1_preserved(self) -> None:
        """Kill-switch V1 explicite : on preserve la valeur utilisateur."""
        payload = apply_settings_defaults({"composite_score_version": 1}, **_defaults_kwargs(Path(".")))
        self.assertEqual(payload["composite_score_version"], 1)

    def test_existing_v2_preserved(self) -> None:
        """V2 explicite : on preserve (idempotent vs defaut)."""
        payload = apply_settings_defaults({"composite_score_version": 2}, **_defaults_kwargs(Path(".")))
        self.assertEqual(payload["composite_score_version"], 2)

    def test_invalid_value_falls_back(self) -> None:
        """Settings.json corrompu/manuel -> V2 silencieux (pas de crash)."""
        payload = apply_settings_defaults({"composite_score_version": "garbage"}, **_defaults_kwargs(Path(".")))
        self.assertEqual(payload["composite_score_version"], 2)


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
        """Payload UI sans le champ (vue legacy) -> defaut V2 (VN-B.1)."""
        section = _save_section_perceptual({})
        self.assertEqual(section["composite_score_version"], 2)

    def test_save_invalid_persists_default(self) -> None:
        section = _save_section_perceptual({"composite_score_version": "v99"})
        self.assertEqual(section["composite_score_version"], 2)


# ---------------------------------------------------------------------------
# Backend dispatch : _build_settings_dict propage le toggle
# ---------------------------------------------------------------------------


class TestBuildSettingsDictDispatch(unittest.TestCase):
    """Le settings_dict perceptuel embarque le toggle pour le dispatch."""

    def test_default_dispatch_v2(self) -> None:
        """Settings sans toggle -> dispatch V2 (VN-B.1, source de verite unique)."""
        d = _build_settings_dict({"perceptual_enabled": True})
        self.assertEqual(d["composite_score_version"], 2)

    def test_explicit_v1_killswitch(self) -> None:
        """Kill-switch rollback explicite vers V1."""
        d = _build_settings_dict({"perceptual_enabled": True, "composite_score_version": 1})
        self.assertEqual(d["composite_score_version"], 1)

    def test_explicit_v2(self) -> None:
        d = _build_settings_dict({"perceptual_enabled": True, "composite_score_version": 2})
        self.assertEqual(d["composite_score_version"], 2)

    def test_string_v2_normalized(self) -> None:
        d = _build_settings_dict({"perceptual_enabled": True, "composite_score_version": "2"})
        self.assertEqual(d["composite_score_version"], 2)

    def test_invalid_falls_back_v2(self) -> None:
        d = _build_settings_dict({"perceptual_enabled": True, "composite_score_version": 99})
        self.assertEqual(d["composite_score_version"], 2)


# ---------------------------------------------------------------------------
# enrich_quality_report_with_perceptual : routage V1 vs V2
# ---------------------------------------------------------------------------


class TestEnrichQualityReportDispatch(unittest.TestCase):
    """Selon `composite_score_version`, on expose V1 (defaut) ou V2 dans
    le payload perceptual du quality_report."""

    def _store_with_v1_and_v2(self) -> Any:
        store = mock.MagicMock()
        store.perceptual.get_perceptual_report.return_value = {
            "global_score": 72,
            "global_tier": "bon",
            "visual_score": 70,
            "audio_score": 75,
            "global_score_v2": 88,
            "global_tier_v2": "gold",
        }
        return store

    def test_default_uses_v2(self) -> None:
        """Pas de kwarg -> V2 (VN-B.1 : source de verite unique)."""
        store = self._store_with_v1_and_v2()
        result: Dict[str, Any] = {}
        enrich_quality_report_with_perceptual(store, "run1", "row1", result)
        self.assertIn("perceptual", result)
        self.assertEqual(result["perceptual"]["global_score"], 88)
        self.assertEqual(result["perceptual"]["global_tier"], "gold")
        self.assertEqual(result["perceptual"]["composite_score_version"], 2)

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
        store.perceptual.get_perceptual_report.return_value = {
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
        store.perceptual.get_perceptual_report.return_value = None
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
        store.perceptual.get_perceptual_report.return_value = {
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
        self.assertGreaterEqual(store.perceptual.get_perceptual_report.call_count, 2)


if __name__ == "__main__":
    unittest.main()

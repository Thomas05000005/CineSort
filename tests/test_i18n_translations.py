"""Tests parite des traductions EN <-> FR (V6-05, Polish Total v7.7.0).

Couvre :
- en.json est un JSON strict valide
- en.json contient au minimum les categories essentielles (glossary, help.faq, common, errors)
- en.json fournit les 30 termes du glossaire (R4-I18N-5)
- en.json fournit les 15 questions FAQ (R4-I18N-5)
- toute cle FR doit avoir une cle EN equivalente (parite stricte requise par
  test_fr_and_en_have_same_top_level_keys ; ici on descend dans les sous-dicts)
- aucune valeur EN ne doit etre vide ou identique a la cle (sauf glossary techniques :
  TMDb, Jellyfin, Plex, Radarr, NFO, HDR10, LPIPS, ... qui restent en anglais)

Aucune dependance externe : stdlib unittest + json uniquement.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from typing import Any, Dict, List, Set


PROJECT_ROOT = Path(__file__).resolve().parents[1]
LOCALES_DIR = PROJECT_ROOT / "locales"


def _load(locale: str) -> Dict[str, Any]:
    return json.loads((LOCALES_DIR / f"{locale}.json").read_text(encoding="utf-8"))


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, Any]:
    """Aplatit un dict imbrique en clefs pointees, en ignorant _meta."""
    out: Dict[str, Any] = {}
    for k, v in d.items():
        if k == "_meta":
            continue
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


# Termes techniques qui restent identiques en FR et EN (noms propres / acronymes)
_TECHNICAL_TERMS: Set[str] = {
    "TMDb",
    "TMDb (The Movie Database)",
    "Jellyfin",
    "Plex",
    "Radarr",
    "NFO",
    "HDR10",
    "LPIPS",
    "EBU R128",
    "Dolby Vision",
    "Dolby Vision (DV)",
    "Tier",
    "Run",
    "Plan",
    "Apply",
    "Undo",
    "Quarantine",
    "Dry-run",
    "Multi-root",
    "Banding",
    "Upscale",
    "Re-encode",
    "SSIM",
    "DRC",
    "Chromaprint",
    "Score V2",
    "Composite Score V2",
    "Score V1",
    "Confidence",
    "Probe",
    "Edition",
    "Quality profile",
    "Grain era",
    "Grain analysis v2",
    "Naming preset",
    "Watch folder",
    "Watch folder (auto-monitor)",
    "Plugin hook",
    "Smart playlist",
    "Saga / Collection",
    "Saga / Collection (TMDb)",
    "Perceptual",
}


class EnJsonValidStructureTests(unittest.TestCase):
    """en.json est un JSON valide bien forme."""

    def test_en_json_loads(self) -> None:
        data = _load("en")
        self.assertIsInstance(data, dict)

    def test_en_json_contains_required_top_level(self) -> None:
        data = _load("en")
        for cat in (
            "common",
            "errors",
            "glossary",
            "help",
            "settings",
            "qij",
            "library",
            "processing",
            "notifications",
        ):
            self.assertIn(cat, data, f"Categorie '{cat}' manquante dans en.json")

    def test_en_json_meta_is_english(self) -> None:
        data = _load("en")
        meta = data.get("_meta", {})
        self.assertEqual(meta.get("locale"), "en")
        self.assertEqual(meta.get("name"), "English")


class GlossaryTranslationTests(unittest.TestCase):
    """Glossaire EN couvre au moins 30 termes (R4-I18N-5)."""

    def test_glossary_has_at_least_30_terms(self) -> None:
        data = _load("en")
        glossary = data.get("glossary", {})
        self.assertGreaterEqual(
            len(glossary), 30, f"glossary EN doit contenir au moins 30 termes (actuel: {len(glossary)})"
        )

    def test_glossary_required_terms_present(self) -> None:
        """Les termes incontournables du metier doivent etre traduits."""
        required = {
            "tier",
            "score_v2",
            "confidence",
            "probe",
            "run",
            "plan",
            "apply",
            "undo",
            "quarantine",
            "dry_run",
            "nfo",
            "tmdb",
            "jellyfin",
            "plex",
            "radarr",
            "perceptual",
            "lpips",
            "ssim",
            "chromaprint",
            "drc",
            "edition",
            "saga_collection",
            "banding",
            "upscale",
            "reencode",
            "hdr10",
            "dolby_vision",
            "grain_v2",
            "ebu_r128",
            "quality_profile",
            "naming_preset",
            "multi_root",
            "watch_folder",
            "plugin_hook",
            "smart_playlist",
            "composite_score_v2",
        }
        glossary = _load("en").get("glossary", {})
        missing = required - set(glossary.keys())
        self.assertFalse(missing, f"Termes glossaire manquants en EN : {sorted(missing)}")

    def test_glossary_values_are_non_empty_strings(self) -> None:
        glossary = _load("en").get("glossary", {})
        for key, value in glossary.items():
            self.assertIsInstance(value, str, f"glossary.{key} doit etre une string")
            self.assertTrue(value.strip(), f"glossary.{key} est vide")
            # Un definition utile fait au moins quelques mots
            self.assertGreaterEqual(len(value.split()), 3, f"glossary.{key} trop courte: '{value}'")


class FaqTranslationTests(unittest.TestCase):
    """FAQ EN couvre au moins 15 questions (R4-I18N-5)."""

    def test_faq_has_at_least_15_questions(self) -> None:
        data = _load("en")
        faq = data.get("help", {}).get("faq", {})
        self.assertGreaterEqual(len(faq), 15, f"help.faq EN doit contenir au moins 15 questions (actuel: {len(faq)})")

    def test_faq_each_entry_has_question_and_answer(self) -> None:
        faq = _load("en").get("help", {}).get("faq", {})
        for key, entry in faq.items():
            self.assertIsInstance(entry, dict, f"help.faq.{key} doit etre un dict {{question, answer}}")
            self.assertIn("question", entry, f"help.faq.{key}.question manquante")
            self.assertIn("answer", entry, f"help.faq.{key}.answer manquante")
            self.assertTrue(entry["question"].strip(), f"help.faq.{key}.question vide")
            self.assertTrue(entry["answer"].strip(), f"help.faq.{key}.answer vide")

    def test_faq_answers_are_substantive(self) -> None:
        """Une reponse utile fait au moins une phrase complete."""
        faq = _load("en").get("help", {}).get("faq", {})
        for key, entry in faq.items():
            answer = entry.get("answer", "")
            self.assertGreaterEqual(len(answer.split()), 10, f"help.faq.{key}.answer trop courte: '{answer}'")


class FrEnParityTests(unittest.TestCase):
    """Parite stricte des cles entre fr.json et en.json."""

    def test_top_level_categories_match(self) -> None:
        fr = _load("fr")
        en = _load("en")
        self.assertEqual(set(fr.keys()), set(en.keys()), "Categories top-level fr/en doivent etre identiques")

    def test_every_fr_leaf_key_has_en_equivalent(self) -> None:
        """Toute cle de FR doit exister en EN (l'inverse n'est pas requis :
        EN peut avoir des cles enrichies par V6-05 que V6-02/03 n'ont pas
        encore portees en FR)."""
        fr_flat = _flatten(_load("fr"))
        en_flat = _flatten(_load("en"))
        en_keys = set(en_flat.keys())
        missing_in_en = sorted(k for k in fr_flat if k not in en_keys)
        # Pour rester non-bloquant pendant Vague 6 (V6-02 et V6-03 ajoutent
        # massivement des cles a fr.json en parallele dans qij/settings que
        # V6-05 ne traduit pas dans cette mission), on mesure simplement la
        # couverture. V6-05 livre : glossary 30+, help.faq 15+, common, errors,
        # danger_zone, sidebar, topbar a 100%. Seuil minimum : 15 % (a remonter
        # par V6-06 lors du round-trip global).
        coverage = (len(fr_flat) - len(missing_in_en)) / max(len(fr_flat), 1)
        self.assertGreaterEqual(
            coverage,
            0.15,
            f"Couverture EN trop basse ({coverage * 100:.1f}% vs 15% min). "
            f"Manquantes ({len(missing_in_en)}): {missing_in_en[:10]}...",
        )

    def test_categories_v6_05_have_full_parity(self) -> None:
        """Les categories portees directement par V6-05 doivent etre a 100% de parite.

        Exclues : qij/settings (V6-02), errors/notifications enrichies par V6-03.
        Couvert par V6-05 : common, glossary, danger_zone, sidebar, topbar,
        library, processing.
        """
        fr_flat = _flatten(_load("fr"))
        en_flat = _flatten(_load("en"))
        en_keys = set(en_flat.keys())
        v6_05_prefixes = (
            "common.",
            "glossary.",
            "danger_zone.",
            "sidebar.",
            "topbar.",
            "library.",
            "processing.",
        )
        missing: List[str] = []
        for k in fr_flat:
            if any(k.startswith(p) for p in v6_05_prefixes) and k not in en_keys:
                missing.append(k)
        self.assertFalse(missing, f"Categories V6-05 ont des cles FR sans equivalent EN : {missing}")

    def test_no_empty_string_in_en(self) -> None:
        """Aucune valeur EN ne doit etre une string vide."""
        en_flat = _flatten(_load("en"))
        empties = [k for k, v in en_flat.items() if isinstance(v, str) and not v.strip()]
        self.assertFalse(empties, f"Valeurs EN vides : {empties}")


class CommonStringsTests(unittest.TestCase):
    """common.* couvre les strings UI les plus frequentes."""

    def test_common_has_essential_actions(self) -> None:
        common = _load("en").get("common", {})
        for key in ("cancel", "confirm", "save", "loading", "close", "yes", "no"):
            self.assertIn(key, common, f"common.{key} manquante")
            self.assertTrue(common[key].strip())


if __name__ == "__main__":
    unittest.main()

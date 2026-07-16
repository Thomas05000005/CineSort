"""Audit ultra 2026-07-13 — Vague 4B : 2 constantes frontend perimees.

Findings couverts (assertions sur la SOURCE JS + comparaison a la source backend
CANONIQUE) :

  - M5 : parametres.js `_DEFAULT_TIERS` etait la grille pre-v1.5.5 (85/68/54/30)
    ECRITE en base au save de profil, alors que le scoring applique la grille
    canonique v1.5.7 70/66/55/40 (cinesort/domain/quality_score
    .default_quality_profile()["tiers"] == cinesort/domain/tiers_helpers
    .DEFAULT_TIER_THRESHOLDS). Fix : recalibrer _DEFAULT_TIERS sur le backend.

  - M6 : processing.js `_renderReviewRow` bucketait la confiance via 80/60 EN DUR
    alors que traitement.js (source de reference) pilote via
    getConfidenceThresholdsSync() (source unique cinesort/domain/
    confidence_thresholds.py). Fix : aligner processing.js sur la meme source.
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from cinesort.domain.quality_score import default_quality_profile
from cinesort.domain.tiers_helpers import DEFAULT_TIER_THRESHOLDS

_ROOT = Path(__file__).resolve().parents[1]
_PARAMETRES_JS = _ROOT / "web" / "dashboard" / "views" / "parametres.js"
_PROCESSING_JS = _ROOT / "web" / "dashboard" / "views" / "processing.js"

_TIER_KEYS = ("platinum", "gold", "silver", "bronze")


def _fn_block(src: str, signature_substr: str) -> str:
    """Corps { ... } de la fonction dont la signature contient `signature_substr`,
    par comptage d'accolades (robuste aux blocs imbriques)."""
    i = src.index(signature_substr)
    b = src.index("{", i)
    depth = 0
    for j in range(b, len(src)):
        ch = src[j]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return src[i : j + 1]
    return src[i:]


def _parse_default_tiers(src: str) -> dict:
    """Extrait l'objet litteral `const _DEFAULT_TIERS = { ... };` en dict int."""
    m = re.search(r"const\s+_DEFAULT_TIERS\s*=\s*\{([^}]*)\}", src)
    assert m, "declaration `const _DEFAULT_TIERS = { ... }` introuvable"
    body = m.group(1)
    out: dict = {}
    for key in _TIER_KEYS:
        km = re.search(rf"\b{key}\s*:\s*(\d+)", body)
        assert km, f"cle tier `{key}` absente de _DEFAULT_TIERS"
        out[key] = int(km.group(1))
    return out


class M5DefaultTiersCanonicalTests(unittest.TestCase):
    """M5 : _DEFAULT_TIERS aligne sur la grille backend canonique v1.5.7."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PARAMETRES_JS.read_text(encoding="utf-8")
        cls.tiers = _parse_default_tiers(cls.js)

    def test_matches_default_tier_thresholds(self) -> None:
        """Egalite exacte avec cinesort/domain/tiers_helpers.DEFAULT_TIER_THRESHOLDS."""
        for key in _TIER_KEYS:
            self.assertEqual(
                self.tiers[key],
                DEFAULT_TIER_THRESHOLDS[key],
                f"_DEFAULT_TIERS['{key}']={self.tiers[key]} != backend "
                f"DEFAULT_TIER_THRESHOLDS['{key}']={DEFAULT_TIER_THRESHOLDS[key]}",
            )

    def test_matches_default_quality_profile(self) -> None:
        """Egalite avec la 2e copie backend synchronisee (default_quality_profile)."""
        prof_tiers = default_quality_profile()["tiers"]
        for key in _TIER_KEYS:
            self.assertEqual(self.tiers[key], prof_tiers[key])

    def test_not_legacy_pre_v155_grid(self) -> None:
        """La grille pre-v1.5.5 (85/68/54/30) ne doit plus etre le defaut."""
        legacy = {"platinum": 85, "gold": 68, "silver": 54, "bronze": 30}
        self.assertNotEqual(self.tiers, legacy)

    def test_strictly_decreasing_invariant(self) -> None:
        """Invariant valide au save (parametres.js) : platinum > gold > silver > bronze."""
        t = self.tiers
        self.assertTrue(
            t["platinum"] > t["gold"] > t["silver"] > t["bronze"],
            f"invariant strictement decroissant viole : {t}",
        )


class M6ProcessingConfidenceThresholdsTests(unittest.TestCase):
    """M6 : processing.js pilote la confiance par getConfidenceThresholdsSync."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PROCESSING_JS.read_text(encoding="utf-8")
        cls.render_fn = _fn_block(cls.js, "function _renderReviewRow(")

    def test_imports_sync_thresholds_from_core_api(self) -> None:
        """Import de getConfidenceThresholdsSync depuis ../core/api.js (source unique)."""
        self.assertRegex(
            self.js,
            r"import\s*\{[^}]*getConfidenceThresholdsSync[^}]*\}\s*from\s*"
            r"[\"']\.\./core/api\.js[\"']",
        )

    def test_render_uses_sync_thresholds(self) -> None:
        """_renderReviewRow lit .high / .medium via getConfidenceThresholdsSync."""
        self.assertIn("getConfidenceThresholdsSync()", self.render_fn)
        self.assertIn(".high", self.render_fn)
        self.assertIn(".medium", self.render_fn)

    def test_render_no_hardcoded_80_60(self) -> None:
        """Plus aucun seuil 80/60 EN DUR dans le bucket de confiance."""
        self.assertNotRegex(self.render_fn, r"conf\s*>=\s*80")
        self.assertNotRegex(self.render_fn, r"conf\s*>=\s*60")

    def test_thresholds_align_with_traitement(self) -> None:
        """La reference traitement.js utilise la meme source (non-regression)."""
        traitement = (_ROOT / "web" / "dashboard" / "views" / "traitement.js").read_text(
            encoding="utf-8"
        )
        self.assertIn("getConfidenceThresholdsSync()", traitement)


if __name__ == "__main__":  # pragma: no cover
    unittest.main()

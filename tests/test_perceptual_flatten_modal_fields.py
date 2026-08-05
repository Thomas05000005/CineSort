"""`get_perceptual_details` doit exposer AU TOP-LEVEL tout ce que la modale lit.

Ultra-audit 2026-08 (N32) : `_flatten_perceptual_for_modal` remontait
grain_analysis / width / height / hdr_analysis / breakdown, mais oubliait deux
champs de la MEME famille, tous deux imbriques sous `metrics` par
`PerceptualResult.to_dict()` (cinesort/domain/perceptual/models.py) :

- `audio_perceptual` (lu en perceptual-modal.js:327 sous la cle
  `dynamic_range_db`, que le rapport stocke sous `astats.dynamic_range`) ;
- `cross_verdicts` (lu en perceptual-modal.js:227 et :422) — la section
  « Verdicts croises » etait TOUJOURS vide, pour tous les films.

Le rapport de test est construit avec les VRAIS dataclasses du domaine, pour
que la forme testee suive automatiquement `to_dict()` si elle evolue.
"""

from __future__ import annotations

import sys
import unittest
from typing import Any, Dict, Optional

sys.path.insert(0, ".")

from cinesort.domain.perceptual.models import AudioPerceptual, PerceptualResult, VideoPerceptual
from cinesort.ui.api import perceptual_support


class _FakePerceptualRepo:
    def __init__(self, report: Optional[Dict[str, Any]]) -> None:
        self._report = report

    def get_perceptual_report(self, *, run_id: str, row_id: str) -> Optional[Dict[str, Any]]:
        return self._report


class _FakeStore:
    def __init__(self, report: Optional[Dict[str, Any]]) -> None:
        self.perceptual = _FakePerceptualRepo(report)


class _FakeApi:
    def __init__(self, report: Optional[Dict[str, Any]]) -> None:
        self._state_dir = "."
        self._store = _FakeStore(report)

    def _get_or_create_infra(self, state_dir: Any):
        return self._store, None


def _build_report() -> Dict[str, Any]:
    """Rapport DB realiste : metrics = PerceptualResult.to_dict()."""
    audio = AudioPerceptual(
        track_index=0,
        track_codec="dts",
        track_channels=6,
        dynamic_range=13.5,
        crest_factor=17.2,
        audio_score=72,
        audio_tier="bon",
    )
    result = PerceptualResult(
        video=VideoPerceptual(resolution_width=1920, resolution_height=1080),
        audio=audio,
        cross_verdicts=[
            {
                "id": "fake_4k",
                "label": "Faux 4K probable",
                "detail": "bit depth effectif faible",
                "severity": "error",
            }
        ],
    )
    return {
        "run_id": "run_n32",
        "row_id": "R1",
        "metrics": result.to_dict(),
    }


class PerceptualFlattenModalFieldsTests(unittest.TestCase):
    def _details(self) -> Dict[str, Any]:
        api = _FakeApi(_build_report())
        out = perceptual_support.get_perceptual_details(api, "run_n32", "R1")
        self.assertTrue(out.get("ok"), out)
        return out["details"]

    def test_cross_verdicts_are_readable_at_top_level(self) -> None:
        details = self._details()
        # Prealable : la donnee EST bien imbriquee sous metrics dans le rapport DB.
        self.assertIn("cross_verdicts", details.get("metrics", {}))
        # Ce que la modale lit : d.cross_verdicts (Array.isArray).
        verdicts = details.get("cross_verdicts")
        self.assertIsInstance(verdicts, list)
        self.assertEqual(len(verdicts), 1)
        self.assertEqual(verdicts[0].get("label"), "Faux 4K probable")
        self.assertEqual(verdicts[0].get("severity"), "error")

    def test_audio_perceptual_is_readable_at_top_level(self) -> None:
        details = self._details()
        self.assertIn("audio_perceptual", details.get("metrics", {}))
        audio = details.get("audio_perceptual")
        self.assertIsInstance(audio, dict)
        self.assertEqual((audio.get("track_analyzed") or {}).get("codec"), "dts")
        self.assertEqual(audio.get("audio_score"), 72)

    def test_dynamic_range_is_exposed_with_the_key_the_modal_reads(self) -> None:
        """La modale lit `dynamic_range_db` ; le rapport le stocke en astats.dynamic_range."""
        details = self._details()
        audio = details.get("audio_perceptual") or {}
        self.assertEqual(audio.get("dynamic_range_db"), 13.5)

    def test_flatten_does_not_mutate_the_stored_metrics(self) -> None:
        """La derivation `dynamic_range_db` ne doit pas polluer le rapport persiste."""
        details = self._details()
        stored_audio = details["metrics"]["audio_perceptual"]
        self.assertNotIn("dynamic_range_db", stored_audio)

    def test_existing_top_level_values_win(self) -> None:
        """Idempotence : un champ deja present au top-level n'est pas ecrase."""
        report = _build_report()
        report["cross_verdicts"] = [{"id": "deja", "label": "Deja la", "severity": "warn"}]
        api = _FakeApi(report)
        details = perceptual_support.get_perceptual_details(api, "run_n32", "R1")["details"]
        self.assertEqual(details["cross_verdicts"][0]["label"], "Deja la")

    def test_report_without_audio_or_verdicts_is_untouched(self) -> None:
        """Aucun champ invente quand la donnee n'existe pas (pas de faux 'vide')."""
        api = _FakeApi({"run_id": "run_n32", "row_id": "R1", "metrics": {}})
        details = perceptual_support.get_perceptual_details(api, "run_n32", "R1")["details"]
        self.assertNotIn("audio_perceptual", details)
        self.assertNotIn("cross_verdicts", details)

    def test_codec_stays_absent_by_design(self) -> None:
        """Arbitrage documente (docstring du flatten) : le codec n'est pas derivable."""
        details = self._details()
        self.assertIsNone(details.get("codec"))


if __name__ == "__main__":
    unittest.main()

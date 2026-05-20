"""Tests Phase 3.2 : Modal Perceptuelle dual-mode (spec 02)."""

from __future__ import annotations

import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PERCEPTUAL_LABELS = _ROOT / "web" / "dashboard" / "core" / "perceptual-labels.js"
_PERCEPTUAL_MODAL = _ROOT / "web" / "dashboard" / "components" / "perceptual-modal.js"
_COMPONENTS_CSS = _ROOT / "web" / "shared" / "components.css"


class FileExistsTests(unittest.TestCase):
    def test_labels_exists(self) -> None:
        self.assertTrue(_PERCEPTUAL_LABELS.is_file())

    def test_modal_exists(self) -> None:
        self.assertTrue(_PERCEPTUAL_MODAL.is_file())


class PerceptualLabelsApiTests(unittest.TestCase):
    """Spec 02 §2 : mapping codes verdicts -> labels humains."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_LABELS.read_text(encoding="utf-8")

    def test_verdict_labels_exported(self) -> None:
        self.assertIn("export const VERDICT_LABELS", self.js)

    def test_humanize_exported(self) -> None:
        self.assertIn("export function humanize", self.js)

    def test_score_components_exported(self) -> None:
        self.assertIn("export const SCORE_V2_COMPONENTS", self.js)

    def test_main_verdict_codes_mapped(self) -> None:
        for code in (
            "lossless",
            "lossy_high",
            "lossy_medium",
            "lossy_low",
            "native_4k",
            "native_1080p",
            "upscaled_1080p",
            "upscaled_4k",
            "platinum",
            "gold",
            "silver",
            "bronze",
            "reject",
            "clean",
            "moderate",
            "noisy",
            "sdr",
            "hdr10",
            "dolby_vision",
        ):
            self.assertIn(f"{code}:", self.js, f"verdict {code} non mappe")

    def test_score_v2_components_weights(self) -> None:
        """Spec 02 : 6 composantes du Score V2 avec poids fixes."""
        for label in ("Résolution", "Bitrate vidéo", "Codec", "Bitrate audio", "Canaux audio", "Sous-titres FR"):
            self.assertIn(label, self.js)


class PerceptualModalApiTests(unittest.TestCase):
    """Spec 02 §1 + §4 : modal centree avec 5 etats."""

    @classmethod
    def setUpClass(cls) -> None:
        cls.js = _PERCEPTUAL_MODAL.read_text(encoding="utf-8")

    def test_exports_open(self) -> None:
        self.assertIn("export async function openPerceptualModal(", self.js)

    def test_exports_close(self) -> None:
        self.assertIn("export function closePerceptualModal(", self.js)

    def test_uses_get_perceptual_details(self) -> None:
        """Spec 02 : utilise get_perceptual_details (lecture pure DB), pas _report."""
        self.assertIn("quality/get_perceptual_details", self.js)

    def test_relaunch_uses_force(self) -> None:
        self.assertIn("force: true", self.js)

    def test_renders_5_states(self) -> None:
        """Spec 02 §4 : normal / missing / disabled / no-ffmpeg / error/loading."""
        for fn in (
            "_renderMissing",
            "_renderDisabled",
            "_renderNoFfmpeg",
            "_renderError",
            "_renderLoading",
            "_renderNormal",
        ):
            self.assertIn(f"function {fn}(", self.js, f"renderer {fn} manquant")

    def test_renders_6_sections(self) -> None:
        """Spec 02 §1 : Score + Video + Audio + Breakdown + Cross-verdicts."""
        for fn in (
            "_renderScoreSection",
            "_renderVideoSection",
            "_renderAudioSection",
            "_renderBreakdownSection",
            "_renderCrossVerdictsSection",
        ):
            self.assertIn(f"function {fn}(", self.js, f"section {fn} manquante")

    def test_keyboard_escape_close(self) -> None:
        self.assertIn('ev.key === "Escape"', self.js)

    def test_uses_perceptual_labels(self) -> None:
        self.assertIn("perceptual-labels.js", self.js)
        self.assertIn("humanize", self.js)


class CssTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.css = _COMPONENTS_CSS.read_text(encoding="utf-8")

    def test_modal_classes(self) -> None:
        for cls in (
            ".perceptual-modal-overlay",
            ".perceptual-modal",
            ".perceptual-modal-header",
            ".perceptual-modal-body",
            ".perceptual-modal-footer",
            ".perceptual-section",
            ".perceptual-score-circle",
            ".perceptual-score-circle--good",
            ".perceptual-score-circle--warning",
            ".perceptual-score-circle--critical",
            ".perceptual-bar",
            ".perceptual-bar-fill",
            ".perceptual-dl",
            ".perceptual-breakdown-table",
            ".perceptual-status--good",
            ".perceptual-status--warning",
            ".perceptual-status--critical",
            ".perceptual-verdicts-list",
        ):
            self.assertIn(cls, self.css)


if __name__ == "__main__":
    unittest.main()

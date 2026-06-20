"""GATE AUDIT 2026-06-14 (R6-D) — onglets Frames/Audio du comparateur.

Bug : le flag de cache `xLoadedByPair[pairKey]` etait pose a `true` AVANT le
querySelector du conteneur. Si le DOM n'etait pas pret, la fonction faisait un
`return` precoce en laissant le flag a `true` -> l'onglet ne se chargeait
JAMAIS (placeholder "Extraction en cours" fige a vie = symptome "audio >30min").
De plus, aucune garde anti-concurrence.

Fix : `Loaded = true` UNIQUEMENT apres un appel reussi (apres `await apiPost`),
et garde `xLoadingByPair` (chargement en vol).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

_MODAL = (
    Path(__file__).resolve().parent.parent
    / "web" / "dashboard" / "components" / "duplicate-comparator-modal.js"
)


class ComparatorLazyLoadGuardTests(unittest.TestCase):
    def setUp(self) -> None:
        self.src = _MODAL.read_text(encoding="utf-8")

    def _fn(self, name: str) -> str:
        m = re.search(r"async function " + re.escape(name) + r"\(\)\s*\{(.+?)\n\}", self.src, re.DOTALL)
        self.assertIsNotNone(m, f"{name} introuvable")
        return m.group(1)

    def _assert_loaded_after_await(self, body: str, endpoint: str, loaded_var: str, loading_var: str) -> None:
        idx_await = body.find(f'await apiPost("{endpoint}"')
        idx_loaded_true = body.find(f"{loaded_var}[pairKey] = true")
        self.assertGreaterEqual(idx_await, 0, "appel apiPost attendu")
        self.assertGreaterEqual(idx_loaded_true, 0, "le flag loaded doit etre pose")
        self.assertLess(idx_await, idx_loaded_true,
                        "Le flag loaded ne doit etre pose qu'APRES l'appel reussi (pas avant le await).")
        self.assertIn(loading_var, body, "Une garde anti-concurrence (loading) doit exister.")

    def test_frames_loaded_only_after_success(self) -> None:
        self._assert_loaded_after_await(
            self._fn("_loadFramesTab"),
            "quality/get_perceptual_compare_frames",
            "_state.framesLoadedByPair",
            "framesLoadingByPair",
        )

    def test_audio_loaded_only_after_success(self) -> None:
        self._assert_loaded_after_await(
            self._fn("_loadAudioTab"),
            "quality/get_perceptual_compare_audio",
            "_state.audioLoadedByPair",
            "audioLoadingByPair",
        )


if __name__ == "__main__":
    unittest.main()

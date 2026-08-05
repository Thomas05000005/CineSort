"""#381 — les sous-scores mel etaient calcules, persistes... et jamais affiches.

`cinesort/domain/perceptual/mel_analysis.py` produit quatre sous-detections
(soft clipping, shelf MP3 16 kHz, trous AAC, aplatissement spectral), un score
composite qui pese 15 % du sous-score audio (`AUDIO_WEIGHT_MEL`) et un verdict.
Tout cela est serialise par `AudioPerceptual.to_dict()["mel"]` et remonte
au top-level par `_flatten_perceptual_for_modal`. Cote ecran, en revanche,
`grep -rn "spectral_flatness" web/` rendait 0 resultat : la modale perceptuelle
n'en montrait aucune ligne.

Deux chaines sont verifiees ici, chacune par son point d'entree REEL :

1. backend — `perceptual_support.get_perceptual_details` doit continuer a
   servir le bloc `mel` sous `audio_perceptual` (rapport construit avec les
   vraies dataclasses du domaine, comme test_perceptual_flatten_modal_fields) ;
2. frontend — `_renderNormal` (la fonction qui construit le corps de la modale,
   pas le helper `_renderMelRows` seul) doit porter ces lignes. La vraie source
   `components/perceptual-modal.js` est executee sous Node, avec le VRAI
   `core/perceptual-labels.js` injecte : les libelles testes sont ceux livres.

Deux pieges couverts explicitement :

- **grandeur incomplete** : quand la mesure n'a pas eu lieu ("disabled",
  "insufficient_data"), les quatre champs valent leur defaut de dataclass
  (0.0 / false). Les afficher annoncerait « 0,0 % de frames clippees » pour une
  analyse qui n'a jamais tourne. Seul le verdict s'affiche alors.
- **etiquette fausse** : le code "clean" existe DEJA dans `VERDICT_LABELS` avec
  le sens grain video (« Très propre (denoised) »). Un verdict mel "clean" ne
  doit pas hériter de ce libellé.
"""

from __future__ import annotations

import unittest
from typing import Any, Dict, Optional

from cinesort.domain.perceptual.models import AudioPerceptual, PerceptualResult, VideoPerceptual
from cinesort.ui.api import perceptual_support
from tests._jsexec import ROOT, inline_module, require_node, run_module_test

PERCEPTUAL_JS = ROOT / "web" / "dashboard" / "components" / "perceptual-modal.js"


# ---------------------------------------------------------------------------
# 1. Backend : le bloc `mel` doit survivre a l'aplatissement
# ---------------------------------------------------------------------------


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


class MelSurvivesFlattenTests(unittest.TestCase):
    """La modale lit `d.audio_perceptual.mel` : l'endpoint doit le porter."""

    def _details(self) -> Dict[str, Any]:
        audio = AudioPerceptual(
            track_index=0,
            track_codec="aac",
            track_channels=6,
            dynamic_range=11.0,
            mel_soft_clipping_pct=7.5,
            mel_mp3_shelf_detected=True,
            mel_aac_holes_ratio=0.125,
            mel_spectral_flatness=0.312,
            mel_score=44,
            mel_verdict="mp3_encoded",
        )
        result = PerceptualResult(
            video=VideoPerceptual(resolution_width=1920, resolution_height=1080),
            audio=audio,
        )
        report = {"metrics": result.to_dict(), "ts": 1749000000.0}
        res = perceptual_support.get_perceptual_details(_FakeApi(report), "run-1", "row-1")
        self.assertTrue(res.get("ok"), res)
        return res["details"]

    def test_mel_block_is_served_at_top_level(self) -> None:
        mel = self._details()["audio_perceptual"]["mel"]
        self.assertEqual(mel["verdict"], "mp3_encoded")
        self.assertEqual(mel["score"], 44)
        self.assertAlmostEqual(mel["spectral_flatness"], 0.312, places=6)
        self.assertAlmostEqual(mel["aac_holes_ratio"], 0.125, places=6)
        self.assertAlmostEqual(mel["soft_clipping_pct"], 7.5, places=6)
        self.assertIs(mel["mp3_shelf_detected"], True)


# ---------------------------------------------------------------------------
# 2. Frontend : la modale doit REELLEMENT rendre ces lignes
# ---------------------------------------------------------------------------

# `humanize` / `humanizeMelVerdict` / `isMelMeasured` viennent de la VRAIE
# source (inline_module) : un stub qui les reecrirait validerait la copie du
# testeur, pas les libelles livres.
PERCEPTUAL_STUBS = (
    inline_module("core/perceptual-labels.js")
    + r"""
const escapeHtml = (s) => String(s == null ? "" : s)
  .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const apiPost = async () => ({ status: 200, data: { ok: true } });
const rpSetSections = () => {};
const rpSetExpandedWidth = () => {};
const rpIsExpandedWidth = () => false;
const openDuplicateComparatorModal = () => {};
const trapFocus = () => () => {};
globalThis.window = globalThis.window || { addEventListener() {}, removeEventListener() {}, location: { hash: "#/bibliotheque" } };
globalThis.document = globalThis.document || {
  querySelector: () => null, querySelectorAll: () => [], getElementById: () => null,
  addEventListener() {}, removeEventListener() {},
};
"""
)

PERCEPTUAL_EXTRA = r"""
export const __h = { renderNormal: _renderNormal };
"""

# Payload realiste : forme exacte de `details` (cf. MelSurvivesFlattenTests).
_DRIVER = r"""
const details = {
  global_score_v2: 61.0, display_tier: "silver", ts: 1749000000.0,
  width: 1920, height: 1080,
  spectral_cutoff_hz: 16000.0, lossy_verdict: "lossy_medium",
  audio_perceptual: { dynamic_range_db: 11.0, mel: __MEL__ },
};
__emit({ html: M.__h.renderNormal("Un film", details) });
"""


def _driver(mel_literal: str) -> str:
    return _DRIVER.replace("__MEL__", mel_literal)


_MEASURED_MEL = """{
  soft_clipping_pct: 7.5, mp3_shelf_detected: true, aac_holes_ratio: 0.125,
  spectral_flatness: 0.312, score: 44, verdict: "mp3_encoded"
}"""

_CLEAN_MEL = """{
  soft_clipping_pct: 0.5, mp3_shelf_detected: false, aac_holes_ratio: 0.0,
  spectral_flatness: 0.288, score: 96, verdict: "clean"
}"""

# Analyse jamais lancee : les quatre champs sont au defaut du dataclass.
_DISABLED_MEL = """{
  soft_clipping_pct: 0.0, mp3_shelf_detected: false, aac_holes_ratio: 0.0,
  spectral_flatness: 0.0, score: 0, verdict: "disabled"
}"""


class MelRowsRenderedTests(unittest.TestCase):
    def setUp(self) -> None:
        require_node(self)

    def _html(self, mel_literal: str) -> str:
        res = run_module_test(
            PERCEPTUAL_JS,
            stubs=PERCEPTUAL_STUBS,
            extra=PERCEPTUAL_EXTRA,
            driver=_driver(mel_literal),
        )
        return res["html"]

    # ------------------------------------------------------------- ROUGE
    def test_measured_mel_shows_the_four_sub_detections(self) -> None:
        """ROUGE avant fix : aucune de ces lignes n'existait dans la modale."""
        html = self._html(_MEASURED_MEL)
        # Bornage sur le couple <dt>/<dd> COMPLET : un `assertIn("12.5", html)`
        # passerait sur un « 112.5 » venu d'ailleurs dans la modale.
        self.assertIn("<dt>Analyse spectrale (mel)</dt><dd>Signature MP3 (coupure vers 16 kHz)</dd>", html)
        self.assertIn("<dt>Score mel</dt><dd>44/100</dd>", html)
        self.assertIn("<dt>Soft clipping</dt><dd>7.5 % des frames</dd>", html)
        self.assertIn("<dt>Shelf MP3 16 kHz</dt><dd>détecté</dd>", html)
        self.assertIn("<dt>Trous AAC</dt><dd>12.5 % des bandes</dd>", html)
        self.assertIn("<dt>Aplatissement spectral</dt><dd>0.312</dd>", html)

    def test_mel_rows_land_inside_the_audio_section(self) -> None:
        """La section qui les porte est « Métriques audio », pas une autre."""
        html = self._html(_MEASURED_MEL)
        start = html.index('data-section="audio"')
        end = html.index('data-section="breakdown"')
        self.assertGreater(end, start)
        self.assertIn("<dt>Aplatissement spectral</dt>", html[start:end])

    def test_clean_mel_verdict_is_not_the_grain_label(self) -> None:
        """ROUGE si `humanize()` (table grain/upscale/tier) etait reutilise :
        le code "clean" y vaut « Très propre (denoised) », un libelle VIDEO."""
        html = self._html(_CLEAN_MEL)
        self.assertIn("<dt>Analyse spectrale (mel)</dt><dd>Aucune signature de compression</dd>", html)
        self.assertNotIn("denoised", html)

    def test_unmeasured_mel_shows_the_verdict_but_no_fake_zero(self) -> None:
        """ROUGE si les grandeurs etaient rendues sans garde : les defauts de
        dataclass (0.0 / false) s'afficheraient comme des mesures."""
        html = self._html(_DISABLED_MEL)
        self.assertIn("<dt>Analyse spectrale (mel)</dt><dd>Analyse mel désactivée</dd>", html)
        self.assertNotIn("<dt>Soft clipping</dt>", html)
        self.assertNotIn("<dt>Shelf MP3 16 kHz</dt>", html)
        self.assertNotIn("<dt>Trous AAC</dt>", html)
        self.assertNotIn("<dt>Aplatissement spectral</dt>", html)
        self.assertNotIn("<dt>Score mel</dt>", html)

    def test_report_without_mel_block_renders_nothing_and_does_not_crash(self) -> None:
        """Retro-compat : rapport anterieur a §12 v7.5.0, pas de cle `mel`."""
        html = self._html("undefined")
        self.assertNotIn("Analyse spectrale (mel)", html)
        # La modale reste complete par ailleurs.
        self.assertIn('data-section="audio"', html)


if __name__ == "__main__":
    unittest.main()

"""Tests de _resolution_label - figer la semantique width-based.

Contexte (hotfix3 2026-06-02, post-commit a141f75) : le commit a141f75
declare uniquement "BUG-015 migration_manager" mais embarquait aussi un
changement de comportement de `cinesort.domain.naming._resolution_label`
(SCAN-1 propagation : alignement sur quality_score._resolution_label,
width-based au lieu de height-only). Ce changement reclasse notamment
les films cinema 1920x800 (ratio ~2.35:1) en 1080p au lieu de 720p.

Ces tests figent la nouvelle semantique pour eviter toute regression
silencieuse future et documenter explicitement le comportement attendu.

Backward compat (release notes hotfix3) : les fichiers DEJA renommes
avec l ancienne logique height-only NE SONT PAS modifies automatiquement
(pas de re-rename batch). Seuls les nouveaux scans appliqueront la
nouvelle classification.
"""

from __future__ import annotations

import unittest

from cinesort.domain.naming import _resolution_label


class ResolutionLabelWidthBasedTests(unittest.TestCase):
    """Cas representatifs : cinema 2.35:1, 16:9 standard, anamorphique, edges."""

    # --- 2160p (UHD) -----------------------------------------------------

    def test_uhd_standard_3840x2160(self) -> None:
        """4K UHD 16:9 standard."""
        self.assertEqual(_resolution_label({"width": 3840, "height": 2160}), "2160p")

    def test_uhd_cinema_3840x1600(self) -> None:
        """4K cinema 2.40:1 (Mad Max Fury Road, Dune, etc.) -> 2160p."""
        self.assertEqual(_resolution_label({"width": 3840, "height": 1600}), "2160p")

    def test_uhd_height_only_seuil(self) -> None:
        """Fallback height : >= 2100 -> 2160p (DCI 4096x2160 ou anamorphique)."""
        self.assertEqual(_resolution_label({"width": 0, "height": 2160}), "2160p")

    def test_uhd_dci_4096x2160(self) -> None:
        """DCI 4K (cinema true 4K) -> 2160p."""
        self.assertEqual(_resolution_label({"width": 4096, "height": 2160}), "2160p")

    # --- 1080p (Full HD) -------------------------------------------------

    def test_fhd_standard_1920x1080(self) -> None:
        """Full HD 16:9 standard."""
        self.assertEqual(_resolution_label({"width": 1920, "height": 1080}), "1080p")

    def test_fhd_cinema_1920x800(self) -> None:
        """Cinema 2.40:1 (1920x800) : ANCIENNE logique height-only -> 720p,
        NOUVELLE logique width-based -> 1080p (critical regression cible)."""
        self.assertEqual(_resolution_label({"width": 1920, "height": 800}), "1080p")

    def test_fhd_cinema_1920x816(self) -> None:
        """Cinema 2.35:1 (1920x816) : meme cas que ci-dessus."""
        self.assertEqual(_resolution_label({"width": 1920, "height": 816}), "1080p")

    def test_fhd_height_only_seuil(self) -> None:
        """Fallback height : >= 1000 -> 1080p (anamorphique sans width)."""
        self.assertEqual(_resolution_label({"width": 0, "height": 1080}), "1080p")

    # --- 720p (HD) -------------------------------------------------------

    def test_hd_standard_1280x720(self) -> None:
        """HD 16:9 standard."""
        self.assertEqual(_resolution_label({"width": 1280, "height": 720}), "720p")

    def test_hd_cinema_1280x540(self) -> None:
        """Cinema 2.40:1 720p (1280x540) -> 720p (pas 480p)."""
        self.assertEqual(_resolution_label({"width": 1280, "height": 540}), "720p")

    def test_hd_height_only_seuil(self) -> None:
        """Fallback height : >= 680 -> 720p."""
        self.assertEqual(_resolution_label({"width": 0, "height": 720}), "720p")

    # --- 480p / fallback custom -----------------------------------------

    def test_sd_480p(self) -> None:
        """SD 480p (DVD NTSC)."""
        self.assertEqual(_resolution_label({"width": 720, "height": 480}), "480p")

    def test_sd_pal_576p_classifie_480p(self) -> None:
        """576p (DVD PAL, height >= 480) tombe dans le seuil 480p, PAS dans
        le fallback custom `{height}p`. Documente le comportement reel :
        seuil 480p couvre [480..679] de height."""
        self.assertEqual(_resolution_label({"width": 720, "height": 576}), "480p")

    def test_sd_low_360p_fallback_custom(self) -> None:
        """height < 480 tombe dans le fallback `{height}p` (ex: 360p VCD)."""
        self.assertEqual(_resolution_label({"width": 480, "height": 360}), "360p")

    # --- Edges : valeurs manquantes / nulles ----------------------------

    def test_empty_dict_returns_empty(self) -> None:
        """video vide -> chaine vide."""
        self.assertEqual(_resolution_label({}), "")

    def test_zero_dimensions_returns_empty(self) -> None:
        """width=0 et height=0 -> chaine vide (couvre None aussi via `not h and not w`)."""
        self.assertEqual(_resolution_label({"width": 0, "height": 0}), "")

    def test_only_width_no_height(self) -> None:
        """width seul renseigne (height absent) -> classification width-based."""
        self.assertEqual(_resolution_label({"width": 1920}), "1080p")

    def test_only_height_no_width(self) -> None:
        """height seul renseigne (width absent) -> classification height-based."""
        self.assertEqual(_resolution_label({"height": 1080}), "1080p")

    def test_negative_values_clamped_to_zero(self) -> None:
        """Valeurs negatives (corrupt probe) clampees a 0 via max(0, int(...))."""
        # max(0, -1) = 0, donc width et height = 0 -> chaine vide
        self.assertEqual(_resolution_label({"width": -1, "height": -1}), "")

    def test_string_values_coerced(self) -> None:
        """Probe peut renvoyer des str depuis ffprobe -> int() les coerce."""
        self.assertEqual(_resolution_label({"width": "1920", "height": "1080"}), "1080p")


if __name__ == "__main__":
    unittest.main()

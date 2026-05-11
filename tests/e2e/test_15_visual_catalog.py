"""Tests E2E catalogue visuel — generation screenshots + rapport HTML.

5 tests : screenshots generes, rapport HTML cree, sections, images, contenu.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)

CATALOG_DIR = _Path(__file__).resolve().parent / "screenshots" / "catalog"
REPORT_PATH = _Path(__file__).resolve().parent / "visual_report.html"


def _run_catalog() -> None:
    """Lance visual_catalog.py en headless si pas deja fait."""
    if len(list(CATALOG_DIR.glob("*.png"))) >= 20:
        return  # deja genere
    script = _Path(__file__).resolve().parent / "visual_catalog.py"
    subprocess.run([sys.executable, str(script)], timeout=600, check=False)


def _run_report() -> None:
    """Lance generate_visual_report.py si pas deja fait."""
    if REPORT_PATH.exists() and REPORT_PATH.stat().st_size > 10000:
        return
    script = _Path(__file__).resolve().parent / "generate_visual_report.py"
    subprocess.run([sys.executable, str(script)], timeout=60, check=False)


class TestVisualCatalog:
    """Tests du catalogue visuel."""

    def test_catalog_generates_screenshots(self, e2e_server):
        """Le catalogue genere au moins 20 screenshots."""
        _run_catalog()
        pngs = list(CATALOG_DIR.glob("*.png"))
        assert len(pngs) >= 20, f"Seulement {len(pngs)} screenshots generes"

    def test_report_html_created(self, e2e_server):
        """Le rapport HTML est cree."""
        _run_catalog()
        _run_report()
        assert REPORT_PATH.exists(), "visual_report.html non genere"
        assert REPORT_PATH.stat().st_size > 10000, "Rapport HTML trop petit"

    def test_report_has_viewport_sections(self, e2e_server):
        """Le rapport contient les sections desktop, tablet, mobile."""
        _run_catalog()
        _run_report()
        html = REPORT_PATH.read_text(encoding="utf-8")
        assert "Desktop" in html
        assert "Tablet" in html
        assert "Mobile" in html

    def test_report_has_images(self, e2e_server):
        """Le rapport contient au moins 40 images base64."""
        _run_catalog()
        _run_report()
        html = REPORT_PATH.read_text(encoding="utf-8")
        img_count = html.count("data:image/png;base64,")
        assert img_count >= 40, f"Seulement {img_count} images dans le rapport"

    def test_report_has_comparison(self, e2e_server):
        """Le rapport contient la section comparaison desktop vs mobile."""
        _run_catalog()
        _run_report()
        html = REPORT_PATH.read_text(encoding="utf-8")
        assert "Comparaison" in html or "compare" in html

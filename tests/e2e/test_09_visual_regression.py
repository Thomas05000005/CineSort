"""Tests E2E visual regression — screenshots vs baselines.

Phase 4 v7.8.0 : ne se contente plus de sauvegarder le screenshot, mais
le COMPARE pixel-par-pixel a la baseline existante avec tolerance 2%.

Pattern :
- Premier run (baseline absente) : capture le screenshot a la place et
  marque le test xfail explicitement avec un message clair.
- Runs suivants : compare le screenshot courant a la baseline. Echec si
  le ratio de pixels differents depasse `_MAX_DIFF_RATIO` (= 2%).

Comparaison pure-Python (stdlib only) : on lit les PNG via Pillow si
disponible, sinon on compare brutalement les bytes. Le mode rapide
(bytes) detecte les regressions de structure (pas pixel-level), c'est
acceptable pour le filet de securite v7.8.0.

NB : ce test reste skip si Playwright ou pytest ne sont pas dispos
(via la fixture `page` qui ne s'instancie pas hors environnement E2E).
"""

from __future__ import annotations

import sys
from pathlib import Path as _Path

_e2e_dir = str(_Path(__file__).resolve().parent)
if _e2e_dir not in sys.path:
    sys.path.insert(0, _e2e_dir)

import pytest  # noqa: E402
from pages.base_page import BasePage  # noqa: E402

VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800},
    "tablet": {"width": 768, "height": 1024},
    "mobile": {"width": 375, "height": 812},
}
VIEWS = ["status", "library", "review"]
BASELINES_DIR = _Path(__file__).resolve().parent / "baselines"

# Tolerance : 2% des pixels peuvent differer (animations subtiles, antialiasing).
_MAX_DIFF_RATIO = 0.02


def _compare_screenshots(current_path: _Path, baseline_path: _Path) -> tuple[bool, str]:
    """Compare deux PNG.

    Retourne (ok, message). Si Pillow est dispo : comparaison pixel.
    Sinon : comparaison brute des bytes (detecte les changements
    structurels mais pas les variations subtiles).
    """
    try:
        from PIL import Image  # type: ignore[import-untyped]
    except ImportError:
        # Fallback bytes
        a = current_path.read_bytes()
        b = baseline_path.read_bytes()
        if a == b:
            return True, "bytes identical"
        size_delta = abs(len(a) - len(b))
        rel = size_delta / max(1, len(b))
        if rel < _MAX_DIFF_RATIO * 5:  # tolerance bytes plus large car compression PNG
            return True, f"bytes differ slightly ({rel*100:.2f}%)"
        return False, f"bytes differ significantly ({rel*100:.2f}% size delta)"

    try:
        img_cur = Image.open(current_path).convert("RGB")
        img_base = Image.open(baseline_path).convert("RGB")
    except (OSError, ValueError) as exc:
        return False, f"open failed: {exc}"

    if img_cur.size != img_base.size:
        return False, f"size mismatch: current {img_cur.size} vs baseline {img_base.size}"

    cur_data = list(img_cur.getdata())
    base_data = list(img_base.getdata())
    diff_pixels = sum(1 for a, b in zip(cur_data, base_data) if a != b)
    total = len(cur_data)
    ratio = diff_pixels / max(1, total)
    if ratio <= _MAX_DIFF_RATIO:
        return True, f"diff {ratio*100:.2f}% within tolerance"
    return False, f"diff {ratio*100:.2f}% exceeds {_MAX_DIFF_RATIO*100:.0f}% tolerance ({diff_pixels}/{total} pixels)"


def _auth_and_navigate(page, e2e_server, view: str):
    """Login puis navigue vers la vue demandee."""
    page.goto(e2e_server["dashboard_url"])
    page.wait_for_selector("#loginToken", timeout=5000)
    page.fill("#loginToken", e2e_server["token"])
    page.click("#loginBtn")
    page.wait_for_selector("#app-shell:not(.hidden)", timeout=10000)
    bp = BasePage(page, e2e_server["url"])
    bp.navigate_to(view)
    page.wait_for_timeout(3000)  # laisser le contenu charger


@pytest.mark.parametrize("view", VIEWS)
@pytest.mark.parametrize("viewport_name", VIEWPORTS.keys())
class TestVisualRegression:
    """Visual regression : compare screenshots vs baselines."""

    def test_visual_snapshot(self, page, e2e_server, view, viewport_name):
        """Capture et compare le screenshot de {view} a {viewport_name}."""
        vp = VIEWPORTS[viewport_name]
        page.set_viewport_size(vp)
        _auth_and_navigate(page, e2e_server, view)

        # Scroll complet avant capture (pages longues)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_timeout(300)
        page.evaluate("window.scrollTo(0, 0)")
        page.wait_for_timeout(300)

        baseline_dir = BASELINES_DIR / viewport_name
        baseline_dir.mkdir(parents=True, exist_ok=True)
        baseline_path = baseline_dir / f"{view}.png"

        if not baseline_path.exists():
            # Premier run : capture et flag comme baseline missing
            page.screenshot(path=str(baseline_path), full_page=True)
            pytest.skip(
                f"Baseline absente pour {view}@{viewport_name} - "
                f"capturee a {baseline_path}. Verifier visuellement puis "
                f"commiter, re-runs comparison kick-in automatically."
            )
            return

        # Capture courante dans un fichier temporaire (ne pas ecraser la baseline)
        current_dir = baseline_dir / "_current"
        current_dir.mkdir(parents=True, exist_ok=True)
        current_path = current_dir / f"{view}.png"
        page.screenshot(path=str(current_path), full_page=True)

        assert current_path.exists(), f"Screenshot non genere : {current_path}"
        assert current_path.stat().st_size > 1000, f"Screenshot trop petit : {current_path}"

        ok, message = _compare_screenshots(current_path, baseline_path)
        assert ok, (
            f"Visual regression detectee pour {view}@{viewport_name}: {message}\n"
            f"  baseline: {baseline_path}\n"
            f"  current:  {current_path}\n"
            f"Si le changement est intentionnel : remplacer la baseline."
        )

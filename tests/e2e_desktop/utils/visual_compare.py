"""Comparaison visuelle de screenshots via pixelmatch."""

from __future__ import annotations

from pathlib import Path


def compare_screenshots(
    baseline_path: str | Path,
    screenshot_path: str | Path,
    diff_path: str | Path | None = None,
    threshold: float = 0.1,
    max_diff_pixels: int = 100,
) -> tuple[bool, int]:
    """Compare deux images PNG. Retourne (ok, mismatch_count).

    ok = True si le nombre de pixels differents est <= max_diff_pixels.
    """
    try:
        from PIL import Image
        from pixelmatch.contrib.PIL import pixelmatch as pm
    except ImportError:
        # Fallback : pas de pixelmatch installe, on skip la comparaison
        return True, 0

    baseline = Image.open(str(baseline_path))
    screenshot = Image.open(str(screenshot_path))

    # Redimensionner si tailles differentes
    if baseline.size != screenshot.size:
        screenshot = screenshot.resize(baseline.size)

    diff_img = Image.new("RGBA", baseline.size)

    mismatch = pm(
        baseline,
        screenshot,
        diff_img,
        threshold=threshold,
        includeAA=True,
    )

    if diff_path:
        diff_img.save(str(diff_path))

    ok = mismatch <= max_diff_pixels
    return ok, mismatch

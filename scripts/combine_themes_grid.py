#!/usr/bin/env python3
"""V4-04 — Combine les 4 captures de themes en une mosaique 2x2 pour le README."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SHOTS = PROJECT_ROOT / "docs" / "screenshots"
THEMES = ["studio", "cinema", "luxe", "neon"]


def main() -> int:
    try:
        from PIL import Image
    except ImportError:
        print("ERR Pillow non installe. Run: pip install pillow")
        return 1

    paths = [SHOTS / f"theme_{t}.png" for t in THEMES]
    missing = [p for p in paths if not p.exists()]
    if missing:
        print(f"ERR fichiers manquants : {missing}")
        return 1

    imgs = [Image.open(p) for p in paths]
    w, h = imgs[0].size
    grid = Image.new("RGB", (w * 2, h * 2))
    for i, img in enumerate(imgs):
        x, y = (i % 2) * w, (i // 2) * h
        grid.paste(img, (x, y))
    grid.thumbnail((1600, 1200))
    out = SHOTS / "themes_grid.png"
    grid.save(out, optimize=True, quality=85)
    print(f"OK {out.relative_to(PROJECT_ROOT)} ({grid.size[0]}x{grid.size[1]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

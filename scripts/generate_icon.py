"""Generate a proper Windows .ico file from the source JPEG image.

Produces a multi-resolution ICO (16, 32, 48, 64, 128, 256 px) with PNG
compression — the standard for modern Windows executables.

Usage:
    python scripts/generate_icon.py [--source assets/icon.ico] [--output assets/cinesort.ico]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    from PIL import Image
except ImportError:
    print("[ERREUR] Pillow requis. Installez avec: pip install pillow>=10.0", file=sys.stderr)
    raise SystemExit(1)

ICO_SIZES = [16, 32, 48, 64, 128, 256]


def generate_ico(source: Path, output: Path) -> None:
    """Convert a source image to a proper multi-resolution .ico file."""
    img = Image.open(source)

    if img.mode != "RGBA":
        img = img.convert("RGBA")

    # Crop to square if needed (center crop)
    w, h = img.size
    if w != h:
        side = min(w, h)
        left = (w - side) // 2
        top = (h - side) // 2
        img = img.crop((left, top, left + side, top + side))

    # Generate each size with high-quality resampling
    resized_images = []
    for size in ICO_SIZES:
        resized = img.resize((size, size), Image.LANCZOS)
        resized_images.append(resized)

    output.parent.mkdir(parents=True, exist_ok=True)
    # Pillow ICO save: the main image is ignored for sizing, we must pass
    # all desired sizes explicitly. Save the largest as base, append the rest.
    resized_images[-1].save(
        str(output),
        format="ICO",
        append_images=resized_images[:-1],
    )

    file_size_kb = output.stat().st_size / 1024
    print(f"[OK] ICO genere: {output} ({file_size_kb:.1f} KB, {len(ICO_SIZES)} tailles: {ICO_SIZES})")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Genere un fichier .ico multi-resolution.")
    parser.add_argument("--source", default="assets/icon.ico", help="Image source (JPEG/PNG).")
    parser.add_argument("--output", default="assets/cinesort.ico", help="Fichier .ico de sortie.")
    args = parser.parse_args(argv)

    repo_root = Path(__file__).resolve().parents[1]
    source = repo_root / args.source
    output = repo_root / args.output

    if not source.exists():
        print(f"[ERREUR] Source introuvable: {source}", file=sys.stderr)
        return 1

    generate_ico(source, output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""
Downscale a pixel art sprite by any integer factor using dominant color
per NxN block, then snap to NES palette.

Usage:
    python scripts/downscale_sprite.py input.png output.png [--factor 2] [--no-snap]

Designed for the hybrid pixel-mcp experiment:
  32x32 → 16x16 (factor 2), 48x48 → 16x16 (factor 3), etc.
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

# NES 2C02 palette (54 colors) — same source as src/retrogaze/palette.py
NES_PALETTE_RGB: list[tuple[int, int, int]] = [
    (124, 124, 124), (0, 0, 252), (0, 0, 188), (68, 40, 188),
    (148, 0, 132), (168, 0, 32), (168, 16, 0), (136, 20, 0),
    (80, 48, 0), (0, 120, 0), (0, 104, 0), (0, 88, 0),
    (0, 64, 88), (0, 0, 0), (188, 188, 188), (0, 120, 248),
    (0, 88, 248), (104, 68, 252), (216, 0, 204), (228, 0, 88),
    (248, 56, 0), (228, 92, 16), (172, 124, 0), (0, 184, 0),
    (0, 168, 0), (0, 168, 68), (0, 131, 136), (60, 60, 60),
    (248, 248, 248), (60, 188, 252), (104, 136, 252), (152, 120, 248),
    (248, 120, 248), (248, 88, 152), (248, 120, 88), (252, 160, 68),
    (248, 184, 0), (184, 248, 24), (88, 216, 84), (44, 232, 148),
    (0, 232, 216), (120, 120, 120), (252, 252, 252), (164, 228, 252),
    (184, 184, 248), (216, 184, 248), (248, 184, 248), (248, 164, 192),
    (240, 208, 176), (252, 224, 168), (248, 216, 120), (216, 248, 120),
    (184, 248, 184), (184, 248, 216), (0, 252, 252), (248, 216, 248),
]


def _color_distance_sq(c1: tuple[int, int, int], c2: tuple[int, int, int]) -> int:
    """Weighted Euclidean distance (human eye is more sensitive to green)."""
    dr = c1[0] - c2[0]
    dg = c1[1] - c2[1]
    db = c1[2] - c2[2]
    return 2 * dr * dr + 4 * dg * dg + 3 * db * db


def snap_to_nes(r: int, g: int, b: int) -> tuple[int, int, int]:
    """Find the nearest NES palette color."""
    best = NES_PALETTE_RGB[0]
    best_dist = _color_distance_sq((r, g, b), best)
    for color in NES_PALETTE_RGB[1:]:
        d = _color_distance_sq((r, g, b), color)
        if d < best_dist:
            best = color
            best_dist = d
    return best


def downscale_dominant(img: Image.Image, factor: int = 2, snap: bool = True) -> Image.Image:
    """
    Downscale image by `factor`x using dominant color per NxN block.

    Transparent pixels are preserved — if all pixels in a block are
    transparent, the output pixel is transparent. Otherwise, only opaque
    pixels vote.
    """
    w, h = img.size
    if w % factor != 0 or h % factor != 0:
        raise ValueError(f"Image dimensions must be divisible by {factor}, got {w}x{h}")

    img = img.convert("RGBA")
    pixels = img.load()
    out_w, out_h = w // factor, h // factor
    out = Image.new("RGBA", (out_w, out_h), (0, 0, 0, 0))
    out_pixels = out.load()

    for oy in range(out_h):
        for ox in range(out_w):
            # Gather the NxN block
            block = []
            for dy in range(factor):
                for dx in range(factor):
                    px = pixels[ox * factor + dx, oy * factor + dy]
                    block.append(px)

            # Filter to opaque pixels only (alpha > 128)
            opaque = [(r, g, b) for r, g, b, a in block if a > 128]

            if not opaque:
                # All transparent
                continue

            # Pick dominant color (most common)
            counter = Counter(opaque)
            dominant_rgb = counter.most_common(1)[0][0]

            if snap:
                dominant_rgb = snap_to_nes(*dominant_rgb)

            out_pixels[ox, oy] = (*dominant_rgb, 255)

    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="Downscale pixel art sprite with dominant color")
    parser.add_argument("input", help="Input PNG (e.g., 48x48)")
    parser.add_argument("output", help="Output PNG (e.g., 16x16)")
    parser.add_argument("--factor", type=int, default=0, help="Downscale factor (default: auto-detect from input size / 16)")
    parser.add_argument("--no-snap", action="store_true", help="Skip NES palette snapping")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"Error: {input_path} not found", file=sys.stderr)
        sys.exit(1)

    img = Image.open(input_path)
    factor = args.factor if args.factor > 0 else img.size[0] // 16
    if factor < 1:
        factor = 1
    print(f"Input: {img.size[0]}x{img.size[1]}, factor: {factor}x")

    result = downscale_dominant(img, factor=factor, snap=not args.no_snap)
    print(f"Output: {result.size[0]}x{result.size[1]}")

    result.save(args.output)
    print(f"Saved to {args.output}")


if __name__ == "__main__":
    main()

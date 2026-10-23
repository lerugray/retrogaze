"""
Pixel grid utilities for the hybrid pipeline.

Two main functions:
  - image_to_pixel_grid: Convert a PIL Image to a compact labeled ASCII grid
    that Haiku can read and reproduce in Aseprite.
  - downscale_dominant: Downscale pixel art using dominant-color-per-block
    (preserves hard pixel edges, no blurring).

Output format for image_to_pixel_grid:
    Row 00: . . K K K K . .
    Row 01: . K A A A K . .
    ...
    Legend: K=#000000(outline) A=#787878(armor) .=transparent
"""

from __future__ import annotations

import string
from collections import Counter

from PIL import Image


def image_to_pixel_grid(img: Image.Image) -> str:
    """Convert a PIL Image to a labeled ASCII pixel grid.

    Transparent pixels = "."
    Each unique opaque color gets a single-letter label (A-Z).
    Colors are assigned labels in order of frequency (most common first).

    Returns a compact string with row-by-row grid and a legend.
    """
    img = img.convert("RGBA")
    w, h = img.size
    pixels = img.load()

    # Collect all unique opaque colors and their counts
    color_counts: dict[tuple[int, int, int], int] = {}
    for y in range(h):
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a > 128:
                rgb = (r, g, b)
                color_counts[rgb] = color_counts.get(rgb, 0) + 1

    # Assign labels by frequency (most common = A)
    sorted_colors = sorted(color_counts.items(), key=lambda kv: -kv[1])
    labels = string.ascii_uppercase
    if len(sorted_colors) > len(labels):
        # More than 26 colors — truncate rare ones to nearest labeled color
        sorted_colors = sorted_colors[:len(labels)]

    color_to_label: dict[tuple[int, int, int], str] = {}
    for i, (rgb, _count) in enumerate(sorted_colors):
        color_to_label[rgb] = labels[i]

    # Build grid rows
    rows: list[str] = []
    for y in range(h):
        cells: list[str] = []
        for x in range(w):
            r, g, b, a = pixels[x, y]
            if a <= 128:
                cells.append(".")
            else:
                rgb = (r, g, b)
                label = color_to_label.get(rgb, "?")
                cells.append(label)
        rows.append(f"Row {y:02d}: {' '.join(cells)}")

    # Build legend
    legend_parts: list[str] = []
    for rgb, label in sorted(color_to_label.items(), key=lambda kv: kv[1]):
        hex_color = f"#{rgb[0]:02X}{rgb[1]:02X}{rgb[2]:02X}"
        legend_parts.append(f"{label}={hex_color}")
    legend_parts.append(".=transparent")

    legend = "Legend: " + " ".join(legend_parts)

    return "\n".join(rows) + "\n" + legend


# ---------------------------------------------------------------------------
# Dominant-color downscale
# ---------------------------------------------------------------------------

def downscale_dominant(
    img: Image.Image,
    target_size: tuple[int, int] = (16, 16),
) -> Image.Image:
    """Downscale pixel art to target_size using dominant color per block.

    Automatically computes the integer scale factor from the image dimensions
    and target size. If the image is already at target size, returns a copy.

    Transparent pixels are preserved — if all pixels in a block are
    transparent, the output pixel is transparent. Otherwise, only opaque
    pixels vote for the dominant color.
    """
    img = img.convert("RGBA")
    w, h = img.size
    tw, th = target_size

    if (w, h) == (tw, th):
        return img.copy()

    factor_x = w // tw
    factor_y = h // th
    factor = min(factor_x, factor_y)

    if factor < 1:
        factor = 1

    # If dimensions aren't evenly divisible, crop to nearest multiple
    crop_w = tw * factor
    crop_h = th * factor
    if (crop_w, crop_h) != (w, h):
        img = img.crop((0, 0, crop_w, crop_h))

    pixels = img.load()
    out = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    out_pixels = out.load()

    for oy in range(th):
        for ox in range(tw):
            block: list[tuple[int, int, int]] = []
            for dy in range(factor):
                for dx in range(factor):
                    r, g, b, a = pixels[ox * factor + dx, oy * factor + dy]
                    if a > 128:
                        block.append((r, g, b))

            if not block:
                continue

            dominant_rgb = Counter(block).most_common(1)[0][0]
            out_pixels[ox, oy] = (*dominant_rgb, 255)

    return out

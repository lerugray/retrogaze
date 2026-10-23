"""
Extract dominant colors from a screenshot and snap them to console-valid palettes.

Workflow: user uploads a screenshot from a game they like → we extract the dominant
colors → snap each to the nearest valid color for their target console → return hex
strings ready to feed into the palette_colors generation parameter.
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from retrogaze.palette import rgb_to_lab
from retrogaze.console_profile import get_profile


def extract_dominant_colors(
    image: Image.Image,
    n: int = 4,
) -> list[tuple[int, int, int]]:
    """Extract *n* dominant colors from an image using PIL's median-cut quantization."""
    img = image.convert("RGB")
    # Downsample large images for speed
    if img.width * img.height > 160_000:
        img.thumbnail((400, 400), Image.NEAREST)
    quantized = img.quantize(colors=n, method=Image.Quantize.MEDIANCUT).convert("P")
    palette_data = quantized.getpalette() or []
    color_counts = quantized.getcolors(maxcolors=256) or []
    color_counts.sort(key=lambda item: item[0], reverse=True)

    colors = []
    for _, palette_idx in color_counts[:n]:
        i = int(palette_idx) * 3
        if i + 2 >= len(palette_data):
            continue
        r, g, b = palette_data[i:i + 3]
        colors.append((r, g, b))
    return colors


def snap_to_console_palette(
    colors: list[tuple[int, int, int]],
    console: str = "nes",
) -> list[str]:
    """Snap a list of RGB colors to the nearest valid colors for a console.

    For fixed-palette consoles (NES, GB, C64): matches against master palette.
    For free-color consoles (SNES, Genesis, GBC, PCE): quantizes to bit depth.

    Returns deduplicated hex strings.
    """
    profile = get_profile(console)
    master = profile.master_palette_rgb()

    if master is not None:
        # Fixed palette — find nearest in Lab space
        master_lab = np.array(
            [rgb_to_lab(r, g, b) for r, g, b in master],
            dtype=np.float64,
        )
        master_arr = np.array(master, dtype=np.uint8)
        snapped = []
        for r, g, b in colors:
            lab = np.array(rgb_to_lab(r, g, b), dtype=np.float64)
            diffs = master_lab - lab
            distances = np.einsum("ij,ij->i", diffs, diffs)
            idx = int(np.argmin(distances))
            snapped.append(tuple(master_arr[idx]))
    else:
        # Free-color console — quantize to bit depth
        if profile.color_depth_bits is None:
            raise ValueError(
                f"Console profile '{profile.name}' is free-color but missing color_depth_bits"
            )
        bits_per_channel = profile.color_depth_bits // 3
        levels = (1 << bits_per_channel) - 1
        snapped = []
        for r, g, b in colors:
            qr = round(r / 255 * levels) * 255 // levels
            qg = round(g / 255 * levels) * 255 // levels
            qb = round(b / 255 * levels) * 255 // levels
            snapped.append((qr, qg, qb))

    # Deduplicate while preserving order
    seen: set[tuple[int, int, int]] = set()
    unique = []
    for c in snapped:
        if c not in seen:
            seen.add(c)
            unique.append(c)

    return [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in unique]


def extract_palette_from_screenshot(
    image: Image.Image,
    n: int = 4,
    console: str = "nes",
) -> list[str]:
    """Extract dominant colors from a screenshot and snap to console palette.

    Returns a list of hex color strings ready for the palette_colors parameter.
    """
    dominant = extract_dominant_colors(image, n=n)
    return snap_to_console_palette(dominant, console=console)

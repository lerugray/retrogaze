"""
Grid alignment utilities for NES pixel art.

NES tile boundaries are on 8-pixel intervals; all images must have dimensions
that are exact multiples of 8.
"""

from __future__ import annotations

import math
from PIL import Image


def _round_up_to_multiple(value: int, multiple: int) -> int:
    """Round *value* up to the nearest multiple of *multiple*."""
    return math.ceil(value / multiple) * multiple


def align_to_grid(
    image: Image.Image,
    target_width: int | None = None,
    target_height: int | None = None,
    tile_size: int = 8,
) -> Image.Image:
    """
    Ensure *image* dimensions are multiples of tile_size.

    If *target_width* / *target_height* are provided the image is resized
    (nearest-neighbor) to those exact dimensions, which must themselves be
    multiples of tile_size. If no targets are given the image is padded with
    transparent pixels to the next tile boundary — no pixel data
    is lost.

    Returns a new RGBA PIL Image.
    """
    img = image.convert("RGBA")
    if tile_size <= 0:
        raise ValueError("tile_size must be a positive integer")

    if target_width is not None or target_height is not None:
        tw = target_width if target_width is not None else img.width
        th = target_height if target_height is not None else img.height
        if tw % tile_size != 0:
            raise ValueError(f"target_width {tw} is not a multiple of {tile_size}")
        if th % tile_size != 0:
            raise ValueError(f"target_height {th} is not a multiple of {tile_size}")
        return img.resize((tw, th), resample=Image.NEAREST)

    # Pad to next multiple of tile_size
    new_w = _round_up_to_multiple(img.width, tile_size)
    new_h = _round_up_to_multiple(img.height, tile_size)

    if new_w == img.width and new_h == img.height:
        return img.copy()

    canvas = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
    canvas.paste(img, (0, 0))
    return canvas

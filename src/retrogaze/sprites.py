"""
Sprite size conformance utilities for NES pixel art.

NES sprites come in 8×8 and 8×16 hardware sizes; metasprites (game objects
composed of multiple hardware sprites) use multiples of those dimensions.
"""

from __future__ import annotations

from PIL import Image

# Supported NES (meta)sprite sizes
VALID_SPRITE_SIZES: set[tuple[int, int]] = {
    (8, 8),
    (8, 16),
    (16, 16),
    (16, 24),
    (16, 32),
}


def conform_sprite_size(
    image: Image.Image, target_size: tuple[int, int]
) -> Image.Image:
    """
    Resize or crop/pad *image* to *target_size* (width, height).

    Content is centered when the canvas grows or shrinks:
    - If the source is larger in any dimension it is cropped (centered).
    - If the source is smaller in any dimension it is padded with transparent
      pixels (centered).
    - If the source is the wrong aspect ratio both operations may occur on
      different axes simultaneously.

    *target_size* must be one of :data:`VALID_SPRITE_SIZES`.
    Nearest-neighbor interpolation is used throughout.

    Returns a new RGBA PIL Image.
    """
    if target_size not in VALID_SPRITE_SIZES:
        raise ValueError(
            f"target_size {target_size} is not a valid NES sprite size. "
            f"Choose one of: {sorted(VALID_SPRITE_SIZES)}"
        )

    img = image.convert("RGBA")
    tw, th = target_size
    sw, sh = img.size

    if (sw, sh) == (tw, th):
        return img.copy()

    # Compute the source crop box (centered)
    crop_w = min(sw, tw)
    crop_h = min(sh, th)
    src_x = (sw - crop_w) // 2
    src_y = (sh - crop_h) // 2
    cropped = img.crop((src_x, src_y, src_x + crop_w, src_y + crop_h))

    # Place on target canvas (centered)
    canvas = Image.new("RGBA", (tw, th), (0, 0, 0, 0))
    dst_x = (tw - crop_w) // 2
    dst_y = (th - crop_h) // 2
    canvas.paste(cropped, (dst_x, dst_y))
    return canvas


def detect_metasprite_grid(image: Image.Image) -> dict:
    """
    Return the tile grid layout for a sprite image.

    Given an RGBA image whose dimensions are multiples of 8, return a dict
    describing how many 8×8 hardware tiles compose it:

    .. code-block:: python

        {
            "tile_cols": 2,
            "tile_rows": 2,
            "total_tiles": 4,
            "tile_size_px": (8, 8),
            "image_size_px": (16, 16),
        }

    Raises ``ValueError`` if dimensions are not multiples of 8.
    """
    img = image.convert("RGBA")
    w, h = img.size
    if w % 8 != 0 or h % 8 != 0:
        raise ValueError(
            f"Image dimensions ({w}×{h}) must be multiples of 8."
        )
    tile_cols = w // 8
    tile_rows = h // 8
    return {
        "tile_cols": tile_cols,
        "tile_rows": tile_rows,
        "total_tiles": tile_cols * tile_rows,
        "tile_size_px": (8, 8),
        "image_size_px": (w, h),
    }

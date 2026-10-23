"""
Metadata generation for Retrogaze-processed assets.

Produces JSON-serializable dicts describing the asset's compliance status,
palette, and tile layout. Console-aware: validates against the target console's
palette rather than hardcoding NES.
"""

from __future__ import annotations

from PIL import Image

from .console_profile import ConsoleProfile, NES, get_profile
from .palette import find_nearest_nes_color, get_nes_palette_index, NES_PALETTE_RGB, _NES_PALETTE_HEX, rgb_to_lab
from .tiles import validate_tile_colors, validate_attribute_table
from .sprites import detect_metasprite_grid
from .grid import align_to_grid

__version__ = "0.1.0"


def _collect_palette_info(
    image: Image.Image,
    profile: ConsoleProfile | None = None,
) -> dict:
    """Extract palette info for all unique opaque colors in *image*.

    For NES or when no profile is given, returns NES palette indices.
    For other consoles, returns the actual hex colors in the image.
    """
    import numpy as np
    arr = np.array(image.convert("RGBA"), dtype=np.uint8)
    opaque = arr[arr[:, :, 3] > 0][:, :3]
    if opaque.size == 0:
        return {"hex": []}

    unique = np.unique(opaque.reshape(-1, 3), axis=0)
    hex_colors = [f"#{int(c[0]):02X}{int(c[1]):02X}{int(c[2]):02X}" for c in unique]

    result: dict = {"hex": hex_colors}

    # Add NES-specific PPU register indices when applicable
    if profile is None or profile.name == "nes":
        nes_indices = []
        seen: set[int] = set()
        for rgb in unique:
            r, g, b = int(rgb[0]), int(rgb[1]), int(rgb[2])
            _, _, _, idx = find_nearest_nes_color(r, g, b)
            if idx not in seen:
                seen.add(idx)
                nes_indices.append(get_nes_palette_index(r, g, b))
        result["nes_indices"] = nes_indices

    return result


def _build_tile_list(image: Image.Image) -> list[dict]:
    """Build a flat list of tile descriptors for all 8×8 tiles in *image*."""
    w, h = image.size
    tile_cols = w // 8
    tile_rows = h // 8
    tiles = []
    tile_id = 0
    for row in range(tile_rows):
        for col in range(tile_cols):
            tiles.append({
                "id": tile_id,
                "x": col * 8,
                "y": row * 8,
                "flip_h": False,
                "flip_v": False,
            })
            tile_id += 1
    return tiles


def _check_palette_valid(
    image: Image.Image,
    profile: ConsoleProfile,
) -> bool:
    """Check if every opaque pixel in *image* is valid for *profile*.

    For fixed-palette consoles: every pixel must be an exact palette color.
    For free-color consoles: every channel value must be valid at the bit depth.
    """
    import numpy as np
    arr = np.array(image.convert("RGBA"), dtype=np.uint8)
    opaque_mask = arr[:, :, 3] > 0
    opaque_rgb = arr[opaque_mask][:, :3]
    if opaque_rgb.size == 0:
        return True

    unique = np.unique(opaque_rgb.reshape(-1, 3), axis=0)

    master_rgb = profile.master_palette_rgb()
    if master_rgb is not None:
        # Fixed palette: every pixel must be an exact match
        palette_set = set(master_rgb)
        return all(tuple(int(c) for c in row) in palette_set for row in unique)

    if profile.color_depth_bits is not None:
        # Free color: each channel must be a valid quantized value
        bits = {9: 3, 15: 5}.get(profile.color_depth_bits)
        if bits is None:
            return True
        shift = 8 - bits
        max_val = (1 << bits) - 1
        for row in unique:
            for ch in row:
                ch = int(ch)
                quantized = (ch >> shift)
                expanded = (quantized * 255) // max_val
                if expanded != ch:
                    return False
        return True

    return True


def generate_metadata(
    image: Image.Image,
    asset_type: str,
    prompt: str | None = None,
    console: str | ConsoleProfile | None = None,
) -> dict:
    """
    Produce a JSON-serializable metadata dict for a Retrogaze-processed asset.

    Parameters
    ----------
    image:
        The processed RGBA PIL image.
    asset_type:
        Human-readable label, e.g. ``"sprite"``, ``"metasprite"``,
        ``"background"``.
    prompt:
        Optional original generation prompt describing the asset.
    console:
        Console profile name or instance. Defaults to NES.

    Returns
    -------
    dict
        JSON-serializable compliance/metadata structure.
    """
    # Resolve profile
    if console is None:
        profile = NES
    elif isinstance(console, str):
        profile = get_profile(console)
    else:
        profile = console

    img = image.convert("RGBA")
    w, h = img.size

    # Grid info
    grid_aligned = (w % 8 == 0 and h % 8 == 0)
    tile_grid_info = detect_metasprite_grid(img) if grid_aligned else None
    tile_cols = tile_grid_info["tile_cols"] if tile_grid_info else None
    tile_rows = tile_grid_info["tile_rows"] if tile_grid_info else None

    # Palette info
    palette_info = _collect_palette_info(img, profile=profile)

    # Console-aware palette validity
    palette_valid = _check_palette_valid(img, profile)

    # Tile color compliance
    colors_per_tile_valid = True
    if grid_aligned:
        report = validate_tile_colors(img, max_colors=profile.max_colors_per_tile)
        colors_per_tile_valid = report.all_valid

    # Attribute table compliance (16x16 blocks)
    attribute_table_valid = True
    if profile.has_attribute_table and grid_aligned and w % 16 == 0 and h % 16 == 0:
        attr_report = validate_attribute_table(img)
        attribute_table_valid = attr_report["all_valid"]

    # Tile list
    tile_list = _build_tile_list(img) if grid_aligned else []

    # Palette slots: colors_per_palette - 1 usable (one slot is bg/transparent)
    import math
    usable_per_slot = max(1, profile.colors_per_palette - 1)
    unique_opaque_count = len(palette_info.get("hex", []))
    palette_slots_required = max(1, math.ceil(unique_opaque_count / usable_per_slot))

    return {
        "retrogaze_version": __version__,
        "asset_type": asset_type,
        "prompt": prompt,
        "dimensions": {
            "width_px": w,
            "height_px": h,
            "tile_grid": [tile_cols, tile_rows] if tile_grid_info else None,
        },
        "palette": palette_info,
        "tiles": tile_list,
        "compliance": {
            "palette_valid": palette_valid,
            "colors_per_tile_valid": colors_per_tile_valid,
            "attribute_table_valid": attribute_table_valid,
            "grid_aligned": grid_aligned,
            "palette_slots_required": palette_slots_required,
        },
    }

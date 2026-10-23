"""
Main constraint-enforcement pipeline for Retrogaze.

Runs compliance steps in order, parameterized by ConsoleProfile:
  1. Grid alignment
  2. Palette remapping (console-specific)
  3. Attribute table enforcement (NES only)
  4. Per-tile color reduction
  5. Metadata generation
  6. Optional file output

Default profile is NES (backward-compatible).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from PIL import Image

from .console_profile import ConsoleProfile, NES, get_profile
from .grid import align_to_grid
from .palette import remap_to_nes_palette, remap_to_palette, quantize_to_bit_depth
from .tiles import validate_tile_colors, reduce_tile_colors, validate_attribute_table, reduce_attribute_block_colors, enforce_global_colors
from .metadata import generate_metadata


def enforce_constraints(
    image_path: str | os.PathLike,
    target_size: tuple[int, int] | None = None,
    asset_type: str = "sprite",
    output_path: str | os.PathLike | None = None,
    prompt: str | None = None,
    max_colors_per_tile: int | None = None,
    console: str | ConsoleProfile | None = None,
) -> dict:
    """
    Run the constraint-enforcement pipeline on *image_path*.

    Steps
    -----
    1. Load image as RGBA.
    2. Grid-align to multiples of tile_size.
    3. Remap every pixel to the console's palette.
    4. (NES only) Enforce attribute table 16x16 block constraint.
    5. Reduce any tile that exceeds *max_colors_per_tile* unique colors.
    6. Generate compliance metadata.
    7. If *output_path* is set, save the processed PNG and metadata JSON.

    Parameters
    ----------
    image_path:
        Path to the source image (any PIL-supported format).
    target_size:
        Optional ``(width, height)`` in pixels; both must be multiples of 8.
    asset_type:
        Label for the asset (e.g. ``"sprite"``, ``"background"``).
    output_path:
        Optional path for the processed PNG output.
    prompt:
        Optional text prompt that was used to generate the asset.
    max_colors_per_tile:
        Maximum unique opaque colors allowed per tile. Defaults to the
        console profile's hardware limit.
    console:
        Console profile name (e.g. "nes", "gb_dmg") or ConsoleProfile
        instance. Defaults to NES for backward compatibility.

    Returns
    -------
    dict
        The compliance/metadata report.
    """
    # Resolve console profile
    if console is None:
        profile = NES
    elif isinstance(console, str):
        profile = get_profile(console)
    else:
        profile = console

    # 1. Load
    src = Image.open(image_path).convert("RGBA")

    # 2. Grid alignment
    if target_size is not None:
        tw, th = target_size
        img = align_to_grid(src, target_width=tw, target_height=th, tile_size=profile.tile_size)
    else:
        img = align_to_grid(src, tile_size=profile.tile_size)

    # 3. Palette remapping / quantization
    # Console-specific dithering during palette remap
    _DITHER_MAP: dict[str, str | bool] = {
        "nes": False,          # NES uses its own remap_to_nes_palette path
        "c64": True,           # Floyd-Steinberg — fixed 16 colors need blending
        "c64_hires": True,
        "commodore_64": True,
        # Genesis/Mega Drive: free-color (no master palette), takes quantize_to_bit_depth
        # path below — dither map entries would be dead code here.
    }
    dither_mode = _DITHER_MAP.get(profile.name, False)
    palette_rgb = profile.master_palette_rgb()
    if palette_rgb is not None:
        # Fixed-palette consoles: remap to nearest color (with console-specific dithering)
        if profile.name == "nes":
            img = remap_to_nes_palette(img)
        else:
            img = remap_to_palette(img, palette_rgb, dither=dither_mode)
    elif profile.color_depth_bits is not None:
        # Free-color consoles: quantize to bit depth
        bits_per_channel = {9: 3, 15: 5}.get(profile.color_depth_bits)
        if bits_per_channel:
            img = quantize_to_bit_depth(img, bits_per_channel)

    # 3b. Attribute table enforcement (NES-specific: 16x16 blocks share one palette)
    if profile.has_attribute_table:
        w, h = img.size
        block = profile.attribute_block_size or 16
        if w % block == 0 and h % block == 0:
            attr_report = validate_attribute_table(img)
            if not attr_report["all_valid"]:
                img = reduce_attribute_block_colors(img, max_colors=profile.colors_per_palette)

    # 3c. Global + per-cell color enforcement (C64 multicolor, etc.)
    if profile.pixel_width > 1 and palette_rgb is not None:
        n_global = profile.max_colors_per_tile - 1  # 3 for C64 multicolor (4 - 1 per-cell)
        cell_w = profile.tile_size  # 4 for C64 multicolor
        cell_h = 8
        img = enforce_global_colors(
            img, palette_rgb, n_global=n_global,
            cell_width=cell_w, cell_height=cell_h,
        )

    # 4. Per-tile color reduction
    # The profile is the default source of truth. Explicit overrides remain
    # bounded by the hardware limit.
    effective_max_colors = profile.max_colors_per_tile
    if max_colors_per_tile is not None:
        effective_max_colors = min(max_colors_per_tile, profile.max_colors_per_tile)
    report_before = validate_tile_colors(
        img, max_colors=effective_max_colors, tile_size=profile.tile_size
    )
    if not report_before.all_valid:
        img = reduce_tile_colors(
            img, max_colors=effective_max_colors, tile_size=profile.tile_size
        )

    # 4b. Palette allocation (free-color consoles with per-tile palette assignment)
    alloc_report = None
    if (profile.palette_assignment == "per_tile"
            and profile.master_palette_hex is None
            and profile.color_depth_bits is not None):
        from .palette_alloc import allocate_palettes
        img, alloc_report = allocate_palettes(
            img,
            num_palettes=profile.bg_palettes,
            colors_per_palette=profile.colors_per_palette,
            tile_size=profile.tile_size,
        )

    # 5. Generate metadata
    metadata = generate_metadata(img, asset_type=asset_type, prompt=prompt, console=profile)
    metadata["console"] = profile.name
    metadata["console_display_name"] = profile.display_name
    if alloc_report:
        metadata["palette_allocation"] = {
            "num_palettes_used": alloc_report.get("num_palettes_used", 0),
            "total_unique_colors": alloc_report.get("total_unique_colors", 0),
            "colors_merged": alloc_report.get("colors_merged", 0),
        }

    # 6. Optional output
    if output_path is not None:
        out = Path(output_path)
        img.save(str(out), format="PNG")

        meta_path = out.with_suffix(".json")
        with open(meta_path, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)

    return metadata

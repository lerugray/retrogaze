"""
Palette allocation for free-color consoles (Genesis, SNES, GBC, PC-Engine).

Given a quantized image, partition its colors into N palettes of K colors
each, assign each tile to one palette, and remap any out-of-palette pixels
to the nearest in-palette color.

This solves the constraint: each 8x8 tile must use colors from exactly
one of the console's hardware palettes. The algorithm:
  1. Collect unique colors per tile
  2. Merge globally if total unique > max capacity
  3. Cluster tiles by color affinity into palette groups
  4. Build each palette from its group's color union
  5. Assign each tile to its best palette
  6. Remap outlier pixels
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .palette import rgb_to_lab


def allocate_palettes(
    image: Image.Image,
    num_palettes: int = 4,
    colors_per_palette: int = 16,
    tile_size: int = 8,
) -> tuple[Image.Image, dict]:
    """
    Partition image colors into hardware palettes and remap tiles.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image, should already be quantized to the target bit depth.
    num_palettes : int
        Number of available palettes (4 for Genesis, 8 for SNES/GBC).
    colors_per_palette : int
        Colors per palette (16 for Genesis/SNES, 4 for GBC).
    tile_size : int
        Tile grid size (8 for most consoles).

    Returns
    -------
    (remapped_image, report)
        remapped_image: PIL Image with all pixels remapped to assigned palettes.
        report: dict with palette definitions, tile assignments, stats.
    """
    if not isinstance(num_palettes, int) or num_palettes <= 0:
        raise ValueError("num_palettes must be a positive integer")
    if not isinstance(colors_per_palette, int) or colors_per_palette <= 0:
        raise ValueError("colors_per_palette must be a positive integer")
    if not isinstance(tile_size, int) or tile_size <= 0:
        raise ValueError("tile_size must be a positive integer")

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    h, w = arr.shape[:2]
    orig_h, orig_w = h, w

    if w % tile_size != 0 or h % tile_size != 0:
        # Pad to full tile coverage so edge pixels are included in allocation.
        pad_w = ((w + tile_size - 1) // tile_size) * tile_size
        pad_h = ((h + tile_size - 1) // tile_size) * tile_size
        padded = np.zeros((pad_h, pad_w, 4), dtype=np.uint8)
        padded[:h, :w] = arr
        arr = padded
        h, w = arr.shape[:2]

    tile_cols = w // tile_size
    tile_rows = h // tile_size
    max_total = num_palettes * colors_per_palette

    # --- Step 1: Collect unique colors per tile ---
    tile_colors: list[set[tuple[int, int, int]]] = []
    for row in range(tile_rows):
        for col in range(tile_cols):
            tx = col * tile_size
            ty = row * tile_size
            tile = arr[ty:ty + tile_size, tx:tx + tile_size]
            opaque = tile[:, :, 3] > 0
            if opaque.any():
                pixels = tile[opaque][:, :3]
                unique = {tuple(c) for c in np.unique(pixels.reshape(-1, 3), axis=0).tolist()}
            else:
                unique = set()
            tile_colors.append(unique)

    # Collect all unique colors globally
    all_colors = set()
    for tc in tile_colors:
        all_colors |= tc

    n_unique = len(all_colors)

    # --- Step 2: Trivial case — fits in one palette ---
    if n_unique <= colors_per_palette:
        palette = sorted(all_colors)
        assignments = [0] * len(tile_colors)
        result_img = _remap_tiles(arr, [palette], assignments, tile_size)
        if result_img.size != (orig_w, orig_h):
            result_img = result_img.crop((0, 0, orig_w, orig_h))
        return result_img, {
            "palettes": [palette],
            "tile_assignments": assignments,
            "colors_merged": 0,
            "total_unique_colors": n_unique,
        }

    # --- Step 3: Merge colors if > max capacity ---
    colors_merged = 0
    if n_unique > max_total:
        all_colors, merge_map = _merge_colors(all_colors, max_total)
        colors_merged = n_unique - len(all_colors)
        # Apply merge map to tile colors and image
        arr = _apply_merge_map(arr, merge_map)
        tile_colors = [
            {merge_map.get(c, c) for c in tc}
            for tc in tile_colors
        ]
        n_unique = len(all_colors)

    # --- Step 4: Cluster tiles into palette groups ---
    # Strategy: greedy bin-packing by color affinity
    palettes, assignments = _cluster_tiles(
        tile_colors, num_palettes, colors_per_palette, all_colors,
    )

    # --- Step 5: Remap pixels to assigned palettes ---
    result_img = _remap_tiles(arr, palettes, assignments, tile_size)
    if result_img.size != (orig_w, orig_h):
        result_img = result_img.crop((0, 0, orig_w, orig_h))

    return result_img, {
        "palettes": [sorted(p) for p in palettes],
        "tile_assignments": assignments,
        "colors_merged": colors_merged,
        "total_unique_colors": n_unique,
        "num_palettes_used": len([p for p in palettes if p]),
    }


def _merge_colors(
    colors: set[tuple[int, int, int]], target_count: int,
) -> tuple[set[tuple[int, int, int]], dict[tuple[int, int, int], tuple[int, int, int]]]:
    """
    Reduce a color set to target_count by merging nearest pairs in Lab space.

    Returns (reduced_set, merge_map) where merge_map maps old→new colors.
    """
    color_list = sorted(colors)
    # Pre-compute Lab values
    lab_values = {c: rgb_to_lab(*c) for c in color_list}
    merge_map: dict[tuple[int, int, int], tuple[int, int, int]] = {}

    while len(color_list) > target_count:
        # Find the two nearest colors
        min_dist = float("inf")
        merge_a, merge_b = 0, 1
        n = len(color_list)

        # For efficiency, use numpy for distance computation
        labs = np.array([lab_values[c] for c in color_list], dtype=np.float64)
        for i in range(n):
            diffs = labs[i + 1:] - labs[i]
            dists = np.einsum("ij,ij->i", diffs, diffs)
            if len(dists) > 0:
                j_local = int(np.argmin(dists))
                if dists[j_local] < min_dist:
                    min_dist = dists[j_local]
                    merge_a, merge_b = i, i + 1 + j_local

        # Merge b into a (keep a, remove b)
        kept = color_list[merge_a]
        removed = color_list[merge_b]
        merge_map[removed] = kept
        # Also update any prior merges that pointed to removed
        for k, v in merge_map.items():
            if v == removed:
                merge_map[k] = kept
        del lab_values[removed]
        color_list.pop(merge_b)

    return set(color_list), merge_map


def _apply_merge_map(
    arr: np.ndarray,
    merge_map: dict[tuple[int, int, int], tuple[int, int, int]],
) -> np.ndarray:
    """Apply color merge map to image array."""
    for old_c, new_c in merge_map.items():
        mask = (
            (arr[:, :, 0] == old_c[0]) &
            (arr[:, :, 1] == old_c[1]) &
            (arr[:, :, 2] == old_c[2]) &
            (arr[:, :, 3] > 0)
        )
        arr[mask, 0] = new_c[0]
        arr[mask, 1] = new_c[1]
        arr[mask, 2] = new_c[2]
    return arr


def _cluster_tiles(
    tile_colors: list[set[tuple[int, int, int]]],
    num_palettes: int,
    colors_per_palette: int,
    all_colors: set[tuple[int, int, int]],
) -> tuple[list[list[tuple[int, int, int]]], list[int]]:
    """
    Greedy bin-packing: assign tiles to palettes by color affinity.

    For each tile, assign it to the palette that already shares the most
    colors with it. If no palette can fit the tile's new colors, assign
    to the palette that requires the fewest remappings.

    Pre-processing (adapted from SuperFamiconv, MIT license):
      - Deduplicate identical color sets so the packer processes fewer items
      - Remove subset color sets — if tile A's colors are a subset of tile B's,
        tile A will always fit wherever tile B fits, so it doesn't constrain
        the packing. Processing it just wastes cycles and can produce worse
        assignments by occupying a palette slot early.
    """
    # --- Pre-processing: identify subset tiles ---
    # Tiles whose color sets are strict subsets of another tile's colors
    # are guaranteed to fit wherever their superset fits. Process them
    # last so the constraining tiles drive palette assignment.
    # (Adapted from SuperFamiconv's filter_subsets, MIT license.)
    frozen = [frozenset(tc) for tc in tile_colors]
    all_nonempty = [fs for fs in frozen if fs]
    is_subset = [
        bool(fs) and any(fs < other for other in all_nonempty)
        for fs in frozen
    ]

    # Sort: non-subset tiles first (most constrained), then subsets
    indexed = list(enumerate(tile_colors))
    indexed.sort(key=lambda x: (is_subset[x[0]], -len(x[1])))

    palette_sets: list[set[tuple[int, int, int]]] = [set() for _ in range(num_palettes)]
    assignments = [-1] * len(tile_colors)

    for tile_idx, tc in indexed:
        if not tc:
            assignments[tile_idx] = 0
            continue

        best_pal = -1
        best_score = -1

        for p in range(num_palettes):
            # How many of this tile's colors are already in palette p?
            overlap = len(tc & palette_sets[p])
            new_colors = tc - palette_sets[p]
            room = colors_per_palette - len(palette_sets[p])

            if len(new_colors) <= room:
                # Tile fits — score by overlap (prefer palettes that share colors)
                score = overlap * 1000 + room  # prefer high overlap, then more room
                if score > best_score:
                    best_score = score
                    best_pal = p

        if best_pal == -1:
            # No palette has room — assign to palette with most overlap
            # (some colors will need remapping)
            for p in range(num_palettes):
                overlap = len(tc & palette_sets[p])
                if overlap > best_score:
                    best_score = overlap
                    best_pal = p
            if best_pal == -1:
                best_pal = 0

        # Assign tile to palette
        assignments[tile_idx] = best_pal
        new_colors = tc - palette_sets[best_pal]
        room = colors_per_palette - len(palette_sets[best_pal])

        if len(new_colors) <= room:
            palette_sets[best_pal] |= new_colors
        else:
            # Add as many as we can (most frequent in the tile — but we
            # don't have frequency data here, so add arbitrary subset)
            for c in sorted(new_colors):
                if len(palette_sets[best_pal]) < colors_per_palette:
                    palette_sets[best_pal].add(c)
                else:
                    break

    palettes = [sorted(ps) for ps in palette_sets]
    return palettes, assignments


def _remap_tiles(
    arr: np.ndarray,
    palettes: list[list[tuple[int, int, int]]],
    assignments: list[int],
    tile_size: int,
) -> Image.Image:
    """Remap each tile's pixels to only use its assigned palette's colors."""
    h, w = arr.shape[:2]
    tile_cols = w // tile_size
    out = arr.copy()

    for tile_idx, pal_idx in enumerate(assignments):
        row = tile_idx // tile_cols
        col = tile_idx % tile_cols
        tx = col * tile_size
        ty = row * tile_size
        tile = out[ty:ty + tile_size, tx:tx + tile_size]

        palette = palettes[pal_idx]
        if not palette:
            continue

        pal_set = set(palette)
        pal_arr = np.array(palette, dtype=np.uint8)

        # Pre-compute Lab for palette
        pal_lab = np.array(
            [rgb_to_lab(*c) for c in palette], dtype=np.float64,
        )

        # Check each pixel
        for y in range(tile_size):
            for x in range(tile_size):
                if tile[y, x, 3] == 0:
                    continue
                px = tuple(tile[y, x, :3].tolist())
                if px in pal_set:
                    continue
                # Remap to nearest palette color
                px_lab = np.array(rgb_to_lab(*px), dtype=np.float64)
                diffs = pal_lab - px_lab
                dists = np.einsum("ij,ij->i", diffs, diffs)
                nearest = pal_arr[int(np.argmin(dists))]
                out[ty + y, tx + x, :3] = nearest

    return Image.fromarray(out, mode="RGBA")

"""
Per-tile color validation and reduction for NES pixel art.

The NES hardware enforces a maximum of 4 colors per 8x8 tile (one of which is
typically the background/transparent color).  This module checks compliance and
auto-reduces violating tiles.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from PIL import Image
import numpy as np

from .palette import find_nearest_nes_color


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class TileReport:
    """Color usage report for a single 8x8 tile."""
    tile_id: int
    x: int          # pixel x of tile top-left
    y: int          # pixel y of tile top-left
    colors: list[tuple[int, int, int]]   # unique opaque colors present
    violates: bool  # True if len(colors) > max_colors


@dataclass
class ValidationReport:
    """Full tile-color validation report for an image."""
    image_width: int
    image_height: int
    tile_cols: int
    tile_rows: int
    max_colors: int
    tiles: list[TileReport] = field(default_factory=list)

    @property
    def all_valid(self) -> bool:
        return all(not t.violates for t in self.tiles)

    @property
    def violating_tiles(self) -> list[TileReport]:
        return [t for t in self.tiles if t.violates]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _tile_unique_colors(
    arr: np.ndarray, tx: int, ty: int, tile_size: int = 8
) -> list[tuple[int, int, int]]:
    """Return list of unique opaque RGB colors in the 8x8 tile at (tx, ty)."""
    tile = arr[ty:ty + tile_size, tx:tx + tile_size]
    opaque_mask = tile[:, :, 3] > 0           # ignore fully-transparent pixels
    opaque_pixels = tile[opaque_mask][:, :3]  # (N, 3) RGB
    if opaque_pixels.size == 0:
        return []
    unique = np.unique(opaque_pixels.reshape(-1, 3), axis=0)
    return [tuple(c) for c in unique]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_tile_colors(
    image: Image.Image, max_colors: int = 4, tile_size: int = 8
) -> ValidationReport:
    """
    Check that each tile uses at most *max_colors* unique opaque colors.

    Returns a :class:`ValidationReport` with per-tile details.
    The image must have dimensions that are multiples of tile_size.
    """
    img = image.convert("RGBA")
    w, h = img.size
    if tile_size <= 0:
        raise ValueError("tile_size must be a positive integer")
    if w % tile_size != 0 or h % tile_size != 0:
        raise ValueError(
            f"Image dimensions ({w}×{h}) must be multiples of {tile_size}. "
            "Run align_to_grid() first."
        )
    arr = np.array(img, dtype=np.uint8)
    tile_cols = w // tile_size
    tile_rows = h // tile_size

    report = ValidationReport(
        image_width=w,
        image_height=h,
        tile_cols=tile_cols,
        tile_rows=tile_rows,
        max_colors=max_colors,
    )

    tile_id = 0
    for row in range(tile_rows):
        for col in range(tile_cols):
            tx = col * tile_size
            ty = row * tile_size
            colors = _tile_unique_colors(arr, tx, ty, tile_size=tile_size)
            report.tiles.append(TileReport(
                tile_id=tile_id,
                x=tx,
                y=ty,
                colors=colors,
                violates=len(colors) > max_colors,
            ))
            tile_id += 1

    return report


def reduce_tile_colors(
    image: Image.Image, max_colors: int = 4, tile_size: int = 8
) -> Image.Image:
    """
    For each tile that exceeds *max_colors* opaque colors, keep the most
    frequent colors and remap minority pixels to the nearest kept color (in
    NES Lab space).

    Returns a new RGBA PIL Image with the same dimensions.
    """
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    w, h = img.size

    if tile_size <= 0:
        raise ValueError("tile_size must be a positive integer")
    if w % tile_size != 0 or h % tile_size != 0:
        raise ValueError(
            f"Image dimensions ({w}×{h}) must be multiples of {tile_size}."
        )

    tile_cols = w // tile_size
    tile_rows = h // tile_size

    for row in range(tile_rows):
        for col in range(tile_cols):
            tx = col * tile_size
            ty = row * tile_size
            tile = arr[ty:ty + tile_size, tx:tx + tile_size]  # view into arr

            opaque_mask = tile[:, :, 3] > 0
            opaque_pixels = tile[opaque_mask][:, :3]

            if opaque_pixels.shape[0] == 0:
                continue

            unique, counts = np.unique(
                opaque_pixels.reshape(-1, 3), axis=0, return_counts=True
            )

            if len(unique) <= max_colors:
                continue  # tile already compliant

            # Keep the max_colors most frequent colors
            top_idx = np.argsort(counts)[::-1][:max_colors]
            kept = unique[top_idx]  # (max_colors, 3)

            # Remap minority pixels to nearest kept color (Lab distance)
            from .palette import rgb_to_lab, _NES_LAB_ARRAY
            kept_lab = np.array(
                [rgb_to_lab(int(r), int(g), int(b)) for r, g, b in kept],
                dtype=np.float64,
            )  # (max_colors, 3)

            # Build a boolean mask for pixels not already in kept set
            kept_set = set(map(tuple, kept.tolist()))
            # Iterate over unique colors that are NOT kept
            minority_colors = [
                tuple(c.tolist()) for c in unique
                if tuple(c.tolist()) not in kept_set
            ]

            for mc in minority_colors:
                mc_lab = np.array(rgb_to_lab(*mc), dtype=np.float64)
                diffs = kept_lab - mc_lab
                dists = np.einsum("ij,ij->i", diffs, diffs)
                nearest_kept = kept[int(np.argmin(dists))]

                # Find pixels in this tile matching mc
                r_match = tile[:, :, 0] == mc[0]
                g_match = tile[:, :, 1] == mc[1]
                b_match = tile[:, :, 2] == mc[2]
                a_match = tile[:, :, 3] > 0
                match = r_match & g_match & b_match & a_match

                arr[ty:ty + tile_size, tx:tx + tile_size][match, 0] = nearest_kept[0]
                arr[ty:ty + tile_size, tx:tx + tile_size][match, 1] = nearest_kept[1]
                arr[ty:ty + tile_size, tx:tx + tile_size][match, 2] = nearest_kept[2]

    return Image.fromarray(arr, mode="RGBA")


def enforce_global_colors(
    image: Image.Image,
    palette_rgb: list[tuple[int, int, int]],
    n_global: int = 3,
    cell_width: int = 4,
    cell_height: int = 8,
) -> Image.Image:
    """
    Enforce global + per-cell color constraints (C64 multicolor mode).

    Selects the *n_global* most frequent colors across the image as shared
    globals. Each cell (cell_width x cell_height) gets those globals plus
    one per-cell foreground color (the most common non-global color in that cell).
    Pixels using other colors are remapped to the nearest valid color.

    Parameters
    ----------
    image : PIL.Image.Image
        Input image, should already be remapped to the target palette.
    palette_rgb : list of RGB tuples
        The console's palette for nearest-color remapping.
    n_global : int
        Number of globally shared colors (3 for C64 multicolor).
    cell_width, cell_height : int
        Cell dimensions (4x8 for C64 multicolor).
    """
    from .palette import rgb_to_lab

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    h, w = arr.shape[:2]

    # Collect all opaque pixel colors
    opaque = arr[:, :, 3] > 0
    all_colors = arr[opaque][:, :3]
    if all_colors.shape[0] == 0:
        return image

    # Find the n_global most frequent colors
    unique, counts = np.unique(all_colors.reshape(-1, 3), axis=0, return_counts=True)
    top_idx = np.argsort(counts)[::-1][:n_global]
    global_colors = set(map(tuple, unique[top_idx].tolist()))

    # Process each cell
    rows = (h + cell_height - 1) // cell_height
    cols = (w + cell_width - 1) // cell_width

    for row in range(rows):
        for col in range(cols):
            cx = col * cell_width
            cy = row * cell_height
            cx_end = min(cx + cell_width, w)
            cy_end = min(cy + cell_height, h)
            cell = arr[cy:cy_end, cx:cx_end]

            cell_opaque = cell[:, :, 3] > 0
            cell_pixels = cell[cell_opaque][:, :3]
            if cell_pixels.shape[0] == 0:
                continue

            # Find the most common non-global color in this cell
            cell_unique, cell_counts = np.unique(
                cell_pixels.reshape(-1, 3), axis=0, return_counts=True
            )
            non_global = [
                (tuple(c.tolist()), cnt)
                for c, cnt in zip(cell_unique, cell_counts)
                if tuple(c.tolist()) not in global_colors
            ]
            if non_global:
                non_global.sort(key=lambda x: x[1], reverse=True)
                cell_fg = non_global[0][0]
            else:
                cell_fg = None

            # Valid colors for this cell
            valid = global_colors.copy()
            if cell_fg:
                valid.add(cell_fg)

            # Remap invalid pixels
            valid_lab = np.array(
                [rgb_to_lab(*c) for c in valid], dtype=np.float64
            )
            valid_arr = np.array(list(valid), dtype=np.uint8)

            for cu, _ in non_global[1:] if non_global else []:
                # This color is not valid for this cell
                cu_lab = np.array(rgb_to_lab(*cu), dtype=np.float64)
                diffs = valid_lab - cu_lab
                dists = np.einsum("ij,ij->i", diffs, diffs)
                nearest = valid_arr[int(np.argmin(dists))]

                r_match = cell[:, :, 0] == cu[0]
                g_match = cell[:, :, 1] == cu[1]
                b_match = cell[:, :, 2] == cu[2]
                a_match = cell[:, :, 3] > 0
                match = r_match & g_match & b_match & a_match

                arr[cy:cy_end, cx:cx_end][match, 0] = nearest[0]
                arr[cy:cy_end, cx:cx_end][match, 1] = nearest[1]
                arr[cy:cy_end, cx:cx_end][match, 2] = nearest[2]

    return Image.fromarray(arr, mode="RGBA")


def validate_attribute_table(image: Image.Image) -> dict:
    """
    Check that each 16×16 block (2×2 tiles) uses at most 4 unique colors
    (attribute table constraint for background tilesets).

    Returns a dict with 'blocks' (list of block reports) and 'all_valid'.
    """
    img = image.convert("RGBA")
    w, h = img.size
    if w % 16 != 0 or h % 16 != 0:
        raise ValueError(
            f"Image dimensions ({w}×{h}) must be multiples of 16 for "
            "attribute table validation."
        )

    arr = np.array(img, dtype=np.uint8)
    block_cols = w // 16
    block_rows = h // 16

    blocks = []
    all_valid = True
    block_id = 0

    for row in range(block_rows):
        for col in range(block_cols):
            bx = col * 16
            by = row * 16
            block = arr[by:by + 16, bx:bx + 16]
            opaque_mask = block[:, :, 3] > 0
            opaque_pixels = block[opaque_mask][:, :3]

            if opaque_pixels.size == 0:
                unique_colors = []
            else:
                unique = np.unique(opaque_pixels.reshape(-1, 3), axis=0)
                unique_colors = [tuple(c) for c in unique]

            violates = len(unique_colors) > 4
            if violates:
                all_valid = False

            blocks.append({
                "block_id": block_id,
                "x": bx,
                "y": by,
                "colors": unique_colors,
                "violates": violates,
            })
            block_id += 1

    return {"blocks": blocks, "all_valid": all_valid}


def reduce_attribute_block_colors(
    image: Image.Image, max_colors: int = 4
) -> Image.Image:
    """
    For each 16x16 block that exceeds *max_colors* opaque colors, keep the most
    frequent colors and remap minority pixels to the nearest kept color.

    This enforces the NES attribute table constraint: each 16x16 pixel area
    (2x2 group of 8x8 tiles) must share the same palette.

    Skips images whose dimensions aren't multiples of 16.
    Returns a new RGBA PIL Image with the same dimensions.
    """
    img = image.convert("RGBA")
    w, h = img.size

    # Skip if not divisible by 16 (e.g., small 8x8 sprites)
    if w % 16 != 0 or h % 16 != 0:
        return img

    arr = np.array(img, dtype=np.uint8).copy()
    block_cols = w // 16
    block_rows = h // 16

    for row in range(block_rows):
        for col in range(block_cols):
            bx = col * 16
            by = row * 16
            block = arr[by:by + 16, bx:bx + 16]  # view into arr

            opaque_mask = block[:, :, 3] > 0
            opaque_pixels = block[opaque_mask][:, :3]

            if opaque_pixels.shape[0] == 0:
                continue

            unique, counts = np.unique(
                opaque_pixels.reshape(-1, 3), axis=0, return_counts=True
            )

            if len(unique) <= max_colors:
                continue  # block already compliant

            # Keep the max_colors most frequent colors
            top_idx = np.argsort(counts)[::-1][:max_colors]
            kept = unique[top_idx]

            # Remap minority pixels to nearest kept color (Lab distance)
            from .palette import rgb_to_lab
            kept_lab = np.array(
                [rgb_to_lab(int(r), int(g), int(b)) for r, g, b in kept],
                dtype=np.float64,
            )

            kept_set = set(map(tuple, kept.tolist()))
            minority_colors = [
                tuple(c.tolist()) for c in unique
                if tuple(c.tolist()) not in kept_set
            ]

            for mc in minority_colors:
                mc_lab = np.array(rgb_to_lab(*mc), dtype=np.float64)
                diffs = kept_lab - mc_lab
                dists = np.einsum("ij,ij->i", diffs, diffs)
                nearest_kept = kept[int(np.argmin(dists))]

                # Find pixels in this block matching mc
                r_match = block[:, :, 0] == mc[0]
                g_match = block[:, :, 1] == mc[1]
                b_match = block[:, :, 2] == mc[2]
                a_match = block[:, :, 3] > 0
                match = r_match & g_match & b_match & a_match

                arr[by:by + 16, bx:bx + 16][match, 0] = nearest_kept[0]
                arr[by:by + 16, bx:bx + 16][match, 1] = nearest_kept[1]
                arr[by:by + 16, bx:bx + 16][match, 2] = nearest_kept[2]

    return Image.fromarray(arr, mode="RGBA")


def check_tile_seamless(image: Image.Image, tolerance: int = 0) -> dict:
    """
    Check if a tile image tiles seamlessly by comparing edge pixels.

    Compares:
    - Top row vs bottom row (vertical tiling)
    - Left column vs right column (horizontal tiling)

    Parameters
    ----------
    image:
        RGBA PIL Image to check (should be a single tile).
    tolerance:
        Maximum per-channel difference allowed between edge pixels
        for them to be considered "matching". 0 = exact match required.

    Returns
    -------
    dict with keys:
        - seamless_h: bool — True if left/right edges match
        - seamless_v: bool — True if top/bottom edges match
        - seamless: bool — True if both directions match
        - mismatched_h: int — count of non-matching pixels on horizontal edges
        - mismatched_v: int — count of non-matching pixels on vertical edges
        - h_score: float — 0.0 to 1.0, fraction of matching horizontal edge pixels
        - v_score: float — 0.0 to 1.0, fraction of matching vertical edge pixels
    """
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    h, w = arr.shape[:2]

    if h < 2 or w < 2:
        return {
            "seamless_h": True, "seamless_v": True, "seamless": True,
            "mismatched_h": 0, "mismatched_v": 0,
            "h_score": 1.0, "v_score": 1.0,
        }

    # Vertical: compare top row with bottom row
    top_row = arr[0, :, :3]       # (w, 3)
    bottom_row = arr[h-1, :, :3]  # (w, 3)
    top_alpha = arr[0, :, 3]
    bottom_alpha = arr[h-1, :, 3]

    # Only compare where both pixels are opaque
    both_opaque_v = (top_alpha > 0) & (bottom_alpha > 0)
    if np.any(both_opaque_v):
        v_diff = np.abs(top_row[both_opaque_v].astype(int) - bottom_row[both_opaque_v].astype(int))
        v_matches = np.all(v_diff <= tolerance, axis=1)
        mismatched_v = int(np.sum(~v_matches))
        v_total = int(np.sum(both_opaque_v))
        v_score = float(np.sum(v_matches)) / v_total if v_total > 0 else 1.0
    else:
        mismatched_v = 0
        v_score = 1.0

    # Horizontal: compare left column with right column
    left_col = arr[:, 0, :3]       # (h, 3)
    right_col = arr[:, w-1, :3]    # (h, 3)
    left_alpha = arr[:, 0, 3]
    right_alpha = arr[:, w-1, 3]

    both_opaque_h = (left_alpha > 0) & (right_alpha > 0)
    if np.any(both_opaque_h):
        h_diff = np.abs(left_col[both_opaque_h].astype(int) - right_col[both_opaque_h].astype(int))
        h_matches = np.all(h_diff <= tolerance, axis=1)
        mismatched_h = int(np.sum(~h_matches))
        h_total = int(np.sum(both_opaque_h))
        h_score = float(np.sum(h_matches)) / h_total if h_total > 0 else 1.0
    else:
        mismatched_h = 0
        h_score = 1.0

    seamless_v = mismatched_v == 0
    seamless_h = mismatched_h == 0

    return {
        "seamless_h": seamless_h,
        "seamless_v": seamless_v,
        "seamless": seamless_h and seamless_v,
        "mismatched_h": mismatched_h,
        "mismatched_v": mismatched_v,
        "h_score": h_score,
        "v_score": v_score,
    }


def make_tile_seamless(image: Image.Image) -> Image.Image:
    """
    Attempt to make a tile seamless by averaging opposing edge pixels.

    For each pair of opposing edge pixels (top↔bottom, left↔right),
    replace both with their average color. This creates smooth transitions
    when the tile is repeated.

    Only modifies opaque pixels. Transparent edges are left alone.

    Parameters
    ----------
    image:
        RGBA PIL Image to make seamless.

    Returns
    -------
    Image.Image
        A new RGBA image with averaged edges.
    """
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    h, w = arr.shape[:2]

    if h < 2 or w < 2:
        return img

    # Average top and bottom rows (where both are opaque)
    top_alpha = arr[0, :, 3]
    bottom_alpha = arr[h-1, :, 3]
    both_v = (top_alpha > 0) & (bottom_alpha > 0)

    if np.any(both_v):
        avg_v = ((arr[0, both_v, :3].astype(np.int16) + arr[h-1, both_v, :3].astype(np.int16)) // 2).astype(np.uint8)
        arr[0, both_v, :3] = avg_v
        arr[h-1, both_v, :3] = avg_v

    # Average left and right columns (where both are opaque)
    left_alpha = arr[:, 0, 3]
    right_alpha = arr[:, w-1, 3]
    both_h = (left_alpha > 0) & (right_alpha > 0)

    if np.any(both_h):
        avg_h = ((arr[both_h, 0, :3].astype(np.int16) + arr[both_h, w-1, :3].astype(np.int16)) // 2).astype(np.uint8)
        arr[both_h, 0, :3] = avg_h
        arr[both_h, w-1, :3] = avg_h

    return Image.fromarray(arr, mode="RGBA")


def preview_tiled(image: Image.Image, repeats: int = 3) -> Image.Image:
    """
    Create a preview image showing the tile repeated in a grid.

    Parameters
    ----------
    image:
        RGBA PIL Image (single tile).
    repeats:
        Number of times to repeat in each direction (default 3 = 3×3 grid).

    Returns
    -------
    Image.Image
        A new RGBA image showing the tile repeated.
    """
    w, h = image.size
    preview = Image.new("RGBA", (w * repeats, h * repeats), (0, 0, 0, 0))
    for row in range(repeats):
        for col in range(repeats):
            preview.paste(image, (col * w, row * h))
    return preview

"""
Quality validation for tiles and animations.

Separate from enforce.py (which fixes constraint violations).
These functions report on quality without modifying images.
"""

from __future__ import annotations

import numpy as np
from PIL import Image


def validate_tile_seamlessness(tile: Image.Image) -> dict:
    """
    Check whether a tile connects seamlessly with copies of itself.

    Compares edge pixels: left column vs right column (horizontal tiling)
    and top row vs bottom row (vertical tiling). A perfectly seamless tile
    has 100% match on both axes.

    Parameters
    ----------
    tile : PIL.Image.Image
        Tile image (typically 8x8 or 16x16).

    Returns
    -------
    dict
        - seamless_h: float — percentage of matching pixels on left/right edges
        - seamless_v: float — percentage of matching pixels on top/bottom edges
        - seamless_overall: float — average of h and v
        - mismatches_h: list of (y, left_color, right_color) tuples
        - mismatches_v: list of (x, top_color, bottom_color) tuples
        - size: (width, height)
        - is_seamless: bool — True if both axes are 100% match
    """
    img = tile.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    h, w = arr.shape[:2]

    # Horizontal: right edge of tile must match left edge of neighbor
    # (i.e., rightmost column must match leftmost column)
    left_col = arr[:, 0, :]     # shape (h, 4)
    right_col = arr[:, -1, :]   # shape (h, 4)
    h_matches = np.all(left_col == right_col, axis=1)
    h_match_pct = round(float(h_matches.mean()) * 100, 1)

    mismatches_h = []
    for y in range(h):
        if not h_matches[y]:
            lc = _rgba_to_hex(left_col[y])
            rc = _rgba_to_hex(right_col[y])
            mismatches_h.append((y, lc, rc))

    # Vertical: bottom edge must match top edge of neighbor
    top_row = arr[0, :, :]      # shape (w, 4)
    bottom_row = arr[-1, :, :]  # shape (w, 4)
    v_matches = np.all(top_row == bottom_row, axis=1)
    v_match_pct = round(float(v_matches.mean()) * 100, 1)

    mismatches_v = []
    for x in range(w):
        if not v_matches[x]:
            tc = _rgba_to_hex(top_row[x])
            bc = _rgba_to_hex(bottom_row[x])
            mismatches_v.append((x, tc, bc))

    overall = round((h_match_pct + v_match_pct) / 2, 1)

    return {
        "size": (w, h),
        "seamless_h": h_match_pct,
        "seamless_v": v_match_pct,
        "seamless_overall": overall,
        "mismatches_h": mismatches_h,
        "mismatches_v": mismatches_v,
        "is_seamless": h_match_pct == 100.0 and v_match_pct == 100.0,
    }


def validate_tile_grid(tile: Image.Image, grid_size: int = 3) -> Image.Image:
    """
    Tile an image in an NxN grid for visual inspection.

    Parameters
    ----------
    tile : PIL.Image.Image
        Source tile.
    grid_size : int
        Grid dimension (default 3 = 3x3 grid).

    Returns
    -------
    PIL.Image.Image
        The tiled grid image.
    """
    img = tile.convert("RGBA")
    w, h = img.size
    grid = Image.new("RGBA", (w * grid_size, h * grid_size))
    for row in range(grid_size):
        for col in range(grid_size):
            grid.paste(img, (col * w, row * h))
    return grid


def validate_animation_frames(frames: list[Image.Image]) -> dict:
    """
    Validate a set of animation frames for quality.

    Checks:
    - Canvas size consistency across frames
    - Palette consistency (no color drift between frames)
    - Pose differentiation (frames are not identical)
    - Bounding box stability (character doesn't wildly shift)

    Parameters
    ----------
    frames : list[PIL.Image.Image]
        List of frame images (minimum 2).

    Returns
    -------
    dict
        - frame_count: int
        - canvas_consistent: bool — all frames same size
        - canvas_sizes: list of (w, h)
        - palette_consistent: bool — all frames use same colors
        - palette_per_frame: list of sets of hex colors
        - palette_union: set of all colors across frames
        - palette_drift: list of colors not in frame 0
        - pose_differentiation: list of dicts per consecutive pair
        - bounding_boxes: list of (x0, y0, x1, y1) per frame
        - bbox_stability: float — max centroid shift in pixels
        - issues: list of string descriptions of problems found
    """
    if len(frames) < 2:
        return {
            "frame_count": len(frames),
            "error": "Need at least 2 frames for animation validation",
        }

    issues = []

    # Convert all to RGBA
    rgba_frames = [f.convert("RGBA") for f in frames]
    arrays = [np.array(f, dtype=np.uint8) for f in rgba_frames]

    # Canvas size consistency
    sizes = [(a.shape[1], a.shape[0]) for a in arrays]
    canvas_consistent = len(set(sizes)) == 1
    if not canvas_consistent:
        issues.append(f"Canvas size varies: {sizes}")

    # Palette per frame
    palettes = []
    for arr in arrays:
        opaque = arr[:, :, 3] > 0
        if opaque.any():
            colors = arr[opaque][:, :3]
            unique = {_rgb_to_hex(c) for c in np.unique(colors.reshape(-1, 3), axis=0)}
        else:
            unique = set()
        palettes.append(unique)

    palette_union = set()
    for p in palettes:
        palette_union |= p

    palette_consistent = all(p == palettes[0] for p in palettes)
    palette_drift = list(palette_union - palettes[0]) if palettes[0] else []
    if palette_drift:
        issues.append(f"Palette drift: {len(palette_drift)} colors not in frame 0: {palette_drift}")

    # Pose differentiation (consecutive frames)
    pose_diffs = []
    for i in range(len(arrays) - 1):
        if arrays[i].shape != arrays[i + 1].shape:
            pose_diffs.append({
                "frames": (i, i + 1),
                "different_pixels": -1,
                "is_identical": False,
                "error": "Different canvas sizes",
            })
            continue

        diff = np.any(arrays[i] != arrays[i + 1], axis=2)
        n_diff = int(diff.sum())
        pose_diffs.append({
            "frames": (i, i + 1),
            "different_pixels": n_diff,
            "total_pixels": int(diff.size),
            "diff_pct": round(n_diff / diff.size * 100, 1),
            "is_identical": n_diff == 0,
        })
        if n_diff == 0:
            issues.append(f"Frames {i} and {i+1} are identical (no pose change)")

    # Bounding boxes and stability
    bboxes = []
    centroids = []
    for f in rgba_frames:
        bb = f.getbbox()
        if bb:
            bboxes.append(bb)
            cx = (bb[0] + bb[2]) / 2
            cy = (bb[1] + bb[3]) / 2
            centroids.append((cx, cy))
        else:
            bboxes.append(None)
            centroids.append(None)

    # Max centroid shift from frame 0
    bbox_stability = 0.0
    if centroids[0] is not None:
        for c in centroids[1:]:
            if c is not None:
                dx = abs(c[0] - centroids[0][0])
                dy = abs(c[1] - centroids[0][1])
                shift = (dx ** 2 + dy ** 2) ** 0.5
                bbox_stability = max(bbox_stability, shift)

    if bbox_stability > 4.0:
        issues.append(f"Large centroid shift: {bbox_stability:.1f}px (threshold: 4px)")

    return {
        "frame_count": len(frames),
        "canvas_consistent": canvas_consistent,
        "canvas_sizes": sizes,
        "palette_consistent": palette_consistent,
        "palette_per_frame": [sorted(p) for p in palettes],
        "palette_union": sorted(palette_union),
        "palette_drift": palette_drift,
        "pose_differentiation": pose_diffs,
        "bounding_boxes": bboxes,
        "bbox_stability": round(bbox_stability, 1),
        "issues": issues,
        "is_valid": len(issues) == 0,
    }


def _rgba_to_hex(pixel: np.ndarray) -> str:
    """Convert RGBA pixel array to hex string."""
    if len(pixel) == 4:
        return f"#{pixel[0]:02x}{pixel[1]:02x}{pixel[2]:02x}{pixel[3]:02x}"
    return f"#{pixel[0]:02x}{pixel[1]:02x}{pixel[2]:02x}"


def _rgb_to_hex(pixel: np.ndarray) -> str:
    """Convert RGB pixel array to hex string."""
    return f"#{pixel[0]:02x}{pixel[1]:02x}{pixel[2]:02x}"

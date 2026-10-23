"""
Post-processing cleanup for pixel art sprites.

Two-stage cleanup:
  1. Background removal — detect and remove solid background colors
     that Image2Pixel didn't fully catch
  2. Artifact removal — remove stray colors that appear in tiny
     quantities (noise from conversion)
"""

from __future__ import annotations

import numpy as np
from PIL import Image

from .palette import rgb_to_lab


def is_degenerate_output(image: Image.Image) -> bool:
    """
    Return True if *image* is a degenerate (useless) pipeline result.

    A processed sprite/asset is degenerate when it carries no usable visual
    content. Concretely:

      * Fully transparent — 0 opaque pixels (i.e. 0 unique opaque colors).
        This is the "blank output" failure seen when the concept/cleanup
        stage collapses and the pipeline returns an empty canvas.
      * A single solid color filling the entire image with no transparency —
        one unique color and no alpha holes. A flat fill is not a sprite.

    This matches the inspector's notion of an EMPTY output (0 unique opaque
    colors) and additionally guards the solid-fill case. It is intentionally
    conservative: a legitimate sprite has at least two opaque colors, or an
    opaque shape over transparency.
    """
    arr = np.asarray(image.convert("RGBA"), dtype=np.uint8)
    if arr.size == 0:
        return True

    alpha = arr[:, :, 3]
    opaque_mask = alpha > 0
    opaque = arr[opaque_mask][:, :3]

    # Case 1: nothing opaque at all (fully transparent canvas).
    if opaque.shape[0] == 0:
        return True

    unique = np.unique(opaque.reshape(-1, 3), axis=0)

    # Case 2: a single solid color covering the whole image (no transparent
    # holes). One flat color is not a usable sprite.
    if len(unique) == 1 and bool(np.all(opaque_mask)):
        return True

    return False


def remove_background(
    image: Image.Image,
    tolerance: int = 45,
) -> Image.Image:
    """
    Detect and remove solid background colors from a sprite image.

    Samples the corner pixels to determine the background color, then
    makes all pixels within *tolerance* of that color transparent.
    Also flood-fills from edges to only remove the outer background,
    not interior pixels that happen to match.

    Parameters
    ----------
    image:
        RGBA PIL Image.
    tolerance:
        Maximum color distance (in RGB space) from the detected background
        color for a pixel to be considered background.
    """
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    h, w = arr.shape[:2]

    if h < 2 or w < 2:
        return img

    # Sample the entire border (all edge pixels) to detect background color
    border_pixels = []
    # Top and bottom rows
    for x in range(w):
        if arr[0, x, 3] > 0:
            border_pixels.append(arr[0, x, :3])
        if arr[h-1, x, 3] > 0:
            border_pixels.append(arr[h-1, x, :3])
    # Left and right columns (excluding corners already counted)
    for y in range(1, h-1):
        if arr[y, 0, 3] > 0:
            border_pixels.append(arr[y, 0, :3])
        if arr[y, w-1, 3] > 0:
            border_pixels.append(arr[y, w-1, :3])

    if len(border_pixels) < 4:
        return img  # not enough samples, skip

    # Find the most common border color — use the mode (most frequent)
    # by finding the color that appears most among border pixels
    border_u8 = np.array(border_pixels, dtype=np.uint8)
    unique_border, border_counts = np.unique(
        border_u8.reshape(-1, 3), axis=0, return_counts=True
    )
    # The background is the most common border color
    bg_color = unique_border[np.argmax(border_counts)]

    # Create a mask of pixels that match the background color
    diff = np.sqrt(np.sum(
        (arr[:, :, :3].astype(np.float64) - bg_color.astype(np.float64)) ** 2,
        axis=2,
    ))
    bg_match = diff <= tolerance

    # Flood fill from edges — only remove background pixels that are
    # connected to the image border, not interior same-colored pixels
    from collections import deque
    visited = np.zeros((h, w), dtype=bool)
    to_remove = np.zeros((h, w), dtype=bool)
    queue = deque()

    # Seed from all border pixels that match background
    for x in range(w):
        if bg_match[0, x]:
            queue.append((0, x))
        if bg_match[h-1, x]:
            queue.append((h-1, x))
    for y in range(1, h-1):
        if bg_match[y, 0]:
            queue.append((y, 0))
        if bg_match[y, w-1]:
            queue.append((y, w-1))

    while queue:
        cy, cx = queue.popleft()
        if visited[cy, cx]:
            continue
        visited[cy, cx] = True
        if not bg_match[cy, cx]:
            continue
        to_remove[cy, cx] = True
        # 4-connected neighbors
        for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
            ny, nx = cy + dy, cx + dx
            if 0 <= ny < h and 0 <= nx < w and not visited[ny, nx]:
                queue.append((ny, nx))

    # Make background pixels transparent
    arr[to_remove, 3] = 0

    return Image.fromarray(arr, mode="RGBA")


def remove_artifact_colors(
    image: Image.Image,
    min_pixel_fraction: float = 0.03,
    min_pixel_count: int = 5,
) -> Image.Image:
    """
    Remove colors that appear in very small quantities (likely artifacts).

    Any color that makes up less than *min_pixel_fraction* of opaque pixels
    AND has fewer than *min_pixel_count* pixels is remapped to the
    perceptually nearest color that IS above the threshold.

    Parameters
    ----------
    image:
        RGBA PIL Image to clean up.
    min_pixel_fraction:
        Minimum fraction of opaque pixels a color must represent to be kept
        (default 3%).
    min_pixel_count:
        Absolute minimum pixel count to keep a color regardless of fraction.
    """
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    h, w = arr.shape[:2]

    opaque_mask = arr[:, :, 3] > 0
    opaque_pixels = arr[opaque_mask][:, :3]

    if opaque_pixels.size == 0:
        return img

    total_opaque = opaque_pixels.shape[0]
    unique_colors, counts = np.unique(
        opaque_pixels.reshape(-1, 3), axis=0, return_counts=True
    )

    # Determine which colors to keep
    threshold = max(min_pixel_count, int(total_opaque * min_pixel_fraction))
    keep_mask = counts >= threshold
    kept_colors = unique_colors[keep_mask]
    artifact_colors = unique_colors[~keep_mask]

    if len(artifact_colors) == 0 or len(kept_colors) == 0:
        return img

    # Compute Lab values for kept colors
    kept_lab = np.array(
        [rgb_to_lab(int(r), int(g), int(b)) for r, g, b in kept_colors],
        dtype=np.float64,
    )

    # Remap each artifact color to the nearest kept color
    for ac in artifact_colors:
        ac_lab = np.array(rgb_to_lab(int(ac[0]), int(ac[1]), int(ac[2])), dtype=np.float64)
        diffs = kept_lab - ac_lab
        dists = np.einsum("ij,ij->i", diffs, diffs)
        nearest = kept_colors[int(np.argmin(dists))]

        match = (
            (arr[:, :, 0] == ac[0]) &
            (arr[:, :, 1] == ac[1]) &
            (arr[:, :, 2] == ac[2]) &
            opaque_mask
        )
        arr[match, 0] = nearest[0]
        arr[match, 1] = nearest[1]
        arr[match, 2] = nearest[2]

    return Image.fromarray(arr, mode="RGBA")


def remove_small_regions(
    image: Image.Image,
    min_region_pixels: int = 5,
) -> Image.Image:
    """
    Remove small disconnected regions (floating pixels / artifacts).

    Uses connected component analysis to find isolated pixel clusters.
    Regions smaller than *min_region_pixels* are made transparent.
    """
    from scipy.ndimage import label as ndimage_label

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    opaque_mask = arr[:, :, 3] > 0

    if not np.any(opaque_mask):
        return img

    labeled, num_regions = ndimage_label(opaque_mask)
    if num_regions <= 1:
        return img

    # Measure each region
    region_sizes = []
    for rid in range(1, num_regions + 1):
        region_sizes.append((rid, int(np.count_nonzero(labeled == rid))))
    region_sizes.sort(key=lambda x: x[1], reverse=True)

    # Remove small regions
    for rid, size in region_sizes:
        if size < min_region_pixels:
            arr[labeled == rid, 3] = 0

    return Image.fromarray(arr, mode="RGBA")


def normalize_frame_sizes(
    frames: list[Image.Image],
    pad_to_multiple_of: int = 8,
) -> list[Image.Image]:
    """
    Pad all frames to uniform dimensions (max width x max height, rounded to
    a multiple of *pad_to_multiple_of*). Each frame is center-padded.
    """
    import math

    if not frames or len(frames) <= 1:
        return frames

    max_w = max(f.width for f in frames)
    max_h = max(f.height for f in frames)
    uniform_w = math.ceil(max_w / pad_to_multiple_of) * pad_to_multiple_of or pad_to_multiple_of
    uniform_h = math.ceil(max_h / pad_to_multiple_of) * pad_to_multiple_of or pad_to_multiple_of

    result = []
    for f in frames:
        if f.width == uniform_w and f.height == uniform_h:
            result.append(f)
            continue
        padded = Image.new("RGBA", (uniform_w, uniform_h), (0, 0, 0, 0))
        # Center, but snap the offset DOWN to a multiple of pad_to_multiple_of
        # so each frame's content stays aligned to the tile grid it was
        # enforced on. A non-grid-aligned shift (e.g. a 4px pad on an 8px
        # grid) makes previously-clean tiles straddle two enforced tiles,
        # re-introducing per-tile color violations on strict consoles
        # (notably c64_hires at 2 colors/tile). Snapping preserves the
        # per-frame enforcement guarantee through normalization.
        m = pad_to_multiple_of
        x_offset = ((uniform_w - f.width) // 2 // m) * m
        y_offset = ((uniform_h - f.height) // 2 // m) * m
        padded.paste(f, (x_offset, y_offset))
        result.append(padded)

    return result


def close_sprite_gaps(
    image: Image.Image,
    gap_size: int = 1,
) -> Image.Image:
    """
    Close small gaps in a sprite's body using morphological closing.

    Background removal and color reduction can create 1-2px gaps at joints
    (neck, waist, arms), fragmenting a connected character into disconnected
    body parts. This fills those gaps by dilating then eroding the opaque
    mask, and assigns colors to newly-filled pixels from their nearest
    opaque neighbor.

    Parameters
    ----------
    image:
        RGBA PIL Image to process.
    gap_size:
        Maximum gap width to close (in pixels). Default 1 fills single-pixel
        gaps. Use 2 for wider gaps at the cost of slightly thickening outlines.
    """
    from scipy.ndimage import binary_dilation, binary_erosion, distance_transform_edt

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    mask = arr[:, :, 3] > 0

    if not np.any(mask):
        return img

    # Morphological closing: dilate (expand) then erode (shrink back)
    # This fills gaps smaller than gap_size while preserving overall shape
    struct = np.ones((gap_size * 2 + 1, gap_size * 2 + 1), dtype=bool)
    closed = binary_dilation(mask, structure=struct)
    closed = binary_erosion(closed, structure=struct)

    # Find newly filled pixels (were transparent, now opaque after closing)
    new_pixels = closed & ~mask

    if not np.any(new_pixels):
        return img

    # For each new pixel, find the nearest original opaque pixel and copy
    # its color. distance_transform_edt on ~mask gives distance from each
    # transparent pixel to the nearest opaque pixel.
    _dists, indices = distance_transform_edt(~mask, return_indices=True)

    # Vectorized color assignment from nearest opaque neighbors
    new_ys, new_xs = np.where(new_pixels)
    src_ys = indices[0][new_ys, new_xs]
    src_xs = indices[1][new_ys, new_xs]
    arr[new_ys, new_xs, :3] = arr[src_ys, src_xs, :3]
    arr[new_ys, new_xs, 3] = 255

    return Image.fromarray(arr, mode="RGBA")


def trim_transparent(image: Image.Image, padding: int = 0) -> Image.Image:
    """
    Crop the image to the bounding box of opaque content, plus optional padding.
    Ensures final dimensions are still multiples of 8.
    """
    import math
    img = image.convert("RGBA")
    arr = np.array(img)
    opaque = arr[:, :, 3] > 0

    if not np.any(opaque):
        return img

    rows = np.any(opaque, axis=1)
    cols = np.any(opaque, axis=0)
    rmin, rmax = np.where(rows)[0][[0, -1]]
    cmin, cmax = np.where(cols)[0][[0, -1]]

    # Add padding
    h, w = arr.shape[:2]
    rmin = max(0, rmin - padding)
    rmax = min(h - 1, rmax + padding)
    cmin = max(0, cmin - padding)
    cmax = min(w - 1, cmax + padding)

    cropped = img.crop((cmin, rmin, cmax + 1, rmax + 1))

    # Pad to multiple of 8
    cw, ch = cropped.size
    new_w = math.ceil(cw / 8) * 8
    new_h = math.ceil(ch / 8) * 8
    if new_w != cw or new_h != ch:
        canvas = Image.new("RGBA", (new_w, new_h), (0, 0, 0, 0))
        paste_x = (new_w - cw) // 2
        paste_y = (new_h - ch) // 2
        canvas.paste(cropped, (paste_x, paste_y))
        return canvas

    return cropped


def reduce_to_max_colors(
    image: Image.Image,
    max_colors: int = 6,
    method: str = "merge",
) -> Image.Image:
    """
    If the image has more than *max_colors* unique opaque colors,
    reduce to *max_colors*.

    Parameters
    ----------
    method:
        ``"merge"`` (default) — iteratively merge the least-used color
        into its nearest neighbor. Fast, but can lose perceptually important
        accent colors that happen to have few pixels.

        ``"median_cut"`` — use Pillow's median-cut quantization, which
        splits the color space along axes of greatest variance. Preserves
        distinct hues better (e.g. a red gem on gray armor stays red).
    """
    if method == "median_cut":
        return _reduce_median_cut(image, max_colors)
    return _reduce_iterative_merge(image, max_colors)


def _reduce_median_cut(
    image: Image.Image,
    max_colors: int,
) -> Image.Image:
    """Reduce colors via Pillow median-cut quantization."""
    img = image.convert("RGBA")
    alpha = img.split()[3]

    rgb = img.convert("RGB")
    quantized = rgb.quantize(colors=max_colors, method=Image.Quantize.MEDIANCUT)
    result = quantized.convert("RGB").convert("RGBA")
    result.putalpha(alpha)

    # Zero out RGB on fully transparent pixels
    arr = np.array(result)
    arr[arr[:, :, 3] == 0] = [0, 0, 0, 0]
    return Image.fromarray(arr, mode="RGBA")


def _reduce_iterative_merge(
    image: Image.Image,
    max_colors: int,
) -> Image.Image:
    """Reduce colors by iteratively merging least-used into nearest neighbor."""
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()

    opaque_mask = arr[:, :, 3] > 0
    opaque_pixels = arr[opaque_mask][:, :3]
    if opaque_pixels.size == 0:
        return img

    unique_colors, counts = np.unique(
        opaque_pixels.reshape(-1, 3), axis=0, return_counts=True
    )

    while len(unique_colors) > max_colors:
        # Find the least-used color
        min_idx = np.argmin(counts)
        victim = unique_colors[min_idx]
        victim_lab = np.array(rgb_to_lab(int(victim[0]), int(victim[1]), int(victim[2])), dtype=np.float64)

        # Find nearest other color
        others_lab = np.array([
            rgb_to_lab(int(r), int(g), int(b))
            for j, (r, g, b) in enumerate(unique_colors) if j != min_idx
        ], dtype=np.float64)
        others = np.array([c for j, c in enumerate(unique_colors) if j != min_idx])

        diffs = others_lab - victim_lab
        dists = np.einsum("ij,ij->i", diffs, diffs)
        nearest = others[int(np.argmin(dists))]

        # Remap victim pixels
        match = (
            (arr[:, :, 0] == victim[0]) &
            (arr[:, :, 1] == victim[1]) &
            (arr[:, :, 2] == victim[2]) &
            opaque_mask
        )
        arr[match, 0] = nearest[0]
        arr[match, 1] = nearest[1]
        arr[match, 2] = nearest[2]

        # Recalculate
        opaque_pixels = arr[arr[:, :, 3] > 0][:, :3]
        unique_colors, counts = np.unique(
            opaque_pixels.reshape(-1, 3), axis=0, return_counts=True
        )

    return Image.fromarray(arr, mode="RGBA")


def remap_to_locked_palette(
    image: Image.Image,
    palette_hex: list[str],
) -> Image.Image:
    """Remap every opaque pixel to the nearest color in the locked palette."""
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()

    # Parse hex colors to RGB
    locked_rgb = []
    for h in palette_hex:
        h = h.lstrip("#")
        locked_rgb.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))

    # Compute Lab for locked palette
    locked_lab = np.array(
        [rgb_to_lab(r, g, b) for r, g, b in locked_rgb],
        dtype=np.float64,
    )

    opaque_mask = arr[:, :, 3] > 0
    opaque_pixels = arr[opaque_mask][:, :3]

    if opaque_pixels.size == 0:
        return img

    # For each unique color, find nearest in locked palette
    unique_colors = np.unique(opaque_pixels.reshape(-1, 3), axis=0)

    for uc in unique_colors:
        uc_lab = np.array(rgb_to_lab(int(uc[0]), int(uc[1]), int(uc[2])), dtype=np.float64)
        diffs = locked_lab - uc_lab
        dists = np.einsum("ij,ij->i", diffs, diffs)
        nearest_idx = int(np.argmin(dists))
        nearest = locked_rgb[nearest_idx]

        match = (
            (arr[:, :, 0] == uc[0]) &
            (arr[:, :, 1] == uc[1]) &
            (arr[:, :, 2] == uc[2]) &
            opaque_mask
        )
        arr[match, 0] = nearest[0]
        arr[match, 1] = nearest[1]
        arr[match, 2] = nearest[2]

    return Image.fromarray(arr, mode="RGBA")


def slice_spritesheet(
    image: Image.Image,
    expected_frames: int = 4,
) -> list[Image.Image]:
    """
    Detect and slice individual frames from a sprite sheet image.

    Strategy:
    1. Find columns of mostly-transparent pixels (frame separators).
    2. If that doesn't work, divide evenly by expected_frames.
    3. Crop each frame to its content bounding box.
    4. Pad all frames to the same size (largest frame dimensions, rounded to 8).

    Returns a list of RGBA PIL Images, one per frame.
    """
    import math

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    h, w = arr.shape[:2]

    if expected_frames <= 1 or w == 0 or h == 0:
        return [img]

    # Strategy: find wide transparent gaps between frames.
    # A real separator is a run of mostly-transparent columns that's at least
    # min_gap_width wide. Thin transparent columns within a sprite (like
    # between skeleton legs) are NOT separators.
    opaque_per_col = (arr[:, :, 3] > 0).sum(axis=0)  # shape: (w,)
    separator_threshold = h * 0.05  # column is "empty" if <5% opaque

    is_separator = opaque_per_col < separator_threshold

    # Find runs of separator columns, but only count wide gaps as real separators
    min_gap_width = max(3, w // (expected_frames * 4))  # at least 3px wide gap
    sep_runs: list[tuple[int, int]] = []  # (start, end) of each gap run
    in_sep = False
    sep_s = 0
    for x in range(w):
        if is_separator[x]:
            if not in_sep:
                in_sep = True
                sep_s = x
        else:
            if in_sep:
                in_sep = False
                run_width = x - sep_s
                if run_width >= min_gap_width:
                    sep_runs.append((sep_s, x - 1))

    # Only keep the N-1 widest gaps (we expect expected_frames-1 separators)
    if len(sep_runs) > expected_frames - 1:
        sep_runs.sort(key=lambda r: r[1] - r[0], reverse=True)
        sep_runs = sep_runs[:expected_frames - 1]
        sep_runs.sort(key=lambda r: r[0])  # re-sort by position

    # Build frame x-ranges from separator positions
    boundaries: list[tuple[int, int]] = []
    prev_end = 0
    for s, e in sep_runs:
        if s > prev_end:
            boundaries.append((prev_end, s - 1))
        prev_end = e + 1
    if prev_end < w:
        boundaries.append((prev_end, w - 1))

    # Filter out trivially narrow regions (less than 4 pixels wide)
    min_frame_width = max(4, w // (expected_frames * 3))
    boundaries = [(s, e) for s, e in boundaries if e - s >= min_frame_width]

    # Fall back to even division if detection didn't find the right frame count
    if len(boundaries) != expected_frames:
        frame_w = w // expected_frames
        boundaries = []
        for i in range(expected_frames):
            x_start = i * frame_w
            x_end = (x_start + frame_w - 1) if i < expected_frames - 1 else (w - 1)
            boundaries.append((x_start, x_end))

    # Crop each frame region, then trim to content bounding box
    frames: list[Image.Image] = []
    for x_start, x_end in boundaries:
        region = img.crop((x_start, 0, x_end + 1, h))
        region_arr = np.array(region, dtype=np.uint8)
        opaque = region_arr[:, :, 3] > 0
        if np.any(opaque):
            rows = np.any(opaque, axis=1)
            cols = np.any(opaque, axis=0)
            rmin, rmax = int(np.where(rows)[0][0]), int(np.where(rows)[0][-1])
            cmin, cmax = int(np.where(cols)[0][0]), int(np.where(cols)[0][-1])
            frame = region.crop((cmin, rmin, cmax + 1, rmax + 1))
        else:
            frame = region
        frames.append(frame)

    if not frames:
        return [img]

    # Determine max frame dimensions
    max_w = max(f.width for f in frames)
    max_h = max(f.height for f in frames)

    # Round up to multiples of 8
    pad_w = math.ceil(max_w / 8) * 8
    pad_h = math.ceil(max_h / 8) * 8
    if pad_w == 0:
        pad_w = 8
    if pad_h == 0:
        pad_h = 8

    # Pad each frame to uniform size, centered
    padded: list[Image.Image] = []
    for frame in frames:
        canvas = Image.new("RGBA", (pad_w, pad_h), (0, 0, 0, 0))
        paste_x = (pad_w - frame.width) // 2
        paste_y = (pad_h - frame.height) // 2
        canvas.paste(frame, (paste_x, paste_y))
        padded.append(canvas)

    return padded


def detect_and_remove_dithering(
    image: Image.Image,
    block_size: int = 4,
) -> Image.Image:
    """
    Detect and remove checkerboard/Bayer dithering patterns.

    Real NES games rarely used dithering on sprites. This function scans
    non-overlapping blocks and replaces dithered regions with the dominant color.

    A block is considered dithered when:
    - It contains exactly 2 unique opaque colors
    - More than 60% of opaque pixels differ from all 4-connected neighbors

    Parameters
    ----------
    image:
        RGBA PIL Image to process.
    block_size:
        Size of non-overlapping blocks to scan (default 4x4).
    """
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8).copy()
    h, w = arr.shape[:2]

    if h < block_size or w < block_size:
        return img

    for by in range(0, h - block_size + 1, block_size):
        for bx in range(0, w - block_size + 1, block_size):
            block = arr[by:by + block_size, bx:bx + block_size]

            # Only consider opaque pixels
            opaque_mask = block[:, :, 3] > 0
            opaque_count = int(np.sum(opaque_mask))
            if opaque_count < 4:
                continue

            # Check unique opaque colors
            opaque_rgb = block[opaque_mask][:, :3]
            unique_colors, counts = np.unique(
                opaque_rgb.reshape(-1, 3), axis=0, return_counts=True
            )

            if len(unique_colors) != 2:
                continue  # only detect 2-color dithering

            # Count pixels that differ from all 4-connected neighbors
            differ_count = 0
            for y in range(block_size):
                for x in range(block_size):
                    if not opaque_mask[y, x]:
                        continue
                    pixel = block[y, x, :3]
                    has_same_neighbor = False
                    for dy, dx in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                        ny, nx = y + dy, x + dx
                        if 0 <= ny < block_size and 0 <= nx < block_size:
                            if opaque_mask[ny, nx] and np.array_equal(pixel, block[ny, nx, :3]):
                                has_same_neighbor = True
                                break
                    if not has_same_neighbor:
                        differ_count += 1

            # If >60% of opaque pixels differ from all neighbors, it's dithered
            if differ_count / opaque_count > 0.6:
                # Replace minority color with majority color
                majority_idx = int(np.argmax(counts))
                minority_idx = 1 - majority_idx
                minority_color = unique_colors[minority_idx]
                majority_color = unique_colors[majority_idx]

                for y in range(block_size):
                    for x in range(block_size):
                        if (opaque_mask[y, x] and
                                np.array_equal(block[y, x, :3], minority_color)):
                            arr[by + y, bx + x, :3] = majority_color

    return Image.fromarray(arr, mode="RGBA")


def normalize_tile_edge_brightness(image: Image.Image, border_px: int = 2, threshold: float = 15.0) -> Image.Image:
    """Fix AI-generated tile edge darkening.

    AI models add subtle brightness falloff at tile edges, creating visible
    seams when tiles are placed side by side. This detects and corrects the
    darkening by blending border pixels toward interior brightness.

    Only affects tiles where the border is noticeably darker than the interior.
    """
    arr = np.array(image.convert("RGBA"), dtype=np.float64)
    h, w = arr.shape[:2]
    if h < border_px * 3 or w < border_px * 3:
        return image

    rgb = arr[:, :, :3]
    alpha = arr[:, :, 3]

    # Compute per-pixel luminance (Rec. 709)
    lum = 0.2126 * rgb[:, :, 0] + 0.7152 * rgb[:, :, 1] + 0.0722 * rgb[:, :, 2]

    # Build border and interior masks (only opaque pixels)
    opaque = alpha > 0
    border_mask = np.zeros((h, w), dtype=bool)
    border_mask[:border_px, :] = True
    border_mask[-border_px:, :] = True
    border_mask[:, :border_px] = True
    border_mask[:, -border_px:] = True

    interior_mask = ~border_mask & opaque
    border_opaque = border_mask & opaque

    if not np.any(interior_mask) or not np.any(border_opaque):
        return image

    interior_avg = np.mean(lum[interior_mask])
    border_avg = np.mean(lum[border_opaque])

    # Only fix if border is darker than interior by threshold
    if interior_avg - border_avg < threshold:
        return image

    # Blend border pixels toward interior brightness
    correction = interior_avg - border_avg
    out = arr.copy()
    for c in range(3):
        channel = out[:, :, c]
        channel[border_opaque] = np.clip(channel[border_opaque] + correction, 0, 255)

    return Image.fromarray(out.astype(np.uint8), mode="RGBA")


def full_cleanup(
    image: Image.Image,
    era: str = "mid",
    palette_colors: list[str] | None = None,
    asset_type: str = "character",
    palette_mood: str = "auto",
    max_colors: int | None = None,
    animation_type: str | None = None,
    console: str | None = None,
    debug_dir: str | None = None,
) -> Image.Image:
    """
    Run the full cleanup pipeline: background removal → artifact cleanup → color reduction → trim.

    Parameters
    ----------
    image:
        RGBA PIL Image to process.
    era:
        Era style — ``"retro"``, ``"early"``, ``"mid"`` (default), or ``"late"``.
        Color limits are console-specific when ``console`` is provided.
    palette_colors:
        Optional list of hex strings for palette lock. When provided, ALL opaque pixels
        are remapped to the nearest color in this list instead of applying era-based
        color reduction.
    asset_type:
        Asset type being generated. Tiles and tilesets skip background removal
        and trimming since the tile content IS the full image.
    palette_mood:
        Color mood (warm, cool, dark, bright, earth, auto). When not "auto" and
        no palette_colors are locked, restricts output to mood-appropriate
        palette colors.
    max_colors:
        Optional override for the maximum number of opaque colors. When set,
        overrides the era-based default. Range: 2-16.
    console:
        Console name for console-aware color limits. When provided, reads
        max_cleanup_colors from the console's EraPromptData.
    """
    # Debug: save intermediate images at each step
    def _dbg(name: str, img: Image.Image) -> None:
        if debug_dir:
            from pathlib import Path
            Path(debug_dir).mkdir(parents=True, exist_ok=True)
            img.save(str(Path(debug_dir) / f"{name}.png"), format="PNG")

    _dbg("00_input", image)

    # NES-calibrated fallback for backward compat when no console specified
    _era_color_limits: dict[str, int] = {
        "retro": 3,
        "early": 4,
        "mid": 6,
        "late": 6,
    }

    # Console-aware color limit from EraPromptData
    _console_era_limit: int | None = None
    if console:
        try:
            from .console_prompt_data import get_prompt_data
            prompt_data = get_prompt_data(console)
            era_key = era.lower() if isinstance(era, str) else "mid"
            era_data = prompt_data.eras.get(era_key, prompt_data.eras.get("mid"))
            if era_data:
                _console_era_limit = era_data.max_cleanup_colors
        except (NotImplementedError, KeyError):
            pass

    is_tile_type = asset_type in ("tile", "tileset")

    # Skip background removal for tiles — the tile IS the background
    if not is_tile_type:
        # P0-2: Adaptive tolerance based on image brightness.
        # Dark sprites (late-era, dark armor) get eaten by tolerance=45
        # because dark sprite colors are within tolerance of dark backgrounds.
        import numpy as np
        src_arr = np.array(image.convert("RGBA"), dtype=np.uint8)
        avg_brightness = float(np.mean(src_arr[:, :, :3]))
        if avg_brightness < 80:
            base_tolerance = 25  # dark image — tight tolerance
        elif avg_brightness < 140:
            base_tolerance = 35  # mid-range
        else:
            base_tolerance = 45  # bright image — default

        img = remove_background(image, tolerance=base_tolerance)

        # Safety check: if removal ate most of the sprite, retry with
        # tighter tolerance then fall back to original.
        original_pixels = image.size[0] * image.size[1]
        alpha = np.array(img)[:, :, 3] if img.mode == "RGBA" else None
        opaque_pixels = int(np.count_nonzero(alpha)) if alpha is not None else original_pixels

        if opaque_pixels < original_pixels * 0.10:
            # Too aggressive — retry with minimum tolerance
            img = remove_background(image, tolerance=15)
            alpha = np.array(img)[:, :, 3] if img.mode == "RGBA" else None
            opaque_pixels = int(np.count_nonzero(alpha)) if alpha is not None else original_pixels

            if opaque_pixels < original_pixels * 0.10:
                # Still too aggressive — just convert to RGBA without removal
                img = image.convert("RGBA")
    else:
        img = image.convert("RGBA")

    _dbg("01_background_removed", img)

    # Preserve judged detail on 16-bit canvases at 32px and above.
    _artifact_scrub_consoles = {"snes", "genesis", "pc_engine"}
    try:
        from .console_profile import get_profile
        _profile_name = get_profile(console).name if console else None
    except KeyError:
        _profile_name = None
    _skip_artifact_scrub = (
        _profile_name in _artifact_scrub_consoles
        and (img.width >= 32 or img.height >= 32)
    )
    _canvas_pixels = img.size[0] * img.size[1]

    if not _skip_artifact_scrub:
        # Use relaxed artifact thresholds for tiles — they need subtle detail.
        # Scale thresholds by canvas size: at 16x16, 5 pixels is a detail (eye, button).
        # At 64x64+, 5 pixels is genuine noise.
        if is_tile_type:
            img = remove_artifact_colors(img, min_pixel_fraction=0.01, min_pixel_count=3)
        elif _canvas_pixels <= 256:  # 16x16
            img = remove_artifact_colors(img, min_pixel_fraction=0.01, min_pixel_count=2)
        elif _canvas_pixels <= 1024:  # 32x32
            img = remove_artifact_colors(img, min_pixel_fraction=0.02, min_pixel_count=3)
        else:
            img = remove_artifact_colors(img)
    _dbg("02_artifacts_removed", img)

    if not is_tile_type:
        # P1-1: Remove floating pixels / disconnected regions
        img = remove_small_regions(img, min_region_pixels=5)

    _dbg("03_small_regions_removed", img)

    # Dithering removal: only on large images where 4x4 blocks are a small fraction.
    # Image2Pixel already handles dithering cleanup. Our detector uses 4x4 blocks which
    # falsely match legitimate color transitions on sprites under ~128px, creating holes.
    # Genesis/Mega Drive preserves dithering as an authentic technique at all sizes.
    _DITHER_CONSOLES = {"genesis", "mega_drive"}
    _max_dim = max(img.size)
    if console in _DITHER_CONSOLES:
        pass  # dithering is authentic for Genesis at all sizes
    elif _max_dim >= 128:
        img = detect_and_remove_dithering(img)
    # else: skip — 4x4 blocks are too coarse, causes false positives

    _dbg("04_dithering_removed", img)

    # Fix AI edge darkening on tiles before palette remapping
    if is_tile_type:
        img = normalize_tile_edge_brightness(img)

    # Resolve effective color limit: user override > console+era > NES-calibrated fallback
    if max_colors is not None:
        effective_max = max_colors
    elif _console_era_limit is not None:
        effective_max = _console_era_limit
    else:
        effective_max = _era_color_limits.get(
            era.lower() if isinstance(era, str) else "mid", 6
        )
    effective_max = max(2, min(16, effective_max))  # clamp to sane range
    if is_tile_type:
        effective_max = max(effective_max, 4)

    if palette_colors:
        # Explicit palette lock — remap to those exact colors
        img = remap_to_locked_palette(img, palette_colors)
    elif palette_mood and palette_mood.lower() != "auto":
        # Mood-aware filtering — restrict to mood-appropriate NES colors
        from .palette import get_mood_palette
        mood_palette = get_mood_palette(palette_mood)
        if mood_palette:
            img = remap_to_locked_palette(img, mood_palette)
            img = reduce_to_max_colors(img, max_colors=effective_max, method="merge")
    else:
        # No mood, no lock — reduce to era limits using iterative merge
        # (median-cut creates synthetic muddy colors on pixel art; reverted 2026-04-09d)
        if debug_dir:
            _dbg("05a_colors_median_cut", reduce_to_max_colors(img.copy(), max_colors=effective_max, method="median_cut"))
            _dbg("05b_colors_iterative_merge", reduce_to_max_colors(img.copy(), max_colors=effective_max, method="merge"))
        img = reduce_to_max_colors(img, max_colors=effective_max, method="merge")

    # P2: Close structural gaps in sprite body (reconnect fragmented body parts)
    # Must run after color reduction (which can create the gaps) and before trimming.
    # gap_size=2 bridges 2px gaps (ankles, wrists, weapon handles).
    # High-motion animations (attack/jump/death/cast) get gap_size=3 because
    # dramatic poses fragment more aggressively.
    _dbg("05_colors_reduced", img)

    _HIGH_MOTION_TYPES = {"attack", "jump", "death", "cast"}
    if not is_tile_type:
        gap = 3 if animation_type and animation_type.lower() in _HIGH_MOTION_TYPES else 2
        img = close_sprite_gaps(img, gap_size=gap)
        _dbg("06_gaps_closed", img)
        # Re-run small region removal after closing — any fragments that didn't
        # merge with the main body after closing are true artifacts.
        # Scale threshold by canvas size: at small sizes, 8px is a hand or foot.
        _min_region_2 = 4 if _canvas_pixels <= 256 else (6 if _canvas_pixels <= 1024 else 8)
        img = remove_small_regions(img, min_region_pixels=_min_region_2)
        _dbg("07_small_regions_removed_2", img)

    # Skip trimming for tiles — they need to stay at their full size
    if not is_tile_type:
        img = trim_transparent(img, padding=1)

    _dbg("08_final", img)
    return img


def generate_walk_frames(
    base_image: Image.Image,
    frame_count: int = 4,
) -> list[Image.Image]:
    """
    Generate walk cycle frames from a single base sprite.

    Splits the sprite into upper body and leg region, then shifts
    the leg pixels horizontally with a vertical bob to simulate
    stepping.  Matches NES convention (Castlevania, Mega Man):
    same upper body, legs alternate between 2-3 positions.

    Shift amplitude is proportional to sprite size so motion remains
    visible at gallery scale (previously ±1px which is invisible at
    32-40px width — only ~3% of the silhouette).

    Robed characters (wizard, cleric) have no distinguishable leg
    region.  When leg detection produces a single column of pixels,
    fall back to a body-sway pattern (alternating ±dx whole-body
    shift + bob) so the sprite still reads as moving.

    Returns a list of *frame_count* RGBA images.
    """
    from scipy.ndimage import label as ndimage_label

    img = base_image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    w, h = img.size

    if not np.any(arr[:, :, 3] > 0):
        return [img.copy() for _ in range(frame_count)]

    bbox = img.getbbox()
    if not bbox:
        return [img.copy() for _ in range(frame_count)]

    bx0, by0, bx1, by1 = bbox
    bw = bx1 - bx0
    bh = by1 - by0

    # Shift amplitude proportional to sprite width.  At 16px width,
    # leg_dx=1.  At 32-40px (gallery scale), leg_dx=2-3.  Larger
    # sprites get larger shifts so motion is visible at 4x display.
    leg_dx = max(1, bw // 14)
    bob_dy = max(1, bh // 24)

    # Leg region: bottom 30% of opaque content height
    leg_y = by0 + int(bh * 0.70)

    # Detect whether legs are actually distinguishable.  A thin band
    # at the top of the leg region is the cleanest signal: distinct
    # legs show as two separate blobs (the gap between them is real),
    # whereas robes/skirts show as one wide mass.  Width-based
    # heuristics get fooled by held items (staves, banners) that
    # inflate the bbox without crossing the leg region.
    leg_opaque = arr[leg_y:, :, 3] > 0
    leg_xs = np.where(leg_opaque.any(axis=0))[0]
    band_h = max(2, bh // 8)
    leg_top_band = arr[leg_y : leg_y + band_h, bx0:bx1, 3] > 0
    has_distinct_legs = False
    if leg_top_band.any():
        labeled_band, _ = ndimage_label(
            leg_top_band, structure=np.ones((3, 3), dtype=int),
        )
        sizes_band = np.bincount(labeled_band.ravel())
        sizes_band[0] = 0
        total_band = int(sizes_band.sum())
        if total_band:
            dominant_frac = int(sizes_band.max()) / total_band
            big_blobs = int((sizes_band >= 5).sum())
            has_distinct_legs = dominant_frac < 0.65 and big_blobs >= 2

    if not has_distinct_legs:
        # Robe fallback: gentle body sway + bob.  No leg split.
        # Each frame shifts the whole sprite slightly side-to-side
        # to suggest forward momentum (like a glide).
        sway_dx = max(1, bw // 24)
        if frame_count == 2:
            params = [(0, 0), (sway_dx, -bob_dy)]
        elif frame_count == 3:
            params = [(0, 0), (sway_dx, -bob_dy), (-sway_dx, 0)]
        else:
            params = [
                (0, 0),
                (sway_dx, -bob_dy),
                (0, bob_dy),
                (-sway_dx, -bob_dy),
            ]
        params = params[:frame_count]

        frames = []
        for dx, dy in params:
            if dx == 0 and dy == 0:
                frames.append(img.copy())
                continue
            frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            frame.paste(img, (dx, dy), img)
            frames.append(frame)
        return frames

    # Split into body (above leg_y) and two leg halves.
    # In side view, the front and back legs overlap horizontally.
    # Split at the leg region's horizontal midpoint — each half
    # shifts in opposite directions to create alternating steps.
    body_arr = arr.copy()
    body_arr[leg_y:, :, 3] = 0
    body_img = Image.fromarray(body_arr, "RGBA")

    leg_mid = int((leg_xs.min() + leg_xs.max()) / 2)

    # Front leg (left half of leg region) and back leg (right half)
    front_arr = arr.copy()
    front_arr[:leg_y, :, 3] = 0
    front_arr[leg_y:, leg_mid:, 3] = 0
    front_img = Image.fromarray(front_arr, "RGBA")

    back_arr = arr.copy()
    back_arr[:leg_y, :, 3] = 0
    back_arr[leg_y:, :leg_mid, 3] = 0
    back_img = Image.fromarray(back_arr, "RGBA")

    # Walk params: (front_dx, back_dx, bob_dy)
    # Front and back legs shift in OPPOSITE directions to create
    # alternating step.  Bob adds vertical bounce.  Amplitudes scale
    # with sprite size via leg_dx and bob_dy.
    if frame_count == 2:
        params = [(0, 0, 0), (leg_dx, -leg_dx, -bob_dy)]
    elif frame_count == 3:
        params = [(0, 0, 0), (leg_dx, -leg_dx, -bob_dy), (-leg_dx, leg_dx, -bob_dy)]
    else:  # 4-frame walk cycle
        params = [
            (0, 0, 0),                         # neutral stance
            (leg_dx, -leg_dx, -bob_dy),        # front leg forward, back leg back, bob up
            (0, 0, bob_dy),                    # passing through, bob down
            (-leg_dx, leg_dx, -bob_dy),        # front leg back, back leg forward, bob up
        ]
    params = params[:frame_count]

    frames = []
    for front_dx, back_dx, body_bob in params:
        if front_dx == 0 and back_dx == 0 and body_bob == 0:
            frames.append(img.copy())
            continue

        frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        # Body shifts only vertically (bob)
        frame.paste(body_img, (0, body_bob), body_img)
        # Front leg shifts one way
        frame.paste(front_img, (front_dx, body_bob), front_img)
        # Back leg shifts the other way
        frame.paste(back_img, (back_dx, body_bob), back_img)
        frames.append(frame)

    return frames


def generate_death_frames(
    base_image: Image.Image,
    frame_count: int = 4,
) -> list[Image.Image]:
    """
    Generate death animation frames from a single base sprite.

    Flash-and-dissolve approach:
      Frame 0 — normal sprite
      Frame 1 — white/bright silhouette flash (all opaque pixels
                shift toward white)
      Frame 2 — half the pixels dissolved to transparent, outside-in
                (edge pixels removed first)
      Frame 3 — mostly gone, only a few center pixels remain

    Matches NES convention: Mega Man flash-and-vanish, Zelda
    blink-and-gone.  More readable at any scale than shear/fall
    and more useful for game devs (dissolve is a common death
    pattern in engines).

    Returns a list of *frame_count* RGBA images.
    """
    from scipy.ndimage import distance_transform_edt

    img = base_image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    w, h = img.size

    if not np.any(arr[:, :, 3] > 0):
        return [img.copy() for _ in range(frame_count)]

    opaque = arr[:, :, 3] > 0

    # Build a distance-from-edge map: pixels at the silhouette edge
    # have distance 0, center pixels have the highest distance.
    # Used to dissolve outside-in.
    dist = distance_transform_edt(opaque).astype(np.float32)
    max_dist = dist.max() if dist.max() > 0 else 1.0

    # Death params: (flash_strength, dissolve_threshold)
    # flash_strength: 0.0 = normal colors, 1.0 = full white
    # dissolve_threshold: fraction of max_dist below which pixels
    #   are removed (0.0 = keep all, 1.0 = remove all)
    if frame_count == 2:
        params = [(0.0, 0.0), (0.8, 0.8)]
    elif frame_count == 3:
        params = [(0.0, 0.0), (0.8, 0.0), (0.0, 0.85)]
    else:  # 4-frame death
        params = [
            (0.0, 0.0),     # normal sprite
            (0.8, 0.0),     # white flash (no dissolve yet)
            (0.0, 0.55),    # half dissolved, edges gone
            (0.0, 0.85),    # mostly gone, center remnant
        ]
    params = params[:frame_count]

    frames = []
    for flash, dissolve_thresh in params:
        if flash == 0.0 and dissolve_thresh == 0.0:
            frames.append(img.copy())
            continue

        new_arr = arr.copy()

        # Apply white flash: lerp RGB toward white
        if flash > 0.0:
            rgb = new_arr[:, :, :3].astype(np.float32)
            white = np.full_like(rgb, 255.0)
            new_arr[:, :, :3] = np.clip(
                rgb + (white - rgb) * flash, 0, 255,
            ).astype(np.uint8)
            # Only affect opaque pixels
            new_arr[~opaque, :3] = 0

        # Apply dissolve: remove pixels whose distance from edge
        # is below the threshold (outside-in erosion)
        if dissolve_thresh > 0.0:
            cutoff = max_dist * dissolve_thresh
            dissolve_mask = opaque & (dist < cutoff)
            new_arr[dissolve_mask, 3] = 0

        frames.append(Image.fromarray(new_arr, "RGBA"))

    return frames


def generate_cast_frames(
    base_image: Image.Image,
    frame_count: int = 4,
) -> list[Image.Image]:
    """
    Generate cast/spell animation frames from a single base sprite.

    Minimal body movement (1px hand shift at most).  Visual interest
    comes from a glow effect emanating from the staff/hand area:
    bright pixels are added around the brightest cluster in the
    sprite, growing outward across frames.

    Matches NES RPG convention (Final Fantasy): tiny gesture, the
    spell effect is what you notice, not the body.

    Returns a list of *frame_count* RGBA images.
    """
    from scipy.ndimage import distance_transform_edt, label as ndimage_label

    img = base_image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    w, h = img.size

    if not np.any(arr[:, :, 3] > 0):
        return [img.copy() for _ in range(frame_count)]

    bbox = img.getbbox()
    if not bbox:
        return [img.copy() for _ in range(frame_count)]

    opaque = arr[:, :, 3] > 0

    # Find the magic source: the brightest SMALL cluster in the upper
    # portion of the sprite (staff tip, orb, hand glow).
    #
    # Previous code used "brightest color globally" which hit the
    # face/skin on pale characters (cleric, wizard beard).  Now:
    # 1. Restrict search to upper 50% of sprite
    # 2. For each bright color, prefer SMALL clusters (staff tips)
    #    over large ones (face, body highlights)
    bx0, by0, bx1, by1 = bbox
    bh = by1 - by0
    upper_limit = by0 + int(bh * 0.50)
    upper_opaque = opaque.copy()
    upper_opaque[upper_limit:, :] = False

    opaque_rgb = arr[opaque][:, :3]
    unique_colors = np.unique(opaque_rgb.reshape(-1, 3), axis=0)
    brightnesses = unique_colors.astype(int).sum(axis=1)

    # Score each color: brightness * isolation (prefer small clusters)
    best_score = -1.0
    brightest_color = unique_colors[np.argmax(brightnesses)]  # fallback
    for color, bright in zip(unique_colors, brightnesses):
        if bright < 100:
            continue  # skip very dark colors
        cmask = np.all(arr[:, :, :3] == color, axis=2) & upper_opaque
        count = int(np.count_nonzero(cmask))
        if count == 0:
            continue
        # Isolation score: small clusters score higher (staff tips ~5-30px,
        # faces ~50-200px).  Cap at 50 to avoid penalizing absent colors.
        isolation = 1.0 / max(count, 1)
        score = float(bright) * isolation
        if score > best_score:
            best_score = score
            brightest_color = color

    # Build a mask of the magic source pixels
    source_mask = (
        np.all(arr[:, :, :3] == brightest_color, axis=2) & opaque
    )
    if not np.any(source_mask):
        # Fallback: use upper-right quadrant
        source_mask = opaque.copy()
        source_mask[upper_limit:, :] = False
        source_mask[:, : bx0 + (bx1 - bx0) // 2] = False

    # Distance from magic source — used to grow glow outward
    source_dist = distance_transform_edt(~source_mask).astype(np.float32)

    # Glow color: white or near-white for NES flash
    glow_color = np.array([255, 255, 255], dtype=np.uint8)

    # Cast params: (hand_dy, glow_radius)
    # hand_dy: 0 or -1 only (minimal body movement)
    # glow_radius: how far glow extends from source (in pixels)
    # Radii are intentionally large — the glow IS the animation,
    # not the body movement.
    if frame_count == 2:
        params = [(0, 0), (-1, 8)]
    elif frame_count == 3:
        params = [(0, 0), (-1, 6), (0, 10)]
    else:  # 4-frame cast
        params = [
            (0, 0),      # ready stance — no glow
            (0, 3),      # charge — glow appears at source
            (-1, 8),     # casting — hand raises 1px, glow bursts out
            (0, 5),      # follow-through — hand returns, glow fading
        ]
    params = params[:frame_count]

    frames = []
    for hand_dy, glow_r in params:
        if hand_dy == 0 and glow_r == 0:
            frames.append(img.copy())
            continue

        new_arr = arr.copy()

        # Subtle hand/arm raise: shift only the top ~25% of content
        # up by 1px.  Body stays intact — no upper/lower split.
        # Start from a COPY of new_arr so unchanged rows keep their
        # original content (previous zero-init left a transparent
        # seam at the bottom of the shifted block that the glow code
        # then filled white, producing a visible horizontal bar
        # across the chest on wizard / similar sprites).
        if hand_dy != 0:
            bx0, by0, bx1, by1 = bbox
            bh = by1 - by0
            hand_y = by0 + int(bh * 0.25)
            abs_dy = abs(hand_dy)
            shifted = new_arr.copy()
            new_top = max(0, by0 - abs_dy)
            new_bot = hand_y - abs_dy
            src_top = by0
            src_bot = src_top + (new_bot - new_top)
            src_bot = min(src_bot, hand_y)
            new_bot = new_top + (src_bot - src_top)
            if new_bot > new_top:
                shifted[new_top:new_bot] = new_arr[src_top:src_bot]
            new_arr = shifted

        # Add glow pixels: transparent pixels near the magic source
        # become bright glow pixels, expanding outward by glow_r.
        if glow_r > 0:
            # Glow zone: pixels within glow_r of source, currently
            # transparent (adds NEW pixels, doesn't overwrite sprite)
            glow_zone = (source_dist > 0) & (source_dist <= glow_r)
            # Only add glow in transparent areas (don't overwrite body)
            add_glow = glow_zone & (new_arr[:, :, 3] == 0)
            # Glow only OUTSIDE the original sprite silhouette — never
            # paint over the character's face, hat, or body.
            for y, x in zip(*np.where(add_glow)):
                dist = source_dist[y, x]
                alpha = int(255 * (1.0 - dist / (glow_r + 1)))
                new_arr[y, x, :3] = glow_color
                new_arr[y, x, 3] = max(alpha, 160)

        frames.append(Image.fromarray(new_arr, "RGBA"))

    return frames


def generate_attack_frames(
    base_image: Image.Image,
    frame_count: int = 4,
) -> list[Image.Image]:
    """
    Generate attack animation frames from a single base sprite.

    Detects the weapon region (rightmost connected component or right-side
    pixels) and repositions it to simulate a swing arc. If weapon detection
    fails, falls back to a subtle body lean + thrust using horizontal shifts.

    Matches NES convention: Zelda used weapons as separate hardware sprites
    positioned relative to the character body.

    Returns a list of *frame_count* RGBA images.
    """
    from scipy.ndimage import label as ndimage_label

    img = base_image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    w, h = img.size
    alpha = arr[:, :, 3]
    opaque = alpha > 0

    if not np.any(opaque):
        return [img.copy() for _ in range(frame_count)]

    # Find bounding box of opaque content
    bbox = img.getbbox()
    if not bbox:
        return [img.copy() for _ in range(frame_count)]
    bx0, by0, bx1, by1 = bbox
    bw = bx1 - bx0
    bh = by1 - by0

    # Try to detect weapon: look for a secondary connected component
    # on the right side of the sprite (weapon held in right hand)
    labeled, num_regions = ndimage_label(opaque)
    weapon_mask = None
    body_mask = None

    if num_regions >= 2:
        # Find the largest region (body) and the rightmost other region (weapon)
        regions = []
        for rid in range(1, num_regions + 1):
            rmask = labeled == rid
            px_count = int(np.count_nonzero(rmask))
            ys, xs = np.where(rmask)
            cx = float(np.mean(xs))
            regions.append((rid, px_count, cx, rmask))
        regions.sort(key=lambda r: r[1], reverse=True)

        body_region = regions[0]
        # Look for a weapon-sized region to the right of body center
        body_cx = body_region[2]
        for rid, px_count, cx, rmask in regions[1:]:
            # Weapon should be: 3-40% of body size, to the right
            if 0.03 * body_region[1] < px_count < 0.40 * body_region[1] and cx > body_cx:
                weapon_mask = rmask
                body_mask = body_region[3]
                break

    # === Detect which side has the weapon ===
    # The weapon is a protrusion — pixels extending beyond the body's
    # median width.  Compare left vs right protrusion to determine
    # weapon side.  Previous code always assumed right; now auto-detect.
    weapon_on_left = False
    if weapon_mask is None:
        row_centers = []
        row_half_widths = []
        for y in range(by0, by1):
            xs_row = np.where(opaque[y])[0]
            if len(xs_row) > 0:
                row_centers.append((xs_row.max() + xs_row.min()) / 2.0)
                row_half_widths.append((xs_row.max() - xs_row.min()) / 2.0)
        if row_centers:
            med_center = float(np.median(row_centers))
            med_hw = float(np.median(row_half_widths))
            left_pro = 0.0
            right_pro = 0.0
            upper_y = by0 + int(bh * 0.70)
            for y in range(by0, upper_y):
                xs_row = np.where(opaque[y])[0]
                if len(xs_row) == 0:
                    continue
                l_ext = med_center - xs_row.min()
                r_ext = xs_row.max() - med_center
                if l_ext > med_hw:
                    left_pro += l_ext - med_hw
                if r_ext > med_hw:
                    right_pro += r_ext - med_hw
            weapon_on_left = left_pro > right_pro

    # Use separate weapon component if found, otherwise use protrusion mask.
    # The protrusion mask captures pixels that extend beyond the body's
    # median edge on the weapon side — this is the arm + weapon as a
    # natural unit, not a fixed-percentage slice of the sprite.
    if weapon_mask is not None and body_mask is not None:
        arm_mask = weapon_mask
    else:
        upper_y = by0 + int(bh * 0.70)
        # Compute median edges (body outline)
        left_edges = []
        right_edges = []
        for y in range(by0, by1):
            xs_row = np.where(opaque[y])[0]
            if len(xs_row) > 0:
                left_edges.append(xs_row.min())
                right_edges.append(xs_row.max())
        med_left = int(np.median(left_edges)) if left_edges else bx0
        med_right = int(np.median(right_edges)) if right_edges else bx1

        arm_mask = np.zeros_like(opaque)
        for y in range(by0, upper_y):
            xs_row = np.where(opaque[y])[0]
            if len(xs_row) == 0:
                continue
            if weapon_on_left:
                # Protrusion: pixels extending left of median left edge
                if xs_row.min() < med_left:
                    arm_mask[y, xs_row.min():med_left] = opaque[y, xs_row.min():med_left]
            else:
                # Protrusion: pixels extending right of median right edge
                if xs_row.max() > med_right:
                    arm_mask[y, med_right:xs_row.max() + 1] = opaque[y, med_right:xs_row.max() + 1]
        if np.count_nonzero(arm_mask) < 3:
            arm_mask = None

    if arm_mask is not None:
        # Extract arm region pixels
        ay, ax = np.where(arm_mask)
        ay0, ay1 = int(ay.min()), int(ay.max()) + 1
        ax0, ax1 = int(ax.min()), int(ax.max()) + 1
        arm_crop = img.crop((ax0, ay0, ax1, ay1))

        # Create body-only image.  Keep a 2px "shoulder bridge" at the
        # body-side edge of the arm region so it stays connected when
        # the arm shifts outward.
        bridge_margin = 2
        body_erase = arm_mask.copy()
        if weapon_on_left:
            # Bridge on the RIGHT edge of the arm region (toward body)
            body_erase[:, ax1 - bridge_margin:] = False
        else:
            # Bridge on the LEFT edge of the arm region (toward body)
            body_erase[:, :ax0 + bridge_margin] = False
        body_arr = arr.copy()
        body_arr[body_erase, 3] = 0
        body_img = Image.fromarray(body_arr, "RGBA")

        # Scale swing offsets to sprite size.  Offsets must be large
        # enough to read as a swing at 4x scale (previous bw//8 was
        # too conservative — 3-4px on a 32px sprite is invisible).
        arm_w = ax1 - ax0
        max_dx = max(3, bw // 5)
        max_dy = max(2, bh // 8)

        # Detect facing direction from lower-body pixel density.
        # The front of the character (face, chest) has more pixels
        # than the back.  Using lower 50% avoids weapon influence.
        # Facing direction determines swing direction — weapon swings
        # TOWARD the direction the character faces, regardless of
        # which side the weapon protrudes from.
        lower_y_face = by0 + int(bh * 0.50)
        mid_x = (bx0 + bx1) // 2
        lower_left = int(np.count_nonzero(opaque[lower_y_face:by1, :mid_x]))
        lower_right = int(np.count_nonzero(opaque[lower_y_face:by1, mid_x:]))
        faces_right = lower_right >= lower_left
        swing_dir = 1 if faces_right else -1

        # Offsets: (arm_dx, arm_dy, body_dx)
        # Weapon side swings outward, body stays anchored.
        # Rest frame pulls the weapon BACK (opposite swing_dir) so the
        # subsequent forward arc has somewhere to go.  Without this,
        # the rest pose already shows the weapon extended and the
        # swing reads as a wobble instead of a strike.
        back_offset = max(1, max_dx // 3)
        if frame_count == 2:
            offsets = [
                (-back_offset * swing_dir, 0, 0),
                (max_dx * swing_dir, -max_dy // 2 or -1, 0),
            ]
        else:
            offsets = [
                (-back_offset * swing_dir, 0, 0),                              # rest: weapon pulled back
                (-(back_offset + 1) * swing_dir, -max_dy, 0),                  # wind-up: further back + up
                (max_dx * swing_dir, 0, 0),                                    # peak swing
                (max(1, max_dx // 3) * swing_dir, max_dy // 2 or 1, -swing_dir),  # follow-through + recoil
            ][:frame_count]

        # Use 8-connectivity (diagonal neighbors count) for the
        # connectivity check.  Pixel art arms often connect to the body
        # via a single diagonal pixel; 4-connectivity breaks these.
        struct_8conn = np.ones((3, 3), dtype=int)

        # Measure baseline component count (body + arm at rest may
        # already be >1 due to small artifacts in the base sprite).
        base_frame = body_img.copy()
        base_frame.paste(arm_crop, (ax0, ay0), arm_crop)
        _, base_components = ndimage_label(
            np.array(base_frame)[:, :, 3] > 0, structure=struct_8conn,
        )

        # Identify the peak swing frame index (largest abs(dx)).
        # The connectivity guard must NOT constrain this frame —
        # disconnection at peak extension is the visual climax,
        # not a bug.  Previous code halved the offset toward zero
        # on every frame, killing the animation.
        peak_idx = max(range(len(offsets)), key=lambda i: abs(offsets[i][0]))

        frames = []
        for frame_idx, (dx, dy, bdx) in enumerate(offsets):
            # Compose: body + arm at swing position
            frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            frame.paste(body_img, (bdx, 0), body_img)
            paste_x = max(0, min(w - arm_w, ax0 + dx + bdx))
            paste_y = max(0, min(h - (ay1 - ay0), ay0 + dy))
            frame.paste(arm_crop, (paste_x, paste_y), arm_crop)

            # Connectivity check — SKIP for peak swing frame.
            # At peak extension the weapon SHOULD separate from
            # the body (sword at full reach).  Only guard wind-up
            # and follow-through frames.
            if frame_idx != peak_idx:
                frame_alpha = np.array(frame)[:, :, 3] > 0
                _, n_components = ndimage_label(frame_alpha, structure=struct_8conn)
                cur_dx, cur_dy = dx, dy
                attempts = 0
                while n_components > base_components and attempts < 3:
                    attempts += 1
                    cur_dx = cur_dx // 2
                    cur_dy = cur_dy // 2
                    frame = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                    frame.paste(body_img, (bdx, 0), body_img)
                    paste_x = max(0, min(w - arm_w, ax0 + cur_dx + bdx))
                    paste_y = max(0, min(h - (ay1 - ay0), ay0 + cur_dy))
                frame.paste(arm_crop, (paste_x, paste_y), arm_crop)
                frame_alpha = np.array(frame)[:, :, 3] > 0
                _, n_components = ndimage_label(frame_alpha, structure=struct_8conn)

            frames.append(frame)
        return frames

    # === Last resort fallback: whole-body lunge ===
    max_lunge = max(1, bw // 8)
    if frame_count == 2:
        offsets = [(0, 0), (max_lunge, -1)]
    else:
        offsets = [
            (0, 0),
            (-1, -1),
            (max_lunge, 0),
            (max_lunge // 2, 0),
        ][:frame_count]

    frames = []
    for dx, dy in offsets:
        shifted = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        shifted.paste(img, (dx, dy))
        frames.append(shifted)
    return frames


def composite_horizontal(
    frames: list[Image.Image],
    pad_to_multiple_of: int = 8,
) -> Image.Image:
    """
    Stitch individual frames into a horizontal strip.

    All frames are padded to uniform dimensions (max width × max height,
    each rounded up to *pad_to_multiple_of*), then pasted left-to-right.

    Returns a single RGBA image of size ``(uniform_w * len(frames), uniform_h)``.
    """
    import math

    if not frames:
        return Image.new("RGBA", (8, 8), (0, 0, 0, 0))

    max_w = max(f.width for f in frames)
    max_h = max(f.height for f in frames)
    pad_w = math.ceil(max_w / pad_to_multiple_of) * pad_to_multiple_of or pad_to_multiple_of
    pad_h = math.ceil(max_h / pad_to_multiple_of) * pad_to_multiple_of or pad_to_multiple_of

    canvas = Image.new("RGBA", (pad_w * len(frames), pad_h), (0, 0, 0, 0))
    for i, frame in enumerate(frames):
        # Snap centering offsets to a multiple of pad_to_multiple_of so each
        # frame's content stays on the tile grid it was enforced on (a non-
        # grid-aligned paste re-breaks per-tile color caps on strict consoles
        # like c64_hires). pad_w is already a multiple, so the cell origin is
        # grid-aligned; this snaps the intra-cell centering too.
        m = pad_to_multiple_of
        paste_x = i * pad_w + (((pad_w - frame.width) // 2 // m) * m)
        paste_y = ((pad_h - frame.height) // 2 // m) * m
        canvas.paste(frame, (paste_x, paste_y))

    return canvas


def composite_grid(
    tiles: dict[str, Image.Image],
    grid: int = 3,
    pad_to_multiple_of: int = 8,
) -> Image.Image:
    """
    Stitch named tiles into a grid (e.g. 3×3 for tilesets).

    Tile names follow the same convention as ``slice_tileset()``:
    top_left, top, top_right, left, center, right,
    bottom_left, bottom, bottom_right.

    Returns a single RGBA image.
    """
    import math

    _NAMES_3X3 = [
        "top_left",    "top",    "top_right",
        "left",        "center", "right",
        "bottom_left", "bottom", "bottom_right",
    ]

    all_tiles = [tiles[name] for name in _NAMES_3X3 if name in tiles]
    if not all_tiles:
        return Image.new("RGBA", (8, 8), (0, 0, 0, 0))

    max_w = max(t.width for t in all_tiles)
    max_h = max(t.height for t in all_tiles)
    pad_w = math.ceil(max_w / pad_to_multiple_of) * pad_to_multiple_of or pad_to_multiple_of
    pad_h = math.ceil(max_h / pad_to_multiple_of) * pad_to_multiple_of or pad_to_multiple_of

    _POS_MAP = {
        "top_left": (0, 0), "top": (0, 1), "top_right": (0, 2),
        "left": (1, 0), "center": (1, 1), "right": (1, 2),
        "bottom_left": (2, 0), "bottom": (2, 1), "bottom_right": (2, 2),
    }

    canvas = Image.new("RGBA", (pad_w * grid, pad_h * grid), (0, 0, 0, 0))
    for name, tile in tiles.items():
        if name not in _POS_MAP:
            continue
        row, col = _POS_MAP[name]
        canvas.paste(tile, (col * pad_w, row * pad_h))

    return canvas


def slice_tileset(
    image: Image.Image,
    grid: int = 3,
) -> dict[str, Image.Image]:
    """
    Slice a generated tileset image into individual connected tiles.

    Expects a 3×3 grid image (or NxN if grid is changed). Divides evenly
    and returns a dict keyed by position name.

    For a 3×3 grid, the keys are:
        top_left, top, top_right,
        left, center, right,
        bottom_left, bottom, bottom_right

    Each tile is cropped to the grid cell size and padded to a multiple of 8.

    Parameters
    ----------
    image:
        RGBA PIL Image containing the tileset grid.
    grid:
        Grid size (default 3 for a 3×3 connected tileset).

    Returns
    -------
    dict[str, Image.Image]
        Named tiles keyed by position.
    """
    import math

    img = image.convert("RGBA")
    w, h = img.size
    cell_w = w // grid
    cell_h = h // grid

    _NAMES_3X3 = [
        "top_left",    "top",    "top_right",
        "left",        "center", "right",
        "bottom_left", "bottom", "bottom_right",
    ]

    tiles: dict[str, Image.Image] = {}
    for row in range(grid):
        for col in range(grid):
            idx = row * grid + col
            name = _NAMES_3X3[idx] if grid == 3 and idx < len(_NAMES_3X3) else f"tile_{row}_{col}"

            x0 = col * cell_w
            y0 = row * cell_h
            x1 = x0 + cell_w
            y1 = y0 + cell_h
            cell = img.crop((x0, y0, x1, y1))

            # Pad to multiple of 8
            cw, ch = cell.size
            pad_w = math.ceil(cw / 8) * 8
            pad_h = math.ceil(ch / 8) * 8
            if pad_w != cw or pad_h != ch:
                canvas = Image.new("RGBA", (pad_w, pad_h), (0, 0, 0, 0))
                canvas.paste(cell, (0, 0))
                cell = canvas

            tiles[name] = cell

    return tiles

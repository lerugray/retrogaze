"""
Sprite quality analysis — generates text reports for debate agents.

Detects disconnected regions, floating pixels, broken outlines,
palette drift, and silhouette consistency across frames.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image
from scipy.ndimage import label as ndimage_label


def analyze_sprite(image: Image.Image) -> dict:
    """Analyze a single sprite image and return metrics."""
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    h, w = arr.shape[:2]
    alpha = arr[:, :, 3]
    opaque_mask = alpha > 0
    opaque_count = int(np.count_nonzero(opaque_mask))
    total = h * w

    result = {
        "size": (w, h),
        "opaque_pixels": opaque_count,
        "transparent_pixels": total - opaque_count,
    }

    if opaque_count == 0:
        result["connected_regions"] = 0
        result["regions"] = []
        result["color_count"] = 0
        result["colors"] = []
        result["symmetry_h"] = 0.0
        return result

    # Connected component analysis (4-connectivity for strict pixel art)
    labeled, num_regions = ndimage_label(opaque_mask)
    regions = []
    for rid in range(1, num_regions + 1):
        region_mask = labeled == rid
        pixel_count = int(np.count_nonzero(region_mask))
        ys, xs = np.where(region_mask)
        centroid = (int(np.mean(xs)), int(np.mean(ys)))
        regions.append({
            "id": rid,
            "pixels": pixel_count,
            "centroid": centroid,
            "is_artifact": pixel_count < 5,
        })
    regions.sort(key=lambda r: r["pixels"], reverse=True)

    result["connected_regions"] = num_regions
    result["regions"] = regions
    result["floating_pixels"] = sum(1 for r in regions if r.get("is_artifact", False))

    # Color palette
    opaque_colors = arr[opaque_mask][:, :3]
    unique_colors = np.unique(opaque_colors.reshape(-1, 3), axis=0)
    result["color_count"] = len(unique_colors)
    result["colors"] = [
        f"#{r:02x}{g:02x}{b:02x}" for r, g, b in unique_colors
    ]

    # Horizontal symmetry
    bbox = img.getbbox()
    if bbox:
        cropped = opaque_mask[bbox[1]:bbox[3], bbox[0]:bbox[2]]
        flipped = np.fliplr(cropped)
        # Pad to same size if needed
        mh, mw = max(cropped.shape[0], flipped.shape[0]), max(cropped.shape[1], flipped.shape[1])
        c_pad = np.zeros((mh, mw), dtype=bool)
        f_pad = np.zeros((mh, mw), dtype=bool)
        c_pad[:cropped.shape[0], :cropped.shape[1]] = cropped
        f_pad[:flipped.shape[0], :flipped.shape[1]] = flipped
        match = (c_pad == f_pad).mean()
        result["symmetry_h"] = round(float(match) * 100, 1)
    else:
        result["symmetry_h"] = 0.0

    return result


def compare_frames(frame0: Image.Image, frame_n: Image.Image) -> dict:
    """Compare two frames for consistency."""
    a0 = analyze_sprite(frame0)
    an = analyze_sprite(frame_n)

    # Silhouette IoU — crop both to bounding boxes first
    def get_cropped_mask(img):
        arr = np.array(img.convert("RGBA"), dtype=np.uint8)
        mask = arr[:, :, 3] > 0
        bbox = img.convert("RGBA").getbbox()
        if bbox:
            return mask[bbox[1]:bbox[3], bbox[0]:bbox[2]]
        return mask

    m0 = get_cropped_mask(frame0)
    mn = get_cropped_mask(frame_n)

    # Resize to same dimensions for comparison
    target_h = max(m0.shape[0], mn.shape[0])
    target_w = max(m0.shape[1], mn.shape[1])
    p0 = np.zeros((target_h, target_w), dtype=bool)
    pn = np.zeros((target_h, target_w), dtype=bool)
    p0[:m0.shape[0], :m0.shape[1]] = m0
    pn[:mn.shape[0], :mn.shape[1]] = mn

    intersection = int((p0 & pn).sum())
    union = int((p0 | pn).sum())
    iou = round(intersection / union * 100, 1) if union > 0 else 0.0

    # Color overlap
    colors_0 = set(a0["colors"])
    colors_n = set(an["colors"])
    shared = colors_0 & colors_n
    new_colors = colors_n - colors_0

    # Bounding box size comparison
    bb0 = frame0.convert("RGBA").getbbox() or (0, 0, 0, 0)
    bbn = frame_n.convert("RGBA").getbbox() or (0, 0, 0, 0)
    size0 = (bb0[2] - bb0[0], bb0[3] - bb0[1])
    sizen = (bbn[2] - bbn[0], bbn[3] - bbn[1])

    return {
        "silhouette_iou": iou,
        "color_overlap": f"{len(shared)}/{len(colors_n)}",
        "new_colors": len(new_colors),
        "palette_drift": list(new_colors)[:10],
        "size_frame0": size0,
        "size_frame_n": sizen,
        "size_delta": (sizen[0] - size0[0], sizen[1] - size0[1]),
    }


def generate_report(
    images: list[Image.Image],
    names: list[str] | None = None,
) -> str:
    """Generate a full text analysis report for a set of sprite frames."""
    if not images:
        return "No images to analyze."

    if names is None:
        names = [f"frame_{i}" for i in range(len(images))]

    lines = []

    for i, (img, name) in enumerate(zip(images, names)):
        a = analyze_sprite(img)
        lines.append(f"SPRITE ANALYSIS: {name}")
        lines.append(f"  Size: {a['size'][0]}x{a['size'][1]}  |  "
                     f"Opaque: {a['opaque_pixels']}px  |  "
                     f"Transparent: {a['transparent_pixels']}px")

        if a["connected_regions"] == 1:
            lines.append(f"  Connected regions: 1  (no floating pixels)")
        else:
            warn = "  [WARNING]" if a.get("floating_pixels", 0) > 0 else ""
            lines.append(f"  Connected regions: {a['connected_regions']}{warn}")
            for r in a.get("regions", []):
                tag = " — likely artifact" if r.get("is_artifact", False) else " (main body)"
                lines.append(f"    Region {r['id']}: {r['pixels']}px "
                            f"at {r['centroid']}{tag}")

        lines.append(f"  Color count: {a['color_count']}")
        lines.append(f"  Horizontal symmetry: {a['symmetry_h']}%")
        lines.append("")

    # Cross-frame comparison if multiple frames
    if len(images) > 1:
        lines.append("CROSS-FRAME COMPARISON:")
        ref = images[0]
        for i in range(1, len(images)):
            comp = compare_frames(ref, images[i])
            lines.append(f"  {names[0]} vs {names[i]}:")
            lines.append(f"    Silhouette IoU: {comp['silhouette_iou']}%")
            lines.append(f"    Color overlap: {comp['color_overlap']} colors shared")
            if comp["new_colors"] > 0:
                lines.append(f"    [WARNING] Palette drift: {comp['new_colors']} new colors")
            delta = comp["size_delta"]
            if abs(delta[0]) > 4 or abs(delta[1]) > 4:
                lines.append(f"    [WARNING] Size mismatch: {comp['size_frame0']} vs "
                           f"{comp['size_frame_n']} (delta: {delta})")
            else:
                lines.append(f"    Size: {comp['size_frame0']} vs {comp['size_frame_n']}")
            lines.append("")

    return "\n".join(lines)


def analyze_directory(directory: str | Path) -> str:
    """Analyze all processed frames in a test output directory."""
    d = Path(directory)
    if not d.exists():
        return f"Directory not found: {d}"

    # Find processed frames (processed_frame_*.png or processed_*.png for tiles)
    frame_files = sorted(d.glob("processed_frame_*.png"))
    if not frame_files:
        # Try tile names
        tile_names = ["center", "top", "bottom", "left", "right",
                      "top_left", "top_right", "bottom_left", "bottom_right"]
        frame_files = [d / f"processed_{n}.png" for n in tile_names
                      if (d / f"processed_{n}.png").exists()]

    if not frame_files:
        # Single processed image
        p = d / "processed.png"
        if p.exists():
            frame_files = [p]

    if not frame_files:
        return f"No processed images found in: {d}"

    images = [Image.open(str(f)).convert("RGBA") for f in frame_files]
    names = [f.stem for f in frame_files]

    report = generate_report(images, names)

    for img in images:
        img.close()

    return report

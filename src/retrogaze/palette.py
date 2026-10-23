"""
NES 2C02 PPU palette definition and color remapping utilities.

Implements perceptually-accurate nearest-color matching using CIE76 Lab color distance.
RGB -> Lab conversion is done manually using standard sRGB -> XYZ -> Lab formulas.
"""

from __future__ import annotations

import copy
import math
import numpy as np
from PIL import Image

# ---------------------------------------------------------------------------
# NES 2C02G canonical palette — 56 entries (some duplicates are intentional)
# ---------------------------------------------------------------------------

_NES_PALETTE_HEX: list[str] = [
    # Row 0  (indices $00–$0D)
    "#626262", "#002C88", "#1B0076", "#3B0076",
    "#560044", "#5A0002", "#4F0800", "#351000",
    "#1A1802", "#002E00", "#003200", "#002A14",
    "#00234A", "#000000",
    # Row 1  (indices $10–$1D)
    "#ABABAB", "#0D56D0", "#4220D0", "#6A12C2",
    "#92088A", "#9A1032", "#913800", "#7A5400",
    "#536800", "#0E7800", "#007A00", "#007028",
    "#006486", "#000000",
    # Row 2  (indices $20–$2D)
    "#FFFFFF", "#4CA0FE", "#7C78FE", "#A862FE",
    "#D85CFE", "#E47ABA", "#E09264", "#C8B216",
    "#A0CC00", "#6ADA02", "#46E438", "#3AD67E",
    "#3EC4D2", "#4E4E4E",
    # Row 3  (indices $30–$3D)
    "#FFFFFF", "#B6D8FE", "#C8C4FE", "#DAB8FE",
    "#EEBAFE", "#F4C4E2", "#F0CEB2", "#E4DE94",
    "#D0E882", "#BCF07E", "#B0F29C", "#ACF0C2",
    "#B2ECEE", "#ACACAC",
]

# PPU register strings corresponding to each palette entry
_NES_PPU_REGISTERS: list[str] = [
    "$00", "$01", "$02", "$03", "$04", "$05", "$06", "$07",
    "$08", "$09", "$0A", "$0B", "$0C", "$0D",
    "$10", "$11", "$12", "$13", "$14", "$15", "$16", "$17",
    "$18", "$19", "$1A", "$1B", "$1C", "$1D",
    "$20", "$21", "$22", "$23", "$24", "$25", "$26", "$27",
    "$28", "$29", "$2A", "$2B", "$2C", "$2D",
    "$30", "$31", "$32", "$33", "$34", "$35", "$36", "$37",
    "$38", "$39", "$3A", "$3B", "$3C", "$3D",
]


def _hex_to_rgb(hex_str: str) -> tuple[int, int, int]:
    h = hex_str.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


# Build the palette as a list of RGB tuples once at module load time
NES_PALETTE_RGB: list[tuple[int, int, int]] = [_hex_to_rgb(h) for h in _NES_PALETTE_HEX]


# ---------------------------------------------------------------------------
# sRGB → CIE Lab conversion (manual implementation, no colormath dependency)
# ---------------------------------------------------------------------------

def _srgb_to_linear(c: float) -> float:
    """Gamma-decode one sRGB channel (0.0–1.0) to linear light."""
    if c <= 0.04045:
        return c / 12.92
    return ((c + 0.055) / 1.055) ** 2.4


def _linear_to_xyz(r: float, g: float, b: float) -> tuple[float, float, float]:
    """Convert linear-light RGB to CIE XYZ (D65 illuminant, sRGB primaries)."""
    x = r * 0.4124564 + g * 0.3575761 + b * 0.1804375
    y = r * 0.2126729 + g * 0.7151522 + b * 0.0721750
    z = r * 0.0193339 + g * 0.1191920 + b * 0.9503041
    return x, y, z


_D65_XN = 0.95047
_D65_YN = 1.00000
_D65_ZN = 1.08883


def _f_lab(t: float) -> float:
    delta = 6.0 / 29.0
    if t > delta ** 3:
        return t ** (1.0 / 3.0)
    return t / (3.0 * delta ** 2) + 4.0 / 29.0


def _xyz_to_lab(x: float, y: float, z: float) -> tuple[float, float, float]:
    """Convert CIE XYZ to CIE Lab (D65 illuminant)."""
    fx = _f_lab(x / _D65_XN)
    fy = _f_lab(y / _D65_YN)
    fz = _f_lab(z / _D65_ZN)
    L = 116.0 * fy - 16.0
    a = 500.0 * (fx - fy)
    b = 200.0 * (fy - fz)
    return L, a, b


def rgb_to_lab(r: int, g: int, b: int) -> tuple[float, float, float]:
    """Convert an 8-bit RGB triplet to CIE Lab."""
    lr = _srgb_to_linear(r / 255.0)
    lg = _srgb_to_linear(g / 255.0)
    lb = _srgb_to_linear(b / 255.0)
    x, y, z = _linear_to_xyz(lr, lg, lb)
    return _xyz_to_lab(x, y, z)


# ---------------------------------------------------------------------------
# Pre-compute Lab values for the entire NES palette (constant at import time)
# ---------------------------------------------------------------------------

_NES_PALETTE_LAB: list[tuple[float, float, float]] = [
    rgb_to_lab(r, g, b) for r, g, b in NES_PALETTE_RGB
]

# Also build a numpy array for fast vectorised distance computation
_NES_LAB_ARRAY = np.array(_NES_PALETTE_LAB, dtype=np.float64)  # shape (56, 3)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def find_nearest_nes_color(r: int, g: int, b: int) -> tuple[int, int, int, int]:
    """
    Find the perceptually nearest NES color to the given RGB triplet.

    Returns (nearest_r, nearest_g, nearest_b, nes_index) where nes_index is the
    0-based index into NES_PALETTE_RGB.
    """
    lab = rgb_to_lab(r, g, b)
    lab_arr = np.array(lab, dtype=np.float64)
    diffs = _NES_LAB_ARRAY - lab_arr  # (56, 3)
    distances = np.einsum("ij,ij->i", diffs, diffs)  # squared CIE76 distances
    idx = int(np.argmin(distances))
    nr, ng, nb = NES_PALETTE_RGB[idx]
    return nr, ng, nb, idx


def get_nes_palette_index(r: int, g: int, b: int) -> str:
    """
    Return the NES PPU register hex string (e.g. "$0F") for the nearest palette entry.
    """
    _, _, _, idx = find_nearest_nes_color(r, g, b)
    return _NES_PPU_REGISTERS[idx]


def remap_to_nes_palette(image: Image.Image) -> Image.Image:
    """
    Remap every pixel in *image* to its perceptually nearest NES 2C02 color.

    Transparent pixels (alpha == 0) are preserved as fully transparent.
    Returns a new RGBA PIL Image.
    """
    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)  # (H, W, 4)
    h, w = arr.shape[:2]

    # Extract RGB channels; flat view for vectorised processing
    rgb_flat = arr[:, :, :3].reshape(-1, 3).astype(np.float64)  # (N, 3)
    alpha_flat = arr[:, :, 3].reshape(-1)                        # (N,)

    # Vectorised sRGB -> linear
    def srgb_to_linear_arr(c_arr: np.ndarray) -> np.ndarray:
        out = np.where(c_arr <= 0.04045, c_arr / 12.92, ((c_arr + 0.055) / 1.055) ** 2.4)
        return out

    norm = rgb_flat / 255.0
    lin = srgb_to_linear_arr(norm)  # (N, 3)

    # linear RGB -> XYZ
    M = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ], dtype=np.float64)
    xyz = lin @ M.T  # (N, 3)

    # XYZ -> Lab
    xyz_n = xyz / np.array([_D65_XN, _D65_YN, _D65_ZN])
    delta = 6.0 / 29.0
    delta3 = delta ** 3
    f = np.where(xyz_n > delta3, xyz_n ** (1.0 / 3.0), xyz_n / (3.0 * delta ** 2) + 4.0 / 29.0)
    L_arr = 116.0 * f[:, 1] - 16.0
    a_arr = 500.0 * (f[:, 0] - f[:, 1])
    b_arr = 200.0 * (f[:, 1] - f[:, 2])
    lab_pixels = np.stack([L_arr, a_arr, b_arr], axis=1)  # (N, 3)

    # Nearest-neighbor in Lab space: (N, 1, 3) - (1, 56, 3) -> (N, 56, 3)
    # Compute squared distances; process in chunks to avoid huge memory usage
    chunk = 4096
    nearest_idx = np.empty(h * w, dtype=np.int32)
    for start in range(0, h * w, chunk):
        end = min(start + chunk, h * w)
        diff = lab_pixels[start:end, np.newaxis, :] - _NES_LAB_ARRAY[np.newaxis, :, :]
        sq = np.einsum("ijk,ijk->ij", diff, diff)
        nearest_idx[start:end] = np.argmin(sq, axis=1)

    # Map indices back to RGB
    palette_arr = np.array(NES_PALETTE_RGB, dtype=np.uint8)  # (56, 3)
    mapped_rgb = palette_arr[nearest_idx]  # (N, 3)

    # Restore transparent pixels
    transparent = alpha_flat == 0
    out_rgba = np.concatenate([mapped_rgb, alpha_flat[:, np.newaxis]], axis=1).astype(np.uint8)
    out_rgba[transparent] = [0, 0, 0, 0]

    out_arr = out_rgba.reshape(h, w, 4)
    return Image.fromarray(out_arr, mode="RGBA")


def remap_to_palette(
    image: Image.Image,
    palette_rgb: list[tuple[int, int, int]],
    dither: bool | str = False,
) -> Image.Image:
    """
    Remap every pixel in *image* to its perceptually nearest color from
    an arbitrary palette.

    Parameters
    ----------
    dither:
        ``False`` or ``"none"`` — Lab-space nearest-neighbor (hard snap).
        ``True`` or ``"floyd-steinberg"`` — Floyd-Steinberg error diffusion
        via Pillow's quantize(). Smooth gradient transitions.
        ``"bayer"`` — ordered Bayer 4x4 dithering. Regular grid pattern
        characteristic of Genesis/Mega Drive art.

    Transparent pixels are preserved in all modes.
    """
    if dither is True or dither == "floyd-steinberg":
        return _remap_with_dither(image, palette_rgb)
    if dither == "bayer":
        return _remap_with_bayer(image, palette_rgb)
    return _remap_nearest(image, palette_rgb)


def _remap_with_dither(
    image: Image.Image,
    palette_rgb: list[tuple[int, int, int]],
) -> Image.Image:
    """Floyd-Steinberg dithered remap via Pillow quantize()."""
    from PIL import Image as PILImage
    if not palette_rgb:
        raise ValueError("palette_rgb must contain at least one color")
    if len(palette_rgb) > 256:
        raise ValueError(
            f"palette_rgb has {len(palette_rgb)} colors; Pillow mode 'P' supports at most 256"
        )

    img = image.convert("RGBA")
    alpha = img.split()[3]

    # Build a palette image for Pillow's quantize()
    # Palette image must be mode "P" with the target colors
    flat_palette = []
    for r, g, b in palette_rgb:
        flat_palette.extend([r, g, b])
    # Pad to 256 colors (Pillow requires exactly 768 bytes). Pad with a real
    # palette color so quantization candidates remain within palette_rgb.
    if len(palette_rgb) < 256:
        flat_palette.extend(list(palette_rgb[0]) * (256 - len(palette_rgb)))

    palette_img = PILImage.new("P", (1, 1))
    palette_img.putpalette(flat_palette)

    # Quantize with Floyd-Steinberg dithering
    rgb = img.convert("RGB")
    quantized = rgb.quantize(
        colors=len(palette_rgb),
        palette=palette_img,
        dither=PILImage.Dither.FLOYDSTEINBERG,
    )
    result = quantized.convert("RGB")

    # Restore alpha channel — transparent pixels stay transparent
    result_rgba = result.convert("RGBA")
    result_rgba.putalpha(alpha)

    # Zero out RGB on fully transparent pixels
    arr = np.array(result_rgba)
    arr[arr[:, :, 3] == 0] = [0, 0, 0, 0]
    return PILImage.fromarray(arr, mode="RGBA")


# Bayer 4x4 threshold matrix (normalized to 0..1 range)
# Produces the ordered grid pattern characteristic of Genesis/Mega Drive art
_BAYER_4X4 = np.array([
    [ 0,  8,  2, 10],
    [12,  4, 14,  6],
    [ 3, 11,  1,  9],
    [15,  7, 13,  5],
], dtype=np.float64)
_BAYER_4X4 = (_BAYER_4X4 + 0.5) / 16.0 - 0.5  # zero-mean ±bias


def _remap_with_bayer(
    image: Image.Image,
    palette_rgb: list[tuple[int, int, int]],
    strength: float = 32.0,
) -> Image.Image:
    """Ordered Bayer 4x4 dithered remap.

    Adds a position-dependent bias from the Bayer matrix to each pixel's
    RGB values before doing nearest-color lookup. This creates the regular
    grid dithering pattern seen in Genesis/Mega Drive games.

    *strength* controls how much the Bayer offset shifts pixel values
    (in 0-255 RGB space). 32.0 is a good default for retro sprites.
    """
    if not palette_rgb:
        raise ValueError("palette_rgb must contain at least one color")

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.float64)
    h, w = arr.shape[:2]

    # Build the tiled Bayer threshold for the full image
    bayer_tiled = np.tile(
        _BAYER_4X4,
        (h // 4 + 1, w // 4 + 1),
    )[:h, :w]

    # Apply Bayer offset to RGB channels (not alpha)
    biased = arr.copy()
    for c in range(3):
        biased[:, :, c] += bayer_tiled * strength
    biased[:, :, :3] = np.clip(biased[:, :, :3], 0, 255)

    # Build Lab lookup for palette
    target_lab = np.array(
        [rgb_to_lab(r, g, b) for r, g, b in palette_rgb],
        dtype=np.float64,
    )
    target_arr = np.array(palette_rgb, dtype=np.uint8)

    # Nearest-neighbor in Lab space on biased pixels
    rgb_flat = biased[:, :, :3].reshape(-1, 3)
    alpha_flat = arr[:, :, 3].reshape(-1).astype(np.uint8)

    norm = rgb_flat / 255.0
    lin = np.where(norm <= 0.04045, norm / 12.92, ((norm + 0.055) / 1.055) ** 2.4)
    M = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ], dtype=np.float64)
    xyz = lin @ M.T
    xyz_n = xyz / np.array([_D65_XN, _D65_YN, _D65_ZN])
    delta = 6.0 / 29.0
    delta3 = delta ** 3
    f = np.where(xyz_n > delta3, xyz_n ** (1.0 / 3.0), xyz_n / (3.0 * delta ** 2) + 4.0 / 29.0)
    L = 116.0 * f[:, 1] - 16.0
    a = 500.0 * (f[:, 0] - f[:, 1])
    b = 200.0 * (f[:, 1] - f[:, 2])
    lab_pixels = np.stack([L, a, b], axis=1)

    chunk = 4096
    nearest_idx = np.empty(h * w, dtype=np.int32)
    for start in range(0, h * w, chunk):
        end = min(start + chunk, h * w)
        diff = lab_pixels[start:end, np.newaxis, :] - target_lab[np.newaxis, :, :]
        sq = np.einsum("ijk,ijk->ij", diff, diff)
        nearest_idx[start:end] = np.argmin(sq, axis=1)

    mapped_rgb = target_arr[nearest_idx]
    transparent = alpha_flat == 0
    out_rgba = np.concatenate([mapped_rgb, alpha_flat[:, np.newaxis]], axis=1).astype(np.uint8)
    out_rgba[transparent] = [0, 0, 0, 0]

    return Image.fromarray(out_rgba.reshape(h, w, 4), mode="RGBA")


def _remap_nearest(
    image: Image.Image,
    palette_rgb: list[tuple[int, int, int]],
) -> Image.Image:
    """Lab-space nearest-neighbor remap (no dithering)."""
    if not palette_rgb:
        raise ValueError("palette_rgb must contain at least one color")

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)
    h, w = arr.shape[:2]

    # Build Lab array for the target palette
    target_lab = np.array(
        [rgb_to_lab(r, g, b) for r, g, b in palette_rgb],
        dtype=np.float64,
    )
    target_arr = np.array(palette_rgb, dtype=np.uint8)

    rgb_flat = arr[:, :, :3].reshape(-1, 3).astype(np.float64)
    alpha_flat = arr[:, :, 3].reshape(-1)

    # sRGB -> Lab (vectorised)
    norm = rgb_flat / 255.0
    lin = np.where(norm <= 0.04045, norm / 12.92, ((norm + 0.055) / 1.055) ** 2.4)

    M = np.array([
        [0.4124564, 0.3575761, 0.1804375],
        [0.2126729, 0.7151522, 0.0721750],
        [0.0193339, 0.1191920, 0.9503041],
    ], dtype=np.float64)
    xyz = lin @ M.T

    xyz_n = xyz / np.array([_D65_XN, _D65_YN, _D65_ZN])
    delta = 6.0 / 29.0
    delta3 = delta ** 3
    f = np.where(xyz_n > delta3, xyz_n ** (1.0 / 3.0), xyz_n / (3.0 * delta ** 2) + 4.0 / 29.0)
    L = 116.0 * f[:, 1] - 16.0
    a = 500.0 * (f[:, 0] - f[:, 1])
    b = 200.0 * (f[:, 1] - f[:, 2])
    lab_pixels = np.stack([L, a, b], axis=1)

    # Nearest-neighbor in Lab space
    chunk = 4096
    nearest_idx = np.empty(h * w, dtype=np.int32)
    for start in range(0, h * w, chunk):
        end = min(start + chunk, h * w)
        diff = lab_pixels[start:end, np.newaxis, :] - target_lab[np.newaxis, :, :]
        sq = np.einsum("ijk,ijk->ij", diff, diff)
        nearest_idx[start:end] = np.argmin(sq, axis=1)

    mapped_rgb = target_arr[nearest_idx]
    transparent = alpha_flat == 0
    out_rgba = np.concatenate([mapped_rgb, alpha_flat[:, np.newaxis]], axis=1).astype(np.uint8)
    out_rgba[transparent] = [0, 0, 0, 0]

    return Image.fromarray(out_rgba.reshape(h, w, 4), mode="RGBA")


def quantize_to_bit_depth(image: Image.Image, bits_per_channel: int) -> Image.Image:
    """
    Quantize an image to a reduced bit depth per channel.

    Used for consoles with free-choice palettes (Genesis 9-bit = 3 bits/channel,
    SNES/GBC 15-bit = 5 bits/channel). Reduces each channel to the target depth
    by truncating low bits, then expanding back to 8-bit range.

    Transparent pixels are preserved.
    """
    if bits_per_channel <= 0:
        raise ValueError("bits_per_channel must be a positive integer")

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)

    shift = 8 - bits_per_channel
    max_val = (1 << bits_per_channel) - 1  # 7 for 3-bit, 31 for 5-bit

    # Quantize RGB channels: truncate then expand back to 8-bit
    rgb = arr[:, :, :3].astype(np.uint16)
    quantized = (rgb >> shift)            # truncate to N bits
    expanded = (quantized * 255) // max_val  # expand back to 0-255 range

    out = arr.copy()
    out[:, :, :3] = expanded.astype(np.uint8)

    # Preserve transparency
    transparent = arr[:, :, 3] == 0
    out[transparent] = [0, 0, 0, 0]

    return Image.fromarray(out, mode="RGBA")


# ---------------------------------------------------------------------------
# Palette role templates — define functional color roles for NES sprites
# ---------------------------------------------------------------------------

PALETTE_ROLE_TEMPLATES: dict[str, dict] = {
    "standard_3": {
        "roles": ["outline", "primary", "secondary"],
        "description": (
            "Classic 3-color NES sprite: dark outline color, "
            "primary fill color for the main body, "
            "secondary fill color for details and accents."
        ),
    },
    "standard_4": {
        "roles": ["outline", "primary", "secondary", "highlight"],
        "description": (
            "4-color NES sprite with depth: dark outline color, "
            "primary fill color for the main body, "
            "secondary fill color for details, "
            "bright highlight color for light-catching edges."
        ),
    },
    "no_outline_3": {
        "roles": ["dark", "midtone", "light"],
        "description": (
            "3-color NES sprite without dedicated outline: "
            "dark shadow color, midtone body color, light highlight color. "
            "Shape defined by color contrast rather than an outline."
        ),
    },
    "no_outline_4": {
        "roles": ["dark", "midtone", "light", "accent"],
        "description": (
            "4-color NES sprite without outline: "
            "dark shadow, midtone body, light highlight, plus an accent color "
            "for special details like eyes, gems, or insignia."
        ),
    },
}


def suggest_palette_roles(era: str = "mid", outline: str = "Black", console: str = "nes") -> dict:
    """
    Return the appropriate palette role template based on era and outline setting.

    Parameters
    ----------
    era:
        NES era — "retro", "early", "mid", or "late".
    outline:
        Outline style — "Black", "Dark", or "No".

    Returns
    -------
    dict
        A palette role template from PALETTE_ROLE_TEMPLATES.
    """
    era = era.lower() if isinstance(era, str) else "mid"
    outline = outline if isinstance(outline, str) else "Black"

    # No-outline styles
    if outline == "No" or era == "retro":
        if era in ("late",):
            return PALETTE_ROLE_TEMPLATES["no_outline_4"]
        return PALETTE_ROLE_TEMPLATES["no_outline_3"]

    # Standard outline styles
    if era in ("late",):
        return PALETTE_ROLE_TEMPLATES["standard_4"]
    if era in ("early", "retro"):
        return PALETTE_ROLE_TEMPLATES["standard_3"]

    # Mid era with outline — 4 colors (more refined than early)
    return PALETTE_ROLE_TEMPLATES["standard_4"]


# ---------------------------------------------------------------------------
# Mood-aware palette filtering
# ---------------------------------------------------------------------------

# NES palette colors grouped by mood.  Each mood returns a generous subset
# (15-25 colors) so there's enough variety while enforcing color temperature.
# Neutrals (blacks, grays, whites) are included in every mood since they
# work as outlines and backgrounds regardless of temperature.

_NEUTRALS = [
    "#000000", "#626262", "#4E4E4E", "#ABABAB", "#ACACAC", "#FFFFFF",
]

_MOOD_PALETTES: dict[str, list[str]] = {
    "warm": _NEUTRALS + [
        # Row 0: dark warm
        "#560044", "#5A0002", "#4F0800", "#351000",
        # Row 1: mid warm
        "#92088A", "#9A1032", "#913800", "#7A5400",
        # Row 2: bright warm
        "#D85CFE", "#E47ABA", "#E09264", "#C8B216",
        # Row 3: pastel warm
        "#EEBAFE", "#F4C4E2", "#F0CEB2", "#E4DE94",
    ],
    "cool": _NEUTRALS + [
        # Row 0: dark cool
        "#002C88", "#1B0076", "#3B0076", "#002E00",
        "#003200", "#002A14", "#00234A",
        # Row 1: mid cool
        "#0D56D0", "#4220D0", "#6A12C2", "#0E7800",
        "#007A00", "#007028", "#006486",
        # Row 2: bright cool
        "#4CA0FE", "#7C78FE", "#A862FE", "#46E438",
        "#3AD67E", "#3EC4D2",
        # Row 3: pastel cool
        "#B6D8FE", "#C8C4FE", "#DAB8FE", "#B0F29C",
        "#ACF0C2", "#B2ECEE",
    ],
    "dark": _NEUTRALS + [
        # Row 0: all darks
        "#002C88", "#1B0076", "#3B0076", "#560044",
        "#5A0002", "#4F0800", "#351000", "#1A1802",
        "#002E00", "#003200", "#002A14", "#00234A",
        # Row 1: mid tones (no brights)
        "#0D56D0", "#4220D0", "#6A12C2", "#92088A",
        "#9A1032", "#913800", "#7A5400", "#006486",
    ],
    "bright": _NEUTRALS + [
        # Row 2: all brights
        "#4CA0FE", "#7C78FE", "#A862FE", "#D85CFE",
        "#E47ABA", "#E09264", "#C8B216", "#A0CC00",
        "#6ADA02", "#46E438", "#3AD67E", "#3EC4D2",
        # Row 3: all pastels
        "#B6D8FE", "#C8C4FE", "#DAB8FE", "#EEBAFE",
        "#F4C4E2", "#F0CEB2", "#E4DE94", "#D0E882",
        "#BCF07E", "#B0F29C", "#ACF0C2", "#B2ECEE",
    ],
    "earth": _NEUTRALS + [
        # Row 0: dark earth
        "#5A0002", "#4F0800", "#351000", "#1A1802",
        "#002E00", "#003200",
        # Row 1: mid earth
        "#9A1032", "#913800", "#7A5400", "#536800",
        "#0E7800", "#007A00",
        # Row 2: bright earth
        "#E09264", "#C8B216", "#A0CC00", "#6ADA02",
        # Row 3: pastel earth
        "#F0CEB2", "#E4DE94", "#D0E882", "#BCF07E",
    ],
}


def get_mood_palette(mood: str, console: str = "nes") -> list[str] | None:
    """
    Return a subset of NES palette colors matching the given mood.

    Returns ``None`` for ``"auto"`` or unrecognised moods (meaning: use
    the full NES palette, no filtering).
    """
    palette = _MOOD_PALETTES.get(mood.lower())
    if palette is None:
        return None
    return copy.deepcopy(palette)


# ---------------------------------------------------------------------------
# Curated NES palette presets — named 3-4 color palettes for common themes
# ---------------------------------------------------------------------------

NES_PALETTE_PRESETS: dict[str, list[str]] = {
    "mario_red":        ["#000000", "#9A1032", "#E09264", "#FFFFFF"],
    "link_green":       ["#000000", "#002E00", "#0E7800", "#FFFFFF"],
    "megaman_blue":     ["#000000", "#0D56D0", "#4CA0FE", "#FFFFFF"],
    "castlevania_dark": ["#000000", "#5A0002", "#4F0800", "#626262"],
    "fire_warm":        ["#000000", "#9A1032", "#913800", "#C8B216"],
    "ice_cool":         ["#000000", "#0D56D0", "#3EC4D2", "#FFFFFF"],
    "earth_forest":     ["#000000", "#002E00", "#351000", "#913800"],
    "dungeon_stone":    ["#000000", "#626262", "#ABABAB", "#4E4E4E"],
    "gold_treasure":    ["#000000", "#351000", "#C8B216", "#FFFFFF"],
    "shadow_night":     ["#000000", "#3B0076", "#002C88", "#626262"],
}


def get_preset_palette(name: str) -> list[str] | None:
    """Return a preset palette by name, or None if not found."""
    palette = NES_PALETTE_PRESETS.get(name.lower())
    if palette is None:
        return None
    return copy.deepcopy(palette)


def list_presets() -> dict[str, list[str]]:
    """Return all available preset palettes."""
    return copy.deepcopy(NES_PALETTE_PRESETS)


# ---------------------------------------------------------------------------
# Palette swap variant generation
# ---------------------------------------------------------------------------

def swap_palette(
    image: Image.Image,
    color_map: dict[tuple[int, int, int], tuple[int, int, int]],
) -> Image.Image:
    """
    Apply an explicit color mapping to produce a recolored image.

    Parameters
    ----------
    image:
        RGBA PIL Image to recolor.
    color_map:
        Dict mapping (R, G, B) -> (R, G, B) for each color to swap.
        Colors not in the map are left unchanged.

    Returns
    -------
    Image.Image
        A new RGBA image with swapped colors.
    """
    img = image.convert("RGBA")
    src_arr = np.array(img, dtype=np.uint8)
    arr = src_arr.copy()

    for old_rgb, new_rgb in color_map.items():
        match = (
            (src_arr[:, :, 0] == old_rgb[0]) &
            (src_arr[:, :, 1] == old_rgb[1]) &
            (src_arr[:, :, 2] == old_rgb[2]) &
            (src_arr[:, :, 3] > 0)
        )
        arr[match, 0] = new_rgb[0]
        arr[match, 1] = new_rgb[1]
        arr[match, 2] = new_rgb[2]

    return Image.fromarray(arr, mode="RGBA")


def generate_palette_swaps(
    image: Image.Image,
    num_variants: int = 3,
    seed: int | None = None,
) -> list[Image.Image]:
    """
    Generate palette-swapped variants of a sprite, keeping the outline color fixed.

    Identifies the darkest opaque color as the "outline" and keeps it unchanged.
    Other colors are replaced with random NES palette colors that preserve the
    relative luminance ordering (lightest stays lightest, etc.).

    Parameters
    ----------
    image:
        RGBA PIL Image to generate variants from.
    num_variants:
        Number of recolored variants to produce (default 3).
    seed:
        Optional random seed for reproducible variants.

    Returns
    -------
    list[Image.Image]
        List of recolored variant images.
    """
    import random

    img = image.convert("RGBA")
    arr = np.array(img, dtype=np.uint8)

    # Find unique opaque colors
    opaque_mask = arr[:, :, 3] > 0
    opaque_pixels = arr[opaque_mask][:, :3]
    if opaque_pixels.size == 0:
        return [img.copy() for _ in range(num_variants)]

    unique_colors = np.unique(opaque_pixels.reshape(-1, 3), axis=0)
    if len(unique_colors) < 2:
        return [img.copy() for _ in range(num_variants)]

    # Compute luminance for each unique color to find darkest (outline)
    luminances = [
        rgb_to_lab(int(c[0]), int(c[1]), int(c[2]))[0]  # L channel
        for c in unique_colors
    ]

    # Sort colors by luminance
    sorted_indices = sorted(range(len(luminances)), key=lambda i: luminances[i])
    outline_idx = sorted_indices[0]  # darkest = outline, keep fixed
    outline_color = tuple(unique_colors[outline_idx].tolist())

    # Non-outline colors sorted by luminance (light to dark)
    swap_indices = [i for i in sorted_indices if i != outline_idx]
    swap_colors = [tuple(unique_colors[i].tolist()) for i in swap_indices]
    swap_luminances = [luminances[i] for i in swap_indices]

    # Build NES palette lookup sorted by luminance
    nes_luminances = [
        (i, rgb_to_lab(r, g, b)[0])
        for i, (r, g, b) in enumerate(NES_PALETTE_RGB)
    ]
    # Exclude colors too close to the outline color
    outline_lum = luminances[outline_idx]
    nes_candidates = [
        (i, lum) for i, lum in nes_luminances
        if abs(lum - outline_lum) > 15  # must be visually distinct from outline
    ]
    nes_candidates.sort(key=lambda x: x[1])  # sort by luminance

    rng = random.Random(seed)
    variants = []

    for _ in range(num_variants):
        color_map: dict[tuple[int, int, int], tuple[int, int, int]] = {}

        # For each non-outline color, pick a random NES color at a similar
        # relative luminance position
        num_swap = len(swap_colors)
        if num_swap == 0 or len(nes_candidates) < num_swap:
            variants.append(img.copy())
            continue

        # Pick num_swap random candidates, then sort them by luminance
        # to preserve the luminance ordering
        chosen_indices = rng.sample(range(len(nes_candidates)), min(num_swap, len(nes_candidates)))
        chosen = sorted(
            [nes_candidates[i] for i in chosen_indices],
            key=lambda x: x[1],
        )

        for j, old_color in enumerate(swap_colors):
            nes_idx, _ = chosen[j]
            new_rgb = NES_PALETTE_RGB[nes_idx]
            color_map[old_color] = new_rgb

        variant = swap_palette(img, color_map)
        variants.append(variant)

    return variants

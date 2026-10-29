"""
Console binding: what a ``.px.js`` drawing is handed for a console and tier.

The binding fixes the drawer's palette to the console's colors, exposes the
grid and limits as ``rg.*``, and names the color helper (``nes()`` on NES,
``snes()`` / ``bgr555()`` on SNES). It is serialized to JSON for
``js/rg-build.mjs`` and hashed into provenance, so a change here changes
``binding_sha256``.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ..console_profile import NES
from .hw.rules import BUILD_CODES, rules_for

JS_DIR = Path(__file__).resolve().parent / "js"
LOADER = JS_DIR / "rg-build.mjs"

TIERS = ("like", "legal")
SUPPORTED = {"nes": TIERS, "snes": TIERS}

# ---------------------------------------------------------------------------
# NES 2C02: bytes, canonical colors
# ---------------------------------------------------------------------------

#: (byte, "#RRGGBB") for the 56 entries of Retrogaze's NES table, row by row ($x0-$xD).
NES_TABLE: tuple[tuple[int, str], ...] = tuple(
    ((i // 14) * 16 + (i % 14), h.upper()) for i, h in enumerate(NES.master_palette_hex or ())
)

#: The 54 unique NES colors in first-occurrence order (black and white appear twice).
NES_COLORS: tuple[str, ...] = tuple(dict.fromkeys(h for _, h in NES_TABLE))

BLACK = "#000000"
WHITE = "#FFFFFF"

#: Canonical byte written for each color: black is $0F (never $0D), white is $30.
NES_CANON_BYTE: dict[str, int] = {}
for _b, _h in NES_TABLE:
    if _b != 0x0D:
        NES_CANON_BYTE.setdefault(_h, _b)
NES_CANON_BYTE[BLACK] = 0x0F
NES_CANON_BYTE[WHITE] = 0x30


def nes_byte_hex(byte: int) -> str:
    """RGB of a 2C02 byte in Retrogaze's table. Columns $xE/$xF (and $0D) display black."""
    if not 0 <= byte <= 0x3F:
        raise ValueError(f"NES color byte out of range: {byte:#x}")
    if (byte & 0x0F) >= 0x0E or byte == 0x0D:
        return BLACK
    return dict(NES_TABLE)[byte]


NES_LIMITS = {
    "oam": 64, "perLine": 8, "bgPalettes": 4, "objPalettes": 4, "colorsPerPalette": 3,
    "bgTiles": 256, "objTiles": 256, "screenW": 256, "screenH": 240,
}

NES_SCENE_KEYS = ["bg", "bgAt", "obj", "objSize", "backdrop", "palettes", "chr", "left8"]

MAX_PIXELS = 4 * 1024 * 1024


# ---------------------------------------------------------------------------
# SNES S-PPU: 15-bit BGR, canonical 8-bit expansion e(q) = (q * 255) // 31
# ---------------------------------------------------------------------------

#: The 32 displayable 8-bit values of a 5-bit channel: Retrogaze's existing expansion
#: (palette.quantize_to_bit_depth, metadata._check_palette_valid), not bit replication.
SNES_LEVELS: list[int] = [(q * 255) // 31 for q in range(32)]   # 5 bits per channel of the 15-bit profile
SNES_Q: dict[int, int] = {v: q for q, v in enumerate(SNES_LEVELS)}


def snes_hex(r5: int, g5: int, b5: int) -> str:
    return f"#{SNES_LEVELS[r5]:02X}{SNES_LEVELS[g5]:02X}{SNES_LEVELS[b5]:02X}"


def snes_word(hexstr: str) -> int:
    """15-bit CGRAM word 0bbbbbgggggrrrrr of a canonical color; ValueError for any other color."""
    v = int(hexstr.lstrip("#")[:6], 16)
    r, g, b = (v >> 16) & 255, (v >> 8) & 255, v & 255
    if r not in SNES_Q or g not in SNES_Q or b not in SNES_Q:
        raise ValueError(f"{hexstr} is not a canonical SNES color (channels must be (q * 255) // 31)")
    return (SNES_Q[b] << 10) | (SNES_Q[g] << 5) | SNES_Q[r]


def word_hex(word: int) -> str:
    return snes_hex(word & 31, (word >> 5) & 31, (word >> 10) & 31)


SNES_LIMITS = {
    "oam": 128, "perLine": 32, "slivers": 34, "bgPalettes": 8, "objPalettes": 8, "colorsPerPalette": 15,
    "bg3Palettes": 8, "bg3ColorsPerPalette": 3, "bgTiles": 1024, "objTiles": 512, "vramBytes": 65536,
    "screenW": 256, "screenH": 224,
}

SNES_SCENE_KEYS = ["bg1", "bg2", "bg3", "obj", "backdrop", "obsel", "palettes", "chr", "mode",
                   "allowUndocumentedObjSizes"]


def check_supported(console: str, tier: str) -> None:
    """Raise ``ValueError`` for a console or tier this milestone does not cover."""
    if tier not in TIERS:
        raise ValueError(f"unknown tier {tier!r}: use 'like' or 'legal'")
    if console not in SUPPORTED:
        raise ValueError(
            f"code mode supports {', '.join(sorted(SUPPORTED))} in this build; "
            f"'{console}' is not specified yet (see docs/spec/CODE-MODE-SPEC.md §6)"
        )
    if tier not in SUPPORTED[console]:
        raise ValueError(f"console-{tier} not yet specified for {console}")


def binding_for(console: str, tier: str) -> dict:
    """The JSON binding handed to ``rg-build.mjs``."""
    check_supported(console, tier)
    if console == "snes":
        return {
            "console": "snes",
            "display_name": "SNES",
            "tier": tier,
            "color_fn": "snes",
            "levels": list(SNES_LEVELS),
            "default_palette": "empty",
            "rg": {"tile": 8, "area": 8, "screen": {"w": 256, "h": 224}, "limits": dict(SNES_LIMITS)},
            "scene_keys": list(SNES_SCENE_KEYS),
            "max_pixels": MAX_PIXELS,
        }
    return {
        "console": "nes",
        "display_name": "NES",
        "tier": tier,
        "color_fn": "nes",
        "colors": list(NES_COLORS),
        "default_palette": "colors",
        "nes_bytes": {str(b): nes_byte_hex(b) for b in range(0x40) if b != 0x0D},
        "color_calls": {h: f"nes(0x{NES_CANON_BYTE[h]:02X})" for h in NES_COLORS},
        "rg": {"tile": 8, "area": 16, "screen": {"w": 256, "h": 240}, "limits": dict(NES_LIMITS)},
        "scene_keys": list(NES_SCENE_KEYS),
        "max_pixels": MAX_PIXELS,
    }


def binding_sha256(binding: dict) -> str:
    """Hash of the binding JSON plus the loader source: both decide how source becomes pixels."""
    h = hashlib.sha256()
    h.update(json.dumps(binding, sort_keys=True, separators=(",", ":")).encode())
    h.update(LOADER.read_bytes())
    return h.hexdigest()


# ---------------------------------------------------------------------------
# Cheat sheet (agent skill, GET /code/binding, MCP retro_code_bind)
# ---------------------------------------------------------------------------

def _build_codes(console: str) -> dict[str, str]:
    other = "CM-SNES-" if console == "nes" else "CM-NES-"
    return {c: why for c, why in BUILD_CODES.items() if not c.startswith(other)}


def render_cheatsheet(console: str = "nes") -> str:
    """Markdown cheat sheet: helpers, palette keys and the rule table. Generated, never hand-edited."""
    check_supported(console, "legal")
    if console == "snes":
        return _snes_cheatsheet()
    keys = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
    lines = [
        f"### {console.upper()} binding",
        "",
        "- Colors: `nes(byte)` returns the hex for a 2C02 byte (`nes(0x0D)` is an error; black is `nes(0x0F)`).",
        "  Bind keys with `pal({ k: nes(0x0F), r: nes(0x16) })`. Hex literals must be NES colors.",
        f"- Default index keys `{keys[0]}`-`{keys[len(NES_COLORS) - 1]}` are the {len(NES_COLORS)} NES colors in "
        "table order; `use(\"pico8\")`-style palettes are disabled.",
        "- Disabled (they leave the palette): `lighting`, `lamp`, `bump`, `normals`, `glow` without `ramp`, "
        "partial-alpha colors, `Math.random`, `Date`.",
        "- `rg.scene(name, { bg, obj: [[asset, x, y, { flip }]...], objSize: \"8x8\"|\"8x16\", backdrop, "
        "palettes, chr, left8 })` declares one hardware frame. pxl `scene()` assets are BG; `sprite()`/`anim()` are OBJ.",
        "- `rg.tileset(name)` marks a BG tile set (each 16x16 metatile is one attribute area).",
        "- Sprite layers named `obj:<n>` become overlapping hardware sprites (extra colors per pixel area).",
        "",
        "| Rule | Tier | Scope | Limit | Rule |",
        "|---|---|---|---|---|",
    ]
    for r in rules_for(console):
        lines.append(f"| {r.id} | {r.tier} | {r.scope} | {r.limit} | {r.text} |")
    lines += ["", "Build errors (exit 3):", ""]
    lines += [f"- `{code}`: {why}" for code, why in _build_codes(console).items()]
    return "\n".join(lines) + "\n"


def _snes_cheatsheet() -> str:
    lines = [
        "### SNES binding",
        "",
        "- Colors: `snes(r5, g5, b5)` (each 0-31) or `bgr555(word)` return the hex of a 15-bit color; hex literals "
        "must be canonical SNES colors (channel = (q * 255) // 31).",
        "  The active palette starts empty: bind keys with `pal({ s: snes(31, 24, 16), k: snes(0, 0, 4) })`.",
        "- Disabled (they leave the palette): `lighting`, `lamp`, `bump`, `normals`, `glow` without `ramp`, "
        "partial-alpha colors, `Math.random`, `Date`.",
        "- `rg.scene(name, { bg1, bg2, bg3, obj: [[asset, x, y, { flip, size }]...], backdrop, obsel, palettes, chr, "
        "mode, allowUndocumentedObjSizes })` declares one Mode 1 frame: BG1/BG2 4bpp (15 colors per tile), BG3 2bpp "
        "(3), OBJ 4bpp (15 per OBJ). Back to front: backdrop, BG3, BG2, BG1, OBJ.",
        "- OBJ sizes come in OBSEL pairs (8/16, 8/32, 8/64, 16/32, 16/64, 32/64); the decomposer picks the cheapest "
        "pair unless `obsel` or a placement `size` (\"16x16\") pins it. 16x32/32x64 need "
        "`allowUndocumentedObjSizes: true`.",
        "- `rg.tileset(name)` marks a BG tile set (BG1; every 8x8 tile picks its own palette).",
        "- Sprite layers named `obj:<n>` become overlapping OBJs.",
        "",
        "| Rule | Tier | Scope | Limit | Rule |",
        "|---|---|---|---|---|",
    ]
    for r in rules_for("snes"):
        lines.append(f"| {r.id} | {r.tier} | {r.scope} | {r.limit} | {r.text} |")
    lines += ["", "Build errors (exit 3):", ""]
    lines += [f"- `{code}`: {why}" for code, why in _build_codes("snes").items()]
    return "\n".join(lines) + "\n"

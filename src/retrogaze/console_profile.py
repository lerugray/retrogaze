"""
Console hardware profiles for multi-console constraint enforcement.

Each profile encodes the hardware constraints of a specific console
(palette, tile size, sprite limits, etc.) as a simple data object.
The enforce pipeline uses these to validate against different consoles
without hardcoding NES-specific behavior.

Architecture decision: config-driven dataclass, not ABC hierarchy.
Consoles differ in data, not algorithms. See Research/Game Boy Constraints.md §4.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ConsoleProfile:
    """Hardware constraint profile for a retro console."""

    name: str
    display_name: str
    resolution: tuple[int, int]
    tile_size: int
    bits_per_pixel: int
    max_colors_per_tile: int

    # Palette
    master_palette_hex: tuple[str, ...] | None  # Fixed palette colors, or None for free color
    color_depth_bits: int | None  # None for fixed palette, 15 for GBC RGB555

    # Palette system
    bg_palettes: int
    sprite_palettes: int
    colors_per_palette: int  # including bg/transparent slot

    # Sprites
    max_sprites: int
    max_sprites_per_scanline: int
    sprite_sizes: tuple[tuple[int, int], ...]

    # Attribute table (NES-specific)
    has_attribute_table: bool
    attribute_block_size: int | None  # 16 for NES, None for others

    # Palette assignment model
    palette_assignment: str  # "per_block_16x16", "global", "per_tile"

    # Valid metasprite sizes (composed from hardware sprites)
    valid_metasprite_sizes: frozenset[tuple[int, int]] = field(default_factory=frozenset)

    # Display
    pixel_aspect_ratio: tuple[int, int] = (1, 1)

    # Extended fields (backward-compatible defaults)
    has_tile_grid: bool = True                    # False for Atari 2600
    pixel_width: int = 1                          # 2 for C64 multicolor (double-wide pixels)
    background_planes: int = 1                    # 2 for Genesis (Plane A+B), 1 for most
    total_palette_entries: int | None = None       # 256 for SNES, 64 for Genesis, None = auto
    palette_shared_bg_sprite: bool = False         # True for Genesis (4 shared palettes)
    max_sprite_pixels_per_scanline: int | None = None  # 320 for Genesis, 256 for SNES

    def master_palette_rgb(self) -> list[tuple[int, int, int]] | None:
        """Return master palette as RGB tuples, or None if free color."""
        if self.master_palette_hex is None:
            return None
        result = []
        for h in self.master_palette_hex:
            h = h.lstrip("#")
            result.append((int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)))
        return result


# ---------------------------------------------------------------------------
# NES 2C02 PPU
# ---------------------------------------------------------------------------

_NES_PALETTE_HEX = (
    # Row 0
    "#626262", "#002C88", "#1B0076", "#3B0076",
    "#560044", "#5A0002", "#4F0800", "#351000",
    "#1A1802", "#002E00", "#003200", "#002A14",
    "#00234A", "#000000",
    # Row 1
    "#ABABAB", "#0D56D0", "#4220D0", "#6A12C2",
    "#92088A", "#9A1032", "#913800", "#7A5400",
    "#536800", "#0E7800", "#007A00", "#007028",
    "#006486", "#000000",
    # Row 2
    "#FFFFFF", "#4CA0FE", "#7C78FE", "#A862FE",
    "#D85CFE", "#E47ABA", "#E09264", "#C8B216",
    "#A0CC00", "#6ADA02", "#46E438", "#3AD67E",
    "#3EC4D2", "#4E4E4E",
    # Row 3
    "#FFFFFF", "#B6D8FE", "#C8C4FE", "#DAB8FE",
    "#EEBAFE", "#F4C4E2", "#F0CEB2", "#E4DE94",
    "#D0E882", "#BCF07E", "#B0F29C", "#ACF0C2",
    "#B2ECEE", "#ACACAC",
)

NES = ConsoleProfile(
    name="nes",
    display_name="NES",
    resolution=(256, 240),
    tile_size=8,
    bits_per_pixel=2,
    max_colors_per_tile=4,
    master_palette_hex=_NES_PALETTE_HEX,
    color_depth_bits=None,
    bg_palettes=4,
    sprite_palettes=4,
    colors_per_palette=4,
    max_sprites=64,
    max_sprites_per_scanline=8,
    sprite_sizes=((8, 8), (8, 16)),
    has_attribute_table=True,
    attribute_block_size=16,
    palette_assignment="per_block_16x16",
    valid_metasprite_sizes=frozenset({
        (8, 8), (8, 16), (16, 16), (16, 24), (16, 32),
    }),
    pixel_aspect_ratio=(8, 7),
)


# ---------------------------------------------------------------------------
# Game Boy DMG (original, green-tinted LCD)
# ---------------------------------------------------------------------------

# Common emulator approximation of DMG green shades
_GB_DMG_PALETTE_HEX = (
    "#9BBC0F",  # Lightest (shade 0)
    "#8BAC0F",  # Light (shade 1)
    "#306230",  # Dark (shade 2)
    "#0F380F",  # Darkest (shade 3)
)

GAME_BOY_DMG = ConsoleProfile(
    name="gb_dmg",
    display_name="Game Boy",
    resolution=(160, 144),
    tile_size=8,
    bits_per_pixel=2,
    max_colors_per_tile=4,
    master_palette_hex=_GB_DMG_PALETTE_HEX,
    color_depth_bits=None,
    bg_palettes=1,
    sprite_palettes=2,
    colors_per_palette=4,
    max_sprites=40,
    max_sprites_per_scanline=10,
    sprite_sizes=((8, 8), (8, 16)),
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="global",
    valid_metasprite_sizes=frozenset({
        (8, 8), (8, 16), (16, 16), (16, 24), (16, 32),
    }),
    pixel_aspect_ratio=(1, 1),
)


# ---------------------------------------------------------------------------
# Game Boy Pocket (true grayscale LCD)
# ---------------------------------------------------------------------------

_GB_POCKET_PALETTE_HEX = (
    "#FFFFFF",  # White (shade 0)
    "#AAAAAA",  # Light gray (shade 1)
    "#555555",  # Dark gray (shade 2)
    "#000000",  # Black (shade 3)
)

GAME_BOY_POCKET = ConsoleProfile(
    name="gb_pocket",
    display_name="Game Boy Pocket",
    resolution=(160, 144),
    tile_size=8,
    bits_per_pixel=2,
    max_colors_per_tile=4,
    master_palette_hex=_GB_POCKET_PALETTE_HEX,
    color_depth_bits=None,
    bg_palettes=1,
    sprite_palettes=2,
    colors_per_palette=4,
    max_sprites=40,
    max_sprites_per_scanline=10,
    sprite_sizes=((8, 8), (8, 16)),
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="global",
    valid_metasprite_sizes=frozenset({
        (8, 8), (8, 16), (16, 16), (16, 24), (16, 32),
    }),
    pixel_aspect_ratio=(1, 1),
)


# ---------------------------------------------------------------------------
# Commodore 64 — Hi-res bitmap mode (320x200, 2 colors per 8x8 cell)
# ---------------------------------------------------------------------------

# VICE emulator canonical palette (commonly accepted)
_C64_PALETTE_HEX = (
    "#000000",  # 0: Black
    "#FFFFFF",  # 1: White
    "#68372B",  # 2: Red
    "#70A4B2",  # 3: Cyan
    "#6F3D86",  # 4: Purple
    "#588D43",  # 5: Green
    "#352879",  # 6: Blue
    "#B8C76F",  # 7: Yellow
    "#6F4F25",  # 8: Orange
    "#433900",  # 9: Brown
    "#9A6759",  # 10: Light Red
    "#444444",  # 11: Dark Gray
    "#6C6C6C",  # 12: Medium Gray
    "#9AD284",  # 13: Light Green
    "#6C5EB5",  # 14: Light Blue
    "#959595",  # 15: Light Gray
)

C64_HIRES = ConsoleProfile(
    name="c64_hires",
    display_name="Commodore 64",
    resolution=(320, 200),
    tile_size=8,
    bits_per_pixel=1,
    max_colors_per_tile=2,  # 1 foreground + 1 background per 8x8 cell
    master_palette_hex=_C64_PALETTE_HEX,
    color_depth_bits=None,
    bg_palettes=1,
    sprite_palettes=1,
    colors_per_palette=16,
    max_sprites=8,
    max_sprites_per_scanline=8,
    sprite_sizes=((24, 21),),
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="per_cell",
    valid_metasprite_sizes=frozenset({
        (24, 21), (48, 21), (24, 42), (48, 42),
    }),
    pixel_aspect_ratio=(1, 1),
)

C64_MULTICOLOR = ConsoleProfile(
    name="c64_multicolor",
    display_name="Commodore 64 (Multicolor)",
    resolution=(160, 200),
    tile_size=4,  # 4x8 cells in multicolor mode (double-wide pixels)
    bits_per_pixel=2,
    max_colors_per_tile=4,  # bg + multicolor1 + multicolor2 (global) + per-cell fg
    master_palette_hex=_C64_PALETTE_HEX,
    color_depth_bits=None,
    bg_palettes=1,
    sprite_palettes=1,
    colors_per_palette=16,
    max_sprites=8,
    max_sprites_per_scanline=8,
    sprite_sizes=((12, 21),),  # multicolor: 12x21 (double-wide)
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="per_cell",
    valid_metasprite_sizes=frozenset({
        (12, 21), (24, 21), (12, 42), (24, 42),
    }),
    pixel_aspect_ratio=(1, 1),
    pixel_width=2,
)


# ---------------------------------------------------------------------------
# Sega Genesis / Mega Drive — H40 mode (320x224, 9-bit RGB)
# ---------------------------------------------------------------------------

GENESIS = ConsoleProfile(
    name="genesis",
    display_name="Sega Genesis",
    resolution=(320, 224),
    tile_size=8,
    bits_per_pixel=4,
    max_colors_per_tile=16,
    master_palette_hex=None,  # Free-choice 9-bit RGB
    color_depth_bits=9,
    bg_palettes=4,
    sprite_palettes=4,  # shared with BG
    colors_per_palette=16,
    max_sprites=80,
    max_sprites_per_scanline=20,
    sprite_sizes=(
        (8, 8), (8, 16), (8, 24), (8, 32),
        (16, 8), (16, 16), (16, 24), (16, 32),
        (24, 8), (24, 16), (24, 24), (24, 32),
        (32, 8), (32, 16), (32, 24), (32, 32),
    ),
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="per_tile",
    valid_metasprite_sizes=frozenset({
        (8, 8), (16, 16), (24, 24), (32, 32), (16, 32), (32, 16),
        (24, 32), (32, 24), (48, 48), (64, 64),
    }),
    pixel_aspect_ratio=(32, 35),
    background_planes=2,
    total_palette_entries=64,
    palette_shared_bg_sprite=True,
    max_sprite_pixels_per_scanline=320,
)


# ---------------------------------------------------------------------------
# SNES / Super Famicom — Mode 1 (256x224, 15-bit RGB, most common)
# ---------------------------------------------------------------------------

SNES_MODE1 = ConsoleProfile(
    name="snes",
    display_name="SNES",
    resolution=(256, 224),
    tile_size=8,
    bits_per_pixel=4,
    max_colors_per_tile=16,
    master_palette_hex=None,  # Free-choice 15-bit RGB
    color_depth_bits=15,
    bg_palettes=8,
    sprite_palettes=8,
    colors_per_palette=16,
    max_sprites=128,
    max_sprites_per_scanline=32,
    sprite_sizes=(
        (8, 8), (16, 16), (32, 32), (64, 64),
        (16, 32), (32, 64),
    ),
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="per_tile",
    valid_metasprite_sizes=frozenset({
        (8, 8), (16, 16), (32, 32), (64, 64),
        (16, 32), (32, 64), (48, 48),
    }),
    pixel_aspect_ratio=(8, 7),
    total_palette_entries=256,
    max_sprite_pixels_per_scanline=256,
)

SNES_MODE7 = ConsoleProfile(
    name="snes_mode7",
    display_name="SNES (Mode 7)",
    resolution=(256, 224),
    tile_size=8,
    bits_per_pixel=8,
    max_colors_per_tile=256,
    master_palette_hex=None,
    color_depth_bits=15,
    bg_palettes=1,
    sprite_palettes=8,
    colors_per_palette=256,
    max_sprites=128,
    max_sprites_per_scanline=32,
    sprite_sizes=((8, 8), (16, 16), (32, 32), (64, 64)),
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="global",
    pixel_aspect_ratio=(8, 7),
    total_palette_entries=256,
)


# ---------------------------------------------------------------------------
# Game Boy Color (15-bit RGB, per-tile palette assignment)
# ---------------------------------------------------------------------------

GBC = ConsoleProfile(
    name="gbc",
    display_name="Game Boy Color",
    resolution=(160, 144),
    tile_size=8,
    bits_per_pixel=2,
    max_colors_per_tile=4,
    master_palette_hex=None,  # Free-choice 15-bit RGB
    color_depth_bits=15,
    bg_palettes=8,
    sprite_palettes=8,
    colors_per_palette=4,
    max_sprites=40,
    max_sprites_per_scanline=10,
    sprite_sizes=((8, 8), (8, 16)),
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="per_tile",
    valid_metasprite_sizes=frozenset({
        (8, 8), (8, 16), (16, 16), (16, 24), (16, 32),
    }),
    pixel_aspect_ratio=(1, 1),
    total_palette_entries=56,  # 32 BG + 24 sprite (color 0 = transparent)
)


# ---------------------------------------------------------------------------
# PC-Engine / TurboGrafx-16 (9-bit RGB, 16+16 palettes)
# ---------------------------------------------------------------------------

PC_ENGINE = ConsoleProfile(
    name="pc_engine",
    display_name="PC-Engine",
    resolution=(256, 224),
    tile_size=8,
    bits_per_pixel=4,
    max_colors_per_tile=16,
    master_palette_hex=None,  # Free-choice 9-bit RGB
    color_depth_bits=9,
    bg_palettes=16,
    sprite_palettes=16,
    colors_per_palette=16,
    max_sprites=64,
    max_sprites_per_scanline=16,
    sprite_sizes=(
        (16, 16), (16, 32), (16, 64),
        (32, 16), (32, 32), (32, 64),
    ),
    has_attribute_table=False,
    attribute_block_size=None,
    palette_assignment="per_tile",
    valid_metasprite_sizes=frozenset({
        (16, 16), (32, 32), (32, 64), (48, 48), (64, 64),
    }),
    pixel_aspect_ratio=(8, 7),
    total_palette_entries=482,  # 512 - 30 transparent slots
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_PROFILES: dict[str, ConsoleProfile] = {
    "nes": NES,
    "gb_dmg": GAME_BOY_DMG,
    "gb": GAME_BOY_DMG,          # alias
    "game_boy": GAME_BOY_DMG,    # alias
    "gb_pocket": GAME_BOY_POCKET,
    "c64": C64_HIRES,
    "c64_hires": C64_HIRES,
    "c64_multicolor": C64_MULTICOLOR,
    "commodore_64": C64_HIRES,
    "genesis": GENESIS,
    "mega_drive": GENESIS,
    "snes": SNES_MODE1,
    "super_nintendo": SNES_MODE1,
    "snes_mode1": SNES_MODE1,
    "snes_mode7": SNES_MODE7,
    "gbc": GBC,
    "game_boy_color": GBC,
    "pc_engine": PC_ENGINE,
    "turbografx": PC_ENGINE,
    "turbografx_16": PC_ENGINE,
}


def get_profile(name: str) -> ConsoleProfile:
    """Look up a console profile by name. Raises KeyError if not found."""
    key = name.lower().replace(" ", "_").replace("-", "_")
    if key not in _PROFILES:
        available = ", ".join(sorted(set(p.name for p in _PROFILES.values())))
        raise KeyError(f"Unknown console profile: {name!r}. Available: {available}")
    return _PROFILES[key]


def list_profiles() -> list[ConsoleProfile]:
    """Return all unique console profiles."""
    seen = set()
    result = []
    for p in _PROFILES.values():
        if p.name not in seen:
            seen.add(p.name)
            result.append(p)
    return result

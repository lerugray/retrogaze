"""
Console-specific prompt engineering data for Retrogaze.

Frozen dataclasses that hold all console-specific prompt data, migrated from
NES-hardcoded dicts in prompts.py and mcp_prompts.py.  Each console gets a
ConsolePromptData instance registered in _REGISTRY; callers use
``get_prompt_data(console)`` to retrieve it.
"""

from __future__ import annotations

from dataclasses import dataclass


# ---------------------------------------------------------------------------
# Dataclass definitions
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class EraPromptData:
    label: str                # "NES 8-bit style (1985-1987)"
    year_range: str           # "1985-1987"
    reference_games: str      # "Super Mario Bros, Mega Man, Castlevania"
    style_ref: str            # game references for FLUX style anchoring
    tile_ref: str             # tile-specific game references
    era_hints: str            # longer era description paragraph
    outline_hint: str         # outline behavior

    # Subject-neutral replacement for ``style_ref`` used when the asset is
    # NOT a character/enemy (item, UI). Some eras describe the reference
    # games in character-only language ("expressive face, detailed armor");
    # injected into an item prompt that contradiction overrides the item
    # framing and FLUX draws a character (Ricky, 2026-09-11 — item + late
    # era rendered characters). None means style_ref is already neutral.
    object_ref: str | None = None

    # Pipeline calibration — console+era-specific tuning parameters
    pixel_scale: int | None = None   # Image2Pixel downscale factor (None = auto-detect)
    max_cleanup_colors: int = 6      # Max opaque colors during cleanup phase


@dataclass(frozen=True)
class ConsolePromptData:
    name: str                 # "nes"
    display_name: str         # "NES"
    default_era: str          # "mid"
    eras: dict[str, EraPromptData]
    terrain_color_hints: list  # FLUX terrain guidance
    palette_rules: dict       # MCP palette rules per era
    color_theory_rules: dict  # MCP color theory per era
    tool_configs: dict        # MCP tool configs per era
    view_rules: dict          # MCP view guidance
    few_shot_examples: dict   # MCP examples per era
    mood_palettes: dict | None
    palette_presets: dict | None


# ---------------------------------------------------------------------------
# NES era prompt data
# ---------------------------------------------------------------------------

_NES_ERA_RETRO = EraPromptData(
    label="extremely primitive pre-NES 8-bit arcade style (1978-1983), only 8x8 pixels, almost abstract",
    year_range="1978-1983",
    reference_games="Space Invaders, Pac-Man, Donkey Kong (1981)",
    style_ref="Style: Space Invaders, Pac-Man, Donkey Kong (1981) sprites. Barely recognizable, geometric shapes only.",
    tile_ref="Style: early arcade tiles, simple colored blocks.",
    era_hints=(
        "Extremely primitive early arcade pixel art, 1978-1983 pre-NES era. "
        "Almost abstract, only 2-3 colors maximum. "
        "Characters are simple geometric shapes: rectangles for bodies, circles for heads, "
        "single-pixel lines for limbs. No facial details except maybe dot eyes. "
        "Silhouette-based design where shape alone conveys the subject. "
        "Style: Jumpman from Donkey Kong (1981), Pac-Man, Space Invaders, Galaga, Frogger. "
        "The most minimal, lo-fi pixel art possible."
    ),
    outline_hint="No visible outline — shapes defined by solid color blocks only.",
    pixel_scale=4,
    max_cleanup_colors=3,
)

_NES_ERA_EARLY = EraPromptData(
    label="extremely primitive early NES 8-bit style (1983-1984), only 12x16 pixels, very blocky and simple",
    year_range="1983-1984",
    reference_games="Donkey Kong (1983), Excitebike, Ice Climber",
    style_ref="Style: Donkey Kong (1983), Excitebike, Ice Climber NES sprites. Simple geometric shapes, minimal detail.",
    tile_ref="Style: early NES ground tiles, simple brick patterns.",
    era_hints=(
        "Extremely simple and blocky pixel art, 1983-1984 NES era. "
        "Very chunky geometric shapes, minimal detail, only 2-3 colors. "
        "Thick bold outlines, square proportions, tiny sprite. "
        "Style: Donkey Kong (1983), Excitebike, Ice Climber — "
        "the most primitive and blocky NES sprites possible. "
        "Almost abstract, silhouette-based design."
    ),
    outline_hint="Thick black 1-pixel outline around entire sprite.",
    pixel_scale=6,
    max_cleanup_colors=4,
)

_NES_ERA_MID = EraPromptData(
    label="NES 8-bit style (1985-1987)",
    year_range="1985-1987",
    reference_games="Super Mario Bros, Mega Man, Castlevania",
    style_ref="Style: Super Mario Bros, Mega Man, Castlevania NES sprites.",
    tile_ref="Style: Super Mario Bros brick blocks, Zelda dungeon floors, Castlevania stone walls.",
    era_hints=(
        "Classic NES pixel art, 1985-1986 golden era. "
        "More refined and proportional than early NES — NOT overly blocky or primitive. "
        "3-4 colors with a dedicated highlight color for depth and polish. "
        "Characters have recognizable features: distinct eyes, visible equipment details, "
        "clear clothing and armor shapes. Smooth readable silhouettes, not abstract blobs. "
        "Style: Super Mario Bros 1 & 3, Legend of Zelda, Castlevania, Mega Man 2. "
        "The definitive NES look — iconic, clean, and instantly readable."
    ),
    outline_hint="Clean black outline, 1 pixel wide, defines silhouette clearly.",
    pixel_scale=None,
    max_cleanup_colors=6,
)

_NES_ERA_LATE = EraPromptData(
    label="detailed late NES 8-bit style (1987-1993), 4-6 colors with shading and highlights",
    year_range="1987-1993",
    reference_games="Kirby's Adventure, Castlevania III, Little Samson",
    style_ref="Style: Kirby's Adventure, Castlevania III, Little Samson NES sprites. Detailed armor, expressive face, visible shading.",
    object_ref="Style: Kirby's Adventure, Castlevania III, Little Samson NES sprites. Detailed shading, highlights, and color transitions.",
    tile_ref="Style: Kirby's Adventure terrain, Castlevania III backgrounds, detailed NES tiles.",
    era_hints=(
        "Refined late NES pixel art, 1987-1993 era — the technical peak of 8-bit. "
        "Noticeably more detailed and proportional than mid-era NES. "
        "4-6 colors used with intention: shading, highlights, and color transitions "
        "that suggest depth and volume. Sprites have expressive faces, detailed armor "
        "and clothing, visible muscle definition or fabric folds where appropriate. "
        "Anti-aliased outlines using dark color variants instead of pure black. "
        "Style: Kirby's Adventure, Castlevania III, Little Samson, Shatterhand, "
        "Batman (Sunsoft), Crisis Force — the most polished NES sprites ever made."
    ),
    outline_hint=(
        "Dark outline using darkest palette color instead of pure black. "
        "Outline may use dark blue, dark brown, or dark purple to match the sprite's color scheme."
    ),
    pixel_scale=None,
    max_cleanup_colors=6,
)


# ---------------------------------------------------------------------------
# NES global blacklists / safe dither lists (used in tool_configs)
# ---------------------------------------------------------------------------

_GLOBAL_BLACKLIST = ["apply_auto_shading", "suggest_antialiasing"]


# ---------------------------------------------------------------------------
# NES terrain color hints (FLUX)
# ---------------------------------------------------------------------------

_NES_TERRAIN_COLOR_HINTS: list[tuple[list[str], str]] = [
    (["grass", "field", "meadow", "lawn", "turf"],
     "IMPORTANT: The colors MUST be shades of GREEN. Bright green and dark green only. "
     "Like the green grass tiles in Super Mario Bros and Legend of Zelda."),
    (["water", "ocean", "sea", "lake", "river", "pond"],
     "IMPORTANT: The colors MUST be shades of BLUE. Blue and dark blue only. "
     "Like the water tiles in Super Mario Bros."),
    (["sand", "desert", "beach", "dune"],
     "IMPORTANT: The colors MUST be TAN and YELLOW. "
     "Sandy warm tones only, like NES desert levels."),
    (["stone", "rock", "cave", "dungeon", "castle", "fortress"],
     "IMPORTANT: The colors MUST be shades of GRAY. Light gray and dark gray only. "
     "Like the dungeon walls in Legend of Zelda and Castlevania."),
    (["brick", "wall", "masonry"],
     "IMPORTANT: The colors MUST be BROWN and dark RED. "
     "Like the brown brick tiles in Super Mario Bros."),
    (["wood", "plank", "floor", "deck", "log", "timber"],
     "IMPORTANT: The colors MUST be shades of BROWN. "
     "Like wooden floor tiles in NES RPGs."),
    (["snow", "ice", "frost", "winter", "tundra"],
     "IMPORTANT: The colors MUST be WHITE and LIGHT BLUE."),
    (["lava", "magma", "fire", "volcano"],
     "IMPORTANT: The colors MUST be RED and ORANGE."),
    (["dirt", "mud", "earth", "soil", "ground"],
     "IMPORTANT: The colors MUST be shades of BROWN. Dark brown and medium brown only."),
]


# ---------------------------------------------------------------------------
# NES palette rules (MCP) — template strings with {n}, {c0}, {r0}, etc.
# ---------------------------------------------------------------------------

_NES_PALETTE_RULES: dict[str, str] = {
    "retro": """\
PALETTE RULES:
- You have exactly {n} colors. No gradients, no shading, no color transitions.
- Color 1 ({c0}, {r0}) is the shape fill — the main body of the sprite.
- Color 2 ({c1}, {r1}) is the secondary shape or negative space within the form.
{extra_color}\
- Every color boundary must be a hard horizontal or vertical edge. No diagonal color transitions.
- No dithering. No shading. Pure flat color blocks.""",

    "early": """\
PALETTE RULES:
- You have {n} colors plus transparency.
- {c0} ({r0}): used for the 1px border around the entire sprite AND internal feature lines (eyes, belt, boot tops).
- {c1} ({r1}): fills 60-70% of opaque pixels. This is the main body/clothing color.
{extra_color}\
- NO highlight color exists at this era. Do not fake highlights with lighter pixels.
- All color regions are solid blocks. Minimum region size is 2x2 pixels.""",

    "mid": """\
PALETTE RULES:
- You have {n} colors plus transparency. One MUST be a dedicated highlight.
- {c0} ({r0}): 1px border on all external edges. Also used for eyes, mouth, belt lines.
- {c1} ({r1}): largest fill area (40-50% of opaque pixels). Main body/armor/clothing.
- {c2} ({r2}): second largest area (25-35%). Contrasting element — skin, cape, boots.
{extra_color}\
- Highlight color: SMALLEST usage (5-15% of pixels). Place ONLY on:
  * Top-left edge of rounded surfaces (e.g. head/helmet top, shoulder, the upper edge of any curved object)
  * Single-pixel dots on the topmost row of curved features
  * Never more than 2 pixels wide in any cluster
- Light source is top-left. Highlights go on top and left edges of convex shapes.""",

    "late": """\
PALETTE RULES:
- You have {n} colors plus transparency. Colors are pre-organized into hue-shifted triads.
- The hue shifting is ALREADY DONE in your palette. You do NOT need to invent new colors.
  Just use each color in its assigned role.
- BODY TRIAD (primary region — armor, robe, main clothing):
  * {c1} (body_shadow): bottom-right edges, undersides, folds. 15-20% of body area.
  * {c2} (body_midtone): largest fill. 50-60% of body area. The base color.
  * {c4} (body_highlight): top-left convex edges ONLY. Single-pixel placements. 5-10% of body.
- ACCENT TRIAD (secondary region — cape, skin, boots, equipment):
  * {c0} (outline): 1px border on ALL external edges. Also eyes, mouth, belt lines.
    This is a dark chromatic color, NOT pure black.
  * {c3} (accent_midtone): secondary region fill — skin, cape, boots, or contrasting clothing.
  * {c5} (accent_highlight): bright accent detail — gem, buckle center, eye glint.
- HOW TO USE THE TRIADS:
  * The body region: paint mostly with body_midtone, add body_shadow on bottom/right edges,
    add body_highlight as single pixels on top/left edges.
  * The accent region: paint with accent_midtone, use accent_highlight for 1-2 detail pixels.
  * Outline wraps everything.
- Strategic single-pixel highlights — place exactly 1 bright pixel on each of:
  * Top of head or hair
  * Left shoulder peak
  * Topmost pixel of any held item (only when the subject names one)
  * Buckle, gem, or small focal feature center
{color_list}""",
}


# ---------------------------------------------------------------------------
# NES color theory rules (MCP)
# ---------------------------------------------------------------------------

_NES_COLOR_THEORY_RULES: dict[str, str] = {
    "retro": """\
COLOR THEORY:
- At 2-3 colors, theory is irrelevant. Pick high-contrast colors and use them flat.
- Maximum luminance distance between your colors — the shape IS the art.""",

    "early": """\
COLOR THEORY:
- Shadows and highlights don't exist at this era. All fills are flat solid color.
- Pick colors with strong value contrast so the outline reads clearly.
- If using 3 colors: darkest for outline, mid-value for body, lightest for skin/accent.""",

    "mid": """\
COLOR THEORY:
- Light source is TOP-LEFT for all sprites. This is universal NES convention.
- Highlight placement: top and left edges of convex surfaces only.
- Shadow placement: bottom and right edges, undersides of overhangs.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: shading around all edges equally like a pillow. Wrong. Shade from one direction.
  * BANDING: visible parallel lines where colors meet. Break up with staggered pixel placement.
- Outline color should be the darkest color. Use it for external edges AND internal feature separation.""",

    "late": """\
COLOR THEORY:
- Light source is TOP-LEFT. All shading decisions follow this.
- HUE SHIFTING (critical for late-era quality):
  * Shadows: shift hue TOWARD BLUE/PURPLE, lower value. A red cape's shadow is dark purple-red, not dark red.
  * Highlights: shift hue TOWARD YELLOW/WHITE, raise value. A blue armor's highlight is cyan-white, not light blue.
  * This makes colors feel vibrant instead of flat. It's what separates good NES art from amateur pixel art.
- NEVER use pure #000000 for shadows — use a dark chromatic color (dark navy, dark brown, dark purple).
- NEVER use pure #FFFFFF for highlights — use a tinted bright color.
- Build 3-step gradients within each body region: shadow → midtone → highlight.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: lighting from all sides equally. Always shade from top-left only.
  * BANDING: parallel color bands. Stagger transitions with 1px offsets.
  * OVER-ANTIALIASING: 1px AA is enough. 2-3px wide AA looks GBA, not NES.
- Strategic highlight placement creates the illusion of material:
  * METAL: high contrast, sharp transitions, 1px specular highlight at brightest point
  * FABRIC: soft transitions, shadow color visible in folds
  * SKIN: midtone dominant, shadow under chin/arms, highlight on forehead/cheekbone""",
}


# ---------------------------------------------------------------------------
# NES tool configs (MCP)
# ---------------------------------------------------------------------------

_NES_TOOL_CONFIGS: dict[str, dict] = {
    "retro": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_pixels",
        ],
        "blacklist": _GLOBAL_BLACKLIST + [
            "draw_circle", "apply_outline", "draw_with_dither",
            "apply_shading", "draw_line", "draw_contour",
        ],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (filled=true), draw_pixels
AVOID: draw_circle (rasterizes to rectangles at 8x8), apply_outline (wastes pixels),
  draw_with_dither (invisible at this scale), apply_auto_shading, suggest_antialiasing
At 8x8 pixels, every pixel is precious. Use rectangles for body blocks, draw_pixels for 1-2 accent details.""",
    },
    "early": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_pixels",
            "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + [
            "draw_circle", "draw_with_dither", "apply_shading",
        ],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (filled=true for body scaffolding),
  draw_pixels (detail placement), apply_outline (color=#000000, thickness=1)
AVOID: draw_circle (too small to rasterize well at 12x16), draw_with_dither,
  apply_auto_shading, suggest_antialiasing, apply_shading
Outline is applied LAST, after all pixels are placed.""",
    },
    "mid": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + ["apply_shading"],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (body scaffolding), draw_circle (rounded forms like the head),
  draw_pixels (main workhorse for detail), draw_line (long thin elements such as belt lines, or held-item shafts when the subject names them),
  apply_outline (color=#000000, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2 or bayer_4x4, ONLY for ground/terrain tiles, NEVER for characters
AVOID: apply_auto_shading (produces GBA gradients, not NES), suggest_antialiasing (GBA technique),
  apply_shading (un-NES smooth gradients)
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
    "late": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (scaffolding), draw_circle (scaffolding),
  draw_pixels (PRIMARY tool — 80%+ of drawing), draw_line (long thin elements such as belt lines, or held-item shafts when the subject names them),
  draw_contour (complex shapes), apply_outline (dark chromatic color, NOT black, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2, bayer_4x4, bayer_8x8, floyd_steinberg. Good for terrain tiles.
AVOID: apply_auto_shading (adds GBA-style intermediate colors), suggest_antialiasing (GBA technique)
CRITICAL: All shading must be manual via draw_pixels. Do NOT use any auto-shading tool.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
}


# ---------------------------------------------------------------------------
# NES view rules (MCP)
# ---------------------------------------------------------------------------

_NES_VIEW_RULES: dict[str, str] = {
    "side": """\
VIEW: Side profile (facing right — NES convention).
- Character faces right. Leading arm/leg slightly forward, trailing slightly back.
- Anything held (only when the subject names a held item) goes in the leading (right) hand, visible on the right side.
- Shadow colors on the back (left) edges of the body.
- Depth: near arm overlaps torso, far arm may be partially hidden.""",

    "front": """\
VIEW: Front facing.
- Bilateral symmetry: left half mirrors right half (within 1px tolerance).
- Arms equidistant from center. A held item (when the subject names one) may break symmetry.
- Shadow colors on bottom edges of features.
- Eyes at same height, same size, centered on face.""",

    "top-down": """\
VIEW: Top-down / overhead.
- Head is a circle/oval filling top 60% of canvas.
- Shoulders visible as wider rectangle below head circle.
- No legs visible. Feet may peek at bottom edge.
- Shadow on bottom edge of head oval.
- Items visible from above: hat or headwear dominant; held items extend to the side only when the subject names them.""",

    "3/4": """\
VIEW: 3/4 perspective (facing right and slightly toward viewer).
- Right side of body is 1-2px wider than left (foreshortening).
- Right arm more visible than left. Right leg forward.
- Shadow on left edges (farther from viewer).
- Face shows both eyes but right eye 1px larger or closer to center.""",
}


# ---------------------------------------------------------------------------
# NES few-shot examples (MCP)
# ---------------------------------------------------------------------------

_NES_FEW_SHOT_EXAMPLES: dict[str, str] = {
    "retro": """\
REFERENCE EXAMPLE — Retro 8x8 ghost (quality benchmark, do not copy):
Palette: #000000 (dark), #626262 (midtone), #FFFFFF (light)
Key pixels: body is a 6x5 oval of midtone (rows 1-5, cols 1-6),
  eyes are 2 dark pixels at (2,2) and (4,2),
  bottom edge is jagged (alternating midtone/transparent) for wispy look.
Total: ~22 opaque pixels. Shape reads as "ghost" at 1x zoom.""",

    "early": """\
REFERENCE EXAMPLE — Early 12x16 humanoid character (quality benchmark, do not copy):
Palette: #000000 (outline), #0058F8 (primary garment), #F8D878 (secondary/skin)
Key structure: 1px black outline around entire sprite.
  Head 4x4 at rows 1-4, centered. Face = 2x2 skin at (4,2)-(5,3).
  Torso 6x4 primary at rows 5-8. Arms 1px wide, extend from torso sides.
  Legs 2x4 primary at rows 9-12, 2px gap between. Feet 3px wide at row 13.
  Optional held item (only when the subject names one): 1px line of secondary extending 3px above the right shoulder.
Total: ~60-65 opaque pixels (varies with held item). Chunky, blocky, immediately reads as a clear character silhouette.""",

    "mid": """\
REFERENCE EXAMPLE — Mid 16x16 humanoid character (quality benchmark, do not copy):
Palette: #000000 (outline), #787878 (primary garment), #F83800 (warm secondary), #BCBCBC (highlight)
Key structure: 1px black outline. Head 4x4 primary at rows 2-5 with a 2px feature slit (eyes, visor, or shadow band — depends on the subject).
  Optional headwear/crest/hair: 2px at rows 0-1 above the head. Highlight pixel on head top.
  Torso 6x4 at rows 6-9, warm-secondary clothing with primary-color edge trim.
  Optional left-arm item or accessory (only when the subject names one): 3x3 contrasting block with a single accent pixel at center.
  Optional right-arm held item (only when the subject names one): 1px wide primary extending from row 1 to row 6.
  Legs 2x4 primary at rows 10-13, footwear 2px wider at row 14.
  Highlight pixels: head top, left shoulder edge, peak of any held item.
Total: ~50-65 opaque pixels (varies with optional items). Clear silhouette with readable distinct body parts.""",

    "late": """\
REFERENCE EXAMPLE — Late 16x16 humanoid character with hooded garment (quality benchmark, do not copy):
Palette: #181848 (outline/navy), #3B0076 (shadow/purple), #6A12C2 (midtone), #A862FE (highlight), #F8D878 (skin), #F83800 (warm accent)
Key structure: Dark navy outline (NOT black). Hood/headwear 5x4 with 3-step purple gradient
  (shadow at bottom, midtone center, highlight at top-left edge).
  Face: 2x2 skin with highlight pixel on forehead.
  Robe/garment: 8x6 with shadow on right side, midtone center, highlight on left shoulder.
  Optional held item (only when the subject names one): 1px wide extending from hand to row 0, accent-color pixel at the top (e.g. a bottle, lantern, brush handle, or other named object).
  Garment bottom: jagged hem with shadow/midtone alternating.
  Highlight pixels: hood top-left, left shoulder, peak of any held item, belt buckle.
Total: ~70-80 opaque pixels (varies with optional items). Shading creates volume. Materials read differently (fabric vs skin vs accent).""",
}


# ---------------------------------------------------------------------------
# NES ConsolePromptData
# ---------------------------------------------------------------------------

NES_PROMPT_DATA = ConsolePromptData(
    name="nes",
    display_name="NES",
    default_era="mid",
    eras={
        "retro": _NES_ERA_RETRO,
        "early": _NES_ERA_EARLY,
        "mid": _NES_ERA_MID,
        "late": _NES_ERA_LATE,
    },
    terrain_color_hints=_NES_TERRAIN_COLOR_HINTS,
    palette_rules=_NES_PALETTE_RULES,
    color_theory_rules=_NES_COLOR_THEORY_RULES,
    tool_configs=_NES_TOOL_CONFIGS,
    view_rules=_NES_VIEW_RULES,
    few_shot_examples=_NES_FEW_SHOT_EXAMPLES,
    mood_palettes=None,
    palette_presets=None,
)


# ---------------------------------------------------------------------------
# Game Boy DMG era prompt data
# ---------------------------------------------------------------------------

_GB_DMG_ERA_EARLY = EraPromptData(
    label="early Game Boy DMG style (1989-1991), simple blocky sprites, high-contrast shading",
    year_range="1989-1991",
    reference_games="Tetris, Super Mario Land, Alleyway",
    style_ref="Style: Tetris, Super Mario Land (1989) Game Boy sprites. Simple geometric shapes, high-contrast shade blocking.",
    tile_ref="Style: Super Mario Land ground tiles, Tetris block patterns.",
    era_hints=(
        "Early Game Boy pixel art, 1989-1991 era. "
        "Only 4 shades available: lightest (shade 0), light (shade 1), dark (shade 2), darkest (shade 3). "
        "Sprites use only shades 1-3 (shade 0 is transparent). "
        "Simple geometric forms, minimal internal detail. "
        "Shade 3 carries all outlines and heavy structure. "
        "Shade 1 or 2 fills the body as a single flat tone. "
        "No dithering — flat shade blocks only. "
        "Style: Super Mario Land, Tetris, Alleyway — "
        "the most basic and chunky Game Boy sprites."
    ),
    outline_hint="Shade 3 (darkest) outline around entire sprite.",
    pixel_scale=6,
    max_cleanup_colors=3,
)

_GB_DMG_ERA_MID = EraPromptData(
    label="Game Boy DMG style (1991-1993)",
    year_range="1991-1993",
    reference_games="Kirby's Dream Land, Super Mario Land 2, Link's Awakening",
    style_ref="Style: Kirby's Dream Land, Super Mario Land 2, Link's Awakening Game Boy sprites.",
    tile_ref="Style: Link's Awakening overworld tiles, Super Mario Land 2 terrain.",
    era_hints=(
        "Mid-era Game Boy pixel art, 1991-1993. "
        "All 4 shades used with clear purpose: shade 3 for outlines and deep shadow, "
        "shade 2 for body fills and mid-tone, shade 1 for highlights and lighter elements. "
        "Silhouette is the primary identity marker — shape must be recognizable as a solid black blob. "
        "Shade 2 internal lines separate body regions (arm from torso, head from body). "
        "Light dithering on backgrounds for texture, but sprites stay clean. "
        "Characters have recognizable features: eyes, equipment, distinctive accessories. "
        "Style: Kirby's Dream Land, Super Mario Land 2, Link's Awakening — "
        "the definitive Game Boy look."
    ),
    outline_hint="Shade 3 (darkest) outline with shade 2 internal detail lines.",
    pixel_scale=None,
    max_cleanup_colors=4,
)

_GB_DMG_ERA_LATE = EraPromptData(
    label="refined late Game Boy DMG style (1994-1996), detailed shading with all 4 shades",
    year_range="1994-1996",
    reference_games="Pokemon Red/Blue, Wario Land, Donkey Kong '94",
    style_ref="Style: Pokemon Red/Blue, Wario Land, Donkey Kong '94 Game Boy sprites. Detailed shading, expressive silhouettes.",
    object_ref="Style: Pokemon Red/Blue, Wario Land, Donkey Kong '94 Game Boy sprites. Detailed shading across all 4 shades.",
    tile_ref="Style: Pokemon Red/Blue town tiles, Wario Land pirate ship planking.",
    era_hints=(
        "Late Game Boy pixel art, 1994-1996 — the peak of DMG art. "
        "Sophisticated use of all 4 shades to create depth and volume. "
        "Shade 3 for outlines and deep features, shade 2 for main body and shadow, "
        "shade 1 for highlights and lighter elements. "
        "Dithering used strategically for texture: checkerboard shade 1/2 mixes "
        "create a virtual fifth tone for gradients and ground surfaces. "
        "Expressive character design with distinctive silhouettes — "
        "each sprite reads clearly as its subject even as a solid black blob. "
        "Style: Pokemon Red/Blue, Wario Land, Donkey Kong '94 — "
        "maximum polish within the 4-shade constraint."
    ),
    outline_hint="Shade 3 outline with occasional shade 2 softening on curved surfaces.",
    pixel_scale=None,
    max_cleanup_colors=4,
)


# ---------------------------------------------------------------------------
# Game Boy DMG terrain color hints (FLUX)
# ---------------------------------------------------------------------------

_GB_DMG_TERRAIN_COLOR_HINTS: list[tuple[list[str], str]] = [
    (["grass", "field", "meadow", "lawn", "turf"],
     "IMPORTANT: Use strong value contrast. Medium-dark green tones for grass body, "
     "dark outlines for blade edges. Monochrome-friendly composition."),
    (["water", "ocean", "sea", "lake", "river", "pond"],
     "IMPORTANT: Dark tones for water body with light ripple highlights. "
     "High contrast between wave crests and water surface."),
    (["sand", "desert", "beach", "dune"],
     "IMPORTANT: Light tones for sand with sparse dark speckle texture. "
     "Keep overall value bright."),
    (["stone", "rock", "cave", "dungeon", "castle", "fortress"],
     "IMPORTANT: Medium-dark tones for stone with occasional light highlights. "
     "Like the cave walls in Metroid II and Link's Awakening dungeons."),
    (["brick", "wall", "masonry"],
     "IMPORTANT: Medium tones with dark mortar lines between bricks."),
    (["wood", "plank", "floor", "deck", "log", "timber"],
     "IMPORTANT: Alternating medium and dark tones for wood grain pattern."),
    (["snow", "ice", "frost", "winter", "tundra"],
     "IMPORTANT: Primarily lightest tones with sparse dark details for definition."),
    (["lava", "magma", "fire", "volcano"],
     "IMPORTANT: High contrast — darkest body with lightest highlights for glow effect."),
    (["dirt", "mud", "earth", "soil", "ground"],
     "IMPORTANT: Medium-dark tones with dithered texture for soil surface."),
]


# ---------------------------------------------------------------------------
# Game Boy DMG palette rules (MCP)
# ---------------------------------------------------------------------------

_GB_DMG_PALETTE_RULES: dict[str, str] = {
    "early": """\
PALETTE RULES:
- You have exactly {n} shades. Shade 0 is transparent for sprites.
- {c0} (darkest): outline around entire sprite AND eyes/mouth features.
- {c1} (mid-dark or mid-light): body fill — pick ONE shade for the main body, keep it flat.
{extra_color}\
- No dithering. No gradients. Pure flat shade blocks.
- Every shade boundary must be a hard horizontal or vertical edge.""",

    "mid": """\
PALETTE RULES:
- You have {n} shades plus transparency (shade 0).
- {c0} (darkest, {r0}): 1px outline on all external edges. Also eyes, feature lines.
- {c1} ({r1}): main body fill, covers 40-50% of opaque pixels.
- {c2} ({r2}): highlights, skin, lighter elements, 25-35% of pixels.
{extra_color}\
- Silhouette is everything — sprite must be recognizable as a solid dark blob.
- Use the mid shade for internal feature separation (arm from torso, head from body).
- Light source is top-left. Lighter shade on top/left edges of convex shapes.""",

    "late": """\
PALETTE RULES:
- You have {n} shades plus transparency (shade 0).
- {c0} (darkest, {r0}): outline and deep features (eyes, mouth, shadow recesses).
- {c1} ({r1}): main body midtone, largest fill area (40-50%).
- {c2} ({r2}): highlights and lighter elements (25-35%).
{extra_color}\
- Strategic dithering: checkerboard patterns of adjacent shades create
  a virtual fifth tone. Use ONLY for ground textures and large surface gradients.
- Every sprite must have a distinctive silhouette readable without shade variation.
{color_list}""",
}


# ---------------------------------------------------------------------------
# Game Boy DMG color theory rules (MCP)
# ---------------------------------------------------------------------------

_GB_DMG_COLOR_THEORY_RULES: dict[str, str] = {
    "early": """\
COLOR THEORY:
- With only 3 usable shades, theory reduces to contrast management.
- Darkest shade defines form. Mid shade fills body. Any third shade is accent.
- Maximum value distance between outline and fill for legibility.""",

    "mid": """\
COLOR THEORY:
- Light source is TOP-LEFT (Game Boy convention matches NES).
- No color exists — only VALUE. Shade placement IS the entire art.
- Lighter shades on top and left edges of convex surfaces.
- Darker shades on bottom and right edges, undersides.
- SILHOUETTE RULE: The sprite must read as its subject when all shades
  are collapsed to pure black. If the silhouette is ambiguous, the sprite fails.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: darkest shade ringing all edges equally. Shade from one direction.
  * SHADE SOUP: all 3 usable shades mixed randomly. Each shade needs a clear role.""",

    "late": """\
COLOR THEORY:
- Light source is TOP-LEFT. All shading decisions follow this.
- SHADE ALLOCATION (critical for late-era quality):
  * Darkest shade (shade 3): outlines, deep shadow, eye pupils, recesses.
  * Mid shade (shade 2): main body fill, the workhorse. 40-50% of pixels.
  * Light shade (shade 1): highlights on top-left edges, skin, lighter clothing.
- DITHERING for apparent tonal variety:
  * Checkerboard of shade 1 + shade 2 reads as a virtual mid-tone.
  * Use only on surfaces larger than 4x4 pixels. Below that it reads as noise.
  * Ideal for: ground texture, water surfaces, cave walls, shadow gradients.
- SILHOUETTE FIRST: design the shape, THEN shade it. Never let shading
  obscure the silhouette boundary.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: shading from all sides. Always top-left light source.
  * BANDING: visible parallel shade lines. Break up with staggered offsets.
  * OVER-DITHERING: dithering on small sprites (8x8) produces noise, not texture.""",
}


# ---------------------------------------------------------------------------
# Game Boy DMG tool configs (MCP)
# ---------------------------------------------------------------------------

_GB_DMG_TOOL_CONFIGS: dict[str, dict] = {
    "early": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_pixels",
            "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + [
            "draw_circle", "draw_with_dither", "apply_shading",
            "draw_contour",
        ],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (filled=true for body blocks),
  draw_pixels (detail placement), apply_outline (darkest shade, thickness=1)
AVOID: draw_circle (too small to rasterize well), draw_with_dither (noise at this scale),
  apply_auto_shading, suggest_antialiasing, apply_shading
Build with rectangles, refine with draw_pixels. Outline applied LAST.""",
    },
    "mid": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + ["apply_shading"],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (body scaffolding), draw_circle (rounded forms like the head),
  draw_pixels (main workhorse for detail), draw_line (long thin elements such as belt lines, or held-item shafts when the subject names them),
  apply_outline (darkest shade, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2, ONLY for background tiles, NEVER for character sprites
AVOID: apply_auto_shading (produces gradients, not 4-shade art), suggest_antialiasing,
  apply_shading (smooth gradients impossible with 4 shades)
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
    "late": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (scaffolding), draw_circle (scaffolding),
  draw_pixels (PRIMARY tool — 80%+ of drawing), draw_line (long thin elements such as belt lines, or held-item shafts when the subject names them),
  draw_contour (complex shapes), apply_outline (darkest shade, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2 or bayer_4x4 for terrain tiles.
AVOID: apply_auto_shading (adds gradient colors outside 4-shade limit), suggest_antialiasing
CRITICAL: All shading must be manual via draw_pixels. Only 4 shades exist — no auto tools.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
}


# ---------------------------------------------------------------------------
# Game Boy DMG view rules (MCP)
# ---------------------------------------------------------------------------

_GB_DMG_VIEW_RULES: dict[str, str] = {
    "side": """\
VIEW: Side profile (facing right — standard convention).
- Character faces right. Leading arm/leg slightly forward.
- Anything held (only when the subject names a held item) goes in the leading (right) hand, visible on the right side.
- Darker shades on the back (left) edges of the body.
- Silhouette must read clearly — exaggerate the subject's distinctive features (hair, hat, posture, or any item the subject names).""",

    "front": """\
VIEW: Front facing.
- Bilateral symmetry: left half mirrors right half.
- Arms equidistant from center. A held item (when the subject names one) may break symmetry.
- Darker shades on bottom edges of features.
- Eyes at same height, same size, centered on face.""",

    "top-down": """\
VIEW: Top-down / overhead.
- Head is a circle/oval filling top 60% of canvas.
- Shoulders visible as wider shape below head.
- No legs visible. Items visible from above (only when the subject names them).
- Darker shade on bottom edge of head oval.""",

    "3/4": """\
VIEW: 3/4 perspective (facing right and slightly toward viewer).
- Right side of body 1-2px wider than left (foreshortening).
- Right arm more visible than left.
- Darker shades on left edges (farther from viewer).
- Face shows both eyes but right eye 1px larger.""",
}


# ---------------------------------------------------------------------------
# Game Boy DMG few-shot examples (MCP)
# ---------------------------------------------------------------------------

_GB_DMG_FEW_SHOT_EXAMPLES: dict[str, str] = {
    "early": """\
REFERENCE EXAMPLE — Early GB 8x16 character (quality benchmark, do not copy):
Shades: #0F380F (darkest/outline), #306230 (dark), #8BAC0F (light)
Key structure: 1px darkest outline around entire sprite.
  Head 4x4 at rows 1-4, centered. Face = 2x2 light shade.
  Torso 6x4 dark shade at rows 5-8. Arms 1px wide.
  Legs 2x4 dark shade at rows 9-12.
Total: ~50 opaque pixels. Chunky, blocky, reads as "small person.\"""",

    "mid": """\
REFERENCE EXAMPLE — Mid GB 16x16 humanoid character (quality benchmark, do not copy):
Shades: #0F380F (darkest/outline), #306230 (dark/body), #8BAC0F (light/highlight)
Key structure: 1px darkest outline. Head 4x4 with light shade face at rows 2-5.
  Optional headwear detail (cap, hair, hood) in dark shade at rows 0-2.
  Torso 6x4 dark shade at rows 6-9, light highlights on left shoulder.
  Optional left-arm item or accessory (only when the subject names one): 3x3 dark with light center pixel.
  Optional right-arm held item (only when the subject names one): 1px darkest extending from row 1 to row 6.
  Legs dark shade at rows 10-13, footwear slightly wider.
  Silhouette: reads as a clear character figure even when collapsed to solid black.
Total: ~50-65 opaque pixels (varies with optional items).""",

    "late": """\
REFERENCE EXAMPLE — Late GB 16x16 creature (quality benchmark, do not copy):
Shades: #0F380F (darkest), #306230 (dark), #8BAC0F (light), #9BBC0F (lightest/rare highlight)
Key structure: Darkest outline, NOT uniform — thins on top-left (light side).
  Body 8x8 core: dark shade fill with light shade on top-left quadrant.
  Eyes: 2px darkest on light shade face area. Single lightest pixel for eye glint.
  Claws/tail: darkest shade extending from body, 1-2px wide.
  Dithered shadow: checkerboard dark+light under body (rows 14-15).
  Silhouette: distinctive non-human shape readable at 1x zoom.
Total: ~80 opaque pixels. Shade placement creates volume and form.""",
}


# ---------------------------------------------------------------------------
# Game Boy DMG ConsolePromptData
# ---------------------------------------------------------------------------

GB_DMG_PROMPT_DATA = ConsolePromptData(
    name="gb_dmg",
    display_name="Game Boy",
    default_era="mid",
    eras={
        "early": _GB_DMG_ERA_EARLY,
        "mid": _GB_DMG_ERA_MID,
        "late": _GB_DMG_ERA_LATE,
    },
    terrain_color_hints=_GB_DMG_TERRAIN_COLOR_HINTS,
    palette_rules=_GB_DMG_PALETTE_RULES,
    color_theory_rules=_GB_DMG_COLOR_THEORY_RULES,
    tool_configs=_GB_DMG_TOOL_CONFIGS,
    view_rules=_GB_DMG_VIEW_RULES,
    few_shot_examples=_GB_DMG_FEW_SHOT_EXAMPLES,
    mood_palettes=None,
    palette_presets=None,
)


# ---------------------------------------------------------------------------
# Game Boy Pocket mid era — separate from DMG mid to carry pixel_scale=6
# and the silhouette-test era_hint addition.
# ---------------------------------------------------------------------------

_GB_POCKET_ERA_MID = EraPromptData(
    label="Game Boy Pocket style (1991-1993)",
    year_range="1991-1993",
    reference_games="Kirby's Dream Land, Super Mario Land 2, Link's Awakening",
    style_ref="Style: Kirby's Dream Land, Super Mario Land 2, Link's Awakening Game Boy sprites.",
    tile_ref="Style: Link's Awakening overworld tiles, Super Mario Land 2 terrain.",
    era_hints=(
        "Mid-era Game Boy pixel art, 1991-1993. "
        "All 4 shades used with clear purpose: shade 3 for outlines and deep shadow, "
        "shade 2 for body fills and mid-tone, shade 1 for highlights and lighter elements. "
        "Silhouette is the primary identity marker — shape must be recognizable as a solid black blob. "
        "Shade 2 internal lines separate body regions (arm from torso, head from body). "
        "Light dithering on backgrounds for texture, but sprites stay clean. "
        "Characters have recognizable features: eyes, equipment, distinctive accessories. "
        "Style: Kirby's Dream Land, Super Mario Land 2, Link's Awakening — "
        "the definitive Game Boy look. "
        "SILHOUETTE TEST: the sprite must read as its subject when collapsed to a solid block of a single color. "
        "strong value contrast across the 4 shades; silhouette legible as a solid block."
    ),
    outline_hint="Shade 3 (darkest) outline with shade 2 internal detail lines.",
    pixel_scale=6,
    max_cleanup_colors=4,
)


# ---------------------------------------------------------------------------
# Game Boy Pocket few-shot examples (MCP) — true grayscale hex values
# ---------------------------------------------------------------------------

_GB_POCKET_FEW_SHOT_EXAMPLES: dict[str, str] = {
    "early": """\
REFERENCE EXAMPLE — Early GB Pocket 8x16 character (quality benchmark, do not copy):
Shades: #000000 (black/outline), #555555 (dark gray), #AAAAAA (light gray)
Key structure: 1px black outline around entire sprite.
  Head 4x4 at rows 1-4, centered. Face = 2x2 light gray.
  Torso 6x4 dark gray at rows 5-8. Arms 1px wide.
  Legs 2x4 dark gray at rows 9-12.
Total: ~50 opaque pixels. Chunky, blocky, reads as "small person.\"""",

    "mid": """\
REFERENCE EXAMPLE — Mid GB Pocket 16x16 humanoid character (quality benchmark, do not copy):
Shades: #000000 (black/outline), #555555 (dark gray/body), #AAAAAA (light gray/highlight)
Key structure: 1px black outline. Head 4x4 with light gray face at rows 2-5.
  Optional headwear detail (cap, hair, hood) in dark gray at rows 0-2.
  Torso 6x4 dark gray at rows 6-9, light gray highlights on left shoulder.
  Optional left-arm item or accessory (only when the subject names one): 3x3 dark gray with light gray center pixel.
  Optional right-arm held item (only when the subject names one): 1px black extending from row 1 to row 6.
  Legs dark gray at rows 10-13, footwear slightly wider.
  Silhouette: reads as a clear character figure even when collapsed to solid black.
Total: ~50-65 opaque pixels (varies with optional items).""",

    "late": """\
REFERENCE EXAMPLE — Late GB Pocket 16x16 creature (quality benchmark, do not copy):
Shades: #000000 (black), #555555 (dark gray), #AAAAAA (light gray), #FFFFFF (white/rare highlight)
Key structure: Black outline, NOT uniform — thins on top-left (light side).
  Body 8x8 core: dark gray fill with light gray on top-left quadrant.
  Eyes: 2px black on light gray face area. Single white pixel for eye glint.
  Claws/tail: black extending from body, 1-2px wide.
  Dithered shadow: checkerboard dark gray + light gray under body (rows 14-15).
  Silhouette: distinctive non-human shape readable at 1x zoom.
Total: ~80 opaque pixels. Shade placement creates volume and form.""",
}


# ---------------------------------------------------------------------------
# Game Boy Pocket ConsolePromptData
# ---------------------------------------------------------------------------

GB_POCKET_PROMPT_DATA = ConsolePromptData(
    name="gb_pocket",
    display_name="Game Boy Pocket",
    default_era="mid",
    eras={
        "early": _GB_DMG_ERA_EARLY,
        "mid": _GB_POCKET_ERA_MID,
        "late": _GB_DMG_ERA_LATE,
    },
    terrain_color_hints=_GB_DMG_TERRAIN_COLOR_HINTS,
    palette_rules=_GB_DMG_PALETTE_RULES,
    color_theory_rules=_GB_DMG_COLOR_THEORY_RULES,
    tool_configs=_GB_DMG_TOOL_CONFIGS,
    view_rules=_GB_DMG_VIEW_RULES,
    few_shot_examples=_GB_POCKET_FEW_SHOT_EXAMPLES,
    mood_palettes=None,
    palette_presets=None,
)


# ---------------------------------------------------------------------------
# Commodore 64 era prompt data
# ---------------------------------------------------------------------------

_C64_ERA_EARLY = EraPromptData(
    label="early Commodore 64 style (1982-1985), simple character mode, basic sprite usage",
    year_range="1982-1985",
    reference_games="Boulder Dash, Impossible Mission, Jumpman",
    style_ref="Style: Impossible Mission agent sprite — bold near-single-color silhouette, shape alone conveys the subject, minimal internal detail.",
    tile_ref="Style: Boulder Dash cave tiles, Jumpman girder platforms, early C64 character-mode environments.",
    era_hints=(
        "Early Commodore 64 pixel art, 1982-1985 era. "
        "Character mode dominates: environments built from redefined 8x8 character tiles "
        "with per-cell foreground colors against a single global background. "
        "Sprites are hi-res mode — 24x21 pixels, single foreground color plus transparency. "
        "Silhouette is everything: the sprite shape alone must convey the subject "
        "because only 1 sprite color is available. "
        "Earthy, muted palette — brown, dark gray, and orange are common background anchors. "
        "Style: Boulder Dash (character-mode cave environments), "
        "Impossible Mission (hi-res animated agent), Jumpman (platform girders and ladders). "
        "Minimal color sophistication — high contrast between sprite and background is the goal. "
        "SILHOUETTE TEST: the sprite must read as its subject when collapsed to a solid block of a single color. "
        "maximum value contrast between sprite color and background."
    ),
    outline_hint="No separate outline — sprite shape defined by single foreground color against transparent background.",
    pixel_scale=6,
    max_cleanup_colors=4,
)

_C64_ERA_MID = EraPromptData(
    label="Commodore 64 multicolor style (1986-1988), double-wide pixels, sophisticated tile reuse",
    year_range="1986-1988",
    reference_games="The Last Ninja, Maniac Mansion, IK+, Bubble Bobble",
    style_ref="Style: The Last Ninja, Maniac Mansion, IK+, Bubble Bobble C64 sprites. Multicolor mode mastery, isometric environments.",
    tile_ref="Style: The Last Ninja stone gardens, Maniac Mansion room interiors, IK+ beach backgrounds.",
    era_hints=(
        "Mid-era Commodore 64 pixel art, 1986-1988 — multicolor mode mastery. "
        "Double-wide pixels are the signature look: 160x200 effective resolution with chunky, "
        "readable pixel mass. Each multicolor cell gets 3 global colors + 1 per-cell accent. "
        "Artists build scenes around three carefully chosen global palette anchors "
        "(typically a gray, a dark tone, and one mid-value color), then vary the per-cell accent "
        "for local detail — a rock gets brown, foliage gets green, water gets cyan. "
        "Sprites in multicolor mode: 12x21 double-wide pixels, 3 colors + transparency. "
        "The three grays (#444444, #6C6C6C, #959595) are the primary shading tool. "
        "Isometric perspective common (The Last Ninja). Backgrounds are quieter and lower-saturation; "
        "sprites pop with brighter or higher-contrast colors. "
        "Style: The Last Ninja (painterly isometric), Maniac Mansion (tile vocabulary mastery), "
        "IK+ (sprite multiplexing showcase), Bubble Bobble (multicolor character charm)."
    ),
    outline_hint="Black (#000000) or darkest palette color outline, 1 double-wide pixel thick in multicolor mode.",
    pixel_scale=None,
    max_cleanup_colors=6,
)

_C64_ERA_LATE = EraPromptData(
    label="late Commodore 64 style (1989-1992), peak technical achievement, mixed modes, sprite multiplexing",
    year_range="1989-1992",
    reference_games="Turrican, Creatures, Mayhem in Monsterland",
    style_ref="Style: Turrican, Creatures, Mayhem in Monsterland C64 sprites. Peak VIC-II mastery, mixed modes, aggressive multiplexing.",
    tile_ref="Style: Turrican parallax backgrounds, Creatures detailed platforms, Mayhem in Monsterland colorful terrain.",
    era_hints=(
        "Late Commodore 64 pixel art, 1989-1992 — the absolute technical ceiling of the VIC-II chip. "
        "Mixed character and bitmap modes in the same frame via raster interrupts. "
        "Sprite multiplexing pushes beyond the 8-hardware-sprite limit to show 16-24+ simultaneous objects. "
        "Color discipline reaches its peak: gray ramps (#444444 -> #6C6C6C -> #959595) create "
        "smooth shading on metal and stone. The warm cluster (red #68372B, orange #6F4F25, brown #433900, "
        "yellow #B8C76F) and cool cluster (cyan #70A4B2, blue #352879, light blue #6C5EB5) "
        "are deployed strategically for scene temperature. "
        "Parallax scrolling backgrounds, detailed terrain tiles, and polished sprite animation. "
        "Sprites may use simplified color to maximize multiplexer budget — one foreground color "
        "for the suit/body, spending sprite slots on enemies and projectiles instead. "
        "Style: Turrican (platform perfection, multi-directional scrolling), "
        "Creatures (character animation polish), Mayhem in Monsterland (colorful late-era peak). "
        "The most technically sophisticated C64 art ever produced."
    ),
    outline_hint=(
        "Dark outline using darkest available palette color rather than pure black when possible. "
        "Outline may use dark blue (#352879), brown (#433900), or dark gray (#444444) to match the sprite's color scheme."
    ),
    pixel_scale=None,
    max_cleanup_colors=8,
)


# ---------------------------------------------------------------------------
# Commodore 64 terrain color hints (FLUX)
# ---------------------------------------------------------------------------

_C64_TERRAIN_COLOR_HINTS: list[tuple[list[str], str]] = [
    (["grass", "field", "meadow", "lawn", "turf"],
     "IMPORTANT: Use C64 green (#588D43) and light green (#9AD284). "
     "Muted, earthy greens — NOT bright NES greens. Chunky double-wide pixel texture."),
    (["water", "ocean", "sea", "lake", "river", "pond"],
     "IMPORTANT: Use C64 cyan (#70A4B2) and blue (#352879). "
     "Teal-leaning water, not pure blue. Light blue (#6C5EB5) for highlights."),
    (["sand", "desert", "beach", "dune"],
     "IMPORTANT: Use C64 yellow (#B8C76F) and orange (#6F4F25). "
     "Warm sandy tones with brown (#433900) shadows."),
    (["stone", "rock", "cave", "dungeon", "castle", "fortress"],
     "IMPORTANT: Use the C64 gray ramp — dark gray (#444444), medium gray (#6C6C6C), "
     "light gray (#959595). Gray-heavy shading is the C64 signature for stone and metal."),
    (["brick", "wall", "masonry"],
     "IMPORTANT: Use C64 red (#68372B) and brown (#433900). "
     "Earthy, muted brick — darker than NES brick tones."),
    (["wood", "plank", "floor", "deck", "log", "timber"],
     "IMPORTANT: Use C64 brown (#433900) and orange (#6F4F25). "
     "Dark, earthy wood tones with light red (#9A6759) highlights."),
    (["snow", "ice", "frost", "winter", "tundra"],
     "IMPORTANT: Use white (#FFFFFF) and light gray (#959595) with cyan (#70A4B2) accents."),
    (["lava", "magma", "fire", "volcano"],
     "IMPORTANT: Use C64 red (#68372B), orange (#6F4F25), and yellow (#B8C76F). "
     "The warm cluster in full — no bright orange exists in the C64 palette."),
    (["dirt", "mud", "earth", "soil", "ground"],
     "IMPORTANT: Use C64 brown (#433900) and dark gray (#444444). "
     "Very dark, earthy ground. Orange (#6F4F25) for lighter dirt patches."),
]


# ---------------------------------------------------------------------------
# Commodore 64 palette rules (MCP)
# ---------------------------------------------------------------------------

_C64_PALETTE_RULES: dict[str, str] = {
    "early": """\
PALETTE RULES:
- You have exactly {n} colors from the fixed C64 16-color Yannes palette.
- C64 hi-res sprites: 1 foreground color + transparency. Shape IS the art.
- {c0} ({r0}): the single sprite color. All opaque pixels use this one color.
{extra_color}\
- Background tiles in character mode: 1 foreground color per 8x8 cell against a global background.
- No shading possible within a single sprite — silhouette clarity is everything.
- The 16 C64 colors are FIXED hardware. No approximation, no interpolation.""",

    "mid": """\
PALETTE RULES:
- You have {n} colors from the fixed C64 16-color Yannes palette plus transparency.
- Multicolor mode: double-wide pixels (2:1 aspect ratio). Design at 160-pixel width.
- 3 global colors shared across the entire screen + 1 per-cell accent color.
- {c0} ({r0}): outline/darkest — used for sprite edges and internal feature lines.
- {c1} ({r1}): primary body fill — 40-50% of opaque pixels.
- {c2} ({r2}): secondary element — skin, equipment, contrasting region.
{extra_color}\
- GRAY SHADING: The three C64 grays (#444444, #6C6C6C, #959595) are the primary shading tool.
  Use gray ramps for metal, stone, and shadow rather than hue-shifting.
- Minimum feature size is 2 double-wide pixels (4 screen pixels) in multicolor mode.
- Background-foreground split: keep backgrounds quieter (grays, browns, dark blues),
  let sprites use brighter or higher-contrast colors.""",

    "late": """\
PALETTE RULES:
- You have {n} colors from the fixed C64 16-color Yannes palette plus transparency.
- Mixed modes: hi-res (320x200, 2 colors/cell) and multicolor (160x200, 4 colors/cell)
  can coexist in the same frame via raster interrupts.
- {c0} ({r0}): outline — a dark chromatic color, not necessarily black.
  Dark blue (#352879), brown (#433900), or dark gray (#444444) for tinted outlines.
- {c1} ({r1}): primary body midtone — largest fill area (40-50%).
- {c2} ({r2}): secondary region — skin, cape, contrasting element (25-35%).
{extra_color}\
- GRAY RAMP SHADING: Build shading from the three grays:
  * #444444 (dark gray) for shadow
  * #6C6C6C (medium gray) for midtone
  * #959595 (light gray) for highlight
  This trio replaces hue-shifting as the primary shading strategy.
- COLOR CLUSTER DISCIPLINE:
  * Warm scenes: red (#68372B), orange (#6F4F25), brown (#433900), yellow (#B8C76F)
  * Cool scenes: cyan (#70A4B2), blue (#352879), light blue (#6C5EB5)
  * Pick one cluster for the scene temperature, then accent with 1-2 colors from the other.
- Sprite color budget is simplified to maximize multiplexer headroom —
  1-2 sprite colors for the player, saving slots for enemies and projectiles.
{color_list}""",
}


# ---------------------------------------------------------------------------
# Commodore 64 color theory rules (MCP)
# ---------------------------------------------------------------------------

_C64_COLOR_THEORY_RULES: dict[str, str] = {
    "early": """\
COLOR THEORY:
- With 1 sprite color, theory reduces to silhouette design.
- Pick a high-contrast foreground color against the expected background.
- The sprite shape alone must communicate the subject — no color variety to help.
- Background tiles: choose foreground colors with maximum luminance distance
  from the global background color for legibility.""",

    "mid": """\
COLOR THEORY:
- Light source is TOP-LEFT (consistent with NES and Game Boy conventions).
- GRAY-HEAVY SHADING (the defining C64 technique):
  * The three grays (#444444, #6C6C6C, #959595) are your primary shading ramp.
  * Use grays for shadow, midtone, and highlight instead of hue-shifting.
  * On colored surfaces, pair one gray with one chromatic color for depth.
- BACKGROUND-FOREGROUND SPLIT:
  * Backgrounds: quieter, lower-saturation colors (grays, browns, dark blue).
  * Sprites: brighter, higher-contrast colors that pop against the background.
  * This separation is critical — the C64 palette is small, so contrast does the work.
- MULTICOLOR CONSTRAINT:
  * 3 global colors must work everywhere on screen. Choose them for maximum versatility.
  * Common global sets: black + dark gray + medium gray, or black + brown + gray.
  * The per-cell accent color provides local variation — use it for the one unique detail.
- ANTI-PATTERNS TO AVOID:
  * FIGHTING THE CHUNKY LOOK: double-wide pixels are the C64 identity. Embrace them.
  * COLOR SOUP: with only 4 colors per cell, every color must have a clear role.""",

    "late": """\
COLOR THEORY:
- Light source is TOP-LEFT. All shading follows this.
- GRAY RAMP AS PRIMARY SHADING TOOL:
  * Dark gray (#444444): shadows, undersides, recesses.
  * Medium gray (#6C6C6C): midtone on neutral surfaces, secondary shadow on colored surfaces.
  * Light gray (#959595): highlights on top-left edges, metal sheen, stone polish.
  * This gray ramp replaces the NES technique of hue-shifting.
    C64 art shades toward neutral gray, not toward blue/purple for shadows.
- COLOR TEMPERATURE CLUSTERING:
  * Warm palette: red (#68372B) + orange (#6F4F25) + brown (#433900) + yellow (#B8C76F).
    Use for: underground caves, desert, fire, wooden structures.
  * Cool palette: cyan (#70A4B2) + blue (#352879) + light blue (#6C5EB5) + green (#588D43).
    Use for: water, sky, forest, ice, night scenes.
  * Set the scene temperature first, then accent with 1-2 colors from the opposite cluster.
- SPRITE ECONOMY:
  * Sprites use fewer colors to save multiplexer budget.
  * A strong silhouette in 1-2 colors reads better than a detailed mess in 3.
  * Character identity comes from shape and animation, not color count.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: shade from one direction only (top-left).
  * NES-STYLE HUE SHIFTING: C64 shading uses grays, not hue shifts. Don't shade
    a red surface toward purple — shade it toward dark gray.
  * OVER-DETAILING: multicolor double-wide pixels cannot hold fine detail.
    Work at 4-pixel minimum feature size.""",
}


# ---------------------------------------------------------------------------
# Commodore 64 tool configs (MCP)
# ---------------------------------------------------------------------------

_C64_TOOL_CONFIGS: dict[str, dict] = {
    "early": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_pixels",
        ],
        "blacklist": _GLOBAL_BLACKLIST + [
            "draw_circle", "draw_with_dither", "apply_shading",
            "apply_outline", "draw_contour",
        ],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (filled=true for body blocks), draw_pixels (detail)
AVOID: draw_circle (poor rasterization at 24x21 hi-res sprite size),
  apply_outline (C64 hi-res sprites are single-color — no separate outline color),
  draw_with_dither (not appropriate for single-color sprites),
  apply_auto_shading, suggest_antialiasing, apply_shading
Build silhouettes with rectangles, refine edges with draw_pixels.
Shape is everything — only 1 color available per sprite.""",
    },
    "mid": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + ["apply_shading"],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (body scaffolding with double-wide pixels),
  draw_circle (rounded forms like the head — will rasterize chunky in multicolor), draw_pixels (main workhorse),
  draw_line (platform edges, or held-item shafts when the subject names them), apply_outline (darkest color, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2 or bayer_4x4, ONLY for terrain tiles, NEVER for sprites
AVOID: apply_auto_shading (produces gradients impossible in 4-color cells),
  suggest_antialiasing (requires color resolution C64 lacks), apply_shading
MULTICOLOR NOTE: All pixel placements should respect double-wide pixel grid (x coordinates in multiples of 2).
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
    "late": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (scaffolding), draw_circle (scaffolding),
  draw_pixels (PRIMARY tool — 80%+ of drawing), draw_line (platform edges, or held-item shafts when the subject names them),
  draw_contour (complex shapes), apply_outline (dark chromatic color, NOT pure black, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2, bayer_4x4, bayer_8x8, floyd_steinberg.
  Good for terrain tiles and large background surfaces.
AVOID: apply_auto_shading (adds gradient colors outside the 16-color palette),
  suggest_antialiasing (C64 lacks the color resolution)
CRITICAL: All shading must be manual via draw_pixels using the gray ramp.
  Do NOT use any auto-shading tool. The C64 palette is fixed — no intermediate colors can be generated.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
}


# ---------------------------------------------------------------------------
# Commodore 64 view rules (MCP)
# ---------------------------------------------------------------------------

_C64_VIEW_RULES: dict[str, str] = {
    "side": """\
VIEW: Side profile (facing right — standard convention).
- Character faces right. Leading arm/leg slightly forward.
- In multicolor mode, all features must be at least 2 double-wide pixels (4 screen pixels) wide.
- Anything held (only when the subject names a held item) goes in the leading (right) hand, visible on the right side.
- Gray shading on the back (left) edges for depth.
- Silhouette must read clearly in monochrome — shape defines character, not color.""",

    "front": """\
VIEW: Front facing.
- Bilateral symmetry: left half mirrors right half.
- In multicolor mode, symmetry operates on the double-wide pixel grid.
- Arms equidistant from center. A held item (when the subject names one) may break symmetry.
- Darker shades (gray ramp) on bottom edges of features.
- Eyes at same height, same size, centered on face.""",

    "top-down": """\
VIEW: Top-down / overhead.
- Head is a circle/oval filling top 60% of canvas.
- In multicolor mode, circles become chunky ovals due to 2:1 pixel aspect.
- Shoulders visible as wider shape below head.
- Items visible from above: hat or headwear dominant; held items extend to the side only when the subject names them.
- Gray shading on bottom edge of head oval.""",

    "3/4": """\
VIEW: 3/4 perspective (facing right and slightly toward viewer).
- Isometric perspective common on C64 (The Last Ninja convention).
- Right side of body 1-2 double-wide pixels wider than left (foreshortening).
- Right arm more visible than left.
- Gray shading on left edges (farther from viewer).
- In multicolor mode, isometric tile edges align to the double-wide pixel grid.""",
}


# ---------------------------------------------------------------------------
# Commodore 64 few-shot examples (MCP)
# ---------------------------------------------------------------------------

_C64_FEW_SHOT_EXAMPLES: dict[str, str] = {
    "early": """\
REFERENCE EXAMPLE — Early C64 24x21 hi-res agent (quality benchmark, do not copy):
Palette: #000000 (black/sprite color), background #352879 (blue)
Key structure: Single-color sprite — ALL opaque pixels are black.
  Head 4x4 oval at rows 1-4, centered. No facial features (1 color only).
  Torso 8x6 rectangle at rows 5-10. Arms 2px wide extending from sides.
  Legs 3x6 at rows 11-16 with 2px gap between. Feet 4px wide at rows 17-18.
  Silhouette must read as "running human" — shape is the entire design.
  Style reference: Impossible Mission agent sprite.
Total: ~90 opaque pixels. Pure silhouette art — no color variation possible.""",

    "mid": """\
REFERENCE EXAMPLE — Mid C64 12x21 multicolor humanoid character (quality benchmark, do not copy):
Palette: #000000 (black/outline), #959595 (light gray/cloth), #68372B (red/accent)
Key structure: Double-wide pixels — 12 logical columns, each 2 screen pixels wide.
  Head 3x3 (double-wide) at rows 1-3. Light gray with black outline (cloth wrap, hat, or hair — depends on the subject).
  Torso 4x5 at rows 4-8. Light gray body with red accent at waist (2 double-wide pixels — sash, belt, or trim).
  Arms 1 double-wide pixel each, extending from torso sides.
  Legs 2x5 at rows 9-13 in light gray, black outline.
  Optional held item (only when the subject names one): 1 double-wide pixel wide extending 4 rows above the right shoulder.
  Gray shading: light gray (#959595) for lit surfaces, implied depth from outline only.
  Style reference: agile-figure C64 sprites such as Impossible Mission's agent or The Last Ninja's protagonist.
Total: ~50-55 opaque double-wide pixels (varies with held item). Chunky, readable, distinctly C64.""",

    "late": """\
REFERENCE EXAMPLE — Late C64 12x21 multicolor humanoid character with hard-surface garment (quality benchmark, do not copy):
Palette: #444444 (dark gray/outline), #6C6C6C (medium gray/garment), #959595 (light gray/highlight)
Key structure: Double-wide pixels. Dark gray outline (NOT pure black — tinted outline).
  Head/headwear 4x3 at rows 0-2: medium gray fill, light gray highlight pixel on top-left.
  Feature slit (eyes, visor, shadow band): 2 double-wide pixels of dark gray at row 1.
  Torso 5x5 at rows 3-7: medium gray with dark gray shadow on right edge,
    light gray highlight on left shoulder (single double-wide pixel).
  Optional held item (only when the subject names one): 1 double-wide pixel wide extending 3 rows right of torso, medium gray with dark gray base detail.
  Legs 2x5 at rows 8-12 in medium gray, dark gray inner edges.
  Footwear: slightly wider at rows 13-14, dark gray.
  Gray ramp creates volume: dark gray shadow (right/bottom) -> medium gray fill -> light gray highlight (left/top).
  Style reference: hard-surface C64 character sprites such as Turrican's protagonist.
Total: ~55-60 opaque double-wide pixels (varies with held item). Gray ramp shading creates convincing hard-surface volume.""",
}


# ---------------------------------------------------------------------------
# Commodore 64 ConsolePromptData
# ---------------------------------------------------------------------------

C64_PROMPT_DATA = ConsolePromptData(
    name="c64",
    display_name="Commodore 64",
    default_era="mid",
    eras={
        "early": _C64_ERA_EARLY,
        "mid": _C64_ERA_MID,
        "late": _C64_ERA_LATE,
    },
    terrain_color_hints=_C64_TERRAIN_COLOR_HINTS,
    palette_rules=_C64_PALETTE_RULES,
    color_theory_rules=_C64_COLOR_THEORY_RULES,
    tool_configs=_C64_TOOL_CONFIGS,
    view_rules=_C64_VIEW_RULES,
    few_shot_examples=_C64_FEW_SHOT_EXAMPLES,
    mood_palettes=None,
    palette_presets=None,
)


# ---------------------------------------------------------------------------
# Game Boy Color era prompt data
# ---------------------------------------------------------------------------

_GBC_ERA_EARLY = EraPromptData(
    label="early Game Boy Color style (1998-1999), DMG-compatible designs with additive color layer",
    year_range="1998-1999",
    reference_games="Dragon Quest Monsters, Pokemon Gold/Silver/Crystal",
    style_ref="Style: Dragon Quest Monsters, Pokemon Gold/Silver/Crystal GBC sprites. Value-first palette design, color as additive layer over DMG-readable structure.",
    tile_ref="Style: Pokemon Gold/Silver town tiles, Dragon Quest Monsters dungeon tilesets.",
    era_hints=(
        "Early Game Boy Color pixel art, 1998-1999 era. "
        "Many titles are GBC-enhanced (DMG-compatible), so art must read in grayscale first. "
        "Color is an additive layer, not a dependency — contrast is built in value, hue adds clarity. "
        "4 colors per tile, 8 BG palettes available but early titles use 4-6 conservatively. "
        "Sprite palettes simple: protagonist owns 1-2 palettes, enemies reuse shared palettes. "
        "Bold outline in darkest palette color, flat color fills with minimal shading. "
        "Per-tile palette assignment allows cleaner color boundaries than NES attribute blocks. "
        "Style: Pokemon Gold/Silver, Dragon Quest Monsters — "
        "the GBC as a 'colorized Game Boy,' not yet exploiting its full palette system."
    ),
    outline_hint="Dark outline using darkest palette color, 1 pixel wide. Consistent weight around entire sprite.",
    pixel_scale=6,
    max_cleanup_colors=4,
)

_GBC_ERA_MID = EraPromptData(
    label="Game Boy Color style (2000-2001), GBC-exclusive designs with sophisticated palette families",
    year_range="2000-2001",
    reference_games="Zelda: Oracle of Ages/Seasons, Wario Land 3, Metal Gear Solid GBC",
    style_ref="Style: Zelda: Oracle of Ages/Seasons, Wario Land 3, Metal Gear Solid GBC sprites. GBC-exclusive palette design, environmental palette families.",
    tile_ref="Style: Oracle of Ages dungeon tiles, Wario Land 3 platform tiles, MGS GBC stealth environments.",
    era_hints=(
        "Mid-era Game Boy Color pixel art, 2000-2001. "
        "GBC-exclusive titles — no DMG fallback required, designed for color from the start. "
        "Full 8-palette system exploited: environmental palette families where related tile groups "
        "share a palette, and different environment types own distinct palettes. "
        "Per-tile palette assignment used for smooth palette transitions at tile boundaries. "
        "Sprites use 2-3 palettes for complex characters: primary colors, secondary accent, shared UI. "
        "Cross-tile gradient shading: adjacent tiles share value gradients for smooth reads. "
        "Level variety through palette swaps on shared tile geometry. "
        "Color-state signaling: palette changes communicate character states (damage, charge, power-up). "
        "Style: Oracle of Ages/Seasons, Wario Land 3, Metal Gear Solid GBC — "
        "the GBC's palette system used as a deliberate art direction tool."
    ),
    outline_hint="Dark chromatic outline using palette-appropriate dark color. May thin on light-source side for volume.",
    pixel_scale=None,
    max_cleanup_colors=6,
)

_GBC_ERA_LATE = EraPromptData(
    label="peak Game Boy Color style (2001-2003), fluid animation and strict palette ownership",
    year_range="2001-2003",
    reference_games="Shantae",
    style_ref="Style: Shantae GBC sprites. Peak GBC art — fluid animation, strict per-category palette ownership, maximum polish within 4-color-per-tile constraint.",
    tile_ref="Style: Shantae town architecture tiles, environmental category palettes.",
    era_hints=(
        "Late-era Game Boy Color pixel art, 2001-2003 — the technical peak of GBC. "
        "Shantae is the definitive reference: fluid character animation, strict palette discipline. "
        "Every palette earns its place — per-category ownership where characters, buildings, foliage, "
        "and terrain each own dedicated palettes that never cross-contaminate. "
        "Character sprites use consistent palette assignments across animation frames "
        "so the eye tracks motion through color continuity even when shape changes significantly. "
        "Enemy variety through palette reuse: same tile shapes with different palette assignments "
        "multiply creature variety without consuming additional tile storage. "
        "Cross-tile shading at its most refined — value gradients across tile boundaries "
        "create depth and volume beyond what any single 4-color tile can express. "
        "The 160x144 resolution makes every pixel critical — 'colorful but chunky' aesthetic "
        "with richer hue than NES but lower detail density. "
        "Style: Shantae — the ceiling of GBC pixel art achievement."
    ),
    outline_hint=(
        "Dark chromatic outline hue-shifted toward the sprite's dominant color. "
        "Outline weight varies: thinner on light-source side (top-left), heavier on shadow side. "
        "Internal feature lines use a mid-dark palette color, not the outline color."
    ),
    pixel_scale=None,
    max_cleanup_colors=8,
)


# ---------------------------------------------------------------------------
# GBC terrain color hints (FLUX)
# ---------------------------------------------------------------------------

_GBC_TERRAIN_COLOR_HINTS: list[tuple[list[str], str]] = [
    (["grass", "field", "meadow", "lawn", "turf"],
     "IMPORTANT: Rich greens with clear value steps. Use 2-3 green hues per palette "
     "with visible light-to-dark gradient. Like Pokemon Gold overworld grass tiles."),
    (["water", "ocean", "sea", "lake", "river", "pond"],
     "IMPORTANT: Blue palette family with highlight for wave crests. "
     "GBC water uses 2-3 blues plus a light sparkle color. Like Oracle of Ages water tiles."),
    (["sand", "desert", "beach", "dune"],
     "IMPORTANT: Warm yellow-tan palette with light highlight and dark shadow. "
     "More hue variety than NES sand — GBC can separate warm and cool tones within one palette."),
    (["stone", "rock", "cave", "dungeon", "castle", "fortress"],
     "IMPORTANT: Cool gray palette family. GBC dungeon stone uses blue-shifted grays "
     "for atmosphere. Like Oracle of Ages dungeon walls."),
    (["brick", "wall", "masonry"],
     "IMPORTANT: Warm brown-red palette with dark mortar lines. "
     "Per-tile palette assignment allows cleaner brick-to-mortar color transitions."),
    (["wood", "plank", "floor", "deck", "log", "timber"],
     "IMPORTANT: Brown palette family with warm and cool brown tones. "
     "Wood grain uses value stepping across adjacent tiles."),
    (["snow", "ice", "frost", "winter", "tundra"],
     "IMPORTANT: Cool white-blue palette. GBC can separate snow white from ice blue "
     "within the same palette family. Like Oracle of Seasons winter palette."),
    (["lava", "magma", "fire", "volcano"],
     "IMPORTANT: Hot red-orange-yellow palette. GBC fire effects use "
     "the full warm spectrum within a single 4-color palette."),
    (["dirt", "mud", "earth", "soil", "ground"],
     "IMPORTANT: Dark brown palette with warm mid-tones. "
     "Distinct from stone palette — earth uses warmer hue shifts."),
]


# ---------------------------------------------------------------------------
# GBC palette rules (MCP)
# ---------------------------------------------------------------------------

_GBC_PALETTE_RULES: dict[str, str] = {
    "early": """\
PALETTE RULES:
- GBC: 15-bit RGB (32768 colors), but each 8x8 tile uses exactly 4 colors from one palette.
- Per-tile palette assignment (not per-block like NES) — each tile independently selects its palette.
- You have {n} colors plus transparency (color 0 for sprites).
- {c0} ({r0}): darkest value — outline and deep features. Must read as outline in grayscale.
- {c1} ({r1}): main body fill, 50-60% of opaque pixels.
{extra_color}\
- VALUE-FIRST design: choose colors that maintain strong value contrast.
  If you removed all hue and viewed in grayscale, the sprite must still read clearly.
  Color is additive — it improves clarity, but the sprite cannot depend on it.
- DMG-compatible: art should be readable as 4 shades of gray.
- All color regions are solid blocks. Minimal shading — flat fills predominate.""",

    "mid": """\
PALETTE RULES:
- GBC: 15-bit RGB (32768 colors), 4 colors per tile, per-tile palette assignment.
- 8 BG palettes x 4 colors = 32 simultaneous BG colors.
- 8 sprite palettes x 3 visible colors = 24 simultaneous sprite colors (color 0 = transparent).
- You have {n} colors plus transparency.
- {c0} ({r0}): dark chromatic outline — NOT pure black. Hue-shifted toward sprite's dominant color.
- {c1} ({r1}): main body midtone, largest fill area (40-50% of opaque pixels).
- {c2} ({r2}): secondary region or accent — skin, cape, boots (25-35%).
{extra_color}\
- GBC-EXCLUSIVE design: no DMG fallback required. Design for color from the start.
- Environmental palette families: group related tiles under shared palettes.
  Grass tiles share a green palette. Water tiles share a blue palette.
  Transition tiles assigned to the palette that best matches their dominant color.
- Palette swaps for variety: same tile shapes recolored with different palette
  assignments create distinct environments without new tile art.
- Per-tile granularity means palette boundaries can occur at any tile edge,
  not just 16px block boundaries like NES.""",

    "late": """\
PALETTE RULES:
- GBC: 15-bit RGB (32768 colors), 4 colors per tile, per-tile palette assignment.
- You have {n} colors plus transparency. Colors organized into functional roles.
- PALETTE OWNERSHIP: each sprite category owns a dedicated palette. Characters, enemies,
  environmental objects — palettes never cross-contaminate between categories.
- {c0} ({r0}): dark chromatic outline, hue-shifted toward dominant sprite color.
  NOT pure black. Used for external edges AND internal feature separation.
- {c1} ({r1}): body midtone, the workhorse. 40-50% of opaque pixels.
- {c2} ({r2}): shadow or secondary region. 20-30% of opaque pixels.
- {c3} ({r3}): highlight or accent. Smallest usage (10-15%). Top-left edges only.
{extra_color}\
- CONSISTENCY ACROSS FRAMES: character palettes stay fixed across all animation frames.
  The eye tracks motion through color continuity — same hues in same regions, always.
- Enemy variety: reuse tile shapes with different palette assignments. A red enemy
  and a blue enemy sharing geometry but differing in palette reads as two distinct creatures.
- Cross-tile shading: adjacent tiles from the same palette family share value gradients
  that read as smooth surfaces across tile boundaries.
{color_list}""",
}


# ---------------------------------------------------------------------------
# GBC color theory rules (MCP)
# ---------------------------------------------------------------------------

_GBC_COLOR_THEORY_RULES: dict[str, str] = {
    "early": """\
COLOR THEORY:
- VALUE FIRST, HUE SECOND. The GBC early era treats color as an additive layer over DMG-readable art.
- Choose palette colors with strong value contrast independent of hue.
  If the sprite doesn't read in grayscale, the color choices are wrong.
- Hue serves identification: a blue character is blue because the player needs to tell it apart
  from a red one, not because blue adds visual depth. The depth comes from value contrast.
- Keep hue count low per sprite: 1-2 hue families plus a neutral (dark outline).
  Too many hues in a 4-color palette produces visual noise at 160x144 resolution.
- The "colorful but chunky" GBC aesthetic means richer hue than NES,
  but lower resolution makes color clarity more important than color variety.""",

    "mid": """\
COLOR THEORY:
- Light source is TOP-LEFT (consistent with NES/DMG convention).
- PALETTE FAMILIES: groups of 3-4 related hues that work together.
  A forest palette family: dark green (shadow), mid green (fill), yellow-green (highlight), brown (trunk).
  A dungeon palette family: dark blue-gray (shadow), mid gray (stone), warm gray (mortar), dim gold (torch light).
- CROSS-TILE SHADING: when a surface spans multiple tiles, adjacent tiles use
  coordinated value placement. Left tiles place lighter values on their left edges;
  right tiles place darker values on their left edges. The result reads as a
  gradient across the tile boundary even though each tile uses only its own 4 colors.
- ATMOSPHERIC PALETTE SEPARATION: background tiles use cooler, more desaturated palettes.
  Foreground tiles use warmer, more saturated ones. Reserve 1-2 of 8 BG palettes
  for background color temperature.
- COLOR-STATE SIGNALING: palette swaps on character sprites communicate game state.
  Damage flash, power-up glow, status effects — all achieved by swapping palette index,
  not by changing tile data. Design base palettes that support meaningful swap variants.
- ANTI-PATTERNS TO AVOID:
  * PALETTE BLEEDING: mixing unrelated color families in one palette. Each palette should
    serve one visual concept (one character, one terrain type, one UI element).
  * VALUE COLLISION: two colors in one palette with similar value but different hue.
    At GBC resolution, they blend into mush. Every color in a palette needs a distinct value step.""",

    "late": """\
COLOR THEORY:
- Light source is TOP-LEFT. All shading decisions follow this.
- THE "COLORFUL BUT CHUNKY" AESTHETIC: GBC has more color than NES but lower resolution (160x144 vs 256x240).
  Colors must read clearly at small pixel counts. Bold hue choices, clean color boundaries,
  no subtle value shifts that disappear at native resolution.
- PALETTE FAMILY DESIGN (critical for late-era quality):
  * Each environment category owns a palette: forest-green, dungeon-gray, town-warm, water-blue.
  * Within a palette, colors form a value ramp: dark (outline/shadow), mid (fill), light (highlight), accent.
  * Hue shifts within the ramp add richness: shadow hue shifts cool (toward blue/purple),
    highlight hue shifts warm (toward yellow). Same principle as NES late-era hue shifting.
- CROSS-TILE GRADIENT SHADING (refined technique):
  * Large surfaces (building walls, cave floors) use coordinated value placement across tile boundaries.
  * Each tile individually obeys the 4-color constraint; the aggregate reads as smooth shading.
  * Dithering at tile edges can bridge value gaps between adjacent palettes.
- ANIMATION COLOR CONTINUITY:
  * Character palettes are fixed across all animation frames. Color placement tracks body parts:
    skin color stays on skin, garment color stays on the same garment region, even as limb positions change.
  * The viewer's eye follows color, not shape, at GBC resolution — color consistency
    is what makes animation readable.
- ANTI-PATTERNS TO AVOID:
  * PALETTE BLEEDING: unrelated hues sharing a palette. One palette = one visual concept.
  * PILLOW SHADING: highlight ringing all edges. Light source is top-left only.
  * OVER-SATURATION: GBC's LCD response compresses saturated colors. Leave headroom —
    use 70-80% saturation for midtones, 90%+ only for accent highlights.
  * BANDING: parallel color bands where values meet. Stagger with 1px offsets.""",
}


# ---------------------------------------------------------------------------
# GBC tool configs (MCP)
# ---------------------------------------------------------------------------

_GBC_TOOL_CONFIGS: dict[str, dict] = {
    "early": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_pixels",
            "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + [
            "draw_circle", "draw_with_dither", "apply_shading",
            "draw_contour",
        ],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (filled=true for body blocks),
  draw_pixels (detail placement), apply_outline (darkest palette color, thickness=1)
AVOID: draw_circle (rasterizes poorly at small GBC sprite sizes), draw_with_dither (noise),
  apply_auto_shading, suggest_antialiasing, apply_shading
GBC early era: flat color fills, bold outlines, minimal internal detail.
Build with rectangles, refine with draw_pixels. Outline applied LAST.""",
    },
    "mid": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + ["apply_shading"],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (body scaffolding), draw_circle (rounded forms like the head),
  draw_pixels (main workhorse for detail and cross-tile shading), draw_line (long thin elements such as belt lines, or held-item shafts when the subject names them),
  apply_outline (dark chromatic color, NOT pure black, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2 or bayer_4x4, ONLY for terrain tiles, NEVER for character sprites
AVOID: apply_auto_shading (produces smooth gradients impossible on GBC), suggest_antialiasing,
  apply_shading (un-GBC smooth gradients)
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
    "late": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (scaffolding), draw_circle (scaffolding),
  draw_pixels (PRIMARY tool — 80%+ of drawing, essential for cross-tile shading),
  draw_line (feature lines), draw_contour (complex shapes),
  apply_outline (dark chromatic color hue-shifted to sprite's dominant hue, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2, bayer_4x4, bayer_8x8, floyd_steinberg. For terrain only.
AVOID: apply_auto_shading (adds intermediate colors beyond 4-per-tile limit), suggest_antialiasing
CRITICAL: All shading must be manual via draw_pixels. Only 4 colors per tile — no auto-shading tools.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
}


# ---------------------------------------------------------------------------
# GBC view rules (MCP)
# ---------------------------------------------------------------------------

_GBC_VIEW_RULES: dict[str, str] = {
    "side": """\
VIEW: Side profile (facing right — standard convention).
- Character faces right. Leading arm/leg slightly forward.
- Anything held (only when the subject names a held item) goes in the leading (right) hand, visible on the right side.
- Shadow colors on the back (left) edges of the body.
- GBC resolution (160x144) means exaggerate the subject's distinctive features for readability.
- Color palette tracks body parts consistently: skin, clothing, and any named accessory stay in their assigned colors.""",

    "front": """\
VIEW: Front facing.
- Bilateral symmetry: left half mirrors right half.
- Arms equidistant from center. A held item (when the subject names one) may break symmetry.
- Shadow colors on bottom edges of features.
- Eyes at same height, same size, centered on face.
- GBC sprites are small — use bold color contrast between face and body for readability.""",

    "top-down": """\
VIEW: Top-down / overhead.
- Head is a circle/oval filling top 60% of canvas.
- Shoulders visible as wider shape below head.
- No legs visible. Items visible from above: hat or headwear dominant; held items extend to the side only when the subject names them.
- Shadow on bottom edge of head oval.
- GBC RPG overworld view: character is small, silhouette and color must identify instantly.""",

    "3/4": """\
VIEW: 3/4 perspective (facing right and slightly toward viewer).
- Right side of body 1-2px wider than left (foreshortening).
- Right arm more visible than left.
- Shadow colors on left edges (farther from viewer).
- Face shows both eyes but right eye 1px larger.
- GBC Zelda-style perspective: Link's Oracle games use this view extensively.""",
}


# ---------------------------------------------------------------------------
# GBC few-shot examples (MCP)
# ---------------------------------------------------------------------------

_GBC_FEW_SHOT_EXAMPLES: dict[str, str] = {
    "early": """\
REFERENCE EXAMPLE — Early GBC 16x16 creature (quality benchmark, do not copy):
Palette: #081808 (dark green-black/outline), #306850 (forest green/body), #58A840 (bright green/accent), #E0D898 (pale yellow/highlight)
Key structure: 1px dark green-black outline around entire sprite.
  Body 6x6 forest green fill at rows 4-9, centered. Roundish silhouette.
  Eyes: 2px dark outline on pale yellow face area at (6,4)-(7,5).
  Limbs: 1-2px wide forest green extending from body. Simple geometry.
  Accent: bright green spots on back, 3-4 pixels total.
  Value-first: reads clearly as "small creature" even with hue removed.
Total: ~55 opaque pixels. DMG-compatible color design — contrast carries form.""",

    "mid": """\
REFERENCE EXAMPLE — Mid GBC 16x16 adventurer (quality benchmark, do not copy):
Palette: #182848 (dark navy/outline), #3870B8 (blue/tunic), #D09858 (warm tan/skin), #80D048 (green/cap+belt)
Key structure: Dark navy chromatic outline (NOT pure black).
  Head 4x4 at rows 1-4: tan skin fill, navy eyes at (6,2)-(7,2).
  Green cap: 3x2 at rows 0-1 above head, with 1px navy brim line.
  Blue tunic: 6x5 at rows 5-9, largest color area. Navy detail lines for collar and hem.
  Arms: 2px wide tan extending from tunic sides.
  Green belt: 1px horizontal line across tunic at row 7.
  Legs: 2x3 navy-dark boots at rows 10-12.
  Light source top-left: tunic slightly lighter on left pixels (same color, just more fill vs outline).
Total: ~70 opaque pixels. GBC-exclusive design — colors chosen for the palette, not DMG fallback.""",

    "late": """\
REFERENCE EXAMPLE — Late GBC 16x16 dancer (quality benchmark, do not copy):
Palette: #281848 (deep purple/outline), #7838A0 (purple/clothing shadow), #D07888 (warm pink/skin+clothing), #F8D868 (golden/hair+highlights)
Key structure: Deep purple outline hue-shifted to match clothing palette.
  Hair: 3x3 golden at rows 0-2, flowing right with 2px strand at (12,1).
  Face: 2x3 warm pink at rows 2-4, purple eyes at (6,3)-(7,3), golden earring at (9,3).
  Body: 5x4 warm pink torso at rows 5-8, purple shadow on right edge (1px wide).
  Clothing: purple shadow on bottom-right of torso, warm pink on top-left (light source).
  Arms: warm pink extending from torso, 2px detail for pose.
  Legs: 2x3 warm pink at rows 9-11, purple shadow on right side of each leg.
  Golden highlights: single pixels on hair top, left shoulder, belt center.
  Animation-ready: palette stays consistent across frames — eye tracks golden hair and pink body.
Total: ~75 opaque pixels. Peak GBC craft — every color earns its place.""",
}


# ---------------------------------------------------------------------------
# GBC ConsolePromptData
# ---------------------------------------------------------------------------

GBC_PROMPT_DATA = ConsolePromptData(
    name="gbc",
    display_name="Game Boy Color",
    default_era="mid",
    eras={
        "early": _GBC_ERA_EARLY,
        "mid": _GBC_ERA_MID,
        "late": _GBC_ERA_LATE,
    },
    terrain_color_hints=_GBC_TERRAIN_COLOR_HINTS,
    palette_rules=_GBC_PALETTE_RULES,
    color_theory_rules=_GBC_COLOR_THEORY_RULES,
    tool_configs=_GBC_TOOL_CONFIGS,
    view_rules=_GBC_VIEW_RULES,
    few_shot_examples=_GBC_FEW_SHOT_EXAMPLES,
    mood_palettes=None,
    palette_presets=None,
)


# ---------------------------------------------------------------------------
# SNES era prompt data
# ---------------------------------------------------------------------------

_SNES_ERA_EARLY = EraPromptData(
    label="early SNES 16-bit style (1990-1992), establishing the 16-bit visual language",
    year_range="1990-1992",
    reference_games="Super Mario World, A Link to the Past, F-Zero, Contra III, ActRaiser",
    style_ref=(
        "Style: Super Mario World, The Legend of Zelda: A Link to the Past, "
        "F-Zero, Contra III, ActRaiser SNES sprites. Clean 16-bit art with "
        "readable silhouettes and distinct palette zones."
    ),
    tile_ref=(
        "Style: A Link to the Past overworld tiles, Super Mario World "
        "ground/castle tiles, Castlevania IV gothic stone and wood."
    ),
    era_hints=(
        "Early SNES pixel art, 1990-1992 — the first generation of 16-bit art. "
        "Artists are transitioning from NES habits: sprites are cleaner and more "
        "colorful than NES but still establishing conventions. "
        "8-12 colors per sprite from a 16-color palette, with clear separation "
        "between body, clothing, skin, and accent regions. "
        "Outlines are still prominent — typically 1px dark or black border. "
        "Shading uses 2-3 value steps per material but not yet the smooth "
        "multi-step gradients of later SNES art. "
        "Backgrounds are bright and readable with strong color contrast. "
        "Style: Super Mario World, A Link to the Past, F-Zero, ActRaiser, "
        "Castlevania IV — the foundation of SNES visual language."
    ),
    outline_hint=(
        "1px dark outline, usually black or near-black. "
        "Consistent thickness around entire sprite. "
        "Internal lines separate major body regions (head from torso, limbs from body)."
    ),
    pixel_scale=None,
    max_cleanup_colors=10,
)

_SNES_ERA_MID = EraPromptData(
    label="SNES 16-bit style (1993-1994), peak hand-drawn pixel art and atmospheric mastery",
    year_range="1993-1994",
    reference_games="Super Metroid, Final Fantasy VI, Mega Man X, Secret of Mana",
    style_ref=(
        "Style: Super Metroid, Final Fantasy VI, Mega Man X, Secret of Mana "
        "SNES sprites. Atmospheric palettes, hue-shifted shading, material "
        "differentiation through color temperature."
    ),
    tile_ref=(
        "Style: Super Metroid's Crateria/Norfair tilesets, Final Fantasy VI "
        "dungeon and town tiles, Secret of Mana's watercolor-warm environments."
    ),
    era_hints=(
        "Mid-era SNES pixel art, 1993-1994 — the peak of hand-drawn 16-bit art. "
        "Full mastery of the 15-bit color space: palettes built around hue families "
        "with controlled saturation and value steps. "
        "Smooth skin tone gradients with 4-5 shades along a warm-to-cool hue path. "
        "Material differentiation is sophisticated — metal reads as metal through "
        "high-contrast specular highlights; fabric reads as fabric through soft "
        "shadow transitions; skin uses warm midtones with cool shadow shifts. "
        "Atmospheric palette design: same tilesets convey different moods through "
        "palette alone (Super Metroid's Crateria vs Norfair, FFVI's Vector vs Narshe). "
        "Outlines shift from pure black to dark chromatic colors that match the "
        "sprite's dominant hue. "
        "Style: Super Metroid, Final Fantasy VI, Mega Man X, Secret of Mana — "
        "the definitive SNES look."
    ),
    outline_hint=(
        "Dark chromatic outline — dark blue, dark purple, or dark brown matched "
        "to the sprite's dominant hue family. Not pure black unless the design "
        "demands high contrast (Mega Man X armor)."
    ),
    pixel_scale=None,
    max_cleanup_colors=12,
)

_SNES_ERA_LATE = EraPromptData(
    label="late SNES 16-bit style (1995-1997), technical peak with pre-rendered sprites and enhancement chips",
    year_range="1995-1997",
    reference_games="Chrono Trigger, DKC2, Yoshi's Island, Star Ocean, Tales of Phantasia",
    style_ref=(
        "Style: Chrono Trigger, Donkey Kong Country 2, Yoshi's Island, "
        "Star Ocean, Tales of Phantasia SNES sprites. Peak palette engineering, "
        "expressive character design, and cinematic visual storytelling."
    ),
    object_ref=(
        "Style: Chrono Trigger, Donkey Kong Country 2, Yoshi's Island, "
        "Star Ocean, Tales of Phantasia SNES sprites. Peak palette engineering "
        "and cinematic visual storytelling."
    ),
    tile_ref=(
        "Style: Chrono Trigger time-period tilesets, DKC2 pirate ship and "
        "mine environments, Tales of Phantasia detailed town tiles."
    ),
    era_hints=(
        "Late SNES pixel art, 1995-1997 — the absolute technical peak of the console. "
        "Palette engineering reaches its zenith: Chrono Trigger's time-period palette "
        "substitution, where the same tile geometry communicates prehistoric warmth, "
        "medieval stone, or futuristic cold through palette alone. "
        "Full 15-color sprite palettes used with intent — every slot serves a purpose: "
        "3-4 skin shades with warm-to-cool hue path, 3-4 clothing shades with "
        "hue-shifted shadows, 2-3 accent colors, 1-2 outline/detail tones. "
        "Pre-rendered 3D sprites (DKC2) coexist with peak hand-drawn art (Chrono Trigger). "
        "Enhancement chip effects (Yoshi's Island's Super FX 2 rotation) push visual "
        "boundaries beyond base SNES hardware. "
        "Characters have expressive faces, detailed costume silhouettes, and "
        "emotion-carrying poses at 16x24 to 32x32 pixel sizes. "
        "Style: Chrono Trigger, DKC2, Yoshi's Island, Star Ocean, Tales of Phantasia — "
        "the most polished pixel art ever produced."
    ),
    outline_hint=(
        "Dark chromatic outline using the darkest palette color — matched to the "
        "sprite's dominant hue family. Outlines may thin on the light side (top-left) "
        "and thicken on the shadow side. Some artists use selective outline removal "
        "on highlight edges for a softer, more painterly feel."
    ),
    pixel_scale=None,
    max_cleanup_colors=15,
)


# ---------------------------------------------------------------------------
# SNES terrain color hints (FLUX)
# ---------------------------------------------------------------------------

_SNES_TERRAIN_COLOR_HINTS: list[tuple[list[str], str]] = [
    (["grass", "field", "meadow", "lawn", "turf"],
     "IMPORTANT: Rich green with 3-4 value steps. Warm yellow-green highlights, "
     "cool blue-green shadows. Like A Link to the Past's Hyrule overworld grass."),
    (["water", "ocean", "sea", "lake", "river", "pond"],
     "IMPORTANT: Multiple blue shades with animated highlight ripples. "
     "Deeper areas use dark navy-blue, shallow areas use cyan-tinted midtones. "
     "Like Secret of Mana's rivers and A Link to the Past's water tiles."),
    (["sand", "desert", "beach", "dune"],
     "IMPORTANT: Warm tan and gold tones with orange-shifted shadows. "
     "Light cream highlights. Like Chrono Trigger's prehistoric desert."),
    (["stone", "rock", "cave", "dungeon", "castle", "fortress"],
     "IMPORTANT: Cool gray with blue-shifted shadows and warm-gray highlights. "
     "3-4 value steps for depth. Like Super Metroid's Crateria rock walls "
     "and A Link to the Past's dungeon stonework."),
    (["brick", "wall", "masonry"],
     "IMPORTANT: Warm brown-red with dark mortar lines. Highlight on upper-left "
     "face of each brick. Like Castlevania IV's castle interior walls."),
    (["wood", "plank", "floor", "deck", "log", "timber"],
     "IMPORTANT: Warm brown with visible grain pattern using 3 value steps. "
     "Highlights along top edge of planks. Like Chrono Trigger's medieval era buildings."),
    (["snow", "ice", "frost", "winter", "tundra"],
     "IMPORTANT: White and pale blue with subtle lavender shadow tones. "
     "Sparkle highlights using near-white pixels. Like Chrono Trigger's 12000 BC era."),
    (["lava", "magma", "fire", "volcano"],
     "IMPORTANT: Deep red base with orange midtones and bright yellow-white "
     "highlights for molten glow. Like Super Metroid's Norfair magma pools."),
    (["dirt", "mud", "earth", "soil", "ground"],
     "IMPORTANT: Warm earthy browns with orange undertones. 3 value steps — "
     "dark brown shadows, medium brown body, tan highlights."),
    (["metal", "iron", "steel", "armor"],
     "IMPORTANT: Cool blue-gray with high-contrast specular highlights. "
     "Sharp value transitions between shadow and highlight to convey reflectivity. "
     "Like Mega Man X's armor plating."),
]


# ---------------------------------------------------------------------------
# SNES palette rules (MCP) — template strings with {n}, {c0}, {r0}, etc.
# ---------------------------------------------------------------------------

_SNES_PALETTE_RULES: dict[str, str] = {
    "early": """\
PALETTE RULES (SNES — 15-bit RGB, 16 colors per palette):
- You have {n} colors plus transparency (color 0).
- The SNES uses SEPARATE palette pools: 8 palettes for backgrounds, 8 for sprites.
  Your sprite palette is independent from the background — no sharing.
- {c0} ({r0}): dark outline on all external edges. Also eyes, mouth, feature lines.
- {c1} ({r1}): main body/clothing fill — largest area, 35-45% of opaque pixels.
- {c2} ({r2}): secondary region — skin, cape, boots, or contrasting element, 20-30%.
{extra_color}\
- Highlight color: use a lighter version of the main body color. Place on top-left edges
  of convex surfaces (e.g. head/helmet top, shoulder, the upper edge of any curved object). 5-12% of pixels.
- Build each color region as a SOLID ZONE — then add shadow on bottom-right edges
  and highlight on top-left edges within that zone.
- Light source is top-left. All shading follows this direction consistently.
{color_list}""",

    "mid": """\
PALETTE RULES (SNES — 15-bit RGB, 16 colors per palette):
- You have {n} colors plus transparency (color 0).
- SNES palette architecture: 8 BG palettes + 8 sprite palettes, SEPARATE pools.
  Characters must read against backgrounds WITHOUT sharing palette entries.
  Ensure value contrast between character and expected background brightness.
- HUE FAMILY DISCIPLINE: Build the palette around a dominant hue with controlled
  saturation and value steps. A knight's palette centers on steel-blue; skin tones
  occupy a separate warm hue lane; the accent color provides complementary contrast.
- {c0} ({r0}): dark chromatic outline — NOT pure black. Matched to dominant hue family.
- {c1} ({r1}): body shadow — bottom-right edges, undersides, folds. Dark saturated hue.
- {c2} ({r2}): body midtone — largest fill area, 40-50% of body region. Base color.
- {c3} ({r3}): body highlight — top-left convex edges only. Lighter, slightly desaturated.
{extra_color}\
- SKIN TONES: allocate 3-4 slots for smooth skin gradients along a warm hue path.
  Shadow skin shifts toward red-brown; highlight skin shifts toward peach-yellow.
- ACCENT REGION: secondary element (e.g. cape, gem, embroidery, contrasting trim) in a contrasting hue
  to create visual interest. At least 2 value steps (midtone + highlight).
- Palette harmony: even colors in different hue families should share a consistent
  saturation range so they feel like they belong together.
{color_list}""",

    "late": """\
PALETTE RULES (SNES — 15-bit RGB, 16 colors per palette):
- You have {n} colors plus transparency (color 0). Every slot matters — no wasted entries.
- SNES palette architecture: 8 BG palettes + 8 sprite palettes, fully independent.
  Palette harmony ACROSS pools is critical — characters must contrast against backgrounds
  through value separation even without shared colors.
- FULL HUE FAMILY ENGINEERING (Chrono Trigger / FFVI standard):
  * Each material on the sprite gets its own hue lane with 3-4 value steps.
  * Clothing: shadow → midtone → highlight, hue-shifted across steps.
  * Skin: 3-4 shades from warm shadow (red-brown) through base (peach) to cool highlight.
  * Hard surfaces (metal, polished stone, glass): high-contrast 2-3 step gradient with sharp specular highlight.
- {c0} ({r0}): dark chromatic outline — matched to the sprite's dominant hue.
  NOT pure black. Dark navy for blue-armored characters, dark brown for earth-toned ones.
- {c1} ({r1}): body shadow — shift hue TOWARD COOL (blue/purple), lower value.
- {c2} ({r2}): body midtone — the base color, largest fill area.
- {c3} ({r3}): body highlight — shift hue TOWARD WARM (yellow/white), raise value.
{extra_color}\
- SKIN GRADIENT: warm hue path — deep shadow in red-brown, midtone in natural flesh,
  highlight in peach-yellow or cream. Shibuya-standard: 4 shades minimum for faces.
- ACCENT SYSTEM: at least one hue-contrasting element (e.g. gem, cape trim, eye color)
  to create focal point. Place accent on a small distinctive feature or face detail.
- ATMOSPHERIC READINESS: palette should be designed so that palette-swap into
  different environments remains coherent (warm version, cool version, dark version).
{color_list}""",
}


# ---------------------------------------------------------------------------
# SNES color theory rules (MCP)
# ---------------------------------------------------------------------------

_SNES_COLOR_THEORY_RULES: dict[str, str] = {
    "early": """\
COLOR THEORY (SNES):
- Light source is TOP-LEFT for all sprites. This is universal SNES convention.
- The SNES gives you 32,768 possible colors (15-bit RGB) — choose precisely.
  Do not scatter colors randomly from the space. Select along controlled hue ramps.
- SHADING BASICS: 2-3 value steps per material region.
  * Shadow on bottom-right edges and undersides.
  * Highlight on top-left edges of convex surfaces.
  * Midtone fills the majority of each region.
- OUTLINE as darkest color — defines silhouette and internal feature boundaries.
- Value contrast is more important than hue variety. A sprite with 4 well-placed
  values in one hue reads better than 8 randomly chosen colors.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: lighting from all sides. Always shade from top-left only.
  * BANDING: parallel color bands at transitions. Stagger with 1px offsets.
  * NES HABITS: flat color blocks without shading. SNES art uses gradation.""",

    "mid": """\
COLOR THEORY (SNES):
- Light source is TOP-LEFT. All shading decisions follow this — no exceptions.
- HUE SHIFTING (critical for mid-era SNES quality):
  * Shadows: shift hue TOWARD BLUE/PURPLE, lower saturation slightly, drop value.
    A red cape's shadow is dark purple-red, not just darker red.
  * Highlights: shift hue TOWARD YELLOW/WHITE, raise value.
    Blue armor's highlight is cyan-white, not pale blue.
  * This creates vibrant, living color rather than flat computer-generated ramps.
- MATERIAL DIFFERENTIATION through color behavior:
  * METAL: high contrast between shadow and highlight, sharp value transitions,
    1px specular highlight at brightest point. Blue-shifted shadows.
  * FABRIC: soft value transitions, shadow color visible in folds and creases,
    moderate saturation throughout the gradient.
  * SKIN: warm midtone dominant, shadow shifts toward red-brown (under chin, arms),
    highlight shifts toward peach-yellow (forehead, cheekbone, nose bridge).
  * HAIR: follows its base hue with 3 value steps. Dark hair gets blue-shifted shadows;
    light hair gets warm golden highlights.
- ATMOSPHERIC PALETTE DESIGN (Super Metroid technique):
  * Cool environments: shift ALL palette midtones toward blue. Reduce saturation.
    Crateria's muted gray-greens with low chroma.
  * Warm environments: shift midtones toward orange-red. Increase saturation.
    Norfair's deep reds with vivid accent.
  * The same character sprite should read correctly against BOTH atmospheres
    because character palettes maintain higher saturation than backgrounds.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: shading from all sides equally.
  * BANDING: visible parallel color bands. Break with staggered transitions.
  * PURE BLACK (#000000) outlines: use dark chromatic outlines instead.
  * PURE WHITE (#FFFFFF) highlights: use tinted near-whites.
  * FLAT RAMPS: shadow/midtone/highlight in the same hue = dead, computer-looking color.""",

    "late": """\
COLOR THEORY (SNES):
- Light source is TOP-LEFT. All shading decisions follow this.
- ADVANCED HUE SHIFTING (Chrono Trigger / FFVI standard — the gold standard):
  * Shadows: shift hue TOWARD COOL (blue/purple), drop value, maintain or slightly
    reduce saturation. A green tunic's shadow is dark teal-green, not dark green.
  * Highlights: shift hue TOWARD WARM (yellow), raise value, slightly desaturate.
    A blue robe's highlight is cyan-white with a warm edge.
  * NEVER use the same hue at different values — always shift. Same-hue ramps
    look flat and computer-generated. Hue-shifted ramps look hand-painted.
- SKIN TONE MASTERY (Shibuya Kazuko technique):
  * Build a 4-6 shade gradient along a precise warm hue path:
    Deep shadow (dark red-brown) → shadow (warm brown) → midtone (natural flesh) →
    light (peach) → highlight (cream-yellow) → specular (near-white warm).
  * The hue shifts subtly warmer through each step. This is what makes SNES
    character faces look alive vs. the NES's flat skin blocks.
- ATMOSPHERIC PALETTE VARIATION (environmental storytelling):
  * Same tileset, different mood: palette alone conveys time of day, weather, danger level.
  * Chrono Trigger technique: prehistoric = warm earth, saturated; medieval = cool stone,
    moderate saturation; future = high-contrast dark + neon accent, desaturated base.
  * Super Metroid technique: each area has a dominant color temperature. Crateria = cool
    gray-green; Norfair = hot red-orange; Maridia = deep blue-purple; Brinstar = organic green.
- MATERIAL DIFFERENTIATION at peak quality:
  * POLISHED METAL: 4-step gradient with extreme value jump at specular point.
    Shadow is dark blue-purple, midtone is steel gray, highlight is white-blue,
    specular is near-white with 1px placement.
  * MATTE FABRIC: 3-step gradient with gentle value transitions.
    Shadow and highlight stay within a narrow value band. Color temperature shifts do the work.
  * TRANSLUCENT MATERIALS: use SNES color math conceptually — lighter values suggest
    transparency. Magic effects use additive-blend logic (bright + saturated).
  * ORGANIC (skin, wood, earth): warm color temperatures throughout. Shadows shift
    toward red, not blue. Highlights shift toward yellow, not white.
- COLOR MATH AWARENESS: the SNES hardware supports additive and subtractive blending
  between layers. Design palettes that anticipate color math interactions —
  bright accent colors will bloom when additively blended over dark backgrounds.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: lighting from all sides. Top-left only.
  * BANDING: parallel color bands. Stagger all transitions.
  * PURE BLACK (#000000) for any purpose: use darkest chromatic color.
  * PURE WHITE (#FFFFFF) for any purpose: use tinted near-whites.
  * FLAT HUE RAMPS: same hue at different values = amateur.
  * OVER-DITHERING: SNES has enough colors that dithering is rarely needed on sprites.
    Reserve dithering for tilesets and large background surfaces only.
  * PALETTE WASTE: every palette slot is precious. No two entries should be
    perceptually identical. If you can't tell them apart at 1x zoom, merge them.""",
}


# ---------------------------------------------------------------------------
# SNES tool configs (MCP)
# ---------------------------------------------------------------------------

_SNES_TOOL_CONFIGS: dict[str, dict] = {
    "early": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + ["apply_shading"],
        "rules": """\
TOOL RULES (SNES early era):
USE: create_canvas, set_palette, draw_rectangle (body scaffolding), draw_circle (rounded forms like the head),
  draw_pixels (main workhorse for detail and shading), draw_line (long thin elements such as belt lines, or held-item shafts when the subject names them),
  apply_outline (dark color, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2 or bayer_4x4, ONLY for background/terrain tiles,
  NEVER for character sprites
AVOID: apply_auto_shading (produces modern gradients, not SNES), suggest_antialiasing,
  apply_shading (smooth gradients not appropriate for early SNES)
Build sprite with rectangles for body scaffolding, then refine EVERY edge with draw_pixels.
SNES sprites need smooth curves and clean shading — draw_pixels is 80%+ of the work.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
    "mid": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES (SNES mid era):
USE: create_canvas, set_palette, draw_rectangle (scaffolding), draw_circle (scaffolding),
  draw_pixels (PRIMARY tool — 80%+ of drawing), draw_line (long thin elements such as belt or detail lines, or held-item shafts when the subject names them),
  draw_contour (complex curves), apply_outline (dark chromatic color, NOT black, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2, bayer_4x4, bayer_8x8, floyd_steinberg.
  Acceptable for terrain tiles and large background surfaces. Not for character sprites.
AVOID: apply_auto_shading (produces modern gradients that break SNES aesthetic),
  suggest_antialiasing (produces GBA-style AA, not SNES)
CRITICAL: All shading MUST be manual via draw_pixels. Place each shadow and highlight
pixel deliberately. SNES shading is precise and intentional — every pixel serves the
hue-shifted gradient. No auto tools can replicate this.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
    "late": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES (SNES late era):
USE: create_canvas, set_palette, draw_rectangle (initial scaffolding only), draw_circle (scaffolding),
  draw_pixels (PRIMARY tool — 90%+ of drawing for late-era quality), draw_line (construction lines),
  draw_contour (complex silhouettes), apply_outline (dark chromatic color matched to hue family, thickness=1)
MAYBE: draw_with_dither — bayer_2x2, bayer_4x4, bayer_8x8, floyd_steinberg.
  Good for terrain tiles and environmental texture. Not for character sprites.
AVOID: apply_auto_shading (cannot replicate hand-crafted hue-shifted gradients),
  suggest_antialiasing (GBA technique, not SNES)
CRITICAL: Late SNES art is 100% manual pixel placement. Every shadow pixel is hue-shifted,
every highlight is temperature-adjusted, every skin tone shade follows a precise warm hue path.
No automated tool can replicate Shibuya Kazuko or Chrono Trigger's sprite team.
draw_pixels is the only tool that gives you this level of control.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
}


# ---------------------------------------------------------------------------
# SNES view rules (MCP)
# ---------------------------------------------------------------------------

_SNES_VIEW_RULES: dict[str, str] = {
    "side": """\
VIEW: Side profile (facing right — SNES convention).
- Character faces right. Leading arm/leg slightly forward, trailing slightly back.
- Anything held (only when the subject names a held item) goes in the leading (right) hand, visible on the right side.
- Shadow colors on the back (left) edges — hue-shifted cool shadows.
- Depth: near arm overlaps torso, far arm may be partially hidden.
- SNES-specific: with 15 usable colors, show material transitions clearly.
  Hard surfaces take a sharp specular highlight on the leading shoulder; soft fabrics drape on the trailing side.""",

    "front": """\
VIEW: Front facing.
- Bilateral symmetry: left half mirrors right half (within 1px tolerance).
- Arms equidistant from center. A held item (when the subject names one) may break symmetry.
- Shadow colors on bottom edges — cool-shifted shadows under chin, below belt, boots.
- Eyes at same height, same size, centered on face.
- SNES-specific: face detail is critical. With 3-4 skin shades available,
  place shadow under hair or headwear, midtone on cheeks, highlight on forehead and nose bridge.""",

    "top-down": """\
VIEW: Top-down / overhead (A Link to the Past standard).
- Head is a circle/oval filling top 60% of canvas.
- Shoulders visible as wider rectangle below head circle.
- No legs visible. Feet may peek at bottom edge.
- Shadow on bottom edge of head oval — cool-shifted.
- Items visible from above: hat or headwear dominant; held items extend to the side only when the subject names them.
- SNES-specific: top-down sprites use strong outline to pop against terrain.
  Hair or headwear gets 3+ shading steps visible from above.""",

    "3/4": """\
VIEW: 3/4 perspective (facing right and slightly toward viewer).
- Right side of body is 1-2px wider than left (foreshortening).
- Right arm more visible than left. Right leg forward.
- Shadow on left edges (farther from viewer) — cool hue shift.
- Face shows both eyes but right eye 1px larger or closer to center.
- SNES-specific: 3/4 view allows maximum material showcase.
  Show armor, fabric, and skin in a single composition with distinct shading behavior per material.""",
}


# ---------------------------------------------------------------------------
# SNES few-shot examples (MCP)
# ---------------------------------------------------------------------------

_SNES_FEW_SHOT_EXAMPLES: dict[str, str] = {
    # rg-023: 16x16 examples for the Aseprite-mid/late web-app path. SNES at
    # 16x16 cannot deliver DKC/SMRPG pre-rendered detail (the 256-pixel budget
    # eats the gradient vocabulary), so these examples scope to "clean readable
    # 16-bit silhouette with hue-shifted ramps" — closer to early-SNES sprite
    # work than to pre-rendered late-SNES showpieces. Honest framing for the
    # bake-off; CLAUDE.md still flags 32x32+ as the recommended size for SNES.
    "mid_16x16": """\
REFERENCE EXAMPLE — Mid SNES 16x16 humanoid character with hard-surface garment (quality benchmark, do not copy):
Palette: #181031 (deep purple-black outline), #4A39A5 (armor midtone), #7363CE (armor highlight),
  #C56B31 (skin midtone), #E79C5A (skin highlight), #F7DE73 (gold accent)
Key structure: deep purple-black chromatic outline (NOT pure black), thins on top-left highlight edges.
  Sprite fills full 16px height — content spans rows 0 to 15.
  Head 5x4 at rows 1-4: 2-step skin (midtone face, highlight on near cheek + nose).
  Eyes: 2px outline color at row 2, 1px gold accent for iris glint optional.
  Headwear/helmet (when the subject names one): armor midtone with 1px highlight stripe top-left.
  Torso: 8x5 at rows 5-9, armor midtone fill, single-pixel highlight on left shoulder.
  Arms: 2px wide flanking torso, rows 5-9.
  Legs: two 3x4 columns at rows 10-13, armor midtone with 1px shadow on inner edges.
  Feet: 4px wide footwear at rows 14-15.
  Optional held item (only when the subject names one): 1px wide armor-highlight extending from row 0 to row 8 on right side, gold accent pixel at the topmost pixel.
  Gold accent pixels: belt buckle (1px at row 9), peak of any held item.
Total: ~75-90 opaque pixels (varies with held item). 6 colors used with intent — armor 2-step ramp,
skin 2-step, gold accent for focal points. Material distinction (armor vs skin vs gold) reads at 16x16.
This is early-Super-Mario-World scale + SNES color vocabulary, NOT pre-rendered DKC scale.
CRITICAL: content spans row 0 to row 15 — the FULL 16px height.""",

    "late_16x16": """\
REFERENCE EXAMPLE — Late SNES 16x16 humanoid character with cloth garment + accent (quality benchmark, do not copy):
Palette: #101029 (outline — darkest indigo), #39296B (robe shadow), #5A4A9C (robe midtone),
  #846BCE (robe highlight), #CE844A (skin midtone), #E7AD6B (skin highlight),
  #4ABDB5 (teal accent), #F7E78C (gold accent)
Key structure: indigo chromatic outline matched to dominant cool purple hue family.
  Sprite fills full 16px height — content spans rows 0 to 15.
  Head 5x4 at rows 1-4: 2-step skin gradient — midtone center, highlight top-left forehead + cheek.
  Eyes: 2px outline color, 1px gold iris optional.
  Hood/headwear (only when the subject names one): robe midtone with shadow inside hood opening, highlight on hood crown.
  Robe body: 8x6 at rows 5-10, 3-step purple ramp — shadow on right side and folds, midtone center, highlight on left shoulder.
  Chest motif (only when the subject names one): teal accent — 1-2 pixels, hue contrast against dominant purple.
  Arms: 2px wide flanking robe, rows 5-9.
  Robe hem: jagged at row 11 with shadow/midtone alternating to suggest fabric weight.
  Legs/feet: 3x4 columns at rows 12-15 in robe shadow color (legs partly hidden by robe).
  Optional held item (only when the subject names one): 1px wide robe-shadow color from row 0 to row 8 on right, gold accent at the topmost pixel (e.g. staff orb, candle, instrument finial).
  Gold accent pixels: belt buckle, peak of any held item, optional eye iris glint.
Total: ~85-100 opaque pixels (varies with held item). 8 colors with full hue-shifted purple ramp.
Materials read distinctly at 16x16: cloth (soft transitions in robe), skin (warm 2-step),
hard accent (high-contrast gold). NOT Chrono Trigger pre-rendered scale — that needs 32x32+.
This is the readable-late-SNES silhouette achievable in 256 pixels.
CRITICAL: content spans row 0 to row 15 — the FULL 16px height.""",

    "early_32x32": """\
REFERENCE EXAMPLE — Early SNES 32x32 humanoid character with hard-surface garment + trailing fabric (quality benchmark, do not copy):
Palette: #182039 (dark navy outline), #3942A5 (blue shadow), #5A73CE (blue midtone),
  #8CA5E7 (blue highlight), #C5A573 (skin shadow), #E7C594 (skin midtone),
  #F7DEA5 (skin highlight), #F7F7E7 (white accent), #8C1821 (red fabric)
Key structure: dark navy outline (NOT black) on all external edges.
  CANVAS UTILIZATION: sprite content spans rows 2-29 (28px tall, 87% of 32px canvas).
  Centered horizontally with 1-2px margin on each side.
  Head 10x9 at rows 2-10, centered. 3 skin shades — shadow under headwear, midtone on cheek,
  highlight on forehead. Eyes: 3px wide, dark navy on skin midtone.
  Headwear: blue midtone with 2px highlight stripe on top-left curve.
  Torso: 14x9 at rows 11-19, blue hard-surface garment — shadow on right side, midtone center,
  highlight on left shoulder edge and chest plate. Belt detail at row 19.
  Red trailing fabric (cape, scarf, sash — depends on the subject): visible on trailing (left) side, 5px wide, 2 shades with fold detail.
  Arms: 4x9 flanking torso. Forearm/upper arm distinction via shade change.
  Legs: 5x7 each at rows 20-26, blue garment with shadow on inner edges. Knee detail.
  Feet: 7px wide at rows 27-29. Footwear shape with sole and heel visible.
  Optional held item (only when the subject names one): 2px wide, highlight-color extending 6px above right shoulder, white accent at the topmost pixel.
  White accent on: top of headwear, peak of any held item, belt buckle, footwear toe.
Total: ~330-350 opaque pixels (varies with held item). Clean shading with clear directional light. Materials
readable: hard-surface garment vs fabric vs skin. Sprite fills the canvas — NOT a 16x16 sprite
in a 32x32 space.""",

    "mid_32x32": """\
REFERENCE EXAMPLE — Mid SNES 32x32 humanoid character with hard-surface armor and trailing fabric (quality benchmark, do not copy):
Palette: #181031 (deep purple-black outline), #312163 (armor shadow), #4A39A5 (armor midtone),
  #7363CE (armor highlight), #9C84E7 (specular), #7B3910 (skin shadow), #C56B31 (skin midtone),
  #E79C5A (skin highlight), #F7C584 (skin light), #8C1018 (fabric shadow),
  #C52129 (fabric midtone), #E75242 (fabric highlight), #F7DE73 (gold accent)
Key structure: deep purple-black outline matched to armor hue family.
  CANVAS UTILIZATION: sprite content spans rows 2-28 (27px tall, 84% of 32px canvas).
  Centered horizontally, 16-20px wide at widest point (torso + arms).
  Head 10x8 at rows 2-9: 4-shade skin gradient — shadow under headwear brim, midtone on far cheek,
  highlight on near cheek and nose bridge, light on forehead. Eyes: 3px wide, outline color.
  Headwear: armor midtone with shadow on right, highlight on left rim, 2px specular on crown.
  Torso: 14x9 armor at rows 10-18 — HARD-SURFACE shading: sharp transitions between shadow and highlight.
  2px specular highlights on shoulder peaks and chest plate center.
  Shoulders extend 2px beyond arm edges for heroic silhouette.
  Trailing fabric (cape, scarf, sash — depends on the subject): trailing from left shoulder, 6px wide, 3 red shades with hue shift —
  shadow is dark burgundy (cool-shifted), midtone is true red, highlight is warm orange-red.
  Arms: 4x10 each, hard-surface detail on forearms. Hands 3x3 with relaxed grip (or gripping a held item if the subject names one).
  Legs: 5x8 each at rows 19-26, armor with shadow/midtone/highlight following directional light.
  Lower-leg plates distinct from upper-leg plates via shade boundary.
  Feet: 7px wide at rows 27-28. Footwear with heel and toe detail.
  Gold accent pixels: belt buckle center (2x2), headwear jewel, peak of any held item, footwear clasps.
Total: ~360-400 opaque pixels (varies with held item). Hue-shifted shading across all materials. Hard surface reads as hard
(high contrast, specular). Trailing fabric reads as fabric (soft transitions). Skin reads as skin
(warm gradient). Sprite fills the 32x32 canvas. This is the Super Metroid / FFVI quality standard.""",

    "early": """\
REFERENCE EXAMPLE — Early SNES 16x24 humanoid character with hard-surface garment + trailing fabric (quality benchmark, do not copy):
Palette: #182039 (dark navy outline), #3942A5 (blue shadow), #5A73CE (blue midtone),
  #8CA5E7 (blue highlight), #C5A573 (skin shadow), #E7C594 (skin midtone),
  #F7DEA5 (skin highlight), #F7F7E7 (white accent), #8C1821 (red fabric)
Key structure: dark navy outline (NOT black) on all external edges.
  Head 5x5 at rows 2-6, 3 skin shades — shadow under headwear, midtone on cheek,
  highlight on forehead. Eyes: 2px dark navy on skin midtone.
  Headwear: blue midtone with 1px highlight on top-left curve.
  Torso: 8x5 at rows 7-11, blue hard-surface garment — shadow on right side, midtone center,
  highlight on left shoulder edge and chest plate.
  Red trailing fabric (cape, scarf, sash — depends on the subject): visible on trailing (left) side, 3px wide, single darker shade at fold.
  Legs: 4x5 at rows 12-16, blue garment with shadow on inner edges.
  Optional held item (only when the subject names one): 1px highlight-color line extending 4px above right shoulder, white accent at the topmost pixel.
  White accent on: top of headwear, peak of any held item, belt buckle.
Total: ~110-120 opaque pixels (varies with held item). Clean shading with clear directional light. Materials
readable: hard-surface garment vs fabric vs skin, each with distinct value behavior.""",

    "mid": """\
REFERENCE EXAMPLE — Mid SNES 16x24 humanoid character with hard-surface armor and trailing fabric (quality benchmark, do not copy):
Palette: #181031 (deep purple-black outline), #312163 (armor shadow), #4A39A5 (armor midtone),
  #7363CE (armor highlight), #9C84E7 (specular), #7B3910 (skin shadow), #C56B31 (skin midtone),
  #E79C5A (skin highlight), #F7C584 (skin light), #8C1018 (fabric shadow),
  #C52129 (fabric midtone), #E75242 (fabric highlight), #F7DE73 (gold accent)
Key structure: deep purple-black outline matched to armor hue family.
  Head 5x5: 4-shade skin gradient — shadow under headwear brim, midtone on far cheek,
  highlight on near cheek and nose bridge, light on forehead. Eyes: outline color.
  Headwear: armor midtone with shadow on right, highlight on left rim, 1px specular on crown.
  Torso: 8x6 armor — HARD-SURFACE shading: sharp transitions between shadow and highlight.
  1px specular highlights on shoulder peak and chest plate center.
  Trailing fabric (cape, scarf, sash — depends on the subject): trailing from left shoulder, 3 red shades with hue shift —
  shadow is dark burgundy (cool-shifted), midtone is true red, highlight is warm orange-red.
  Legs: 4x6 armor with shadow/midtone/highlight following directional light.
  Gold accent pixels: belt buckle center, headwear jewel, peak of any held item. 1px each.
Total: ~125-140 opaque pixels (varies with held item). Hue-shifted shading across all materials. Hard surface reads as hard
(high contrast, specular). Trailing fabric reads as fabric (soft transitions). Skin reads as skin
(warm gradient). This is the Super Metroid / FFVI quality standard.""",

    "late": """\
REFERENCE EXAMPLE — Late SNES 24x32 humanoid character with flowing fabric robe and chest-detail accent (quality benchmark, do not copy):
Palette: #101029 (outline — darkest indigo), #211842 (robe deep shadow), #39296B (robe shadow),
  #5A4A9C (robe midtone), #846BCE (robe highlight), #A594E7 (robe light),
  #6B2910 (skin deep shadow), #9C5231 (skin shadow), #CE844A (skin midtone),
  #E7AD6B (skin highlight), #F7CE8C (skin light), #184A4A (accent shadow — teal),
  #298484 (accent midtone), #4ABDB5 (accent highlight), #F7E78C (gold accent)
Key structure: indigo outline following the sprite's dominant cool purple hue family.
  Head 6x6: FULL Shibuya-standard skin gradient with 5 shades along warm hue path.
  Deep shadow under headwear brim and chin. Shadow on far cheek. Midtone across face.
  Highlight on near cheekbone and nose. Light on forehead.
  Eyes: outline color with 1px gold accent for iris glint.
  Headwear/hood: robe palette, 4-step gradient from deep shadow inside hood to highlight on brim peak.
  Robe body: 10x10, 5 purple shades with FULL HUE SHIFT — deep shadow is blue-purple (cool),
  shadow is red-purple (warm shift at dark end), midtone is true purple, highlight is
  lavender (desaturated), light is pale lilac on top-left shoulder and sleeve edge.
  Chest motif (clockwork, embroidery, insignia — depends on the subject): teal accent — 3 shades of teal-green provide hue contrast
  against dominant purple. Detail strokes in gold accent, 1px each.
  Optional held item (only when the subject names one): 2px wide, robe shadow color, topped with gold accent (3px circle with
  1px highlight) — could be a staff orb, candle flame, instrument finial, etc.
  Robe bottom: wide flowing hem, deep shadow in folds, midtone on front face.
Total: ~230-250 opaque pixels (varies with held item). Every material has a distinct shading language. Robe = soft fabric
transitions across 5 hue-shifted steps. Skin = warm path with precise anatomical shadow
placement. Hard accent = high contrast with specular. This is Chrono Trigger peak quality.""",
}


# ---------------------------------------------------------------------------
# SNES ConsolePromptData
# ---------------------------------------------------------------------------

SNES_PROMPT_DATA = ConsolePromptData(
    name="snes",
    display_name="Super Nintendo",
    default_era="mid",
    eras={
        "early": _SNES_ERA_EARLY,
        "mid": _SNES_ERA_MID,
        "late": _SNES_ERA_LATE,
    },
    terrain_color_hints=_SNES_TERRAIN_COLOR_HINTS,
    palette_rules=_SNES_PALETTE_RULES,
    color_theory_rules=_SNES_COLOR_THEORY_RULES,
    tool_configs=_SNES_TOOL_CONFIGS,
    view_rules=_SNES_VIEW_RULES,
    few_shot_examples=_SNES_FEW_SHOT_EXAMPLES,
    mood_palettes=None,
    palette_presets=None,
)


# ---------------------------------------------------------------------------
# PC Engine era prompt data
# ---------------------------------------------------------------------------

_PCE_ERA_EARLY = EraPromptData(
    label="early PC Engine style (1987-1989), arcade port fidelity, establishing the 16-palette sprite system",
    year_range="1987-1989",
    reference_games="R-Type, Bonk's Adventure, Galaga '88",
    style_ref="Style: R-Type, Bonk's Adventure, Galaga '88 PC Engine sprites. Bright saturated colors, clean mechanical linework, large character sprites.",
    object_ref="Style: R-Type, Bonk's Adventure, Galaga '88 PC Engine sprites. Bright saturated colors, clean mechanical linework, large bold shapes.",
    tile_ref="Style: R-Type space station tiles, Bonk's Adventure prehistoric terrain. Dense single-layer backgrounds.",
    era_hints=(
        "Early PC Engine pixel art, 1987-1989 era. "
        "The platform launched as a bridge between 8-bit and 16-bit — sprites are richer than NES "
        "but still finding the hardware's identity. Arcade port fidelity is the priority. "
        "Sprites use 4-8 colors from a 15-color palette slot. Artists haven't yet exploited "
        "the full 16 sprite palette budget — most games use 6-10 palettes. "
        "Colors are bright and saturated, pulled from the 9-bit RGB space (512 total). "
        "Minimum sprite size is 16x16 — no 8x8 sprites exist on this hardware. "
        "Single background plane means tile detail must carry all environmental depth. "
        "Style: R-Type mechanical enemies, Bonk's large-headed caveboy, Galaga '88 alien formations — "
        "arcade-quality visuals on a home console."
    ),
    outline_hint="Clean dark outline, 1 pixel wide. Outline color chosen from darkest palette entry, often dark blue or near-black.",
    pixel_scale=None,
    max_cleanup_colors=8,
)

_PCE_ERA_MID = EraPromptData(
    label="PC Engine style (1990-1992), mature hardware exploitation, shmup excellence",
    year_range="1990-1992",
    reference_games="Blazing Lazers, Bomberman '93, Soldier Blade, Ys I & II",
    style_ref="Style: Blazing Lazers, Soldier Blade, Ys I & II PC Engine sprites. Full palette exploitation, smooth gradient shading, weapon contrast palettes.",
    tile_ref="Style: Ys overworld tiles, Soldier Blade starfield backgrounds. Dense single-layer tile composition with high local contrast.",
    era_hints=(
        "Mid-era PC Engine pixel art, 1990-1992 — mature hardware exploitation. "
        "Artists now use 10-15 colors per sprite from the full 15-slot palette. "
        "Smooth gradient shading across large sprites: shadow, midtone, highlight transitions "
        "with 3-5 value steps within a single hue. 16 sprite palettes fully allocated — "
        "different enemy types, weapon effects, and player states each get dedicated palettes. "
        "Weapon/projectile sprites use high-contrast palettes for readability against busy backgrounds. "
        "Composited large sprites from multiple 16x16 or 32x32 hardware units. "
        "Shmup genre dominates: clean mechanical designs, readable bullet patterns, "
        "multi-segment bosses distributed across scanlines within the 16/scanline limit. "
        "Style: Soldier Blade's tiered weapon states, Blazing Lazers' boss compositions, "
        "Bomberman '93's compact multiplayer-optimized character sprites."
    ),
    outline_hint="Dark chromatic outline using darkest palette value. Dark navy, dark teal, or dark brown — not pure black.",
    pixel_scale=4,
    max_cleanup_colors=12,
)

_PCE_ERA_LATE = EraPromptData(
    label="late PC Engine CD style (1993-1994), peak sprite art, animation depth, CD-ROM era",
    year_range="1993-1994",
    reference_games="Castlevania: Rondo of Blood, Sapphire, Lords of Thunder",
    style_ref="Style: Castlevania: Rondo of Blood, Sapphire, Lords of Thunder PC Engine CD sprites. Peak 15-color shading, hue-shifted gradients, expressive animation frames.",
    object_ref="Style: Castlevania: Rondo of Blood, Sapphire, Lords of Thunder PC Engine CD sprites. Peak 15-color shading, hue-shifted gradients, polished detail.",
    tile_ref="Style: Rondo of Blood gothic castle tiles, Lords of Thunder environmental backgrounds. Maximum tile variety, architectural detail in single-layer BG.",
    era_hints=(
        "Late PC Engine CD pixel art, 1993-1994 — the absolute peak of the platform. "
        "CD-ROM storage removes sprite sheet size limits, enabling deep animation frame counts. "
        "All 15 visible palette slots used for smooth, hue-shifted gradient shading on large sprites. "
        "Shadow colors shift toward blue/purple, highlights shift toward yellow/white — "
        "the same hue-shifting discipline as peak NES and Genesis late art, but with more color slots "
        "to create smoother transitions. Material differentiation through shading: metal is high-contrast "
        "with sharp specular highlights, fabric shows soft value transitions in folds, "
        "skin uses warm midtones with subtle cool shadows. "
        "Boss sprites are massive composites spanning many 32x32 hardware sprites, "
        "carefully distributed across scanlines. Background tiles reach peak density — "
        "gothic stonework, clocktower gears, underground waterways — all from a single BG plane. "
        "Style: Richter Belmont's full animation set in Rondo of Blood, "
        "Lords of Thunder's screen-filling boss encounters, Sapphire's polished shmup art."
    ),
    outline_hint=(
        "Dark chromatic outline using hue-shifted darkest color, NOT pure black. "
        "Dark navy-purple for cool palettes, dark brown-maroon for warm palettes. "
        "Outline may thin to 0px on highlight edges where light source meets the form."
    ),
    pixel_scale=None,
    max_cleanup_colors=15,
)


# ---------------------------------------------------------------------------
# PC Engine terrain color hints (FLUX)
# ---------------------------------------------------------------------------

_PCE_TERRAIN_COLOR_HINTS: list[tuple[list[str], str]] = [
    (["grass", "field", "meadow", "lawn", "turf"],
     "IMPORTANT: Rich saturated greens from the 9-bit RGB space. "
     "Multiple green values for grass body and blade detail — PC Engine can afford more color variety than NES. "
     "Like the prehistoric terrain tiles in Bonk's Adventure."),
    (["water", "ocean", "sea", "lake", "river", "pond"],
     "IMPORTANT: Deep blues with lighter blue-cyan highlights for wave crests. "
     "Use the 9-bit palette's blue range to create depth in water surfaces. "
     "Like the waterway tiles in Rondo of Blood."),
    (["sand", "desert", "beach", "dune"],
     "IMPORTANT: Warm tan and yellow tones from the 9-bit RGB space. "
     "Sandy terrain with subtle value variation for texture on the single BG plane."),
    (["stone", "rock", "cave", "dungeon", "castle", "fortress"],
     "IMPORTANT: Grays and desaturated blues for stone surfaces. "
     "Dense tile detail to compensate for single BG plane — mortar lines, weathering, cracks. "
     "Like the gothic castle stonework in Rondo of Blood."),
    (["brick", "wall", "masonry"],
     "IMPORTANT: Browns and dark reds with visible mortar grid. "
     "High tile variety for architectural detail on the single background layer."),
    (["wood", "plank", "floor", "deck", "log", "timber"],
     "IMPORTANT: Warm browns with grain texture. Multiple brown values "
     "for wood plank variation — PC Engine's palette budget allows richer wood shading."),
    (["snow", "ice", "frost", "winter", "tundra"],
     "IMPORTANT: White and light blue-cyan tones. Subtle blue shadows on snow surfaces."),
    (["lava", "magma", "fire", "volcano"],
     "IMPORTANT: Bright reds, oranges, and yellows with high contrast. "
     "Lava glow rendered with warm highlight against dark rock."),
    (["dirt", "mud", "earth", "soil", "ground"],
     "IMPORTANT: Dark and medium browns with subtle warm/cool variation for texture."),
    (["space", "starfield", "cosmos", "nebula"],
     "IMPORTANT: Deep black background with single-pixel star dots in white and light blue. "
     "PC Engine shmup convention — clean dark backgrounds for projectile readability. "
     "Like the starfield tiles in Soldier Blade and Blazing Lazers."),
]


# ---------------------------------------------------------------------------
# PC Engine palette rules (MCP)
# ---------------------------------------------------------------------------

_PCE_PALETTE_RULES: dict[str, str] = {
    "early": """\
PALETTE RULES:
- You have {n} colors plus transparency (color 0 of each palette is transparent).
- PC Engine uses 9-bit RGB: 512 possible colors. Values are multiples of 32 per channel (0, 32, 64, 96, 128, 160, 192, 224).
- 16 sprite palettes available, each with 15 visible color slots — but early-era games use 4-8 colors per sprite.
- {c0} ({r0}): dark outline color. Used for 1px external border and internal feature lines.
- {c1} ({r1}): primary body fill, covers 50-60% of opaque pixels.
- {c2} ({r2}): secondary color — skin, accent, contrasting element.
{extra_color}\
- Single background plane: no parallax layers. All environmental depth must come from tile detail.
- Minimum sprite size is 16x16 — design accordingly, no 8x8 sprites.
- Keep palette usage conservative at this era. 4-8 colors, not the full 15.""",

    "mid": """\
PALETTE RULES:
- You have {n} colors plus transparency (color 0 = transparent).
- PC Engine 9-bit RGB: all color values must be multiples of 32 per channel.
- 16 sprite palettes x 15 visible colors each = up to 240 simultaneous sprite colors.
- This era exploits the palette system — use 10-15 colors per sprite for smooth shading.
- {c0} ({r0}): dark chromatic outline — NOT pure black. 1px external edge + feature lines.
- {c1} ({r1}): primary body midtone, 35-45% of opaque pixels.
- {c2} ({r2}): secondary region fill — skin, cape, boots, 20-30% of pixels.
{extra_color}\
- Projectile sprites MUST use a separate high-contrast palette from character sprites.
  Projectiles need to read instantly against busy single-layer backgrounds.
- Composite large sprites from multiple 16x16 or 32x32 hardware sprite objects.
- Assign different enemy types to different sprite palettes — 16 palettes is enough
  to give every distinct entity its own color identity.
- Boss sprites: distribute component sprites across scanlines to stay within 16/scanline limit.
{color_list}""",

    "late": """\
PALETTE RULES:
- You have {n} colors plus transparency (color 0 = transparent).
- PC Engine CD era: CD storage removes sprite sheet size constraints. Use all 15 palette slots.
- 9-bit RGB space: values are multiples of 32 per channel (0, 32, 64, 96, 128, 160, 192, 224).
- Colors are pre-organized into hue-shifted gradient groups. Use each in its assigned role.
- BODY GRADIENT (primary region — armor, robe, main clothing):
  * {c1} (body_deep_shadow): bottom-right deep recesses, undersides. 8-12% of body area.
  * {c2} (body_shadow): bottom-right edges, folds. 15-20% of body area.
  * {c3} (body_midtone): largest fill. 40-50% of body area. The base color.
  * {c4} (body_highlight): top-left convex edges. 10-15% of body area.
  * {c5} (body_bright): peak highlights, single-pixel placements. 3-5% of body.
- ACCENT GROUP (secondary region — e.g. cape, skin, boots, accessories):
  * {c0} (outline): 1px border on ALL external edges. Dark chromatic color, NOT pure black.
  * Remaining colors: accent midtone, accent highlight, detail/gem colors.
- With 15 usable colors, build 4-5 step gradients within body regions.
  This is the largest sprite color budget of any 8/16-bit console — use it for smooth shading.
- Strategic single-pixel highlights — place on:
  * Top of head or hair
  * Left shoulder peak
  * The topmost pixel of any held item (only when the subject names one)
  * Gem or buckle center
  * Eye glint
{color_list}""",
}


# ---------------------------------------------------------------------------
# PC Engine color theory rules (MCP)
# ---------------------------------------------------------------------------

_PCE_COLOR_THEORY_RULES: dict[str, str] = {
    "early": """\
COLOR THEORY:
- 9-bit RGB color space: each channel has 8 possible values (0-7), producing 512 total colors.
- In hex, valid channel values are: #00, #24, #48, #6D, #91, #B6, #DA, #FF
  (approximately — the 3-bit values map to 0, 36, 73, 109, 146, 182, 219, 255).
- At 4-8 colors per sprite, focus on strong value contrast between outline and fills.
- Pick saturated, bright colors — the PC Engine's identity is vivid color against the NES's muted tones.
- Arcade port aesthetic: high contrast, clean color boundaries, instant readability.
- Single BG plane: background tile colors must carry environmental depth on their own.
  Use value contrast between foreground objects and distant elements within the same tile layer.""",

    "mid": """\
COLOR THEORY:
- Light source is TOP-LEFT for all sprites. Universal convention.
- 9-bit RGB gives 512 colors — enough for smooth shading gradients.
  Build 3-4 step value ramps within each hue: dark shadow, shadow, midtone, highlight.
- SMOOTH GRADIENT TECHNIQUE (exploit 15-color palette):
  * With 10-15 colors available per sprite, you can shade with 3-5 value steps per hue group.
  * This is the key advantage over NES (3 colors per sprite) and Genesis (15 colors but only 4 palettes).
  * Use the extra slots for transition colors between shadow and midtone.
- Projectile contrast: projectile palettes should use complementary or high-saturation
  colors that pop against the dominant background hues. If backgrounds are cool (blue, green),
  projectiles should be warm (orange, yellow, white).
- Dense single-layer background composition:
  * No second BG plane for parallax — all depth must come from tile design.
  * Use value contrast: distant elements darker/less saturated, near elements brighter/more saturated.
  * Foreground-implying tiles (bushes, pillars) should have sharper outlines than distance tiles.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: shading around all edges equally. Shade from top-left only.
  * BANDING: parallel color lines. Stagger with 1px offsets.
  * PALETTE WASTE: using 5 colors when you have 15 available. Use the budget for shading depth.""",

    "late": """\
COLOR THEORY:
- Light source is TOP-LEFT. All shading follows this.
- HUE SHIFTING (critical for late-era quality — same principle as peak NES/Genesis):
  * Shadows: shift hue TOWARD BLUE/PURPLE, lower value. A red cape's shadow is dark purple-red.
  * Highlights: shift hue TOWARD YELLOW/WHITE, raise value. Blue armor's highlight is cyan-white.
  * With 15 palette slots, you can build 4-5 step hue-shifted gradients within a single sprite.
    This is impossible on NES (3 colors) and impractical on Genesis (4 shared palettes).
- 9-BIT RGB GRADIENT CONSTRUCTION:
  * Plan gradients in 3-bit-per-channel space. Each channel step is ~36 in 8-bit terms.
  * A blue gradient: #000048 -> #0000B6 -> #2448DA -> #48B6FF -> #91DAFF
    (shadow navy -> midtone blue -> highlight cyan-white, with hue shift toward cyan).
  * The 8-step-per-channel granularity means some desired transitions won't have exact values.
    Pick the closest 9-bit color rather than inventing values between grid points.
- MATERIAL DIFFERENTIATION (exploit the 15-color budget):
  * METAL: high contrast, sharp value jumps, 1px specular highlight at brightest point.
    Use 4-5 colors for the metal gradient alone.
  * FABRIC: soft value transitions, visible color in folds. 3-4 colors for fabric.
  * SKIN: warm midtone dominant, subtle cool shadow under chin/arms, warm highlight on forehead.
  * GEM/GLASS: extreme contrast — darkest dark adjacent to brightest bright. 2-3 colors.
- DENSE SINGLE-LAYER BG COMPOSITION:
  * No second plane — environmental depth comes entirely from tile artistry.
  * Atmospheric perspective via tile value: distant architecture darker, near elements brighter.
  * Tile variety is unlimited with CD storage — use unique tiles freely.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: lighting from all sides. Always top-left.
  * BANDING: parallel color bands. Break up with staggered pixels.
  * OVER-ANTIALIASING: 1px AA is plenty. Wider AA looks SNES, not PC Engine.
  * PALETTE UNDERUSE: with 15 slots available, using 6 is a waste. Fill the budget.""",
}


# ---------------------------------------------------------------------------
# PC Engine tool configs (MCP)
# ---------------------------------------------------------------------------

_PCE_TOOL_CONFIGS: dict[str, dict] = {
    "early": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_pixels",
            "draw_circle", "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + [
            "draw_with_dither", "apply_shading",
        ],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (filled=true for body scaffolding),
  draw_circle (head, round shapes — 16x16 minimum sprite is large enough for circles),
  draw_pixels (detail placement), apply_outline (darkest palette color, thickness=1)
AVOID: draw_with_dither (not characteristic of early PCE style), apply_auto_shading,
  suggest_antialiasing, apply_shading
PC Engine sprites start at 16x16 minimum — you have more room than NES for shape construction.
Outline applied LAST. Use draw_rectangle for body blocks, then refine with draw_pixels.""",
    },
    "mid": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST + ["apply_shading"],
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (scaffolding), draw_circle (rounded forms like the head and round parts),
  draw_pixels (PRIMARY workhorse — 70%+ of drawing), draw_line (long thin elements such as belt lines or panel seams, or held-item shafts when the subject names them),
  draw_contour (complex curved shapes), apply_outline (dark chromatic color, NOT black, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2 or bayer_4x4, ONLY for background terrain tiles, NEVER for character sprites
AVOID: apply_auto_shading (adds gradient colors outside intended palette), suggest_antialiasing,
  apply_shading (smooth auto-gradients don't match hand-placed PCE sprite shading)
All shading is manual via draw_pixels. With 10-15 colors available, place each shade deliberately.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
    "late": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES:
USE: create_canvas, set_palette, draw_rectangle (scaffolding), draw_circle (scaffolding),
  draw_pixels (PRIMARY tool — 80%+ of drawing), draw_line (long thin elements such as belt lines or panel seams, or held-item shafts when the subject names them),
  draw_contour (complex shapes — armor curves, wing edges), apply_outline (dark chromatic color, thickness=1)
MAYBE: draw_with_dither — ONLY bayer_2x2, bayer_4x4, bayer_8x8, floyd_steinberg. Good for terrain tiles.
AVOID: apply_auto_shading (adds unwanted intermediate colors), suggest_antialiasing
CRITICAL: With 15 colors available, ALL shading must be manual via draw_pixels.
  Place each hue-shifted gradient step by hand — this is what makes late PCE art look polished.
  Do NOT rely on auto tools to create transitions.
BROKEN DITHER PATTERNS (silently produce solid fills — do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
}


# ---------------------------------------------------------------------------
# PC Engine view rules (MCP)
# ---------------------------------------------------------------------------

_PCE_VIEW_RULES: dict[str, str] = {
    "side": """\
VIEW: Side profile (facing right — standard convention).
- Character faces right. Leading arm/leg slightly forward, trailing slightly back.
- Anything held (only when the subject names a held item) goes in the leading (right) hand, visible on the right side.
- Shadow colors on the back (left) edges of the body.
- PC Engine sprites start at 16x16 minimum — use the extra canvas for detail.
- Large characters should be composited from multiple 16x16 or 32x32 hardware sprite blocks.
- Depth: near arm overlaps torso, far arm may be partially hidden.""",

    "front": """\
VIEW: Front facing.
- Bilateral symmetry: left half mirrors right half (within 1px tolerance).
- Arms equidistant from center. A held item (when the subject names one) may break symmetry.
- Shadow colors on bottom edges of features.
- Eyes at same height, same size, centered on face.
- With 15 palette colors available, face/head can have richer shading than NES equivalent.""",

    "top-down": """\
VIEW: Top-down / overhead (RPG perspective — Ys style).
- Head is a circle/oval filling top 60% of canvas.
- Shoulders visible as wider rectangle below head circle.
- No legs visible. Feet may peek at bottom edge.
- Shadow on bottom edge of head oval.
- Items visible from above: hat or headwear dominant; held items extend to the side only when the subject names them.
- Use distinct palette for player vs. environment for readability in dense tile maps.""",

    "3/4": """\
VIEW: 3/4 perspective (facing right and slightly toward viewer).
- Right side of body is 1-2px wider than left (foreshortening).
- Right arm more visible than left. Right leg forward.
- Shadow on left edges (farther from viewer).
- Face shows both eyes but right eye 1px larger or closer to center.
- PC Engine's larger palette budget allows richer foreshortening shading — use it.""",
}


# ---------------------------------------------------------------------------
# PC Engine few-shot examples (MCP)
# ---------------------------------------------------------------------------

_PCE_FEW_SHOT_EXAMPLES: dict[str, str] = {
    "early": """\
REFERENCE EXAMPLE — Early PCE 16x16 space fighter (quality benchmark, do not copy):
Palette: #000048 (dark navy outline), #4891DA (primary blue hull), #91DAFF (highlight),
  #DA6D00 (engine glow orange), #B6B6B6 (cockpit gray)
Key structure: 1px dark navy outline around ship body.
  Hull 10x6 primary blue at rows 5-10, tapered nose at rows 2-4.
  Cockpit: 3x2 gray at rows 6-7, centered. Highlight pixel on canopy top-left.
  Engine exhaust: 2x3 orange at rows 11-13, trailing behind hull.
  Wing details: 1px lines extending from hull sides at row 7.
Total: ~90 opaque pixels. Clean mechanical design, arcade port quality.
Note: all hex values are 9-bit RGB grid points (multiples of ~36 per channel).""",

    "mid": """\
REFERENCE EXAMPLE — Mid PCE 32x32 humanoid character with hard-surface garment + trailing fabric (quality benchmark, do not copy):
Palette: #24006D (dark purple outline), #480091 (body shadow), #6D24B6 (body midtone),
  #9148DA (body highlight), #B691FF (body bright), #DA9100 (skin shadow),
  #FFB624 (skin midtone), #FFDAB6 (skin highlight), #910000 (fabric shadow),
  #DA2400 (fabric midtone), #FF6D48 (fabric highlight), #B6B6B6 (hard-surface gray),
  #DADADA (hard-surface highlight), #FFFF91 (accent glow)
Key structure: Dark purple chromatic outline (NOT black).
  Headwear 8x6 with 4-step purple gradient: shadow at bottom-right, midtone center,
  highlight at top-left edge, bright pixel at top of head.
  Face: 4x3 skin area with 3-step warm gradient — shadow under chin, midtone cheeks, highlight forehead.
  Torso garment: 10x8 purple with full 5-step body gradient showing volume.
  Trailing fabric (cape, scarf, sash — depends on the subject): 6x10 behind body, 3-step red gradient with shadow on right folds.
  Optional held item (only when the subject names one): 2px wide, gray body with hard-surface highlight along left edge, accent-glow pixel at the topmost or grip point.
  Legs: garment with 3-step purple shading.
Total: ~330-350 opaque pixels (varies with held item). 14 colors used — the PC Engine's 15-slot palette exploited for smooth shading.
Material reads: hard surface (high contrast), trailing fabric (soft gradient), skin (warm tones).""",

    "late": """\
REFERENCE EXAMPLE — Late PCE CD 32x32 humanoid character with ornate flowing garment + chest accent (quality benchmark, do not copy):
Palette: #240024 (outline dark maroon), #480048 (body deep shadow), #6D006D (body shadow),
  #910091 (body midtone), #B624B6 (body highlight), #DA48DA (body bright),
  #6D4800 (skin shadow warm), #B69148 (skin midtone), #DADAB6 (skin highlight),
  #000091 (fabric deep shadow navy), #2424DA (fabric shadow), #4848FF (fabric midtone blue),
  #9191FF (fabric highlight), #FFFF48 (eye glow yellow), #FF0000 (gem accent red)
Key structure: Dark maroon chromatic outline — hue-shifted, NOT pure black.
  Head 8x7: skin gradient with warm shadows (brown-maroon under chin, warm midtone on cheeks,
  pale highlight on forehead). Eyes: 1px yellow glow each. Hair: darkest body colors swept back.
  Torso: 12x8 with 5-step purple hue-shifted gradient — deep shadow at bottom-right recesses,
  shadow on underside of garment ridges, midtone fills 40% of area, highlight on top-left edges,
  bright single-pixel on left shoulder peak.
  Trailing fabric (cape, robe, train — depends on the subject): 8x14 flowing behind and below body, 4-step blue gradient with navy deep shadow
  in folds, blue midtone on flat surfaces, highlight on leading edge catching light.
  Red gem accent on chest: 2x2, darkest red adjacent to brightest body highlight — maximum contrast for the focal jewel.
  Hands: skin tones, fingertip detail in outline color.
Total: ~400-420 opaque pixels. All 15 palette slots used. Hue-shifted gradients on every material.
Purple body shifts shadow toward red, highlight toward pink. Blue trailing fabric shifts shadow toward navy,
highlight toward lavender. Skin shifts shadow toward brown, highlight toward cream.
This is the PC Engine's peak — more simultaneous sprite colors than any other 8/16-bit console.""",
}


# ---------------------------------------------------------------------------
# PC Engine ConsolePromptData
# ---------------------------------------------------------------------------

PCE_PROMPT_DATA = ConsolePromptData(
    name="pc_engine",
    display_name="PC Engine",
    default_era="mid",
    eras={
        "early": _PCE_ERA_EARLY,
        "mid": _PCE_ERA_MID,
        "late": _PCE_ERA_LATE,
    },
    terrain_color_hints=_PCE_TERRAIN_COLOR_HINTS,
    palette_rules=_PCE_PALETTE_RULES,
    color_theory_rules=_PCE_COLOR_THEORY_RULES,
    tool_configs=_PCE_TOOL_CONFIGS,
    view_rules=_PCE_VIEW_RULES,
    few_shot_examples=_PCE_FEW_SHOT_EXAMPLES,
    mood_palettes=None,
    palette_presets=None,
)




# ---------------------------------------------------------------------------
# Sega Genesis / Mega Drive era prompt data
# ---------------------------------------------------------------------------

_GENESIS_ERA_EARLY = EraPromptData(
    label="early Sega Genesis 16-bit style (1989-1991), NES-influenced, learning 16-bit capabilities",
    year_range="1989-1991",
    reference_games="Sonic the Hedgehog, Golden Axe, Streets of Rage, Phantasy Star II",
    style_ref="Style: Sonic the Hedgehog (1991), Golden Axe, Streets of Rage, Phantasy Star II sprites. Bright primary colors, still NES-influenced proportions.",
    tile_ref="Style: Sonic Green Hill Zone checkerboard grass, Golden Axe stone tiles, Streets of Rage urban pavement.",
    era_hints=(
        "Early Sega Genesis pixel art, 1989-1991 era. "
        "Developers are still learning 16-bit capabilities \u2014 sprites often resemble "
        "enhanced NES ports rather than native 16-bit design. "
        "Sprite sizes are modest: 24x32 typical, up to 32x40 for bosses. "
        "Colors are brighter and more saturated than NES but palettes are simple \u2014 "
        "artists rarely use more than 10-12 of the 15 available colors per palette. "
        "Outlines are still heavy black, inherited from NES conventions. "
        "Dithering is minimal \u2014 flat color fills dominate. "
        "Character proportions lean chibi/squat, not yet the tall naturalistic "
        "figures of later Genesis games. "
        "Style: Sonic the Hedgehog, Golden Axe, Streets of Rage, Phantasy Star II, "
        "Altered Beast, Ghouls 'n Ghosts."
    ),
    outline_hint="Heavy black 1px outline around entire sprite, NES-inherited convention.",
    pixel_scale=None,
    max_cleanup_colors=10,
)

_GENESIS_ERA_MID = EraPromptData(
    label="peak Sega Genesis 16-bit style (1992-1993), large detailed sprites, parallax mastery",
    year_range="1992-1993",
    reference_games="Streets of Rage 2, Sonic 2, Gunstar Heroes, Thunder Force IV, Shinobi III",
    style_ref="Style: Streets of Rage 2, Sonic 2, Gunstar Heroes, Shinobi III Genesis sprites. Large, detailed, fluid animation.",
    tile_ref="Style: Sonic 2 Chemical Plant tiles, Streets of Rage 2 urban backgrounds, Thunder Force IV parallax layers.",
    era_hints=(
        "Peak Sega Genesis pixel art, 1992-1993 \u2014 the golden era of 16-bit. "
        "Artists have mastered the hardware. Sprites are large and detailed: "
        "32x48 for player characters, 48x48+ for bosses built from linked hardware sprites. "
        "Full 15-color palettes used with purpose \u2014 3-4 step shading ramps "
        "for skin, armor, and clothing. Smooth gradients simulated with 2x2 dithering. "
        "Character proportions are naturalistic: tall figures with visible muscle "
        "definition, clothing creases, and expressive faces. "
        "Muted backgrounds with saturated foreground characters \u2014 "
        "best Genesis art reserves bright colors for gameplay-critical elements. "
        "Dark atmospheric palettes emerge (Shinobi III spotlight technique). "
        "Parallax scrolling creates multi-layered depth. "
        "Style: Streets of Rage 2, Sonic 2, Gunstar Heroes, Thunder Force IV, "
        "Shinobi III, Phantasy Star IV."
    ),
    outline_hint=(
        "Dark chromatic outline, not always pure black. "
        "Dark navy, dark brown, or dark purple chosen to complement the sprite's palette."
    ),
    pixel_scale=None,
    max_cleanup_colors=12,
)

_GENESIS_ERA_LATE = EraPromptData(
    label="late mastery Sega Genesis 16-bit style (1994-1996), pre-rendered sprites, peak palette tricks",
    year_range="1994-1996",
    reference_games="Comix Zone, Vectorman, Castlevania: Bloodlines, Phantasy Star IV",
    style_ref="Style: Comix Zone, Vectorman, Castlevania: Bloodlines Genesis sprites. Pre-rendered gloss, peak palette exploitation.",
    tile_ref="Style: Comix Zone comic panel tiles, Castlevania: Bloodlines gothic stonework, Vectorman industrial backgrounds.",
    era_hints=(
        "Late-mastery Sega Genesis pixel art, 1994-1996 \u2014 developers squeezing "
        "every last drop from the hardware. Two distinct visual styles coexist: "
        "hand-crafted pixel art at its peak (Comix Zone, Castlevania: Bloodlines) "
        "and pre-rendered 3D sprites (Vectorman, Toy Story). "
        "Hand-crafted: full 15 colors used with expert hue shifting, "
        "every palette slot purposeful. Complex dithering for atmospheric gradients. "
        "Gothic palettes with torchlight accent colors (Castlevania: Bloodlines). "
        "Comic-book flat fills with halftone dithering (Comix Zone). "
        "Pre-rendered: smooth glossy surfaces, soft color banding from quantization, "
        "dramatic directional lighting and specular highlights. "
        "Both styles push the 4-palette system to its limits with palette cycling "
        "for water shimmer, lava pulse, and lightning effects. "
        "Style: Comix Zone, Vectorman, Castlevania: Bloodlines, Phantasy Star IV, "
        "Ristar, The Story of Thor."
    ),
    outline_hint=(
        "Dark chromatic outline matched to sprite palette \u2014 dark navy for cool palettes, "
        "dark brown for warm palettes. Pure black used only for comic-book style (Comix Zone). "
        "Outline may thin on highlight side (top-left) for advanced light integration."
    ),
    pixel_scale=None,
    max_cleanup_colors=15,
)


# ---------------------------------------------------------------------------
# Genesis terrain color hints (FLUX)
# ---------------------------------------------------------------------------

_GENESIS_TERRAIN_COLOR_HINTS: list[tuple[list[str], str]] = [
    (["grass", "field", "meadow", "lawn", "turf"],
     "IMPORTANT: Use rich saturated GREENS with 2-3 shade gradient. "
     "Checkerboard dithering between light and dark green for lush depth. "
     "Like Sonic Green Hill Zone rolling checkerboard hills."),
    (["water", "ocean", "sea", "lake", "river", "pond"],
     "IMPORTANT: Deep BLUE to cyan gradient with dithered transitions. "
     "Light ripple highlights on dark water surface. "
     "Palette cycling would animate this on real hardware."),
    (["sand", "desert", "beach", "dune"],
     "IMPORTANT: Warm TAN and YELLOW with subtle dithered shadow. "
     "3-step gradient from bright sand highlights to warm brown shadow. "
     "Like Golden Axe desert stages."),
    (["stone", "rock", "cave", "dungeon", "castle", "fortress"],
     "IMPORTANT: Dark GRAY to purple-gray atmospheric palette. "
     "Gothic stonework with warm amber torchlight accent color. "
     "Like Castlevania: Bloodlines castle interiors."),
    (["brick", "wall", "masonry"],
     "IMPORTANT: BROWN and DARK RED with visible mortar lines. "
     "3-step brick shading: highlight face, mid body, dark mortar."),
    (["wood", "plank", "floor", "deck", "log", "timber"],
     "IMPORTANT: Rich BROWNS with visible wood grain pattern. "
     "Dithered grain texture between light and dark brown bands."),
    (["snow", "ice", "frost", "winter", "tundra"],
     "IMPORTANT: WHITE and LIGHT BLUE with subtle blue shadow dithering. "
     "Cool-shifted shadows for icy atmosphere."),
    (["lava", "magma", "fire", "volcano"],
     "IMPORTANT: RED, ORANGE, and YELLOW with bright hot-spot highlights. "
     "Palette cycling would animate glow on real hardware."),
    (["dirt", "mud", "earth", "soil", "ground"],
     "IMPORTANT: Rich BROWNS with dithered texture. "
     "Dark brown shadow, mid brown body, warm highlight."),
    (["metal", "steel", "iron", "mech", "robot", "factory"],
     "IMPORTANT: Cool GRAY ramp with specular highlight. "
     "Sharp contrast between dark shadow and bright specular point. "
     "Like Vectorman industrial environments."),
]


# ---------------------------------------------------------------------------
# Genesis palette rules (MCP)
# ---------------------------------------------------------------------------

_GENESIS_PALETTE_RULES: dict[str, str] = {
    "early": """\
PALETTE RULES (Sega Genesis \u2014 9-bit RGB, 4 palettes x 16 colors):
- You have {n} colors from the Genesis 9-bit color space (512 possible colors).
- All RGB values MUST snap to Genesis hardware steps: 0, 36, 73, 109, 146, 182, 219, 255 per channel.
- Color 0 is transparent for sprites. You have 15 usable color slots.
- {c0} ({r0}): heavy black outline, 1px around entire sprite. Inherited NES convention.
- {c1} ({r1}): main body fill \u2014 largest area, 40-50% of opaque pixels.
- {c2} ({r2}): secondary fill \u2014 skin, cape, or contrasting clothing element.
{extra_color}\
- Early Genesis palettes are simple: artists rarely use more than 10-12 colors.
  Unused palette slots are acceptable. Do not force filler colors.
- Palette is dedicated to this character \u2014 it does NOT share with backgrounds.
  On real hardware, backgrounds use separate palette rows from CRAM.""",

    "mid": """\
PALETTE RULES (Sega Genesis \u2014 9-bit RGB, 4 palettes x 16 colors):
- You have {n} colors from the Genesis 9-bit color space (512 possible colors).
- All RGB values MUST snap to Genesis hardware steps: 0, 36, 73, 109, 146, 182, 219, 255 per channel.
- Color 0 is transparent. 15 usable slots for this sprite's dedicated palette.
- {c0} ({r0}): dark chromatic outline. NOT pure black \u2014 use dark navy, brown, or purple
  that complements the sprite's color scheme.
- {c1} ({r1}): main body midtone \u2014 largest fill area, 35-45% of opaque pixels.
- {c2} ({r2}): body shadow \u2014 bottom-right edges, undersides, folds. 15-20% of body area.
- {c3} ({r3}): body highlight \u2014 top-left convex edges. 5-10% of body area.
{extra_color}\
- Build 3-4 step shading ramps: shadow \u2192 midtone \u2192 highlight within each material region.
- Skin tones need their own 2-3 color gradient: dark skin shadow, mid skin, skin highlight.
- The character owns this full palette row. Background tiles use different CRAM rows.
- Dithering (2x2 checkerboard) is valid between adjacent ramp colors for smooth gradients.""",

    "late": """\
PALETTE RULES (Sega Genesis \u2014 9-bit RGB, 4 palettes x 16 colors):
- You have {n} colors from the Genesis 9-bit color space (512 possible colors).
- All RGB values MUST snap to Genesis hardware steps: 0, 36, 73, 109, 146, 182, 219, 255 per channel.
- Color 0 is transparent. All 15 remaining slots should be purposeful \u2014 no wasted entries.
- OUTLINE: {c0} ({r0}) \u2014 dark chromatic color matched to palette temperature.
  Warm palette \u2192 dark brown. Cool palette \u2192 dark navy. Comic style \u2192 pure black.
- BODY RAMP (primary material \u2014 armor, robe, main clothing):
  * {c1} (body_shadow): deepest shadow on body. Bottom-right edges, undersides.
  * {c2} (body_midtone): largest fill area. Base color of the main material.
  * {c3} (body_highlight): top-left convex edges, specular points. Single-pixel placements.
- ACCENT RAMP (secondary material \u2014 e.g. skin, cape, boots, accessories):
  * {c4} (accent_shadow): shadow on secondary regions.
  * {c5} (accent_midtone): secondary region fill.
  * {c6} (accent_highlight): bright accent detail \u2014 gem, buckle, eye glint.
{extra_color}\
- Hue-shifted ramps: shadows shift TOWARD BLUE/PURPLE, highlights shift TOWARD YELLOW/WHITE.
  A red armor's shadow is dark purple-red; its highlight is orange-red. NOT just lighter/darker red.
- Dithering: 2x2 or 4x4 checkerboard between adjacent ramp colors for gradient simulation.
  Valid for large surfaces (armor plates, capes, sky areas). Avoid on surfaces smaller than 4x4px.
- This palette is the character's dedicated CRAM row. Backgrounds and UI use separate rows.
{color_list}""",
}


# ---------------------------------------------------------------------------
# Genesis color theory rules (MCP)
# ---------------------------------------------------------------------------

_GENESIS_COLOR_THEORY_RULES: dict[str, str] = {
    "early": """\
COLOR THEORY (Genesis):
- Light source is TOP-LEFT (standard convention, inherited from NES era).
- Genesis unlocks free RGB \u2014 but early devs often use NES-like flat fills.
  Colors are brighter and more saturated than NES but shading ramps are minimal (2 steps max).
- Pick high-contrast primary colors. Avoid subtle tonal shifts \u2014 early Genesis art is bold and simple.
- Black outlines separate all elements. Outline is the primary readability tool.
- Characters use a dedicated palette. Background colors should NOT appear in the character palette.""",

    "mid": """\
COLOR THEORY (Genesis):
- Light source is TOP-LEFT. All shading follows this single directional source.
- HUE SHIFTING (the key technique that separates good Genesis art from flat art):
  * Shadows: shift hue TOWARD BLUE/PURPLE, lower value and saturation slightly.
    A red tunic's shadow is dark burgundy-purple, NOT dark red.
    A blue armor's shadow is deep navy-violet, NOT dark blue.
  * Highlights: shift hue TOWARD YELLOW/WHITE, raise value.
    A red tunic's highlight is orange-red, NOT pink.
    A blue armor's highlight is cyan-white, NOT light blue.
  * This makes colors feel luminous and dimensional, not flat.
- DITHERING FOR GRADIENTS:
  * 2x2 checkerboard between adjacent ramp colors simulates intermediate tones.
  * At Genesis resolution (320x224), dithering blends optically at normal viewing distance.
  * Use for: large armor plates, flowing capes, sky gradients, skin shading on big sprites.
  * Avoid on surfaces smaller than 4x4 pixels \u2014 reads as noise, not gradient.
- ATMOSPHERIC DARK PALETTE TECHNIQUE (Shinobi III style):
  * Background uses darkest palette entries (near-black blues, purples, dark greens).
  * Character palette uses vibrant saturated colors.
  * Result: spotlight effect \u2014 character pops against dark environment without hardware lighting.
  * Reserve brightest, most saturated colors for the player character and interactive elements.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: lighting from all sides. Always shade from top-left only.
  * BANDING: visible parallel color bands. Stagger transitions with 1px offsets.
  * NES FLATNESS: using only 2 shades when you have 15 colors available. Build proper ramps.""",

    "late": """\
COLOR THEORY (Genesis):
- Light source is TOP-LEFT. All shading decisions follow this.
- ADVANCED HUE SHIFTING (critical for late-era quality):
  * Every shading ramp is a hue arc, not a straight value ramp.
  * Shadows: shift toward BLUE/PURPLE and desaturate slightly.
  * Midtones: the purest, most saturated version of the color.
  * Highlights: shift toward YELLOW/WHITE and slightly desaturate toward pastel.
  * Example 3-step red ramp: #6D0024 (dark purple-red) \u2192 #DB0000 (pure red) \u2192 #DB6D00 (orange-red highlight).
  * Example 3-step blue ramp: #240049 (deep violet-blue) \u2192 #0000DB (pure blue) \u2192 #006DDB (cyan-blue highlight).
- DITHERING FOR GRADIENT SIMULATION:
  * 2x2 checkerboard: standard method, blends well at Genesis resolution.
  * 4x4 ordered: smoother perceived gradient, good for large surfaces and sky.
  * Halftone pattern: specific to comic-book style (Comix Zone). Regular dot grid simulates print.
  * Threshold: dithering on surfaces smaller than 4x4px produces noise, not texture. Avoid.
- ATMOSPHERIC PALETTE DESIGN:
  * Gothic: dark purple-gray backgrounds, warm amber/orange torchlight accents (Castlevania: Bloodlines).
  * Industrial: cool blue-gray backgrounds, hot red-orange hazard accents (Vectorman).
  * Comic: heavy black outlines, flat high-saturation fills, halftone dither mid-tones (Comix Zone).
  * Always: muted/dark backgrounds, bright/saturated foreground characters.
- MATERIAL RENDERING with 16-color constraint:
  * METAL: high contrast, sharp transitions between 3-4 steps. Bright specular highlight point.
  * FABRIC: softer transitions, visible fold shadows. Dithered boundaries between ramp steps.
  * SKIN: warm ramp (3 colors minimum). Shadow under chin/arms, highlight on forehead/nose.
  * GLASS/GEM: transparent color at edge, bright saturated center, white specular dot.
- ANTI-PATTERNS TO AVOID:
  * PILLOW SHADING: lighting from all sides. Always top-left only.
  * BANDING: parallel color bands. Break up with staggered offsets.
  * WASTED PALETTE: using only 8 of 15 available colors. Every slot should be purposeful.
  * FLAT RAMPS: going from dark red to light red without hue shift. Always arc the hue.""",
}


# ---------------------------------------------------------------------------
# Genesis tool configs (MCP)
# ---------------------------------------------------------------------------

_GENESIS_TOOL_CONFIGS: dict[str, dict] = {
    "early": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_pixels",
            "draw_circle", "draw_line", "apply_outline",
        ],
        "blacklist": _GLOBAL_BLACKLIST + [
            "draw_with_dither", "apply_shading",
        ],
        "rules": """\
TOOL RULES (Genesis \u2014 early era):
USE: create_canvas, set_palette, draw_rectangle (filled=true for body blocks),
  draw_circle (rounded forms like the head), draw_pixels (detail placement),
  draw_line (long thin elements such as belt lines, or held-item shafts when the subject names them), apply_outline (color=#000000, thickness=1)
AVOID: draw_with_dither (early Genesis art uses flat fills, not dithered gradients),
  apply_auto_shading (produces smooth gradients foreign to this era),
  suggest_antialiasing (too refined for early Genesis), apply_shading
Canvas size: 24x32 to 32x40 typical. Larger sprites (48x48+) are mid/late era.
Build with rectangles and circles, refine with draw_pixels. Outline applied LAST.""",
    },
    "mid": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES (Genesis \u2014 mid era):
USE: create_canvas, set_palette, draw_rectangle (body scaffolding), draw_circle (rounded forms like the head),
  draw_pixels (PRIMARY tool \u2014 70%+ of drawing), draw_line (long thin elements such as belt or structural lines, or held-item shafts when the subject names them),
  draw_contour (complex body curves), apply_outline (dark chromatic color, NOT always black, thickness=1)
MAYBE: draw_with_dither \u2014 bayer_2x2 or bayer_4x4 ONLY, for large surfaces (armor plates, capes, backgrounds).
  NEVER dither on surfaces smaller than 4x4 pixels.
AVOID: apply_auto_shading (adds non-Genesis gradient smoothing), suggest_antialiasing (too refined)
Canvas size: 32x48 for characters, 48x48+ for bosses (metasprite composition).
All shading is manual via draw_pixels. Build ramps with hue-shifted colors.
BROKEN DITHER PATTERNS (silently produce solid fills \u2014 do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
    "late": {
        "whitelist": [
            "create_canvas", "set_palette", "draw_rectangle", "draw_circle",
            "draw_pixels", "draw_line", "apply_outline", "draw_contour",
            "draw_with_dither",
        ],
        "blacklist": _GLOBAL_BLACKLIST,
        "rules": """\
TOOL RULES (Genesis \u2014 late era):
USE: create_canvas, set_palette, draw_rectangle (scaffolding), draw_circle (scaffolding),
  draw_pixels (PRIMARY tool \u2014 70%+ of drawing), draw_line (structural lines),
  draw_contour (complex shapes, comic-style outlines),
  apply_outline (dark chromatic color matched to palette, thickness=1),
  draw_with_dither (bayer_2x2, bayer_4x4, bayer_8x8, floyd_steinberg \u2014 for gradients on large surfaces)
AVOID: apply_auto_shading (produces non-Genesis smooth gradients), suggest_antialiasing
Canvas size: 32x48 for characters, 48x48 to 64x64 for bosses.
All shading is manual via draw_pixels. Dithering supplements ramps for gradient simulation.
Late Genesis exploits every palette slot \u2014 all 15 colors should be purposeful.
BROKEN DITHER PATTERNS (silently produce solid fills \u2014 do NOT use):
  checkerboard, grass, water, stone, cloud, brick, dots, diagonal, cross, noise, horizontal_lines, vertical_lines""",
    },
}


# ---------------------------------------------------------------------------
# Genesis view rules (MCP)
# ---------------------------------------------------------------------------

_GENESIS_VIEW_RULES: dict[str, str] = {
    "side": """\
VIEW: Side profile (facing right \u2014 standard convention).
- Character faces right. Leading arm/leg slightly forward, trailing slightly back.
- Anything held (only when the subject names a held item) goes in the leading (right) hand, visible on the right side.
- Shadow colors on the back (left) edges and underside of the body.
- Use the full canvas — sprite content should span from top rows to bottom rows.
- Show muscle definition, clothing creases, and any named accessory detail where canvas size allows.
- Depth: near arm overlaps torso, far arm partially hidden. Near leg forward.""",

    "front": """\
VIEW: Front facing.
- Bilateral symmetry: left half mirrors right half (within 1px tolerance).
- Arms equidistant from center. A held item (when the subject names one) may break symmetry.
- Shadow colors on bottom edges and undersides of features.
- Eyes at same height, same size, centered on face. Eyes 2-3px wide when canvas allows.
- Show body volume: wider at shoulders, narrower at waist.""",

    "top-down": """\
VIEW: Top-down / overhead (RPG style).
- Head is a circle/oval filling top 40-50% of canvas (or headwear if the subject names one).
- Shoulders visible as wider rectangle/oval below head.
- Items visible from above: hat or headwear dominant; held items extend to the side and capes drape behind only when the subject names them.
- Shadow on bottom edge of head and body.
- Used in Genesis RPGs (Phantasy Star) and strategy games.""",

    "3/4": """\
VIEW: 3/4 perspective (facing right and slightly toward viewer).
- Right side of body 1-2px wider than left (foreshortening).
- Right arm more visible than left. Right leg forward.
- Shadow on left edges (farther from viewer) and bottom edges.
- Face shows both eyes but right eye 1px larger or closer to center.
- Common in Genesis beat-em-ups (Streets of Rage) \u2014 show body depth.""",
}


# ---------------------------------------------------------------------------
# Genesis few-shot examples (MCP)
# ---------------------------------------------------------------------------

_GENESIS_FEW_SHOT_EXAMPLES: dict[str, str] = {
    # --- Default examples at 16x16 (most common canvas size) ---
    "early": """\
REFERENCE EXAMPLE \u2014 Early Genesis 16x16 humanoid character (quality benchmark, do not copy):
Palette: #000000 (outline), #006D00 (dark green), #00B600 (mid green),
  #B66D00 (skin shadow), #DB9200 (skin mid)
Key structure: 1px black outline. Sprite fills rows 0-15 (full canvas height).
  Head 5x5 at rows 0-4: skin mid fill, skin shadow on right edge. Eyes 2px dark at row 2.
  Headwear (cap, hood, helmet \u2014 depends on the subject): dark green top 2 rows of head, mid green highlight stripe.
  Torso 7x5 at rows 5-9: dark green body, mid green on left shoulder.
  Arms: 2px wide from torso sides, rows 5-9.
  Legs: two 3x4 columns at rows 10-13, 1px gap. Dark green with mid green front edge.
  Feet: 4px wide at rows 14-15, footwear shape.
  Optional held item (only when the subject names one): 1px wide extending 3px above head on right side.
Total: ~95-100 opaque pixels (varies with held item). Bold primary colors, NES-influenced but on Genesis hardware.
CRITICAL: content spans row 0 to row 15 \u2014 the FULL 16px height.""",

    "mid": """\
REFERENCE EXAMPLE \u2014 Mid Genesis 16x16 humanoid character (quality benchmark, do not copy):
Palette: #490049 (outline/deep purple), #6D006D (body shadow), #920092 (body midtone),
  #B600B6 (body highlight), #6D4900 (skin shadow), #B67300 (skin mid), #DBDBDB (held-item color)
Key structure: chromatic purple outline. Sprite fills rows 0-15 (full canvas height).
  Head 5x4 at rows 0-3: skin 2-step (shadow right, mid left). Eyes 2px at row 1.
  Torso 8x5 at rows 4-8: body midtone fill, shadow on right edge, highlight on left shoulder.
  Arms: 2px wide each side, rows 4-8. Muscle separation via shadow/midtone boundary.
  Belt: 1px accent at row 9.
  Legs: two 3x4 columns at rows 9-12, body midtone with shadow on inner edges.
  Feet: 4px wide at rows 13-15, footwear shape distinct.
  Optional held item (only when the subject names one): 1px wide held-item color from row 0 to row 10 on right side.
Total: ~95-110 opaque pixels (varies with held item). Hue-shifted purple ramp reads as one material.
CRITICAL: content spans row 0 to row 15 \u2014 the FULL 16px height.""",

    "late": """\
REFERENCE EXAMPLE \u2014 Late Genesis 16x16 humanoid character with hard-surface garment (quality benchmark, do not copy):
Palette: #24006D (outline/dark indigo), #490092 (armor shadow), #6D24B6 (armor midtone),
  #9249DB (armor highlight), #6D4900 (skin shadow), #B67300 (skin mid),
  #929292 (hard-surface gray), #FFDB00 (gold accent)
Key structure: dark indigo chromatic outline, thins on highlight edges. Full canvas height.
  Head 5x4 at rows 0-3: armor shadow headwear, skin mid face visible at rows 1-2.
  Armor highlight pixel on head top-left.
  Torso 8x5 at rows 4-8: armor midtone dominant, shadow on right, highlight on left shoulder.
  Gold accent at belt (row 9), 2px wide.
  Arms: 2px wide, rows 4-8. Forearm detail via shadow/midtone split.
  Legs: two 3x4 columns at rows 9-12, armor ramp with dithered boundary.
  Feet: 4px wide at rows 13-15, armored footwear with hard-surface accent.
  Optional held item (only when the subject names one): hard-surface 1px from row 0 to row 12 on right. Gold accent pixel at the topmost or grip point.
Total: ~100-115 opaque pixels (varies with held item). Hue-shifted armor ramp (indigo→purple→lavender).
CRITICAL: content spans row 0 to row 15 \u2014 the FULL 16px height.""",

    # --- Size-specific examples for larger canvases ---
    "early_24x32": """\
REFERENCE EXAMPLE \u2014 Early Genesis 24x32 humanoid character with hard-surface garment (quality benchmark, do not copy):
Palette: #000000 (outline), #006D00 (dark green garment), #00B600 (mid green garment),
  #00DB49 (green highlight), #B66D00 (skin shadow), #DB9200 (skin mid), #FFDB00 (gold accent)
Key structure: 1px black outline around entire sprite \u2014 heavy, NES-inherited.
  Head 6x6 at rows 2-7, skin mid fill with skin shadow on right side. Eyes 2px dark.
  Headwear: 8x4 dark green with mid green highlight stripe at rows 0-3.
  Torso 10x8 at rows 8-15: dark green garment body, mid green left shoulder highlight.
  Belt: 1px gold accent line at row 16.
  Legs 4x8 each at rows 17-24: dark green with mid green on front-facing edges.
  Optional held item (only when the subject names one): 2px wide, gold accent from row 4 to row 20, extending right.
  Shading is minimal \u2014 2 step ramp (dark/mid green), not yet full Genesis capability.
Total: ~180-200 opaque pixels (varies with held item). Readable silhouette, bright primary colors, NES-influenced proportions.""",

    "mid_32x32": """\
REFERENCE EXAMPLE \u2014 Mid Genesis 32x32 humanoid character with stealth-style garment (quality benchmark, do not copy):
Palette: #240049 (outline/deep purple), #490049 (body shadow), #6D006D (body midtone),
  #920092 (body highlight), #B6006D (accent shadow), #DB0049 (accent midtone),
  #FF2400 (accent highlight), #6D4900 (skin shadow), #B67300 (skin mid),
  #929292 (held-item shadow), #B6B6B6 (held-item mid), #DBDBDB (held-item highlight)
Key structure: dark purple chromatic outline (NOT black). Fills 28+ of 32 rows.
  Head 8x7 at rows 1-7: skin 2-step gradient, shadow right, mid left.
  Eyes: 2px red accent. Optional face covering (mask, scarf, beard \u2014 depends on the subject) in body midtone over the lower face.
  Torso 14x8 at rows 8-15: midtone fill, shadow on right edges, highlight on left shoulder.
  Waist accent (sash, belt, cummerbund): 3-color ramp diagonal across waist at rows 16-17.
  Arms 4x9 each, muscle definition via shadow/midtone boundary.
  Optional held item (only when the subject names one): 2px wide from row 0 to row 22, 3-step gray ramp.
  Legs 6x10 each at rows 18-27: midtone with shadow on inner edges.
  Feet at rows 28-30. Content spans row 0 to row 30 minimum.
Total: ~320-350 opaque pixels (varies with held item). Full hue-shifted ramps. Materials read distinctly.""",

    "mid_32x48": """\
REFERENCE EXAMPLE \u2014 Mid Genesis 32x48 humanoid character with stealth-style garment (quality benchmark, do not copy):
Palette: #240049 (outline/deep purple), #490049 (body shadow), #6D006D (body midtone),
  #920092 (body highlight), #B6006D (accent shadow), #DB0049 (accent midtone),
  #FF2400 (accent highlight), #6D4900 (skin shadow), #B67300 (skin mid),
  #DBA600 (skin highlight), #929292 (held-item shadow), #B6B6B6 (held-item mid),
  #DBDBDB (held-item highlight), #FF0000 (eye accent), #492400 (footwear leather)
Key structure: dark purple chromatic outline (NOT black).
  Head 8x8 at rows 2-9: skin 3-step gradient \u2014 shadow right/bottom, mid center, highlight top-left.
  Eyes: 2px red accent on dark skin shadow. Optional face covering (mask, scarf, beard) over lower face in body midtone.
  Torso 14x10 at rows 10-19: body midtone fill, body shadow on right edges and folds,
  body highlight as single pixels on left shoulder and chest plate edge.
  Waist accent (sash, belt): diagonal 3-color ramp across waist \u2014 shadow where it tucks, midtone face, highlight edge.
  Arms 4x12 each, visible muscle definition via shadow/midtone boundary.
  Optional held item (only when the subject names one): 3-step gray ramp, 2px wide from row 0 to row 30 \u2014 shadow on flat, highlight on edge.
  Legs 6x14 each: body midtone with shadow on inner edges, footwear leather at feet.
  Dithered shadow under body: 2x2 checkerboard of outline color and body shadow.
Total: ~410-450 opaque pixels (varies with held item). Full hue-shifted ramps. Materials read differently (fabric vs skin vs hard accent).""",

    "late_32x32": """\
REFERENCE EXAMPLE \u2014 Late Genesis 32x32 humanoid character with hard-surface garment + trailing fabric (quality benchmark, do not copy):
Palette: #24006D (outline/dark indigo), #490092 (armor shadow), #6D24B6 (armor midtone),
  #9249DB (armor highlight), #240000 (fabric shadow), #6D0024 (fabric midtone),
  #B60049 (fabric highlight), #6D4900 (skin shadow), #B67324 (skin mid),
  #494949 (hard-surface shadow), #929292 (hard-surface mid), #DBDBDB (hard-surface highlight),
  #FFDB00 (gold accent), #FF0000 (gem accent)
Key structure: dark indigo chromatic outline, thins on highlight edges. Fills 28+ of 32 rows.
  Headwear 8x6 rows 0-5: armor 3-step ramp with hue shift. Gold accent on front face.
  Face through opening: skin shadow lower, skin mid center.
  Trailing fabric (cape, scarf \u2014 depends on the subject): flows from shoulders, 3-step ramp in folds behind body.
  Torso 14x8 rows 6-13: armor midtone dominant. Shadow right, highlight left shoulder.
  Arms 4x9 each with forearm detail (rows 6-14).
  Gold belt at row 14, 2px wide.
  Legs 6x10 at rows 15-24: armor ramp with dithered shadow/midtone boundary.
  Feet at rows 25-28. Optional held item (only when the subject names one): hard-surface 2px from row 0 to row 22, specular highlight at top, gem accent at grip.
Total: ~370-400 opaque pixels (varies with held item). Expert hue shifting. Multiple materials distinct.""",

    "late_32x48": """\
REFERENCE EXAMPLE \u2014 Late Genesis 32x48 humanoid character with ornate hard-surface garment + trailing fabric (quality benchmark, do not copy):
Palette: #24006D (outline/dark indigo), #490092 (armor shadow), #6D24B6 (armor midtone),
  #9249DB (armor highlight), #240000 (fabric shadow/dark burgundy), #6D0024 (fabric midtone),
  #B60049 (fabric highlight), #6D4900 (skin shadow), #B67324 (skin mid), #DBAB49 (skin highlight),
  #494949 (hard-surface shadow), #929292 (hard-surface mid), #DBDBDB (hard-surface highlight/specular),
  #FFDB00 (gold accent), #FF0000 (gem accent)
Key structure: dark indigo chromatic outline \u2014 thins to 0px on top-left highlight edges.
  Headwear 10x8 rows 0-7: armor 3-step ramp with hue shift (shadow is blue-purple,
  midtone is purple, highlight is lavender). Gold accent emblem on front face.
  Face visible through opening: skin shadow lower, skin mid center, skin highlight on forehead.
  Trailing fabric (cape, robe train, long scarf \u2014 depends on the subject): flows from shoulders behind body. Fabric 3-step ramp: dark burgundy shadow in folds,
  red-brown midtone face, bright highlight on outer edges catching light.
  Torso 16x12: armor midtone dominant. Shadow on right side and under chest plate.
  Single-pixel highlight on left shoulder peak and chest plate upper edge.
  Optional held item (only when the subject names one): hard-surface 3-step ramp, 2px wide. Specular highlight (brightest color) at the topmost or grip pixel.
  Red gem accent on chest or item \u2014 single focal pixel.
  Legs 8x14 each: armor ramp with dithered boundary between shadow and midtone on large surfaces.
  Gold belt buckle: 2x2 gold accent with highlight pixel.
  2x2 dithered transitions between armor shadow and midtone on thigh plates.
Total: ~470-500 opaque pixels (varies with held item). Expert hue shifting on every ramp. Comic/gothic atmosphere.
  Multiple material types rendered distinctly (armor, fabric, skin, hard-surface accent, gem).""",
}


# ---------------------------------------------------------------------------
# Genesis ConsolePromptData
# ---------------------------------------------------------------------------

GENESIS_PROMPT_DATA = ConsolePromptData(
    name="genesis",
    display_name="Sega Genesis",
    default_era="mid",
    eras={
        "early": _GENESIS_ERA_EARLY,
        "mid": _GENESIS_ERA_MID,
        "late": _GENESIS_ERA_LATE,
    },
    terrain_color_hints=_GENESIS_TERRAIN_COLOR_HINTS,
    palette_rules=_GENESIS_PALETTE_RULES,
    color_theory_rules=_GENESIS_COLOR_THEORY_RULES,
    tool_configs=_GENESIS_TOOL_CONFIGS,
    view_rules=_GENESIS_VIEW_RULES,
    few_shot_examples=_GENESIS_FEW_SHOT_EXAMPLES,
    mood_palettes=None,
    palette_presets=None,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

_REGISTRY: dict[str, ConsolePromptData] = {
    "nes": NES_PROMPT_DATA,
    "gb_dmg": GB_DMG_PROMPT_DATA,
    "gb": GB_DMG_PROMPT_DATA,
    "game_boy": GB_DMG_PROMPT_DATA,
    "gb_pocket": GB_POCKET_PROMPT_DATA,
    "c64": C64_PROMPT_DATA,
    "c64_hires": C64_PROMPT_DATA,
    "commodore_64": C64_PROMPT_DATA,
    "gbc": GBC_PROMPT_DATA,
    "game_boy_color": GBC_PROMPT_DATA,
    "snes": SNES_PROMPT_DATA,
    "super_nintendo": SNES_PROMPT_DATA,
    "pc_engine": PCE_PROMPT_DATA,
    "turbografx": PCE_PROMPT_DATA,
    "turbografx_16": PCE_PROMPT_DATA,
    "genesis": GENESIS_PROMPT_DATA,
    "mega_drive": GENESIS_PROMPT_DATA,
}

# Profile-only modes: these have a pixelization/palette profile but NO
# generation prompt data by design — generation endpoints reject them with a
# clean 422 (see is_generation_supported and test_byok_aseprite's
# TestUnsupportedConsole). Adding prompt-data support for a mode is a product
# decision (prompt text must describe the mode's constraints), not an alias fix.
_PROFILE_ONLY_MODES = frozenset({"c64_multicolor", "snes_mode1", "snes_mode7"})


def _normalize_console(console: str) -> str:
    """Normalize a console name for registry lookup.

    Mirrors the normalization in ``console_profile.get_profile`` so that any
    string accepted by ``get_profile`` (case-insensitive, spaces/dashes →
    underscores) is also accepted here.  This closes the alias-mismatch bug
    documented in docs/PIXEL-GEN-STUDY-2026-07-04.md.
    """
    return console.lower().replace(" ", "_").replace("-", "_")


def get_prompt_data(console: str = "nes") -> ConsolePromptData:
    key = _normalize_console(console)
    if key not in _REGISTRY:
        raise NotImplementedError(
            f"Prompt data for console '{console}' not yet available. "
            f"Currently supported: {sorted(set(p.name for p in _REGISTRY.values()))}"
        )
    return _REGISTRY[key]


def is_generation_supported(console: str) -> bool:
    """True if the console has generation prompt data (not just a palette
    profile). Some consoles (e.g. c64_multicolor) have a ConsoleProfile for
    pixelization but no prompt data yet — those must be rejected at the
    generation endpoints with a clean 422 rather than 500ing mid-pipeline.
    """
    return _normalize_console(console) in _REGISTRY

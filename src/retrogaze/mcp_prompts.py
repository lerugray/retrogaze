"""
MCP-specific prompt builder for Retrogaze Aseprite generation.

Produces structured system/user prompts for Claude API driving pixel-mcp.
Parallel to prompts.py (FLUX) — same interface, completely different output.

FLUX prompts steer a dumb image model with aesthetic vibes.
MCP prompts give Claude specific drawing RULES: highlight placement,
shadow direction, palette usage patterns, body proportions, tool guidance.
"""

from __future__ import annotations

from .palette import (
    get_mood_palette,
    suggest_palette_roles,
    NES_PALETTE_RGB,
    rgb_to_lab,
)
from .console_prompt_data import get_prompt_data


# ---------------------------------------------------------------------------
# Era constraints
# ---------------------------------------------------------------------------

_ERA_CONSTRAINTS: dict[str, dict] = {
    "retro": {
        "label": "Pre-NES Arcade (1978-1983)",
        "year_range": "1978-1983",
        "default_size": (8, 8),
        "max_colors": 3,
        "outline_default": "No",
        "reference_games": "Space Invaders, Pac-Man, Donkey Kong (1981)",
    },
    "early": {
        "label": "Early NES (1983-1984)",
        "year_range": "1983-1984",
        "default_size": (12, 16),
        "max_colors": 3,
        "outline_default": "Black",
        "reference_games": "Donkey Kong (1983), Excitebike, Ice Climber",
    },
    "mid": {
        "label": "Golden NES (1985-1987)",
        "year_range": "1985-1987",
        "default_size": (16, 16),
        "max_colors": 4,
        "outline_default": "Black",
        "reference_games": "Super Mario Bros, Mega Man, Castlevania",
    },
    "late": {
        "label": "Late NES (1987-1993)",
        "year_range": "1987-1993",
        "default_size": (16, 16),
        "max_colors": 6,
        "outline_default": "Dark",
        "reference_games": "Kirby's Adventure, Castlevania III, Little Samson",
    },
}


def _era_constraints(era: str, console: str = "nes") -> dict:
    """Return constraint dict for the given era and console."""
    # Try console-specific data first, fall back to module-level NES dicts
    try:
        pd = get_prompt_data(console)
        if era in pd.eras:
            era_data = pd.eras[era]
            nes_defaults = _ERA_CONSTRAINTS.get(era, _ERA_CONSTRAINTS["mid"])
            max_colors = nes_defaults["max_colors"]
            if pd.name in {"gb_dmg", "gb_pocket"}:
                from .console_profile import get_profile

                profile = get_profile(console)
                if profile.master_palette_hex is not None:
                    max_colors = min(max_colors, len(profile.master_palette_hex))
            return {
                "label": era_data.label,
                "year_range": era_data.year_range,
                "default_size": nes_defaults["default_size"],
                "max_colors": max_colors,
                "outline_default": nes_defaults["outline_default"],
                "reference_games": era_data.reference_games,
            }
    except NotImplementedError:
        pass
    return _ERA_CONSTRAINTS.get(era, _ERA_CONSTRAINTS["mid"])


# ---------------------------------------------------------------------------
# Palette resolution
# ---------------------------------------------------------------------------

def _hex_to_rgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _rgb_to_hex(r: int, g: int, b: int) -> str:
    return f"#{r:02X}{g:02X}{b:02X}"


def _luminance(hex_color: str) -> float:
    r, g, b = _hex_to_rgb(hex_color)
    return rgb_to_lab(r, g, b)[0]


# ---------------------------------------------------------------------------
# Subject-keyword → mood routing
# ---------------------------------------------------------------------------
# When palette_mood is "auto", we scan the description for material/theme
# keywords and route to the best-matching mood. This prevents mismatches
# like "golden chalice" getting red tones from the default auto palette.

_MOOD_KEYWORDS: dict[str, list[str]] = {
    "warm": [
        "fire", "flame", "lava", "magma", "infernal", "demon", "hell",
        "volcanic", "ember", "blaze", "torch", "candle", "phoenix",
        "crimson", "scarlet", "ruby", "garnet", "blood",
        "red", "orange", "magenta", "pink",
    ],
    "cool": [
        "ice", "frost", "frozen", "crystal", "gem", "gemstone", "sapphire",
        "diamond", "water", "ocean", "aqua", "magic", "arcane", "mana",
        "mystic", "mystical", "ethereal", "spirit", "spectral",
        "amethyst", "opal", "moonstone",
        "blue", "cyan", "teal", "indigo", "violet", "purple",
    ],
    "earth": [
        "gold", "golden", "bronze", "copper", "iron", "steel", "metal",
        "metallic", "stone", "rock", "clay", "wood", "wooden", "tree",
        "forest", "bone", "sand", "sandy", "desert", "ancient", "rust",
        "rusted", "coin", "treasure", "chalice", "goblet", "crown",
        "armor", "armored", "shield",
        "green", "brown", "olive", "moss", "slime", "swamp", "vine",
    ],
    "dark": [
        "shadow", "dark", "darkness", "undead", "death", "void", "abyss",
        "phantom", "ghost", "specter", "wraith", "night", "midnight",
        "obsidian", "onyx", "necro", "zombie", "skeleton", "skull",
        "reaper", "lich", "vampire", "bat",
        "black",
    ],
    "bright": [
        "light", "holy", "divine", "celestial", "radiant", "sun", "solar",
        "fairy", "angel", "luminous", "glow", "glowing", "star", "prism",
        "rainbow", "healing", "pure", "blessed", "halo",
        "white", "yellow",
    ],
}


def _infer_mood_from_description(description: str) -> str | None:
    """
    Scan description for subject keywords and return the best-matching mood.

    Returns None if no keywords match (caller should fall back to "auto").
    If multiple moods match, picks the one with the most keyword hits.
    """
    desc_lower = description.lower()
    # Split into words for whole-word matching
    words = set(desc_lower.split())

    scores: dict[str, int] = {}
    for mood, keywords in _MOOD_KEYWORDS.items():
        count = 0
        for kw in keywords:
            # Check both whole-word and substring (for compound words like "fire-breathing")
            if kw in words or kw in desc_lower:
                count += 1
        if count > 0:
            scores[mood] = count

    if not scores:
        return None

    return max(scores, key=scores.get)


# ---------------------------------------------------------------------------
# Pre-computed hue-shifted triads for late era
# ---------------------------------------------------------------------------
# NES PPU columns give natural hue gradients across brightness rows.
# Each triad is (shadow, midtone, highlight) from the same hue family
# but different rows — the NES hardware inherently shifts hue with brightness.
# This removes the need to tell Claude to hue-shift; the colors arrive pre-shifted.

_LATE_ERA_TRIADS: dict[str, list[tuple[str, str, str]]] = {
    # mood -> list of (shadow, midtone, highlight) triads
    "warm": [
        ("#5A0002", "#9A1032", "#E47ABA"),   # red family
        ("#4F0800", "#913800", "#E09264"),   # orange family
        ("#351000", "#7A5400", "#C8B216"),   # gold family
        ("#560044", "#92088A", "#D85CFE"),   # magenta family
    ],
    "cool": [
        ("#002C88", "#0D56D0", "#4CA0FE"),   # blue family
        ("#1B0076", "#4220D0", "#7C78FE"),   # indigo family
        ("#3B0076", "#6A12C2", "#A862FE"),   # purple family
        ("#00234A", "#006486", "#3EC4D2"),   # teal family
    ],
    "dark": [
        ("#002C88", "#0D56D0", "#4CA0FE"),   # blue family
        ("#3B0076", "#6A12C2", "#A862FE"),   # purple family
        ("#5A0002", "#9A1032", "#E47ABA"),   # red family
        ("#00234A", "#006486", "#3EC4D2"),   # teal family
    ],
    "bright": [
        ("#4220D0", "#7C78FE", "#C8C4FE"),   # indigo family (row 1-2-3)
        ("#9A1032", "#E47ABA", "#F4C4E2"),   # red family (row 1-2-3)
        ("#913800", "#E09264", "#F0CEB2"),   # orange family (row 1-2-3)
        ("#0E7800", "#46E438", "#B0F29C"),   # green family (row 1-2-3)
    ],
    "earth": [
        ("#002E00", "#0E7800", "#6ADA02"),   # green family (body — most earth subjects are green)
        ("#351000", "#7A5400", "#C8B216"),   # gold family (accent)
        ("#4F0800", "#913800", "#E09264"),   # orange family
        ("#1A1802", "#536800", "#A0CC00"),   # olive family
    ],
    "auto": [
        ("#002C88", "#0D56D0", "#4CA0FE"),   # blue family (armor)
        ("#5A0002", "#9A1032", "#E47ABA"),   # red family (tunic/cape)
        ("#351000", "#7A5400", "#C8B216"),   # gold family (accents)
        ("#3B0076", "#6A12C2", "#A862FE"),   # purple family (magic)
    ],
}


def _snap_to_bit_depth(hex_color: str, bits_per_channel: int) -> str:
    """Snap a hex color to the nearest valid value for the given bit depth.

    E.g. 9-bit (3 bits/channel) -> valid steps are 0, 36, 73, 109, 146, 182, 219, 255.
    """
    r, g, b = _hex_to_rgb(hex_color)
    max_val = (1 << bits_per_channel) - 1
    scale = 255 / max_val
    r2 = round(min(round(r / scale), max_val) * scale)
    g2 = round(min(round(g / scale), max_val) * scale)
    b2 = round(min(round(b / scale), max_val) * scale)
    return _rgb_to_hex(r2, g2, b2)


def _resolve_palette(
    era: str,
    palette_mood: str,
    palette_colors: list[str] | None,
    outline: str,
    asset_type: str,
    console: str = "nes",
) -> tuple[list[str], dict[str, str]]:
    """
    Resolve final palette colors and assign roles.

    For late era: builds palette from pre-computed hue-shifted triads.
    For other eras: spreads across luminance range from mood palette.

    For free-color consoles (Genesis 9-bit, SNES/GBC/PCE 15-bit), snaps
    all colors to the console's bit depth so MCP prompts provide
    hardware-valid colors from the start.

    Returns (colors_list, roles_dict) where roles_dict maps hex -> role name.
    """
    ec = _era_constraints(era, console)
    max_colors = ec["max_colors"]

    if palette_colors:
        colors = palette_colors[:max_colors]
    elif era == "late":
        # Late era: use pre-computed hue-shifted triads
        colors = _resolve_late_palette(palette_mood, outline)
    else:
        mood_palette = get_mood_palette(palette_mood)
        if mood_palette:
            with_lum = [(c, _luminance(c)) for c in mood_palette]
            with_lum.sort(key=lambda x: x[1])
            if len(with_lum) >= max_colors:
                step = max(1, len(with_lum) // max_colors)
                colors = [with_lum[i * step][0] for i in range(max_colors)]
            else:
                colors = [c for c, _ in with_lum[:max_colors]]
        else:
            # Use console's palette when available, fall back to NES
            from .console_profile import get_profile
            profile = get_profile(console)
            if profile.master_palette_hex:
                all_hex = list(profile.master_palette_hex)
            else:
                all_hex = [_rgb_to_hex(r, g, b) for r, g, b in NES_PALETTE_RGB]
            with_lum = [(c, _luminance(c)) for c in all_hex]
            with_lum.sort(key=lambda x: x[1])
            step = max(1, len(with_lum) // max_colors)
            colors = [with_lum[i * step][0] for i in range(max_colors)]

    # Fixed-palette consoles must receive literal hardware palette values.
    # Map mood/custom suggestions to the nearest master entries, de-duplicate,
    # then fill any collapsed slots deterministically to preserve the promised
    # console+era color count.
    from .console_profile import get_profile
    _profile = get_profile(console)
    if _profile.master_palette_hex is not None:
        master = [color.upper() for color in _profile.master_palette_hex]

        def _rgb_distance(left: str, right: str) -> int:
            lr, lg, lb = _hex_to_rgb(left)
            rr, rg, rb = _hex_to_rgb(right)
            return (lr - rr) ** 2 + (lg - rg) ** 2 + (lb - rb) ** 2

        target_count = len(colors) if palette_colors else max_colors
        snapped: list[str] = []
        for color in colors:
            nearest = min(master, key=lambda candidate: _rgb_distance(color, candidate))
            if nearest not in snapped:
                snapped.append(nearest)
        for candidate in sorted(master, key=_luminance):
            if len(snapped) >= target_count:
                break
            if candidate not in snapped:
                snapped.append(candidate)
        colors = snapped[:target_count]
    elif _profile.color_depth_bits is not None:
        bpc = {9: 3, 15: 5}.get(_profile.color_depth_bits)
        if bpc:
            colors = [_snap_to_bit_depth(c, bpc) for c in colors]

    # Sort by luminance for role assignment
    colors_sorted = sorted(colors, key=_luminance)

    # Get role template
    role_template = suggest_palette_roles(era, outline)
    role_names = role_template["roles"]

    # Map colors to roles
    if era == "late":
        # Late era: assign meaningful roles to all 6 colors
        roles = _assign_late_roles(colors_sorted)
    else:
        _extra_role_names = ["shadow", "midtone_alt", "highlight_alt", "accent"]
        roles: dict[str, str] = {}
        extra_idx = 0
        for i, color in enumerate(colors_sorted):
            if i < len(role_names):
                roles[color] = role_names[i]
            else:
                roles[color] = _extra_role_names[extra_idx % len(_extra_role_names)]
                extra_idx += 1

    return colors_sorted, roles


def _resolve_late_palette(palette_mood: str, outline: str) -> list[str]:
    """
    Build a 6-color late-era palette from pre-shifted hue triads.

    Picks 2 triads from the mood, giving 6 colors total:
    - Triad 1 (body): shadow, midtone, highlight for the primary region
    - Triad 2 (accent): shadow used as outline, midtone + highlight for secondary
    """
    mood = palette_mood.lower() if palette_mood else "auto"
    triads = _LATE_ERA_TRIADS.get(mood, _LATE_ERA_TRIADS["auto"])

    # Primary triad (body/armor) — first triad
    body_shadow, body_mid, body_highlight = triads[0]
    # Secondary triad (accent/detail) — second triad
    accent_shadow, accent_mid, accent_highlight = triads[1]

    # The darkest shadow from the accent triad serves as the outline
    # (dark chromatic, NOT pure black — late era convention)
    return [accent_shadow, body_shadow, body_mid, accent_mid, body_highlight, accent_highlight]


def _assign_late_roles(colors_sorted: list[str]) -> dict[str, str]:
    """Assign meaningful role names to late-era 6-color palette."""
    # Colors are sorted darkest to lightest
    role_sequence = [
        "outline",           # darkest — dark chromatic outline
        "body_shadow",       # primary region shadow
        "body_midtone",      # primary region base
        "accent_midtone",    # secondary region base
        "body_highlight",    # primary region highlight
        "accent_highlight",  # secondary region highlight
    ]
    roles: dict[str, str] = {}
    for i, color in enumerate(colors_sorted):
        if i < len(role_sequence):
            roles[color] = role_sequence[i]
        else:
            roles[color] = f"extra_{i}"
    return roles


# ---------------------------------------------------------------------------
# Palette rules (era-specific)
# ---------------------------------------------------------------------------

_PALETTE_RULES: dict[str, str] = {
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
  * Top of head/hair/headwear
  * Left shoulder peak
  * Held-item edge — topmost pixel — when the subject names one
  * Carried-object center or buckle when the subject names one
{color_list}""",
}


def _palette_rules(
    era: str,
    colors: list[str],
    roles: dict[str, str],
    console: str = "nes",
) -> str:
    """Build palette rules text for the system prompt."""
    n = len(colors)

    # Try console-specific palette rules first, fall back to module-level NES dicts
    template = None
    try:
        pd = get_prompt_data(console)
        template = pd.palette_rules.get(era, pd.palette_rules.get("mid"))
    except (NotImplementedError, KeyError):
        pass
    if template is None:
        template = _PALETTE_RULES.get(era, _PALETTE_RULES["mid"])

    # Build color reference strings (up to 16 to support consoles with larger palettes)
    max_slots = max(n, 8)
    c = {f"c{i}": colors[i] if i < n else "N/A" for i in range(max_slots)}
    r = {f"r{i}": roles.get(colors[i], "extra") if i < n else "N/A" for i in range(max_slots)}

    # Extra color lines for eras with variable counts
    extra_lines = []
    if era == "retro" and n >= 3:
        extra_lines.append(
            f"- Color 3 ({colors[2]}, {roles.get(colors[2], 'accent')}): "
            "single accent — eyes, a held-item tip (when the subject names one), or a belt buckle. Use on 2-4 pixels maximum."
        )
    elif era == "early" and n >= 3:
        extra_lines.append(
            f"- {colors[2]} ({roles.get(colors[2], 'secondary')}): "
            "fills remaining 30-40%. Used for skin, hair, or contrasting clothing."
        )
    elif era == "mid" and n >= 4:
        extra_lines.append(
            f"- {colors[3]} ({roles.get(colors[3], 'highlight')}): "
            "the highlight color — see placement rules below."
        )

    extra_color = "\n".join(extra_lines) + "\n" if extra_lines else ""

    # For late era, list all colors with roles
    color_list = ""
    if era == "late":
        color_list = "- Full palette:\n"
        for color in colors:
            role = roles.get(color, "extra")
            color_list += f"  * {color} — {role}\n"

    return template.format(
        n=n,
        extra_color=extra_color,
        color_list=color_list,
        **c, **r,
    )


# ---------------------------------------------------------------------------
# Tool rules (era + asset_type specific)
# ---------------------------------------------------------------------------

_SAFE_DITHER_PATTERNS = ["bayer_2x2", "bayer_4x4", "bayer_8x8", "floyd_steinberg"]

_BROKEN_DITHER_PATTERNS = [
    "checkerboard", "grass", "water", "stone", "cloud", "brick",
    "dots", "diagonal", "cross", "noise", "horizontal_lines", "vertical_lines",
]

_GLOBAL_BLACKLIST = ["apply_auto_shading", "suggest_antialiasing"]

_TOOL_CONFIGS: dict[str, dict] = {
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


def _tool_rules(
    era: str,
    asset_type: str,
    console: str = "nes",
    size: tuple[int, int] = (16, 16),
    auto_shading_16x16: bool = False,
) -> tuple[str, list[str], list[str]]:
    """Return (rules_text, whitelist, blacklist) for the given era.

    rg-023 trial: auto_shading_16x16 extends the 32x32+ auto_shading mandate to
    16x16 mid/late on 16-bit consoles. Default off; the bake-off harness sets it.
    """
    # Try console-specific tool configs first, fall back to module-level NES dicts
    config = None
    try:
        pd = get_prompt_data(console)
        config = pd.tool_configs.get(era, pd.tool_configs.get("mid"))
    except (NotImplementedError, KeyError):
        pass
    if config is None:
        config = _TOOL_CONFIGS.get(era, _TOOL_CONFIGS["mid"])
    rules = config["rules"]
    whitelist = list(config["whitelist"])
    blacklist = list(config["blacklist"])

    # Tiles can use dither in mid/late eras
    is_tile = asset_type in ("tile", "tileset")
    if is_tile and era in ("mid", "late"):
        if "draw_with_dither" not in whitelist:
            whitelist.append("draw_with_dither")

    # At 32x32+, 16-bit consoles get auto_shading and mandatory validation.
    # rg-023 trial: auto_shading_16x16=True extends the gate to 16x16 mid/late
    # on 16-bit consoles. auto_shading improves both quality AND canvas
    # utilization (adds 1-2px edge detail).
    _16BIT_CONSOLES = {
        "snes", "super_nintendo", "genesis", "mega_drive",
        "pc_engine", "turbografx", "turbografx_16",
    }
    auto_shading_eligible = (
        max(size) >= 24
        or (max(size) == 16 and auto_shading_16x16 and era in ("mid", "late"))
    )
    if auto_shading_eligible and console in _16BIT_CONSOLES and not is_tile:
        # Add auto_shading and get_sprite_info to whitelist
        for tool in ("apply_auto_shading", "get_sprite_info", "add_layer", "flatten_layers"):
            if tool not in whitelist:
                whitelist.append(tool)
        # Remove auto_shading from blacklist if present
        blacklist = [t for t in blacklist if t != "apply_auto_shading"]
        # Append size-aware tool guidance to rules
        size_label = "32x32+" if max(size) >= 24 else "16x16 trial"
        rules += (
            f"\n\n{size_label} ADDITIONS: apply_auto_shading is REQUIRED after drawing "
            "(light_direction=\"top_left\", hue_shift=true, intensity=0.3-0.4, style=\"smooth\"). "
            "This adds directional depth and helps fill the canvas. "
            "get_sprite_info is MANDATORY after every sprite — check bounding box fills "
            "70%+ height and 45%+ width. If not, erase and redraw larger."
        )

    return rules, whitelist, blacklist


# ---------------------------------------------------------------------------
# Drawing order (era + asset_type specific)
# ---------------------------------------------------------------------------

_DRAWING_ORDERS: dict[str, list[str]] = {
    "retro": [
        "1. create_canvas({w}, {h}, \"rgb\")",
        "2. set_palette with your {n} colors",
        "3. draw_rectangle for the main body block (filled=true, primary color)",
        "4. draw_rectangle for the head block (filled=true)",
        "5. draw_pixels for 1-3 accent details (eyes, or a held-item tip when the subject names one)",
    ],
    "early": [
        "1. create_canvas({w}, {h}, \"rgb\")",
        "2. set_palette with your {n} colors",
        "3. draw_rectangle blocks for torso, head, limbs (primary color, filled=true)",
        "4. draw_pixels for secondary color regions (skin, hair, boots)",
        "5. draw_pixels for internal detail lines (eyes, belt)",
        "6. apply_outline with #000000, thickness=1",
    ],
    "mid": [
        "1. create_canvas({w}, {h}, \"rgb\")",
        "2. set_palette with your {n} colors",
        "3. SCAFFOLD: draw_rectangle for torso, draw_circle for head — establishes proportions",
        "4. SILHOUETTE: draw_pixels to refine scaffold into actual body shape, add limb separation",
        "5. COLOR: draw_pixels to place secondary color (skin, cape, boots) as contiguous blocks",
        "6. HIGHLIGHT: draw_pixels for highlight color — top-left edges only, 5-15% of pixels",
        "7. DETAIL: draw_pixels for eyes, mouth, belt buckle, and held-item edges when the subject names them",
        "8. apply_outline with #000000, thickness=1",
    ],
    "late": [
        "1. create_canvas({w}, {h}, \"rgb\")",
        "2. set_palette with your {n} colors",
        "3. SCAFFOLD: draw_rectangle/draw_circle for major body regions using midtone colors",
        "4. SHADOW: draw_pixels for shadow color on bottom-right edges of each body region",
        "5. SILHOUETTE: draw_pixels to refine shape — arm positions, leg separation, and held-item extension when the subject names one",
        "6. DETAIL: draw_pixels for secondary regions, facial features, and outfit details",
        "7. HIGHLIGHT: draw_pixels for single-pixel highlights on top-left convex edges",
        "8. apply_outline with dark chromatic color (e.g. {outline_color}), thickness=1",
    ],
}

_TILE_DRAWING_ORDERS: dict[str, list[str]] = {
    "retro": [
        "1. create_canvas({w}, {h}, \"rgb\")",
        "2. set_palette with your {n} colors",
        "3. fill_area to set base color across entire canvas",
        "4. draw_pixels or draw_rectangle for pattern elements",
    ],
    "early": [
        "1. create_canvas({w}, {h}, \"rgb\")",
        "2. set_palette with your {n} colors",
        "3. fill_area for base color",
        "4. draw_pixels or draw_line for pattern detail (brick lines, crack marks)",
    ],
    "mid": [
        "1. create_canvas({w}, {h}, \"rgb\")",
        "2. set_palette with your {n} colors",
        "3. fill_area for base color",
        "4. draw_with_dither (bayer_2x2 or bayer_4x4) for texture variation — optional",
        "5. draw_pixels for pattern detail and highlights",
    ],
    "late": [
        "1. create_canvas({w}, {h}, \"rgb\")",
        "2. set_palette with your {n} colors",
        "3. fill_area for base midtone color",
        "4. draw_with_dither (bayer_4x4 or bayer_8x8) for texture gradient — optional",
        "5. draw_pixels for mortar lines, crack details, surface highlights",
        "6. draw_pixels for single-pixel light highlights on top edges of stones/bricks",
    ],
}


def _drawing_order(
    era: str,
    asset_type: str,
    size: tuple[int, int],
    n_colors: int,
    outline_color: str = "#000000",
    auto_shading_16x16: bool = False,
) -> str:
    """Return formatted drawing order text.

    rg-023 trial: auto_shading_16x16 extends the 32x32+ auto_shading + validation
    drawing-order steps to 16x16 mid/late.
    """
    is_tile = asset_type in ("tile", "tileset")
    orders = _TILE_DRAWING_ORDERS if is_tile else _DRAWING_ORDERS
    steps = orders.get(era, orders["mid"])

    formatted = []
    for step in steps:
        formatted.append(step.format(
            w=size[0], h=size[1], n=n_colors, outline_color=outline_color,
        ))

    # At 32x32+, add mandatory auto_shading step for non-tile sprites
    # and mandatory validation as the final step.
    # rg-023 trial: auto_shading_16x16 extends this to 16x16 mid/late.
    auto_shading_eligible = (
        max(size) >= 24
        or (max(size) == 16 and auto_shading_16x16 and era in ("mid", "late"))
    )
    if auto_shading_eligible and not is_tile:
        next_num = len(formatted) + 1
        formatted.append(
            f"{next_num}. apply_auto_shading with light_direction=\"top_left\", "
            "hue_shift=true, intensity=0.3-0.4, style=\"smooth\" — "
            "adds directional depth and fills canvas edges"
        )
        next_num += 1
        formatted.append(
            f"{next_num}. MANDATORY: get_sprite_info — check bounding box. "
            "If height fill <70% or width fill <45%, your sprite is too small. "
            "Erase and redraw LARGER. Do NOT skip this step."
        )

    return "DRAW ORDER:\n" + "\n".join(formatted)


# ---------------------------------------------------------------------------
# Proportion rules (asset_type + era)
# ---------------------------------------------------------------------------

_CHARACTER_PROPORTIONS_16: dict[str, str] = {
    "retro": """\
PROPORTIONS (8x8 character):
- Head: 3x3 block, top-center (rows 0-2). May be 2x2 if body needs space.
- Body: 4x3 block, below head (rows 3-5). Single solid color.
- Legs: two 1x2 columns at bottom (rows 6-7). 1px gap between them.
- Arms: optional 1px lines from body sides. Often omitted at this size.
- Total: 8 pixels tall. Head is ~37% of height.
- This is NOT a recognizable human. It is a colored shape that suggests "person."
- Held items (only when the subject names them): 1-2 extra pixels extending from the body edge. Keep simple.""",

    "early": """\
PROPORTIONS (12x16 character):
- Head: 6x5 block (rows 1-5), centered horizontally. 2px eyes on row 3.
- Body: 6x4 block (rows 6-9). Single primary color fill.
- Arms: 2x3 blocks flanking body (rows 6-8), 1px wide each side.
- Legs: two 2x5 columns (rows 10-14), 1px gap between.
- Feet: 3px wide at row 15 (1px wider than legs).
- Head is ~31% of total height. Chibi ratio: 2.5 heads tall.
- Held items (only when the subject names them): extend 2-3px beyond body silhouette as a 1px vertical line with optional 1px crossbar.""",

    "mid": """\
PROPORTIONS (16x16 character):
- Head: 7x6 block (rows 1-6), centered. Eyes at row 4, 2px wide, 3px apart.
- Torso: 7x4 block (rows 7-10). Primary color with possible belt detail at row 10.
- Arms: 2x5 extending from torso sides. BOTH arms visible from any view angle.
- Legs: two 3x4 columns (rows 11-14), 1px gap between.
- Feet: 4px wide at row 15. Boot shape distinguishable.
- Head is ~37% of height. Chibi ratio: 2.5 heads tall.
- Held items (only when the subject names them): a long held item is 2px wide and extends 3-4px above or beside the body; a carried object on the arm occupies a 3x4 area.
- BOTH arms and BOTH legs must be visible regardless of view angle.
- Face: 2px eyes, optional 1px mouth. Hair/helmet distinguishable from face.""",

    "late": """\
PROPORTIONS (16x16 character):
- Head: 6x5 block (rows 1-5), slightly smaller ratio than mid era — more "adult" proportions.
- Torso: 8x5 block (rows 6-10), wider than head for heroic build.
- Arms: 2x5 with visible shoulder pauldrons (1px wider at row 6-7).
- Legs: two 3x4 columns (rows 11-14), with 1px boot cuff detail.
- Feet: 4px wide at row 15, distinct boot shape with heel pixel.
- Head is ~31% of height. Ratio: 3 heads tall (more proportional than mid era).
- Armor detail: belt line at row 10 in secondary color, pauldron edges, boot tops.
- Face: 2px eyes, 1px mouth. Highlight pixel on forehead/hair top.
- Muscle/clothing definition: use shadow color to separate arm from torso, leg from leg.""",
}

_CHARACTER_PROPORTIONS_32: dict[str, str] = {
    "early": """\
PROPORTIONS (32x32 character):
- IMPORTANT: You have a 32x32 canvas. DO NOT draw a 16x16 sprite in a 32x32 canvas.
- The sprite content must fill at least 75% of the canvas height (24+ rows) and 50% width (16+ cols).
- Head: 10x9 block (rows 2-10), centered. Eyes at row 7, 3px wide, 4px apart.
  Hair/helmet detail: 3-4 rows with distinct color regions.
- Torso: 14x8 block (rows 11-18). Room for belt, tunic detail, armor segmentation.
- Arms: 4x9 extending from torso sides (rows 10-18). Forearm/upper arm distinction.
  BOTH arms visible. Hands 3x3 at arm ends.
- Legs: two 5x9 columns (rows 19-27), 2px gap between. Knee bend visible.
- Feet: 7px wide at rows 28-30, clear boot shape with sole and heel.
- Head is ~28% of height. Ratio: 3.5 heads tall — more realistic proportions.
- Held items (only when the subject names them): a long held item is 3px wide and extends 5-6px above the shoulder; a carried object on the arm occupies a 6x7 area.
  Outfit detail (clothing folds, buckles, laces, plating) has enough space for distinct shapes.
- Face: 3px eyes with 1px pupil, 2px nose, 2px mouth. Expression readable.""",

    "mid": """\
PROPORTIONS (32x32 character):
- IMPORTANT: You have a 32x32 canvas. DO NOT draw a 16x16 sprite in a 32x32 canvas.
- The sprite content must fill at least 75% of the canvas height (24+ rows) and 50% width (16+ cols).
- Head: 10x8 block (rows 2-9), centered. Eyes at row 6, 3px wide with 1px pupil.
  Helmet/hair: distinct shape with 2-3 color gradient.
- Torso: 14x9 block (rows 10-18). Belt at row 18 in accent color.
  Armor segmentation: pauldrons (2px wider than shoulders), chest plate, side plates.
- Arms: 4x10 extending from torso (rows 9-18). Upper arm and forearm distinct.
  Hands 3x3 — empty by default; show grip detail only when the subject names a held item.
- Legs: two 5x9 columns (rows 19-27), 2px gap. Thigh vs shin distinct via shade.
- Feet: 7px wide at rows 28-30. Boot shape with distinct sole, heel, and cuff.
- Head is ~25% of height. Ratio: 3.5-4 heads tall.
- Held items (only when the subject names them): a long held item is 3-4px wide with crossbar and base detail; a carried object on the arm occupies a 7x8 area.
  Outfit detail: individual segments, fasteners (1px), surface markings (2px).
- Face: expressive — 3px eyes, brow line, nose bridge, mouth. Scar or marking optional.
- BOTH arms and BOTH legs visible. Shadow color separates overlapping limbs.""",

    "late": """\
PROPORTIONS (32x32 character):
- IMPORTANT: You have a 32x32 canvas. DO NOT draw a 16x16 sprite in a 32x32 canvas.
- The sprite content must fill at least 75% of the canvas height (24+ rows) and 50% width (16+ cols).
- Head: 9x8 block (rows 2-9). Slightly smaller head-to-body ratio for heroic proportions.
  Face: full detail — 3px eyes with highlight, nose, mouth, chin. Hair flows 2-3px beyond head.
- Torso: 16x10 block (rows 10-19). Wide heroic build. Detailed armor with 4+ shade steps.
  Chest plate center, side plates, shoulder pauldrons extending 2px beyond arm line.
  Belt/waist at row 19: buckle, pouches, or sash detail.
- Arms: 5x10 from pauldrons (rows 10-19). Gauntlets on forearms (rows 15-19, different shade).
  Hands 3x3 — empty by default; show grip detail or held-item effect only when the subject names them.
- Legs: two 6x8 columns (rows 20-27), 2px gap. Lower-leg coverings distinct from thigh.
- Feet: 8px wide at rows 28-30. Footwear with 2-color detail.
- Head is ~25% of height. Ratio: 4 heads tall — most realistic proportions.
- Held items (only when the subject names them): a long held item is 4px wide with crossbar, central line, and ornament; a tall thin held item is 2-3px wide extending the full sprite height with a detailed head.
  Cape/cloak: trails from shoulders, 3-shade fabric with fold lines.
- Shading: every major surface has 3+ shade steps. Metal = sharp transitions + specular.
  Fabric = soft gradients. Skin = warm hue path.""",
}

_ENEMY_PROPORTIONS_16: dict[str, str] = {
    "retro": """\
PROPORTIONS (8x8 enemy):
- Single compact shape filling 6x6 to 8x8 of canvas.
- No limb separation. Body IS the silhouette.
- Eyes: 1-2 pixels of secondary color. May be omitted.
- Shape conveys type: circle = blob, triangle = spike, square = block.""",

    "early": """\
PROPORTIONS (enemy):
- Compact body filling 70-80% of canvas.
- Simple geometric base: oval, circle, or triangle.
- Eyes: 2px wide, placed in upper third of body.
- Optional limbs: 1px wide stubs, max 2px long.
- Teeth/horns: 1px protrusions from body edge.""",

    "mid": """\
PROPORTIONS (enemy):
- Body fills 60-75% of canvas. Leave 1-2px border for outline.
- Recognizable shape: distinct head region, body, and appendages.
- Eyes: 2-3px wide, expressive (angry, surprised). Can use highlight color.
- Limbs/wings/tentacles: 2px wide minimum, clearly attached to body.
- Distinguishing feature (horns, shell, tail): extends 2-3px from main body.""",

    "late": """\
PROPORTIONS (enemy):
- Body fills 60-75% of canvas. Complex silhouette with interesting negative space.
- Multiple body regions with distinct coloring (head vs body vs tail/wings).
- Eyes: expressive, may use 2 colors (pupil + white/glow).
- 3-step shading on largest body region for volume.
- Surface detail: scales, armor plates, fur texture via alternating pixel rows.""",
}

_ENEMY_PROPORTIONS_32: dict[str, str] = {
    "early": """\
PROPORTIONS (32x32 enemy):
- IMPORTANT: You have a 32x32 canvas. DO NOT draw a small enemy in a 32x32 canvas.
- Body fills 70-80% of canvas (22-26px tall, 18-24px wide). Center the creature.
- Distinct head region: 8-10px. Body: 12-16px. Tail/appendages: extend to canvas edges.
- Eyes: 4px wide, placed in upper third. Expressive shape (angry slits, round surprised).
- Limbs/wings: 3-4px wide, clearly attached. Wing span can reach canvas edges.
- Teeth/horns/spikes: 2-3px protrusions from body edge.""",

    "mid": """\
PROPORTIONS (32x32 enemy):
- IMPORTANT: You have a 32x32 canvas. DO NOT draw a small enemy in a 32x32 canvas.
- Body fills 65-80% of canvas. Complex silhouette with interesting negative space.
- Head region: 8-10px with distinct features (horns, jaw, crest).
- Body: 14-18px with texture detail (scales 2x2, plates 3x3, fur via alternating rows).
- Wings/tentacles/tail: extend to canvas edges, 4-5px wide with membrane or segmentation.
- Eyes: 4-5px wide, 2 colors (pupil + glow/white). Menacing expression.
- Shading: 3-step on all major body regions. Light source consistent across creature.""",

    "late": """\
PROPORTIONS (32x32 enemy):
- IMPORTANT: You have a 32x32 canvas. DO NOT draw a small enemy in a 32x32 canvas.
- Body fills 65-80% of canvas. Complex, layered silhouette.
- Head: 8-10px, detailed — jaw musculature, horn ridges, eye sockets with depth.
- Body: 14-18px with surface material variety (scales, carapace, exposed muscle).
- Appendages: fill remaining canvas space. Wings with visible membrane veins.
  Tail with segments. Claws 3-4px with individual digits.
- Eyes: 5px wide, multi-shade (dark socket, iris color, highlight glint).
- 4-step shading on largest surfaces. Specular highlights on wet/chitinous areas.
- Environmental detail: dripping venom (1px trails), glowing markings, battle scars.""",
}

_ITEM_PROPORTIONS_16: dict[str, str] = {
    "retro": """\
PROPORTIONS (8x8 item):
- Object fills 6x6 to 8x8 of canvas. Centered.
- Pure geometric shape: square, diamond, circle, cross.
- 1-2 colors maximum. Shape alone identifies the item.""",

    "early": """\
PROPORTIONS (item):
- Object fills 70-80% of canvas. Centered vertically and horizontally.
- Clear silhouette — identifiable at a glance without context.
- No rotation — items face the viewer straight on.
- Details limited to 2-3 internal features (gem facets, bottle neck, key teeth).""",

    "mid": """\
PROPORTIONS (item):
- Object fills 70-80% of canvas. Centered.
- Bold iconic silhouette. Must be identifiable at 1x zoom.
- Highlight color on top-left edge for 3D pop.
- Internal detail: 3-5 distinct features visible.
- No character hands or person — just the item itself.""",

    "late": """\
PROPORTIONS (item):
- Object fills 70-80% of canvas. Centered.
- Rich detail with 3-step shading on largest surface.
- Gem/glass surfaces: highlight + midtone + shadow for reflective look.
- Metal surfaces: dark outline, midtone body, bright edge highlight.
- Organic surfaces: use shadow color for depth, highlight for moisture/sheen.""",
}

_ITEM_PROPORTIONS_32: dict[str, str] = {
    "early": """\
PROPORTIONS (32x32 item):
- IMPORTANT: You have a 32x32 canvas. The item must fill 70-80% of it (22-26px tall/wide).
- Object centered in canvas. Clear silhouette identifiable at 1x zoom.
- Room for sub-features: a bottle has neck + body + base as distinct shapes;
  a key has bow + shaft + teeth; render whatever sub-features the named item naturally has.
- Internal detail: 4-6 distinct features. Material distinction via shading.""",

    "mid": """\
PROPORTIONS (32x32 item):
- IMPORTANT: You have a 32x32 canvas. The item must fill 70-80% of it (22-26px tall/wide).
- Bold iconic silhouette centered in canvas.
- Highlight on top-left edges, shadow on bottom-right for consistent light source.
- Sub-component detail: gem facets (3x3 regions with individual shading),
  metal engravings (2px patterns), leather texture (alternating rows).
- Internal detail: 6-8 distinct features. Each material reads differently.""",

    "late": """\
PROPORTIONS (32x32 item):
- IMPORTANT: You have a 32x32 canvas. The item must fill 70-80% of it (22-26px tall/wide).
- Rich detail with 4-step shading on all surfaces. Each material type has a distinct shading language.
- Gem/glass: 4-shade gradient with bright specular highlight and dark core.
- Metal: sharp shadow/highlight transitions, 1px specular edge, engraving detail.
- Wood: warm brown gradient, visible grain via alternating 1px rows.
- Organic: soft transitions, moisture highlight, cellular texture.
- Magical effects: 2-3px glow aura around enchanted regions.""",
}

_TILE_PROPORTIONS: dict[str, str] = {
    "retro": """\
PROPORTIONS (tile):
- ENTIRE canvas must be filled. No empty pixels. No transparent pixels.
- Simple repeating pattern: 2-color checkerboard, stripes, solid with dots.
- Pattern must tile seamlessly — left edge connects to right, top to bottom.""",

    "early": """\
PROPORTIONS (tile):
- ENTIRE canvas filled. No transparency.
- Simple texture: bricks, grass blades, water ripples using 2-3 colors.
- Pattern elements repeat at predictable intervals.
- Edge pixels must match opposite edge for seamless tiling.""",

    "mid": """\
PROPORTIONS (tile):
- ENTIRE canvas filled. No transparency for background tiles.
- Texture with visible detail: individual bricks with mortar, grass tufts, stone grain.
- Use highlight color sparingly for surface light (top of bricks, grass tips).
- Seamless tiling: left column matches right column, top row matches bottom row.""",

    "late": """\
PROPORTIONS (tile):
- ENTIRE canvas filled. No transparency for background tiles.
- Rich texture with shading: bricks have individual highlight + shadow faces.
- Mortar lines, surface cracks, moss patches for environmental storytelling.
- 3-step gradient across tile surface for lighting direction.
- Seamless tiling is critical — verify edge pixel colors match opposites.""",
}


_16BIT_CONSOLES_SET = {
    "snes", "super_nintendo", "genesis", "mega_drive",
    "pc_engine", "turbografx", "turbografx_16",
}


def _proportion_rules(asset_type: str, era: str, size: tuple[int, int],
                      console: str = "nes") -> str:
    """Return proportion rules for the given asset type and era.

    Selects 32x32-specific proportions when canvas is 24x24 or larger,
    falling back to standard (16x16 and below) proportions otherwise.
    Tiles don't change by size — they always fill the full canvas.

    For 16-bit consoles, prepends a canvas utilization warning that
    overrides the NES-centric chibi assumptions.
    """
    is_large = max(size) >= 24

    # Tiles always fill full canvas — no size-specific variants needed
    if asset_type in ("tile", "tileset"):
        return _TILE_PROPORTIONS.get(era, _TILE_PROPORTIONS["mid"])

    # Spritesheet/directional use character proportions
    if asset_type in ("spritesheet", "directional"):
        if is_large:
            props = _CHARACTER_PROPORTIONS_32
        else:
            props = _CHARACTER_PROPORTIONS_16
        base = props.get(era, props.get("mid", list(props.values())[0]))
    else:
        # Standard lookup with size-aware selection
        if is_large:
            lookup = {
                "character": _CHARACTER_PROPORTIONS_32,
                "enemy": _ENEMY_PROPORTIONS_32,
                "item": _ITEM_PROPORTIONS_32,
            }
        else:
            lookup = {
                "character": _CHARACTER_PROPORTIONS_16,
                "enemy": _ENEMY_PROPORTIONS_16,
                "item": _ITEM_PROPORTIONS_16,
            }

        props = lookup.get(asset_type, lookup.get("character"))
        base = props.get(era, props.get("mid", list(props.values())[0]))

    # 16-bit consoles: add canvas utilization prefix
    if console in _16BIT_CONSOLES_SET:
        h_fill = int(size[1] * 0.88)
        w_fill = int(size[0] * 0.50)
        prefix = (
            f"CANVAS UTILIZATION (CRITICAL — 16-bit console at {size[0]}x{size[1]}):\n"
            f"Your canvas is {size[0]}x{size[1]} pixels. The sprite MUST fill this canvas.\n"
            f"- Minimum height: {h_fill}px ({size[1]}px * 88%). "
            f"Content spans from row 1 to row {h_fill}.\n"
            f"- Minimum width: {w_fill}px ({size[0]}px * 50%). "
            f"Body centered horizontally.\n"
            f"- Start drawing at row 0-1 (head top) and extend to row {size[1] - 1} (feet).\n"
            "- Do NOT leave empty rows above the head or below the feet.\n"
            "- A common failure mode is drawing a sprite that only fills 60-70% of the "
            "canvas height. This produces tiny, underwhelming output. Fill the space.\n"
        )
        return prefix + "\n" + base

    return base


# ---------------------------------------------------------------------------
# View rules
# ---------------------------------------------------------------------------

_VIEW_RULES: dict[str, str] = {
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


def _view_rules(view: str) -> str:
    """Return view-specific drawing guidance."""
    return _VIEW_RULES.get(view, _VIEW_RULES["side"])


# ---------------------------------------------------------------------------
# Animation rules
# ---------------------------------------------------------------------------

_POSE_DESCRIPTIONS: dict[str, dict[tuple[int, int], str]] = {
    "walk": {
        (0, 2): "contact position — one foot forward, arms at sides",
        (1, 2): "passing position — legs crossing under body, arms swinging",
        (0, 3): "contact — left foot forward, right back, arms at sides",
        (1, 3): "passing — legs crossing, arms counter-swing",
        (2, 3): "contact mirrored — right foot forward, left back",
        (0, 4): "contact — left foot forward, right foot back",
        (1, 4): "first passing — legs crossing, arms swinging forward",
        (2, 4): "contact mirrored — right foot forward, left foot back",
        (3, 4): "second passing — legs crossing, arms swinging back",
    },
    "run": {
        (0, 2): "push-off — back leg extended, front leg bent",
        (1, 2): "airborne flight — both legs tucked under body",
        (0, 4): "push-off — back leg extended, front knee driving up",
        (1, 4): "airborne flight — both legs tucked",
        (2, 4): "landing — front leg reaching forward, back leg trailing",
        (3, 4): "recovery — legs switching, arms pumping opposite",
    },
    "idle": {
        (0, 2): "standing still — arms at sides, neutral pose",
        (1, 2): "slight chest rise — breathing in, 1px torso shift up",
        (0, 4): "neutral standing — weight centered",
        (1, 4): "slight shift — chest rising, subtle breathing",
        (2, 4): "neutral standing — weight centered (same as frame 1)",
        (3, 4): "slight shift — chest lowering, exhaling",
    },
    "attack": {
        (0, 2): "windup — striking arm raised above shoulder, body leaning back 1px",
        (1, 2): "swing — striking arm extended forward, body leaning forward 1px",
        (0, 3): "ready — striking arm at chest height",
        (1, 3): "windup — striking arm raised above head, body coiling",
        (2, 3): "strike — striking arm fully extended, body lunging 1px forward",
        (0, 4): "ready — striking arm held at chest height",
        (1, 4): "windup — striking arm raised to shoulder, slight body turn",
        (2, 4): "strike — striking arm extended forward, small step forward",
        (3, 4): "recovery — striking arm returning to chest, body straightening",
    },
    "jump": {
        (0, 2): "crouch — knees bent, arms at sides, body 1px shorter",
        (1, 2): "airborne — feet off ground, body compact, arms up",
        (0, 4): "crouch — knees bent, body compressed 1px shorter",
        (1, 4): "push-off — knees straightening, feet leaving ground",
        (2, 4): "peak — airborne, body compact, arms raised",
        (3, 4): "descend — legs extending down, arms lowering",
    },
    "death": {
        (0, 2): "hit — flinching, slight backward lean of 1px",
        (1, 2): "collapsed — on knees, body slumped forward",
        (0, 4): "hit — body recoiling 1px backward",
        (1, 4): "stumbling — one knee bending, leaning back",
        (2, 4): "dropping — falling to knees, arms going limp",
        (3, 4): "collapsed — body slumped forward, arms hanging",
    },
    "cast": {
        (0, 2): "channel — hands together at chest height",
        (1, 2): "release — hands raised to head height, glow pixel near hands",
        (0, 4): "ready — hands at sides, neutral stance",
        (1, 4): "gather — hands raised to chest height",
        (2, 4): "channel — hands at head height, 1-2 glow pixels between hands",
        (3, 4): "release — hands pushing forward, glow pixel launched",
    },
}

_ANIMATION_CHANGE_RULES: dict[str, str] = {
    "walk": """\
WHAT CHANGES PER FRAME:
- Legs alternate stride positions (front foot becomes back foot)
- 1px vertical bob on passing frames (sprite shifts up 1px)
- Arms counter-swing opposite to legs
- Head and torso stay at same width/height""",

    "run": """\
WHAT CHANGES PER FRAME:
- Wider stride than walk (2px leg separation at maximum)
- Both feet off ground on flight frame
- Torso leans forward 1px
- Arms pump more dramatically than walk""",

    "idle": """\
WHAT CHANGES PER FRAME:
- 1px vertical shift of torso only (up on frame 2, down on frame 4)
- Limbs do NOT change position
- Head does NOT move
- The change must be subtle — this is breathing, not bouncing""",

    "attack": """\
WHAT CHANGES PER FRAME:
- Striking arm rotates through arc (raised → extended → returning); if the subject names a held item, it follows the arm
- Body leans 1px in strike direction, then recovers
- Off-arm stays stable
- Legs shift 0-1px for weight transfer""",

    "jump": """\
WHAT CHANGES PER FRAME:
- Crouch: body 1px shorter (legs compressed)
- Rise: normal height, feet leaving ground line
- Peak: body 1px higher than normal, arms raised
- Descend: legs extending downward""",

    "death": """\
WHAT CHANGES PER FRAME:
- Progressive collapse: frame 1 upright, each frame tilts/drops further
- Frame 1→2: lean back 1px
- Frame 2→3: drop 1-2px, knees buckling
- Frame 3→4: slumped position, minimal silhouette""",

    "cast": """\
WHAT CHANGES PER FRAME:
- Arms rise from sides → chest → head height → push forward
- 1-2 glow pixels appear on channel frame (use highlight color)
- Glow pixels move outward on release frame
- Body stays stable except slight lean on release""",
}


def _animation_rules(
    animation_type: str,
    frame_index: int,
    frame_total: int,
) -> str:
    """Return animation frame guidance."""
    # Get pose description
    key = (frame_index, frame_total)
    poses = _POSE_DESCRIPTIONS.get(animation_type, {})
    pose = poses.get(key, f"frame {frame_index + 1} of {frame_total}")

    # Get change rules
    changes = _ANIMATION_CHANGE_RULES.get(animation_type, "")

    return f"""\
ANIMATION: {animation_type}, frame {frame_index + 1} of {frame_total}

POSE FOR THIS FRAME: {pose}

{changes}

CONSISTENCY RULES:
- Palette is LOCKED. Do not introduce new colors. Use set_palette with the exact same colors as frame 1.
- Head size, body width, and total sprite height must match frame 1 exactly.
- Outline color and thickness must be identical across all frames.
- Only limb positions, held-item angle (when the subject names one), and vertical offset should change."""


# ---------------------------------------------------------------------------
# Tileset coherence rules
# ---------------------------------------------------------------------------

_TILE_POSITIONS: list[str] = [
    "center",
    "top", "bottom", "left", "right",
    "top_left", "top_right", "bottom_left", "bottom_right",
]

_TILE_EDGE_HINTS: dict[str, str] = {
    "center": "Interior fill tile. All 4 edges must tile seamlessly when repeated.",
    "top": "Top border tile. Bottom edge must connect seamlessly to center tile.",
    "bottom": "Bottom border tile. Top edge must connect seamlessly to center tile.",
    "left": "Left border tile. Right edge must connect seamlessly to center tile.",
    "right": "Right border tile. Left edge must connect seamlessly to center tile.",
    "top_left": "Top-left corner. Bottom and right edges connect to adjacent border tiles.",
    "top_right": "Top-right corner. Bottom and left edges connect to adjacent border tiles.",
    "bottom_left": "Bottom-left corner. Top and right edges connect to adjacent border tiles.",
    "bottom_right": "Bottom-right corner. Top and left edges connect to adjacent border tiles.",
}


# ---------------------------------------------------------------------------
# Color theory rules (from pixel-plugin research + NeurIPS VoT)
# ---------------------------------------------------------------------------

_COLOR_THEORY_RULES: dict[str, str] = {
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


def _color_theory_rules(era: str) -> str:
    """Return color theory guidance for the given era."""
    return _COLOR_THEORY_RULES.get(era, _COLOR_THEORY_RULES["mid"])


# ---------------------------------------------------------------------------
# VoT (Visualization-of-Thought) ASCII planning
# ---------------------------------------------------------------------------

_VOT_TEMPLATES: dict[str, str] = {
    "character": """\
PLANNING STEP — DO THIS FIRST:
Before making any tool calls, mentally plan the sprite as an ASCII grid.
Use these symbols: . = transparent, O = outline, P = primary, S = secondary, H = highlight

Example of a well-planned {w}x{h} character (use this format, not this exact design):
{example_grid}

Write out YOUR grid plan for the requested subject, then convert each non-transparent
cell to a draw_pixels coordinate with the matching palette color.
This planning step is critical — it prevents the "same body" problem where all
characters look identical. Plan the UNIQUE silhouette first.""",

    "enemy": """\
PLANNING STEP — DO THIS FIRST:
Before making any tool calls, mentally plan the sprite as an ASCII grid.
Use: . = transparent, O = outline, P = primary, S = secondary, H = highlight

Enemies should have a distinctive silhouette — NOT a human body shape.
Plan the unique shape first (blob, winged, tentacled, spiked, etc.),
then fill with colors. The silhouette is what makes an enemy readable at 1x zoom.""",

    "item": """\
PLANNING STEP — DO THIS FIRST:
Before making any tool calls, mentally plan the sprite as an ASCII grid.
Use: . = transparent, O = outline, P = primary, S = secondary, H = highlight

Items must be ICONIC — identifiable without context. Plan the shape to fill
70-80% of the canvas, centered. The silhouette alone should communicate the object.""",

    "tile": """\
PLANNING STEP — DO THIS FIRST:
Before making any tool calls, mentally plan the sprite as an ASCII grid.
Use: P = primary/base, S = secondary/detail, H = highlight, D = shadow/dark

Tiles must fill the ENTIRE canvas — no transparent pixels. Plan the repeating
pattern so that left edge pixels match right edge, top matches bottom.
Visualize 4 copies of your tile in a 2x2 grid — do the seams disappear?""",
}

# Compact example grids for VoT per era (character type)
_VOT_EXAMPLE_GRIDS: dict[str, str] = {
    "retro_8x8": """\
. . P P P . . .
. P P P P P . .
. P S P S P . .
. P P P P P . .
. . P P P . . .
. . P . P . . .
. . P . P . . .
. . . . . . . .""",

    "early_12x16": """\
. . . O O O O . . . . .
. . O P P P P O . . . .
. . O P S P S O . . . .
. . O P P P P O . . . .
. . . O P P O . . . . .
. . O P P P P O . . . .
. . O P P P P O . . . .
. . O S P P S O . . . .
. . . O P P O . . . . .
. . . O P P O . . . . .
. . . O P P O . . . . .
. . . O . . O . . . . .
. . O O . . O O . . . .
. . . . . . . . . . . .""",

    "mid_16x16": """\
. . . . . O O O O O . . . . . .
. . . . O H P P P O . . . . . .
. . . . O P P P P O . . . . . .
. . . . O P S P S O . . . . . .
. . . . O P P P P O . . . . . .
. . . . . O S S O . . . . . . .
. . . O O P P P P O . . . . . .
. . . O S O P P P O . . . . . .
. . . O O P P P P O . . . . . .
. . . . . O P P O . . . . . . .
. . . . . O P P O . . . . . . .
. . . . O O P P O O . . . . . .
. . . . O . . . . O . . . . . .
. . . . O O . . O O . . . . . .
. . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . .""",

    "late_16x16": """\
. . . . . O O O O O . . . . . .
. . . . O H H P P O . . . . . .
. . . . O P P P P O . . . . . .
. . . . O P S P S O . . . . . .
. . . . O D P P P O . . . . . .
. . . . . O S S O . . . . . . .
. . O O O H P P P O O . . . . .
. . O S S O P P P O H O . . . .
. . O O O D P P D O . O . . . .
. . . . . O P P O . . . . . . .
. . . . . O D D O . . . . . . .
. . . . O O P P O O . . . . . .
. . . . O D . . D O . . . . . .
. . . . O O . . O O . . . . . .
. . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . .""",

    # 32x32 grids — character centered with 2px headroom top, 2-3px floor margin
    "early_32x32": """\
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . O O O O O O O O O . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P P O . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P P O . . . . . . . . . . .
. . . . . . . . . . O P P S P P P S P P O . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P P O . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P P O . . . . . . . . . . .
. . . . . . . . . . . O P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . . O S S S S S S S O . . . . . . . . . . . .
. . . . . . . . . O O P P P P P P P P P O O . . . . . . . . . .
. . . . . . . . . O P P P P P P P P P P P O . . . . . . . . . .
. . . . . . . . . O P P P P S S P P P P P O . . . . . . . . . .
. . . . . . . . . O P P P P P P P P P P P O . . . . . . . . . .
. . . . . . . . . O P P P P P P P P P P P O . . . . . . . . . .
. . . . . . . . . O P P P P P P P P P P P O . . . . . . . . . .
. . . . . . . . . O P P P P P P P P P P P O . . . . . . . . . .
. . . . . . . . . O P P P P P P P P P P P O . . . . . . . . . .
. . . . . . . . . . O O P P P P P P P O O . . . . . . . . . . .
. . . . . . . . . . . O P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P P O . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P P O . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P P O . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P P O . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P P O . . . . . . . . . . . .
. . . . . . . . . . O O P P P . P P P O O . . . . . . . . . . .
. . . . . . . . . . O P P P . . . P P P O . . . . . . . . . . .
. . . . . . . . . . O O O O . . . O O O O . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .""",

    "mid_32x32": """\
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . O O O O O O O O . . . . . . . . . . . . .
. . . . . . . . . . O H H P P P P P O . . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P O . . . . . . . . . . . . .
. . . . . . . . . . O P P S P P S P O . . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P O . . . . . . . . . . . . .
. . . . . . . . . . O D P P P P P P O . . . . . . . . . . . . .
. . . . . . . . . . . O P P P P P O . . . . . . . . . . . . . .
. . . . . . . . . . . O S S S S S O . . . . . . . . . . . . . .
. . . . . . . . O O O H P P P P P P O O . . . . . . . . . . . .
. . . . . . . . O S S O P P P P P P O H O . . . . . . . . . . .
. . . . . . . . O O O P P P P P P P P O O . . . . . . . . . . .
. . . . . . . . . . O P P P S S P P P O . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . O D P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . . O S S P P S S O . . . . . . . . . . . . .
. . . . . . . . . . . O P P P P P P O . . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P O . . . . . . . . . . . . .
. . . . . . . . . . . O D P P . P D O . . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P O . . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P O . . . . . . . . . . . . .
. . . . . . . . . . O O P P P . P P O O . . . . . . . . . . . .
. . . . . . . . . . O D P P . . . P D O . . . . . . . . . . . .
. . . . . . . . . . O O O O . . . O O O . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .""",

    "late_32x32": """\
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . O O O O O O O O O . . . . . . . . . . . . .
. . . . . . . . . O H H H P P P P P O . . . . . . . . . . . . .
. . . . . . . . . O H P P P P P P P O . . . . . . . . . . . . .
. . . . . . . . . O P P S P P P S P O . . . . . . . . . . . . .
. . . . . . . . . O D P P P P P P P O . . . . . . . . . . . . .
. . . . . . . . . O D D P P P P P D O . . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P O . . . . . . . . . . . . . .
. . . . . . . . . . O S S S S S S O . . . . . . . . . . . . . .
. . . . . . . O O O H H P P P P P P O O O . . . . . . . . . . .
. . . . . . . O S S O H P P P P P P O H H O . . . . . . . . . .
. . . . . . . O S O O P P P P P P P P O H O . . . . . . . . . .
. . . . . . . O O . O D P P S S P P P O . O . . . . . . . . . .
. . . . . . . . . . O D P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . O D P P P P P P D O . . . . . . . . . . . .
. . . . . . . . . . O P P P P P P P P O . . . . . . . . . . . .
. . . . . . . . . . . O S S P P S S O . . . . . . . . . . . . .
. . . . . . . . . . . O P P P P P P O . . . . . . . . . . . . .
. . . . . . . . . . . O D P P P P D O . . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P O . . . . . . . . . . . . .
. . . . . . . . . . . O D P P . P D O . . . . . . . . . . . . .
. . . . . . . . . . . O P P P . P P O . . . . . . . . . . . . .
. . . . . . . . . . O O D P P . P D O O . . . . . . . . . . . .
. . . . . . . . . . O D P P . . . P D O . . . . . . . . . . . .
. . . . . . . . . . O D O O . . . O O D O . . . . . . . . . . .
. . . . . . . . . . O O O . . . . . O O O . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .
. . . . . . . . . . . . . . . . . . . . . . . . . . . . . . . .""",
}


def _vot_planning(asset_type: str, era: str, size: tuple[int, int]) -> str:
    """Return VoT ASCII planning instruction for the given asset type."""
    # Select template
    base_type = asset_type
    if asset_type in ("spritesheet", "directional"):
        base_type = "character"
    elif asset_type in ("tileset",):
        base_type = "tile"
    elif asset_type in ("ui_element", "ui_frame"):
        base_type = "item"

    template = _VOT_TEMPLATES.get(base_type, _VOT_TEMPLATES["character"])

    # Select example grid
    grid_key = f"{era}_{size[0]}x{size[1]}"
    example_grid = _VOT_EXAMPLE_GRIDS.get(grid_key, "")

    # Fallback to closest size
    if not example_grid:
        for key in [f"{era}_16x16", f"{era}_8x8", "mid_16x16"]:
            if key in _VOT_EXAMPLE_GRIDS:
                example_grid = _VOT_EXAMPLE_GRIDS[key]
                break

    return template.format(w=size[0], h=size[1], example_grid=example_grid)


# ---------------------------------------------------------------------------
# Few-shot coordinate examples
# ---------------------------------------------------------------------------

_FEW_SHOT_EXAMPLES: dict[str, str] = {
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


def _few_shot_example(era: str) -> str:
    """Return a compact reference sprite description for the given era."""
    return _FEW_SHOT_EXAMPLES.get(era, _FEW_SHOT_EXAMPLES["mid"])


# ---------------------------------------------------------------------------
# System prompt assembly
# ---------------------------------------------------------------------------

_RG013_GATING_PHRASES: tuple[str, ...] = (
    " (only when the subject names one)",
    " (only when the subject names a held item)",
    " (only when the subject names a held item or weapon)",
    " (only when the subject names them)",
    " (when the subject names one)",
    " (when the subject names a held item)",
    " (when the subject names a held item or weapon)",
    " (when the subject names them)",
)


def _strip_rg013_gating(text: str) -> str:
    """Remove rg-013 anti-bias parenthetical gates from a rendered prompt.

    rg-023 bake-off uses this to isolate Haiku's raw 16x16 ceiling from the
    prompt-budget cost of the gating language. NOT for production paths.
    """
    out = text
    for phrase in _RG013_GATING_PHRASES:
        out = out.replace(phrase, "")
    return out


def _build_system_prompt(
    era: str,
    asset_type: str,
    size: tuple[int, int],
    view: str,
    outline: str,
    colors: list[str],
    roles: dict[str, str],
    tool_rules_text: str,
    drawing_order_text: str,
    console: str = "nes",
    prompt_topology: str = "era_first",
    disable_rg013_gating: bool = False,
    auto_shading_16x16: bool = False,
) -> str:
    """Assemble the full system prompt from all sections.

    rg-023 bake-off knobs:
      prompt_topology: "era_first" (default) or "topology_first" — reorders
        sections so canvas-shape rules come before era-fidelity rules.
      disable_rg013_gating: strip the "only when the subject names one"
        parentheticals from the rendered prompt to free up prompt budget at
        16x16. Bake-off only.
      auto_shading_16x16: extends the 32x32+ post-draw validation gate to
        16x16 mid/late on 16-bit consoles.
    """
    ec = _era_constraints(era, console)

    # Build all named sections first, then assemble in the chosen order.
    slots: dict[str, str] = {}

    slots["identity"] = (
        f"You are a pixel artist drawing a {size[0]}x{size[1]} pixel sprite "
        f"in Aseprite using MCP tools.\n"
        f"Era: {ec['label']}. Maximum {len(colors)} opaque colors plus transparency.\n"
        f"Reference games from this era: {ec['reference_games']}.\n"
        f"Every pixel placement is deliberate. You are constructing pixel art, "
        f"not generating an image."
    )

    slots["palette_rules"] = _palette_rules(era, colors, roles, console=console)
    slots["color_theory"] = _color_theory_rules(era)
    slots["tool_rules"] = tool_rules_text
    slots["proportions"] = _proportion_rules(asset_type, era, size, console=console)

    if asset_type not in ("tile", "tileset", "ui_element", "ui_frame"):
        view_text = None
        try:
            pd = get_prompt_data(console)
            view_text = pd.view_rules.get(view)
        except (NotImplementedError, KeyError):
            pass
        if view_text is None:
            view_text = _view_rules(view)
        slots["view"] = view_text

    slots["vot_planning"] = _vot_planning(asset_type, era, size)

    # Few-shot reference example (size-aware lookup).
    few_shot = None
    try:
        pd = get_prompt_data(console)
        few_shot = pd.few_shot_examples.get(f"{era}_{size[0]}x{size[1]}")
        if few_shot is None:
            few_shot = pd.few_shot_examples.get(era)
    except (NotImplementedError, KeyError):
        pass
    if few_shot is None:
        few_shot = _few_shot_example(era)
    slots["few_shot"] = few_shot

    slots["drawing_order"] = drawing_order_text

    # Post-draw canvas utilization check.
    # Default: 32x32+ only. rg-023 trial: optionally extend to 16x16 mid/late.
    validation_eligible = (
        max(size) >= 24
        or (max(size) == 16 and auto_shading_16x16 and era in ("mid", "late"))
    )
    if validation_eligible and asset_type not in ("tile", "tileset"):
        is_item = asset_type in ("item",)
        h_pct = 0.65 if is_item else 0.70
        h_min = int(size[1] * h_pct)
        w_min = int(size[0] * 0.45)
        slots["post_draw_validation"] = (
            "MANDATORY VALIDATION — YOU MUST DO THIS AFTER EVERY SPRITE:\n"
            "Call get_sprite_info and check the opaque content bounding box.\n"
            "Minimum thresholds:\n"
            f"- Height: at least {h_min}px ({int(h_pct * 100)}% of {size[1]}px canvas)\n"
            f"- Width: at least {w_min}px (45% of {size[0]}px canvas)\n"
            f"If the content is smaller than this, you drew a "
            f"{size[0]//2}x{size[1]//2} sprite in a {size[0]}x{size[1]} canvas. "
            f"Erase and redraw LARGER — fill the space.\n"
            "Common mistake: drawing at the same scale you would for 16x16, "
            "leaving most of the canvas empty.\n"
            "DO NOT SKIP THIS STEP. Every sprite must be validated. No exceptions."
        )

    # Section ordering.
    # era_first (default, current production behavior): identity + palette/color/tool
    # context first, then proportions/view, then vot/few-shot/drawing order,
    # then post-draw validation.
    # topology_first (rg-023 bake-off probe): identity + proportions/view/drawing-order
    # first (what shape am I drawing), then era constraints layered on
    # (palette/color/tool/few-shot), then vot/post-draw.
    # Hammerstein hypothesis: at 16x16, the model gets crushed by era detail
    # collapsing into a 256-pixel budget. Topology-first frames the task as
    # "draw a clean readable 16x16 X, then apply era constraints" which may
    # clear the ceiling without changing models.
    if prompt_topology == "topology_first":
        order = [
            "identity",
            "proportions",
            "view",
            "drawing_order",
            "palette_rules",
            "color_theory",
            "tool_rules",
            "few_shot",
            "vot_planning",
            "post_draw_validation",
        ]
    else:
        order = [
            "identity",
            "palette_rules",
            "color_theory",
            "tool_rules",
            "proportions",
            "view",
            "vot_planning",
            "few_shot",
            "drawing_order",
            "post_draw_validation",
        ]

    sections = [slots[name] for name in order if name in slots]
    rendered = "\n\n".join(sections)

    if disable_rg013_gating:
        rendered = _strip_rg013_gating(rendered)

    return rendered


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def build_mcp_prompt(
    description: str,
    asset_type: str = "character",
    size: tuple[int, int] = (16, 16),
    view: str = "side",
    palette_mood: str = "auto",
    outline: str = "Black",
    era: str = "mid",
    frame_count: int = 4,
    animation_type: str = "walk",
    palette_colors: list[str] | None = None,
    seed: int | None = None,
    console: str = "nes",
    prompt_topology: str = "era_first",
    disable_rg013_gating: bool = False,
    auto_shading_16x16: bool = False,
) -> dict:
    """
    Build a structured MCP prompt for Claude API sprite generation.

    Same parameters as prompts.build_prompt(), completely different output.
    Returns a dict with system_prompt, user_prompt, canvas spec, palette,
    constraints, and tool whitelist/blacklist.

    rg-023 bake-off knobs (default off; production callers ignore them):
      prompt_topology: "era_first" or "topology_first" — section ordering.
      disable_rg013_gating: strip rg-013 anti-bias parentheticals.
      auto_shading_16x16: extend the 32x32+ auto_shading mandate to 16x16
        mid/late on 16-bit consoles.
    """
    # Validate era
    era = era.lower() if isinstance(era, str) else "mid"
    if era not in _ERA_CONSTRAINTS:
        era = "mid"

    # Infer mood from description when set to "auto"
    if palette_mood == "auto":
        inferred = _infer_mood_from_description(description)
        if inferred:
            palette_mood = inferred

    # Validate asset_type
    valid_types = {
        "character", "enemy", "item", "tile", "tileset",
        "spritesheet", "directional", "ui_element", "ui_frame",
    }
    if asset_type not in valid_types:
        asset_type = "character"

    # Resolve palette
    colors, roles = _resolve_palette(era, palette_mood, palette_colors, outline, asset_type, console=console)

    # Get tool rules (size-aware for 32x32+ auto_shading on 16-bit consoles)
    tool_rules_text, whitelist, blacklist = _tool_rules(
        era, asset_type, console=console, size=size,
        auto_shading_16x16=auto_shading_16x16,
    )

    # Get outline color for drawing order
    outline_color = colors[0] if era == "late" else "#000000"

    # Get drawing order
    drawing_order_text = _drawing_order(
        era, asset_type, size, len(colors), outline_color,
        auto_shading_16x16=auto_shading_16x16,
    )

    # Build system prompt
    system_prompt = _build_system_prompt(
        era=era,
        asset_type=asset_type,
        size=size,
        view=view,
        outline=outline,
        colors=colors,
        roles=roles,
        tool_rules_text=tool_rules_text,
        drawing_order_text=drawing_order_text,
        console=console,
        prompt_topology=prompt_topology,
        disable_rg013_gating=disable_rg013_gating,
        auto_shading_16x16=auto_shading_16x16,
    )

    # Apply rg-013 strip to tool_rules_text too (it's returned to the caller
    # for whitelist/blacklist context but also embedded in system_prompt; the
    # latter was already stripped in _build_system_prompt).
    if disable_rg013_gating:
        tool_rules_text = _strip_rg013_gating(tool_rules_text)

    # Build user prompt — simple and direct
    palette_str = ", ".join(f"{c} ({roles.get(c, 'extra')})" for c in colors)
    user_prompt = (
        f"Draw a {asset_type}: {description}\n\n"
        f"View: {view}\n"
        f"Canvas: {size[0]}x{size[1]} pixels\n"
        f"Palette: {palette_str}\n\n"
        "Begin by calling create_canvas, then set_palette, "
        "then follow the DRAW ORDER in your instructions."
    )

    return {
        "system_prompt": system_prompt,
        "user_prompt": user_prompt,
        "canvas": {
            "width": size[0],
            "height": size[1],
            "color_mode": "rgb",
        },
        "palette": {
            "colors": colors,
            "roles": roles,
        },
        "constraints": {
            "max_colors": len(colors),
            "outline_style": outline,
        },
        "tool_whitelist": whitelist,
        "tool_blacklist": blacklist,
    }


def build_mcp_frame_prompt(
    description: str,
    asset_type: str,
    frame_index: int,
    frame_total: int,
    is_reference_frame: bool = False,
    animation_type: str = "walk",
    tile_position: str | None = None,
    view: str = "side",
    palette_mood: str = "auto",
    outline: str = "Black",
    era: str = "mid",
    palette_colors: list[str] | None = None,
    sprite_path: str | None = None,
    console: str = "nes",
) -> dict:
    """
    Build an MCP prompt for a single frame in a multi-frame generation.

    For animations: frame_index is 0-based, frame_total is the count.
    For tilesets: tile_position identifies which tile in the 3x3 grid.

    The reference frame (frame 0) uses build_mcp_prompt directly.
    Follow-up frames get animation/tile constraints added.
    """
    # Reference frame — use standard prompt
    if is_reference_frame or frame_index == 0:
        base = build_mcp_prompt(
            description=description,
            asset_type="character" if asset_type == "spritesheet" else asset_type,
            size=_era_constraints(era, console).get("default_size", (16, 16)),
            view=view,
            palette_mood=palette_mood,
            outline=outline,
            era=era,
            palette_colors=palette_colors,
            console=console,
        )
        # Add note that this is frame 1 of a sequence
        if asset_type in ("spritesheet", "directional"):
            base["user_prompt"] += (
                f"\n\nThis is frame 1 of {frame_total} in a {animation_type} animation. "
                "Draw the neutral/starting pose."
            )
        elif asset_type == "tileset" and tile_position:
            hint = _TILE_EDGE_HINTS.get(tile_position, "")
            base["user_prompt"] += f"\n\nTile position: {tile_position}. {hint}"
        return base

    # Follow-up frames — add animation or tileset rules
    base = build_mcp_prompt(
        description=description,
        asset_type="character" if asset_type == "spritesheet" else asset_type,
        size=_era_constraints(era, console).get("default_size", (16, 16)),
        view=view,
        palette_mood=palette_mood,
        outline=outline,
        era=era,
        palette_colors=palette_colors,
        console=console,
    )

    # Add animation rules to system prompt
    if asset_type in ("spritesheet", "directional"):
        anim_rules = _animation_rules(animation_type, frame_index, frame_total)
        base["system_prompt"] += "\n\n" + anim_rules
        base["user_prompt"] = (
            f"Draw frame {frame_index + 1} of {frame_total} "
            f"for a {animation_type} animation: {description}\n\n"
            f"View: {view}\n"
            f"Canvas: {base['canvas']['width']}x{base['canvas']['height']} pixels\n"
            f"Palette: {', '.join(base['palette']['colors'])} (LOCKED — same as frame 1)\n\n"
            "Follow the DRAW ORDER and ANIMATION rules in your instructions."
        )
        if sprite_path:
            base["user_prompt"] += (
                f"\n\nReference sprite (frame 1): {sprite_path}"
            )

    # Add tileset rules
    elif asset_type == "tileset" and tile_position:
        hint = _TILE_EDGE_HINTS.get(tile_position, "")
        base["system_prompt"] += f"""

TILESET COHERENCE:
- This tile is part of a 9-tile connected tileset.
- Palette is LOCKED to the center tile's palette. Use set_palette with the exact same colors.
- Tile position: {tile_position}. {hint}
- Edge pixels along connecting sides must use the same colors at matching positions as the adjacent tile."""

        base["user_prompt"] = (
            f"Draw the {tile_position} tile for a tileset: {description}\n\n"
            f"Canvas: {base['canvas']['width']}x{base['canvas']['height']} pixels\n"
            f"Palette: {', '.join(base['palette']['colors'])} (LOCKED — same as center tile)\n\n"
            "Follow the DRAW ORDER and TILESET COHERENCE rules."
        )
        if sprite_path:
            base["user_prompt"] += (
                f"\n\nReference tile (center): {sprite_path}"
            )

    return base

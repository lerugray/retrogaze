"""
Prompt builder for Retrogaze image generation.

Assembles the full prompt and negative prompt strings that get sent to the
image generation API based on the user's asset options.
"""

from __future__ import annotations

import re
from collections import defaultdict

from .console_prompt_data import get_prompt_data

# rg-013: anti-bias keyword sets. Two reported failures (moontini's
# "street punks for a beat-em-up" returning swords + armor; Ricky Moses'
# "witch wearing tattered clothes" returning a witch with sword + buckler)
# both stemmed from gallery baselines being 100% fantasy/RPG and FLUX
# defaulting under-determination toward its training median (fantasy).
# When the description lacks these anchors, we inject explicit
# scoping clauses to keep the output true to the requested subject.
_FANTASY_ANCHOR_KEYWORDS = frozenset({
    "knight", "wizard", "mage", "sorcerer", "warlock", "witch",
    "paladin", "barbarian", "ranger", "rogue", "cleric",
    "necromancer", "druid", "monk", "bard", "warrior",
    "skeleton", "goblin", "orc", "demon", "elf", "dwarf", "ogre",
    "troll", "dragon", "slime", "fairy", "phoenix", "gryphon",
    "unicorn", "minotaur", "lich", "wraith", "vampire",
    "scroll", "potion", "elixir", "rune", "amulet", "talisman",
    "spellbook", "spell",
    "dungeon", "castle", "medieval", "fantasy", "magic", "magical",
    "enchanted", "cursed", "kingdom", "wizardry",
})

_EQUIPMENT_KEYWORDS = frozenset({
    "weapon", "weapons", "armed",
    "sword", "knife", "dagger", "blade", "machete", "katana",
    "axe", "hatchet", "mace", "club", "hammer",
    "spear", "lance", "halberd", "staff", "wand", "scythe",
    "bow", "crossbow", "arrow", "pistol", "gun", "rifle",
    "shotgun", "blaster", "phaser", "raygun", "uzi",
    "shield", "buckler", "armor", "helmet", "gauntlet",
    "chainsaw",
})


def _has_anchor_keyword(description: str, keywords: frozenset[str]) -> bool:
    """Whole-word, case-insensitive keyword presence check."""
    if not description:
        return False
    desc_lower = description.lower()
    for kw in keywords:
        if re.search(r"\b" + re.escape(kw) + r"\b", desc_lower):
            return True
    return False


_BIAS_APPLICABLE_ASSET_TYPES = frozenset({
    "character", "enemy", "spritesheet", "directional",
})


def _bias_clauses(description: str, asset_type: str) -> str:
    """
    Return any anti-bias clauses to append to the prompt.

    Only applies to character-equivalent asset types (single character,
    enemy, animated spritesheet, directional turnaround). Tiles, items,
    and UI elements aren't subject to the fantasy/equipment bias.
    Returns empty string when no clauses needed.
    """
    if asset_type not in _BIAS_APPLICABLE_ASSET_TYPES:
        return ""
    clauses: list[str] = []
    if not _has_anchor_keyword(description, _FANTASY_ANCHOR_KEYWORDS):
        clauses.append(
            "Match the contemporary, modern, or real-world setting that the subject implies. "
            "The character's outfit, posture, and accessories belong to the era or genre named."
        )
    if not _has_anchor_keyword(description, _EQUIPMENT_KEYWORDS):
        clauses.append(
            "The character holds only what the subject names. "
            "Many characters carry nothing in their hands."
        )
    return " ".join(clauses)

# ---------------------------------------------------------------------------
# Asset type prompt templates
# ---------------------------------------------------------------------------

_ANIMATION_TYPES: dict[str, str] = {
    "walk":   "walk cycle",
    "idle":   "idle breathing",
    "attack": "attack swing",
    "run":    "run cycle",
    "jump":   "jump arc",
    "death":  "death falling",
    "cast":   "spell casting",
}

_TEMPLATES: dict[str, str] = {
    "spritesheet": (
        "Pixel art sprite sheet, {era_style}. "
        "{frame_count} animation frames of the same character arranged in a single horizontal row. "
        "Each frame shows a different pose in the {animation_type} animation sequence. "
        "All frames must show the SAME character with consistent proportions, colors, and style. "
        "Only 3-4 flat colors total, {outline} outline. "
        "No dithering, no anti-aliasing, no gradients. "
        "Frames evenly spaced on solid single-color background. "
        "Each pixel is a clearly visible square block. "
        "{era_style_ref} "
        "Subject: {description}, {view} view."
    ),
    "character": (
        "Single pixel art character sprite, {era_style}. "
        "Chunky proportions, large head, short body. Only 3-4 flat colors total, "
        "{outline} outline. No dithering, no anti-aliasing, no gradients, no smooth edges, no background scenery. "
        "Sharp pixel edges. "
        "Single directional light from top-left only — darker values only on bottom and right edges. No pillow shading (do not shade from all sides equally). "
        "IMPORTANT: The character MUST have both legs visible and both arms visible. "
        "Match the character's items, accessories, and equipment exactly to the subject description. "
        "Full body from head to feet, centered on solid single-color background. "
        "Each pixel is a clearly visible square block. "
        "{era_style_ref} "
        "Subject: {description}, {view} view, full body with all limbs and equipment visible."
    ),
    "enemy": (
        "Single pixel art enemy creature sprite, {era_style}. "
        "Simple bold silhouette, only 3-4 flat colors total, {outline} outline. "
        "No dithering, no anti-aliasing, no smooth gradients, no background scenery. "
        "Full creature visible from head to feet or tail. No cropping, no partial body. "
        "Sharp pixel edges. Fills most of the canvas, centered on solid single-color background. "
        "Each pixel is a clearly visible square block. "
        "{era_style_ref} "
        "Subject: {description}."
    ),
    "item": (
        "Single large pixel art game item, {era_style}. "
        "Bold iconic silhouette, only 3-4 flat colors. "
        "No dithering, no anti-aliasing, no smooth gradients, no background scenery. "
        "No character, no hands, no person — just the item itself, drawn large and centered. "
        "Sharp pixel edges. Item fills most of the canvas on solid single-color background. "
        "Each pixel is a clearly visible square block. "
        "{era_style_ref} "
        "Subject: {description}."
    ),
    "tile": (
        "Seamless tileable pixel art tile in authentic {era_style}, 8x8 pixels. "
        "Use a mid-to-light value range for the main fill — avoid dark fills that collapse to a single tone when downscaled. "
        "The ENTIRE tile must be filled with the pattern — no empty space, no isolated objects. "
        "The pattern covers every pixel with a clear, distinct texture. "
        "Use 3-4 colors with visible contrast between pattern elements. "
        "Flat color fills, no dithering, no gradients. "
        "Must tile perfectly when repeated in a grid — edges match seamlessly. Sharp pixel edges. "
        "Show clear structural detail: individual bricks, stones, planks, or blades of grass "
        "should be distinguishable. Bold color contrast between elements and mortar/gaps. "
        "{era_tile_ref} "
        "Subject: {description} surface texture pattern."
    ),
    "ui_element": (
        "Pixel art UI element in authentic {era_style}, {width}x{height} pixels on "
        "transparent background. Clean, readable game interface component. Maximum 3 colors "
        "plus transparency. Sharp pixel edges, no anti-aliasing. High contrast for readability. "
        "Style reference: Final Fantasy menu borders, Legend of Zelda HUD, Super Mario Bros "
        "score display. Subject: {description}."
    ),
    "ui_frame": (
        "Pixel art bordered text box frame in authentic {era_style}. Built from 8x8 "
        "corner tiles and 8x8 edge tiles that tile to form a resizable window. Maximum 3 colors "
        "plus background. Clean geometric borders. Style reference: Final Fantasy and Dragon "
        "Warrior dialog boxes. Output as a tile set: 4 corners + 4 edges + 1 fill. "
        "Subject: {description}."
    ),
    "tileset": (
        "Pixel art connected tileset in authentic {era_style}. "
        "A 3x3 grid showing 9 connected tiles that form a complete terrain patch: "
        "top-left corner, top edge, top-right corner (top row), "
        "left edge, center fill, right edge (middle row), "
        "bottom-left corner, bottom edge, bottom-right corner (bottom row). "
        "All 9 tiles must share the same palette and style. "
        "Edge tiles must connect seamlessly to center fill tiles. "
        "Corner tiles must connect to both adjacent edges. "
        "Maximum 3 colors plus background. Flat color fills, no dithering, no gradients. "
        "Sharp pixel edges. Each tile is 8x8 pixels. "
        "{era_tile_ref} "
        "Subject: {description} terrain."
    ),
    "directional": (
        "Pixel art character turnaround sprite sheet, {era_style}. "
        "Exactly 4 full-body character views in a single horizontal row, evenly spaced: "
        "1) front facing view, 2) right side view, 3) back view, 4) left side view. "
        "Every view shows the COMPLETE CHARACTER from head to feet, with items appearing only as part of the character's outfit. "
        "All 4 views must have identical proportions, colors, outfit, and equipment. "
        "Only 3-4 flat colors total, {outline} outline. "
        "No dithering, no anti-aliasing, no gradients. "
        "No separate objects — only the character in 4 rotations. "
        "Views evenly spaced on solid single-color background. "
        "Each pixel is a clearly visible square block. "
        "{era_style_ref} "
        "Subject: {description}."
    ),
}

# Valid era keys — used for input validation only.
# Actual era text is sourced from console_prompt_data.py per console.
_VALID_ERAS = {"retro", "early", "mid", "late"}

# Asset types whose prompts describe a living subject's anatomy, outfit, and
# equipment. Every other type (item, tile, tileset, UI) must use the
# subject-neutral era ref: some eras describe their reference games in
# character-only terms ("expressive face, detailed armor" for NES late;
# "expressive character design" for SNES late). Injected into an item prompt,
# that language contradicts the item framing ("no character, no hands") and
# FLUX resolves it toward a character — the reported item + late era bug.
_CHARACTER_ASSET_TYPES = frozenset({
    "character", "enemy", "spritesheet", "directional",
})


def _era_style_ref(era_data, asset_type: str) -> str:
    """Pick the era style anchor for *asset_type*.

    Character-equivalent types keep the rich ``style_ref`` (armor, faces,
    expressive design). Non-character types prefer the subject-neutral
    ``object_ref`` when the era defines one, so the anchor never asks for
    anatomy the template forbids.
    """
    if asset_type not in _CHARACTER_ASSET_TYPES and era_data.object_ref:
        return era_data.object_ref
    return era_data.style_ref

_PROPORTION_HINTS: dict[str, str] = {
    "character": (
        "Chibi proportions: head is one-third of total body height. "
        "Short stubby limbs, oversized head and eyes relative to body. "
        "Two to three head-heights tall total."
    ),
    "enemy": (
        "Simple compact proportions. Body is a single bold shape. "
        "No fine anatomical detail — readable at tiny pixel sizes."
    ),
}


_PALETTE_MOOD_HINTS: dict[str, str] = {
    "warm": "warm color palette with oranges and reds",
    "cool": "cool color palette with blues and greens",
    "dark": "dark moody color palette",
    "bright": "bright vibrant color palette",
    "earth": "earth tone palette with browns and greens",
    "auto": "",
}


# ---------------------------------------------------------------------------
# Per-frame prompt data (Wave 3: individual frame generation)
# ---------------------------------------------------------------------------

_POSE_DESCRIPTIONS: dict[str, dict[tuple[int, int], str]] = {
    "walk": {
        (0, 2): "contact position, one foot forward, arms at sides",
        (1, 2): "passing position, legs crossing under body, arms swinging",
        (0, 4): "contact position, left foot forward, right foot back",
        (1, 4): "first passing position, legs crossing, arms swinging forward",
        (2, 4): "contact position mirrored, right foot forward, left foot back",
        (3, 4): "second passing position, legs crossing, arms swinging back",
    },
    "run": {
        (0, 2): "push-off position, back leg extended, front leg bent",
        (1, 2): "airborne flight phase, both legs tucked under body",
        (0, 4): "push-off, back leg extended, front knee driving up",
        (1, 4): "airborne flight, both legs tucked under body",
        (2, 4): "landing, front leg reaching forward, back leg trailing",
        (3, 4): "recovery, legs switching, arms pumping opposite",
    },
    "idle": {
        (0, 2): "standing still, arms at sides, neutral pose",
        (1, 2): "slight chest rise, breathing in, arms unchanged",
        (0, 4): "neutral standing pose, weight centered",
        (1, 4): "slight shift, chest rising, subtle breathing",
        (2, 4): "neutral standing pose, weight centered",
        (3, 4): "slight shift, chest lowering, exhaling",
    },
    "attack": {
        (0, 2): "standing ready, weapon held at chest height",
        (1, 2): "weapon swung forward to shoulder height, slight lean",
        (0, 4): "standing ready, weapon held at chest height",
        (1, 4): "weapon raised to shoulder, slight body turn",
        (2, 4): "weapon extended forward at chest height, small step",
        (3, 4): "weapon returning to chest, body straightening",
    },
    "jump": {
        (0, 2): "crouching, knees bent, arms at sides, preparing to jump",
        (1, 2): "in the air, both feet off the ground, body compact, arms up",
        (0, 4): "crouching, knees bent, arms at sides, preparing to jump",
        (1, 4): "pushing off, knees straightening, feet leaving ground",
        (2, 4): "airborne at peak, both feet clearly off ground, body compact",
        (3, 4): "descending, legs extending down, arms lowering for landing",
    },
    "death": {
        (0, 2): "standing upright, reacting to a hit, slight backward lean",
        (1, 2): "on knees, body slumped forward, arms hanging",
        (0, 4): "standing upright, flinching from hit, body recoiling",
        (1, 4): "stumbling, one knee bending, body leaning back",
        (2, 4): "dropping to knees, arms going limp, head tilting",
        (3, 4): "on knees, body slumped forward, arms hanging down",
    },
    "cast": {
        (0, 2): "standing with hands together at chest",
        (1, 2): "hands raised to head height, small glow near hands",
        (0, 4): "standing with hands at sides, same pose and proportions",
        (1, 4): "same standing pose, hands raised to chest height",
        (2, 4): "hands raised to head height, small glow between hands",
        (3, 4): "hands pushing forward at chest height, glow released",
    },
}

_DIRECTION_LABELS: dict[int, str] = {
    0: "front facing",
    1: "right side profile",
    2: "back facing, seen from behind",
    3: "left side profile",
}

_DIRECTION_NAMES: list[str] = ["front", "right", "back", "left"]

_TILE_POSITIONS: list[str] = [
    "center",
    "top", "bottom", "left", "right",
    "top_left", "top_right", "bottom_left", "bottom_right",
]

_TILE_EDGE_HINTS: dict[str, str] = {
    "center": "The interior fill tile. Edges must be seamless in all directions when tiled.",
    "top": "Top edge tile. Bottom edge must connect seamlessly to the center tile.",
    "bottom": "Bottom edge tile. Top edge must connect seamlessly to the center tile.",
    "left": "Left edge tile. Right edge must connect seamlessly to the center tile.",
    "right": "Right edge tile. Left edge must connect seamlessly to the center tile.",
    "top_left": "Top-left corner tile. Bottom and right edges connect to adjacent edge tiles.",
    "top_right": "Top-right corner tile. Bottom and left edges connect to adjacent edge tiles.",
    "bottom_left": "Bottom-left corner tile. Top and right edges connect to adjacent edge tiles.",
    "bottom_right": "Bottom-right corner tile. Top and left edges connect to adjacent edge tiles.",
}

# Per-frame templates: describe ONE image of ONE frame, never a sheet/row/grid.
_FRAME_TEMPLATES: dict[str, str] = {
    "spritesheet_ref": (
        "Single pixel art character sprite, {era_style}. "
        "Chunky proportions, large head, short body. "
        "Full body from head to feet, centered on solid single-color background. "
        "{outline} outline. "
        "No dithering, no anti-aliasing, no gradients, no background scenery. "
        "Each pixel is a clearly visible square block. "
        "ALL described weapons and items MUST be clearly visible. "
        "{era_style_ref} "
        "Subject: {description}, {view} view, full body with all limbs and equipment visible."
    ),
    "spritesheet_follow": (
        "Single pixel art character sprite, {era_style}. "
        "Chunky proportions, large head, short body. "
        "This is frame {frame_1based} of {frame_total} in a {animation_type} animation. "
        "{pose_description}. "
        "The character must match the reference exactly: same colors, proportions, outfit, and equipment. "
        "{outline} outline. "
        "No dithering, no anti-aliasing, no gradients, no background scenery. "
        "Full body from head to feet, centered on solid single-color background. "
        "Each pixel is a clearly visible square block. "
        "{era_style_ref} "
        "Subject: {description}, {view} view."
    ),
    "directional_ref": (
        "Single pixel art character sprite, {era_style}. "
        "{direction_label} view of a game character. "
        "Full body from head to feet, centered on solid single-color background. "
        "Only 3-4 flat colors total, {outline} outline. "
        "No dithering, no anti-aliasing, no gradients. "
        "Each pixel is a clearly visible square block. "
        "{era_style_ref} "
        "Subject: {description}."
    ),
    "directional_follow": (
        "Single pixel art character sprite, {era_style}. "
        "{direction_label} view of a game character. "
        "The character must match the reference exactly: same colors, proportions, outfit, and equipment. "
        "Only 3-4 flat colors total, {outline} outline. "
        "No dithering, no anti-aliasing, no gradients. "
        "Full body from head to feet, centered on solid single-color background. "
        "Each pixel is a clearly visible square block. "
        "{era_style_ref} "
        "Subject: {description}."
    ),
    "tileset_ref": (
        "Single pixel art terrain tile, {era_style}. "
        "This is the center fill tile of a connected terrain set. "
        "The ENTIRE tile must be filled with the pattern — no empty space. "
        "Maximum 3 colors, flat fills, no dithering, no gradients. "
        "Sharp pixel edges. {era_tile_ref} "
        "Subject: {description} surface texture."
    ),
    "tileset_follow": (
        "Single pixel art terrain tile, {era_style}. "
        "This is the {tile_position} tile of a connected terrain set. "
        "{tile_edge_hint} "
        "Must use the same colors, texture style, and pixel density as the reference center tile. "
        "The ENTIRE tile must be filled with the pattern — no empty space. "
        "Maximum 3 colors, flat fills, no dithering, no gradients. "
        "Sharp pixel edges. {era_tile_ref} "
        "Subject: {description} surface texture."
    ),
}


def build_frame_prompt(
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
    console: str = "nes",
) -> dict[str, str]:
    """
    Build a prompt for a single frame/tile in a multi-frame generation.

    Unlike ``build_prompt()``, this describes ONE image — never a sheet, row, or
    grid. For follow-up frames (not the reference), includes language to match
    the reference frame.

    Returns ``{"prompt": str, "negative_prompt": ""}``
    """
    description = description.strip()
    era = era.lower() if isinstance(era, str) else "mid"
    if era not in _VALID_ERAS:
        era = "mid"

    prompt_data = get_prompt_data(console)
    era_data = prompt_data.eras.get(era, prompt_data.eras.get("mid"))
    era_style = era_data.label
    era_style_ref = _era_style_ref(era_data, asset_type)
    era_tile_ref = era_data.tile_ref

    # Pick the right template
    if asset_type == "tileset":
        if is_reference_frame:
            template_key = "tileset_ref"
        else:
            template_key = "tileset_follow"
    elif asset_type == "directional":
        if is_reference_frame:
            template_key = "directional_ref"
        else:
            template_key = "directional_follow"
    else:
        # spritesheet
        if is_reference_frame:
            template_key = "spritesheet_ref"
        else:
            template_key = "spritesheet_follow"

    template = _FRAME_TEMPLATES[template_key]

    # Resolve pose description for animation frames
    anim_key = animation_type.lower()
    anim_label = _ANIMATION_TYPES.get(anim_key, animation_type)
    pose_key = (frame_index, frame_total)
    pose_map = _POSE_DESCRIPTIONS.get(anim_key, {})
    pose_description = pose_map.get(
        pose_key,
        f"frame {frame_index + 1} of {frame_total} showing progressive motion",
    )

    # Resolve direction label
    direction_label = _DIRECTION_LABELS.get(frame_index, f"view {frame_index + 1}")

    # Resolve tile position and edge hint
    tile_pos = tile_position or "center"
    tile_edge_hint = _TILE_EDGE_HINTS.get(tile_pos, "")

    format_values = defaultdict(str,
        description=description,
        view=view,
        outline=outline,
        era_style=era_style,
        era_style_ref=era_style_ref,
        era_tile_ref=era_tile_ref,
        frame_1based=frame_index + 1,
        frame_total=frame_total,
        animation_type=anim_label,
        pose_description=pose_description,
        direction_label=direction_label,
        tile_position=tile_pos,
        tile_edge_hint=tile_edge_hint,
    )
    prompt = template.format_map(format_values)

    bias_text = _bias_clauses(description, asset_type)
    if bias_text:
        prompt = f"{prompt} {bias_text}"

    # Append palette mood hint
    palette_mood = palette_mood.lower()
    mood_hint = _PALETTE_MOOD_HINTS.get(palette_mood, "")
    if mood_hint:
        prompt = f"{prompt} Use a {mood_hint}."
    elif asset_type == "tileset" and not palette_colors:
        desc_lower = description.lower()
        for keywords, hint in prompt_data.terrain_color_hints:
            if any(kw in desc_lower for kw in keywords):
                prompt = f"{prompt} {hint}"
                break

    # Append palette lock
    if palette_colors:
        color_list = ", ".join(palette_colors)
        prompt = f"{prompt} Use ONLY these exact colors: {color_list}. No other colors allowed."

    return {"prompt": prompt, "negative_prompt": ""}


def build_prompt(
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
) -> dict[str, str]:
    """
    Assemble a generation prompt dict from user options.

    Parameters
    ----------
    description:
        Free-text description of the subject to generate.
    asset_type:
        One of ``"character"``, ``"enemy"``, ``"item"``, ``"tile"``,
        ``"ui_element"``, ``"ui_frame"``, or ``"spritesheet"``.
    size:
        ``(width, height)`` in pixels for the target NES asset.
    view:
        Camera view for character/enemy types — ``"side"``, ``"front"``,
        ``"top-down"``, or ``"3/4"``.
    palette_mood:
        Color mood hint — ``"warm"``, ``"cool"``, ``"dark"``, ``"bright"``,
        ``"earth"``, or ``"auto"`` (no hint added).
    outline:
        Outline style — ``"Black"``, ``"Dark"``, or ``"No"``.
    era:
        NES era style — ``"early"`` (1983-84), ``"mid"`` (1985-86, default),
        or ``"late"`` (1987+). Falls back to ``"mid"`` for unknown values.
    frame_count:
        Number of animation frames (spritesheet type only). Defaults to 4.
    animation_type:
        Animation type short name (spritesheet type only): walk, idle, attack,
        run, jump, death, cast. Defaults to ``"walk"``.
    palette_colors:
        Optional list of hex color strings (e.g. ``["#000000", "#F83800"]``).
        When provided, appends a strict color constraint to the prompt.
    seed:
        Optional random seed for reproducible generation. Passed through to
        the generation API; not used in prompt construction.

    Returns
    -------
    dict
        ``{"prompt": str, "negative_prompt": str}``
    """
    if not isinstance(description, str):
        raise TypeError("description must be a string")
    if len(description) > 500:
        raise ValueError("description must be 500 characters or fewer")
    description = description.strip()

    if not (2 <= frame_count <= 8):
        raise ValueError(
            f"frame_count must be between 2 and 8 inclusive, got {frame_count!r}"
        )

    asset_type = asset_type.lower()
    if asset_type not in _TEMPLATES:
        raise ValueError(
            f"Unknown asset_type {asset_type!r}. "
            f"Valid types: {list(_TEMPLATES.keys())}"
        )

    palette_mood = palette_mood.lower()
    if palette_mood not in _PALETTE_MOOD_HINTS:
        palette_mood = "auto"

    era = era.lower() if isinstance(era, str) else "mid"
    if era not in _VALID_ERAS:
        era = "mid"

    width, height = size
    template = _TEMPLATES[asset_type]

    # Resolve animation_type short name to descriptive text
    anim_label = _ANIMATION_TYPES.get(animation_type.lower(), animation_type)

    # Resolve era-adaptive placeholders from console prompt data
    prompt_data = get_prompt_data(console)
    era_data = prompt_data.eras.get(era, prompt_data.eras.get("mid"))
    era_style = era_data.label
    era_style_ref = _era_style_ref(era_data, asset_type)
    era_tile_ref = era_data.tile_ref

    format_values = defaultdict(str,
        description=description,
        width=width,
        height=height,
        view=view,
        outline=outline,
        frame_count=frame_count,
        animation_type=anim_label,
        era_style=era_style,
        era_style_ref=era_style_ref,
        era_tile_ref=era_tile_ref,
    )
    prompt = template.format_map(format_values)

    bias_text = _bias_clauses(description, asset_type)
    if bias_text:
        prompt = f"{prompt} {bias_text}"

    # Append palette mood hint when specified
    mood_hint = _PALETTE_MOOD_HINTS[palette_mood]
    if mood_hint:
        prompt = f"{prompt} Use a {mood_hint}."
    elif asset_type in ("tile", "tileset") and not palette_colors:
        # Auto-detect terrain type and add color guidance for tiles
        # so FLUX doesn't choose bizarre colors for common surfaces
        desc_lower = description.lower()
        for keywords, hint in prompt_data.terrain_color_hints:
            if any(kw in desc_lower for kw in keywords):
                prompt = f"{prompt} {hint}"
                break

    # Append palette lock hint when specific colors are requested
    if palette_colors:
        color_list = ", ".join(palette_colors)
        prompt = f"{prompt} Use ONLY these exact colors: {color_list}. No other colors allowed."

    # Negative prompt kept as empty string for API compatibility.
    # FLUX Schnell does not support negative prompts — all constraints
    # are enforced via the positive prompt templates above.
    negative_prompt = ""

    return {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
    }

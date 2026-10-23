"""
MCP Server Product API endpoints.

Exposes Retrogaze's classic-console constraint intelligence as HTTP
endpoints that the local MCP server (TypeScript) calls on behalf of
users. Supports multi-console: NES, Game Boy, GBC, C64, Genesis,
SNES, PC Engine.

Mounted at ``/mcp`` via APIRouter in api.py.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import tempfile
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from PIL import UnidentifiedImageError
from pydantic import BaseModel, Field
from slowapi import Limiter
from slowapi.util import get_remote_address
from starlette.requests import Request

from .mcp_auth import McpAuthenticatedUser, get_mcp_user, get_optional_mcp_user
from .palette import (
    _NES_PALETTE_HEX,
    NES_PALETTE_PRESETS,
    get_mood_palette,
    get_preset_palette,
    list_presets,
    find_nearest_nes_color,
)

logger = logging.getLogger("retrogaze.mcp_routes")

router = APIRouter()

# Standalone limiter for MCP endpoints — rate limits tracked independently
# from the main app endpoints. The RateLimitExceeded exception handler is
# shared (registered on the app in api.py).
limiter = Limiter(key_func=get_remote_address)

# All eras are open in the OSS build (no tier gates).
_ALL_ERAS = {"retro", "early", "mid", "late"}

_HEX_RE = re.compile(r"^#[0-9A-Fa-f]{6}$")

# Max image size for validation (2MB, same as reference image limit)
_MAX_IMAGE_BYTES = 2 * 1024 * 1024

_VALID_CONSOLES = {"nes", "gb_dmg", "gb_pocket", "gbc", "c64", "genesis", "snes", "pc_engine"}


# ---------------------------------------------------------------------------
# Request / Response models
# ---------------------------------------------------------------------------

class PromptRequest(BaseModel):
    console: str = Field(default="nes", description="Target console: nes, gb_dmg, gb_pocket, gbc, c64, genesis, snes, pc_engine.")
    description: str = Field(..., max_length=500, description="What to draw.")
    asset_type: str = Field(default="character", description="character, enemy, item, tile, etc.")
    era: str = Field(default="mid", description="retro, early, mid, or late.")
    size: str = Field(default="16x16", pattern=r"^\d+x\d+$", description="Canvas size, e.g. 16x16.")
    view: str = Field(default="side", description="side, front, top_down, or three_quarter.")
    palette_mood: str = Field(default="auto", description="auto, warm, cool, earth, dark, etc.")
    outline: str = Field(default="Black", description="Black, Dark, or No.")
    palette_colors: list[str] | None = Field(default=None, max_length=6, description="Up to 6 hex colors to use.")
    seed: int | None = Field(default=None, description="Random seed for reproducibility.")
    tool_format: Literal["anthropic", "openai"] = Field(
        default="anthropic",
        description=(
            "Tool schema dialect. Set explicitly to anthropic or openai to "
            "include filtered pixel-mcp tool definitions."
        ),
    )


class PromptResponse(BaseModel):
    system_prompt: str = Field(description="Full system prompt for the drawing model.")
    user_prompt: str = Field(description="User message for the drawing model.")
    canvas: dict = Field(description="Canvas spec: width, height, color_mode.")
    palette: dict = Field(description="Resolved palette: colors list + roles mapping.")
    constraints: dict = Field(description="Max colors, outline style.")
    tool_whitelist: list[str] = Field(description="Pixel-mcp tools the drawing model should use.")
    tool_blacklist: list[str] = Field(description="Pixel-mcp tools the drawing model should NOT use.")
    tools: list[dict] | None = Field(
        default=None,
        description="Filtered pixel-mcp definitions in the requested tool schema dialect.",
    )
    remaining_calls: int | None = Field(default=None, description="Remaining monthly API calls.")


class ValidateRequest(BaseModel):
    console: str = Field(default="nes", description="Target console for constraint validation.")
    image_base64: str = Field(..., description="PNG image as base64 string.")
    asset_type: str = Field(default="sprite", description="sprite or background.")
    target_size: str | None = Field(default=None, pattern=r"^\d+x\d+$", description="Target size, e.g. 16x16.")
    max_colors_per_tile: int = Field(default=4, ge=1, le=8, description="Max unique colors per 8x8 tile.")
    fix: bool = Field(default=False, description="When true, returns the auto-corrected image.")


class ValidateResponse(BaseModel):
    compliant: bool = Field(description="True if image passes all console constraints.")
    metadata: dict = Field(description="Full compliance report.")
    fixed_image_base64: str | None = Field(default=None, description="Corrected PNG (only when fix=true).")
    remaining_calls: int | None = Field(default=None, description="Remaining monthly API calls.")


class PalettesResponse(BaseModel):
    nes_palette: list[str] = Field(description="All 56 NES 2C02 palette colors as hex (backward compat).")
    master_palette: list[str] = Field(default_factory=list, description="Console-specific palette colors as hex.")
    presets: dict[str, list[str]] = Field(description="Named palette presets.")
    moods: list[str] = Field(description="Available mood names for palette_mood parameter.")


class StatusResponse(BaseModel):
    tier: str
    monthly_used: int
    monthly_limit: int | None
    remaining_calls: int | None
    available_eras: list[str]


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _remaining(user: McpAuthenticatedUser) -> int | None:
    if user.monthly_limit is None:
        return None
    return max(0, user.monthly_limit - user.monthly_used)


def _parse_size(size_str: str) -> tuple[int, int]:
    """Parse '16x16' -> (16, 16). Raises HTTPException on invalid input."""
    parts = size_str.lower().split("x")
    if len(parts) != 2:
        raise HTTPException(status_code=422, detail=f"Invalid size format: {size_str}. Use WxH, e.g. 16x16.")
    try:
        w, h = int(parts[0]), int(parts[1])
    except ValueError:
        raise HTTPException(status_code=422, detail=f"Invalid size: {size_str}. Width and height must be integers.")
    if w < 8 or h < 8 or w > 256 or h > 240:
        raise HTTPException(status_code=422, detail=f"Size {w}x{h} out of NES range (8-256 x 8-240).")
    return w, h


def _validate_console(console: str) -> str:
    """Validate console name. Returns the canonical name or raises 422."""
    c = console.lower().strip()
    if c not in _VALID_CONSOLES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid console: '{console}'. Valid: {', '.join(sorted(_VALID_CONSOLES))}.",
        )
    return c


def _snap_palette_colors(colors: list[str]) -> list[str]:
    """Validate and snap hex colors to nearest NES palette entries."""
    snapped = []
    for c in colors:
        if not _HEX_RE.match(c):
            raise HTTPException(status_code=422, detail=f"Invalid hex color: {c}")
        h = c.lstrip("#")
        r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
        nr, ng, nb, _idx = find_nearest_nes_color(r, g, b)
        snapped.append(f"#{nr:02X}{ng:02X}{nb:02X}")
    return snapped


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

@router.post(
    "/prompt",
    response_model=PromptResponse,
    response_model_exclude_unset=True,
    tags=["mcp"],
)
@limiter.limit("30/minute")
async def mcp_prompt(
    request: Request,
    body: PromptRequest,
    user: McpAuthenticatedUser = Depends(get_optional_mcp_user),
) -> PromptResponse:
    """
    Generate a console-optimized prompt for MCP-capable sprite drawing.

    Returns a system prompt, user message, palette, canvas spec, and tool
    guidance for an MCP-capable client such as Claude, Cursor, Cline, Zed,
    Continue, or Copilot. Direct API callers can explicitly request Anthropic
    or OpenAI-compatible pixel-mcp tool definitions with ``tool_format``.

    All eras and consoles are available. Per-IP slowapi limits still apply.
    """
    console = _validate_console(body.console)
    era = body.era.lower()
    if era not in _ALL_ERAS:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid era '{body.era}'. Valid: {', '.join(sorted(_ALL_ERAS))}.",
        )

    size = _parse_size(body.size)

    # Snap palette colors to NES palette if provided (NES only — other
    # consoles may have free-color palettes)
    palette_colors = None
    if body.palette_colors:
        if console == "nes":
            palette_colors = _snap_palette_colors(body.palette_colors)
        else:
            # Validate hex format only, don't snap
            for c in body.palette_colors:
                if not _HEX_RE.match(c):
                    raise HTTPException(status_code=422, detail=f"Invalid hex color: {c}")
            palette_colors = body.palette_colors

    from .mcp_prompts import build_mcp_prompt

    result = build_mcp_prompt(
        description=body.description,
        asset_type=body.asset_type,
        size=size,
        view=body.view,
        palette_mood=body.palette_mood,
        outline=body.outline,
        era=era,
        palette_colors=palette_colors,
        seed=body.seed,
        console=console,
    )

    response = PromptResponse(
        system_prompt=result["system_prompt"],
        user_prompt=result["user_prompt"],
        canvas=result["canvas"],
        palette=result["palette"],
        constraints=result["constraints"],
        tool_whitelist=result["tool_whitelist"],
        tool_blacklist=result["tool_blacklist"],
        remaining_calls=_remaining(user),
    )
    if "tool_format" in body.model_fields_set:
        from .generate_aseprite import _filter_tools, _openai_tools

        tools = _filter_tools(result["tool_whitelist"])
        response.tools = _openai_tools(tools) if body.tool_format == "openai" else tools

    return response


@router.post("/validate", response_model=ValidateResponse, tags=["mcp"])
@limiter.limit("30/minute")
async def mcp_validate(
    request: Request,
    body: ValidateRequest,
    user: McpAuthenticatedUser = Depends(get_optional_mcp_user),
) -> ValidateResponse:
    """
    Validate an image against console hardware constraints.

    Returns a compliance report. When ``fix=true``, also returns the
    auto-corrected image. Available to everyone in the open-source build.
    """
    console = _validate_console(body.console)

    # Decode image
    try:
        image_bytes = base64.b64decode(body.image_base64)
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid base64 image data.")

    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(status_code=422, detail=f"Image exceeds {_MAX_IMAGE_BYTES // 1024}KB limit.")

    # Parse target size
    target_size = None
    if body.target_size:
        target_size = _parse_size(body.target_size)

    from .enforce import enforce_constraints

    # Write to temp file and run enforcement (CPU-bound, run in thread)
    tmp_path = None
    output_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as tmp:
            tmp.write(image_bytes)
            tmp_path = tmp.name

        if body.fix:
            output_path = tmp_path.replace(".png", "_fixed.png")

        try:
            metadata = await asyncio.to_thread(
                enforce_constraints,
                image_path=tmp_path,
                target_size=target_size,
                asset_type=body.asset_type,
                output_path=output_path,
                max_colors_per_tile=body.max_colors_per_tile,
                console=console,
            )
        except UnidentifiedImageError:
            # Decoded base64 was not a parseable image (e.g. truncated,
            # wrong format, or arbitrary bytes). This is bad client input,
            # not a server fault — reject cleanly with a 422 instead of
            # letting PIL's exception surface as a raw 500.
            raise HTTPException(
                status_code=422,
                detail="image_base64 did not decode to a valid image. Provide a PNG (or other PIL-supported image) encoded as base64.",
            )

        # Read fixed image if requested
        fixed_b64 = None
        if body.fix and output_path:
            fixed_png = Path(output_path)
            if fixed_png.exists():
                fixed_b64 = base64.b64encode(fixed_png.read_bytes()).decode()

        # Check compliance from metadata — use palette_valid (console-aware)
        # with fallback to nes_palette_valid for backward compat
        compliance = metadata.get("compliance", {})
        compliant = all([
            compliance.get("palette_valid", compliance.get("nes_palette_valid", False)),
            compliance.get("colors_per_tile_valid", False),
            compliance.get("grid_aligned", False),
        ])

        return ValidateResponse(
            compliant=compliant,
            metadata=metadata,
            fixed_image_base64=fixed_b64,
            remaining_calls=_remaining(user),
        )

    finally:
        # Cleanup temp files
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
        if body.fix and output_path:
            try:
                os.unlink(output_path)
            except OSError:
                pass
            # enforce_constraints also writes a .json metadata file alongside
            json_path = output_path.replace(".png", ".json")
            try:
                os.unlink(json_path)
            except OSError:
                pass


@router.get("/palettes", response_model=PalettesResponse, tags=["mcp"])
@limiter.limit("120/minute")
async def mcp_palettes(request: Request, console: str = "nes") -> PalettesResponse:
    """
    Return the console's master palette, named presets, and available moods.

    No authentication required — this is reference data.
    Accepts ``?console=genesis`` etc. Defaults to NES.
    """
    console = _validate_console(console)
    moods = ["warm", "cool", "earth", "dark", "heroic", "eerie", "aquatic", "fire"]

    from .console_profile import get_profile
    profile = get_profile(console)
    palette_hex = profile.master_palette_hex or []

    return PalettesResponse(
        nes_palette=list(_NES_PALETTE_HEX),
        master_palette=list(palette_hex),
        presets=list_presets(),
        moods=moods,
    )


@router.get("/status", response_model=StatusResponse, tags=["mcp"])
async def mcp_status(
    request: Request,
    user: McpAuthenticatedUser = Depends(get_optional_mcp_user),
) -> StatusResponse:
    """Usage/status introspection. All eras are available to every caller."""
    return StatusResponse(
        tier=user.tier,
        monthly_used=user.monthly_used,
        monthly_limit=user.monthly_limit,
        remaining_calls=_remaining(user),
        available_eras=sorted(_ALL_ERAS),
    )

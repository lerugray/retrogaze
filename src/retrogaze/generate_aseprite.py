"""
Aseprite-native sprite generation via Claude API + pixel-mcp.

Alternative generation path to FLUX. Claude (Haiku) generates drawing
instructions as tool calls, which are executed against pixel-mcp
(Aseprite MCP server) to produce sprites natively in Aseprite.

Sprites are palette-compliant by construction — no post-generation
cleanup needed. NES enforcement still runs for grid alignment validation.

Requires:
  - ANTHROPIC_API_KEY env var
  - pixel-mcp server running (Aseprite + pixel-plugin)
  - mcp Python package for client connection
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import anthropic

from .mcp_prompts import build_mcp_prompt

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

HAIKU_MODEL = "claude-haiku-4-5-20251001"
MAX_TOKENS = 4096
MAX_TOOL_ROUNDS = 20  # safety limit on agentic loop iterations

# Retry configuration
_API_MAX_RETRIES = 3
_API_RETRY_BASE_DELAY = 2.0  # seconds — doubles each attempt (2, 4, 8)
_EXPORT_MAX_RETRIES = 3
_EXPORT_RETRY_DELAY = 1.0  # seconds between export file checks

# Rate limiting — cap concurrent Anthropic API calls to avoid 429s
# when running parallel MCP generations
_MAX_CONCURRENT_GENERATIONS = int(os.environ.get("RETROGAZE_MCP_CONCURRENCY", "3"))
_generation_semaphore: asyncio.Semaphore | None = None


def _get_semaphore() -> asyncio.Semaphore:
    """Lazy-init semaphore (must be created inside a running event loop)."""
    global _generation_semaphore
    if _generation_semaphore is None:
        _generation_semaphore = asyncio.Semaphore(_MAX_CONCURRENT_GENERATIONS)
    return _generation_semaphore

# Cost per million tokens (Haiku 4.5)
_INPUT_COST_PER_M = 1.0   # $1/M input
_OUTPUT_COST_PER_M = 5.0   # $5/M output


# ---------------------------------------------------------------------------
# Tool definitions for Anthropic API
# ---------------------------------------------------------------------------
# These match the pixel-mcp tools that our prompt module whitelists.
# Only tools that appear in at least one era's whitelist are defined.

ASEPRITE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "create_canvas",
        "description": "Create a new sprite canvas in Aseprite.",
        "input_schema": {
            "type": "object",
            "properties": {
                "width": {"type": "integer", "description": "Canvas width in pixels"},
                "height": {"type": "integer", "description": "Canvas height in pixels"},
                "color_mode": {
                    "type": "string",
                    "enum": ["rgb", "indexed", "grayscale"],
                    "description": "Color mode (default: rgb)",
                },
            },
            "required": ["width", "height"],
        },
    },
    {
        "name": "set_palette",
        "description": "Set the sprite's color palette.",
        "input_schema": {
            "type": "object",
            "properties": {
                "colors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Array of hex color strings (e.g. ['#FF0000', '#00FF00'])",
                },
            },
            "required": ["colors"],
        },
    },
    {
        "name": "draw_pixels",
        "description": "Draw individual pixels at specific coordinates.",
        "input_schema": {
            "type": "object",
            "properties": {
                "pixels": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                            "color": {"type": "string"},
                        },
                        "required": ["x", "y", "color"],
                    },
                    "description": "Array of {x, y, color} pixel objects",
                },
            },
            "required": ["pixels"],
        },
    },
    {
        "name": "draw_rectangle",
        "description": "Draw a rectangle (filled or outline).",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Top-left X coordinate"},
                "y": {"type": "integer", "description": "Top-left Y coordinate"},
                "width": {"type": "integer", "description": "Rectangle width"},
                "height": {"type": "integer", "description": "Rectangle height"},
                "color": {"type": "string", "description": "Hex color string"},
                "filled": {"type": "boolean", "description": "Whether to fill the rectangle (default: true)"},
            },
            "required": ["x", "y", "width", "height", "color"],
        },
    },
    {
        "name": "draw_circle",
        "description": "Draw a circle (filled or outline).",
        "input_schema": {
            "type": "object",
            "properties": {
                "center_x": {"type": "integer", "description": "Center X coordinate"},
                "center_y": {"type": "integer", "description": "Center Y coordinate"},
                "radius": {"type": "integer", "description": "Circle radius in pixels"},
                "color": {"type": "string", "description": "Hex color string"},
                "filled": {"type": "boolean", "description": "Whether to fill the circle (default: true)"},
            },
            "required": ["center_x", "center_y", "radius", "color"],
        },
    },
    {
        "name": "draw_line",
        "description": "Draw a line between two points.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x1": {"type": "integer", "description": "Start X coordinate"},
                "y1": {"type": "integer", "description": "Start Y coordinate"},
                "x2": {"type": "integer", "description": "End X coordinate"},
                "y2": {"type": "integer", "description": "End Y coordinate"},
                "color": {"type": "string", "description": "Hex color string"},
            },
            "required": ["x1", "y1", "x2", "y2", "color"],
        },
    },
    {
        "name": "draw_contour",
        "description": "Draw a contour (connected path of points).",
        "input_schema": {
            "type": "object",
            "properties": {
                "points": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "x": {"type": "integer"},
                            "y": {"type": "integer"},
                        },
                        "required": ["x", "y"],
                    },
                    "description": "Array of {x, y} points defining the contour path",
                },
                "color": {"type": "string", "description": "Hex color string"},
            },
            "required": ["points", "color"],
        },
    },
    {
        "name": "apply_outline",
        "description": "Apply an outline around all non-transparent pixels.",
        "input_schema": {
            "type": "object",
            "properties": {
                "color": {"type": "string", "description": "Outline hex color (e.g. '#000000')"},
                "thickness": {"type": "integer", "description": "Outline thickness in pixels (default: 1)"},
            },
            "required": ["color"],
        },
    },
    {
        "name": "draw_with_dither",
        "description": "Draw a dithered area using a pattern.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "Top-left X coordinate"},
                "y": {"type": "integer", "description": "Top-left Y coordinate"},
                "width": {"type": "integer", "description": "Area width"},
                "height": {"type": "integer", "description": "Area height"},
                "color1": {"type": "string", "description": "First hex color"},
                "color2": {"type": "string", "description": "Second hex color"},
                "pattern": {
                    "type": "string",
                    "description": "Dither pattern name (bayer_2x2, bayer_4x4, bayer_8x8, floyd_steinberg)",
                },
            },
            "required": ["x", "y", "width", "height", "color1", "color2", "pattern"],
        },
    },
    {
        "name": "export_sprite",
        "description": "Export the current sprite to a file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "File path for the exported image"},
            },
            "required": ["output_path"],
        },
    },
    {
        "name": "save_as",
        "description": "Save the sprite as an Aseprite file.",
        "input_schema": {
            "type": "object",
            "properties": {
                "output_path": {"type": "string", "description": "File path for the .aseprite file"},
            },
            "required": ["output_path"],
        },
    },
    {
        "name": "fill_area",
        "description": "Flood fill an area with a color.",
        "input_schema": {
            "type": "object",
            "properties": {
                "x": {"type": "integer", "description": "X coordinate to start fill from"},
                "y": {"type": "integer", "description": "Y coordinate to start fill from"},
                "color": {"type": "string", "description": "Hex color to fill with"},
            },
            "required": ["x", "y", "color"],
        },
    },
]


def _openai_tools(anthropic_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in anthropic_tools
    ]


def _filter_tools(whitelist: list[str]) -> list[dict[str, Any]]:
    """Filter tool definitions to only those in the whitelist.

    Always includes export_sprite and save_as for output.
    """
    always_include = {"export_sprite", "save_as"}
    allowed = set(whitelist) | always_include
    return [t for t in ASEPRITE_TOOLS if t["name"] in allowed]


def _estimate_cost(usage: anthropic.types.Usage) -> float:
    """Estimate USD cost from API usage."""
    input_cost = (usage.input_tokens / 1_000_000) * _INPUT_COST_PER_M
    output_cost = (usage.output_tokens / 1_000_000) * _OUTPUT_COST_PER_M
    return round(input_cost + output_cost, 6)


# ---------------------------------------------------------------------------
# MCP client — executes tool calls against pixel-mcp
# ---------------------------------------------------------------------------

def _adapt_tool_input(
    name: str,
    params: dict[str, Any],
    sprite_path: str | None,
) -> dict[str, Any]:
    """Inject fields that pixel-mcp requires but the Claude API schemas omit.

    The Anthropic tool definitions are intentionally simplified (Haiku doesn't
    need to know about sprite_path / layer_name / frame_number — those are
    always the same for single-frame generation). This adapter fills them in
    before forwarding to the real MCP server.
    """
    p = dict(params)  # shallow copy

    # Inject sprite_path for all drawing/palette/export tools
    if name != "create_canvas" and sprite_path and "sprite_path" not in p:
        p["sprite_path"] = sprite_path

    # Inject layer_name and frame_number for drawing tools
    drawing_tools = {
        "draw_pixels", "draw_rectangle", "draw_circle", "draw_line",
        "draw_contour", "draw_with_dither", "apply_outline", "fill_area",
    }
    if name in drawing_tools:
        p.setdefault("layer_name", "Layer 1")
        p.setdefault("frame_number", 1)

    # Inject defaults for specific tools
    if name == "create_canvas":
        p.setdefault("color_mode", "rgb")
    elif name == "draw_rectangle":
        p.setdefault("filled", True)
    elif name == "draw_circle":
        p.setdefault("filled", True)
    elif name == "apply_outline":
        p.setdefault("thickness", 1)
    elif name == "export_sprite":
        p.setdefault("format", "png")
        p.setdefault("frame_number", 1)
    elif name == "fill_area":
        p.setdefault("tolerance", 0)

    return p


async def _connect_and_execute(
    tool_calls: list[dict[str, Any]],
    pixel_mcp_command: str | None = None,
    sprite_path: str | None = None,
) -> tuple[list[dict[str, Any]], str | None]:
    """
    Execute a batch of tool calls against pixel-mcp via MCP client protocol.

    Tracks the sprite_path from create_canvas and injects it (plus other
    required fields) into subsequent tool calls via _adapt_tool_input().

    Returns (results list, sprite_path) — sprite_path is captured from
    create_canvas and returned so the caller can pass it to future rounds.
    """
    try:
        from mcp import ClientSession
        from mcp.client.stdio import stdio_client, StdioServerParameters
    except ImportError:
        raise RuntimeError(
            "MCP client library not installed. Run: pip install mcp"
        )

    # Resolve pixel-mcp command
    if pixel_mcp_command is None:
        pixel_mcp_command = os.environ.get("PIXEL_MCP_COMMAND")
    if pixel_mcp_command is None:
        # Try common locations
        candidates = [
            Path.home() / ".claude" / "plugins" / "marketplaces" / "pixel-plugin" / "bin" / "pixel-mcp-windows-amd64.exe",
            Path.home() / ".claude" / "pixel-mcp.exe",
            Path.home() / "AppData" / "Roaming" / "npm" / "pixel-mcp.cmd",
        ]
        for c in candidates:
            if c.exists():
                pixel_mcp_command = str(c)
                break
    if pixel_mcp_command is None:
        raise RuntimeError(
            "pixel-mcp not found. Set PIXEL_MCP_COMMAND env var or install pixel-mcp."
        )

    server_params = StdioServerParameters(
        command=pixel_mcp_command,
        args=[],
    )

    results = []
    async with stdio_client(server_params) as streams:
        async with ClientSession(*streams) as session:
            await session.initialize()

            for call in tool_calls:
                adapted = _adapt_tool_input(call["name"], call["input"], sprite_path)
                try:
                    result = await session.call_tool(
                        call["name"],
                        adapted,
                    )
                    content_str = str(result.content) if result.content else "OK"

                    # Capture sprite_path from create_canvas response
                    if call["name"] == "create_canvas" and result.content:
                        import json as _json
                        try:
                            for item in result.content:
                                text = getattr(item, "text", None)
                                if text:
                                    parsed = _json.loads(text)
                                    if "file_path" in parsed:
                                        sprite_path = parsed["file_path"]
                                        logger.info("Sprite path: %s", sprite_path)
                        except (ValueError, AttributeError):
                            pass

                    results.append({
                        "tool_use_id": call["id"],
                        "content": content_str,
                        "is_error": False,
                    })
                except Exception as exc:
                    logger.warning("Tool call %s failed: %s", call["name"], exc)
                    results.append({
                        "tool_use_id": call["id"],
                        "content": f"Error: tool call failed ({type(exc).__name__})",
                        "is_error": True,
                    })

    return results, sprite_path


# ---------------------------------------------------------------------------
# Main generation function
# ---------------------------------------------------------------------------

async def generate_aseprite_sprite(
    description: str,
    asset_type: str = "character",
    size: tuple[int, int] = (16, 16),
    view: str = "side",
    palette_mood: str = "auto",
    outline: str = "Black",
    era: str = "mid",
    palette_colors: list[str] | None = None,
    seed: int | None = None,
    output_dir: str | os.PathLike | None = None,
    pixel_mcp_command: str | None = None,
    console: str = "nes",
    prompt_topology: str = "era_first",
    disable_rg013_gating: bool = False,
    auto_shading_16x16: bool = False,
    anthropic_key: str | None = None,
) -> dict[str, Any]:
    """
    Generate a sprite via Claude API + pixel-mcp.

    Calls Claude API (Haiku) with structured MCP prompts, executes the
    resulting tool calls against pixel-mcp to draw in Aseprite, then
    exports the result as PNG.

    Returns a dict with:
      - image: PIL Image (RGBA)
      - aseprite_path: path to .aseprite file (if saved)
      - png_path: path to exported PNG
      - cost_usd: estimated API cost
      - tool_calls: total number of tool calls made
      - tokens: {input, output} token counts
      - instructions: raw tool call log (for debugging)
    """
    from PIL import Image as PILImage

    # Validate auth — accept either ANTHROPIC_API_KEY (sk-ant-api-...) or
    # CLAUDE_CODE_OAUTH_TOKEN (sk-ant-oat-...). The SDK's `auth_token` param
    # routes OAuth tokens correctly; `api_key` stays the default for API keys.
    #
    # BYOK: the user-supplied `anthropic_key` (passed transiently from the
    # request) ALWAYS wins over server env. It's never logged, stored, or
    # echoed — it lives only as this function argument. Server env is a
    # fallback for self-hosted/dev where an operator key is present.
    api_key = anthropic_key or os.environ.get("ANTHROPIC_API_KEY") or None
    oauth_token = os.environ.get("CLAUDE_CODE_OAUTH_TOKEN") or None
    if api_key and api_key.startswith("sk-ant-oat"):
        # User pasted an OAuth token into the key field / ANTHROPIC_API_KEY —
        # route it as an OAuth token (auth_token), not an API key.
        oauth_token = api_key
        api_key = None
    elif anthropic_key:
        # User supplied an API-style key. It MUST win over any server-side
        # OAuth env token — otherwise BYOK would silently bill the operator.
        oauth_token = None
    if not api_key and not oauth_token:
        raise RuntimeError(
            "Auth not set. Provide ANTHROPIC_API_KEY (sk-ant-api-...) or "
            "CLAUDE_CODE_OAUTH_TOKEN (sk-ant-oat-...)."
        )

    # Build prompt
    prompt_data = build_mcp_prompt(
        description=description,
        asset_type=asset_type,
        size=size,
        view=view,
        palette_mood=palette_mood,
        outline=outline,
        era=era,
        palette_colors=palette_colors,
        seed=seed,
        console=console,
        prompt_topology=prompt_topology,
        disable_rg013_gating=disable_rg013_gating,
        auto_shading_16x16=auto_shading_16x16,
    )

    # Filter tools to era whitelist
    tools = _filter_tools(prompt_data["tool_whitelist"])

    # Set up output directory
    _temp_dir_obj = None
    if output_dir is None:
        _temp_dir_obj = tempfile.TemporaryDirectory()
        out_dir = Path(_temp_dir_obj.name)
    else:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    # Use forward slashes for paths (pixel-mcp requirement on Windows)
    png_path = (out_dir / "sprite.png").as_posix()
    aseprite_path = (out_dir / "sprite.aseprite").as_posix()

    # Append export instructions to user prompt
    user_prompt = (
        prompt_data["user_prompt"]
        + f"\n\nWhen finished drawing, call export_sprite with "
        f'output_path="{png_path}" and save_as with '
        f'output_path="{aseprite_path}".'
    )

    # Initialize Anthropic client (OAuth or API-key depending on what we got)
    if oauth_token:
        client = anthropic.AsyncAnthropic(auth_token=oauth_token)
    else:
        client = anthropic.AsyncAnthropic(api_key=api_key)

    # Throttle concurrent generations to avoid Anthropic API rate limits
    sem = _get_semaphore()
    await sem.acquire()
    try:
        return await _run_agentic_loop(
            client=client,
            prompt_data=prompt_data,
            user_prompt=user_prompt,
            tools=tools,
            png_path=png_path,
            aseprite_path=aseprite_path,
            pixel_mcp_command=pixel_mcp_command,
        )
    finally:
        sem.release()


async def _run_agentic_loop(
    *,
    client: anthropic.AsyncAnthropic,
    prompt_data: dict,
    user_prompt: str,
    tools: list[dict[str, Any]],
    png_path: str,
    aseprite_path: str,
    pixel_mcp_command: str | None,
) -> dict[str, Any]:
    """Run the Claude agentic loop — factored out for semaphore wrapping."""
    from PIL import Image as PILImage

    # Agentic loop
    messages = [{"role": "user", "content": user_prompt}]
    total_input_tokens = 0
    total_output_tokens = 0
    total_tool_calls = 0
    all_instructions: list[dict] = []
    _sprite_path: str | None = None  # tracked across MCP rounds

    for round_num in range(MAX_TOOL_ROUNDS):
        # Retry Anthropic API calls on transient errors (rate limits, 500s,
        # and the occasional 400 that resolves on retry)
        last_api_exc: Exception | None = None
        for api_attempt in range(_API_MAX_RETRIES + 1):
            try:
                response = await client.messages.create(
                    model=HAIKU_MODEL,
                    max_tokens=MAX_TOKENS,
                    system=prompt_data["system_prompt"],
                    messages=messages,
                    tools=tools,
                )
                break
            except anthropic.RateLimitError as exc:
                delay = _API_RETRY_BASE_DELAY * (2 ** api_attempt)
                logger.warning(
                    "Anthropic rate limit (attempt %d/%d), retrying in %.1fs",
                    api_attempt + 1, _API_MAX_RETRIES + 1, delay,
                )
                last_api_exc = exc
                await asyncio.sleep(delay)
            except anthropic.InternalServerError as exc:
                delay = _API_RETRY_BASE_DELAY * (2 ** api_attempt)
                logger.warning(
                    "Anthropic 500 error (attempt %d/%d), retrying in %.1fs",
                    api_attempt + 1, _API_MAX_RETRIES + 1, delay,
                )
                last_api_exc = exc
                await asyncio.sleep(delay)
            except anthropic.BadRequestError as exc:
                # Some 400s are transient (e.g. overloaded). Retry once.
                if api_attempt < 1:
                    delay = _API_RETRY_BASE_DELAY
                    logger.warning(
                        "Anthropic 400 error (attempt %d/%d), retrying in %.1fs: %s",
                        api_attempt + 1, _API_MAX_RETRIES + 1, delay, exc,
                    )
                    last_api_exc = exc
                    await asyncio.sleep(delay)
                else:
                    raise
        else:
            raise last_api_exc  # type: ignore[misc]

        total_input_tokens += response.usage.input_tokens
        total_output_tokens += response.usage.output_tokens

        # Extract tool calls from response
        tool_calls = []
        text_parts = []
        for block in response.content:
            if block.type == "tool_use":
                tool_calls.append({
                    "id": block.id,
                    "name": block.name,
                    "input": block.input,
                })
                all_instructions.append({
                    "round": round_num,
                    "tool": block.name,
                    "input": block.input,
                })
            elif block.type == "text":
                text_parts.append(block.text)

        if not tool_calls:
            # Claude is done (end_turn with no more tool calls)
            logger.info(
                "Generation complete after %d rounds, %d tool calls",
                round_num + 1, total_tool_calls,
            )
            break

        total_tool_calls += len(tool_calls)

        # Execute tool calls against pixel-mcp
        results, _sprite_path = await _connect_and_execute(
            tool_calls,
            pixel_mcp_command=pixel_mcp_command,
            sprite_path=_sprite_path,
        )

        # Build assistant message (what Claude said) and tool results
        messages.append({"role": "assistant", "content": response.content})
        messages.append({
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": r["tool_use_id"],
                    "content": r["content"],
                    "is_error": r["is_error"],
                }
                for r in results
            ],
        })
    else:
        logger.warning("Hit max tool rounds (%d) — generation may be incomplete", MAX_TOOL_ROUNDS)

    # Load the exported PNG (retry for race condition — export_sprite may
    # not have flushed to disk yet when pixel-mcp returns)
    png_file = Path(png_path)
    for export_attempt in range(_EXPORT_MAX_RETRIES + 1):
        if png_file.exists() and png_file.stat().st_size > 0:
            break
        if export_attempt < _EXPORT_MAX_RETRIES:
            logger.info(
                "Waiting for export file %s (attempt %d/%d)",
                png_path, export_attempt + 1, _EXPORT_MAX_RETRIES + 1,
            )
            await asyncio.sleep(_EXPORT_RETRY_DELAY)
    if not png_file.exists():
        raise RuntimeError(
            f"Sprite PNG not exported at {png_path}. "
            f"Claude may not have called export_sprite. "
            f"Tool calls made: {total_tool_calls}"
        )

    image = PILImage.open(str(png_file)).convert("RGBA")

    # Calculate cost
    usage = anthropic.types.Usage(
        input_tokens=total_input_tokens,
        output_tokens=total_output_tokens,
    )
    cost_usd = _estimate_cost(usage)

    return {
        "image": image,
        "png_path": str(png_file),
        "aseprite_path": str(Path(aseprite_path)) if Path(aseprite_path).exists() else None,
        "cost_usd": cost_usd,
        "tool_calls": total_tool_calls,
        "tokens": {
            "input": total_input_tokens,
            "output": total_output_tokens,
        },
        "instructions": all_instructions,
    }

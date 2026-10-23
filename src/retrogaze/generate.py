"""
Image generation client for Retrogaze.

Two-step pipeline:
  1. FLUX Schnell generates a pixel-art concept image at 512x512
  2. Image2Pixel converts it to true pixel art with grid alignment,
     palette reduction, and proper downscaling

Set ``RETROGAZE_MOCK=1`` in the environment to skip real API calls and return
a synthetic test image instead.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import random
import threading

import httpx
from PIL import Image

logger = logging.getLogger(__name__)

from .palette import NES_PALETTE_RGB, _NES_PALETTE_HEX
from .console_profile import get_profile, ConsoleProfile
from .console_prompt_data import get_prompt_data

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_FLUX_API_URL = "https://fal.run/fal-ai/flux/schnell"
_FLUX_IMG2IMG_API_URL = "https://fal.run/fal-ai/flux/dev/image-to-image"
_IMAGE2PIXEL_API_URL = "https://fal.run/fal-ai/image2pixel"

# FLUX generates at 512x512 — we want a clear, detailed pixel art concept
_FLUX_SIZE = 512

# ---------------------------------------------------------------------------
# Safety limits — prevent accidental overcharging
# ---------------------------------------------------------------------------

# Max generations per session (resets on server restart)
_MAX_GENERATIONS_PER_SESSION = int(os.environ.get("RETROGAZE_MAX_GENS", "100"))

# Estimated cost per generation (conservative — covers both API calls).
# FLUX Schnell text-to-image: ~$0.01; FLUX Dev image-to-image: ~$0.03.
_COST_PER_GEN = float(os.environ.get("RETROGAZE_COST_PER_GEN", "0.04"))

# Max spend per session in dollars
_MAX_SPEND = float(os.environ.get("RETROGAZE_MAX_SPEND", "5.00"))

# Content moderation — fal.ai's safety checker.
# Default OFF for local dev (fewer false positives on game content).
# Set RETROGAZE_SAFETY_CHECKER=1 for the public-facing deployment.
_SAFETY_CHECKER = os.environ.get("RETROGAZE_SAFETY_CHECKER", "").strip() == "1"

_lock = threading.Lock()
_session_gen_count = 0
_session_spend = 0.0


def _cap_message(kind: str) -> str:
    """Human-readable message when a session spend/gen cap is hit."""
    if os.environ.get("RETROGAZE_DEMO", "").strip() == "1":
        repo = (
            os.environ.get("RETROGAZE_REPO_URL", "https://github.com/lerugray/retrogaze").strip()
            or "https://github.com/lerugray/retrogaze"
        )
        return (
            "The free demo credits are used up. Retrogaze is open source: "
            f"run it yourself with your own fal key. {repo}"
        )
    if kind == "gens":
        return (
            f"Session generation limit reached ({_MAX_GENERATIONS_PER_SESSION}). "
            f"Restart the server to reset, or set RETROGAZE_MAX_GENS higher."
        )
    return (
        f"Spend cap reached (~${_session_spend:.2f} of ${_MAX_SPEND:.2f} limit). "
        f"Set RETROGAZE_MAX_SPEND higher to continue."
    )


def _check_safety_limits() -> None:
    """Raise if any safety limit is exceeded."""
    global _session_gen_count, _session_spend

    with _lock:
        if _session_gen_count >= _MAX_GENERATIONS_PER_SESSION:
            raise RuntimeError(_cap_message("gens"))

        projected_spend = _session_spend + _COST_PER_GEN
        if projected_spend > _MAX_SPEND:
            raise RuntimeError(_cap_message("spend"))


def _record_generation() -> None:
    """Record a successful generation for limit tracking."""
    global _session_gen_count, _session_spend
    with _lock:
        _session_gen_count += 1
        _session_spend += _COST_PER_GEN


def _reserve_generation() -> None:
    """Atomically check limits and reserve one generation slot."""
    global _session_gen_count, _session_spend
    with _lock:
        if _session_gen_count >= _MAX_GENERATIONS_PER_SESSION:
            raise RuntimeError(_cap_message("gens"))

        projected_spend = _session_spend + _COST_PER_GEN
        if projected_spend > _MAX_SPEND:
            raise RuntimeError(_cap_message("spend"))

        _session_gen_count += 1
        _session_spend += _COST_PER_GEN


def _refund_generation() -> None:
    """Release one reserved generation slot after failure."""
    global _session_gen_count, _session_spend
    with _lock:
        if _session_gen_count > 0:
            _session_gen_count -= 1
        _session_spend = max(0.0, _session_spend - _COST_PER_GEN)


_MAX_RETRIES = 3
_RETRY_BASE_DELAY = 2.0  # seconds — doubles each attempt (2, 4, 8)


async def _post_with_retry(
    client: httpx.AsyncClient,
    url: str,
    *,
    json: dict,
    headers: dict,
) -> httpx.Response:
    """POST with exponential backoff on 429 (rate limit) and 5xx errors."""
    for attempt in range(_MAX_RETRIES + 1):
        try:
            resp = await client.post(url, json=json, headers=headers)
            if resp.status_code == 429 or resp.status_code >= 500:
                if attempt >= _MAX_RETRIES:
                    resp.raise_for_status()
                delay = _RETRY_BASE_DELAY * (2 ** attempt)
                logger.warning(
                    "fal.ai %s on %s (attempt %d/%d), retrying in %.1fs",
                    resp.status_code, url.split("/")[-1], attempt + 1,
                    _MAX_RETRIES + 1, delay,
                )
                await asyncio.sleep(delay)
                continue
            resp.raise_for_status()
            return resp
        except httpx.TimeoutException as exc:
            if attempt >= _MAX_RETRIES:
                raise
            delay = _RETRY_BASE_DELAY * (2 ** attempt)
            logger.warning(
                "Timeout on %s (attempt %d/%d), retrying in %.1fs",
                url.split("/")[-1], attempt + 1, _MAX_RETRIES + 1, delay,
            )
            await asyncio.sleep(delay)
    raise RuntimeError("Unexpected retry loop exit in _post_with_retry")


def _get_fal_key() -> str:
    """Return the fal.ai API key or raise a clear error."""
    key = os.environ.get("FAL_KEY", "").strip()
    if not key:
        raise EnvironmentError(
            "FAL_KEY environment variable is not set. "
            "Get your API key from https://fal.ai and set FAL_KEY=<your-key>."
        )
    return key


def _fal_headers(key: str) -> dict:
    return {"Authorization": f"Key {key}", "Content-Type": "application/json"}


_ALLOWED_FAL_DOMAINS = {"fal.run", "fal.ai", "fal.media", "storage.googleapis.com"}


def _validate_fal_url(url: str) -> None:
    """Reject URLs not from expected fal.ai CDN domains (SSRF protection)."""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    host = parsed.hostname or ""
    if not any(host == d or host.endswith("." + d) for d in _ALLOWED_FAL_DOMAINS):
        raise ValueError(f"Unexpected image URL domain: {host}")


async def _download_image(url: str) -> Image.Image:
    """Download an image from a URL and return as PIL Image."""
    _validate_fal_url(url)
    async with httpx.AsyncClient(timeout=60.0) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return Image.open(io.BytesIO(resp.content)).convert("RGBA")


# ---------------------------------------------------------------------------
# Step 1: FLUX generates a pixel-art concept
# ---------------------------------------------------------------------------

async def _generate_concept(
    prompt: str,
    negative_prompt: str,
    fal_key: str,
    seed: int | None = None,
) -> str:
    """
    Generate a pixel art concept image via FLUX Schnell.
    Returns the URL of the generated image (hosted on fal.ai).
    """
    payload = {
        "prompt": prompt,
        "image_size": {"width": _FLUX_SIZE, "height": _FLUX_SIZE},
        "num_images": 1,
        "num_inference_steps": 4,
        "enable_safety_checker": _SAFETY_CHECKER,
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["seed"] = seed

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await _post_with_retry(
            client, _FLUX_API_URL, json=payload, headers=_fal_headers(fal_key)
        )
        data = response.json()

    return data["images"][0]["url"]


# ---------------------------------------------------------------------------
# Step 1b: FLUX Dev image-to-image with a reference image
# ---------------------------------------------------------------------------

async def _generate_from_reference(
    prompt: str,
    negative_prompt: str,
    reference_image_url: str,
    strength: float,
    fal_key: str,
    seed: int | None = None,
) -> str:
    """
    Generate pixel art using FLUX Dev image-to-image with a reference image.
    Returns the URL of the generated image.

    strength: 0.0 = exact copy, 1.0 = ignore reference entirely.
    For pixel art references, 0.6-0.8 works well (keep composition, adapt style).
    """
    payload = {
        "prompt": prompt,
        "image_url": reference_image_url,
        "strength": strength,
        "num_inference_steps": 28,
        "guidance_scale": 3.5,
        "num_images": 1,
        "enable_safety_checker": _SAFETY_CHECKER,
        "output_format": "png",
    }
    if negative_prompt:
        payload["negative_prompt"] = negative_prompt
    if seed is not None:
        payload["seed"] = seed

    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await _post_with_retry(
            client, _FLUX_IMG2IMG_API_URL, json=payload, headers=_fal_headers(fal_key)
        )
        data = response.json()

    return data["images"][0]["url"]


# ---------------------------------------------------------------------------
# Step 2: Image2Pixel converts to true pixel art
# ---------------------------------------------------------------------------

async def _pixelize(
    image_url: str,
    target_w: int,
    target_h: int,
    fal_key: str,
    palette_colors: list[str] | None = None,
    asset_type: str = "character",
    era: str = "mid",
    force_pixel_scale: int | None = None,
    console: str | None = None,
) -> tuple[Image.Image, Image.Image]:
    """
    Convert a concept image to true pixel art via fal.ai's Image2Pixel.

    Returns (full_size_image, downscaled_pixel_art_image).
    """
    is_tile_type = asset_type in ("tile", "tileset")

    # Resolve console profile and era prompt data for calibration
    profile: ConsoleProfile | None = None
    era_data = None
    if console:
        try:
            profile = get_profile(console)
        except KeyError:
            pass
        try:
            prompt_data = get_prompt_data(console)
            era_data = prompt_data.eras.get(era, prompt_data.eras.get("mid"))
        except (NotImplementedError, KeyError):
            pass

    # P1-3: When force_pixel_scale is set (per-frame mode), use it directly
    # to ensure all frames get the same downscale factor.
    if force_pixel_scale is not None:
        pixel_scale = force_pixel_scale
    elif is_tile_type:
        pixel_scale = 8
    elif era_data is not None:
        pixel_scale = era_data.pixel_scale
    elif era == "retro":
        # Fallback for unknown console — NES-calibrated defaults
        pixel_scale = 4
    elif era == "early":
        pixel_scale = 6
    else:
        pixel_scale = None

    # When a locked palette is set, restrict Image2Pixel to only those colors.
    # Otherwise, use the console's master palette (fixed-palette consoles)
    # or no fixed palette (free-color consoles like Genesis, SNES, GBC).
    if palette_colors:
        fixed_palette = list(dict.fromkeys(palette_colors))
        max_colors = len(fixed_palette)
    elif profile and profile.master_palette_hex is not None:
        # Fixed-palette console — use its hardware palette
        fixed_palette = list(dict.fromkeys(profile.master_palette_hex))
        max_colors = 8
    elif profile and profile.master_palette_hex is None:
        # Free-color console — let Image2Pixel choose colors freely
        fixed_palette = None
        max_colors = profile.max_colors_per_tile * 2  # generous headroom
    else:
        # Default (no console specified) — NES behavior for backward compat
        fixed_palette = list(dict.fromkeys(_NES_PALETTE_HEX))
        max_colors = 8

    # Tiles: bump max_colors to preserve texture variation through Image2Pixel
    if is_tile_type and not palette_colors:
        max_colors = max(max_colors, 12)

    payload = {
        "image_url": image_url,
        "max_colors": max_colors,
        "snap_grid": True,
        "transparent_background": not is_tile_type,
        "cleanup_jaggy": not is_tile_type,  # Tiles: skip jaggy cleanup to preserve mortar/texture lines
        "cleanup_morph": False,  # Don't erode small details
        "downscale_method": "dominant",
        "detect_method": "auto",
        "background_tolerance": 40,  # More aggressive background removal (catches gradient backgrounds)
        "background_mode": "corners",  # Detect background from corner pixels
    }
    # Only send fixed_palette when we have one (free-color consoles skip it)
    if fixed_palette is not None:
        payload["fixed_palette"] = fixed_palette
    # Only set scale if explicitly provided (otherwise auto-detect)
    if pixel_scale is not None:
        payload["scale"] = pixel_scale

    async with httpx.AsyncClient(timeout=300.0) as client:
        response = await _post_with_retry(
            client, _IMAGE2PIXEL_API_URL, json=payload, headers=_fal_headers(fal_key)
        )
        data = response.json()

    images = data.get("images", [])
    if not images:
        raise RuntimeError("Image2Pixel returned no images")

    # Image2Pixel returns two images:
    # [0] = full-size processed (512x512 with pixel grid visible)
    # [1] = downscaled to actual pixel art resolution
    full_img = await _download_image(images[0]["url"])

    if len(images) > 1:
        scaled_img = await _download_image(images[1]["url"])
    else:
        # Fallback: downscale the full image ourselves
        scaled_img = full_img.resize(
            (target_w, target_h), resample=Image.Resampling.NEAREST
        )

    return full_img, scaled_img


# ---------------------------------------------------------------------------
# Reference image helper
# ---------------------------------------------------------------------------

def prepare_reference_url(image: Image.Image) -> str:
    """
    Convert a PIL Image to a ``data:image/png;base64,…`` URL for FLUX Dev img2img.

    Upscales small pixel art to 512×512 using nearest-neighbor to give FLUX
    enough resolution to work with, then base64 encodes.
    """
    import base64

    img = image.convert("RGBA")
    if img.width < 512 or img.height < 512:
        img = img.resize((512, 512), resample=Image.Resampling.NEAREST)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return f"data:image/png;base64,{b64}"


# ---------------------------------------------------------------------------
# Combined pipeline: FLUX → Image2Pixel
# ---------------------------------------------------------------------------

async def generate_image(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    reference_image_url: str | None = None,
    reference_strength: float = 0.9,
    palette_colors: list[str] | None = None,
    seed: int | None = None,
    asset_type: str = "character",
    era: str = "mid",
    force_pixel_scale: int | None = None,
    console: str | None = None,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    """
    Generate pixel art via the two-step pipeline.

    When ``reference_image_url`` is provided, uses FLUX Dev image-to-image
    instead of FLUX Schnell text-to-image.

    Returns (concept_image, full_pixelized, downscaled_pixel_art).
    """
    fal_key = _get_fal_key()
    _reserve_generation()

    try:
        # Step 1: Generate concept — text-to-image or image-to-image
        if reference_image_url is not None:
            concept_url = await _generate_from_reference(
                prompt,
                negative_prompt,
                reference_image_url,
                reference_strength,
                fal_key,
                seed=seed,
            )
        else:
            concept_url = await _generate_concept(
                prompt, negative_prompt, fal_key, seed=seed
            )

        # Note: GB DMG/Pocket grayscale desaturation was considered here but
        # fal.ai's Image2Pixel doesn't accept large data URLs. Instead, the
        # fixed_palette (4 green/gray shades) passed to Image2Pixel already
        # constrains output to luminance-appropriate colors, and enforcement
        # handles final remapping.

        concept_img = await _download_image(concept_url)

        # Step 2: Convert to pixel art with Image2Pixel
        full_img, scaled_img = await _pixelize(
            concept_url, width, height, fal_key, palette_colors,
            asset_type=asset_type, era=era, force_pixel_scale=force_pixel_scale,
            console=console,
        )
    except Exception:
        _refund_generation()
        raise

    return concept_img, full_img, scaled_img


# ---------------------------------------------------------------------------
# Mock client for development / testing
# ---------------------------------------------------------------------------

def generate_image_mock(
    prompt: str,
    width: int,
    height: int,
    reference_image_url: str | None = None,
    reference_strength: float = 0.9,
    palette_colors: list[str] | None = None,
    seed: int | None = None,
    asset_type: str = "character",
) -> tuple[Image.Image, Image.Image, Image.Image]:
    """Return synthetic test images for the three pipeline stages."""
    rng = random.Random(seed if seed is not None else hash(prompt) & 0xFFFF_FFFF)

    def rand_color() -> tuple[int, int, int, int]:
        r = rng.choice([0, 85, 170, 255])
        g = rng.choice([0, 85, 170, 255])
        b = rng.choice([0, 85, 170, 255])
        return (r, g, b, 255)

    # Mock concept (512x512)
    concept = Image.new("RGBA", (_FLUX_SIZE, _FLUX_SIZE), rand_color())

    # Mock full pixelized (512x512)
    full = Image.new("RGBA", (_FLUX_SIZE, _FLUX_SIZE), rand_color())

    # Mock downscaled (target size with border)
    fill = rand_color()
    border = rand_color()
    scaled = Image.new("RGBA", (width, height), fill)
    if width >= 2 and height >= 2:
        pixels = scaled.load()
        for x in range(width):
            pixels[x, 0] = border
            pixels[x, height - 1] = border
        for y in range(height):
            pixels[0, y] = border
            pixels[width - 1, y] = border

    return concept, full, scaled


# ---------------------------------------------------------------------------
# Unified entry point (respects RETROGAZE_MOCK)
# ---------------------------------------------------------------------------

async def get_image(
    prompt: str,
    negative_prompt: str,
    width: int,
    height: int,
    reference_image_url: str | None = None,
    reference_strength: float = 0.9,
    palette_colors: list[str] | None = None,
    seed: int | None = None,
    asset_type: str = "character",
    era: str = "mid",
    force_pixel_scale: int | None = None,
    console: str | None = None,
) -> tuple[Image.Image, Image.Image, Image.Image]:
    """
    Return generated images, using mock mode when ``RETROGAZE_MOCK=1``.

    Returns (concept_image, full_pixelized, downscaled_pixel_art).
    """
    if os.environ.get("RETROGAZE_MOCK", "").strip() == "1":
        return generate_image_mock(
            prompt, width, height, reference_image_url, reference_strength,
            palette_colors, seed=seed, asset_type=asset_type,
        )
    return await generate_image(
        prompt, negative_prompt, width, height, reference_image_url,
        reference_strength, palette_colors, seed=seed, asset_type=asset_type,
        era=era, force_pixel_scale=force_pixel_scale, console=console,
    )

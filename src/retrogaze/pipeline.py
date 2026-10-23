"""
Full Retrogaze generation pipeline.

Ties together:
  1. Prompt assembly   (prompts.build_prompt)
  2. Image generation  (generate.get_image) — FLUX concept → Image2Pixel
  3. Constraint enforcement (enforce.enforce_constraints)

The pipeline is fully async; the synchronous ``enforce_constraints`` call is
offloaded to a thread so it does not block the event loop.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

from .generate import get_image, prepare_reference_url
from .prompts import build_prompt, build_frame_prompt
from .cleanup import (
    full_cleanup, slice_spritesheet, slice_tileset,
    composite_horizontal, composite_grid,
    normalize_frame_sizes, remove_small_regions,
    generate_attack_frames, generate_walk_frames,
    generate_death_frames, generate_cast_frames,
    is_degenerate_output,
)
from . import enforce_constraints


# ---------------------------------------------------------------------------
# Degenerate-output retry budget
# ---------------------------------------------------------------------------
# Number of times the single-frame path will re-generate when the processed
# result collapses to a blank / solid fill before failing loudly.
_DEGENERATE_MAX_RETRIES = 3


# ---------------------------------------------------------------------------
# Reference strength defaults per animation/asset type
# ---------------------------------------------------------------------------

_REFERENCE_STRENGTHS: dict[str, float] = {
    "walk": 0.75,
    "run": 0.75,
    "idle": 0.75,
    "attack": 0.78,
    "jump": 0.75,
    "death": 0.68,
    "cast": 0.76,
    "directional": 0.70,
    "tileset": 0.75,
}

_TILE_POSITIONS_ORDER: list[str] = [
    "center",
    "top", "bottom", "left", "right",
    "top_left", "top_right", "bottom_left", "bottom_right",
]


def _extract_palette(image: "Image.Image") -> list[str]:
    """Extract hex color palette from a processed sprite's opaque pixels."""
    import numpy as np

    arr = np.array(image.convert("RGBA"), dtype=np.uint8)
    opaque = arr[:, :, 3] > 0
    if not np.any(opaque):
        return []
    colors = arr[opaque][:, :3]
    unique = np.unique(colors.reshape(-1, 3), axis=0)
    return [f"#{r:02x}{g:02x}{b:02x}" for r, g, b in unique]


async def _generate_per_frame(
    description: str,
    asset_type: str,
    size: tuple[int, int],
    frame_count: int,
    animation_type: str,
    view: str,
    palette_mood: str,
    outline: str,
    era: str,
    palette_colors: list[str] | None,
    seed: int | None,
    max_colors: int | None,
    out_dir: Path,
    console: str | None = None,
) -> list:
    """
    Generate *frame_count* individual frames sequentially.

    Frame 0 is generated from scratch (text-to-image via FLUX Schnell).
    Frames 1..N-1 use frame 0 as a reference image (image-to-image via FLUX Dev)
    to maintain character consistency while allowing pose changes.

    Each frame goes through: get_image → full_cleanup → enforce_constraints.

    Returns a list of (cleaned_image, metadata) tuples.
    """
    from PIL import Image as PILImage

    width, height = size
    base_ref_strength = _REFERENCE_STRENGTHS.get(
        "directional" if asset_type == "directional" else animation_type.lower(),
        0.65,
    )
    frames: list[tuple] = []
    reference_url: str | None = None
    frame0_palette: list[str] | None = None
    warnings: list[str] = []

    # P1-3: Force consistent pixel scale for per-frame mode
    forced_scale = 8 if era in ("mid", "late") else None

    for i in range(frame_count):
        is_ref = (i == 0)

        # R2: Per-frame reference strength ramp.
        # Frame 1 gets lower strength to allow the initial pose change;
        # frames 2+ use the base strength to stay consistent.
        if is_ref:
            frame_ref_strength = base_ref_strength
        elif i == 1:
            frame_ref_strength = max(0.50, base_ref_strength - 0.12)
        else:
            frame_ref_strength = base_ref_strength

        # P0-3: Lock subsequent frames to frame 0's palette
        effective_palette = palette_colors if is_ref else (frame0_palette or palette_colors)

        # Build per-frame prompt
        prompt_data = build_frame_prompt(
            description=description,
            asset_type=asset_type,
            frame_index=i,
            frame_total=frame_count,
            is_reference_frame=is_ref,
            animation_type=animation_type,
            view=view,
            palette_mood=palette_mood,
            outline=outline,
            era=era,
            palette_colors=effective_palette,
            console=console or "nes",
        )
        prompt = prompt_data["prompt"]

        try:
            concept_img, full_pixel_img, scaled_img = await get_image(
                prompt=prompt,
                negative_prompt="",
                width=width,
                height=height,
                reference_image_url=reference_url,
                reference_strength=frame_ref_strength,
                palette_colors=effective_palette,
                seed=seed,
                asset_type="character",  # treat each frame as a single character
                era=era,
                force_pixel_scale=forced_scale,
                console=console,
            )
        except Exception as exc:
            if is_ref:
                raise RuntimeError(
                    f"Failed to generate reference frame (frame 0): {exc}"
                ) from exc
            # Non-reference frame failed — substitute frame 0
            warnings.append(f"Frame {i} generation failed ({exc}), substituted frame 0.")
            frames.append(frames[0])
            continue

        # Save concept for debugging
        concept_img.save(str(out_dir / f"concept_frame_{i}.png"), format="PNG")

        # Detect near-black / empty FLUX output (e.g. "dark mage" →
        # FLUX generates a black image).  Retry once with a brightness
        # hint appended to the prompt; if still empty, treat as failure.
        import numpy as _np_check
        _concept_arr = _np_check.array(concept_img.convert("RGB"), dtype=_np_check.uint8)
        if _concept_arr.max() < 30:
            warnings.append(f"Frame {i}: FLUX output near-black (max brightness {_concept_arr.max()}), retrying with brightness hint.")
            bright_prompt = prompt + " well-lit character, visible colors, not silhouette"
            try:
                concept_img.close()
                full_pixel_img.close()
                scaled_img.close()
                concept_img, full_pixel_img, scaled_img = await get_image(
                    prompt=bright_prompt,
                    negative_prompt="dark, silhouette, shadow, all black",
                    width=width,
                    height=height,
                    reference_image_url=reference_url,
                    reference_strength=frame_ref_strength,
                    palette_colors=effective_palette,
                    seed=(seed + 1) if seed else None,
                    asset_type="character",
                    era=era,
                    force_pixel_scale=forced_scale,
                    console=console,
                )
                concept_img.save(str(out_dir / f"concept_frame_{i}_retry.png"), format="PNG")
            except Exception:
                if is_ref:
                    raise RuntimeError(
                        f"Frame 0 produced black image and retry failed"
                    )
                warnings.append(f"Frame {i} retry also failed, substituting frame 0.")
                frames.append(frames[0])
                continue

        # Cleanup
        cleaned = full_cleanup(
            scaled_img, era=era, palette_colors=effective_palette,
            asset_type="character", palette_mood=palette_mood,
            max_colors=max_colors, animation_type=animation_type,
            console=console,
        )

        # Enforce constraints
        frame_raw = out_dir / f"raw_frame_{i}.png"
        cleaned.save(str(frame_raw), format="PNG")

        frame_processed = out_dir / f"processed_frame_{i}.png"
        meta = await asyncio.to_thread(
            enforce_constraints,
            frame_raw,
            target_size=None,
            asset_type="character",
            output_path=frame_processed,
            prompt=prompt,
            console=console,
        )

        result_img = PILImage.open(str(frame_processed)).convert("RGBA")

        # R2/R3: Record frame 0 bbox for normalize_frame_sizes downstream.
        # Scaling pixel art distorts it, so we only record — the existing
        # normalize_frame_sizes handles canvas padding, and the content
        # variance is an inherent FLUX limitation we accept.
        frames.append((result_img, meta))

        if is_ref:
            # P1-2: Use the pixelized image (Image2Pixel 512x512 output) as
            # FLUX reference — cleaner than concept (painterly) or processed
            # (too small). Already has flat colors and pixel grid structure.
            reference_url = prepare_reference_url(full_pixel_img)

            # P0-3: Extract frame 0's palette for locking subsequent frames
            frame0_palette = _extract_palette(result_img)

        concept_img.close()
        full_pixel_img.close()

    # P1-4: Normalize all frames to uniform dimensions
    if frames:
        frame_images = [img for img, _meta in frames]
        frame_images = normalize_frame_sizes(frame_images)
        # Apply remove_small_regions as final cleanup on normalized frames
        frame_images = [remove_small_regions(img, min_region_pixels=5) for img in frame_images]
        frames = [(img, meta) for img, (_, meta) in zip(frame_images, frames)]

        # Re-save normalized frames
        for i, (img, _meta) in enumerate(frames):
            img.save(str(out_dir / f"frame_{i}.png"), format="PNG")

    return frames, warnings


async def _generate_tileset_per_tile(
    description: str,
    size: tuple[int, int],
    era: str,
    palette_mood: str,
    outline: str,
    palette_colors: list[str] | None,
    seed: int | None,
    max_colors: int | None,
    out_dir: Path,
    console: str | None = None,
) -> tuple[dict, list[str]]:
    """
    Generate 9 tiles individually for a 3×3 connected tileset.

    Center tile is generated first (text-to-image). All 8 surrounding tiles
    use center as reference (image-to-image) to maintain palette/texture
    consistency.

    Returns (dict of tile_name → PIL Image, warnings list).
    """
    from PIL import Image as PILImage

    width, height = size
    ref_strength = _REFERENCE_STRENGTHS["tileset"]
    tiles: dict = {}
    reference_url: str | None = None
    center_palette: list[str] | None = None
    warnings: list[str] = []

    for tile_pos in _TILE_POSITIONS_ORDER:
        is_ref = (tile_pos == "center")

        # P0-3: Lock surrounding tiles to center tile's palette
        effective_palette = palette_colors if is_ref else (center_palette or palette_colors)

        prompt_data = build_frame_prompt(
            description=description,
            asset_type="tileset",
            frame_index=0,
            frame_total=9,
            is_reference_frame=is_ref,
            tile_position=tile_pos,
            palette_mood=palette_mood,
            outline=outline,
            era=era,
            palette_colors=effective_palette,
            console=console or "nes",
        )
        prompt = prompt_data["prompt"]

        try:
            concept_img, full_pixel_img, scaled_img = await get_image(
                prompt=prompt,
                negative_prompt="",
                width=max(width, 8),
                height=max(height, 8),
                reference_image_url=reference_url,
                reference_strength=ref_strength,
                palette_colors=effective_palette,
                seed=seed,
                asset_type="tile",
                era=era,
                console=console,
            )
        except Exception as exc:
            if is_ref:
                raise RuntimeError(
                    f"Failed to generate center tile: {exc}"
                ) from exc
            warnings.append(f"Tile {tile_pos} failed ({exc}), substituted center.")
            tiles[tile_pos] = tiles["center"].copy()
            continue

        concept_img.save(str(out_dir / f"concept_{tile_pos}.png"), format="PNG")

        cleaned = full_cleanup(
            scaled_img, era=era, palette_colors=effective_palette,
            asset_type="tile", palette_mood=palette_mood,
            max_colors=max_colors, console=console,
        )

        tile_raw = out_dir / f"raw_{tile_pos}.png"
        cleaned.save(str(tile_raw), format="PNG")

        tile_processed = out_dir / f"processed_{tile_pos}.png"
        await asyncio.to_thread(
            enforce_constraints,
            tile_raw,
            target_size=None,
            asset_type="tile",
            output_path=tile_processed,
            prompt=prompt,
            console=console,
        )

        result_img = PILImage.open(str(tile_processed)).convert("RGBA")
        tiles[tile_pos] = result_img

        if is_ref:
            # P1-2: Use pixelized image as reference (cleaner than concept)
            reference_url = prepare_reference_url(full_pixel_img)
            # P0-3: Extract center tile palette for locking surrounding tiles
            center_palette = _extract_palette(result_img)

        concept_img.close()
        full_pixel_img.close()

    return tiles, warnings


async def run_pipeline(
    description: str,
    asset_type: str = "character",
    size: tuple[int, int] = (16, 16),
    view: str = "side",
    palette_mood: str = "auto",
    outline: str = "Black",
    era: str = "mid",
    output_dir: str | os.PathLike | None = None,
    reference_image_path: str | None = None,
    reference_strength: float = 0.9,
    frame_count: int = 4,
    animation_type: str = "walk",
    palette_colors: list[str] | None = None,
    palette_preset: str | None = None,
    seed: int | None = None,
    generate_variants: int = 0,
    max_colors: int | None = None,
    generation_mode: str = "flux",
    console: str | None = None,
    anthropic_key: str | None = None,
) -> dict:
    """
    Run the full Retrogaze generation pipeline.

    Steps
    -----
    1. Build a prompt from the supplied options.
    2. Generate images via FLUX → Image2Pixel or Claude API + pixel-mcp.
    3. Save intermediate images.
    4. Run ``enforce_constraints`` on the downscaled pixel art.
    5. Return a metadata dict plus file paths.

    When ``generation_mode="aseprite"``, uses Claude API (Haiku) to draw
    sprites natively in Aseprite via pixel-mcp. Sprites are palette-compliant
    by construction — cleanup is skipped, only grid alignment is validated.

    Output-size contract (deliberate design — see also rg-061, restored
    2026-07-05 after d680c14 reclassified it as a bug):
      * The requested ``size`` (e.g. "16x16") is a prompt target for the
        generator and the target for the *secondary* strict render. It is
        NOT a promise about the primary output's dimensions.
      * The PRIMARY output keeps the sprite's NATURAL resolution: after
        background-removal trim, ``enforce_constraints`` runs with
        ``target_size=None`` and only pads dimensions up to tile-grid
        multiples. A "16x16" request may therefore legitimately deliver
        56×120, 72×112, etc. The 2026-09-30 funnel check flagged this as
        odd — it is by design.
      * The exact-target render (``strict_nes.png``) is produced alongside
        and is served only when the request sets ``strict_size=true``
        (see ``GenerateRequest.strict_size`` in api.py).
    """
    width, height = size

    # Resolve palette preset to explicit colors
    if palette_preset and not palette_colors:
        from .palette import get_preset_palette
        resolved = get_preset_palette(palette_preset)
        if resolved is None:
            raise ValueError(f"Unknown palette preset: {palette_preset!r}")
        palette_colors = resolved

    # Determine output directory early — per-frame paths need it during gen
    _temp_dir_obj = None
    if output_dir is None:
        _temp_dir_obj = tempfile.TemporaryDirectory()
        out_dir = Path(_temp_dir_obj.name)
    else:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)

    # -----------------------------------------------------------------------
    # Aseprite generation path (Claude API + pixel-mcp)
    # Single-frame only for now. Sprites are palette-compliant by construction.
    # Gated to retro/early eras — mid/late falls back to FLUX automatically.
    # -----------------------------------------------------------------------
    fallback_notice: str | None = None
    if generation_mode == "aseprite" and era in ("mid", "late"):
        import logging as _logging
        _logging.getLogger(__name__).warning(
            "Aseprite mode not supported for %s era, falling back to FLUX.", era
        )
        generation_mode = "flux"
        fallback_notice = (
            f"Requested generation_mode='aseprite' for era='{era}', "
            "so generation used 'flux' instead."
        )

    if generation_mode == "aseprite":
        from .generate_aseprite import generate_aseprite_sprite

        result = await generate_aseprite_sprite(
            description=description,
            asset_type=asset_type,
            size=size,
            view=view,
            palette_mood=palette_mood,
            outline=outline,
            era=era,
            palette_colors=palette_colors,
            seed=seed,
            output_dir=str(out_dir),
            console=console or "nes",
            anthropic_key=anthropic_key,
        )

        image = result["image"]

        # Run grid alignment validation (sprites are already palette-valid)
        processed_path = out_dir / "processed.png"
        image.save(str(processed_path), format="PNG")

        raw_path = out_dir / "raw.png"
        image.save(str(raw_path), format="PNG")

        # Run constraint enforcement at the NATURAL pixel art resolution
        #   (don't force-downscale to target — that destroys detail).
        # rg-061: restored after d680c14 (2026-07-05) reclassified this
        # deliberate April design decision as a bug and passed the target
        # size, collapsing every shipped sprite to the requested grid size.
        metadata: dict = await asyncio.to_thread(
            enforce_constraints,
            raw_path,
            target_size=None,
            asset_type=asset_type,
            output_path=processed_path,
            prompt=description,
            console=console,
        )

        metadata["paths"] = {
            "processed": str(processed_path),
            "raw": str(raw_path),
        }
        if result.get("aseprite_path"):
            metadata["paths"]["aseprite"] = result["aseprite_path"]
        metadata["generation_mode"] = "aseprite"
        metadata["cost_usd"] = result["cost_usd"]
        metadata["tool_calls"] = result["tool_calls"]
        metadata["tokens"] = result["tokens"]
        metadata["prompt"] = description
        metadata["seed"] = seed

        meta_json_path = out_dir / "metadata.json"
        with open(meta_json_path, "w", encoding="utf-8") as fh:
            json.dump(
                {k: v for k, v in metadata.items() if k != "image"},
                fh, indent=2, default=str,
            )
        metadata["paths"]["metadata"] = str(meta_json_path)

        if fallback_notice:
            metadata.setdefault("warnings", []).append(fallback_notice)

        return metadata

    # -----------------------------------------------------------------------
    # Multi-frame path: spritesheet / directional / tileset
    # Generate each frame individually, then composite into a sheet.
    # -----------------------------------------------------------------------
    if asset_type in ("spritesheet", "directional", "tileset"):
        from PIL import Image as PILImage

        if asset_type == "tileset":
            tile_dict, warnings = await _generate_tileset_per_tile(
                description=description,
                size=size,
                era=era,
                palette_mood=palette_mood,
                outline=outline,
                palette_colors=palette_colors,
                seed=seed,
                max_colors=max_colors,
                out_dir=out_dir,
                console=console,
            )

            # Composite into grid
            processed_img = composite_grid(tile_dict)
            processed_path = out_dir / "processed.png"
            processed_img.save(str(processed_path), format="PNG")

            # Save individual tiles and check seamlessness
            from .tiles import check_tile_seamless
            tile_paths: dict[str, str] = {}
            seamless_report: dict[str, dict] = {}
            for name, tile_img in tile_dict.items():
                tp = out_dir / f"{name}.png"
                tile_img.save(str(tp), format="PNG")
                tile_paths[name] = str(tp)
                seamless_report[name] = check_tile_seamless(tile_img)

            metadata: dict = {
                "tileset": {
                    "grid": 3,
                    "tile_names": list(tile_dict.keys()),
                    "tile_count": len(tile_dict),
                    "seamless": seamless_report,
                },
                "paths": {
                    "processed": str(processed_path),
                    "tiles": tile_paths,
                },
                "seed": seed,
                "prompt": "(per-tile generation, see concept files)",
                "negative_prompt": "",
            }
            if warnings:
                metadata["warnings"] = warnings

        else:
            # Spritesheet, directional, or idle
            is_idle = (asset_type == "spritesheet" and animation_type.lower() == "idle")
            is_jump = (asset_type == "spritesheet" and animation_type.lower() == "jump")
            is_attack = (asset_type == "spritesheet" and animation_type.lower() == "attack")
            is_walk = (asset_type == "spritesheet" and animation_type.lower() == "walk")
            is_death = (asset_type == "spritesheet" and animation_type.lower() == "death")
            is_cast = (asset_type == "spritesheet" and animation_type.lower() == "cast")

            if is_idle or is_jump or is_attack or is_walk or is_death or is_cast:
                # Programmatic animations: generate one frame, create motion
                # via pixel offsets. FLUX cannot produce consistent frames
                # for these types (idle: 28% IoU, jump: fragmentation,
                # attack: 3.3/5 ceiling from subject-dependent drift).
                actual_frame_count = 1
            else:
                actual_frame_count = 4 if asset_type == "directional" else frame_count

            frame_results, warnings = await _generate_per_frame(
                description=description,
                asset_type=asset_type,
                size=size,
                frame_count=actual_frame_count,
                animation_type=animation_type,
                view=view,
                palette_mood=palette_mood,
                outline=outline,
                era=era,
                palette_colors=palette_colors,
                seed=seed,
                max_colors=max_colors,
                out_dir=out_dir,
                console=console,
            )

            # Extract images from (image, meta) tuples
            frame_images = [r[0] for r in frame_results]

            # Programmatic idle: expand single frame into breathing animation
            if is_idle and len(frame_images) == 1:
                base_img = frame_images[0]
                base_meta = frame_results[0][1]
                w, h = base_img.size
                shifted_up = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
                shifted_up.paste(base_img, (0, -1))
                shifted_down = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
                shifted_down.paste(base_img, (0, 1))
                idle_count = max(2, min(frame_count, 4))
                if idle_count == 2:
                    frame_images = [base_img, shifted_up]
                else:
                    frame_images = [base_img, shifted_up, base_img.copy(), shifted_down][:idle_count]
                frame_results = [(img, base_meta) for img in frame_images]
                warnings.append("Idle animation uses programmatic 1px shift (not per-frame FLUX generation).")

            # Programmatic jump: single frame shifted vertically to simulate arc.
            # Matches NES convention (same sprite, different y-position).
            if is_jump and len(frame_images) == 1:
                base_img = frame_images[0]
                base_meta = frame_results[0][1]
                w, h = base_img.size
                # Jump arc offsets: crouch(0), rise(-2), peak(-4), land(-2)
                # Negative = shift up (character rises)
                jump_count = max(2, min(frame_count, 4))
                if jump_count == 2:
                    offsets = [0, -3]
                else:
                    offsets = [0, -2, -4, -2][:jump_count]
                jump_frames = []
                for dy in offsets:
                    shifted = PILImage.new("RGBA", (w, h), (0, 0, 0, 0))
                    shifted.paste(base_img, (0, dy))
                    jump_frames.append(shifted)
                frame_images = jump_frames
                frame_results = [(img, base_meta) for img in frame_images]
                warnings.append("Jump animation uses programmatic vertical offset (not per-frame FLUX generation).")

            # Programmatic attack: single frame with weapon repositioned.
            # Detects weapon as a separate connected component and moves it
            # through a swing arc. Falls back to body lean if no weapon found.
            # Matches NES convention (Zelda: sword = separate hardware sprite).
            if is_attack and len(frame_images) == 1:
                base_img = frame_images[0]
                base_meta = frame_results[0][1]
                attack_count = max(2, min(frame_count, 4))
                frame_images = generate_attack_frames(base_img, attack_count)
                frame_results = [(img, base_meta) for img in frame_images]
                warnings.append("Attack animation uses programmatic weapon overlay (not per-frame FLUX generation).")

            # Programmatic walk: single frame with leg region shifted to
            # simulate stepping, plus vertical bob.
            if is_walk and len(frame_images) == 1:
                base_img = frame_images[0]
                base_meta = frame_results[0][1]
                walk_count = max(2, min(frame_count, 4))
                frame_images = generate_walk_frames(base_img, walk_count)
                frame_results = [(img, base_meta) for img in frame_images]
                warnings.append("Walk animation uses programmatic leg shift (not per-frame FLUX generation).")

            # Programmatic death: progressive shear + drop to simulate
            # falling backward. NES convention (Castlevania knockback).
            if is_death and len(frame_images) == 1:
                base_img = frame_images[0]
                base_meta = frame_results[0][1]
                death_count = max(2, min(frame_count, 4))
                frame_images = generate_death_frames(base_img, death_count)
                frame_results = [(img, base_meta) for img in frame_images]
                warnings.append("Death animation uses programmatic shear/drop (not per-frame FLUX generation).")

            # Programmatic cast: minimal body motion (1px hand raise),
            # glow pixels emanate from staff/hand area.  FF NES mage
            # style — tiny gesture, spell effect is the visual interest.
            if is_cast and len(frame_images) == 1:
                base_img = frame_images[0]
                base_meta = frame_results[0][1]
                cast_count = max(2, min(frame_count, 4))
                frame_images = generate_cast_frames(base_img, cast_count)
                frame_results = [(img, base_meta) for img in frame_images]
                warnings.append("Cast animation uses programmatic glow effect (not per-frame FLUX generation).")

            # Save individual frames
            frame_paths: list[str] = []
            if asset_type == "directional":
                direction_names = ["front", "right", "back", "left"]
                for i, (frame_img, name) in enumerate(zip(frame_images, direction_names)):
                    fp = out_dir / f"{name}.png"
                    frame_img.save(str(fp), format="PNG")
                    frame_paths.append(str(fp))
            else:
                for i, frame_img in enumerate(frame_images):
                    fp = out_dir / f"frame_{i}.png"
                    frame_img.save(str(fp), format="PNG")
                    frame_paths.append(str(fp))

            # Composite into sheet
            processed_img = composite_horizontal(frame_images)
            sheet_name = "directional_sheet.png" if asset_type == "directional" else "spritesheet.png"
            sheet_path = out_dir / sheet_name
            processed_img.save(str(sheet_path), format="PNG")

            processed_path = out_dir / "processed.png"
            processed_img.save(str(processed_path), format="PNG")

            metadata = {
                "paths": {
                    "processed": str(processed_path),
                    "frames": frame_paths,
                    "spritesheet": str(sheet_path),
                },
                "seed": seed,
                "prompt": "(per-frame generation, see concept files)",
                "negative_prompt": "",
            }

            if asset_type == "directional":
                metadata["directions"] = {
                    "count": len(frame_images),
                    "names": direction_names[:len(frame_images)],
                }
            else:
                metadata["animation"] = {
                    "frame_count": len(frame_images),
                    "animation_type": animation_type,
                    "frame_duration_ms": 150,
                    "loop": True,
                }

            if warnings:
                metadata["warnings"] = warnings

        # Write metadata JSON
        meta_json_path = out_dir / "metadata.json"
        with open(meta_json_path, "w", encoding="utf-8") as fh:
            json.dump(metadata, fh, indent=2)
        metadata["paths"]["metadata"] = str(meta_json_path)

        if fallback_notice:
            metadata.setdefault("warnings", []).append(fallback_notice)

        return metadata

    # -----------------------------------------------------------------------
    # Single-frame path: character / enemy / item / tile / prop / boss
    # Original flow — unchanged from before Wave 3.
    # -----------------------------------------------------------------------
    gen_width = width
    gen_height = height

    # 1. Build prompts
    prompt_data = build_prompt(
        description=description,
        asset_type=asset_type,
        size=size,
        view=view,
        palette_mood=palette_mood,
        outline=outline,
        era=era,
        frame_count=frame_count,
        animation_type=animation_type,
        palette_colors=palette_colors,
        console=console or "nes",
    )
    prompt = prompt_data["prompt"]
    negative_prompt = prompt_data["negative_prompt"]

    # 2. Resolve reference image
    reference_url = None
    if reference_image_path is not None:
        from PIL import Image as PILImage
        ref_path = Path(reference_image_path)
        if ref_path.exists():
            ref_img = PILImage.open(ref_path).convert("RGBA")
            reference_url = prepare_reference_url(ref_img)
            ref_img.close()

    # 3-5. Generate → cleanup → enforce, with degenerate-output detect+retry.
    # The concept/cleanup stage can collapse to a blank (fully transparent) or
    # a solid fill — e.g. when background removal misfires and strips the whole
    # subject. Detect that on the *processed* result and re-generate up to
    # _DEGENERATE_MAX_RETRIES times with a fresh seed + brightness hint. If it
    # is still degenerate after the budget, fail loudly rather than silently
    # returning a blank asset.
    import logging as _logging
    _log = _logging.getLogger(__name__)

    from PIL import Image as _PILImage

    concept_path = out_dir / "concept.png"
    full_pixel_path = out_dir / "full_pixelized.png"
    raw_path = out_dir / "raw.png"
    processed_path = out_dir / "processed.png"
    target_w, target_h = gen_width, gen_height

    metadata: dict | None = None
    natural_w = natural_h = 0
    base_negative = negative_prompt

    for attempt in range(_DEGENERATE_MAX_RETRIES + 1):
        if attempt == 0:
            attempt_prompt = prompt
            attempt_negative = base_negative
            attempt_seed = seed
        else:
            # Nudge away from blank/silhouette collapses and reseed so FLUX
            # explores a different sample.
            attempt_prompt = prompt + " well-lit, visible subject, clear colors, centered"
            attempt_negative = (base_negative + ", blank, empty, all transparent, "
                                "solid fill, silhouette").lstrip(", ")
            attempt_seed = (seed + attempt) if seed is not None else None
            _log.warning(
                "Degenerate output for %r (attempt %d/%d) — regenerating with "
                "fresh seed + brightness hint.",
                asset_type, attempt, _DEGENERATE_MAX_RETRIES,
            )

        concept_img, full_pixel_img, scaled_img = await get_image(
            prompt=attempt_prompt,
            negative_prompt=attempt_negative,
            width=gen_width,
            height=gen_height,
            reference_image_url=reference_url,
            reference_strength=reference_strength,
            palette_colors=palette_colors,
            seed=attempt_seed,
            asset_type=asset_type,
            era=era,
            console=console,
        )

        # Save intermediate images for debugging/inspection
        concept_img.save(str(concept_path), format="PNG")
        concept_img.close()
        full_pixel_img.save(str(full_pixel_path), format="PNG")
        full_pixel_img.close()

        # Full cleanup: background removal → artifact color removal → trim
        scaled_img = full_cleanup(
            scaled_img, era=era, palette_colors=palette_colors,
            asset_type=asset_type, palette_mood=palette_mood,
            max_colors=max_colors, console=console,
        )

        # Save the cleaned Image2Pixel output as raw input for enforcement
        scaled_img.save(str(raw_path), format="PNG")

        natural_w, natural_h = scaled_img.size

        # Run constraint enforcement at the NATURAL pixel art resolution
        #   (don't force-downscale to target — that destroys detail).
        # This is the PRIMARY output. The exact-target render is produced
        # below as a SECONDARY file (strict_nes.png) and is served only when
        # the request sets strict_size=true — which is what api.py's
        # strict_size field documents ("strict_size=false returns the natural
        # higher-resolution output for best quality").
        # rg-061: restored after d680c14 (2026-07-05) reclassified this
        # deliberate April design decision as a bug and passed the target
        # size, collapsing every shipped sprite to the requested grid size
        # and silently making strict_size=false behave like strict_size=true.
        metadata = await asyncio.to_thread(
            enforce_constraints,
            raw_path,
            target_size=None,
            asset_type=asset_type,
            output_path=processed_path,
            prompt=prompt,
            console=console,
        )

        processed_check = _PILImage.open(str(processed_path)).convert("RGBA")
        degenerate = is_degenerate_output(processed_check)
        processed_check.close()

        if not degenerate:
            break
    else:
        # Loop exhausted without `break` — every attempt was degenerate.
        raise RuntimeError(
            f"Pipeline produced a degenerate (blank/solid) output for "
            f"asset_type={asset_type!r}, console={console!r} after "
            f"{_DEGENERATE_MAX_RETRIES} retries. Refusing to return an empty "
            f"asset. Last processed output: {processed_path}"
        )

    # Secondary: strict target-size version if different from natural.
    # Capture its metadata so the API can serve accurate dimensions/compliance
    # when the user opts into strict_size on the request.
    needs_resize = (natural_w, natural_h) != (target_w, target_h)
    strict_metadata: dict | None = None
    if needs_resize:
        strict_path = out_dir / "strict_nes.png"
        strict_metadata = await asyncio.to_thread(
            enforce_constraints,
            raw_path,
            target_size=(target_w, target_h),
            asset_type=asset_type,
            output_path=strict_path,
            prompt=prompt,
            console=console,
        )
    else:
        strict_path = None

    # For single tile types, apply seamlessness fix
    if asset_type in ("tile",):
        from PIL import Image as PILImage
        from .tiles import make_tile_seamless
        from .palette import remap_to_nes_palette, remap_to_palette, quantize_to_bit_depth
        from .console_profile import get_profile, NES
        tile_img = PILImage.open(str(processed_path)).convert("RGBA")
        tile_img = make_tile_seamless(tile_img)
        # Re-snap to the correct console palette after seamlessness blending
        _tile_profile = get_profile(console) if console else NES
        _tile_palette_rgb = _tile_profile.master_palette_rgb()
        if _tile_palette_rgb is not None:
            if _tile_profile.name == "nes":
                tile_img = remap_to_nes_palette(tile_img)
            else:
                tile_img = remap_to_palette(tile_img, _tile_palette_rgb)
        elif _tile_profile.color_depth_bits is not None:
            _bits = {9: 3, 15: 5}.get(_tile_profile.color_depth_bits)
            if _bits:
                tile_img = quantize_to_bit_depth(tile_img, _bits)
        tile_img.save(str(processed_path), format="PNG")
        tile_img.close()

    # 6. Persist metadata
    metadata["paths"] = {
        "concept": str(concept_path),
        "full_pixelized": str(full_pixel_path),
        "raw": str(raw_path),
        "processed": str(processed_path),
    }
    if strict_path is not None:
        metadata["paths"]["strict_nes"] = str(strict_path)
        if strict_metadata:
            # Preserve strict's enforce output so the API can return matching
            # dimensions/compliance/palette/tiles when strict_size=True. Path
            # entries from strict's metadata are dropped — we manage paths here.
            metadata["strict_metadata"] = {
                k: v for k, v in strict_metadata.items() if k != "paths"
            }
    metadata["natural_dimensions"] = {"width_px": natural_w, "height_px": natural_h}
    metadata["target_dimensions"] = {"width_px": target_w, "height_px": target_h}
    metadata["prompt"] = prompt
    metadata["negative_prompt"] = negative_prompt
    metadata["seed"] = seed

    # 7. Optional palette swap variants
    if generate_variants > 0 and asset_type not in ("tile", "tileset"):
        from PIL import Image as PILImage
        from .palette import generate_palette_swaps
        processed_img = PILImage.open(str(processed_path)).convert("RGBA")
        variants = generate_palette_swaps(processed_img, num_variants=generate_variants, seed=seed)
        variant_paths: list[str] = []
        for i, variant_img in enumerate(variants):
            vp = out_dir / f"variant_{i}.png"
            variant_img.save(str(vp), format="PNG")
            variant_paths.append(str(vp))
        metadata["variants"] = {
            "count": len(variants),
        }
        metadata["paths"]["variants"] = variant_paths

    meta_json_path = out_dir / "metadata.json"
    with open(meta_json_path, "w", encoding="utf-8") as fh:
        json.dump(metadata, fh, indent=2)

    metadata["paths"]["metadata"] = str(meta_json_path)

    if fallback_notice:
        metadata.setdefault("warnings", []).append(fallback_notice)

    return metadata


async def run_pipeline_best_of_n(
    num_candidates: int = 1,
    **kwargs,
) -> dict:
    """
    Generate multiple candidates and return them all for the user to pick.

    Runs ``run_pipeline`` *num_candidates* times (sequentially to respect
    rate limits). Each candidate gets its own subdirectory.

    Returns a dict with:
    - ``"candidates"``: list of per-candidate metadata dicts
    - ``"primary"``: index 0 (first result) as the default selection
    - ``"num_candidates"``: how many were generated

    The caller/frontend should present all candidates and let the user choose.
    """
    num_candidates = max(1, min(4, num_candidates))

    if num_candidates == 1:
        result = await run_pipeline(**kwargs)
        return {
            "candidates": [result],
            "primary": 0,
            "num_candidates": 1,
        }

    # Multiple candidates — each goes in a numbered subdirectory
    base_dir = kwargs.get("output_dir")
    candidates: list[dict] = []

    for i in range(num_candidates):
        if base_dir is not None:
            candidate_dir = Path(base_dir) / f"candidate_{i}"
            candidate_dir.mkdir(parents=True, exist_ok=True)
            kwargs["output_dir"] = str(candidate_dir)

        result = await run_pipeline(**kwargs)
        candidates.append(result)

    # Restore original output_dir in kwargs
    if base_dir is not None:
        kwargs["output_dir"] = base_dir

    return {
        "candidates": candidates,
        "primary": 0,
        "num_candidates": len(candidates),
    }

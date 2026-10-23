"""
Output-resolution semantics — the regression guard for rg-061 / d680c14.

WHY THIS FILE EXISTS
--------------------
On 2026-07-05, commit ``d680c14`` changed two ``enforce_constraints`` call
sites in ``pipeline.py`` from ``target_size=None`` to the requested target
size. That collapsed the shipped sprite from its natural Image2Pixel
resolution (~64-112 px on the long side) down to the requested grid size
(typically 16x16), and silently broke the documented API contract: the
``strict_size`` field promises that ``strict_size=false`` returns "the natural
higher-resolution output for best quality", but with the primary output itself
force-resized there was no natural output left to return.

**The full 952-test suite stayed green through that commit, because no test
asserted anything about output resolution.** This file is that missing test.

Note on the built-in mock: ``generate_image_mock`` returns its downscaled stage
at *exactly* the requested size, so under plain ``RETROGAZE_MOCK=1`` natural
and target are identical and the distinction these tests exist to protect is
inexpressible. That is itself part of why the regression was invisible. So the
tests below keep ``RETROGAZE_MOCK=1`` set (belt-and-braces: no network is
reachable even if a patch were to miss) *and* substitute a ``get_image`` stand-in
that returns a natural resolution larger than the target, exactly as the real
Image2Pixel grid auto-detection does.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force mock mode before importing anything from retrogaze — no API calls.
os.environ["RETROGAZE_MOCK"] = "1"

from retrogaze import pipeline as pipeline_mod  # noqa: E402
from retrogaze.api import _select_output  # noqa: E402
from retrogaze.pipeline import run_pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    return asyncio.run(coro)


# The natural resolution a real Image2Pixel grid auto-detect would produce for
# a late-NES character. The golden warrior exemplar was 64x104; the golden
# knight was 96x112. Anything well above the 16x16 target proves the point.
NATURAL_W, NATURAL_H = 96, 112
TARGET_W, TARGET_H = 16, 16


def _fake_natural_sprite() -> Image.Image:
    """
    A sprite-shaped stand-in at natural resolution.

    Solid background (which ``full_cleanup`` strips) plus a multi-colour blob
    occupying the middle ~60% so the image survives cleanup, is not degenerate,
    and still trims to something far larger than 16x16.
    """
    bg = (0, 128, 128, 255)
    img = Image.new("RGBA", (NATURAL_W, NATURAL_H), bg)
    px = img.load()
    body = [(216, 40, 0, 255), (252, 152, 56, 255), (0, 0, 0, 255), (252, 252, 252, 255)]
    x0, x1 = int(NATURAL_W * 0.2), int(NATURAL_W * 0.8)
    y0, y1 = int(NATURAL_H * 0.2), int(NATURAL_H * 0.8)
    for y in range(y0, y1):
        for x in range(x0, x1):
            px[x, y] = body[((x // 8) + (y // 8)) % len(body)]
    return img


def _patch_get_image(monkeypatch):
    """Make the pipeline's generation stage return a larger-than-target natural image."""

    async def fake_get_image(*args, **kwargs):
        concept = Image.new("RGBA", (512, 512), (0, 128, 128, 255))
        full = Image.new("RGBA", (512, 512), (0, 128, 128, 255))
        return concept, full, _fake_natural_sprite()

    monkeypatch.setattr(pipeline_mod, "get_image", fake_get_image)


def _long_side(path: Path) -> int:
    with Image.open(path) as im:
        return max(im.size)


def _dims(path: Path) -> tuple[int, int]:
    with Image.open(path) as im:
        return im.size


# ---------------------------------------------------------------------------
# The regression guard
# ---------------------------------------------------------------------------

class TestOutputResolutionSemantics:
    def test_primary_output_keeps_natural_resolution(self, monkeypatch):
        """
        strict_size=false (the default) must yield the NATURAL output.

        This is the assertion whose absence let d680c14 ship green: with the
        regression in place the primary output is 16x16 and this fails.
        """
        _patch_get_image(monkeypatch)
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline(
                "warrior with sword and shield",
                asset_type="character",
                era="late",
                console="nes",
                size=(TARGET_W, TARGET_H),
                output_dir=tmp,
            ))
            processed = Path(result["paths"]["processed"])
            assert processed.exists()
            long_side = _long_side(processed)

        assert long_side > TARGET_W, (
            f"Primary output collapsed to the requested grid size "
            f"({_dims(processed) if processed.exists() else long_side}). The primary "
            f"output must be the natural Image2Pixel resolution — this is the "
            f"d680c14 regression (rg-061 R1)."
        )
        # Natural output is grid-aligned, not resized.
        assert long_side % 8 == 0, "Natural output should be grid-aligned to 8px tiles"

    def test_reported_dimensions_match_the_primary_file(self, monkeypatch):
        """Metadata must describe the file actually returned, not the request."""
        _patch_get_image(monkeypatch)
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline(
                "warrior with sword and shield",
                asset_type="character",
                era="late",
                console="nes",
                size=(TARGET_W, TARGET_H),
                output_dir=tmp,
            ))
            w, h = _dims(Path(result["paths"]["processed"]))

        assert result["dimensions"]["width_px"] == w
        assert result["dimensions"]["height_px"] == h
        assert result["target_dimensions"] == {"width_px": TARGET_W, "height_px": TARGET_H}

    def test_strict_size_secondary_is_the_requested_size(self, monkeypatch):
        """strict_size=true must yield exactly the requested size."""
        _patch_get_image(monkeypatch)
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline(
                "warrior with sword and shield",
                asset_type="character",
                era="late",
                console="nes",
                size=(TARGET_W, TARGET_H),
                output_dir=tmp,
            ))
            assert "strict_nes" in result["paths"], (
                "No strict-size secondary output was produced. When natural != "
                "target the pipeline must still offer the exact-size render for "
                "strict_size=true requests."
            )
            strict_dims = _dims(Path(result["paths"]["strict_nes"]))

        assert strict_dims == (TARGET_W, TARGET_H), (
            f"strict_nes.png is {strict_dims}, expected exactly "
            f"{(TARGET_W, TARGET_H)}"
        )

    def test_api_select_output_honours_the_documented_contract(self, monkeypatch):
        """
        End-to-end on the API's own selector.

        ``strict_size=false`` -> natural (higher-resolution) file.
        ``strict_size=true``  -> exact requested size, with matching metadata.

        This is the documented contract on ``GenerateRequest.strict_size``.
        """
        _patch_get_image(monkeypatch)
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline(
                "warrior with sword and shield",
                asset_type="character",
                era="late",
                console="nes",
                size=(TARGET_W, TARGET_H),
                output_dir=tmp,
            ))

            loose_path, loose_meta = _select_output(result, strict=False)
            strict_path, strict_meta = _select_output(result, strict=True)

            loose_dims = _dims(loose_path)
            strict_dims = _dims(strict_path)

        assert max(loose_dims) > TARGET_W, (
            f"strict_size=false returned {loose_dims} — the documented promise is "
            f"'the natural higher-resolution output for best quality'."
        )
        assert strict_dims == (TARGET_W, TARGET_H)
        assert loose_path != strict_path, (
            "strict_size=false and strict_size=true returned the same file — "
            "every customer is getting strict-size output whether they asked "
            "for it or not (the d680c14 side effect)."
        )
        # The metadata must describe the file actually served.
        assert strict_meta["dimensions"]["width_px"] == TARGET_W
        assert strict_meta["dimensions"]["height_px"] == TARGET_H
        assert loose_meta["dimensions"]["width_px"] == loose_dims[0]
        assert loose_meta["dimensions"]["height_px"] == loose_dims[1]

    @pytest.mark.parametrize("era", ["early", "mid", "late"])
    def test_natural_resolution_holds_across_eras(self, monkeypatch, era):
        """The resolution contract is not era-specific."""
        _patch_get_image(monkeypatch)
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline(
                "warrior with sword and shield",
                asset_type="character",
                era=era,
                console="nes",
                size=(TARGET_W, TARGET_H),
                output_dir=tmp,
            ))
            long_side = _long_side(Path(result["paths"]["processed"]))
        assert long_side > TARGET_W, f"era={era} collapsed to {long_side}px"


@pytest.mark.skip(
    reason="Prompt restorations HELD by operator ruling 2026-07-27: the golden prompt "
    "text may carry old quirks (e.g. shield-guarantee) — ships only via the rg-066 "
    "controlled A/B experiment. These tests are the spec for that landing; unskip then. "
    "Restoration diff preserved in bdb7888."
)
class TestEraColourBudget:
    """
    rg-061 R2 — the era colour instruction must not contradict itself.

    Golden appended the era hint LAST so late-era's "4-6 colors" won recency
    over the template's "3-4 flat colors"; a later refactor flipped that. The
    fix makes the template's colour clause era-aware, so both halves of the
    prompt now agree. This guards the agreement, not the clause order.
    """

    def test_late_era_prompt_does_not_contradict_its_own_colour_budget(self):
        from retrogaze.prompts import build_prompt
        prompt = build_prompt(
            "warrior with sword and shield", asset_type="character",
            era="late", console="nes",
        )["prompt"]
        assert "4-6 flat colors total" in prompt
        assert "3-4 flat colors total" not in prompt, (
            "Late-era prompt still carries the '3-4 flat colors' clause while "
            "its era label asks for 4-6 — the rg-061 R2 contradiction."
        )

    def test_mid_era_colour_budget_unchanged(self):
        from retrogaze.prompts import build_prompt
        prompt = build_prompt(
            "warrior with sword and shield", asset_type="character",
            era="mid", console="nes",
        )["prompt"]
        assert "3-4 flat colors total" in prompt

    def test_late_style_reference_keeps_the_golden_anchors(self):
        """rg-061 R4 — Mega Man / Final Fantasy are the late-NES style anchors."""
        from retrogaze.prompts import build_prompt
        prompt = build_prompt(
            "warrior with sword and shield", asset_type="character",
            era="late", console="nes",
        )["prompt"]
        assert "Mega Man" in prompt
        assert "Final Fantasy" in prompt

    def test_character_template_tells_flux_to_fill_the_frame(self):
        """rg-061 R3 — the frame-fill instruction is load-bearing for coverage."""
        from retrogaze.prompts import build_prompt
        prompt = build_prompt(
            "warrior with sword and shield", asset_type="character",
            era="late", console="nes",
        )["prompt"]
        assert "fills most of the canvas" in prompt

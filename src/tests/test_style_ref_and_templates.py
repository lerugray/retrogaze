"""
Tests for style reference lock ("More Like This") and prompt templates.

Features tested:
1. Style reference lock — using a generated image as reference for next generation
   (validates the reference_image + reference_strength API path)
2. Prompt templates — API validation for all form fields that templates save/restore

Prompt template save/load/delete is entirely frontend (localStorage), so we test
that the API accepts all the parameter combinations a template might produce.
"""
import sys
import os
import base64
import io
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"
os.environ["RETROGAZE_API_RATE_LIMIT"] = "500/minute"

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from retrogaze.api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def generate(extra_params=None):
    """Run a minimal generation request with optional extra params."""
    payload = {"description": "a knight", "size": "16x16"}
    if extra_params:
        payload.update(extra_params)
    resp = client.post("/generate", json=payload)
    return resp


def decode_image(b64_str):
    """Decode a base64 PNG string into a PIL Image."""
    return Image.open(io.BytesIO(base64.b64decode(b64_str)))


def make_test_reference_b64(width=16, height=16):
    """Create a small test PNG as base64 for use as reference image."""
    img = Image.new("RGBA", (width, height), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode("utf-8")


# ===========================================================================
# 1. Style Reference Lock — "More Like This"
# ===========================================================================

class TestStyleReferenceLock:
    """
    The "More Like This" button takes a generated image's base64 and feeds it
    back as reference_image with reference_strength=0.7. These tests validate
    the API accepts and processes this flow.
    """

    def test_generate_then_use_as_reference(self):
        """Full flow: generate once, use result as reference for a second generation."""
        first = generate({"seed": 42})
        assert first.status_code == 200
        first_b64 = first.json()["image_base64"]

        # Use the first image as a reference
        second = generate({
            "reference_image": first_b64,
            "reference_strength": 0.7,
            "description": "a knight variant",
        })
        assert second.status_code == 200
        second_data = second.json()
        assert second_data["image_base64"]
        assert len(second_data["image_base64"]) > 0

    def test_reference_image_accepted(self):
        """API accepts a base64 reference image."""
        ref_b64 = make_test_reference_b64()
        resp = generate({"reference_image": ref_b64})
        assert resp.status_code == 200

    def test_reference_strength_zero(self):
        """Strength 0.0 = close to reference (valid)."""
        ref_b64 = make_test_reference_b64()
        resp = generate({"reference_image": ref_b64, "reference_strength": 0.0})
        assert resp.status_code == 200

    def test_reference_strength_one(self):
        """Strength 1.0 = ignore reference (valid)."""
        ref_b64 = make_test_reference_b64()
        resp = generate({"reference_image": ref_b64, "reference_strength": 1.0})
        assert resp.status_code == 200

    def test_reference_strength_point_seven(self):
        """The default 'More Like This' strength of 0.7."""
        ref_b64 = make_test_reference_b64()
        resp = generate({"reference_image": ref_b64, "reference_strength": 0.7})
        assert resp.status_code == 200

    def test_reference_strength_too_high(self):
        """Strength > 1.0 should be rejected."""
        ref_b64 = make_test_reference_b64()
        resp = generate({"reference_image": ref_b64, "reference_strength": 1.5})
        assert resp.status_code == 422

    def test_reference_strength_negative(self):
        """Strength < 0.0 should be rejected."""
        ref_b64 = make_test_reference_b64()
        resp = generate({"reference_image": ref_b64, "reference_strength": -0.5})
        assert resp.status_code == 422

    def test_reference_with_all_options(self):
        """Reference image should work with all other generation options."""
        ref_b64 = make_test_reference_b64()
        resp = generate({
            "reference_image": ref_b64,
            "reference_strength": 0.7,
            "era": "late",
            "palette_mood": "dark",
            "outline": "Dark",
            "asset_type": "enemy",
            "view": "front",
        })
        assert resp.status_code == 200

    def test_reference_preserves_compliance(self):
        """A reference-based generation still returns compliance data."""
        ref_b64 = make_test_reference_b64()
        resp = generate({"reference_image": ref_b64, "reference_strength": 0.7})
        data = resp.json()
        compliance = data["metadata"]["compliance"]
        assert "palette_valid" in compliance
        assert "grid_aligned" in compliance
        assert "colors_per_tile_valid" in compliance
        # attribute_table_valid stripped from client response (IP protection)

    def test_reference_image_none_by_default(self):
        """Without reference_image, the normal generation path runs."""
        resp = generate()
        assert resp.status_code == 200

    def test_result_has_base64_for_reuse(self):
        """Every generation result has image_base64 available for 'More Like This'."""
        resp = generate()
        data = resp.json()
        assert "image_base64" in data
        assert len(data["image_base64"]) > 100  # non-trivial base64


# ===========================================================================
# 2. Prompt Templates — API Validation for Template Parameter Combos
# ===========================================================================

class TestPromptTemplateParams:
    """
    Prompt templates save/restore all form fields. These tests verify the API
    accepts every parameter combination a template might produce.
    """

    def test_all_asset_types(self):
        """Templates can save any asset type."""
        asset_types = ["character", "enemy", "npc", "item", "background_tile",
                       "ui_element", "ui_frame", "spritesheet", "directional"]
        for at in asset_types:
            extra = {"asset_type": at}
            if at == "spritesheet":
                extra["frame_count"] = 4
                extra["animation_type"] = "walk"
            resp = generate(extra)
            assert resp.status_code == 200, f"Failed for asset_type={at}"

    def test_all_sizes(self):
        """Templates can save any size."""
        sizes = ["8x8", "16x16", "16x24", "16x32", "8x16"]
        for sz in sizes:
            resp = generate({"size": sz})
            assert resp.status_code == 200, f"Failed for size={sz}"

    def test_all_views(self):
        """Templates can save any view."""
        views = ["side", "front", "top_down", "three_quarter"]
        for v in views:
            resp = generate({"view": v})
            assert resp.status_code == 200, f"Failed for view={v}"

    def test_all_eras(self):
        """Templates can save any era."""
        eras = ["retro", "early", "mid", "late"]
        for era in eras:
            resp = generate({"era": era})
            assert resp.status_code == 200, f"Failed for era={era}"

    def test_all_palette_moods(self):
        """Templates can save any palette mood."""
        moods = ["auto", "warm", "cool", "dark", "bright", "earth"]
        for m in moods:
            resp = generate({"palette_mood": m})
            assert resp.status_code == 200, f"Failed for palette_mood={m}"

    def test_all_outlines(self):
        """Templates can save any outline style."""
        outlines = ["Black", "Dark", "No"]
        for o in outlines:
            resp = generate({"outline": o})
            assert resp.status_code == 200, f"Failed for outline={o}"

    def test_all_scale_factors(self):
        """Templates can save any scale factor."""
        scales = [1, 2, 3, 4, 8]
        for s in scales:
            resp = generate({"scale_factor": s})
            assert resp.status_code == 200, f"Failed for scale_factor={s}"

    def test_all_export_palette_formats(self):
        """Templates can save palette export format."""
        formats = ["gpl", "hex", "pal"]
        for fmt in formats:
            resp = generate({"export_palette": fmt})
            assert resp.status_code == 200, f"Failed for export_palette={fmt}"

    def test_template_with_palette_colors(self):
        """Templates can save locked palette colors."""
        resp = generate({"palette_colors": ["#000000", "#F83800", "#FFFFFF"]})
        assert resp.status_code == 200

    def test_template_with_background_color(self):
        """Templates can save background color setting."""
        resp = generate({"background_color": "#1A1A2E"})
        assert resp.status_code == 200

    def test_template_with_flip(self):
        """Templates can save flip setting."""
        resp = generate({"flip_horizontal": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["flipped_base64"] is not None

    def test_full_template_combo(self):
        """A template with ALL fields set should be accepted."""
        resp = generate({
            "description": "fire mage casting spell",
            "asset_type": "character",
            "size": "16x32",
            "view": "front",
            "palette_mood": "warm",
            "outline": "Dark",
            "era": "late",
            "scale_factor": 2,
            "export_palette": "gpl",
            "background_color": "#000000",
            "flip_horizontal": True,
            "palette_colors": ["#F83800", "#FFFFFF", "#000000"],
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["image_base64"]
        assert data["flipped_base64"]
        assert data["palette_file_base64"]

    def test_minimal_template(self):
        """A template with only description should work (all defaults)."""
        resp = client.post("/generate", json={"description": "a tree"})
        assert resp.status_code == 200

    def test_template_spritesheet_with_animation(self):
        """Template for spritesheet saves animation settings."""
        resp = generate({
            "asset_type": "spritesheet",
            "animation_type": "attack",
            "frame_count": 6,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["frames_base64"]) > 0


# ===========================================================================
# 3. Style Ref + Template Combos
# ===========================================================================

class TestStyleRefWithTemplateParams:
    """
    Test that reference images work correctly with all the parameters
    a template might restore.
    """

    def test_reference_with_different_era(self):
        """Style ref should work when template changes the era."""
        ref_b64 = make_test_reference_b64()
        for era in ["retro", "early", "mid", "late"]:
            resp = generate({
                "reference_image": ref_b64,
                "reference_strength": 0.7,
                "era": era,
            })
            assert resp.status_code == 200, f"Failed for era={era} with reference"

    def test_reference_with_background_and_flip(self):
        """Style ref + background + flip all at once."""
        ref_b64 = make_test_reference_b64()
        resp = generate({
            "reference_image": ref_b64,
            "reference_strength": 0.7,
            "background_color": "#1A1A2E",
            "flip_horizontal": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["flipped_base64"] is not None

    def test_reference_with_scale(self):
        """Style ref + scaled export."""
        ref_b64 = make_test_reference_b64()
        resp = generate({
            "reference_image": ref_b64,
            "reference_strength": 0.7,
            "scale_factor": 4,
        })
        assert resp.status_code == 200
        img = decode_image(resp.json()["image_base64"])
        assert img.width == 16 * 4
        assert img.height == 16 * 4

    def test_reference_with_palette_lock(self):
        """Style ref + locked palette colors."""
        ref_b64 = make_test_reference_b64()
        resp = generate({
            "reference_image": ref_b64,
            "reference_strength": 0.7,
            "palette_colors": ["#000000", "#F83800"],
        })
        assert resp.status_code == 200

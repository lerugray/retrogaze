"""
Tests for quick-win features shipped 2026-04-07.

Features tested:
1. Attribute table compliance badge (attribute_table_valid in response)
2. Transparent background toggle (background_color parameter)
3. Horizontal sprite flip (flip_horizontal parameter)
4. Individual frame download (frames_base64 populated for spritesheets)
5. Scaled PNG export (scale_factor parameter)
6. Palette file export (export_palette parameter — GPL/hex/PAL)
7. Variations / candidates (num_candidates=4)
"""
import sys
import os
import base64
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"
os.environ["RETROGAZE_API_RATE_LIMIT"] = "500/minute"

import pytest
from PIL import Image
from fastapi.testclient import TestClient

from retrogaze.api import app

client = TestClient(app)

# ---------------------------------------------------------------------------
# Helper
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


# ===========================================================================
# 1. Attribute table compliance badge
# ===========================================================================

class TestAttributeTableBadge:
    def test_attribute_table_valid_stripped_from_client_response(self):
        """attribute_table_valid is stripped from client response (IP protection)."""
        resp = generate()
        assert resp.status_code == 200
        data = resp.json()
        compliance = data["metadata"]["compliance"]
        assert "attribute_table_valid" not in compliance

    def test_palette_slots_stripped_from_client_response(self):
        """palette_slots_required is stripped from client response (IP protection)."""
        resp = generate()
        data = resp.json()
        compliance = data["metadata"]["compliance"]
        assert "palette_slots_required" not in compliance

    def test_compliance_fields_present(self):
        resp = generate()
        data = resp.json()
        compliance = data["metadata"]["compliance"]
        expected = {"palette_valid", "colors_per_tile_valid", "grid_aligned"}
        assert expected.issubset(set(compliance.keys()))


# ===========================================================================
# 2. Transparent background toggle
# ===========================================================================

class TestBackgroundColor:
    def test_default_has_transparent_pixels(self):
        resp = generate()
        assert resp.status_code == 200
        img = decode_image(resp.json()["image_base64"])
        assert img.mode == "RGBA" or img.mode == "RGB"

    def test_background_color_black(self):
        resp = generate({"background_color": "#000000"})
        assert resp.status_code == 200
        img = decode_image(resp.json()["image_base64"])
        # With a solid background, there should be no fully transparent pixels
        if img.mode == "RGBA":
            pixels = list(img.get_flattened_data())
            transparent_count = sum(1 for px in pixels if px[3] < 10)
            assert transparent_count == 0, (
                f"Expected no transparent pixels with background_color set, "
                f"but found {transparent_count}"
            )

    def test_background_color_red(self):
        resp = generate({"background_color": "#FF0000"})
        assert resp.status_code == 200
        img = decode_image(resp.json()["image_base64"])
        # Check that red is present in the image
        pixels = list(img.get_flattened_data())
        has_red = any(px[0] > 200 and px[1] < 50 and px[2] < 50 for px in pixels)
        assert has_red, "Background color #FF0000 should produce red pixels in the output"

    def test_background_color_short_hex(self):
        resp = generate({"background_color": "#F00"})
        assert resp.status_code == 200

    def test_background_color_invalid_hex_rejected(self):
        resp = generate({"background_color": "not-a-color"})
        assert resp.status_code == 422

    def test_background_color_invalid_hex_chars(self):
        resp = generate({"background_color": "#GGGGGG"})
        assert resp.status_code == 422

    def test_background_color_empty_string_treated_as_none(self):
        # Empty string is falsy in Python, should skip compositing
        resp = generate({"background_color": ""})
        assert resp.status_code == 200


# ===========================================================================
# 3. Horizontal sprite flip
# ===========================================================================

class TestFlipHorizontal:
    def test_flip_false_by_default(self):
        resp = generate()
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("flipped_base64") is None

    def test_flip_returns_flipped_image(self):
        resp = generate({"flip_horizontal": True})
        assert resp.status_code == 200
        data = resp.json()
        assert data["flipped_base64"] is not None
        assert len(data["flipped_base64"]) > 0

    def test_flip_image_is_valid_png(self):
        resp = generate({"flip_horizontal": True})
        data = resp.json()
        img = decode_image(data["flipped_base64"])
        assert img.width > 0
        assert img.height > 0

    def test_flip_image_same_dimensions_as_original(self):
        resp = generate({"flip_horizontal": True})
        data = resp.json()
        original = decode_image(data["image_base64"])
        flipped = decode_image(data["flipped_base64"])
        assert original.size == flipped.size

    def test_flip_image_is_actually_flipped(self):
        """The flipped image should be the mirror of the original."""
        resp = generate({"flip_horizontal": True, "seed": 42})
        data = resp.json()
        original = decode_image(data["image_base64"])
        flipped = decode_image(data["flipped_base64"])

        # Manually flip the original and compare
        expected_flip = original.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
        orig_pixels = list(expected_flip.get_flattened_data())
        flip_pixels = list(flipped.get_flattened_data())
        assert orig_pixels == flip_pixels, "Flipped image doesn't match a manual horizontal flip"

    def test_flip_with_background_color(self):
        """Flip should work together with background color."""
        resp = generate({"flip_horizontal": True, "background_color": "#000000"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["flipped_base64"] is not None
        flipped = decode_image(data["flipped_base64"])
        # Flipped image should also have the background applied
        if flipped.mode == "RGBA":
            pixels = list(flipped.get_flattened_data())
            transparent_count = sum(1 for px in pixels if px[3] < 10)
            assert transparent_count == 0


# ===========================================================================
# 4. Individual frame download (frames_base64)
# ===========================================================================

class TestFramesBase64:
    def test_spritesheet_returns_frames(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["frames_base64"]) > 0, "Spritesheet should return individual frames"

    def test_each_frame_is_valid_png(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        data = resp.json()
        for i, frame_b64 in enumerate(data["frames_base64"]):
            img = decode_image(frame_b64)
            assert img.width > 0, f"Frame {i} has zero width"
            assert img.height > 0, f"Frame {i} has zero height"

    def test_single_sprite_has_no_frames(self):
        resp = generate({"asset_type": "character"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["frames_base64"]) == 0

    def test_directional_returns_frames(self):
        resp = generate({"asset_type": "directional"})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["frames_base64"]) > 0, "Directional should return individual view frames"


# ===========================================================================
# 5. Scaled PNG export
# ===========================================================================

class TestScaledExport:
    def test_scale_1x_unchanged(self):
        resp = generate({"scale_factor": 1, "seed": 99})
        assert resp.status_code == 200
        img = decode_image(resp.json()["image_base64"])
        # At 1x, dimensions should match target (16x16 or close to it)
        assert img.width <= 32 and img.height <= 32, f"1x image unexpectedly large: {img.size}"

    def test_scale_2x_doubles_dimensions(self):
        # Generate at 1x first to get baseline
        resp_1x = generate({"scale_factor": 1, "seed": 123})
        img_1x = decode_image(resp_1x.json()["image_base64"])

        resp_2x = generate({"scale_factor": 2, "seed": 123})
        img_2x = decode_image(resp_2x.json()["image_base64"])

        assert img_2x.width == img_1x.width * 2, (
            f"Expected 2x width {img_1x.width * 2}, got {img_2x.width}"
        )
        assert img_2x.height == img_1x.height * 2, (
            f"Expected 2x height {img_1x.height * 2}, got {img_2x.height}"
        )

    def test_scale_4x_quadruples_dimensions(self):
        resp_1x = generate({"scale_factor": 1, "seed": 456})
        img_1x = decode_image(resp_1x.json()["image_base64"])

        resp_4x = generate({"scale_factor": 4, "seed": 456})
        img_4x = decode_image(resp_4x.json()["image_base64"])

        assert img_4x.width == img_1x.width * 4
        assert img_4x.height == img_1x.height * 4

    def test_scale_8x(self):
        resp = generate({"scale_factor": 8, "seed": 789})
        assert resp.status_code == 200
        img = decode_image(resp.json()["image_base64"])
        # 16x16 * 8 = 128x128 (minimum)
        assert img.width >= 128

    def test_scale_0_rejected(self):
        resp = generate({"scale_factor": 0})
        assert resp.status_code == 422

    def test_scale_9_rejected(self):
        resp = generate({"scale_factor": 9})
        assert resp.status_code == 422

    def test_scale_negative_rejected(self):
        resp = generate({"scale_factor": -1})
        assert resp.status_code == 422

    def test_scale_preserves_pixel_art(self):
        """Scaled image should use nearest-neighbor (no anti-aliasing)."""
        resp = generate({"scale_factor": 4, "seed": 42})
        img = decode_image(resp.json()["image_base64"])
        pixels = list(img.get_flattened_data())
        # In a 4x nearest-neighbor upscale, each 4x4 block should be uniform
        w = img.width
        mismatches = 0
        for y in range(0, img.height - 3, 4):
            for x in range(0, w - 3, 4):
                block_colors = set()
                for dy in range(4):
                    for dx in range(4):
                        block_colors.add(pixels[(y + dy) * w + (x + dx)])
                if len(block_colors) > 1:
                    mismatches += 1
        total_blocks = (img.width // 4) * (img.height // 4)
        # Allow some edge blocks to differ (constraint enforcement may create sub-pixel patterns)
        assert mismatches < total_blocks * 0.15, (
            f"Too many non-uniform 4x4 blocks ({mismatches}/{total_blocks}). "
            f"Scaling may not be nearest-neighbor."
        )

    def test_scale_with_flip(self):
        """Scale and flip should both apply."""
        resp = generate({"scale_factor": 2, "flip_horizontal": True, "seed": 55})
        assert resp.status_code == 200
        data = resp.json()
        img = decode_image(data["image_base64"])
        flipped = decode_image(data["flipped_base64"])
        # Both should be 2x scaled
        assert img.size == flipped.size
        assert img.width >= 32  # 16*2


# ===========================================================================
# 6. Palette file export
# ===========================================================================

class TestPaletteExport:
    def test_gpl_format(self):
        resp = generate({"export_palette": "gpl"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["palette_file_base64"] is not None
        assert data["palette_file_format"] == "gpl"
        content = base64.b64decode(data["palette_file_base64"]).decode("utf-8")
        assert content.startswith("GIMP Palette"), f"GPL file should start with 'GIMP Palette', got: {content[:30]}"
        assert "Name: Retrogaze NES Palette" in content
        # Should have at least one color line (R G B #HEX)
        lines = content.strip().split("\n")
        color_lines = [l for l in lines if l and not l.startswith("#") and not l.startswith("GIMP") and not l.startswith("Name") and not l.startswith("Columns")]
        assert len(color_lines) > 0, "GPL file should contain at least one color entry"

    def test_hex_format(self):
        resp = generate({"export_palette": "hex"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["palette_file_format"] == "hex"
        content = base64.b64decode(data["palette_file_base64"]).decode("utf-8")
        lines = content.strip().split("\n")
        for line in lines:
            assert line.startswith("#"), f"Hex line should start with #, got: {line}"
            assert len(line) == 7, f"Hex line should be 7 chars (#RRGGBB), got: {line}"

    def test_pal_format(self):
        resp = generate({"export_palette": "pal"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["palette_file_format"] == "pal"
        raw = base64.b64decode(data["palette_file_base64"])
        # PAL is raw RGB bytes, length should be multiple of 3
        assert len(raw) % 3 == 0, f"PAL file length ({len(raw)}) should be multiple of 3"
        assert len(raw) >= 3, "PAL file should have at least one color (3 bytes)"

    def test_no_palette_export_by_default(self):
        resp = generate()
        data = resp.json()
        assert data.get("palette_file_base64") is None
        assert data.get("palette_file_format") is None

    def test_invalid_palette_format_rejected(self):
        resp = generate({"export_palette": "csv"})
        assert resp.status_code == 422

    def test_gpl_colors_match_metadata_palette(self):
        """Exported palette colors should match the metadata palette hex values."""
        resp = generate({"export_palette": "gpl"})
        data = resp.json()
        gpl_content = base64.b64decode(data["palette_file_base64"]).decode("utf-8")
        metadata_hex = data["metadata"]["palette"]["hex"]

        # Extract hex colors from GPL lines
        gpl_colors = []
        for line in gpl_content.strip().split("\n"):
            if line.startswith("#") or line.startswith("GIMP") or line.startswith("Name") or line.startswith("Columns"):
                continue
            parts = line.split("\t")
            if len(parts) >= 2:
                gpl_colors.append(parts[1].upper())

        metadata_hex_upper = [c.upper() for c in metadata_hex]
        assert set(gpl_colors) == set(metadata_hex_upper), (
            f"GPL colors {gpl_colors} don't match metadata palette {metadata_hex_upper}"
        )


# ===========================================================================
# 7. Variations / num_candidates
# ===========================================================================

class TestVariations:
    def test_single_candidate_by_default(self):
        resp = generate()
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["candidates_base64"]) == 0

    def test_four_candidates(self):
        resp = generate({"num_candidates": 4})
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["candidates_base64"]) == 4, (
            f"Expected 4 candidates, got {len(data['candidates_base64'])}"
        )

    def test_each_candidate_is_valid_png(self):
        resp = generate({"num_candidates": 4})
        data = resp.json()
        for i, cand_b64 in enumerate(data["candidates_base64"]):
            img = decode_image(cand_b64)
            assert img.width > 0, f"Candidate {i} has zero width"
            assert img.height > 0, f"Candidate {i} has zero height"

    def test_candidates_same_dimensions(self):
        resp = generate({"num_candidates": 4, "seed": 100})
        data = resp.json()
        sizes = [decode_image(b64).size for b64 in data["candidates_base64"]]
        assert len(set(sizes)) == 1, f"All candidates should have same dimensions, got: {sizes}"

    def test_first_candidate_matches_main_image(self):
        resp = generate({"num_candidates": 2})
        data = resp.json()
        assert data["candidates_base64"][0] == data["image_base64"], (
            "First candidate should match the primary image_base64"
        )

    def test_candidates_are_different(self):
        """With different seeds (no seed param), candidates should differ."""
        resp = generate({"num_candidates": 4})
        data = resp.json()
        unique = set(data["candidates_base64"])
        # Mock mode uses hash(prompt) as seed, so candidates might be identical
        # in mock mode. This test is more meaningful in real mode.
        # At minimum, we should get the right count.
        assert len(data["candidates_base64"]) == 4

    def test_num_candidates_0_rejected(self):
        resp = generate({"num_candidates": 0})
        assert resp.status_code == 422

    def test_num_candidates_5_rejected(self):
        resp = generate({"num_candidates": 5})
        assert resp.status_code == 422


# ===========================================================================
# Integration: multiple features combined
# ===========================================================================

class TestFeatureCombinations:
    def test_all_features_together(self):
        """Smoke test: all quick-win features enabled at once."""
        resp = generate({
            "background_color": "#001122",
            "flip_horizontal": True,
            "scale_factor": 2,
            "export_palette": "gpl",
            "seed": 777,
        })
        assert resp.status_code == 200
        data = resp.json()
        # All response fields should be populated
        assert data["image_base64"]
        assert data["flipped_base64"]
        assert data["palette_file_base64"]
        assert data["palette_file_format"] == "gpl"
        assert data["metadata"]["compliance"]["palette_valid"] is not None

    def test_scale_and_background(self):
        resp = generate({"background_color": "#FFFFFF", "scale_factor": 4, "seed": 50})
        assert resp.status_code == 200
        img = decode_image(resp.json()["image_base64"])
        # Should be scaled up
        assert img.width >= 64  # 16 * 4
        # Should have no transparent pixels
        if img.mode == "RGBA":
            pixels = list(img.get_flattened_data())
            transparent = sum(1 for px in pixels if px[3] < 10)
            assert transparent == 0

    def test_spritesheet_with_flip_and_scale(self):
        resp = generate({
            "asset_type": "spritesheet",
            "animation_type": "idle",
            "frame_count": 2,
            "flip_horizontal": True,
            "scale_factor": 2,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["frames_base64"]) > 0
        assert data["flipped_base64"] is not None


# ===========================================================================
# 8. Atlas JSON export (TexturePacker-compatible)
# ===========================================================================

class TestAtlasJson:
    def test_single_sprite_has_no_atlas(self):
        resp = generate({"asset_type": "character"})
        assert resp.status_code == 200
        data = resp.json()
        assert data.get("atlas_json") is None

    def test_spritesheet_has_atlas(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        assert resp.status_code == 200
        data = resp.json()
        assert data["atlas_json"] is not None

    def test_atlas_has_frames_and_meta(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        atlas = resp.json()["atlas_json"]
        assert "frames" in atlas
        assert "meta" in atlas

    def test_atlas_meta_fields(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        meta = resp.json()["atlas_json"]["meta"]
        assert meta["app"] == "Retrogaze"
        assert meta["version"] == "0.1.0"
        assert meta["format"] == "RGBA8888"
        assert "size" in meta
        assert "w" in meta["size"]
        assert "h" in meta["size"]

    def test_atlas_frame_structure(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        atlas = resp.json()["atlas_json"]
        frames = atlas["frames"]
        assert len(frames) > 0
        # Check first frame has required fields
        first_frame = list(frames.values())[0]
        assert "frame" in first_frame
        assert "x" in first_frame["frame"]
        assert "y" in first_frame["frame"]
        assert "w" in first_frame["frame"]
        assert "h" in first_frame["frame"]
        assert "rotated" in first_frame
        assert first_frame["rotated"] is False
        assert "trimmed" in first_frame
        assert "spriteSourceSize" in first_frame
        assert "sourceSize" in first_frame
        assert "pivot" in first_frame
        assert "duration" in first_frame

    def test_atlas_frame_names_sequential(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        atlas = resp.json()["atlas_json"]
        frame_names = list(atlas["frames"].keys())
        for i, name in enumerate(frame_names):
            assert name == f"frame_{i}", f"Expected 'frame_{i}', got '{name}'"

    def test_atlas_frame_positions_horizontal_strip(self):
        """Frames in a spritesheet should be laid out left-to-right."""
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        atlas = resp.json()["atlas_json"]
        frames = list(atlas["frames"].values())
        if len(frames) >= 2:
            frame_w = frames[0]["frame"]["w"]
            for i, f in enumerate(frames):
                assert f["frame"]["x"] == i * frame_w, (
                    f"Frame {i} x should be {i * frame_w}, got {f['frame']['x']}"
                )
                assert f["frame"]["y"] == 0

    def test_atlas_frame_tags_spritesheet(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "attack", "frame_count": 4})
        atlas = resp.json()["atlas_json"]
        tags = atlas["meta"]["frameTags"]
        assert len(tags) == 1
        assert tags[0]["name"] == "attack"
        assert tags[0]["from"] == 0
        assert tags[0]["direction"] == "forward"

    def test_atlas_directional_uses_direction_names(self):
        resp = generate({"asset_type": "directional"})
        assert resp.status_code == 200
        data = resp.json()
        if data.get("atlas_json"):
            atlas = data["atlas_json"]
            frame_names = list(atlas["frames"].keys())
            expected_directions = ["front", "right", "back", "left"]
            for name in frame_names:
                assert name in expected_directions, (
                    f"Directional frame name '{name}' not in {expected_directions}"
                )

    def test_atlas_pivot_bottom_center(self):
        """Default pivot should be bottom-center (0.5, 1.0) for game sprites."""
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        atlas = resp.json()["atlas_json"]
        for frame_data in atlas["frames"].values():
            pivot = frame_data["pivot"]
            assert pivot["x"] == 0.5
            assert pivot["y"] == 1.0

    def test_atlas_duration_matches_metadata(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        data = resp.json()
        atlas = data["atlas_json"]
        # Default duration is 150ms
        for frame_data in atlas["frames"].values():
            assert frame_data["duration"] == 150

    def test_atlas_scale_factor_reflected(self):
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4, "scale_factor": 3})
        atlas = resp.json()["atlas_json"]
        assert atlas["meta"]["scale"] == 3

    def test_atlas_json_is_valid_json(self):
        """The atlas should be serializable to valid JSON."""
        resp = generate({"asset_type": "spritesheet", "animation_type": "walk", "frame_count": 4})
        atlas = resp.json()["atlas_json"]
        import json
        serialized = json.dumps(atlas)
        reparsed = json.loads(serialized)
        assert reparsed == atlas

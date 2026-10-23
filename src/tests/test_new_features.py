"""
Tests for new features: palette extraction, tile edge fix, game engine export.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
from PIL import Image

os.environ["RETROGAZE_MOCK"] = "1"


# ---------------------------------------------------------------------------
# Palette extraction
# ---------------------------------------------------------------------------

class TestPaletteExtraction:
    def test_extract_dominant_colors_basic(self):
        from retrogaze.palette_extract import extract_dominant_colors
        # Create an image with 3 distinct color blocks
        img = Image.new("RGB", (30, 10))
        for x in range(10):
            for y in range(10):
                img.putpixel((x, y), (255, 0, 0))       # red block
                img.putpixel((x + 10, y), (0, 255, 0))   # green block
                img.putpixel((x + 20, y), (0, 0, 255))   # blue block
        colors = extract_dominant_colors(img, n=3)
        assert len(colors) == 3
        # Should find something close to red, green, blue
        reds = [c for c in colors if c[0] > 200 and c[1] < 50 and c[2] < 50]
        greens = [c for c in colors if c[1] > 200 and c[0] < 50 and c[2] < 50]
        blues = [c for c in colors if c[2] > 200 and c[0] < 50 and c[1] < 50]
        assert len(reds) >= 1
        assert len(greens) >= 1
        assert len(blues) >= 1

    def test_extract_dominant_colors_count(self):
        from retrogaze.palette_extract import extract_dominant_colors
        # Image with 2 distinct colors
        img = Image.new("RGB", (20, 10))
        for x in range(10):
            for y in range(10):
                img.putpixel((x, y), (255, 0, 0))
                img.putpixel((x + 10, y), (0, 0, 255))
        colors = extract_dominant_colors(img, n=2)
        assert len(colors) == 2

    def test_snap_to_nes_palette(self):
        from retrogaze.palette_extract import snap_to_console_palette
        # Pure red should snap to the nearest NES red
        result = snap_to_console_palette([(255, 0, 0)], console="nes")
        assert len(result) == 1
        assert result[0].startswith("#")
        assert len(result[0]) == 7

    def test_snap_to_gb_dmg_palette(self):
        from retrogaze.palette_extract import snap_to_console_palette
        # GB DMG only has 4 colors
        colors = [(0, 0, 0), (80, 80, 80), (160, 160, 160), (255, 255, 255)]
        result = snap_to_console_palette(colors, console="gb_dmg")
        assert len(result) <= 4

    def test_snap_deduplicates(self):
        from retrogaze.palette_extract import snap_to_console_palette
        # Two very similar colors should snap to the same NES color
        result = snap_to_console_palette([(255, 0, 0), (250, 5, 5)], console="nes")
        # May or may not deduplicate depending on NES palette, but should not crash
        assert len(result) >= 1

    def test_full_pipeline(self):
        from retrogaze.palette_extract import extract_palette_from_screenshot
        img = Image.new("RGB", (20, 20), (100, 50, 200))
        result = extract_palette_from_screenshot(img, n=3, console="nes")
        assert isinstance(result, list)
        assert all(c.startswith("#") for c in result)

    def test_snap_to_free_color_console(self):
        from retrogaze.palette_extract import snap_to_console_palette
        # Genesis is free-color — should quantize to bit depth
        result = snap_to_console_palette([(128, 64, 200)], console="genesis")
        assert len(result) == 1
        assert result[0].startswith("#")


# ---------------------------------------------------------------------------
# Tile edge brightness fix
# ---------------------------------------------------------------------------

class TestTileEdgeBrightness:
    def test_dark_edges_are_corrected(self):
        from retrogaze.cleanup import normalize_tile_edge_brightness
        # Create a tile with artificially dark edges
        arr = np.full((16, 16, 4), 200, dtype=np.uint8)  # bright interior
        arr[:, :, 3] = 255  # fully opaque
        # Darken edges
        arr[:2, :, :3] = 100
        arr[-2:, :, :3] = 100
        arr[:, :2, :3] = 100
        arr[:, -2:, :3] = 100
        img = Image.fromarray(arr, mode="RGBA")

        result = normalize_tile_edge_brightness(img)
        result_arr = np.array(result)

        # Border should be brighter after correction
        border_avg_before = 100
        border_avg_after = np.mean(result_arr[:2, 2:-2, :3])
        assert border_avg_after > border_avg_before

    def test_uniform_tile_unchanged(self):
        from retrogaze.cleanup import normalize_tile_edge_brightness
        # A tile with uniform brightness should not be modified
        arr = np.full((16, 16, 4), 150, dtype=np.uint8)
        arr[:, :, 3] = 255
        img = Image.fromarray(arr, mode="RGBA")

        result = normalize_tile_edge_brightness(img)
        result_arr = np.array(result)
        np.testing.assert_array_equal(np.array(img), result_arr)

    def test_small_tile_unchanged(self):
        from retrogaze.cleanup import normalize_tile_edge_brightness
        # Very small tile should be returned unchanged
        arr = np.full((4, 4, 4), 150, dtype=np.uint8)
        arr[:, :, 3] = 255
        img = Image.fromarray(arr, mode="RGBA")
        result = normalize_tile_edge_brightness(img)
        assert result.size == img.size

    def test_transparent_pixels_preserved(self):
        from retrogaze.cleanup import normalize_tile_edge_brightness
        arr = np.full((16, 16, 4), 200, dtype=np.uint8)
        arr[:, :, 3] = 255
        arr[:2, :, :3] = 100  # dark edges
        arr[-2:, :, :3] = 100
        arr[:, :2, :3] = 100
        arr[:, -2:, :3] = 100
        # Make some pixels transparent
        arr[0, 0, 3] = 0
        arr[8, 8, 3] = 0
        img = Image.fromarray(arr, mode="RGBA")

        result = normalize_tile_edge_brightness(img)
        result_arr = np.array(result)
        assert result_arr[0, 0, 3] == 0  # still transparent
        assert result_arr[8, 8, 3] == 0


# ---------------------------------------------------------------------------
# Game engine export formats
# ---------------------------------------------------------------------------

class TestExportFormats:
    @pytest.fixture
    def sample_atlas(self):
        return {
            "frames": {
                "frame_0": {
                    "frame": {"x": 0, "y": 0, "w": 16, "h": 16},
                    "rotated": False,
                    "trimmed": False,
                    "spriteSourceSize": {"x": 0, "y": 0, "w": 16, "h": 16},
                    "sourceSize": {"w": 16, "h": 16},
                    "pivot": {"x": 0.5, "y": 1.0},
                    "duration": 150,
                },
                "frame_1": {
                    "frame": {"x": 16, "y": 0, "w": 16, "h": 16},
                    "rotated": False,
                    "trimmed": False,
                    "spriteSourceSize": {"x": 0, "y": 0, "w": 16, "h": 16},
                    "sourceSize": {"w": 16, "h": 16},
                    "pivot": {"x": 0.5, "y": 1.0},
                    "duration": 150,
                },
            },
            "meta": {
                "app": "Retrogaze",
                "version": "0.1.0",
                "format": "RGBA8888",
                "size": {"w": 32, "h": 16},
                "scale": 1,
                "frameTags": [
                    {"name": "walk", "from": 0, "to": 1, "direction": "forward"},
                ],
            },
        }

    def test_godot_tres_output(self, sample_atlas):
        from retrogaze.export_formats import build_godot_tres
        tres = build_godot_tres(sample_atlas)
        assert isinstance(tres, str)
        assert '[gd_resource type="SpriteFrames"' in tres
        assert "walk" in tres
        assert "Rect2(0, 0, 16, 16)" in tres
        assert "Rect2(16, 0, 16, 16)" in tres

    def test_godot_tres_custom_filename(self, sample_atlas):
        from retrogaze.export_formats import build_godot_tres
        tres = build_godot_tres(sample_atlas, texture_filename="knight_walk.png")
        assert "knight_walk.png" in tres

    def test_unity_anim_output(self, sample_atlas):
        from retrogaze.export_formats import build_unity_anim
        result = build_unity_anim(sample_atlas)
        assert isinstance(result, dict)
        assert "sprites" in result
        assert "animationClips" in result
        assert len(result["sprites"]) == 2
        assert len(result["animationClips"]) == 1
        assert result["animationClips"][0]["name"] == "walk"

    def test_unity_sprite_rects(self, sample_atlas):
        from retrogaze.export_formats import build_unity_anim
        result = build_unity_anim(sample_atlas)
        sprite = result["sprites"][0]
        assert sprite["rect"]["width"] == 16
        assert sprite["rect"]["height"] == 16
        assert sprite["pivot"]["x"] == 0.5

    def test_apply_pivot_center(self, sample_atlas):
        from retrogaze.export_formats import apply_pivot
        import copy
        atlas = copy.deepcopy(sample_atlas)
        apply_pivot(atlas, "center")
        for frame_data in atlas["frames"].values():
            assert frame_data["pivot"]["x"] == 0.5
            assert frame_data["pivot"]["y"] == 0.5

    def test_apply_pivot_top_left(self, sample_atlas):
        from retrogaze.export_formats import apply_pivot
        import copy
        atlas = copy.deepcopy(sample_atlas)
        apply_pivot(atlas, "top_left")
        for frame_data in atlas["frames"].values():
            assert frame_data["pivot"]["x"] == 0.0
            assert frame_data["pivot"]["y"] == 0.0

    def test_gamemaker_yy_output(self, sample_atlas):
        from retrogaze.export_formats import build_gamemaker_yy
        result = build_gamemaker_yy(sample_atlas)
        assert isinstance(result, dict)
        assert result["resourceType"] == "GMSprite"
        assert result["width"] == 16
        assert result["height"] == 16
        assert len(result["frames"]) == 2
        assert result["frames"][0]["x"] == 0
        assert result["frames"][1]["x"] == 16

    def test_gamemaker_yy_sequences(self, sample_atlas):
        from retrogaze.export_formats import build_gamemaker_yy
        result = build_gamemaker_yy(sample_atlas)
        assert len(result["sequences"]) == 1
        assert result["sequences"][0]["name"] == "walk"
        assert len(result["sequences"][0]["frames"]) == 2

    def test_gamemaker_yy_custom_name(self, sample_atlas):
        from retrogaze.export_formats import build_gamemaker_yy
        result = build_gamemaker_yy(sample_atlas, sprite_name="spr_knight")
        assert result["name"] == "spr_knight"

    def test_gamemaker_yy_origin(self, sample_atlas):
        from retrogaze.export_formats import build_gamemaker_yy
        result = build_gamemaker_yy(sample_atlas)
        assert result["origin"]["x"] == 8   # 16 // 2
        assert result["origin"]["y"] == 16   # bottom-center

    def test_unreal_sprite_output(self, sample_atlas):
        from retrogaze.export_formats import build_unreal_sprite
        result = build_unreal_sprite(sample_atlas)
        assert isinstance(result, dict)
        assert "sprites" in result
        assert "flipbooks" in result
        assert len(result["sprites"]) == 2
        assert result["sprites"][0]["sourceDimension"]["x"] == 16

    def test_unreal_flipbook(self, sample_atlas):
        from retrogaze.export_formats import build_unreal_sprite
        result = build_unreal_sprite(sample_atlas)
        assert len(result["flipbooks"]) == 1
        assert "walk" in result["flipbooks"][0]["name"]
        assert len(result["flipbooks"][0]["keyFrames"]) == 2

    def test_unreal_custom_asset_name(self, sample_atlas):
        from retrogaze.export_formats import build_unreal_sprite
        result = build_unreal_sprite(sample_atlas, asset_name="S_Knight")
        assert result["assetName"] == "S_Knight"
        assert result["sprites"][0]["name"].startswith("S_Knight_")

    def test_unreal_pivot_preserved(self, sample_atlas):
        from retrogaze.export_formats import build_unreal_sprite
        result = build_unreal_sprite(sample_atlas)
        assert result["sprites"][0]["pivot"]["x"] == 0.5
        assert result["sprites"][0]["pivot"]["y"] == 1.0

    def test_no_frame_tags_uses_default(self):
        from retrogaze.export_formats import build_godot_tres
        atlas = {
            "frames": {
                "frame_0": {
                    "frame": {"x": 0, "y": 0, "w": 16, "h": 16},
                    "pivot": {"x": 0.5, "y": 1.0},
                    "duration": 200,
                },
            },
            "meta": {"size": {"w": 16, "h": 16}, "frameTags": []},
        }
        tres = build_godot_tres(atlas)
        assert "default" in tres


# ---------------------------------------------------------------------------
# API endpoint: /extract-palette
# ---------------------------------------------------------------------------

class TestExtractPaletteEndpoint:
    def test_extract_palette_returns_colors(self):
        import base64
        from io import BytesIO
        from fastapi.testclient import TestClient
        from retrogaze.api import app

        client = TestClient(app)
        # Create a simple red image
        img = Image.new("RGB", (10, 10), (255, 0, 0))
        buf = BytesIO()
        img.save(buf, format="PNG")
        img_b64 = base64.b64encode(buf.getvalue()).decode()

        resp = client.post("/extract-palette", json={
            "image": img_b64,
            "n": 3,
            "console": "nes",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "palette_colors" in data
        assert len(data["palette_colors"]) >= 1
        assert all(c.startswith("#") for c in data["palette_colors"])

    def test_extract_palette_invalid_image(self):
        from fastapi.testclient import TestClient
        from retrogaze.api import app

        client = TestClient(app)
        resp = client.post("/extract-palette", json={
            "image": "not-valid-base64!!!",
            "n": 3,
            "console": "nes",
        })
        assert resp.status_code == 422

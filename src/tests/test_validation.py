"""Tests for tile seamlessness and animation frame validation."""

import numpy as np
import pytest
from PIL import Image

from retrogaze.validation import (
    validate_tile_seamlessness,
    validate_tile_grid,
    validate_animation_frames,
)


# --- Tile seamlessness tests ---


def _make_solid_tile(w=8, h=8, color=(255, 0, 0, 255)):
    """Solid color tile — perfectly seamless."""
    img = Image.new("RGBA", (w, h), color)
    return img


def _make_gradient_tile(w=8, h=8):
    """Horizontal gradient — seamless vertically, NOT horizontally."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for x in range(w):
        val = int(255 * x / (w - 1))
        arr[:, x] = [val, 0, 0, 255]
    return Image.fromarray(arr, "RGBA")


def _make_checkerboard_tile(w=8, h=8):
    """Checkerboard — seamless when both dimensions are even."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        for x in range(w):
            if (x + y) % 2 == 0:
                arr[y, x] = [255, 255, 255, 255]
            else:
                arr[y, x] = [0, 0, 0, 255]
    return Image.fromarray(arr, "RGBA")


class TestTileSeamlessness:
    def test_solid_tile_is_seamless(self):
        tile = _make_solid_tile()
        result = validate_tile_seamlessness(tile)
        assert result["is_seamless"] is True
        assert result["seamless_h"] == 100.0
        assert result["seamless_v"] == 100.0
        assert result["seamless_overall"] == 100.0
        assert result["mismatches_h"] == []
        assert result["mismatches_v"] == []

    def test_gradient_not_seamless_h(self):
        tile = _make_gradient_tile()
        result = validate_tile_seamlessness(tile)
        assert result["is_seamless"] is False
        assert result["seamless_h"] < 100.0
        assert len(result["mismatches_h"]) > 0

    def test_checkerboard_not_identical_edges(self):
        """8x8 checkerboard has complementary edges (left inverts right).
        Pattern continues when tiled, but edges are NOT identical pixels."""
        tile = _make_checkerboard_tile()
        result = validate_tile_seamlessness(tile)
        # Left col: W,B,W,B... Right col: B,W,B,W... — they're inverted
        assert result["is_seamless"] is False
        assert result["seamless_h"] == 0.0
        assert result["seamless_v"] == 0.0

    def test_16x16_tile(self):
        tile = _make_solid_tile(16, 16, (0, 128, 255, 255))
        result = validate_tile_seamlessness(tile)
        assert result["size"] == (16, 16)
        assert result["is_seamless"] is True

    def test_asymmetric_edges(self):
        """Left column red, right column blue — not seamless horizontally."""
        arr = np.full((8, 8, 4), [128, 128, 128, 255], dtype=np.uint8)
        arr[:, 0] = [255, 0, 0, 255]
        arr[:, -1] = [0, 0, 255, 255]
        tile = Image.fromarray(arr, "RGBA")
        result = validate_tile_seamlessness(tile)
        assert result["seamless_h"] == 0.0
        assert len(result["mismatches_h"]) == 8

    def test_mismatch_details_include_colors(self):
        arr = np.full((4, 4, 4), [100, 100, 100, 255], dtype=np.uint8)
        arr[:, 0] = [255, 0, 0, 255]
        arr[:, -1] = [0, 255, 0, 255]
        tile = Image.fromarray(arr, "RGBA")
        result = validate_tile_seamlessness(tile)
        assert len(result["mismatches_h"]) == 4
        y, left_c, right_c = result["mismatches_h"][0]
        assert y == 0
        assert "ff0000" in left_c
        assert "00ff00" in right_c


class TestTileGrid:
    def test_grid_3x3_dimensions(self):
        tile = _make_solid_tile(8, 8)
        grid = validate_tile_grid(tile, grid_size=3)
        assert grid.size == (24, 24)

    def test_grid_2x2_dimensions(self):
        tile = _make_solid_tile(16, 16)
        grid = validate_tile_grid(tile, grid_size=2)
        assert grid.size == (32, 32)

    def test_grid_preserves_content(self):
        tile = _make_checkerboard_tile(4, 4)
        grid = validate_tile_grid(tile, grid_size=3)
        arr = np.array(grid)
        # Top-left 4x4 should match the tile
        tile_arr = np.array(tile.convert("RGBA"))
        np.testing.assert_array_equal(arr[:4, :4], tile_arr)
        # Adjacent tile should also match
        np.testing.assert_array_equal(arr[:4, 4:8], tile_arr)


# --- Animation frame validation tests ---


def _make_frame(w=16, h=16, color=(255, 0, 0, 255), offset_x=0, offset_y=0):
    """Frame with a colored rectangle, optionally offset."""
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    arr = np.array(img)
    y0, y1 = 4 + offset_y, 12 + offset_y
    x0, x1 = 4 + offset_x, 12 + offset_x
    y0, y1 = max(0, y0), min(h, y1)
    x0, x1 = max(0, x0), min(w, x1)
    arr[y0:y1, x0:x1] = color
    return Image.fromarray(arr, "RGBA")


class TestAnimationFrameValidation:
    def test_minimum_frames_required(self):
        result = validate_animation_frames([_make_frame()])
        assert "error" in result

    def test_identical_frames_flagged(self):
        f = _make_frame()
        result = validate_animation_frames([f, f.copy()])
        assert result["pose_differentiation"][0]["is_identical"] is True
        assert any("identical" in i for i in result["issues"])
        assert result["is_valid"] is False

    def test_different_frames_pass(self):
        f1 = _make_frame(color=(255, 0, 0, 255))
        f2 = _make_frame(color=(0, 0, 255, 255))
        result = validate_animation_frames([f1, f2])
        assert result["pose_differentiation"][0]["is_identical"] is False
        assert result["pose_differentiation"][0]["different_pixels"] > 0

    def test_canvas_size_consistency(self):
        f1 = _make_frame(w=16, h=16)
        f2 = _make_frame(w=16, h=16)
        result = validate_animation_frames([f1, f2])
        assert result["canvas_consistent"] is True

    def test_canvas_size_mismatch(self):
        f1 = _make_frame(w=16, h=16)
        f2 = _make_frame(w=8, h=8)
        result = validate_animation_frames([f1, f2])
        assert result["canvas_consistent"] is False
        assert any("Canvas size" in i for i in result["issues"])

    def test_palette_consistency(self):
        f1 = _make_frame(color=(255, 0, 0, 255))
        f2 = _make_frame(color=(255, 0, 0, 255), offset_x=1)
        result = validate_animation_frames([f1, f2])
        assert result["palette_consistent"] is True
        assert result["palette_drift"] == []

    def test_palette_drift_detected(self):
        f1 = _make_frame(color=(255, 0, 0, 255))
        f2 = _make_frame(color=(0, 255, 0, 255))
        result = validate_animation_frames([f1, f2])
        assert result["palette_consistent"] is False
        assert len(result["palette_drift"]) > 0

    def test_bounding_box_stability(self):
        f1 = _make_frame(offset_x=0, offset_y=0)
        f2 = _make_frame(offset_x=1, offset_y=0)
        result = validate_animation_frames([f1, f2])
        assert result["bbox_stability"] <= 4.0

    def test_large_bbox_shift_flagged(self):
        f1 = _make_frame(offset_x=0, offset_y=0)
        # Shift character way off center
        img2 = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        arr2 = np.array(img2)
        arr2[0:4, 12:16] = [255, 0, 0, 255]
        f2 = Image.fromarray(arr2, "RGBA")
        result = validate_animation_frames([f1, f2])
        assert result["bbox_stability"] > 4.0
        assert any("centroid" in i.lower() for i in result["issues"])

    def test_four_frame_walk(self):
        """Simulate a walk cycle — same color, different positions."""
        frames = [
            _make_frame(offset_x=0),
            _make_frame(offset_x=1),
            _make_frame(offset_x=0),
            _make_frame(offset_x=-1),
        ]
        result = validate_animation_frames(frames)
        assert result["frame_count"] == 4
        assert result["canvas_consistent"] is True
        assert result["palette_consistent"] is True
        # Consecutive frames should differ
        for pd in result["pose_differentiation"]:
            assert pd["is_identical"] is False

    def test_diff_pct_reported(self):
        f1 = _make_frame(color=(255, 0, 0, 255))
        f2 = _make_frame(color=(0, 0, 255, 255))
        result = validate_animation_frames([f1, f2])
        assert "diff_pct" in result["pose_differentiation"][0]
        assert result["pose_differentiation"][0]["diff_pct"] > 0

    def test_empty_frame_handled(self):
        f1 = _make_frame()
        f2 = Image.new("RGBA", (16, 16), (0, 0, 0, 0))  # fully transparent
        result = validate_animation_frames([f1, f2])
        assert result["frame_count"] == 2
        # Should not crash, palette drift expected

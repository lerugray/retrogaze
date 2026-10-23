"""Tests for sprite sheet generation and slicing."""
import os
os.environ["RETROGAZE_MOCK"] = "1"

import numpy as np
from PIL import Image
import pytest

from retrogaze.cleanup import (
    slice_spritesheet, normalize_frame_sizes, composite_horizontal,
)
from retrogaze.tiles import validate_tile_colors
from retrogaze.prompts import build_prompt


class TestFrameTileGridAlignment:
    """
    normalize_frame_sizes / composite_horizontal must keep each frame's
    content aligned to the tile grid (multiples of 8). A non-grid paste
    offset re-introduces per-tile color violations on strict consoles
    (c64_hires at 2 colors/tile) by making clean tiles straddle two
    enforced tiles. Regression guard for that fix.
    """

    @staticmethod
    def _two_color_grid_frame(w: int, h: int) -> Image.Image:
        """A frame where every 8x8 tile holds exactly 2 colors, on-grid."""
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        px = img.load()
        for ty in range(0, h, 8):
            for tx in range(0, w, 8):
                # one solid color per tile + a second color in the corner
                base = (10 + (tx + ty) % 200, 30, 60, 255)
                for y in range(ty, min(ty + 8, h)):
                    for x in range(tx, min(tx + 8, w)):
                        px[x, y] = base
                px[tx, ty] = (255, 255, 255, 255)
        return img

    def _worst_colors_per_tile(self, img: Image.Image) -> int:
        report = validate_tile_colors(img, max_colors=2)
        return max((len(t.colors) for t in report.tiles), default=0)

    def test_normalize_offsets_are_multiples_of_8(self):
        # Frames of differing size force padding/centering.
        frames = [
            self._two_color_grid_frame(40, 56),  # uniform target
            self._two_color_grid_frame(40, 48),  # needs vertical pad (was 4px)
            self._two_color_grid_frame(32, 56),  # needs horizontal pad (was 4px)
        ]
        out = normalize_frame_sizes(frames)
        for f in out:
            assert f.width % 8 == 0 and f.height % 8 == 0
            # Each normalized frame must still hold <=2 colors per 8x8 tile.
            assert self._worst_colors_per_tile(f) <= 2, (
                "normalize_frame_sizes shifted content off the tile grid"
            )

    def test_composite_horizontal_keeps_tiles_aligned(self):
        frames = [
            self._two_color_grid_frame(40, 56),
            self._two_color_grid_frame(40, 48),
            self._two_color_grid_frame(32, 56),
        ]
        norm = normalize_frame_sizes(frames)
        sheet = composite_horizontal(norm)
        assert sheet.width % 8 == 0 and sheet.height % 8 == 0
        assert self._worst_colors_per_tile(sheet) <= 2, (
            "composite_horizontal straddled tiles across frames"
        )


class TestSliceSpritesheet:
    def _make_sheet(self, frame_count=4, frame_w=16, frame_h=16, gap=4):
        """Create a synthetic sprite sheet with N frames separated by transparent gaps."""
        total_w = frame_count * frame_w + (frame_count - 1) * gap
        img = Image.new("RGBA", (total_w, frame_h), (0, 0, 0, 0))
        px = img.load()
        colors = [(255, 0, 0, 255), (0, 255, 0, 255), (0, 0, 255, 255), (255, 255, 0, 255)]
        for i in range(frame_count):
            x_start = i * (frame_w + gap)
            color = colors[i % len(colors)]
            for x in range(x_start, x_start + frame_w):
                for y in range(frame_h):
                    px[x, y] = color
        return img

    def test_detects_correct_frame_count(self):
        sheet = self._make_sheet(frame_count=4)
        frames = slice_spritesheet(sheet, expected_frames=4)
        assert len(frames) == 4

    def test_frames_are_same_size(self):
        sheet = self._make_sheet(frame_count=3)
        frames = slice_spritesheet(sheet, expected_frames=3)
        sizes = set(f.size for f in frames)
        assert len(sizes) == 1, f"Frames have inconsistent sizes: {sizes}"

    def test_frame_dimensions_multiple_of_8(self):
        sheet = self._make_sheet(frame_count=4, frame_w=13, frame_h=11)
        frames = slice_spritesheet(sheet, expected_frames=4)
        for f in frames:
            assert f.width % 8 == 0
            assert f.height % 8 == 0

    def test_fallback_even_division(self):
        # No gaps, just solid blocks side by side
        img = Image.new("RGBA", (64, 16), (255, 0, 0, 255))
        frames = slice_spritesheet(img, expected_frames=4)
        assert len(frames) == 4

    def test_single_frame_returns_list(self):
        img = Image.new("RGBA", (16, 16), (0, 255, 0, 255))
        frames = slice_spritesheet(img, expected_frames=1)
        assert len(frames) == 1


class TestSpritesheetPrompt:
    def test_spritesheet_template_exists(self):
        result = build_prompt("knight walk", asset_type="spritesheet", frame_count=4, animation_type="walk")
        assert "frames" in result["prompt"].lower() or "frame" in result["prompt"].lower()

    def test_frame_count_in_prompt(self):
        result = build_prompt("warrior", asset_type="spritesheet", frame_count=3, animation_type="attack")
        assert "3" in result["prompt"]

    def test_animation_type_in_prompt(self):
        result = build_prompt("mage", asset_type="spritesheet", frame_count=4, animation_type="cast")
        assert "cast" in result["prompt"].lower() or "spell" in result["prompt"].lower()


class TestDirectionalPrompt:
    def test_directional_template_exists(self):
        result = build_prompt("knight", asset_type="directional")
        assert "front" in result["prompt"].lower() or "4 views" in result["prompt"].lower()

    def test_directional_mentions_all_directions(self):
        result = build_prompt("warrior", asset_type="directional")
        prompt = result["prompt"].lower()
        assert "front" in prompt
        assert "back" in prompt
        assert "left" in prompt or "right" in prompt

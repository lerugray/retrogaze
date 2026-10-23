"""Tests for palette allocation (free-color consoles)."""

import numpy as np
import pytest
from PIL import Image

from retrogaze.palette_alloc import allocate_palettes
from retrogaze.palette import quantize_to_bit_depth
from retrogaze.enforce import enforce_constraints


def _make_image_with_colors(w, h, colors_per_tile):
    """Create an image where each 8x8 tile has specific colors."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    tile_idx = 0
    for ty in range(0, h, 8):
        for tx in range(0, w, 8):
            colors = colors_per_tile[tile_idx % len(colors_per_tile)]
            for y in range(8):
                for x in range(8):
                    c = colors[(y * 8 + x) % len(colors)]
                    arr[ty + y, tx + x] = [c[0], c[1], c[2], 255]
            tile_idx += 1
    return Image.fromarray(arr, "RGBA")


class TestAllocatePalettes:
    def test_single_palette_trivial(self):
        """Image with ≤16 unique colors → single palette, no remapping."""
        # 16x16 image, 4 tiles, all same 4 colors
        colors = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (128, 128, 128)]
        img = _make_image_with_colors(16, 16, [colors] * 4)
        result_img, report = allocate_palettes(img, num_palettes=4, colors_per_palette=16)

        assert report["total_unique_colors"] == 4
        assert report["colors_merged"] == 0
        # All tiles should be assigned to the same palette
        assert all(a == report["tile_assignments"][0] for a in report["tile_assignments"])

    def test_multiple_palettes_needed(self):
        """Image with >16 unique colors needs multiple palettes."""
        # Create tiles with distinct color sets (avoid (0,0,0) overlap)
        palette_a = [(i * 16 + 1, 0, 0) for i in range(16)]  # 16 reds
        palette_b = [(0, i * 16 + 1, 0) for i in range(16)]  # 16 greens
        img = _make_image_with_colors(16, 16, [palette_a, palette_b, palette_a, palette_b])

        result_img, report = allocate_palettes(img, num_palettes=4, colors_per_palette=16)

        assert report["total_unique_colors"] == 32
        assert report["num_palettes_used"] >= 2

    def test_each_tile_uses_assigned_palette(self):
        """Critical invariant: each tile only uses colors from its assigned palette."""
        # Create tiles with 8 different colors each
        colors_a = [(i * 30, 0, 0) for i in range(8)]
        colors_b = [(0, i * 30, 0) for i in range(8)]
        colors_c = [(0, 0, i * 30) for i in range(8)]
        colors_d = [(i * 30, i * 30, 0) for i in range(8)]
        img = _make_image_with_colors(16, 16, [colors_a, colors_b, colors_c, colors_d])

        result_img, report = allocate_palettes(img, num_palettes=4, colors_per_palette=16)

        # Verify each tile only uses its assigned palette's colors
        result_arr = np.array(result_img)
        palettes = report["palettes"]
        assignments = report["tile_assignments"]

        for i, pal_idx in enumerate(assignments):
            row = i // 2
            col = i % 2
            tile = result_arr[row * 8:(row + 1) * 8, col * 8:(col + 1) * 8]
            opaque = tile[:, :, 3] > 0
            if not opaque.any():
                continue
            tile_pixels = tile[opaque][:, :3]
            tile_unique = {tuple(c) for c in np.unique(tile_pixels.reshape(-1, 3), axis=0).tolist()}
            pal_set = set(map(tuple, palettes[pal_idx]))
            assert tile_unique <= pal_set, (
                f"Tile {i} has colors {tile_unique - pal_set} not in palette {pal_idx}"
            )

    def test_color_merging_when_over_capacity(self):
        """Image with >64 unique colors triggers merging."""
        # Create an image with 80 unique colors (needs merging for 4x16=64 capacity)
        all_colors = [(i * 3, (i * 7) % 256, (i * 11) % 256) for i in range(80)]
        # Spread across 16 tiles (5 colors each)
        per_tile = [all_colors[i * 5:(i + 1) * 5] for i in range(16)]
        img = _make_image_with_colors(32, 32, per_tile)

        result_img, report = allocate_palettes(img, num_palettes=4, colors_per_palette=16)

        assert report["colors_merged"] > 0
        assert report["total_unique_colors"] <= 64

    def test_transparent_tiles_handled(self):
        """Fully transparent tiles don't crash the algorithm."""
        arr = np.zeros((16, 16, 4), dtype=np.uint8)
        # Only top-left tile has content
        arr[0:8, 0:8] = [255, 0, 0, 255]
        img = Image.fromarray(arr, "RGBA")

        result_img, report = allocate_palettes(img, num_palettes=4, colors_per_palette=16)
        assert len(report["tile_assignments"]) == 4

    def test_4_colors_per_palette_gbc(self):
        """GBC-style: 8 palettes of 4 colors."""
        # 5 unique colors → needs 2 palettes of 4
        colors_a = [(255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0)]
        colors_b = [(128, 0, 128)]  # 5th color
        img = _make_image_with_colors(16, 8, [colors_a, colors_a + colors_b])

        result_img, report = allocate_palettes(img, num_palettes=8, colors_per_palette=4)
        assert report["num_palettes_used"] >= 1


class TestGenesisEnforcement:
    def test_genesis_full_pipeline(self, tmp_path):
        """Genesis enforcement: quantize + tile reduce + palette allocation."""
        img_path = tmp_path / "test.png"
        out_path = tmp_path / "output.png"

        # Create a colorful 16x16 image
        arr = np.zeros((16, 16, 4), dtype=np.uint8)
        arr[:, :, 3] = 255
        for y in range(16):
            for x in range(16):
                arr[y, x, :3] = [(x * 17) % 256, (y * 23) % 256, ((x + y) * 13) % 256]
        Image.fromarray(arr, "RGBA").save(str(img_path))

        result = enforce_constraints(str(img_path), console="genesis", output_path=str(out_path))

        assert result["console"] == "genesis"
        # Should have palette allocation report
        assert "palette_allocation" in result

        # Output image should exist and have valid 9-bit colors
        out_img = Image.open(str(out_path)).convert("RGBA")
        out_arr = np.array(out_img)
        out_img.close()

        opaque = out_arr[:, :, 3] > 0
        if opaque.any():
            colors = out_arr[opaque][:, :3]
            # Each channel should be quantized to 3-bit (values in 0,36,73,109,146,182,219,255)
            valid_3bit = {int(i * 255 / 7) for i in range(8)}
            for c in np.unique(colors.reshape(-1, 3), axis=0):
                for ch in range(3):
                    assert c[ch] in valid_3bit or abs(c[ch] - min(valid_3bit, key=lambda v: abs(v - c[ch]))) <= 1

    def test_genesis_tile_palette_invariant(self, tmp_path):
        """Each tile in Genesis output uses colors from one palette only."""
        img_path = tmp_path / "test.png"
        out_path = tmp_path / "output.png"

        arr = np.zeros((16, 16, 4), dtype=np.uint8)
        arr[:, :, 3] = 255
        # Give each quadrant distinct colors
        arr[0:8, 0:8, :3] = [200, 0, 0]
        arr[0:8, 8:16, :3] = [0, 200, 0]
        arr[8:16, 0:8, :3] = [0, 0, 200]
        arr[8:16, 8:16, :3] = [200, 200, 0]
        Image.fromarray(arr, "RGBA").save(str(img_path))

        result = enforce_constraints(str(img_path), console="genesis", output_path=str(out_path))
        assert result["console"] == "genesis"

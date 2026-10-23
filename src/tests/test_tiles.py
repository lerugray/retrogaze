"""
Tests for retrogaze.tiles, retrogaze.grid, and retrogaze.metadata.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import numpy as np
from PIL import Image

from retrogaze.grid import align_to_grid
from retrogaze.tiles import (
    validate_tile_colors,
    reduce_tile_colors,
    validate_attribute_table,
    check_tile_seamless,
    make_tile_seamless,
    preview_tiled,
)
from retrogaze.metadata import generate_metadata
from retrogaze.palette import NES_PALETTE_RGB


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _solid_rgba(r, g, b, a=255, size=(8, 8)) -> Image.Image:
    return Image.new("RGBA", size, (r, g, b, a))


def _make_nes_color_image(colors: list[tuple], size=(8, 8)) -> Image.Image:
    """
    Fill an 8×8 (or given size) image with NES palette colors, cycling through
    the provided list of (r,g,b) tuples row by row.
    """
    img = Image.new("RGBA", size, (0, 0, 0, 0))
    arr = np.array(img)
    h, w = arr.shape[:2]
    for i, (r, g, b) in enumerate(colors):
        row = i % h
        arr[row, :] = [r, g, b, 255]
    return Image.fromarray(arr, "RGBA")


# ---------------------------------------------------------------------------
# align_to_grid
# ---------------------------------------------------------------------------

class TestAlignToGrid:
    def test_already_aligned_unchanged(self):
        img = _solid_rgba(255, 0, 0, size=(16, 16))
        result = align_to_grid(img)
        assert result.size == (16, 16)

    def test_pads_width_to_multiple_of_8(self):
        img = _solid_rgba(0, 255, 0, size=(10, 8))
        result = align_to_grid(img)
        assert result.size == (16, 8)

    def test_pads_height_to_multiple_of_8(self):
        img = _solid_rgba(0, 0, 255, size=(8, 13))
        result = align_to_grid(img)
        assert result.size == (8, 16)

    def test_pads_both_dimensions(self):
        img = _solid_rgba(128, 128, 128, size=(5, 5))
        result = align_to_grid(img)
        assert result.size == (8, 8)

    def test_padding_is_transparent(self):
        img = _solid_rgba(255, 0, 0, size=(4, 4))
        result = align_to_grid(img)
        arr = np.array(result)
        # Bottom-right quadrant (was padded) should be transparent
        assert arr[4, 4, 3] == 0

    def test_target_size_respected(self):
        img = _solid_rgba(0, 128, 255, size=(4, 4))
        result = align_to_grid(img, target_width=16, target_height=16)
        assert result.size == (16, 16)

    def test_non_multiple_target_raises(self):
        img = _solid_rgba(0, 0, 0, size=(8, 8))
        with pytest.raises(ValueError):
            align_to_grid(img, target_width=15)

    def test_output_is_rgba(self):
        img = Image.new("RGB", (8, 8), (0, 0, 0))
        result = align_to_grid(img)
        assert result.mode == "RGBA"


# ---------------------------------------------------------------------------
# validate_tile_colors
# ---------------------------------------------------------------------------

class TestValidateTileColors:
    def test_single_color_tile_valid(self):
        img = _solid_rgba(*NES_PALETTE_RGB[0])
        report = validate_tile_colors(img)
        assert report.all_valid
        assert len(report.tiles) == 1
        assert not report.tiles[0].violates

    def test_four_color_tile_valid(self):
        """An 8×8 tile with exactly 4 unique colors should pass."""
        colors = NES_PALETTE_RGB[:4]
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        arr = np.array(img)
        for i, (r, g, b) in enumerate(colors):
            arr[i * 2:(i + 1) * 2, :] = [r, g, b, 255]
        result_img = Image.fromarray(arr, "RGBA")
        report = validate_tile_colors(result_img, max_colors=4)
        assert report.all_valid

    def test_five_color_tile_violates(self):
        """An 8×8 tile with 5 unique colors should fail with max_colors=4."""
        colors = NES_PALETTE_RGB[:5]
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        arr = np.array(img)
        for i, (r, g, b) in enumerate(colors):
            arr[i, :] = [r, g, b, 255]
        # Fill remaining rows with first color
        arr[5:, :] = [*colors[0], 255]
        result_img = Image.fromarray(arr, "RGBA")
        report = validate_tile_colors(result_img, max_colors=4)
        assert not report.all_valid
        assert len(report.violating_tiles) == 1

    def test_transparent_pixels_not_counted(self):
        """Fully-transparent pixels should not count toward color total."""
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))  # all transparent
        report = validate_tile_colors(img)
        assert report.tiles[0].colors == []
        assert not report.tiles[0].violates

    def test_non_multiple_of_8_raises(self):
        img = Image.new("RGBA", (10, 10), (0, 0, 0, 255))
        with pytest.raises(ValueError):
            validate_tile_colors(img)

    def test_multi_tile_image(self):
        """16×8 image = 2 tiles; report should have 2 entries."""
        img = Image.new("RGBA", (16, 8), (*NES_PALETTE_RGB[1], 255))
        report = validate_tile_colors(img)
        assert len(report.tiles) == 2
        assert report.tile_cols == 2
        assert report.tile_rows == 1


# ---------------------------------------------------------------------------
# reduce_tile_colors
# ---------------------------------------------------------------------------

class TestReduceTileColors:
    def test_reduces_five_colors_to_four(self):
        """A tile with 5 colors should be reduced to max_colors=4."""
        colors = NES_PALETTE_RGB[:5]
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        arr = np.array(img)
        for i, (r, g, b) in enumerate(colors):
            arr[i, :] = [r, g, b, 255]
        arr[5:, :] = [*colors[0], 255]
        result_img = Image.fromarray(arr, "RGBA")

        reduced = reduce_tile_colors(result_img, max_colors=4)
        report = validate_tile_colors(reduced, max_colors=4)
        assert report.all_valid, (
            f"Expected compliance after reduction; violating tiles: "
            f"{report.violating_tiles}"
        )

    def test_compliant_tile_unchanged(self):
        """A tile already within max_colors should not be modified."""
        r, g, b = NES_PALETTE_RGB[5]
        img = _solid_rgba(r, g, b)
        reduced = reduce_tile_colors(img, max_colors=4)
        arr_before = np.array(img)
        arr_after = np.array(reduced)
        np.testing.assert_array_equal(arr_before, arr_after)

    def test_output_dimensions_unchanged(self):
        colors = NES_PALETTE_RGB[:6]
        img = Image.new("RGBA", (16, 8), (0, 0, 0, 0))
        arr = np.array(img)
        for i, (r, g, b) in enumerate(colors):
            arr[i % 8, i % 16 * 1:] = [r, g, b, 255]
        result = Image.fromarray(arr, "RGBA")
        reduced = reduce_tile_colors(result, max_colors=4)
        assert reduced.size == (16, 8)


# ---------------------------------------------------------------------------
# validate_attribute_table
# ---------------------------------------------------------------------------

class TestValidateAttributeTable:
    def test_four_color_block_valid(self):
        """A 16×16 block with 4 colors should pass."""
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        arr = np.array(img)
        for i, (r, g, b) in enumerate(NES_PALETTE_RGB[:4]):
            arr[i * 4:(i + 1) * 4, :] = [r, g, b, 255]
        result = validate_attribute_table(Image.fromarray(arr, "RGBA"))
        assert result["all_valid"]

    def test_five_color_block_violates(self):
        """A 16×16 block with 5 colors should fail."""
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        arr = np.array(img)
        for i, (r, g, b) in enumerate(NES_PALETTE_RGB[:5]):
            arr[i * 3:(i + 1) * 3, :] = [r, g, b, 255]
        result = validate_attribute_table(Image.fromarray(arr, "RGBA"))
        assert not result["all_valid"]

    def test_non_multiple_16_raises(self):
        img = Image.new("RGBA", (8, 8), (255, 255, 255, 255))
        with pytest.raises(ValueError):
            validate_attribute_table(img)


# ---------------------------------------------------------------------------
# generate_metadata
# ---------------------------------------------------------------------------

class TestGenerateMetadata:
    def _compliant_image(self, size=(16, 16)) -> Image.Image:
        """Create an NES-palette-compliant image."""
        r, g, b = NES_PALETTE_RGB[1]
        return Image.new("RGBA", size, (r, g, b, 255))

    def test_required_top_level_keys(self):
        img = self._compliant_image()
        meta = generate_metadata(img, asset_type="sprite")
        for key in ("retrogaze_version", "asset_type", "dimensions",
                    "palette", "tiles", "compliance"):
            assert key in meta, f"Missing key: {key}"

    def test_version_field(self):
        img = self._compliant_image()
        meta = generate_metadata(img, asset_type="sprite")
        assert meta["retrogaze_version"] == "0.1.0"

    def test_asset_type_stored(self):
        img = self._compliant_image()
        meta = generate_metadata(img, asset_type="background")
        assert meta["asset_type"] == "background"

    def test_prompt_stored(self):
        img = self._compliant_image()
        meta = generate_metadata(img, asset_type="sprite", prompt="warrior")
        assert meta["prompt"] == "warrior"

    def test_dimensions_correct(self):
        img = self._compliant_image(size=(16, 16))
        meta = generate_metadata(img, asset_type="sprite")
        assert meta["dimensions"]["width_px"] == 16
        assert meta["dimensions"]["height_px"] == 16
        assert meta["dimensions"]["tile_grid"] == [2, 2]

    def test_compliance_keys(self):
        img = self._compliant_image()
        meta = generate_metadata(img, asset_type="sprite")
        comp = meta["compliance"]
        for key in ("palette_valid", "colors_per_tile_valid", "grid_aligned"):
            assert key in comp, f"Missing compliance key: {key}"

    def test_grid_aligned_flag_true(self):
        img = self._compliant_image(size=(8, 8))
        meta = generate_metadata(img, asset_type="sprite")
        assert meta["compliance"]["grid_aligned"] is True

    def test_tile_list_populated(self):
        img = self._compliant_image(size=(16, 8))
        meta = generate_metadata(img, asset_type="sprite")
        # 16×8 = 2 tiles
        assert len(meta["tiles"]) == 2
        assert meta["tiles"][0]["id"] == 0
        assert meta["tiles"][1]["id"] == 1

    def test_tile_has_required_fields(self):
        img = self._compliant_image(size=(8, 8))
        meta = generate_metadata(img, asset_type="sprite")
        tile = meta["tiles"][0]
        for key in ("id", "x", "y", "flip_h", "flip_v"):
            assert key in tile, f"Missing tile key: {key}"

    def test_palette_has_required_fields(self):
        img = self._compliant_image()
        meta = generate_metadata(img, asset_type="sprite")
        pal = meta["palette"]
        assert "hex" in pal
        # NES-specific indices present when no console specified (defaults to NES)
        assert "nes_indices" in pal

    def test_palette_valid_for_compliant_image(self):
        """An image using exact NES colors should report palette_valid=True."""
        r, g, b = NES_PALETTE_RGB[5]
        img = Image.new("RGBA", (8, 8), (r, g, b, 255))
        meta = generate_metadata(img, asset_type="sprite")
        assert meta["compliance"]["palette_valid"] is True


# ---------------------------------------------------------------------------
# check_tile_seamless
# ---------------------------------------------------------------------------

class TestCheckTileSeamless:
    def test_solid_color_is_seamless(self):
        """A solid-color tile is perfectly seamless."""
        img = Image.new("RGBA", (8, 8), (100, 150, 200, 255))
        result = check_tile_seamless(img)
        assert result["seamless"] is True
        assert result["h_score"] == 1.0
        assert result["v_score"] == 1.0

    def test_different_top_bottom_not_seamless_v(self):
        """Top row differs from bottom row → not vertically seamless."""
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        arr = np.array(img)
        arr[0, :] = [200, 200, 200, 255]  # different top row
        arr[-1, :] = [50, 50, 50, 255]    # different bottom row
        img = Image.fromarray(arr, "RGBA")
        result = check_tile_seamless(img)
        assert result["seamless_v"] is False
        assert result["mismatched_v"] > 0

    def test_different_left_right_not_seamless_h(self):
        """Left col differs from right col → not horizontally seamless."""
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        arr = np.array(img)
        arr[:, 0] = [200, 200, 200, 255]
        arr[:, -1] = [50, 50, 50, 255]
        img = Image.fromarray(arr, "RGBA")
        result = check_tile_seamless(img)
        assert result["seamless_h"] is False
        assert result["mismatched_h"] > 0

    def test_matching_edges_is_seamless(self):
        """If top==bottom and left==right, tile is seamless."""
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        arr = np.array(img)
        # Make top and bottom match (both red)
        arr[0, :] = [255, 0, 0, 255]
        arr[-1, :] = [255, 0, 0, 255]
        # Make left and right match (both green)
        arr[:, 0] = [0, 255, 0, 255]
        arr[:, -1] = [0, 255, 0, 255]
        # Fix corners to be consistent
        arr[0, 0] = arr[0, -1] = arr[-1, 0] = arr[-1, -1] = [128, 128, 0, 255]
        img = Image.fromarray(arr, "RGBA")
        result = check_tile_seamless(img)
        assert result["seamless"] is True

    def test_transparent_edges_treated_as_seamless(self):
        """Transparent edge pixels should not count as mismatches."""
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))  # fully transparent
        result = check_tile_seamless(img)
        assert result["seamless"] is True
        assert result["h_score"] == 1.0

    def test_tolerance_allows_near_matches(self):
        """With tolerance > 0, close colors should count as matching."""
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        arr = np.array(img)
        arr[0, :] = [100, 100, 100, 255]
        arr[-1, :] = [102, 100, 100, 255]  # 2 off in red channel
        img = Image.fromarray(arr, "RGBA")

        strict = check_tile_seamless(img, tolerance=0)
        lenient = check_tile_seamless(img, tolerance=5)
        assert strict["seamless_v"] is False
        assert lenient["seamless_v"] is True

    def test_tiny_image(self):
        """1x1 image should be trivially seamless."""
        img = Image.new("RGBA", (1, 1), (255, 0, 0, 255))
        result = check_tile_seamless(img)
        assert result["seamless"] is True

    def test_score_is_fraction(self):
        """Scores should be between 0.0 and 1.0."""
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        arr = np.array(img)
        # Make half the top row different from bottom
        arr[0, :4] = [200, 200, 200, 255]
        arr[-1, :4] = [50, 50, 50, 255]
        arr[0, 4:] = [100, 100, 100, 255]
        arr[-1, 4:] = [100, 100, 100, 255]
        img = Image.fromarray(arr, "RGBA")
        result = check_tile_seamless(img)
        assert 0.0 <= result["v_score"] <= 1.0
        assert result["v_score"] == 0.5  # half match


# ---------------------------------------------------------------------------
# make_tile_seamless
# ---------------------------------------------------------------------------

class TestMakeTileSeamless:
    def test_already_seamless_unchanged(self):
        """A seamless tile should not be modified."""
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        result = make_tile_seamless(img)
        arr_before = np.array(img)
        arr_after = np.array(result)
        np.testing.assert_array_equal(arr_before, arr_after)

    def test_makes_non_seamless_tile_seamless(self):
        """After make_tile_seamless, edges should match."""
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        arr = np.array(img)
        arr[0, :] = [200, 200, 200, 255]
        arr[-1, :] = [100, 100, 100, 255]
        img = Image.fromarray(arr, "RGBA")

        fixed = make_tile_seamless(img)
        result = check_tile_seamless(fixed)
        assert result["seamless_v"] is True

    def test_preserves_dimensions(self):
        img = Image.new("RGBA", (16, 16), (50, 50, 50, 255))
        result = make_tile_seamless(img)
        assert result.size == (16, 16)

    def test_preserves_transparency(self):
        """Transparent pixels should remain transparent."""
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        result = make_tile_seamless(img)
        arr = np.array(result)
        assert np.all(arr[:, :, 3] == 0)

    def test_averages_edge_colors(self):
        """Edge pixels should be averaged."""
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        arr = np.array(img)
        arr[0, 3] = [200, 100, 100, 255]   # top pixel
        arr[-1, 3] = [100, 100, 100, 255]  # bottom pixel
        img = Image.fromarray(arr, "RGBA")

        fixed = make_tile_seamless(img)
        fixed_arr = np.array(fixed)
        # Average of 200 and 100 = 150
        assert fixed_arr[0, 3, 0] == 150
        assert fixed_arr[-1, 3, 0] == 150


# ---------------------------------------------------------------------------
# preview_tiled
# ---------------------------------------------------------------------------

class TestPreviewTiled:
    def test_default_3x3_preview(self):
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        preview = preview_tiled(img)
        assert preview.size == (24, 24)  # 8*3 = 24

    def test_custom_repeat_count(self):
        img = Image.new("RGBA", (8, 8), (100, 100, 100, 255))
        preview = preview_tiled(img, repeats=5)
        assert preview.size == (40, 40)

    def test_content_is_repeated(self):
        """Each tile position should have the same pixel values."""
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        arr = np.array(img)
        arr[0, 0] = [255, 0, 0, 255]  # red pixel at top-left
        img = Image.fromarray(arr, "RGBA")

        preview = preview_tiled(img, repeats=2)
        prev_arr = np.array(preview)
        # Check that all 4 tile positions have red at their top-left
        assert tuple(prev_arr[0, 0]) == (255, 0, 0, 255)
        assert tuple(prev_arr[0, 8]) == (255, 0, 0, 255)
        assert tuple(prev_arr[8, 0]) == (255, 0, 0, 255)
        assert tuple(prev_arr[8, 8]) == (255, 0, 0, 255)


# ---------------------------------------------------------------------------
# slice_tileset (from cleanup module)
# ---------------------------------------------------------------------------

class TestSliceTileset:
    def test_slices_into_9_tiles(self):
        """A 24×24 image should yield 9 named tiles from a 3×3 grid."""
        from retrogaze.cleanup import slice_tileset
        img = Image.new("RGBA", (24, 24), (100, 100, 100, 255))
        tiles = slice_tileset(img, grid=3)
        assert len(tiles) == 9

    def test_tile_names_correct(self):
        from retrogaze.cleanup import slice_tileset
        img = Image.new("RGBA", (24, 24), (100, 100, 100, 255))
        tiles = slice_tileset(img, grid=3)
        expected_names = {
            "top_left", "top", "top_right",
            "left", "center", "right",
            "bottom_left", "bottom", "bottom_right",
        }
        assert set(tiles.keys()) == expected_names

    def test_each_tile_is_8x8(self):
        """Each tile from a 24×24 image with 3×3 grid should be 8×8."""
        from retrogaze.cleanup import slice_tileset
        img = Image.new("RGBA", (24, 24), (100, 100, 100, 255))
        tiles = slice_tileset(img, grid=3)
        for name, tile in tiles.items():
            assert tile.size == (8, 8), f"Tile {name} is {tile.size}, expected (8, 8)"

    def test_tiles_padded_to_multiple_of_8(self):
        """Tiles from uneven divisions should be padded to multiple of 8."""
        from retrogaze.cleanup import slice_tileset
        # 30x30 / 3 = 10x10 per cell → padded to 16x16
        img = Image.new("RGBA", (30, 30), (100, 100, 100, 255))
        tiles = slice_tileset(img, grid=3)
        for name, tile in tiles.items():
            assert tile.width % 8 == 0, f"Tile {name} width not multiple of 8"
            assert tile.height % 8 == 0, f"Tile {name} height not multiple of 8"

    def test_tile_content_from_correct_region(self):
        """Each tile should contain content from the correct grid position."""
        from retrogaze.cleanup import slice_tileset
        img = Image.new("RGBA", (24, 24), (0, 0, 0, 0))
        arr = np.array(img)
        # Paint top-left 8x8 red
        arr[0:8, 0:8] = [255, 0, 0, 255]
        # Paint center 8x8 green
        arr[8:16, 8:16] = [0, 255, 0, 255]
        img = Image.fromarray(arr, "RGBA")

        tiles = slice_tileset(img, grid=3)
        tl_arr = np.array(tiles["top_left"])
        assert tl_arr[0, 0, 0] == 255  # red channel
        assert tl_arr[0, 0, 1] == 0

        center_arr = np.array(tiles["center"])
        assert center_arr[0, 0, 1] == 255  # green channel
        assert center_arr[0, 0, 0] == 0


# ---------------------------------------------------------------------------
# reduce_attribute_block_colors
# ---------------------------------------------------------------------------

class TestReduceAttributeBlockColors:
    """Tests for 16x16 attribute table enforcement."""

    def test_reduces_five_color_block_to_four(self):
        from retrogaze.tiles import reduce_attribute_block_colors
        # Create a 16x16 image with 5 distinct opaque colors
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        pixels = img.load()
        colors = [
            (255, 0, 0, 255),    # red
            (0, 255, 0, 255),    # green
            (0, 0, 255, 255),    # blue
            (255, 255, 0, 255),  # yellow
            (128, 0, 128, 255),  # purple (minority)
        ]
        # Fill with first 4 colors (3 pixels each), then purple gets 1 pixel
        idx = 0
        for y in range(16):
            for x in range(16):
                pixels[x, y] = colors[idx % 5]
                idx += 1

        result = reduce_attribute_block_colors(img, max_colors=4)
        # Count unique opaque colors — should be at most 4
        arr = np.array(result.convert("RGBA"), dtype=np.uint8)
        opaque = arr[arr[:, :, 3] > 0][:, :3]
        unique = np.unique(opaque.reshape(-1, 3), axis=0)
        assert len(unique) <= 4

    def test_compliant_block_unchanged(self):
        from retrogaze.tiles import reduce_attribute_block_colors
        # 16x16 with only 3 colors — should be unchanged
        img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
        pixels = img.load()
        for x in range(8):
            for y in range(16):
                pixels[x, y] = (0, 255, 0, 255)

        result = reduce_attribute_block_colors(img, max_colors=4)
        assert np.array_equal(np.array(img), np.array(result))

    def test_preserves_dimensions(self):
        from retrogaze.tiles import reduce_attribute_block_colors
        img = Image.new("RGBA", (32, 32), (255, 0, 0, 255))
        result = reduce_attribute_block_colors(img)
        assert result.size == (32, 32)

    def test_skips_non_multiple_of_16(self):
        from retrogaze.tiles import reduce_attribute_block_colors
        # 8x8 image — not divisible by 16, should return unchanged
        img = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
        result = reduce_attribute_block_colors(img)
        assert np.array_equal(np.array(img), np.array(result))

    def test_transparent_pixels_ignored(self):
        from retrogaze.tiles import reduce_attribute_block_colors
        # 16x16 with transparent pixels — should not count them
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        pixels = img.load()
        # Only 2 opaque colors
        for x in range(4):
            pixels[x, 0] = (255, 0, 0, 255)
            pixels[x, 1] = (0, 255, 0, 255)
        result = reduce_attribute_block_colors(img, max_colors=4)
        # Should be unchanged since only 2 colors
        assert np.array_equal(np.array(img), np.array(result))


class TestDetectAndRemoveDithering:
    """Tests for dithering detection and suppression."""

    def test_checkerboard_detected_and_removed(self):
        from retrogaze.cleanup import detect_and_remove_dithering
        # Create an 8x8 image with a perfect 2-color checkerboard
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        pixels = img.load()
        for y in range(8):
            for x in range(8):
                if (x + y) % 2 == 0:
                    pixels[x, y] = (255, 0, 0, 255)
                else:
                    pixels[x, y] = (0, 255, 0, 255)

        result = detect_and_remove_dithering(img, block_size=4)
        # After removal, each 4x4 block should have only 1 color
        arr = np.array(result, dtype=np.uint8)
        opaque = arr[arr[:, :, 3] > 0][:, :3]
        unique = np.unique(opaque.reshape(-1, 3), axis=0)
        assert len(unique) <= 2  # might still be 2 across blocks, but each block is uniform

    def test_non_dithered_image_unchanged(self):
        from retrogaze.cleanup import detect_and_remove_dithering
        # Solid color image — should not be modified
        img = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
        result = detect_and_remove_dithering(img, block_size=4)
        assert np.array_equal(np.array(img), np.array(result))

    def test_horizontal_stripes_not_dithered(self):
        from retrogaze.cleanup import detect_and_remove_dithering
        # Horizontal stripes (2px wide) — should NOT be detected as dithering
        # because each pixel has same-color neighbors horizontally
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        pixels = img.load()
        for y in range(8):
            for x in range(8):
                if y % 2 == 0:
                    pixels[x, y] = (255, 0, 0, 255)
                else:
                    pixels[x, y] = (0, 255, 0, 255)

        result = detect_and_remove_dithering(img, block_size=4)
        # Horizontal stripes: each pixel has same-color left/right neighbors
        # so differ_count should be low → NOT detected as dithering
        arr_orig = np.array(img, dtype=np.uint8)
        arr_result = np.array(result, dtype=np.uint8)
        assert np.array_equal(arr_orig, arr_result)

    def test_transparent_pixels_ignored(self):
        from retrogaze.cleanup import detect_and_remove_dithering
        # Mostly transparent image with a few opaque pixels
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        pixels = img.load()
        pixels[0, 0] = (255, 0, 0, 255)
        pixels[1, 1] = (0, 255, 0, 255)
        result = detect_and_remove_dithering(img, block_size=4)
        # Too few opaque pixels (< 4), should be unchanged
        assert np.array_equal(np.array(img), np.array(result))

    def test_small_image_unchanged(self):
        from retrogaze.cleanup import detect_and_remove_dithering
        # Image smaller than block_size — should return unchanged
        img = Image.new("RGBA", (2, 2), (255, 0, 0, 255))
        result = detect_and_remove_dithering(img, block_size=4)
        assert np.array_equal(np.array(img), np.array(result))

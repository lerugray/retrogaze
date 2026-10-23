"""
Tests for retrogaze.palette — NES palette definition and color remapping.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from PIL import Image

from retrogaze.palette import (
    NES_PALETTE_RGB,
    _NES_PALETTE_HEX,
    _NES_PPU_REGISTERS,
    find_nearest_nes_color,
    get_nes_palette_index,
    remap_to_nes_palette,
    rgb_to_lab,
)


# ---------------------------------------------------------------------------
# Palette definition sanity checks
# ---------------------------------------------------------------------------

class TestPaletteDefinition:
    def test_palette_length(self):
        """The NES 2C02G palette should have exactly 56 entries."""
        assert len(NES_PALETTE_RGB) == 56

    def test_hex_length_matches(self):
        assert len(_NES_PALETTE_HEX) == 56

    def test_register_length_matches(self):
        assert len(_NES_PPU_REGISTERS) == 56

    def test_all_rgb_in_range(self):
        for r, g, b in NES_PALETTE_RGB:
            assert 0 <= r <= 255
            assert 0 <= g <= 255
            assert 0 <= b <= 255

    def test_known_black_entries(self):
        """Indices 13 ($0D) and 27 ($1D) should both be black."""
        assert NES_PALETTE_RGB[13] == (0, 0, 0)
        assert NES_PALETTE_RGB[27] == (0, 0, 0)

    def test_known_white_entries(self):
        """Indices 28 ($20) and 42 ($30) should both be white."""
        assert NES_PALETTE_RGB[28] == (255, 255, 255)
        assert NES_PALETTE_RGB[42] == (255, 255, 255)

    def test_register_format(self):
        """Every register string should start with '$' and be 3 chars."""
        for reg in _NES_PPU_REGISTERS:
            assert reg.startswith("$"), f"Bad register: {reg}"
            assert len(reg) == 3, f"Bad register length: {reg}"


# ---------------------------------------------------------------------------
# Lab conversion
# ---------------------------------------------------------------------------

class TestLabConversion:
    def test_black_maps_to_origin(self):
        L, a, b = rgb_to_lab(0, 0, 0)
        assert abs(L) < 1.0
        assert abs(a) < 1.0
        assert abs(b) < 1.0

    def test_white_maps_to_high_L(self):
        L, a, b = rgb_to_lab(255, 255, 255)
        assert abs(L - 100.0) < 1.0

    def test_red_has_positive_a(self):
        """Red should have a high positive 'a' component in Lab."""
        _, a, _ = rgb_to_lab(255, 0, 0)
        assert a > 50


# ---------------------------------------------------------------------------
# find_nearest_nes_color
# ---------------------------------------------------------------------------

class TestFindNearestNesColor:
    def test_exact_nes_color_maps_to_itself(self):
        """A color that IS in the NES palette should map to itself."""
        # #626262 is the first entry (index 0)
        r, g, b = 0x62, 0x62, 0x62
        nr, ng, nb, idx = find_nearest_nes_color(r, g, b)
        assert (nr, ng, nb) == (r, g, b)
        assert idx == 0

    def test_pure_black_maps_to_nes_black(self):
        """Pure black (0,0,0) is in the NES palette at indices 13 and 27."""
        nr, ng, nb, idx = find_nearest_nes_color(0, 0, 0)
        assert (nr, ng, nb) == (0, 0, 0)

    def test_pure_white_maps_to_nes_white(self):
        """Pure white (255,255,255) is in the NES palette."""
        nr, ng, nb, idx = find_nearest_nes_color(255, 255, 255)
        assert (nr, ng, nb) == (255, 255, 255)

    def test_off_color_snaps_to_nearest(self):
        """A non-NES color should snap to a valid NES color."""
        nr, ng, nb, idx = find_nearest_nes_color(100, 100, 100)
        assert (nr, ng, nb) in NES_PALETTE_RGB

    def test_returns_four_values(self):
        result = find_nearest_nes_color(128, 64, 32)
        assert len(result) == 4
        assert isinstance(result[3], int)
        assert 0 <= result[3] < 56


# ---------------------------------------------------------------------------
# get_nes_palette_index
# ---------------------------------------------------------------------------

class TestGetNesPaletteIndex:
    def test_returns_dollar_string(self):
        reg = get_nes_palette_index(0, 0, 0)
        assert reg.startswith("$")

    def test_known_black_index(self):
        """Black should return $0D or $1D."""
        reg = get_nes_palette_index(0, 0, 0)
        assert reg in ("$0D", "$1D")

    def test_known_white_index(self):
        """White should return $20 or $30."""
        reg = get_nes_palette_index(255, 255, 255)
        assert reg in ("$20", "$30")


# ---------------------------------------------------------------------------
# remap_to_nes_palette
# ---------------------------------------------------------------------------

class TestRemapToNesPalette:
    def _solid_image(self, r, g, b, a=255, size=(8, 8)):
        img = Image.new("RGBA", size, (r, g, b, a))
        return img

    def test_output_is_rgba(self):
        img = self._solid_image(200, 100, 50)
        result = remap_to_nes_palette(img)
        assert result.mode == "RGBA"

    def test_output_size_preserved(self):
        img = self._solid_image(200, 100, 50, size=(16, 24))
        result = remap_to_nes_palette(img)
        assert result.size == (16, 24)

    def test_all_output_pixels_are_nes_colors(self):
        """Every opaque output pixel must be a valid NES palette color."""
        import numpy as np
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 255))
        # Paint a few non-NES colors
        pixels = img.load()
        pixels[0, 0] = (123, 45, 67, 255)
        pixels[4, 4] = (200, 180, 10, 255)

        result = remap_to_nes_palette(img)
        arr = np.array(result)
        opaque = arr[arr[:, :, 3] > 0][:, :3]
        nes_set = set(NES_PALETTE_RGB)
        for pixel in opaque:
            assert tuple(pixel) in nes_set, f"Non-NES pixel found: {tuple(pixel)}"

    def test_transparent_pixels_preserved(self):
        """Fully transparent pixels (alpha=0) should stay transparent."""
        import numpy as np
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        result = remap_to_nes_palette(img)
        arr = np.array(result)
        assert np.all(arr[:, :, 3] == 0)

    def test_exact_nes_color_unchanged(self):
        """A solid image of an exact NES color should be unchanged after remapping."""
        r, g, b = NES_PALETTE_RGB[0]  # #626262
        img = self._solid_image(r, g, b)
        result = remap_to_nes_palette(img)
        out_pixel = result.getpixel((0, 0))[:3]
        assert out_pixel == (r, g, b)


class TestPaletteRoleTemplates:
    """Tests for palette role template system."""

    def test_suggest_palette_roles_returns_dict_with_roles(self):
        from retrogaze.palette import suggest_palette_roles
        result = suggest_palette_roles(era="mid", outline="Black")
        assert "roles" in result
        assert "description" in result
        assert isinstance(result["roles"], list)
        assert isinstance(result["description"], str)

    def test_retro_era_uses_no_outline_template(self):
        from retrogaze.palette import suggest_palette_roles
        result = suggest_palette_roles(era="retro", outline="Black")
        assert "outline" not in result["roles"]
        assert "dark" in result["roles"] or "midtone" in result["roles"]

    def test_late_era_uses_4_color_template(self):
        from retrogaze.palette import suggest_palette_roles
        result = suggest_palette_roles(era="late", outline="Black")
        assert len(result["roles"]) == 4

    def test_mid_era_black_outline_uses_standard_4(self):
        from retrogaze.palette import suggest_palette_roles
        result = suggest_palette_roles(era="mid", outline="Black")
        assert "outline" in result["roles"]
        assert len(result["roles"]) == 4

    def test_no_outline_setting_uses_no_outline_template(self):
        from retrogaze.palette import suggest_palette_roles
        result = suggest_palette_roles(era="mid", outline="No")
        assert "outline" not in result["roles"]

    def test_palette_role_templates_dict_has_expected_keys(self):
        from retrogaze.palette import PALETTE_ROLE_TEMPLATES
        expected = {"standard_3", "standard_4", "no_outline_3", "no_outline_4"}
        assert set(PALETTE_ROLE_TEMPLATES.keys()) == expected


class TestPaletteSwapGeneration:
    """Tests for palette swap variant generation."""

    def test_generate_palette_swaps_returns_correct_count(self):
        from retrogaze.palette import generate_palette_swaps
        # Create a simple 8x8 sprite with 3 colors
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        pixels = img.load()
        for x in range(8):
            pixels[x, 0] = (0, 0, 0, 255)       # outline (darkest)
            pixels[x, 1] = (255, 0, 0, 255)      # primary
            pixels[x, 2] = (255, 255, 0, 255)     # secondary
        variants = generate_palette_swaps(img, num_variants=3, seed=42)
        assert len(variants) == 3

    def test_swapped_images_use_only_nes_colors(self):
        from retrogaze.palette import generate_palette_swaps, NES_PALETTE_RGB
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        pixels = img.load()
        for x in range(8):
            pixels[x, 0] = (0, 0, 0, 255)
            pixels[x, 1] = (255, 0, 0, 255)
            pixels[x, 2] = (255, 255, 0, 255)
        variants = generate_palette_swaps(img, num_variants=2, seed=42)
        nes_set = set(NES_PALETTE_RGB)
        for variant in variants:
            import numpy as np
            arr = np.array(variant, dtype=np.uint8)
            opaque = arr[arr[:, :, 3] > 0][:, :3]
            for pixel in np.unique(opaque.reshape(-1, 3), axis=0):
                # Outline color (0,0,0) or NES palette color
                assert tuple(pixel) in nes_set or tuple(pixel) == (0, 0, 0)

    def test_swap_preserves_outline_color(self):
        from retrogaze.palette import generate_palette_swaps
        # Outline (darkest) should remain unchanged
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        pixels = img.load()
        for x in range(8):
            pixels[x, 0] = (0, 0, 0, 255)        # outline
            pixels[x, 1] = (200, 100, 50, 255)    # fill
        variants = generate_palette_swaps(img, num_variants=2, seed=42)
        import numpy as np
        for variant in variants:
            arr = np.array(variant, dtype=np.uint8)
            # Check row 0 (outline) is still black
            for x in range(8):
                assert arr[0, x, 0] == 0 and arr[0, x, 1] == 0 and arr[0, x, 2] == 0

    def test_swap_palette_with_explicit_map(self):
        from retrogaze.palette import swap_palette
        img = Image.new("RGBA", (4, 4), (255, 0, 0, 255))
        result = swap_palette(img, {(255, 0, 0): (0, 0, 255)})
        import numpy as np
        arr = np.array(result, dtype=np.uint8)
        # All pixels should now be blue
        assert arr[0, 0, 0] == 0
        assert arr[0, 0, 1] == 0
        assert arr[0, 0, 2] == 255

    def test_mood_palette_warm_has_no_blues(self):
        from retrogaze.palette import get_mood_palette
        warm = get_mood_palette("warm")
        assert warm is not None
        # Warm palette should not contain deep blues
        assert "#002C88" not in warm
        assert "#0D56D0" not in warm
        assert "#4CA0FE" not in warm
        # But should contain reds/oranges
        assert "#5A0002" in warm or "#9A1032" in warm
        assert "#E09264" in warm

    def test_mood_palette_cool_has_no_reds(self):
        from retrogaze.palette import get_mood_palette
        cool = get_mood_palette("cool")
        assert cool is not None
        # Cool palette should not contain warm reds/oranges
        assert "#5A0002" not in cool
        assert "#9A1032" not in cool
        assert "#E09264" not in cool
        # But should contain blues/greens
        assert "#0D56D0" in cool or "#4CA0FE" in cool
        assert "#007A00" in cool or "#46E438" in cool

    def test_mood_palette_auto_returns_none(self):
        from retrogaze.palette import get_mood_palette
        assert get_mood_palette("auto") is None
        assert get_mood_palette("unknown") is None

    def test_mood_palette_all_colors_are_valid_nes(self):
        from retrogaze.palette import get_mood_palette, _NES_PALETTE_HEX
        nes_set = {h.upper() for h in _NES_PALETTE_HEX}
        for mood in ("warm", "cool", "dark", "bright", "earth"):
            colors = get_mood_palette(mood)
            assert colors is not None, f"Mood {mood} should return colors"
            for c in colors:
                assert c.upper() in nes_set, f"{c} in mood '{mood}' is not a valid NES color"

    def test_mood_palette_includes_neutrals(self):
        """Every mood should include black and white for outlines/bg."""
        from retrogaze.palette import get_mood_palette
        for mood in ("warm", "cool", "dark", "bright", "earth"):
            colors = get_mood_palette(mood)
            assert "#000000" in colors, f"Mood '{mood}' missing black"
            assert "#FFFFFF" in colors, f"Mood '{mood}' missing white"

    def test_variants_differ_from_original(self):
        from retrogaze.palette import generate_palette_swaps
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        pixels = img.load()
        for x in range(8):
            pixels[x, 0] = (0, 0, 0, 255)
            pixels[x, 1] = (255, 0, 0, 255)
            pixels[x, 2] = (0, 255, 0, 255)
        variants = generate_palette_swaps(img, num_variants=3, seed=42)
        import numpy as np
        orig_arr = np.array(img, dtype=np.uint8)
        any_different = False
        for variant in variants:
            if not np.array_equal(orig_arr, np.array(variant, dtype=np.uint8)):
                any_different = True
                break
        assert any_different, "At least one variant should differ from the original"

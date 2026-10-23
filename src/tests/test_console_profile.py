"""Tests for ConsoleProfile system and multi-console enforcement."""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from retrogaze.console_profile import (
    ConsoleProfile,
    NES,
    GAME_BOY_DMG,
    GAME_BOY_POCKET,
    C64_HIRES,
    C64_MULTICOLOR,
    GENESIS,
    SNES_MODE1,
    SNES_MODE7,
    GBC,
    PC_ENGINE,
    get_profile,
    list_profiles,
)
from retrogaze.enforce import enforce_constraints
import retrogaze.enforce as enforce_module
import retrogaze.cleanup as cleanup_module
from retrogaze.cleanup import full_cleanup
from retrogaze.metadata import generate_metadata, _check_palette_valid
from retrogaze.palette import remap_to_palette, quantize_to_bit_depth


# --- ConsoleProfile dataclass tests ---


class TestConsoleProfiles:
    def test_nes_profile_values(self):
        assert NES.name == "nes"
        assert NES.resolution == (256, 240)
        assert NES.tile_size == 8
        assert NES.max_colors_per_tile == 4
        assert NES.has_attribute_table is True
        assert NES.attribute_block_size == 16
        assert NES.palette_assignment == "per_block_16x16"
        assert NES.max_sprites == 64
        assert NES.max_sprites_per_scanline == 8
        assert NES.pixel_aspect_ratio == (8, 7)

    def test_nes_palette_has_54_colors(self):
        """NES 2C02 has 56 entries (some duplicates), all defined."""
        assert NES.master_palette_hex is not None
        assert len(NES.master_palette_hex) == 56
        rgb = NES.master_palette_rgb()
        assert rgb is not None
        assert len(rgb) == 56
        # Verify first color is correct
        assert rgb[0] == (0x62, 0x62, 0x62)

    def test_gb_dmg_profile_values(self):
        assert GAME_BOY_DMG.name == "gb_dmg"
        assert GAME_BOY_DMG.resolution == (160, 144)
        assert GAME_BOY_DMG.tile_size == 8
        assert GAME_BOY_DMG.max_colors_per_tile == 4
        assert GAME_BOY_DMG.has_attribute_table is False
        assert GAME_BOY_DMG.attribute_block_size is None
        assert GAME_BOY_DMG.palette_assignment == "global"
        assert GAME_BOY_DMG.max_sprites == 40
        assert GAME_BOY_DMG.max_sprites_per_scanline == 10
        assert GAME_BOY_DMG.bg_palettes == 1
        assert GAME_BOY_DMG.sprite_palettes == 2

    def test_gb_dmg_palette_has_4_shades(self):
        assert GAME_BOY_DMG.master_palette_hex is not None
        assert len(GAME_BOY_DMG.master_palette_hex) == 4
        rgb = GAME_BOY_DMG.master_palette_rgb()
        assert rgb is not None
        assert len(rgb) == 4

    def test_gb_pocket_profile_values(self):
        assert GAME_BOY_POCKET.name == "gb_pocket"
        assert GAME_BOY_POCKET.resolution == (160, 144)
        rgb = GAME_BOY_POCKET.master_palette_rgb()
        assert rgb is not None
        assert len(rgb) == 4
        # Pocket uses true grayscale
        assert rgb[0] == (255, 255, 255)  # white
        assert rgb[3] == (0, 0, 0)        # black

    def test_profiles_are_frozen(self):
        with pytest.raises(AttributeError):
            NES.name = "snes"


# --- Profile registry tests ---


class TestProfileRegistry:
    def test_get_profile_by_name(self):
        assert get_profile("nes") is NES
        assert get_profile("gb_dmg") is GAME_BOY_DMG
        assert get_profile("gb_pocket") is GAME_BOY_POCKET

    def test_get_profile_aliases(self):
        assert get_profile("gb") is GAME_BOY_DMG
        assert get_profile("game_boy") is GAME_BOY_DMG

    def test_get_profile_case_insensitive(self):
        assert get_profile("NES") is NES
        assert get_profile("GB_DMG") is GAME_BOY_DMG

    def test_get_profile_unknown_raises(self):
        with pytest.raises(KeyError, match="Unknown console profile"):
            get_profile("dreamcast")

    def test_list_profiles(self):
        profiles = list_profiles()
        names = {p.name for p in profiles}
        assert "nes" in names
        assert "gb_dmg" in names
        assert "gb_pocket" in names
        # Should not have duplicates from aliases
        assert len(profiles) == len(names)


# --- Generic palette remapping tests ---


class TestRemapToPalette:
    def test_remap_to_4_shade_gb(self):
        """Remap a colored image to 4 GB DMG shades."""
        gb_palette = GAME_BOY_DMG.master_palette_rgb()
        # Create a small test image with various colors
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[:, :, 3] = 255  # fully opaque
        arr[0, :, :3] = [255, 0, 0]    # red
        arr[1, :, :3] = [0, 255, 0]    # green
        arr[2, :, :3] = [0, 0, 255]    # blue
        arr[3, :, :3] = [128, 128, 128]  # gray
        img = Image.fromarray(arr, "RGBA")

        result = remap_to_palette(img, gb_palette)
        result_arr = np.array(result)

        # All pixels should now use only GB DMG palette colors
        gb_set = {tuple(c) for c in gb_palette}
        for y in range(4):
            for x in range(4):
                pixel_rgb = tuple(result_arr[y, x, :3])
                assert pixel_rgb in gb_set, f"Pixel ({x},{y})={pixel_rgb} not in GB palette"

    def test_remap_preserves_transparency(self):
        gb_palette = GAME_BOY_DMG.master_palette_rgb()
        arr = np.zeros((4, 4, 4), dtype=np.uint8)
        arr[0, :] = [255, 0, 0, 255]  # opaque red
        arr[1, :] = [0, 0, 0, 0]      # transparent
        img = Image.fromarray(arr, "RGBA")

        result = remap_to_palette(img, gb_palette)
        result_arr = np.array(result)

        # Row 0: should be remapped to a shade
        assert result_arr[0, 0, 3] == 255
        # Row 1: should stay transparent
        assert result_arr[1, 0, 3] == 0


# --- Enforce with console parameter tests ---


def _save_test_image(path, w=16, h=16, color=(255, 0, 0)):
    """Create and save a simple test image."""
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    arr[:, :, :3] = color
    arr[:, :, 3] = 255
    Image.fromarray(arr, "RGBA").save(str(path))


class TestEnforceWithConsole:
    def test_default_is_nes(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path)
        result = enforce_constraints(str(img_path))
        assert result["console"] == "nes"

    def test_nes_explicit(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path)
        result = enforce_constraints(str(img_path), console="nes")
        assert result["console"] == "nes"
        assert result["console_display_name"] == "NES"

    def test_gb_dmg_enforcement(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 100, 50))
        result = enforce_constraints(str(img_path), console="gb_dmg")
        assert result["console"] == "gb_dmg"
        assert result["console_display_name"] == "Game Boy"

    def test_gb_pocket_enforcement(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(128, 128, 128))
        result = enforce_constraints(str(img_path), console="gb_pocket")
        assert result["console"] == "gb_pocket"
        assert result["console_display_name"] == "Game Boy Pocket"

    def test_profile_object_accepted(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path)
        result = enforce_constraints(str(img_path), console=GAME_BOY_DMG)
        assert result["console"] == "gb_dmg"

    def test_nes_backward_compatible(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(100, 50, 200))
        result_default = enforce_constraints(str(img_path))
        result_nes = enforce_constraints(str(img_path), console="nes")
        c_def = result_default["compliance"]
        c_nes = result_nes["compliance"]
        assert c_def["palette_valid"] == c_nes["palette_valid"]
        assert c_def["colors_per_tile_valid"] == c_nes["colors_per_tile_valid"]

    @pytest.mark.parametrize("profile", list_profiles(), ids=lambda p: p.name)
    def test_default_tile_cap_flows_from_profile(self, tmp_path, monkeypatch, profile):
        img_path = tmp_path / f"{profile.name}.png"
        _save_test_image(img_path, w=8, h=8)
        observed = []
        original = enforce_module.validate_tile_colors

        def capture_cap(image, max_colors=4, tile_size=8):
            observed.append(max_colors)
            return original(image, max_colors=max_colors, tile_size=tile_size)

        monkeypatch.setattr(enforce_module, "validate_tile_colors", capture_cap)
        enforce_constraints(img_path, console=profile)

        assert observed == [profile.max_colors_per_tile]

    @pytest.mark.parametrize(
        "profile",
        [NES, GAME_BOY_DMG, GAME_BOY_POCKET, C64_HIRES, C64_MULTICOLOR, GBC],
        ids=lambda p: p.name,
    )
    def test_8_bit_default_matches_old_explicit_cap_byte_for_byte(
        self, tmp_path, profile
    ):
        input_path = tmp_path / f"{profile.name}_input.png"
        default_path = tmp_path / f"{profile.name}_default.png"
        old_default_path = tmp_path / f"{profile.name}_old_default.png"
        colors = np.arange(8 * 8 * 4, dtype=np.uint8).reshape((8, 8, 4))
        colors[:, :, 3] = 255
        Image.fromarray(colors, "RGBA").save(input_path)

        enforce_constraints(input_path, output_path=default_path, console=profile)
        enforce_constraints(
            input_path,
            output_path=old_default_path,
            console=profile,
            max_colors_per_tile=4,
        )

        assert default_path.read_bytes() == old_default_path.read_bytes()

    def test_gb_output_has_only_4_shades(self, tmp_path):
        img_path = tmp_path / "input.png"
        out_path = tmp_path / "output.png"
        arr = np.zeros((16, 16, 4), dtype=np.uint8)
        arr[:, :, 3] = 255
        for y in range(16):
            for x in range(16):
                arr[y, x, :3] = [(x * 17) % 256, (y * 17) % 256, ((x + y) * 13) % 256]
        Image.fromarray(arr, "RGBA").save(str(img_path))
        enforce_constraints(str(img_path), console="gb_dmg", output_path=str(out_path))
        result_img = Image.open(str(out_path)).convert("RGBA")
        result_arr = np.array(result_img)
        result_img.close()
        opaque = result_arr[:, :, 3] > 0
        colors = result_arr[opaque][:, :3]
        unique = np.unique(colors.reshape(-1, 3), axis=0)
        assert len(unique) <= 4, f"Expected <=4 shades, got {len(unique)}"


class TestArtifactColorScrubGate:
    @pytest.mark.parametrize(
        "console,size",
        [
            ("snes", (32, 16)),
            ("super_nintendo", (16, 32)),
            ("genesis", (32, 32)),
            ("mega_drive", (64, 16)),
            ("pc_engine", (32, 32)),
            ("turbografx_16", (16, 64)),
        ],
    )
    def test_skips_scrub_for_large_16_bit_canvas(
        self, monkeypatch, console, size
    ):
        calls = []

        def spy(image, *args, **kwargs):
            calls.append((args, kwargs))
            return image

        monkeypatch.setattr(cleanup_module, "remove_artifact_colors", spy)
        full_cleanup(Image.new("RGBA", size, (10, 20, 30, 255)), console=console)

        assert calls == []

    @pytest.mark.parametrize(
        "console,size",
        [
            ("nes", (32, 32)),
            ("gbc", (64, 64)),
            ("c64", (32, 32)),
            ("snes", (31, 31)),
            ("genesis", (16, 16)),
            ("pc_engine", (31, 16)),
            (None, (32, 32)),
        ],
    )
    def test_keeps_scrub_everywhere_else(self, monkeypatch, console, size):
        calls = []

        def spy(image, *args, **kwargs):
            calls.append((args, kwargs))
            return image

        monkeypatch.setattr(cleanup_module, "remove_artifact_colors", spy)
        full_cleanup(Image.new("RGBA", size, (10, 20, 30, 255)), console=console)

        assert len(calls) == 1


# --- C64 profile tests ---


class TestC64Profiles:
    def test_c64_hires_profile_values(self):
        assert C64_HIRES.name == "c64_hires"
        assert C64_HIRES.resolution == (320, 200)
        assert C64_HIRES.max_colors_per_tile == 2
        assert C64_HIRES.has_attribute_table is False
        assert C64_HIRES.pixel_width == 1

    def test_c64_multicolor_profile_values(self):
        assert C64_MULTICOLOR.name == "c64_multicolor"
        assert C64_MULTICOLOR.resolution == (160, 200)
        assert C64_MULTICOLOR.max_colors_per_tile == 4
        assert C64_MULTICOLOR.pixel_width == 2

    def test_c64_palette_has_16_colors(self):
        assert C64_HIRES.master_palette_hex is not None
        assert len(C64_HIRES.master_palette_hex) == 16
        rgb = C64_HIRES.master_palette_rgb()
        assert rgb is not None
        assert len(rgb) == 16
        assert rgb[0] == (0, 0, 0)      # Black
        assert rgb[1] == (255, 255, 255)  # White

    def test_c64_lookup_by_name(self):
        assert get_profile("c64") is C64_HIRES
        assert get_profile("c64_hires") is C64_HIRES
        assert get_profile("c64_multicolor") is C64_MULTICOLOR
        assert get_profile("commodore_64") is C64_HIRES

    def test_c64_in_list_profiles(self):
        names = {p.name for p in list_profiles()}
        assert "c64_hires" in names
        assert "c64_multicolor" in names


class TestC64Enforcement:
    def test_c64_hires_enforcement(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 50, 100))
        result = enforce_constraints(str(img_path), console="c64")
        assert result["console"] == "c64_hires"
        assert result["console_display_name"] == "Commodore 64"

    def test_c64_output_has_only_16_colors(self, tmp_path):
        """C64 enforcement remaps to 16-color VICE palette."""
        img_path = tmp_path / "input.png"
        out_path = tmp_path / "output.png"
        arr = np.zeros((16, 16, 4), dtype=np.uint8)
        arr[:, :, 3] = 255
        for y in range(16):
            for x in range(16):
                arr[y, x, :3] = [(x * 17) % 256, (y * 17) % 256, ((x + y) * 13) % 256]
        Image.fromarray(arr, "RGBA").save(str(img_path))
        enforce_constraints(str(img_path), console="c64", output_path=str(out_path))
        result_img = Image.open(str(out_path)).convert("RGBA")
        result_arr = np.array(result_img)
        result_img.close()
        opaque = result_arr[:, :, 3] > 0
        colors = result_arr[opaque][:, :3]
        unique = np.unique(colors.reshape(-1, 3), axis=0)
        c64_rgb = {tuple(c) for c in C64_HIRES.master_palette_rgb()}
        for uc in unique:
            assert tuple(uc) in c64_rgb, f"Color {tuple(uc)} not in C64 palette"

    def test_c64_hires_max_2_colors_per_tile(self, tmp_path):
        """C64 hi-res: enforce max 2 colors per 8x8 cell."""
        img_path = tmp_path / "input.png"
        out_path = tmp_path / "output.png"
        # Create 16x16 image with many colors
        arr = np.zeros((16, 16, 4), dtype=np.uint8)
        arr[:, :, 3] = 255
        arr[0:8, 0:8, :3] = [255, 0, 0]    # red
        arr[0:8, 8:16, :3] = [0, 255, 0]   # green
        arr[8:16, 0:8, :3] = [0, 0, 255]   # blue
        arr[8:16, 8:16, :3] = [128, 128, 0] # olive
        Image.fromarray(arr, "RGBA").save(str(img_path))
        enforce_constraints(
            str(img_path), console="c64_hires",
            max_colors_per_tile=2, output_path=str(out_path),
        )
        # Each 8x8 tile should have at most 2 colors
        result_img = Image.open(str(out_path)).convert("RGBA")
        result_arr = np.array(result_img)
        result_img.close()
        for ty in range(0, 16, 8):
            for tx in range(0, 16, 8):
                tile = result_arr[ty:ty+8, tx:tx+8]
                opaque = tile[:, :, 3] > 0
                if opaque.any():
                    colors = tile[opaque][:, :3]
                    unique = np.unique(colors.reshape(-1, 3), axis=0)
                    assert len(unique) <= 2, (
                        f"Tile ({tx},{ty}) has {len(unique)} colors, expected <=2"
                    )


# --- Genesis profile tests ---


class TestGenesisProfile:
    def test_genesis_profile_values(self):
        assert GENESIS.name == "genesis"
        assert GENESIS.resolution == (320, 224)
        assert GENESIS.max_colors_per_tile == 16
        assert GENESIS.color_depth_bits == 9
        assert GENESIS.has_attribute_table is False
        assert GENESIS.palette_shared_bg_sprite is True
        assert GENESIS.background_planes == 2

    def test_genesis_free_color(self):
        """Genesis uses free 9-bit RGB — no fixed master palette."""
        assert GENESIS.master_palette_hex is None
        assert GENESIS.master_palette_rgb() is None

    def test_genesis_lookup(self):
        assert get_profile("genesis") is GENESIS
        assert get_profile("mega_drive") is GENESIS

    def test_genesis_enforcement(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 100, 50))
        result = enforce_constraints(str(img_path), console="genesis")
        assert result["console"] == "genesis"

    def test_genesis_9bit_quantization(self, tmp_path):
        """Genesis 9-bit: each channel must be one of the 8 valid 3-bit levels."""
        # Valid 3-bit levels expanded to 8-bit: 0,36,73,109,146,182,219,255
        valid_levels = set()
        for v in range(8):
            valid_levels.add(round(v * 255 / 7))
        # Allow off-by-one due to integer rounding
        valid_with_tolerance = set()
        for lv in valid_levels:
            for delta in (-1, 0, 1):
                clamped = max(0, min(255, lv + delta))
                valid_with_tolerance.add(clamped)

        arr = np.zeros((16, 16, 4), dtype=np.uint8)
        arr[:, :, :3] = [200, 100, 50]
        arr[:, :, 3] = 255
        img = Image.fromarray(arr, "RGBA")
        result_img = quantize_to_bit_depth(img, bits_per_channel=3)
        result_arr = np.array(result_img)

        opaque = result_arr[:, :, 3] > 0
        pixels = result_arr[opaque][:, :3]
        for px in pixels.reshape(-1, 3):
            for ch in px:
                assert int(ch) in valid_with_tolerance, (
                    f"Channel value {ch} is not a valid 9-bit (3-bit/channel) level"
                )


# --- SNES profile tests ---


class TestSNESProfiles:
    def test_snes_mode1_values(self):
        assert SNES_MODE1.name == "snes"
        assert SNES_MODE1.resolution == (256, 224)
        assert SNES_MODE1.max_colors_per_tile == 16
        assert SNES_MODE1.color_depth_bits == 15

    def test_snes_mode7_values(self):
        assert SNES_MODE7.name == "snes_mode7"
        assert SNES_MODE7.max_colors_per_tile == 256
        assert SNES_MODE7.bits_per_pixel == 8

    def test_snes_lookup(self):
        assert get_profile("snes") is SNES_MODE1
        assert get_profile("super_nintendo") is SNES_MODE1
        assert get_profile("snes_mode7") is SNES_MODE7

    def test_snes_enforcement(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(100, 200, 150))
        result = enforce_constraints(str(img_path), console="snes")
        assert result["console"] == "snes"

    def test_snes_15bit_quantization(self, tmp_path):
        """SNES 15-bit: each channel must be one of the 32 valid 5-bit levels."""
        # Valid 5-bit levels expanded to 8-bit: multiples of 255/31 ~ 8.226
        valid_levels = set()
        for v in range(32):
            valid_levels.add(round(v * 255 / 31))
        # Allow off-by-one due to integer rounding
        valid_with_tolerance = set()
        for lv in valid_levels:
            for delta in (-1, 0, 1):
                clamped = max(0, min(255, lv + delta))
                valid_with_tolerance.add(clamped)

        arr = np.zeros((16, 16, 4), dtype=np.uint8)
        arr[:, :, :3] = [100, 200, 150]
        arr[:, :, 3] = 255
        img = Image.fromarray(arr, "RGBA")
        result_img = quantize_to_bit_depth(img, bits_per_channel=5)
        result_arr = np.array(result_img)

        opaque = result_arr[:, :, 3] > 0
        pixels = result_arr[opaque][:, :3]
        for px in pixels.reshape(-1, 3):
            for ch in px:
                assert int(ch) in valid_with_tolerance, (
                    f"Channel value {ch} is not a valid 15-bit (5-bit/channel) level"
                )


# --- GBC profile tests ---


class TestGBCProfile:
    def test_gbc_profile_values(self):
        assert GBC.name == "gbc"
        assert GBC.resolution == (160, 144)
        assert GBC.max_colors_per_tile == 4
        assert GBC.color_depth_bits == 15
        assert GBC.bg_palettes == 8
        assert GBC.sprite_palettes == 8

    def test_gbc_lookup(self):
        assert get_profile("gbc") is GBC
        assert get_profile("game_boy_color") is GBC

    def test_gbc_enforcement(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(80, 160, 220))
        result = enforce_constraints(str(img_path), console="gbc")
        assert result["console"] == "gbc"


# --- PC-Engine profile tests ---


class TestPCEngineProfile:
    def test_pc_engine_values(self):
        assert PC_ENGINE.name == "pc_engine"
        assert PC_ENGINE.resolution == (256, 224)
        assert PC_ENGINE.max_colors_per_tile == 16
        assert PC_ENGINE.color_depth_bits == 9

    def test_pc_engine_lookup(self):
        assert get_profile("pc_engine") is PC_ENGINE
        assert get_profile("turbografx") is PC_ENGINE


# --- Quantization tests ---


class TestQuantization:
    def test_9bit_quantization_reduces_colors(self):
        """9-bit quantization (3 bits/channel) allows at most 8^3 = 512 unique colors."""
        arr = np.zeros((64, 64, 4), dtype=np.uint8)
        arr[:, :, 3] = 255
        # Fill with a wide variety of RGB values
        for y in range(64):
            for x in range(64):
                arr[y, x, 0] = (x * 4) % 256
                arr[y, x, 1] = (y * 4) % 256
                arr[y, x, 2] = ((x + y) * 3) % 256
        img = Image.fromarray(arr, "RGBA")
        result = quantize_to_bit_depth(img, bits_per_channel=3)
        result_arr = np.array(result)
        opaque = result_arr[:, :, 3] > 0
        colors = result_arr[opaque][:, :3].reshape(-1, 3)
        unique = np.unique(colors, axis=0)
        assert len(unique) <= 512, (
            f"9-bit quantization produced {len(unique)} colors, expected <= 512"
        )

    def test_15bit_quantization_reduces_colors(self):
        """15-bit quantization (5 bits/channel) allows at most 32^3 = 32768 unique colors."""
        arr = np.zeros((64, 64, 4), dtype=np.uint8)
        arr[:, :, 3] = 255
        for y in range(64):
            for x in range(64):
                arr[y, x, 0] = (x * 4) % 256
                arr[y, x, 1] = (y * 4) % 256
                arr[y, x, 2] = ((x + y) * 3) % 256
        img = Image.fromarray(arr, "RGBA")
        result = quantize_to_bit_depth(img, bits_per_channel=5)
        result_arr = np.array(result)
        opaque = result_arr[:, :, 3] > 0
        colors = result_arr[opaque][:, :3].reshape(-1, 3)
        unique = np.unique(colors, axis=0)
        assert len(unique) <= 32768, (
            f"15-bit quantization produced {len(unique)} colors, expected <= 32768"
        )

    def test_quantization_preserves_transparency(self):
        """Transparent pixels must remain fully transparent after quantization."""
        arr = np.zeros((8, 8, 4), dtype=np.uint8)
        arr[0:4, :, :3] = [200, 100, 50]
        arr[0:4, :, 3] = 255   # opaque top half
        arr[4:8, :, 3] = 0     # transparent bottom half
        img = Image.fromarray(arr, "RGBA")

        for bits in (3, 5):
            result = quantize_to_bit_depth(img, bits_per_channel=bits)
            result_arr = np.array(result)
            transparent_pixels = result_arr[4:8, :, 3]
            assert np.all(transparent_pixels == 0), (
                f"quantize_to_bit_depth({bits}) corrupted transparency"
            )


# --- Console-aware palette validation tests ---


class TestConsoleAwarePaletteValidation:
    """Tests that metadata reports palette_valid correctly per console."""

    def test_nes_exact_colors_are_valid(self):
        """Image with exact NES palette colors should be palette_valid."""
        from retrogaze.palette import NES_PALETTE_RGB
        r, g, b = NES_PALETTE_RGB[5]
        img = Image.new("RGBA", (8, 8), (r, g, b, 255))
        assert _check_palette_valid(img, NES) is True

    def test_nes_non_palette_color_invalid(self):
        """Image with a non-NES color should be palette_valid=False."""
        img = Image.new("RGBA", (8, 8), (123, 45, 67, 255))
        assert _check_palette_valid(img, NES) is False

    def test_gb_dmg_exact_shades_valid(self):
        """Image using exact DMG palette shades should be valid."""
        gb_rgb = GAME_BOY_DMG.master_palette_rgb()
        r, g, b = gb_rgb[1]
        img = Image.new("RGBA", (8, 8), (r, g, b, 255))
        assert _check_palette_valid(img, GAME_BOY_DMG) is True

    def test_gb_dmg_non_palette_invalid(self):
        """Non-DMG color should fail palette check."""
        img = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
        assert _check_palette_valid(img, GAME_BOY_DMG) is False

    def test_gb_pocket_exact_shades_valid(self):
        pocket_rgb = GAME_BOY_POCKET.master_palette_rgb()
        r, g, b = pocket_rgb[0]
        img = Image.new("RGBA", (8, 8), (r, g, b, 255))
        assert _check_palette_valid(img, GAME_BOY_POCKET) is True

    def test_c64_exact_colors_valid(self):
        c64_rgb = C64_HIRES.master_palette_rgb()
        r, g, b = c64_rgb[6]  # dark blue
        img = Image.new("RGBA", (8, 8), (r, g, b, 255))
        assert _check_palette_valid(img, C64_HIRES) is True

    def test_genesis_9bit_quantized_valid(self):
        """A properly 9-bit quantized color should pass Genesis validation."""
        # 3-bit per channel: value 5 -> expanded = 5*255//7 = 182
        img = Image.new("RGBA", (8, 8), (182, 182, 182, 255))
        assert _check_palette_valid(img, GENESIS) is True

    def test_genesis_non_9bit_invalid(self):
        """A color that isn't a valid 9-bit value should fail."""
        # 200 is not a valid 3-bit expanded level (valid: 0,36,73,109,146,182,219,255)
        img = Image.new("RGBA", (8, 8), (200, 200, 200, 255))
        assert _check_palette_valid(img, GENESIS) is False

    def test_snes_15bit_quantized_valid(self):
        """A properly 15-bit quantized color should pass SNES validation."""
        # 5-bit per channel: value 16 -> expanded = 16*255//31 = 131
        img = Image.new("RGBA", (8, 8), (131, 131, 131, 255))
        assert _check_palette_valid(img, SNES_MODE1) is True

    def test_gbc_15bit_quantized_valid(self):
        """GBC also uses 15-bit RGB like SNES."""
        img = Image.new("RGBA", (8, 8), (131, 131, 131, 255))
        assert _check_palette_valid(img, GBC) is True

    def test_pc_engine_9bit_quantized_valid(self):
        """PC Engine uses 9-bit RGB like Genesis."""
        img = Image.new("RGBA", (8, 8), (182, 182, 182, 255))
        assert _check_palette_valid(img, PC_ENGINE) is True

    def test_transparent_image_always_valid(self):
        """A fully transparent image should be palette_valid for any console."""
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        assert _check_palette_valid(img, NES) is True
        assert _check_palette_valid(img, GAME_BOY_DMG) is True
        assert _check_palette_valid(img, GENESIS) is True


class TestEnforcePaletteValidOutput:
    """Tests that enforce_constraints produces palette_valid output for each console."""

    def test_nes_enforcement_passes_palette(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 100, 50))
        result = enforce_constraints(str(img_path), console="nes")
        assert result["compliance"]["palette_valid"] is True

    def test_gb_dmg_enforcement_passes_palette(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 100, 50))
        result = enforce_constraints(str(img_path), console="gb_dmg")
        assert result["compliance"]["palette_valid"] is True

    def test_gb_pocket_enforcement_passes_palette(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(128, 128, 128))
        result = enforce_constraints(str(img_path), console="gb_pocket")
        assert result["compliance"]["palette_valid"] is True

    def test_c64_enforcement_passes_palette(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 50, 100))
        result = enforce_constraints(str(img_path), console="c64")
        assert result["compliance"]["palette_valid"] is True

    def test_genesis_enforcement_passes_palette(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 100, 50))
        result = enforce_constraints(str(img_path), console="genesis")
        assert result["compliance"]["palette_valid"] is True

    def test_snes_enforcement_passes_palette(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(100, 200, 150))
        result = enforce_constraints(str(img_path), console="snes")
        assert result["compliance"]["palette_valid"] is True

    def test_gbc_enforcement_passes_palette(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(80, 160, 220))
        result = enforce_constraints(str(img_path), console="gbc")
        assert result["compliance"]["palette_valid"] is True

    def test_pc_engine_enforcement_passes_palette(self, tmp_path):
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 100, 50))
        result = enforce_constraints(str(img_path), console="pc_engine")
        assert result["compliance"]["palette_valid"] is True

    def test_compliance_key_is_palette_valid_not_nes(self, tmp_path):
        """Compliance key should be 'palette_valid', not 'nes_palette_valid'."""
        img_path = tmp_path / "test.png"
        _save_test_image(img_path)
        for console_name in ("nes", "gb_dmg", "genesis", "snes", "gbc"):
            result = enforce_constraints(str(img_path), console=console_name)
            assert "palette_valid" in result["compliance"]
            assert "nes_palette_valid" not in result["compliance"]

    def test_metadata_has_console_hex_not_nes(self, tmp_path):
        """For non-NES consoles, palette hex should NOT contain nes_indices."""
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 100, 50))
        result = enforce_constraints(str(img_path), console="gb_dmg")
        assert "nes_indices" not in result["palette"]
        assert "hex" in result["palette"]

    def test_nes_metadata_still_has_nes_indices(self, tmp_path):
        """NES should still include nes_indices for backward compat."""
        img_path = tmp_path / "test.png"
        _save_test_image(img_path, color=(200, 100, 50))
        result = enforce_constraints(str(img_path), console="nes")
        assert "nes_indices" in result["palette"]
        assert "hex" in result["palette"]

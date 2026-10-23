"""
Tests for console-relative era calibration.

Verifies that pixel_scale and max_cleanup_colors are correctly set per
console+era combo, and that NES values match the pre-change hardcoded behavior.
"""

from __future__ import annotations

import os
import sys
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from retrogaze.console_prompt_data import get_prompt_data, EraPromptData


# ---------------------------------------------------------------------------
# Tests: EraPromptData fields exist and have correct NES values
# ---------------------------------------------------------------------------

class TestNESCalibrationUnchanged:
    """NES calibration must exactly match the old hardcoded values."""

    def test_nes_retro_pixel_scale(self):
        era = get_prompt_data("nes").eras["retro"]
        assert era.pixel_scale == 4

    def test_nes_early_pixel_scale(self):
        era = get_prompt_data("nes").eras["early"]
        assert era.pixel_scale == 6

    def test_nes_mid_pixel_scale(self):
        era = get_prompt_data("nes").eras["mid"]
        assert era.pixel_scale is None

    def test_nes_late_pixel_scale(self):
        era = get_prompt_data("nes").eras["late"]
        assert era.pixel_scale is None

    def test_nes_retro_max_cleanup_colors(self):
        era = get_prompt_data("nes").eras["retro"]
        assert era.max_cleanup_colors == 3

    def test_nes_early_max_cleanup_colors(self):
        era = get_prompt_data("nes").eras["early"]
        assert era.max_cleanup_colors == 4

    def test_nes_mid_max_cleanup_colors(self):
        era = get_prompt_data("nes").eras["mid"]
        assert era.max_cleanup_colors == 6

    def test_nes_late_max_cleanup_colors(self):
        era = get_prompt_data("nes").eras["late"]
        assert era.max_cleanup_colors == 6


# ---------------------------------------------------------------------------
# Tests: 16-bit consoles have higher color budgets than NES
# ---------------------------------------------------------------------------

class TestSixteenBitConsoleCalibration:
    """Genesis, SNES, and PC Engine should have more generous color budgets."""

    @pytest.mark.parametrize("console", ["genesis", "snes", "pc_engine"])
    def test_early_era_more_colors_than_nes(self, console):
        era_16bit = get_prompt_data(console).eras["early"]
        era_nes = get_prompt_data("nes").eras["early"]
        assert era_16bit.max_cleanup_colors > era_nes.max_cleanup_colors, (
            f"{console} early should have more cleanup colors than NES early"
        )

    @pytest.mark.parametrize("console", ["genesis", "snes", "pc_engine"])
    def test_mid_era_more_colors_than_nes(self, console):
        era_16bit = get_prompt_data(console).eras["mid"]
        era_nes = get_prompt_data("nes").eras["mid"]
        assert era_16bit.max_cleanup_colors > era_nes.max_cleanup_colors, (
            f"{console} mid should have more cleanup colors than NES mid"
        )

    @pytest.mark.parametrize("console", ["genesis", "snes", "pc_engine"])
    def test_late_era_more_colors_than_nes(self, console):
        era_16bit = get_prompt_data(console).eras["late"]
        era_nes = get_prompt_data("nes").eras["late"]
        assert era_16bit.max_cleanup_colors > era_nes.max_cleanup_colors, (
            f"{console} late should have more cleanup colors than NES late"
        )

    @pytest.mark.parametrize("console", ["genesis", "snes", "pc_engine"])
    def test_early_pixel_scale_is_none(self, console):
        """16-bit 'early' is already sophisticated — should auto-detect, not chunk down."""
        era = get_prompt_data(console).eras["early"]
        assert era.pixel_scale is None, (
            f"{console} early should use auto-detect pixel_scale, not a chunky forced value"
        )


# ---------------------------------------------------------------------------
# Tests: Game Boy stays limited
# ---------------------------------------------------------------------------

class TestGameBoyCalibration:
    """GB DMG/Pocket only have 4 shades — color budgets should be low."""

    def test_gb_dmg_mid_max_4_colors(self):
        era = get_prompt_data("gb_dmg").eras["mid"]
        assert era.max_cleanup_colors <= 4

    def test_gb_dmg_late_max_4_colors(self):
        era = get_prompt_data("gb_dmg").eras["late"]
        assert era.max_cleanup_colors <= 4

    def test_gb_dmg_early_pixel_scale_chunky(self):
        era = get_prompt_data("gb_dmg").eras["early"]
        assert era.pixel_scale is not None and era.pixel_scale <= 6


# ---------------------------------------------------------------------------
# Tests: GBC gets more colors than GB DMG
# ---------------------------------------------------------------------------

class TestGBCCalibration:
    """GBC has free color but limited per-tile — more than DMG, less than Genesis."""

    def test_gbc_mid_more_colors_than_gb_dmg(self):
        gbc = get_prompt_data("gbc").eras["mid"]
        dmg = get_prompt_data("gb_dmg").eras["mid"]
        assert gbc.max_cleanup_colors > dmg.max_cleanup_colors

    def test_gbc_late_less_colors_than_genesis(self):
        gbc = get_prompt_data("gbc").eras["late"]
        gen = get_prompt_data("genesis").eras["late"]
        assert gbc.max_cleanup_colors < gen.max_cleanup_colors


# ---------------------------------------------------------------------------
# Tests: Era progression within each console
# ---------------------------------------------------------------------------

class TestEraProgression:
    """Within each console, later eras should have >= color budget."""

    @pytest.mark.parametrize("console", ["nes", "genesis", "snes", "gbc", "pc_engine", "gb_dmg", "c64"])
    def test_color_budget_non_decreasing(self, console):
        data = get_prompt_data(console)
        eras_ordered = ["early", "mid", "late"]
        # Only test eras that exist for this console
        available = [e for e in eras_ordered if e in data.eras]
        for i in range(1, len(available)):
            prev = data.eras[available[i - 1]].max_cleanup_colors
            curr = data.eras[available[i]].max_cleanup_colors
            assert curr >= prev, (
                f"{console}: {available[i]} ({curr}) should have >= colors than {available[i-1]} ({prev})"
            )


# ---------------------------------------------------------------------------
# Tests: _pixelize uses era_data.pixel_scale
# ---------------------------------------------------------------------------

class TestPixelizeUsesEraData:
    """Verify _pixelize reads pixel_scale from EraPromptData."""

    def _make_mock_response(self, payload_capture):
        async def fake_post_with_retry(client, url, *, json, headers):
            payload_capture.append(json)
            mock_resp = MagicMock()
            mock_resp.json.return_value = {
                "images": [
                    {"url": "https://fake/full.png"},
                    {"url": "https://fake/scaled.png"},
                ]
            }
            return mock_resp
        return fake_post_with_retry

    def _make_mock_download(self):
        from PIL import Image as PILImage
        async def fake_download(url):
            return PILImage.new("RGBA", (16, 16), (100, 100, 100, 255))
        return fake_download

    @pytest.mark.asyncio
    async def test_nes_retro_sends_scale_4(self):
        from retrogaze.generate import _pixelize
        captured = []
        with patch("retrogaze.generate._post_with_retry", self._make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", self._make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key",
                            console="nes", era="retro")
        assert captured[0].get("scale") == 4

    @pytest.mark.asyncio
    async def test_nes_mid_no_scale(self):
        from retrogaze.generate import _pixelize
        captured = []
        with patch("retrogaze.generate._post_with_retry", self._make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", self._make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key",
                            console="nes", era="mid")
        assert "scale" not in captured[0]

    @pytest.mark.asyncio
    async def test_genesis_early_no_scale(self):
        """Genesis early should auto-detect, not use NES-calibrated chunky scale."""
        from retrogaze.generate import _pixelize
        captured = []
        with patch("retrogaze.generate._post_with_retry", self._make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", self._make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key",
                            console="genesis", era="early")
        assert "scale" not in captured[0]

    @pytest.mark.asyncio
    async def test_gb_dmg_early_sends_scale_6(self):
        from retrogaze.generate import _pixelize
        captured = []
        with patch("retrogaze.generate._post_with_retry", self._make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", self._make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key",
                            console="gb_dmg", era="early")
        assert captured[0].get("scale") == 6


# ---------------------------------------------------------------------------
# Tests: full_cleanup uses console-aware color limits
# ---------------------------------------------------------------------------

class TestCleanupConsoleAware:
    """Verify full_cleanup reads max_cleanup_colors from console+era."""

    def test_nes_mid_cleanup_limits_to_6(self):
        """NES mid should still use 6 colors max — unchanged behavior."""
        from retrogaze.cleanup import full_cleanup
        from PIL import Image as PILImage
        import numpy as np

        # Create a test image with 10 colors
        img = PILImage.new("RGBA", (16, 16), (0, 0, 0, 0))
        pixels = img.load()
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 0, 255), (0, 255, 255),
            (128, 0, 0), (0, 128, 0), (0, 0, 128),
            (128, 128, 0),
        ]
        for i in range(10):
            x, y = i % 4 + 2, i // 4 + 2
            pixels[x, y] = (*colors[i], 255)

        result = full_cleanup(img, era="mid", console="nes")
        # Count unique opaque colors
        arr = np.array(result.convert("RGBA"), dtype=np.uint8)
        opaque = arr[:, :, 3] > 0
        if np.any(opaque):
            unique = np.unique(arr[opaque][:, :3].reshape(-1, 3), axis=0)
            assert len(unique) <= 6

    def test_genesis_mid_cleanup_allows_more_than_6(self):
        """Genesis mid should allow more colors than NES's 6."""
        from retrogaze.cleanup import full_cleanup
        from PIL import Image as PILImage
        import numpy as np

        # Create a test image with 10 colors — Genesis should keep more of them
        img = PILImage.new("RGBA", (32, 32), (0, 0, 0, 0))
        pixels = img.load()
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 0, 255), (0, 255, 255),
            (128, 0, 0), (0, 128, 0), (0, 0, 128),
            (128, 128, 0), (64, 64, 64), (192, 192, 192),
        ]
        # Fill a 4x3 block with each color (enough pixels to survive artifact removal)
        for i, (r, g, b) in enumerate(colors):
            x0, y0 = (i % 4) * 4 + 4, (i // 4) * 4 + 4
            for dx in range(4):
                for dy in range(4):
                    pixels[x0 + dx, y0 + dy] = (r, g, b, 255)

        result = full_cleanup(img, era="mid", console="genesis")
        arr = np.array(result.convert("RGBA"), dtype=np.uint8)
        opaque = arr[:, :, 3] > 0
        if np.any(opaque):
            unique = np.unique(arr[opaque][:, :3].reshape(-1, 3), axis=0)
            # Genesis mid allows 12 colors — should keep more than NES's 6
            assert len(unique) > 6, (
                f"Genesis mid should allow more than 6 colors, got {len(unique)}"
            )

    def test_no_console_falls_back_to_nes_defaults(self):
        """Without console param, should use NES-calibrated fallback."""
        from retrogaze.cleanup import full_cleanup
        from PIL import Image as PILImage
        import numpy as np

        img = PILImage.new("RGBA", (16, 16), (0, 0, 0, 0))
        pixels = img.load()
        colors = [
            (255, 0, 0), (0, 255, 0), (0, 0, 255),
            (255, 255, 0), (255, 0, 255), (0, 255, 255),
            (128, 0, 0), (0, 128, 0), (0, 0, 128),
            (128, 128, 0),
        ]
        for i in range(10):
            x, y = i % 4 + 2, i // 4 + 2
            pixels[x, y] = (*colors[i], 255)

        result = full_cleanup(img, era="mid")  # no console
        arr = np.array(result.convert("RGBA"), dtype=np.uint8)
        opaque = arr[:, :, 3] > 0
        if np.any(opaque):
            unique = np.unique(arr[opaque][:, :3].reshape(-1, 3), axis=0)
            assert len(unique) <= 6


# ---------------------------------------------------------------------------
# Tests: all registered consoles have calibration fields
# ---------------------------------------------------------------------------

class TestAllConsolesHaveCalibration:
    """Every era in every registered console must have calibration fields."""

    @pytest.mark.parametrize("console", ["nes", "gb_dmg", "c64", "gbc", "snes", "genesis", "pc_engine"])
    def test_all_eras_have_pixel_scale(self, console):
        data = get_prompt_data(console)
        for era_name, era in data.eras.items():
            assert hasattr(era, "pixel_scale"), f"{console}/{era_name} missing pixel_scale"

    @pytest.mark.parametrize("console", ["nes", "gb_dmg", "c64", "gbc", "snes", "genesis", "pc_engine"])
    def test_all_eras_have_max_cleanup_colors(self, console):
        data = get_prompt_data(console)
        for era_name, era in data.eras.items():
            assert hasattr(era, "max_cleanup_colors"), f"{console}/{era_name} missing max_cleanup_colors"
            assert era.max_cleanup_colors >= 2, f"{console}/{era_name}: max_cleanup_colors too low"
            assert era.max_cleanup_colors <= 16, f"{console}/{era_name}: max_cleanup_colors too high"

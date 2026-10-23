"""
Tests for console-aware Image2Pixel palette selection in generate.py.

Verifies that _pixelize() uses the correct fixed_palette per console:
- NES: NES 2C02 palette (54 colors) — must be identical to pre-change behavior
- GB DMG: 4 green shades
- GB Pocket: 4 grayscale shades
- C64: 16 VICE colors
- Genesis/SNES/GBC/PC Engine: no fixed palette (free color)
"""

from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from retrogaze.generate import _pixelize
from retrogaze.palette import _NES_PALETTE_HEX
from retrogaze.console_profile import (
    NES, GAME_BOY_DMG, GAME_BOY_POCKET, C64_HIRES, C64_MULTICOLOR,
    GENESIS, SNES_MODE1, GBC, PC_ENGINE,
)


# ---------------------------------------------------------------------------
# Helpers — capture what _pixelize sends to Image2Pixel
# ---------------------------------------------------------------------------

def _make_mock_response(payload_capture: list):
    """Create a mock httpx response that captures the payload and returns fake images."""
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


def _make_mock_download():
    """Create a mock image downloader that returns a small RGBA image."""
    from PIL import Image as PILImage

    async def fake_download(url):
        return PILImage.new("RGBA", (16, 16), (100, 100, 100, 255))
    return fake_download


# ---------------------------------------------------------------------------
# Tests: fixed-palette consoles get their master palette
# ---------------------------------------------------------------------------

class TestFixedPaletteConsoles:
    """Consoles with a hardware-fixed palette should pass it to Image2Pixel."""

    @pytest.mark.asyncio
    async def test_nes_uses_nes_palette(self):
        """NES must use the NES 2C02 palette — identical to pre-change behavior."""
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="nes")

        payload = captured[0]
        expected = list(dict.fromkeys(_NES_PALETTE_HEX))
        assert payload["fixed_palette"] == expected
        assert payload["max_colors"] == 8

    @pytest.mark.asyncio
    async def test_nes_default_unchanged(self):
        """When no console is specified, behavior should match NES (backward compat)."""
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key")

        payload = captured[0]
        expected = list(dict.fromkeys(_NES_PALETTE_HEX))
        assert payload["fixed_palette"] == expected
        assert payload["max_colors"] == 8

    @pytest.mark.asyncio
    async def test_gb_dmg_uses_4_green_shades(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="gb_dmg")

        payload = captured[0]
        assert payload["fixed_palette"] == list(GAME_BOY_DMG.master_palette_hex)
        assert len(payload["fixed_palette"]) == 4

    @pytest.mark.asyncio
    async def test_gb_pocket_uses_4_grayscale_shades(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="gb_pocket")

        payload = captured[0]
        assert payload["fixed_palette"] == list(GAME_BOY_POCKET.master_palette_hex)
        assert set(payload["fixed_palette"]) == {"#FFFFFF", "#AAAAAA", "#555555", "#000000"}

    @pytest.mark.asyncio
    async def test_c64_uses_16_vice_colors(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="c64")

        payload = captured[0]
        assert payload["fixed_palette"] == list(C64_HIRES.master_palette_hex)
        assert len(payload["fixed_palette"]) == 16

    @pytest.mark.asyncio
    async def test_c64_multicolor_uses_same_16_colors(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="c64_multicolor")

        payload = captured[0]
        assert payload["fixed_palette"] == list(C64_MULTICOLOR.master_palette_hex)


# ---------------------------------------------------------------------------
# Tests: free-color consoles get NO fixed palette
# ---------------------------------------------------------------------------

class TestFreeColorConsoles:
    """Free-color consoles should NOT send a fixed_palette to Image2Pixel."""

    @pytest.mark.asyncio
    async def test_genesis_no_fixed_palette(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="genesis")

        payload = captured[0]
        assert "fixed_palette" not in payload

    @pytest.mark.asyncio
    async def test_snes_no_fixed_palette(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="snes")

        payload = captured[0]
        assert "fixed_palette" not in payload

    @pytest.mark.asyncio
    async def test_gbc_no_fixed_palette(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="gbc")

        payload = captured[0]
        assert "fixed_palette" not in payload

    @pytest.mark.asyncio
    async def test_pc_engine_no_fixed_palette(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="pc_engine")

        payload = captured[0]
        assert "fixed_palette" not in payload

    @pytest.mark.asyncio
    async def test_free_color_max_colors_uses_headroom(self):
        """Free-color consoles should get generous max_colors based on per-tile limit."""
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize("https://fake/img.png", 16, 16, "fake-key", console="genesis")

        payload = captured[0]
        # Genesis: 16 colors per tile * 2 = 32
        assert payload["max_colors"] == GENESIS.max_colors_per_tile * 2


# ---------------------------------------------------------------------------
# Tests: palette_colors override takes priority over console
# ---------------------------------------------------------------------------

class TestPaletteColorsOverride:
    """When palette_colors is explicitly set, it should override console defaults."""

    @pytest.mark.asyncio
    async def test_locked_palette_overrides_console(self):
        locked = ["#FF0000", "#00FF00", "#0000FF"]
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize(
                "https://fake/img.png", 16, 16, "fake-key",
                palette_colors=locked, console="genesis",
            )

        payload = captured[0]
        assert payload["fixed_palette"] == locked
        assert payload["max_colors"] == 3

    @pytest.mark.asyncio
    async def test_locked_palette_overrides_nes_default(self):
        locked = ["#000000", "#FFFFFF"]
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize(
                "https://fake/img.png", 16, 16, "fake-key",
                palette_colors=locked, console="nes",
            )

        payload = captured[0]
        assert payload["fixed_palette"] == locked
        assert payload["max_colors"] == 2


# ---------------------------------------------------------------------------
# Tests: tile max_colors bump
# ---------------------------------------------------------------------------

class TestTileMaxColors:
    """Tiles should get at least 12 max_colors for texture variation."""

    @pytest.mark.asyncio
    async def test_nes_tile_max_colors_bumped(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize(
                "https://fake/img.png", 8, 8, "fake-key",
                asset_type="tile", console="nes",
            )

        payload = captured[0]
        assert payload["max_colors"] >= 12

    @pytest.mark.asyncio
    async def test_genesis_tile_max_colors_at_least_12(self):
        captured = []
        with patch("retrogaze.generate._post_with_retry", _make_mock_response(captured)), \
             patch("retrogaze.generate._download_image", _make_mock_download()):
            await _pixelize(
                "https://fake/img.png", 8, 8, "fake-key",
                asset_type="tile", console="genesis",
            )

        payload = captured[0]
        # Genesis tile: max(16*2, 12) = 32 (headroom already exceeds 12)
        assert payload["max_colors"] >= 12

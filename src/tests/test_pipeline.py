"""
Tests for retrogaze.pipeline — full generation pipeline in mock mode.

All tests set RETROGAZE_MOCK=1 so no real API calls are made.
"""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path

import pytest

import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Force mock mode before importing anything from retrogaze
os.environ["RETROGAZE_MOCK"] = "1"

from retrogaze.pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(coro):
    """Run a coroutine synchronously (compatible with Python 3.10+)."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Required metadata keys
# ---------------------------------------------------------------------------

REQUIRED_METADATA_KEYS = {
    "retrogaze_version",
    "asset_type",
    "prompt",
    "dimensions",
    "palette",
    "tiles",
    "compliance",
}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestPipelineMock:
    def test_pipeline_returns_dict(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a red mushroom", output_dir=tmp))
        assert isinstance(result, dict)

    def test_pipeline_metadata_has_required_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a ghost", output_dir=tmp))
        for key in REQUIRED_METADATA_KEYS:
            assert key in result, f"Missing required metadata key: {key!r}"

    def test_pipeline_paths_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a coin", output_dir=tmp))
        assert "paths" in result
        assert "processed" in result["paths"]
        assert "raw" in result["paths"]

    def test_output_image_saved_when_output_dir_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a sword", output_dir=tmp))
            processed_path = Path(result["paths"]["processed"])
            assert processed_path.exists(), "Processed image file not found"
            assert processed_path.stat().st_size > 0, "Processed image file is empty"

    def test_raw_image_saved_when_output_dir_provided(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a shield", output_dir=tmp))
            raw_path = Path(result["paths"]["raw"])
            assert raw_path.exists()

    def test_metadata_json_saved_alongside(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a potion", output_dir=tmp))
            meta_path = Path(result["paths"]["metadata"])
            assert meta_path.exists(), "metadata.json not found"
            with open(meta_path, encoding="utf-8") as fh:
                saved = json.load(fh)
            assert "retrogaze_version" in saved

    def test_compliance_keys_present(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a dragon", output_dir=tmp))
        compliance = result["compliance"]
        assert "palette_valid" in compliance
        assert "colors_per_tile_valid" in compliance
        assert "grid_aligned" in compliance

    def test_nes_compliance_passes(self):
        """Output image should pass NES compliance checks after enforce_constraints."""
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a star", output_dir=tmp))
        compliance = result["compliance"]
        assert compliance["palette_valid"], "Output is not palette valid"
        assert compliance["colors_per_tile_valid"], "Output exceeds per-tile color limit"
        assert compliance["grid_aligned"], "Output is not grid-aligned"

    def test_asset_type_reflected_in_metadata(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a goblin", asset_type="enemy", output_dir=tmp))
        assert result["asset_type"] == "enemy"

    def test_dimensions_match_requested_size(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(
                run_pipeline("a hero", asset_type="character", size=(16, 16), output_dir=tmp)
            )
        dims = result["dimensions"]
        assert dims["width_px"] == 16
        assert dims["height_px"] == 16

    def test_pipeline_works_without_output_dir(self):
        """Pipeline should not raise even when output_dir is None."""
        result = run(run_pipeline("a bat"))
        assert isinstance(result, dict)
        assert "compliance" in result

    def test_pipeline_prompt_and_negative_prompt_returned(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(run_pipeline("a wizard", output_dir=tmp))
        assert "prompt" in result
        assert "negative_prompt" in result
        assert len(result["prompt"]) > 10

    @pytest.mark.parametrize("asset_type", ["character", "enemy", "item", "tile"])
    def test_various_asset_types_complete(self, asset_type):
        with tempfile.TemporaryDirectory() as tmp:
            result = run(
                run_pipeline("a test subject", asset_type=asset_type, output_dir=tmp)
            )
        assert isinstance(result, dict)
        assert "compliance" in result


class TestSeedParameter:
    """Seed parameter threading tests."""

    def test_pipeline_accepts_seed(self):
        """run_pipeline should accept a seed parameter without error."""
        import asyncio
        os.environ["RETROGAZE_MOCK"] = "1"
        result = asyncio.run(run_pipeline(
            description="a knight",
            asset_type="character",
            size=(16, 16),
            seed=42,
        ))
        assert result["seed"] == 42

    def test_pipeline_seed_none_by_default(self):
        """Without a seed, metadata should show seed=None."""
        import asyncio
        os.environ["RETROGAZE_MOCK"] = "1"
        result = asyncio.run(run_pipeline(
            description="a knight",
            asset_type="character",
            size=(16, 16),
        ))
        assert result["seed"] is None

    def test_mock_same_seed_same_output(self):
        """Same seed should produce identical mock images."""
        import asyncio
        os.environ["RETROGAZE_MOCK"] = "1"
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            r1 = asyncio.run(run_pipeline(
                description="a knight",
                asset_type="character",
                size=(16, 16),
                seed=12345,
                output_dir=tmp1,
            ))
            r2 = asyncio.run(run_pipeline(
                description="a knight",
                asset_type="character",
                size=(16, 16),
                seed=12345,
                output_dir=tmp2,
            ))
            # Both should produce the same processed image bytes
            from pathlib import Path
            img1 = Path(r1["paths"]["processed"]).read_bytes()
            img2 = Path(r2["paths"]["processed"]).read_bytes()
            assert img1 == img2

    def test_mock_different_seed_different_output(self):
        """Different seeds should produce different mock images."""
        import asyncio
        os.environ["RETROGAZE_MOCK"] = "1"
        with tempfile.TemporaryDirectory() as tmp1, tempfile.TemporaryDirectory() as tmp2:
            r1 = asyncio.run(run_pipeline(
                description="a knight",
                asset_type="character",
                size=(16, 16),
                seed=111,
                output_dir=tmp1,
            ))
            r2 = asyncio.run(run_pipeline(
                description="a knight",
                asset_type="character",
                size=(16, 16),
                seed=222,
                output_dir=tmp2,
            ))
            from pathlib import Path
            img1 = Path(r1["paths"]["processed"]).read_bytes()
            img2 = Path(r2["paths"]["processed"]).read_bytes()
            assert img1 != img2


class TestTilesetPipeline:
    """Tileset generation pipeline tests."""

    def test_tileset_generates_tile_metadata(self):
        import asyncio
        os.environ["RETROGAZE_MOCK"] = "1"
        result = asyncio.run(run_pipeline(
            description="stone wall",
            asset_type="tileset",
            size=(24, 24),
        ))
        assert "tileset" in result
        assert result["tileset"]["grid"] == 3
        assert result["tileset"]["tile_count"] == 9
        assert "tiles" in result["paths"]

    def test_tileset_has_all_nine_tile_names(self):
        import asyncio
        os.environ["RETROGAZE_MOCK"] = "1"
        result = asyncio.run(run_pipeline(
            description="grass terrain",
            asset_type="tileset",
            size=(24, 24),
        ))
        expected = {"top_left", "top", "top_right", "left", "center", "right",
                    "bottom_left", "bottom", "bottom_right"}
        assert set(result["tileset"]["tile_names"]) == expected

    def test_tileset_includes_seamless_report(self):
        import asyncio
        os.environ["RETROGAZE_MOCK"] = "1"
        result = asyncio.run(run_pipeline(
            description="water",
            asset_type="tileset",
            size=(24, 24),
        ))
        seamless = result["tileset"]["seamless"]
        assert "center" in seamless
        assert "seamless" in seamless["center"]

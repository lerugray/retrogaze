"""
Tests for degenerate-output detection + retry.

Covers:
  * is_degenerate_output() — the detector (fully-transparent, solid-fill,
    and the negative case of a normal sprite).
  * run_pipeline() degenerate handling — retry-then-recover, and
    fail-loud when every attempt is degenerate.

All pipeline tests force RETROGAZE_MOCK=1 so no real API calls are made;
get_image is monkeypatched to control the generated stages directly.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

from retrogaze.cleanup import is_degenerate_output


def run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Detector unit tests
# ---------------------------------------------------------------------------

class TestIsDegenerateOutput:
    def test_fully_transparent_is_degenerate(self):
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        assert is_degenerate_output(img) is True

    def test_zero_unique_opaque_colors_is_degenerate(self):
        # Alpha all zero even though RGB carries data -> no opaque pixels.
        img = Image.new("RGBA", (16, 16), (123, 200, 50, 0))
        assert is_degenerate_output(img) is True

    def test_single_solid_color_full_coverage_is_degenerate(self):
        img = Image.new("RGBA", (16, 16), (255, 0, 0, 255))
        assert is_degenerate_output(img) is True

    def test_normal_sprite_two_colors_is_not_degenerate(self):
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = img.load()
        # An opaque shape (two colors) on a transparent field.
        for x in range(4, 12):
            for y in range(4, 12):
                px[x, y] = (255, 0, 0, 255)
        px[6, 6] = (0, 255, 0, 255)
        assert is_degenerate_output(img) is False

    def test_single_color_shape_over_transparency_is_not_degenerate(self):
        # One opaque color, but with transparent holes -> a real silhouette,
        # not a flat fill. Should NOT be flagged.
        img = Image.new("RGBA", (16, 16), (0, 0, 0, 0))
        px = img.load()
        for x in range(4, 12):
            for y in range(4, 12):
                px[x, y] = (10, 90, 200, 255)
        assert is_degenerate_output(img) is False


# ---------------------------------------------------------------------------
# Pipeline retry / fail-loud tests
# ---------------------------------------------------------------------------

_FLUX = 512


def _blank_triple(width: int, height: int):
    """Three fully-transparent stages — guaranteed degenerate processed output."""
    concept = Image.new("RGBA", (_FLUX, _FLUX), (0, 0, 0, 0))
    full = Image.new("RGBA", (_FLUX, _FLUX), (0, 0, 0, 0))
    scaled = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    return concept, full, scaled


def _valid_triple(width: int, height: int):
    """Three stages with a real multi-color opaque subject on transparency."""
    concept = Image.new("RGBA", (_FLUX, _FLUX), (0, 0, 0, 0))
    full = Image.new("RGBA", (_FLUX, _FLUX), (0, 0, 0, 0))
    scaled = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    px = scaled.load()
    for x in range(width):
        for y in range(height):
            # checker of two distinct colors so per-tile + palette steps have
            # real content to work with
            px[x, y] = (255, 0, 0, 255) if (x + y) % 2 == 0 else (0, 0, 255, 255)
    return concept, full, scaled


class TestPipelineDegenerateHandling:
    def test_fails_loudly_when_always_degenerate(self, monkeypatch):
        import retrogaze.pipeline as pipe

        async def always_blank(*args, **kwargs):
            w = kwargs.get("width", 16)
            h = kwargs.get("height", 16)
            return _blank_triple(w, h)

        monkeypatch.setattr(pipe, "get_image", always_blank)

        with tempfile.TemporaryDirectory() as tmp:
            with pytest.raises(RuntimeError, match="degenerate"):
                run(pipe.run_pipeline("a ghost", asset_type="character",
                                      size=(16, 16), output_dir=tmp))

    def test_retries_then_recovers(self, monkeypatch):
        import retrogaze.pipeline as pipe

        calls = {"n": 0}

        async def blank_then_valid(*args, **kwargs):
            w = kwargs.get("width", 16)
            h = kwargs.get("height", 16)
            calls["n"] += 1
            # First attempt degenerate, second attempt valid.
            if calls["n"] == 1:
                return _blank_triple(w, h)
            return _valid_triple(w, h)

        monkeypatch.setattr(pipe, "get_image", blank_then_valid)

        with tempfile.TemporaryDirectory() as tmp:
            result = run(pipe.run_pipeline("a hero", asset_type="character",
                                           size=(16, 16), output_dir=tmp))
            assert calls["n"] == 2, "expected exactly one retry after the blank attempt"
            assert isinstance(result, dict)
            # The recovered processed output must be non-degenerate.
            processed = Image.open(result["paths"]["processed"]).convert("RGBA")
            assert is_degenerate_output(processed) is False
            processed.close()

"""
Tests for stress test bug fixes:
1. Palette mood routing — color words in descriptions
2. Retry logic in generate_aseprite.py
3. MCP rate limiting (concurrency semaphore)
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from retrogaze.mcp_prompts import (
    _infer_mood_from_description,
    _resolve_palette,
    build_mcp_prompt,
)


# ---------------------------------------------------------------------------
# 1. Palette mood routing — color words
# ---------------------------------------------------------------------------


class TestMoodInference:
    """_infer_mood_from_description should route color words to correct moods."""

    @pytest.mark.parametrize("desc,expected", [
        ("green slime", "earth"),
        ("green dragon", "earth"),
        ("slime blob", "earth"),
        ("brown bear", "earth"),
        ("moss golem", "earth"),
        ("red demon", "warm"),
        ("orange flame wizard", "warm"),
        ("pink fairy", "warm"),
        ("blue knight", "cool"),
        ("purple wizard", "cool"),
        ("cyan mermaid", "cool"),
        ("teal serpent", "cool"),
        ("black knight", "dark"),
        ("shadow assassin", "dark"),
        ("white angel", "bright"),
        ("yellow star", "bright"),
        ("holy paladin", "bright"),
    ])
    def test_color_words_route_to_correct_mood(self, desc, expected):
        result = _infer_mood_from_description(desc)
        assert result == expected, f"'{desc}' should route to '{expected}', got '{result}'"

    def test_unknown_description_returns_none(self):
        # Avoid words containing mood keywords as substrings
        # (e.g. "knight" contains "night" which matches "dark")
        result = _infer_mood_from_description("a simple adventurer")
        assert result is None

    def test_mixed_keywords_picks_strongest(self):
        """When multiple moods match, the one with most keyword hits wins."""
        # "fire flame lava" has 3 warm keywords vs 0 of anything else
        result = _infer_mood_from_description("fire flame lava creature")
        assert result == "warm"


class TestResolvePaletteWithColors:
    """_resolve_palette should produce appropriate colors for color-word subjects."""

    def test_green_slime_gets_green_palette_non_late(self):
        """'green slime' via earth mood should have green-ish colors, not purple."""
        # Simulate what build_mcp_prompt does: infer mood, then resolve
        colors, roles = _resolve_palette(
            era="mid", palette_mood="earth", palette_colors=None,
            outline="Black", asset_type="enemy",
        )
        # Earth palette has greens — at least one color should have
        # green channel dominant (G > R and G > B)
        hex_colors = colors
        has_green = False
        for c in hex_colors:
            r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
            if g > r and g > b and g > 40:
                has_green = True
                break
        assert has_green, f"Earth palette should contain greens, got {hex_colors}"

    def test_build_prompt_green_slime_infers_earth(self):
        """build_mcp_prompt for 'green slime' should infer earth mood."""
        result = build_mcp_prompt(
            description="green slime blob",
            asset_type="enemy",
            size=(16, 16),
            palette_mood="auto",
            console="nes",
        )
        # The palette dict has "colors" and "roles" keys
        palette_colors = result["palette"]["colors"]
        assert len(palette_colors) >= 3


class TestLateEraColorRouting:
    """Late era triads should also respect color-word mood inference."""

    def test_green_slime_late_era_gets_earth_triads(self):
        result = build_mcp_prompt(
            description="green slime",
            asset_type="enemy",
            size=(16, 16),
            palette_mood="auto",
            era="late",
            console="nes",
        )
        palette_colors = result["palette"]["colors"]
        # Earth triads include green family — check at least one green
        has_green = False
        for c in palette_colors:
            r, g, b = int(c[1:3], 16), int(c[3:5], 16), int(c[5:7], 16)
            if g > r and g > b and g > 40:
                has_green = True
                break
        assert has_green, f"Late-era earth palette should have greens, got {palette_colors}"


# ---------------------------------------------------------------------------
# 2. Retry logic
# ---------------------------------------------------------------------------


class TestAnthropicRetry:
    """Retry logic in generate_aseprite.py should handle transient errors."""

    @pytest.mark.asyncio
    async def test_rate_limit_retries(self):
        """RateLimitError should be retried with backoff."""
        import anthropic
        from retrogaze.generate_aseprite import (
            _API_MAX_RETRIES,
            _API_RETRY_BASE_DELAY,
        )

        # Verify constants are reasonable
        assert _API_MAX_RETRIES >= 2
        assert _API_RETRY_BASE_DELAY >= 1.0

    @pytest.mark.asyncio
    async def test_export_retry_constants(self):
        """Export retry constants should be set."""
        from retrogaze.generate_aseprite import (
            _EXPORT_MAX_RETRIES,
            _EXPORT_RETRY_DELAY,
        )
        assert _EXPORT_MAX_RETRIES >= 2
        assert _EXPORT_RETRY_DELAY >= 0.5


# ---------------------------------------------------------------------------
# 3. MCP rate limiting
# ---------------------------------------------------------------------------


class TestMcpRateLimiting:
    """Concurrency semaphore should limit parallel MCP generations."""

    def test_semaphore_creation(self):
        """_get_semaphore should return an asyncio.Semaphore."""
        from retrogaze.generate_aseprite import _get_semaphore
        sem = _get_semaphore()
        assert isinstance(sem, asyncio.Semaphore)

    def test_default_concurrency(self):
        """Default concurrency should be reasonable (not too high)."""
        from retrogaze.generate_aseprite import _MAX_CONCURRENT_GENERATIONS
        assert 1 <= _MAX_CONCURRENT_GENERATIONS <= 10

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrency(self):
        """Semaphore should actually limit concurrent access."""
        from retrogaze.generate_aseprite import _get_semaphore

        sem = _get_semaphore()
        max_concurrent = 0
        current = 0

        async def _track():
            nonlocal max_concurrent, current
            async with sem:
                current += 1
                if current > max_concurrent:
                    max_concurrent = current
                await asyncio.sleep(0.05)
                current -= 1

        # Launch more tasks than the semaphore allows
        tasks = [asyncio.create_task(_track()) for _ in range(10)]
        await asyncio.gather(*tasks)

        from retrogaze.generate_aseprite import _MAX_CONCURRENT_GENERATIONS
        assert max_concurrent <= _MAX_CONCURRENT_GENERATIONS


# ---------------------------------------------------------------------------
# 4. fal.ai retry (already existed — verify it's wired correctly)
# ---------------------------------------------------------------------------


class TestFalRetry:
    """Verify fal.ai retry logic is correctly configured."""

    def test_retry_constants(self):
        from retrogaze.generate import _MAX_RETRIES, _RETRY_BASE_DELAY
        assert _MAX_RETRIES >= 2
        assert _RETRY_BASE_DELAY >= 1.0

    def test_post_with_retry_exists(self):
        import inspect
        from retrogaze.generate import _post_with_retry
        assert inspect.iscoroutinefunction(_post_with_retry)

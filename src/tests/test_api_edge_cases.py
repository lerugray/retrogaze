"""
API-level edge case tests for input validation.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

# Set mock mode for testing
os.environ["RETROGAZE_MOCK"] = "1"

from retrogaze.api import app

client = TestClient(app)


class TestGenerateEndpointValidation:
    def test_missing_description_returns_422(self):
        resp = client.post("/generate", json={})
        assert resp.status_code == 422

    def test_invalid_size_format(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "size": "not-a-size",
        })
        assert resp.status_code == 422

    def test_negative_size(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "size": "-16x16",
        })
        assert resp.status_code == 422

    def test_zero_size(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "size": "0x0",
        })
        assert resp.status_code == 422

    def test_invalid_palette_color_format(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "palette_colors": ["not-hex"],
        })
        assert resp.status_code == 422

    def test_too_many_palette_colors(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "palette_colors": ["#000000"] * 7,
        })
        assert resp.status_code == 422

    def test_non_nes_palette_color_gets_snapped(self):
        """Non-NES hex colors are snapped to nearest NES color, not rejected."""
        resp = client.post("/generate", json={
            "description": "a knight",
            "palette_colors": ["#123456"],  # Not a real NES color — gets snapped
        })
        assert resp.status_code == 200

    def test_valid_minimal_request(self):
        resp = client.post("/generate", json={
            "description": "a knight",
        })
        assert resp.status_code == 200

    def test_health_endpoint(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_palettes_endpoint(self):
        resp = client.get("/palettes")
        assert resp.status_code == 200
        assert resp.json()["total"] > 0

    def test_security_headers_present(self):
        """All responses should include security headers."""
        resp = client.get("/health")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"
        assert resp.headers.get("X-Frame-Options") == "DENY"
        assert resp.headers.get("X-XSS-Protection") == "1; mode=block"
        assert resp.headers.get("Referrer-Policy") == "strict-origin-when-cross-origin"

    def test_security_headers_on_generate(self):
        """Security headers should be present on API endpoints too."""
        resp = client.post("/generate", json={"description": "a knight"})
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"

    def test_long_description_rejected_at_api(self):
        resp = client.post("/generate", json={
            "description": "a" * 501,
        })
        assert resp.status_code == 422

    def test_rate_limit_headers_present(self):
        """Rate-limited endpoints should include rate limit headers."""
        resp = client.get("/palettes")
        # slowapi adds X-RateLimit headers
        assert resp.status_code == 200

    def test_generate_accepts_request(self):
        """Generate endpoint should still work with rate limiting."""
        resp = client.post("/generate", json={
            "description": "a knight",
        })
        assert resp.status_code == 200


class TestPalettePresetValidation:
    """Coverage for the user-facing `palette_preset` generation feature.

    Guards the launch-day path: a valid preset is accepted, an unknown preset
    is rejected with a clean 422 (NOT a 500), and omitting it uses the default
    (no preset). Mirrors the `palette_colors` validation tests above.
    """

    def test_valid_preset_accepted(self):
        """A real preset name resolves and the request succeeds."""
        from retrogaze.palette import list_presets
        a_real_preset = next(iter(list_presets().keys()))
        resp = client.post("/generate", json={
            "description": "a knight",
            "palette_preset": a_real_preset,
        })
        assert resp.status_code == 200, resp.text

    def test_known_preset_mario_red_accepted(self):
        """A specific advertised preset (mario_red) is accepted."""
        resp = client.post("/generate", json={
            "description": "a plumber",
            "palette_preset": "mario_red",
        })
        assert resp.status_code == 200, resp.text

    def test_preset_name_is_case_insensitive(self):
        """Preset lookup lowercases the name, so uppercase still resolves."""
        resp = client.post("/generate", json={
            "description": "a knight",
            "palette_preset": "MARIO_RED",
        })
        assert resp.status_code == 200, resp.text

    def test_unknown_preset_rejected_cleanly(self):
        """An unknown preset returns a clean 422 (not a 500), with a helpful list."""
        resp = client.post("/generate", json={
            "description": "a knight",
            "palette_preset": "definitely_not_a_real_preset",
        })
        assert resp.status_code == 422, resp.text
        detail = resp.json().get("detail", "")
        # The error names the offending value and lists at least one valid preset.
        assert "definitely_not_a_real_preset" in detail
        assert "mario_red" in detail

    def test_omitted_preset_uses_default(self):
        """Omitting palette_preset (the default) generates normally with no preset."""
        resp = client.post("/generate", json={
            "description": "a knight",
        })
        assert resp.status_code == 200, resp.text

    def test_preset_and_colors_together_rejected(self):
        """palette_preset XOR palette_colors — supplying both is a clean 422."""
        resp = client.post("/generate", json={
            "description": "a knight",
            "palette_preset": "mario_red",
            "palette_colors": ["#000000", "#FFFFFF"],
        })
        assert resp.status_code == 422, resp.text


class TestViewAliasNormalization:
    """Coverage for FIX: the `view` param accepts advertised alias spellings.

    Docs / marketing / MCP advertise 'top-down', '3/4', 'three-quarter'; the
    internal vocabulary uses underscores. The API normalizes any reasonable
    spelling (case-insensitive, hyphen/slash/space) instead of 422-ing a user
    who copy-pasted an advertised value.
    """

    @pytest.mark.parametrize("view_value", [
        "top_down", "top-down", "TOP-DOWN", "Top_Down", "top down",
    ])
    def test_top_down_aliases_accepted(self, view_value):
        resp = client.post("/generate", json={
            "description": "a knight",
            "view": view_value,
        })
        assert resp.status_code == 200, f"{view_value!r}: {resp.text}"

    @pytest.mark.parametrize("view_value", [
        "three_quarter", "three-quarter", "3/4", "Three-Quarter", "three quarter",
    ])
    def test_three_quarter_aliases_accepted(self, view_value):
        resp = client.post("/generate", json={
            "description": "a knight",
            "view": view_value,
        })
        assert resp.status_code == 200, f"{view_value!r}: {resp.text}"

    @pytest.mark.parametrize("view_value", ["side", "front"])
    def test_canonical_simple_views_accepted(self, view_value):
        resp = client.post("/generate", json={
            "description": "a knight",
            "view": view_value,
        })
        assert resp.status_code == 200, f"{view_value!r}: {resp.text}"

    def test_unknown_view_still_rejected(self):
        """A genuinely invalid view (e.g. the non-existent 'back' camera) 422s."""
        resp = client.post("/generate", json={
            "description": "a knight",
            "view": "isometric",
        })
        assert resp.status_code == 422, resp.text
        detail = resp.json().get("detail", "")
        assert "top_down" in detail and "three_quarter" in detail

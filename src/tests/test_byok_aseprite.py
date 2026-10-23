"""
Aseprite-is-MCP-only + Sentry key-scrubber tests, plus bundled view-alias
normalization and palette_preset endpoint coverage.

Aseprite ("Claude draws every pixel") generation runs in the user's OWN
Claude via the Retrogaze MCP server — never server-side on the web API.
The web /generate endpoint therefore rejects generation_mode=aseprite and
no longer accepts an Anthropic key. These tests lock that contract in.
"""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from fastapi.testclient import TestClient

# Mock mode so the FLUX path returns without real image generation.
os.environ["RETROGAZE_MOCK"] = "1"

from retrogaze.api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Aseprite is MCP-only: the web /generate endpoint rejects it and never
# accepts an Anthropic key (it runs in the user's own Claude via the MCP
# server). A stray key from a cached old client stays harmless.
# ---------------------------------------------------------------------------

class TestAsepriteIsMcpOnly:
    def test_aseprite_mode_rejected_points_to_mcp(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "generation_mode": "aseprite",
            "era": "retro",
        })
        assert resp.status_code == 422, resp.text
        detail = resp.json()["detail"]
        assert "MCP" in detail
        assert "flux" in detail.lower()

    def test_generate_request_has_no_anthropic_key_field(self):
        from retrogaze.api import GenerateRequest
        assert "anthropic_key" not in GenerateRequest.model_fields

    def test_stray_anthropic_key_is_ignored_on_flux(self):
        # A cached old client may still send anthropic_key. pydantic ignores
        # the unknown field (extra=ignore), so flux generation still succeeds
        # and the value is never echoed back.
        secret = "sk-ant-api03-STRAY-FROM-CACHED-CLIENT"
        resp = client.post("/generate", json={
            "description": "a knight",
            "anthropic_key": secret,
        })
        assert resp.status_code == 200, resp.text
        assert secret not in resp.text


# ---------------------------------------------------------------------------
# Sentry key-scrubber (before_send)
# ---------------------------------------------------------------------------

class TestSentryScrubber:
    def test_scrubs_api_key_in_request_data(self):
        from retrogaze.api import _sentry_before_send
        event = {
            "request": {"data": {"anthropic_key": "sk-ant-api03-LEAKED"}},
            "message": "boom",
        }
        scrubbed = _sentry_before_send(event, {})
        assert "sk-ant-api03-LEAKED" not in str(scrubbed)
        assert scrubbed["request"]["data"]["anthropic_key"] == "[REDACTED_ANTHROPIC_KEY]"

    def test_scrubs_key_in_stack_frame_locals(self):
        from retrogaze.api import _sentry_before_send
        # Sentry captures frame locals by default — the main leak vector.
        event = {
            "exception": {
                "values": [
                    {
                        "stacktrace": {
                            "frames": [
                                {
                                    "function": "generate_aseprite_sprite",
                                    "vars": {
                                        "api_key": "sk-ant-api03-FROM-LOCALS",
                                        "other": "harmless",
                                    },
                                }
                            ]
                        }
                    }
                ]
            }
        }
        scrubbed = _sentry_before_send(event, {})
        assert "sk-ant-api03-FROM-LOCALS" not in str(scrubbed)
        frame = scrubbed["exception"]["values"][0]["stacktrace"]["frames"][0]
        assert frame["vars"]["api_key"] == "[REDACTED_ANTHROPIC_KEY]"
        assert frame["vars"]["other"] == "harmless"

    def test_scrubs_oauth_token_form(self):
        from retrogaze.api import _scrub_anthropic_keys
        out = _scrub_anthropic_keys({"t": "Bearer sk-ant-oat01-ABC_def-123"})
        assert "sk-ant-oat01-ABC_def-123" not in str(out)

    def test_leaves_non_keys_untouched(self):
        from retrogaze.api import _scrub_anthropic_keys
        out = _scrub_anthropic_keys({"msg": "no secrets here", "n": 5})
        assert out == {"msg": "no secrets here", "n": 5}


# ---------------------------------------------------------------------------
# Bundled fix A: view alias normalization (top-down, 3/4)
# ---------------------------------------------------------------------------

class TestViewAliasNormalization:
    def test_top_down_hyphen_accepted(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "view": "top-down",
        })
        assert resp.status_code == 200, resp.text

    def test_three_quarter_slash_accepted(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "view": "3/4",
        })
        assert resp.status_code == 200, resp.text

    def test_underscore_forms_still_accepted(self):
        for v in ("top_down", "three_quarter", "side", "front"):
            resp = client.post("/generate", json={
                "description": "a knight",
                "view": v,
            })
            assert resp.status_code == 200, f"{v}: {resp.text}"

    def test_unknown_view_still_422(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "view": "isometric",
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Bundled fix B: palette_preset endpoint coverage
# ---------------------------------------------------------------------------

class TestPalettePresetEndpoint:
    def test_valid_preset_accepted(self):
        resp = client.post("/generate", json={
            "description": "a hero",
            "palette_preset": "mario_red",
        })
        assert resp.status_code == 200, resp.text

    def test_preset_and_palette_colors_conflict_422(self):
        resp = client.post("/generate", json={
            "description": "a hero",
            "palette_preset": "mario_red",
            "palette_colors": ["#000000", "#F83800", "#FFFFFF"],
        })
        assert resp.status_code == 422
        assert "palette_preset OR palette_colors" in resp.json()["detail"]

    def test_unknown_preset_422(self):
        resp = client.post("/generate", json={
            "description": "a hero",
            "palette_preset": "not_a_real_preset_xyz",
        })
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Consoles with a palette profile but no generation prompt data (e.g.
# c64_multicolor) must be rejected with a clean 422, not a 500.
# ---------------------------------------------------------------------------

class TestUnsupportedConsole:
    def test_c64_multicolor_rejected_422_not_500(self):
        resp = client.post("/generate", json={
            "description": "a knight",
            "console": "c64_multicolor",
            "era": "retro",
        })
        assert resp.status_code == 422, resp.text
        assert "c64_multicolor" in resp.json()["detail"]

    def test_supported_console_still_generates(self):
        # Regression: a generation-supported console still passes validation.
        resp = client.post("/generate", json={
            "description": "a knight",
            "console": "c64",
            "era": "retro",
        })
        assert resp.status_code == 200, resp.text

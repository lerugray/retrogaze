"""
Tests for MCP Server Product API endpoints (/mcp/*).

All tests run in RETROGAZE_MOCK=1 mode. MCP auth returns a studio-tier
mock user, so all tier-gated features are accessible for testing.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

import ast
import base64
import json
from pathlib import Path
import re
import pytest
from fastapi.testclient import TestClient
from retrogaze.api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# POST /mcp/prompt
# ---------------------------------------------------------------------------

class TestMcpPrompt:
    def test_prompt_default_response_legacy_shape_unchanged(self):
        """Omitting tool_format preserves the pre-tool-schema response exactly."""
        from retrogaze.mcp_prompts import build_mcp_prompt

        body = {"description": "compatibility sentinel", "seed": 173}
        resp = client.post("/mcp/prompt", json=body)
        assert resp.status_code == 200

        expected = build_mcp_prompt(description=body["description"], seed=body["seed"])
        expected["remaining_calls"] = None
        assert resp.json() == expected
        assert "tools" not in resp.json()

    def test_basic_prompt_request(self):
        resp = client.post("/mcp/prompt", json={"description": "a warrior"})
        assert resp.status_code == 200
        data = resp.json()
        assert "system_prompt" in data
        assert "user_prompt" in data
        assert "canvas" in data
        assert "palette" in data
        assert "constraints" in data
        assert "tool_whitelist" in data
        assert "tool_blacklist" in data

    def test_prompt_returns_string_prompts(self):
        resp = client.post("/mcp/prompt", json={"description": "a dragon"})
        data = resp.json()
        assert isinstance(data["system_prompt"], str)
        assert isinstance(data["user_prompt"], str)
        assert len(data["system_prompt"]) > 100  # should be substantial

    def test_prompt_canvas_spec(self):
        resp = client.post("/mcp/prompt", json={
            "description": "a knight",
            "size": "16x16",
        })
        data = resp.json()
        assert data["canvas"]["width"] == 16
        assert data["canvas"]["height"] == 16
        assert data["canvas"]["color_mode"] == "rgb"

    def test_prompt_custom_size(self):
        resp = client.post("/mcp/prompt", json={
            "description": "a tile",
            "size": "8x8",
            "asset_type": "tile",
            "era": "retro",
        })
        data = resp.json()
        assert data["canvas"]["width"] == 8
        assert data["canvas"]["height"] == 8

    def test_prompt_palette_has_colors_and_roles(self):
        resp = client.post("/mcp/prompt", json={"description": "a slime"})
        data = resp.json()
        palette = data["palette"]
        assert "colors" in palette
        assert "roles" in palette
        assert isinstance(palette["colors"], list)
        assert len(palette["colors"]) > 0

    def test_prompt_tool_whitelist_non_empty(self):
        resp = client.post("/mcp/prompt", json={"description": "a potion"})
        data = resp.json()
        assert len(data["tool_whitelist"]) > 0

    def test_prompt_openai_tools_match_anthropic_tools(self):
        body = {"description": "a potion", "seed": 211}
        anthropic = client.post(
            "/mcp/prompt",
            json={**body, "tool_format": "anthropic"},
        )
        openai = client.post(
            "/mcp/prompt",
            json={**body, "tool_format": "openai"},
        )

        assert anthropic.status_code == 200
        assert openai.status_code == 200
        anthropic_tools = anthropic.json()["tools"]
        openai_tools = openai.json()["tools"]

        assert [tool["name"] for tool in anthropic_tools] == [
            tool["function"]["name"] for tool in openai_tools
        ]
        for anthropic_tool, openai_tool in zip(anthropic_tools, openai_tools):
            assert set(anthropic_tool) == {"name", "description", "input_schema"}
            assert openai_tool == {
                "type": "function",
                "function": {
                    "name": anthropic_tool["name"],
                    "description": anthropic_tool["description"],
                    "parameters": anthropic_tool["input_schema"],
                },
            }

    def test_prompt_unknown_tool_format_lists_supported_values(self):
        resp = client.post(
            "/mcp/prompt",
            json={"description": "test", "tool_format": "gemini"},
        )

        assert resp.status_code == 422
        detail = json.dumps(resp.json()["detail"])
        assert "anthropic" in detail
        assert "openai" in detail

    def test_prompt_all_eras(self):
        """All 4 eras should work (mock user has studio tier)."""
        for era in ("retro", "early", "mid", "late"):
            resp = client.post("/mcp/prompt", json={
                "description": "a test sprite",
                "era": era,
            })
            assert resp.status_code == 200, f"Era {era} failed: {resp.text}"

    def test_prompt_all_asset_types(self):
        for asset_type in ("character", "enemy", "item", "tile"):
            resp = client.post("/mcp/prompt", json={
                "description": "test",
                "asset_type": asset_type,
            })
            assert resp.status_code == 200, f"Asset type {asset_type} failed"

    def test_prompt_with_palette_colors(self):
        resp = client.post("/mcp/prompt", json={
            "description": "a hero",
            "palette_colors": ["#FF0000", "#00FF00", "#0000FF"],
        })
        assert resp.status_code == 200
        data = resp.json()
        # Colors should be snapped to nearest NES colors
        assert len(data["palette"]["colors"]) >= 3

    def test_prompt_invalid_size_format(self):
        resp = client.post("/mcp/prompt", json={
            "description": "test",
            "size": "big",
        })
        assert resp.status_code == 422

    def test_prompt_size_out_of_range(self):
        resp = client.post("/mcp/prompt", json={
            "description": "test",
            "size": "512x512",
        })
        assert resp.status_code == 422

    def test_prompt_description_required(self):
        resp = client.post("/mcp/prompt", json={})
        assert resp.status_code == 422

    def test_prompt_description_max_length(self):
        resp = client.post("/mcp/prompt", json={
            "description": "x" * 501,
        })
        assert resp.status_code == 422

    def test_prompt_invalid_hex_color(self):
        resp = client.post("/mcp/prompt", json={
            "description": "test",
            "palette_colors": ["not-a-color"],
        })
        assert resp.status_code == 422

    def test_prompt_remaining_calls_in_response(self):
        resp = client.post("/mcp/prompt", json={"description": "test"})
        data = resp.json()
        # Mock user has unlimited (studio tier)
        assert "remaining_calls" in data


def test_openai_tool_converter_has_one_library_definition():
    repo_root = Path(__file__).resolve().parents[2]
    definition_pattern = re.compile(r"^def _openai_tools\(", re.MULTILINE)
    definitions = [
        path.relative_to(repo_root).as_posix()
        for path in repo_root.rglob("*.py")
        if definition_pattern.search(path.read_text())
    ]

    assert definitions == ["src/retrogaze/generate_aseprite.py"]

    experiment_path = repo_root / "scripts/experiments/e6b_mcp_aseprite.py"
    if not experiment_path.exists():
        return  # internal experiment tree is not part of the public checkout
    experiment_tree = ast.parse(experiment_path.read_text())
    assert any(
        isinstance(node, ast.ImportFrom)
        and node.module == "retrogaze.generate_aseprite"
        and any(alias.name == "_openai_tools" for alias in node.names)
        for node in experiment_tree.body
    )


# ---------------------------------------------------------------------------
# POST /mcp/validate
# ---------------------------------------------------------------------------

def _make_test_png() -> str:
    """Create a minimal 8x8 red PNG and return as base64."""
    from PIL import Image
    import io
    img = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


class TestMcpValidate:
    def test_basic_validate(self):
        resp = client.post("/mcp/validate", json={
            "image_base64": _make_test_png(),
        })
        assert resp.status_code == 200
        data = resp.json()
        assert "compliant" in data
        assert "metadata" in data
        assert isinstance(data["compliant"], bool)

    def test_validate_returns_compliance_fields(self):
        resp = client.post("/mcp/validate", json={
            "image_base64": _make_test_png(),
        })
        data = resp.json()
        metadata = data["metadata"]
        assert "compliance" in metadata
        compliance = metadata["compliance"]
        assert "palette_valid" in compliance
        assert "colors_per_tile_valid" in compliance
        assert "grid_aligned" in compliance

    def test_validate_with_fix(self):
        resp = client.post("/mcp/validate", json={
            "image_base64": _make_test_png(),
            "fix": True,
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["fixed_image_base64"] is not None
        # Should be valid base64
        decoded = base64.b64decode(data["fixed_image_base64"])
        assert len(decoded) > 0

    def test_validate_without_fix_no_image(self):
        resp = client.post("/mcp/validate", json={
            "image_base64": _make_test_png(),
            "fix": False,
        })
        data = resp.json()
        assert data["fixed_image_base64"] is None

    def test_validate_with_target_size(self):
        resp = client.post("/mcp/validate", json={
            "image_base64": _make_test_png(),
            "target_size": "16x16",
        })
        assert resp.status_code == 200

    def test_validate_invalid_base64(self):
        resp = client.post("/mcp/validate", json={
            "image_base64": "not-valid-base64!!!",
        })
        assert resp.status_code == 422

    def test_validate_image_required(self):
        resp = client.post("/mcp/validate", json={})
        assert resp.status_code == 422

    def test_validate_invalid_target_size(self):
        resp = client.post("/mcp/validate", json={
            "image_base64": _make_test_png(),
            "target_size": "nope",
        })
        assert resp.status_code == 422

    def test_validate_valid_base64_not_an_image(self):
        """Well-formed base64 that decodes to non-image bytes must reject
        cleanly with a 4xx + JSON body, not a raw 500.

        'dGVzdA==' is valid base64 (decodes to b'test'), so it passes the
        base64 check but is not a parseable image. Regression test for the
        UnidentifiedImageError -> 500 bug.
        """
        resp = client.post("/mcp/validate", json={
            "image_base64": "dGVzdA==",
        })
        assert resp.status_code == 422
        assert "detail" in resp.json()

    def test_validate_remaining_calls(self):
        resp = client.post("/mcp/validate", json={
            "image_base64": _make_test_png(),
        })
        data = resp.json()
        assert "remaining_calls" in data


# ---------------------------------------------------------------------------
# GET /mcp/palettes
# ---------------------------------------------------------------------------

class TestMcpPalettes:
    def test_palettes_no_auth_required(self):
        resp = client.get("/mcp/palettes")
        assert resp.status_code == 200

    def test_palettes_has_nes_palette(self):
        data = client.get("/mcp/palettes").json()
        assert "nes_palette" in data
        assert len(data["nes_palette"]) > 50  # 56 NES colors

    def test_palettes_has_presets(self):
        data = client.get("/mcp/palettes").json()
        assert "presets" in data
        assert "mario_red" in data["presets"]
        assert "megaman_blue" in data["presets"]

    def test_palettes_has_moods(self):
        data = client.get("/mcp/palettes").json()
        assert "moods" in data
        assert "warm" in data["moods"]
        assert "cool" in data["moods"]

    def test_palette_colors_are_hex(self):
        data = client.get("/mcp/palettes").json()
        for color in data["nes_palette"]:
            assert color.startswith("#"), f"Color {color} not hex"
            assert len(color) == 7, f"Color {color} wrong length"


# ---------------------------------------------------------------------------
# GET /mcp/status
# ---------------------------------------------------------------------------

class TestMcpStatus:
    def test_status_returns_tier(self):
        resp = client.get("/mcp/status")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "studio"  # mock mode

    def test_status_has_usage_fields(self):
        data = client.get("/mcp/status").json()
        assert "monthly_used" in data
        assert "monthly_limit" in data
        assert "remaining_calls" in data

    def test_status_has_available_eras(self):
        data = client.get("/mcp/status").json()
        assert "available_eras" in data
        # Studio tier gets all eras
        assert set(data["available_eras"]) == {"early", "late", "mid", "retro"}

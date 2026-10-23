"""Open-source release: open MCP access + RETROGAZE_DEMO profile."""

from __future__ import annotations

import base64
import importlib
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image


REPO_ROOT = Path(__file__).resolve().parents[2]
SRC = REPO_ROOT / "src"


def _png_b64() -> str:
    img = Image.new("RGBA", (8, 8), (255, 0, 0, 255))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture()
def mock_client(monkeypatch):
    monkeypatch.setenv("RETROGAZE_MOCK", "1")
    monkeypatch.delenv("RETROGAZE_DEMO", raising=False)
    # Ensure a clean import isn't required — app already imported by other tests.
    from fastapi.testclient import TestClient
    from retrogaze.api import app

    return TestClient(app)


class TestOpenAccess:
    def test_all_eras_open(self, mock_client):
        for era in ("retro", "early", "mid", "late"):
            resp = mock_client.post(
                "/mcp/prompt",
                json={"description": "a test sprite", "era": era},
            )
            assert resp.status_code == 200, era

    def test_fix_open_to_everyone(self, mock_client):
        resp = mock_client.post(
            "/mcp/validate",
            json={"image_base64": _png_b64(), "fix": True},
        )
        assert resp.status_code == 200
        assert resp.json().get("fixed_image_base64")

    def test_status_lists_all_eras(self, mock_client):
        data = mock_client.get("/mcp/status").json()
        assert set(data["available_eras"]) == {"early", "late", "mid", "retro"}


class TestDemoProfile:
    def test_demo_without_safety_refuses_to_import(self):
        env = os.environ.copy()
        env["RETROGAZE_DEMO"] = "1"
        env.pop("RETROGAZE_SAFETY_CHECKER", None)
        env["RETROGAZE_MOCK"] = "1"
        env["PYTHONPATH"] = str(SRC) + os.pathsep + env.get("PYTHONPATH", "")
        proc = subprocess.run(
            [
                sys.executable,
                "-c",
                "import retrogaze.api",
            ],
            cwd=str(SRC),
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode != 0
        assert "RETROGAZE_SAFETY_CHECKER" in (proc.stderr + proc.stdout)

    def test_demo_forces_single_candidate_and_blocks_reference(self, monkeypatch):
        monkeypatch.setenv("RETROGAZE_MOCK", "1")
        monkeypatch.setenv("RETROGAZE_DEMO", "1")
        monkeypatch.setenv("RETROGAZE_SAFETY_CHECKER", "1")
        # Re-import api in a subprocess so module-level demo guard runs cleanly
        env = os.environ.copy()
        env.update(
            {
                "RETROGAZE_MOCK": "1",
                "RETROGAZE_DEMO": "1",
                "RETROGAZE_SAFETY_CHECKER": "1",
                "PYTHONPATH": str(SRC) + os.pathsep + env.get("PYTHONPATH", ""),
            }
        )
        code = r"""
import base64, io
from PIL import Image
from fastapi.testclient import TestClient
from retrogaze import api
assert api._DEMO is True
client = TestClient(api.app)
img = Image.new("RGBA", (8, 8), (0, 255, 0, 255))
buf = io.BytesIO(); img.save(buf, format="PNG")
b64 = base64.b64encode(buf.getvalue()).decode()
resp = client.post("/generate", json={
    "description": "a slime",
    "num_candidates": 3,
    "reference_image": b64,
})
assert resp.status_code == 422, resp.text
assert "Reference image" in resp.json()["detail"]
print("OK")
"""
        proc = subprocess.run(
            [sys.executable, "-c", code],
            cwd=str(SRC),
            env=env,
            capture_output=True,
            text=True,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "OK" in proc.stdout

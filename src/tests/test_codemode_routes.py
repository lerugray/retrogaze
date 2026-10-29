"""M1-22: the /code API. Off by default, refused on the demo, never strips provenance, not in /v1."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["RETROGAZE_MOCK"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from retrogaze.api import V1_ALLOWED_PAIRS, app  # noqa: E402

from ._codemode import EXAMPLES  # noqa: E402

client = TestClient(app)
HERO = {"files": {"nes_hero.px.js": (EXAMPLES / "nes_hero.px.js").read_text()}, "entry": "nes_hero.px.js"}


def test_off_unless_enabled(monkeypatch):
    monkeypatch.delenv("RETROGAZE_CODE_MODE", raising=False)
    assert client.post("/code/build", json=HERO).status_code == 404
    assert client.get("/code/binding").status_code == 404


def test_refused_on_the_demo(monkeypatch):
    monkeypatch.setenv("RETROGAZE_CODE_MODE", "1")
    monkeypatch.setenv("RETROGAZE_DEMO", "1")
    r = client.post("/code/build", json=HERO)
    assert r.status_code == 403 and "public demo" in r.json()["detail"]


def test_build_endpoint(monkeypatch):
    monkeypatch.setenv("RETROGAZE_CODE_MODE", "1")
    monkeypatch.delenv("RETROGAZE_DEMO", raising=False)
    r = client.post("/code/build", json={**HERO, "author": "llm"})
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["exit_code"] == 0 and data["verdict"] == "legal"
    prov = data["provenance"]
    assert prov["mode"] == "code" and prov["ai_image_model"] is None and prov["source_author"] == "llm"
    assert "nes/title.chr" in data["outputs"]
    # The same payload verifies.
    v = client.post("/code/verify", json={"files": HERO["files"], "manifest": data["manifest"],
                                          "outputs": data["outputs"]})
    assert v.status_code == 200 and v.json()["exit_code"] == 0, v.json()


def test_build_endpoint_rejects_raster_and_bad_console(monkeypatch):
    monkeypatch.setenv("RETROGAZE_CODE_MODE", "1")
    monkeypatch.delenv("RETROGAZE_DEMO", raising=False)
    r = client.post("/code/build", json={"files": {"a.png": "x"}, "entry": "a.png"})
    assert r.status_code == 200 and r.json()["exit_code"] == 3
    assert r.json()["report"]["errors"][0]["code"] == "CM-INPUT"
    assert client.post("/code/build", json={**HERO, "console": "genesis"}).status_code == 422


def test_binding_endpoint(monkeypatch):
    monkeypatch.setenv("RETROGAZE_CODE_MODE", "1")
    monkeypatch.delenv("RETROGAZE_DEMO", raising=False)
    r = client.get("/code/binding?console=nes&tier=legal")
    assert r.status_code == 200 and "| NES-H1 |" in r.json()["cheatsheet"]


def test_no_v1_alias():
    assert not any(path.startswith("/code") for _, path in V1_ALLOWED_PAIRS)
    assert client.post("/v1/code/build", json=HERO).status_code == 404

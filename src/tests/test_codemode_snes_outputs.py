"""M2 end to end: CLI, API, provenance, determinism, sheets and the profile for --console snes (§4.4, §1.4)."""

import json
import os
import shutil
import subprocess
import sys

import jsonschema
from fastapi.testclient import TestClient

from retrogaze.codemode.binding import SNES_LIMITS
from retrogaze.codemode.build import MANIFEST, audit, build, build_path, verify
from retrogaze.codemode.provenance import read_png_provenance, schema
from retrogaze.codemode.runner import read_art_dir
from retrogaze.console_profile import SNES_MODE1
from retrogaze.export_formats import build_gamemaker_yy, build_godot_tres, build_unity_anim, build_unreal_sprite

from ._codemode_snes import EXAMPLES, FIXTURES, REPO, build_file, expectations

PROOF = EXAMPLES / "snes_proof.px.js"


def cli(*args):
    return subprocess.run([sys.executable, "-m", "retrogaze.codemode", *map(str, args)], cwd=REPO / "src",
                          capture_output=True, text=True, timeout=180)


def test_cli_build_verify_audit(tmp_path):
    shutil.copy(PROOF, tmp_path / PROOF.name)
    shutil.copy(FIXTURES / "snes_H10_fail.px.js", tmp_path / "too_many.px.js")
    ok = cli("build", tmp_path / PROOF.name, "--console", "snes", "--tier", "legal")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "verdict: legal" in ok.stdout and "OBSEL" in ok.stdout
    out = tmp_path / "out" / "snes" / "legal"
    for f in ("proof.bg1.4bpp", "proof.bg1.map", "proof.obj.4bpp", "proof.cgram", "proof.oam", "proof.vram.json",
              "proof.s", "proof.h", "proof.ref.png"):
        assert (out / "snes" / f).is_file(), f
    assert len((out / "snes" / "proof.cgram").read_bytes()) == 512
    assert len((out / "snes" / "proof.oam").read_bytes()) == 544
    assert len((out / "snes" / "proof.bg1.map").read_bytes()) == 2048
    assert any((out / "snes" / "pal").iterdir())
    v = cli("verify", out)
    assert v.returncode == 0 and "verified" in v.stdout
    assert cli("audit", out).returncode == 0
    bad = cli("build", tmp_path / "too_many.px.js", "--console", "snes")
    (line, _), = expectations(FIXTURES / "snes_H10_fail.px.js")
    assert bad.returncode == 1 and "SNES-H10" in bad.stdout and f"too_many.px.js:{line}" in bad.stdout
    like = cli("build", tmp_path / "too_many.px.js", "--console", "snes", "--tier", "like")
    assert like.returncode == 0 and "verdict: like" in like.stdout
    b = cli("bind", "--console", "snes")
    assert b.returncode == 0 and "| SNES-H11 |" in b.stdout and "snes(r5, g5, b5)" in b.stdout


def test_snes_provenance_and_audit(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    shutil.copy(PROOF, art / PROOF.name)
    r = build_path(art / PROOF.name, console="snes", author="llm")
    assert r.exit_code == 0
    out = r.out_dir
    prov_schema = schema("provenance-1.json")
    for p in sorted(out.rglob("*.png")):
        prov = read_png_provenance(p)
        jsonschema.validate(prov, prov_schema)
        assert prov["console"] == "snes" and prov["verdict"] == "legal" and prov["source_author"] == "llm"
    man = json.loads((out / MANIFEST).read_text())
    listed = set(man["outputs"])
    assert listed == {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} - {MANIFEST}
    jsonschema.validate(json.loads((out / "report.json").read_text()), schema("report-1.json"))
    assert verify(out)[0] == 0
    assert audit(out)[0] == 0
    cg = out / "snes" / "proof.bg1.4bpp"
    data = cg.read_bytes()
    cg.write_bytes(bytes([data[0] ^ 0xFF]) + data[1:])
    code, msgs = audit(out)
    assert code == 1 and any(cg.name in m and "changed" in m for m in msgs)
    assert verify(out)[0] == 1


def test_snes_rebuild_is_byte_identical():
    files, entry = read_art_dir(PROOF)
    a = build(files, entry, console="snes")
    b = build(files, entry, console="snes")
    assert a.verdict == b.verdict == "legal"
    assert a.outputs == b.outputs
    assert a.manifest["outputs"] == b.manifest["outputs"]


def test_snes_sheet_feeds_the_engine_exporters():
    r = build_file(str(PROOF))
    sheets = [json.loads(v) for k, v in r.outputs.items() if k.startswith("sheets/") and k.endswith(".json")]
    assert sheets
    for atlas in sheets:
        assert all("duration" in f for f in atlas["frames"].values())
        meta = atlas["meta"]["retrogaze"]
        assert meta["console"] == "snes" and meta["provenance"]["mode"] == "code"
        assert "Texture" in build_godot_tres(atlas)
        assert build_unity_anim(atlas) and build_gamemaker_yy(atlas) and build_unreal_sprite(atlas)
    cells = sheets[0]["meta"]["retrogaze"]["hardware"]["hero"]
    assert cells and set(cells[0]) == {"x", "y", "w", "h", "tile", "palette", "flip"}


def test_snes_api(monkeypatch):
    monkeypatch.setenv("RETROGAZE_MOCK", "1")
    monkeypatch.setenv("RETROGAZE_CODE_MODE", "1")
    monkeypatch.delenv("RETROGAZE_DEMO", raising=False)
    from retrogaze.api import app
    client = TestClient(app)
    body = {"files": {PROOF.name: PROOF.read_text()}, "entry": PROOF.name, "console": "snes", "author": "llm"}
    res = client.post("/code/build", json=body)
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["verdict"] == "legal" and data["provenance"]["console"] == "snes"
    assert "snes/proof.cgram" in data["outputs"]
    v = client.post("/code/verify", json={"files": body["files"], "manifest": data["manifest"], "outputs": data["outputs"]})
    assert v.status_code == 200 and v.json()["exit_code"] == 0, v.json()
    bind = client.get("/code/binding?console=snes&tier=legal")
    assert bind.status_code == 200 and "| SNES-H1 |" in bind.json()["cheatsheet"]
    assert os.environ["RETROGAZE_CODE_MODE"] == "1"


def test_snes_limits_agree_with_the_profile():
    """Where code mode and ConsoleProfile overlap they agree; the known differences are listed in
    test_codemode_hw_consistency.KNOWN_PROFILE_DIFFS (15 vs 16 colors per tile, 272 vs 256 px per line)."""
    assert SNES_LIMITS["oam"] == SNES_MODE1.max_sprites == 128
    assert SNES_LIMITS["perLine"] == SNES_MODE1.max_sprites_per_scanline == 32
    assert SNES_LIMITS["bgPalettes"] == SNES_MODE1.bg_palettes == 8
    assert SNES_LIMITS["objPalettes"] == SNES_MODE1.sprite_palettes == 8
    assert (SNES_LIMITS["screenW"], SNES_LIMITS["screenH"]) == SNES_MODE1.resolution
    assert SNES_LIMITS["colorsPerPalette"] == SNES_MODE1.colors_per_palette - 1 == 15
    assert SNES_LIMITS["slivers"] * 8 == 272 != SNES_MODE1.max_sprite_pixels_per_scanline
    assert SNES_MODE1.tile_size == 8 and SNES_MODE1.color_depth_bits == 15

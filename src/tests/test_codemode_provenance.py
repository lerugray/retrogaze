"""M1-18..20: every output says it is code-drawn; verify proves it; audit gates a game's asset folder."""

import importlib
import json
import shutil

import jsonschema
import numpy as np
import pytest
from PIL import Image

from retrogaze.codemode.build import MANIFEST, audit, build_path, verify
from retrogaze.codemode.provenance import CHUNK, DIGITAL_SOURCE_TYPE, read_png_provenance, schema

from ._codemode import EXAMPLES, REPO


@pytest.fixture()
def built(tmp_path):
    art = tmp_path / "art"
    art.mkdir()
    shutil.copy(EXAMPLES / "nes_hero.px.js", art / "nes_hero.px.js")
    r = build_path(art / "nes_hero.px.js", author="llm")
    assert r.exit_code == 0
    return art, r.out_dir


def test_embedded_provenance(built):
    art, out = built
    prov_schema = schema("provenance-1.json")
    pngs = sorted(out.rglob("*.png"))
    assert len(pngs) >= 6
    for p in pngs:
        prov = read_png_provenance(p)
        jsonschema.validate(prov, prov_schema)
        assert prov["source_author"] == "llm" and prov["verdict"] == "legal"
        with Image.open(p) as im:
            assert DIGITAL_SOURCE_TYPE in im.text["XML:com.adobe.xmp"]
            assert CHUNK in im.text
    sheet = json.loads((out / "sheets" / "chars.json").read_text())
    jsonschema.validate(sheet["meta"]["retrogaze"]["provenance"], prov_schema)
    man = json.loads((out / MANIFEST).read_text())
    jsonschema.validate(man["provenance"], prov_schema)
    listed = set(man["outputs"])
    on_disk = {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()} - {MANIFEST}
    assert listed == on_disk
    jsonschema.validate(json.loads((out / "report.json").read_text()), schema("report-1.json"))


def test_verify(built, monkeypatch):
    art, out = built
    assert verify(out)[0] == 0

    png = out / "png" / "hero.png"
    original = png.read_bytes()
    img = np.array(Image.open(png).convert("RGBA"))
    img[5, 5] = [255, 0, 0, 255]
    Image.fromarray(img).save(png)
    code, msgs = verify(out)
    assert code == 1 and any("png/hero.png" in m for m in msgs)
    png.write_bytes(original)
    assert verify(out)[0] == 0

    src = art / "nes_hero.px.js"
    text = src.read_text()
    src.write_text(text.replace('objSize: "8x8"', 'objSize: "8x8" '))
    code, msgs = verify(out)
    assert code == 1 and any("source changed" in m for m in msgs)
    src.write_text(text)

    build_mod = importlib.import_module("retrogaze.codemode.build")   # the module, not the build() function
    monkeypatch.setattr(build_mod, "binding_sha256", lambda b: "0" * 64)
    code, msgs = verify(out)
    assert code == 4 and "binding" in msgs[0]


def test_audit(built, tmp_path):
    art, out = built
    assert audit(out)[0] == 0
    game = tmp_path / "game_assets"
    shutil.copytree(out, game / "code")
    shutil.copy(REPO / "test_sprites" / "final_validation" / "early_coin.png", game / "flux_coin.png")
    code, msgs = audit(game)
    assert code == 1
    assert any("flux_coin.png" in m and "no code-mode provenance" in m for m in msgs)
    (game / "flux_coin.png").unlink()
    assert audit(game)[0] == 0
    chr_file = game / "code" / "nes" / "title.chr"
    data = chr_file.read_bytes()
    chr_file.write_bytes(bytes([data[0] ^ 0xFF]) + data[1:])
    code, msgs = audit(game)
    assert code == 1 and any("title.chr" in m and "changed" in m for m in msgs)

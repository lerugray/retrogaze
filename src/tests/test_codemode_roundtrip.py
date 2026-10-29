"""M1-16..17: rules, encoder + reference PPU, and the existing engine agree about legality."""

import io
import tempfile
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from retrogaze.codemode import ppu_ref
from retrogaze.codemode.encode.nes import EncodeError, encode_scene
from retrogaze.enforce import enforce_constraints
from retrogaze.metadata import generate_metadata

from ._codemode import EXAMPLES, FIXTURES, build_file

LEGAL = sorted(FIXTURES.glob("nes_*_pass.px.js")) + [FIXTURES / "nes_H4_info.px.js"] + sorted(EXAMPLES.glob("*.px.js"))
# Fail fixtures whose violation is a byte the console cannot hold: the encoder must refuse with that rule.
ENCODABLE = ["H2", "H3", "H6", "H7", "H8", "H11", "H12", "H13"]


@pytest.mark.parametrize("path", LEGAL, ids=lambda p: p.stem)
def test_nes_reference_render_matches(path):
    r = build_file(str(path))
    assert r.verdict == "legal"
    for m in r.models:
        assert m.legal
        b = encode_scene(m)
        for s in range(m.states):
            got = ppu_ref.render(b.chr[m.chr_index(s)], b.pal, b.nam[s], b.oam[s], b.rom)
            want = m.composites[s].copy()
            if not m.left8:
                want[:, :8, :3] = [(m.backdrop >> 16) & 255, (m.backdrop >> 8) & 255, m.backdrop & 255]
            assert np.array_equal(got, want), (m.name, s)


@pytest.mark.parametrize("rule", ENCODABLE)
def test_encoder_refuses_with_the_validators_rule(rule):
    r = build_file(str(FIXTURES / f"nes_{rule}_fail.px.js"))
    bad = [m for m in r.models if m.checked and not m.legal]
    assert bad
    with pytest.raises(EncodeError) as e:
        encode_scene(bad[0])
    assert e.value.rule == f"NES-{rule}"


def test_runtime_limit_scene_still_encodes():
    """NES-H9 is a runtime limit: the bytes exist, the PPU drops sprites. The reference PPU shows the drop."""
    r = build_file(str(FIXTURES / "nes_H9_fail.px.js"))
    m = r.models[0]
    b = encode_scene(m)
    got = ppu_ref.render(b.chr[0], b.pal, b.nam[0], b.oam[0], b.rom)
    diff = np.argwhere((got != m.composites[0]).any(axis=2))
    dropped = m.oam[0][8]
    assert len(diff) == 64
    assert set(map(tuple, diff)) == {(y, x) for y in range(dropped.top, dropped.top + 8)
                                     for x in range(dropped.x, dropped.x + 8)}


def single_palette_obj(r, asset):
    pals = {c.palette for m in r.models for s in m.oam for c in s if c.asset == asset}
    return len(pals) <= 1


@pytest.mark.parametrize("path", LEGAL, ids=lambda p: p.stem)
def test_existing_engine_agrees_nes(path):
    r = build_file(str(path))
    roles = {a["name"]: a["role"] for a in r.report["assets"]}
    for key, data in r.outputs.items():
        if not key.startswith("png/") or key.endswith(".idx.png") or ".screen" in key:
            continue
        asset = key[4:-4].rsplit("_", 1)[0] if key[4:-4] not in roles else key[4:-4]
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        comp = generate_metadata(img, asset_type="sprite", console="nes")["compliance"]
        assert comp["palette_valid"] and comp["colors_per_tile_valid"] and comp["grid_aligned"], key
        if roles.get(asset) == "bg" or single_palette_obj(r, asset):
            with tempfile.TemporaryDirectory() as tmp:
                src, out = Path(tmp) / "in.png", Path(tmp) / "out.png"
                img.save(src)
                enforce_constraints(src, console="nes", output_path=out)
                assert np.array_equal(np.array(Image.open(out).convert("RGBA")), np.array(img)), key

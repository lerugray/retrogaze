"""M2-11..12: SNES rules, encoder + reference PPU, and the existing engine agree about legality.
(Spec file name: test_codemode_roundtrip.py; kept in a new file so the M1 test files stay byte-identical.)"""

import io

import numpy as np
import pytest
from PIL import Image

from retrogaze.codemode import ppu_ref_snes
from retrogaze.codemode.encode.snes import EncodeError, encode_scene
from retrogaze.metadata import generate_metadata

from ._codemode_snes import EXAMPLES, FIXTURES, build_file

LEGAL = sorted(FIXTURES.glob("snes_*_pass.px.js")) + sorted(EXAMPLES.glob("*.px.js"))
# Fail fixtures whose violation no bytes can hold: the encoder must refuse with the validator's rule.
ENCODABLE = ["H1", "H2", "H3", "H4", "H5", "H6", "H7", "H8", "H9", "H12", "H13", "H14", "H15"]


def render(b, s):
    return ppu_ref_snes.render(b.vram(s), b.cgram, b.oam[s], b.registers)


@pytest.mark.parametrize("path", LEGAL, ids=lambda p: p.stem)
def test_snes_reference_render_matches(path):
    r = build_file(str(path))
    assert r.verdict == "legal", r.report
    assert r.models
    for m in r.models:
        assert m.legal
        b = encode_scene(m)
        for s in range(m.states):
            got = render(b, s)
            assert got.shape == (224, 256, 4)
            assert np.array_equal(got, m.composites[s]), (m.name, s, np.argwhere((got != m.composites[s]).any(axis=2))[:5])


@pytest.mark.parametrize("rule", ENCODABLE)
def test_encoder_refuses_with_the_validators_rule(rule):
    r = build_file(str(FIXTURES / f"snes_{rule}_fail.px.js"))
    bad = [m for m in r.models if m.checked and not m.legal]
    assert bad
    with pytest.raises(EncodeError) as e:
        encode_scene(bad[0])
    assert e.value.rule == f"SNES-{rule}"


@pytest.mark.parametrize("rule, dropped", [("H10", "range"), ("H11", "time")])
def test_runtime_limit_scenes_still_encode(rule, dropped):
    """SNES-H10/H11 are runtime limits: the bytes exist and the PPU drops OBJs or slivers. The reference PPU
    differs from the art only on the pixels the validator says are dropped."""
    r = build_file(str(FIXTURES / f"snes_{rule}_fail.px.js"))
    m = r.models[0]
    b = encode_scene(m)
    got = render(b, 0)
    diff = {(int(x), int(y)) for y, x in np.argwhere((got != m.composites[0]).any(axis=2))}
    pred = m.predicted_drops(0)
    assert diff and diff <= pred


@pytest.mark.parametrize("path", LEGAL, ids=lambda p: p.stem)
def test_existing_engine_agrees_snes(path):
    """M2-12: the existing compliance check passes every legal PNG (no pixel-identity claim: the existing
    greedy palette allocator is not exact)."""
    r = build_file(str(path))
    seen = 0
    for key, data in r.outputs.items():
        if not key.startswith("png/") or key.endswith(".idx.png") or ".screen" in key:
            continue                      # composites of several layers are not one asset (as in M1-17)
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        comp = generate_metadata(img, asset_type="sprite", console="snes")["compliance"]
        assert comp["palette_valid"] and comp["colors_per_tile_valid"], key
        seen += 1
    assert seen

"""M1-12..15: NES byte formats, checked against golden bytes (CODE-MODE-SPEC §4.5)."""

import numpy as np
import pytest

from retrogaze.codemode.encode.nes import attribute_bytes, encode_scene, oam_entry, tile_bytes

from ._codemode import EXAMPLES, FIXTURES, build_file

HALF = [".1.....3", "11....3.", ".1...3..", ".1..3...", "...3.22.", "..3....2", ".3....2.", "3....222"]


def test_chr_golden_half_tile():
    """The NESdev pattern-table example ("1/2")."""
    pat = np.array([[0 if c == "." else int(c) for c in row] for row in HALF], dtype=np.uint8)
    assert tile_bytes(pat).hex(" ").upper() == "41 C2 44 48 10 20 40 80 01 02 04 08 16 21 42 87"


def test_nametable_and_attributes():
    attrs = np.zeros((15, 16), dtype=np.int32)
    attrs[0, 0], attrs[0, 1], attrs[1, 0], attrs[1, 1] = 0, 1, 2, 3
    attrs[14, :] = 3
    b = attribute_bytes(attrs)
    assert b[0] == 0xE4
    assert len(b) == 64
    assert all(x == 0x0F for x in b[56:64])          # rows 30-31 do not exist: their fields stay 0
    r = build_file(str(EXAMPLES / "nes_hero.px.js"))
    assert len(r.outputs["nes/title.nam"]) == 1024


def legal_pal_outputs():
    paths = sorted(FIXTURES.glob("nes_*_pass.px.js")) + sorted(EXAMPLES.glob("*.px.js"))
    for p in paths:
        r = build_file(str(p))
        for k, v in r.outputs.items():
            if k.endswith(".pal"):
                yield p.name, k, v


def test_palette_bytes():
    seen = 0
    for _, key, pal in legal_pal_outputs():
        seen += 1
        assert len(pal) == 32
        assert 0x0D not in pal, key
        for i in (0, 4, 8, 12):
            assert pal[16 + i] == pal[i] == pal[0], key      # $3F10/14/18/1C mirror; one backdrop
        assert all(b <= 0x3F for b in pal)
    assert seen >= 10
    r = build_file(str(EXAMPLES / "nes_hero.px.js"))
    pal = r.outputs["nes/title.pal"]
    assert pal[0] == 0x21                                     # the sky backdrop the solver picked
    pinned = build_file(str(FIXTURES / "nes_H5_pass.px.js")).outputs["nes/s.pal"]
    assert list(pinned[:4]) == [0x0F, 0x01, 0x02, 0x03]     # pinned bytes are exported verbatim


def test_black_is_0F_never_0D():
    r = build_file(str(FIXTURES / "nes_H1_pass.px.js"))
    assert r.outputs["nes/s.pal"][0] == 0x0F


def test_oam_bytes():
    assert oam_entry(top=176, tile=5, palette=2, x=120, flip_h=True).hex(" ").upper() == "AF 05 42 78"
    assert oam_entry(top=1, tile=0, palette=3, x=0, flip_v=True, behind=True).hex(" ").upper() == "00 00 A3 00"
    r = build_file(str(EXAMPLES / "nes_hero.px.js"))
    oam = r.outputs["nes/title.oam"]
    assert len(oam) == 256
    used = 8
    assert all(oam[4 * i:4 * i + 4] == bytes([0xFF, 0, 0, 0]) for i in range(used, 64))
    assert all(oam[4 * i + 2] & 0x1C == 0 for i in range(64))   # bits 2-4 do not exist in the PPU


def test_8x16_tile_byte_selects_the_table():
    r = build_file(str(FIXTURES / "nes_H10_pass.px.js"))
    m = next(x for x in r.models if x.name == "s1")
    b = encode_scene(m)
    assert b.rom["sprite_size"] == "8x16"
    tile = b.oam[0][1]
    assert tile & 1 == 1 and tile & 0xFE == 0                 # pattern table $1000, first pair


@pytest.mark.parametrize("name", ["nes_hero.px.js", "nes_proof.px.js"])
def test_text_includes(name):
    r = build_file(str(EXAMPLES / name))
    s = [k for k in r.outputs if k.endswith(".s") and not k.endswith(".ms.s")]
    assert s
    for k in s:
        text = r.outputs[k].decode()
        assert '.segment "CHARS"' in text and ".incbin" in text and "algorithmicMedia" in text
        h = r.outputs[k[:-2] + ".h"].decode()
        assert "extern const unsigned char" in h

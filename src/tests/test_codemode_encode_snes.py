"""M2-03..06: SNES byte formats, checked against golden bytes (CODE-MODE-SPEC §4.4, §4.5)."""

import numpy as np
import pytest

from retrogaze.codemode.encode.snes import (
    EncodeError, SnesObj, cgram_word, oam_bytes, tile_2bpp, tile_4bpp, tilemap_word,
)

from ._codemode_snes import EXAMPLES, FIXTURES, build_file, scene

HALF = [".1.....3", "11....3.", ".1...3..", ".1..3...", "...3.22.", "..3....2", ".3....2.", "3....222"]


def _pat(rows):
    return np.array([[0 if c == "." else int(c, 16) for c in row] for row in rows], dtype=np.uint8)


def test_4bpp_goldens():
    """M2-03: the NESdev "1/2" tile as SNES 4bpp, and a lone index-15 pixel."""
    half = tile_4bpp(_pat(HALF))
    assert half.hex(" ").upper() == "41 01 C2 02 44 04 48 08 10 16 20 21 40 42 80 87" + " 00" * 16
    one = np.zeros((8, 8), dtype=np.uint8)
    one[0, 0] = 15
    b = tile_4bpp(one)
    assert len(b) == 32 and [i for i, x in enumerate(b) if x] == [0, 1, 16, 17] and b[0] == b[1] == b[16] == b[17] == 0x80
    assert tile_2bpp(_pat(HALF)) == half[:16]                  # 2bpp = the first 16 bytes (Game Boy layout)


def test_cgram_goldens():
    """M2-04: 15-bit BGR words, low byte first; the file is 512 bytes and OBJ palettes start at byte 256."""
    for hexstr, word in [("#FF0000", "1F 00"), ("#00FF00", "E0 03"), ("#0000FF", "00 7C"), ("#FFFFFF", "FF 7F"),
                         ("#834120", "10 11")]:
        assert cgram_word(hexstr).to_bytes(2, "little").hex(" ").upper() == word
    with pytest.raises(ValueError):
        cgram_word("#848484")                                  # not a canonical e(q) color
    r = build_file(str(FIXTURES / "snes_H7_pass.px.js"))
    cg = r.outputs["snes/s.cgram"]
    assert len(cg) == 512
    m = scene(r, "s")
    first_obj = m.obj_slots[0][0]                              # OBJ palette 0, color index 1 = CGRAM 129
    assert cg[256 + 2:256 + 4] == cgram_word(f"#{first_obj:06X}").to_bytes(2, "little")
    assert cg[0:2] == cgram_word(m.backdrop_hex).to_bytes(2, "little")


def test_tilemap_word():
    """M2-05: tile $155, palette 3, priority 1, H-flip -> $6D55, stored 55 6D."""
    w = tilemap_word(0x155, palette=3, priority=1, flip_h=True)
    assert w == 0x6D55 and w.to_bytes(2, "little").hex(" ").upper() == "55 6D"
    assert tilemap_word(0x3FF, palette=7, priority=0, flip_v=True) == 0x9FFF
    with pytest.raises(ValueError):
        tilemap_word(0x400, palette=0)


def test_oam_and_high_table():
    """M2-06: 544 bytes; X = -1 is low byte FF + high bit 1; size bits; unused OBJs parked off screen."""
    objs = [SnesObj(x=-1, y=10, tile=0x105, palette=5, priority=3, flip_h=True, large=True),
            SnesObj(x=200, y=0, tile=0x02, palette=0, priority=3, large=False)]
    b = oam_bytes(objs)
    assert len(b) == 544
    assert b[0:4].hex(" ").upper() == "FF 0A 05 7B"            # VHPPCCCt = 0 1 11 101 1
    assert b[4:8].hex(" ").upper() == "C8 00 02 30"
    hi = b[512]
    assert hi & 0b11 == 0b11                                   # OBJ 0: X bit 8 = 1, large
    assert (hi >> 2) & 0b11 == 0b00                            # OBJ 1: X bit 8 = 0, small
    for i in range(2, 128):                                    # parked: Y = 224, X = -128 (never X = -256)
        assert b[4 * i:4 * i + 4] == bytes([0x80, 0xE0, 0x00, 0x00])
        assert (b[512 + i // 4] >> (2 * (i % 4))) & 0b11 == 0b01
    with pytest.raises(EncodeError) as e:
        oam_bytes([SnesObj(x=-256, y=10, tile=0, palette=0, priority=3, large=False)])
    assert e.value.rule == "SNES-H4"


def test_large_obj_tiles_are_a_16_column_block():
    """M2-10 (part): a 16x16 OBJ uses tiles N, N+1, N+16, N+17 of the OBJ name table."""
    r = build_file(str(EXAMPLES / "snes_proof.px.js"))
    m = scene(r, "proof")
    b = r.outputs["snes/proof.obj.4bpp"]
    obj = next(o for o in m.oam[0] if (o.w, o.h) == (32, 32) and not o.flip_h and not o.flip_v)
    n = obj.tile
    for ty in range(4):
        for tx in range(4):
            idx = n + tx + 16 * ty
            assert b[32 * idx:32 * idx + 32] == tile_4bpp(obj.pattern[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8])

#!/usr/bin/env python3
"""Write the hand-built NES self-test scenes (exporter contract) plus their reference renders.

    make_selftest.py --out-dir D

Scenes (each = N.chr N.pal N.nam N.oam N.rom.json N.ref.png):
  selftest               8x8 sprites, BG table 0, sprite table 1, left 8 px shown. 8 BG tiles over all
                         4 BG palettes, every attribute byte has 4 different quadrants, a 16x16
                         metasprite of 4 sprites in 2 palettes (#3 H-flipped), a Y-convention marker
                         (#4: Y byte $4F, one-row tile -> must appear on line $50 only), a V+H-flipped
                         sprite at X=2 (#5) and a V-flipped behind-BG sprite (#6), half over blank BG.
  selftest_9line         8x16 sprites, BG table 1, left 8 px hidden. Sprites #0-#7 cover lines 120-135,
                         #8 covers 128-143, so the reference drops #8 on lines 128-135 only.
  selftest_9line_nodrop  NEGATIVE CONTROL: the bytes of selftest_9line, but the reference ignores the
                         8-per-line limit. Gate (d) must fail on exactly #8's pixels on lines 128-135.

The renderer models the 2C02 for one static frame: 8 sprites per line in OAM order, sprites never on
line 0 (top = Y byte + 1 >= 1), lower OAM index wins, then the priority bit vs. opaque BG, left-8 clip.
Colors use Retrogaze's NES RGB table. Standard library only.
"""
import argparse
import json
import struct
import zlib
from pathlib import Path

# Copy of _NES_PALETTE_HEX, src/retrogaze/console_profile.py:79 (56 entries, 4 rows x 14 columns).
# Byte = row * 16 + column; columns $E/$F are black.
NES_HEX = (
    "626262 002C88 1B0076 3B0076 560044 5A0002 4F0800 351000 1A1802 002E00 003200 002A14 00234A 000000 "
    "ABABAB 0D56D0 4220D0 6A12C2 92088A 9A1032 913800 7A5400 536800 0E7800 007A00 007028 006486 000000 "
    "FFFFFF 4CA0FE 7C78FE A862FE D85CFE E47ABA E09264 C8B216 A0CC00 6ADA02 46E438 3AD67E 3EC4D2 4E4E4E "
    "FFFFFF B6D8FE C8C4FE DAB8FE EEBAFE F4C4E2 F0CEB2 E4DE94 D0E882 BCF07E B0F29C ACF0C2 B2ECEE ACACAC"
).split()


def nes_rgb(byte: int) -> bytes:
    row, col = (byte >> 4) & 3, byte & 0x0F
    return b"\0\0\0" if col >= 0x0E else bytes.fromhex(NES_HEX[row * 14 + col])


# ---------------------------------------------------------------- encoding helpers (exporter contract)

def encode_tile(rows) -> bytes:
    """8 strings of 8 chars '0'-'3' ('.' = 0) -> 16 bytes: plane 0 rows, plane 1 rows, bit 7 = left."""
    vals = [[0 if ch == "." else int(ch) for ch in row] for row in rows]
    assert len(vals) == 8 and all(len(r) == 8 and max(r) <= 3 for r in vals)
    plane0 = bytes(sum((v & 1) << (7 - x) for x, v in enumerate(r)) for r in vals)
    plane1 = bytes(sum((v >> 1) << (7 - x) for x, v in enumerate(r)) for r in vals)
    return plane0 + plane1


def make_chr(tables) -> bytes:
    """tables = {table: {tile: rows}}. Unused tiles get deterministic noise, so every byte matters."""
    chr_ = bytearray((i * 37 + 11) & 0xFF for i in range(8192))
    for table, tiles in tables.items():
        for index, rows in tiles.items():
            at = table * 4096 + index * 16
            chr_[at:at + 16] = encode_tile(rows)
    return bytes(chr_)


def make_pal(backdrop, bg, spr) -> bytes:
    """4 BG + 4 sprite color triples; every entry 0 (incl. the $3F10/14/18/1C mirrors) = backdrop."""
    pal = bytearray()
    for triple in list(bg) + list(spr):
        pal += bytes([backdrop, *triple])
    assert len(pal) == 32 and 0x0D not in pal
    return bytes(pal)


def make_nam(tile_at, pal_at) -> bytes:
    """tile_at(cx, cy) for 32x30 cells; pal_at(ax, ay) for the 16x16 areas (rows 30-31 -> 0)."""
    nam = bytearray(tile_at(cx, cy) for cy in range(30) for cx in range(32))
    area = lambda ax, ay: pal_at(ax, ay) if ay < 15 else 0
    for by in range(8):
        for bx in range(8):
            tl, tr = area(2 * bx, 2 * by), area(2 * bx + 1, 2 * by)
            bl, br = area(2 * bx, 2 * by + 1), area(2 * bx + 1, 2 * by + 1)
            nam.append((br << 6) | (bl << 4) | (tr << 2) | tl)
    return bytes(nam)


def make_oam(sprites) -> bytes:
    """sprites = [(top, tile, attr, x)] in OAM order; the rest are parked at Y = $FF."""
    oam = bytearray()
    for top, tile, attr, x in sprites:
        assert 1 <= top <= 239 and attr & 0x1C == 0
        oam += bytes([top - 1, tile, attr, x])
    for i in range(len(sprites), 64):
        oam += bytes([0xFF, i, (i * 7) & 0xE3, (i * 13) & 0xFF])   # attr bits 2-4 do not exist
    return bytes(oam)


# ---------------------------------------------------------------- reference renderer

def chr_pixel(chr_, table, tile, row, col) -> int:
    base = table * 4096 + tile * 16
    return ((chr_[base + row] >> (7 - col)) & 1) | (((chr_[base + 8 + row] >> (7 - col)) & 1) << 1)


def render(chr_, pal, nam, oam, rom, sprite_limit=8) -> bytes:
    """Return 256x240 RGBA of the frame the PPU shows. sprite_limit=None disables the 8/line rule."""
    tall = rom["sprite_size"] == "8x16"
    height = 16 if tall else 8
    sprites = [(oam[i] + 1, oam[i + 1], oam[i + 2], oam[i + 3]) for i in range(0, 256, 4)]
    out = bytearray()
    for y in range(240):
        on_line = [s for s in sprites if s[0] <= y < s[0] + height][:sprite_limit]
        for x in range(256):
            color = pal[0]
            if x >= 8 or rom["left8"]:
                cx, cy = x >> 3, y >> 3
                bg = chr_pixel(chr_, rom["bg_table"], nam[cy * 32 + cx], y & 7, x & 7)
                attr = nam[960 + (cy >> 2) * 8 + (cx >> 2)]
                bg_pal = (attr >> (((cy & 2) << 1) | (cx & 2))) & 3
                if bg:
                    color = pal[bg_pal * 4 + bg]
                for top, tile, sattr, sx in on_line:
                    col, row = x - sx, y - top
                    if not 0 <= col < 8:
                        continue
                    if sattr & 0x40:
                        col = 7 - col
                    if sattr & 0x80:
                        row = height - 1 - row
                    if tall:
                        table, tile, row = tile & 1, (tile & 0xFE) + (row >> 3), row & 7
                    else:
                        table = rom["spr_table"]
                    px = chr_pixel(chr_, table, tile, row, col)
                    if px:                       # first opaque sprite (lowest OAM index) wins
                        if not (sattr & 0x20 and bg):
                            color = pal[0x10 + (sattr & 3) * 4 + px]
                        break
            out += nes_rgb(color) + b"\xff"
    return bytes(out)


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))
    stride = width * 4
    raw = b"".join(b"\0" + rgba[y * stride:(y + 1) * stride] for y in range(height))
    path.write_bytes(b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


# ---------------------------------------------------------------- the scenes

BLANK = ["........"] * 8
SOLID = lambda c: [c * 8] * 8
HALF = [".1.....3", "11....3.", ".1...3..", ".1..3...", "...3.22.", "..3....2", ".3....2.", "3....222"]
BG_TILES = {
    0: BLANK, 1: SOLID("1"), 2: SOLID("2"), 3: SOLID("3"),
    4: ["3.3.3.3.", ".3.3.3.3"] * 4,                       # checkerboard with transparent pixels
    5: ["..112233"] * 8,                                   # column order: bit 7 = leftmost
    6: HALF,                                               # NESdev "1/2" tile (golden bytes)
    7: ["........"] * 2 + ["11111111"] * 2 + ["22222222"] * 2 + ["33333333"] * 2,
}
GLYPH_F = ["3333333.", "31111113", "312.....", "31222...", "312.....", "312.....", "31......", "3......."]
GLYPH_L = ["1.......", "12......", "123.....", "1233....", "12333...", "123333..", "1222222.", "11111111"]
GLYPH_O = ["22222222", "2......2", "2.3333.2", "2.3..3.2", "2.3..3.2", "2.3333.2", "2......1", "22222211"]
MARKER = ["33333333"] + ["........"] * 7


def scene_selftest():
    rom = {"sprite_size": "8x8", "bg_table": 0, "spr_table": 1, "left8": True}
    chr_ = make_chr({0: BG_TILES, 1: {1: GLYPH_F, 2: GLYPH_L, 3: GLYPH_O, 4: MARKER}})
    pal = make_pal(0x0F, bg=[(0x06, 0x16, 0x26), (0x01, 0x11, 0x21), (0x09, 0x19, 0x29), (0x04, 0x14, 0x24)],
                   spr=[(0x27, 0x37, 0x30), (0x2C, 0x1C, 0x3C), (0x08, 0x18, 0x28), (0x02, 0x12, 0x22)])
    # each attribute byte: TL = k, TR = k+1, BL = k+2, BR = k+3 (mod 4), k = bx + by
    nam = make_nam(lambda cx, cy: (cx + cy) % 8,
                   lambda ax, ay: ((ax >> 1) + (ay >> 1) + (ax & 1) + 2 * (ay & 1)) % 4)
    oam = make_oam([
        (100, 1, 0x00, 120), (100, 2, 0x00, 128),     # 16x16 metasprite, palette 0 on top...
        (108, 3, 0x01, 120), (108, 1, 0x41, 128),     # ...palette 1 below, #3 = #0's tile H-flipped
        (0x50, 4, 0x00, 40),                          # Y byte $4F: first row must be on line $50
        (180, 2, 0xC2, 2),                            # V+H flip, palette 2, inside the left 8 px
        (60, 3, 0xA3, 200),                           # behind BG (priority bit) + V flip, palette 3
    ])
    return chr_, pal, nam, oam, rom


def scene_9line():
    rom = {"sprite_size": "8x16", "bg_table": 1, "spr_table": 0, "left8": False}
    # 8x16: tile byte bit 0 = table; top tile = byte & $FE, bottom = top + 1
    chr_ = make_chr({0: {0: GLYPH_F, 1: GLYPH_L, 2: GLYPH_O, 3: MARKER}, 1: BG_TILES})
    pal = make_pal(0x00, bg=[(0x07, 0x17, 0x2A), (0x0B, 0x1B, 0x2B), (0x03, 0x13, 0x23), (0x05, 0x15, 0x25)],
                   spr=[(0x30, 0x26, 0x16), (0x3C, 0x2C, 0x1C), (0x38, 0x28, 0x18), (0x31, 0x21, 0x11)])
    nam = make_nam(lambda cx, cy: (3 * cx + cy) % 8,
                   lambda ax, ay: (3 * (ax >> 1) + (ay >> 1) + 2 * (ax & 1) + 3 * (ay & 1)) % 4)
    tiles = [0x00, 0x02, 0x05, 0x00, 0x02, 0x05, 0x00, 0x02]          # 0x05 -> table 1, tiles 4/5
    attrs = [0x00, 0x01, 0x82, 0x40, 0xC0, 0x01, 0x02, 0x00]
    sprites = [(120, tiles[i], attrs[i], 4 + 28 * i) for i in range(8)]  # #0 at X=4 is half clipped
    sprites.append((128, 0x02, 0x03, 228))                             # #8: 9th sprite on 128-135
    return chr_, pal, nam, make_oam(sprites), rom


def write_scene(out_dir: Path, name: str, scene, sprite_limit=8) -> None:
    chr_, pal, nam, oam, rom = scene
    for ext, data in ((".chr", chr_), (".pal", pal), (".nam", nam), (".oam", oam)):
        (out_dir / f"{name}{ext}").write_bytes(data)
    (out_dir / f"{name}.rom.json").write_text(json.dumps(rom, sort_keys=True) + "\n", encoding="utf-8")
    write_png(out_dir / f"{name}.ref.png", 256, 240, render(chr_, pal, nam, oam, rom, sprite_limit))


SCENES = {  # name -> (builder, sprite_limit of the reference, gates expected to pass)
    "selftest": (scene_selftest, 8, True),
    "selftest_9line": (scene_9line, 8, True),
    "selftest_9line_nodrop": (scene_9line, None, False),
}


def write_all(out_dir) -> list:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    assert encode_tile(HALF).hex(" ").upper() == "41 C2 44 48 10 20 40 80 01 02 04 08 16 21 42 87"
    for name, (builder, limit, _) in SCENES.items():
        write_scene(out_dir, name, builder(), limit)
    return list(SCENES)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out-dir", required=True, type=Path)
    args = ap.parse_args(argv)
    for name in write_all(args.out_dir):
        print(f"wrote {args.out_dir / name}.{{chr,pal,nam,oam,rom.json,ref.png}}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

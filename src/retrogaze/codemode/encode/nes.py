"""
Serialize a legal NES scene model into the bytes the console loads.

Formats (docs/spec/CODE-MODE-SPEC.md §4.3):
  .chr  8 KiB: pattern table $0000 then $1000; 16 bytes per tile, plane 0 rows then plane 1 rows, bit 7 leftmost
  .pal  32 bytes: $3F00-$3F1F image; $3F10/14/18/1C mirror $3F00/04/08/0C; never $0D
  .nam  1024 bytes: 960 tile indices (32x30) + 64 attribute bytes (BR<<6 | BL<<4 | TR<<2 | TL)
  .oam  256 bytes: 64 x [top-1, tile, attr, X]; unused entries have Y = $FF

The encoder re-checks the model on its own and refuses (with the rule ID) anything the
hardware cannot hold, so it is a second, independent answer to "is this legal".
"""

from __future__ import annotations

import json
from dataclasses import dataclass

import numpy as np

from ..hw.common import round_up
from ..hw.nes import AREA, COLS, H, ROWS, W, SceneModel


class EncodeError(Exception):
    def __init__(self, rule: str, message: str):
        super().__init__(f"{rule}: {message}")
        self.rule = rule


@dataclass
class NesBytes:
    chr: list[bytes]          # one 8 KiB image per CHR set (one unless chr: "chr-ram")
    pal: bytes
    nam: list[bytes]          # one per state
    oam: list[bytes]          # one per state
    rom: dict                 # PPU settings for the viewer ROM
    tile_bytes: dict          # (state, oam index) -> OAM tile byte, for metasprites


def oam_entry(top: int, tile: int, palette: int, x: int, flip_h: bool = False, flip_v: bool = False,
              behind: bool = False) -> bytes:
    """One OAM entry: [Y = top - 1, tile, attributes VHP000PP, X]."""
    attr = (palette & 3) | (int(behind) << 5) | (int(flip_h) << 6) | (int(flip_v) << 7)
    return bytes([(top - 1) & 0xFF, tile & 0xFF, attr, x & 0xFF])


def tile_bytes(pat: np.ndarray) -> bytes:
    """One 8x8 tile: 8 bytes of plane 0 then 8 of plane 1, bit 7 = leftmost pixel."""
    p0 = bytearray(8)
    p1 = bytearray(8)
    for y in range(8):
        for x in range(8):
            v = int(pat[y, x])
            if v & 1:
                p0[y] |= 0x80 >> x
            if v & 2:
                p1[y] |= 0x80 >> x
    return bytes(p0 + p1)


def palette_bytes(m: SceneModel) -> bytes:
    out = bytearray()
    for group in (m.bg_palette_bytes, m.obj_palette_bytes):
        for p in group[:4]:
            out.append(m.backdrop_byte)
            out.extend(p[:3])
    if 0x0D in out:
        raise EncodeError("NES-H1", "palette would contain $0D")
    if len(out) != 32 or any(b > 0x3F for b in out):
        raise EncodeError("NES-H1", "palette RAM image must be 32 bytes of 6-bit colors")
    return bytes(out)


def attribute_bytes(attrs: np.ndarray) -> bytes:
    out = bytearray(64)
    rows, cols = attrs.shape            # (15, 16) areas
    for by in range(8):
        for bx in range(8):
            def a(dx, dy):
                x, y = 2 * bx + dx, 2 * by + dy
                return int(attrs[y, x]) & 3 if y < rows and x < cols else 0
            out[by * 8 + bx] = (a(1, 1) << 6) | (a(0, 1) << 4) | (a(1, 0) << 2) | a(0, 0)
    return bytes(out)


def _check_model(m: SceneModel) -> None:
    """Independent re-check: everything the bytes must hold actually fits."""
    if not m.checked:
        raise EncodeError("NES-H13", f"scene '{m.name}' was not analyzed")
    ch = 16 if m.sprite_size == "8x16" else 8
    for s, plane_attrs in enumerate(m.attributes):
        if plane_attrs.max(initial=0) > 3:
            raise EncodeError("NES-H6", "attribute index above 3")
    if m.rejected:
        c = m.rejected[0]
        raise EncodeError("NES-H13", f"sprite cell at ({c.x},{c.top}) cannot be placed")
    for state in range(m.states):
        got = render_bg(m, state)
        if not np.array_equal(got, m.bg_screens[state]):
            y, x = np.argwhere(got != m.bg_screens[state])[0]
            area = m.bg_screens[state][y // AREA * AREA:(y // AREA + 1) * AREA, x // AREA * AREA:(x // AREA + 1) * AREA]
            n = len({int(v) for v in np.unique(area)} - {m.backdrop})
            raise EncodeError("NES-H2" if n > 3 else "NES-H6",
                              f"BG pixel ({x},{y}) is not reproducible from its area's palette ({n} colors there)")
        for c in m.oam[state]:
            if len(c.colors) > 3:
                raise EncodeError("NES-H3", f"sprite cell at ({c.x},{c.top}) has {len(c.colors)} colors")
            if any(col not in m.obj_palettes[c.palette] for col in c.colors):
                raise EncodeError("NES-H7", f"sprite cell at ({c.x},{c.top}) needs colors outside the 4 sprite palettes")
            if not (0 <= c.x <= 255 and 1 <= c.top <= 239):
                raise EncodeError("NES-H13", f"sprite cell at ({c.x},{c.top}) cannot be placed")
            if c.h != ch:
                raise EncodeError("NES-H10", "mixed sprite sizes")
        if len(m.oam[state]) > 64:
            raise EncodeError("NES-H8", f"{len(m.oam[state])} sprites; OAM holds 64")
    for ci in range(m.chr_sets):
        nb, no = len(m.bg_tiles[ci]), len(m.obj_tiles[ci])
        units = no * (2 if ch == 16 else 1)
        if nb > 256:
            raise EncodeError("NES-H11", f"{nb} BG tiles")
        cap = (256 - (round_up(nb, 2) if ch == 16 else nb)) if m.chr_model == "shared" else \
            (256 if ch == 8 else 256 + max(0, 256 - round_up(nb, 2)))
        if units > cap:
            raise EncodeError("NES-H12", f"{units} sprite tiles; room for {cap}")


def render_bg(m: SceneModel, state: int) -> np.ndarray:
    """BG as the model's tiles, attributes and palettes describe it: (240, 256) rgb."""
    tiles = np.stack(m.bg_tiles[m.chr_index(state)]) if m.bg_tiles[m.chr_index(state)] else np.zeros((1, 8, 8), np.uint8)
    idx = tiles[m.nametables[state]].transpose(0, 2, 1, 3).reshape(H, W)
    table = np.array([[m.backdrop] + list(p[:3]) for p in m.bg_palettes[:4]], dtype=np.int64)
    attr = np.repeat(np.repeat(m.attributes[state], AREA, axis=0), AREA, axis=1)
    return table[attr, idx].astype(np.int32)


def encode_scene(m: SceneModel) -> NesBytes:
    _check_model(m)
    ch = 16 if m.sprite_size == "8x16" else 8
    shared = m.chr_model == "shared"
    chr_images: list[bytes] = []
    slot_of: list[dict[int, tuple[int, int]]] = []    # per CHR set: obj unit -> (table, first tile index)
    for ci in range(m.chr_sets):
        tables = [bytearray(4096), bytearray(4096)]
        for i, pat in enumerate(m.bg_tiles[ci]):
            tables[0][16 * i:16 * i + 16] = tile_bytes(pat)
        nb = len(m.bg_tiles[ci])
        slots: dict[int, tuple[int, int]] = {}
        for i, pat in enumerate(m.obj_tiles[ci]):
            if ch == 8:
                table, idx = (0, nb + i) if shared else (1, i)
                tables[table][16 * idx:16 * idx + 16] = tile_bytes(pat)
            else:
                if shared:
                    table, idx = 0, round_up(nb, 2) + 2 * i
                elif i < 128:
                    table, idx = 1, 2 * i
                else:
                    table, idx = 0, round_up(nb, 2) + 2 * (i - 128)
                tables[table][16 * idx:16 * idx + 16] = tile_bytes(pat[:8])
                tables[table][16 * idx + 16:16 * idx + 32] = tile_bytes(pat[8:])
            slots[i] = (table, idx)
        chr_images.append(bytes(tables[0] + tables[1]))
        slot_of.append(slots)

    nams, oams, tbytes = [], [], {}
    for s in range(m.states):
        nt = m.nametables[s]
        nam = bytes(int(v) for v in nt.ravel()) + attribute_bytes(m.attributes[s])
        assert len(nam) == 1024
        nams.append(nam)
        oam = bytearray([0xFF, 0x00, 0x00, 0x00] * 64)
        slots = slot_of[m.chr_index(s)]
        for i, c in enumerate(m.oam[s]):
            table, idx = slots[c.tile]
            tile = idx if ch == 8 else (idx & 0xFE) | table
            oam[4 * i:4 * i + 4] = oam_entry(c.top, tile, c.palette, c.x, c.flip_h, c.flip_v)
            tbytes[(s, i)] = tile
        oams.append(bytes(oam))
    rom = {
        "sprite_size": m.sprite_size,
        "bg_table": 0,
        "spr_table": 0 if (shared and ch == 8) else 1,
        "left8": m.left8,
    }
    return NesBytes(chr=chr_images, pal=palette_bytes(m), nam=nams, oam=oams, rom=rom, tile_bytes=tbytes)


# ---------------------------------------------------------------------------
# Text includes: ca65 + cc65, neslib-style metasprites
# ---------------------------------------------------------------------------


def _ident(s: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in s)
    return out if not out[0].isdigit() else "_" + out


def metasprites(m: SceneModel, b: NesBytes) -> list[tuple[str, list[tuple[int, int, int, int]]]]:
    """Per (asset, frame): cells relative to the placement origin, as (x, y, tile, attr), neslib order."""
    out = []
    seen = set()
    placements = m.spec.get("obj") or []
    for s in range(m.states):
        for i, c in enumerate(m.oam[s]):
            key = (c.asset, c.frame, c.placement)
            if key in seen:
                continue
            first = next((pi for pi, p in enumerate(placements) if p[0] == c.asset), c.placement)
            if c.placement != first:
                continue
            seen.add(key)
            px, py = int(placements[c.placement][1]), int(placements[c.placement][2])
            cells = [(d.x - px, d.top - py, b.tile_bytes[(s, j)], (d.palette & 3) | (int(d.flip_h) << 6) | (int(d.flip_v) << 7))
                     for j, d in enumerate(m.oam[s]) if d.asset == c.asset and d.placement == c.placement]
            out.append((f"{c.asset}_f{c.frame}", cells))
    return out


def ca65_include(m: SceneModel, b: NesBytes, files: dict[str, str], header: str) -> str:
    n = _ident(m.name)
    lines = [f"; {header}", f"; Scene '{m.name}': {m.sprite_size} sprites, chr model {m.chr_model}.", ""]
    exports = [f"{n}_pal", f"{n}_nam", f"{n}_oam", f"{n}_chr"]
    lines.append(".export " + ", ".join(exports))
    lines += ["", '.segment "CHARS"', f'{n}_chr: .incbin "{files["chr"]}"', "", '.segment "RODATA"',
              f'{n}_pal: .incbin "{files["pal"]}"', f'{n}_nam: .incbin "{files["nam"]}"',
              f'{n}_oam: .incbin "{files["oam"]}"']
    if m.metatiles:
        lines += ["", f"; 16x16 metatiles: top-left, top-right, bottom-left, bottom-right, palette ({len(m.metatiles)})",
                  f".export {n}_metatiles", f"{n}_metatiles:"]
        lines += [f"  .byte ${t[0]:02X}, ${t[1]:02X}, ${t[2]:02X}, ${t[3]:02X}, ${t[4]:02X}" for t in m.metatiles]
    return "\n".join(lines) + "\n"


def metasprite_source(m: SceneModel, b: NesBytes, header: str) -> str:
    n = _ident(m.name)
    lines = [f"; {header}",
             "; neslib-style metasprites: x, y, tile, attr per sprite (offsets from the placement origin), $80 ends.",
             ""]
    for label, cells in metasprites(m, b):
        lab = f"{n}_{_ident(label)}"
        lines += [f".export {lab}", f"{lab}:"]
        lines += [f"  .byte ${x & 0xFF:02X}, ${y & 0xFF:02X}, ${t:02X}, ${a:02X}" for x, y, t, a in cells]
        lines += ["  .byte $80", ""]
    return "\n".join(lines)


def c_header(m: SceneModel, b: NesBytes, header: str) -> str:
    n = _ident(m.name)
    guard = f"RETROGAZE_{n.upper()}_H"
    lines = [f"/* {header} */", f"#ifndef {guard}", f"#define {guard}", "",
             f"extern const unsigned char {n}_chr[{len(b.chr[0])}];",
             f"extern const unsigned char {n}_pal[32];",
             f"extern const unsigned char {n}_nam[1024];",
             f"extern const unsigned char {n}_oam[256];"]
    if m.metatiles:
        lines.append(f"extern const unsigned char {n}_metatiles[{5 * len(m.metatiles)}];")
    for label, _ in metasprites(m, b):
        lines.append(f"extern const unsigned char {n}_{_ident(label)}[];")
    lines += ["", f"#endif /* {guard} */", ""]
    return "\n".join(lines)


def rom_json(b: NesBytes) -> str:
    return json.dumps(b.rom, indent=2, sort_keys=True) + "\n"


__all__ = ["EncodeError", "NesBytes", "encode_scene", "oam_entry", "tile_bytes", "palette_bytes", "attribute_bytes",
           "ca65_include", "metasprite_source", "c_header", "rom_json", "W", "H", "AREA"]

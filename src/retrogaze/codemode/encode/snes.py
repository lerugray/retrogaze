"""
Serialize a legal SNES scene model into the bytes the console loads.

Formats (docs/spec/CODE-MODE-SPEC.md §4.4):
  .bgN.4bpp  32 bytes per tile: row r -> [2r] plane 0, [2r+1] plane 1, [16+2r] plane 2, [17+2r] plane 3; bit 7 leftmost
  .bg3.2bpp  16 bytes per tile: the first half of the 4bpp layout
  .obj.4bpp  the OBJ name tables (8 KiB each) as the allocator filled them (16-column grid)
  .bgN.map   2048 bytes: 32x32 little-endian words VHPCCCTT TTTTTTTT
  .cgram     512 bytes: 256 little-endian words 0bbbbbgggggrrrrr; BG palettes at 0-127, OBJ at 128-255
  .oam       544 bytes: 128 x [X low, Y, tile low, VHPPCCCt] + 32 bytes of (X bit 8, size) pairs
  .vram.json the VRAM map and the PPU register values

The encoder re-checks the model on its own and refuses (with the rule ID) anything the hardware cannot
hold, so it is a second, independent answer to "is this legal".
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import numpy as np

from ..binding import snes_word
from ..hw.common import color_set, hex_of
from ..hw.snes import (
    BG_LAYERS, BG_TILES, BPP, DOCUMENTED_OBSEL, MAP, MAX_OBJ, OBJ_PRIORITY, OBJ_SIZES, OBSEL_PAIRS, TILE_CAP,
    VRAM_BYTES, SceneModel, VramLayout, VramRequest, allocate_vram, assign, q_slots,
)

VOFS = 0x3FF        # screen row r is scanline r + 1; BG line = scanline + VOFS, so -1 shows BG row 0 on row 0
PARK_X, PARK_Y = -128, 224     # unused OBJs: below the 224-line screen and fully left of it (never X = -256)


class EncodeError(Exception):
    def __init__(self, rule: str, message: str):
        super().__init__(f"{rule}: {message}")
        self.rule = rule


def _planes(pat: np.ndarray, planes: int) -> list[bytearray]:
    out = [bytearray(8) for _ in range(planes)]
    for y in range(8):
        for x in range(8):
            v = int(pat[y, x])
            for p in range(planes):
                if v >> p & 1:
                    out[p][y] |= 0x80 >> x
    return out


def tile_4bpp(pat: np.ndarray) -> bytes:
    """One 8x8 tile, 4 bits per pixel: rows interleave planes 0/1, then planes 2/3."""
    p = _planes(pat, 4)
    lo = bytes(b for y in range(8) for b in (p[0][y], p[1][y]))
    hi = bytes(b for y in range(8) for b in (p[2][y], p[3][y]))
    return lo + hi


def tile_2bpp(pat: np.ndarray) -> bytes:
    """One 8x8 tile, 2 bits per pixel: rows interleave planes 0/1 (the Game Boy layout)."""
    p = _planes(pat, 2)
    return bytes(b for y in range(8) for b in (p[0][y], p[1][y]))


def cgram_word(hexstr: str) -> int:
    """15-bit CGRAM word of a canonical color, q = e^-1(channel). ValueError for any other color."""
    return snes_word(hexstr)


def tilemap_word(tile: int, palette: int, priority: int = 0, flip_h: bool = False, flip_v: bool = False) -> int:
    if not 0 <= tile <= 0x3FF:
        raise ValueError(f"tile {tile} needs more than 10 bits")
    if not 0 <= palette <= 7:
        raise ValueError(f"palette {palette} is not 0-7")
    return (int(flip_v) << 15) | (int(flip_h) << 14) | ((priority & 1) << 13) | (palette << 10) | tile


@dataclass
class SnesObj:
    x: int
    y: int
    tile: int                   # 9-bit name: bit 8 selects the second OBJ name table
    palette: int
    priority: int = OBJ_PRIORITY
    flip_h: bool = False
    flip_v: bool = False
    large: bool = False


def oam_bytes(objs: list[SnesObj]) -> bytes:
    """544 bytes. Unused entries are parked at Y = 224, X = -128 (small): out of range on every visible line."""
    if len(objs) > MAX_OBJ:
        raise EncodeError("SNES-H9", f"{len(objs)} OBJs; OAM holds 128")
    lo = bytearray()
    hi = bytearray(32)
    entries = list(objs) + [SnesObj(PARK_X, PARK_Y, 0, 0, priority=0)] * (MAX_OBJ - len(objs))
    for i, o in enumerate(entries):
        if o.x == -256 or not -256 < o.x <= 255:
            raise EncodeError("SNES-H4", f"OBJ #{i} X = {o.x}: X is 9-bit and -256 is counted on every line")
        if not 0 <= o.y <= 255 or not 0 <= o.tile <= 0x1FF or not 0 <= o.palette <= 7:
            raise EncodeError("SNES-H4", f"OBJ #{i} cannot be encoded (Y {o.y}, tile {o.tile}, palette {o.palette})")
        attr = (int(o.flip_v) << 7) | (int(o.flip_h) << 6) | ((o.priority & 3) << 4) | (o.palette << 1) | (o.tile >> 8)
        lo += bytes([o.x & 0xFF, o.y, o.tile & 0xFF, attr])
        hi[i // 4] |= (((o.x >> 8) & 1) | (int(o.large) << 1)) << (2 * (i % 4))
    return bytes(lo + hi)


@dataclass
class SnesBytes:
    chr: dict[str, list[bytes]]           # BG layer -> per CHR set
    obj_chr: list[bytes]                  # per CHR set: the OBJ name tables in use
    maps: dict[str, list[bytes]]          # BG layer -> per state
    cgram: bytes
    oam: list[bytes]                      # per state
    layout: VramLayout
    registers: dict[str, int]
    chr_model: str
    tile_names: dict = field(default_factory=dict)    # (state, oam index) -> 9-bit name

    def chr_index(self, state: int) -> int:
        return state if self.chr_model == "per-frame" else 0

    def vram(self, state: int) -> bytes:
        """The 64 KiB VRAM image the viewer ROM uploads for one state (zeros elsewhere)."""
        v = bytearray(VRAM_BYTES)
        ci = self.chr_index(state)
        for layer, sets in self.chr.items():
            a, _ = self.layout.regions[f"{layer}_chr"]
            data = sets[ci]
            v[a:a + len(data)] = data
            a, _ = self.layout.regions[f"{layer}_map"]
            v[a:a + 2048] = self.maps[layer][state]
        if "obj" in self.layout.regions:
            a, _ = self.layout.regions["obj"]
            data = self.obj_chr[ci]
            v[a:a + len(data)] = data
        return bytes(v)

    def vram_json(self, scene: str, files: dict[str, str]) -> str:
        doc = self.layout.to_json()
        doc["scene"] = scene
        doc["files"] = files
        doc["registers"] = {k: f"${v:02X}" if v <= 0xFF else f"${v:03X}" for k, v in self.registers.items()}
        return json.dumps(doc, indent=2, sort_keys=True) + "\n"


def cgram_bytes(m: SceneModel) -> bytes:
    words = [0] * 256
    words[0] = cgram_word(m.backdrop_hex)
    for p, slots in enumerate(m.bg_slots):
        for i, c in enumerate(slots):
            if c is not None:
                words[16 * p + 1 + i] = cgram_word(hex_of(c))
    for p, slots in enumerate(m.obj_slots):
        for i, c in enumerate(slots):
            if c is not None:
                words[128 + 16 * p + 1 + i] = cgram_word(hex_of(c))
    return b"".join(w.to_bytes(2, "little") for w in words)


def palette_slices(m: SceneModel, cgram: bytes) -> dict[str, bytes]:
    """32-byte slices (16 words, entry 0 included) of every palette in use, for snes/pal/."""
    out = {}
    for kind, base, slots in (("bg", 0, m.bg_slots), ("obj", 256, m.obj_slots)):
        for p, s in enumerate(slots):
            if any(c is not None for c in s):
                out[f"{kind}{p}"] = cgram[base + 32 * p:base + 32 * p + 32]
    return out


def _check_model(m: SceneModel) -> None:
    """Independent re-check: everything the bytes must hold actually fits."""
    if not m.checked:
        raise EncodeError("SNES-H15", f"scene '{m.name}' was not analyzed")
    if m.spec.get("mode", 1) != 1:
        raise EncodeError("SNES-H15", "only BG mode 1 is encoded")
    for layer in m.layers:
        w, h = m.bg_sizes[layer]
        if any(p.shape != (MAP, MAP) for p in m.planes[layer]) or w > MAP or h > MAP:
            raise EncodeError("SNES-H15", f"{layer} ({w}x{h}) is not one 32x32 tilemap")
    bd = m.spec.get("backdrop")
    try:
        ok = bd is None or (isinstance(bd, int) and not isinstance(bd, bool) and 0 <= bd <= 0x7FFF) or \
            (isinstance(bd, str) and cgram_word(bd) >= 0)
        cgram_word(m.backdrop_hex)
    except ValueError:
        ok = False
    if not ok:
        raise EncodeError("SNES-H5", f"backdrop {bd!r} is not a 15-bit CGRAM color")
    for slots in m.bg_slots + m.obj_slots:
        for c in slots:
            if c is not None:
                try:
                    cgram_word(hex_of(c))
                except ValueError:
                    raise EncodeError("SNES-H5", f"palette color {hex_of(c)} is not a 15-bit color")
    qpal = [q_slots(m.bg_slots, q) for q in range(8)]
    for layer in m.layers:
        cap = TILE_CAP[layer]
        for s, plane in enumerate(m.planes[layer]):
            blocks = plane.reshape(32, 8, 32, 8).transpose(0, 2, 1, 3)
            for ty in range(32):
                for tx in range(32):
                    cs = color_set(blocks[ty, tx])
                    if len(cs) > cap:
                        raise EncodeError("SNES-H1", f"{layer} tile ({tx},{ty}) has {len(cs)} colors; {cap} fit")
                    if cs and assign(cs, qpal if layer == "bg3" else m.bg_slots) < 0:
                        raise EncodeError("SNES-H6", f"{layer} tile ({tx},{ty}) colors are in no BG palette")
        for ci, tiles in enumerate(m.bg_tiles[layer]):
            if len(tiles) > BG_TILES:
                raise EncodeError("SNES-H12", f"{layer} has {len(tiles)} tiles; 1024 fit")
    for pl in m.spec.get("obj") or []:
        opts = pl[3] if isinstance(pl, list) and len(pl) > 3 and isinstance(pl[3], dict) else {}
        if "size" in opts and tuple(int(v) for v in str(opts["size"]).split("x") if v.isdigit()) not in OBJ_SIZES:
            raise EncodeError("SNES-H2", f"{opts['size']!r} is not an OBJ size")
    if m.rejected:
        o = m.rejected[0]
        raise EncodeError("SNES-H4", f"OBJ at ({o.x},{o.top}) cannot be placed")
    allowed = DOCUMENTED_OBSEL + ((6, 7) if m.allow_undocumented else ())
    pair = OBSEL_PAIRS[m.obsel]
    for s, objs in enumerate(m.oam):
        if len(objs) > MAX_OBJ:
            raise EncodeError("SNES-H9", f"{len(objs)} OBJs; OAM holds 128")
        for o in objs:
            if (o.w, o.h) not in OBJ_SIZES:
                raise EncodeError("SNES-H2", f"{o.w}x{o.h} is not an OBJ size")
            if (o.w, o.h) not in pair or m.obsel not in allowed:
                raise EncodeError("SNES-H8", f"{o.w}x{o.h} is not in OBSEL {m.obsel}")
            if len(o.colors) > 15:
                raise EncodeError("SNES-H3", f"OBJ at ({o.x},{o.top}) has {len(o.colors)} colors")
            if not o.colors <= {c for c in m.obj_slots[o.palette] if c is not None}:
                raise EncodeError("SNES-H7", f"OBJ at ({o.x},{o.top}) needs colors outside its palette")
            if o.x == -256 or not -256 < o.x <= 255 or o.top < 0 or o.top + o.h > 256:
                raise EncodeError("SNES-H4", f"OBJ at ({o.x},{o.top}) cannot be placed")
            if not 0 <= o.tile <= 0x1FF:
                raise EncodeError("SNES-H13", f"OBJ at ({o.x},{o.top}) has no place in the OBJ name tables")
    if m.vram is None:
        raise EncodeError("SNES-H14", f"VRAM needs {m.vram_need} bytes with alignment; 65536 fit")


def _obj_tables(m: SceneModel, ci: int) -> bytes:
    tables = bytearray(8192 * m.obj_tables)
    for name, w, h, pat in m.obj_blocks[ci]:
        for ty in range(h // 8):
            for tx in range(w // 8):
                n = name + tx + 16 * ty
                if n >= 256 * m.obj_tables or (name % 16) + tx >= 16:
                    raise EncodeError("SNES-H13", "an OBJ block leaves its name table")
                tables[32 * n:32 * n + 32] = tile_4bpp(pat[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8])
    return bytes(tables)


def encode_scene(m: SceneModel) -> SnesBytes:
    _check_model(m)
    chr_ = {layer: [b"".join((tile_4bpp if BPP[layer] == 4 else tile_2bpp)(p) for p in tiles)
                    for tiles in m.bg_tiles[layer]] for layer in m.layers}
    prio = {layer: 0x2000 if (layer == "bg3" and m.bg3_front) else 0 for layer in m.layers}   # BG3 in front
    maps = {layer: [b"".join((int(w) | prio[layer]).to_bytes(2, "little") for w in words.ravel())
                    for words in m.maps[layer]] for layer in m.layers}
    obj_chr = [_obj_tables(m, ci) for ci in range(m.chr_sets)] if m.obj_tables else []
    layout = allocate_vram(VramRequest(bg_chr={layer: max(len(c) for c in chr_[layer]) for layer in m.layers},
                                       maps=list(m.layers), obj_tables=m.obj_tables))
    if layout is None:
        raise EncodeError("SNES-H14", "the VRAM layout does not fit 64 KiB")
    pair = OBSEL_PAIRS[m.obsel]
    oams, names = [], {}
    for s, objs in enumerate(m.oam):
        enc = []
        for i, o in enumerate(objs):
            enc.append(SnesObj(x=o.x, y=o.top, tile=o.tile, palette=o.palette, priority=OBJ_PRIORITY,
                               flip_h=o.flip_h, flip_v=o.flip_v, large=(o.w, o.h) == pair[1]))
            names[(s, i)] = o.tile
        oams.append(oam_bytes(enc))
    regs = {k: v for k, v in layout.registers.items() if not k.startswith("OBSEL_")}
    regs["BGMODE"] = 0x09 if m.bg3_front else 0x01        # bit 3: mode 1 BG3 priority
    regs["OBSEL"] = (m.obsel << 5) | (layout.registers["OBSEL_NN"] << 3) | layout.registers["OBSEL_BASE"]
    for layer in BG_LAYERS:
        regs[f"{layer.upper()}HOFS"] = 0
        regs[f"{layer.upper()}VOFS"] = VOFS
    return SnesBytes(chr=chr_, obj_chr=obj_chr, maps=maps, cgram=cgram_bytes(m), oam=oams, layout=layout,
                     registers=regs, chr_model=m.chr_model, tile_names=names)


# ---------------------------------------------------------------------------
# Text includes: ca65 + cc65
# ---------------------------------------------------------------------------


def _ident(s: str) -> str:
    out = "".join(c if c.isalnum() else "_" for c in s)
    return out if not out[0].isdigit() else "_" + out


def ca65_include(m: SceneModel, b: SnesBytes, files: dict[str, str], header: str) -> str:
    n = _ident(m.name)
    lines = [f"; {header}",
             f"; Scene '{m.name}': BG mode 1, OBSEL ${b.registers['OBSEL']:02X}, layers {', '.join(m.layers) or 'none'}.",
             "; DMA each blob to its VRAM word address (VMAIN = $80), .cgram through $2122, .oam through $2104,",
             f"; then write the register values below. BGnVOFS = ${b.registers['BG1VOFS']:03X}: the first visible "
             "line is scanline 1.", ""]
    labels = [(f"{n}_{k}", f) for k, f in files.items()]
    lines.append(".export " + ", ".join(lab for lab, _ in labels))
    lines += ["", '.segment "RODATA"']
    for lab, f in labels:
        lines.append(f'{lab}: .incbin "{f}"')
    lines += ["", "; VRAM word addresses and sizes in bytes"]
    for name, (a, size) in sorted(b.layout.regions.items(), key=lambda kv: kv[1][0]):
        lines.append(f"{n.upper()}_{name.upper()}_VRAM = ${a // 2:04X}")
        lines.append(f"{n.upper()}_{name.upper()}_BYTES = {size}")
    lines += ["", "; PPU register values"]
    for k, v in b.registers.items():
        lines.append(f"{n.upper()}_{k} = ${v:02X}" if v <= 0xFF else f"{n.upper()}_{k} = ${v:03X}")
    return "\n".join(lines) + "\n"


def c_header(m: SceneModel, b: SnesBytes, files: dict[str, bytes], header: str) -> str:
    n = _ident(m.name)
    guard = f"RETROGAZE_{n.upper()}_SNES_H"
    lines = [f"/* {header} */", f"#ifndef {guard}", f"#define {guard}", ""]
    for k, data in files.items():
        lines.append(f"extern const unsigned char {n}_{k}[{len(data)}];")
    lines.append("")
    for name, (a, _) in sorted(b.layout.regions.items(), key=lambda kv: kv[1][0]):
        lines.append(f"#define {n.upper()}_{name.upper()}_VRAM 0x{a // 2:04X}")
    for k, v in b.registers.items():
        lines.append(f"#define {n.upper()}_{k} 0x{v:02X}")
    lines += ["", f"#endif /* {guard} */", ""]
    return "\n".join(lines)


__all__ = ["EncodeError", "SnesBytes", "SnesObj", "encode_scene", "tile_4bpp", "tile_2bpp", "cgram_word",
           "tilemap_word", "oam_bytes", "cgram_bytes", "palette_slices", "ca65_include", "c_header"]

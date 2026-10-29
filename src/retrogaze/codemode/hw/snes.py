"""
SNES (S-PPU) console-like and console-legal checks, BG mode 1: BG1 and BG2 4bpp, BG3 2bpp, OBJ 4bpp.

Besides violations, the legal pass builds the hardware model of every scene (CGRAM palettes, BG patterns
and tilemap entries, OBJ blocks on the OBJ name tables, OAM, the VRAM layout) that ``encode/snes.py``
serializes and ``ppu_ref_snes.py`` renders back. The rules here and the encode + re-render round trip are
two independent answers to "is this legal"; tests require them to agree, and the emulator proof (Mesen 2)
is the third.

Hardware behavior modeled (SNESdev wiki; edge cases pinned against Mesen 2, see proof/TOOLS.md):
  * screen row r is scanline r + 1. BG line = scanline + BGnVOFS, so the viewer sets VOFS = $3FF;
    an OBJ with Y byte y is evaluated on scanline y and drawn from screen row y (Y = top row).
  * per line, OAM is scanned from index 0; the first 32 OBJs in range are kept ("range over" drops the
    rest). Their tiles are fetched from the last kept OBJ back to OAM #0, left to right on screen, only
    tiles that reach the screen; 34 are fetched ("time over" drops the rest: the frontmost OBJs' slivers).
  * the lower OAM index is in front; with OBJ priority 3 and BG tile priority 0 the order (front to back)
    is OBJ, BG1, BG2, BG3, backdrop.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ...console_profile import SNES_MODE1
from ...metadata import _check_palette_valid
from ...tiles import validate_tile_colors
from ..binding import SNES_LEVELS, snes_word, word_hex
from .common import (
    Asset, Violation, blame_for, color_set, hex_of, order_palette, pack_palettes, pad_to, rgb_of,
    rgb_plane, round_up,
)

W, H = 256, 224                     # the screen
MAP = 256                           # one 32x32 tilemap of 8x8 tiles
LEVEL_SET = frozenset(SNES_LEVELS)
BG_LAYERS = ("bg1", "bg2", "bg3")
BPP = {"bg1": 4, "bg2": 4, "bg3": 2}
TILE_CAP = {"bg1": 15, "bg2": 15, "bg3": 3}
OBJ_SIZES = ((8, 8), (16, 16), (32, 32), (64, 64), (16, 32), (32, 64))
OBSEL_PAIRS = {0: ((8, 8), (16, 16)), 1: ((8, 8), (32, 32)), 2: ((8, 8), (64, 64)), 3: ((16, 16), (32, 32)),
               4: ((16, 16), (64, 64)), 5: ((32, 32), (64, 64)), 6: ((16, 32), (32, 64)), 7: ((16, 32), (32, 32))}
DOCUMENTED_OBSEL = (0, 1, 2, 3, 4, 5)
OBJ_PRIORITY = 3                    # in front of every BG tile (all BG tiles use priority 0)
MAX_OBJ, PER_LINE, SLIVERS = 128, 32, 34
BG_TILES, OBJ_TILES = 1024, 512
VRAM_BYTES = 65536
CHR_MODELS = ("union", "per-frame")
LONE_OBJ_AT = (0, 0)
SIZE_RE = re.compile(r"^(\d+)x(\d+)$")


def size_name(wh) -> str:
    return f"{wh[0]}x{wh[1]}"


def on_screen_cols(x: int, w: int) -> list[int]:
    """Tile columns of an OBJ at X = x that reach the screen (the ones the PPU fetches). X != -256."""
    return [c for c in range(w // 8) if x + 8 * c + 7 >= 0 and x + 8 * c <= W - 1]


def on_screen_slivers(x: int, w: int) -> int:
    return len(on_screen_cols(x, w))


def export_image(asset: Asset, frame: np.ndarray, bg: bool) -> np.ndarray:
    """The image code mode exports and validates: OBJ canvases padded to whole 8x8 tiles (SNES-L2)."""
    if bg:
        return frame
    return pad_to(frame, round_up(frame.shape[1], 8), round_up(frame.shape[0], 8))


# ---------------------------------------------------------------------------
# Console-like (per image)
# ---------------------------------------------------------------------------


def like_checks(asset: Asset, bg: bool) -> tuple[list[Violation], list[dict]]:
    vs: list[Violation] = []
    info: list[dict] = []
    for k, frame in enumerate(asset.frames):
        fh, fw = frame.shape[:2]
        a = frame[..., 3]
        partial = np.argwhere((a > 0) & (a < 255))
        if len(partial):
            px, bl = blame_for(asset, ((x, y) for y, x in partial), k)
            vs.append(Violation("SNES-L4", f"{len(partial)} pixel(s) have partial alpha", asset=asset.name, frame=k,
                                pixels=px, blame=bl, hint="use fully opaque colors or '_' (transparent)"))
        opaque = a > 0
        chan_ok = np.isin(frame[..., :3], list(LEVEL_SET)).all(axis=2)
        off = np.argwhere(opaque & ~chan_ok)
        palette_ok = _check_palette_valid(Image.fromarray(frame, "RGBA"), SNES_MODE1)
        if len(off) or not palette_ok:
            plane = rgb_plane(frame)
            cols = sorted({hex_of(int(plane[y, x])) for y, x in off})
            px, bl = blame_for(asset, ((x, y) for y, x in off), k)
            vs.append(Violation("SNES-L1", f"{len(cols)} color(s) are not 15-bit SNES colors: {', '.join(cols[:6])}",
                                asset=asset.name, frame=k, colors=cols, pixels=px, blame=bl,
                                hint="bind colors with snes(r5, g5, b5); hex literals must be canonical SNES colors"))
        if bg:
            if fw % 8 or fh % 8:
                vs.append(Violation("SNES-L2", f"BG image is {fw}x{fh}; BG width and height must be multiples of 8",
                                    asset=asset.name, frame=k, found=[fw, fh], limit=8,
                                    blame=[{"loc": asset.loc, "op": f"{asset.kind} '{asset.name}'", "pixels": fw * fh}]))
                continue
            img = frame
        else:
            img = export_image(asset, frame, bg=False)
            if img.shape[:2] != frame.shape[:2] and k == 0:
                info.append({"rule": "SNES-L2", "asset": asset.name,
                             "padded": [[fw, fh], [img.shape[1], img.shape[0]]]})
        layers = [l for name, l in (asset.layers[k] if asset.layers else []) if name.startswith("obj:")]
        checked = [export_image(asset, l, bg) for l in layers] if layers and not bg else [img]
        plane = rgb_plane(frame)
        for im in checked:
            rep = validate_tile_colors(Image.fromarray(im, "RGBA"), max_colors=SNES_MODE1.max_colors_per_tile,
                                       tile_size=8)
            for t in rep.violating_tiles:
                tile = plane[t.y:t.y + 8, t.x:t.x + 8]
                counts = Counter(int(c) for c in tile.ravel() if c >= 0)
                minority = {c for c, _ in counts.most_common()[SNES_MODE1.max_colors_per_tile:]}
                pts = [(t.x + x, t.y + y) for y in range(tile.shape[0]) for x in range(tile.shape[1])
                       if int(tile[y, x]) in minority]
                px, bl = blame_for(asset, pts, k)
                vs.append(Violation("SNES-L3", f"tile at ({t.x},{t.y}) has {len(t.colors)} opaque colors; the limit "
                                    "is 16", asset=asset.name, frame=k, where={"tile": [t.x // 8, t.y // 8]},
                                    found=len(t.colors), limit=16, colors=[hex_of(c) for c in counts],
                                    pixels=px, blame=bl))
    return vs, info


# ---------------------------------------------------------------------------
# Palette packing: 4bpp BG (8 x 15) jointly with BG3 (8 x 3 inside CGRAM 0-31)
# ---------------------------------------------------------------------------


def _maximal(sets) -> list[frozenset]:
    uniq = sorted({frozenset(s) for s in sets if s}, key=lambda s: (-len(s), sorted(s)))
    keep: list[frozenset] = []
    for s in uniq:
        if not any(s <= k for k in keep):
            keep.append(s)
    return keep


def _joint_milp(sets4: list[frozenset], sets2: list[frozenset]):
    """Exact joint packing. BG3 palette q occupies CGRAM 4q+1..4q+3, i.e. three slots of 4bpp palette q // 4.
    Returns (extra colors per 4bpp palette, colors per BG3 palette) or None if no packing exists."""
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix

    c4 = sorted(set().union(*sets4)) if sets4 else []
    c2 = sorted(set().union(*sets2)) if sets2 else []
    n4, n2 = len(sets4), len(sets2)
    nv = 0

    def block(n):
        nonlocal nv
        start, nv = nv, nv + n
        return start

    X4 = block(n4 * 8)            # set s -> 4bpp palette p
    X2 = block(n2 * 8)            # BG3 set t -> BG3 palette q
    Y3 = block(len(c2) * 8)       # color c in BG3 palette q
    WF = block(len(c4) * 8)       # color c in a free slot of 4bpp palette p
    i4 = {c: i for i, c in enumerate(c4)}
    i2 = {c: i for i, c in enumerate(c2)}
    rows: list[dict[int, float]] = []
    lo, hi = [], []

    def row(coefs, a, b):
        rows.append(coefs)
        lo.append(a)
        hi.append(b)

    for s in range(n4):
        row({X4 + s * 8 + p: 1 for p in range(8)}, 1, 1)
    for t in range(n2):
        row({X2 + t * 8 + q: 1 for q in range(8)}, 1, 1)
    for t, st in enumerate(sets2):
        for c in st:
            for q in range(8):
                row({Y3 + i2[c] * 8 + q: 1, X2 + t * 8 + q: -1}, 0, np.inf)
    if c2:
        for q in range(8):
            row({Y3 + i2[c] * 8 + q: 1 for c in c2}, 0, 3)
    for s, st in enumerate(sets4):
        for c in st:
            for p in range(8):
                coefs = {WF + i4[c] * 8 + p: 1, X4 + s * 8 + p: -1}
                if p < 2 and c in i2:
                    for q in range(4 * p, 4 * p + 4):
                        coefs[Y3 + i2[c] * 8 + q] = 1
                row(coefs, 0, np.inf)
    for p in range(8):
        coefs = {WF + i4[c] * 8 + p: 1 for c in c4}
        if p < 2:
            for c in c2:
                for q in range(4 * p, 4 * p + 4):
                    coefs[Y3 + i2[c] * 8 + q] = coefs.get(Y3 + i2[c] * 8 + q, 0) + 1
        if coefs:
            row(coefs, 0, 15)
    A = lil_matrix((len(rows), max(nv, 1)))
    for r, coefs in enumerate(rows):
        for j, v in coefs.items():
            A[r, j] = v
    res = milp(c=np.zeros(max(nv, 1)), constraints=LinearConstraint(A.tocsr(), lo, hi),
               integrality=np.ones(max(nv, 1)), bounds=Bounds(0, 1))
    if res.status != 0 or res.x is None:
        return None
    x = res.x
    extra = [{c for c in c4 if x[WF + i4[c] * 8 + p] > 0.5} for p in range(8)]
    q_sets = [{c for c in c2 if x[Y3 + i2[c] * 8 + q] > 0.5} for q in range(8)]
    # keep only what the sets need (the solver may switch on unused colors)
    need4 = [set() for _ in range(8)]
    for s, st in enumerate(sets4):
        p = int(np.argmax([x[X4 + s * 8 + p] for p in range(8)]))
        need4[p] |= st
    need2 = [set() for _ in range(8)]
    for t, st in enumerate(sets2):
        q = int(np.argmax([x[X2 + t * 8 + q] for q in range(8)]))
        need2[q] |= st
    q_sets = [q_sets[q] & need2[q] if need2[q] else set() for q in range(8)]
    extra = [(need4[p] - set().union(*(q_sets[q] for q in range(4 * p, 4 * p + 4)) if p < 2 else set()))
             for p in range(8)]
    return extra, q_sets


def bg_slots_from(extra: list[set], q_sets: list[set]) -> list[list[int | None]] | None:
    """8 palettes x 15 slots (slot i = color index i + 1). BG3 palette q fills slots 4(q%4)..+2 of q // 4."""
    slots: list[list[int | None]] = [[None] * 15 for _ in range(8)]
    for q, qs in enumerate(q_sets):
        if len(qs) > 3:
            return None
        p, base = q // 4, 4 * (q % 4)
        for i, c in enumerate(order_palette(qs)):
            slots[p][base + i] = c
    for p, ex in enumerate(extra):
        have = {c for c in slots[p] if c is not None}
        free = [i for i in range(15) if slots[p][i] is None]
        add = order_palette(set(ex) - have)
        if len(add) > len(free):
            return None
        for i, c in zip(free, add):
            slots[p][i] = c
    return slots


def pack_bg(sets4, sets2):
    """Slots for 4bpp BG palettes 0-7 that cover every 4bpp tile set and every BG3 tile set, or None."""
    w4, w2 = _maximal(sets4), _maximal(sets2)
    if any(len(s) > 15 for s in w4) or any(len(s) > 3 for s in w2):
        return None
    if not w2:
        p4 = pack_palettes(w4, 8, 15)
        return None if p4 is None else bg_slots_from([set(p) for p in p4] + [set()] * (8 - len(p4)), [set()] * 8)
    # Fast path: BG1/BG2 in palettes 2-7, BG3 alone in CGRAM 0-31.
    p4 = pack_palettes(w4, 6, 15)
    p2 = pack_palettes(w2, 8, 3)
    if p4 is not None and p2 is not None:
        extra = [set(), set()] + [set(p) for p in p4] + [set()] * (6 - len(p4))
        return bg_slots_from(extra, [set(p) for p in p2] + [set()] * (8 - len(p2)))
    if p2 is None or len(set().union(*w4, *w2)) > 8 * 15:
        return None
    got = _joint_milp(w4, w2)
    return None if got is None else bg_slots_from(*got)


def pins_to_slots(pins: list) -> tuple[list[list[int | None]], list[str]]:
    """Pinned palettes (lists of snes() hex or 15-bit words; 16 entries = with index 0) -> slots + problems."""
    slots, bad = [], []
    for p in (pins or [])[:8]:
        entries = list(p[1:] if len(p) == 16 else p)[:15]
        row: list[int | None] = []
        for v in entries:
            c = _color_entry(v)
            if c is None:
                bad.append(repr(v))
            row.append(c)
        slots.append(row + [None] * (15 - len(row)))
    while len(slots) < 8:
        slots.append([None] * 15)
    return slots, bad


def _color_entry(v) -> int | None:
    try:
        if isinstance(v, bool):
            return None
        if isinstance(v, int):
            return rgb_of(word_hex(v)) if 0 <= v <= 0x7FFF else None
        if isinstance(v, str) and v.startswith("#"):
            snes_word(v)
            return rgb_of(v)
    except ValueError:
        return None
    return None


def q_slots(slots, q: int) -> list[int | None]:
    return slots[q // 4][4 * (q % 4):4 * (q % 4) + 3]


def assign(colors: frozenset, palettes) -> int:
    for i, p in enumerate(palettes):
        if colors <= {c for c in p if c is not None}:
            return i
    return -1


def index_pattern(block: np.ndarray, slots) -> np.ndarray:
    """4-bit (or 2-bit) color indices of an RGB block (-1 = transparent = 0) under one palette's slots."""
    out = np.zeros(block.shape, dtype=np.uint8)
    for i, c in enumerate(slots):
        if c is None:
            continue
        hit = (block == c) & (out == 0)
        if hit.any():
            out[hit] = i + 1
    return out


def _flips(p: np.ndarray, square: bool = True):
    yield p, False, False
    yield p[:, ::-1], True, False
    if square:
        yield p[::-1, :], False, True
        yield p[::-1, ::-1], True, True


# ---------------------------------------------------------------------------
# VRAM allocation (SNES-H14)
# ---------------------------------------------------------------------------


@dataclass
class VramRequest:
    bg_chr: dict[str, int]          # layer -> CHR bytes
    maps: list[str]                 # layers with a 32x32 tilemap (2 KiB each)
    obj_tables: int                 # OBJ name tables in use (0, 1 or 2; 8 KiB each)


@dataclass
class VramLayout:
    regions: dict[str, tuple[int, int]]     # name -> (byte address, bytes)
    registers: dict[str, int]
    used: int

    def to_json(self) -> dict:
        return {"regions": {k: {"address": f"${a:04X}", "word_address": f"${a // 2:04X}", "bytes": n}
                            for k, (a, n) in sorted(self.regions.items(), key=lambda kv: kv[1][0])},
                "registers": {k: (f"${v:02X}" if k not in ("BG1VOFS", "BG2VOFS", "BG3VOFS") else f"${v:03X}")
                              for k, v in self.registers.items()},
                "used": self.used, "limit": VRAM_BYTES}


def allocate_vram(req: VramRequest) -> VramLayout | None:
    """First fit, largest alignment first: the OBJ tables (16 KiB boundary; the second table right after the
    first, OBSEL name select 0), BG CHR (8 KiB boundaries), tilemaps (2 KiB boundaries). None if 64 KiB
    cannot hold it."""
    items = []
    if req.obj_tables:
        items.append(("obj", 8192 * req.obj_tables, 16384))
    for layer in BG_LAYERS:
        if req.bg_chr.get(layer):
            items.append((f"{layer}_chr", req.bg_chr[layer], 8192))
    for layer in BG_LAYERS:
        if layer in req.maps:
            items.append((f"{layer}_map", 2048, 2048))
    taken: list[tuple[int, int]] = []
    regions: dict[str, tuple[int, int]] = {}
    for name, size, align in items:
        addr = 0
        while addr + size <= VRAM_BYTES:
            if all(addr + size <= a or addr >= a + n for a, n in taken):
                break
            addr += align
        else:
            return None
        taken.append((addr, size))
        regions[name] = (addr, size)
    regs = {"BGMODE": 0x01, "TM": 0x10}
    for i, layer in enumerate(BG_LAYERS):
        if f"{layer}_map" in regions:
            regs[f"{layer.upper()}SC"] = (regions[f"{layer}_map"][0] >> 11) << 2
            regs["TM"] |= 1 << i
    base = lambda layer: regions[f"{layer}_chr"][0] >> 13 if f"{layer}_chr" in regions else 0  # noqa: E731
    regs["BG12NBA"] = (base("bg2") << 4) | base("bg1")
    regs["BG34NBA"] = base("bg3")
    regs["OBSEL_BASE"] = regions["obj"][0] >> 14 if "obj" in regions else 0
    regs["OBSEL_NN"] = 0
    return VramLayout(regions, regs, sum(n for _, n in regions.values()))


# ---------------------------------------------------------------------------
# Hardware model
# ---------------------------------------------------------------------------


@dataclass
class Obj:
    """One OBJ as placed on screen."""
    asset: str
    frame: int
    placement: int
    x: int
    top: int
    w: int
    h: int
    pix: np.ndarray                  # (h, w) int32 rgb or -1
    to_asset: tuple                  # (cx, cy, flip_x, flip_y, img_w, img_h): OBJ pixel -> asset coords
    colors: frozenset
    palette: int = -1
    tile: int = -1                   # 9-bit OBJ name (bit 8 = second name table)
    flip_h: bool = False
    flip_v: bool = False
    pattern: np.ndarray | None = None   # (h, w) color indices as shown on screen
    block: int = -1

    def asset_px(self, u: int, v: int) -> tuple[int, int]:
        cx, cy, fx, fy, iw, ih = self.to_asset
        x, y = cx + u, cy + v
        return (iw - 1 - x if fx else x, ih - 1 - y if fy else y)


@dataclass
class SceneModel:
    name: str
    declared: bool
    loc: str | None
    spec: dict
    console: str = "snes"
    mode: int = 1
    states: int = 1
    chr_model: str = "union"
    chr_sets: int = 1
    obsel: int = 0
    allow_undocumented: bool = False
    backdrop: int = 0
    layers: list[str] = field(default_factory=list)
    planes: dict[str, list[np.ndarray]] = field(default_factory=dict)       # layer -> per state (256, 256) rgb
    bg_sizes: dict[str, tuple[int, int]] = field(default_factory=dict)    # layer -> largest (w, h) drawn
    bg_slots: list[list[int | None]] = field(default_factory=lambda: [[None] * 15 for _ in range(8)])
    obj_slots: list[list[int | None]] = field(default_factory=lambda: [[None] * 15 for _ in range(8)])
    tile_pal: dict[str, list[np.ndarray]] = field(default_factory=dict)     # layer -> per state (32, 32) palette
    bg_tiles: dict[str, list[list[np.ndarray]]] = field(default_factory=dict)   # layer -> per CHR set: patterns
    maps: dict[str, list[np.ndarray]] = field(default_factory=dict)         # layer -> per state (32, 32) words
    oam: list[list[Obj]] = field(default_factory=list)                      # per state, OAM order
    rejected: list[Obj] = field(default_factory=list)                       # OBJs the hardware cannot place (SNES-H4)
    obj_blocks: list[list[tuple[int, int, int, np.ndarray]]] = field(default_factory=list)  # per CHR set: (name, w, h, pattern)
    obj_tables: int = 0
    vram: VramLayout | None = None
    vram_need: int = 0
    composites: list[np.ndarray] = field(default_factory=list)              # per state (224, 256, 4)
    drops: list[list[tuple[int, int | None, list[int]]]] = field(default_factory=list)  # (oam, column or None, lines)
    line_stats: list[dict] = field(default_factory=list)
    assets: list[str] = field(default_factory=list)
    metatiles: list | None = None
    violations: list[Violation] = field(default_factory=list)
    info: list[dict] = field(default_factory=list)
    checked: bool = False

    @property
    def legal(self) -> bool:
        return self.checked and not any(v.severity == "error" for v in self.violations)

    @property
    def backdrop_hex(self) -> str:
        return hex_of(self.backdrop)

    @property
    def pair(self) -> tuple:
        return OBSEL_PAIRS[self.obsel]

    def chr_index(self, state: int) -> int:
        return state if self.chr_model == "per-frame" else 0

    def bg3_palette_of_tile(self, state: int, ty: int, tx: int) -> int:
        return int(self.tile_pal["bg3"][state][ty, tx])

    def layer_tile_colors(self, layer: str, state: int, ty: int, tx: int) -> frozenset:
        return color_set(self.planes[layer][state][8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8])

    def predicted_drops(self, state: int) -> set[tuple[int, int]]:
        """Screen pixels of the OBJ slivers the PPU drops (SNES-H10 range, SNES-H11 time), on their lines."""
        out = set()
        for i, col, lines in self.drops[state]:
            o = self.oam[state][i]
            cols = range(o.w) if col is None else range(8 * col, 8 * col + 8)
            for y in lines:
                for u in cols:
                    x = o.x + u
                    if 0 <= x < W and o.pix[y - o.top, u] >= 0:
                        out.add((x, y))
        return out


# ---------------------------------------------------------------------------
# OBJ decomposition
# ---------------------------------------------------------------------------


def _cells(plane: np.ndarray, ox: int, oy: int, cw: int, ch: int):
    """(cx, cy, block) of a cw x ch grid anchored at (ox, oy) that holds opaque pixels."""
    ys, xs = np.nonzero(plane >= 0)
    if not len(xs):
        return []
    out = []
    for gy in range(oy + ((ys.min() - oy) // ch) * ch, ys.max() + 1, ch):
        for gx in range(ox + ((xs.min() - ox) // cw) * cw, xs.max() + 1, cw):
            blk = np.full((ch, cw), -1, dtype=np.int32)
            y0, y1, x0, x1 = max(gy, 0), min(gy + ch, plane.shape[0]), max(gx, 0), min(gx + cw, plane.shape[1])
            if y1 > y0 and x1 > x0:
                blk[y0 - gy:y1 - gy, x0 - gx:x1 - gx] = plane[y0:y1, x0:x1]
            if (blk >= 0).any():
                out.append((gx, gy, blk))
    return out


def decompose(plane: np.ndarray, small, large, forced=None) -> list[tuple[int, int, int, int, np.ndarray]]:
    """Cover the opaque pixels with OBJs of the pair's sizes (or only the forced size): a large OBJ where at
    least half of its small sub-cells hold pixels and it has at most 15 colors, else its non-empty small
    sub-cells. The grid is anchored at the asset origin or at the opaque bounding box, whichever is cheaper
    (fewest over-15-color OBJs, OBJs, tiles; ties keep the asset origin)."""
    ys, xs = np.nonzero(plane >= 0)
    if not len(xs):
        return []
    anchors = [(0, 0)]
    if (int(xs.min()), int(ys.min())) != (0, 0):
        anchors.append((int(xs.min()), int(ys.min())))
    best, best_key = None, None
    for ox, oy in anchors:
        objs = []
        if forced:
            for gx, gy, blk in _cells(plane, ox, oy, *forced):
                objs.append((gx, gy, forced[0], forced[1], blk))
        else:
            (sw, sh), (lw, lh) = small, large
            per = (lw // sw) * (lh // sh)
            for gx, gy, blk in _cells(plane, ox, oy, lw, lh):
                subs = [(gx + sx, gy + sy, blk[sy:sy + sh, sx:sx + sw]) for sy in range(0, lh, sh)
                        for sx in range(0, lw, sw)]
                subs = [s for s in subs if (s[2] >= 0).any()]
                if 2 * len(subs) >= per and len(color_set(blk)) <= 15:
                    objs.append((gx, gy, lw, lh, blk))
                else:
                    objs += [(sx, sy, sw, sh, b.copy()) for sx, sy, b in subs]
        key = (sum(1 for o in objs if len(color_set(o[4])) > 15), len(objs), sum(o[2] * o[3] for o in objs))
        if best_key is None or key < best_key:
            best, best_key = objs, key
    return best


def _flip(img: np.ndarray, flip: str | None) -> np.ndarray:
    out = img
    if flip and "x" in flip:
        out = out[:, ::-1]
    if flip and "y" in flip:
        out = out[::-1, :]
    return np.ascontiguousarray(out)


# ---------------------------------------------------------------------------
# Scene analysis (console-legal)
# ---------------------------------------------------------------------------


class SceneAnalyzer:
    def __init__(self, assets: dict[str, Asset], model: SceneModel, pins: dict | None):
        self.assets = assets
        self.m = model
        self.pins = model.spec.get("palettes") or pins or {}
        self.v = model.violations
        self.post_reported = False

    def add(self, rule, message, lead=False, **kw):
        here = {"loc": self.m.loc, "op": "rg.scene" if self.m.declared else "asset", "pixels": 0}
        bl = kw.pop("blame", None) or []
        if lead or not bl:
            bl = [here] + [b for b in bl if b.get("loc") != here["loc"]]
        self.v.append(Violation(rule, message, scene=self.m.name, blame=bl, **kw))

    def frame(self, asset: Asset, state: int) -> int:
        return state % len(asset.frames)

    # -- main ----------------------------------------------------------------

    def run(self) -> SceneModel:
        m, spec = self.m, self.m.spec
        mode = spec.get("mode", 1)
        if mode != 1:
            self.add("SNES-H15", f"mode {mode!r}: the legal tier targets BG mode 1 (BG1/BG2 4bpp, BG3 2bpp)",
                     found=mode, limit=1)
        chr_spec = spec.get("chr", "union")
        m.chr_model = chr_spec if isinstance(chr_spec, str) else (chr_spec or {}).get("model", "union")
        if m.chr_model not in CHR_MODELS:
            self.add("SNES-H14", f"chr must be one of {', '.join(CHR_MODELS)}, got {m.chr_model!r}")
            m.chr_model = "union"
        m.allow_undocumented = spec.get("allowUndocumentedObjSizes") is True
        placements = spec.get("obj") or []
        names = [spec[k] for k in BG_LAYERS if isinstance(spec.get(k), str)] + \
                [p[0] for p in placements if isinstance(p, list) and p]
        missing = [n for n in names if n not in self.assets]
        for n in missing:
            self.add("SNES-H15", f"rg.scene '{m.name}' references unknown asset '{n}'")
        if missing:
            m.checked = True
            return m
        m.assets = list(dict.fromkeys(names))
        m.states = max([len(self.assets[n].frames) for n in m.assets] or [1])
        m.chr_sets = m.states if m.chr_model == "per-frame" else 1
        m.layers = [k for k in BG_LAYERS if isinstance(spec.get(k), str)]

        self.backdrop()
        for layer in m.layers:
            m.planes[layer] = [self.bg_plane(layer, s) for s in range(m.states)]
        self.solve_bg()
        objs = self.objs(placements)
        self.solve_obj(objs)
        self.bg_tiles()
        self.obj_tiles()
        self.lines()
        self.vram()
        self.composites()
        m.checked = True
        return m

    # -- backdrop ----------------------------------------------------------------

    def backdrop(self):
        m = self.m
        declared = m.spec.get("backdrop")
        c = 0
        if declared is not None:
            got = _color_entry(declared)
            if got is None:
                self.add("SNES-H5", f"backdrop {declared!r} is not a 15-bit SNES color (CGRAM words are 0-$7FFF)",
                         found=declared, limit="$0000-$7FFF")
            else:
                c = got
        pinned = self.pins.get("bg") if isinstance(self.pins, dict) else None
        if pinned and isinstance(pinned[0], list) and len(pinned[0]) == 16:
            p0 = _color_entry(pinned[0][0])
            if declared is None and p0 is not None:
                c = p0
            elif p0 != c:
                self.add("SNES-H5", f"backdrop {hex_of(c)} conflicts with the pinned BG palette 0 entry "
                         f"{pinned[0][0]!r}: CGRAM 0 is one color", found=pinned[0][0], limit=hex_of(c))
        m.backdrop = c

    # -- BG ------------------------------------------------------------------

    def bg_plane(self, layer: str, state: int) -> np.ndarray:
        plane = np.full((MAP, MAP), -1, dtype=np.int32)
        a = self.assets[self.m.spec[layer]]
        img = a.frames[self.frame(a, state)]
        ih, iw = img.shape[:2]
        pw, ph = self.m.bg_sizes.get(layer, (0, 0))
        self.m.bg_sizes[layer] = (max(pw, iw), max(ph, ih))
        if state == 0 and (iw > MAP or ih > MAP):
            self.add("SNES-H15", f"{layer.upper()} '{a.name}' is {iw}x{ih}; one 32x32 tilemap shows at most 256x256",
                     asset=a.name, found=[iw, ih], limit=[MAP, MAP],
                     blame=[{"loc": a.loc, "op": f"{a.kind} '{a.name}'", "pixels": iw * ih}])
        src = rgb_plane(img)
        plane[:min(ih, MAP), :min(iw, MAP)] = src[:MAP, :MAP]
        return plane

    def tile_sets(self):
        """(layer, state, ty, tx, colors) of every BG tile with opaque pixels."""
        for layer in self.m.layers:
            for s, plane in enumerate(self.m.planes[layer]):
                blocks = plane.reshape(32, 8, 32, 8).transpose(0, 2, 1, 3)
                for ty in range(32):
                    for tx in range(32):
                        b = blocks[ty, tx]
                        if (b >= 0).any():
                            yield layer, s, ty, tx, color_set(b)

    def bg_blame(self, layer, s, ty, tx, colors=None):
        a = self.assets[self.m.spec[layer]]
        region = self.m.planes[layer][s][8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8]
        pts = [(8 * tx + x, 8 * ty + y) for y in range(8) for x in range(8)
               if region[y, x] >= 0 and (colors is None or int(region[y, x]) in colors)]
        px, bl = blame_for(a, pts, self.frame(a, s))
        return a, px, bl

    def solve_bg(self):
        m = self.m
        tiles = list(self.tile_sets())
        sets4, sets2, first = [], [], {}
        for layer, s, ty, tx, cs in tiles:
            cap = TILE_CAP[layer]
            if len(cs) > cap:
                region = m.planes[layer][s][8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8]
                counts = Counter(int(c) for c in region.ravel() if c >= 0)
                a, px, bl = self.bg_blame(layer, s, ty, tx, {c for c, _ in counts.most_common()[cap:]})
                self.add("SNES-H1", f"{layer.upper()} tile ({tx},{ty}) has {len(cs)} opaque colors; a "
                         f"{BPP[layer]}bpp tile shows {cap}", asset=a.name, frame=s,
                         where={"layer": layer, "tile": [tx, ty]}, found=len(cs), limit=cap,
                         colors=[hex_of(c) for c in sorted(cs)], pixels=px, blame=bl)
                continue
            (sets2 if layer == "bg3" else sets4).append(cs)
            first.setdefault((layer == "bg3", cs), (layer, s, ty, tx))
        pinned = self.pins.get("bg") if isinstance(self.pins, dict) else None
        if pinned:
            slots, bad = pins_to_slots(pinned)
            for b in bad:
                self.add("SNES-H5", f"pinned BG palette entry {b} is not a 15-bit SNES color", found=b)
            fit = all(assign(s, slots) >= 0 for s in sets4) and \
                all(assign(s, [q_slots(slots, q) for q in range(8)]) >= 0 for s in sets2)
            if not fit:
                core = [(False, s) for s in dict.fromkeys(sets4) if assign(s, slots) < 0] + \
                       [(True, s) for s in dict.fromkeys(sets2) if assign(s, [q_slots(slots, q) for q in range(8)]) < 0]
                self.report_h6(core, first, pinned=True)
        else:
            slots = pack_bg(sets4, sets2)
            if slots is None:
                self.report_h6(self.bg_core(sets4, sets2), first, pinned=False)
                slots = [[None] * 15 for _ in range(8)]
        m.bg_slots = slots

    def bg_core(self, sets4, sets2):
        items = [(False, s) for s in _maximal(sets4)] + [(True, s) for s in _maximal(sets2)]
        if len(items) > 48:     # deletion filter would take too long: report every maximal set
            return items
        core = list(items)
        for it in list(items):
            trial = [x for x in core if x != it]
            if pack_bg([s for b, s in trial if not b], [s for b, s in trial if b]) is None:
                core = trial
        return core

    def report_h6(self, core, first, pinned):
        for is_bg3, s in core:
            key = (is_bg3, s)
            if key not in first:            # a maximal set stands for its subsets: blame the first tile with it
                key = next(k for k in first if k[0] == is_bg3 and k[1] <= s)
            layer, st, ty, tx = first[key]
            a, px, bl = self.bg_blame(layer, st, ty, tx)
            why = "do not fit the pinned BG palettes" if pinned else \
                f"belong to a set of {len(core)} tile color sets that cannot share 8 palettes of 15 " \
                "(BG3's 8 x 3 inside CGRAM 0-31)"
            self.add("SNES-H6", f"{layer.upper()} tile ({tx},{ty}) colors {why}", asset=a.name, frame=st,
                     where={"layer": layer, "tile": [tx, ty], "core": len(core)}, limit="8 x 15",
                     colors=[hex_of(c) for c in sorted(s)], pixels=px, blame=bl,
                     hint="these tiles together need more palettes; merge colors across them or move one to "
                          "another layer")

    # -- OBJ -------------------------------------------------------------------

    def placement_sources(self, pl, state):
        name = pl[0]
        a = self.assets[name]
        k = self.frame(a, state)
        layers = a.layers[k] if a.layers else None
        if layers:
            return a, k, [img for lname, img in layers if lname.startswith("obj:")]
        return a, k, [a.frames[k]]

    def objs(self, placements) -> list[list[Obj]]:
        """Decompose every placement for every state, choosing the OBSEL pair (SNES-H2, H3, H8)."""
        m = self.m
        parsed = []
        for pi, pl in enumerate(placements):
            if not isinstance(pl, list) or len(pl) < 3:
                self.add("SNES-H15", f"obj placement #{pi + 1} must be [asset, x, y, {{opts}}]",
                         blame=[{"loc": m.loc, "op": "rg.scene obj", "pixels": 0}])
                continue
            opts = pl[3] if len(pl) > 3 and isinstance(pl[3], dict) else {}
            forced = None
            if "size" in opts:
                mt = SIZE_RE.match(str(opts["size"]))
                wh = (int(mt[1]), int(mt[2])) if mt else None
                if wh not in OBJ_SIZES:
                    self.add("SNES-H2", f"placement of '{pl[0]}' asks for {opts['size']!r} OBJs; SNES OBJ sizes are "
                             "8x8, 16x16, 32x32, 64x64 (and the undocumented 16x32, 32x64)", asset=pl[0],
                             found=opts["size"], limit=[size_name(s) for s in OBJ_SIZES],
                             hint="there is no 8x16 OBJ on the SNES" if wh == (8, 16) else None)
                    continue
                forced = wh
            parsed.append((pi, pl, opts, forced))
        forced_sizes = sorted({f for *_, f in parsed if f}, key=lambda s: (s[0] * s[1], s))
        pinned = m.spec.get("obsel")
        if pinned is not None and pinned not in OBSEL_PAIRS:
            self.add("SNES-H8", f"obsel {pinned!r} is not an OBSEL size setting (0-7)", found=pinned, limit="0-7")
            pinned = None
        allowed = DOCUMENTED_OBSEL + ((6, 7) if m.allow_undocumented else ())
        candidates = [pinned] if pinned is not None else list(allowed)
        feasible = [o for o in candidates if all(f in OBSEL_PAIRS[o] for f in forced_sizes)]
        limit = [f"{size_name(a)}/{size_name(b)}" for a, b in (OBSEL_PAIRS[o] for o in allowed)]
        problem = None
        if pinned is not None and pinned not in allowed:
            problem = (f"obsel {pinned} selects the undocumented {size_name(OBSEL_PAIRS[pinned][0])}/"
                       f"{size_name(OBSEL_PAIRS[pinned][1])} sizes; set allowUndocumentedObjSizes: true to use them",
                       [size_name(x) for x in OBSEL_PAIRS[pinned]])
        elif not feasible:
            names = [size_name(x) for x in forced_sizes]
            if not m.allow_undocumented and any(all(f in OBSEL_PAIRS[o] for f in forced_sizes) for o in (6, 7)):
                msg = (f"OBJ size(s) {', '.join(names)} exist only in the undocumented OBSEL pairs 6-7; set "
                       "allowUndocumentedObjSizes: true to use them")
            elif pinned is not None:
                msg = (f"OBJ sizes {', '.join(names)} are not all in OBSEL {pinned} "
                       f"({size_name(OBSEL_PAIRS[pinned][0])}/{size_name(OBSEL_PAIRS[pinned][1])})")
            else:
                msg = f"the frame uses OBJ sizes {', '.join(names)}; OBSEL gives two sizes per frame"
            problem = (msg, names)
        if problem:
            self.add("SNES-H8", problem[0], lead=True, found=problem[1], limit=limit)
            best = pinned if pinned is not None else 0
            best_objs = self.decompose_all(parsed, OBSEL_PAIRS[best])
        else:
            best, best_key, best_objs = None, None, None
            for o in feasible:
                objs = self.decompose_all(parsed, OBSEL_PAIRS[o])
                key = self.cost(objs) + (o,)
                if best_key is None or key < best_key:
                    best, best_key, best_objs = o, key, objs
        m.obsel = best
        for objs in best_objs:
            for o in objs:
                if len(o.colors) > 15:
                    counts = Counter(int(v) for v in o.pix.ravel() if v >= 0)
                    px, bl = self.obj_pixels(o, {c for c, _ in counts.most_common()[15:]})
                    self.add("SNES-H3", f"{o.w}x{o.h} OBJ at screen ({o.x},{o.top}) of '{o.asset}' has "
                             f"{len(o.colors)} opaque colors; one OBJ uses one palette of 15", asset=o.asset,
                             frame=o.frame, where={"screen": [o.x, o.top], "obj_in_asset": list(o.to_asset[:2]),
                                                   "size": size_name((o.w, o.h))},
                             found=len(o.colors), limit=15, colors=[hex_of(c) for c in sorted(o.colors)],
                             pixels=px, blame=bl, hint="drop a color in this OBJ, or ask for smaller OBJs "
                                                        "({ size } or obsel)")
        return best_objs

    def decompose_all(self, parsed, pair) -> list[list[Obj]]:
        out = []
        for s in range(self.m.states):
            objs: list[Obj] = []
            for pi, pl, opts, forced in parsed:
                a, k, sources = self.placement_sources(pl, s)
                if a.layers and a.post and s == 0 and not self.post_reported:
                    self.post_reported = True
                    self.add("SNES-H2", f"'{a.name}' uses obj:<n> layers together with post-processing "
                             "(mx/outline/flip/crop); layered sprites must be drawn without it", asset=a.name,
                             blame=[{"loc": a.loc, "op": f"{a.kind} '{a.name}'", "pixels": 0}])
                flip = opts.get("flip")
                for img in sources:
                    fimg = _flip(export_image(a, img, bg=False), flip)
                    ih, iw = fimg.shape[:2]
                    for cx, cy, w, h, pix in decompose(rgb_plane(fimg), pair[0], pair[1], forced):
                        objs.append(Obj(asset=a.name, frame=k, placement=pi, x=int(pl[1]) + cx, top=int(pl[2]) + cy,
                                        w=w, h=h, pix=pix, colors=color_set(pix),
                                        to_asset=(cx, cy, "x" in (flip or ""), "y" in (flip or ""), iw, ih)))
            out.append(objs)
        return out

    def cost(self, objs_by_state) -> tuple:
        bad = unplaceable = n = tiles = range_over = time_over = 0
        for objs in objs_by_state:
            vis = [o for o in objs if self.visible(o)]
            bad += sum(1 for o in vis if len(o.colors) > 15)
            unplaceable += sum(1 for o in vis if o.top < 0 or o.top + o.h > 256 or o.x == -256)
            n = max(n, len(vis))
            tiles += sum(o.w * o.h // 64 for o in vis)
            for y in range(H):
                on = [o for o in vis if o.top <= y < o.top + o.h]
                range_over += max(0, len(on) - PER_LINE)
                time_over += max(0, sum(on_screen_slivers(o.x, o.w) for o in on[:PER_LINE]) - SLIVERS)
        # hard limits first (SNES-H3, H4, H9-H11, H13), then fewer OBJs (OAM slots, per-line range), then fewer
        # tiles (VRAM, slivers)
        return (bad, unplaceable, max(0, n - MAX_OBJ), range_over, time_over, max(0, tiles - OBJ_TILES), n, tiles)

    @staticmethod
    def visible(o: Obj) -> bool:
        ys, xs = np.nonzero(o.pix >= 0)
        sx, sy = xs + o.x, ys + o.top
        return bool(((sx >= 0) & (sx < W) & (sy >= 0) & (sy < H)).any())

    def obj_pixels(self, o: Obj, colors=None, rows=None, cols=None):
        a = self.assets[o.asset]
        pts = [o.asset_px(u, v) for v in range(o.h) for u in range(o.w)
               if o.pix[v, u] >= 0 and (colors is None or int(o.pix[v, u]) in colors)
               and (rows is None or v in rows) and (cols is None or u in cols)]
        return blame_for(a, pts, o.frame)

    def solve_obj(self, objs_by_state):
        m = self.m
        # screen bounds and OAM order (last painted = OAM #0, frontmost)
        for s, objs in enumerate(objs_by_state):
            oam = []
            for o in reversed(objs):
                if not self.visible(o):
                    m.info.append({"offscreen_obj": [o.asset, o.x, o.top], "state": s})
                    continue
                if o.top < 0 or o.top + o.h > 256 or o.x == -256:
                    px, bl = self.obj_pixels(o)
                    why = "X = -256 is counted on every line it covers" if o.x == -256 else \
                        "Y is 8-bit and its rows must stay in 0-255; an OBJ that straddles the top edge (or runs " \
                        "past line 255) wraps to the top of the screen"
                    self.add("SNES-H4", lead=True, message=f"{o.w}x{o.h} OBJ of '{o.asset}' at screen ({o.x},{o.top}) "
                             f"cannot be placed: {why}", asset=o.asset, frame=o.frame,
                             where={"screen": [o.x, o.top]}, pixels=px, blame=bl)
                    m.rejected.append(o)
                    continue
                oam.append(o)
            if len(oam) > MAX_OBJ:
                self.add("SNES-H9", f"{len(oam)} OBJs in frame {s}; OAM holds 128", lead=True, frame=s,
                         found=len(oam), limit=MAX_OBJ)
            m.oam.append(oam)
        pinned = self.pins.get("obj") if isinstance(self.pins, dict) else None
        sets = [o.colors for objs in m.oam for o in objs if len(o.colors) <= 15]
        if pinned:
            slots, bad = pins_to_slots(pinned)
            for b in bad:
                self.add("SNES-H7", f"pinned OBJ palette entry {b} is not a 15-bit SNES color", found=b)
            misfit = list(dict.fromkeys(s for s in sets if assign(s, slots) < 0))
        else:
            packed = pack_palettes(sets, 8, 15)
            misfit = []
            if packed is None:
                uniq = _maximal(sets)
                misfit = uniq if len(uniq) > 48 else _core(uniq, 8, 15)
                packed = []
            slots = bg_slots_from([set(p) for p in packed] + [set()] * (8 - len(packed)), [set()] * 8)
        reported = set()
        for objs in m.oam:
            for o in objs:
                if any(o.colors <= c for c in misfit) and o.colors not in reported:
                    reported.add(o.colors)
                    px, bl = self.obj_pixels(o)
                    self.add("SNES-H7", f"OBJ colors {', '.join(hex_of(x) for x in sorted(o.colors)[:6])}"
                             f"{'...' if len(o.colors) > 6 else ''} belong to a set of {len(misfit)} OBJs that "
                             "cannot share 8 OBJ palettes of 15" if not pinned else
                             "OBJ colors do not fit the pinned OBJ palettes", asset=o.asset, frame=o.frame,
                             where={"screen": [o.x, o.top], "core": len(misfit)}, limit="8 x 15",
                             colors=[hex_of(x) for x in sorted(o.colors)], pixels=px, blame=bl)
        m.obj_slots = slots
        for objs in m.oam:
            for o in objs:
                o.palette = max(0, assign(o.colors, slots))
                o.pattern = index_pattern(o.pix, slots[o.palette])

    # -- tiles ---------------------------------------------------------------

    def bg_tiles(self):
        m = self.m
        q_pal = [q_slots(m.bg_slots, q) for q in range(8)]
        for layer in m.layers:
            m.bg_tiles[layer] = [[] for _ in range(m.chr_sets)]
            index = [dict() for _ in range(m.chr_sets)]
            m.tile_pal[layer], m.maps[layer] = [], []
            for s, plane in enumerate(m.planes[layer]):
                ci = m.chr_index(s)
                pal = np.zeros((32, 32), dtype=np.int32)
                words = np.zeros((32, 32), dtype=np.int32)
                blocks = plane.reshape(32, 8, 32, 8).transpose(0, 2, 1, 3)
                for ty in range(32):
                    for tx in range(32):
                        b = blocks[ty, tx]
                        cs = color_set(b)
                        if layer == "bg3":
                            p = max(0, assign(cs, q_pal))
                            pat = index_pattern(b, q_pal[p])
                        else:
                            p = max(0, assign(cs, m.bg_slots))
                            pat = index_pattern(b, m.bg_slots[p])
                        for v, fh, fv in _flips(pat):
                            key = np.ascontiguousarray(v).tobytes()
                            if key in index[ci]:
                                t = index[ci][key]
                                break
                        else:
                            t, fh, fv = len(m.bg_tiles[layer][ci]), False, False
                            index[ci][pat.tobytes()] = t
                            m.bg_tiles[layer][ci].append(pat)
                        pal[ty, tx] = p
                        words[ty, tx] = (int(fv) << 15) | (int(fh) << 14) | (p << 10) | (t & 0x3FF)
                m.tile_pal[layer].append(pal)
                m.maps[layer].append(words)
            asset = self.assets[m.spec[layer]]
            for ci, ts in enumerate(m.bg_tiles[layer]):
                if len(ts) > BG_TILES:
                    where = f" (CHR set {ci})" if m.chr_sets > 1 else ""
                    self.add("SNES-H12", f"{layer.upper()} needs {len(ts)} unique tiles{where}; tilemap entries "
                             "address 1024 (10-bit tile numbers)", found=len(ts), limit=BG_TILES,
                             blame=[{"loc": asset.loc, "op": f"{layer.upper()} '{asset.name}'", "pixels": 0}],
                             hint="reuse identical 8x8 tiles (flips count as the same tile)")

    def obj_tiles(self):
        m = self.m
        m.obj_blocks = [[] for _ in range(m.chr_sets)]
        tables_used = 0
        for ci in range(m.chr_sets):
            uniq: dict[bytes, int] = {}
            blocks: list[tuple[int, int, np.ndarray]] = []
            members: list[list[Obj]] = []
            states = [s for s in range(m.states) if m.chr_index(s) == ci]
            for s in states:
                for o in m.oam[s]:
                    square = o.w == o.h          # V flip of 16x32 / 32x64 OBJs does not swap the halves
                    for v, fh, fv in _flips(o.pattern, square):
                        key = bytes([o.w, o.h]) + np.ascontiguousarray(v).tobytes()
                        if key in uniq:
                            o.block, o.flip_h, o.flip_v = uniq[key], fh, fv
                            break
                    else:
                        o.block, o.flip_h, o.flip_v = len(blocks), False, False
                        uniq[bytes([o.w, o.h]) + o.pattern.tobytes()] = o.block
                        blocks.append((o.w, o.h, o.pattern))
                        members.append([])
                    members[o.block].append(o)
            names = place_obj_blocks([(w // 8, h // 8) for w, h, _ in blocks])
            need = sum(w * h // 64 for w, h, _ in blocks)
            if names is None:
                names = [-1] * len(blocks)
                obj_names = list(dict.fromkeys(o.asset for s in states for o in m.oam[s]))
                self.add("SNES-H13", lead=True, message=f"the OBJs need {need} tiles{' (CHR set %d)' % ci if m.chr_sets > 1 else ''}; "
                         "the two OBJ name tables hold 512 (each large OBJ as one block on the 16-column grid)",
                         found=need, limit=OBJ_TILES,
                         blame=[{"loc": self.assets[n].loc, "op": f"OBJ '{n}'", "pixels": 0} for n in obj_names],
                         hint="reuse OBJ shapes (flips are free) or use smaller OBJs")
            for b, (w, h, pat) in enumerate(blocks):
                m.obj_blocks[ci].append((names[b], w, h, pat))
                for o in members[b]:
                    o.tile = names[b]
            used = [n for n in names if n >= 0]
            tables_used = max(tables_used, (2 if any(n >= 256 for n in used) else 1) if used else 0)
        m.obj_tables = tables_used

    # -- OAM lines -------------------------------------------------------------

    def lines(self):
        m = self.m
        for s, oam in enumerate(m.oam):
            drops: dict[tuple[int, int | None], list[int]] = {}
            stats = {"per_line": 0, "slivers": 0}
            range_by_line, time_by_line = {}, {}
            for y in range(H):
                on = [i for i, o in enumerate(oam) if o.top <= y < o.top + o.h and not (o.x + o.w <= 0 or o.x > 255)]
                stats["per_line"] = max(stats["per_line"], len(on))
                kept, lost = on[:PER_LINE], on[PER_LINE:]
                fetch = [(i, c) for i in reversed(kept) for c in on_screen_cols(oam[i].x, oam[i].w)]
                stats["slivers"] = max(stats["slivers"], len(fetch))
                for i in lost:
                    drops.setdefault((i, None), []).append(y)
                for i, c in fetch[SLIVERS:]:
                    drops.setdefault((i, c), []).append(y)
                if lost:
                    range_by_line[y] = (tuple(lost), len(on))
                if len(fetch) > SLIVERS:
                    time_by_line[y] = (tuple(sorted(fetch[SLIVERS:])), len(fetch))
            m.drops.append([(i, c, ys) for (i, c), ys in sorted(drops.items(), key=lambda kv: (kv[0][0], kv[0][1] or -1))])
            m.line_stats.append(stats)
            for rule, by_line, limit in (("SNES-H10", range_by_line, PER_LINE), ("SNES-H11", time_by_line, SLIVERS)):
                for y0, y1, (dropped, found) in _runs(by_line):
                    if rule == "SNES-H10":
                        where = {"oam": list(dropped), "lines": [y0, y1]}
                        first = oam[dropped[0]]
                        px, bl = self.obj_pixels(first, rows=set(range(y0 - first.top, y1 - first.top + 1)))
                        msg = (f"{found} OBJs on lines {y0}-{y1}; the PPU keeps the first 32 in OAM order and drops "
                               f"OAM #{', #'.join(map(str, dropped))} there")
                    else:
                        where = {"dropped": [list(d) for d in dropped], "lines": [y0, y1]}
                        first = oam[dropped[0][0]]
                        px, bl = self.obj_pixels(first, rows=set(range(y0 - first.top, y1 - first.top + 1)),
                                                 cols=set(range(8 * dropped[0][1], 8 * dropped[0][1] + 8)))
                        msg = (f"{found} 8-px slivers on lines {y0}-{y1}; the PPU fetches 34, from the highest OAM "
                               f"index down, so {len(dropped)} sliver(s) of the frontmost OBJ(s) are dropped "
                               f"(OAM #{', #'.join(str(i) for i, _ in dropped)})")
                    self.add(rule, msg, lead=True, asset=first.asset, frame=s, where=where, found=found,
                             limit=limit, pixels=px, blame=bl,
                             hint="spread the OBJs vertically, use fewer or narrower OBJs on these lines")

    # -- VRAM ------------------------------------------------------------------

    def vram(self):
        m = self.m
        chr_bytes = {layer: max(len(t) for t in m.bg_tiles[layer]) * (32 if BPP[layer] == 4 else 16)
                     for layer in m.layers}
        req = VramRequest(bg_chr=chr_bytes, maps=list(m.layers), obj_tables=m.obj_tables)
        need = sum(chr_bytes.values()) + 2048 * len(m.layers) + 8192 * m.obj_tables
        m.vram_need = need
        m.vram = allocate_vram(req)
        if m.vram is None:
            parts = ", ".join([f"{k.upper()} CHR {v} bytes" for k, v in chr_bytes.items()] +
                              [f"{len(m.layers)} tilemaps {2048 * len(m.layers)} bytes"] +
                              ([f"OBJ tables {8192 * m.obj_tables} bytes"] if m.obj_tables else []))
            blame = [{"loc": self.assets[m.spec[layer]].loc, "op": f"{layer.upper()} '{m.spec[layer]}'", "pixels": 0}
                     for layer in m.layers]
            self.add("SNES-H14", lead=True, message=f"VRAM needs {need} bytes ({parts}) with BG CHR on 8 KiB, maps on 2 KiB and the OBJ "
                     "base on 16 KiB boundaries; VRAM is 65536 bytes", found=need, limit=VRAM_BYTES, blame=blame,
                     hint="reuse tiles, drop a layer, or use fewer unique tiles")

    # -- composite -------------------------------------------------------------

    def composites(self):
        m = self.m
        for s in range(m.states):
            scr = np.full((H, W), m.backdrop, dtype=np.int64)
            for layer in ("bg3", "bg2", "bg1"):
                if layer in m.layers:
                    p = m.planes[layer][s][:H, :W]
                    scr = np.where(p >= 0, p, scr)
            for o in reversed(m.oam[s]):        # paint order: highest OAM index first
                for v in range(o.h):
                    y = o.top + v
                    if not 0 <= y < H:
                        continue
                    row = o.pix[v]
                    for u in range(o.w):
                        x = o.x + u
                        if 0 <= x < W and row[u] >= 0:
                            scr[y, x] = row[u]
            img = np.zeros((H, W, 4), dtype=np.uint8)
            img[..., 0] = (scr >> 16) & 255
            img[..., 1] = (scr >> 8) & 255
            img[..., 2] = scr & 255
            img[..., 3] = 255
            m.composites.append(img)


def _runs(by_line: dict) -> list[tuple[int, int, tuple]]:
    """Group consecutive lines with the same value into (first, last, value)."""
    out = []
    for y in sorted(by_line):
        val = by_line[y]
        if out and out[-1][1] == y - 1 and out[-1][2][0] == val[0]:
            out[-1] = (out[-1][0], y, (val[0], max(out[-1][2][1], val[1])))
        else:
            out.append((y, y, val))
    return out


def _core(sets: list[frozenset], P: int, K: int) -> list[frozenset]:
    core = list(sets)
    for s in list(sets):
        trial = [x for x in core if x != s]
        if pack_palettes(trial, P, K) is None:
            core = trial
    return core


def place_obj_blocks(blocks: list[tuple[int, int]]) -> list[int] | None:
    """OBJ name of every block (tile columns x rows) in two 16x16-tile name tables; each block sits at
    N, N+1, ..., N+16, ... aligned to its own size, largest first. None if they do not fit."""
    grid = [np.zeros((16, 16), dtype=bool) for _ in range(2)]
    names = [-1] * len(blocks)
    order = sorted(range(len(blocks)), key=lambda i: (-blocks[i][0] * blocks[i][1], -blocks[i][1], -blocks[i][0], i))
    for i in order:
        bw, bh = blocks[i]
        done = False
        for t in range(2):
            for row in range(0, 16 - bh + 1, bh):
                for col in range(0, 16 - bw + 1, bw):
                    if not grid[t][row:row + bh, col:col + bw].any():
                        grid[t][row:row + bh, col:col + bw] = True
                        names[i] = 256 * t + 16 * row + col
                        done = True
                        break
                if done:
                    break
            if done:
                break
        if not done:
            return None
    return names


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@dataclass
class SnesAnalysis:
    like: list[Violation]
    like_info: list[dict]
    scenes: list[SceneModel]
    images: dict[str, list[np.ndarray]]
    roles: dict[str, str]


def analyze(assets: dict[str, Asset], scenes: list[dict], tilesets: list[dict], pins: dict | None) -> SnesAnalysis:
    tileset_names = {t["name"] for t in tilesets}
    roles = {n: ("bg" if (a.kind == "scene" or n in tileset_names) else "obj") for n, a in assets.items()}
    for s in scenes:
        for k in BG_LAYERS:
            if isinstance(s["spec"].get(k), str) and s["spec"][k] in roles:
                roles[s["spec"][k]] = "bg"
    like: list[Violation] = []
    info: list[dict] = []
    images: dict[str, list[np.ndarray]] = {}
    for n, a in assets.items():
        vs, inf = like_checks(a, roles[n] == "bg")
        like += vs
        info += inf
        images[n] = [export_image(a, f, roles[n] == "bg") for f in a.frames]

    models: list[SceneModel] = []
    referenced: set[str] = set()
    for s in scenes:
        spec = s["spec"]
        referenced |= {spec.get(k) for k in BG_LAYERS} | {p[0] for p in spec.get("obj", []) if isinstance(p, list) and p}
        models.append(SceneModel(name=s["name"], declared=True, loc=s.get("loc"), spec=spec))
    taken = {s["name"] for s in scenes}

    def lone_name(n):
        return n if n not in taken else f"lone-{n}"

    for t in tilesets:
        opts = dict(t.get("opts") or {})
        spec = {"bg1": t["name"], "tileset": opts}
        if "backdrop" in opts:
            spec["backdrop"] = opts["backdrop"]
        models.append(SceneModel(name=lone_name(t["name"]), declared=False, loc=t.get("loc"), spec=spec))
    for n, a in assets.items():
        if not a.exported or n in referenced or n in tileset_names:
            continue
        spec = {"bg1": n} if roles[n] == "bg" else {"obj": [[n, LONE_OBJ_AT[0], LONE_OBJ_AT[1]]]}
        models.append(SceneModel(name=lone_name(n), declared=False, loc=a.loc, spec=spec))

    like_bad = {v.asset for v in like if v.severity == "error"}
    for m in models:
        involved = {m.spec.get(k) for k in BG_LAYERS} | {p[0] for p in m.spec.get("obj", []) if isinstance(p, list) and p}
        blocked = sorted(x for x in involved if x in like_bad)
        if blocked:
            m.info.append({"blocked_by_like": blocked})
            continue
        SceneAnalyzer(assets, m, pins).run()
    return SnesAnalysis(like=like, like_info=info, scenes=models, images=images, roles=roles)

"""
NES (NTSC 2C02) console-like and console-legal checks.

Besides violations, the legal pass builds the hardware model of every scene
(palettes, nametable, attribute areas, pattern tiles, OAM) that
``encode/nes.py`` serializes and ``ppu_ref.py`` renders back. Rules here and
the encode + re-render round trip are two independent answers to "is this
legal"; tests require them to agree.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

import numpy as np
from PIL import Image

from ...console_profile import NES
from ...metadata import _check_palette_valid
from ...tiles import validate_tile_colors
from ..binding import BLACK, NES_CANON_BYTE, NES_COLORS, nes_byte_hex
from .common import (
    Asset, Violation, assign_palette, blame_for, color_set, hex_of, order_palette, pack_palettes,
    pad_to, rgb_of, rgb_plane, round_up, unsat_core,
)

W, H = 256, 240
AREA = 16
COLS, ROWS = 32, 30
LEGAL_RGB = frozenset(rgb_of(h) for h in NES_COLORS)
BLACK_RGB = rgb_of(BLACK)
CHR_MODELS = ("nrom-split", "shared", "chr-ram")
LONE_OBJ_AT = (8, 8)


def canon_byte(rgb: int) -> int:
    return NES_CANON_BYTE[hex_of(rgb)]


def obj_role(asset: Asset) -> bool:
    return asset.kind in ("sprite", "anim")


def export_image(asset: Asset, frame: np.ndarray, bg: bool) -> np.ndarray:
    """The image code mode exports and validates: OBJ canvases padded to whole 8x8 tiles (NES-L2)."""
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
            vs.append(Violation("NES-L4", f"{len(partial)} pixel(s) have partial alpha", asset=asset.name, frame=k,
                                pixels=px, blame=bl, hint="use fully opaque colors or '_' (transparent)"))
        plane = rgb_plane(frame)
        off = np.argwhere((plane >= 0) & ~np.isin(plane, list(LEGAL_RGB)))
        palette_ok = _check_palette_valid(Image.fromarray(frame, "RGBA"), NES)
        if len(off) or not palette_ok:
            cols = sorted({hex_of(int(plane[y, x])) for y, x in off})
            px, bl = blame_for(asset, ((x, y) for y, x in off), k)
            vs.append(Violation("NES-L1", f"{len(cols)} color(s) are not NES colors: {', '.join(cols[:6])}",
                                asset=asset.name, frame=k, colors=cols, pixels=px, blame=bl,
                                hint="bind colors with nes(byte); hex literals must be NES colors"))
        if bg:
            if fw % 8 or fh % 8:
                vs.append(Violation("NES-L2", f"BG image is {fw}x{fh}; BG width and height must be multiples of 8",
                                    asset=asset.name, frame=k, found=[fw, fh], limit=8,
                                    blame=[{"loc": asset.loc, "op": f"{asset.kind} '{asset.name}'", "pixels": fw * fh}]))
                continue
            img = frame
        else:
            img = export_image(asset, frame, bg=False)
            if img.shape[:2] != frame.shape[:2] and k == 0:
                info.append({"rule": "NES-L2", "asset": asset.name,
                             "padded": [[fw, fh], [img.shape[1], img.shape[0]]]})
        # Layered sprites (obj:<n>): each layer is what one set of hardware tiles holds, so the
        # per-tile cap applies per layer, not to the composite of overlapping sprites.
        layers = [l for name, l in (asset.layers[k] if asset.layers else []) if name.startswith("obj:")]
        checked = [export_image(asset, l, bg) for l in layers] if layers and not bg else [img]
        violating = []
        for im in checked:
            rep = validate_tile_colors(Image.fromarray(im, "RGBA"), max_colors=NES.max_colors_per_tile, tile_size=8)
            violating += rep.violating_tiles
        for t in violating:
            tile = plane[t.y:t.y + 8, t.x:t.x + 8]
            counts = Counter(int(c) for c in tile.ravel() if c >= 0)
            minority = {c for c, _ in counts.most_common()[NES.max_colors_per_tile:]}
            pts = [(t.x + x, t.y + y) for y in range(tile.shape[0]) for x in range(tile.shape[1])
                   if int(tile[y, x]) in minority]
            px, bl = blame_for(asset, pts, k)
            vs.append(Violation("NES-L3", f"tile at ({t.x},{t.y}) has {len(t.colors)} opaque colors; the limit is 4",
                                asset=asset.name, frame=k, where={"tile": [t.x // 8, t.y // 8]},
                                found=len(t.colors), limit=4, colors=[hex_of(c) for c in counts],
                                pixels=px, blame=bl))
    return vs, info


# ---------------------------------------------------------------------------
# Hardware model
# ---------------------------------------------------------------------------


@dataclass
class Cell:
    """One hardware sprite as placed on screen."""
    asset: str
    frame: int
    x: int
    top: int
    h: int
    pix: np.ndarray                  # (h, 8) int32 rgb or -1
    to_asset: tuple                  # (cx, cy, flip_x, flip_y, img_w, img_h): cell pixel -> asset coords
    colors: frozenset
    placement: int
    palette: int = -1
    tile: int = -1
    table: int = 1
    flip_h: bool = False
    flip_v: bool = False
    pattern: np.ndarray | None = None

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
    sprite_size: str = "8x8"
    chr_model: str = "nrom-split"
    left8: bool = True
    states: int = 1
    backdrop: int = BLACK_RGB
    backdrop_byte: int = 0x0F
    bg_palettes: list[list[int]] = field(default_factory=list)       # rgb, 3 per palette
    bg_palette_bytes: list[list[int]] = field(default_factory=list)
    obj_palettes: list[list[int]] = field(default_factory=list)
    obj_palette_bytes: list[list[int]] = field(default_factory=list)
    nametables: list[np.ndarray] = field(default_factory=list)       # per state (30, 32) tile index
    attributes: list[np.ndarray] = field(default_factory=list)       # per state (15, 16) palette
    bg_tiles: list[list[np.ndarray]] = field(default_factory=list)   # per CHR set: (8, 8) uint8 patterns
    obj_tiles: list[list[np.ndarray]] = field(default_factory=list)  # per CHR set: (h, 8) uint8 patterns
    chr_sets: int = 1
    oam: list[list[Cell]] = field(default_factory=list)              # per state, OAM order
    rejected: list[Cell] = field(default_factory=list)               # cells the hardware cannot place (NES-H13)
    composites: list[np.ndarray] = field(default_factory=list)       # per state (240, 256, 4) expected screen
    bg_screens: list[np.ndarray] = field(default_factory=list)       # per state (240, 256) BG rgb, backdrop filled
    assets: list[str] = field(default_factory=list)
    metatiles: list[tuple[int, int, int, int, int]] | None = None
    violations: list[Violation] = field(default_factory=list)
    info: list[dict] = field(default_factory=list)
    checked: bool = False

    @property
    def legal(self) -> bool:
        return self.checked and not any(v.severity == "error" for v in self.violations)

    def chr_index(self, state: int) -> int:
        return state if self.chr_model == "chr-ram" else 0


def _palette_entry(v) -> int:
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.startswith("#"):
        return NES_CANON_BYTE.get(v.upper(), -1)
    return -1


def _flip(img: np.ndarray, flip: str | None) -> np.ndarray:
    if not flip:
        return img
    out = img
    if "x" in flip:
        out = out[:, ::-1]
    if "y" in flip:
        out = out[::-1, :]
    return np.ascontiguousarray(out)


def _unique_blocks(cells) -> int:
    seen: set[bytes] = set()
    n = 0
    for _, _, b in cells:
        variants = [b, b[:, ::-1], b[::-1, :], b[::-1, ::-1]]
        if not any(np.ascontiguousarray(v).tobytes() in seen for v in variants):
            seen.add(b.tobytes())
            n += 1
    return n


def best_grid(plane: np.ndarray, ch: int) -> list[tuple[int, int, np.ndarray]]:
    """Cells (cx, cy, pix) covering the opaque pixels. Searches the 8 x ch grid offsets for the
    layout with the fewest over-color cells, then fewest sprites per scanline, fewest sprites,
    fewest pattern tiles (flips dedup), and finally prefers the grid aligned to the asset origin."""
    ys, xs = np.nonzero(plane >= 0)
    if not len(xs):
        return []
    bx0, by0, bx1, by1 = xs.min(), ys.min(), xs.max(), ys.max()
    best_key, best_cells = None, None
    for sy in range(ch):
        for sx in range(8):
            ox, oy = int(bx0 - sx), int(by0 - sy)
            ncols = (bx1 - ox) // 8 + 1
            nrows = (by1 - oy) // ch + 1
            region = np.full((nrows * ch, ncols * 8), -1, dtype=np.int32)
            region[by0 - oy:by1 - oy + 1, bx0 - ox:bx1 - ox + 1] = plane[by0:by1 + 1, bx0:bx1 + 1]
            blocks = region.reshape(nrows, ch, ncols, 8).transpose(0, 2, 1, 3)
            cells, bad, per_row = [], 0, []
            for j in range(nrows):
                n = 0
                for i in range(ncols):
                    b = blocks[j, i]
                    if (b >= 0).any():
                        n += 1
                        if len(color_set(b)) > 3:
                            bad += 1
                        cells.append((ox + 8 * i, oy + ch * j, b.copy()))
                per_row.append(n)
            key = (bad, max(per_row), len(cells), _unique_blocks(cells), int(ox % 8 != 0) + int(oy % ch != 0), sy, sx)
            if best_key is None or key < best_key:
                best_key, best_cells = key, cells
    return best_cells


# ---------------------------------------------------------------------------
# Scene analysis (console-legal)
# ---------------------------------------------------------------------------


class SceneAnalyzer:
    def __init__(self, assets: dict[str, Asset], model: SceneModel, pins: dict | None):
        self.assets = assets
        self.m = model
        self.pins = model.spec.get("palettes") or pins or {}
        self.v = model.violations

    # -- helpers -----------------------------------------------------------

    def add(self, rule, message, lead=False, **kw):
        """Record a violation. Scene-caused ones (placement, budget) lead with the rg.scene line."""
        here = {"loc": self.m.loc, "op": "rg.scene" if self.m.declared else "asset", "pixels": 0}
        bl = kw.pop("blame", None) or []
        if lead or not bl:
            bl = [here] + [b for b in bl if b.get("loc") != here["loc"]]
        self.v.append(Violation(rule, message, scene=self.m.name, blame=bl, **kw))

    def frame(self, asset: Asset, state: int) -> int:
        return state % len(asset.frames)

    # -- main --------------------------------------------------------------

    def run(self) -> SceneModel:
        m, spec = self.m, self.m.spec
        m.sprite_size = spec.get("objSize", "8x8")
        if m.sprite_size not in ("8x8", "8x16"):
            self.add("NES-H10", f"objSize must be \"8x8\" or \"8x16\", got {m.sprite_size!r}", found=m.sprite_size)
            m.sprite_size = "8x8"
        chr_spec = spec.get("chr", "nrom-split")
        m.chr_model = chr_spec if isinstance(chr_spec, str) else chr_spec.get("model", "nrom-split")
        if m.chr_model not in CHR_MODELS:
            self.add("NES-H11", f"chr must be one of {', '.join(CHR_MODELS)}, got {m.chr_model!r}")
            m.chr_model = "nrom-split"
        m.left8 = spec.get("left8", True) is not False
        bg_name = spec.get("bg")
        placements = spec.get("obj") or []
        names = ([bg_name] if bg_name else []) + [p[0] for p in placements if isinstance(p, list) and p]
        missing = [n for n in names if n not in self.assets]
        for n in missing:
            self.add("NES-H13", f"rg.scene '{m.name}' references unknown asset '{n}'")
        if missing:
            m.checked = True
            return m
        m.assets = list(dict.fromkeys(names))
        m.states = max([len(self.assets[n].frames) for n in m.assets] or [1])
        ch = 16 if m.sprite_size == "8x16" else 8

        bg_planes = [self.bg_plane(bg_name, s) for s in range(m.states)]
        cells = [self.obj_cells(placements, s, ch) for s in range(m.states)]
        self.solve_bg(bg_planes, bg_name)
        self.solve_obj(cells)
        self.tiles(bg_planes, cells, ch)
        self.oam_and_lines(cells, ch)
        self.composites(bg_planes, cells)
        if not m.left8:
            self.left_column(bg_planes, cells)
        m.checked = True
        return m

    # -- BG ------------------------------------------------------------------

    def bg_plane(self, bg_name: str | None, state: int) -> np.ndarray:
        plane = np.full((H, W), -1, dtype=np.int32)
        if not bg_name:
            return plane
        a = self.assets[bg_name]
        k = self.frame(a, state)
        img = a.frames[k]
        at = self.m.spec.get("bgAt", [0, 0])
        bx, by = int(at[0]), int(at[1])
        if state == 0 and (bx % AREA or by % AREA):
            self.add("NES-H13", f"bgAt ({bx},{by}) must be a multiple of 16 (attribute areas)", asset=bg_name,
                     found=[bx, by], blame=[{"loc": self.m.loc, "op": "rg.scene bgAt", "pixels": 0}])
        ih, iw = img.shape[:2]
        if state == 0 and (bx < 0 or by < 0 or bx + iw > W or by + ih > H):
            self.add("NES-H13", f"BG '{bg_name}' ({iw}x{ih} at {bx},{by}) does not fit one 256x240 nametable",
                     asset=bg_name, found=[iw, ih], limit=[W, H],
                     blame=[{"loc": a.loc, "op": f"{a.kind} '{a.name}'", "pixels": iw * ih}])
        src = rgb_plane(img)
        x0, y0 = max(bx, 0), max(by, 0)
        x1, y1 = min(bx + iw, W), min(by + ih, H)
        if x1 > x0 and y1 > y0:
            plane[y0:y1, x0:x1] = src[y0 - by:y1 - by, x0 - bx:x1 - bx]
        self._bg_at = (bx, by)
        return plane

    def area_sets(self, planes) -> list[tuple[int, int, int, frozenset]]:
        out = []
        for s, plane in enumerate(planes):
            for ay in range(H // AREA):
                for ax in range(W // AREA):
                    out.append((s, ax, ay, color_set(plane[ay * AREA:(ay + 1) * AREA, ax * AREA:(ax + 1) * AREA])))
        return out

    def bg_pixels(self, planes, s, ax, ay, colors=None):
        """Asset-coordinate pixels of an area (optionally only those colors), for blame."""
        bg = self.m.spec.get("bg")
        if not bg:
            return None, [], []
        a = self.assets[bg]
        bx, by = getattr(self, "_bg_at", (0, 0))
        region = planes[s][ay * AREA:(ay + 1) * AREA, ax * AREA:(ax + 1) * AREA]
        pts = [(ax * AREA + x - bx, ay * AREA + y - by) for y in range(AREA) for x in range(AREA)
               if region[y, x] >= 0 and (colors is None or int(region[y, x]) in colors)]
        px, bl = blame_for(a, pts, self.frame(a, s))
        return a, px, bl

    def solve_bg(self, planes, bg_name):
        m = self.m
        areas = self.area_sets(planes)
        counts: Counter = Counter()
        for p in planes:
            vals, n = np.unique(p[p >= 0], return_counts=True)
            for c, k in zip(vals, n):
                counts[int(c)] += int(k)
        declared = m.spec.get("backdrop")
        pinned = self.pins.get("bg") if isinstance(self.pins, dict) else None
        if declared is not None:
            b = _palette_entry(declared)
            if b < 0 or b == 0x0D or b > 0x3F:
                self.add("NES-H1", f"backdrop {declared!r} is not a usable NES color (never $0D)", found=declared)
                b = 0x0F
            candidates = [rgb_of(nes_byte_hex(b))]
            m.backdrop_byte = b if isinstance(declared, int) else canon_byte(candidates[0])
            if pinned and len(pinned[0]) == 4 and _palette_entry(pinned[0][0]) != m.backdrop_byte:
                self.add("NES-H5", f"backdrop ${m.backdrop_byte:02X} conflicts with the pinned BG palette 0 entry "
                         f"{pinned[0][0]!r}: the console has one backdrop ($3F00)", found=pinned[0][0],
                         limit=f"${m.backdrop_byte:02X}")
        elif pinned and len(pinned[0]) == 4:
            b = _palette_entry(pinned[0][0])
            candidates = [rgb_of(nes_byte_hex(b))] if 0 <= b <= 0x3F and b != 0x0D else [BLACK_RGB]
        else:
            candidates = sorted(counts, key=lambda c: (-counts[c], canon_byte(c))) or [BLACK_RGB]
        chosen, palettes = None, None
        for c in candidates:
            sets = [s - {c} for (_, _, _, s) in areas]
            if any(len(s) > 3 for s in sets):
                continue
            pal = self.pinned_or_packed(sets, pinned, "bg")
            if pal is not None:
                chosen, palettes = c, pal
                break
        if chosen is None:
            chosen = candidates[0]
            sets = [s - {chosen} for (_, _, _, s) in areas]
            for (s, ax, ay, _), st in zip(areas, sets):
                if len(st) > 3:
                    region = planes[s][ay * AREA:(ay + 1) * AREA, ax * AREA:(ax + 1) * AREA]
                    counts = Counter(int(c) for c in region.ravel() if c >= 0 and int(c) in st)
                    a, px, bl = self.bg_pixels(planes, s, ax, ay, {c for c, _ in counts.most_common()[3:]})
                    self.add("NES-H2", f"attribute area ({ax},{ay}) uses {len(st)} colors besides the backdrop "
                             f"{hex_of(chosen)}; the limit is 3", asset=a.name if a else None, frame=s,
                             where={"area": [ax, ay], "px": [ax * AREA, ay * AREA]}, found=len(st), limit=3,
                             colors=[hex_of(c) for c in sorted(st)], pixels=px, blame=bl,
                             hint="recolor or move detail so each 16x16 area keeps 3 colors + backdrop")
            ok = [i for i, st in enumerate(sets) if len(st) <= 3]
            if self.pinned_or_packed([sets[i] for i in ok], pinned, "bg") is None:
                core = unsat_core([sets[i] for i in ok], 4, 3) if not pinned else \
                    [j for j, i in enumerate(ok) if assign_palette(sets[i], [p for p in pinned_colors(pinned)]) < 0]
                for j in core:
                    s, ax, ay, _ = areas[ok[j]]
                    a, px, bl = self.bg_pixels(planes, s, ax, ay)
                    self.add("NES-H6", f"attribute area ({ax},{ay}) is part of a set of {len(core)} areas whose "
                             f"colors cannot share 4 BG palettes of 3", asset=a.name if a else None, frame=s,
                             where={"area": [ax, ay], "core": len(core)}, limit="4 x 3",
                             colors=[hex_of(c) for c in sorted(sets[ok[j]])], pixels=px, blame=bl,
                             hint="these areas together need more than 4 palettes; merge colors across them")
            palettes = [[] for _ in range(4)]
        m.backdrop = chosen
        if declared is None:
            m.backdrop_byte = canon_byte(chosen)
            if pinned and len(pinned[0]) == 4:
                m.backdrop_byte = _palette_entry(pinned[0][0])
        m.bg_palettes, m.bg_palette_bytes = self.finish_palettes(palettes, pinned, chosen)
        self._areas = areas
        self._area_sets = [s - {chosen} for (_, _, _, s) in areas]

    def pinned_or_packed(self, sets, pinned, kind):
        if pinned:
            pals = pinned_colors(pinned)
            return pals if all(assign_palette(s, pals) >= 0 for s in sets if s) else None
        return pack_palettes(sets, 4, 3)

    def finish_palettes(self, palettes, pinned, backdrop):
        if pinned:
            rgb, byt = [], []
            for p in pinned[:4]:
                entries = list(p[1:] if len(p) == 4 else p)[:3]
                bs = [_palette_entry(v) for v in entries]
                for v, b in zip(entries, bs):
                    if b < 0 or b == 0x0D or b > 0x3F:
                        self.add("NES-H1", f"pinned palette entry {v!r} is not a usable NES color (never $0D)", found=v)
                bs = [b if 0 <= b <= 0x3F and b != 0x0D else 0x0F for b in bs]
                bs += [self.m.backdrop_byte] * (3 - len(bs))
                byt.append(bs)
                rgb.append([rgb_of(nes_byte_hex(b)) for b in bs])
        else:
            rgb, byt = [], []
            for p in palettes[:4]:
                cols = order_palette(p)
                rgb.append(cols + [backdrop] * (3 - len(cols)))
                byt.append([canon_byte(c) for c in cols] + [self.m.backdrop_byte] * (3 - len(cols)))
        while len(rgb) < 4:
            rgb.append([backdrop] * 3)
            byt.append([self.m.backdrop_byte] * 3)
        return rgb, byt

    # -- OBJ -----------------------------------------------------------------

    def obj_cells(self, placements, state: int, ch: int) -> list[Cell]:
        out: list[Cell] = []
        for pi, pl in enumerate(placements):
            if not isinstance(pl, list) or len(pl) < 3:
                self.add("NES-H13", f"obj placement #{pi + 1} must be [asset, x, y, {{opts}}]",
                         blame=[{"loc": self.m.loc, "op": "rg.scene obj", "pixels": 0}])
                continue
            name, px, py = pl[0], int(pl[1]), int(pl[2])
            opts = pl[3] if len(pl) > 3 and isinstance(pl[3], dict) else {}
            if opts.get("size") and opts["size"] != self.m.sprite_size:
                self.add("NES-H10", f"placement of '{name}' asks for {opts['size']} sprites; the frame uses "
                         f"{self.m.sprite_size}", asset=name, found=opts["size"], limit=self.m.sprite_size)
            a = self.assets[name]
            k = self.frame(a, state)
            flip = opts.get("flip")
            layers = a.layers[k] if a.layers else None
            if layers:
                if a.post and state == 0:
                    self.add("NES-H3", f"'{name}' uses obj:<n> layers together with post-processing "
                             f"(mx/outline/flip/crop); layered sprites must be drawn without it", asset=name,
                             blame=[{"loc": a.loc, "op": f"{a.kind} '{name}'", "pixels": 0}])
                sources = [img for lname, img in layers if lname.startswith("obj:")]
            else:
                sources = [a.frames[k]]
            for img in sources:
                fimg = _flip(img, flip)
                ih, iw = fimg.shape[:2]
                for cx, cy, pix in best_grid(rgb_plane(fimg), ch):
                    out.append(Cell(asset=name, frame=k, x=px + cx, top=py + cy, h=ch, pix=pix,
                                    to_asset=(cx, cy, "x" in (flip or ""), "y" in (flip or ""), iw, ih),
                                    colors=color_set(pix), placement=pi))
        return out

    def cell_pixels(self, cell: Cell, colors=None, rows=None):
        a = self.assets[cell.asset]
        pts = [cell.asset_px(u, v) for v in range(cell.h) for u in range(8)
               if cell.pix[v, u] >= 0 and (colors is None or int(cell.pix[v, u]) in colors)
               and (rows is None or v in rows)]
        return blame_for(a, pts, cell.frame)

    def solve_obj(self, cells_by_state):
        m = self.m
        all_cells = [c for cs in cells_by_state for c in cs]
        for c in all_cells:
            if len(c.colors) > 3:
                counts = Counter(int(v) for v in c.pix.ravel() if v >= 0)
                minority = {col for col, _ in counts.most_common()[3:]}
                px, bl = self.cell_pixels(c, minority)
                self.add("NES-H3", f"sprite cell at screen ({c.x},{c.top}) of '{c.asset}' has {len(c.colors)} "
                         "opaque colors; a hardware sprite has 3", asset=c.asset, frame=c.frame,
                         where={"screen": [c.x, c.top], "cell_in_asset": list(c.to_asset[:2])},
                         found=len(c.colors), limit=3, colors=[hex_of(x) for x in sorted(c.colors)],
                         pixels=px, blame=bl, hint="drop a color in this 8px cell or split it with an obj:<n> layer")
        pinned = self.pins.get("obj") if isinstance(self.pins, dict) else None
        sets = [c.colors for c in all_cells if len(c.colors) <= 3]
        pal = self.pinned_or_packed(sets, pinned, "obj")
        if pal is None:
            uniq = list(dict.fromkeys(s for s in sets))
            core = unsat_core(uniq, 4, 3) if not pinned else \
                [i for i, s in enumerate(uniq) if assign_palette(s, pinned_colors(pinned)) < 0]
            core_sets = {uniq[i] for i in core}
            seen = set()
            for c in all_cells:
                if c.colors in core_sets and c.colors not in seen:
                    seen.add(c.colors)
                    px, bl = self.cell_pixels(c)
                    self.add("NES-H7", f"sprite colors {', '.join(hex_of(x) for x in sorted(c.colors))} belong to a "
                             f"set of {len(core)} cells that cannot share 4 sprite palettes of 3", asset=c.asset,
                             frame=c.frame, where={"screen": [c.x, c.top], "core": len(core)}, limit="4 x 3",
                             colors=[hex_of(x) for x in sorted(c.colors)], pixels=px, blame=bl)
            pal = [[] for _ in range(4)]
        m.obj_palettes, m.obj_palette_bytes = self.finish_palettes(pal, pinned, m.backdrop)
        for c in all_cells:
            c.palette = max(0, assign_palette(c.colors, m.obj_palettes))

    # -- tiles ---------------------------------------------------------------

    def tiles(self, bg_planes, cells_by_state, ch):
        m = self.m
        m.chr_sets = m.states if m.chr_model == "chr-ram" else 1
        m.bg_tiles = [[] for _ in range(m.chr_sets)]
        m.obj_tiles = [[] for _ in range(m.chr_sets)]
        bg_index = [dict() for _ in range(m.chr_sets)]
        obj_index = [dict() for _ in range(m.chr_sets)]
        attr_of = {}
        for (s, ax, ay, _), st in zip(self._areas, self._area_sets):
            attr_of[(s, ax, ay)] = max(0, assign_palette(st, m.bg_palettes))
        for s, plane in enumerate(bg_planes):
            ci = m.chr_index(s)
            attrs = np.zeros((H // AREA, W // AREA), dtype=np.int32)
            nt = np.zeros((ROWS, COLS), dtype=np.int32)
            for ay in range(H // AREA):
                for ax in range(W // AREA):
                    attrs[ay, ax] = attr_of[(s, ax, ay)]
            for ty in range(ROWS):
                for tx in range(COLS):
                    pal = m.bg_palettes[attrs[ty // 2, tx // 2]]
                    block = plane[ty * 8:(ty + 1) * 8, tx * 8:(tx + 1) * 8]
                    pat = np.zeros((8, 8), dtype=np.uint8)
                    for v in range(8):
                        for u in range(8):
                            c = int(block[v, u])
                            if c >= 0 and c != m.backdrop:
                                pat[v, u] = pal.index(c) + 1 if c in pal else 0
                    key = pat.tobytes()
                    if key not in bg_index[ci]:
                        bg_index[ci][key] = len(m.bg_tiles[ci])
                        m.bg_tiles[ci].append(pat)
                    nt[ty, tx] = bg_index[ci][key]
            m.nametables.append(nt)
            m.attributes.append(attrs)
        for s, cells in enumerate(cells_by_state):
            ci = m.chr_index(s)
            for c in reversed(cells):            # OAM order: frontmost first
                pal = m.obj_palettes[c.palette]
                pat = np.zeros((ch, 8), dtype=np.uint8)
                for v in range(ch):
                    for u in range(8):
                        col = int(c.pix[v, u])
                        if col >= 0:
                            pat[v, u] = pal.index(col) + 1 if col in pal else 0
                c.pattern = pat
                for fh, fv in ((False, False), (True, False), (False, True), (True, True)):
                    key = _flip_pat(pat, fh, fv).tobytes()
                    if key in obj_index[ci]:
                        c.tile, c.flip_h, c.flip_v = obj_index[ci][key], fh, fv
                        break
                else:
                    obj_index[ci][pat.tobytes()] = len(m.obj_tiles[ci])
                    c.tile = len(m.obj_tiles[ci])
                    m.obj_tiles[ci].append(pat)
        bg_name = m.spec.get("bg")
        bg_blame = [{"loc": self.assets[bg_name].loc, "op": f"BG '{bg_name}'", "pixels": 0}] if bg_name else []
        obj_names = list(dict.fromkeys(c.asset for cs in cells_by_state for c in cs))
        obj_blame = [{"loc": self.assets[n].loc, "op": f"OBJ '{n}'", "pixels": 0} for n in obj_names]
        for ci in range(m.chr_sets):
            nb, no = len(m.bg_tiles[ci]), len(m.obj_tiles[ci])
            units = no * (2 if ch == 16 else 1)
            where = f" (CHR set {ci})" if m.chr_sets > 1 else ""
            if m.chr_model == "shared":
                cap = 256 - (round_up(nb, 2) if ch == 16 else nb)
                if nb > 256:
                    self.add("NES-H11", f"{nb} unique BG tiles{where}; one pattern table holds 256", found=nb, limit=256,
                             blame=bg_blame)
                elif units > cap:
                    self.add("NES-H12", f"{nb} BG + {units} sprite tiles{where} share one 256-tile pattern table "
                             "(chr: \"shared\")", found=nb + units, limit=256, blame=obj_blame + bg_blame)
            else:
                if nb > 256:
                    self.add("NES-H11", f"{nb} unique BG tiles{where}; the BG pattern table holds 256 (no flips on NES BG)",
                             found=nb, limit=256, blame=bg_blame,
                             hint="reuse identical 8x8 tiles; BG tiles cannot be flipped")
                cap = 256 if ch == 8 else 256 + max(0, 256 - round_up(nb, 2))
                if units > cap:
                    self.add("NES-H12", f"{units} unique sprite tiles{where}; the sprite pattern table holds {cap}",
                             found=units, limit=cap, blame=obj_blame)
        m.info.append({"bg_tiles": [len(t) for t in m.bg_tiles], "obj_tiles": [len(t) for t in m.obj_tiles],
                       "chr_model": m.chr_model, "sprite_size": m.sprite_size})

    # -- OAM, scanlines, screen bounds -----------------------------------------

    def oam_and_lines(self, cells_by_state, ch):
        m = self.m
        for s, cells in enumerate(cells_by_state):
            oam: list[Cell] = []
            for c in reversed(cells):
                vis_rows = [v for v in range(ch) if 0 <= c.top + v < H and (c.pix[v] >= 0).any()]
                vis_cols = [u for u in range(8) if 0 <= c.x + u < W]
                if not vis_rows or not vis_cols or not (c.pix[np.ix_(vis_rows, vis_cols)] >= 0).any():
                    m.info.append({"offscreen_cell": [c.asset, c.x, c.top], "state": s})
                    continue
                if c.x < 0 or c.x > 255 or c.top < 1 or c.top > 239:
                    m.rejected.append(c)
                    px, bl = self.cell_pixels(c)
                    self.add("NES-H13", lead=True, message=f"sprite cell of '{c.asset}' at screen ({c.x},{c.top}) cannot be placed: "
                             "X must be 0-255 and the top row 1-239 (sprites never show on line 0)",
                             asset=c.asset, frame=c.frame, where={"screen": [c.x, c.top]}, pixels=px, blame=bl)
                    continue
                oam.append(c)
            if len(oam) > 64:
                self.add("NES-H8", f"{len(oam)} hardware sprites in frame {s}; OAM holds 64", lead=True, frame=s,
                         found=len(oam), limit=64)
            m.oam.append(oam)
            dropped: dict[int, list[int]] = {}
            for y in range(H):
                on = [i for i, c in enumerate(oam) if c.top <= y < c.top + c.h]
                for i in on[8:]:
                    dropped.setdefault(i, []).append(y)
            by_cell = sorted(dropped.items())
            if by_cell:
                lines = sorted({y for _, ys in by_cell for y in ys})
                for i, ys in by_cell:
                    c = oam[i]
                    rows = {y - c.top for y in ys}
                    px, bl = self.cell_pixels(c, rows=rows)
                    self.add("NES-H9", lead=True, message=f"more than 8 sprites on lines {ys[0]}-{ys[-1]}: OAM #{i} "
                             f"('{c.asset}' cell at {c.x},{c.top}) is dropped there", asset=c.asset, frame=c.frame,
                             where={"oam": i, "lines": [ys[0], ys[-1]], "screen": [c.x, c.top]},
                             found=max(sum(1 for d in oam if d.top <= y < d.top + d.h) for y in lines), limit=8,
                             pixels=px, blame=bl, hint="spread the sprites vertically or narrow the metasprites")

    def composites(self, bg_planes, cells_by_state):
        m = self.m
        bd = m.backdrop
        for s, plane in enumerate(bg_planes):
            scr = np.where(plane >= 0, plane, bd).astype(np.int64)
            m.bg_screens.append(scr.astype(np.int32))
            for c in cells_by_state[s]:      # paint order
                for v in range(c.h):
                    y = c.top + v
                    if not 0 <= y < H:
                        continue
                    for u in range(8):
                        x = c.x + u
                        if 0 <= x < W and c.pix[v, u] >= 0:
                            scr[y, x] = c.pix[v, u]
            img = np.zeros((H, W, 4), dtype=np.uint8)
            img[..., 0] = (scr >> 16) & 255
            img[..., 1] = (scr >> 8) & 255
            img[..., 2] = scr & 255
            img[..., 3] = 255
            m.composites.append(img)

    def left_column(self, bg_planes, cells_by_state):
        m = self.m
        for s, plane in enumerate(bg_planes):
            bg_hit = int(((plane[:, :8] >= 0) & (plane[:, :8] != m.backdrop)).sum())
            obj_hit = sum(int((c.pix[:, max(0, -c.x):max(0, 8 - c.x)] >= 0).sum()) for c in cells_by_state[s] if c.x < 8)
            if bg_hit or obj_hit:
                self.add("NES-H14", f"{bg_hit + obj_hit} visible pixel(s) in the left 8 px are hidden because the scene "
                         "sets left8: false", severity="warning", frame=s)
                break


def pinned_colors(pinned) -> list[list[int]]:
    out = []
    for p in pinned[:4]:
        entries = list(p[1:] if len(p) == 4 else p)[:3]
        out.append([rgb_of(nes_byte_hex(b)) for b in (_palette_entry(v) for v in entries) if 0 <= b <= 0x3F])
    return out


def _flip_pat(p: np.ndarray, fh: bool, fv: bool) -> np.ndarray:
    if fh:
        p = p[:, ::-1]
    if fv:
        p = p[::-1, :]
    return p


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


@dataclass
class NesAnalysis:
    like: list[Violation]
    like_info: list[dict]
    scenes: list[SceneModel]
    images: dict[str, list[np.ndarray]]     # exported image per asset frame (OBJ padded)
    roles: dict[str, str]


def analyze(assets: dict[str, Asset], scenes: list[dict], tilesets: list[dict], pins: dict | None) -> NesAnalysis:
    tileset_names = {t["name"] for t in tilesets}
    roles = {n: ("bg" if (a.kind == "scene" or n in tileset_names) else "obj") for n, a in assets.items()}
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
        referenced |= {spec.get("bg")} | {p[0] for p in spec.get("obj", []) if isinstance(p, list) and p}
        models.append(SceneModel(name=s["name"], declared=True, loc=s.get("loc"), spec=spec))
    taken = {s["name"] for s in scenes}

    def lone_name(n):
        return n if n not in taken else f"lone-{n}"

    for t in tilesets:
        opts = dict(t.get("opts") or {})
        spec = {"bg": t["name"], "tileset": opts}
        if "backdrop" in opts:
            spec["backdrop"] = opts["backdrop"]
        models.append(SceneModel(name=lone_name(t["name"]), declared=False, loc=t.get("loc"), spec=spec))
    for n, a in assets.items():
        if not a.exported or n in referenced or n in tileset_names:
            continue
        if roles[n] == "bg":
            spec = {"bg": n}
        else:
            spec = {"obj": [[n, LONE_OBJ_AT[0], LONE_OBJ_AT[1]]], "backdrop": 0x0F}
        models.append(SceneModel(name=lone_name(n), declared=False, loc=a.loc, spec=spec))

    like_bad = {v.asset for v in like if v.severity == "error"}
    for m in models:
        involved = {m.spec.get("bg")} | {p[0] for p in m.spec.get("obj", []) if isinstance(p, list) and p}
        blocked = sorted(x for x in involved if x in like_bad)
        if blocked:
            m.info.append({"blocked_by_like": blocked})
            continue
        SceneAnalyzer(assets, m, pins).run()
        if "tileset" in m.spec and m.legal:
            m.metatiles = _metatiles(m)
    return NesAnalysis(like=like, like_info=info, scenes=models, images=images, roles=roles)


def _metatiles(m: SceneModel):
    """16x16 metatiles of a tile set, row-major: (top-left, top-right, bottom-left, bottom-right, palette)."""
    bg = m.spec["bg"]
    out = []
    nt, attrs = m.nametables[0], m.attributes[0]
    seen = set()
    for ay in range(H // AREA):
        for ax in range(W // AREA):
            t = (int(nt[2 * ay, 2 * ax]), int(nt[2 * ay, 2 * ax + 1]), int(nt[2 * ay + 1, 2 * ax]),
                 int(nt[2 * ay + 1, 2 * ax + 1]), int(attrs[ay, ax]))
            if t not in seen:
                seen.add(t)
                out.append(t)
    del bg
    return out

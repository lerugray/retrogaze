"""
Reference SNES S-PPU: render exported bytes back to pixels (BG mode 1, main screen).

Deliberately independent of the scene model: it reads only a 64 KiB VRAM image, the 512-byte CGRAM, the
544-byte OAM and the register values from vram.json, the same inputs the console gets. Modeled:
  * screen row r is scanline r + 1; a BG shows line (scanline + BGnVOFS) & 255 of its 32x32 map;
  * tilemap entries VHPCCCTT TTTTTTTT with H/V flips, 4bpp BG1/BG2 (palette p = CGRAM 16p), 2bpp BG3
    (palette p = CGRAM 4p), pixel value 0 transparent;
  * OBJ: OBSEL sizes and name base / name select, 9-bit X, OAM high table, H/V flips (rectangular OBJs
    flip each half on its own, as the hardware does); per line the first 32 OBJs in range from OAM #0
    (an X = -256 OBJ is in range), their on-screen tiles fetched from the last kept OBJ back to OAM #0,
    at most 34; the lower OAM index wins;
  * mode 1 priority (BGMODE bit 3 clear): OBJ.3 > BG1.1 > BG2.1 > OBJ.2 > BG1.0 > BG2.0 > OBJ.1 > BG3.1 >
    OBJ.0 > BG3.0 > backdrop.
Colors expand 5 bits to 8 with Retrogaze's e(q) = (q * 255) // 31.
"""

from __future__ import annotations

import numpy as np

from .binding import SNES_LEVELS

W, H = 256, 224
OBJ_W = [8, 8, 8, 16, 16, 32, 16, 16, 16, 32, 64, 32, 64, 64, 32, 32]    # by OBSEL size | large << 3
OBJ_H = [8, 8, 8, 16, 16, 32, 32, 32, 16, 32, 64, 32, 64, 64, 64, 32]
BG_PRIO = {1: (6, 9), 2: (5, 8), 3: (1, 3)}
OBJ_PRIO = (2, 4, 7, 10)


def _word(vram: bytes, addr: int) -> int:
    a = 2 * (addr & 0x7FFF)
    return vram[a] | (vram[a + 1] << 8)


def _rgb(cgram: bytes) -> np.ndarray:
    out = np.zeros((256, 3), dtype=np.uint8)
    for i in range(256):
        w = cgram[2 * i] | (cgram[2 * i + 1] << 8)
        out[i] = [SNES_LEVELS[w & 31], SNES_LEVELS[(w >> 5) & 31], SNES_LEVELS[(w >> 10) & 31]]
    return out


def _tile_row(vram: bytes, base: int, tile: int, row: int, bpp: int) -> list[int]:
    words = 8 * bpp // 2
    a = base + tile * words + row
    p01 = _word(vram, a)
    p23 = _word(vram, a + 8) if bpp == 4 else 0
    out = []
    for x in range(8):
        bit = 7 - x
        v = ((p01 >> bit) & 1) | (((p01 >> (8 + bit)) & 1) << 1)
        if bpp == 4:
            v |= (((p23 >> bit) & 1) << 2) | (((p23 >> (8 + bit)) & 1) << 3)
        out.append(v)
    return out


def _tile(vram: bytes, base: int, tile: int, bpp: int) -> np.ndarray:
    """(8, 8) color values of one BG tile at word address base + tile * (4 * bpp)."""
    return np.array([_tile_row(vram, base, tile, row, bpp) for row in range(8)], dtype=np.int32)


def _bg(vram: bytes, regs: dict, n: int):
    """(cgram index or -1, priority) for every screen pixel of BG n (1-3)."""
    sc = regs[f"BG{n}SC"]
    if sc & 3:
        raise NotImplementedError("only 32x32 tilemaps are modeled")
    map_base = (sc >> 2) << 10
    nba = regs["BG12NBA"] if n < 3 else regs["BG34NBA"]
    chr_base = ((nba >> (4 if n == 2 else 0)) & 0x0F) << 12
    bpp = 4 if n < 3 else 2
    hofs, vofs = regs.get(f"BG{n}HOFS", 0), regs.get(f"BG{n}VOFS", 0)
    layer = np.full((256, 256), -1, dtype=np.int32)          # the whole 32x32 map, as CGRAM indices
    lprio = np.zeros((256, 256), dtype=np.int32)
    cache: dict[int, np.ndarray] = {}
    for ty in range(32):
        for tx in range(32):
            e = _word(vram, map_base + ty * 32 + tx)
            tile, pal, prio = e & 0x3FF, (e >> 10) & 7, (e >> 13) & 1
            if tile not in cache:
                cache[tile] = _tile(vram, chr_base, tile, bpp)
            t = cache[tile]
            if e & 0x4000:
                t = t[:, ::-1]
            if e & 0x8000:
                t = t[::-1, :]
            layer[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8] = np.where(t > 0, pal * (16 if bpp == 4 else 4) + t, -1)
            lprio[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8] = prio
    rows = (np.arange(H) + 1 + vofs) & 0xFF                  # screen row r is scanline r + 1
    cols = (np.arange(W) + hofs) & 0xFF
    return layer[np.ix_(rows, cols)], lprio[np.ix_(rows, cols)]


def _objs(vram: bytes, oam: bytes, regs: dict, range_limit: int = 32, time_limit: int = 34,
          fetch_hidden: bool = False):
    """(cgram index or -1, OBJ priority) per screen pixel, with the 32-per-line and 34-sliver limits.
    The keyword arguments describe the hardware by default; the emulator proof also renders variants (no
    limit, tiles off the left edge fetched) as negative controls that Mesen must disagree with."""
    obsel = regs["OBSEL"]
    size, nn, base = obsel >> 5, (obsel >> 3) & 3, (obsel & 7) << 13
    second = (nn + 1) << 12
    sprites = []
    for i in range(128):
        hi = oam[512 + i // 4] >> (2 * (i % 4))
        x = oam[4 * i] - (256 if hi & 1 else 0)
        mode = size | ((hi & 2) << 2)
        sprites.append((x, oam[4 * i + 1], oam[4 * i + 2], oam[4 * i + 3], OBJ_W[mode], OBJ_H[mode]))
    idx = np.full((H, W), -1, dtype=np.int32)
    pri = np.zeros((H, W), dtype=np.int32)
    for r in range(H):
        s = r                                  # evaluated on scanline r, shown on scanline r + 1 = row r
        sel = []
        for i, (x, y, _, _, w, h) in enumerate(sprites):
            if x != -256 and (x + w <= 0 or x > 255):
                continue
            end = y + h
            if (y <= s < end) or ((end & 0xFF) < y and s < (end & 0xFF)):
                sel.append(i)
                if len(sel) == range_limit:
                    break
        fetched = 0
        row_idx = np.full(W, -1, dtype=np.int32)
        row_pri = np.zeros(W, dtype=np.int32)
        for i in reversed(sel):
            x, y, t, attr, w, h = sprites[i]
            cols = w // 8
            left = cols + (int(x / 8) if x <= -8 and x != -256 and not fetch_hidden else 0)
            gap = (s - y)
            vflip, hflip = bool(attr & 0x80), bool(attr & 0x40)
            if vflip:
                pos = w - 1 - gap if gap < w else w * 3 - 1 - gap
                yoff, rowoff = pos & 7, pos >> 3
            else:
                yoff, rowoff = gap & 7, gap >> 3
            x0 = 0 if x == -256 else x
            while left > 0 and fetched < time_limit:
                left -= 1
                screen_col = cols - left - 1
                tcol = left if hflip else screen_col
                name = (((t >> 4) + rowoff) & 0x0F) << 4 | (((t & 0x0F) + tcol) & 0x0F)
                addr = (base + (name << 4) + (second if attr & 1 else 0)) & 0x7FFF
                pix = _tile_row(vram, addr, 0, yoff, 4)
                fetched += 1
                draw_x = x + screen_col * 8
                for u in range(8):
                    sx = draw_x + u
                    if not 0 <= sx <= 255:
                        continue
                    v = pix[7 - u if hflip else u]
                    if v:
                        row_idx[sx] = 128 + ((attr >> 1) & 7) * 16 + v
                        row_pri[sx] = (attr >> 4) & 3
                if x0 + screen_col * 8 + 8 >= 256:
                    break
        idx[r] = row_idx
        pri[r] = row_pri
    return idx, pri


def render(vram: bytes, cgram: bytes, oam: bytes, regs: dict, **variant) -> np.ndarray:
    """(224, 256, 4) uint8 RGBA of what the PPU shows for one frame. ``variant``: see ``_objs``."""
    assert len(vram) == 65536 and len(cgram) == 512 and len(oam) == 544
    if regs.get("BGMODE", 1) & 0x0F != 1:
        raise NotImplementedError("the reference PPU models BG mode 1 (BG3 priority bit clear)")
    rgb = _rgb(cgram)
    tm = regs.get("TM", 0x1F)
    best = np.zeros((H, W), dtype=np.int32)          # priority of the winning layer (0 = backdrop)
    color = np.zeros((H, W), dtype=np.int32)         # CGRAM index of the winning pixel
    for n in (1, 2, 3):
        if tm & (1 << (n - 1)):
            idx, pri = _bg(vram, regs, n)
            p = np.where(pri == 1, BG_PRIO[n][1], BG_PRIO[n][0])
            win = (idx >= 0) & (p > best)
            best = np.where(win, p, best)
            color = np.where(win, idx, color)
    if tm & 0x10:
        idx, pri = _objs(vram, oam, regs, **variant)
        p = np.array(OBJ_PRIO)[pri]
        win = (idx >= 0) & (p > best)
        color = np.where(win, idx, color)
    out = np.zeros((H, W, 4), dtype=np.uint8)
    out[..., :3] = rgb[color]
    out[..., 3] = 255
    return out

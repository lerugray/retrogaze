"""
Reference NES PPU: render exported bytes back to pixels.

Deliberately independent of the scene model: it reads only .chr/.pal/.nam/.oam
bytes and the viewer ROM settings, the same inputs the console gets. Models the
hardware behavior code mode relies on: attribute areas, the shared backdrop,
8x8 / 8x16 sprites, OAM priority, H/V flips, sprites never on line 0 (Y = top - 1),
at most 8 sprites per scanline (higher OAM indices dropped), left-column clipping.
Colors come from Retrogaze's NES table (binding.nes_byte_hex).
"""

from __future__ import annotations

import numpy as np

from .binding import nes_byte_hex
from .hw.common import rgb_of

W, H = 256, 240


def _rgb_table() -> np.ndarray:
    return np.array([rgb_of(nes_byte_hex(b)) for b in range(64)], dtype=np.int64)


def _tile(chr_: bytes, table: int, index: int) -> np.ndarray:
    base = table * 4096 + index * 16
    p0 = chr_[base:base + 8]
    p1 = chr_[base + 8:base + 16]
    out = np.zeros((8, 8), dtype=np.uint8)
    for y in range(8):
        for x in range(8):
            out[y, x] = ((p0[y] >> (7 - x)) & 1) | (((p1[y] >> (7 - x)) & 1) << 1)
    return out


def render(chr_: bytes, pal: bytes, nam: bytes, oam: bytes, rom: dict) -> np.ndarray:
    """(240, 256, 4) uint8 RGBA of what the PPU shows for one frame."""
    assert len(chr_) == 8192 and len(pal) == 32 and len(nam) == 1024 and len(oam) == 256
    rgb = _rgb_table()
    pal = [b & 0x3F for b in pal]
    bg_table = int(rom.get("bg_table", 0))
    spr_table = int(rom.get("spr_table", 1))
    tall = rom.get("sprite_size", "8x8") == "8x16"
    left8 = rom.get("left8", True)
    cache: dict[tuple[int, int], np.ndarray] = {}

    def tile(t, i):
        k = (t, i)
        if k not in cache:
            cache[k] = _tile(chr_, t, i)
        return cache[k]

    # Background: color index 0 of any palette shows the backdrop ($3F00).
    bg_idx = np.zeros((H, W), dtype=np.uint8)
    bg_pal = np.zeros((H, W), dtype=np.uint8)
    for ty in range(30):
        for tx in range(32):
            t = tile(bg_table, nam[ty * 32 + tx])
            a = nam[960 + (ty // 4) * 8 + tx // 4]
            shift = ((ty // 2) % 2) * 4 + ((tx // 2) % 2) * 2
            bg_idx[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = t
            bg_pal[ty * 8:ty * 8 + 8, tx * 8:tx * 8 + 8] = (a >> shift) & 3
    if not left8:
        bg_idx[:, :8] = 0
    color = np.where(bg_idx == 0, pal[0], np.array(pal, dtype=np.int64)[bg_pal.astype(np.int64) * 4 + bg_idx])
    screen = rgb[color].copy()

    # Sprites, scanline by scanline: the first 8 in OAM order that cover the line are drawn.
    h = 16 if tall else 8
    sprites = [tuple(oam[4 * i:4 * i + 4]) for i in range(64)]
    for y in range(H):
        on = [i for i, (sy, _, _, _) in enumerate(sprites) if sy + 1 <= y < sy + 1 + h and sy < 0xEF][:8]
        drawn = np.zeros(W, dtype=bool)
        for i in on:
            sy, t, attr, sx = sprites[i]
            row = y - (sy + 1)
            if attr & 0x80:
                row = h - 1 - row
            if tall:
                table, top = t & 1, t & 0xFE
                pat = tile(table, top + (row >= 8))[row % 8]
            else:
                pat = tile(spr_table, t)[row]
            if attr & 0x40:
                pat = pat[::-1]
            behind = bool(attr & 0x20)
            for u in range(8):
                x = sx + u
                if x >= W or drawn[x] or pat[u] == 0 or (not left8 and x < 8):
                    continue
                drawn[x] = True
                if behind and bg_idx[y, x] != 0:
                    continue
                screen[y, x] = rgb[pal[16 + (attr & 3) * 4 + pat[u]]]
    out = np.zeros((H, W, 4), dtype=np.uint8)
    out[..., 0] = (screen >> 16) & 255
    out[..., 1] = (screen >> 8) & 255
    out[..., 2] = screen & 255
    out[..., 3] = 255
    return out

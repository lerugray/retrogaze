#!/usr/bin/env python3
"""Independent oracle for code mode's SNES 4bpp tile encoder (spec §5.2, test M2-15): SuperFamiconv.

    sfc_oracle.py --superfamiconv BIN --art art.png --map N.bg1.map --cgram N.cgram --tiles N.bg1.4bpp --work W

The input to SuperFamiconv is built from the art itself (pxl's rendered RGBA image of the BG layer), never
from code mode's tile bytes, so a wrong encoder cannot pass by decoding its own mistake back. For every
tile number in the exported tilemap, the first map entry that uses it gives the 8x8 block of the art, the
H/V flips to undo and the palette. The blocks of each palette go to SuperFamiconv in one image with that
16-color CGRAM palette (color 0 replaced by a color the tiles do not use, so no opaque pixel can map to the
transparent index), with --no-discard --no-flip, so its output is one 32-byte 4bpp tile per block.
Pass = SuperFamiconv's bytes for every tile equal the exported .4bpp. Needs Pillow.
"""
import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image


def map_entries(data: bytes) -> list[int]:
    return [data[2 * i] | (data[2 * i + 1] << 8) for i in range(len(data) // 2)]


def check(superfamiconv, art_png, map_bytes: bytes, cgram: bytes, tiles: bytes, work=None) -> dict:
    art = Image.open(art_png).convert("RGBA")
    aw, ah = art.size
    first: dict[int, tuple] = {}
    for i, e in enumerate(map_entries(map_bytes)):
        ty, tx = divmod(i, 32)
        tile = e & 0x3FF
        if tile not in first:            # a tile first used outside the art (below a 224-line BG) is blank
            first[tile] = (ty, tx, (e >> 10) & 7, bool(e & 0x4000), bool(e & 0x8000))
    n = len(tiles) // 32
    blank = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
    by_pal: dict[int, list[int]] = {}
    for t in range(n):
        if t in first:
            by_pal.setdefault(first[t][2], []).append(t)
    got: dict[int, bytes] = {}
    with tempfile.TemporaryDirectory(prefix="rg-sfc-") as tmp:
        tmp = Path(work or tmp)
        tmp.mkdir(parents=True, exist_ok=True)
        for p, ts in sorted(by_pal.items()):
            cols = min(16, len(ts))
            img = Image.new("RGBA", (8 * cols, 8 * ((len(ts) + cols - 1) // cols)), (0, 0, 0, 0))
            used = set()
            for k, t in enumerate(ts):
                ty, tx, _, hf, vf = first[t]
                block = art.crop((8 * tx, 8 * ty, 8 * tx + 8, 8 * ty + 8)) if 8 * ty < ah and 8 * tx < aw else blank
                if hf:
                    block = block.transpose(Image.Transpose.FLIP_LEFT_RIGHT)
                if vf:
                    block = block.transpose(Image.Transpose.FLIP_TOP_BOTTOM)
                img.paste(block, (8 * (k % cols), 8 * (k // cols)))
                used |= {px[:3] for px in block.getdata() if px[3]}
            words = [cgram[32 * p + 2 * i] | (cgram[32 * p + 2 * i + 1] << 8) for i in range(16)]
            levels = [(q * 255) // 31 for q in range(32)]
            rgb = lambda w: (levels[w & 31], levels[(w >> 5) & 31], levels[(w >> 10) & 31])  # noqa: E731
            words[0] = next(w for w in range(0x7FFF, -1, -1) if rgb(w) not in used and w not in words[1:])
            (tmp / f"pal{p}.bin").write_bytes(b"".join(w.to_bytes(2, "little") for w in words))
            img.save(tmp / f"tiles{p}.png")
            out = tmp / f"tiles{p}.4bpp"
            proc = subprocess.run([str(superfamiconv), "tiles", "-i", str(tmp / f"tiles{p}.png"), "-p",
                                   str(tmp / f"pal{p}.bin"), "-d", str(out), "-B", "4", "-D", "-F"],
                                  capture_output=True, text=True)
            if proc.returncode != 0:
                return {"ok": False, "error": f"superfamiconv failed: {proc.stderr.strip()[-400:]}"}
            data = out.read_bytes()
            for k, t in enumerate(ts):
                got[t] = data[32 * k:32 * k + 32]
    bad = [t for t in range(n) if t in got and got[t] != tiles[32 * t:32 * t + 32]]
    unchecked = [t for t in range(n) if t not in got]
    return {"ok": not bad and not unchecked, "tiles": n, "checked": len(got), "mismatched_tiles": bad[:32],
            "unchecked_tiles": unchecked[:32], "palettes": sorted(by_pal)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--superfamiconv", required=True, type=Path)
    ap.add_argument("--art", required=True, type=Path)
    ap.add_argument("--map", required=True, type=Path)
    ap.add_argument("--cgram", required=True, type=Path)
    ap.add_argument("--tiles", required=True, type=Path)
    ap.add_argument("--work", type=Path, default=None)
    args = ap.parse_args(argv)
    res = check(args.superfamiconv, args.art, args.map.read_bytes(), args.cgram.read_bytes(),
                args.tiles.read_bytes(), args.work)
    print(json.dumps(res, indent=1))
    return 0 if res["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

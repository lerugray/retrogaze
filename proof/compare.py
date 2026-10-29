#!/usr/bin/env python3
"""Proof gates (c) and (d) for one NES or SNES scene: emulator memory == exported bytes, and the screenshot
matches the reference render under a color bijection.

    compare.py --in-dir D --name N --run-dir O [--console nes|snes]

Gate (c), byte-exact: O/palette.bin == D/N.pal, O/oam.bin == D/N.oam, O/nametable.bin == D/N.nam,
O/chr.bin == D/N.chr. Mesen's palette RAM is a plain 32-byte array: writes are masked to 6 bits and
land in both $3F00/$3F10-style mirror slots, so a legal .pal (values < $40, mirrors equal) reads back
unchanged and is compared raw. OAM byte 2 bits 2-4 do not exist in the PPU (they read back 0).
Gate (d): O/screenshot.png vs D/N.ref.png over the full 256x240 frame. No crop: run_mesen.py pins
Mesen's NTSC overscan to 0, and any other screenshot size fails. Each expected color must map to
exactly one screen color, no two expected colors to the same one, and every pixel must agree.
On a gate (d) failure O/diff.png = [reference | screenshot | disagreeing pixels in red].
SNES (D/N.vram.json present): gate (c) compares O/cgram.bin with D/N.cgram, O/oam.bin with D/N.oam (544 B,
high table included), and all 64 KiB of O/vram.bin with the image vram.json describes: every exported blob
at its word address, zeros elsewhere (the viewer clears VRAM first). Gate (d) is the same bijection over
the 256x224 frame (Mesen crops its 239-line buffer to the 224 visible lines).
Writes O/compare.json; exit 0 only if both gates pass. Import: compare(in_dir, name, run_dir) -> dict.
"""
import argparse
import json
import sys
from collections import Counter
from pathlib import Path

from PIL import Image

WIDTH, HEIGHT = 256, 240
DUMPS = [("palette.bin", ".pal"), ("oam.bin", ".oam"), ("nametable.bin", ".nam"), ("chr.bin", ".chr")]
SNES_HEIGHT = 224
MAX_LISTED = 16


def gate_c(in_dir: Path, name: str, run_dir: Path) -> dict:
    files = {}
    for dump, ext in DUMPS:
        try:
            expected, got = (in_dir / f"{name}{ext}").read_bytes(), (run_dir / dump).read_bytes()
        except OSError as exc:
            files[ext] = {"ok": False, "error": str(exc), "first": []}
            continue
        diffs = [(i, expected[i] if i < len(expected) else None, got[i] if i < len(got) else None)
                 for i in range(max(len(expected), len(got)))
                 if i >= len(expected) or i >= len(got) or expected[i] != got[i]]
        entry = {"ok": not diffs, "mismatches": len(diffs),
                 "first": [{"offset": i, "expected": e, "got": g} for i, e, g in diffs[:MAX_LISTED]]}
        if ext == ".oam" and any(i % 4 == 2 and e is not None and e & 0x1C for i, e, _ in diffs):
            entry["hint"] = "OAM byte 2 bits 2-4 do not exist on the 2C02 and read back 0"
        if ext == ".pal" and any(e is not None and e > 0x3F for _, e, _ in diffs):
            entry["hint"] = "palette RAM is 6 bits wide"
        elif ext == ".pal" and any(i in (0x10, 0x14, 0x18, 0x1C) for i, _, _ in diffs):
            entry["hint"] = "$3F10/14/18/1C mirror $3F00/04/08/0C; the .pal must hold equal bytes there"
        files[ext] = entry
    return {"ok": all(f["ok"] for f in files.values()), "files": files}


def _diffs(expected: bytes, got: bytes, base: int = 0) -> list:
    return [(base + i, expected[i] if i < len(expected) else None, got[i] if i < len(got) else None)
            for i in range(max(len(expected), len(got)))
            if i >= len(expected) or i >= len(got) or expected[i] != got[i]]


def snes_vram_image(in_dir: Path, name: str) -> tuple:
    """The 64 KiB VRAM image vram.json describes, and {region: (byte address, bytes)}."""
    doc = json.loads((in_dir / f"{name}.vram.json").read_text(encoding="utf-8"))
    image = bytearray(65536)
    regions = {}
    for region, r in doc["regions"].items():
        addr = int(r["word_address"][1:], 16) * 2
        data = (in_dir / doc["files"]["obj_chr" if region == "obj" else region]).read_bytes()
        image[addr:addr + len(data)] = data
        regions[region] = (addr, len(data))
    return bytes(image), regions


def gate_c_snes(in_dir: Path, name: str, run_dir: Path) -> dict:
    files = {}
    for dump, ext in (("cgram.bin", ".cgram"), ("oam.bin", ".oam")):
        try:
            d = _diffs((in_dir / f"{name}{ext}").read_bytes(), (run_dir / dump).read_bytes())
        except OSError as exc:
            files[ext] = {"ok": False, "error": str(exc), "first": []}
            continue
        files[ext] = {"ok": not d, "mismatches": len(d),
                      "first": [{"offset": i, "expected": e, "got": g} for i, e, g in d[:MAX_LISTED]]}
    try:
        expected, regions = snes_vram_image(in_dir, name)
        got = (run_dir / "vram.bin").read_bytes()
    except (OSError, KeyError, ValueError) as exc:
        files["vram"] = {"ok": False, "error": str(exc), "first": []}
        return {"ok": False, "files": files}
    d = _diffs(expected, got)
    where = {}
    for i, _, _ in d:
        region = next((k for k, (a, n) in regions.items() if a <= i < a + n), "outside the exported blobs")
        where[region] = where.get(region, 0) + 1
    files["vram"] = {"ok": not d, "mismatches": len(d), "regions": {k: list(v) for k, v in regions.items()},
                     "mismatches_by_region": where,
                     "first": [{"offset": i, "expected": e, "got": g} for i, e, g in d[:MAX_LISTED]]}
    return {"ok": all(f["ok"] for f in files.values()), "files": files}


def gate_d(ref_path: Path, shot_path: Path, diff_path: Path, height: int = HEIGHT) -> dict:
    try:
        ref, shot = Image.open(ref_path).convert("RGBA"), Image.open(shot_path).convert("RGB")
    except OSError as exc:
        return {"ok": False, "error": str(exc)}
    for label, img in (("reference", ref), ("screenshot", shot)):
        if img.size != (WIDTH, height):
            return {"ok": False, "error": f"{label} is {img.size[0]}x{img.size[1]}, expected {WIDTH}x{height}"}
    expected, got = pixels(ref, 4), pixels(shot, 3)
    color_map, bad = bijection(expected, got)
    targets = Counter(color_map.values())
    collisions = sorted([list(e), list(g)] for e, g in color_map.items() if targets[g] > 1)
    result = {
        "ok": not bad and not collisions,
        "expected_colors": len(color_map),
        "screen_colors": len(set(got)),
        "color_map": sorted([list(e), list(g)] for e, g in color_map.items()),
        "mismatched_pixels": len(bad),
        "collisions": collisions,
        "first": [{"x": i % WIDTH, "y": i // WIDTH, "expected": list(expected[i]),
                   "mapped_to": list(color_map[expected[i]]), "got": list(got[i])} for i in bad[:MAX_LISTED]],
    }
    translucent = sum(1 for e in expected if e[3] != 255)
    if translucent:
        result["warning"] = f"{translucent} reference pixels are not opaque; ref.png should be alpha 255"
    if bad:
        xs, ys = [i % WIDTH for i in bad], [i // WIDTH for i in bad]
        result["mismatch_bbox"] = [min(xs), min(ys), max(xs), max(ys)]
        result["mismatch_rows"] = sorted(set(ys))
    if not result["ok"]:
        write_diff(ref, shot, set(bad), expected, diff_path, height)
    return result


def bijection(expected: list, got: list) -> tuple:
    """Return (color_map, indices of disagreeing pixels).

    color_map sends each expected color to its most frequent screen color, reverse sends each screen
    color to its most frequent expected color, and a pixel agrees iff the two maps send its pair to
    each other. No pixel disagrees exactly when color_map is a bijection that holds everywhere."""
    color_map, reverse = majority(zip(expected, got)), majority(zip(got, expected))
    return color_map, [i for i, (e, g) in enumerate(zip(expected, got)) if color_map[e] != g or reverse[g] != e]


def pixels(img, channels: int) -> list:
    data = img.tobytes()
    return [tuple(data[i:i + channels]) for i in range(0, len(data), channels)]


def majority(pairs) -> dict:
    votes = {}
    for a, b in pairs:
        votes.setdefault(a, Counter())[b] += 1
    return {a: c.most_common(1)[0][0] for a, c in votes.items()}


def write_diff(ref, shot, bad, expected, path: Path, height: int = HEIGHT) -> None:
    """[reference | screenshot | disagreeing pixels in red over a dimmed reference]."""
    marks = [(255, 0, 0) if i in bad else (e[0] // 4, e[1] // 4, e[2] // 4) for i, e in enumerate(expected)]
    mask = Image.frombytes("RGB", (WIDTH, height), bytes(v for m in marks for v in m))
    out = Image.new("RGB", (WIDTH * 3, height))
    for n, img in enumerate((ref.convert("RGB"), shot, mask)):
        out.paste(img, (n * WIDTH, 0))
    out.save(path)


def compare(in_dir, name, run_dir, console=None) -> dict:
    in_dir, run_dir = Path(in_dir), Path(run_dir)
    console = console or ("snes" if (in_dir / f"{name}.vram.json").exists() else "nes")
    (run_dir / "diff.png").unlink(missing_ok=True)
    snes = console == "snes"
    result = {"name": name, "console": console,
              "gate_c": gate_c_snes(in_dir, name, run_dir) if snes else gate_c(in_dir, name, run_dir),
              "gate_d": gate_d(in_dir / f"{name}.ref.png", run_dir / "screenshot.png", run_dir / "diff.png",
                               SNES_HEIGHT if snes else HEIGHT)}
    result["ok"] = result["gate_c"]["ok"] and result["gate_d"]["ok"]
    (run_dir / "compare.json").write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    return result


def report(result: dict) -> str:
    lines = [f"{result['name']}: {'PASS' if result['ok'] else 'FAIL'}"]
    for ext, f in result["gate_c"]["files"].items():
        status = "ok" if f["ok"] else f.get("error") or f"{f['mismatches']} bytes differ"
        lines.append(f"  (c) {ext}: {status}" + (f" -- {f['hint']}" if "hint" in f else ""))
        lines += [f"      offset {m['offset']:#06x}: expected {m['expected']}, got {m['got']}" for m in f["first"]]
    d = result["gate_d"]
    if "error" in d:
        lines.append(f"  (d) {d['error']}")
        return "\n".join(lines)
    lines.append(f"  (d) {'ok' if d['ok'] else 'mismatch'}: {d['expected_colors']} expected colors, "
                 f"{d['screen_colors']} screen colors, {d['mismatched_pixels']} pixels differ, "
                 f"{len(d['collisions'])} colliding colors")
    if "warning" in d:
        lines.append(f"      warning: {d['warning']}")
    if "mismatch_bbox" in d:
        lines.append(f"      mismatch bbox (x0, y0, x1, y1) = {tuple(d['mismatch_bbox'])}")
    lines += [f"      ({m['x']}, {m['y']}): expected {tuple(m['expected'])} -> {tuple(m['mapped_to'])}, "
              f"got {tuple(m['got'])}" for m in d["first"]]
    lines += [f"      collision: {tuple(e)} -> {tuple(g)}" for e, g in d["collisions"][:MAX_LISTED]]
    return "\n".join(lines)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--in-dir", required=True, type=Path)
    ap.add_argument("--name", required=True)
    ap.add_argument("--run-dir", required=True, type=Path)
    ap.add_argument("--console", choices=("nes", "snes"), default=None, help="default: snes if N.vram.json exists")
    args = ap.parse_args(argv)
    result = compare(args.in_dir, args.name, args.run_dir, args.console)
    print(report(result))
    if not result["gate_d"]["ok"] and (args.run_dir / "diff.png").exists():
        print(f"  diff: {args.run_dir / 'diff.png'}")
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

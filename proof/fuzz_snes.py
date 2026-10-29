#!/usr/bin/env python3
"""Random SNES scenes through the whole proof: validator -> bytes -> reference PPU -> LoROM -> Mesen 2.

    fuzz_snes.py --mesen <binary> --work-dir W [--seeds 0-19]

Each seed writes one random .px.js (BG1, often BG2 and a 2bpp BG3 HUD, 1-14 OBJs of random sizes, flips and
positions, including OBJs straddling the left and right edges and the bottom; sometimes a pinned obsel or a
forced OBJ size). Scenes the validator calls legal must pass gates (b), (c) and (d). Scenes that fail only the
runtime limits (SNES-H10/H11) are built with --force and Mesen must drop exactly what the model predicts.
Other verdicts are counted and skipped. Exit 0 only if no scene disagrees.
"""
import argparse
import json
import random
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "src"))
sys.path.insert(0, str(HERE))
import build_snes_rom  # noqa: E402
import compare  # noqa: E402
import run_mesen  # noqa: E402
from retrogaze.codemode.build import scene_for_rom  # noqa: E402

KEYS = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"


def art(seed: int) -> str:
    r = random.Random(seed)
    keys = iter(KEYS)

    def group(n):
        out = []
        for _ in range(n):
            k = next(keys)
            out.append((k, f"snes({r.randrange(32)}, {r.randrange(32)}, {r.randrange(32)})"))
        return out

    bg_a, bg_b, bg_c = group(r.randint(3, 9)), group(r.randint(3, 9)), group(r.randint(2, 6))
    hud = group(3)
    objg = [group(r.randint(2, 7)) for _ in range(3)]
    lines = ["pal({ " + ", ".join(f"{k}: {v}" for k, v in bg_a + bg_b + bg_c + hud + sum(objg, [])) + " })"]

    def shapes(g, w, h, n):
        ops = []
        for _ in range(n):
            k = r.choice(g)[0]
            x, y = r.randrange(w), r.randrange(h)
            kind = r.random()
            if kind < 0.45:
                ops.append(f'rect({x}, {y}, {r.randint(2, max(2, w // 2))}, {r.randint(2, max(2, h // 2))}, "{k}")')
            elif kind < 0.75:
                ops.append(f'circ({x}, {y}, {r.randint(1, max(1, min(w, h) // 3))}, "{k}")')
            elif kind < 0.9:
                ops.append(f'line({x}, {y}, {r.randrange(w)}, {r.randrange(h)}, "{k}")')
            else:
                ops.append(f'noise(0, 0, {w}, {h}, "{k}", {r.choice([0.05, 0.1, 0.2])}, {r.randint(1, 99)})')
        return ", ".join(ops)

    lines.append(f'scene("one", {{ w: 256, h: 224 }}, rect(0, 0, 256, 224, "{bg_a[0][0]}"), '
                 f'{shapes(bg_a, 128, 224, r.randint(2, 6))}, {shapes(bg_b, 256, 224, r.randint(2, 6))})')
    spec = ['bg1: "one"']
    if r.random() < 0.7:
        lines.append(f'scene("two", {{ w: 256, h: 224 }}, {shapes(bg_c, 256, 224, r.randint(2, 5))})')
        spec.append('bg2: "two"')
    if r.random() < 0.6:
        t = r.choice(["SCORE 0042", "HI 999", "LIFE x3", "STAGE 1-2"])
        lines.append(f'scene("hud", {{ w: 256, h: 224 }}, text({r.randrange(8, 120)}, {r.randrange(4, 200)}, "{t}", '
                     f'"{hud[0][0]}"), px(2, 2, "{hud[1][0]}"), px(3, 2, "{hud[2][0]}"))')
        spec.append('bg3: "hud"')
    obj = []
    for i in range(r.randint(1, 14)):
        g = r.choice(objg)
        w, h = r.choice([8, 12, 16, 16, 24, 32, 32, 40, 48]), r.choice([8, 12, 16, 16, 24, 32, 32])
        lines.append(f'sprite("s{i}", {{ w: {w}, h: {h} }}, rect(0, 0, {w}, {h}, "{g[0][0]}"), '
                     f'{shapes(g, w, h, r.randint(1, 5))})')
        x = r.choice([r.randint(-20, 250), r.randint(-40, -1), r.randint(240, 255), r.randint(0, 220)])
        y = r.choice([r.randint(0, 200), max(0, 224 - h // 2), r.randint(0, 120)])
        opts = {}
        if r.random() < 0.35:
            opts["flip"] = r.choice(["x", "y", "xy"])
        if r.random() < 0.15:
            opts["size"] = r.choice(["16x16", "32x32"])
        obj.append(f'["s{i}", {x}, {y}' + (f", {json.dumps(opts)}" if opts else "") + "]")
    if r.random() < 0.3:                # a crowded line: range (32 OBJs) and time (34 slivers) overflows
        g = r.choice(objg)
        w = r.choice([8, 16])
        lines.append(f'sprite("crowd", {{ w: {w}, h: {w} }}, rect(0, 0, {w}, {w}, "{g[0][0]}"), '
                     f'{shapes(g, w, w, 2)})')
        y, step = r.randint(20, 180), r.choice([5, 7, 9, 12])
        for k in range(r.randint(18, 40)):
            obj.append(f'["crowd", {(k * step) % 280 - 20}, {y + r.choice([0, 0, 0, 4])}]')
    spec.append("obj: [" + ", ".join(obj) + "]")
    spec.append(f"backdrop: snes({r.randrange(32)}, {r.randrange(32)}, {r.randrange(32)})")
    if r.random() < 0.2:
        spec.append(f"obsel: {r.choice([0, 1, 3])}")
    lines.append('rg.scene("fuzz", { ' + ", ".join(spec) + " })")
    return "\n".join(lines) + "\n"


def run(seed: int, mesen: Path, work: Path) -> dict:
    d = work / f"seed{seed:03d}"
    (d / "scene").mkdir(parents=True, exist_ok=True)
    src = d / "fuzz.px.js"
    src.write_text(art(seed))
    res = {"seed": seed}
    try:
        files, name, m = scene_for_rom(src, "fuzz", force=True, console="snes")
    except Exception as exc:          # not legal and not runtime-only, or not buildable
        res["skipped"] = f"{type(exc).__name__}: {str(exc)[:160]}"
        return res
    errors = sorted({v.rule for v in m.violations if v.severity == "error"})
    res["errors"] = errors
    res["obsel"], res["objs"] = m.obsel, len(m.oam[0])
    res["layers"] = m.layers
    for k, v in files.items():
        (d / "scene" / k).write_bytes(v)
    ref = np.array(Image.open(d / "scene" / f"{name}.ref.png").convert("RGBA"))
    diff = {(int(x), int(y)) for y, x in np.argwhere((ref != m.composites[0]).any(axis=2))}
    res["gate_b"] = (not diff) if not errors else (diff <= m.predicted_drops(0))
    build_snes_rom.build(d / "scene", name, d / f"{name}.sfc")
    run_mesen.run(mesen, d / f"{name}.sfc", d / "run")
    cmp = compare.compare(d / "scene", name, d / "run", "snes")
    res["gate_c"], res["gate_d"] = cmp["gate_c"]["ok"], cmp["gate_d"]["ok"]
    res["ok"] = res["gate_b"] and res["gate_c"] and res["gate_d"]
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mesen", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--seeds", default="0-19")
    args = ap.parse_args(argv)
    a, _, b = args.seeds.partition("-")
    seeds = range(int(a), int(b or a) + 1)
    results = [run(s, args.mesen, args.work_dir) for s in seeds]
    args.work_dir.mkdir(parents=True, exist_ok=True)
    (args.work_dir / "fuzz_summary.json").write_text(json.dumps(results, indent=1) + "\n")
    ran = [r for r in results if "ok" in r]
    bad = [r for r in ran if not r["ok"]]
    for r in results:
        print(r)
    print(f"{len(ran)} scenes ran in Mesen ({sum(1 for r in ran if not r['errors'])} legal, "
          f"{sum(1 for r in ran if r['errors'])} runtime-limit), {len(results) - len(ran)} skipped, "
          f"{len(bad)} disagreed")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())

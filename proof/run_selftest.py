#!/usr/bin/env python3
"""End-to-end self-test of the NES proof harness, independent of the exporter.

    run_selftest.py --mesen <binary> --work-dir W [--frames 10] [--timeout 60]

make_selftest -> build_nes_rom (twice, sha256 must match) -> run_mesen -> compare, for every scene in
make_selftest.SCENES, plus two empirical checks of Mesen against the reference PPU model:
  * Y convention: in "selftest", OAM #4 (Y byte $4F, one opaque row) is on line $50, not $4F or $51;
  * 8 sprites per line: "selftest_9line" passes (reference drops #8 on lines 128-135), and the negative
    control "selftest_9line_nodrop" passes gate (c) but fails gate (d) on exactly the pixels where
    the two references differ (sprite #8 on lines 128-135).
Exit 0 only if everything above holds. Writes W/selftest_summary.json. Needs Pillow (compare.py).
"""
import argparse
import json
import sys
import time
from pathlib import Path

sys.dont_write_bytecode = True    # keep proof/ free of __pycache__
import build_nes_rom  # noqa: E402
import compare  # noqa: E402
import make_selftest  # noqa: E402
import run_mesen  # noqa: E402


def timed(fn, *args):
    start = time.monotonic()
    value = fn(*args)
    return value, round(time.monotonic() - start, 2)


def screen_and_ref(scenes: Path, runs: Path, name: str, ref_name: str):
    ref = compare.pixels(compare.Image.open(scenes / f"{ref_name}.ref.png").convert("RGBA"), 4)
    shot = compare.pixels(compare.Image.open(runs / name / "screenshot.png").convert("RGB"), 3)
    return ref, shot


def check_y_marker(scenes: Path, runs: Path) -> dict:
    """OAM #4 of "selftest": Y byte $4F, tile = one row of color 3 ($30), X = 40..47."""
    ref, shot = screen_and_ref(scenes, runs, "selftest", "selftest")
    color_map, _ = compare.bijection(ref, shot)
    marker = color_map[tuple(make_selftest.nes_rgb(0x30)) + (255,)]
    rows = [y for y in range(0x4C, 0x55) if all(shot[y * 256 + x] == marker for x in range(40, 48))]
    return {"ok": rows == [0x50], "rows_with_marker": rows, "oam_y_byte": 0x4F}


def check_nodrop_control(scenes: Path, runs: Path) -> dict:
    drop = compare.pixels(compare.Image.open(scenes / "selftest_9line.ref.png").convert("RGBA"), 4)
    nodrop, shot = screen_and_ref(scenes, runs, "selftest_9line_nodrop", "selftest_9line_nodrop")
    predicted = {i for i, (a, b) in enumerate(zip(drop, nodrop)) if a != b}
    _, bad = compare.bijection(nodrop, shot)
    rows = sorted({i // 256 for i in predicted})
    cols = sorted({i % 256 for i in predicted})
    return {"ok": bool(predicted) and set(bad) == predicted, "predicted_pixels": len(predicted),
            "mismatched_pixels": len(bad), "predicted_rows": [rows[0], rows[-1]],
            "predicted_cols": [cols[0], cols[-1]]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mesen", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=60)
    args = ap.parse_args(argv)
    scenes, roms, runs = (args.work_dir / d for d in ("scenes", "roms", "runs"))
    make_selftest.write_all(scenes)

    summary, ok = {"scenes": {}}, True
    for name, (_, _, expect_pass) in make_selftest.SCENES.items():
        rom = roms / f"{name}.nes"
        sha, build_s = timed(build_nes_rom.build, scenes, name, rom)
        sha_again = build_nes_rom.build(scenes, name, roms / f"{name}.rebuild.nes")
        run, mesen_s = timed(run_mesen.run, args.mesen, rom, runs / name, args.frames, args.timeout)
        result, compare_s = timed(compare.compare, scenes, name, runs / name)
        print(compare.report(result))
        as_expected = (result["ok"] if expect_pass
                       else result["gate_c"]["ok"] and not result["gate_d"]["ok"])
        deterministic = sha == sha_again
        ok &= as_expected and deterministic
        print(f"  rom sha256 {sha} (rebuild {'identical' if deterministic else 'DIFFERS'}); "
              f"build {build_s} s, mesen {mesen_s} s [{run['info']}], compare {compare_s} s; "
              f"{'as expected' if as_expected else 'NOT AS EXPECTED'}"
              f"{'' if expect_pass else ' (negative control: gate (d) must fail)'}")
        summary["scenes"][name] = {"rom_sha256": sha, "deterministic": deterministic,
                                   "expect_pass": expect_pass, "as_expected": as_expected,
                                   "gate_c": result["gate_c"]["ok"], "gate_d": result["gate_d"]["ok"],
                                   "seconds": {"build": build_s, "mesen": mesen_s, "compare": compare_s}}

    summary["y_marker"] = check_y_marker(scenes, runs)
    summary["sprite_limit"] = check_nodrop_control(scenes, runs)
    y, lim = summary["y_marker"], summary["sprite_limit"]
    print(f"Y convention: OAM Y byte $4F -> marker row on screen line(s) "
          f"{[f'${r:02X}' for r in y['rows_with_marker']]}: {'confirmed' if y['ok'] else 'NOT confirmed'}")
    print(f"8 sprites/line: negative control mismatches {lim['mismatched_pixels']} px, predicted "
          f"{lim['predicted_pixels']} px of OAM #8 on lines {lim['predicted_rows'][0]}-"
          f"{lim['predicted_rows'][1]}, x {lim['predicted_cols'][0]}-{lim['predicted_cols'][1]}: "
          f"{'Mesen drops the highest OAM index' if lim['ok'] else 'NOT as predicted'}")
    ok &= y["ok"] and lim["ok"]
    summary["ok"] = ok
    (args.work_dir / "selftest_summary.json").write_text(json.dumps(summary, indent=1) + "\n")
    print(f"SELFTEST {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())

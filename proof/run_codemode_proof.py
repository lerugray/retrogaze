#!/usr/bin/env python3
"""Code-mode proof of legality, NES (CODE-MODE-SPEC §5, tests M1-26 and M1-27).

    run_codemode_proof.py --mesen <binary> --work-dir W [--update-goldens]

For every scene in SCENES: export it with Retrogaze code mode, build the viewer ROM (twice: the
bytes must match, and match proof/goldens.json), run it in Mesen, then check
  (a) the validator verdict (legal, or the expected rule for a negative fixture),
  (b) the reference PPU render of the exported bytes equals the art composite (legal scenes),
  (c) Mesen's palette RAM, OAM, nametable and CHR equal the exported bytes,
  (d) Mesen's screenshot equals the reference render under a color bijection.
Negative fixtures are built with --force; there the reference must differ from the art composite
only on the sprite pixels the validator says the PPU drops.
M1.1 scenes also check the cartridge (the iNES header of an MMC1 + CHR-RAM ROM: mapper 1, 128 KiB PRG,
no CHR-ROM, 8 KiB CHR-RAM; Mesen's CHR dump is then the CHR-RAM the viewer filled) and, for the flip
scenes, that the OAM really uses all four H/V flip combinations.
Exit 0 only if all of it holds. Writes W/codemode_proof_summary.json.
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
REPO = HERE.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(HERE))
import build_nes_rom  # noqa: E402
import compare  # noqa: E402
import run_mesen  # noqa: E402
from retrogaze.codemode import ppu_ref  # noqa: E402
from retrogaze.codemode.build import scene_for_rom  # noqa: E402

SCENES = [
    {"id": "nes_proof", "art": "examples/codemode/nes_proof.px.js", "scene": "proof", "expect": "legal"},
    {"id": "nes_proof_tileset", "art": "examples/codemode/nes_proof.px.js", "scene": "level", "expect": "legal"},
    {"id": "nes_hero", "art": "examples/codemode/nes_hero.px.js", "scene": "title", "expect": "legal"},
    {"id": "nes_9_on_a_line", "art": "src/tests/fixtures/codemode/nes/nes_H9_fail.px.js", "scene": "line",
     "expect": "NES-H9"},
    # M1.1: Ray's cartridge (MMC1, 8 KiB CHR-RAM), and 8x16 sprites + H/V flips (M1 review F7)
    {"id": "nes_mmc1_chr_ram", "art": "examples/codemode/nes_mmc1.px.js", "scene": "room", "expect": "legal",
     "cart": "mmc1"},
    {"id": "nes_flips_8x8", "art": "examples/codemode/nes_flips.px.js", "scene": "flips8", "expect": "legal",
     "flips": True},
    {"id": "nes_flips_8x16", "art": "examples/codemode/nes_flips.px.js", "scene": "flips16", "expect": "legal",
     "flips": True},
]
# iNES header bytes 4-7 (and NES 2.0 byte 11) per viewer cartridge.
CART_HEADERS = {"nrom": {"prg_16k": 1, "chr_8k": 1, "mapper": 0, "chr_ram": 0},
                "mmc1": {"prg_16k": 8, "chr_8k": 0, "mapper": 1, "chr_ram": 8192}}
GOLDENS = HERE / "goldens.json"


def predicted_drops(m) -> set:
    """Screen pixels of the sprites the validator says are dropped, on the lines it names."""
    out = set()
    for v in m.violations:
        if v.rule != "NES-H9":
            continue
        c = m.oam[0][v.where["oam"]]
        y0, y1 = v.where["lines"]
        for y in range(y0, y1 + 1):
            for u in range(8):
                if c.pix[y - c.top, u] >= 0 and c.x + u < 256:
                    out.add((c.x + u, y))
    return out


def ines_header(rom: bytes) -> dict:
    """The fields of an iNES / NES 2.0 header the viewer carts differ in."""
    assert rom[:4] == b"NES\x1a", "not an iNES file"
    nes2 = rom[7] & 0x0C == 0x08
    shift = rom[11] & 0x0F if nes2 else 0
    return {"prg_16k": rom[4], "chr_8k": rom[5], "mapper": (rom[6] >> 4) | (rom[7] & 0xF0),
            "chr_ram": (64 << shift) if nes2 and shift else (8192 if rom[5] == 0 else 0)}


def flip_bits(oam: bytes, used: int) -> set:
    return {oam[4 * i + 2] & 0xC0 for i in range(used)}


def run_scene(spec, mesen: Path, work: Path, goldens: dict, update: bool) -> dict:
    sid = spec["id"]
    d = work / sid
    scene_dir = d / "scene"
    scene_dir.mkdir(parents=True, exist_ok=True)
    negative = spec["expect"] != "legal"
    files, name, m = scene_for_rom(REPO / spec["art"], spec["scene"], force=negative)
    for fname, data in files.items():
        (scene_dir / fname).write_bytes(data)
    res = {"id": sid, "scene": name, "art": spec["art"]}

    # (a) the validator
    errors = sorted({v.rule for v in m.violations if v.severity == "error"})
    res["gate_a"] = (errors == []) if not negative else (errors == [spec["expect"]])
    res["validator_errors"] = errors

    # (b) reference PPU render vs art composite
    ref = np.array(Image.open(scene_dir / f"{name}.ref.png").convert("RGBA"))
    comp = m.composites[0]
    diff = {(int(x), int(y)) for y, x in np.argwhere((ref != comp).any(axis=2))}
    if negative:
        pred = predicted_drops(m)
        res["gate_b"] = bool(diff) and diff <= pred
        res["predicted_drop_pixels"] = len(pred)
        res["reference_vs_art_diff_pixels"] = len(diff)
    else:
        res["gate_b"] = not diff

    # ROM, twice, deterministic and golden
    rom1, rom2 = d / f"{name}.nes", d / f"{name}.again.nes"
    sha1 = build_nes_rom.build(scene_dir, name, rom1)
    sha2 = build_nes_rom.build(scene_dir, name, rom2)
    res["rom_sha256"] = sha1
    res["rom_deterministic"] = sha1 == sha2
    if update:
        goldens[sid] = sha1
    res["rom_golden"] = goldens.get(sid) == sha1
    cart = build_nes_rom.cart_for(build_nes_rom.read_rom_json(scene_dir / f"{name}.rom.json"))
    res["cart"] = cart
    res["header"] = ines_header(rom1.read_bytes())
    res["cart_ok"] = cart == spec.get("cart", "nrom") and res["header"] == CART_HEADERS[cart]
    if spec.get("flips"):
        res["flip_bits"] = sorted(flip_bits((scene_dir / f"{name}.oam").read_bytes(), len(m.oam[0])))
        res["cart_ok"] = res["cart_ok"] and res["flip_bits"] == [0x00, 0x40, 0x80, 0xC0]

    # (c) and (d) in Mesen
    run_dir = d / "run"
    run_mesen.run(mesen, rom1, run_dir)
    cmp = compare.compare(scene_dir, name, run_dir)
    res["gate_c"] = bool(cmp.get("gate_c", {}).get("ok"))
    res["gate_d"] = bool(cmp.get("gate_d", {}).get("ok"))
    res["compare"] = {k: v for k, v in cmp.items() if k in ("gate_c", "gate_d")}
    res["ok"] = all(res[k] for k in ("gate_a", "gate_b", "gate_c", "gate_d", "rom_deterministic", "rom_golden",
                                     "cart_ok"))
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mesen", required=True, type=Path)
    ap.add_argument("--work-dir", required=True, type=Path)
    ap.add_argument("--update-goldens", action="store_true", help="record ROM sha256s (only after a reviewed change)")
    args = ap.parse_args(argv)
    goldens = json.loads(GOLDENS.read_text()) if GOLDENS.exists() else {}
    results = [run_scene(s, args.mesen, args.work_dir, goldens, args.update_goldens) for s in SCENES]
    if args.update_goldens:
        GOLDENS.write_text(json.dumps(goldens, indent=2, sort_keys=True) + "\n")
    summary = {"ok": all(r["ok"] for r in results), "scenes": results}
    args.work_dir.mkdir(parents=True, exist_ok=True)
    (args.work_dir / "codemode_proof_summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    for r in results:
        gates = " ".join(f"{g}={'ok' if r[g] else 'FAIL'}" for g in ("gate_a", "gate_b", "gate_c", "gate_d"))
        print(f"{r['id']:20} {gates} rom={r['rom_sha256'][:12]} golden={'ok' if r['rom_golden'] else 'FAIL'} "
              f"deterministic={'ok' if r['rom_deterministic'] else 'FAIL'} "
              f"cart={r['cart']}:{'ok' if r['cart_ok'] else 'FAIL'}")
    print("PASS" if summary["ok"] else "FAIL")
    return 0 if summary["ok"] else 1


if __name__ == "__main__":
    sys.exit(main())

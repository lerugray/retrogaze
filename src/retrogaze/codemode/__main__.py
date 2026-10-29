"""
python -m retrogaze.codemode {bind,build,export,rom,verify,audit}

Exit codes: 0 requested tier passed, 1 failed, 2 usage/unsupported, 3 the art did not build,
4 verify: pxl or binding version mismatch.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

from .binding import binding_for, check_supported, render_cheatsheet
from .build import audit, build_path, scene_bytes_for_rom, verify
from .provenance import AUTHORS
from .runner import REPO_ROOT, CodeModeError


def _summary(result) -> str:
    r = result.report
    lines = []
    if r.get("errors"):
        for e in r["errors"]:
            lines.append(f"error {e.get('code', '')}: {e.get('message', '')}")
        return "\n".join(lines)
    lines.append(f"verdict: {r['verdict']} (requested {r['tier_requested']})")
    viols = list(r["violations"]) + [v for s in r["scenes"] for v in s["violations"]]
    for v in viols:
        where = (v.get("blame") or [{}])[0].get("loc") or ""
        tag = "warning" if v["severity"] == "warning" else v["tier"]
        scope = f"scene '{v['scene']}'" if v.get("scene") else f"asset '{v.get('asset')}'"
        lines.append(f"  {v['rule']:8} [{tag}] {where}: {scope}: {v['message']}")
        if v.get("hint"):
            lines.append(f"           hint: {v['hint']}")
    for s in r["scenes"]:
        if s.get("checked") and r.get("console") == "snes":
            b = s["budgets"]
            lines.append(f"  scene {s['name']}: {'legal' if s['legal'] else 'NOT legal'}; OBSEL {s['obsel']} "
                         f"({'/'.join(s['obj_sizes'])}); BG tiles {b['bg_tiles']['used']}/1024 per layer, "
                         f"OBJ tiles {b['obj_tiles']['used']}/512, OAM {b['oam']['used']}/128, "
                         f"max {b['per_line']['used']}/32 OBJs and {b['slivers']['used']}/34 slivers per line, "
                         f"VRAM {b['vram']['used']}/65536 bytes, backdrop {s['backdrop']}")
        elif s.get("checked"):
            b = s["budgets"]
            lines.append(f"  scene {s['name']}: {'legal' if s['legal'] else 'NOT legal'}; "
                         f"BG tiles {b['bg_tiles']['used']}/256, OBJ tiles {b['obj_tiles']['used']}/256, "
                         f"OAM {b['oam']['used']}/64, max {b['per_line']['used']}/8 per line, backdrop {s['backdrop']}")
    if result.out_dir:
        lines.append(f"wrote {len(result.outputs)} files to {result.out_dir}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m retrogaze.codemode", description="Retrogaze code mode")
    sub = ap.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("bind", help="print the binding cheat sheet for a console")
    b.add_argument("--console", default="nes")
    b.add_argument("--tier", default="legal")
    b.add_argument("--json", action="store_true", help="print the raw binding JSON")

    for name, helptext in (("build", "build, check and export an art file"),
                           ("export", "same as build (hardware files are written when the legal tier passes)")):
        p = sub.add_parser(name, help=helptext)
        p.add_argument("entry", type=Path)
        p.add_argument("--console", default="nes")
        p.add_argument("--tier", default="legal", choices=("like", "legal"))
        p.add_argument("--author", default="unknown", choices=AUTHORS)
        p.add_argument("--out", type=Path, default=None)
        p.add_argument("--json", action="store_true", help="print the report JSON")
        p.add_argument("--no-write", action="store_true")

    r = sub.add_parser("rom", help="build a viewer ROM that shows a scene (NES .nes or SNES LoROM .sfc)")
    r.add_argument("entry", type=Path)
    r.add_argument("--console", default="nes", choices=("nes", "snes"))
    r.add_argument("--scene", default=None)
    r.add_argument("--out", type=Path, default=None)
    r.add_argument("--force", action="store_true",
                   help="also build scenes that break only runtime limits (NES-H8/H9, SNES-H10/H11)")

    v = sub.add_parser("verify", help="rebuild an output folder from its recorded sources and compare")
    v.add_argument("out_dir", type=Path)

    a = sub.add_parser("audit", help="check that every image/binary asset under a folder is code-drawn")
    a.add_argument("root", type=Path)

    args = ap.parse_args(argv)

    if args.cmd == "bind":
        try:
            check_supported(args.console, args.tier)
        except ValueError as e:
            print(f"error: {e}", file=sys.stderr)
            return 2
        print(json.dumps(binding_for(args.console, args.tier), indent=2) if args.json else render_cheatsheet(args.console))
        return 0

    if args.cmd in ("build", "export"):
        result = build_path(args.entry, console=args.console, tier=args.tier, author=args.author, out_dir=args.out,
                            write=not args.no_write)
        print(json.dumps(result.report, indent=2) if args.json else _summary(result))
        return result.exit_code

    if args.cmd == "rom":
        script = REPO_ROOT / "proof" / ("build_snes_rom.py" if args.console == "snes" else "build_nes_rom.py")
        if not script.is_file() or not shutil.which("ca65") or not shutil.which("ld65"):
            print(f"error: the viewer ROM needs cc65 (ca65, ld65) on PATH and proof/{script.name}", file=sys.stderr)
            return 2
        try:
            files, scene = scene_bytes_for_rom(args.entry, args.scene, args.force, args.console)
        except CodeModeError as e:
            print(f"error {e.code}: {e}", file=sys.stderr)
            return 1 if e.code == "CM-INPUT" else 3
        ext = "sfc" if args.console == "snes" else "nes"
        out = args.out or (args.entry.resolve().parent / "out" / args.console / "rom" / f"{scene}.{ext}")
        out.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory() as tmp:
            for name, data in files.items():
                (Path(tmp) / name).write_bytes(data)
                (out.parent / name).write_bytes(data)
            proc = subprocess.run([sys.executable, str(script), "--in-dir", tmp, "--name", scene, "--out", str(out)],
                                  capture_output=True, text=True)
        sys.stdout.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        if proc.returncode == 0:
            print(f"wrote {out}")
        return 0 if proc.returncode == 0 else 3

    if args.cmd == "verify":
        code, msgs = verify(args.out_dir)
        print("\n".join(msgs))
        return code

    if args.cmd == "audit":
        code, msgs = audit(args.root)
        print("\n".join(msgs))
        return code
    return 2


if __name__ == "__main__":
    sys.exit(main())

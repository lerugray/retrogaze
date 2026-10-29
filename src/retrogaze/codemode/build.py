"""
Code-mode build: art source -> pixels -> tier checks -> hardware bytes -> outputs.

``build()`` works in memory (the API uses it directly); ``build_path()`` reads an
art folder and writes ``out/<console>/<tier>/``. ``verify()`` rebuilds from the
recorded sources and compares; ``audit()`` checks a folder of game assets.

Exit codes: 0 requested tier passed, 1 failed, 2 usage/unsupported,
3 the art did not build, 4 verify: pxl or binding version mismatch.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import math
import os
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from .. import __version__ as RETROGAZE_VERSION
from . import ppu_ref, ppu_ref_snes
from .binding import binding_for, binding_sha256, check_supported, nes_byte_hex
from .encode import snes as snes_enc
from .encode.nes import EncodeError, c_header, ca65_include, encode_scene, metasprite_source, rom_json
from .hw import nes, snes
from .hw.common import Asset, Violation, hex_of, rgb_of
from .provenance import (
    AUTHORS, block, indexed_png, pixels_sha256, png_rgba, read_png_provenance, rgba_png, sha256_bytes,
    vendored_tree_sha256,
)
from .runner import REPO_ROOT, CodeModeError, read_art_dir, run_loader

CODEMODE_VERSION = f"{RETROGAZE_VERSION}+codemode.m2"
REPORT_SCHEMA = "retrogaze.report/1"
MANIFEST = "manifest.json"
HARDWARE_EXT = (".chr", ".pal", ".nam", ".oam")
STILL_MS = 100


@dataclass
class BuildResult:
    exit_code: int
    verdict: str
    report: dict
    outputs: dict[str, bytes] = field(default_factory=dict)
    manifest: dict | None = None
    out_dir: Path | None = None
    models: list = field(default_factory=list)


def _json(obj) -> bytes:
    return (json.dumps(obj, indent=2, sort_keys=True) + "\n").encode()


def _git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5)
        return out.stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# ---------------------------------------------------------------------------
# Build (in memory)
# ---------------------------------------------------------------------------


def build(files: dict[str, str], entry: str, *, console: str = "nes", tier: str = "legal",
          author: str = "unknown", hardware: bool = True) -> BuildResult:
    try:
        check_supported(console, tier)
        if author not in AUTHORS:
            raise ValueError(f"author must be one of {', '.join(AUTHORS)}")
    except ValueError as e:
        return BuildResult(2, "error", {"schema": REPORT_SCHEMA, "verdict": "error", "errors": [
            {"code": "CM-USAGE", "message": str(e)}]})
    binding = binding_for(console, tier)
    bsha = binding_sha256(binding)
    try:
        raw = run_loader(files, entry, binding)
    except CodeModeError as e:
        return BuildResult(3, "error", {"schema": REPORT_SCHEMA, "console": console, "tier_requested": tier,
                                        "verdict": "error", "errors": e.errors})
    assets = {a["name"]: Asset.from_json(a) for a in raw.assets}
    an = (snes if console == "snes" else nes).analyze(assets, raw.scenes, raw.tilesets, raw.pins)

    encoded, problems = {}, []
    for m in an.scenes:
        if not m.legal:
            continue
        if console == "snes":
            b, problem = _roundtrip_snes(m)
            if problem:
                problems.append(problem)
            else:
                encoded[m.name] = b
            continue
        try:
            b = encode_scene(m)
        except EncodeError as e:
            problems.append(Violation("CM-ROUNDTRIP", f"encoder refused a scene the rules passed: {e}", scene=m.name))
            continue
        for s in range(m.states):
            ref = ppu_ref.render(b.chr[m.chr_index(s)], b.pal, b.nam[s], b.oam[s], b.rom)
            want = m.composites[s]
            if not m.left8:      # hidden on purpose (NES-H14 warns): the console shows the backdrop there
                want = want.copy()
                want[:, :8, :3] = [(m.backdrop >> 16) & 255, (m.backdrop >> 8) & 255, m.backdrop & 255]
            if not np.array_equal(ref, want):
                bad = np.argwhere((ref != want).any(axis=2))[0]
                problems.append(Violation("CM-ROUNDTRIP", f"reference PPU render differs from the art at ({bad[1]},{bad[0]}) "
                                          f"in state {s}: encoder/rules disagreement", scene=m.name, frame=s))
                break
        else:
            encoded[m.name] = b
    for p in problems:
        p.message = "[internal] " + p.message
        m = next(x for x in an.scenes if x.name == p.scene)
        m.violations.append(p)

    like_errors = [v for v in an.like if v.severity == "error"]
    like_ok = not like_errors
    scene_ok = all(m.legal for m in an.scenes) and all(m.name in encoded for m in an.scenes)
    verdict = "legal" if like_ok and scene_ok else ("like" if like_ok else "fail")
    passed = verdict == "legal" or (tier == "like" and verdict in ("like", "legal"))
    report = _report(console, tier, verdict, an, assets, raw, encoded)
    prov = block(binding_sha=bsha, version=CODEMODE_VERSION, sources=files, entry=entry, author=author,
                 console=console, tier=tier, verdict=verdict)
    outputs = _outputs(an, assets, raw, encoded, prov, report,
                       hardware=hardware and tier == "legal" and verdict == "legal", console=console)
    manifest = {
        "schema": "retrogaze.manifest/1",
        "provenance": {**prov, "renderer": {**prov["renderer"], "node": raw.node},
                       "retrogaze": {**prov["retrogaze"], "git_commit": _git_commit()},
                       "built_at": _dt.datetime.now(_dt.timezone.utc).replace(microsecond=0).isoformat()},
        "build": {"console": console, "tier": tier, "author": author, "entry": entry, "files": sorted(files)},
        "outputs": {k: sha256_bytes(v) for k, v in sorted(outputs.items())},
    }
    return BuildResult(0 if passed else 1, verdict, report, outputs, manifest, models=an.scenes)


def _roundtrip_snes(m):
    """Encode a legal SNES scene and render the bytes back; (bytes, None) or (None, CM-ROUNDTRIP violation)."""
    try:
        b = snes_enc.encode_scene(m)
    except snes_enc.EncodeError as e:
        return None, Violation("CM-ROUNDTRIP", f"encoder refused a scene the rules passed: {e}", scene=m.name)
    for s in range(m.states):
        ref = ppu_ref_snes.render(b.vram(s), b.cgram, b.oam[s], b.registers)
        if not np.array_equal(ref, m.composites[s]):
            bad = np.argwhere((ref != m.composites[s]).any(axis=2))[0]
            return None, Violation("CM-ROUNDTRIP", f"reference PPU render differs from the art at ({bad[1]},{bad[0]}) "
                                   f"in state {s}: encoder/rules disagreement", scene=m.name, frame=s)
    return b, None


def _snes_scene_report(m) -> dict:
    words = lambda slots: [[f"${snes_enc.cgram_word(hex_of(c)):04X}" if c is not None else None for c in p]  # noqa: E731
                           for p in slots if any(c is not None for c in p)]
    return {
        "mode": 1, "layers": m.layers, "bg3_front": m.bg3_front, "obsel": m.obsel,
        "obj_sizes": [f"{w}x{h}" for w, h in snes.OBSEL_PAIRS[m.obsel]],
        "chr_model": m.chr_model, "states": m.states,
        "backdrop": f"${snes_enc.cgram_word(m.backdrop_hex):04X}",
        "bg_palettes": words(m.bg_slots), "obj_palettes": words(m.obj_slots),
        "budgets": {
            "bg_tiles": {"used": max((len(t) for ts in m.bg_tiles.values() for t in ts), default=0),
                         "max": snes.BG_TILES},
            "obj_tiles": {"used": max((sum(w * h // 64 for _, w, h, _ in bl) for bl in m.obj_blocks), default=0),
                          "max": snes.OBJ_TILES},
            "oam": {"used": max((len(o) for o in m.oam), default=0), "max": snes.MAX_OBJ},
            "per_line": {"used": max((st["per_line"] for st in m.line_stats), default=0), "max": snes.PER_LINE},
            "slivers": {"used": max((st["slivers"] for st in m.line_stats), default=0), "max": snes.SLIVERS},
            "vram": {"used": m.vram.used if m.vram else m.vram_need, "max": snes.VRAM_BYTES},
        },
        "vram": m.vram.to_json() if m.vram else None,
    }


def _report(console, tier, verdict, an, assets, raw, encoded) -> dict:
    scenes = []
    for m in an.scenes:
        s = {"name": m.name, "declared": m.declared, "checked": m.checked, "legal": m.legal}
        if m.checked and console == "snes":
            s.update(_snes_scene_report(m))
        elif m.checked:
            ch = 16 if m.sprite_size == "8x16" else 8
            s.update({
                "sprite_size": m.sprite_size, "chr_model": m.chr_model, "states": m.states,
                "backdrop": f"${m.backdrop_byte:02X}",
                "bg_palettes": [[f"${b:02X}" for b in p] for p in m.bg_palette_bytes],
                "obj_palettes": [[f"${b:02X}" for b in p] for p in m.obj_palette_bytes],
                "budgets": {
                    "bg_tiles": {"used": max((len(t) for t in m.bg_tiles), default=0), "max": 256},
                    "obj_tiles": {"used": max((len(t) for t in m.obj_tiles), default=0) * (2 if ch == 16 else 1), "max": 256},
                    "oam": {"used": max((len(o) for o in m.oam), default=0), "max": 64},
                    "per_line": {"used": max((max((sum(1 for c in o if c.top <= y < c.top + c.h) for y in range(240)),
                                                  default=0) for o in m.oam), default=0), "max": 8},
                },
            })
        if m.info:
            s["info"] = m.info
        s["violations"] = [v.to_dict() for v in m.violations]
        scenes.append(s)
    return {
        "schema": REPORT_SCHEMA,
        "console": console,
        "tier_requested": tier,
        "verdict": verdict,
        "tiers": {"like": not [v for v in an.like if v.severity == "error"],
                  "legal": verdict == "legal"},
        "assets": [{"name": n, "kind": a.kind, "role": an.roles[n], "size": [a.frames[0].shape[1], a.frames[0].shape[0]],
                    "frames": len(a.frames), "loc": a.loc} for n, a in assets.items()],
        "violations": [v.to_dict() for v in an.like],
        "info": an.like_info,
        "scenes": scenes,
        "logs": raw.logs,
    }


# ---------------------------------------------------------------------------
# Outputs
# ---------------------------------------------------------------------------


def _shelf(items, cols, pad):
    per_row = cols or math.ceil(math.sqrt(len(items)))
    x = y = row_h = width = 0
    placed = []
    for i, (name, img, ms) in enumerate(items):
        if i and i % per_row == 0:
            x, y, row_h = 0, y + row_h + pad, 0
        placed.append((name, img, ms, x, y))
        width = max(width, x + img.shape[1])
        x += img.shape[1] + pad
        row_h = max(row_h, img.shape[0])
    sheet = np.zeros((y + row_h, width, 4), dtype=np.uint8)
    for _, img, _, px, py in placed:
        region = sheet[py:py + img.shape[0], px:px + img.shape[1]]
        mask = img[..., 3] > 0
        region[mask] = img[mask]
    return sheet, placed


def _cells_for(asset: str, frame: int, models, encoded) -> list[dict]:
    for m in models:
        if m.name not in encoded:
            continue
        for s in range(m.states):
            for i, c in enumerate(m.oam[s]):
                if c.asset == asset and c.frame == frame:
                    pl = m.spec["obj"][c.placement]
                    px, py = int(pl[1]), int(pl[2])
                    return [{"x": d.x - px, "y": d.top - py, "w": 8, "h": d.h,
                             "tile": encoded[m.name].tile_bytes[(s, j)], "palette": d.palette,
                             "flip": ("x" if d.flip_h else "") + ("y" if d.flip_v else "")}
                            for j, d in enumerate(m.oam[s]) if d.asset == asset and d.placement == c.placement]
    return []


def _cells_for_snes(asset: str, frame: int, models, encoded) -> list[dict]:
    for m in models:
        if m.name not in encoded:
            continue
        for s in range(m.states):
            for o in m.oam[s]:
                if o.asset == asset and o.frame == frame:
                    pl = m.spec["obj"][o.placement]
                    px, py = int(pl[1]), int(pl[2])
                    return [{"x": d.x - px, "y": d.top - py, "w": d.w, "h": d.h, "tile": d.tile, "palette": d.palette,
                             "flip": ("x" if d.flip_h else "") + ("y" if d.flip_v else "")}
                            for d in m.oam[s] if d.asset == asset and d.placement == o.placement]
    return []


def _snes_screen_index(m) -> tuple[np.ndarray, list[int]]:
    """CGRAM indices of the legal SNES screen (state 0) and the 256 CGRAM colors, in the composite's paint order."""
    idx = np.zeros((snes.H, snes.W), dtype=np.int32)
    order = ("bg2", "bg1", "obj", "bg3") if m.bg3_front else ("bg3", "bg2", "bg1", "obj")
    for layer in order:
        if layer == "obj":
            for o in reversed(m.oam[0]):
                for v in range(o.h):
                    for u in range(o.w):
                        y, x = o.top + v, o.x + u
                        if o.pix[v, u] >= 0 and 0 <= y < snes.H and 0 <= x < snes.W:
                            idx[y, x] = 128 + 16 * o.palette + int(o.pattern[v, u])
            continue
        if layer not in m.layers:
            continue
        plane = m.planes[layer][0]
        for ty in range(snes.H // 8):
            for tx in range(32):
                block = plane[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8]
                p = int(m.tile_pal[layer][0][ty, tx])
                slots = snes.q_slots(m.bg_slots, p) if layer == "bg3" else m.bg_slots[p]
                pat = snes.index_pattern(block, slots).astype(np.int32)
                base = 4 * p if layer == "bg3" else 16 * p
                region = idx[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8]
                idx[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8] = np.where(pat > 0, base + pat, region)
    cg = snes_enc.cgram_bytes(m)
    colors = [rgb_of(snes.word_hex(cg[2 * i] | (cg[2 * i + 1] << 8))) for i in range(256)]
    return idx, colors


def _snes_hardware(m, b, prov) -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    n = m.name
    header = (f"Retrogaze code mode, code-drawn (IPTC algorithmicMedia); pxl {prov['renderer']['commit'][:12]}; "
              f"source {prov['source']['entry']}")
    files: dict[str, str] = {}
    for layer in m.layers:
        ext = "4bpp" if snes.BPP[layer] == 4 else "2bpp"
        files[f"{layer}_chr"] = f"{n}.{layer}.{ext}"
        files[f"{layer}_map"] = f"{n}.{layer}.map"
        out[f"snes/{n}.{layer}.{ext}"] = b.chr[layer][0]
        for k in range(1, len(b.chr[layer])):
            out[f"snes/{n}_c{k}.{layer}.{ext}"] = b.chr[layer][k]
        out[f"snes/{n}.{layer}.map"] = b.maps[layer][0]
        for st in range(1, m.states):
            out[f"snes/{n}_s{st}.{layer}.map"] = b.maps[layer][st]
    if b.obj_chr:
        files["obj_chr"] = f"{n}.obj.4bpp"
        out[f"snes/{n}.obj.4bpp"] = b.obj_chr[0]
        for k in range(1, len(b.obj_chr)):
            out[f"snes/{n}_c{k}.obj.4bpp"] = b.obj_chr[k]
    files["cgram"], files["oam"] = f"{n}.cgram", f"{n}.oam"
    out[f"snes/{n}.cgram"] = b.cgram
    out[f"snes/{n}.oam"] = b.oam[0]
    for st in range(1, m.states):
        out[f"snes/{n}_s{st}.oam"] = b.oam[st]
    for name, data in snes_enc.palette_slices(m, b.cgram).items():
        out[f"snes/pal/{n}.{name}.pal"] = data
    out[f"snes/{n}.vram.json"] = b.vram_json(n, files).encode()
    ref = ppu_ref_snes.render(b.vram(0), b.cgram, b.oam[0], b.registers)
    out[f"snes/{n}.ref.png"] = rgba_png(ref, prov, {"scene": n, "reference_ppu": True})
    out[f"snes/{n}.s"] = snes_enc.ca65_include(m, b, files, header).encode()
    out[f"snes/{n}.h"] = snes_enc.c_header(m, b, {k: out[f"snes/{f}"] for k, f in files.items()}, header).encode()
    idx, colors = _snes_screen_index(m)
    out[f"png/{n}.screen.idx.png"] = indexed_png(idx, colors, [], prov, {"scene": n, "indexed": "cgram"},
                                                 m.composites[0])
    return out


def _screen_index(m, b) -> tuple[np.ndarray, list[int]]:
    """Palette-RAM indices of the legal screen (BG: attr*4+i, sprites: 16+pal*4+i) and its 32 colors."""
    tiles = np.stack(m.bg_tiles[0])
    idx = tiles[m.nametables[0]].transpose(0, 2, 1, 3).reshape(240, 256).astype(np.int32)
    attr = np.repeat(np.repeat(m.attributes[0], 16, axis=0), 16, axis=1)
    out = np.where(idx == 0, 0, attr * 4 + idx)
    for c in reversed(m.oam[0]):
        for v in range(c.h):
            for u in range(8):
                if c.pix[v, u] >= 0 and 0 <= c.top + v < 240 and c.x + u < 256:
                    out[c.top + v, c.x + u] = 16 + c.palette * 4 + int(c.pattern[v, u])
    colors = [rgb_of(nes_byte_hex(x)) for x in b.pal]
    return out, colors


def _outputs(an, assets, raw, encoded, prov, report, hardware: bool, console: str = "nes") -> dict[str, bytes]:
    out: dict[str, bytes] = {}
    for name, a in assets.items():
        if not a.exported:
            continue
        imgs = an.images[name]
        out[f"png/{name}.png"] = rgba_png(imgs[0], prov, {"asset": name, "frame": 0})
        if len(imgs) > 1:
            for k, img in enumerate(imgs):
                out[f"png/{name}_{k}.png"] = rgba_png(img, prov, {"asset": name, "frame": k})
    for m in an.scenes:
        if not m.checked or not m.composites:
            continue
        out[f"png/{m.name}.screen.png"] = rgba_png(m.composites[0], prov, {"scene": m.name, "state": 0})
        for s in range(1, m.states):
            out[f"png/{m.name}.screen_{s}.png"] = rgba_png(m.composites[s], prov, {"scene": m.name, "state": s})
    for sh in raw.sheets:
        items = []
        tags = []
        for name in sh["entries"]:
            imgs = an.images[name]
            a = assets[name]
            if len(imgs) > 1:
                tags.append({"name": name, "from": len(items), "to": len(items) + len(imgs) - 1, "direction": "forward"})
                items += [(f"{name}_{k}", img, a.frame_ms[k] or STILL_MS) for k, img in enumerate(imgs)]
            else:
                items.append((name, imgs[0], STILL_MS))
        if not items:
            continue
        sheet, placed = _shelf(items, sh.get("cols"), sh.get("pad") or 0)
        frames = {}
        hw = {}
        for fname, img, ms, x, y in placed:
            h, w = img.shape[:2]
            frames[fname] = {"frame": {"x": x, "y": y, "w": w, "h": h}, "rotated": False, "trimmed": False,
                             "spriteSourceSize": {"x": 0, "y": 0, "w": w, "h": h}, "sourceSize": {"w": w, "h": h},
                             "duration": ms}
            base, _, k = fname.rpartition("_")
            asset, frame = (base, int(k)) if base in assets and k.isdigit() and assets[base].animated else (fname, 0)
            cells = ((_cells_for_snes if console == "snes" else _cells_for)(asset, frame, an.scenes, encoded)
                     if hardware else [])
            if cells:
                hw[fname] = cells
        meta = {"app": "retrogaze code mode (pxl)", "image": f"{sh['name']}.png", "format": "RGBA8888",
                "size": {"w": sheet.shape[1], "h": sheet.shape[0]}, "scale": "1",
                "retrogaze": {"provenance": prov, "console": prov["console"], "tier": prov["tier_requested"],
                              "verdict": prov["verdict"], "hardware": hw}}
        if tags:
            meta["frameTags"] = tags
        out[f"sheets/{sh['name']}.png"] = rgba_png(sheet, prov, {"sheet": sh["name"]})
        out[f"sheets/{sh['name']}.json"] = _json({"frames": frames, "meta": meta})
    if hardware and console == "snes":
        for m in an.scenes:
            out.update(_snes_hardware(m, encoded[m.name], prov))
    elif hardware:
        header = (f"Retrogaze code mode, code-drawn (IPTC algorithmicMedia); pxl {prov['renderer']['commit'][:12]}; "
                  f"source {prov['source']['entry']}")
        for m in an.scenes:
            b = encoded[m.name]
            n = m.name
            files = {"chr": f"{n}.chr", "pal": f"{n}.pal", "nam": f"{n}.nam", "oam": f"{n}.oam"}
            out[f"nes/{n}.chr"] = b.chr[0]
            for k in range(1, len(b.chr)):
                out[f"nes/{n}_c{k}.chr"] = b.chr[k]
            out[f"nes/{n}.pal"] = b.pal
            out[f"nes/{n}.nam"] = b.nam[0]
            out[f"nes/{n}.oam"] = b.oam[0]
            for s in range(1, m.states):
                out[f"nes/{n}_s{s}.nam"] = b.nam[s]
                out[f"nes/{n}_s{s}.oam"] = b.oam[s]
            out[f"nes/{n}.rom.json"] = rom_json(b).encode()
            ref = ppu_ref.render(b.chr[0], b.pal, b.nam[0], b.oam[0], b.rom)
            out[f"nes/{n}.ref.png"] = rgba_png(ref, prov, {"scene": n, "reference_ppu": True})
            out[f"nes/{n}.s"] = ca65_include(m, b, files, header).encode()
            out[f"nes/{n}.h"] = c_header(m, b, header).encode()
            if any(m.oam):
                out[f"nes/{n}.ms.s"] = metasprite_source(m, b, header).encode()
            idx, colors = _screen_index(m, b)
            out[f"png/{n}.screen.idx.png"] = indexed_png(idx, colors, [], prov, {"scene": n, "indexed": "palette-ram"},
                                                         m.composites[0])
    out["report.json"] = _json(report)
    return dict(sorted(out.items()))


# ---------------------------------------------------------------------------
# Disk
# ---------------------------------------------------------------------------


def default_out_dir(entry_path: Path, console: str, tier: str) -> Path:
    return entry_path.resolve().parent / "out" / console / tier


def write_outputs(result: BuildResult, out_dir: Path, source_dir: Path) -> None:
    out_dir = out_dir.resolve()
    if out_dir.exists():
        owned = (out_dir / MANIFEST).exists() or not any(out_dir.iterdir())
        if not owned:
            raise CodeModeError("CM-INPUT", f"{out_dir} exists and is not a code-mode output folder; refusing to overwrite")
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True)
    for rel, data in result.outputs.items():
        p = out_dir / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(data)
    man = dict(result.manifest)
    man["build"] = {**man["build"], "source_dir": Path(os.path.relpath(source_dir.resolve(), out_dir)).as_posix()}
    (out_dir / MANIFEST).write_bytes(_json(man))
    result.out_dir = out_dir


def build_path(entry_path: Path, *, console="nes", tier="legal", author="unknown", out_dir: Path | None = None,
               write: bool = True) -> BuildResult:
    entry_path = Path(entry_path)
    try:
        files, entry = read_art_dir(entry_path)
    except (OSError, CodeModeError) as e:
        code = getattr(e, "code", "CM-INPUT")
        return BuildResult(2 if isinstance(e, OSError) else 3, "error",
                           {"schema": REPORT_SCHEMA, "verdict": "error", "errors": [{"code": code, "message": str(e)}]})
    result = build(files, entry, console=console, tier=tier, author=author)
    if write and result.exit_code in (0, 1):
        try:
            write_outputs(result, out_dir or default_out_dir(entry_path, console, tier), entry_path.resolve().parent)
        except CodeModeError as e:
            return BuildResult(2, "error", {"schema": REPORT_SCHEMA, "verdict": "error",
                                            "errors": [{"code": e.code, "message": str(e)}]})
    return result


# ---------------------------------------------------------------------------
# verify / audit
# ---------------------------------------------------------------------------


def _same_output(rel: str, a: bytes, b: bytes) -> bool:
    if a == b:
        return True
    if rel.endswith(".png"):
        import io
        from PIL import Image
        pa = json.loads(Image.open(io.BytesIO(a)).text.get("retrogaze:provenance", "null"))
        pb = json.loads(Image.open(io.BytesIO(b)).text.get("retrogaze:provenance", "null"))
        ia = np.array(Image.open(io.BytesIO(a)).convert("RGBA"))
        ib = np.array(Image.open(io.BytesIO(b)).convert("RGBA"))
        return pa == pb and pixels_sha256(ia) == pixels_sha256(ib)
    return False


def verify(out_dir: Path) -> tuple[int, list[str]]:
    out_dir = Path(out_dir).resolve()
    try:
        man = json.loads((out_dir / MANIFEST).read_text())
    except (OSError, json.JSONDecodeError) as e:
        return 1, [f"no readable {MANIFEST} in {out_dir}: {e}"]
    prov, b = man["provenance"], man["build"]
    msgs = []
    if prov["renderer"]["vendored_tree_sha256"] != vendored_tree_sha256():
        return 4, [f"built with pxl tree {prov['renderer']['vendored_tree_sha256'][:12]}, this checkout has "
                   f"{vendored_tree_sha256()[:12]}; check out retrogaze {prov['retrogaze'].get('git_commit', '?')}"]
    if prov["retrogaze"]["binding_sha256"] != binding_sha256(binding_for(b["console"], b["tier"])):
        return 4, [f"built with binding {prov['retrogaze']['binding_sha256'][:12]}; this checkout's binding differs; "
                   f"check out retrogaze {prov['retrogaze'].get('git_commit', '?')}"]
    src_dir = (out_dir / b["source_dir"]).resolve()
    files = {}
    for name in b["files"]:
        p = src_dir / name
        if not p.is_file():
            return 1, [f"source missing: {name}"]
        files[name] = p.read_text(encoding="utf-8")
        if "sha256:" + sha256_bytes(files[name].encode()) != prov["source"]["files"].get(name):
            msgs.append(f"source changed since build: {name}")
    for rel, digest in man["outputs"].items():
        p = out_dir / rel
        if not p.is_file():
            msgs.append(f"output missing: {rel}")
        elif sha256_bytes(p.read_bytes()) != digest:
            msgs.append(f"output modified since build: {rel}")
    for p in sorted(out_dir.rglob("*")):
        rel = p.relative_to(out_dir).as_posix()
        if p.is_file() and rel != MANIFEST and rel not in man["outputs"]:
            msgs.append(f"unexpected file: {rel}")
    if msgs:
        return 1, msgs
    again = build(files, b["entry"], console=b["console"], tier=b["tier"], author=b["author"])
    if set(again.outputs) != set(man["outputs"]):
        return 1, [f"rebuild produced a different file set: {sorted(set(again.outputs) ^ set(man['outputs']))}"]
    for rel, data in again.outputs.items():
        if not _same_output(rel, data, (out_dir / rel).read_bytes()):
            msgs.append(f"rebuild differs: {rel}")
    return (1, msgs) if msgs else (0, [f"verified {len(man['outputs'])} outputs against {len(files)} source file(s)"])


AUDIT_EXT = (".png", ".chr", ".pal", ".nam", ".oam", ".bin", ".4bpp", ".2bpp", ".map", ".cgram")


def audit(root: Path) -> tuple[int, list[str]]:
    """Every image/binary asset under ``root`` must carry intact code-mode provenance."""
    root = Path(root).resolve()
    listed: dict[Path, str] = {}
    for man_path in root.rglob(MANIFEST):
        try:
            man = json.loads(man_path.read_text())
            if man.get("provenance", {}).get("mode") != "code":
                continue
            for rel, digest in man.get("outputs", {}).items():
                listed[(man_path.parent / rel).resolve()] = digest
        except (OSError, json.JSONDecodeError):
            continue
    bad, ok = [], 0
    for p in sorted(root.rglob("*")):
        if not p.is_file() or not p.name.lower().endswith(AUDIT_EXT):
            continue
        rel = p.relative_to(root).as_posix()
        if p.suffix.lower() == ".png":
            prov = read_png_provenance(p)
            if not prov or prov.get("mode") != "code":
                bad.append(f"{rel}: no code-mode provenance (not cleared for paid release)")
                continue
            if prov.get("ai_image_model") is not None or prov.get("digital_source_type", "").rsplit("/", 1)[-1] != "algorithmicMedia":
                bad.append(f"{rel}: provenance does not mark code-drawn art")
                continue
            if prov.get("pixels_sha256") != pixels_sha256(png_rgba(p)):
                bad.append(f"{rel}: pixels changed after the build")
                continue
            ok += 1
        else:
            digest = listed.get(p.resolve())
            if digest is None:
                bad.append(f"{rel}: no code-mode provenance (not in any code-mode manifest)")
            elif sha256_bytes(p.read_bytes()) != digest:
                bad.append(f"{rel}: bytes changed after the build")
            else:
                ok += 1
    msgs = bad + [f"{ok} asset file(s) carry valid code-mode provenance"]
    return (1 if bad else 0), msgs


def scene_bytes_for_rom(entry_path: Path, scene: str | None, force: bool,
                        console: str = "nes") -> tuple[dict[str, bytes], str]:
    files, name, _ = scene_for_rom(entry_path, scene, force, console)
    return files, name


# Runtime limits: the bytes exist, the PPU drops sprites. ``rom --force`` builds such scenes on purpose.
RUNTIME_RULES = {"nes": ("NES-H8", "NES-H9"), "snes": ("SNES-H10", "SNES-H11")}


def scene_for_rom(entry_path: Path, scene: str | None, force: bool, console: str = "nes"):
    """Hardware files (and the model) for one scene, for the viewer ROM. ``force`` encodes even with
    runtime-limit violations (NES-H8/H9, SNES-H10/H11), so negative fixtures can show what the console does."""
    files, entry = read_art_dir(Path(entry_path))
    binding = binding_for(console, "legal")
    raw = run_loader(files, entry, binding)
    assets = {a["name"]: Asset.from_json(a) for a in raw.assets}
    an = (snes if console == "snes" else nes).analyze(assets, raw.scenes, raw.tilesets, raw.pins)
    models = [m for m in an.scenes if (scene is None or m.name == scene)]
    if not models:
        raise CodeModeError("CM-INPUT", f"no scene named {scene!r}" if scene else "the art defines no scene")
    m = models[0] if scene else next((x for x in models if x.declared), models[0])
    runtime_only = all(v.rule in RUNTIME_RULES[console] for v in m.violations if v.severity == "error")
    if not m.legal and not (force and m.checked and runtime_only):
        rules = sorted({v.rule for v in m.violations if v.severity == "error"})
        raise CodeModeError("CM-INPUT", f"scene '{m.name}' is not console-legal ({', '.join(rules) or 'not checked'})")
    if console == "snes":
        b = snes_enc.encode_scene(m)
        prov = block(binding_sha=binding_sha256(binding), version=CODEMODE_VERSION, sources=files, entry=entry,
                     author="unknown", console="snes", tier="legal", verdict="legal" if m.legal else "fail")
        hw = _snes_hardware(m, b, prov)
        out = {k[len("snes/"):]: v for k, v in hw.items()
               if k.startswith("snes/") and "/pal/" not in k and not k.endswith((".s", ".h"))
               and not k[len("snes/"):].startswith(f"{m.name}_")}
        return out, m.name, m
    b = encode_scene(m)
    ref = ppu_ref.render(b.chr[0], b.pal, b.nam[0], b.oam[0], b.rom)
    prov = block(binding_sha=binding_sha256(binding), version=CODEMODE_VERSION, sources=files, entry=entry,
                 author="unknown", console="nes", tier="legal", verdict="legal" if m.legal else "fail")
    out = {f"{m.name}.chr": b.chr[0], f"{m.name}.pal": b.pal, f"{m.name}.nam": b.nam[0], f"{m.name}.oam": b.oam[0],
           f"{m.name}.rom.json": rom_json(b).encode(),
           f"{m.name}.ref.png": rgba_png(ref, prov, {"scene": m.name, "reference_ppu": True})}
    return out, m.name, m


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()

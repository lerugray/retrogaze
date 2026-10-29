#!/usr/bin/env python3
"""Run one NES or SNES ROM headless in Mesen 2 (--testRunner) and dump what the PPU holds.

    run_mesen.py --mesen <binary> --rom X.nes|X.sfc --out-dir O [--frames 10] [--timeout 60] [--keep-home]

Writes O/screenshot.png and O/run_info.txt via run_mesen.lua, plus for a .nes ROM O/palette.bin (32 B),
O/oam.bin (256 B), O/nametable.bin (1024 B), O/chr.bin (8192 B), and for a .sfc ROM O/cgram.bin (512 B),
O/oam.bin (544 B), O/vram.bin (65536 B). Exits non-zero on any failure or timeout.
Mesen runs with a throwaway home (HOME / XDG_CONFIG_HOME in a temp dir, pre-seeded settings.json,
nothing saved), so no global state is read or written. Standard library only.
"""
import argparse
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
LUA = HERE / "run_mesen.lua"
DUMPS = {"palette.bin": 32, "oam.bin": 256, "nametable.bin": 1024, "chr.bin": 8192}
SNES_DUMPS = {"cgram.bin": 512, "oam.bin": 544, "vram.bin": 65536}
OUTPUTS = ["screenshot.png", "run_info.txt", "lua_error.txt", *DUMPS, *SNES_DUMPS]

# Every switch below was checked against the pinned Mesen 2 source (see TOOLS.md). A switch is
# "--<Config property path>=<value>" resolved by ConfigManager.ProcessSwitch; unknown names are
# silently ignored by --testRunner, so do not add one without checking the source.
SWITCHES = [
    "--debug.scriptWindow.allowIoOsAccess=true",   # loads Lua io/os (needed to write the dumps)
    "--nes.region=Ntsc",
    "--nes.ntscOverscan.left=0", "--nes.ntscOverscan.right=0",   # full 256x240, no crop
    "--nes.ntscOverscan.top=0", "--nes.ntscOverscan.bottom=0",
    "--nes.removeSpriteLimit=false", "--nes.adaptiveSpriteLimit=false",   # keep 8 sprites/line
    "--nes.disableSprites=false", "--nes.disableBackground=false",
    "--nes.forceBackgroundFirstColumn=false", "--nes.forceSpritesFirstColumn=false",
    "--nes.enableHdPacks=false", "--nes.ramPowerOnState=AllZeros",
    "--emulation.runAheadFrames=0",
    "--video.videoFilter=None", "--video.screenRotation=None", "--video.scanlineIntensity=0",
    "--video.brightness=0", "--video.contrast=0", "--video.hue=0", "--video.saturation=0",
]
# SNES: pinned the same way (UI/Config/SnesConfig.cs at the pinned commit). Overscan top 7 / bottom 8 is the
# default and crops Mesen's 239-line buffer to the 224 visible lines (screen row r = scanline r + 1).
SNES_SWITCHES = [
    "--snes.region=Ntsc", "--snes.ramPowerOnState=AllZeros", "--snes.enableRandomPowerOnState=false",
    "--snes.overscan.top=7", "--snes.overscan.bottom=8", "--snes.overscan.left=0", "--snes.overscan.right=0",
    "--snes.forceFixedResolution=false", "--snes.blendHighResolutionModes=false",
    "--snes.hideBgLayer1=false", "--snes.hideBgLayer2=false", "--snes.hideBgLayer3=false",
    "--snes.hideBgLayer4=false", "--snes.hideSprites=false",
    "--snes.ppuExtraScanlinesBeforeNmi=0", "--snes.ppuExtraScanlinesAfterNmi=0",
]


class MesenError(RuntimeError):
    pass


def make_env(home: Path, out_dir: Path, frames: int, console: str = "nes") -> dict:
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "LANG": "C.UTF-8",
        "HOME": str(home),
        "XDG_CONFIG_HOME": str(home / "config"),   # Mesen home = $XDG_CONFIG_HOME/Mesen2
        "XDG_DATA_HOME": str(home / "data"),
        "XDG_CACHE_HOME": str(home / "cache"),
        "TMPDIR": str(home / "tmp"),
        "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
        "DOTNET_EnableDiagnostics": "0",            # no diagnostics IPC socket
        "SDL_VIDEODRIVER": "dummy",                 # --testRunner never opens SDL; belt and braces
        "SDL_AUDIODRIVER": "dummy",
        "RG_OUT_DIR": str(out_dir),
        "RG_FRAMES": str(frames),
        "RG_CONSOLE": console,
    }
    for key in ("DOTNET_ROOT", "DOTNET_ROOT_X64"):  # framework-dependent build: find the runtime
        if key in os.environ:
            env[key] = os.environ[key]
    return env


def run(mesen, rom, out_dir, frames=10, timeout=60, keep_home=False) -> dict:
    """Run Mesen; return {"seconds", "info", "home"}. Raises MesenError on any failure."""
    mesen, rom, out_dir = Path(mesen).resolve(), Path(rom).resolve(), Path(out_dir).resolve()
    console = "snes" if rom.suffix.lower() in (".sfc", ".smc") else "nes"
    dumps = SNES_DUMPS if console == "snes" else DUMPS
    if not os.access(mesen, os.X_OK):
        raise MesenError(f"not an executable: {mesen}")
    if (mesen.parent / "settings.json").exists():
        raise MesenError(f"{mesen.parent}/settings.json would put Mesen in portable mode; remove it")
    if not rom.is_file():
        raise MesenError(f"missing ROM {rom}")
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in OUTPUTS:
        (out_dir / name).unlink(missing_ok=True)

    home = Path(tempfile.mkdtemp(prefix="rg-mesen-home-"))
    try:
        mesen_home = home / "config" / "Mesen2"
        for sub in (mesen_home, home / "data", home / "cache", home / "tmp"):
            sub.mkdir(parents=True)
        # Without settings.json Mesen opens its first-run wizard (a GUI) even with --testRunner.
        (mesen_home / "settings.json").write_text("{}\n", encoding="utf-8")
        cmd = [str(mesen), "--testRunner", f"--timeout={timeout}", "--doNotSaveSettings",
               *SWITCHES, *(SNES_SWITCHES if console == "snes" else []), str(LUA), str(rom)]
        start = time.monotonic()
        try:
            proc = subprocess.run(cmd, env=make_env(home, out_dir, frames, console), cwd=home,
                                  capture_output=True, text=True, timeout=timeout + 30)
        except subprocess.TimeoutExpired:
            raise MesenError(f"Mesen did not exit within {timeout + 30} s")
        seconds = time.monotonic() - start
        log = (proc.stdout + proc.stderr).strip()
        lua_error = out_dir / "lua_error.txt"
        if lua_error.exists():
            raise MesenError(f"Lua error: {lua_error.read_text().strip()}")
        if proc.returncode != 0:
            hint = " (255 = Mesen --timeout reached or ROM not loaded)" if proc.returncode == 255 else ""
            raise MesenError(f"Mesen exited with {proc.returncode}{hint}" + (f"\n{log[-2000:]}" if log else ""))
        for name, size in dumps.items():
            path = out_dir / name
            if not path.is_file() or path.stat().st_size != size:
                raise MesenError(f"{path}: missing or not {size} bytes")
        if (out_dir / "screenshot.png").read_bytes()[:8] != b"\x89PNG\r\n\x1a\n":
            raise MesenError("screenshot.png is missing or not a PNG")
        info = (out_dir / "run_info.txt").read_text().strip()
        return {"seconds": round(seconds, 2), "info": info, "home": str(home) if keep_home else None}
    finally:
        if not keep_home:
            shutil.rmtree(home, ignore_errors=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--mesen", required=True, type=Path)
    ap.add_argument("--rom", required=True, type=Path)
    ap.add_argument("--out-dir", required=True, type=Path)
    ap.add_argument("--frames", type=int, default=10)
    ap.add_argument("--timeout", type=int, default=60, help="seconds (Mesen --timeout; +30 s hard kill)")
    ap.add_argument("--keep-home", action="store_true", help="keep the throwaway Mesen home dir")
    args = ap.parse_args(argv)
    try:
        result = run(args.mesen, args.rom, args.out_dir, args.frames, args.timeout, args.keep_home)
    except MesenError as exc:
        print(f"run_mesen: FAIL: {exc}", file=sys.stderr)
        return 1
    extra = f", home kept at {result['home']}" if result["home"] else ""
    print(f"run_mesen: ok in {result['seconds']} s ({result['info']}) -> {args.out_dir}{extra}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

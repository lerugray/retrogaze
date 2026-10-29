# Proof harness: tools, versions, how Mesen is run

This is the harness for gates (c) and (d) of the proof of legality (CODE-MODE-SPEC §5) for NES (milestone M1,
M1.1) and SNES (milestone M2, see "SNES (M2)" below).
Everything below was run and checked on Ubuntu 24.04.5 (x86_64, 4 cores). The Mesen 2 behaviour described
here was read from the source at the pinned commit and then confirmed by experiment.

## Files

| File | Role |
|---|---|
| `tools/build_mesen2.sh <src-dir> <prefix>` | builds Mesen 2 from source at the pinned commit into `<prefix>/bin/Mesen` (idempotent) |
| `nes/viewer.s`, `nes/nrom.cfg` | ca65/ld65 viewer ROM, NROM-128: iNES header + 16 KiB PRG + 8 KiB CHR-ROM (= the scene `.chr`) |
| `nes/viewer_mmc1.s`, `nes/mmc1.cfg` | M1.1: viewer ROM for an MMC1 cartridge with CHR-RAM (Ray's cartridge): NES 2.0 header, mapper 1, 8 x 16 KiB PRG, no CHR-ROM, 8 KiB CHR-RAM, horizontal mirroring, PRG mode 3. The `.chr` is in PRG bank 0 and is copied into CHR-RAM |
| `build_nes_rom.py --in-dir D --name N --out X.nes` | validates the scene files, writes `scene.inc`, picks the cartridge from `rom.json` `chr` (`rom` → NROM, `ram` → MMC1), runs ca65 + ld65, prints the sha256 |
| `run_mesen.py --mesen BIN --rom X.nes --out-dir O [--frames 10] [--timeout 60]` | runs Mesen headless with `run_mesen.lua`, checks the dumps |
| `run_mesen.lua` | after N frames (plus a settle check) writes `screenshot.png`, `palette.bin`, `oam.bin`, `nametable.bin`, `chr.bin`, `run_info.txt` |
| `compare.py --in-dir D --name N --run-dir O` | gate (c), byte-exact, and gate (d), color bijection. Writes `compare.json`, plus `diff.png` on a gate (d) failure. Importable: `compare(in_dir, name, run_dir) -> dict` |
| `snes/viewer.s`, `snes/lorom.cfg` | M2: ca65 (65816) / ld65 SNES viewer ROM, LoROM, 4 x 32 KiB banks, internal header at `$00:FFC0` |
| `build_snes_rom.py --in-dir D --name N --out X.sfc` | M2: validates `N.vram.json` and the files it names, writes `scene.inc`, runs ca65 + ld65, writes the header checksum, prints the sha256 |
| `sfc_oracle.py` | M2-15: re-encodes a BG layer's tiles with SuperFamiconv from the art's own pixels and compares with the exported `.4bpp` |
| `tools/build_superfamiconv.sh <src-dir> <prefix>` | builds SuperFamiconv from source at the pinned commit into `<prefix>/bin/superfamiconv` (idempotent) |
| `fuzz_snes.py --mesen BIN --work-dir W [--seeds 0-24]` | M2: random SNES scenes (layers, palettes, OBJ sizes, flips, edge straddlers, crowded lines) through validator, bytes, LoROM and Mesen; legal ones must pass gates (b)-(d), runtime-limit ones must drop exactly the predicted pixels |
| `make_selftest.py --out-dir D` | hand-built scenes in the exporter contract, with their own reference renderer |
| `run_selftest.py --mesen BIN --work-dir W` | end-to-end self-test: build ×2 → Mesen → compare, plus the empirical checks |

Only `compare.py` and `run_selftest.py` need a third-party package (Pillow). Everything else uses the standard library.

## Versions

| Tool | Version | Notes |
|---|---|---|
| cc65 (ca65, ld65) | Ubuntu package `cc65 2.19-1` | binaries report `V2.18 - Ubuntu 2.19-1`. ROM sha256 goldens are only valid for this package |
| Mesen 2 | `SourMesen/Mesen2` commit **`b9fa69ddc6d0a331fb103fdb5eef6904305703c2`** (master, 2026-06-04; `UI.csproj` version 2.1.1) | upstream marks this repo as the archive of 2.1.1; development moved to `nesdev-org/MesenCE`. Built from source (the harness was developed where GitHub release downloads were not reachable; CI builds the same way and caches the result). The pin is the commit, not a binary hash: two builds of this commit gave different sha256 (`4689ac98…`, `140a43d0…`), because the .NET bundle is not bit-reproducible |
| .NET | SDK 8.0.132, runtime Microsoft.NETCore.App 8.0.32 (Ubuntu `dotnet-sdk-8.0 8.0.132-0ubuntu1~24.04.1`) | needed to build. The runtime is also needed to run, because the binary is framework-dependent |
| clang | Ubuntu clang 18.1.3 (`clang 1:18.0-59~exp2`) | upstream makefile default (`-O3 -flto=thin`) |
| SDL2 | `libsdl2-dev` / `libsdl2-2.0-0` 2.30.0+dfsg-1ubuntu3.1 | `MesenCore.so` links libSDL2 and libX11 dynamically. Neither is initialised in `--testRunner` mode |
| other build tools | `make 4.3`, `zip 3.0` (the Linux pre-build step zips the native libraries), `git` | |
| Python / Pillow | Python 3.13.17, Pillow 13.0.0 | the scripts need Python 3.8+ and use only stable Pillow APIs (`tobytes`, `frombytes`, `paste`) |
| SuperFamiconv | `Optiroc/SuperFamiconv` tag v0.9.2, commit **`fda06602e62ba04391eca488ae4f2697916907d5`** (MIT) | M2-15 oracle. Built with CMake 3.28 + g++ 13 (Ubuntu 24.04). Here the build is bit-reproducible: two clean builds gave the same binary sha256 `c34165c0d669f2688c0d6ab0d08cce7621344b80f29180b53d494a3ea93d8d74` |

Mesen 2 is **GPL-3.0**. It is used only as an external test tool: it is never linked, vendored or shipped, and
nothing under `proof/` contains Mesen code.

## Reproduce

```bash
sudo apt-get install -y cc65 clang libsdl2-dev zip make dotnet-sdk-8.0     # Ubuntu 24.04
proof/tools/build_mesen2.sh ~/tools/mesen2-src ~/tools/mesen2                # fetches the pinned commit if missing
python3 -m venv ~/venv && ~/venv/bin/pip install pillow
~/venv/bin/python proof/run_selftest.py --mesen ~/tools/mesen2/bin/Mesen --work-dir /tmp/rg-proof

# one exported scene, step by step
python3 proof/build_nes_rom.py --in-dir OUT/nes --name hero --out /tmp/hero.nes
python3 proof/run_mesen.py --mesen ~/tools/mesen2/bin/Mesen --rom /tmp/hero.nes --out-dir /tmp/hero-run
~/venv/bin/python proof/compare.py --in-dir OUT/nes --name hero --run-dir /tmp/hero-run
```

## How Mesen is run (verified against the source of the pinned commit)

**Command** (from `run_mesen.py`):

```
Mesen --testRunner --timeout=<T> --doNotSaveSettings <switches> proof/run_mesen.lua <rom.nes>
```

- `--testRunner` (`UI/Program.cs`, `UI/Utilities/TestRunner.cs`) runs headless. `InitializeEmu` gets no window
  handle, so no renderer, no SDL audio and no input manager are created. It loads the ROM and the `.lua` file,
  which are told apart by extension. It runs at maximum speed, and the process exit code is the value passed
  to `emu.stop(code)`.
- `--timeout=<T>`: whole seconds (default 100). When it runs out, or when the ROM fails to load, the exit code
  is 255 (-1). `run_mesen.py` also kills the process after T + 30 s.
- Other switches are `--<config.path>=<value>`, resolved case-insensitively by `ConfigManager.ProcessSwitch`.
  **An unknown switch is silently ignored in `--testRunner` mode** (checked: `--nes.noSuchSetting=1` changes
  nothing). So every switch was checked against `UI/Config/*.cs`, and the ones with an observable effect were
  also flipped to prove they apply.

| Switch | Why | Checked |
|---|---|---|
| `--debug.scriptWindow.allowIoOsAccess=true` | loads Lua `io`/`os` (`Core/Debugger/ScriptingContext.cpp`); without it the script cannot write the dumps | without it: script error, exit 255 at timeout |
| `--nes.ntscOverscan.{left,right,top,bottom}=0` | full 256×240 frame, no crop | the default is already 0. `top=8` gives a 256×232 screenshot, which compare rejects |
| `--nes.removeSpriteLimit=false`, `--nes.adaptiveSpriteLimit=false` | keep the hardware 8-sprites-per-line rule | with `removeSpriteLimit=true`, `selftest_9line` fails on exactly 40 px and the no-drop control passes |
| `--nes.region=Ntsc`, `--nes.ramPowerOnState=AllZeros`, `--nes.enableHdPacks=false`, `--nes.disableSprites=false`, `--nes.disableBackground=false`, `--nes.forceBackgroundFirstColumn=false`, `--nes.forceSpritesFirstColumn=false`, `--emulation.runAheadFrames=0`, `--video.videoFilter=None`, `--video.screenRotation=None`, `--video.scanlineIntensity=0`, `--video.{brightness,contrast,hue,saturation}=0` | pin every setting that could change the picture to its default | names and enum values checked in source |

**Environment** (`run_mesen.py`):
- A fresh temp dir is used as `HOME`, with `XDG_CONFIG_HOME=$HOME/config`, `XDG_DATA_HOME`, `XDG_CACHE_HOME`
  and `TMPDIR` inside it. Mesen's home is `$XDG_CONFIG_HOME/Mesen2` (.NET `SpecialFolder.ApplicationData`), unless a
  `settings.json` sits next to the binary (portable mode, which `run_mesen.py` refuses). The temp dir is deleted
  after the run.
- **A `settings.json` must exist** in that home. Otherwise `Program.Main` opens the first-run wizard (Avalonia)
  *before* it looks at `--testRunner`, and aborts headless with exit 134. `run_mesen.py` writes `{}`. Settings are
  never saved back (`TestRunner` sets `DisableSaveSettings`).
- At every start Mesen unpacks its embedded `Dependencies.zip` (MesenCore.so, Skia, HarfBuzz, game DB) into that home.
- `DOTNET_EnableDiagnostics=0` stops .NET from creating IPC sockets. `DOTNET_ROOT` is passed through if set.
  `SDL_VIDEODRIVER=dummy` / `SDL_AUDIODRIVER=dummy` are set but not needed: runs under `env -i` with no `DISPLAY`
  work, because `--testRunner` never initialises SDL.
- Checked: during a run nothing is written outside the temp home and the output dir.

**Lua API used** (names from `Core/Debugger/LuaApi.cpp` and `UI/Debugger/Documentation/LuaDocumentation.json`):
- `emu.addEventCallback(fn, emu.eventType.endFrame)`: the NES fires it at the start of vblank (`NesPpu.cpp`).
- `emu.takeScreenshot()`: PNG bytes of the video filter's output buffer. That buffer has no scaling with
  `videoFilter=None`, no rotation, and overscan applied. Because frames are decoded on a separate thread,
  the script waits until two consecutive screenshots are byte-identical.
- `emu.read(addr, emu.memType.X)` with these memory types:
  - `nesPaletteRam`: the raw 32-byte array.
  - `nesSpriteRam`: 256 bytes.
  - `nesPpuMemory`: through `NesConsole::DebugReadVram`, so no side effects. `$2000-$23FF` is nametable 0 via
    the cart's mirroring, and `$0000-$1FFF` is CHR-ROM.
- `emu.getScreenSize()`, `emu.stop(code)`, `emu.log`. `emu.memType` names are the `MemoryType` enum with a
  lower-case first letter. The `xxxMemory` types also get an `xxxDebug` alias.

**What the hardware model in Mesen means for gate (c)**:
- *Palette RAM*: writes are masked to 6 bits, and a write to `$3F00/04/08/0C` or `$3F10/14/18/1C` updates both
  slots (`BaseNesPpu::WritePaletteRam`). The 32-byte dump therefore already has the shape of the `.pal` contract and
  is compared raw. A `.pal` with a byte ≥ `$40` or unequal mirror slots fails, with a hint.
- *OAM*: `$2004` writes, and therefore OAM DMA, clear bits 2-4 of byte 2 (`value &= 0xE3`), because those bits do
  not exist on the 2C02. **Unused OAM entries must keep those bits clear**, e.g. `FF 00 00 00`. Checked: an exporter
  that parks unused sprites as `FF FF FF FF` fails gate (c) on 57 bytes (byte 2 reads back `$E3`), and compare prints
  the hint.

**Gate (d) and the color bijection.** Retrogaze's `_NES_PALETTE_HEX` (columns `$xE`/`$xF` black) and Mesen's
built-in 2C02 table (`Core/NES/NesDefaultVideoFilter.cpp`) split the 64 color bytes into **the same 54 classes**.
Black is {`$0D,$0E,$0F,$1D,$1E,$1F,$2E,$2F,$3E,$3F`}, white is {`$20,$30`}, and every other byte is unique in both
tables. So for any palette bytes, the reference and the screenshot are related by a well-defined color bijection,
and the check is sound.
- How a pixel is judged: each expected color goes to its most frequent screen color, and each screen color goes back
  to its most frequent expected color. A pixel fails when either map disagrees. When the bijection holds, no pixel
  fails. When it does not hold, the failing pixels are exactly the pixels that differ (the self-test shows this).
- Limitation: a uniform recoloring of one color everywhere is invisible to gate (d) by design. Gate (c)'s palette
  compare catches it.

**Overscan / crop.** No crop is applied. NTSC overscan is pinned to 0 on all sides, so `takeScreenshot()` is the full
256×240 PPU frame. `compare.py` fails any screenshot that is not exactly 256×240 instead of guessing a crop.

## Viewer ROM (`nes/viewer.s`)

- Reset: `sei/cld`, APU frame IRQ and DMC IRQ off, NMI and rendering off, wait for 2 vblanks, clear `$0000-$07FF`
  (the OAM page `$0200` is filled with `$FF`).
- Then: `.pal` → `$3F00` (32 B), `.nam` → `$2000` (1024 B), `.oam` → `$0200` (256 B), and
  PPUCTRL = `$80 | 8x16<<5 | bg_table<<4 | spr_table<<3`.
- NMI: `OAMADDR=0`, `$4014=$02`, PPUCTRL again (nametable 0), `bit $2002`, `$2005=0,0`, PPUMASK = `$1E`
  (`left8`) or `$18`.
- iNES header: mapper 0, 1×16 KiB PRG, 1×8 KiB CHR, horizontal mirroring (only nametable 0 is shown).
- The data comes in with `.incbin` straight from the export directory (`ca65 --bin-include-dir`). The only
  generated file is `scene.inc` (file names + the two register values).
- `rom.json` must have the keys `sprite_size`, `bg_table`, `spr_table`, `left8`, plus (M1.1) an optional `chr`:
  `"rom"` (the default, and what an M1 export without the key means) or `"ram"`. Scene names must match
  `[A-Za-z0-9_][A-Za-z0-9_.-]*`.

## MMC1 + CHR-RAM viewer (`nes/viewer_mmc1.s`, M1.1)

Ray's NES project runs on mapper 1 (MMC1) with no CHR-ROM, 8 KiB CHR-RAM, horizontal mirroring and MMC1 PRG
mode 3 (bank 7 fixed at `$C000`), assembled by a JavaScript 6502 assembler from raw binaries. A scene that sets
`chr: "chr-ram"` exports exactly those raw binaries (`.chr` 8192 B, `.pal` 32 B, `.nam`, `.oam`) and gets
`"chr": "ram"` in `rom.json`, so `build_nes_rom.py` builds this viewer instead of the NROM one:

- Header: NES 2.0, mapper 1 submapper 0, PRG 8 × 16 KiB, CHR-ROM 0, CHR-RAM `64 << 7` = 8192 B, no PRG-RAM,
  horizontal mirroring, NTSC. ROM size 16 + 131072 = 131,088 bytes.
- Every bank ends with the same 10-byte reset stub at `$xFF0` (`sei; ldx #$FF; txs; stx $8000; jmp reset`) and
  vectors pointing at `$FFF0`: MMC1 may power on with any bank at `$C000`, the write of `$FF` resets the mapper
  into PRG mode 3, and bank 7's identical stub continues. (Mesen powers on in mode 3, so it only exercises bank
  7's stub; the others are for real hardware.)
- Reset: as `viewer.s`, plus the MMC1 setup by serial writes: control `$0F` (8 KiB CHR mode, PRG mode 3, horizontal
  mirroring), CHR banks 0/0, PRG bank 0 at `$8000`. With rendering off it copies the `.chr` (in PRG bank 0) to PPU
  `$0000-$1FFF` (CHR-RAM), then `.pal`, `.nam`, `.oam` exactly as the NROM viewer, and the same NMI.
- Gate (c) is unchanged: Mesen's `nesPpuMemory` `$0000-$1FFF` read is the CHR-RAM the viewer filled, compared
  byte for byte with the `.chr`. A one-byte change to the `.chr` fails it (checked).
- `run_codemode_proof.py` also checks the header of every proof ROM (`cart=mmc1:ok`) and, for the flip scenes,
  that the `.oam` uses all four flip-bit combinations.
- Deterministic: two builds give identical bytes, checked by `run_selftest.py` for every scene.

## Self-test (`make_selftest.py`, `run_selftest.py`)

| Scene | Content | Expected |
|---|---|---|
| `selftest` | 8×8 sprites, BG table 0, sprite table 1, `left8` true. 8 BG tiles across all 4 BG palettes. Every attribute byte has 4 different quadrants, and the bytes differ from each other. Sprites: a 16×16 metasprite of 4 sprites in 2 palettes (#3 is #0's tile H-flipped); a Y marker (#4, Y byte `$4F`); a V+H-flipped sprite at X=2; a V-flipped behind-BG sprite half over blank BG. Unused CHR tiles hold noise, so every CHR byte is checked. 25 colors | pass (c) and (d) |
| `selftest_9line` | 8×16 sprites (one with an odd tile byte, so it reads from table 1), BG table 1, `left8` false (sprite #0 at X=4 is half clipped). Sprites #0-#7 cover lines 120-135; #8 covers 128-143. The reference drops #8 on lines 128-135 only | pass (c) and (d) |
| `selftest_9line_nodrop` | negative control: the same bytes, but the reference has no sprite limit | (c) passes; (d) must fail on exactly the pixels where the two references differ |

Results here (cc65 2.19-1, Mesen `b9fa69d`). ROM sha256 goldens:

| Scene | ROM sha256 | (c) | (d) |
|---|---|---|---|
| `selftest` | `1db264f28d769813774db355975beeb32d71ff22ce383abd60b0d25905e6b6ff` | pass | pass (25 colors ↔ 25) |
| `selftest_9line` | `870679170e5a9108caf8c284cfbb582b735dafdabf78949af851fb111b7a4496` | pass | pass (23 colors ↔ 23) |
| `selftest_9line_nodrop` | same ROM as `selftest_9line` | pass | fails as required: 40 px = exactly the 40 predicted px of OAM #8, lines 128-135, x 228-235 |

Empirical answers:
- **Y convention:** OAM Y byte `$4F` puts the sprite's first row on screen line `$50`. The one-row marker shows on
  line `$50` only, not `$4F` or `$51`. Sprites are never on line 0: the smallest possible top is Y byte 0 + 1.
- **9 sprites on a line:** Mesen drops the highest OAM index (#8) on exactly the lines where it is the 9th sprite
  (128-135), and draws it on lines 136-143, where it is alone.

## Runtime (this machine, 4 cores)

| Step | Time |
|---|---|
| `build_mesen2.sh` from nothing: shallow fetch + core `make -j4` (clang, ThinLTO, about 3 min 50 s) + UI 2× `dotnet publish` (about 1 min) | 4 min 41 s |
| NuGet restore, cold cache | about 15 s |
| `build_mesen2.sh` re-run when already installed | instant (stamp check) |
| `build_nes_rom.py` per ROM | 0.01 s |
| `run_mesen.py` per ROM (startup + unpacking the dependencies + 11 frames + dumps) | 1.0-1.6 s |
| `compare.py` per scene | about 0.15 s |
| `run_selftest.py`, all 3 scenes | 4-5 s |

## CI recipe (GitHub `ubuntu-24.04`)

The Mesen build is cached under a key made from the pinned commit and the build script's hash. A cache hit skips
the 5-minute build. The runtime still needs .NET 8, `libsdl2-2.0-0` and `libx11-6`.

```yaml
codemode-proof:
  runs-on: ubuntu-24.04
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.12" }
    - uses: actions/setup-dotnet@v4            # sets DOTNET_ROOT; run_mesen.py passes it through
      with: { dotnet-version: "8.0.x" }
    - run: sudo apt-get update && sudo apt-get install -y cc65 libsdl2-2.0-0 libx11-6
    - id: mesen-cache
      uses: actions/cache@v4
      with:
        path: ~/mesen2
        key: mesen2-${{ runner.os }}-b9fa69ddc6d0a331fb103fdb5eef6904305703c2-${{ hashFiles('proof/tools/build_mesen2.sh') }}
    - if: steps.mesen-cache.outputs.cache-hit != 'true'
      run: |
        sudo apt-get install -y clang libsdl2-dev zip make
        proof/tools/build_mesen2.sh "$RUNNER_TEMP/mesen2-src" ~/mesen2
    - run: pip install pillow
    - run: python proof/run_selftest.py --mesen ~/mesen2/bin/Mesen --work-dir "$RUNNER_TEMP/proof"
    # then, for every fixture scene: build_nes_rom.py -> run_mesen.py -> compare.py
    - if: always()
      uses: actions/upload-artifact@v4
      with: { name: proof-runs, path: "${{ runner.temp }}/proof/runs" }
```

`cc65` on `ubuntu-24.04` is the same `2.19-1` package the goldens were recorded with, so the ROM sha256 goldens hold.

M1.1 added three proof scenes, recorded here with the same toolchain (and M1's four goldens unchanged):

| Scene | Art | What it proves | ROM sha256 |
|---|---|---|---|
| `nes_mmc1_chr_ram` | `examples/codemode/nes_mmc1.px.js` `room` | MMC1 + 8 KiB CHR-RAM, 8x16 sprites, 4 BG palettes | `b29e1b77d48d95088520ea77784068ff2d52b4a0b23c46ab5a6044187997dad7` |
| `nes_flips_8x8` | `examples/codemode/nes_flips.px.js` `flips8` | one sprite placed as drawn and flipped X, Y, XY: all four OAM flip combinations, 8x8 | `5c1ca9b5bdddc0abd832170cb1303b1952b85563adf502b9b09281e273955002` |
| `nes_flips_8x16` | `examples/codemode/nes_flips.px.js` `flips16` | the same in 8x16 mode, where V flips the whole 16-row sprite (the tile pair swaps) | `7a76204ea7d365ac74c9b3fa28b36c7d311c44c21298804db3535fcf07195d67` |
The recipe is implemented in `.github/workflows/codemode-proof.yml`, which also runs `run_codemode_proof.py` (real
code-drawn scenes, `goldens.json`) and the MCP end-to-end check. Every step was run locally before it went into CI.

## SNES (M2)

### Viewer ROM (`snes/viewer.s`, `snes/lorom.cfg`, `build_snes_rom.py`)

- LoROM, 128 KiB: bank `$00` holds the code, `.cgram`, `.oam` and the tilemaps; banks `$01`/`$02` the BG1/BG2
  CHR (up to 32 KiB each); bank `$03` the BG3 CHR and the OBJ name tables. Internal header at `$00:FFC0`: title
  `RETROGAZE CODE MODE`, map mode `$20`, ROM size `$07` (128 KiB), no SRAM; `build_snes_rom.py` writes the
  checksum (16-bit sum of every byte, computed with complement `$FFFF` / checksum `$0000` in place) and its
  complement. Vectors: RESET = `reset`, every other vector an `rti`.
- Reset: native mode, 8-bit A, 16-bit X/Y, forced blank (`INIDISP = $8F`), NMI/IRQ/HDMA off; mosaic, windows,
  color math, sub screen, BG4 and interlace registers zeroed. Then **all 64 KiB of VRAM is cleared** (a fixed-source
  DMA of a zero word), every blob in `vram.json` is DMAed to its word address (`VMAIN = $80`, mode 1 into
  `$2118/$2119`), `.cgram` (512 B) through `$2122` from CGRAM address 0, `.oam` (544 B, high table included)
  through `$2104` from OAM address 0 (priority rotation off). `BGMODE`, `BGnSC`, `BG12NBA`, `BG34NBA`, `OBSEL`,
  the six scroll registers (written twice) and `TM` come from `vram.json`; then `INIDISP = $0F`.
- `vram.json` holds the allocator's map (`regions`: byte and word address and size of every blob), the PPU
  register values and the exported file names. The only generated source is `scene.inc`.
- BG vertical scroll is `$3FF` (-1): the first visible line is scanline 1 and a BG shows line scanline + VOFS
  (Mesen `SnesPpu::GetTilemapData`: `realY = _scanline`). With VOFS = -1 BG row 0 is screen row 0. An OBJ with Y
  byte `y` is evaluated on scanline `y` and drawn on the next one, i.e. screen row `y` (Y = top row).
- Unused OBJs are parked at Y = 224 (below the 224-line screen; a small OBJ never wraps back) and X = -128
  (fully left of the screen), never at X = -256.

### Mesen run

`run_mesen.py` picks the console from the ROM extension (`.sfc`). It adds these switches, checked against
`UI/Config/SnesConfig.cs` at the pinned commit: `--snes.region=Ntsc`, `--snes.ramPowerOnState=AllZeros`,
`--snes.enableRandomPowerOnState=false`, `--snes.overscan.{top=7,bottom=8,left=0,right=0}` (the default: it crops
Mesen's 239-line buffer to the 224 visible lines, screen row r = scanline r + 1), `--snes.forceFixedResolution=false`,
`--snes.blendHighResolutionModes=false`, `--snes.hideBgLayer1..4=false`, `--snes.hideSprites=false`,
`--snes.ppuExtraScanlines{Before,After}Nmi=0`. `run_mesen.lua` (`RG_CONSOLE=snes`) dumps `cgram.bin` (512 B,
`snesCgRam`), `oam.bin` (544 B, `snesSpriteRam`) and `vram.bin` (65536 B, `snesVideoRam`). `takeScreenshot()` is
256x224 (`emu.getScreenSize()` reports the uncropped 256x239).

### Gates for SNES (`compare.py`)

- (c) `cgram.bin == .cgram`, `oam.bin == .oam`, and **all of VRAM**: `vram.bin` equals the image `vram.json`
  describes (each blob at its address, zeros elsewhere, because the viewer clears VRAM first); a mismatch is
  reported per region. One flipped byte in `.cgram`, `.oam`, `.bg1.4bpp`, `.bg3.map` or `.obj.4bpp` fails it
  (checked on `snes_layers`).
- (d) the same color bijection over 256x224. Mesen expands 5-bit channels by bit replication, Retrogaze by
  `e(q) = (q * 255) // 31`; both are injective, so the bijection is sound. One changed reference pixel fails it.

### The sprite-evaluation rules the proof pins (M2-14)

Read in Mesen's `SnesPpu::EvaluateNextLineSprites` / `FetchSpriteData` / `FetchSpriteAttributes` and then
confirmed in the emulator by negative controls: `run_codemode_proof.py` renders the scene with a wrong variant of
the reference PPU and requires Mesen's screenshot to disagree with it on exactly the pixels where the variant
differs from the model.

| Rule | Model | Control (wrong variant) | Result |
|---|---|---|---|
| Range: 32 OBJs per line | OAM scanned from #0, the first 32 in range kept | `no_range_limit` on `snes_33_on_a_line` | Mesen differs from it on exactly the 56 visible px of OAM #32, lines 100-107: OAM #32 is dropped |
| Time: 34 slivers per line | tiles of the kept OBJs fetched from the last kept one back to OAM #0, left to right, 34 fetched | `no_time_limit` on `snes_35_slivers` | 122 px = the right 8-px column of OAM #0 (the last painted, frontmost OBJ) is dropped |
| Partly off-screen OBJs | only tiles that reach the screen are fetched: an OBJ at X = -12 (16 wide) costs 1 sliver, at X = 250 costs 1 | `fetch_hidden` (the left tile counts too) on `snes_35_slivers` and `snes_34_slivers` | 122 px and 128 px: with 34 counted slivers nothing is dropped; the hidden tile is not fetched |

### SuperFamiconv oracle (M2-15)

`sfc_oracle.py` takes the BG1 art as pxl rendered it (`png/<asset>.png`), and for every tile number the first
tilemap entry that uses it (block, flips, palette). It writes one image per palette and that 16-color CGRAM slice
(color 0 replaced by a color the tiles do not use), runs `superfamiconv tiles -B 4 -D -F`, and requires the result
to equal the exported `.bg1.4bpp` tile for tile. The input never comes from code mode's tile bytes, so an encoder
bug cannot cancel out. `snes_proof`: 72 of 72 tiles equal, palettes 0-2.

### Results here (cc65 2.19-1, Mesen `b9fa69d`, SuperFamiconv `fda0660`)

| Scene | Art | ROM sha256 | (c) | (d) |
|---|---|---|---|---|
| `snes_proof` | `examples/codemode/snes/snes_proof.px.js` `proof`: 32x32 hero = one 32x32 OBJ, slimes in a 2nd OBJ palette, BG1 tile set in 3 BG palettes | `8bcd3312acc736f83bb371ef0c373bfcc678081c23a2dd053231a6e6073b90b4` | pass | pass, 46 colors |
| `snes_proof_tileset` | the same file, `land` (BG1 only) | `8c52807db636dee15a855a8b35bb71827f600b8648d14602270b5939638ed68b` | pass | pass, 30 colors |
| `snes_layers` | `examples/codemode/snes/snes_layers.px.js`: BG1 + BG2 + 2bpp BG3 HUD + flipped OBJs | `74f77fefa5add2514d8594663d18d6ec98d93762cdc485a9c121795ab12b0687` | pass | pass, 24 colors |
| `snes_34_slivers` | `snes_H11_pass`: 34 slivers incl. both edge straddlers | `345d7bc5f3fcef349ae10bb51e73ee3db8141eadc51509daaa15205439a898b3` | pass | pass |
| `snes_33_on_a_line` | `snes_H10_fail` (`rom --force`) | `005efa05c1c9c6165b2f7417f790a459a78330d9e623bacb44e8d5f7c6b4ce06` | pass | pass: reference = art except OAM #32 on lines 100-107 |
| `snes_35_slivers` | `snes_H11_fail` (`rom --force`) | `63d567139a71a21ac1b4763fe062ef743f39c03b6042125c9ebd1988e20c7f7c` | pass | pass: reference = art except OAM #0's right sliver, lines 100-115 |

Each SNES ROM is built twice (identical bytes) and its header is checked (map mode `$20`, 128 KiB, valid checksum).
One SNES scene takes about 1.2 s in Mesen here.

### Fuzzing (`fuzz_snes.py`)

Seeds 0-79 here: 70 scenes ran in Mesen (60 legal, 10 with SNES-H10/H11 overflows built with `--force`), 0
disagreements; 10 seeds were genuinely illegal (VRAM over budget, three forced OBJ sizes) and were skipped. An
earlier run found one decomposer weakness (a 64x64 OBJ chosen near the bottom edge, which would wrap: SNES-H4,
while a smaller OBSEL pair is legal); SNES-H4 is now a hard limit in the pair search
(`test_codemode_rules_snes.py::test_pair_choice_avoids_unplaceable_objs`). CI runs seeds 0-24 (about 40 s).

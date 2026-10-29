---
name: retrogaze-code-mode
description: Draw console-legal NES and SNES pixel art as code with Retrogaze code mode (pxl .px.js files checked against real NES and SNES hardware limits, exported as CHR/palette/nametable/OAM bytes on NES and 4bpp tiles/tilemaps/CGRAM/OAM/VRAM layout on SNES, with provenance proving no AI image model was used). Use when asked for NES or SNES sprites, tiles, backgrounds or scenes that must run on the console or be cleared for paid release as code-drawn art.
---

# Retrogaze code mode (NES and SNES)

You write a small `.px.js` file in the pxl DSL. Retrogaze renders it with no image model, checks it against
the NES hardware (2C02 palette, 16x16 attribute areas, 3 colors per sprite, 8 sprites per scanline, 64 sprites,
256-tile pattern tables), and exports the exact bytes a NES loads. Every output carries provenance that marks it
as code-drawn (IPTC `algorithmicMedia`) and can be re-verified from the source.

The DSL itself is documented in `third_party/pxl/SKILL.md` and `third_party/pxl/reference.md` (vendored pxl).
Read those for shapes, grids, mirroring, outlines, layers, tilemaps and animation.

## Workflow

1. `python -m retrogaze.codemode bind --console nes` prints the rules and helpers below.
2. Write `art.px.js`. Bind colors with `nes(byte)`, declare the frame with `rg.scene(...)`.
3. `python -m retrogaze.codemode build art.px.js --console nes --tier legal --author llm`
   (`--author llm` when you wrote the code; the studio rule counts LLM-written code as code-drawn, and the
   provenance records who wrote it).
4. Read the report. Every violation names the rule, the limit, and `blame`: the `file:line:col` that painted the
   offending pixels (grid strings resolve to the exact row). Fix that line; never ask for pixels to be fixed for you,
   code mode never changes pixels.
5. Repeat until `verdict: legal`. Outputs land in `out/nes/legal/`: PNGs, sheet + JSON, and `nes/<scene>.chr .pal
   .nam .oam` plus ca65 `.s`, cc65 `.h` and neslib-style metasprites (`.ms.s`).
6. Optional: `python -m retrogaze.codemode rom art.px.js` builds a viewer ROM (needs cc65) so you can see it boot.
7. `python -m retrogaze.codemode verify out/nes/legal` proves the outputs still come from the source.

Over MCP the same loop is `retro_code_bind`, `retro_code_build`, `retro_code_verify`.

## Never

- Never use an AI-generated image (or any image) as input or reference for art meant for a paid release.
- Never use `lighting`, `lamp`, `bump`, `normals`, `glow` without `ramp`, `Math.random` or `Date`: they are
  disabled because they leave the palette or break reproducibility.

## NES craft habits

- Plan backgrounds on the 16x16 attribute grid: each 16x16 area gets 3 colors + the shared backdrop. Put color
  changes on area boundaries.
- Give every sprite palette a 3-color ramp (dark, mid, light). Black outlines count as one of the 3.
- Draw half of a symmetric sprite and use `mx`: the mirrored half reuses the same tiles through the H-flip bit,
  so it costs no pattern-table space. NES background tiles cannot flip; sprites can.
- Keep metasprites at most 8 hardware sprites (64 px) wide on any line, minus whatever else shares the line.
- Need more than 3 colors in one 8x8 spot of a sprite? Split it into layers named `obj:0`, `obj:1`: each becomes
  its own hardware sprite (they overlap; each costs scanline budget).
- Reuse identical 8x8 tiles in backgrounds; the BG pattern table holds 256.
- On a CHR-RAM cartridge (for example MMC1 with 8 KiB CHR-RAM), set `chr: "chr-ram"` in `rg.scene`: the budget is
  the same, the exported `.chr` is what the game copies into CHR-RAM at boot, and `rom` builds an MMC1 viewer.
- Flip placements (`{ flip: "x" | "y" | "xy" }`) reuse a sprite's tiles through the OAM flip bits; in 8x16 mode a
  V flip turns the whole 16-row sprite over.

## Rules (generated from the rule registry; do not edit by hand)

<!-- BEGIN GENERATED: rules nes -->
### NES binding

- Colors: `nes(byte)` returns the hex for a 2C02 byte (`nes(0x0D)` is an error; black is `nes(0x0F)`).
  Bind keys with `pal({ k: nes(0x0F), r: nes(0x16) })`. Hex literals must be NES colors.
- Default index keys `0`-`R` are the 54 NES colors in table order; `use("pico8")`-style palettes are disabled.
- Disabled (they leave the palette): `lighting`, `lamp`, `bump`, `normals`, `glow` without `ramp`, partial-alpha colors, `Math.random`, `Date`.
- `rg.scene(name, { bg, obj: [[asset, x, y, { flip }]...], objSize: "8x8"|"8x16", backdrop, palettes, chr, left8 })` declares one hardware frame. pxl `scene()` assets are BG; `sprite()`/`anim()` are OBJ.
- `rg.tileset(name)` marks a BG tile set (each 16x16 metatile is one attribute area).
- Sprite layers named `obj:<n>` become overlapping hardware sprites (extra colors per pixel area).

| Rule | Tier | Scope | Limit | Rule |
|---|---|---|---|---|
| NES-L1 | like | image | 54 colors | Every opaque pixel is one of the 54 NES colors (exact RGB). |
| NES-L2 | like | image | 8 px | Grid: BG images are multiples of 8 (never padded); OBJ images are padded with transparent pixels on the right and bottom to multiples of 8 (reported, no drawn pixel moves). |
| NES-L3 | like | image | 4 | At most 4 opaque colors per 8x8 tile. |
| NES-L4 | like | image | — | Alpha is binary: every pixel is fully opaque or fully transparent. |
| NES-H1 | legal | image | — | Every color encodes to a 2C02 byte; $0D is never emitted or accepted. |
| NES-H2 | legal | image | 3 + backdrop | BG: each 16x16 attribute area uses at most 3 colors besides the scene backdrop (transparent BG pixels are backdrop). |
| NES-H3 | legal | image | 3 | OBJ: each hardware sprite cell uses at most 3 opaque colors (+ transparent). |
| NES-H4 | legal | image | — | OBJ: cells are 8x8, or 8x16 in 8x16 mode; the decomposition covers the asset with whole cells (normalization, never fails). |
| NES-H5 | legal | scene | 1 | One backdrop color per scene ($3F00); if not declared, the solver picks one that makes NES-H6 feasible. |
| NES-H6 | legal | scene | 4 x 3 | BG area color sets pack into at most 4 palettes of 3 colors (+ shared backdrop). |
| NES-H7 | legal | scene | 4 x 3 | OBJ cell color sets pack into at most 4 sprite palettes of 3 colors. |
| NES-H8 | legal | scene | 64 | At most 64 hardware sprites in the frame. |
| NES-H9 | legal | scene | 8 | At most 8 hardware sprites on any scanline (the PPU drops the rest). |
| NES-H10 | legal | scene | 1 mode | One sprite size for the whole frame: all 8x8 or all 8x16. |
| NES-H11 | legal | scene | 256 | Unique BG tiles fit the BG pattern table (exact match, no flips). |
| NES-H12 | legal | scene | 256 | Unique OBJ tiles fit the sprite pattern table (dedup with H/V flips). |
| NES-H13 | legal | scene | 256 x 240 | Screen: BG fits 256x240 (one nametable); OBJ X in [0, 255] and top row in [1, 239]. |
| NES-H14 | legal | scene | — | Content in the left 8 px is hidden when the scene clips the left column. |

Build errors (exit 3):

- `CM-STRICT-LIGHTING`: lighting/lamp/bump/normals multiply RGB and leave the palette
- `CM-STRICT-GLOW`: glow() colour mode leaves the palette; use glow(keys, { ramp: n })
- `CM-STRICT-ALPHA`: partial alpha has no hardware meaning
- `CM-STRICT-COLOR`: a hex color that is not a console color
- `CM-STRICT-USE`: built-in pxl palettes are not console colors
- `CM-NES-0D`: nes(0x0D) is forbidden ('blacker than black')
- `CM-NES-RANGE`: nes() takes a byte 0x00-0x3F
- `CM-DETERMINISM`: Math.random/Date are disabled so builds are reproducible
- `CM-SCENE`: malformed rg.scene / rg.tileset
- `CM-INCLUDE`: include() outside the submitted art files
- `CM-SANDBOX-TIMEOUT`: the build ran past its time limit
- `CM-SANDBOX-SIZE`: rendered output is larger than allowed
- `CM-SANDBOX-EXIT`: the build process died or wrote no result
- `CM-INPUT`: the submitted files are not acceptable (raster input, size, names)
- `CM-BUILD`: pxl reported an error
- `CM-ROUNDTRIP`: internal: the rules and the encoder/reference PPU disagree (a code-mode bug; please report it)
<!-- END GENERATED: rules nes -->

## SNES (BG mode 1)

The same loop with `--console snes`: `bind --console snes`, write the art, `build ... --console snes --tier legal`,
fix the blamed lines, `verify`. Outputs land in `out/snes/legal/snes/`: `<scene>.bg1.4bpp` (`.bg2.4bpp`,
`.bg3.2bpp`), `<scene>.bgN.map`, `<scene>.obj.4bpp`, `<scene>.cgram`, `<scene>.oam`, `<scene>.vram.json` (where each
blob goes in VRAM and the PPU register values), per-palette slices in `pal/`, and ca65 `.s` / cc65 `.h` includes.
`python -m retrogaze.codemode rom art.px.js --console snes` builds a LoROM viewer (`.sfc`, needs cc65).

### SNES craft habits

- Colors are 15-bit: `snes(r, g, b)` with each channel 0-31. Nothing is bound until you call `pal({...})`.
- A 4bpp BG tile shows 15 colors and picks one of 8 palettes; plan tiles so neighbours can share palettes. BG3 is
  2bpp (3 colors per tile) and its palettes live inside BG palettes 0-1: keep HUD colors few.
- One OBJ uses one palette of 15 colors, whatever its size: a 32x32 OBJ with 16 colors fails even if every 8x8 tile
  has fewer. Split a busy sprite into smaller OBJs (`{ size: "16x16" }`) or layers named `obj:<n>`.
- Two OBJ sizes per frame (OBSEL). The decomposer picks the pair with the fewest OBJs; pin it with `obsel` or a
  placement `size` when you need control. There is no 8x16 OBJ.
- 32 OBJs and 34 8-px slivers per line: wide OBJs cost slivers even where they are transparent.
- Back to front: backdrop, BG3, BG2, BG1, OBJ. Transparent pixels show the layer below. For a HUD, draw it on BG3
  and set `bg3Front: true`: BG3 then sits in front of everything, OBJs included.

## SNES rules (generated from the rule registry; do not edit by hand)

<!-- BEGIN GENERATED: rules snes -->
### SNES binding

- Colors: `snes(r5, g5, b5)` (each 0-31) or `bgr555(word)` return the hex of a 15-bit color; hex literals must be canonical SNES colors (channel = (q * 255) // 31).
  The active palette starts empty: bind keys with `pal({ s: snes(31, 24, 16), k: snes(0, 0, 4) })`.
- Disabled (they leave the palette): `lighting`, `lamp`, `bump`, `normals`, `glow` without `ramp`, partial-alpha colors, `Math.random`, `Date`.
- `rg.scene(name, { bg1, bg2, bg3, bg3Front, obj: [[asset, x, y, { flip, size }]...], backdrop, obsel, palettes, chr, mode, allowUndocumentedObjSizes })` declares one Mode 1 frame: BG1/BG2 4bpp (15 colors per tile), BG3 2bpp (3), OBJ 4bpp (15 per OBJ). Back to front: backdrop, BG3, BG2, BG1, OBJ; with `bg3Front: true` (BGMODE bit 3) BG3 moves in front of everything, OBJs included: a HUD.
- OBJ sizes come in OBSEL pairs (8/16, 8/32, 8/64, 16/32, 16/64, 32/64); the decomposer picks the cheapest pair unless `obsel` or a placement `size` ("16x16") pins it. 16x32/32x64 need `allowUndocumentedObjSizes: true`.
- `rg.tileset(name)` marks a BG tile set (BG1; every 8x8 tile picks its own palette).
- Sprite layers named `obj:<n>` become overlapping OBJs.

| Rule | Tier | Scope | Limit | Rule |
|---|---|---|---|---|
| SNES-L1 | like | image | 32 768 colors | Every opaque channel value is a canonical 5-bit level e(q) = (q * 255) // 31 (15-bit BGR). |
| SNES-L2 | like | image | 8 px | Grid: BG images are multiples of 8 (never padded); OBJ images are padded with transparent pixels on the right and bottom to multiples of 8 (reported, no drawn pixel moves). |
| SNES-L3 | like | image | 16 | At most 16 opaque colors per 8x8 tile. |
| SNES-L4 | like | image | — | Alpha is binary: every pixel is fully opaque or fully transparent. |
| SNES-H1 | legal | image | 15 / 3 | BG: each 8x8 tile of a 4bpp layer (BG1, BG2) uses at most 15 opaque colors, of the 2bpp BG3 at most 3 (pixel value 0 is transparent). |
| SNES-H2 | legal | image | — | OBJ: the asset decomposes into OBJs of real OBJ sizes (8x8, 16x16, 32x32, 64x64; 16x32 and 32x64 are undocumented); there is no 8x16 OBJ. |
| SNES-H3 | legal | image | 15 | OBJ: each OBJ as a whole (8x8 up to 64x64) uses at most 15 opaque colors: one palette per OBJ. |
| SNES-H4 | legal | image | 9-bit X, 8-bit Y | OBJ: X in [-255, 255] and never -256 (counted on every line it covers); Y is 8-bit and an OBJ's rows stay in 0-255 (taller spans wrap to the top of the screen). |
| SNES-H5 | legal | scene | 1 | One backdrop color (CGRAM 0); opaque pixels in the backdrop color still take a palette slot. |
| SNES-H6 | legal | scene | 8 x 15 | 4bpp BG tile color sets (BG1 and BG2 share CGRAM 0-127) pack into 8 palettes of 15; BG3's 8 palettes of 3 sit inside CGRAM 0-31 and are packed jointly with them. |
| SNES-H7 | legal | scene | 8 x 15 | OBJ color sets pack into 8 palettes of 15 (CGRAM 128-255). |
| SNES-H8 | legal | scene | 1 pair | Every OBJ size in the frame belongs to one OBSEL pair (0-5; 6-7 only with allowUndocumentedObjSizes). |
| SNES-H9 | legal | scene | 128 | At most 128 OBJs in the frame. |
| SNES-H10 | legal | scene | 32 | At most 32 OBJs on any line (range); the PPU keeps the first 32 in OAM order. |
| SNES-H11 | legal | scene | 34 | At most 34 8-px slivers on any line (time); only tiles that reach the screen count; slivers are fetched from the highest OAM index down, so the frontmost OBJs lose theirs. |
| SNES-H12 | legal | scene | 1024 | Unique BG tiles per layer fit its 10-bit tile numbers (dedup with H/V flips; the palette is per map entry). |
| SNES-H13 | legal | scene | 2 x 256 | OBJ tiles fit the two 256-tile OBJ name tables; each large OBJ is a block on the 16-column grid. |
| SNES-H14 | legal | scene | 65 536 bytes | VRAM layout fits 64 KiB: BG CHR on 8 KiB, tilemaps on 2 KiB, the OBJ base on 16 KiB boundaries. |
| SNES-H15 | legal | scene | mode 1 | Screen 256x224, BG mode 1, one 32x32 tilemap per BG layer (BG images at most 256x256). |

Build errors (exit 3):

- `CM-STRICT-LIGHTING`: lighting/lamp/bump/normals multiply RGB and leave the palette
- `CM-STRICT-GLOW`: glow() colour mode leaves the palette; use glow(keys, { ramp: n })
- `CM-STRICT-ALPHA`: partial alpha has no hardware meaning
- `CM-STRICT-COLOR`: a hex color that is not a console color
- `CM-STRICT-USE`: built-in pxl palettes are not console colors
- `CM-SNES-RANGE`: snes() takes three integers 0-31; bgr555() a word 0x0000-0x7FFF
- `CM-DETERMINISM`: Math.random/Date are disabled so builds are reproducible
- `CM-SCENE`: malformed rg.scene / rg.tileset
- `CM-INCLUDE`: include() outside the submitted art files
- `CM-SANDBOX-TIMEOUT`: the build ran past its time limit
- `CM-SANDBOX-SIZE`: rendered output is larger than allowed
- `CM-SANDBOX-EXIT`: the build process died or wrote no result
- `CM-INPUT`: the submitted files are not acceptable (raster input, size, names)
- `CM-BUILD`: pxl reported an error
- `CM-ROUNDTRIP`: internal: the rules and the encoder/reference PPU disagree (a code-mode bug; please report it)
<!-- END GENERATED: rules snes -->

---
name: retrogaze-code-mode
description: Draw console-legal NES pixel art as code with Retrogaze code mode (pxl .px.js files checked against real NES hardware limits, exported as CHR/palette/nametable/OAM bytes with provenance proving no AI image model was used). Use when asked for NES sprites, tiles, backgrounds or scenes that must run on the console or be cleared for paid release as code-drawn art.
---

# Retrogaze code mode (NES)

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

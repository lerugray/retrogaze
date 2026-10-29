# Retrogaze Code Mode: spec

**Status:** approved for build (§8 decided 2026-10-29). **M1 (NES console-legal) is implemented** on branch
`claude/happy-bardeen-i9nsun`; this spec records the decisions the build made (marked *M1:*).
**Base:** `main` at `5276809`. **Date:** 2026-10-29.
**Owner:** Ray Weiss. **First consoles at full legality:** NES and SNES (Ray's pick).

> "maybe we should attempt to see if the new code-drawn graphic approaches we've borrowed from other repos could be
> combined with retrogaze principles to create sort of a customized code-drawn graphics generator that can do both
> console-like and console-legal graphics for games"
>
> Ray Weiss, who then picked **NES + SNES first.**

Everything below answers that sentence. Two words in it carry the design: *console-like* and *console-legal*. They are
two tiers with exact, testable definitions (§2). "Legal" is proven by building a ROM and running it (§5), not claimed.

**Reading guide.** §1 explains why the mode exists and what it promises. §2 is the rulebook a validator implements.
§3 covers architecture and the claude-pxl decision. §4 lists exporters byte by byte. §5 is the proof harness. §6 lists
milestones with red-first acceptance tests. §7 lists anti-goals. §8 asks the questions that only Ray can answer.
Appendix A lists every source this spec relies on.

---

## 1. Purpose and why

### 1.1 What code mode is

Code mode is a third way to make art in Retrogaze, beside the two that exist today:

| Mode | Where it lives today | How pixels are made | Rebuildable source? | Hardware legality |
|---|---|---|---|---|
| `flux` | `src/retrogaze/generate.py`, `pipeline.py` | AI image model (FLUX on fal.ai), then pixelize and `enforce_constraints` | No | Compliance metadata only |
| `aseprite` | `src/retrogaze/generate_aseprite.py`, `pipeline.py:474-540` | An LLM issues drawing tool calls into Aseprite via pixel-mcp. It is "palette-compliant by construction" (`generate_aseprite.py:8`) | No (Aseprite state plus a tool-call log) | Compliance metadata only |
| **`code` (new)** | `src/retrogaze/codemode/` | A deterministic drawing program (`.px.js`, the claude-pxl DSL) runs inside a Retrogaze console binding | **Yes: the `.px.js` files are the art** | **Two tiers: console-like, or console-legal proven by ROM** |

In code mode a `.px.js` file is bound to a Retrogaze console profile. The drawer only gets that console's colors and
grid. Retrogaze then checks the rendered pixels against the console's rules, encodes them into the console's real
memory formats (CHR, nametables, CGRAM, OAM), re-renders those bytes with a reference PPU, and confirms that the result
is pixel-identical. At milestone gates it also boots the bytes in an emulator.

### 1.2 Why

Ray's studio rule allows AI-image art in free releases only. Art drawn as code is allowed in paid games. Neither
existing mode produces art the rule clears:

- FLUX output comes from an AI image model by definition.
- Aseprite-mode output has no rebuildable source. Nobody can later show how a given pixel was made.

Code mode makes art that (a) never passes through an image model, (b) carries proof of that, and (c) is
**console-legal**. The last point lets it go straight into Ray's own NES and SNES homebrew as CHR and CGRAM bytes, with
no hand cleanup.

The second reason is quality. Retrogaze's engine today fixes images after the fact: `enforce.py` remaps colors and
`tiles.py:reduce_tile_colors` (line 120) recolors minority pixels. That is right for FLUX output but wrong for authored
art. Code mode never changes a pixel. It reports the violation and points at the source line that painted it (§3.4.6),
and the author edits the code.

### 1.3 Promises (invariants every milestone must keep)

| ID | Invariant | Enforced by |
|---|---|---|
| **I1** | **No AI image model anywhere in the path.** The code-mode package imports no image-generation client and no model SDK. It makes no network calls and accepts **no raster input** (no PNG/JPEG upload, no reference image, no base64 image, no image-import op). | M1-02, M1-03, M1-04 |
| **I2** | **Deterministic.** The same source files, vendored pxl tree and Retrogaze commit produce byte-identical outputs. | M1-07 |
| **I3** | **No silent pixel changes.** Code mode validates and reports. It never remaps, dithers or "fixes" pixels. Hardware layout choices (cell offsets, palette slots, OAM order) are not pixel changes, and neither is the reported transparent padding of OBJ canvases (NES-L2, SNES-L2). | M1-16, M1-17 |
| **I4** | **Every output says it is code-drawn**, in-band (PNG chunks, sheet JSON `meta`) and in a sidecar manifest. No API layer strips it. | M1-18, M1-22 |
| **I5** | **"Legal" means encodable and proven.** The art encodes into hardware bytes, those bytes re-render pixel-identically, and per-scene runtime limits hold. The proof ROM confirms it in an emulator. | M1-16, M1-26, M2-13 |
| **I6** | **Existing modes are untouched.** FLUX and Aseprite behavior, outputs and tests stay byte-for-byte the same. | §7, M1-28 |

### 1.4 Provenance: output is marked as code-generated

Every code-mode output carries this block. It is JSON Schema `retrogaze.provenance/1`, and the schema file ships at
`src/retrogaze/codemode/schema/provenance-1.json`.

```json
{
  "schema": "retrogaze.provenance/1",
  "mode": "code",
  "digital_source_type": "http://cv.iptc.org/newscodes/digitalsourcetype/algorithmicMedia",
  "ai_image_model": null,
  "raster_inputs": [],
  "network_used": false,
  "renderer": {
    "name": "pxl",
    "upstream": "https://github.com/crsolver/claude-pxl",
    "commit": "21fee41f7ecce00bc868d7567f24ffd0f3acc8fa",
    "vendored_tree_sha256": "<sha256 of third_party/pxl/MANIFEST.sha256>",
    "node": "v24.x.y"
  },
  "retrogaze": { "version": "<package version>", "git_commit": "<sha or 'unknown'>", "binding_sha256": "<sha256 of the generated binding>" },
  "source": {
    "entry": "hero.px.js",
    "files": { "hero.px.js": "sha256:…", "parts.px.js": "sha256:…" }
  },
  "source_author": "human | llm | mixed | unknown",
  "console": "nes",
  "tier_requested": "legal",
  "verdict": "legal | like | fail",
  "outputs": { "png/hero.png": "sha256:…", "nes/title.chr": "sha256:…" },
  "built_at": "2026-10-29T12:00:00Z"
}
```

- `digital_source_type` uses the IPTC NewsCodes term **`algorithmicMedia`**: "Media created purely by an algorithm not
  based on any sampled training data". It is deliberately not `trainedAlgorithmicMedia`, the term for AI-model output.
- `source_author` records who wrote the code. An LLM writing `.px.js` is an LLM writing code, not an image model.
  Whether the studio rule cares about that difference is Ray's call (**§8 Q1**). The field defaults to `unknown`.
  The agent skill tells agents to set it to `llm` when they wrote the code.
- `built_at` is the only field outside the determinism hash (I2). *M1:* files embed only the deterministic fields
  (plus `pixels_sha256` of that image); `built_at`, the Node version and the git commit live in `manifest.json` only,
  so a rebuild at another commit or on another machine still compares equal.
- **Where it goes:**
  - Each PNG gets an `iTXt` chunk with keyword `retrogaze:provenance` holding the JSON.
  - Each PNG also gets an XMP packet (`iTXt` keyword `XML:com.adobe.xmp`) with `Iptc4xmpExt:DigitalSourceType` set to
    the URI above. Both are written with Pillow's `PngInfo`, which is already a dependency.
  - Each sheet JSON gets `meta.retrogaze.provenance`.
  - Raw binaries (`.chr`, `.cgram`, …) cannot carry metadata. They are listed with their sha256 in
    `out/.../manifest.json`, which embeds the same block.
- **Verifiable, not just asserted:** `python -m retrogaze.codemode verify <out-dir>` rebuilds from the recorded sources
  and compares every recorded hash. Exit codes: `0` all match, `1` a mismatch (it names the file), `4` the checkout's
  pxl tree or binding hash differs from the recorded one (it tells the user which commit to check out).
- **Release gate:** `python -m retrogaze.codemode audit <assets-dir>` walks a game's asset folder. It exits non-zero if
  any PNG or binary lacks provenance that verifies. Ray can run it in a paid game's CI to enforce the studio rule
  mechanically. A FLUX PNG reports as "no code-mode provenance".

---

## 2. Two tiers, defined exactly per console

### 2.1 Vocabulary

- **Asset**: one pxl `sprite`, `anim`, `scene` or Retrogaze `rg.tileset` (§3.2), as rendered by pxl. An anim has one
  image per frame.
- **Image**: one rendered RGBA bitmap of an asset (one frame of an anim).
- **Tile**: an 8×8 pixel block aligned to the image or screen origin.
- **Cell**: one hardware sprite. On NES that is 8×8 or 8×16. On SNES it is one OBJ of 8×8 up to 64×64.
- **Area**: a NES attribute area of 16×16 pixels (2×2 tiles) that shares one BG palette.
- **Scene**: everything the hardware shows in one frame: the BG layers, every OBJ placement, the backdrop and the
  palette assignment. A scene is declared with `rg.scene(...)` (§3.2). An asset built without a scene is checked as a
  **lone-asset scene**: pxl `scene()` assets as BG at the screen origin, `sprite()`/`anim()` assets as OBJ at
  (8, 8) on NES (so any decomposition offset stays on screen) or (0, 0) on SNES. So "this metasprite alone is too wide for a scanline" is still caught.
- **Scope tags**: **[I]** is a per-image check (needs only that one image). **[S]** is a per-scene check (needs the
  whole frame or animation: palettes, counts, budgets).
- **Tiers**:
  - **Console-like** = palette and grid of the era. Every **[I]** "L" rule passes. It is defined to equal the existing
    Retrogaze compliance verdict (`mcp_routes.py:333-336`: `palette_valid ∧ colors_per_tile_valid ∧ grid_aligned`)
    plus binary alpha, so "like" means what Retrogaze already means by compliant.
  - **Console-legal** = passes the real hardware limits. Every L rule and every "H" rule passes, **[I]** and **[S]**.
    By construction legal ⇒ like.
- **Verdict** = the highest tier that passed: `legal`, `like` or `fail`. The CLI exits 0 when the *requested* tier
  passed.

**What "legal" deliberately excludes.** Mid-frame tricks are out of scope: raster palette changes, sprite
multiplexing or flicker, mid-frame CHR bank switches, scrolling across more than one screen, sprite-0 splits, color
emphasis bits. These tricks can only make *more* art displayable. Excluding them makes the validator conservative:
it never calls something legal that needs a trick. Flicker is **§8 Q8**.

### 2.2 NES (NTSC 2C02 PPU)

Hardware facts used, from the NESdev wiki (Appendix A):

- Palette RAM is `$3F00-$3F1F`: 4 BG palettes and 4 sprite palettes of 4 entries each. Entry 0 is transparent. The
  backdrop is `$3F00`, which `$3F10` mirrors.
- `$0D` must not be used ("blacker than black"). Canonical black is `$0F`. Columns `$xE`/`$xF` are black.
- Each attribute byte covers 32×32 px as four 2-bit fields of 16×16 each:
  `value = (BR<<6)|(BL<<4)|(TR<<2)|TL`.
- OAM holds 64 sprites × 4 bytes: Y−1, tile, attributes (`VHP000PP`), X. Sprites are never drawn on the first visible
  line. Secondary OAM holds 8 sprites per scanline.
- Sprite size (8×8 or 8×16) is one global PPUCTRL bit. In 8×16 mode, tile bit 0 selects the pattern table and the
  bottom tile is the next index.
- A pattern table holds 256 tiles of 16 bytes each: plane 0 then plane 1, bit 7 = leftmost pixel. There are two
  tables, `$0000` and `$1000`.
- **BG tiles cannot be flipped. Sprites can** (H/V attribute bits).

**Color set.** The legal colors are the unique RGB values of Retrogaze's existing NES table `_NES_PALETTE_HEX`
(`console_profile.py:79`, also `palette.py:19`): 56 entries, **54 unique**. `#FFFFFF` appears at both `$20` and `$30`,
and `#000000` at `$0D` and `$1D`. The byte for table index *i* is `(i // 14) * 16 + (i % 14)`. Canonical bytes on
export are `#000000 → $0F` (never `$0D`) and `#FFFFFF → $30`. A scene that pins palette bytes explicitly gets those
bytes verbatim (§3.2), except that `$0D` is always rejected.

| ID | Tier | Scope | Rule | Limit |
|---|---|---|---|---|
| NES-L1 | like | [I] | Every opaque pixel is one of the 54 NES colors (exact RGB match, as in `metadata._check_palette_valid`, `metadata.py:77`) | 54 colors |
| NES-L2 | like | [I] | Grid. **BG** images have width and height that are multiples of 8, with no padding. **OBJ** images (pxl `outline` grows the canvas by 1 px per side) are padded with transparent pixels on the right and bottom to multiples of 8. The padding is reported as `padded: [w₀,h₀]→[w,h]`, and no drawn pixel moves | 8 px |
| NES-L3 | like | [I] | ≤ 4 opaque colors per 8×8 tile (the existing `tiles.validate_tile_colors`, `tiles.py:72`, with `NES.max_colors_per_tile`) | 4 |
| NES-L4 | like | [I] | Alpha is binary: every pixel has α = 0 or 255 (pxl allows `#rrggbbaa`) | — |
| NES-H1 | legal | [I] | Every color encodes to a 2C02 byte; `$0D` is never emitted or accepted | — |
| NES-H2 | legal | [I] | **BG:** each 16×16 attribute area, aligned to the nametable origin, uses ≤ 3 colors besides the scene backdrop. Transparent BG pixels count as backdrop | 3 + backdrop |
| NES-H3 | legal | [I] | **OBJ:** each hardware sprite cell uses ≤ 3 opaque colors (+ transparent). Cells are aligned to the decomposition origin (§3.4.1), and fully transparent cells cost nothing | 3 |
| NES-H4 | legal | [I] | **OBJ (normalization, never fails):** in 8×16 mode the transparent padding of NES-L2 extends to height multiples of 16. Padded cells that stay fully transparent cost nothing | — |
| NES-H5 | legal | [S] | One backdrop color for the scene (`$3F00`). If not declared, the solver picks the color that makes NES-H6 feasible (ties go to the most frequent color, then the lowest byte) | 1 |
| NES-H6 | legal | [S] | The color sets of all BG areas pack into ≤ 4 palettes of 3 colors (+ shared backdrop). Exact solver; an unsat core is reported on failure (§3.4.2) | 4 × 3 |
| NES-H7 | legal | [S] | The color sets of all OBJ cells pack into ≤ 4 sprite palettes of 3 colors | 4 × 3 |
| NES-H8 | legal | [S] | ≤ 64 hardware sprites in the frame | 64 |
| NES-H9 | legal | [S] | ≤ 8 hardware sprites on any scanline 0-239. A sprite covers lines `[top, top+h)`. When over the limit, the report names the sprites the PPU drops (highest OAM index first) | 8 |
| NES-H10 | legal | [S] | One sprite size for the whole frame: all 8×8 or all 8×16 | 1 mode |
| NES-H11 | legal | [S] | Unique BG tiles ≤ 256. Dedup is exact on 2-bit index patterns, **with no flips** | 256 |
| NES-H12 | legal | [S] | Unique OBJ tiles ≤ 256 (8×8 mode, one table), dedup on index patterns with H/V flips. In 8×16 mode, tile pairs (even top index) can draw from both tables, subject to the CHR budget model (§8 Q5) | 256 / budget |
| NES-H13 | legal | [S] | Screen: BG ≤ 256×240 (one nametable, M1). OBJ X ∈ [0, 255] and top ∈ [1, 239] (Y byte = top − 1; top 0 is not displayable) | — |
| NES-H14 | legal | [S] | (warning) Content in the left 8 px is reported when the scene enables left-column clipping | — |

Animations: each frame is a scene state. Palettes stay fixed across all frames of a scene. The CHR budget (NES-H11,
NES-H12) counts the **union** of all frames' tiles (CHR-ROM, no banking). A scene can set `chr: "per-frame"` for
CHR-RAM streaming; the budget is then checked per frame and the report lists bytes uploaded per frame. Vblank
bandwidth is not checked in M1 or M2.

### 2.3 SNES (S-PPU), focus Mode 1 4bpp

Hardware facts used, from the SNESdev wiki (Appendix A):

**BG modes and bit depth (bpp per layer):**

| Mode | BG1 | BG2 | BG3 | BG4 | Note |
|---|---|---|---|---|---|
| 0 | 2 | 2 | 2 | 2 | Each layer has its own 32-color range of CGRAM 0-127 |
| **1** | **4** | **4** | 2 | — | **Code mode's legal target.** BG3 uses CGRAM 0-31 |
| 2 | 4 | 4 | offset-per-tile | — | |
| 3 | 8 | 4 | — | — | BG1: 256 colors or direct color |
| 4 | 8 | 2 | offset-per-tile | — | |
| 5 | 4 | 2 | — | — | hi-res |
| 6 | 4 | — | offset-per-tile | — | hi-res |
| 7 | 8 | (EXTBG) | — | — | 128×128 map, 256 tiles |

**Palettes:**

- CGRAM is 256 entries of 15-bit BGR (`0bbbbbgggggrrrrr`, written low byte first). Entry 0 is the backdrop.
- 4bpp BG uses 8 palettes × 16 (CGRAM 0-127).
- 2bpp BG uses 8 palettes × 4. Mode 1 BG3 sits at CGRAM 0-31, overlapping 4bpp palettes 0-1.
- OBJ uses 8 palettes × 16 (CGRAM 128-255) and is 4bpp only.
- **Pixel value 0 is transparent at every depth**, so a 4bpp palette shows 15 colors.

**OBJ:**

- OAM is 544 bytes: 128 × 4 bytes plus a 32-byte table holding 2 bits per sprite (X bit 8, size select).
- Attribute byte is `VHPP CCCt`.
- OBSEL picks two sizes per frame:

  | OBSEL | Small | Large |
  |---|---|---|
  | 0 | 8×8 | 16×16 |
  | 1 | 8×8 | 32×32 |
  | 2 | 8×8 | 64×64 |
  | 3 | 16×16 | 32×32 |
  | 4 | 16×16 | 64×64 |
  | 5 | 32×32 | 64×64 |
  | 6 | 16×32 | 32×64 (undocumented) |
  | 7 | 16×32 | 32×32 (undocumented) |

- There is no 8×16 OBJ.
- Per scanline: ≤ 32 sprites, and ≤ 34 8-pixel slivers.
- A sprite at X = −256 still counts against both limits (hardware bug).
- **One palette per OBJ**, not per tile.

**Tilemaps and VRAM:**

- Tilemap entries are `VHPC CCTT TTTT TTTT`: 10-bit tile, 3-bit palette, priority, flips.
- A 32×32 map is 2 KiB. 16×16 BG tiles use N, N+1, N+16, N+17.
- VRAM is 64 KiB.
- BG CHR bases sit on 8 KiB boundaries and tilemaps on 2 KiB boundaries.
- The OBJ name base is `bBB<<13` words (16 KiB steps). The second OBJ table sits `(NN+1)<<12` words above it.

**Color set and canonical expansion.** A 5-bit channel value *q* displays as `e(q) = (q·255) // 31`. This is
Retrogaze's existing expansion: `palette.quantize_to_bit_depth` (`palette.py:463`) and
`metadata._check_palette_valid` (`metadata.py:112`). Code mode keeps it so that "like" agrees with the existing engine.
It differs from the common bit-replication `(q<<3)|(q>>2)` at 15 of 32 levels (for example `e(4) = 32`, not 33). The
binding therefore hands out `snes(r5, g5, b5)` and never asks the artist to type hex (§3.2).

| ID | Tier | Scope | Rule | Limit |
|---|---|---|---|---|
| SNES-L1 | like | [I] | Every opaque channel value is some `e(q)` (= `metadata._check_palette_valid` for `color_depth_bits=15`) | 32 768 colors |
| SNES-L2 | like | [I] | Grid, as NES-L2: BG images are multiples of 8; OBJ images are padded transparently and the padding is reported | 8 px |
| SNES-L3 | like | [I] | ≤ 16 opaque colors per 8×8 tile (existing `validate_tile_colors` with `SNES_MODE1.max_colors_per_tile=16`, `console_profile.py:323`) | 16 |
| SNES-L4 | like | [I] | Binary alpha | — |
| SNES-H1 | legal | [I] | **BG:** each 8×8 tile of a 4bpp layer uses ≤ 15 opaque colors (index 0 = transparent). A 2bpp layer (BG3) uses ≤ 3 | 15 / 3 |
| SNES-H2 | legal | [I] | **OBJ:** the asset decomposes into OBJs of the scene's two OBSEL sizes (§3.4.1) | — |
| SNES-H3 | legal | [I] | **OBJ:** each OBJ as a whole (8×8 up to 64×64) uses ≤ 15 opaque colors, because the palette is per object | 15 |
| SNES-H4 | legal | [I] | OBJ X ∈ [−255, 255] (9-bit), **X ≠ −256**. Y is 8-bit | — |
| SNES-H5 | legal | [S] | One backdrop (CGRAM 0). Opaque pixels in the backdrop color still use a palette slot (conservative: never relies on index 0 showing the backdrop through other layers) | 1 |
| SNES-H6 | legal | [S] | 4bpp BG tile color sets (BG1 and BG2 share CGRAM 0-127) pack into ≤ 8 palettes × 15. If BG3 is used, its 8 × 3 palettes occupy CGRAM 0-31 and the solver packs them jointly | 8 × 15 |
| SNES-H7 | legal | [S] | OBJ color sets pack into ≤ 8 palettes × 15 (CGRAM 128-255) | 8 × 15 |
| SNES-H8 | legal | [S] | Every OBJ size in the frame belongs to **one** OBSEL pair. Pairs 0-5 by default; 6-7 only with `allowUndocumentedObjSizes` (§8 Q7) | 1 pair |
| SNES-H9 | legal | [S] | ≤ 128 OBJs in the frame | 128 |
| SNES-H10 | legal | [S] | ≤ 32 OBJs on any scanline 0-223 ("range") | 32 |
| SNES-H11 | legal | [S] | ≤ 34 8-px slivers on any scanline ("time"). On-screen slivers count; every sliver of an X = −256 sprite counts (SNESdev wiki). The proof ROM pins the exact edge behavior (§5.4) | 34 |
| SNES-H12 | legal | [S] | Unique BG tiles ≤ 1024 per BG CHR base (10-bit index). Dedup on 4-bit index patterns with H/V flips. Palette is per tilemap entry, so the same pattern under two palettes is one tile | 1024 |
| SNES-H13 | legal | [S] | OBJ tiles fit the two 256-tile OBJ name tables. Each large OBJ's tiles must place as a block on the 16-column grid (tile N, N+1, …, N+16, …); the allocator must succeed | 2 × 256 |
| SNES-H14 | legal | [S] | VRAM layout ≤ 65 536 bytes with alignment: BG CHR on 8 KiB, tilemaps on 2 KiB, OBJ base on 16 KiB. The allocator prints the map | 64 KiB |
| SNES-H15 | legal | [S] | Screen 256×224. One 32×32 tilemap per BG layer in M2. `mode` must be 1 at the legal tier; other modes are like-only for now | — |

Animations follow the NES rules in §2.2: palettes fixed per scene, CHR union by default, `chr: "per-frame"` opt-in.

### 2.4 The other six systems (M3, console-like only)

The six are Game Boy DMG, Game Boy Pocket, Game Boy Color, Genesis / Mega Drive, Commodore 64 (hires and multicolor
profiles) and PC Engine. Each gets L1-L4 from its existing `ConsoleProfile` (`console_profile.py`):

- L1: exact palette match for fixed-palette consoles, or canonical bit-depth values (9-bit `e₃(q) = (q·255)//7`,
  15-bit `e(q)`), exactly as in `metadata._check_palette_valid`.
- L2: grid of `profile.tile_size`. C64 multicolor uses 4×8 cells with `pixel_width = 2`.
- L3: `profile.max_colors_per_tile`.
- L4: binary alpha.

Asking for `--tier legal` on these consoles returns exit 2 with "console-legal not yet specified for <console>". It
never passes silently.

---

## 3. Architecture

### 3.1 Pipeline

```
 hero.px.js (+ includes)                    ConsoleProfile (console_profile.py) + HardwareModel (codemode/hw/*.py)
        │                                                │
        │                   Binding: palette keys, nes()/snes(), rg.*, strict wrappers, limits
        ▼                                                ▼
  python -m retrogaze.codemode build ── spawns ──► node --permission … codemode/js/rg-build.mjs
                                                        │  imports vendored pxl core (third_party/pxl @ 21fee41)
                                                        │  stdin: {files, entry, binding}   stdout: JSON
                                                        ▼
                         per asset/frame/layer RGBA · blame map · rg.scene manifests · sheet JSON
        ┌───────────────────────────────────────────────┘
        ▼
  codemode.check (Python):  [I] like rules ─► [I] legal rules ─► [S] scene rules (solvers)
                                  │
                                  ▼
                       encode (hardware structs) ─► ppu_ref.render(bytes) == composite(scene)?   (cross-check)
                                  │
             ┌────────────────────┼─────────────────────────────┐
             ▼                    ▼                             ▼
      report.json           exporters (§4)              provenance + manifest (§1.4)
  (violations + blame)   PNG · sheet+JSON · CHR/NAM/PAL/OAM · 4bpp/MAP/CGRAM/OAM · .s/.h
                                  │
                                  ▼
                 proof/ (§5): ca65+ld65 viewer ROM → Mesen2 --testRunner → dumps + screenshot == exports + render
```

**Legality is checked three times, by three independent mechanisms that must agree** (*M1:* a disagreement is
reported as `CM-ROUNDTRIP` and fails the build; it caught the left-column clipping case during the build):

1. **Rules** (§2 tables). These give readable messages and blame.
2. **Encoding plus re-render.** Building the real bytes and decoding them through `ppu_ref` must reproduce the
   composite pixel-for-pixel. If the rules pass but encoding fails, or the reverse, that is a bug (test M1-16).
3. **Emulator** (§5) confirms that `ppu_ref` matches hardware behavior.

### 3.2 Binding: how a `.px.js` drawing gets the console's palette and grid

pxl evaluates an art file in a `node:vm` context whose globals are the DSL. In pxl's sources these come from
`Project.env()` (`src/core/project.ts`), and the loader is `src/node/load.ts`, about 60 lines. Retrogaze does **not**
fork pxl. It ships its own loader, `codemode/js/rg-build.mjs`, which:

1. Creates a `Project` with `{ trace: true }` and takes `p.env()`.
2. Extends and wraps that env with the binding.
3. Runs the files from an in-memory file map (`include()` resolves only inside that map, so no file-system reads are
   needed).
4. Returns everything as JSON on stdout.

This uses only pxl's public library surface (`Project`, `Palette`, `Trace`, `packSheet`, `sheetJson`, exported from
`src/core/index.ts`).

**What the drawer is handed.** These globals are added to the pxl env:

| Global | NES | SNES | Notes |
|---|---|---|---|
| active palette | `use()` preset to the 54 NES colors (index keys `0-9a-zA-R`, in table order) | empty. Every key comes from `pal({...})` with `snes()` values | built-in `use("pico8")`-style palettes are disabled (they are not console colors) |
| `nes(byte)` | → canonical hex for a 2C02 byte. `$0D` throws `CM-NES-0D`. `> $3F` throws. `$xE/$xF` → black | — | `pal({ k: nes(0x0F), r: nes(0x16), o: nes(0x27), w: nes(0x30) })` |
| `snes(r5,g5,b5)` / `bgr555(word)` | — | → canonical hex `#rrggbb` via `e(q)` | `pal({ s: snes(31, 24, 16) })` |
| `rg` (frozen) | `rg.console`, `rg.tier`, `rg.tile=8`, `rg.area=16`, `rg.screen={w:256,h:240}`, `rg.limits{…}`, `rg.colors[]` | same, with `rg.screen={w:256,h:224}` | limits come from §2 tables, rendered from `codemode/hw/*.py` |
| `rg.scene(name, spec)` | `{ bg, obj:[[asset,x,y,opts]…], backdrop, objSize:"8x8"\|"8x16", palettes?, chr? }` | `{ bg1, bg2?, bg3?, obj, backdrop, obsel?, palettes?, chr? }` | records a hardware scene manifest (§2.1) |
| `rg.tileset(name, { metatile })` | declares a BG tile set. Each 16×16 metatile is one attribute area | each 8×8 / 16×16 tile picks its own palette | the asset is drawn with normal pxl ops |
| `rg.palettes({ bg:[…], obj:[…] })` | optional pins, as NES bytes or `nes()` values. Pinned bytes are exported verbatim | optional pins, as 15-bit words or `snes()` values | otherwise the solver assigns them (§3.4.2) |

**Strict wrappers** (both tiers; they fail at definition time with pxl's own `file:line:col` error locations):

| Wrapped | Why | Error |
|---|---|---|
| `lighting`, `lamp`, `bump`, `normals` | pxl lighting multiplies RGB (`src/core/light.ts`) and leaves the palette | `CM-STRICT-LIGHTING` |
| `glow(keys, opts)` without `opts.ramp` | colour mode "screens the source colour on top, which leaves the palette" (`src/core/glow.ts`) | `CM-STRICT-GLOW` (use `ramp:`) |
| any `#rgba` / `#rrggbbaa` with α ∉ {00, ff} | partial alpha has no hardware meaning | `CM-STRICT-ALPHA` |
| `pal({...})` and op color args that are hex | hex must be a console color (NES table, or SNES `e(q)` values) | `CM-STRICT-COLOR` (hint names the nearest legal color and the `nes()`/`snes()` call) |
| `use(name)` for built-in palettes | off-console colors | `CM-STRICT-USE` |

Everything else in the DSL is allowed and stays inside the palette: `shade`/`light` along `ramps`, `grad`, `dither`,
`noise`, `outline`, `mx`/`my`, `swap`, `stamp`, `tile`, `pattern`, `tilemap`, `scatter`, `text`, `anim`, `frame`, and
`shade:`/`light:` layers. In pxl's `blend()` (`src/core/build.ts:303`) these remap colors through the palette's ramp
maps only. The wrappers are a seat belt. **The validator is the gate.** It still catches, for example, a hex color
painted from inside a `(c) => { c.px(...) }` function.

**Example (NES):**

```js
// hero.px.js — drawn once, checked for NES legality.
pal({ k: nes(0x0F), r: nes(0x16), s: nes(0x27),     // top half:    black, dark red, gold
      b: nes(0x12), c: nes(0x21),                   // bottom half: black, blue, light blue
      g: nes(0x1A) })                               // BG ground:   green
ramps("krs", "kbc")

// Write the left 7 columns; mx mirrors to 14, outline grows to 16×16.
// Outlined rows 0-7 use {k,r,s} and rows 8-15 use {k,b,c}: 3 colors per 8×8 cell (NES-H3).
sprite("hero", { mx: true, outline: "k" }, `
  ....rrr
  ..rrrrr
  .rrssss
  .rsskss
  .rsssss
  ..sssss
  ...ssss
  ..bbbbb
  .bbcbbb
  .bbcbbb
  .bbbbbb
  ..bb.bb
  ..bb.bb
  .ccc.cc`)

scene("field", { w: 256, h: 240, bg: "c" },
  layer("ground", { y: 192 }, rect(0, 0, 256, 48, "g")))

rg.scene("title", {
  bg: "field",                                       // backdrop is solved: "c" ($21) is the most frequent
  obj: [["hero", 120, 176], ["hero", 136, 176, { flip: "x" }]],
  objSize: "8x8",
})
sheet("chars", ["hero"])
```

This scene is legal:

- 8 hardware sprites, 4 per scanline.
- 2 sprite palettes, `{k,r,s}` and `{k,b,c}`.
- 2 unique sprite tiles, because the hero is mirror-symmetric and dedups with H-flip.
- 1 BG palette `{g}` plus the backdrop, and 2 unique BG tiles.

### 3.3 Validator: reuse versus extend `enforce.py` / `tiles.py`

Rule: **call existing functions, never modify them** (I6). New checks live in new modules under `codemode/`.

| Existing function | Verdict | Use in code mode |
|---|---|---|
| `tiles.validate_tile_colors` (`tiles.py:72`) | **reuse as-is** | NES-L3, SNES-L3 and M3 L3. Its opaque-color counting is exactly the like-tier semantics |
| `metadata._check_palette_valid` (`metadata.py:77`) | **reuse as-is** | NES-L1, SNES-L1, M3 L1 |
| `metadata.generate_metadata` (`metadata.py:120`) | **reuse as-is** | the `compliance` block in code-mode metadata, so existing consumers keep working |
| `enforce.enforce_constraints` (`enforce.py:30`) | **reuse as an oracle only** | test M1-17: on legal NES BG fixtures and single-palette OBJ fixtures it must change zero pixels (finding 7 below explains the exception). It never runs in the code-mode build path, because it rewrites pixels (I3) |
| `tiles.validate_attribute_table` (`tiles.py:308`) | **not used for legality** | it caps each 16×16 block at 4 opaque colors. Legality needs ≤ 3 plus a *shared* backdrop and a ≤ 4-palette packing (NES-H2, NES-H5, NES-H6) |
| `grid.align_to_grid` (`grid.py:19`) | **not used** | it resizes (with targets) or pads without saying so. Code mode never resizes: BG misalignment fails NES-L2 / SNES-L2, and OBJ padding is explicit and reported |
| `palette.get_nes_palette_index` (`palette.py:147`) | **not used for export** | it returns the first match, so black → `$0D` (pinned by `tests/test_palette.py:127-129`). Code mode has its own byte map (§2.2) |
| `palette_alloc.allocate_palettes` (`palette_alloc.py:26`) | **not used for legality** | it is a greedy allocator that remaps pixels. Code mode needs an exact feasibility answer with an unsat core |
| `export_formats.build_godot_tres` and the Unity, GameMaker and Unreal builders (`export_formats.py:11,72,124,197`) | **reuse as-is** | they consume code-mode sheet JSON unchanged (§4.2) |

**Findings in the current engine that code mode must not inherit.** None is changed here (I6); see **§8 Q11**.

1. NES and SNES per-tile caps count opaque colors against 4 / 16 (`console_profile.py:108,323`). Hardware gives
   3 / 15 plus transparent or backdrop. So a NES sprite tile with 4 opaque colors passes today's check but cannot be
   encoded.
2. `SNES_MODE1.max_sprite_pixels_per_scanline=256` (`console_profile.py:344`), but the hardware limit is 34 slivers ×
   8 = **272** px.
3. `SNES_MODE1.sprite_sizes` lists `(16,32)` and `(32,64)` (`console_profile.py:333`) without the OBSEL "two sizes per
   frame" rule.
4. `metadata._collect_palette_info` reports NES black as `$0D` (`metadata.py:51` via `palette.py:147`).
5. `metadata.palette_slots_required = ceil(n/3)` (`metadata.py:188`) is a lower bound, not an assignment.
6. `api.py:1684-1698` strips `generation_mode` and `attribute_table_valid` from client responses (a leftover of the
   paid-product "IP protection"). Code-mode routes must not pass through that filter, because provenance is the point
   (I4).
7. `enforce.py:119-125` applies the 16×16 attribute-area reduction to every NES image whose size is a multiple of 16,
   whatever `asset_type` is. Sprites have no attribute areas, so a legal two-palette metasprite (like the §3.2 hero:
   5 colors in one 16×16 block) gets recolored. This is why M1-17 runs the zero-change check only on BG fixtures and
   single-palette OBJ fixtures.

**Profile consistency test.** `codemode/hw/nes.py` and `snes.py` hold the exact limits. A test asserts that they agree
with `ConsoleProfile` wherever the two overlap (NES 64 sprites / 8 per line / palette set; SNES 128 / 32). It also
asserts the **known differences** listed above *exactly*, as a `KNOWN_PROFILE_DIFFS` table. If someone later fixes the
profile, the test says to delete the matching diff entry.

### 3.4 Legality engine internals (`codemode/hw/`, `codemode/encode/`, `codemode/ppu_ref.py`)

#### 3.4.1 Decomposition

- **NES BG:** split into 16×16 areas and 8×8 tiles from the nametable origin. `rg.scene({ bgAt: [x, y] })` must be a
  multiple of 16.
- **NES OBJ:**
  - Each placed asset is split into cells of the scene's sprite size. Fully transparent cells are skipped.
  - The decomposition origin is searched over the 8×8 offsets (8×16 in 8×16 mode). *M1:* the search minimizes, in
    order, cells over 3 colors, max sprites per scanline, total sprites, unique pattern tiles (with flip dedup), and
    misalignment with the asset origin. So a mirror-symmetric sprite keeps the grid that lets its halves share tiles
    through the H-flip bit. It changes layout, not pixels, so I3 holds.
  - **Layered sprites:** a sprite whose pxl layers are named `obj:<n>` is decomposed per layer. Overlapping hardware
    sprites with different palettes are allowed (the classic extra-color trick). They are counted in NES-H8/H9, and
    OAM order follows paint order. *M1:* layered sprites must not use post-processing (`mx`, `outline`, `flip`,
    `crop`), because pxl applies it to the composite, not to each layer; the per-tile cap (NES-L3) applies per layer.
- **SNES OBJ:**
  - The asset is tiled greedily with the large OBSEL size, then the small size, skipping transparent blocks.
  - The search covers both sizes of each candidate OBSEL pair, and the cheapest feasible pair wins.
- **OAM order:** the last-painted object gets the lowest OAM index, which is the highest priority.

#### 3.4.2 Palette packing (NES-H6/H7, SNES-H6/H7)

The problem: given color sets S₁…Sₙ (|Sᵢ| ≤ K), find ≤ P palettes of ≤ K colors so that every Sᵢ is a subset of some
palette.

Steps:

1. Drop every set that is a subset of another set.
2. Exact backtracking, largest sets first, with symmetry breaking. This is instant for NES (K = 3, P = 4).
3. If backtracking exceeds a node budget, switch to an exact MILP using `scipy.optimize.milp` (HiGHS). SciPy is already
   a runtime dependency (`src/requirements.txt`), so this adds **no new dependency**.

On infeasibility, a deletion filter shrinks the input to a **minimal unsat core**: "these 5 areas need 5 different
palettes", with coordinates and blame. Colors are ordered inside each palette deterministically (dark → light by CIE L*
via `palette.rgb_to_lab`) unless pinned. That ordering fixes index patterns, which fixes tile dedup.

#### 3.4.3 Scanline sweep

For each line *y*, count objects covering *y*. For SNES, also sum on-screen 8-px slivers. Overflow reports name the
line ranges and the objects the PPU drops (highest OAM index first on NES; per the SNESdev evaluation order on SNES).

#### 3.4.4 Tile dedup and VRAM allocation

- Dedup runs on index patterns after palette assignment: NES BG with no flips; NES OBJ and all SNES with H/V flips.
- The SNES allocator places BG CHR, tilemaps and the OBJ tables (large OBJs as 16-column blocks) under the alignment
  rules in §2.3, first-fit by size class. It prints `vram.json`.

#### 3.4.5 Reference PPU (`ppu_ref.py`)

The reference PPU renders encoded bytes back to RGBA. Scope:

- **NES:** nametable + attributes + 4 BG palettes + OAM in 8×8 / 8×16 mode, sprite-over-BG priority 0, and dropping
  sprites past 8 per line.
- **SNES:** Mode 1 BG1/BG2 4bpp + BG3 2bpp + OBJ, the OBSEL pair, and the 32 / 34 per-line drops.

It is small, pure-Python and used in unit tests. The emulator job confirms it (§5).

#### 3.4.6 Blame: from bad pixel to source line

pxl's `Trace` (`src/core/trace.ts`) records every top-level op, layer and post-processing step with its `file:line`.
It stores each step as a diff over the previous frame. `rg-build.mjs` turns those diffs into a per-pixel "last writer"
map: `{ op label, loc }`.

Every violation lists its pixels and the top writers, for example:

```json
{
  "rule": "NES-H3",
  "scope": "image",
  "asset": "knight",
  "cell": [1, 0],
  "found": 4,
  "limit": 3,
  "colors": ["#000000", "#E09264", "#913800", "#FFFFFF"],
  "blame": [
    { "loc": "knight.px.js:9:3", "op": "grid", "pixels": 5 },
    { "loc": "knight.px.js:7:42", "op": "outline", "pixels": 2 }
  ],
  "hint": "cell (8..15, 0..7) has 4 opaque colors; sprites allow 3. Drop one of k/s/r/w here, or split with an obj:<n> layer."
}
```

Known limits, reported honestly: pxl traces only seed-0, t = 0 builds, so frames > 0 of an anim get asset-level blame.
A trace caps at 4 000 steps; steps past the cap fold into one entry.

### 3.5 Where the mode lives

```
src/retrogaze/codemode/
  __init__.py            build(), check(), export(), verify(), audit()          — public Python API
  __main__.py            python -m retrogaze.codemode {bind,build,export,rom,verify,audit}
  binding.py             ConsoleProfile + HardwareModel → binding JSON (palette, keys, limits, rule cheat sheet)
  runner.py              node subprocess: permission flags, timeouts, memory cap, stdin/stdout JSON
  js/rg-build.mjs        Retrogaze-owned loader around vendored pxl core (env extension, strict wrappers, blame)
  hw/common.py           Violation/Report types, decomposition, packing solver, scanline sweep, dedup
  hw/nes.py  hw/snes.py  exact limits + rules (single source for §2 tables, cheat sheet, MCP/skill text)
  encode/nes.py          CHR, nametable+attributes, palette, OAM, metasprites
  encode/snes.py         2bpp/4bpp, tilemap, CGRAM, OAM, VRAM allocator
  ppu_ref.py             reference renderers (bytes → RGBA)
  provenance.py          block, PNG iTXt/XMP embed, manifest, verify, audit
  schema/provenance-1.json, schema/report-1.json
src/retrogaze/codemode_routes.py   FastAPI router mounted at /code
third_party/pxl/                   vendored upstream (see §3.6)
proof/nes/  proof/snes/  proof/run_mesen.lua  proof/compare.py  proof/TOOLS.md
skills/retrogaze-code-mode/SKILL.md
examples/codemode/*.px.js
src/tests/test_codemode_*.py   src/tests/fixtures/codemode/{nes,snes,m3}/*.px.js
```

- **Art files.** *M1:* a build reads the entry file plus every file it reaches through string-literal
  `include("…")` paths (at most 32 files, 256 KiB); computed include paths are not followed.
- **CLI.** The entry point is `python -m retrogaze.codemode …`. The existing CLI (`cli.py`) takes a positional image
  path, so a `code` subcommand there would clash with it. It stays untouched.

  | Exit code | Meaning |
  |---|---|
  | 0 | requested tier passed |
  | 1 | requested tier failed (report written) |
  | 2 | usage error, or tier not supported for this console |
  | 3 | the art file did not build (syntax, sandbox, timeout) |
  | 4 | verify: version mismatch |

- **API.** A new router, `codemode_routes.py`, is mounted at `/code` the same way `/mcp` is (`api.py:253,261`):

  | Endpoint | Body or query | Returns |
  |---|---|---|
  | `POST /code/build` | `{ files: {name: text}, entry, console, tier, exports: [...], author? }` | `{ report, provenance, outputs: {path: base64} }` |
  | `POST /code/verify` | — | verify result |
  | `GET /code/binding` | `?console=&tier=` | the cheat sheet |

  - Limits: ≤ 32 files, ≤ 256 KiB of source, build timeout 20 s, ≤ 4 Mpx of output. slowapi limits as for `/mcp`.
  - Responses are built directly, never through `_STRIP_KEYS`.
  - The router is **off unless `RETROGAZE_CODE_MODE=1`**, and is refused (403) under `RETROGAZE_DEMO=1` (see §8 Q4).
  - It is **not** added to `_V1_ALLOWLIST` (`api.py:291`) in M1-M3.
- **MCP.** Three tools are added to `mcp-server/src/tools.ts`. They follow the existing tools' pattern: read local
  files, call the API, save outputs next to the source (like `retro_fix_sprite`).

  | Tool | Does |
  |---|---|
  | `retro_code_bind` | returns the binding cheat sheet for a console and tier |
  | `retro_code_build` | takes `file_path` to an entry `.px.js`, sends its directory's `*.px.js` (bounded), and returns the report with blame; writes exports |
  | `retro_code_verify` | runs verify |

  The banner's "6 tools" (`mcp-server/src/index.ts:28,90`) becomes 9.
- **Agent skill.** `skills/retrogaze-code-mode/SKILL.md` (frontmatter `name`, `description`) teaches this loop:
  1. `bind`, write, `build`.
  2. Read `report.json`.
  3. Patch the blamed lines.
  4. Repeat until `verdict == requested`.
  5. `export`, then `rom` to see it boot.

  It points to the vendored pxl `SKILL.md` and `reference.md` for the DSL. Its rules cheat sheet is generated from
  `hw/*.py`, the same text `GET /code/binding` serves. It also carries NES/SNES craft habits: plan attribute areas on
  the 16 px grid; 3-color ramps per palette; mirror with sprite flips (sprites can flip, NES BG cannot); reuse tiles.
- **Web UI.** Out of M1-M3 (see §8 Q4).

### 3.6 Bringing in claude-pxl

What upstream is (read at commit `21fee41`): MIT, copyright 2026 crsolver, version 0.1.0. It has **two commits, both
on 2026-10-14**. The README installs it via `npx github:crsolver/claude-pxl`, and its `package.json` has a
`prepare` build step for git installs. It needs Node ≥ 22.18, which runs its TypeScript via type stripping. Its core
has no runtime dependencies (`src/core`, about 2.8k lines; about 4.2k with the Node glue and viewer). Node glue lives
in `src/node`. The tree is about 300 KB without its 2.9 MB `docs/gallery`.

| Option | License | Maintenance | Reproducibility / provenance | Cost | Verdict |
|---|---|---|---|---|---|
| **npm / git dependency** (`github:crsolver/claude-pxl#<sha>`) | MIT, fine | follows upstream, but upstream is 2 weeks old with an unstable API. A force-push or deletion breaks installs | the git SHA is exact, but needs network at install. `prepare` builds `dist/` at install time | smallest diff | no, for now |
| **Vendored pin** (`third_party/pxl/`, unmodified) | MIT: keep `LICENSE` and notice | upgrades are deliberate: re-vendor, run the suite, bump. Survives upstream churn or deletion | **exact:** `MANIFEST.sha256` tree hash goes into every provenance block. Offline CI | ~300 KB in tree | **yes** |
| **Port to Python** | MIT, fine | Retrogaze owns ~4k lines and drifts from upstream. The agent skill and docs would need rewriting | exact | large, and loses upstream fixes plus the live viewer | no |

**Decision: vendored pin, with zero local patches.**

- `third_party/pxl/` holds upstream `src/`, `bin/`, `types/`, `scripts/build.js`, `package.json`, `LICENSE`,
  `SKILL.md`, `reference.md` and `lighting.md` at `21fee41f7ecce00bc868d7567f24ffd0f3acc8fa`. It also holds
  `UPSTREAM.md` (commit, date, file list, upgrade procedure) and `MANIFEST.sha256`.
- `examples/`, `test/` and `docs/gallery/` are not vendored.
- All Retrogaze glue lives outside the folder (`codemode/js/rg-build.mjs`). If a change in pxl is ever needed, it goes
  upstream first (see §8 Q10).
- Revisit becoming a pinned npm dependency when upstream publishes ≥ 1.0 to npm.

**Node floor.** Code mode needs Node ≥ 22.18. Node 24 LTS is recommended, because Node 22 reaches end of life in
April 2027. The MCP server keeps its own floor (`mcp-server/package.json`: ≥ 18) for its existing tools.
`retro_code_*` tools report a clear error on older Node. CI's `python-tests` job (`.github/workflows/ci.yml`) gains an
`actions/setup-node` step. The Dockerfile (`python:3.12-slim`, no Node) only gains Node if Ray wants hosted code mode
(§8 Q4).

### 3.7 Sandbox and limits

pxl's loader runs art in `node:vm`, which Node documents as **not a security mechanism**. Code mode layers its own
limits:

1. **One process per build.** `node --permission` (stable since Node 22.13 / 23.5) with:
   - `--allow-fs-read` limited to `third_party/pxl` and `codemode/js`;
   - no `--allow-fs-write` (sources arrive on stdin, outputs leave on stdout);
   - no child processes, workers, addons or WASI;
   - network denied where that Node version's permission model gates it.
2. Time and memory limits: a `vm` `timeout` of 5 s for the definition phase, a 20 s wall-clock kill for the whole
   build (render-time functions can loop), `--max-old-space-size=512`, and output capped at 4 Mpx and 64 MiB of
   stdout.
3. Node's own docs say the permission model "does not protect against malicious code". **Any hosted deployment
   therefore also needs OS-level isolation** (container without network, read-only root, unprivileged user). Until then
   code mode is local-only by default (§8 Q4).

---

## 4. Exporters

Hardware binaries are produced **only when the legal tier passed**. A like-tier build gets PNG, sheet+JSON and the
report. Layout under the entry file's directory: `out/<console>/<tier>/…`. Every file is listed with its sha256 in
`manifest.json` (§1.4).

### 4.1 PNG

- `png/<asset>.png`: RGBA at 1×, with provenance `iTXt` and XMP. Anim frames are numbered `<asset>_<n>.png`.
- At the legal tier there is also `png/<scene>.screen.idx.png` (*M1:* per scene, since one asset can use several
  sprite palettes), an indexed PNG (mode `P`). Its `PLTE` is in hardware order:
  - NES: the 32-byte palette-RAM image, with index = `palette*4 + entry`.
  - SNES: CGRAM order.

  So YY-CHR, NEXXT or SuperFamiconv read identical indices.
- `_preview/`: pxl-style upscaled previews (not part of the manifest's hardware set).

### 4.2 Sprite sheet + JSON

- `sheets/<sheet>.png` + `.json` in pxl's TexturePacker-hash format (`src/core/render.ts:sheetJson`; `frames{}` plus
  `meta` with `frameTags`).
- Code mode adds `meta.retrogaze = { provenance, console, tier, verdict, hardware }`. Here `hardware` lists the cells
  of each frame: `{x, y, w, h, tile, palette, flip}`.
- **Every frame carries `duration`.** Stills default to 100 ms. All four existing engine builders read
  `frame["duration"]`, so without it they raise `KeyError` (`export_formats.py:49,108,173,237,242`). With it they
  accept code-mode JSON unchanged (test M1-29).

### 4.3 NES (legal tier)

| File | Bytes | Layout |
|---|---|---|
| `nes/<scene>.chr` | 8 KiB: pattern table `$0000` then `$1000` (a full NROM CHR-ROM), 16 bytes per tile | Plane 0 rows 0-7, then plane 1 rows 0-7. Bit 7 = leftmost pixel. Index = `p0 \| p1<<1`. BG table first, then the sprite table (split budget model, §8 Q5) |
| `nes/<scene>.pal` | 32 | `$3F00-$3F1F` image: `[bd, b0.1, b0.2, b0.3, bd, b1.1, …, bd, s0.1, s0.2, s0.3, bd, s1.1, …]`. `$3F10/14/18/1C` are written equal to `$3F00/04/08/0C` (mirrors), and unused entry-0 slots hold the backdrop. **No byte is ever `$0D`.** Black is `$0F`, white `$30`, unless pinned |
| `nes/<scene>.nam` | 1024 | 960 tile indices, row-major 32×30, then 64 attribute bytes `(BR<<6)\|(BL<<4)\|(TR<<2)\|TL`. Fields for non-existent rows 30-31 are 0 |
| `nes/<scene>.oam` | 256 | 64 × `[top−1, tile, attr, X]`, with `attr = pal \| prio<<5 \| H<<6 \| V<<7`. In 8×16 mode `tile = (top_tile & $FE) \| table`. Unused entries have `Y = $FF` |
| `nes/<scene>.ms.s` | text | metasprite tables, one per (asset, frame) placed in the scene: `x, y, tile, attr` per cell, terminated by `$80` (neslib-style; see §8 Q6) |
| `nes/<scene>.rom.json`, `nes/<scene>.ref.png` | text, PNG | *M1:* PPU settings for the viewer ROM, and the reference-PPU render of the bytes (what the console must show). *M1.1:* `rom.json` also says `"chr": "rom"` or `"ram"` (`chr: "chr-ram"` scenes), which picks the viewer cartridge (NROM or MMC1, §5.3) |
| `nes/<scene>.s`, `.h` | text | ca65 include (`.segment "RODATA"`, labels, `.incbin`) and a cc65 C header with `extern const unsigned char …[]`. *M1.1:* a `chr-ram` scene keeps the `.chr` in `RODATA` (the game uploads it), never in a CHR-ROM `CHARS` segment |

### 4.4 SNES (legal tier)

| File | Bytes | Layout |
|---|---|---|
| `snes/<scene>.bg1.4bpp` (`.bg2.4bpp`) | 32 per tile | Bytes 0-15: for row r, `[2r] = plane0`, `[2r+1] = plane1`. Bytes 16-31: `[16+2r] = plane2`, `[17+2r] = plane3`. Bit 7 = leftmost |
| `snes/<scene>.bg3.2bpp` | 16 per tile | as bytes 0-15 above (the same layout as Game Boy 2bpp) |
| `snes/<scene>.obj.4bpp` | 32 per tile | OBJ name tables laid out as the allocator placed them (16-column grid) |
| `snes/<scene>.bgN.map` | 2048 per 32×32 | little-endian words `VHPC CCTT TTTT TTTT` |
| `snes/<scene>.cgram` | 512 | 256 little-endian words `0bbbbbgggggrrrrr`, where `q = e⁻¹(channel)` (exact, because legal colors are canonical). BG palettes at 0-127, OBJ at 128-255. Per-palette 32-byte slices go in `snes/pal/` |
| `snes/<scene>.oam` | 544 | 128 × `[X low, Y, tile low, VHPPCCCt]`, then 32 bytes of 2-bit pairs (X bit 8, size). Unused sprites are parked off-screen, never at X = −256. The exact parking convention is pinned by the proof ROM |
| `snes/<scene>.vram.json` | text | allocator map: base addresses, sizes, register values (`BG1SC`, `BG12NBA`, `OBSEL`) |
| `snes/<scene>.s`, `.h` | text | ca65 include and C header (format per §8 Q6) |

### 4.5 Golden bytes (exact; the acceptance tests quote them)

- **NESdev "½" example tile**. Rows: `.1.....3` `11....3.` `.1...3..` `.1..3...` `...3.22.` `..3....2` `.3....2.`
  `3....222`.
  - NES CHR: `41 C2 44 48 10 20 40 80 01 02 04 08 16 21 42 87`. This matches the NESdev pattern-table page.
  - The same tile as SNES 4bpp: `41 01 C2 02 44 04 48 08 10 16 20 21 40 42 80 87` followed by 16 × `00`.
- **SNES 4bpp:** a tile whose only pixel is index 15 at (0, 0) has bytes 0, 1, 16 and 17 = `80`, and every other byte
  `00`.
- **NES attribute byte:** TL = 0, TR = 1, BL = 2, BR = 3 gives `E4`.
- **NES OAM:** a sprite at X = 120, top = 176, tile 5, palette 2, H-flip gives `AF 05 42 78`.
- **SNES CGRAM:**

  | Color | Word bytes |
  |---|---|
  | `#FF0000` | `1F 00` |
  | `#00FF00` | `E0 03` |
  | `#0000FF` | `00 7C` |
  | `#FFFFFF` | `FF 7F` |
  | `snes(16,8,4)` = `#834120` | `10 11` |

- **SNES tilemap word:** tile `$155`, palette 3, priority 1, H-flip gives `$6D55`, stored as `55 6D`.

---

## 5. Proof of legality: running, not asserting

### 5.1 What counts as proven

A scene is **proven legal** for a console when all four of these hold:

1. **(a)** The validator says `legal`.
2. **(b)** `ppu_ref.render(encode(scene))` equals the scene composite pixel-for-pixel.
3. **(c)** A viewer ROM built from the exported bytes boots in an emulator, and the emulator's memory (palette RAM or
   CGRAM, OAM, VRAM) equals the exported bytes.
4. **(d)** The emulator's screenshot matches the reference render under a **color bijection**. Each expected color maps
   to exactly one screen color, no two expected colors share one, and every pixel position agrees.

The bijection makes the comparison independent of the emulator's RGB palette. NES palettes differ between emulators,
and SNES 5→8-bit expansion differs too.

Gates (a) and (b) run in every unit-test run. Gates (c) and (d) run in the `codemode-proof` CI job, for every fixture
scene in `examples/codemode/` and `src/tests/fixtures/codemode/proof/`.

### 5.2 Tools (all free; none is a paid service)

| Tool | Role | License | Pin |
|---|---|---|---|
| **cc65** suite: `ca65` + `ld65` | assembles and links both ROMs (6502 for NES; 65816 via `.p816` for SNES) | zlib | exact version in `proof/TOOLS.md`; ROM sha256 goldens are per pinned toolchain |
| **Mesen 2** | NES + SNES emulator in headless `--testRunner` mode (*M1:* built from source at commit `b9fa69dd`, the archived 2.1.1; pinned by commit because its .NET bundle is not bit-reproducible; see `proof/TOOLS.md`). Lua: `emu.takeScreenshot()` (PNG string), `emu.read(addr, emu.memType.nesPaletteRam \| nesSpriteRam \| nesPpuMemory \| snesCgRam \| snesSpriteRam \| snesVideoRam)`, `emu.stop(exitCode)` sets the process exit code | GPL-3.0 (test tool only: not linked or shipped) | release version + sha256 in `proof/TOOLS.md`. The Linux build needs the .NET runtime and SDL2. Exact CLI flags (for example `--timeout`, IO access for Lua file writes) are pinned there and verified against that version |
| **SuperFamiconv** | independent oracle for the SNES 4bpp tile encoder (byte-compare on a fixture with pinned palette) | MIT | version + sha256 |
| Real hardware (optional) | NES / SNES plus a flash cart, CRT photo | — | manual sign-off checklist (§8 Q9) |

### 5.3 The viewer ROMs (also a product feature: `python -m retrogaze.codemode rom`)

**`proof/nes/viewer.s`** (ca65), NROM-128 (mapper 0): 16 KiB PRG, 8 KiB CHR-ROM = the exported `.chr` (BG table at
`$0000`, sprites at `$1000`). On reset it:

1. disables NMI and rendering, then waits two vblanks;
2. clears RAM and the OAM shadow page;
3. writes `.pal` to `$3F00` (32 bytes) and `.nam` to `$2000` (1024 bytes);
4. copies `.oam` to `$0200`;
5. sets PPUCTRL's sprite size from the manifest and enables NMI.

Each NMI then runs OAM DMA (`$4014 = $02`), sets scroll 0,0, and writes PPUMASK `$1E`. The data arrives by `.incbin`
of the exported files, so **the bytes on screen are the bytes Ray ships**.

*M1.1:* **`proof/nes/viewer_mmc1.s`** (ca65) is the same viewer on the cartridge of Ray's own NES project: MMC1
(mapper 1), 128 KiB PRG, no CHR-ROM, 8 KiB CHR-RAM, horizontal mirroring, PRG mode 3 (bank 7 fixed at `$C000`), NES 2.0
header. Every bank carries the MMC1 reset stub; reset sets MMC1 control `$0F`, maps PRG bank 0 (which holds the `.chr`) at
`$8000` and copies the `.chr` into CHR-RAM `$0000-$1FFF` before the steps above. A scene with `chr: "chr-ram"` gets it
automatically (`rom.json` `"chr": "ram"`); NROM stays the default. `examples/codemode/nes_mmc1.px.js` is the matching
example, and the proof job runs it next to the NROM scenes, plus 8x8 and 8x16 flip scenes (`nes_flips.px.js`).

**`proof/snes/viewer.s`** (ca65, 65816), LoROM. It:

1. switches to native mode and force-blanks (`INIDISP = $8F`);
2. DMAs `.4bpp` and `.map` to the VRAM addresses in `vram.json`, `.cgram` (512 B) through `$2122`, and `.oam` (544 B)
   through `$2104`;
3. sets `BGMODE = $01`, `BG1SC`, `BG12NBA` and `OBSEL` from `vram.json`, and `TM = $11` (BG1 + OBJ);
4. sets `INIDISP = $0F`, then loops.

**`proof/run_mesen.lua`** waits N frames (default 10). It then takes a screenshot and dumps palette RAM / CGRAM, OAM,
and the relevant PPU memory / VRAM ranges to the job directory, and calls `emu.stop(0)`. Any Lua error calls
`emu.stop(1)`.

**`proof/compare.py`** checks gate (c), the byte-exact dumps, and gate (d), the bijection screenshot match. It writes a
diff PNG on failure.

### 5.4 Negative fixtures: the emulator must agree with the validator's *failures*

The validator must also be right about what fails:

| Fixture | Validator says | ROM (built with `rom --force`) must show |
|---|---|---|
| `nes_9_on_a_line` | NES-H9 on lines y₀…y₁; sprite #8 dropped | screenshot differs from the reference **only** in sprite #8's pixels on y₀…y₁ |
| `snes_33_on_a_line` | SNES-H10; the OBJ named in the report is dropped | differs only in that OBJ's pixels on those lines |
| `snes_35_slivers` | SNES-H11 | differs only in the predicted slivers. This fixture also pins the partially-off-screen counting rule: one sprite straddles X = 0 |

Rules that cannot be expressed in bytes at all (for example 4 colors in a NES area) are covered differently: the
**encoder must refuse with the same rule ID** the validator gave.

### 5.5 CI

A new workflow job, `codemode-proof`, runs on `ubuntu-latest` for pushes and PRs that touch `src/retrogaze/codemode/`,
`proof/`, `third_party/pxl/` or `examples/codemode/`. It:

1. installs the pinned cc65, Mesen 2 and SuperFamiconv (checksum-verified);
2. builds every proof scene;
3. runs gates (a)-(d) and the negative fixtures;
4. uploads screenshots and diffs as artifacts.

A failure blocks the milestone. The existing `python-tests` job also runs gates (a) and (b) on every push.

---

## 6. Milestones

Every test below is written **first** and fails ("red") before its implementation exists. Fixtures mark the line they
expect blame on with `// expect: <RULE-ID>`. Rule fixture tests check that the reported rule matches **and** that the
blame `loc` points at that marked line.

### M1: NES console-legal, end to end

**Build order:**

1. Vendor pxl.
2. `rg-build.mjs` and the runner.
3. Binding.
4. Like rules.
5. Legal rules and solvers.
6. Encoders and `ppu_ref`.
7. Provenance.
8. CLI, API, MCP and skill.
9. Proof ROM.

| ID | Test (file::name) | Asserts |
|---|---|---|
| M1-01 | `test_codemode_vendor.py::test_vendored_pxl_matches_manifest` | every vendored file hashes to `MANIFEST.sha256`; `UPSTREAM.md` names commit `21fee41f7ecce00bc868d7567f24ffd0f3acc8fa`; `LICENSE` is present |
| M1-02 | `test_codemode_isolation.py::test_no_image_model_imports` | in a fresh subprocess, `import retrogaze.codemode` leaves none of `retrogaze.generate`, `retrogaze.pipeline`, `retrogaze.generate_aseprite`, `fal_client`, `anthropic`, `openai` in `sys.modules` |
| M1-03 | `test_codemode_isolation.py::test_build_with_network_disabled` | with `socket.socket` patched to raise, the NES example builds and passes; provenance `network_used == false` |
| M1-04 | `test_codemode_isolation.py::test_no_raster_inputs` | the CLI, API and MCP reject any non-`.px.js`/`.px.ts` file; the set of env globals equals a reviewed allowlist (a future upstream image-import op fails this until reviewed) |
| M1-05 | `test_codemode_binding.py::test_nes_colors` | `rg.colors` = the 54 unique hex of `_NES_PALETTE_HEX`; `nes(0x0F) == "#000000"`; `nes(0x30) == "#FFFFFF"`; `nes(0x0D)` → `CM-NES-0D` with loc; `nes(0x40)` raises |
| M1-06 | `test_codemode_binding.py::test_strict_wrappers[...]` | each of lighting / lamp / bump / normals / glow-without-ramp / `use("pico8")` / off-palette hex / `#ff000080` fails at definition with its `CM-STRICT-*` code and the right `file:line:col` |
| M1-07 | `test_codemode_determinism.py::test_byte_identical_rebuild` | two builds produce identical sha256 for every output; provenance is equal except `built_at` |
| M1-08 | `test_codemode_rules_nes.py::test_rule[NES-L1…NES-H14]` | for each failing rule, the pass fixture passes and the fail fixture yields exactly that rule (no other hard failure) with blame on the marked line. NES-H4 (normalization) and NES-H14 (warning) each get a fixture asserting their report entry instead |
| M1-09 | `test_codemode_rules_nes.py::test_bg_palette_packing` | 4 distinct area triples → pass with an assignment; 5 → NES-H6 with an unsat core of exactly those 5 areas; subset sets (`{a,b}` ⊆ `{a,b,c}`) share a palette; the backdrop choice turns a 4-color area legal |
| M1-10 | `test_codemode_rules_nes.py::test_scanline_limit` | 8 sprites on a line pass; 9 → NES-H9 naming OAM #8 and the line range; 8×16 mode counts 16 rows |
| M1-11 | `test_codemode_rules_nes.py::test_decomposition_offset_search` | a 16 px-wide figure drawn at x = 4..19 on a 24 px canvas decomposes into 2 cells wide, not 3, and the pixels are unchanged |
| M1-12 | `test_codemode_encode_nes.py::test_chr_golden_half_tile` | the NESdev ½ tile → `41 C2 44 48 10 20 40 80 01 02 04 08 16 21 42 87` |
| M1-13 | `test_codemode_encode_nes.py::test_nametable_and_attributes` | attribute byte golden `E4`; `.nam` is 1024 bytes; rows 30-31 fields are 0 |
| M1-14 | `test_codemode_encode_nes.py::test_palette_bytes` | 32 bytes; mirrors equal; black → `$0F`; **no `$0D` in any exported `.pal`** across all fixtures; pinned bytes are emitted verbatim |
| M1-15 | `test_codemode_encode_nes.py::test_oam_bytes` | golden `AF 05 42 78`; unused entries `Y = $FF`; 8×16 tile byte has the table bit |
| M1-16 | `test_codemode_roundtrip.py::test_nes_reference_render_matches` | for every legal fixture, `ppu_ref.render(encode(scene)) == composite`, exact. For every encodable-rule fail fixture, the encoder refuses with the validator's rule ID |
| M1-17 | `test_codemode_roundtrip.py::test_existing_engine_agrees_nes` | for every legal fixture PNG, `generate_metadata(..., console="nes")` reports `palette_valid`, `colors_per_tile_valid`, `grid_aligned` all true. For every legal BG fixture and every legal single-palette OBJ fixture, `enforce_constraints(..., console="nes")` also changes **zero** pixels. Multi-palette OBJ fixtures are excluded from the zero-change check because of engine finding 7 (§3.3) |
| M1-18 | `test_codemode_provenance.py::test_embedded_provenance` | PNG `iTXt retrogaze:provenance` validates against `provenance-1.json`; XMP `DigitalSourceType` = `algorithmicMedia`; sheet JSON `meta.retrogaze.provenance` is present; `manifest.json` lists every file |
| M1-19 | `test_codemode_provenance.py::test_verify` | `verify` exits 0; one flipped pixel → exits 1 naming the file; an edited source → exits 1; a changed binding hash → exits 4 |
| M1-20 | `test_codemode_provenance.py::test_audit` | `audit` passes a code-mode out dir and fails a dir that also contains a PNG from `test_sprites/` ("no code-mode provenance") |
| M1-21 | `test_codemode_cli.py::test_exit_codes` | 0 / 1 / 2 / 3 as specified in §3.5 |
| M1-22 | `test_codemode_routes.py::test_build_endpoint` | `/code/build` returns `provenance` (never stripped); 404 without `RETROGAZE_CODE_MODE=1`; 403 with `RETROGAZE_DEMO=1`; no `/v1/code/*` alias; `test_api_v1_allowlist.py` is unchanged and green |
| M1-23 | `test_codemode_sandbox.py::test_hostile_art[...]` | art that reaches for `process`, reads a file, loops forever, or allocates a 4096×4096 canvas fails with `CM-SANDBOX-*` within the timeout; the host process is unaffected |
| M1-24 | `mcp-server/test-e2e-codemode.sh` | `retro_code_bind`, `retro_code_build`, `retro_code_verify` are registered; building `examples/codemode/nes_hero.px.js` returns `verdict: legal` |
| M1-25 | `test_codemode_skill.py::test_cheatsheet_is_generated` | `SKILL.md`'s rules block equals `binding.render_cheatsheet("nes")` (no drift) |
| M1-26 | CI `codemode-proof` (`proof/compare.py`) | the NES proof scene (a code-drawn 16×16 hero from 4 sprites in 2 palettes, plus a code-drawn 16×16 metatile set covering a 256×240 BG in 4 palettes) builds to the golden ROM sha256; Mesen 2 exits 0; palette RAM == `.pal`; OAM == `.oam`; nametable == `.nam`; screenshot bijection-matches the reference |
| M1-27 | CI `codemode-proof` | `nes_9_on_a_line` differs only in the predicted sprite's pixels on the predicted lines (§5.4) |
| M1-28 | `pytest src/tests` + git check | the whole existing suite passes; collected count ≥ the `main` baseline (measured at `5276809`: **1465 passed, 6 skipped** with `RETROGAZE_MOCK=1 python -m pytest tests/ -q`, Python 3.13, `requirements-lock.txt`); `git diff --diff-filter=MD origin/main -- src/tests mcp-server/test-e2e.sh` is empty (no existing test modified or deleted); no new `skip`/`xfail` on existing tests |
| M1-29 | `test_codemode_exporters.py::test_engine_exporters_accept_sheet` | code-mode sheet JSON feeds `build_godot_tres`, `build_unity_anim`, `build_gamemaker_yy` and `build_unreal_sprite` without error; every frame has `duration` |

**Done when:**

```bash
python -m retrogaze.codemode build examples/codemode/nes_hero.px.js --console nes --tier legal
```

exits 0 and writes `out/nes/legal/{png,sheets,nes}/…`;

```bash
python -m retrogaze.codemode rom examples/codemode/nes_hero.px.js
```

produces an `.nes` file that boots in Mesen 2 showing the art; and M1-01…M1-29 are green.

### M2: SNES console-legal (Mode 1, 4bpp BG + OBJ)

| ID | Test | Asserts |
|---|---|---|
| M2-01 | `test_codemode_binding.py::test_snes_colors` | `snes(31,0,0) == "#FF0000"`; `snes(16,8,4) == "#834120"`; `pal({x:"#848484"})` → `CM-STRICT-COLOR` with hint `#838383 = snes(16,16,16)`; the active palette starts empty |
| M2-02 | `test_codemode_rules_snes.py::test_rule[SNES-L1…SNES-H15]` | pass/fail fixture per rule, with blame on the marked line |
| M2-03 | `test_codemode_encode_snes.py::test_4bpp_goldens` | ½ tile → `41 01 C2 02 44 04 48 08 10 16 20 21 40 42 80 87` + 16 × `00`; the index-15 pixel tile → bytes 0, 1, 16, 17 = `80` |
| M2-04 | `::test_cgram_goldens` | `1F 00`, `E0 03`, `00 7C`, `FF 7F`, `10 11` per §4.5; file is 512 bytes; OBJ palettes start at byte 256 |
| M2-05 | `::test_tilemap_word` | tile `$155`, palette 3, priority, H-flip → `55 6D` |
| M2-06 | `::test_oam_and_high_table` | 544 bytes; X = −1 → low `FF` + high bit 1; size bits match OBSEL; X = −256 → SNES-H4 |
| M2-07 | `test_codemode_rules_snes.py::test_obsel` | sizes {8, 16, 32} → SNES-H8 listing them; {8, 16} → OBSEL 0; a 16×32 OBJ fails unless `allowUndocumentedObjSizes`, which then gives OBSEL 6 or 7 |
| M2-08 | `::test_scanline_range_and_time` | 32 OBJs pass and 33 → SNES-H10; 34 slivers pass and 35 → SNES-H11; partially off-screen counting follows the rule pinned by M2-14 |
| M2-09 | `::test_obj_palette_is_per_object` | a 32×32 OBJ with 16 opaque colors → SNES-H3, even though every 8×8 tile has ≤ 15 |
| M2-10 | `test_codemode_vram.py::test_allocator` | fits → aligned map (BG CHR 8 KiB, maps 2 KiB, OBJ base 16 KiB); over budget → SNES-H14 with byte totals; 16×16 OBJ uses N, N+1, N+16, N+17 |
| M2-11 | `test_codemode_roundtrip.py::test_snes_reference_render_matches` | the M1-16 checks, for SNES |
| M2-12 | `test_codemode_roundtrip.py::test_existing_engine_agrees_snes` | for every legal fixture, `generate_metadata(..., console="snes")` reports `palette_valid` and `colors_per_tile_valid` true (no pixel-identity claim: the existing greedy allocator is not exact) |
| M2-13 | CI `codemode-proof` | the SNES proof scene (a code-drawn 32×32 hero OBJ plus a code-drawn 4bpp tile set on BG1, with ≥ 3 BG palettes and 2 OBJ palettes) builds; Mesen 2 exits 0; CGRAM == `.cgram`; OAM == `.oam`; VRAM ranges == exports; screenshot bijection-matches |
| M2-14 | CI `codemode-proof` | `snes_33_on_a_line` and `snes_35_slivers` behave as predicted (§5.4); the straddling sprite pins SNES-H11's edge rule, and M2-08 is updated to match **before** M2 closes |
| M2-15 | CI `codemode-proof` | SuperFamiconv's 4bpp tile output for the proof tile set equals `.bg1.4bpp` |
| M2-16 | as M1-28 | no regressions; no existing test modified |

**Done when:** `build … --console snes --tier legal` exits 0, `rom` produces an `.sfc` that boots in Mesen 2 showing
the art, and M2-01…M2-16 are green.

### M3: the other six systems at console-like

| ID | Test | Asserts |
|---|---|---|
| M3-01 | `test_codemode_binding.py::test_m3_bindings[gb_dmg, gb_pocket, gbc, genesis, c64_hires, c64_multicolor, pc_engine]` | each binding exposes exactly its profile's colors: fixed tables via `gb(shade)` and `c64(index)`, bit-depth canonical values via `gbc(r5,g5,b5)`, `md(r3,g3,b3)`, `pce(r3,g3,b3)` |
| M3-02 | `test_codemode_rules_m3.py::test_like_rules[console × L1…L4]` | pass/fail fixtures per console and rule, with blame |
| M3-03 | `::test_c64_multicolor_double_wide` | art authored at 160×200 logical exports as 320×200 with doubled columns; the validator checks the logical image |
| M3-04 | `test_codemode_cli.py::test_legal_unsupported` | `--tier legal` on each M3 console exits 2 with the "not yet specified" message, never 0 |
| M3-05 | `test_codemode_exporters.py::test_m3_png_and_sheet` | PNG + sheet+JSON with provenance for every M3 console; the engine exporters accept the sheets |
| M3-06 | `test_codemode_roundtrip.py::test_existing_engine_agrees_m3` | `generate_metadata` reports all compliance booleans true for every like fixture |
| M3-07 | as M1-28 | no regressions |

**Done when** all eight systems build at their supported tier from one CLI, MCP tool and skill.

---

## 7. Anti-goals

1. **No AI image generation in code mode.** No FLUX or fal call, no image model SDK, no raster input of any kind
   (upload, reference image, image-import op, base64 image), no "AI assist" pass over pixels. Checked by M1-02 to M1-04.
2. **No change to the existing FLUX or Aseprite modes.**
   - `generate.py`, `generate_aseprite.py` and `pipeline.py` keep their behavior.
   - The pixel-transforming engine stays the same: `enforce.py`, `tiles.py`, `palette.py`, `palette_alloc.py`,
     `grid.py`.
   - `ConsoleProfile` values, `metadata.py`, `/generate`, `/mcp/*`, `_STRIP_KEYS` and `_V1_ALLOWLIST` are unchanged.
   - Code mode only *calls* existing functions. The engine findings in §3.3 are left alone (§8 Q11).
3. **No new paid service dependency.** Everything runs offline on free tools: pxl (MIT), cc65 (zlib), Mesen 2 (GPL-3,
   test-only), SuperFamiconv (MIT), and SciPy (already a dependency). Code mode needs no fal key, no model-provider key
   and no account.
4. **Nothing that weakens existing tests.**
   - No existing test is modified, deleted, skipped or marked xfail.
   - The collected test count never drops below the `main` baseline (1465 passed, 6 skipped at `5276809`).
   - New Node-dependent tests run in CI, not behind silent skips.
5. **No silent pixel fixing in code mode.** No auto-remap, no dither-to-fit, no "closest legal" rewrite of rendered
   pixels (I3). Hints may suggest edits; the author makes them.
6. **No fork of pxl.** No local patches inside `third_party/pxl/`. Glue lives outside it.
7. **No security claims beyond the evidence.** Code mode is not presented as safe for running untrusted code on a public
   host until OS-level isolation exists (§3.7, §8 Q4).
8. **No mid-frame tricks in "legal"** (flicker, raster effects, bank switching) in M1-M3. "Legal" stays conservative.

---

## 8. Open questions only Ray can answer

Each question has a recommended answer. The build proceeds on the recommendation unless Ray says otherwise.

**Decided 2026-10-29:** Ray adopted every recommended answer below (Q1-Q11) and started M1.

| # | Question | Recommended answer |
|---|---|---|
| **Q1** | **Does LLM-written `.px.js` count as "art drawn as code" under the studio rule, or only human-written code?** | **Yes, it counts.** The rule is about AI *image* models. Provenance proves no image model touched the pixels, and `verify` proves the pixels come from the code. Record `source_author` anyway (`llm` / `human` / `mixed`) so the rule can tighten later without re-auditing. |
| **Q2** | **Are raster references allowed while authoring?** For example, an agent shown a FLUX image or a photo as reference while writing the code. | **No raster inputs to the tool, ever** (I1). Policy on what a person or agent *looks at* is Ray's. The recommendation: for paid-release art, the skill tells agents not to use AI-generated images as reference. |
| **Q3** | **How should non-code outputs be classified?** Do Aseprite-mode sprites (an LLM issuing drawing commands, no rebuildable source) count as code-drawn? Should FLUX and Aseprite outputs get their own provenance stamp so `audit` can classify them positively? | **Aseprite outputs do not count** (no source to verify). **Stamp the other modes later**, in a separate small PR after M1 (it touches existing modes, so it is out of scope here). Until then `audit` treats "no code-mode provenance" as "not cleared for paid release". |
| **Q4** | **Where may code mode run?** It executes user-supplied JS. | **Local first:** CLI, the local MCP server, and the API on localhost with `RETROGAZE_CODE_MODE=1`. **The public demo refuses it (403)** until it runs in an OS-isolated worker (no network, read-only, unprivileged). The web UI comes after M2. |
| **Q5** | **Which NES cartridge model is the default budget?** This sets NES-H11 and NES-H12. | **NROM, 8 KiB CHR-ROM, split 256 BG / 256 sprite tiles.** Allow a per-scene `chr: { model: "nrom-split" \| "shared" \| "chr-ram" }` override. If Ray's current NES project uses another mapper, that mapper becomes the example's default. *M1.1:* Ray's project is MMC1 + 8 KiB CHR-RAM; `examples/codemode/nes_mmc1.px.js` uses `chr: "chr-ram"` and boots on the MMC1 viewer (§5.3). NROM stays the spec default. |
| **Q6** | **Which homebrew toolchain should the include files target?** | **ca65 `.s` + cc65 `.h` on both consoles**, plus **neslib-style metasprites** for NES. Raw binaries always ship, so asm6, NESASM, WLA-DX or PVSnesLib users can `.incbin` them. Whatever toolchain Ray's projects use becomes the primary target. |
| **Q7** | **Allow the SNES's undocumented OBJ sizes (OBSEL 6-7: 16×32 / 32×64)?** | **Off by default.** Opt in per scene with `allowUndocumentedObjSizes`. The SNES development manual didn't document them. |
| **Q8** | **Should "legal" ever include sprite flicker or multiplexing**, to beat 8 per line (NES) or 32 / 34 (SNES)? | **No.** Legal = a stable single frame. A later, separate "legal-with-flicker" report can plan OAM cycling, but it is never the default verdict. |
| **Q9** | **Should each milestone have a real-hardware sign-off step?** For example a flash cart on a real NES / SNES, with a CRT photo in the release notes. | **Yes, if the hardware is on hand:** a manual checklist item at M1 and M2 closes. The emulator CI job stays the automatic gate. |
| **Q10** | **Upstream relationship with claude-pxl (crsolver)?** | **After M1 works, open one courteous upstream issue** describing the integration. Offer a "palette-lock / strict colors" hook upstream so the Retrogaze wrappers could shrink. Nothing in M1-M3 depends on upstream accepting it. Code mode stays on the vendored pin either way. |
| **Q11** | **Fix the existing engine's hardware inaccuracies** found in §3.3? (SNES 34 slivers = 272 px vs 256; NES / SNES per-tile caps counting 4 / 16 opaque; NES black reported as `$0D`; SNES OBJ sizes without the OBSEL rule; NES attribute reduction applied to sprites.) | **Yes, in a separate PR after M2.** Each fix gets its own new test. Any existing test that asserts the old value (for example `tests/test_palette.py:127-129` accepting `$0D`) is changed only with Ray's explicit OK. Code mode does not depend on these fixes. |

---

## Appendix A: Sources

**This repository (read at `5276809`):**

- `README.md`
- `src/retrogaze/console_profile.py`, `enforce.py`, `tiles.py`, `palette.py`, `palette_alloc.py`, `grid.py`,
  `validation.py`, `metadata.py`, `export_formats.py`, `generate_aseprite.py`, `pipeline.py`
- `api.py` (generation-mode wiring, `_STRIP_KEYS`, `_V1_ALLOWLIST`, router mounts), `mcp_routes.py`, `cli.py`
- `mcp-server/README.md`, `mcp-server/src/{index,tools}.ts`, `mcp-server/package.json`
- `.github/workflows/ci.yml`, `Dockerfile`, `src/requirements.txt`, `src/tests/` (in particular `test_palette.py`,
  `test_console_profile.py`)

**claude-pxl** (<https://github.com/crsolver/claude-pxl>, MIT), read at
`21fee41f7ecce00bc868d7567f24ffd0f3acc8fa`:

- `README.md`, `SKILL.md`, `reference.md`, `LICENSE`, `package.json`, `.github/workflows/ci.yml`
- `src/core/{palette,color,project,build,trace,image,glow,light,render,index}.ts`
- `src/node/{load,output,cli}.ts`

No upstream code is copied into this repository by this spec.

**NES hardware** (NESdev wiki):

- <https://www.nesdev.org/wiki/PPU_palettes>
- <https://www.nesdev.org/wiki/PPU_OAM>
- <https://www.nesdev.org/wiki/PPU_attribute_tables>
- <https://www.nesdev.org/wiki/PPU_pattern_tables>

**SNES hardware** (SNESdev wiki):

- <https://snes.nesdev.org/wiki/Backgrounds>
- <https://snes.nesdev.org/wiki/Sprites>
- <https://snes.nesdev.org/wiki/Tiles>
- <https://snes.nesdev.org/wiki/Palettes>
- <https://snes.nesdev.org/wiki/Tilemaps>
- <https://snes.nesdev.org/wiki/PPU_registers>

**Provenance vocabulary:** IPTC NewsCodes Digital Source Type, <https://cv.iptc.org/newscodes/digitalsourcetype/>
(`algorithmicMedia`, `trainedAlgorithmicMedia`).

**Tools:**

- Node.js permission model: <https://nodejs.org/api/permissions.html>
- Mesen 2 Lua API (`UI/Debugger/Documentation/LuaDocumentation.json` in <https://github.com/SourMesen/Mesen2>:
  `takeScreenshot`, `getScreenBuffer`, memory types, `stop`)
- SuperFamiconv: <https://github.com/Optiroc/SuperFamiconv> (MIT)
- cc65: <https://cc65.github.io/>

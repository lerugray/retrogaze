"""
Rule registry: the single source for rule IDs, tiers, scopes and wording.

The §2 tables of docs/spec/CODE-MODE-SPEC.md, the agent-skill cheat sheet, the
``GET /code/binding`` text and the MCP tool help are all rendered from here.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rule:
    id: str
    tier: str          # "like" | "legal"
    scope: str         # "image" | "scene"
    text: str
    limit: str = "—"
    kind: str = "check"  # "check" | "normalization" | "warning"


NES_RULES: tuple[Rule, ...] = (
    Rule("NES-L1", "like", "image", "Every opaque pixel is one of the 54 NES colors (exact RGB).", "54 colors"),
    Rule("NES-L2", "like", "image",
         "Grid: BG images are multiples of 8 (never padded); OBJ images are padded with transparent pixels "
         "on the right and bottom to multiples of 8 (reported, no drawn pixel moves).", "8 px"),
    Rule("NES-L3", "like", "image", "At most 4 opaque colors per 8x8 tile.", "4"),
    Rule("NES-L4", "like", "image", "Alpha is binary: every pixel is fully opaque or fully transparent."),
    Rule("NES-H1", "legal", "image", "Every color encodes to a 2C02 byte; $0D is never emitted or accepted."),
    Rule("NES-H2", "legal", "image",
         "BG: each 16x16 attribute area uses at most 3 colors besides the scene backdrop "
         "(transparent BG pixels are backdrop).", "3 + backdrop"),
    Rule("NES-H3", "legal", "image", "OBJ: each hardware sprite cell uses at most 3 opaque colors (+ transparent).", "3"),
    Rule("NES-H4", "legal", "image",
         "OBJ: cells are 8x8, or 8x16 in 8x16 mode; the decomposition covers the asset with whole cells "
         "(normalization, never fails).", kind="normalization"),
    Rule("NES-H5", "legal", "scene",
         "One backdrop color per scene ($3F00); if not declared, the solver picks one that makes NES-H6 feasible.", "1"),
    Rule("NES-H6", "legal", "scene", "BG area color sets pack into at most 4 palettes of 3 colors (+ shared backdrop).", "4 x 3"),
    Rule("NES-H7", "legal", "scene", "OBJ cell color sets pack into at most 4 sprite palettes of 3 colors.", "4 x 3"),
    Rule("NES-H8", "legal", "scene", "At most 64 hardware sprites in the frame.", "64"),
    Rule("NES-H9", "legal", "scene", "At most 8 hardware sprites on any scanline (the PPU drops the rest).", "8"),
    Rule("NES-H10", "legal", "scene", "One sprite size for the whole frame: all 8x8 or all 8x16.", "1 mode"),
    Rule("NES-H11", "legal", "scene", "Unique BG tiles fit the BG pattern table (exact match, no flips).", "256"),
    Rule("NES-H12", "legal", "scene", "Unique OBJ tiles fit the sprite pattern table (dedup with H/V flips).", "256"),
    Rule("NES-H13", "legal", "scene",
         "Screen: BG fits 256x240 (one nametable); OBJ X in [0, 255] and top row in [1, 239].", "256 x 240"),
    Rule("NES-H14", "legal", "scene", "Content in the left 8 px is hidden when the scene clips the left column.",
         kind="warning"),
)

SNES_RULES: tuple[Rule, ...] = (
    Rule("SNES-L1", "like", "image",
         "Every opaque channel value is a canonical 5-bit level e(q) = (q * 255) // 31 (15-bit BGR).", "32 768 colors"),
    Rule("SNES-L2", "like", "image",
         "Grid: BG images are multiples of 8 (never padded); OBJ images are padded with transparent pixels "
         "on the right and bottom to multiples of 8 (reported, no drawn pixel moves).", "8 px"),
    Rule("SNES-L3", "like", "image", "At most 16 opaque colors per 8x8 tile.", "16"),
    Rule("SNES-L4", "like", "image", "Alpha is binary: every pixel is fully opaque or fully transparent."),
    Rule("SNES-H1", "legal", "image",
         "BG: each 8x8 tile of a 4bpp layer (BG1, BG2) uses at most 15 opaque colors, of the 2bpp BG3 at most 3 "
         "(pixel value 0 is transparent).", "15 / 3"),
    Rule("SNES-H2", "legal", "image",
         "OBJ: the asset decomposes into OBJs of real OBJ sizes (8x8, 16x16, 32x32, 64x64; 16x32 and 32x64 are "
         "undocumented); there is no 8x16 OBJ."),
    Rule("SNES-H3", "legal", "image",
         "OBJ: each OBJ as a whole (8x8 up to 64x64) uses at most 15 opaque colors: one palette per OBJ.", "15"),
    Rule("SNES-H4", "legal", "image",
         "OBJ: X in [-255, 255] and never -256 (counted on every line it covers); Y is 8-bit and an OBJ's rows "
         "stay in 0-255 (taller spans wrap to the top of the screen).", "9-bit X, 8-bit Y"),
    Rule("SNES-H5", "legal", "scene",
         "One backdrop color (CGRAM 0); opaque pixels in the backdrop color still take a palette slot.", "1"),
    Rule("SNES-H6", "legal", "scene",
         "4bpp BG tile color sets (BG1 and BG2 share CGRAM 0-127) pack into 8 palettes of 15; BG3's 8 palettes "
         "of 3 sit inside CGRAM 0-31 and are packed jointly with them.", "8 x 15"),
    Rule("SNES-H7", "legal", "scene", "OBJ color sets pack into 8 palettes of 15 (CGRAM 128-255).", "8 x 15"),
    Rule("SNES-H8", "legal", "scene",
         "Every OBJ size in the frame belongs to one OBSEL pair (0-5; 6-7 only with allowUndocumentedObjSizes).",
         "1 pair"),
    Rule("SNES-H9", "legal", "scene", "At most 128 OBJs in the frame.", "128"),
    Rule("SNES-H10", "legal", "scene",
         "At most 32 OBJs on any line (range); the PPU keeps the first 32 in OAM order.", "32"),
    Rule("SNES-H11", "legal", "scene",
         "At most 34 8-px slivers on any line (time); only tiles that reach the screen count; slivers are "
         "fetched from the highest OAM index down, so the frontmost OBJs lose theirs.", "34"),
    Rule("SNES-H12", "legal", "scene",
         "Unique BG tiles per layer fit its 10-bit tile numbers (dedup with H/V flips; the palette is per map "
         "entry).", "1024"),
    Rule("SNES-H13", "legal", "scene",
         "OBJ tiles fit the two 256-tile OBJ name tables; each large OBJ is a block on the 16-column grid.", "2 x 256"),
    Rule("SNES-H14", "legal", "scene",
         "VRAM layout fits 64 KiB: BG CHR on 8 KiB, tilemaps on 2 KiB, the OBJ base on 16 KiB boundaries.",
         "65 536 bytes"),
    Rule("SNES-H15", "legal", "scene",
         "Screen 256x224, BG mode 1, one 32x32 tilemap per BG layer (BG images at most 256x256).", "mode 1"),
)

# Errors raised while an art file is defined or rendered (exit code 3).
BUILD_CODES: dict[str, str] = {
    "CM-STRICT-LIGHTING": "lighting/lamp/bump/normals multiply RGB and leave the palette",
    "CM-STRICT-GLOW": "glow() colour mode leaves the palette; use glow(keys, { ramp: n })",
    "CM-STRICT-ALPHA": "partial alpha has no hardware meaning",
    "CM-STRICT-COLOR": "a hex color that is not a console color",
    "CM-STRICT-USE": "built-in pxl palettes are not console colors",
    "CM-NES-0D": "nes(0x0D) is forbidden ('blacker than black')",
    "CM-NES-RANGE": "nes() takes a byte 0x00-0x3F",
    "CM-SNES-RANGE": "snes() takes three integers 0-31; bgr555() a word 0x0000-0x7FFF",
    "CM-DETERMINISM": "Math.random/Date are disabled so builds are reproducible",
    "CM-SCENE": "malformed rg.scene / rg.tileset",
    "CM-INCLUDE": "include() outside the submitted art files",
    "CM-SANDBOX-TIMEOUT": "the build ran past its time limit",
    "CM-SANDBOX-SIZE": "rendered output is larger than allowed",
    "CM-SANDBOX-EXIT": "the build process died or wrote no result",
    "CM-INPUT": "the submitted files are not acceptable (raster input, size, names)",
    "CM-BUILD": "pxl reported an error",
    "CM-ROUNDTRIP": "internal: the rules and the encoder/reference PPU disagree (a code-mode bug; please report it)",
}

RULES_BY_ID: dict[str, Rule] = {r.id: r for r in NES_RULES + SNES_RULES}


def rules_for(console: str) -> tuple[Rule, ...]:
    if console == "nes":
        return NES_RULES
    if console == "snes":
        return SNES_RULES
    raise KeyError(console)

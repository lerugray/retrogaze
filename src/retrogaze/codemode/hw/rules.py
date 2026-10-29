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

# Errors raised while an art file is defined or rendered (exit code 3).
BUILD_CODES: dict[str, str] = {
    "CM-STRICT-LIGHTING": "lighting/lamp/bump/normals multiply RGB and leave the palette",
    "CM-STRICT-GLOW": "glow() colour mode leaves the palette; use glow(keys, { ramp: n })",
    "CM-STRICT-ALPHA": "partial alpha has no hardware meaning",
    "CM-STRICT-COLOR": "a hex color that is not a console color",
    "CM-STRICT-USE": "built-in pxl palettes are not console colors",
    "CM-NES-0D": "nes(0x0D) is forbidden ('blacker than black')",
    "CM-NES-RANGE": "nes() takes a byte 0x00-0x3F",
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

RULES_BY_ID: dict[str, Rule] = {r.id: r for r in NES_RULES}


def rules_for(console: str) -> tuple[Rule, ...]:
    if console == "nes":
        return NES_RULES
    raise KeyError(console)

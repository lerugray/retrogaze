"""M2-02, M2-07..09: every SNES rule fires exactly when it should, with blame on the source line that caused it;
OBSEL pairs, per-line range and time limits, one palette per OBJ, and the joint BG3 / 4bpp palette packing."""

import pytest

from retrogaze.codemode.hw.rules import SNES_RULES
from retrogaze.codemode.hw.snes import on_screen_slivers

from ._codemode_snes import (
    FIXTURES, blame_lines, build_file, build_source, error_rules, expectations, scene, violations,
)

FAIL_FIXTURES = sorted(FIXTURES.glob("snes_*_fail.px.js"))
PASS_FIXTURES = sorted(FIXTURES.glob("snes_*_pass.px.js"))
CHECK_RULES = [r.id for r in SNES_RULES if r.kind == "check"]


def test_every_snes_rule_has_a_fixture_pair():
    covered = {p.name.split("_")[1] for p in FAIL_FIXTURES}
    passing = {p.name.split("_")[1] for p in PASS_FIXTURES}
    assert len(CHECK_RULES) == 19
    for rule in CHECK_RULES:
        short = rule.split("-")[1]
        assert short in covered, f"no fail fixture for {rule}"
        assert short in passing, f"no pass fixture for {rule}"


@pytest.mark.parametrize("path", FAIL_FIXTURES, ids=lambda p: p.stem)
def test_rule_fail_fixture(path):
    (line, rule), = expectations(path)
    r = build_file(str(path))
    assert r.exit_code == 1
    assert error_rules(r.report) == {rule}, violations(r.report)
    hits = [v for v in violations(r.report) if v["rule"] == rule]
    assert hits and any(line in blame_lines(v) for v in hits), [v.get("blame") for v in hits]


@pytest.mark.parametrize("path", PASS_FIXTURES, ids=lambda p: p.stem)
def test_rule_pass_fixture(path):
    r = build_file(str(path))
    assert r.exit_code == 0, violations(r.report)
    assert r.verdict == "legal"
    assert not [v for v in violations(r.report) if v["severity"] == "error"]


def test_obj_padding_is_reported():
    r = build_file(str(FIXTURES / "snes_L2_pass.px.js"))
    assert {"rule": "SNES-L2", "asset": "odd", "padded": [[10, 10], [16, 16]]} in r.report["info"]


BASE = 'pal({ r: snes(31, 8, 0) })\nsprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "r"))\n'


def test_obsel():
    """M2-07: OBJ sizes must belong to one OBSEL pair; 16x32 / 32x64 only with allowUndocumentedObjSizes (§8 Q7)."""
    three = build_source(BASE + 'rg.scene("x", { obj: [["s", 16, 16, { size: "8x8" }], '
                                '["s", 48, 16, { size: "16x16" }], ["s", 96, 16, { size: "32x32" }]] })')
    h8 = [v for v in violations(three.report) if v["rule"] == "SNES-H8"]
    assert h8 and set(h8[0]["found"]) == {"8x8", "16x16", "32x32"}
    assert error_rules(three.report) == {"SNES-H8"}

    two = build_source(BASE + 'rg.scene("x", { obj: [["s", 16, 16, { size: "8x8" }], ["s", 48, 16, { size: "16x16" }]] })')
    assert two.verdict == "legal" and scene(two, "x").obsel == 0
    assert two.report["scenes"][0]["obsel"] == 0

    tall = BASE + 'rg.scene("x", { obj: [["s", 16, 16, { size: "16x32" }]]%s })'
    assert error_rules(build_source(tall % "").report) == {"SNES-H8"}
    ok = build_source(tall % ", allowUndocumentedObjSizes: true")
    assert ok.verdict == "legal" and scene(ok, "x").obsel in (6, 7)

    pinned = build_source(BASE + 'rg.scene("x", { obj: [["s", 16, 16, { size: "32x32" }]], obsel: 0 })')
    assert error_rules(pinned.report) == {"SNES-H8"}
    assert error_rules(build_source(BASE + 'rg.scene("x", { obj: [["s", 1, 1]], obsel: 6 })').report) == {"SNES-H8"}

    # Without sizes the decomposer picks the cheapest pair: a 32x32 sprite is one 32x32 OBJ.
    big = build_source('pal({ r: snes(31, 8, 0) })\nsprite("b", { w: 32, h: 32 }, rect(0, 0, 32, 32, "r"))\n'
                       'rg.scene("x", { obj: [["b", 40, 40]] })')
    m = scene(big, "x")
    assert [(o.w, o.h) for o in m.oam[0]] == [(32, 32)] and m.obsel == 1


def _line(n, w=8, step=7, y=100):
    size = f"{w}x{w}"
    return (f'pal({{ r: snes(31, 8, 0) }})\nsprite("s", {{ w: {w}, h: {w} }}, rect(0, 0, {w}, {w}, "r"))\n'
            f'const obj = []\nfor (let i = 0; i < {n}; i++) obj.push(["s", 2 + i * {step}, {y}, {{ size: "{size}" }}])\n'
            f'rg.scene("x", {{ obj }})\n')


def test_scanline_range_and_time():
    """M2-08: 32 OBJs on a line pass, 33 lose the highest OAM index; 34 slivers pass, 35 lose the last fetched one."""
    assert build_source(_line(32)).verdict == "legal"
    r = build_source(_line(33))
    assert error_rules(r.report) == {"SNES-H10"}
    h10 = [v for v in violations(r.report) if v["rule"] == "SNES-H10"]
    assert h10[0]["where"]["oam"] == [32] and h10[0]["where"]["lines"] == [100, 107] and h10[0]["found"] == 33

    assert build_source(_line(17, w=16, step=14)).verdict == "legal"          # 34 slivers
    r = build_source(_line(18, w=16, step=13))                                 # 36 slivers
    assert error_rules(r.report) == {"SNES-H11"}
    h11 = [v for v in violations(r.report) if v["rule"] == "SNES-H11"]
    assert h11[0]["found"] == 36 and h11[0]["limit"] == 34
    # Fetched from the highest OAM index down: OAM #0 (the last painted) loses both of its slivers.
    assert h11[0]["where"]["dropped"] == [[0, 0], [0, 1]]

    # Partially off-screen OBJs (pinned by the emulator proof, M2-14): only tiles that reach the screen count.
    assert on_screen_slivers(-12, 16) == 1
    assert on_screen_slivers(-4, 16) == 2
    assert on_screen_slivers(250, 16) == 1
    assert on_screen_slivers(248, 16) == 1
    assert on_screen_slivers(-16, 16) == 0
    assert on_screen_slivers(-60, 64) == 1
    edge = build_file(str(FIXTURES / "snes_H11_pass.px.js"))
    assert edge.verdict == "legal" and edge.report["scenes"][0]["budgets"]["slivers"]["used"] == 34
    over = build_file(str(FIXTURES / "snes_H11_fail.px.js"))
    h11 = [v for v in violations(over.report) if v["rule"] == "SNES-H11"]
    assert h11[0]["found"] == 35 and h11[0]["where"]["dropped"] == [[0, 1]]


def test_obj_palette_is_per_object():
    """M2-09: a 32x32 OBJ with 16 colors fails SNES-H3 although every 8x8 tile has at most 15."""
    path = FIXTURES / "snes_H3_fail.px.js"
    r = build_file(str(path))
    assert error_rules(r.report) == {"SNES-H3"}
    h3 = [v for v in violations(r.report) if v["rule"] == "SNES-H3"][0]
    assert h3["found"] == 16 and h3["limit"] == 15
    assert build_file(str(path), tier="like").verdict == "like"            # SNES-L3 (16 per tile) passes


def _bg(tiles, z=7):
    return (f"(c) => {{ for (let t = 0; t < {tiles}; t++) for (let i = 0; i < 15; i++) "
            f"c.px(t * 8 + (i % 8), i >> 3, snes(t * 3 + 1, i * 2 + 1, {z})) }}")


@pytest.mark.parametrize("bg_tiles, hud, legal", [
    (8, "snes(1, 1, 7), snes(1, 3, 7), snes(1, 5, 7)", True),       # BG3 shares 3 of BG1 palette 0's colors
    (8, "snes(30, 30, 30), snes(0, 0, 31), snes(31, 0, 0)", False),  # BG3 needs slots that BG1 fills
    (7, "snes(30, 30, 30), snes(0, 0, 31), snes(31, 0, 0)", True),   # 7 BG1 palettes leave room in CGRAM 0-31
])
def test_bg3_packs_jointly_with_4bpp(bg_tiles, hud, legal):
    """SNES-H6: BG3's 2bpp palettes live in CGRAM 0-31, inside 4bpp palettes 0-1, and are packed with them."""
    src = (f'scene("bg", {{ w: 256, h: 224 }}, {_bg(bg_tiles)})\n'
           f'scene("hud", {{ w: 256, h: 224 }}, (c) => {{ const k = [{hud}]; for (let i = 0; i < 3; i++) c.px(i, 100, k[i]) }})\n'
           'rg.scene("x", { bg1: "bg", bg3: "hud" })\n')
    r = build_source(src)
    if not legal:
        assert error_rules(r.report) == {"SNES-H6"}
        return
    assert r.verdict == "legal", violations(r.report)
    m = scene(r, "x")
    q = m.bg3_palette_of_tile(0, 100 // 8, 0)
    assert 0 <= q <= 7
    shared = m.bg_slots[q // 4][4 * (q % 4):4 * (q % 4) + 3]
    hud_colors = set(m.layer_tile_colors("bg3", 0, 100 // 8, 0))
    assert hud_colors <= {c for c in shared if c is not None}

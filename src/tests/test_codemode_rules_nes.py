"""M1-08..11: every NES rule fires exactly when it should, with blame on the source line that caused it."""

import pytest

from retrogaze.codemode.hw.common import pack_palettes, unsat_core
from retrogaze.codemode.hw.rules import NES_RULES

from ._codemode import FIXTURES, blame_lines, build_file, build_source, error_rules, expectations, violations

FAIL_FIXTURES = sorted(p for p in FIXTURES.glob("nes_*_fail.px.js"))
PASS_FIXTURES = sorted(p for p in FIXTURES.glob("nes_*_pass.px.js"))
CHECK_RULES = [r.id for r in NES_RULES if r.kind == "check"]


def test_every_failing_rule_has_a_fixture_pair():
    covered = {p.name.split("_")[1] for p in FAIL_FIXTURES}
    passing = {p.name.split("_")[1] for p in PASS_FIXTURES}
    for rule in CHECK_RULES:
        short = rule.split("-")[1]
        assert short in covered, f"no fail fixture for {rule}"
        assert short in passing, f"no pass fixture for {rule}"


@pytest.mark.parametrize("path", FAIL_FIXTURES, ids=lambda p: p.stem)
def test_rule_fail_fixture(path):
    (line, rule), = expectations(path)
    r = build_file(str(path))
    assert r.exit_code == 1
    assert error_rules(r.report) == {rule}
    hits = [v for v in violations(r.report) if v["rule"] == rule]
    assert hits and any(line in blame_lines(v) for v in hits), [v.get("blame") for v in hits]


@pytest.mark.parametrize("path", PASS_FIXTURES, ids=lambda p: p.stem)
def test_rule_pass_fixture(path):
    r = build_file(str(path))
    assert r.exit_code == 0, violations(r.report)
    assert r.verdict == "legal"
    assert not [v for v in violations(r.report) if v["severity"] == "error"]


def test_warning_fixture():
    path = FIXTURES / "nes_H14_warn.px.js"
    (line, rule), = expectations(path)
    r = build_file(str(path))
    assert r.exit_code == 0 and r.verdict == "legal"
    warns = [v for v in violations(r.report) if v["rule"] == rule]
    assert warns and warns[0]["severity"] == "warning" and line in blame_lines(warns[0])


def test_normalization_fixture_8x16_and_padding():
    r = build_file(str(FIXTURES / "nes_H4_info.px.js"))
    assert r.verdict == "legal"
    assert {"rule": "NES-L2", "asset": "odd", "padded": [[10, 10], [16, 16]]} in r.report["info"]
    scene = next(s for s in r.report["scenes"] if s["name"] == "tall")
    assert scene["sprite_size"] == "8x16"
    assert scene["budgets"]["oam"]["used"] == 3          # 8x8 -> one 8x16 sprite; 10x10 -> two
    m = next(m for m in r.models if m.name == "tall")
    assert {c.h for c in m.oam[0]} == {16}


def test_grid_row_blame_points_at_the_row():
    src = (
        'pal({ a: nes(0x16), b: nes(0x27), c: nes(0x12), d: nes(0x30) })\n'
        'sprite("g", `\n'
        '  aaaaaaaa\n'
        '  bbbbbbbb\n'
        '  cccccccc\n'
        '  aaaaaaad\n'      # line 6: the 4th color of the cell
        '  bbbbbbbb\n'
        '  cccccccc\n'
        '  aaaaaaaa\n'
        '  bbbbbbbb`)\n'
    )
    r = build_source(src)
    hits = [v for v in violations(r.report) if v["rule"] == "NES-H3"]
    assert hits and blame_lines(hits[0]) == {6}
    assert hits[0]["blame"][0]["op"] == "grid row 3"


def test_bg_palette_packing():
    t = [frozenset({1, 2, 3}), frozenset({4, 5, 6}), frozenset({7, 8, 9}), frozenset({10, 11, 12})]
    assert pack_palettes(t, 4, 3) is not None
    five = t + [frozenset({13, 14, 15})]
    assert pack_palettes(five, 4, 3) is None
    assert unsat_core(five, 4, 3) == [0, 1, 2, 3, 4]
    shared = t + [frozenset({1, 2}), frozenset({4})]
    assert len(pack_palettes(shared, 4, 3)) == 4
    # Two-color sets can pair up: 8 of them fit 4 palettes of 3? No: {a,b},{c,d} need 4 colors.
    pairs = [frozenset({2 * i, 2 * i + 1}) for i in range(5)]
    assert pack_palettes(pairs, 4, 3) is None
    # The MILP fallback agrees with backtracking.
    assert pack_palettes(t, 4, 3, node_budget=0) is not None
    assert pack_palettes(five, 4, 3, node_budget=0) is None


def test_backdrop_choice_makes_a_four_color_area_legal():
    r = build_file(str(FIXTURES / "nes_H2_pass.px.js"))
    assert r.verdict == "legal"
    scene = r.report["scenes"][0]
    # Area (0,0) holds 4 colors; it is legal only because one of them becomes the shared backdrop.
    assert scene["backdrop"] in ("$01", "$02")


def test_scanline_limit_names_the_dropped_sprite():
    r = build_file(str(FIXTURES / "nes_H9_fail.px.js"))
    (v,) = [v for v in violations(r.report) if v["rule"] == "NES-H9"]
    assert v["where"]["oam"] == 8 and v["where"]["lines"] == [100, 107]
    assert v["found"] == 9 and v["limit"] == 8
    src = (FIXTURES / "nes_H9_fail.px.js").read_text().replace(
        'rect(0, 0, 8, 8, "1")', 'rect(0, 0, 8, 16, "1")').replace('{ w: 8, h: 8 }', '{ w: 8, h: 16 }').replace(
        'rg.scene("line", { obj })', 'rg.scene("line", { obj, objSize: "8x16" })')
    r16 = build_source(src)
    (v16,) = [v for v in violations(r16.report) if v["rule"] == "NES-H9"]
    assert v16["where"]["lines"] == [100, 115]


def test_decomposition_offset_search():
    r = build_source('sprite("a", { w: 24, h: 8 }, rect(4, 0, 16, 8, "1"))')
    assert r.verdict == "legal"
    (scene,) = r.report["scenes"]
    assert scene["budgets"]["oam"]["used"] == 2           # an origin-aligned grid would need 3
    import io

    import numpy as np
    from PIL import Image
    img = np.array(Image.open(io.BytesIO(r.outputs["png/a.png"])).convert("RGBA"))
    assert img.shape == (8, 24, 4)
    assert (img[:, 4:20, 3] == 255).all() and (img[:, :4, 3] == 0).all() and (img[:, 20:, 3] == 0).all()


def test_layered_sprites_allow_overlapping_palettes():
    src = (
        'pal({ a: nes(0x16), b: nes(0x27), c: nes(0x30), d: nes(0x12), e: nes(0x21), f: nes(0x0F) })\n'
        'sprite("hero", { w: 8, h: 8 },\n'
        '  layer("obj:0", rect(0, 0, 8, 8, "a"), rect(0, 4, 8, 4, "b"), px(1, 1, "c")),\n'
        '  layer("obj:1", px(3, 3, "d"), px(4, 3, "e"), px(5, 5, "f")))\n'
    )
    r = build_source(src)
    assert r.verdict == "legal", violations(r.report)
    (scene,) = r.report["scenes"]
    assert scene["budgets"]["oam"]["used"] == 2           # two overlapping hardware sprites, 6 colors in one 8x8

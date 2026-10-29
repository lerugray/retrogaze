"""M1-05..06: the NES binding hands the drawer only console colors, and strict mode fails fast with a location."""

import pytest

from retrogaze.codemode.binding import NES_COLORS, binding_for, nes_byte_hex, render_cheatsheet
from retrogaze.codemode.hw.rules import NES_RULES
from retrogaze.codemode.runner import CodeModeError, run_loader
from retrogaze.palette import _NES_PALETTE_HEX


def run(src):
    return run_loader({"t.px.js": src}, "t.px.js", binding_for("nes", "legal"))


def test_nes_colors():
    b = binding_for("nes", "legal")
    assert len(NES_COLORS) == 54
    assert b["colors"] == list(dict.fromkeys(h.upper() for h in _NES_PALETTE_HEX))
    raw = run('console.log(nes(0x0F), nes(0x30), nes(0x20), nes(0x1D), nes(0x3E), nes(0x16))')
    assert raw.logs == ["#000000 #FFFFFF #FFFFFF #000000 #000000 #913800"]
    assert nes_byte_hex(0x16) == "#913800"


@pytest.mark.parametrize("src, code", [
    ("// line 1\nnes(0x0D)\n", "CM-NES-0D"),
    ("// line 1\nnes(0x40)\n", "CM-NES-RANGE"),
    ("// line 1\nnes(-1)\n", "CM-NES-RANGE"),
])
def test_nes_bad_bytes(src, code):
    with pytest.raises(CodeModeError) as e:
        run(src)
    assert e.value.code == code
    assert e.value.loc.startswith("t.px.js:2:")


@pytest.mark.parametrize("line, code", [
    ("lighting()", "CM-STRICT-LIGHTING"),
    ('sprite("a", { w: 8, h: 8 }, lamp(1, 1))', "CM-STRICT-LIGHTING"),
    ('sprite("a", { w: 8, h: 8 }, bump("dome", {}))', "CM-STRICT-LIGHTING"),
    ('sprite("a", { w: 8, h: 8 }, normals(0, 0, "5"))', "CM-STRICT-LIGHTING"),
    ('glow("k")', "CM-STRICT-GLOW"),
    ('use("pico8")', "CM-STRICT-USE"),
    ('pal({ z: "#123456" })', "CM-STRICT-COLOR"),
    ('sprite("a", rect(0, 0, 8, 8, "#123456"))', "CM-STRICT-COLOR"),
    ('sprite("a", { w: 8, h: 8, swap: { "1": "#123456" } })', "CM-STRICT-COLOR"),
    ('sprite("a", rect(0, 0, 8, 8, "#ff000080"))', "CM-STRICT-ALPHA"),
    ("Math.random()", "CM-DETERMINISM"),
    ("Date.now()", "CM-DETERMINISM"),
    ("new Date()", "CM-DETERMINISM"),
])
def test_strict_wrappers(line, code):
    with pytest.raises(CodeModeError) as e:
        run(f"// line 1\n// line 2\n{line}\n")
    assert e.value.code == code
    assert e.value.loc is not None and e.value.loc.split(":")[:2] == ["t.px.js", "3"]


def test_glow_ramp_mode_is_allowed():
    raw = run('pal({ k: nes(0x0F), y: nes(0x28) })\nramps("ky")\n'
              'sprite("a", { w: 8, h: 8 }, rect(0, 0, 8, 8, "k"), px(4, 4, "y"), glow("y", { r: 2, ramp: 1 }))')
    assert [a["name"] for a in raw.assets] == ["a"]


def test_illegal_color_hint_names_the_call():
    with pytest.raises(CodeModeError) as e:
        run('pal({ z: "#123456" })')
    assert "nes(0x" in str(e.value)


def test_cheatsheet_lists_every_rule():
    sheet = render_cheatsheet("nes")
    for r in NES_RULES:
        assert f"| {r.id} |" in sheet

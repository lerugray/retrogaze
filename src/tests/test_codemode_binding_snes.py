"""M2-01: the SNES binding hands the drawer only canonical 15-bit colors, through snes()/bgr555(), and the
active palette starts empty. (Spec file name: test_codemode_binding.py::test_snes_colors; kept in a new file
so the M1 test files stay byte-identical.)"""

import json
import re

import numpy as np
import pytest
from PIL import Image

from retrogaze.codemode.binding import SNES_LEVELS, binding_for, render_cheatsheet
from retrogaze.codemode.hw.rules import SNES_RULES
from retrogaze.codemode.runner import CodeModeError, run_loader
from retrogaze.console_profile import SNES_MODE1
from retrogaze.metadata import _check_palette_valid
from retrogaze.palette import quantize_to_bit_depth

from ._codemode import REPO
from .test_codemode_isolation import REVIEWED_GLOBALS


def run(src):
    return run_loader({"t.px.js": src}, "t.px.js", binding_for("snes", "legal"))


def test_snes_colors():
    raw = run("console.log(snes(31, 0, 0), snes(16, 8, 4), snes(0, 31, 0), bgr555(0x7C00), bgr555(0x1110), "
              "rg.screen.w, rg.screen.h, rg.colors.length)")
    assert raw.logs == ["#FF0000 #834120 #00FF00 #0000FF #834120 256 224 32768"]
    with pytest.raises(CodeModeError) as e:
        run('// line 1\npal({ x: "#848484" })\n')
    assert e.value.code == "CM-STRICT-COLOR"
    assert "#838383 = snes(16,16,16)" in str(e.value)
    assert e.value.loc.startswith("t.px.js:2:")
    # The active palette starts empty: no index keys exist until pal() binds them.
    assert binding_for("snes", "legal")["default_palette"] == "empty"
    with pytest.raises(CodeModeError):
        run('sprite("a", { w: 1, h: 1 }, px(0, 0, "1"))')
    raw = run('pal({ s: snes(31, 24, 16) })\nsprite("a", { w: 1, h: 1 }, px(0, 0, "s"))')
    assert [a["name"] for a in raw.assets] == ["a"]


def test_levels_are_the_existing_engines_expansion():
    """e(q) = (q * 255) // 31: palette.quantize_to_bit_depth and metadata._check_palette_valid agree."""
    assert SNES_LEVELS == [(q * 255) // 31 for q in range(32)]
    assert SNES_LEVELS[4] == 32                                  # not the bit-replication value 33
    every = np.array([[[v, v, v, 255] for v in range(256)]], dtype=np.uint8)
    quant = np.array(quantize_to_bit_depth(Image.fromarray(every, "RGBA"), 5))
    assert sorted(set(quant[0, :, 0].tolist())) == SNES_LEVELS
    for v in range(256):
        ok = _check_palette_valid(Image.fromarray(np.array([[[v, 0, 0, 255]]], np.uint8), "RGBA"), SNES_MODE1)
        assert ok == (v in SNES_LEVELS), v


@pytest.mark.parametrize("call", ["snes(32, 0, 0)", "snes(-1, 0, 0)", "snes(1.5, 0, 0)", "snes(1, 2)",
                                  "bgr555(0x8000)", "bgr555(-1)"])
def test_snes_bad_values(call):
    with pytest.raises(CodeModeError) as e:
        run(f"// line 1\n{call}\n")
    assert e.value.code == "CM-SNES-RANGE"
    assert e.value.loc.startswith("t.px.js:2:")


@pytest.mark.parametrize("line, code", [
    ("lighting()", "CM-STRICT-LIGHTING"),
    ('glow("k")', "CM-STRICT-GLOW"),
    ('use("pico8")', "CM-STRICT-USE"),
    ('pal({ z: "#123456" })', "CM-STRICT-COLOR"),
    ('sprite("a", rect(0, 0, 8, 8, "#ff000080"))', "CM-STRICT-ALPHA"),
    ("Math.random()", "CM-DETERMINISM"),
])
def test_snes_strict_wrappers(line, code):
    with pytest.raises(CodeModeError) as e:
        run(f"// line 1\n// line 2\n{line}\n")
    assert e.value.code == code
    assert e.value.loc.split(":")[:2] == ["t.px.js", "3"]


def test_snes_art_globals_are_reviewed():
    raw = run("console.log(JSON.stringify(Object.keys(globalThis).sort()))")
    assert set(json.loads(raw.logs[0])) == (REVIEWED_GLOBALS - {"nes"}) | {"snes", "bgr555"}


def test_snes_cheatsheet_and_skill_block():
    sheet = render_cheatsheet("snes")
    for r in SNES_RULES:
        assert f"| {r.id} |" in sheet
    skill = (REPO / "skills" / "retrogaze-code-mode" / "SKILL.md").read_text()
    m = re.search(r"<!-- BEGIN GENERATED: rules snes -->\n(.*)<!-- END GENERATED: rules snes -->", skill, re.S)
    assert m, "generated SNES rules block missing"
    assert m.group(1) == sheet, "regenerate the block from binding.render_cheatsheet('snes')"

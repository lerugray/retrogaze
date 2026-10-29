"""M1-23: hostile art files fail cleanly inside the build process; the host is unaffected."""

import time

import pytest

from retrogaze.codemode.binding import binding_for
from retrogaze.codemode.runner import CodeModeError, run_loader

from ._codemode import EXAMPLES, build_source

ESCAPE = 'const P = this.constructor.constructor("return process")()'


@pytest.mark.parametrize("src, codes", [
    ("process.exit(1)", {"CM-BUILD"}),                                       # no process in the art context
    (f"{ESCAPE}; P.exit(0)", {"CM-SANDBOX-EXIT"}),                          # vm escape: the process dies
    (f"{ESCAPE}; P.getBuiltinModule('fs').readFileSync('/etc/hostname')", {"CM-BUILD"}),   # permission model
    (f"{ESCAPE}; P.getBuiltinModule('child_process').execSync('true')", {"CM-BUILD"}),
    ("while (true) {}", {"CM-SANDBOX-TIMEOUT"}),                             # definition-time loop
    ('sprite("big", { w: 4096, h: 4096 }, rect(0, 0, 1, 1, "1"))', {"CM-SANDBOX-SIZE"}),
])
def test_hostile_art(src, codes):
    t0 = time.monotonic()
    with pytest.raises(CodeModeError) as e:
        run_loader({"t.px.js": src}, "t.px.js", binding_for("nes", "legal"), timeout=10)
    assert e.value.code in codes, (e.value.code, str(e.value))
    assert time.monotonic() - t0 < 15


def test_fs_access_is_denied_not_just_missing():
    with pytest.raises(CodeModeError) as e:
        run_loader({"t.px.js": f"{ESCAPE}; P.getBuiltinModule('fs').readFileSync('/etc/hostname')"}, "t.px.js",
                   binding_for("nes", "legal"))
    assert "ERR_ACCESS_DENIED" in str(e.value) or "permission" in str(e.value).lower()


def test_render_time_loop_is_killed():
    t0 = time.monotonic()
    with pytest.raises(CodeModeError) as e:
        run_loader({"t.px.js": 'sprite("a", { w: 8, h: 8 }, (c) => { while (true) {} })'}, "t.px.js",
                   binding_for("nes", "legal"), timeout=3)
    assert e.value.code == "CM-SANDBOX-TIMEOUT"
    assert time.monotonic() - t0 < 10


def test_host_unaffected_after_hostile_runs():
    r = build_source((EXAMPLES / "nes_hero.px.js").read_text(), "nes_hero.px.js")
    assert r.verdict == "legal"

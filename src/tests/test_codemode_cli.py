"""M1-21: CLI exit codes. 0 passed, 1 failed, 2 usage/unsupported, 3 the art did not build."""

import shutil
import subprocess
import sys

import pytest

from ._codemode import EXAMPLES, FIXTURES, REPO


def cli(*args):
    return subprocess.run([sys.executable, "-m", "retrogaze.codemode", *map(str, args)], cwd=REPO / "src",
                          capture_output=True, text=True, timeout=120)


@pytest.fixture()
def art(tmp_path):
    for name in ("nes_hero.px.js",):
        shutil.copy(EXAMPLES / name, tmp_path / name)
    shutil.copy(FIXTURES / "nes_H9_fail.px.js", tmp_path / "too_many.px.js")
    (tmp_path / "broken.px.js").write_text('sprite("a", { w: 8, h: 8 }, rect(0, 0, 8, 8, "1")\n')
    return tmp_path


def test_exit_codes(art):
    ok = cli("build", art / "nes_hero.px.js")
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "verdict: legal" in ok.stdout
    assert (art / "out" / "nes" / "legal" / "nes" / "title.chr").is_file()

    like = cli("build", art / "too_many.px.js", "--tier", "like")
    assert like.returncode == 0 and "verdict: like" in like.stdout

    bad = cli("build", art / "too_many.px.js")
    assert bad.returncode == 1 and "NES-H9" in bad.stdout and "too_many.px.js:4" in bad.stdout

    assert cli("build", art / "nes_hero.px.js", "--console", "genesis").returncode == 2
    assert cli("build", art / "missing.px.js").returncode == 2

    broken = cli("build", art / "broken.px.js")
    assert broken.returncode == 3 and "broken.px.js" in broken.stdout


def test_bind_prints_the_cheatsheet():
    r = cli("bind", "--console", "nes")
    assert r.returncode == 0 and "| NES-H9 |" in r.stdout
    assert cli("bind", "--console", "snes").returncode == 2


def test_verify_and_audit_commands(art):
    assert cli("build", art / "nes_hero.px.js").returncode == 0
    out = art / "out" / "nes" / "legal"
    v = cli("verify", out)
    assert v.returncode == 0 and "verified" in v.stdout
    assert cli("audit", out).returncode == 0

"""M1-02..04: no image model, no network, no raster input anywhere in code mode (invariant I1)."""

import json
import socket
import subprocess
import sys

import pytest

from retrogaze.codemode.binding import binding_for
from retrogaze.codemode.runner import CodeModeError, run_loader

from ._codemode import EXAMPLES, REPO, build_source

FORBIDDEN = ("retrogaze.generate", "retrogaze.pipeline", "retrogaze.generate_aseprite", "fal_client", "anthropic",
             "openai")


def test_no_image_model_imports():
    code = (
        "import json, sys\n"
        "from pathlib import Path\n"
        "import retrogaze.codemode, retrogaze.codemode.__main__, retrogaze.codemode.build\n"
        "from retrogaze.codemode.runner import read_art_dir\n"
        f"files, entry = read_art_dir(Path({str(EXAMPLES / 'nes_hero.px.js')!r}))\n"
        "r = retrogaze.codemode.build(files, entry)\n"
        "assert r.verdict == 'legal', r.report\n"
        "print(json.dumps(sorted(sys.modules)))\n"
    )
    out = subprocess.run([sys.executable, "-c", code], cwd=REPO / "src", capture_output=True, text=True, check=True)
    loaded = json.loads(out.stdout.strip().splitlines()[-1])
    bad = [m for m in loaded if any(m == f or m.startswith(f + ".") for f in FORBIDDEN)]
    assert bad == []


def test_build_with_network_disabled(monkeypatch):
    def no_network(*a, **k):
        raise OSError("network disabled for this test")

    monkeypatch.setattr(socket, "socket", no_network)
    monkeypatch.setattr(socket, "create_connection", no_network)
    r = build_source((EXAMPLES / "nes_hero.px.js").read_text(), "nes_hero.px.js")
    assert r.verdict == "legal"
    assert r.manifest["provenance"]["network_used"] is False
    assert r.manifest["provenance"]["raster_inputs"] == []
    assert r.manifest["provenance"]["ai_image_model"] is None


@pytest.mark.parametrize("files", [
    {"art.png": "\x89PNG"},
    {"t.px.js": 'sprite("a", { w: 8, h: 8 })', "reference.png": "\x89PNG"},
    {"t.px.js": 'sprite("a", { w: 8, h: 8 })', "ref.jpg": "x"},
])
def test_no_raster_inputs(files):
    from retrogaze.codemode.build import build

    r = build(files, "t.px.js" if "t.px.js" in files else "art.png")
    assert r.exit_code == 3
    assert r.report["errors"][0]["code"] == "CM-INPUT"


# The DSL surface an art file can reach. A new upstream op (for example an image importer)
# makes this test fail until someone reviews it for invariant I1.
REVIEWED_GLOBALS = {
    "Date",  # the determinism guard (throws on use), not the real Date
    "anim", "box", "bump", "circ", "clip", "console", "dither", "ellipse", "fill", "frame", "glow", "grad", "grid",
    "group", "hline", "include", "lamp", "layer", "light", "lighting", "line", "nes", "noise", "normals", "pal",
    "pattern", "poly", "px", "ramps", "recolor", "rect", "rg", "ring", "rng", "scatter", "scene", "shade", "sheet",
    "sprite", "stamp", "text", "tile", "tilemap", "use", "vline", "wire",
}


def test_art_globals_are_reviewed():
    raw = run_loader({"t.px.js": "console.log(JSON.stringify(Object.keys(globalThis).sort()))"}, "t.px.js",
                     binding_for("nes", "legal"))
    assert set(json.loads(raw.logs[0])) == REVIEWED_GLOBALS


def test_unknown_include_is_refused():
    with pytest.raises(CodeModeError) as e:
        run_loader({"t.px.js": 'include("other.px.js")'}, "t.px.js", binding_for("nes", "legal"))
    assert e.value.code == "CM-INCLUDE"

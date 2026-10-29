"""M1-29: code-mode sheet JSON feeds the existing engine exporters unchanged."""

import json

from retrogaze.export_formats import build_gamemaker_yy, build_godot_tres, build_unity_anim, build_unreal_sprite

from ._codemode import EXAMPLES, FIXTURES, build_file


def sheets():
    out = []
    for p in (EXAMPLES / "nes_hero.px.js", EXAMPLES / "nes_proof.px.js"):
        r = build_file(str(p))
        out += [json.loads(v) for k, v in r.outputs.items() if k.startswith("sheets/") and k.endswith(".json")]
    return out


def test_engine_exporters_accept_sheet():
    found = sheets()
    assert found
    for atlas in found:
        assert all("duration" in f for f in atlas["frames"].values())
        assert atlas["meta"]["retrogaze"]["provenance"]["mode"] == "code"
        assert "Texture" in build_godot_tres(atlas)
        assert build_unity_anim(atlas)
        assert build_gamemaker_yy(atlas)
        assert build_unreal_sprite(atlas)


def test_sheet_carries_hardware_cells():
    r = build_file(str(EXAMPLES / "nes_hero.px.js"))
    atlas = json.loads(r.outputs["sheets/chars.json"])
    cells = atlas["meta"]["retrogaze"]["hardware"]["hero"]
    assert len(cells) == 4
    assert {c["flip"] for c in cells} == {"", "x"}          # the mirrored half reuses tiles with H-flip


def test_anim_sheet_has_frame_tags():
    src = (FIXTURES / "nes_H12_pass.px.js").read_text() + '\nsheet("noise", ["n"])\n'
    from ._codemode import build_source
    r = build_source(src)
    atlas = json.loads(r.outputs["sheets/noise.json"])
    assert atlas["meta"]["frameTags"] == [{"name": "n", "from": 0, "to": 2, "direction": "forward"}]
    assert len(atlas["frames"]) == 3
    assert build_godot_tres(atlas)

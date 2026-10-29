"""M1.1: Ray's cartridge (MMC1, 8 KiB CHR-RAM) and the 8x16 / flip proof scenes (M1 review F7, "NROM vs MMC1").

NROM stays the default (spec §8 Q5). A scene that sets chr: "chr-ram" exports the same raw .chr/.pal/.nam/.oam
bytes, marks rom.json with chr "ram", keeps the CHR out of a CHR-ROM segment in the ca65 include, and is shown
by the MMC1 viewer ROM (proof/nes/viewer_mmc1.s) that uploads the .chr into CHR-RAM. The ROM-level checks
(iNES header, size, Mesen dumps) run in the codemode-proof job (proof/run_codemode_proof.py).
"""

import importlib.util
import json

import pytest

from retrogaze.codemode import ppu_ref
from retrogaze.codemode.encode.nes import encode_scene

from ._codemode import EXAMPLES, REPO, build_file

MMC1 = EXAMPLES / "nes_mmc1.px.js"
FLIPS = EXAMPLES / "nes_flips.px.js"


def _rom_builder():
    spec = importlib.util.spec_from_file_location("build_nes_rom", REPO / "proof" / "build_nes_rom.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_chr_ram_scene_is_marked_for_the_mmc1_viewer():
    r = build_file(str(MMC1))
    assert r.verdict == "legal", r.report
    rom = json.loads(r.outputs["nes/room.rom.json"])
    assert rom["chr"] == "ram" and rom["sprite_size"] == "8x16"
    hero = json.loads(build_file(str(EXAMPLES / "nes_hero.px.js")).outputs["nes/title.rom.json"])
    assert hero["chr"] == "rom"                      # NROM (CHR-ROM) stays the default
    assert len(r.outputs["nes/room.chr"]) == 8192 and len(r.outputs["nes/room.pal"]) == 32


def test_chr_ram_include_keeps_chr_out_of_chr_rom():
    r = build_file(str(MMC1))
    text = r.outputs["nes/room.s"].decode()
    assert '.segment "CHARS"' not in text
    rodata = text.index('.segment "RODATA"')
    assert rodata < text.index('room_chr: .incbin "room.chr"')
    assert "CHR-RAM" in text
    hero = build_file(str(EXAMPLES / "nes_hero.px.js")).outputs["nes/title.s"].decode()
    assert '.segment "CHARS"' in hero


def test_rom_builder_picks_the_cart_from_rom_json(tmp_path):
    b = _rom_builder()
    base = {"sprite_size": "8x8", "bg_table": 0, "spr_table": 1, "left8": True}
    assert b.cart_for(base) == "nrom"                                   # M1 rom.json (no "chr" key)
    assert b.cart_for({**base, "chr": "rom"}) == "nrom"
    assert b.cart_for({**base, "chr": "ram"}) == "mmc1"
    for rom in (base, {**base, "chr": "ram"}):
        p = tmp_path / "s.rom.json"
        p.write_text(json.dumps(rom))
        assert b.read_rom_json(p) == rom
    p.write_text(json.dumps({**base, "chr": "flash"}))
    with pytest.raises(b.SceneError):
        b.read_rom_json(p)
    assert b.CARTS["nrom"]["size"] == 16 + 16384 + 8192
    assert b.CARTS["mmc1"]["size"] == 16 + 8 * 16384                  # 128 KiB PRG, no CHR-ROM


@pytest.mark.parametrize("scene, size", [("flips8", "8x8"), ("flips16", "8x16")])
def test_flip_scenes_use_every_flip_bit(scene, size):
    r = build_file(str(FLIPS))
    assert r.verdict == "legal", r.report
    m = next(x for x in r.models if x.name == scene)
    assert m.sprite_size == size
    flips = {(c.flip_h, c.flip_v) for c in m.oam[0]}
    assert flips == {(False, False), (True, False), (False, True), (True, True)}
    b = encode_scene(m)
    attrs = {b.oam[0][4 * i + 2] & 0xC0 for i in range(len(m.oam[0]))}
    assert attrs == {0x00, 0x40, 0x80, 0xC0}
    # Four placements of one asymmetric sprite: the flipped copies cost no pattern tiles.
    one = len({c.placement for c in m.oam[0]})
    assert one == 4
    per_placement = len([c for c in m.oam[0] if c.placement == 0])
    assert len(m.obj_tiles[0]) == per_placement
    got = ppu_ref.render(b.chr[0], b.pal, b.nam[0], b.oam[0], b.rom)
    assert (got == m.composites[0]).all()


def test_8x16_vertical_flip_swaps_the_tile_pair():
    """In 8x16 mode the V bit flips the whole 16-row sprite: its bottom tile is drawn on top."""
    r = build_file(str(FLIPS))
    m = next(x for x in r.models if x.name == "flips16")
    up = next(c for c in m.oam[0] if not c.flip_v and not c.flip_h)
    down = next(c for c in m.oam[0] if c.flip_v and not c.flip_h and c.tile == up.tile)
    assert (down.pix == up.pix[::-1, :]).all()
    assert not (up.pix[:8] == up.pix[8:]).all()     # the halves differ, so a swap is visible

"""The Python half of the SNES viewer-ROM builder (proof/build_snes_rom.py): vram.json validation, the
generated scene.inc and the LoROM header checksum. The ROM itself is assembled and run in the codemode-proof
CI job (it needs cc65 and Mesen 2). Written after the builder, not red first."""

import importlib.util
import json

import pytest

from ._codemode_snes import EXAMPLES, REPO, build_file


def _builder():
    spec = importlib.util.spec_from_file_location("build_snes_rom", REPO / "proof" / "build_snes_rom.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def scene_dir(tmp_path):
    r = build_file(str(EXAMPLES / "snes_layers.px.js"))
    for k, v in r.outputs.items():
        if k.startswith("snes/") and "/pal/" not in k:
            (tmp_path / k[len("snes/"):]).write_bytes(v)
    return tmp_path, r


def test_scene_include_carries_the_vram_map_and_registers(scene_dir):
    d, r = scene_dir
    b = _builder()
    scene = b.read_scene(d, "layers")
    inc = b.scene_include("layers", scene)
    doc = json.loads((d / "layers.vram.json").read_text())
    for layer in ("BG1", "BG2", "BG3", "OBJ"):
        assert f"HAS_{layer} = 1" in inc
    assert f"BG1_CHR_VRAM = {doc['regions']['bg1_chr']['word_address']}" in inc
    assert f"OBJ_VRAM = {doc['regions']['obj']['word_address']}" in inc
    obsel = int(doc["registers"]["OBSEL"][1:], 16)
    assert f"REG_OBSEL = ${obsel:04X}" in inc and "REG_BG1VOFS = $03FF" in inc
    assert obsel >> 5 == r.report["scenes"][0]["obsel"]


def test_scene_files_are_checked(scene_dir):
    d, _ = scene_dir
    b = _builder()
    (d / "layers.oam").write_bytes(b"\0" * 543)
    with pytest.raises(b.SceneError):
        b.read_scene(d, "layers")


def test_lorom_checksum():
    b = _builder()
    rom = bytearray((i * 7 + 3) & 0xFF for i in range(b.ROM_SIZE))
    b.checksum(rom)
    h = b.HEADER
    comp, chk = rom[h + 0x1C] | rom[h + 0x1D] << 8, rom[h + 0x1E] | rom[h + 0x1F] << 8
    assert comp ^ chk == 0xFFFF
    assert sum(rom) & 0xFFFF == chk          # complement + checksum bytes always add up to $1FE, like $FFFF/$0000

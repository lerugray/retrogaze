"""M2-10: the SNES VRAM allocator. BG CHR on 8 KiB, tilemaps on 2 KiB, the OBJ base on 16 KiB; over budget is
SNES-H14 with byte totals; a large OBJ's tiles sit as a block on the 16-column OBJ name-table grid."""

from retrogaze.codemode.encode.snes import tile_4bpp
from retrogaze.codemode.hw.snes import VRAM_BYTES, VramRequest, allocate_vram

from ._codemode_snes import FIXTURES, build_file, build_source, scene, violations


def _overlaps(regions):
    spans = sorted((a, a + n) for a, n in regions.values())
    return any(spans[i][1] > spans[i + 1][0] for i in range(len(spans) - 1))


def test_allocator():
    req = VramRequest(bg_chr={"bg1": 600 * 32, "bg2": 100 * 32, "bg3": 50 * 16}, maps=["bg1", "bg2", "bg3"],
                      obj_tables=2)
    lay = allocate_vram(req)
    assert lay is not None and VRAM_BYTES == 65536
    reg = lay.regions
    assert set(reg) == {"obj", "bg1_chr", "bg2_chr", "bg3_chr", "bg1_map", "bg2_map", "bg3_map"}
    for name in ("bg1_chr", "bg2_chr", "bg3_chr"):
        assert reg[name][0] % 8192 == 0, name
    for name in ("bg1_map", "bg2_map", "bg3_map"):
        assert reg[name][0] % 2048 == 0 and reg[name][1] == 2048, name
    assert reg["obj"][0] % 16384 == 0 and reg["obj"][1] == 16384
    assert not _overlaps(reg) and all(a + n <= VRAM_BYTES for a, n in reg.values())
    r = lay.registers
    assert r["BG12NBA"] == ((reg["bg2_chr"][0] >> 13) << 4) | (reg["bg1_chr"][0] >> 13)
    assert r["BG34NBA"] == reg["bg3_chr"][0] >> 13
    assert r["BG1SC"] == (reg["bg1_map"][0] >> 11) << 2 and r["BG3SC"] == (reg["bg3_map"][0] >> 11) << 2
    assert r["OBSEL_BASE"] == reg["obj"][0] >> 14 and r["OBSEL_NN"] == 0
    assert lay.used == sum(n for _, n in reg.values())

    over = VramRequest(bg_chr={"bg1": 1024 * 32, "bg2": 1024 * 32}, maps=["bg1", "bg2"], obj_tables=0)
    assert allocate_vram(over) is None


def test_over_budget_is_h14_with_byte_totals():
    r = build_file(str(FIXTURES / "snes_H14_fail.px.js"))
    h14 = [v for v in violations(r.report) if v["rule"] == "SNES-H14"]
    assert h14 and h14[0]["found"] > 65536 and h14[0]["limit"] == 65536
    assert "bytes" in h14[0]["message"]
    ok = build_file(str(FIXTURES / "snes_H14_pass.px.js"))
    vram = ok.report["scenes"][0]["vram"]
    assert vram["used"] <= 65536 and set(vram["regions"]) >= {"bg1_chr", "bg1_map", "bg2_chr", "bg2_map"}


def test_16x16_obj_uses_n_n1_n16_n17():
    src = ('pal({ a: snes(31, 0, 0), b: snes(0, 31, 0), c: snes(0, 0, 31), d: snes(31, 31, 0) })\n'
           'sprite("q", { w: 16, h: 16 }, rect(0, 0, 8, 8, "a"), rect(8, 0, 8, 8, "b"), rect(0, 8, 8, 8, "c"), '
           'rect(8, 8, 8, 8, "d"))\n'
           'rg.scene("x", { obj: [["q", 40, 40, { size: "16x16" }]] })\n')
    r = build_source(src)
    assert r.verdict == "legal"
    obj = scene(r, "x").oam[0][0]
    data = r.outputs["snes/x.obj.4bpp"]
    n = obj.tile
    for k, (ty, tx) in zip((n, n + 1, n + 16, n + 17), ((0, 0), (0, 1), (1, 0), (1, 1))):
        assert data[32 * k:32 * k + 32] == tile_4bpp(obj.pattern[8 * ty:8 * ty + 8, 8 * tx:8 * tx + 8])
    assert len({data[32 * k:32 * k + 32] for k in (n, n + 1, n + 16, n + 17)}) == 4

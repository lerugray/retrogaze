RG-CODE-MODE-M2 DONE head=c836108a tests=1769/1775 m1_1=done nes_mmc1_proof=ran snes_proof=ran invariants=ok(1-M1-assert-retargeted-not-weakened)
Branch `gs/code-mode-m2` from `main`@f5597af5. Code head `c836108a`; the commit after it adds only this report and the screenshots next to it.
The one existing-test edit (see "Invariants"): `test_codemode_cli.py` line 48 asserted `bind --console snes` exits 2 (SNES unsupported); M2 makes SNES supported, so it now asserts the same for `genesis` (still unsupported, M3). Nothing else in an existing test file changed.

# Code mode M1.1 + M2: report

**Outcome.** Ray's NES cartridge (MMC1, 8 KiB CHR-RAM) now has an emulator proof, with 8x16 and flip scenes. SNES mode 1 is
console-legal end to end: rules SNES-L1..L4 and SNES-H1..H15, the 4bpp/2bpp/tilemap/CGRAM/OAM/VRAM exporters, a reference PPU,
and a ca65/ld65 LoROM viewer. In Mesen 2 it shows the code-drawn art with CGRAM, OAM and all 64 KiB of VRAM byte-exact.
SuperFamiconv independently agrees on the tile bytes, and negative controls pin the sprite range/time edge rules. All 16 M2
acceptance tests are green. Nothing was posted, merged, released or deployed.

## Commits on `gs/code-mode-m2`

| Commit | What |
|---|---|
| `1f3cce6` | **M1.1** (separate, as asked): MMC1 + CHR-RAM viewer, `nes_mmc1.px.js`, 8x16 and flip proof scenes |
| `7ed8a1c` | M2 checkpoint: SNES rules, binding, loader, legality engine, encoders, reference PPU, CLI/API |
| `caa47d0` | M2 proof: LoROM viewer, SNES Mesen runs, SuperFamiconv oracle, edge-rule controls, MCP, CI |
| `61a9092` | M2: SNES fuzzer; SNES-H4 made a hard limit in the OBSEL search (a bug the fuzzer found); spec/README/skill docs; Q10 draft |
| `c836108` | M2: `bg3Front` (BG3 priority) so a mode-1 HUD shows (found by looking at a screenshot); final docs |

## Counts, with the exact commands

| Check | Command | Result |
|---|---|---|
| Python suite, head, 3.13 | `cd src && RETROGAZE_MOCK=1 python -m pytest tests/ -q` (venv from `requirements-lock.txt`, Python 3.13.17) | **1769 passed, 6 skipped** (1775 collected) |
| Python suite, head, 3.11 (CI's version) | same, venv from the unpinned `src/requirements.txt` + pytest, Python 3.11.17 | **1769 passed, 6 skipped** |
| Python suite, base `main`@f5597af5 | same command before any change | 1621 passed, 6 skipped. Delta +148, all code-mode tests; the same 6 skips |
| Code-mode subset | `-k codemode` | 304 collected (M1: 156) |
| Emulator proof | `python proof/run_codemode_proof.py --mesen <Mesen> --superfamiconv <sfc> --work-dir W` | **PASS**, 13 scenes (7 NES, 6 SNES), exit 0; log below |
| NES harness self-test (M1) | `python proof/run_selftest.py --mesen <Mesen> --work-dir W` | SELFTEST PASS (after the runner/compare changes) |
| SNES fuzz, CI seeds | `python proof/fuzz_snes.py --mesen <Mesen> --work-dir W --seeds 0-24` | 21 scenes in Mesen (17 legal, 4 range/time overflows), 4 genuinely illegal skipped, **0 disagreed** |
| SNES fuzz, wider | seeds 0-79 (before `bg3Front`) and 0-59 (with it) | 70 and 53 scenes in Mesen, **0 disagreed** |
| MCP e2e, NES (M1) | `cd mcp-server && npm ci && PYTHON=<py> ./test-e2e-codemode.sh` | all checks passed (9 tools, build legal, verify, image refused, `title.chr` written) |
| MCP e2e, SNES (new) | `PYTHON=<py> ./test-e2e-codemode-snes.sh` | all checks passed (`retro_code_bind` SNES table, build `--console snes` legal, verify, `proof.cgram` written) |

Tools here (Ubuntu 24.04.5): cc65 `2.19-1` (the M1 goldens' package), Mesen 2 built by `proof/tools/build_mesen2.sh` at the pinned
`b9fa69dd` (.NET SDK 8.0.132; no NuGet workaround was needed here), SuperFamiconv v0.9.2 `fda06602` built by the new
`proof/tools/build_superfamiconv.sh` (two clean builds gave the same binary sha256 `c34165c0…8d74`), Node v22.22.0.

## Part 1: M1.1 (MMC1 + CHR-RAM, 8x16, flips)

- **Ray's cartridge.** `chr: "chr-ram"` scenes export the same raw `.chr` (8192 B) / `.pal` (32 B) / `.nam` / `.oam` for `.incbin`,
  write `"chr": "ram"` into `rom.json`, and their ca65 include keeps the `.chr` in `RODATA` (to upload) instead of a CHR-ROM
  `CHARS` segment. NROM stays the default (Q5); an M1 `rom.json` without the key still means NROM.
- **`proof/nes/viewer_mmc1.s` + `mmc1.cfg`**: NES 2.0 header (mapper 1, 8 x 16 KiB PRG, no CHR-ROM, CHR-RAM `64 << 7` = 8 KiB, no
  PRG-RAM, horizontal mirroring), the standard MMC1 reset stub at `$xFF0` of every bank, MMC1 control `$0F` (8 KiB CHR, PRG mode
  3 with bank 7 fixed at `$C000`, horizontal mirroring), PRG bank 0 (which holds the `.chr`) at `$8000`, the `.chr` copied into
  CHR-RAM `$0000-$1FFF`, then palette/nametable/OAM exactly as the NROM viewer. `build_nes_rom.py` picks the cart from `rom.json`.
- **Example**: `examples/codemode/nes_mmc1.px.js` (a dungeon room, 4 BG palettes, an 8x16-sprite knight and slimes).
  `python -m retrogaze.codemode rom` builds it as MMC1 automatically.
- **Flips (review F7)**: `examples/codemode/nes_flips.px.js`: an asymmetric sprite placed as drawn and flipped X, Y, XY, in 8x8
  (`flips8`) and 8x16 (`flips16`) mode. The flipped copies cost no tiles, and the `.oam` uses all four flip-bit combinations. In
  8x16 mode the V bit swaps the tile pair.
- **Proof**: three new scenes in the same job: `nes_mmc1_chr_ram` (`cart=mmc1`, header checked; Mesen's CHR dump is the CHR-RAM the
  viewer filled, byte-exact; one flipped `.chr` byte fails gate (c)), `nes_flips_8x8`, `nes_flips_8x16` (flip bits checked). All pass
  (a)-(d). **M1's four ROM goldens are byte-identical.**
- Tests: `test_codemode_nes_mmc1.py` (6), red first (6 failed before the implementation: missing examples / builder functions). The two
  new examples also join M1's own parametrized round-trip and engine-agreement tests (+4).

## Part 2: M2 (SNES console-legal, mode 1)

### Acceptance tests M2-01..M2-16 (spec §6), all green

| ID | Where | Result |
|---|---|---|
| M2-01 | `test_codemode_binding_snes.py::test_snes_colors` (+ e(q) levels vs the existing engine, `CM-SNES-RANGE` x6, strict wrappers x6, reviewed globals, cheat sheet/skill block) | pass (16 tests) |
| M2-02 | `test_codemode_rules_snes.py::test_rule_fail_fixture[19]`, `test_rule_pass_fixture[19]`, `test_every_snes_rule_has_a_fixture_pair` (38 fixtures in `src/tests/fixtures/codemode/snes/`; each fail fixture yields exactly its rule, blame on the marked line) | pass |
| M2-03 | `test_codemode_encode_snes.py::test_4bpp_goldens` (½ tile `41 01 C2 02 … 87` + 16 x `00`; index-15 tile bytes 0,1,16,17 = `80`) | pass |
| M2-04 | `::test_cgram_goldens` (`1F 00`, `E0 03`, `00 7C`, `FF 7F`, `10 11`; 512 bytes; OBJ palettes from byte 256) | pass |
| M2-05 | `::test_tilemap_word` (`$155`, palette 3, priority, H → `55 6D`) | pass |
| M2-06 | `::test_oam_and_high_table` (544 B; X = −1 → `FF` + high bit; size bits; parking; X = −256 → SNES-H4) | pass |
| M2-07 | `test_codemode_rules_snes.py::test_obsel` ({8,16,32} → SNES-H8 listing them; {8,16} → OBSEL 0; 16x32 needs `allowUndocumentedObjSizes` → OBSEL 6/7) | pass |
| M2-08 | `::test_scanline_range_and_time` (32 pass / 33 → SNES-H10 naming OAM #32; 34 pass / 35-36 → SNES-H11 naming the slivers; edge counting) | pass |
| M2-09 | `::test_obj_palette_is_per_object` (32x32 OBJ, 16 colors, 1 per tile → SNES-H3) | pass |
| M2-10 | `test_codemode_vram.py` (aligned map; over budget → SNES-H14 with byte totals; 16x16 OBJ at N, N+1, N+16, N+17) + `test_codemode_encode_snes.py::test_large_obj_tiles_are_a_16_column_block` | pass |
| M2-11 | `test_codemode_roundtrip_snes.py::test_snes_reference_render_matches[21]`, `test_encoder_refuses_with_the_validators_rule[13]`, `test_runtime_limit_scenes_still_encode[2]` | pass |
| M2-12 | `::test_existing_engine_agrees_snes[21]` (`generate_metadata(…, console="snes")`: `palette_valid`, `colors_per_tile_valid`) | pass |
| M2-13 | proof `snes_proof`: 32x32 hero = one 32x32 OBJ, BG1 tile set in 3 BG palettes, 2 OBJ palettes; Mesen exits 0; CGRAM == `.cgram`; OAM == `.oam`; VRAM == exports (all 64 KiB); screenshot bijection-matches (46 colors) | pass |
| M2-14 | proof `snes_33_on_a_line`, `snes_35_slivers` (and legal `snes_34_slivers`) + negative controls; the straddling OBJ pins SNES-H11's edge rule | pass; M2-08 already encoded the confirmed rule, so it did not need an update |
| M2-15 | proof `snes_proof` oracle: SuperFamiconv re-encodes the BG1 tiles **from the art's pixels** (not from our bytes) = `.bg1.4bpp`, 72/72 tiles, palettes 0-2 | pass |
| M2-16 | whole suite 1769/6 vs base 1621/6; no new skip/xfail; see Invariants for the one retargeted line | pass |

Test names: the spec puts M2-01 / M2-11 / M2-12 in M1's files (`test_codemode_binding.py`, `test_codemode_roundtrip.py`). They live in
new `*_snes.py` files so the M1 test files stay byte-identical (a rename only, like M1 review F3). Also new: `test_codemode_snes_outputs.py`
(CLI build/verify/audit, provenance, determinism, sheets + engine exporters, API, profile agreement) and `test_codemode_snes_rom.py`
(the Python half of the ROM builder; **written after the builder, not red first**). SNES art is in `examples/codemode/snes/`, because
M1's tests treat every `examples/codemode/*.px.js` as NES.

**Red first.** The six M2 test modules were written before any SNES code, and all of them failed to import. The first green run
then caught three gaps: the encoder did not yet refuse SNES-H2/H4 on its own, the CLI summary was not SNES-aware, and one test had
a wrong argument type, which was fixed in the test. Later tests were red first too: `test_bg3_in_front_for_a_hud` (unknown key)
and `test_pair_choice_avoids_unplaceable_objs` (red against the unfixed engine, green after). Before the first commit, one
fixture marker moved: `snes_H12_fail`'s `// expect` went to the anim line, because SNES-H12 blames the BG asset (as NES-H11 does).

### Done-when (spec §6 M2), run from `src/`

```
python -m retrogaze.codemode build ../examples/codemode/snes/snes_proof.px.js --console snes --tier legal   -> exit 0, "verdict: legal", 35 files in examples/codemode/snes/out/snes/legal/
python -m retrogaze.codemode rom ../examples/codemode/snes/snes_proof.px.js --console snes                  -> exit 0, out/snes/rom/proof.sfc, sha256 8bcd3312…90b4 = the proof golden
python -m retrogaze.codemode verify ../examples/codemode/snes/out/snes/legal                                -> "verified 35 outputs against 1 source file(s)"
```

That `.sfc` is the ROM that booted in Mesen 2 and showed the art (`snes_proof.mesen.png` next to this report).

### What was built (details in spec *M2:* notes, `proof/TOOLS.md`)

- **Binding/loader**: `snes(r5,g5,b5)`, `bgr555(word)`, canonical `e(q) = (q·255)//31` per channel, empty active palette,
  `#848484` → hint `#838383 = snes(16,16,16)`, `rg.colors` = 32 768 colors, reviewed globals.
- **Engine (`hw/snes.py`)**: BG1/BG2 4bpp and BG3 2bpp layers. 4bpp sets pack into 8 x 15, and BG3's 8 x 3 palettes are packed
  **jointly** inside CGRAM 0-31 (fast path, then an exact MILP, then a minimal unsat core). OBJ decomposition picks the cheapest
  OBSEL pair: hard limits first (incl. H4), then fewest OBJs, then fewest tiles. `obsel` and per-placement `size` pins, Q7
  opt-in, one palette per OBJ, 9-bit X, the range/time sweep with exact drops, BG tile dedup with flips (palette per map entry),
  OBJ blocks on the 16-column name tables, the VRAM allocator, and `bg3Front` (BGMODE bit 3) for HUDs.
- **Encoders (`encode/snes.py`)**: `.bgN.4bpp`/`.bg3.2bpp`/`.obj.4bpp`, `.bgN.map`, `.cgram`, `.oam` (unused OBJs parked at Y 224 /
  X −128, never −256), `.vram.json`, `pal/` slices, ca65 `.s` + C `.h`, and `.ref.png` + `screen.idx.png` (CGRAM order). The
  encoder runs its own re-check and refuses with the validator's rule (13 rules tested).
- **Reference PPU (`ppu_ref_snes.py`)**: renders only bytes (VRAM image, CGRAM, OAM, registers): mode 1 priorities, OBSEL, the
  name base/select, rectangular-OBJ V-flip quirk, range 32 / time 34 fetch order, the X = −256 bug.
- **Viewer (`proof/snes/viewer.s`)**: LoROM 128 KiB, valid header checksum. It clears VRAM, DMAs each blob to its `vram.json`
  address, loads the CGRAM and the 544-byte OAM, and sets the registers. It booted on its first run.

### Emulator proof, at `c836108a` (cc65 2.19-1, Mesen `b9fa69d`, SuperFamiconv `fda0660`)

```
nes_proof            gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=aa38c883049f golden=ok deterministic=ok cart=nrom:ok
nes_proof_tileset    gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=5667fb61dd15 golden=ok deterministic=ok cart=nrom:ok
nes_hero             gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=6da2ad721fad golden=ok deterministic=ok cart=nrom:ok
nes_9_on_a_line      gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=49d535a6c785 golden=ok deterministic=ok cart=nrom:ok
nes_mmc1_chr_ram     gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=b29e1b77d48d golden=ok deterministic=ok cart=mmc1:ok
nes_flips_8x8        gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=5c1ca9b5bddd golden=ok deterministic=ok cart=nrom:ok
nes_flips_8x16       gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=7a76204ea7d3 golden=ok deterministic=ok cart=nrom:ok
snes_proof           gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=8bcd3312acc7 golden=ok deterministic=ok cart=lorom:ok
snes_proof_tileset   gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=8c52807db636 golden=ok deterministic=ok cart=lorom:ok
snes_layers          gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=7622c3e7893c golden=ok deterministic=ok cart=lorom:ok
snes_34_slivers      gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=345d7bc5f3fc golden=ok deterministic=ok cart=lorom:ok control:fetch_hidden=ok
snes_33_on_a_line    gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=005efa05c1c9 golden=ok deterministic=ok cart=lorom:ok control:no_range_limit=ok
snes_35_slivers      gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=63d567139a71 golden=ok deterministic=ok cart=lorom:ok control:no_time_limit=ok control:fetch_hidden=ok
PASS
```

- Full ROM sha256s are in `proof/goldens.json` and `proof/TOOLS.md`. Every ROM was built twice with identical bytes.
- **The gates have teeth** (checked on `snes_layers`). One flipped byte in `.cgram`, `.oam`, `.bg1.4bpp`, `.bg3.map` or `.obj.4bpp`
  fails gate (c), and the failure is reported in that file or VRAM region. One changed reference pixel fails gate (d).
- **Sprite-evaluation edge rules, pinned** (M2-14). Each control is a deliberately wrong variant of the reference PPU. Mesen
  disagrees with it on exactly the pixels the variant changes:
  - `no_range_limit`: 56 px, which is OAM #32 dropped on lines 100-107.
  - `no_time_limit`: 122 px, which is OAM #0's right sliver dropped, because the fetch runs from the highest index down.
  - `fetch_hidden`: 122 px and 128 px. Tiles entirely off the left edge are not fetched, so an OBJ at X = −12 costs 1 sliver.
- **Fuzz**: random scenes with 1-3 BG layers, BG3 in front or behind, random palettes, OBJ sizes and flips, edge straddlers and
  crowded lines. Across the runs in the counts table (seeds 0-79, seeds 0-59 with `bg3Front`, seeds 0-24 at the head), 144
  scenes ran in Mesen, with 0 disagreements. An earlier run (seeds 0-29) found one real weakness, now fixed and
  regression-tested: the pair search could pick a 64x64 OBJ that runs past line 255 (SNES-H4) when a smaller pair was legal.

## Invariants (§1.3) and "no existing test weakened"

- **I1 ok.** No new imports of image-model code or network code: `test_no_image_model_imports` passes with SNES in the package.
  Inputs are still `.px.js`/`.px.ts` text only. SuperFamiconv reads PNGs, but it is a proof-harness oracle outside the package,
  and its input is our own rendered art. The SNES globals are pinned by a reviewed-set test.
- **I2 ok.** SNES rebuilds are byte-identical (`test_snes_rebuild_is_byte_identical`), and `verify` passes on SNES out dirs.
- **I3 ok.** No pixel is changed. OBJ canvas padding is transparent and reported (`SNES-L2 padded`). OBSEL choice, OBJ
  decomposition, palette slots and name-table placement change only the hardware layout.
- **I4 ok.** Every SNES PNG carries the provenance chunk + XMP; the sheet JSON and `manifest.json` list every file;
  `audit` covers `.4bpp/.2bpp/.map/.cgram` (a flipped `.bg1.4bpp` byte → audit fails).
- **I5 ok.** Rules, the encoder's independent re-check, `ppu_ref_snes` and Mesen all agree, plus SuperFamiconv on the tiles.
- **I6 ok.** `git diff --name-only origin/main -- src/retrogaze/{generate,generate_aseprite,pipeline,enforce,tiles,palette,palette_alloc,grid,console_profile,metadata,api,mcp_routes,cli,export_formats}.py third_party/`
  is **empty**. FLUX/Aseprite code, outputs and tests are untouched; the vendored pxl tree is unchanged (M1-01 passes).
- **Tests.** `git diff --diff-filter=MD --name-only origin/main -- src/tests mcp-server/test-e2e.sh mcp-server/test-e2e-codemode.*`
  lists exactly `src/tests/test_codemode_cli.py`, and that is the one retargeted line quoted at the top. It is not weakened: it
  still asserts that an unsupported console exits 2, and a new test asserts that `bind --console snes` now exits 0 with the SNES
  table. This is the only deviation from the literal "no existing test modified" (§7.4 / M2-16); SNES support cannot keep an
  assertion that SNES is unsupported. No skip or xfail was added, and the count did not drop.
- Other existing files changed (additively): `codemode/{build,binding,__main__}.py`, `hw/rules.py`, `encode/nes.py`
  (`rom.json` `chr` key, CHR-RAM include), `js/rg-build.mjs`, `schema/report-1.json` (rule pattern allows `SNES-`), `proof/*`,
  `mcp-server/src/tools.ts` (`console: "snes"`), CI, README, SKILL.md, spec. NES outputs are unchanged except `rom.json` (new
  `chr` key) and the provenance version string (`+codemode.m2`). All NES ROM goldens are unchanged.

## Decisions to look at (all recorded as *M2:* / *M1.1:* in the spec; §6 and §8 table rows are byte-identical to `main`)

1. **`bg3Front`** is an addition beyond the spec's `rg.scene` SNES keys. I added it after seeing the layered example's HUD hidden
   behind BG2. It uses mode 1's own BG3 priority bit, which is the standard mode-1 HUD, and it is proven in Mesen.
2. **SNES-H4 is conservative.** OBJ rows must stay in 0-255, so OBJs straddling the **top** edge are not legal in M2 (they need
   Y wrap-around). Left/right edge straddlers are legal and proven.
3. **Pair cost order.** Hard limits come first, then fewest OBJs, then fewest tiles. Without this, a 32x32 hero became sixteen 8x8
   OBJs.
4. **Layer model.** Each BG layer is one asset at the origin on one 32x32 map with 8x8 tiles. All BG tiles have priority 0 (except
   `bg3Front`) and all OBJs priority 3. 16x16 BG tiles, larger maps and per-tile priorities are not modeled yet.
5. **Joint BG3 packing.** It uses SciPy's MILP only when the fast path fails. It is exact, but the specific solution could differ
   across HiGHS versions; NES's MILP fallback (M1) has the same property.
6. **M1.1.** The cart follows `rom.json` `chr` (rom → NROM, ram → MMC1). MMC1 with CHR-ROM is not offered.

## Not done / limits

- **Real-hardware sign-off (Q9)** is a manual step for Ray (flash cart + console) and was not part of this run.
- **CI**: `codemode-proof.yml` triggers on pushes and PRs to `main` only, so it has not run on this branch. Every step it runs (the
  SuperFamiconv build, the 13-scene proof, fuzz seeds 0-24, both MCP e2e scripts, self-test) was run here with the same tools.
  Mesen 2 is not bit-reproducible (as M1 noted): this build's sha256 is `0a14c9f7…8f84`.
- Out of scope and untouched: M3; Q11 engine fixes; M1 review notes F1, F2, F5, F6 and F8. F7 and the NROM-vs-MMC1 note are
  addressed above.
- **Q10**: the upstream note is drafted in `docs/spec/UPSTREAM-ISSUE-DRAFT.md`. It was not posted.

## Files next to this report

`snes_proof.mesen.png`, `snes_layers.mesen.png`, `snes_35_slivers.mesen.png`, `nes_mmc1_chr_ram.mesen.png`, `nes_flips_8x16.mesen.png`
are Mesen 2 screenshots from the run above (256x224 SNES, 256x240 NES).

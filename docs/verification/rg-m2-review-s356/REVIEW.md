RG-M2-REVIEW ACCEPT-WITH-NOTES head=a215935e tests=1769/1775 skips=6 nes_mmc1_proof=ran snes_proof=ran fuzz=21/0 retarget=NOT-WEAKENED invariants=ok S1=0 S2=0
Does a Retrogaze user now get console-legal SNES mode-1 art drawn as code, proven in an emulator: YES

# RG-M2-REVIEW: code mode M1.1 + M2, the one independent end review

Reviewer: Claude Sonnet 5.5 (not the author's model), GS co-seat night-s355 t1284, MAIN-account cloud door. Review only: no product
edit, no PR, no merge, no deploy, no issue or comment. Carrier `gs/rg-m2-review-s356`@5c126c16 = author head `gs/code-mode-m2`@a215935e
(code head c836108a) + the card. BASE `origin/main`@f5597af5. No `STOP`, `HOLD` or `STEER.md` was present at the start or at the checkpoints
(rechecked after the proof runs). `.write-probe` create/verify/delete passed. Judged against `docs/spec/CODE-MODE-SPEC.md` at f5597af5.

**Verdict: ACCEPT-WITH-NOTES. 0 S1, 0 S2, 7 S3.** Every check on the card ran; nothing was skipped for lack of a toolchain. The Mac seat may
fast-forward `main` to the author head (the carrier adds only `docs/verification/rg-m2-review-s356/`, no product file).

## 1. Environment and exact commands

| Item | Value |
|---|---|
| OS / Python | Ubuntu 24.04.5, **Python 3.13.17**, venv from `src/requirements-lock.txt` (Pillow 13.0.0, scipy 1.18.0, numpy 2.5.0) |
| Toolchain | cc65 `2.19-1` (ca65 V2.18 Ubuntu), .NET SDK 8.0.132, clang, SDL2 2.30.0, Node v22.22.0 |
| Mesen 2 | built by `proof/tools/build_mesen2.sh` at the pinned `b9fa69dd`; binary sha256 `8391cb33…c128e` (not bit-reproducible, as TOOLS.md says) |
| SuperFamiconv | built by `proof/tools/build_superfamiconv.sh` at v0.9.2 `fda06602`; binary sha256 `6131e494…a5644` (TOOLS.md records a different binary hash, `c34165c0…`, from the author's compiler; the pin is the commit and the oracle result is what matters) |

| Check | Command | Result |
|---|---|---|
| Suite, author head | `cd src && RETROGAZE_MOCK=1 python -m pytest tests/ -q -rs` | **1769 passed, 6 skipped, 0 failed** (1775 collected), 125.8 s |
| Suite, BASE main | same, in a clean worktree of `origin/main` | **1621 passed, 6 skipped, 0 failed** (1627 collected), 75.4 s |
| Delta | `--collect-only` ids, head vs base | +148 ids, **0 base ids missing** from head. New ids by file: binding_snes 16, encode_snes 5, nes_mmc1 6, roundtrip (existing file, +4 parametrized cases from the two new NES examples) 4, roundtrip_snes 57, rules_snes 48, snes_outputs 6, snes_rom 3, vram 3 |
| Skips | `-rs`, and `git grep` for skip/xfail on both trees | the same 6 as base (`test_auth_and_user.py:313`, `test_pricing_limits.py:61`, 4 in `test_output_resolution.py`: "SaaS migration tree" and the operator prompt-restoration hold). 3 skip markers on both trees; **0 new skip or xfail** |
| MCP build | `cd mcp-server && npm ci && npm run build` | tsc clean |
| MCP e2e NES | `PYTHON=<venv> ./test-e2e-codemode.sh` | all 8 checks PASS, exit 0 |
| MCP e2e SNES | `PYTHON=<venv> ./test-e2e-codemode-snes.sh` | all 6 checks PASS (SNES rule table, build `--console snes` legal, verify, `proof.cgram` written), exit 0 |
| Harness self-test | `python proof/run_selftest.py --mesen M --work-dir W` | `SELFTEST PASS` (4.9 s; negative controls fail as intended; OAM Y convention confirmed; Mesen drops the highest OAM index) |
| Code-mode proof | `python proof/run_codemode_proof.py --mesen M --superfamiconv SFC --work-dir W` | **PASS, 13 scenes, exit 0** (24 s) |
| SNES fuzz | `python proof/fuzz_snes.py --mesen M --work-dir W --seeds 0-24` | **21 scenes in Mesen (17 legal, 4 runtime-limit), 4 skipped as illegal, 0 disagreed**, exit 0 (48 s) |

No CI file runs another Node test beyond the two e2e scripts above (`ci.yml` runs the Python suite and a separate browser smoke for the frontend; unchanged by the author).

Logs are in `logs/` next to this file (`run_codemode_proof.log`, `codemode_proof_summary.json`, `proof_gates_per_scene.txt`, `fuzz_snes_seeds_0-24.log`,
`run_selftest_tail.log`, `pytest_author_head.log`, `pytest_base_main.log`).

### Proof log (all 13 scenes, verbatim)

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

### Per-scene detail (from `codemode_proof_summary.json`)

- **ROM sha256 vs goldens.** All 13 equal `proof/goldens.json`, built twice (deterministic). **M1's four NES goldens are byte-identical to base**:
  `nes_proof aa38c883…`, `nes_proof_tileset 5667fb61…`, `nes_hero 6da2ad72…`, `nes_9_on_a_line 49d535a6…` (the four values in `goldens.json` are unchanged in the diff (one of them only gains a trailing comma);
  the 9 other lines are additions). I also rebuilt `nes_hero` through the CLI and `build_nes_rom.py` on my own and got `6da2ad72…` both with the `chr` key in `rom.json` and with it removed.
- **Mesen.** Every run exits 0 (`run_mesen: ok`, 11 frames, a 256-wide screenshot).
- **NES gates (c).** `.pal .oam .nam .chr` 0 mismatches on all 7 NES scenes; for `nes_mmc1_chr_ram` the `.chr` compared is Mesen's CHR dump, i.e. the CHR-RAM the viewer filled. Gate (d) bijection ok (expected colors == screen colors: 16, 13, 6, 2, 17, 9, 9).
- **SNES gates (c).** `.cgram` (512 B), `.oam` (544 B) and **all 64 KiB of VRAM** 0 mismatches on all 6 SNES scenes. Gate (d) ok (46, 30, 27, 4, 3, 4 colors, 0 mismatched pixels, 0 collisions).
- **M2-13 (`snes_proof`).** One 32×32 hero OBJ (OAM #2, size bit large, OBSEL 3 = 16×16/32×32), 2 small OBJs, 3 BG palettes, 2 OBJ palettes, BG1 tile set (72 tiles).
  A side-by-side of the Mesen screenshot and the reference render is `snes_proof_mesen_vs_ref.png` in this folder.
- **M2-14.** `snes_33_on_a_line`: validator `SNES-H10`, OAM #32 dropped, reference vs art differs in 56 pixels, all inside the 64 predicted (the rest are hidden by neighbours); control `no_range_limit`:
  the emulator disagrees with the no-range-limit variant on exactly its 56 pixels. `snes_35_slivers`: `SNES-H11`, 122 predicted = 122 differing; controls `no_time_limit` and `fetch_hidden` both ok.
  `snes_34_slivers` (legal, straddlers at X = −12 and X = 250) passes (c)/(d) with control `fetch_hidden` ok. So the edge rule (only tiles that reach the screen count, an X = −12 16-wide OBJ costs 1 sliver) is pinned by Mesen, and `test_scanline_range_and_time` asserts the same numbers.
- **M2-15.** SuperFamiconv re-encode of the proof tile set: `ok=True, tiles 72/72 checked, 0 mismatched tiles, 0 unchecked`, palettes [0,1,2].
- **Not vacuous (my own tamper checks on `proof/compare.py`).** Flipping one byte of `proof.bg1.4bpp`, `proof.cgram`, `proof.oam`, `proof.obj.4bpp` or `proof.bg1.map` after the run makes gate (c) fail; flipping a byte of the Mesen CGRAM dump fails it too;
  editing 8 pixels of `proof.ref.png` makes gate (d) fail while (c) stays ok.

## 2. Done when (§6 M2)

1. `python -m retrogaze.codemode build examples/codemode/snes/snes_proof.px.js --console snes --tier legal` exits **0** (verdict legal; same for `snes_layers.px.js`).
2. `python -m retrogaze.codemode rom … --console snes --scene proof --out proof.sfc` exits 0, writes a 131 072-byte LoROM `.sfc` with sha256 `8bcd3312…` = the golden; it boots in Mesen 2 (exit 0) and the screenshot shows the castle/knight/slime art (`snes_proof_mesen_vs_ref.png`).
3. M2-01..M2-16: table below. **Met.**

| ID | Where it is (all exist and pass; none skipped) | Name note |
|---|---|---|
| M2-01 | `test_codemode_binding_snes.py::test_snes_colors` (+15 more in that file) | spec names `test_codemode_binding.py`; the author's *M2:* note relocates it |
| M2-02 | `test_codemode_rules_snes.py::test_rule_fail_fixture[19]`, `::test_rule_pass_fixture[19]`, `::test_every_snes_rule_has_a_fixture_pair` | spec name `test_rule[...]` is split into fail/pass |
| M2-03 | `test_codemode_encode_snes.py::test_4bpp_goldens` | asserts `41 01 C2 02 44 04 48 08 10 16 20 21 40 42 80 87` + 16×`00` and bytes 0,1,16,17 = `80`, exactly as the spec |
| M2-04 | `::test_cgram_goldens` | `1F 00`, `E0 03`, `00 7C`, `FF 7F`, `10 11`; 512 B; OBJ palettes at byte 256 |
| M2-05 | `::test_tilemap_word` | `$155`, palette 3, priority, H-flip → `55 6D` |
| M2-06 | `::test_oam_and_high_table` | 544 B; X = −1 → `FF` + high bit; size bits; X = −256 → SNES-H4 |
| M2-07 | `test_codemode_rules_snes.py::test_obsel` | {8,16,32} → H8 listing them; {8,16} → OBSEL 0; 16×32 needs the flag → OBSEL 6/7 |
| M2-08 | `::test_scanline_range_and_time` | 32/33 → H10 (OAM #32); 34/35-36 → H11; edge rule per M2-14 |
| M2-09 | `::test_obj_palette_is_per_object` | 32×32, 16 colors, ≤15 per tile → H3 |
| M2-10 | `test_codemode_vram.py::test_allocator`, `::test_over_budget_is_h14_with_byte_totals`, `::test_16x16_obj_uses_n_n1_n16_n17` | |
| M2-11 | `test_codemode_roundtrip_snes.py::test_snes_reference_render_matches[21]` (+13 refusal, +2 runtime-limit) | spec names `test_codemode_roundtrip.py` |
| M2-12 | `::test_existing_engine_agrees_snes[21]` | |
| M2-13 / 14 / 15 | `proof/run_codemode_proof.py`, CI `codemode-proof` | ran by me, see §1 |
| M2-16 | no regression; existing tests: see §4 | |

M1.1 tests: `test_codemode_nes_mmc1.py` has the 6 the author names (`chr_ram_scene_is_marked_for_the_mmc1_viewer`, `chr_ram_include_keeps_chr_out_of_chr_rom`, `rom_builder_picks_the_cart_from_rom_json`,
`flip_scenes_use_every_flip_bit[flips8, flips16]`, `8x16_vertical_flip_swaps_the_tile_pair`), plus the +4 parametrized round-trip/engine-agreement cases in `test_codemode_roundtrip.py`. All pass.

## 3. Spec text: author edit vs main

`git diff origin/main...HEAD -- docs/spec/CODE-MODE-SPEC.md` has 11 hunks and **only 3 removed lines**: the status sentence, and the two §4.3 `nes/<scene>.rom.json` / `nes/<scene>.s` table rows, each re-emitted with an added *M1.1:* sentence. Everything else is additive (*M1.1:*/*M2:* notes in §2.3, §3.2, §3.4.1, §4.3, §4.4, §5.3, §5.4, §6 and after the §8 table). The §6 M2 table (M2-01…M2-16 rows and the "Done when" line, the line-numbered rows I read in main) and the §8 Q1-Q11 table rows are **byte-identical to main**
(none of the 3 removed lines is in them). No test, invariant or §8 answer is loosened. Two of the *M2:* notes make a rule stricter than main's text (SNES-H4 Y range, F2 below); none loosens.

## 4. The one retargeted M1 assertion: **NOT WEAKENED**

`git diff --diff-filter=MD --name-only origin/main -- src/tests mcp-server/test-e2e.sh 'mcp-server/test-e2e-codemode.*'` lists **only** `src/tests/test_codemode_cli.py`. No other existing test was modified or deleted, and no skip/xfail was added.
The hunk (`test_bind_prints_the_cheatsheet`, line 48):

```
-    assert cli("bind", "--console", "snes").returncode == 2
+    assert cli("bind", "--console", "genesis").returncode == 2    # M2 made snes supported; genesis is M3
```

Why it stays strong: `bind` has no argparse `choices` for `--console`, so exit 2 for `genesis` comes only from `check_supported()` → `ValueError` → `return 2` (`codemode/__main__.py:96-99`), the same path the old `snes` assertion exercised.
`genesis` is genuinely unsupported (`SUPPORTED = {"nes", "snes"}`) and is the next milestone's console (M3-04 expects it to stay exit 2 at the legal tier). The positive side is covered by a new test: `test_codemode_snes_outputs.py:51-52` asserts `bind --console snes` exits 0 and prints `| SNES-H11 |` and `snes(r5, g5, b5)`.
`test_exit_codes` (unchanged) additionally asserts `build --console genesis` exits 2.

**Planted mutants** (in a throwaway worktree of the carrier, reverted afterwards):

| Mutant | Result |
|---|---|
| A: `bind` returns 0 instead of 2 on the `ValueError` (`__main__.py:99`) | `test_bind_prints_the_cheatsheet` **FAILED** (`assert 0 == 2` at `test_codemode_cli.py:48`); 1 failed, 2 passed. Unmutated: 3 passed |
| B: `check_supported` no longer rejects an unknown console | `test_bind_prints_the_cheatsheet` **and** `test_exit_codes` **FAILED** (`KeyError: 'genesis'`, exit 1); 2 failed |

So the retargeted assertion goes red when unsupported-console handling breaks. One literal note: spec M2-16 says "no existing test modified"; exactly this one assertion was retargeted because the premise ("SNES is unsupported") became false, which the card itself anticipates (S3 F5).

## 5. Invariants I1-I6

| | Result |
|---|---|
| **I1** | OK. No image-model/network import anywhere in `src/retrogaze/codemode/` (grep for requests/httpx/urllib/socket/anthropic/openai: none). I built both SNES examples with `socket.socket` and `create_connection` disabled: verdict legal, `network_used=false`, `raster_inputs=[]`, `ai_image_model=null`, and `sys.modules` holds none of `retrogaze.generate/pipeline/generate_aseprite`, `fal_client`, `anthropic`, `openai`, `httpx`, `requests`, `urllib3`, `aiohttp`. Input is `.px.js/.px.ts` text only (`test_no_raster_inputs` passes). SuperFamiconv is only in `proof/sfc_oracle.py` (outside the package). New runtime deps for the package are scipy (already in `requirements.txt`/lock) and the existing `retrogaze.tiles/metadata/console_profile`. See F3 |
| **I2** | OK. `test_snes_rebuild_is_byte_identical` passes; `verify` on a fresh SNES out dir: "verified 35 outputs against 1 source file(s)", exit 0; all 13 ROM builds deterministic and equal to the goldens on a different machine than the author's. See F6 for the one residual risk |
| **I3** | OK. `test_obj_padding_is_reported` passes; for every legal scene gate (b) shows the reference render of the bytes equals the art composite with 0 differing pixels (negative scenes differ only on predicted dropped pixels). Palette slots, OAM order and OBJ cell choice are layout, not pixel changes. A backdrop-coloured opaque pixel still takes slot 1 (my probe: BG tile `rect` in the backdrop colour → palette `['$0C41','$7F14',…]`, per SNES-H5) |
| **I4** | OK. SNES PNGs (`png/*.screen.idx.png`, `sheets/*.png`) carry `retrogaze:provenance`, `xmp` and `XML:com.adobe.xmp`; `manifest.json` has `provenance` with `mode: code`, `digital_source_type` algorithmicMedia; `audit` over the SNES out dir: "27 asset file(s) carry valid code-mode provenance", exit 0. **I flipped byte 40 of `snes/proof.bg1.4bpp`: `audit` exit 1 (`snes/proof.bg1.4bpp: bytes changed after the build`) and `verify` exit 1 (`output modified since build`).** `AUDIT_EXT` now includes `.4bpp .2bpp .map .cgram` |
| **I5** | OK, and stronger than the card needs. Legal ⇒ encodable ⇒ bytes re-render pixel-identically (build runs `CM-ROUNDTRIP` for every legal SNES scene and state) ⇒ Mesen agrees. Beyond the author's proof I ran four probe scenes through the same gates (see §7); all passed |
| **I6** | OK. `git diff --stat origin/main...HEAD -- src/retrogaze/{generate,generate_aseprite,pipeline,enforce,tiles,palette,palette_alloc,grid,console_profile,metadata,api,mcp_routes,cli,export_formats}.py third_party/` is **empty**. `codemode_routes.py` and `api.py` are also not in the diff. The vendored pxl tree is unchanged (`test_codemode_vendor.py` passes, `git diff` of `third_party/` empty); the only JS change is the loader `src/retrogaze/codemode/js/rg-build.mjs` (not vendored): SNES colour helpers and level-based legality, NES paths guarded by `B.levels ?? null` |

## 6. SNES legality spot-check (spec §2.3) and M1.1 spot-check

**SNES (read `hw/snes.py`, `hw/rules.py`, `encode/snes.py`, `ppu_ref_snes.py`, `allocate_vram`; mutants killed the tests):**

- 4bpp BG: 8 palettes × 15 + backdrop (`TILE_CAP`, `SNES-H1/H6`); BG3 2bpp 8 × 3 inside CGRAM 0-31, packed jointly (greedy first, then an exact MILP, `_joint_milp`). Both joint cases in `test_bg3_packs_jointly_with_4bpp` plus two scenes I built that force the MILP path pass all gates in Mesen (§7).
- OBJ: 8 palettes × 15 from CGRAM 128 (`SNES-H7`, proof shows CGRAM equal), palette per OBJ (`SNES-H3`, M2-09), `OBSEL_PAIRS` 0-5 documented, 6-7 only with `allowUndocumentedObjSizes` (`SNES-H8`, M2-07, Q7). OBSEL 5 (32/64) with 64×64 OBJs and OBSEL 6 (16×32/32×64) with flips both agree with Mesen in my probes.
- 128 OBJs (`SNES-H9`), 32 per line (`SNES-H10`), 34 slivers (`SNES-H11`) with the edge rule exactly as pinned by M2-14: only tiles that reach the screen count (`on_screen_cols`), slivers fetched from the highest OAM index down so the frontmost OBJs lose theirs, and a fully off-screen-left OBJ is not "in range". Six planted mutants (`PER_LINE` 33, `SLIVERS` 35, `MAX_OBJ` 129, `VRAM_BYTES` 65537, right-edge off-by-one, `TILE_CAP` 16) were each caught by the M2 tests.
- X range: −255…255, never −256 (`SNES-H4`, `oam_bytes` raises with that rule); unused OAM parked at Y = 224, X = −128.
- VRAM (`SNES-H12/13/14`): ≤1024 BG tiles per layer (my 897-unique-tile probe passes in Mesen), OBJ blocks on the two 256-tile tables (my 400-OBJ-tile probe uses both tables and passes), allocator aligns BG CHR 8 KiB, maps 2 KiB, OBJ base 16 KiB with the second table right after (`OBSEL_NN = 0`), over budget → `SNES-H14` with byte totals; the proof compares all 64 KiB.
- **`bg3Front`** (author's last change). It is *not* in main's spec text (§3.2 key list is `{bg1, bg2?, bg3?, obj, backdrop, obsel?, palettes?, chr?}`); it is an additive, opt-in scene key recorded as an *M2:* decision on the branch. It is covered by `test_bg3_in_front_for_a_hud` (BGMODE `0x09`, priority bit on all BG3 entries, reference render equals the composite, BG3 over an opaque BG2 and over an OBJ), by the `snes_layers` proof scene (`bg3Front: true`, passes (c)/(d)) and by the fuzzer (`bg3Front` on ~half of the BG3 seeds). It changes nothing when absent. Not a rule the code checks differently from the spec; recorded as S3 F7 only for completeness.
- Rules checked more strictly than main's text: SNES-H4 also rejects an OBJ whose rows leave 0-255 at the top or bottom (F2).

**M1.1 (MMC1 + CHR-RAM):** header of my own build of `nes_mmc1.px.js`: `4E 45 53 1A 08 00 10 08 00 00 00 07 …` = 8 × 16 KiB PRG, no CHR-ROM, flags6 `$10` (mapper 1 low nibble, horizontal mirroring), flags7 `$08` (NES 2.0), byte 11 `$07` = 64<<7 = 8 KiB CHR-RAM; file size 131 088 = 16 + 8 × 16 384. Every PRG bank ends with the same reset stub (`78 A2 FF 9A 8E 00 80 4C 00 C0`), bank 7 fixed at `$C000`, vectors in bank 7. `MMC1_CONTROL_INIT = $0F` (`viewer_mmc1.s:30,91`). The `.chr` stays in `RODATA` for `chr-ram` scenes (`room.s`: `.segment "RODATA"` / `room_chr: .incbin`), `CHARS` only for CHR-ROM scenes. A scene whose `rom.json` lacks `chr`
builds NROM (24 592 B, mapper 0) with the identical golden sha (Q5 default unchanged). `test_8x16_vertical_flip_swaps_the_tile_pair` and the `nes_flips_8x16` proof scene (flip bits `[0, 64, 128, 192]`) cover the V-flip pair swap.

**Exposure gate: unchanged.** `api.py` and `codemode_routes.py` are not in the diff. With `fastapi.testclient` and the three environments: no `RETROGAZE_CODE_MODE`: `/code/build` **404**; `RETROGAZE_CODE_MODE=1`: **200**; with `RETROGAZE_DEMO=1` (+ `RETROGAZE_SAFETY_CHECKER=1`, required by the app): **403**; `/v1/code/build` is **404** in all three, so there is no `/v1/code/*` alias. `mcp-server/src/tools.ts` changes the `console` enum of `retro_code_bind` and `retro_code_build` to `["nes","snes"]` and also a text-summary change (F1).

## 7. Extra evidence I generated (all four pass gates (a)-(d), `probes/`)

Run through `proof/run_codemode_proof.py::run_snes_scene` (validator, reference round trip, LoROM ROM x2, Mesen, byte and pixel compare):

| Probe | What it exercises that the author's 13 scenes and 25 fuzz seeds do not | Result |
|---|---|---|
| `p1.px.js` | OBSEL 5 (32/64), three 64×64 OBJs with X/Y/XY flips, partial edges at X = −30 and 226, a flipped 32×32 | gate_a-d ok, 15 colors |
| `p2.px.js` | 897 unique BG1 tiles (tile numbers up to 896), 100 distinct 16×16 OBJs = 400 OBJ tiles across **both** name tables, 120 colours in all 8 BG palettes | ok, 120 colors, 0 mismatched pixels |
| `p3.px.js` | undocumented OBSEL 6 (16×32 / 32×64 OBJs) with `allowUndocumentedObjSizes`, X/Y/XY flips | ok |
| `p4_1`, `p4_3` | BG3 HUD forced through the exact MILP joint packing (`_joint_milp` called once each) | ok |
| `topwrap.py` | the hero OBJ with Y byte 250 (screen top −6): Mesen shows its lower rows at the top of the screen and equals the reference PPU (see F2) | gate (c)+(d) ok |

The fuzzer's 21 Mesen scenes used OBSEL 0 (×4), 1 (×2) and 3 (×15) only.

## 8. Findings (S3 only)

- **F1 (S3) — `mcp-server/src/tools.ts:146-152`.** The card says the file "adds only `console: "snes"`". It also changes `summarize()` to read `bg_tiles.max`/`obj_tiles.max`/`oam.max`/`per_line.max` and append `slivers`/`vram` when present. NES reports still carry `max: 256/256/64/8`, so the NES text is unchanged; tsc is clean and both e2e scripts pass. Exposure unaffected. No action.
- **F2 (S3) — SNES-H4 is stricter than main's text; `hw/snes.py:905`, `rules.py` SNES-H4, spec §2.3 row SNES-H4 ("X ∈ [−255, 255], X ≠ −256. Y is 8-bit").** The code also rejects an OBJ that "straddles the top edge" (e.g. a 16×16 at Y = −6 → `SNES-H4 … cannot be placed`) as well as one with `top + height > 256`. The author's note says both "wrap to the top of the screen". That is the failure for the bottom case (rows 16-31 of a 32-high OBJ at Y = 240 reappear on lines 0-15), but for the top case the wrap *is* the intended display: my probe (`probes/topwrap.py`) patched the hero's Y byte to 250 and Mesen's screenshot equals the reference PPU render, with the lower rows at the top lines. So the check never admits an illegal scene (I5 holds) but rejects art that is legal on hardware. It matches the M1 precedent (NES-H13 "top row 1-239", accepted at RG-M1-REVIEW), so S3. Suggested follow-up: allow `top < 0` and encode `Y = 256 + top`, keep the bottom rejection.
- **F3 (S3) — `src/tests/test_codemode_isolation.py:19-47`.** The I1 tests (no image-model import, network disabled) only build `nes_hero`. The SNES path newly imports `scipy`, `retrogaze.tiles/metadata/console_profile` and `ppu_ref_snes`; I verified by hand that a SNES build with sockets disabled loads no forbidden module (§5), but a regression there would not be caught. Add a SNES parametrization.
- **F4 (S3) — animated SNES scenes are not emulator-proven.** Only `snes_H12_fail.px.js` uses `anim`; the viewer shows state 0. I built a 2-frame animated BG + OBJ scene (`anim`): verdict legal, `s_s1.bg1.map`/`s_s1.oam` written, `verify` ok (the build's `CM-ROUNDTRIP` checks every state against the reference PPU), but no Mesen run of state ≥ 1 or of `chr: "per-frame"`. Not required by M2-01…16.
- **F5 (S3) — test names and M2-16 wording.** Spec rows M2-01/-11/-12 name `test_codemode_binding.py` / `test_codemode_roundtrip.py`; the tests exist and pass but live in `test_codemode_binding_snes.py` / `test_codemode_roundtrip_snes.py` (the author's *M2:* note says so, to keep M1 test files byte-identical), and M2-02 is split into `test_rule_fail_fixture`/`test_rule_pass_fixture`. M2-16 literally says "no existing test modified"; one assertion was retargeted (§4, NOT WEAKENED).
- **F6 (S3) — SNES-H6 exact MILP depends on scipy/HiGHS.** `hw/snes.py:_joint_milp` uses `scipy.optimize.milp`. None of the committed examples or goldens hit it (I counted: 0 calls for `snes_proof`/`snes_layers`), so the 13 golden ROMs are unaffected, but for a scene that needs it a different scipy/HiGHS version could return a different optimal packing, i.e. different (still legal) bytes, against I2. `requirements.txt` has `scipy>=1.11.0` (CI), the lock pins 1.18.0, provenance does not record the scipy version. Suggest recording it, or a deterministic tie-break.
- **F7 (S3) — fuzz and `bg3Front` coverage notes.** 4 of 25 seeds are skipped as illegal (H14, H8, H11+H8, H8), the 21 that ran used OBSEL 0/1/3 only (the 64×64, 16×32 and 32/64 paths are covered by my probes, not by CI), and `bg3Front` is an author extension outside main's §3.2 key list (it is documented in the branch's *M2:* note, tested, and proved by `snes_layers`).

No S1 and no S2. Nothing was found in the sealed user-JS sandbox (§3.7; out of scope per the card), and the RG-M1-REVIEW notes F1/F2 are not claimed fixed by the author, so they were not re-verified.

## 9. Cleanup

Throwaway worktrees (`base` of `origin/main`, `mut` with the planted mutants, reverted) live in the session scratchpad, not in this commit. The only repo change is this folder: `REVIEW.md`, `logs/`, `probes/` (review scripts and probe art, absolute paths are the session's), and `snes_proof_mesen_vs_ref.png`.

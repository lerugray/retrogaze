RG-M1-REVIEW ACCEPT-WITH-NOTES head=f5597af5 tests=1621/1627 skips=6 nes_proof=ran invariants=ok S1=0 S2=0
Does a Retrogaze user now get console-legal NES art drawn as code, proven in an emulator: YES

# RG-M1-REVIEW: code mode M1, the one independent end review

Reviewer: Claude Sonnet 5.5 (not the Opus 5.5 author). Review only: no product edits, no PR, no deploy, no GitHub post.
Judged against `origin/gs/code-mode-spec-s356`@99f902ae (`docs/spec/CODE-MODE-SPEC.md`), not the author-edited copy.
Carrier `gs/rg-m1-review-s356` = f5597af5 + the GS card. Base = `origin/main`@52768093. No STOP, HOLD or STEER file appeared
(checked at start and at each checkpoint). `.write-probe` create/verify/delete passed.

Verdict: **ACCEPT-WITH-NOTES**. 0 S1, 0 S2, 8 S3 notes (all non-blocking; F1 and F2 are the two worth a follow-up row).

## Counts, with the exact commands

| Check | Command | Result |
|---|---|---|
| Python suite, head | `cd src && RETROGAZE_MOCK=1 python -m pytest tests/ -q` (Python 3.13.17, venv from `requirements-lock.txt`) | **1621 passed, 6 skipped, 0 failed** (1627 collected) |
| Python suite, BASE 5276809 | same command in a worktree of `origin/main` | **1465 passed, 6 skipped** (matches the M1-28 baseline exactly) |
| Delta | | +156 passed, +0 skipped: all 156 are `test_codemode_*` tests; the same 6 skips as base |
| M1-24 | `cd mcp-server && npm ci && PYTHON=<venv>/bin/python ./test-e2e-codemode.sh` (Node v22.22.0) | 8/8 PASS: `tsc` clean, 9 tools listed incl. `retro_code_bind/build/verify`, build -> `verdict legal`, verify -> verified, image file refused, `title.chr` written |
| Existing `mcp-server/test-e2e.sh` | `bash test-e2e.sh` | Not runnable here: it targets the live site `https://retrogazeai.com` (egress blocked, 8 FAIL with HTTP 000). Pointed at a local mock API with `RETROGAZE_API_URL`: 9 pass, 1 fail (`/mcp/prompt` returned 200, expected 4xx; a mock-mode/auth artifact of a local server). The file is byte-unchanged by the author, and CI does not run it (CI runs pytest only). NOTE, not an author fault |
| Python 3.11 (CI's `ci.yml` version) | venv from the unpinned `requirements.txt` + pytest; `RETROGAZE_MOCK=1 python -m pytest tests/ -q -k codemode` | **156 passed, 0 failed** (the whole suite was run on 3.13 only) |

M1 test inventory (all exist and pass; none skipped): M1-01 `test_vendored_pxl_matches_manifest`; M1-02 `test_no_image_model_imports`;
M1-03 `test_build_with_network_disabled`; M1-04 `test_no_raster_inputs[3]` + `test_art_globals_are_reviewed`; M1-05 `test_nes_colors`;
M1-06 `test_strict_wrappers[13]`; M1-07 `test_byte_identical_rebuild`; M1-08 `test_rule_pass_fixture[17]`/`test_rule_fail_fixture[16]`/
`test_warning_fixture`/`test_normalization_fixture_8x16_and_padding`/`test_every_failing_rule_has_a_fixture_pair` (renamed, see F3);
M1-09 `test_bg_palette_packing`; M1-10 `test_scanline_limit_names_the_dropped_sprite` (renamed, F3); M1-11 `test_decomposition_offset_search`;
M1-12 `test_chr_golden_half_tile`; M1-13 `test_nametable_and_attributes`; M1-14 `test_palette_bytes`; M1-15 `test_oam_bytes`;
M1-16 `test_nes_reference_render_matches[20]`; M1-17 `test_existing_engine_agrees_nes[20]`; M1-18 `test_embedded_provenance`; M1-19 `test_verify`;
M1-20 `test_audit`; M1-21 `test_exit_codes`; M1-22 `test_build_endpoint` (+5 more route tests); M1-23 `test_hostile_art[6]`;
M1-25 `test_cheatsheet_is_generated`; M1-29 `test_engine_exporters_accept_sheet`. Missing: none. Skipped: none.

## The emulator proof (M1-26, M1-27): I ran it myself

- Toolchain: `apt` cc65 2.19-1, clang 18, libsdl2-dev, dotnet-sdk-8.0 (8.0.132). Mesen 2 built with `proof/tools/build_mesen2.sh`
  at the pinned commit `b9fa69dd…` (installed binary sha256 `09b16e6c64329f0f7850202ea99e28370a0f3f4f825414c7d79513ea886493c8`;
  the author notes the bundle is not bit-reproducible, so this differs from the author's builds, as TOOLS.md predicts).
- One environment workaround, outside the repo: `UI/UI.csproj` lists `https://nuget-feed-nightly.avaloniaui.net` as a restore
  source and this sandbox's egress proxy refuses that host, so the first `dotnet publish` failed with `NU1301`. I put
  `-p:RestoreSources=https://api.nuget.org/v3/index.json` in a `Directory.Build.rsp` inside my throw-away Mesen source tree
  and re-ran the unmodified `build_mesen2.sh`. The resolved packages are the stable ones named in the csproj (Avalonia 11.3.1).
  The repo's scripts and the pin are untouched. (F8: CI depends on that nightly feed being up.)
- `python proof/run_codemode_proof.py --mesen /tmp/.../mesen2/bin/Mesen --work-dir …` -> **PASS, exit 0**, 5.6 s:

```
nes_proof            gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=aa38c883049f golden=ok deterministic=ok
nes_proof_tileset    gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=5667fb61dd15 golden=ok deterministic=ok
nes_hero             gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=6da2ad721fad golden=ok deterministic=ok
nes_9_on_a_line      gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=49d535a6c785 golden=ok deterministic=ok
PASS
```

  - ROM sha256 vs `proof/goldens.json`: all four equal (full hashes: proof `aa38c883…8b83`, tileset `5667fb61…319a`, hero `6da2ad72…58d4`,
    9-line `49d535a6…0632`); each ROM built twice, identical. Mesen exit code 0 for each run (`run_mesen.py` raises on any other code).
  - Gate (c), byte-exact vs the exported `.pal` `.oam` `.nam` `.chr`: 0 mismatches in all four scenes. Gate (d), screenshot vs
    reference PPU under a colour bijection: 0 mismatched pixels, 0 collisions (16 colours in `nes_proof`, 13 in the tile set, 6 in the hero, 2 in the 9-line case).
  - M1-27 `nes_9_on_a_line`: reference differs from the art composite in **64 px = exactly the 64 px of OAM #8 on lines 100-107** that the validator
    predicted; Mesen's screenshot matches the reference. The harness self-test (`proof/run_selftest.py`) also passes, including its
    negative controls (Y-byte convention, 40 px dropped, tamper detection).
  - The M1-26 scene matches the spec text: a 16x16 hero from 4 hardware sprites in 2 sprite palettes, plus a 16x16 metatile set covering 256x240 in 4 BG palettes.
  - I looked at the Mesen screenshots (`nes_proof`: sky, clouds, bricks, stone blocks, grass, water and the hero; `nes_hero`: two heroes on grass). The art is on the screen.
- **Do the gates have teeth?** I flipped one palette byte, one OAM X byte and one nametable byte in the exported scene and re-ran `compare.compare`
  against the real Mesen dump: gate (c) failed each time. I changed one pixel of the reference render: gate (d) failed. So a pass is not vacuous.
- **Beyond the author's scenes (my own probes, not in the repo):** (1) a hand-written 8x16-mode scene with all four flip combinations and 4 sprite palettes;
  (2) 8 randomly generated scenes (random BG attribute areas over 4 random palettes, 4 sprite types, 12 random flipped placements, half in 8x16 mode).
  Each was built `legal` by the validator, then run in Mesen: every one passed gates (a)-(d). No case where the validator said legal and the emulator disagreed.
  I also compared `pack_palettes` (both the backtracking path and the MILP fallback) against a brute-force oracle on 1500 random small instances (3000 solver calls): 0 mismatches.
- **Done-when commands.** From `src/` (the repo's convention): `python -m retrogaze.codemode build ../examples/codemode/nes_hero.px.js --console nes --tier legal`
  -> exit 0, "verdict: legal", wrote 16 files to `examples/codemode/out/nes/legal/{png,sheets,nes}/…` (the entry file's directory, as spec §4 says).
  `python -m retrogaze.codemode rom ../examples/codemode/nes_hero.px.js` -> exit 0, wrote `out/nes/rom/title.nes` (24,592 bytes = 16 + 16 KiB + 8 KiB; sha256 `6da2ad72…58d4`
  = the golden), which is the same ROM that booted in Mesen above. See F5 for the literal-from-repo-root caveat.

## Invariants

- **I6 ok.** `git diff --name-only origin/main...HEAD` touches no FLUX/Aseprite module or output path; the only edits to existing product files are
  `src/retrogaze/api.py` (+4 lines: import, `include_router("/code")`, `_MOUNTED_ROUTERS`, `_API_PATH_PREFIXES`), `mcp-server/src/{client,index,tools,types}.ts`
  (additive), `README.md`, `.gitignore`, and `ci.yml` (a Node setup step). `git diff --diff-filter=MD origin/main -- src/tests mcp-server/test-e2e.sh` is **empty**.
  `git diff --diff-filter=MD --name-status origin/main...HEAD` lists 8 modified files, none a test; no deletions. No new `skip`/`xfail` anywhere.
  `src/tests/test_api_v1_allowlist.py` unchanged and green.
- **Vendored pxl ok.** All 33 files under `third_party/pxl/` hash to `MANIFEST.sha256` (`sha256sum -c`: 33 OK, 0 failed; 33 manifest lines); `UPSTREAM.md` names
  `21fee41f7ecce00bc868d7567f24ffd0f3acc8fa`; the MIT `LICENSE` is present. A fresh fetch of upstream `crsolver/claude-pxl` at that exact commit
  (network allowed) is **byte-identical** (`cmp` on every vendored file, 0 differences); "Local patches: none" is true.
- **I1 ok.** Read the code, not only M1-02..04. The package's imports are numpy, Pillow, scipy (lazy MILP), and the repo's own `console_profile/palette/metadata/tiles`; none of
  `generate/pipeline/generate_aseprite/fal_client/anthropic/openai`, and no `socket/urllib/http/requests`. `runner.validate_files` rejects any name not ending `.px.js/.px.ts`,
  absolute or `..` paths, >32 files, >256 KiB. The Node child runs with `--permission` and read access only to pxl and the loader, source in on stdin, result out on stdout.
  `Image.open` appears only in `provenance.py`/`build.py` to read code mode's own outputs (verify, audit); the base64 in `hw/common.py` decodes the loader's own RGBA output.
  `test_art_globals_are_reviewed` pins the DSL globals, so a future upstream image-import op fails until reviewed.
- **I2 ok.** Two builds 3 s apart: `diff -r` of the two output trees differs only in `manifest.json` `built_at` (appears in 2 places). `verify` -> exit 0; `audit` -> exit 0.
- **I3 ok.** No remap/dither/quantise/nearest-colour code exists in `codemode/` (the only "nearest" is a text hint on `CM-STRICT-COLOR`); OBJ canvas padding is transparent-only and reported (`NES-L2 padded`);
  M1-17 proves `enforce_constraints` changes 0 pixels on every legal BG and single-palette OBJ fixture.
- **I4 ok.** See provenance below. **I5 ok.** The rules, the encoder's independent `_check_model` re-check, and `ppu_ref` (which reads only bytes) are three mechanisms; Mesen is the fourth.

## NES legality spot-check against spec §2.2

I read `hw/nes.py`, `hw/rules.py`, `encode/nes.py` against §2.2 and found no rule checked differently:
4 BG palettes x 3 colours + one shared backdrop (`solve_bg`, `finish_palettes`; mirrors `$3F10/14/18/1C` = `$3F00/04/08/0C`, checked in `test_palette_bytes`);
16x16 attribute areas aligned to the nametable origin (`AREA = 16`, `bgAt` must be a multiple of 16, rows 30-31 fields are 0: golden `E4`); 4 sprite palettes x 3 (`solve_obj`);
8 sprites per scanline over lines 0-239 with a sprite covering `[top, top+h)`, 8x16 counted as 16 rows, dropped = highest OAM index first (`oam_and_lines`);
64 OAM total (`NES-H8`); Y byte = top-1, `top ∈ [1,239]`, `X ∈ [0,255]` (`NES-H13`); one sprite size per frame (`NES-H10`); BG tiles <= 256 with no flips,
OBJ tiles <= 256 with H/V flip dedup, 8x16 may draw from both tables under the budget model; default CHR model `nrom-split` (Q5); `$0D` is rejected in `nes()`, in pinned palettes and backdrop, and `palette_bytes` re-asserts none is emitted; canonical `#000000 -> $0F`, `#FFFFFF -> $30`.
Backdrop choice: candidates ordered by (-frequency, lowest byte) and the first that makes NES-H6 feasible wins, as §2.2 NES-H5 says. The palette packer is exact (above).

## Provenance (M1-18..20, I4)

`png/*.png` carry an `iTXt` `retrogaze:provenance` chunk (validates against `schema/provenance-1.json`: mode `code`, `algorithmicMedia`, `ai_image_model: null`, `raster_inputs: []`,
`network_used: false`, renderer pinned to the upstream commit and the manifest tree hash) plus an `XML:com.adobe.xmp` chunk with `Iptc4xmpExt:DigitalSourceType = …algorithmicMedia`; sheet JSON carries
`meta.retrogaze.provenance`; `manifest.json` lists all 16 other outputs with sha256 and embeds the block. `verify`: 0 on a clean build; 1 naming the file on a flipped pixel or edited source; 4 on a changed binding hash (asserted by `test_verify`; the same exit 4 for a changed vendored-tree hash is in the code at `build.py` `verify` but no test drives it, a small gap). `audit`: passes a code-mode out dir, fails a dir that also holds a `test_sprites/` PNG ("no code-mode provenance"). See F2 for how far `audit` goes.

## Q4 exposure gate

`codemode_routes.require_code_mode`: 404 unless `RETROGAZE_CODE_MODE == "1"`; then 403 if `RETROGAZE_DEMO == "1"` (same truthiness test as `api.py:201`). It is a router-level dependency on `/binding`, `/build`, `/verify`.
Not added to `_V1_ALLOWLIST`; `test_no_v1_alias` asserts no `/code` pair in `V1_ALLOWED_PAIRS` and `POST /v1/code/build` -> 404. Responses are built in the router, never through `_STRIP_KEYS`, so provenance is always returned
(`test_build_endpoint`). No auth dependency, as the spec's "local first" model implies. Per card item 8 I did not review the JS sandbox's security.

## Findings

| # | Sev | Where | Spec | Finding |
|---|---|---|---|---|
| F1 | S3 | `runner.py:155` (`read_art_dir`), `build.py:346` (`build_path`) | §3.5 exit codes, M1-04 | Pointing the CLI at a **real** PNG (`python -m retrogaze.codemode build ref.png`) prints a `UnicodeDecodeError` traceback and exits **1** (spec: "tier failed, report written"). The raster is still never read as an image, so I1 holds, and a text file named `.jpg` correctly gives `CM-INPUT`, exit 3 (that is all M1-04 tests). Fix: check the suffix before `read_text`, or catch `UnicodeDecodeError` -> `CM-INPUT`, exit 3 |
| F2 | S3 | `build.py:426-455` (`audit`) | §1.4 release gate | For PNGs, `audit` checks the embedded chunk and `pixels_sha256` only, not a manifest or source. I built a PNG from a `test_sprites/` image with a hand-written, self-consistent provenance chunk: `audit` returned 0 ("1 asset file(s) carry valid code-mode provenance"). It does catch the real risk M1-20 names (unstamped FLUX/Aseprite PNGs, changed pixels, changed binaries), but "provenance that verifies" is then an integrity check, not a rebuild. Suggest a follow-up row: require each PNG to appear in a manifest (the manifest lists them) and an `audit --rebuild` mode |
| F3 | S3 | `test_codemode_rules_nes.py` | §6 M1-08, M1-10 | Spec names `test_rule[NES-L1…NES-H14]` and `test_scanline_limit`; the author split them into `test_rule_pass_fixture`/`test_rule_fail_fixture` (+ warning/normalization tests) and `test_scanline_limit_names_the_dropped_sprite`. Every asserted behaviour is present and stricter in places (fail fixtures must yield exactly one error rule and the blame line; coverage test fails if a rule lacks a fixture pair). Rename only |
| F4 | S3 | `docs/spec/CODE-MODE-SPEC.md` (author copy, 22+/12-) | §1.4, §2.1, §3.4.1, §4.1, §4.3, §5.2 | I diffed the author's spec edits against 99f902ae. **None loosens an M1 test row, an invariant or a §8 answer** (§6 and §8 are byte-identical). They are build decisions: (a) files embed only the deterministic provenance fields, `built_at`/Node version/git commit live in `manifest.json` only (the spec put the full block, with `built_at`, in each PNG; the schema still validates and I2 is stronger); (b) NES-L3 applies per `obj:<n>` layer for layered sprites (a layered sprite's exported composite can exceed 4 colours in a tile while each hardware cell still obeys NES-H3's 3; M1-17 has no layered fixture, so this path is untested against the old engine); (c) lone OBJ placed at (8,8) not (0,8); (d) `.chr` always 8 KiB (`--chr-pad` dropped); (e) Mesen pinned by source commit, not release+sha256; (f) `.idx.png` is per scene. Also `test_nes_reference_render_matches` blanks the left 8 px of the expected composite when a scene sets `left8: false` (NES-H14 warning case). Worth Ray seeing (a), (b), (e) |
| F5 | S3 | Done-when text | §6 | The command as written from the repo root (`python -m retrogaze.codemode build examples/...`) fails with `ModuleNotFoundError: retrogaze`: there is no `pyproject.toml`, so the package imports only from `src/` (or with `PYTHONPATH=src`), exactly like the existing `python -m retrogaze` CLI and the README, which says `cd src`. Run from `src/` it meets Done-when. Spec wording or a root-level shim is a docs row |
| F6 | S3 | `codemode_routes.py:32-37`, `api.py:269` | §3.5, Q4 | With `RETROGAZE_DEMO=1` and `RETROGAZE_CODE_MODE` unset the route is a 404, not a 403 (the 403 needs both set). Safer, and the test sets both. `"/code"` is matched by `startswith`, so the `X-Robots-Tag` header would also apply to any future path beginning `/code…`. Cosmetic |
| F7 | S3 | `proof/run_codemode_proof.py` `SCENES` | §5, M1-26 | The committed proof scenes are 8x8-sprite NROM-split only. 8x16 mode, flips, `shared` and `chr-ram` models are covered by the byte/round-trip unit tests but not by an emulator scene. My own 8x16/flip and random-scene probes (above) passed in Mesen; recommend adding the 8x16+flip scene to `SCENES` |
| F8 | S3 | `proof/tools/build_mesen2.sh`, `.github/workflows/codemode-proof.yml` | §5.2 | Mesen's `UI.csproj` hard-codes `nuget-feed-nightly.avaloniaui.net` as a restore source; where that host is unreachable (this sandbox) the build fails with `NU1301` until the source is overridden (see above). The CI job caches the built Mesen, so it only matters on a cold cache. A one-line `-p:RestoreSources=…nuget.org…` in `build_mesen2.sh` would make the build independent of that feed |

No S1 and no S2: no M1 test missing/failing/skipped, no invariant broken, no existing test weakened, no silent pixel change found, and "Done when" is met (from `src/`).

## NROM vs MMC1 (NOTE only, not a fault)

The NES default is the spec's **NROM** default (§8 Q5, adopted by Ray): CHR model `nrom-split`, 8 KiB CHR-ROM as two 256-tile tables (BG at `$0000`, sprites at `$1000`), and the viewer ROM
`proof/nes/nrom.cfg` is NROM-128 (16 KiB PRG + 8 KiB CHR-ROM; ROMs are 24,592 bytes). The repo contains no MMC1 reference, so the example and proof do not target Ray's project (MMC1 + 8 KiB CHR-RAM).
What exists toward it: a per-scene `chr: "chr-ram"` override (per-frame CHR sets, budget checked per frame) and `chr: "shared"`; tile budgets are identical for 8 KiB CHR-RAM (2 x 256 tiles), so the
legality verdicts for an MMC1 + CHR-RAM game's art would already hold. Follow-up row (Q5's own rule: "that mapper becomes the example's default"): make the examples default to `chr: "chr-ram"`, add a `proof/nes/mmc1.cfg` +
viewer variant that uploads the `.chr` into CHR-RAM, and add one emulator scene for it. Not a reject.

## Proof log tail (own run)

```
nes_proof            gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=aa38c883049f golden=ok deterministic=ok
nes_proof_tileset    gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=5667fb61dd15 golden=ok deterministic=ok
nes_hero             gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=6da2ad721fad golden=ok deterministic=ok
nes_9_on_a_line      gate_a=ok gate_b=ok gate_c=ok gate_d=ok rom=49d535a6c785 golden=ok deterministic=ok
PASS
... SELFTEST PASS (Y convention confirmed; 8 sprites/line negative control: 40 px mismatch predicted 40 px, Mesen drops the highest OAM index)
```

## Not done / limits

Sandbox security (§3.7) not reviewed, per the card. Real-hardware sign-off (Q9) is a manual item and was not part of this review. Node used here is v22.22.0 (CI uses 24). Python 3.13 for the main run.

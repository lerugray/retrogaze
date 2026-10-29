> SPEC anchor — `docs/spec/CODE-MODE-SPEC.md`@99f902ae (Ray Weiss, §1): "a customized code-drawn graphics generator that can do both console-like and console-legal graphics for games" — NES + SNES first. This card is the ONE independent end review of milestone M1 (NES console-legal, end to end, spec §6).

# RG-M1-REVIEW — Retrogaze code mode M1, the one independent end review (GS co-seat night-s355 t1271)

REPO: lerugray/retrogaze (open source)
WORK_KIND: review only (no product edits)
HEAD UNDER REVIEW: `claude/happy-bardeen-i9nsun`@f5597af5 (Opus 5.5 author, MAIN cloud session, three commits on top of the spec branch)
BASE: `main`@52768093 (the M1-28 baseline commit `5276809`)
SPEC (the bar): `gs/code-mode-spec-s356`@99f902ae `docs/spec/CODE-MODE-SPEC.md` — §1.3 invariants I1-I6, §6 M1 table M1-01..M1-29 and its "Done when", §8 decided (Ray adopted every recommendation, 2026-10-29). The author edited the spec on its branch (records *M1:* build decisions, 22+/12-): judge against the 99f902ae text, and flag any author edit that loosens an M1 test, an invariant or a §8 answer.
CARRIER: `gs/rg-m1-review-s356` = f5597af5 + this card only. Write and push only to the carrier.
REVIEWER: Claude Sonnet 5.5 (different model from the Opus author). Cap 3,600 s inclusive; final 600 s reserved for the report and push.
MOVES: M1 is the first shippable step of code mode; ACCEPT lets the Mac seat merge it to retrogaze main, so a Retrogaze user can draw NES art as code and get console-legal CHR/palette/nametable/OAM bytes proven in an emulator. REJECT names the one fix round.
RULING_ID: Ray s356 2026-10-29 08:37 RULING (code mode M1 start; §8 answers adopted); Mac seat 09:22 row (this review's scope).

## What the reviewer does (all on the exact head, with exact counts)
1. **Suites.** `pip install -r src/requirements-lock.txt` (Python 3.13 if available; say which), then `cd src && RETROGAZE_MOCK=1 python -m pytest tests/ -q`; report passed/skipped/failed and compare with the M1-28 baseline (1465 passed, 6 skipped at 5276809: run the same command on BASE too if time allows, else quote the spec). Node: the mcp-server build + `mcp-server/test-e2e-codemode.sh` (M1-24), and any Node test the CI files run. Every M1-01..M1-25 and M1-29 test exists under the name the spec gives and passes: list any missing, renamed or skipped.
2. **The emulator proof itself (M1-26, M1-27).** Follow `.github/workflows/codemode-proof.yml` and `proof/TOOLS.md`: build Mesen 2 with `proof/tools/build_mesen2.sh` (pinned commit; needs clang, SDL2, zip, .NET SDK 8), run `proof/run_codemode_proof.py`; report ROM sha256 vs `proof/goldens.json`, Mesen exit code, the palette/OAM/nametable compares, the screenshot bijection, and the 9-on-a-line negative fixture. If the toolchain cannot be installed in your environment, say exactly which step failed and report `nes_proof=not` (that is a NOTE, not an author fault). Also run the two "Done when" commands (`build ... --tier legal` exits 0 and writes `out/nes/legal/...`; `rom` produces an `.nes`).
3. **Invariants.** I6: `git diff --name-only origin/main...HEAD` touches no FLUX/Aseprite module or output path; M1-28's `git diff --diff-filter=MD origin/main -- src/tests mcp-server/test-e2e.sh` is empty; no new skip/xfail on an existing test; `test_api_v1_allowlist.py` unchanged and green. Vendored pxl: every file under `third_party/pxl/` hashes to its MANIFEST, `UPSTREAM.md` names `21fee41f7ecce00bc868d7567f24ffd0f3acc8fa`, the MIT `LICENSE` is present, and (network permitting) a fresh clone of upstream claude-pxl at 21fee41 is byte-identical to the vendored tree. I1: the codemode package imports no image model or network client and accepts no raster input (read the code, not only M1-02/03/04). I2/I3/I4/I5: spot-read that determinism, no-silent-pixel-change, provenance and legality are enforced where the spec says.
4. **NES legality spot-check against spec §2.2** (read `codemode/hw/nes.py`, `hw/rules.py`, `encode/nes.py`): 4 BG palettes x 3 colours + the shared backdrop; 16x16 attribute areas; 4 sprite palettes; 8 sprites per scanline; 64 OAM total; the CHR tile budget; no `$0D` exported. Name any rule the code checks differently from the spec.
5. **Provenance (M1-18..M1-20, I4):** iTXt chunk, XMP `algorithmicMedia`, sheet JSON meta, manifest; `verify` and `audit` behave as specified.
6. **Q4 exposure gate:** code mode is off on the public API: `/code/build` 404 without `RETROGAZE_CODE_MODE=1`, 403 with `RETROGAZE_DEMO=1`, no `/v1/code/*` alias (read `codemode_routes.py` + `api.py`, and the M1-22 test).
7. **NOTE only, never a reject:** whether the NES default budget is the spec's NROM default or Ray's project (MMC1 + 8 KiB CHR-RAM); a follow-up row, not a fault.
8. **Out of scope (HELD by the Mac seat to exposure):** the sealed security review of the user-JS sandbox (§3.7). Do not review the sandbox for security; M1-23 passing is enough here.

Severity: S1 = an M1 test missing/failing, an invariant broken, a weakened existing test, a pixel changed silently, or "Done when" not met. S2 = a spec rule implemented differently, or a proof step that does not prove what it claims. S3 = notes. ACCEPT = 0 S1 and 0 S2; ACCEPT-WITH-NOTES = S3 only; REJECT = any S1/S2, with the fix list.

## Never
No product edits, no PR, no merge to main, no `railway up` or any deploy, no GitHub issue or comment (the Q10 upstream issue stays a drafted file for Ray), no contact with anyone. Nothing audible.

## Return
`docs/verification/rg-m1-review-s356/REVIEW.md` on the carrier, line 1 exactly:
`RG-M1-REVIEW ACCEPT|ACCEPT-WITH-NOTES|REJECT head=f5597af5 tests=<passed>/<total> skips=<n> nes_proof=<ran|not> invariants=<ok|list> S1=<n> S2=<n>`
Line 2: `Does a Retrogaze user now get console-legal NES art drawn as code, proven in an emulator: YES / PARTLY / NO`.
Then findings (F1.. with severity, file:line, the spec section), the exact commands and counts, the proof log tail, and the NROM/MMC1 note. Commit and push the carrier.

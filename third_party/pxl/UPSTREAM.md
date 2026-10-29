# Vendored: pxl (claude-pxl)

| | |
|---|---|
| Upstream | https://github.com/crsolver/claude-pxl |
| Commit | `21fee41f7ecce00bc868d7567f24ffd0f3acc8fa` (2026-10-14, "README: lead the gallery with the animated no_magic_night scene") |
| Version | `pxl-pixelart` 0.1.0 |
| License | MIT, copyright 2026 crsolver (see `LICENSE`, kept verbatim) |
| Vendored on | 2026-10-29, for Retrogaze code mode (`docs/spec/CODE-MODE-SPEC.md` §3.6) |
| Local patches | **none** |

Files are byte-identical copies of upstream at that commit:

- `src/`, `bin/`, `types/`
- `scripts/build.js`, `package.json`, `LICENSE`
- `SKILL.md`, `reference.md`, `lighting.md`

`examples/`, `test/`, `docs/` (2.9 MB gallery) and upstream CI are not vendored.

Retrogaze-owned files in this folder, excluded from the manifest:

- `UPSTREAM.md`
- `MANIFEST.sha256`
- `.gitattributes` (`* -text`, so git never rewrites line endings and the hashes stay stable)

`MANIFEST.sha256` is `sha256sum` output for every vendored file, sorted by path (C locale). Its own sha256 is the
"vendored tree hash" that code mode writes into every provenance block. `src/tests/test_codemode_vendor.py` checks
both.

## Upgrading

1. `git clone https://github.com/crsolver/claude-pxl` and check out the new commit.
2. Replace the vendored files listed above (same list, no others).
3. Regenerate the manifest from this folder:

   ```bash
   find . -type f ! -name MANIFEST.sha256 ! -name UPSTREAM.md ! -name .gitattributes | sed 's|^\./||' | LC_ALL=C sort | xargs sha256sum > MANIFEST.sha256
   ```

4. Update the commit, date and version in this file and the commit constant in
   `src/retrogaze/codemode/provenance.py`.
5. Run the full suite, including the code-mode proof job. Outputs built with the old pin keep verifying only against a
   checkout of the old pin (`verify` exits 4 otherwise).

Never patch files in this folder. Retrogaze glue lives in `src/retrogaze/codemode/js/`.

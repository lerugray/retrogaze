"""M1-01: the vendored pxl is byte-identical to its manifest, and its tree hash is in every provenance."""

import hashlib

from retrogaze.codemode.provenance import PXL_COMMIT, vendored_mismatches, vendored_tree_sha256
from retrogaze.codemode.runner import PXL_DIR

from ._codemode import EXAMPLES, build_file


def test_vendored_pxl_matches_manifest():
    assert vendored_mismatches() == []
    upstream = (PXL_DIR / "UPSTREAM.md").read_text()
    assert "21fee41f7ecce00bc868d7567f24ffd0f3acc8fa" in upstream
    assert PXL_COMMIT == "21fee41f7ecce00bc868d7567f24ffd0f3acc8fa"
    lic = (PXL_DIR / "LICENSE").read_text()
    assert "MIT License" in lic and "crsolver" in lic


def test_vendored_tree_hash_is_recorded_in_provenance():
    r = build_file(str(EXAMPLES / "nes_hero.px.js"))
    expected = hashlib.sha256((PXL_DIR / "MANIFEST.sha256").read_bytes()).hexdigest()
    assert vendored_tree_sha256() == expected
    assert r.manifest["provenance"]["renderer"]["vendored_tree_sha256"] == expected
    assert r.manifest["provenance"]["renderer"]["commit"] == PXL_COMMIT

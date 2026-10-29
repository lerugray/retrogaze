"""M1-07: same source + same vendored pxl + same Retrogaze = byte-identical outputs (invariant I2)."""

from pathlib import Path

from retrogaze.codemode.build import build
from retrogaze.codemode.runner import read_art_dir

from ._codemode import EXAMPLES


def test_byte_identical_rebuild():
    files, entry = read_art_dir(Path(EXAMPLES / "nes_proof.px.js"))
    a = build(files, entry)
    b = build(files, entry)
    assert a.verdict == b.verdict == "legal"
    assert set(a.outputs) == set(b.outputs)
    for k in a.outputs:
        assert a.outputs[k] == b.outputs[k], k
    pa, pb = dict(a.manifest["provenance"]), dict(b.manifest["provenance"])
    pa.pop("built_at")
    pb.pop("built_at")
    assert pa == pb
    assert a.manifest["outputs"] == b.manifest["outputs"]

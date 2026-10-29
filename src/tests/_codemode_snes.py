"""Shared helpers for the SNES code-mode tests (docs/spec/CODE-MODE-SPEC.md §6, M2)."""

from __future__ import annotations

import functools
from pathlib import Path

from retrogaze.codemode.build import build
from retrogaze.codemode.runner import read_art_dir

from ._codemode import REPO, TESTS, blame_lines, error_rules, expectations, violations  # noqa: F401

FIXTURES = TESTS / "fixtures" / "codemode" / "snes"
EXAMPLES = REPO / "examples" / "codemode" / "snes"


@functools.lru_cache(maxsize=None)
def build_file(path: str, tier: str = "legal"):
    files, entry = read_art_dir(Path(path))
    return build(files, entry, console="snes", tier=tier)


def build_source(src: str, name: str = "t.px.js", tier: str = "legal"):
    return build({name: src}, name, console="snes", tier=tier)


def scene(result, name: str):
    return next(m for m in result.models if m.name == name)

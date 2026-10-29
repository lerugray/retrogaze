"""Shared helpers for the code-mode tests (docs/spec/CODE-MODE-SPEC.md §6, M1)."""

from __future__ import annotations

import functools
import re
from pathlib import Path

from retrogaze.codemode.build import build
from retrogaze.codemode.runner import read_art_dir

TESTS = Path(__file__).resolve().parent
REPO = TESTS.parents[1]
FIXTURES = TESTS / "fixtures" / "codemode" / "nes"
EXAMPLES = REPO / "examples" / "codemode"
EXPECT = re.compile(r"// expect: (\S+)")


@functools.lru_cache(maxsize=None)
def build_file(path: str, tier: str = "legal"):
    files, entry = read_art_dir(Path(path))
    return build(files, entry, console="nes", tier=tier)


def build_source(src: str, name: str = "t.px.js", tier: str = "legal"):
    return build({name: src}, name, console="nes", tier=tier)


def expectations(path: Path) -> list[tuple[int, str]]:
    return [(i + 1, m.group(1)) for i, line in enumerate(path.read_text().splitlines())
            if (m := EXPECT.search(line))]


def violations(report: dict) -> list[dict]:
    return list(report.get("violations", [])) + [v for s in report.get("scenes", []) for v in s["violations"]]


def error_rules(report: dict) -> set[str]:
    return {v["rule"] for v in violations(report) if v["severity"] == "error"}


def blame_lines(v: dict) -> set[int]:
    out = set()
    for b in v.get("blame", []):
        loc = b.get("loc") or ""
        parts = loc.split(":")
        if len(parts) >= 2 and parts[1].isdigit():
            out.add(int(parts[1]))
    return out

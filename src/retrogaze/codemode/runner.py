"""
Run ``js/rg-build.mjs`` on the vendored pxl in a locked-down Node process.

Sources go in on stdin and results come back on stdout, so the process needs
no file-system writes at all. Node's permission model is a seat belt, not a
security boundary (its docs say so); hosted use also needs OS-level isolation.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath

from .binding import JS_DIR, LOADER

REPO_ROOT = Path(__file__).resolve().parents[3]
PXL_DIR = REPO_ROOT / "third_party" / "pxl"

MIN_NODE = (22, 18)
MAX_FILES = 32
MAX_SOURCE_BYTES = 256 * 1024
BUILD_TIMEOUT_S = 20
ART_SUFFIXES = (".px.js", ".px.ts")


class CodeModeError(Exception):
    """A build that cannot produce pixels (exit code 3), with a CM-* code."""

    def __init__(self, code: str, message: str, loc: str | None = None, errors: list[dict] | None = None):
        super().__init__(message)
        self.code = code
        self.loc = loc
        self.errors = errors or [{"code": code, "message": message, "loc": loc}]


@dataclass
class RawBuild:
    """What rg-build.mjs returned."""

    assets: list[dict]
    scenes: list[dict]
    tilesets: list[dict]
    sheets: list[dict]
    pins: dict | None
    node: str
    logs: list[str] = field(default_factory=list)


def node_binary() -> str:
    node = os.environ.get("RETROGAZE_NODE") or shutil.which("node")
    if not node:
        raise CodeModeError("CM-SANDBOX-EXIT", "code mode needs Node >= 22.18 on PATH (or RETROGAZE_NODE)")
    return node


def node_version(node: str) -> tuple[int, int, int]:
    out = subprocess.run([node, "--version"], capture_output=True, text=True, timeout=10).stdout.strip()
    m = re.match(r"v(\d+)\.(\d+)\.(\d+)", out)
    if not m:
        raise CodeModeError("CM-SANDBOX-EXIT", f"cannot read the Node version from {out!r}")
    return int(m[1]), int(m[2]), int(m[3])


def validate_files(files: dict[str, str], entry: str) -> None:
    """Reject anything that is not a bounded set of art source files (no raster input, ever)."""
    if not files:
        raise CodeModeError("CM-INPUT", "no art files submitted")
    if len(files) > MAX_FILES:
        raise CodeModeError("CM-INPUT", f"at most {MAX_FILES} art files per build (got {len(files)})")
    total = 0
    seen: dict[str, str] = {}
    for name, text in files.items():
        p = PurePosixPath(name.replace("\\", "/"))
        if p.is_absolute() or ".." in p.parts or not name:
            raise CodeModeError("CM-INPUT", f"art file name {name!r} must be a relative path inside the art folder")
        if not name.endswith(ART_SUFFIXES):
            raise CodeModeError(
                "CM-INPUT",
                f"{name!r} is not a .px.js/.px.ts art file; code mode accepts no other input (no images, ever)",
            )
        if not isinstance(text, str):
            raise CodeModeError("CM-INPUT", f"{name!r} must be text")
        if p.name in seen:
            raise CodeModeError("CM-INPUT", f"two art files share the name {p.name!r} ({seen[p.name]}, {name})")
        seen[p.name] = name
        total += len(text.encode("utf-8"))
    if total > MAX_SOURCE_BYTES:
        raise CodeModeError("CM-INPUT", f"art sources exceed {MAX_SOURCE_BYTES // 1024} KiB")
    if entry not in files:
        raise CodeModeError("CM-INPUT", f"entry {entry!r} is not among the submitted files")


def run_loader(files: dict[str, str], entry: str, binding: dict, timeout: float = BUILD_TIMEOUT_S) -> RawBuild:
    validate_files(files, entry)
    node = node_binary()
    if node_version(node)[:2] < MIN_NODE:
        raise CodeModeError("CM-SANDBOX-EXIT", "code mode needs Node >= 22.18 (pxl runs its TypeScript by type stripping)")
    cmd = [
        node,
        "--permission",
        f"--allow-fs-read={PXL_DIR}",
        f"--allow-fs-read={JS_DIR}",
        "--disable-warning=ExperimentalWarning",
        "--max-old-space-size=512",
        str(LOADER),
        "--pxl",
        str(PXL_DIR),
    ]
    payload = json.dumps({"entry": entry, "files": files, "binding": binding})
    try:
        proc = subprocess.run(
            cmd, input=payload, capture_output=True, text=True, timeout=timeout,
            env={"PATH": os.environ.get("PATH", ""), "NODE_OPTIONS": ""},
        )
    except subprocess.TimeoutExpired:
        raise CodeModeError("CM-SANDBOX-TIMEOUT", f"the build ran past its {timeout:g} s limit and was killed")
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        tail = (proc.stderr or "").strip().splitlines()[-3:]
        raise CodeModeError(
            "CM-SANDBOX-EXIT",
            f"the build process exited ({proc.returncode}) without a result" + (f": {' | '.join(tail)}" if tail else ""),
        )
    if out.get("errors"):
        first = out["errors"][0]
        raise CodeModeError(first.get("code", "CM-BUILD"), first.get("message", "build failed"), first.get("loc"), out["errors"])
    return RawBuild(
        assets=out["assets"], scenes=out["scenes"], tilesets=out["tilesets"], sheets=out["sheets"],
        pins=out.get("pins"), node=out["node"], logs=out.get("logs", []),
    )


INCLUDE_RE = re.compile(r"""\binclude\(\s*(["'`])([^"'`]+)\1\s*\)""")


def read_art_dir(entry_path: Path) -> tuple[dict[str, str], str]:
    """The entry file plus every art file it includes (string-literal include() paths, recursively)."""
    entry_path = entry_path.resolve()
    root = entry_path.parent
    files: dict[str, str] = {}
    todo = [entry_path]
    while todo:
        p = todo.pop()
        rel = p.relative_to(root).as_posix() if p.is_relative_to(root) else None
        if rel is None:
            raise CodeModeError("CM-INCLUDE", f"{p.name} is outside the entry file's folder")
        if rel in files:
            continue
        files[rel] = p.read_text(encoding="utf-8")
        if len(files) > MAX_FILES:
            raise CodeModeError("CM-INPUT", f"more than {MAX_FILES} art files reached from {entry_path.name}")
        for m in INCLUDE_RE.finditer(files[rel]):
            target = (p.parent / m.group(2)).resolve()
            if target.is_file():
                todo.append(target)
    return dict(sorted(files.items())), entry_path.relative_to(root).as_posix()

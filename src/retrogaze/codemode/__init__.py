"""
Retrogaze code mode: code-drawn pixel art, checked against console hardware.

A ``.px.js`` drawing (the claude-pxl DSL, vendored in third_party/pxl) is bound
to a console's palette and grid, rendered without any image model, checked at
two tiers (console-like, console-legal), encoded into the console's memory
formats and marked with verifiable provenance. Spec: docs/spec/CODE-MODE-SPEC.md.
"""

from .build import BuildResult, audit, build, build_path, verify

__all__ = ["BuildResult", "audit", "build", "build_path", "verify"]

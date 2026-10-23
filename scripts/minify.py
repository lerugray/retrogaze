#!/usr/bin/env python
"""Minify frontend JS for production. Run before deploy:
    python scripts/minify.py
"""
from pathlib import Path
from jsmin import jsmin

frontend = Path(__file__).resolve().parent.parent / "frontend"
src = frontend / "app.js"
dst = frontend / "app.min.js"

original = src.read_text(encoding="utf-8")
minified = jsmin(original)

# In Docker build, overwrite app.js so HTML doesn't need to change.
# Also write app.min.js for reference.
src.write_text(minified, encoding="utf-8")
dst.write_text(minified, encoding="utf-8")

pct = 100 - len(minified) / len(original) * 100
print(f"app.js  {len(original):,} bytes → {len(minified):,} bytes  ({pct:.0f}% smaller)")

"""
Provenance: every code-mode output says it is code-drawn, and can prove it.

* PNGs carry an ``iTXt`` chunk ``retrogaze:provenance`` (JSON) and an XMP packet
  whose ``Iptc4xmpExt:DigitalSourceType`` is IPTC ``algorithmicMedia``.
* ``manifest.json`` lists the sha256 of every output (binaries cannot carry metadata).
* ``verify`` rebuilds from the recorded sources and compares; ``audit`` checks a
  folder of game assets for valid code-mode provenance.

Only deterministic fields are embedded in files (I2); ``built_at``, the Node version
and the git commit live in the manifest only.
"""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, PngImagePlugin

from .runner import PXL_DIR

SCHEMA = "retrogaze.provenance/1"
PXL_UPSTREAM = "https://github.com/crsolver/claude-pxl"
PXL_COMMIT = "21fee41f7ecce00bc868d7567f24ffd0f3acc8fa"
DIGITAL_SOURCE_TYPE = "http://cv.iptc.org/newscodes/digitalsourcetype/algorithmicMedia"
CHUNK = "retrogaze:provenance"
AUTHORS = ("human", "llm", "mixed", "unknown")
SCHEMA_DIR = Path(__file__).resolve().parent / "schema"


def sha256_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def vendored_tree_sha256() -> str:
    return sha256_bytes((PXL_DIR / "MANIFEST.sha256").read_bytes())


def vendored_mismatches() -> list[str]:
    """Vendored pxl files whose bytes differ from MANIFEST.sha256 (empty when intact)."""
    bad = []
    listed = set()
    for line in (PXL_DIR / "MANIFEST.sha256").read_text().splitlines():
        digest, rel = line.split("  ", 1)
        listed.add(rel)
        p = PXL_DIR / rel
        if not p.is_file() or sha256_bytes(p.read_bytes()) != digest:
            bad.append(rel)
    own = {"MANIFEST.sha256", "UPSTREAM.md", ".gitattributes"}
    for p in PXL_DIR.rglob("*"):
        rel = p.relative_to(PXL_DIR).as_posix()
        if p.is_file() and rel not in listed and rel not in own:
            bad.append(f"{rel} (not in manifest)")
    return bad


def pixels_sha256(rgba: np.ndarray) -> str:
    """Hash of the visible image: RGB of fully transparent pixels does not count."""
    px = np.array(rgba, dtype=np.uint8, copy=True)
    px[px[..., 3] == 0] = 0
    h = hashlib.sha256(f"{px.shape[1]}x{px.shape[0]}:".encode())
    h.update(px.tobytes())
    return h.hexdigest()


def block(*, binding_sha: str, version: str, sources: dict[str, str], entry: str, author: str, console: str,
          tier: str, verdict: str) -> dict:
    """The deterministic provenance block shared by every output of one build."""
    return {
        "schema": SCHEMA,
        "mode": "code",
        "digital_source_type": DIGITAL_SOURCE_TYPE,
        "ai_image_model": None,
        "raster_inputs": [],
        "network_used": False,
        "renderer": {"name": "pxl", "upstream": PXL_UPSTREAM, "commit": PXL_COMMIT,
                     "vendored_tree_sha256": vendored_tree_sha256()},
        "retrogaze": {"version": version, "binding_sha256": binding_sha},
        "source": {"entry": entry, "files": {k: "sha256:" + sha256_bytes(v.encode("utf-8")) for k, v in sorted(sources.items())}},
        "source_author": author,
        "console": console,
        "tier_requested": tier,
        "verdict": verdict,
    }


XMP = (
    '<?xpacket begin="﻿" id="W5M0MpCehiHzreSzNTczkc9d"?>'
    '<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
    '<rdf:Description rdf:about="" xmlns:Iptc4xmpExt="http://iptc.org/std/Iptc4xmpExt/2008-02-29/" '
    f'Iptc4xmpExt:DigitalSourceType="{DIGITAL_SOURCE_TYPE}"/>'
    '</rdf:RDF></x:xmpmeta><?xpacket end="r"?>'
)


def png_bytes(img: Image.Image, prov: dict) -> bytes:
    info = PngImagePlugin.PngInfo()
    info.add_itxt(CHUNK, json.dumps(prov, sort_keys=True, separators=(",", ":")))
    info.add_itxt("XML:com.adobe.xmp", XMP)
    buf = io.BytesIO()
    img.save(buf, format="PNG", pnginfo=info, optimize=False, compress_level=9)
    return buf.getvalue()


def rgba_png(rgba: np.ndarray, prov: dict, what: dict) -> bytes:
    return png_bytes(Image.fromarray(rgba, "RGBA"), {**prov, **what, "pixels_sha256": pixels_sha256(rgba)})


def indexed_png(index: np.ndarray, palette_rgb: list[int], transparent: list[int], prov: dict, what: dict,
                rgba: np.ndarray) -> bytes:
    img = Image.fromarray(index.astype(np.uint8), "P")
    flat = []
    for c in palette_rgb:
        flat += [(c >> 16) & 255, (c >> 8) & 255, c & 255]
    img.putpalette(flat, rawmode="RGB")
    if transparent:
        alpha = bytes(0 if i in transparent else 255 for i in range(len(palette_rgb)))
        img.info["transparency"] = alpha
    return png_bytes(img, {**prov, **what, "pixels_sha256": pixels_sha256(rgba)})


def read_png_provenance(path: Path) -> dict | None:
    try:
        with Image.open(path) as im:
            im.load()
            text = getattr(im, "text", {}) or {}
            raw = text.get(CHUNK)
            return json.loads(raw) if raw else None
    except Exception:
        return None


def png_rgba(path: Path) -> np.ndarray:
    with Image.open(path) as im:
        return np.array(im.convert("RGBA"))


def schema(name: str) -> dict:
    return json.loads((SCHEMA_DIR / name).read_text())

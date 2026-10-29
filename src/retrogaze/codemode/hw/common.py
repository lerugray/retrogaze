"""
Shared pieces of the legality engine: assets, violations, blame, the exact
palette-packing solver with unsat cores, and small image helpers.
"""

from __future__ import annotations

import array
import base64
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from ...palette import rgb_to_lab
from .rules import RULES_BY_ID

# ---------------------------------------------------------------------------
# Colors and images
# ---------------------------------------------------------------------------


def hex_of(rgb: int) -> str:
    return f"#{rgb:06X}"


def rgb_of(hexstr: str) -> int:
    return int(hexstr.lstrip("#")[:6], 16)


def rgb_plane(img: np.ndarray) -> np.ndarray:
    """(h, w) int32 of 0xRRGGBB, with -1 where the pixel is transparent (alpha 0)."""
    rgb = (img[..., 0].astype(np.int32) << 16) | (img[..., 1].astype(np.int32) << 8) | img[..., 2].astype(np.int32)
    return np.where(img[..., 3] > 0, rgb, -1)


def color_set(plane: np.ndarray) -> frozenset[int]:
    u = np.unique(plane)
    return frozenset(int(c) for c in u if c >= 0)


def lightness(rgb: int) -> float:
    return rgb_to_lab((rgb >> 16) & 255, (rgb >> 8) & 255, rgb & 255)[0]


def order_palette(colors) -> list[int]:
    """Deterministic in-palette order: dark to light by CIE L*, ties by value."""
    return sorted(colors, key=lambda c: (round(lightness(c), 6), c))


def pad_to(img: np.ndarray, w: int, h: int) -> np.ndarray:
    if img.shape[1] == w and img.shape[0] == h:
        return img
    out = np.zeros((h, w, 4), dtype=np.uint8)
    out[: img.shape[0], : img.shape[1]] = img
    return out


def round_up(n: int, m: int) -> int:
    return -(-n // m) * m


# ---------------------------------------------------------------------------
# Assets and blame
# ---------------------------------------------------------------------------


@dataclass
class Blame:
    w: int
    h: int
    ops: list[dict]
    map: np.ndarray  # (h, w) int32 index into ops, -1 = no writer

    @classmethod
    def from_json(cls, d: dict | None) -> "Blame | None":
        if not d:
            return None
        a = array.array("i")
        a.frombytes(base64.b64decode(d["map"]))
        return cls(d["w"], d["h"], d["ops"], np.frombuffer(a, dtype=np.int32).reshape(d["h"], d["w"]).copy())


@dataclass
class Asset:
    name: str
    kind: str                       # sprite | anim | scene
    loc: str | None
    exported: bool
    post: bool
    frames: list[np.ndarray]        # rendered RGBA, unpadded, as pxl drew them
    frame_ms: list[int | None]
    layers: list[list[tuple[str, np.ndarray]]] | None
    blame: Blame | None

    @classmethod
    def from_json(cls, d: dict) -> "Asset":
        def img(f):
            return np.frombuffer(base64.b64decode(f["rgba"]), dtype=np.uint8).reshape(f["h"], f["w"], 4).copy()

        layers = None
        if d.get("layers"):
            layers = [[(l["name"], img(l)) for l in fr] for fr in d["layers"]]
        return cls(
            name=d["name"], kind=d["kind"], loc=d.get("loc"), exported=d["exported"], post=d["post"],
            frames=[img(f) for f in d["frames"]], frame_ms=[f["ms"] for f in d["frames"]],
            layers=layers, blame=Blame.from_json(d.get("blame")),
        )

    @property
    def animated(self) -> bool:
        return len(self.frames) > 1

    def writers(self, pixels, frame: int = 0, limit: int = 5) -> list[dict]:
        """Top source locations that painted these pixels (asset coordinates)."""
        pixels = list(pixels)
        if not pixels:
            return []
        if frame != 0 or self.blame is None:
            return [{"loc": self.loc, "op": f"{self.kind} '{self.name}' (frame {frame})", "pixels": len(pixels)}]
        b = self.blame
        c: Counter = Counter()
        for x, y in pixels:
            if 0 <= x < b.w and 0 <= y < b.h:
                i = int(b.map[y, x])
                if i >= 0:
                    c[i] += 1
        out = []
        for i, n in c.most_common(limit):
            op = b.ops[i]
            out.append({"loc": op.get("loc") or self.loc, "op": op["label"], "pixels": n})
        return out or [{"loc": self.loc, "op": f"{self.kind} '{self.name}'", "pixels": len(pixels)}]


# ---------------------------------------------------------------------------
# Violations and reports
# ---------------------------------------------------------------------------


@dataclass
class Violation:
    rule: str
    message: str
    severity: str = "error"          # error | warning | info
    asset: str | None = None
    scene: str | None = None
    frame: int | None = None
    where: dict = field(default_factory=dict)
    found: object = None
    limit: object = None
    colors: list[str] = field(default_factory=list)
    pixels: list[list[int]] = field(default_factory=list)
    blame: list[dict] = field(default_factory=list)
    hint: str | None = None

    @property
    def tier(self) -> str:
        r = RULES_BY_ID.get(self.rule)
        return r.tier if r else "build"

    @property
    def scope(self) -> str:
        r = RULES_BY_ID.get(self.rule)
        return r.scope if r else "image"

    def to_dict(self) -> dict:
        d = {
            "rule": self.rule, "tier": self.tier, "scope": self.scope, "severity": self.severity,
            "message": self.message,
        }
        for k in ("asset", "scene", "frame", "found", "limit", "hint"):
            v = getattr(self, k)
            if v is not None:
                d[k] = v
        if self.where:
            d["where"] = self.where
        if self.colors:
            d["colors"] = self.colors
        if self.pixels:
            d["pixels"] = self.pixels[:64]
            d["pixel_count"] = len(self.pixels)
        if self.blame:
            d["blame"] = self.blame
        return d


def blame_for(asset: Asset, pixels, frame: int = 0) -> tuple[list[list[int]], list[dict]]:
    px = [[int(x), int(y)] for x, y in pixels]
    return px, asset.writers(((x, y) for x, y in px), frame)


# ---------------------------------------------------------------------------
# Palette packing: exact, with a MILP fallback and minimal unsat cores
# ---------------------------------------------------------------------------


class PackBudget(Exception):
    pass


def _maximal(sets: list[frozenset]) -> list[frozenset]:
    uniq = sorted(set(s for s in sets if s), key=lambda s: (-len(s), sorted(s)))
    keep: list[frozenset] = []
    for s in uniq:
        if not any(s <= k for k in keep):
            keep.append(s)
    return keep


def _backtrack(sets: list[frozenset], P: int, K: int, budget: int) -> list[set] | None:
    pals: list[set] = []
    nodes = [0]

    def go(i: int) -> bool:
        nodes[0] += 1
        if nodes[0] > budget:
            raise PackBudget
        if i == len(sets):
            return True
        s = sets[i]
        tried: set[frozenset] = set()
        for p in pals:
            key = frozenset(p)
            if key in tried:
                continue
            tried.add(key)
            if len(p | s) <= K:
                added = s - p
                p |= s
                if go(i + 1):
                    return True
                p -= added
        if len(pals) < P:
            pals.append(set(s))
            if go(i + 1):
                return True
            pals.pop()
        return False

    return [set(p) for p in pals] if go(0) else None


def _milp(sets: list[frozenset], P: int, K: int) -> list[set] | None:
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import lil_matrix

    colors = sorted(set().union(*sets))
    ci = {c: i for i, c in enumerate(colors)}
    S, C = len(sets), len(colors)
    nx, ny = S * P, C * P
    X = lambda s, p: s * P + p  # noqa: E731
    Y = lambda c, p: nx + c * P + p  # noqa: E731
    rows = S + sum(len(s) for s in sets) * P + P
    A = lil_matrix((rows, nx + ny))
    lo, hi = [], []
    r = 0
    for s in range(S):
        for p in range(P):
            A[r, X(s, p)] = 1
        lo.append(1); hi.append(1); r += 1
    for s, st in enumerate(sets):
        for c in st:
            for p in range(P):
                A[r, Y(ci[c], p)] = 1
                A[r, X(s, p)] = -1
                lo.append(0); hi.append(np.inf); r += 1
    for p in range(P):
        for c in range(C):
            A[r, Y(c, p)] = 1
        lo.append(0); hi.append(K); r += 1
    res = milp(
        c=np.zeros(nx + ny), constraints=LinearConstraint(A.tocsr(), lo, hi),
        integrality=np.ones(nx + ny), bounds=Bounds(0, 1),
    )
    if res.status != 0 or res.x is None:
        return None
    pals = [{colors[c] for c in range(C) if res.x[Y(c, p)] > 0.5} for p in range(P)]
    return [p for p in pals if p]


def pack_palettes(sets, P: int, K: int, node_budget: int = 200_000) -> list[set] | None:
    """Find at most P palettes of at most K colors covering every set, or None if impossible."""
    work = _maximal([frozenset(s) for s in sets])
    if any(len(s) > K for s in work):
        return None
    if not work:
        return []
    try:
        return _backtrack(work, P, K, node_budget)
    except PackBudget:
        return _milp(work, P, K)


def unsat_core(sets: list[frozenset], P: int, K: int) -> list[int]:
    """Indices of a minimal subset of ``sets`` that still cannot be packed (deletion filter)."""
    idx = [i for i, s in enumerate(sets) if s]
    core = list(idx)
    for i in list(idx):
        trial = [j for j in core if j != i]
        if pack_palettes([sets[j] for j in trial], P, K) is None:
            core = trial
    return core


def assign_palette(colors: frozenset, palettes: list[list[int]]) -> int:
    for i, p in enumerate(palettes):
        if colors <= set(p):
            return i
    return -1

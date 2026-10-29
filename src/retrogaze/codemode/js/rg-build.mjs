// Retrogaze code-mode loader around the vendored pxl core (third_party/pxl).
//
// Reads one JSON object on stdin: { entry, files: {name: source}, binding }.
// Writes one JSON object on stdout: rendered assets (RGBA), per-pixel blame, rg.scene manifests.
// It never touches the file system: art files come from the in-memory map, outputs go to stdout.
// Retrogaze owns this file; pxl itself is used unmodified through its public core exports.
import { stripTypeScriptTypes } from "node:module";
import { basename, dirname, isAbsolute, join, posix } from "node:path";
import { pathToFileURL } from "node:url";
import * as vm from "node:vm";

const argv = process.argv.slice(2);
const pxlDir = argv[argv.indexOf("--pxl") + 1];
const core = await import(pathToFileURL(join(pxlDir, "src", "core", "index.ts")).href);
const { Project, PxError, wrap, gridRows, parseHex, TRANSPARENT, OPS } = core;

const ROOT = "/art/";
const DEFINE_TIMEOUT_MS = 5000;

class CMError extends PxError {
  constructor(code, detail, loc) {
    super(`[${code}] ${detail}`, loc);
    this.code = code;
  }
}

function codeOf(message) {
  const m = /\[(CM-[A-Z0-9-]+)\]/.exec(message);
  return m ? m[1] : "CM-BUILD";
}

function errorJson(e) {
  const err = e instanceof PxError ? e : wrap(e);
  return { code: err.code ?? codeOf(err.message), message: err.message, loc: err.loc ?? null };
}

async function readStdin() {
  const chunks = [];
  for await (const c of process.stdin) chunks.push(c);
  return Buffer.concat(chunks).toString("utf8");
}

// ---------------------------------------------------------------- colors

function hex6(c) {
  return "#" + [(c >>> 24) & 255, (c >>> 16) & 255, (c >>> 8) & 255].map((v) => v.toString(16).padStart(2, "0")).join("").toUpperCase();
}

function lab(c) {
  const lin = (v) => { v /= 255; return v <= 0.04045 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
  const r = lin((c >>> 24) & 255), g = lin((c >>> 16) & 255), b = lin((c >>> 8) & 255);
  const x = (0.4124564 * r + 0.3575761 * g + 0.1804375 * b) / 0.95047;
  const y = 0.2126729 * r + 0.7151522 * g + 0.072175 * b;
  const z = (0.0193339 * r + 0.119192 * g + 0.9503041 * b) / 1.08883;
  const f = (t) => (t > (6 / 29) ** 3 ? Math.cbrt(t) : t / (3 * (6 / 29) ** 2) + 4 / 29);
  return [116 * f(y) - 16, 500 * (f(x) - f(y)), 200 * (f(y) - f(z))];
}

// ---------------------------------------------------------------- main

const input = JSON.parse(await readStdin());
const B = input.binding;
const legal = new Map(B.colors.map((h) => [parseHex(h), h.toUpperCase()]));
const legalLab = [...legal.keys()].map((c) => [c, lab(c)]);
const logs = [];
const out = { ok: false, node: process.version, errors: [], logs, assets: [], scenes: [], tilesets: [], sheets: [], pins: null };

function nearestHint(c) {
  const l = lab(c);
  let best = null, bd = Infinity;
  for (const [k, kl] of legalLab) {
    const d = (kl[0] - l[0]) ** 2 + (kl[1] - l[1]) ** 2 + (kl[2] - l[2]) ** 2;
    if (d < bd) { bd = d; best = k; }
  }
  if (best === null) return "";
  const h = legal.get(best);
  const call = B.color_calls?.[h];
  return ` nearest legal color: ${h}${call ? ` = ${call}` : ""}`;
}

const files = new Map();
for (const [name, src] of Object.entries(input.files)) {
  const n = posix.normalize(name.replace(/\\/g, "/"));
  if (n.startsWith("..") || isAbsolute(n)) throw new Error(`bad art file name '${name}'`);
  files.set(ROOT + n, src);
}

const p = new Project({ trace: true });
const env = p.env();
const loc = () => p.callerLoc();

// Strict color checks: any "#hex" a call receives must be a console color with binary alpha.
function checkColorString(s, where) {
  if (typeof s !== "string" || !/^#[0-9a-fA-F]{3,8}$/.test(s)) return;
  const c = parseHex(s);
  if (c === undefined || c === TRANSPARENT) return;
  if ((c & 255) !== 255) throw new CMError("CM-STRICT-ALPHA", `${where}: color '${s}' has partial alpha; console pixels are opaque or transparent`, loc());
  if (!legal.has(c)) throw new CMError("CM-STRICT-COLOR", `${where}: '${s}' is not a ${B.display_name} color;${nearestHint(c)}`, loc());
}

function checkDeep(v, where, depth = 0) {
  if (depth > 4 || v === null || v === undefined) return;
  if (typeof v === "string") return checkColorString(v, where);
  if (Array.isArray(v)) return v.forEach((x) => checkDeep(x, where, depth + 1));
  if (typeof v === "object" && !v.__op && !v.__layer) for (const x of Object.values(v)) checkDeep(x, where, depth + 1);
}

const disabled = {
  lighting: "CM-STRICT-LIGHTING", lamp: "CM-STRICT-LIGHTING", bump: "CM-STRICT-LIGHTING", normals: "CM-STRICT-LIGHTING",
};
for (const [name, code] of Object.entries(disabled)) {
  env[name] = () => { throw new CMError(code, `${name}() is not available in code mode: pxl lighting multiplies RGB and leaves the console palette`, loc()); };
}
for (const name of [...OPS, "clip", "glow", "sprite", "scene", "anim", "layer", "frame"]) {
  if (disabled[name]) continue;
  const original = env[name];
  env[name] = (...a) => {
    if (name === "glow") {
      const o = a[1];
      if (!o || typeof o !== "object" || !o.ramp)
        throw new CMError("CM-STRICT-GLOW", "glow() colour mode leaves the console palette; use glow(keys, { ramp: n })", loc());
    }
    checkDeep(a, name);
    return original(...a);
  };
}
const originalUse = env.use;
env.use = (pl) => {
  if (!Array.isArray(pl)) throw new CMError("CM-STRICT-USE", `use(${JSON.stringify(pl)}): built-in palettes are not console colors; colors come from ${B.color_fn}()`, loc());
  pl.forEach((c, i) => typeof c === "string" && checkColorString(c, `use() entry ${i}`));
  return originalUse(pl);
};
const originalPal = env.pal;
env.pal = (aliases) => {
  if (aliases && typeof aliases === "object")
    for (const [k, v] of Object.entries(aliases)) if (typeof v === "string" && [...v].length > 1) checkColorString(v, `pal key '${k}'`);
  return originalPal(aliases);
};

// Console color helpers.
if (B.console === "nes") {
  env.nes = (byte) => {
    if (!Number.isInteger(byte) || byte < 0 || byte > 0x3f) throw new CMError("CM-NES-RANGE", `nes(${JSON.stringify(byte)}): a 2C02 color byte is an integer 0x00-0x3F`, loc());
    if (byte === 0x0d) throw new CMError("CM-NES-0D", "nes(0x0D) is forbidden: it is 'blacker than black' and upsets some TVs; use nes(0x0F)", loc());
    return B.nes_bytes[String(byte)];
  };
}

// rg: limits, grid and the hardware scene manifest.
const scenes = [], tilesets = [];
let pins = null;
const rg = {
  console: B.console, tier: B.tier, tile: B.rg.tile, area: B.rg.area, screen: Object.freeze({ ...B.rg.screen }),
  limits: Object.freeze({ ...B.rg.limits }), colors: Object.freeze([...B.colors]),
  scene(name, spec) {
    const l = loc();
    if (typeof name !== "string" || !name) throw new CMError("CM-SCENE", "rg.scene needs a name string first", l);
    if (!spec || typeof spec !== "object") throw new CMError("CM-SCENE", `rg.scene('${name}', { ... }) needs a spec object`, l);
    const allowed = B.scene_keys;
    for (const k of Object.keys(spec)) if (!allowed.includes(k)) throw new CMError("CM-SCENE", `rg.scene '${name}': unknown key '${k}' (allowed: ${allowed.join(", ")})`, l);
    if (scenes.some((s) => s.name === name)) throw new CMError("CM-SCENE", `rg.scene '${name}' is already defined`, l);
    checkDeep(spec, `rg.scene '${name}'`);
    scenes.push({ name, spec: JSON.parse(JSON.stringify(spec)), loc: l });
  },
  tileset(name, opts = {}) {
    const l = loc();
    if (typeof name !== "string" || !name) throw new CMError("CM-SCENE", "rg.tileset needs an asset name", l);
    tilesets.push({ name, opts: JSON.parse(JSON.stringify(opts)), loc: l });
  },
  palettes(spec) {
    checkDeep(spec, "rg.palettes");
    pins = JSON.parse(JSON.stringify(spec));
  },
};
env.rg = Object.freeze(rg);

const quiet = (...a) => { if (logs.length < 100) logs.push(a.map(String).join(" ")); };
const ctx = vm.createContext({ ...env, console: { log: quiet, info: quiet, warn: quiet, error: quiet } });
vm.runInContext(`(() => {
  const no = (n) => () => { throw new Error("[CM-DETERMINISM] " + n + " is not available in code mode: builds must be reproducible (use rng(seed))"); };
  Object.defineProperty(Math, "random", { value: no("Math.random") });
  const D = Date;
  globalThis.Date = new Proxy(D, { construct: no("Date"), apply: no("Date"), get: (t, k) => (k === "now" ? no("Date.now") : t[k]) });
})()`, ctx);

// Default active palette, set before any user code runs.
if (B.default_palette === "colors") originalUse(B.colors);
else originalUse([]);

function compile(code, file) {
  return /\.[cm]?ts$/.test(file) ? stripTypeScriptTypes(code, { mode: "strip" }) : code;
}

const stack = [];
const run = (abs) => {
  if (stack.includes(abs)) throw new PxError(`include cycle: ${[...stack, abs].join(" -> ")}`);
  const code = files.get(abs);
  if (code === undefined) throw new CMError("CM-INCLUDE", `include('${abs.slice(ROOT.length)}'): not among the submitted art files`, p.callerLoc());
  p.addFile(abs);
  stack.push(abs);
  try {
    vm.runInContext(compile(code, abs), ctx, { filename: abs, timeout: DEFINE_TIMEOUT_MS });
  } catch (e) {
    const err = wrap(e, (s) => p.locFromStack(s));
    if (!err.loc && typeof e === "object" && e && "stack" in e) {
      const m = new RegExp(abs.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ":(\\d+)").exec(String(e.stack));
      if (m) { err.loc = `${basename(abs)}:${m[1]}`; err.message = err.format(); }
    }
    if (/Script execution timed out/.test(err.message)) {
      err.message = `[CM-SANDBOX-TIMEOUT] art file definitions took longer than ${DEFINE_TIMEOUT_MS} ms: ${err.message}`;
    }
    throw err;
  } finally {
    stack.pop();
  }
};
p.includeHook = (path) => {
  const cur = stack[stack.length - 1];
  const target = posix.normalize(posix.join(posix.dirname(cur), path.replace(/\\/g, "/")));
  if (!target.startsWith(ROOT)) throw new CMError("CM-INCLUDE", `include('${path}') leaves the art folder`, p.callerLoc());
  run(target);
};

let defined = true;
try {
  run(ROOT + posix.normalize(input.entry.replace(/\\/g, "/")));
} catch (e) {
  out.errors.push(errorJson(e));
  defined = false;
}

// ---------------------------------------------------------------- blame

const sourceByShort = new Map([...files].map(([abs, src]) => [basename(abs), src]));

function locLine(l) {
  const m = /^(.*):(\d+):(\d+)$/.exec(l ?? "") ?? /^(.*):(\d+)$/.exec(l ?? "");
  return m ? { file: m[1], line: Number(m[2]) } : null;
}

// Find the grid literal a trace step drew, so each grid row maps to its own source line.
function gridRowLocs(label, at) {
  const m = /^grid\((-?[\d.]+), (-?[\d.]+), ([\s\S]*)\)$/.exec(label);
  const where = locLine(at);
  if (!m || !where) return null;
  const src = sourceByShort.get(where.file);
  if (src === undefined) return null;
  let firstRow = null, single = null;
  if (m[3].startsWith("`")) firstRow = m[3].slice(1).replace(/…`$/, "");
  else { try { single = JSON.parse(m[3]); } catch { return null; } }
  const lineStarts = [0];
  for (let i = 0; i < src.length; i++) if (src[i] === "\n") lineStarts.push(i + 1);
  const lineOf = (off) => { let lo = 0, hi = lineStarts.length - 1; while (lo < hi) { const mid = (lo + hi + 1) >> 1; if (lineStarts[mid] <= off) lo = mid; else hi = mid - 1; } return lo; };
  const from = lineStarts[Math.max(0, where.line - 1)] ?? 0;
  const literal = single !== null ? null : /`([^`$]*)`/g;
  if (literal) {
    literal.lastIndex = from;
    let lm;
    while ((lm = literal.exec(src))) {
      const content = lm[1];
      const rows = gridRows(content);
      if (rows.length && rows[0] === firstRow.trim()) {
        const raw = content.replace(/\r/g, "").split("\n");
        let lead = 0;
        while (lead < raw.length && raw[lead].trim() === "") lead++;
        const startLine = lineOf(lm.index + 1);
        return rows.map((_, r) => {
          const ri = lead + r, text = raw[ri];
          const col = text.length - text.trimStart().length + 1 + (ri === 0 ? lm.index + 1 - lineStarts[startLine] : 0);
          return { loc: `${where.file}:${startLine + ri + 1}:${col}`, row: rows[r] };
        });
      }
    }
    return null;
  }
  const quoted = JSON.stringify(single);
  const off = src.indexOf(quoted, from);
  if (off < 0) return null;
  const ln = lineOf(off);
  return gridRows(single).map((row) => ({ loc: `${where.file}:${ln + 1}:${off - lineStarts[ln] + 1}`, row }));
}

function geometry(label, w, h) {
  // Returns new-index -> old-index for same-size geometric post-processing steps.
  const half = (n) => Math.floor(n / 2);
  if (label === "mirror x") return (i) => { const x = i % w, y = (i / w) | 0; return x >= w - half(w) ? y * w + (w - 1 - x) : i; };
  if (label === "mirror y") return (i) => { const x = i % w, y = (i / w) | 0; return y >= h - half(h) ? (h - 1 - y) * w + x : i; };
  const fl = /^flip (x|y|xy)$/.exec(label) ?? (label === "rot 180" ? [0, "xy"] : null);
  if (fl) {
    const fx = fl[1].includes("x"), fy = fl[1].includes("y");
    return (i) => { const x = i % w, y = (i / w) | 0; return (fy ? h - 1 - y : y) * w + (fx ? w - 1 - x : x); };
  }
  return null;
}

function computeBlame(def, trace) {
  if (!trace || !trace.frames.length) return null;
  const ops = [], ids = new Map();
  const opId = (label, at) => {
    const k = label + "\u0000" + (at ?? "");
    let i = ids.get(k);
    if (i === undefined) { i = ops.length; ops.push({ label, loc: at ?? def.loc ?? null }); ids.set(k, i); }
    return i;
  };
  let w = 0, h = 0, img = null, bl = null;
  if (def.opts.base) {
    try {
      const b = p.image(def.opts.base);
      w = b.w; h = b.h; img = b.data.slice();
      const id = opId(`base '${def.opts.base}'`, def.loc);
      bl = new Int32Array(w * h).fill(-1);
      for (let i = 0; i < img.length; i++) if (img[i] !== TRANSPARENT) bl[i] = id;
    } catch { img = null; }
  }
  for (const f of trace.frames) {
    const id = opId(f.label, f.loc);
    let next;
    if (f.full) next = f.full;
    else { next = img.slice(); for (let j = 0; j < f.changes.length; j += 2) next[f.changes[j]] = f.changes[j + 1]; }
    if (!img) {
      bl = new Int32Array(f.w * f.h).fill(-1);
      const painted = [];
      for (let i = 0; i < next.length; i++) if (next[i] !== TRANSPARENT) { bl[i] = id; painted.push(i); }
      if (f.label.startsWith("grid(") && painted.length) refineGrid(f, painted, bl, opId, f.w);
    } else if (f.w !== w || f.h !== h) {
      const nb = new Int32Array(f.w * f.h).fill(-1);
      let src = null;
      if (/^outline8? /.test(f.label)) src = (x, y) => [x - 1, y - 1];
      else if (f.label === "crop") {
        let bx = Infinity, by = Infinity;
        for (let i = 0; i < img.length; i++) if (img[i] !== TRANSPARENT) { bx = Math.min(bx, i % w); by = Math.min(by, (i / w) | 0); }
        if (bx !== Infinity) src = (x, y) => [x + bx, y + by];
      } else if (f.label === "rot 90") src = (x, y) => [y, h - 1 - x];
      else if (f.label === "rot 270") src = (x, y) => [w - 1 - y, x];
      for (let y = 0; y < f.h; y++)
        for (let x = 0; x < f.w; x++) {
          const i = y * f.w + x, c = next[i];
          if (c === TRANSPARENT) continue;
          if (src) {
            const [sx, sy] = src(x, y);
            if (sx >= 0 && sy >= 0 && sx < w && sy < h && img[sy * w + sx] === c) { nb[i] = bl[sy * w + sx]; continue; }
          }
          nb[i] = id;
        }
      bl = nb;
    } else {
      const geo = geometry(f.label, w, h);
      if (geo) {
        const nb = new Int32Array(w * h);
        for (let i = 0; i < nb.length; i++) {
          const j = geo(i);
          nb[i] = next[i] === TRANSPARENT ? -1 : img[j] === next[i] ? bl[j] : id;
        }
        bl = nb;
      } else {
        const changed = [];
        for (let i = 0; i < next.length; i++) if (next[i] !== img[i]) { bl[i] = next[i] === TRANSPARENT ? -1 : id; if (next[i] !== TRANSPARENT) changed.push(i); }
        if (f.label.startsWith("grid(") && changed.length) refineGrid(f, changed, bl, opId, w);
      }
    }
    img = next; w = f.w; h = f.h;
  }
  return { w, h, ops, map: Buffer.from(bl.buffer, bl.byteOffset, bl.byteLength).toString("base64") };
}

function refineGrid(f, changed, bl, opId, w) {
  const rows = gridRowLocs(f.label, f.loc);
  if (!rows) return;
  const marks = [];
  rows.forEach((r, ry) => [...r.row].forEach((ch, rx) => { if (ch !== "." && ch !== " ") marks.push([rx, ry]); }));
  if (!marks.length || marks.length * changed.length > 4_000_000) return;
  const set = new Set(marks.map(([x, y]) => y * 65536 + x));
  const px0 = changed[0] % w, py0 = (changed[0] / w) | 0;
  for (const [mx, my] of marks) {
    const dx = px0 - mx, dy = py0 - my;
    if (changed.every((i) => set.has((((i / w) | 0) - dy) * 65536 + ((i % w) - dx)))) {
      for (const i of changed) {
        const ry = ((i / w) | 0) - dy;
        bl[i] = opId(`grid row ${ry}`, rows[ry].loc);
      }
      return;
    }
  }
}

// ---------------------------------------------------------------- render everything

function rgba(img) {
  const b = Buffer.alloc(img.w * img.h * 4);
  for (let i = 0; i < img.data.length; i++) {
    const c = img.data[i];
    b[4 * i] = (c >>> 24) & 255; b[4 * i + 1] = (c >>> 16) & 255; b[4 * i + 2] = (c >>> 8) & 255; b[4 * i + 3] = c & 255;
  }
  return b.toString("base64");
}

function buildAll() {
const wanted = new Set(p.exported());
for (const s of scenes) {
  for (const k of ["bg", "bg1", "bg2", "bg3"]) if (typeof s.spec[k] === "string") wanted.add(s.spec[k]);
  for (const o of s.spec.obj ?? []) if (Array.isArray(o) && typeof o[0] === "string") wanted.add(o[0]);
}
for (const t of tilesets) wanted.add(t.name);

let pixels = 0;
for (const name of p.order) {
  if (!wanted.has(name)) continue;
  const def = p.assets.get(name);
  try {
    const b = p.build(name);
    const frames = b.anim ? p.frames(name) : [{ img: b.img, ms: null }];
    const hidden = new Set(def.items.filter((v) => v && v.__layer && v.opts.hidden).map((v) => v.name));
    const layered = b.layers.some((l) => /^obj:\d+$/.test(l.name));
    const layerFrames = [];
    if (layered) {
      let t = 0;
      for (const f of frames) {
        layerFrames.push(p.build(name, 0, t).layers.filter((l) => !hidden.has(l.name)).map((l) => ({ name: l.name, w: l.img.w, h: l.img.h, rgba: rgba(l.img) })));
        t += f.ms ?? 0;
      }
    }
    for (const f of frames) pixels += f.img.w * f.img.h;
    if (pixels > B.max_pixels) throw new CMError("CM-SANDBOX-SIZE", `rendered output exceeds ${B.max_pixels} pixels`, def.loc);
    const o = def.opts;
    out.assets.push({
      name, kind: def.kind, loc: def.loc ?? null, exported: !name.startsWith("_"),
      post: !!(o.mx || o.my || o.flip || o.rot || o.outline || o.outline8 || o.crop || o.swap),
      w: b.img.w, h: b.img.h,
      frames: frames.map((f) => ({ ms: f.ms, w: f.img.w, h: f.img.h, rgba: rgba(f.img) })),
      layers: layered ? layerFrames : null,
      blame: computeBlame(def, b.trace),
    });
  } catch (e) {
    out.errors.push({ ...errorJson(e), asset: name });
  }
}
for (const s of p.sheets) {
  try {
    out.sheets.push({ name: s.name, loc: s.loc ?? null, entries: p.sheetNames(s), cols: s.opts.cols ?? null, pad: s.opts.pad ?? 0 });
  } catch (e) {
    out.errors.push({ ...errorJson(e), sheet: s.name });
  }
}
}

if (defined) buildAll();
out.scenes = scenes;
out.tilesets = tilesets;
out.pins = pins;
out.ok = out.errors.length === 0;
process.stdout.write(JSON.stringify(out));

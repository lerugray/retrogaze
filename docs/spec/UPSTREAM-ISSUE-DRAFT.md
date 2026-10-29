# Draft: upstream issue for crsolver/claude-pxl (spec §8 Q10)

**Status: draft only. Not posted.** Ray decides whether and when to open it (Q10: "after M1 works, open one courteous
upstream issue"). M1 is merged and M2 works on `gs/code-mode-m2`, so the note below is ready. Nothing in Retrogaze
depends on upstream accepting any of it: code mode stays on the vendored pin (`third_party/pxl` at
`21fee41f7ecce00bc868d7567f24ffd0f3acc8fa`, unmodified) either way.

---

**Title:** Retrogaze builds console-legal NES/SNES art on pxl; would an optional palette-lock hook be welcome?

Hi, and thanks for pxl. It is the most pleasant way we have found to draw pixel art as code.

**What we built on it.** [Retrogaze](https://github.com/lerugray/retrogaze) (MIT) has a "code mode" that uses pxl
to draw game art that has to run on real consoles. A `.px.js` file is bound to a console (NES or SNES so far). The
rendered pixels are checked against the hardware rules (NES: the 2C02 palette, 16x16 attribute areas, 3 colors per
sprite, 8 sprites per line; SNES mode 1: 15-bit colors, 15 colors per 4bpp tile and per OBJ, OBSEL sizes, 32 OBJs
and 34 slivers per line). The art is then exported as the bytes the console loads, and those bytes are run in an
emulator (Mesen 2) to prove that the screen shows exactly the art. Every output records that it was drawn by code,
with the pxl commit and a hash of the source, so it can be rebuilt and verified.

**How we use pxl.** We vendor it unmodified at `21fee41` (MIT notice kept) and use only the core exports. Our own
loader creates a `Project({ trace: true })`, extends `p.env()` with a console binding (`nes(byte)`,
`snes(r, g, b)`, `rg.scene(...)`), runs the art files from an in-memory map through `includeHook`, and turns the
`Trace` steps into a per-pixel "last writer" map. That map lets every rule violation name the source line that
painted the bad pixels (for grid strings, the exact row). It works very well.

**One thing that would let us delete code.** To keep art inside a console palette, we wrap every DSL op and check
each hex string argument, and we disable the ops that leave the palette (`lighting`, `lamp`, `bump`, `normals`, and
`glow` without `ramp`). That catches most mistakes at definition time with a `file:line:col`. A color painted from
inside a function item (`(c) => c.px(3, 3, "#123456")`) still gets through, though, and is only caught after
rendering, by our validator.

Would you be open to an optional, off-by-default hook in the core, for example:

```js
new Project({
  // called for every color a definition or a canvas call resolves; return a message to reject it
  checkColor: (packed /* 0xRRGGBBAA */) => (isConsoleColor(packed) ? null : "not an NES color"),
})
```

pxl would throw its usual `PxError` with the caller's location when the hook rejects a color. With that hook our
wrappers could shrink to one line. Other people who want "palette-locked" pxl (fixed 16-color palettes, game jams
with palette rules) would get it for free, and existing behavior would not change.

We are happy to send a PR with tests if this sounds reasonable, or to adapt to whatever shape you prefer. If you
would rather keep the core as it is, that is completely fine too. We will keep using the pinned version.

Thanks again for pxl.

// nes_proof.px.js: the NES proof scene for Retrogaze code mode (docs/spec/CODE-MODE-SPEC.md §5).
// A code-drawn 16x16 metatile set fills a 256x240 background in all 4 BG palettes,
// and a code-drawn 16x16 hero (4 hardware sprites, 2 sprite palettes) stands on it.
// No image model anywhere: every pixel below comes from these lines.

pal({
  k: nes(0x0F),                                  // black: outlines (sprites)
  G: nes(0x2A), g: nes(0x1A), D: nes(0x17),      // BG palette: grass and dirt
  R: nes(0x16), r: nes(0x06), M: nes(0x36),      // BG palette: brick and mortar
  W: nes(0x31), w: nes(0x11), v: nes(0x01),      // BG palette: water
  C: nes(0x30), c: nes(0x10), q: nes(0x00),      // BG palette: cloud and stone
  h: nes(0x16), s: nes(0x27),                    // hero top: dark red, gold
  b: nes(0x12), l: nes(0x21),                    // hero bottom: blue, light blue
})

// ---- metatiles: each 16x16 is one attribute area, 3 colors + the sky backdrop ----

sprite("_grass", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "D"),
  rect(0, 0, 16, 4, "G"),
  dither(0, 4, 16, 2, "G", "g", 0.5),
  noise(0, 7, 16, 9, "g", 0.08, 3))

sprite("_dirt", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "D"),
  noise(0, 0, 16, 16, "g", 0.06, 5))

sprite("_brick", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "R"),
  hline(0, 7, 16, "M"), hline(0, 15, 16, "M"),
  vline(7, 0, 7, "M"), vline(3, 8, 7, "M"), vline(11, 8, 7, "M"),
  hline(0, 6, 7, "r"), hline(8, 6, 7, "r"), hline(0, 14, 3, "r"), hline(4, 14, 7, "r"), hline(12, 14, 4, "r"))

sprite("_water", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "w"),
  hline(1, 3, 5, "W"), hline(9, 7, 5, "W"), hline(3, 11, 5, "W"),
  hline(6, 4, 3, "v"), hline(13, 8, 3, "v"), hline(0, 12, 3, "v"))

sprite("_cloud", { w: 16, h: 16 },
  circ(5, 9, 4, "C"), circ(10, 8, 5, "C"),
  hline(2, 13, 13, "c"), px(13, 12, "c"), px(3, 12, "c"))

sprite("_stone", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "c"),
  box(0, 0, 16, 16, "q"), hline(1, 8, 14, "q"), vline(8, 1, 7, "q"),
  px(3, 3, "C"), px(11, 11, "C"))

group("sky", ["_cloud"])

// ---- the level: one character per metatile, 16 x 15 = 256 x 240 ----

scene("level", { w: 256, h: 240 },
  tilemap(`
................
................
..cc........cc..
.ccc.......ccc..
................
................
.........bbbb...
................
...bbb..........
................
.s............s.
gggggggggggggggg
dddddddddddddddd
wwwwwwwwwwwwwwww
wwwwwwwwwwwwwwww`, { map: { g: "_grass", d: "_dirt", b: "_brick", c: "_cloud", w: "_water", s: "_stone" }, size: 16 }))

rg.tileset("level", { backdrop: 0x21 })                // sky: transparent pixels show the backdrop

// ---- the hero: 16x16, 4 hardware sprites, 2 palettes ----

sprite("hero", { mx: true, outline: "k" }, `
  ....hhh
  ..hhhhh
  .hhssss
  .hsskss
  .hsssss
  ..sssss
  ...ssss
  ..bbbbb
  .bblbbb
  .bblbbb
  .bbbbbb
  ..bb.bb
  ..bb.bb
  .lll.ll`)

rg.scene("proof", {
  bg: "level",
  backdrop: 0x21,
  obj: [["hero", 120, 160]],
  objSize: "8x8",
})

sheet("proof_sheet", ["hero"])

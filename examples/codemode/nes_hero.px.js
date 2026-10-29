// hero.px.js — drawn once, checked for NES legality.
pal({ k: nes(0x0F), r: nes(0x16), s: nes(0x27),     // top half:    black, dark red, gold
      b: nes(0x12), c: nes(0x21),                   // bottom half: black, blue, light blue
      g: nes(0x1A) })                               // BG ground:   green
ramps("krs", "kbc")

// Write the left 7 columns; mx mirrors to 14, outline grows to 16x16.
// Outlined rows 0-7 use {k,r,s} and rows 8-15 use {k,b,c}: 3 colors per 8x8 cell (NES-H3).
sprite("hero", { mx: true, outline: "k" }, `
  ....rrr
  ..rrrrr
  .rrssss
  .rsskss
  .rsssss
  ..sssss
  ...ssss
  ..bbbbb
  .bbcbbb
  .bbcbbb
  .bbbbbb
  ..bb.bb
  ..bb.bb
  .ccc.cc`)

scene("field", { w: 256, h: 240, bg: "c" },
  layer("ground", { y: 192 }, rect(0, 0, 256, 48, "g")))

rg.scene("title", {
  bg: "field",                                       // backdrop is solved: "c" ($21) is the most frequent
  obj: [["hero", 120, 176], ["hero", 136, 176, { flip: "x" }]],
  objSize: "8x8",
})
sheet("chars", ["hero"])

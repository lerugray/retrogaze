// nes_flips.px.js: sprite flips in both NES sprite sizes (M1 review F7). One asymmetric sprite is drawn once
// and placed four times: as drawn, flipped on X, on Y, and on both. The flipped copies cost no pattern tiles:
// they reuse the same tiles through the OAM H and V bits. In 8x16 mode the V bit flips the whole 16-row
// sprite, so its bottom tile is drawn on top; the emulator proof checks that the bytes show exactly that.
// No image model anywhere: every pixel below comes from these lines.

pal({
  k: nes(0x0F),                                  // black: outlines
  y: nes(0x28), o: nes(0x17),                    // bird: yellow body, brown wing
  c: nes(0x2C), b: nes(0x12),                    // key: cyan metal, blue shadow
  G: nes(0x1A), g: nes(0x0A), D: nes(0x07),      // BG: grass and earth
  W: nes(0x30), w: nes(0x10),                    // BG: tiles of the plaza
})

// ---- background: a plaza (2 BG palettes) under a sky backdrop ----

sprite("_plaza", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "W"), box(0, 0, 16, 16, "w"), px(4, 4, "k"), px(11, 11, "k"))

sprite("_grass", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "D"), rect(0, 0, 16, 5, "G"), dither(0, 5, 16, 2, "G", "g", 0.5))

scene("plaza", { w: 256, h: 240 },
  tilemap(`
................
................
................
................
................
................
................
................
................
................
................
pppppppppppppppp
gggggggggggggggg
gggggggggggggggg
gggggggggggggggg`, { map: { p: "_plaza", g: "_grass" }, size: 16 }))

// ---- 8x8 sprites: a 16x16 bird, asymmetric on both axes (3 colors: k, y, o) ----

sprite("bird", `
  ......kkkk......
  .....kyyyyk.....
  ....kyyykyyk....
  ....kyyyyyykkkk.
  ...kyyyyyykoook.
  ..kyyyyyyyykook.
  .kyyyooyyyyk.kk.
  kyyyoooyyyk.....
  kyyoooyyyk......
  .kyooyyyyk......
  ..kyyyyyk.......
  ...kkkkkk.......
  ....k..k........
  ....k..k........
  ...kk.kk........
  .kkk.kkk........`)

rg.scene("flips8", {
  bg: "plaza",
  backdrop: 0x21,
  obj: [["bird", 64, 48], ["bird", 168, 48, { flip: "x" }],
        ["bird", 64, 104, { flip: "y" }], ["bird", 168, 104, { flip: "xy" }]],
  objSize: "8x8",
})

// ---- 8x16 sprites: a 16x32 key, asymmetric on both axes (3 colors: k, c, b) ----

sprite("key", { w: 16, h: 32 },
  ring(7, 6, 6, "k"), circ(7, 6, 5, "c"), circ(7, 6, 2, "k"), px(9, 4, "b"), px(10, 5, "b"),
  rect(5, 12, 5, 19, "k"), rect(6, 12, 3, 18, "c"), vline(8, 13, 17, "b"),
  rect(9, 20, 6, 4, "k"), rect(9, 21, 5, 2, "c"),
  rect(9, 26, 7, 5, "k"), rect(9, 27, 6, 3, "c"), px(15, 31, "k"), px(0, 6, "k"))

rg.scene("flips16", {
  bg: "plaza",
  backdrop: 0x21,
  obj: [["key", 64, 40], ["key", 168, 40, { flip: "x" }],
        ["key", 64, 120, { flip: "y" }], ["key", 168, 120, { flip: "xy" }]],
  objSize: "8x16",
})

sheet("flips_sheet", ["bird", "key"])

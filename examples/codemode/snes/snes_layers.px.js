// snes_layers.px.js: all three mode-1 BG layers and flipped OBJs.
// BG2 (4bpp) is a sunset with mountains, BG1 (4bpp) the ground and floating platforms in front of it, and
// BG3 (2bpp, 3 colors per tile) a HUD whose palettes share CGRAM 0-31 with BG palettes 0-1. Birds are
// placed as drawn and flipped on X, Y and both; transparent pixels show the layer below.
// No image model anywhere: every pixel below comes from these lines.

pal({
  // BG2: sunset sky and mountains
  a: snes(6, 3, 12), b: snes(12, 4, 14), c: snes(20, 6, 12), d: snes(27, 11, 9), e: snes(31, 19, 8),
  f: snes(31, 27, 14), m: snes(4, 3, 9), M: snes(8, 6, 14), n: snes(13, 10, 18),
  // BG1: ground, platforms
  g: snes(4, 12, 5), G: snes(8, 19, 6), h: snes(15, 26, 9), r: snes(9, 5, 3), R: snes(15, 9, 4),
  s: snes(22, 15, 8), k: snes(6, 6, 9), K: snes(12, 12, 15), l: snes(19, 19, 22),
  // BG3: HUD (white, shadow, heart red)
  W: snes(31, 31, 31), S: snes(3, 3, 7), H: snes(31, 6, 8),
  // OBJ: bird and coin
  O: snes(2, 2, 4), y: snes(30, 24, 6), Y: snes(31, 30, 18), o: snes(24, 12, 4), w: snes(29, 29, 31),
  t: snes(19, 13, 2),
})

scene("far", { w: 256, h: 224 },
  grad(0, 0, 256, 150, "abcdef", "v", 0.5),
  circ(196, 120, 22, "f"),
  poly([0, 224, 0, 150, 40, 110, 80, 150, 120, 100, 170, 160, 210, 120, 256, 150, 256, 224], "m"),
  poly([120, 100, 145, 130, 132, 128, 120, 112, 110, 126, 98, 128], "n"),
  poly([0, 224, 0, 175, 60, 150, 130, 178, 190, 155, 256, 180, 256, 224], "M"))

scene("near", { w: 256, h: 224 },
  rect(0, 192, 256, 32, "R"), rect(0, 192, 256, 4, "h"), rect(0, 196, 256, 2, "G"), dither(0, 198, 256, 2, "G", "R", 0.5),
  noise(0, 200, 256, 24, "r", 0.15, 9), noise(0, 200, 256, 24, "s", 0.05, 11),
  rect(32, 136, 64, 16, "K"), hline(32, 136, 64, "l"), hline(32, 151, 64, "k"), vline(63, 137, 14, "k"),
  rect(160, 104, 48, 16, "K"), hline(160, 104, 48, "l"), hline(160, 119, 48, "k"), vline(183, 105, 14, "k"),
  rect(40, 128, 48, 8, "g"), hline(40, 128, 48, "h"), rect(168, 96, 32, 8, "g"), hline(168, 96, 32, "h"))

scene("hud", { w: 256, h: 224 },
  text(9, 9, "SCORE 001200", "S"), text(8, 8, "SCORE 001200", "W"),
  text(193, 9, "x3", "S"), text(192, 8, "x3", "W"),
  circ(181, 10, 2, "H"), circ(185, 10, 2, "H"), poly([178, 11, 188, 11, 183, 16], "H"))

// a bird, 16x16, asymmetric so every flip shows
sprite("bird", `
  ......OOOO......
  .....OyyyyO.....
  ....OyyyOyyO....
  ....OyyyyyyOOOO.
  ...OyyyyyyOoooO.
  ..OyyyyyyyyOooO.
  .OyyyooyyyyO.OO.
  OyyyoooyyyO.....
  OyyoooyyyO......
  .OyooyyyyO......
  ..OyyyyyO.......
  ...OOOOOO.......
  ....O..O........
  ....O..O........
  ...OO.OO........
  .OOO.OOO........`)

// a coin, 16x16
sprite("coin", { w: 16, h: 16 }, circ(7, 7, 7, "O"), circ(7, 7, 6, "t"), circ(7, 7, 5, "y"), rect(6, 3, 3, 9, "Y"),
  px(5, 4, "w"), px(4, 5, "w"))

rg.scene("layers", {
  bg1: "near", bg2: "far", bg3: "hud",
  backdrop: snes(6, 3, 12),
  obj: [["bird", 40, 40], ["bird", 88, 40, { flip: "x" }], ["bird", 136, 56, { flip: "y" }],
        ["bird", 216, 64, { flip: "xy" }], ["coin", 56, 112], ["coin", 72, 112], ["coin", 176, 80],
        ["coin", 192, 80]],
})

sheet("layers_sheet", ["bird", "coin"])

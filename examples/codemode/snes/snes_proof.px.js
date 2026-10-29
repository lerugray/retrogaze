// snes_proof.px.js: the SNES proof scene for Retrogaze code mode (docs/spec/CODE-MODE-SPEC.md §5, M2-13).
// BG mode 1: a code-drawn 4bpp tile set on BG1 (sky, hills, a castle, water, earth: several BG palettes of
// up to 15 colors), a code-drawn 32x32 hero that is one 32x32 OBJ, and a slime in a second OBJ palette.
// Colors are 15-bit: snes(r, g, b) with each channel 0-31. No image model anywhere: every pixel below comes
// from these lines.

pal({
  // sky: a dithered gradient and clouds
  a: snes(5, 9, 21), b: snes(7, 13, 24), c: snes(10, 17, 27), d: snes(13, 21, 29), e: snes(17, 25, 30),
  f: snes(22, 28, 31), W: snes(31, 31, 31), w: snes(25, 28, 31),
  // hills and grass
  g: snes(3, 11, 6), G: snes(6, 16, 7), h: snes(10, 21, 8), H: snes(16, 26, 10),
  // earth
  r: snes(10, 6, 3), R: snes(15, 9, 4), s: snes(21, 14, 7),
  // castle stone and roof
  k: snes(5, 5, 8), K: snes(10, 10, 13), l: snes(16, 16, 19), L: snes(23, 23, 25),
  x: snes(14, 3, 3), X: snes(22, 6, 4), z: snes(28, 12, 6),
  // water, distant mountains, flowers
  u: snes(2, 8, 16), U: snes(4, 13, 22), V: snes(10, 20, 28),
  A: snes(11, 8, 18), B: snes(15, 12, 22), C: snes(20, 17, 26), F: snes(31, 12, 20), Z: snes(31, 28, 10),
  // hero (one OBJ palette): outline, steel, plume, face, gold
  O: snes(2, 2, 5), m: snes(8, 10, 14), M: snes(14, 16, 21), n: snes(21, 23, 27), N: snes(30, 31, 31),
  p: snes(18, 2, 4), P: snes(28, 6, 6), q: snes(26, 18, 13), y: snes(25, 18, 2), Y: snes(31, 27, 8),
  v: snes(4, 4, 8),
  // slime (the second OBJ palette)
  "1": snes(1, 8, 4), "2": snes(4, 16, 6), "3": snes(9, 24, 9), "4": snes(17, 30, 14), "5": snes(28, 31, 24),
  "6": snes(2, 4, 3),
})
ramps("abcdef", "gGhH", "rRs", "kKlL", "xXz", "uUV", "ABC")

// ---- the tile set: 16x16 metatiles, each 8x8 tile takes the palette that holds its colors ----

sprite("_sky", { w: 16, h: 16 }, rect(0, 0, 16, 16, "a"))
sprite("_cloud", { w: 16, h: 16 }, circ(5, 9, 5, "w"), circ(10, 8, 5, "W"), hline(1, 14, 14, "w"))
sprite("_hill", { w: 16, h: 16 }, ellipse(8, 16, 9, 11, "G"), ellipse(8, 17, 6, 9, "h"), px(6, 9, "H"), px(9, 11, "H"))
sprite("_grass", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "R"), rect(0, 0, 16, 5, "h"), dither(0, 5, 16, 2, "h", "g", 0.5),
  hline(0, 0, 16, "H"), noise(0, 7, 16, 9, "r", 0.12, 3), noise(0, 7, 16, 9, "s", 0.06, 4),
  px(3, 2, "F"), px(12, 1, "Z"), px(8, 3, "F"))
sprite("_mount", { w: 16, h: 16 }, poly([0, 16, 8, 2, 16, 16], "A"), poly([8, 2, 16, 16, 11, 16], "B"),
  poly([6, 5, 8, 2, 10, 5, 8, 4], "C"))
sprite("_earth", { w: 16, h: 16 }, rect(0, 0, 16, 16, "R"), noise(0, 0, 16, 16, "r", 0.15, 5), noise(0, 0, 16, 16, "s", 0.06, 6))
sprite("_wall", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "l"), hline(0, 7, 16, "k"), hline(0, 15, 16, "k"), vline(7, 0, 7, "k"), vline(15, 8, 7, "k"),
  hline(0, 0, 7, "L"), hline(8, 8, 7, "L"), px(3, 3, "K"), px(11, 11, "K"))
sprite("_battlement", { w: 16, h: 16 },
  rect(0, 8, 16, 8, "l"), rect(2, 2, 5, 6, "l"), rect(10, 2, 5, 6, "l"), hline(0, 15, 16, "k"),
  hline(2, 2, 5, "L"), hline(10, 2, 5, "L"), vline(6, 3, 5, "K"), vline(14, 3, 5, "K"))
sprite("_roof", { w: 16, h: 16 }, poly([0, 16, 8, 0, 16, 16], "X"), poly([8, 0, 16, 16, 12, 16], "x"), line(8, 1, 8, 15, "z"))
sprite("_door", { w: 16, h: 16 }, rect(0, 0, 16, 16, "l"), rect(4, 4, 8, 12, "k"), circ(8, 5, 4, "k"), px(10, 11, "K"))
sprite("_water", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "U"), hline(1, 3, 6, "V"), hline(9, 8, 5, "V"), hline(3, 13, 6, "V"),
  hline(7, 4, 3, "u"), hline(13, 9, 3, "u"), hline(0, 14, 3, "u"))

scene("land", { w: 256, h: 224 },
  grad(0, 0, 256, 128, "abcdef", "v", 0.6),
  tilemap(`
................
..cc.......c....
.ccc......ccc...
................
..........rr....
....h....rrrr...
...hhh...bbbb.m.
..hhhhh..wwwwmmm
ggggggggggDwgggg
eeeeeeeeeeeeeeee
eeeeeeeeeeeeeeee
eeeeeeeeeeeeeeee
wwwwwwwwwwwwwwww
wwwwwwwwwwwwwwww`, { map: { c: "_cloud", h: "_hill", g: "_grass", e: "_earth", b: "_battlement", w: "_wall",
                             r: "_roof", D: "_door", m: "_mount" }, size: 16 }),
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
................
WWWWWWWWWWWWWWWW
WWWWWWWWWWWWWWWW`, { map: { W: "_water" }, size: 16 }))

rg.tileset("land")

// ---- the hero: 32x32, drawn as its left half and mirrored, then given a sword on one side ----

sprite("_knight", { mx: true }, `
  ...........OOOOO
  ..........OPPPPP
  .........OPPpPPP
  .........OPpPPPP
  ..........OOOOOO
  .........OnnnnnM
  ........OnnNnnMM
  ........OnnnnMMM
  ........OnMMvvvv
  ........OnMvqqqq
  ........OnMMvvvv
  ........OnMMMMMM
  .........OMMMMMM
  ......OOOOyyyyyy
  .....OnnnOYyMMMM
  ....OnNnnOMMMMMM
  ....OnnnMOMMMnMM
  ....OnnMMOMMnNnM
  ....OnMMMOMMMnMM
  ....OqqOOOMMMMMM
  ....OqqqOyyyyyyy
  .....OqqOYyYyyYy
  ......OOOmMMMMMM
  ........OmMMMMMM
  ........OmMMMOOO
  ........OmMMO...
  ........OmMMO...
  ........OmmMO...
  .......OmmmMO...
  ......OOOOOOO...`)

sprite("hero", { base: "_knight" },
  line(29, 6, 29, 20, "N"), line(30, 6, 30, 20, "n"), px(29, 5, "N"),
  rect(27, 21, 5, 1, "y"), px(29, 22, "Y"), px(29, 23, "y"))

// ---- the slime: 16x16, in a second OBJ palette ----

sprite("slime", { mx: true }, `
  ........
  ........
  ........
  ........
  .....666
  ....6444
  ...64444
  ..643333
  ..633333
  .6335533
  .6333333
  63366333
  63333333
  62222222
  62222222
  .6666666`)

rg.scene("proof", {
  bg1: "land",
  backdrop: snes(5, 9, 21),
  obj: [["hero", 112, 96], ["slime", 176, 112], ["slime", 48, 112, { flip: "x" }]],
})

sheet("proof_sheet", ["hero", "slime"])

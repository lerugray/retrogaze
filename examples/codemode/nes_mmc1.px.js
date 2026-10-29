// nes_mmc1.px.js: code-drawn art for an MMC1 cartridge with 8 KiB CHR-RAM (mapper 1, horizontal mirroring,
// PRG mode 3 with the last 16 KiB bank fixed at $C000). That is the cartridge of Ray's own NES project.
//
// chr: "chr-ram" says the 8 KiB pattern data is not a CHR-ROM: the game copies room.chr into CHR-RAM at
// boot. The tile budget is the same 256 BG + 256 sprite tiles (BG table at $0000, sprites at $1000), and the
// exports are the same raw binaries: room.chr (8192 B), room.pal (32 B), room.nam (1024 B), room.oam (256 B),
// ready for .incbin in any 6502 assembler. `python -m retrogaze.codemode rom` shows it on the MMC1 viewer
// (proof/nes/viewer_mmc1.s), which does exactly that upload.
// No image model anywhere: every pixel below comes from these lines.

pal({
  k: nes(0x0F),                                  // black: sprite outlines
  S: nes(0x2D), s: nes(0x00), L: nes(0x10),      // BG palette: stone wall (dark, mid, light gray)
  F: nes(0x07), f: nes(0x17), e: nes(0x27),      // BG palette: wooden floor and door
  R: nes(0x06), r: nes(0x16), Y: nes(0x28),      // BG palette: torch flame on its bracket
  B: nes(0x01), b: nes(0x11), c: nes(0x21),      // BG palette: banner and window glass
  a: nes(0x00), A: nes(0x20),                    // knight armor (with k): helmet and plate
  m: nes(0x16), t: nes(0x36),                    // knight cape and face (with k)
  g: nes(0x1A), G: nes(0x2A),                    // slime (with k)
})

// ---- metatiles: each 16x16 is one attribute area: 3 colors + the black backdrop ----

sprite("_wall", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "s"),
  hline(0, 0, 16, "L"), hline(0, 8, 16, "L"),
  hline(0, 7, 16, "S"), hline(0, 15, 16, "S"),
  vline(10, 1, 6, "S"), vline(4, 9, 6, "S"),
  px(11, 1, "L"), px(5, 9, "L"))

sprite("_floor", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "f"),
  hline(0, 0, 16, "e"), hline(0, 15, 16, "F"),
  vline(7, 1, 14, "F"), vline(15, 1, 14, "F"),
  px(3, 5, "F"), px(11, 10, "F"), px(2, 12, "e"), px(12, 3, "e"))

sprite("_door", { w: 16, h: 16 },
  rect(0, 0, 16, 16, "F"),
  rect(1, 1, 14, 15, "f"),
  vline(5, 1, 15, "F"), vline(10, 1, 15, "F"),
  hline(1, 4, 14, "e"), px(12, 9, "e"), px(12, 10, "e"))

sprite("_torch", { w: 16, h: 16 },
  rect(6, 10, 4, 2, "R"), rect(7, 12, 2, 4, "R"),
  circ(8, 6, 3, "r"), circ(8, 7, 2, "Y"), px(8, 2, "r"), px(7, 1, "r"))

sprite("_banner", { w: 16, h: 16 },
  rect(3, 0, 10, 13, "B"), poly([3, 13, 8, 16, 13, 13], "B"),
  rect(5, 2, 6, 8, "b"), px(7, 4, "c"), px(8, 4, "c"), rect(6, 5, 4, 2, "c"), px(7, 7, "c"), px(8, 7, "c"))

sprite("_window", { w: 16, h: 16 },
  rect(2, 2, 12, 14, "B"), rect(3, 3, 10, 13, "b"),
  vline(7, 3, 13, "B"), hline(3, 9, 10, "B"), px(4, 4, "c"), px(5, 4, "c"), px(4, 5, "c"))

// ---- the room: one character per metatile, 16 x 15 = 256 x 240 ----

scene("room", { w: 256, h: 240 },
  tilemap(`
################
################
##t..w...w...t##
##............##
##..b......b..##
##............##
##t..........t##
##............##
##ffffffffffff##
##ffffffffffff##
##ffffffffffff##
##ffffffffffff##
##ffffffDDffff##
################
################`, { map: { "#": "_wall", t: "_torch", b: "_banner", w: "_window", f: "_floor", D: "_door" }, size: 16 }))

// ---- sprites: 8x16 hardware sprites (objSize "8x16"), 3 colors each ----

// The knight, 16x32: 2 x 2 tall sprites. Rows 0-15 use {k, a, A}; rows 16-31 use {k, m, t}.
sprite("knight", { mx: true }, `
  ....kkkk
  ...kAAAA
  ..kAAAAA
  ..kAaaaa
  ..kAakkk
  ..kAakAA
  ..kAakAA
  ..kAaaaa
  ...kAAAA
  ..kAAaaa
  .kAAAAAa
  kAAaAAAA
  kAaaAAAA
  kAakAAAA
  kAakAaaa
  kaakkkkk
  kmmktttt
  kmmktttt
  kmmkkttt
  kmmmkttt
  kmmmktkk
  .kmmkkmm
  .kmmmmmm
  ..kmmmmm
  ..kmmmmm
  ..kmmmmm
  ...kmmmm
  ...kmkkk
  ...kmk..
  ...kmk..
  ..kkmk..
  ..kkkk..`)

// The slime, 16x16 (one 8x16 sprite column on each side), {k, g, G}.
sprite("slime", { mx: true }, `
  ........
  ........
  ........
  ........
  ........
  ........
  .....kkk
  ....kGGG
  ...kGGgg
  ..kGgggg
  ..kGgkkg
  .kGggkGg
  .kggggkg
  kgggggg.
  kggggggg
  .kkkkkkk`)

rg.scene("room", {
  bg: "room",
  backdrop: 0x0F,
  obj: [["knight", 104, 128], ["slime", 152, 144], ["slime", 72, 144, { flip: "x" }]],
  objSize: "8x16",
  chr: "chr-ram",
})

sheet("room_sheet", ["knight", "slime"])

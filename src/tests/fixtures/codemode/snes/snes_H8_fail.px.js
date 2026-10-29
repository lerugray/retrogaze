// OBSEL gives two OBJ sizes per frame; 8x8, 16x16 and 32x32 are three.
pal({ r: snes(31, 8, 0) })
sprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "r"))
rg.scene("s", { obj: [["s", 16, 16, { size: "8x8" }], ["s", 48, 16, { size: "16x16" }], ["s", 96, 16, { size: "32x32" }]] })   // expect: SNES-H8

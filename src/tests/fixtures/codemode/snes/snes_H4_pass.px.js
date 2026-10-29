// X is 9-bit: an OBJ may straddle the left edge (X = -4).
pal({ r: snes(31, 8, 0) })
sprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "r"))
rg.scene("s", { obj: [["s", -4, 0], ["s", 252, 216]] })

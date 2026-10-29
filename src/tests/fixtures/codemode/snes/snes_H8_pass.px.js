pal({ r: snes(31, 8, 0) })
sprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "r"))
rg.scene("s", { obj: [["s", 16, 16, { size: "8x8" }], ["s", 48, 16, { size: "16x16" }]] })

// Every 8x8 tile has one color, but the 32x32 OBJ as a whole has 16: one palette per OBJ.
sprite("big", { w: 32, h: 32 }, (c) => { for (let i = 0; i < 16; i++) c.rect((i % 4) * 8, (i >> 2) * 8, 8, 8, snes(i * 2, 16, 31 - i * 2)) })   // expect: SNES-H3
rg.scene("s", { obj: [["big", 32, 32, { size: "32x32" }]] })

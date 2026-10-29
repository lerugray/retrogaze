// Nine 8x8 OBJs, each with 15 colors no other OBJ uses: 9 OBJ palettes; the console has 8.
sprite("row", { w: 72, h: 8 }, (c) => { for (let t = 0; t < 9; t++) for (let i = 0; i < 15; i++) c.px(t * 8 + (i % 8), i >> 3, snes(t * 3 + 1, i * 2 + 1, 9)) })   // expect: SNES-H7
rg.scene("s", { obj: [["row", 32, 32, { size: "8x8" }]] })

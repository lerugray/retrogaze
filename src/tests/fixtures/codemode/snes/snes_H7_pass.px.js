sprite("row", { w: 64, h: 8 }, (c) => { for (let t = 0; t < 8; t++) for (let i = 0; i < 15; i++) c.px(t * 8 + (i % 8), i >> 3, snes(t * 3 + 1, i * 2 + 1, 9)) })
rg.scene("s", { obj: [["row", 32, 32, { size: "8x8" }]] })

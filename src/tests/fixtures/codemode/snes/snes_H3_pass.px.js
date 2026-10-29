sprite("big", { w: 32, h: 32 }, (c) => { for (let i = 0; i < 15; i++) c.rect((i % 4) * 8, (i >> 2) * 8, 8, 8, snes(i * 2, 16, 31 - i * 2)) })
rg.scene("s", { obj: [["big", 32, 32, { size: "32x32" }]] })

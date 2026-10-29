// Nine BG tiles, each with 15 colors no other tile uses: they need 9 palettes; 4bpp BG has 8.
scene("bg", { w: 256, h: 224 }, (c) => { for (let t = 0; t < 9; t++) for (let i = 0; i < 15; i++) c.px(t * 8 + (i % 8), i >> 3, snes(t * 3 + 1, i * 2 + 1, 7)) })   // expect: SNES-H6
rg.scene("s", { bg1: "bg" })

// 15 colors in one BG1 tile, and 3 in one BG3 (2bpp) tile.
scene("bg", { w: 256, h: 224 }, (c) => { for (let i = 0; i < 15; i++) c.px(i % 8, i >> 3, snes(i * 2, 31 - i, 4)) })
scene("hud", { w: 256, h: 224 }, (c) => { c.px(8, 8, snes(31, 31, 31)); c.px(9, 8, snes(0, 0, 31)); c.px(10, 8, snes(31, 0, 0)) })
rg.scene("s", { bg1: "bg", bg3: "hud" })

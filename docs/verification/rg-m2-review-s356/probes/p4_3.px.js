scene("bg", { w: 256, h: 224 }, (c) => { for (let t = 0; t < 7; t++) for (let i = 0; i < 15; i++) c.px(t * 8 + (i % 8), i >> 3, snes(t * 3 + 1, i * 2 + 1, 7)) })
scene("hud", { w: 256, h: 224 }, (c) => { const k = [snes(30, 30, 30), snes(0, 0, 31), snes(31, 0, 0)]; for (let i = 0; i < 3; i++) for (let j = 0; j < 40; j++) c.px(8 + j, 100 + i * 3, k[i]) })
rg.scene("x", { bg1: "bg", bg3: "hud" })

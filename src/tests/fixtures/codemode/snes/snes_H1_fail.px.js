// A 4bpp BG tile shows 15 colors (pixel value 0 is transparent); 16 passes NES-like L3 but not the hardware.
scene("bg", { w: 256, h: 224 }, (c) => { for (let i = 0; i < 16; i++) c.px(i % 8, i >> 3, snes(i * 2, 31 - i, 4)) })   // expect: SNES-H1
rg.scene("s", { bg1: "bg" })

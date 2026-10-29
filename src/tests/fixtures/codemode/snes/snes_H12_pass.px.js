// 1024 unique BG tiles: the whole 32x32 tilemap, each tile different (10-bit tile numbers).
pal({ a: snes(2, 6, 12), b: snes(20, 24, 31) })
scene("n", { w: 256, h: 256 }, (c) => { c.rect(0, 0, 256, 256, "a"); c.noise(0, 0, 256, 256, "b", 0.5, 1) })
rg.scene("s", { bg1: "n" })

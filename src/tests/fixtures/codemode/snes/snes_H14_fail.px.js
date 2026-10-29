// BG1 and BG2 each fill a 32x32 map with 1024 different tiles: 2 x 32 KiB of CHR + 2 x 2 KiB of maps > 64 KiB VRAM.
pal({ a: snes(2, 6, 12), b: snes(20, 24, 31), c: snes(12, 4, 2), d: snes(31, 20, 8) })
scene("one", { w: 256, h: 256 }, (c) => { c.rect(0, 0, 256, 256, "a"); c.noise(0, 0, 256, 256, "b", 0.5, 1) })
scene("two", { w: 256, h: 256 }, (c) => { c.rect(0, 0, 256, 256, "c"); c.noise(0, 0, 256, 256, "d", 0.5, 2) })
rg.scene("s", { bg1: "one", bg2: "two" })   // expect: SNES-H14

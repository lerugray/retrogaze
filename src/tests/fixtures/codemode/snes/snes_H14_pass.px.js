pal({ a: snes(2, 6, 12), b: snes(20, 24, 31), c: snes(12, 4, 2), d: snes(31, 20, 8) })
scene("one", { w: 256, h: 256 }, (c) => { c.rect(0, 0, 256, 256, "a"); c.noise(0, 0, 256, 256, "b", 0.5, 1) })
scene("two", { w: 256, h: 224 }, rect(0, 192, 256, 32, "c"), rect(0, 192, 256, 2, "d"))
rg.scene("s", { bg1: "one", bg2: "two" })

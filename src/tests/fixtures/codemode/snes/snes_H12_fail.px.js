// An animated BG: the CHR of all frames is loaded at once (union), 1024 + 64 unique tiles > 1024.
pal({ a: snes(2, 6, 12), b: snes(20, 24, 31) })
anim("n", { w: 256, h: 256, frames: 2 }, (c) => { c.rect(0, 0, 256, 256, "a"); c.noise(0, 0, 256, 256, "b", 0.5, 1); if (c.frame) c.noise(0, 0, 64, 64, "b", 0.5, 7) })   // expect: SNES-H12
rg.scene("s", { bg1: "n" })

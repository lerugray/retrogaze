anim("n", { w: 64, h: 64, frames: 5 }, (c) => c.noise(0, 0, 64, 64, "123", 0.6, c.frame + 1))   // expect: NES-H12
rg.scene("s", { obj: [["n", 64, 64]] })

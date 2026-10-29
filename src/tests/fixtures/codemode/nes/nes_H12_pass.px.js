anim("n", { w: 64, h: 64, frames: 3 }, (c) => c.noise(0, 0, 64, 64, "123", 0.6, c.frame + 1))
rg.scene("s", { obj: [["n", 64, 64]] })

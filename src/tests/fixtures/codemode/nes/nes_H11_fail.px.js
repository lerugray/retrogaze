scene("bg", { w: 256, h: 240 }, noise(0, 0, 256, 240, "12", 0.5, 7))   // expect: NES-H11
rg.scene("s", { bg: "bg" })

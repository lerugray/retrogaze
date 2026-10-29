scene("bg", { w: 256, h: 240 }, rect(0, 0, 16, 16, "1"))
rg.scene("s", { bg: "bg", backdrop: 0x0D })   // expect: NES-H1

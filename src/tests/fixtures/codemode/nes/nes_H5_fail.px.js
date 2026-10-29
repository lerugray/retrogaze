scene("bg", { w: 256, h: 240 }, rect(0, 0, 16, 16, "1"))
rg.scene("s", { bg: "bg", backdrop: 0x21, palettes: { bg: [[0x0F, 0x01, 0x02, 0x03]] } })   // expect: NES-H5

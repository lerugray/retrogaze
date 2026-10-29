pal({ k: snes(2, 4, 8) })
scene("bg", { w: 256, h: 224 }, rect(0, 0, 16, 16, "k"))
rg.scene("s", { bg1: "bg", backdrop: 0x8000 })   // expect: SNES-H5

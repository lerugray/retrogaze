sprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "1"))
rg.scene("s1", { obj: [["s", -4, 100]] })   // expect: NES-H13

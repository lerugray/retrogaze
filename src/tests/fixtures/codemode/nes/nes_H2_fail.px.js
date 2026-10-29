scene("bg", { w: 256, h: 240 },
  rect(0, 0, 8, 16, "1"),
  rect(8, 0, 8, 16, "2"),
  rect(2, 2, 1, 3, "4"),
  rect(10, 2, 1, 2, "5"),
  px(10, 12, "6"))   // expect: NES-H2
rg.scene("s", { bg: "bg" })

pal({ r: snes(31, 0, 0) })
sprite("a", { w: 8, h: 8 }, (c) => {
  c.rect(0, 0, 8, 8, "r")
  c.px(3, 3, "#848484")   // expect: SNES-L1
})

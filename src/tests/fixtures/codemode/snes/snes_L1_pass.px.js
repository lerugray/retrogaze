pal({ r: snes(31, 0, 0) })
sprite("a", { w: 8, h: 8 }, (c) => {
  c.rect(0, 0, 8, 8, "r")
  c.px(3, 3, snes(16, 16, 16))
})

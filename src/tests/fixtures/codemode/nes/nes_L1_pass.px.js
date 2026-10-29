sprite("a", { w: 8, h: 8 }, (c) => {
  c.rect(0, 0, 8, 8, nes(0x16))
  c.px(3, 3, nes(0x30))
})

sprite("a", { w: 8, h: 8 }, (c) => {
  c.rect(0, 0, 8, 8, nes(0x16))
  c.px(1, 1, "#E0926480")   // expect: NES-L4
})

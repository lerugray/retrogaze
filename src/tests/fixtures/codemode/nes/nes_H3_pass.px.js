// A 2x2 checker of 3 colors: every 8x8 window holds 3 colors.
sprite("a", { w: 8, h: 8 }, (c) => {
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++)
    c.px(x, y, ["1", "2", "3", "1"][(x % 2) + 2 * (y % 2)])
})

// A 2x2 checker of 4 colors: every 8x8 window holds 4 colors, whatever the cell grid.
sprite("a", { w: 8, h: 8 }, (c) => {
  for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++)
    c.px(x, y, ["1", "2", "3", "4"][(x % 2) + 2 * (y % 2)])   // expect: NES-H3
})

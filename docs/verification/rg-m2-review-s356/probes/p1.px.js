// reviewer probe: 64x64 / 32x32 / 16x32 OBJs, flips, partial edges, OBSEL 5 (32/64) and 2 (8/64)
pal({ a: snes(31, 0, 0), b: snes(0, 31, 0), c: snes(0, 0, 31), d: snes(31, 31, 0), e: snes(31, 0, 31), f: snes(0, 31, 31),
      g: snes(16, 8, 4), h: snes(8, 16, 24), i: snes(24, 24, 8), j: snes(5, 5, 5), k: snes(30, 30, 30), l: snes(12, 3, 20),
      m: snes(20, 12, 3), n: snes(3, 20, 12) })
sprite("big", { w: 64, h: 64 },
  rect(0, 0, 64, 64, "j"), rect(2, 2, 60, 60, "a"), rect(14, 14, 36, 36, "b"), rect(8, 8, 20, 6, "c"), rect(36, 40, 18, 9, "d"),
  line(0, 0, 63, 63, "e"), line(63, 0, 0, 63, "f"), rect(30, 4, 5, 55, "g"), rect(4, 30, 55, 5, "h"), rect(50, 6, 8, 8, "i"),
  rect(6, 50, 8, 8, "k"), px(1, 1, "l"), px(62, 62, "m"), px(1, 62, "n"))
sprite("med", { w: 32, h: 32 }, rect(0, 0, 32, 32, "c"), rect(4, 4, 24, 8, "d"), rect(4, 16, 10, 12, "a"), px(30, 30, "k"))
rg.scene("big", { backdrop: snes(1, 2, 3), obj: [["big", -30, 100], ["big", 226, 20, { flip: "x" }], ["big", 100, 150, { flip: "y" }],
  ["med", 10, 10], ["med", 200, 180, { flip: "xy" }]], obsel: 5 })

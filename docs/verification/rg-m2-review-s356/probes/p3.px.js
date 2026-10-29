pal({ a: snes(31, 0, 0), b: snes(0, 31, 0), c: snes(0, 0, 31), d: snes(31, 31, 0), e: snes(31, 0, 31), g: snes(16, 8, 4) })
sprite("tall", { w: 16, h: 32 }, rect(0, 0, 16, 32, "c"), rect(1, 1, 14, 10, "a"), rect(2, 12, 12, 8, "b"), rect(3, 22, 10, 8, "d"), px(0, 31, "e"), px(15, 0, "g"))
sprite("huge", { w: 32, h: 64 }, rect(0, 0, 32, 64, "g"), rect(2, 2, 28, 20, "a"), rect(4, 24, 24, 16, "b"), rect(6, 42, 20, 18, "d"), px(31, 63, "e"), px(0, 0, "c"))
rg.scene("und", { allowUndocumentedObjSizes: true, obj: [["tall", 20, 20], ["tall", 60, 20, { flip: "x" }], ["tall", 100, 20, { flip: "y" }], ["tall", 140, 20, { flip: "xy" }],
  ["huge", 20, 100], ["huge", 90, 100, { flip: "x" }], ["huge", 160, 100, { flip: "y" }], ["huge", 220, 100, { flip: "xy" }]] })

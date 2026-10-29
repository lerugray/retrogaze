// 34 slivers on one line: 16 OBJs fully on screen (32), one straddling X = 0 at X = -12 (1: only its
// right tile is on screen) and one straddling X = 256 at X = 250 (1: only its left tile is on screen).
pal({ k: snes(0, 0, 8), b: snes(8, 16, 31), w: snes(28, 30, 31) })
sprite("s", { w: 16, h: 16 }, rect(0, 0, 16, 16, "k"), rect(1, 1, 14, 14, "b"), px(3, 3, "w"), px(12, 12, "w"))
const obj = [["s", -12, 100], ["s", 250, 100]]
for (let i = 0; i < 16; i++) obj.push(["s", 8 + i * 14, 100])
rg.scene("slivers", { obj, obsel: 3 })

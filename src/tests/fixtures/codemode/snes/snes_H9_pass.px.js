pal({ r: snes(31, 8, 0) })
sprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "r"))
const obj = []
for (let i = 0; i < 128; i++) obj.push(["s", (i % 16) * 16, Math.floor(i / 16) * 16])
rg.scene("many", { obj })

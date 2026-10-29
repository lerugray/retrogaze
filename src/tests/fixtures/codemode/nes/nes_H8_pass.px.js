sprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "1"))
const obj = []
for (let i = 0; i < 64; i++) obj.push(["s", 16 + (i % 8) * 16, 16 + Math.floor(i / 8) * 16])
rg.scene("many", { obj })

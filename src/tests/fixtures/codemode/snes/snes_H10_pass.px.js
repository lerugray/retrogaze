pal({ r: snes(31, 8, 0), y: snes(31, 28, 4) })
sprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "r"), rect(2, 2, 4, 4, "y"))
const obj = []
for (let i = 0; i < 32; i++) obj.push(["s", i * 7, 100])
rg.scene("line", { obj })

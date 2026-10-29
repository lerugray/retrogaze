pal({ a: snes(2, 6, 12), b: snes(20, 24, 31) })
for (let i = 0; i < 8; i++) sprite(`n${i}`, { w: 64, h: 64 }, (c) => { c.rect(0, 0, 64, 64, "a"); c.noise(0, 0, 64, 64, "b", 0.5, i + 1) })
const obj = []
for (let i = 0; i < 8; i++) obj.push([`n${i}`, (i % 3) * 80, Math.floor(i / 3) * 72, { size: "64x64" }])
rg.scene("s", { obj })

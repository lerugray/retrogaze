// snes_33_on_a_line (spec §5.4): 33 OBJs on lines 100-107. The PPU keeps the first 32 in OAM order
// ("range over"); OAM #32 is the first one painted, at x = 0.
pal({ r: snes(31, 8, 0), y: snes(31, 28, 4) })
sprite("s", `
  rrrrrrrr
  ryyyyyyr
  ryrrrryr
  ryryyryr
  ryryyryr
  ryrrrryr
  ryyyyyyr
  rrrrrrrr`)
const obj = []
for (let i = 0; i < 33; i++) obj.push(["s", i * 7, 100])
rg.scene("line", { obj })   // expect: SNES-H10

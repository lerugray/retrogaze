// snes_35_slivers (spec §5.4): 18 OBJs of 16x16 on lines 100-115 need 35 8-px slivers; the PPU fetches 34.
// The first one painted straddles X = 0 at X = -12: only its right tile is on screen, so it costs 1 sliver
// (its left tile is entirely off screen and is not fetched). Slivers are fetched from the highest OAM index
// down, so the one that is lost is the right half of OAM #0, the last OBJ painted.
pal({ k: snes(0, 0, 8), b: snes(8, 16, 31), w: snes(28, 30, 31) })
sprite("s", `
  ..kkkkkkkkkkkk..
  .kbbbbbbbbbbbbk.
  kbbwwbbbbbbbbbbk
  kbwwwbbbbbbbbbbk
  kbbwbbbbbbbbbbbk
  kbbbbbbbbbbbbbbk
  kbbbbbbbbbbbbbbk
  kbbbbbbbbbbbbbbk
  kbbbbbbbbbbbbbbk
  kbbbbbbbbbbbbbbk
  kbbbbbbbbbbbbbbk
  kbbbbbbbbbbbbbbk
  kbbbbbbbbbbbbbbk
  kbbbbbbbbbbbbwbk
  .kbbbbbbbbbbbbk.
  ..kkkkkkkkkkkk..`)
const obj = [["s", -12, 100]]
for (let i = 0; i < 17; i++) obj.push(["s", 8 + i * 14, 100])
rg.scene("slivers", { obj, obsel: 3 })   // expect: SNES-H11

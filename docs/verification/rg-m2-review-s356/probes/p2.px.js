// reviewer probe: >256 unique BG1 tiles (10-bit tile numbers), BG2 + BG3, OBJ tiles in BOTH name tables, many palettes
const C = [];
for (let q = 0; q < 8; q++) { const p = {}; for (let k = 0; k < 15; k++) p[String.fromCharCode(0x100 + q * 16 + k)] = snes((q * 4 + k * 2) % 32, (k * 5 + q * 3) % 32, (q * 9 + k * 7 + 3) % 32); C.push(p); }
let all = {}; for (const p of C) Object.assign(all, p);
const keys = (q) => Object.keys(C[q]);
pal(all);
// BG1: 32x28 tiles, each tile its own random-ish pattern inside one palette group; 896 tiles -> 1024 cap
function bgdraw(seedOff, groups) {
  return (c) => {
    let s = 12345 + seedOff;
    const rnd = () => { s = (s * 1103515245 + 12345) & 0x7fffffff; return s >> 8; };
    for (let ty = 0; ty < 28; ty++) for (let tx = 0; tx < 32; tx++) {
      const q = groups[(tx + ty) % groups.length]; const ks = keys(q);
      for (let y = 0; y < 8; y++) for (let x = 0; x < 8; x++) c.px(tx * 8 + x, ty * 8 + y, ks[rnd() % 15]);
    }
  };
}
scene("one", { w: 256, h: 224 }, bgdraw(0, [0, 1, 2, 3, 4]));
// OBJs: 100 distinct 16x16 sprites, 4 tiles each -> 400 tiles > 256
for (let i = 0; i < 100; i++) {
  const q = 4 + (i % 4); const ks = keys(q);
  sprite("o" + i, { w: 16, h: 16 }, rect(0, 0, 16, 16, ks[i % 15]), rect(1 + (i % 7), 2, 6, 11, ks[(i * 3 + 1) % 15]), px(i % 16, (i * 5) % 16, ks[(i * 7) % 15]), rect(8, 8 + (i % 4), 4, 3, ks[(i + 5) % 15]));
}
const obj = [];
for (let i = 0; i < 100; i++) obj.push(["o" + i, (i % 12) * 20 + 4, Math.floor(i / 12) * 26 + 3, { size: "16x16" }]);
rg.scene("many", { bg1: "one", obj });

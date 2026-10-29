sprite("a", { w: 8, h: 8 }, (c) => { for (let i = 0; i < 17; i++) c.px(i % 8, i >> 3, snes(i, 31 - i, 8)) })   // expect: SNES-L3

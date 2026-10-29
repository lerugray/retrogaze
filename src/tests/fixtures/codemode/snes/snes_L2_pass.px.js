// OBJ canvases are padded with transparent pixels to whole 8x8 tiles (reported); BG canvases are not.
pal({ k: snes(2, 4, 8), r: snes(31, 8, 0) })
scene("bg", { w: 256, h: 224, bg: "k" })
sprite("odd", { w: 10, h: 10 }, rect(0, 0, 10, 10, "r"))
rg.scene("s", { bg1: "bg", obj: [["odd", 40, 40]] })

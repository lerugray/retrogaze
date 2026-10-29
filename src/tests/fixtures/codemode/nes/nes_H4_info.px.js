// 8x16 mode: an 8x8 sprite still takes one whole 8x16 hardware sprite (normalization, not a failure).
sprite("s", { w: 8, h: 8 }, rect(0, 0, 8, 8, "1"))
sprite("odd", { w: 10, h: 10 }, rect(0, 0, 10, 10, "2"))
rg.scene("tall", { obj: [["s", 16, 16], ["odd", 64, 64]], objSize: "8x16" })

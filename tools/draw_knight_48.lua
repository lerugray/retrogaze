-- Sprite 1: Mid Era Knight (48x48, 4 colors + transparency)
-- All details >= 3x3 for 3:1 downscale safety

local spr = Sprite(48, 48, ColorMode.RGB)
spr.filename = "knight_48"

local BLK = Color(0, 0, 0)
local ARM = Color(120, 120, 120)
local TUN = Color(248, 56, 0)
local HI  = Color(188, 188, 188)
local CLEAR = Color(0, 0, 0, 0)

local cel = spr.cels[1]
local img = cel.image

-- Helper: fill rectangle
local function rect(x, y, w, h, col)
  for py = y, y + h - 1 do
    for px = x, x + w - 1 do
      if px >= 0 and px < 48 and py >= 0 and py < 48 then
        img:drawPixel(px, py, col)
      end
    end
  end
end

-- Helper: fill 3x3 block
local function block3(x, y, col)
  rect(x, y, 3, 3, col)
end

-- === SCAFFOLDING ===

-- Helmet (rows 3-8, cols 15-29)
rect(15, 3, 15, 6, ARM)

-- Plume (rows 0-3, cols 20-25)
rect(20, 0, 6, 4, TUN)

-- Visor slit (black bar)
rect(18, 8, 9, 3, BLK)

-- Torso armor
rect(12, 11, 21, 12, ARM)

-- Tunic below armor
rect(14, 19, 18, 6, TUN)

-- Shield on left arm
rect(3, 12, 9, 12, ARM)

-- Sword blade (right hand, extends above shoulder)
rect(35, 5, 3, 21, ARM)

-- Sword crossguard
rect(32, 25, 9, 3, ARM)

-- Sword grip
rect(35, 28, 3, 6, TUN)

-- Left leg
rect(15, 25, 6, 15, ARM)

-- Right leg
rect(24, 25, 6, 15, ARM)

-- Left boot
rect(13, 38, 10, 6, TUN)

-- Right boot
rect(22, 38, 10, 6, TUN)

-- === DETAILS & HIGHLIGHTS (all 3x3) ===

-- Helmet highlight top-left
block3(15, 3, HI)

-- Plume highlight top-left
block3(20, 0, HI)

-- Eyes through visor (3x3 each, red glow)
block3(19, 8, TUN)
block3(24, 8, TUN)

-- Torso highlight top-left
block3(12, 11, HI)

-- Shield highlight top-left
block3(3, 12, HI)

-- Shield cross emblem (red)
rect(6, 16, 3, 6, TUN)   -- vertical
rect(4, 18, 7, 3, TUN)   -- horizontal

-- Sword tip highlight
block3(35, 5, HI)

-- Leg highlights top-left of each
block3(15, 25, HI)
block3(24, 25, HI)

-- === OUTLINE (1px black border around all non-transparent pixels) ===
-- Scan and mark outline pixels
local outline_pixels = {}
for py = 0, 47 do
  for px = 0, 47 do
    local c = img:getPixel(px, py)
    -- Check if this pixel is transparent
    local a = app.pixelColor.rgbaA(c)
    if a == 0 then
      -- Check 4 neighbors for non-transparent
      local neighbors = {{px-1,py},{px+1,py},{px,py-1},{px,py+1}}
      for _, n in ipairs(neighbors) do
        if n[1] >= 0 and n[1] < 48 and n[2] >= 0 and n[2] < 48 then
          local nc = img:getPixel(n[1], n[2])
          if app.pixelColor.rgbaA(nc) > 0 then
            table.insert(outline_pixels, {px, py})
            break
          end
        end
      end
    end
  end
end

for _, p in ipairs(outline_pixels) do
  img:drawPixel(p[1], p[2], BLK)
end

-- Export
local out = app.params["output"] or "sprite1_knight_48.png"
spr:saveCopyAs(out)
print("Exported: " .. out)

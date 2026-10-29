-- Mesen 2 --testRunner script for the Retrogaze NES proof (spec section 5.3). Driven by run_mesen.py.
--
-- Environment: RG_OUT_DIR (required, absolute), RG_FRAMES (default 10).
-- After RG_FRAMES frames it waits until two consecutive screenshots are byte-identical (the picture
-- is static, so this guards against reading a half-decoded frame), then writes to RG_OUT_DIR:
--   screenshot.png  emu.takeScreenshot()
--   palette.bin     32 B   nesPaletteRam $00-$1F
--   oam.bin         256 B  nesSpriteRam  $00-$FF
--   nametable.bin   1024 B nesPpuMemory  $2000-$23FF
--   chr.bin         8192 B nesPpuMemory  $0000-$1FFF
--   run_info.txt    frame count and screen size
-- and calls emu.stop(0). Any error writes lua_error.txt and calls emu.stop(1).
-- Needs --debug.scriptWindow.allowIoOsAccess=true (io/os are not loaded otherwise).

local outDir = os.getenv("RG_OUT_DIR")
local frames = tonumber(os.getenv("RG_FRAMES") or "10")
local maxExtraFrames = 60
local frame = 0
local lastShot = nil
local finished = false

local function writeFile(name, data)
  local f = assert(io.open(outDir .. "/" .. name, "wb"))
  assert(f:write(data))
  f:close()
end

local function dump(memType, start, length)
  local bytes = {}
  for i = 0, length - 1 do
    bytes[#bytes + 1] = string.char(emu.read(start + i, memType))
  end
  return table.concat(bytes)
end

local function onEndFrame()
  frame = frame + 1
  if finished or frame < frames then
    return
  end
  local shot = emu.takeScreenshot()
  assert(shot ~= nil and #shot > 0, "emu.takeScreenshot() returned nothing")
  if shot ~= lastShot then
    assert(frame < frames + maxExtraFrames, "screen did not settle within " .. maxExtraFrames .. " frames")
    lastShot = shot
    return
  end
  finished = true
  local size = emu.getScreenSize()
  writeFile("screenshot.png", shot)
  writeFile("palette.bin", dump(emu.memType.nesPaletteRam, 0x00, 32))
  writeFile("oam.bin", dump(emu.memType.nesSpriteRam, 0x00, 256))
  writeFile("nametable.bin", dump(emu.memType.nesPpuMemory, 0x2000, 1024))
  writeFile("chr.bin", dump(emu.memType.nesPpuMemory, 0x0000, 8192))
  writeFile("run_info.txt", string.format("frames=%d width=%d height=%d\n", frame, size.width, size.height))
  emu.stop(0)
end

local function guarded(fn)
  return function(...)
    local ok, err = pcall(fn, ...)
    if not ok then
      finished = true
      if outDir then
        pcall(writeFile, "lua_error.txt", tostring(err) .. "\n")
      end
      emu.log("run_mesen.lua: " .. tostring(err))
      emu.stop(1)
    end
  end
end

guarded(function()
  assert(outDir and outDir ~= "", "RG_OUT_DIR is not set")
  assert(frames and frames >= 1, "RG_FRAMES must be a positive number")
  emu.addEventCallback(guarded(onEndFrame), emu.eventType.endFrame)
end)()

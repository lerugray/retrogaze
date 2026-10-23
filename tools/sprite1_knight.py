"""
Sprite 1: Mid Era Knight (1985-1987)
32x32, 4 colors + transparency. Downscale-safe (all details >= 2x2px).

Palette:
  #000000 — outline
  #787878 — armor (primary, 40-50%)
  #F83800 — tunic (secondary, 25-35%)
  #BCBCBC — highlight (5-15%, top-left edges)

Design: Knight with helmet, red plume, gray armor, sword right hand, shield left arm.
"""
import json, sys, os

# Output path
OUT_DIR = os.path.join(os.path.dirname(__file__), "..", "test-outputs")
OUT_PNG = os.path.abspath(os.path.join(OUT_DIR, "sprite1_knight.png"))

# Colors
BLK = "#000000"  # outline
ARM = "#787878"  # armor gray
TUN = "#F83800"  # tunic red
HI  = "#BCBCBC"  # highlight

# We'll build commands list, sprite_path gets filled after create_canvas
# Using placeholder SPRITE that we'll replace after creation
commands = []

def px(pixels):
    """Helper: list of {x, y, color} dicts."""
    return [{"x": p[0], "y": p[1], "color": p[2]} for p in pixels]

def rect(x, y, w, h, color, filled=True):
    return {"tool": "draw_rectangle", "args": {
        "sprite_path": "SPRITE", "layer_name": "Layer 1", "frame_number": 1,
        "x": x, "y": y, "width": w, "height": h, "color": color, "filled": filled
    }}

def pixels(pxlist):
    return {"tool": "draw_pixels", "args": {
        "sprite_path": "SPRITE", "layer_name": "Layer 1", "frame_number": 1,
        "pixels": px(pxlist)
    }}

def line(x1, y1, x2, y2, color, thickness=1):
    return {"tool": "draw_line", "args": {
        "sprite_path": "SPRITE", "layer_name": "Layer 1", "frame_number": 1,
        "x1": x1, "y1": y1, "x2": x2, "y2": y2, "color": color, "thickness": thickness
    }}

# ---- BUILD SPRITE ----

# Step 1: Create canvas
commands.append({"tool": "create_canvas", "args": {"width": 32, "height": 32, "color_mode": "rgb"}, "label": "create canvas"})

# Step 2: Set palette
commands.append({"tool": "set_palette", "args": {"sprite_path": "SPRITE", "colors": [BLK, ARM, TUN, HI]}, "label": "set palette"})

# Step 3: Body scaffolding with rectangles
# -- HELMET (top, rows 2-5, centered) --
commands.append(rect(11, 2, 10, 4, ARM))        # helmet body 10x4
commands.append({"label": "helmet"})

# -- PLUME (red, on top of helmet, rows 0-3) --
commands.append(rect(14, 0, 4, 3, TUN))         # plume base 4x3

# -- VISOR SLIT (black, row 4-5) --
commands.append(rect(13, 5, 6, 2, BLK))         # visor area
commands.append(rect(14, 5, 4, 2, ARM))         # visor interior gray (leaving black border)

# -- TORSO (armor, rows 7-18) --
commands.append(rect(9, 7, 14, 12, ARM))        # main torso 14x12

# -- TUNIC visible below armor (rows 15-18) --
commands.append(rect(10, 15, 12, 4, TUN))       # tunic strip

# -- SHIELD on left arm (rows 8-15, cols 3-8) --
commands.append(rect(3, 8, 6, 8, ARM))          # shield body 6x8

# -- SWORD in right hand (cols 24-25, rows 4-20) --
commands.append(rect(24, 4, 2, 16, ARM))        # sword blade 2x16
commands.append(rect(22, 18, 6, 2, ARM))        # sword crossguard

# -- LEGS (rows 19-27, two columns with gap) --
commands.append(rect(11, 19, 4, 9, ARM))        # left leg
commands.append(rect(17, 19, 4, 9, ARM))        # right leg

# -- BOOTS (rows 26-29) --
commands.append(rect(10, 26, 6, 4, TUN))        # left boot
commands.append(rect(16, 26, 6, 4, TUN))        # right boot

# Step 4: Detail and highlights with draw_pixels
detail_pixels = []

# Helmet highlight (top-left edge, rows 2-3)
for y in range(2, 4):
    for x in range(11, 13):
        detail_pixels.append((x, y, HI))

# Helmet plume highlight
detail_pixels.extend([(14, 0, HI), (15, 0, HI), (14, 1, HI), (15, 1, HI)])

# Shield highlight (top-left of shield)
for y in range(8, 10):
    for x in range(3, 5):
        detail_pixels.append((x, y, HI))

# Shield cross emblem (red)
detail_pixels.extend([
    (5, 10, TUN), (6, 10, TUN),  # horizontal
    (5, 11, TUN), (6, 11, TUN),
    (5, 12, TUN), (6, 12, TUN),
    (4, 11, TUN), (7, 11, TUN),  # vertical extension
])

# Torso highlight (top-left edge of armor)
for y in range(7, 10):
    for x in range(9, 11):
        detail_pixels.append((x, y, HI))

# Sword highlight (top of blade)
detail_pixels.extend([(24, 4, HI), (25, 4, HI), (24, 5, HI), (25, 5, HI)])

# Sword handle (below crossguard)
detail_pixels.extend([
    (24, 20, TUN), (25, 20, TUN),
    (24, 21, TUN), (25, 21, TUN),
])

# Leg highlight (top-left of each leg)
detail_pixels.extend([(11, 19, HI), (12, 19, HI), (11, 20, HI), (12, 20, HI)])
detail_pixels.extend([(17, 19, HI), (18, 19, HI), (17, 20, HI), (18, 20, HI)])

# Eyes through visor (2x2 each, red glow)
detail_pixels.extend([
    (14, 5, TUN), (15, 5, TUN),
    (14, 6, TUN), (15, 6, TUN),
    (17, 5, TUN), (18, 5, TUN),
    (17, 6, TUN), (18, 6, TUN),
])

commands.append(pixels(detail_pixels))
commands[-1]["label"] = "details and highlights"

# Step 5: Apply outline (1px black)
commands.append({"tool": "apply_outline", "args": {
    "sprite_path": "SPRITE", "layer_name": "Layer 1", "frame_number": 1,
    "color": BLK, "thickness": 1
}, "label": "apply outline"})

# Step 6: Export as PNG
commands.append({"tool": "export_sprite", "args": {
    "sprite_path": "SPRITE", "output_path": OUT_PNG, "format": "png", "frame_number": 1
}, "label": "export PNG"})

# Remove the empty placeholder command
commands = [c for c in commands if "tool" in c]

# Write commands JSON
out_json = os.path.join(os.path.dirname(__file__), "sprite1_cmds.json")
with open(out_json, "w") as f:
    json.dump(commands, f, indent=2)

print(f"Commands written to {out_json}")
print(f"Run: python tools/mcp_driver.py {out_json}")
print(f"Then replace SPRITE placeholders with actual path from create_canvas output.")

import sys, shutil
from pathlib import Path
import numpy as np
from PIL import Image
sys.path.insert(0, "/home/user/retrogaze/proof"); sys.path.insert(0, "/home/user/retrogaze/src")
import build_snes_rom, run_mesen, compare
from retrogaze.codemode import ppu_ref_snes
from retrogaze.codemode.build import scene_for_rom
from retrogaze.codemode.encode.snes import encode_scene
S = Path(sys.argv[1]); d = S / "topwrap"; shutil.rmtree(d, ignore_errors=True); d.mkdir(parents=True)
files, name, m = scene_for_rom(Path("/home/user/retrogaze/examples/codemode/snes/snes_proof.px.js"), "proof", False, "snes")
for k, v in files.items(): (d / k).write_bytes(v)
b = encode_scene(m)
oam = bytearray(b.oam[0]); print("OBJ2", oam[8:12].hex()); oam[9] = 250       # hero 32x32: Y byte 250
ref = ppu_ref_snes.render(b.vram(0), b.cgram, bytes(oam), b.registers)
Image.fromarray(ref).save(d / "proof.ref.png"); (d / "proof.oam").write_bytes(bytes(oam))
build_snes_rom.build(d, "proof", d / "p.sfc")
run_mesen.run(S / "mesen2/bin/Mesen", d / "p.sfc", d / "run")
r = compare.compare(d, "proof", d / "run", "snes")
print("gate_c", r["gate_c"]["ok"], "gate_d", r["gate_d"]["ok"], {k: v for k, v in r["gate_d"].items() if k in ("mismatched_pixels", "expected_colors", "screen_colors")})
top = ref[0:26, 0:256]; print("ref has hero pixels in lines 0-25:", int((top != ref[27:28]).any()))

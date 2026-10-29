import sys, json
from pathlib import Path
sys.path.insert(0, "/home/user/retrogaze/proof"); sys.path.insert(0, "/home/user/retrogaze/src")
import run_codemode_proof as P
S = Path(sys.argv[1]); art = sys.argv[2]; scene = sys.argv[3]; expect = sys.argv[4] if len(sys.argv) > 4 else "legal"
spec = {"id": "probe_" + Path(art).stem, "console": "snes", "scene": scene, "art": art, "expect": expect}
res = P.run_snes_scene(spec, S / "mesen2/bin/Mesen", S / "probe_out", {}, True, None)
res["compare"] = {k: {kk: vv for kk, vv in v.items() if kk != "color_map"} for k, v in res["compare"].items()}
print(json.dumps(res, indent=1)[:3000])

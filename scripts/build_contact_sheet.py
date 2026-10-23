#!/usr/bin/env python3
"""Build a self-contained contact sheet for Ray's eyes on the wave-3 driver-arm sprites.

Per the standing convention: never a bare montage. Labels live in the HTML, every section
says what to look for and asks a verdict question, and the file gets a fresh timestamped
name so macOS Preview can never show a cached older version.
"""
import base64
import json
import os
from datetime import datetime
from pathlib import Path

EXP = Path(os.environ.get("RETROGAZE_CONTACT_EXP", "experiments"))
STAMP = datetime.now().strftime("%Y-%m-%d-%H%M")
OUT = Path(os.environ.get("RETROGAZE_CONTACT_OUT", f"retrogaze-wave3-driver-arms-{STAMP}.html"))

CASES = [
    ("01-armored-knight-with-round-shield-s101", "Armored knight with round shield"),
    ("02-skeleton-archer-with-small-bow-s101", "Skeleton archer with small bow"),
    ("03-red-healing-potion-with-cork-s101", "Red healing potion with cork"),
]

FAILURES = [
    ("Green slime with eyes", "Protocol violation — drew after the final checkpoint, when only export is allowed."),
    ("Wizard holding a candle", "Painted 97 pixels of pure black that is not in the console palette. Blocked by the palette gate."),
    ("Street punk, denim vest", "Ran past a 16,000-token budget mid-draw. An output-budget limit, not a drawing failure."),
    ("Bat monster with torn wings", "Same off-palette black as the wizard — 83 pixels. Blocked."),
]


def b64(path: Path) -> str | None:
    if not path.exists():
        return None
    return base64.b64encode(path.read_bytes()).decode()


def img(path: Path, alt: str, size: int = 176) -> str:
    data = b64(path)
    if not data:
        return f'<div class="missing" style="width:{size}px;height:{size}px">not produced</div>'
    return (
        f'<img src="data:image/png;base64,{data}" alt="{alt}" '
        f'style="width:{size}px;height:{size}px">'
    )


def score_for(run_dir: str, case: str) -> str:
    import csv
    p = EXP / run_dir / "metrics.csv"
    if not p.exists():
        return "—"
    for row in csv.DictReader(p.open()):
        vals = " ".join(str(v) for v in row.values())
        if case.split("-")[0] in vals or case in vals:
            return row.get("score", "—")
    return "—"


sections = []
for case_dir, title in CASES:
    son = EXP / "wave3-sonnet-5-run3" / case_dir
    hai = EXP / "e6b-mcp-aseprite" / case_dir
    sections.append(f"""
    <section class="case">
      <h2>{title}</h2>
      <div class="row">
        <figure>
          {img(son / 'raw.png', title + ' sonnet raw')}
          <figcaption><b>Sonnet 5</b><br><span class="sub">raw output</span></figcaption>
        </figure>
        <figure>
          {img(son / 'processed.png', title + ' sonnet processed')}
          <figcaption><b>Sonnet 5</b><br><span class="sub">after enforcement</span></figcaption>
        </figure>
        <div class="divider"></div>
        <figure>
          {img(hai / 'raw.png', title + ' haiku raw')}
          <figcaption><b>Haiku 4.5</b><br><span class="sub">raw output</span></figcaption>
        </figure>
        <figure>
          {img(hai / 'processed.png', title + ' haiku processed')}
          <figcaption><b>Haiku 4.5</b><br><span class="sub">after enforcement</span></figcaption>
        </figure>
      </div>
      <p class="look"><b>What to look for:</b> is the subject readable at a glance? Do the shapes
      hold together, or is it coloured blocks? Does either one look like something you would
      put in a game?</p>
    </section>""")

# checkpoint progression, case 01 — evidence the render-inspect-revise loop now runs
c1 = EXP / "wave3-sonnet-5-run3" / CASES[0][0]
progression = f"""
    <section class="case">
      <h2>How Sonnet built the knight, step by step</h2>
      <div class="row">
        <figure>{img(c1 / 'checkpoint-silhouette-before-repair.png', 'sil before', 148)}
          <figcaption>1. silhouette<br><span class="sub">first pass</span></figcaption></figure>
        <figure>{img(c1 / 'checkpoint-silhouette-after-repair.png', 'sil after', 148)}
          <figcaption>2. silhouette<br><span class="sub">after self-critique</span></figcaption></figure>
        <figure>{img(c1 / 'checkpoint-color_detail-before-repair.png', 'col before', 148)}
          <figcaption>3. colour + detail<br><span class="sub">first pass</span></figcaption></figure>
        <figure>{img(c1 / 'checkpoint-color_detail-after-repair.png', 'col after', 148)}
          <figcaption>4. colour + detail<br><span class="sub">after self-critique</span></figcaption></figure>
      </div>
      <p class="look"><b>What to look for:</b> this is the model looking at its own canvas and
      revising — the loop that only started working today. Does step 2 actually improve on step 1,
      and step 4 on step 3? If the "after" images are no better, the self-critique is decorative.</p>
    </section>"""

# e9 reference, explicitly a different subject
e9dir = EXP / "e9-prerendered" / "12-crystal-treasure-chest-s101"
e9 = f"""
    <section class="case ref">
      <h2>For scale — your production path (e9), a DIFFERENT subject</h2>
      <div class="row">
        <figure>{img(e9dir / 'processed.png', 'e9 reference')}
          <figcaption><b>e9 FLUX pre-render</b><br><span class="sub">crystal treasure chest</span></figcaption></figure>
      </div>
      <p class="look"><b>Not a like-for-like comparison</b> — e9 never ran these three subjects, so
      this is here only to put the bar on screen. This is the path you called "almost exactly what
      I wish everything looked like." The question the sheet is really asking is whether anything
      above is in the same league.</p>
    </section>"""

fail_rows = "".join(
    f"<tr><td>{name}</td><td>{why}</td></tr>" for name, why in FAILURES
)

html = f"""<!doctype html>
<html><head><meta charset="utf-8">
<title>Retrogaze wave-3 driver arms — {STAMP}</title>
<style>
  body {{ background:#14121a; color:#e8e4de; font:15px/1.55 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
         margin:0; padding:40px 32px 80px; }}
  .wrap {{ max-width:1000px; margin:0 auto; }}
  h1 {{ font-size:26px; margin:0 0 6px; letter-spacing:-.01em; }}
  .stamp {{ color:#8b8496; font-size:13px; margin-bottom:26px; }}
  .caveat {{ background:#2a1f18; border-left:3px solid #c8783c; padding:16px 20px; margin:0 0 34px;
            border-radius:0 6px 6px 0; }}
  .caveat b {{ color:#e5a067; }}
  section.case {{ background:#1c1926; border:1px solid #2c2738; border-radius:10px;
                  padding:22px 24px 18px; margin-bottom:22px; }}
  section.ref {{ background:#181f1c; border-color:#2a3a33; }}
  h2 {{ font-size:17px; margin:0 0 16px; color:#cfc8dd; font-weight:600; }}
  .row {{ display:flex; gap:22px; align-items:flex-start; flex-wrap:wrap; }}
  figure {{ margin:0; text-align:center; }}
  img {{ image-rendering:pixelated; background:#0d0b12; border:1px solid #35304a; border-radius:4px; display:block; }}
  figcaption {{ margin-top:8px; font-size:12px; color:#bdb6cc; line-height:1.4; }}
  .sub {{ color:#7d7690; }}
  .divider {{ width:1px; align-self:stretch; background:#2f2a3e; margin:0 6px; }}
  .missing {{ background:#0d0b12; border:1px dashed #443c5c; color:#6b6480; font-size:11px;
              display:flex; align-items:center; justify-content:center; border-radius:4px; }}
  .look {{ margin:16px 0 0; font-size:13.5px; color:#a8a0b8; border-top:1px solid #2c2738; padding-top:13px; }}
  .look b {{ color:#d4cce4; }}
  table {{ width:100%; border-collapse:collapse; font-size:13.5px; margin-top:6px; }}
  td {{ padding:9px 12px; border-bottom:1px solid #2c2738; vertical-align:top; color:#a8a0b8; }}
  td:first-child {{ color:#d4cce4; width:230px; }}
  .verdict {{ background:#1a2430; border-left:3px solid #4d87b8; padding:18px 22px; margin-top:30px;
              border-radius:0 6px 6px 0; }}
  .verdict b {{ color:#7fb6e0; }}
  .verdict ol {{ margin:10px 0 0; padding-left:20px; }}
  .verdict li {{ margin-bottom:7px; color:#b8c4d0; }}
</style></head>
<body><div class="wrap">

<h1>Wave 3 — does a stronger model draw better sprites?</h1>
<div class="stamp">Generated {STAMP} · Sonnet 5 driving pixel-mcp / Aseprite · $2.47 of the $10 allowance</div>

<div class="caveat">
  <b>Read this before judging.</b> These three Sonnet sprites are the first ever produced through
  the <i>real</i> pixel-mcp and Aseprite path — three separate harness bugs were blocking it until
  today. The Haiku sprites beside them came from an older build whose metadata does not record
  which renderer actually drew them, so it was most likely a stand-in, not real Aseprite.
  <b>The automated scores are therefore not comparable, and I am not reporting them as a verdict.</b>
  You already found that the score anti-correlates with your own judgment anyway. Your eyes are
  the only measure here.
</div>

{"".join(sections)}
{progression}
{e9}

<section class="case">
  <h2>The four that failed, and why</h2>
  <table>{fail_rows}</table>
  <p class="look"><b>Worth noting:</b> none of these is "the model drew badly." Two were stopped for
  painting black that is not in the console palette, one broke the drawing protocol, one ran out of
  output budget mid-draw. Those are fixable — if the sprites above are good enough to be worth fixing.</p>
</section>

<div class="verdict">
  <b>What I need from you:</b>
  <ol>
    <li>Are any of these three sprites usable in a game, or is this whole path not close?</li>
    <li>Is Sonnet visibly better than Haiku on the same subject, visibly worse, or too close to call?</li>
    <li>Given the e9 reference above — is this path worth more money and time, or should e6b stay retired?</li>
  </ol>
</div>

</div></body></html>"""

OUT.write_text(html, encoding="utf-8")
print(f"wrote {OUT}")
print(f"size: {OUT.stat().st_size / 1024:.0f} KB (self-contained, images embedded)")

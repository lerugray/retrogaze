# Retrogaze

Pixel art generation for 7 classic systems in the app, plus Game Boy Pocket (beta) through the API and MCP. Real hardware constraints enforced: palette, tile limits, grid.

*Built by a game designer, not venture capital.*

Retrogaze is free and open source under the MIT license. Image generation runs on [fal.ai](https://fal.ai) with your own key.
The constraint engine runs offline and needs no key at all.

## What it does

- Generates sprites and tilesets inside the hardware limits of the NES, SNES, Sega Genesis / Mega Drive, Game Boy (DMG and
  Pocket), Game Boy Color, Commodore 64 and PC Engine.
- Enforces each console's palette, per-tile color cap and grid on any image you give it, generated or hand-drawn.
- Comes as a web app, a command-line tool and an MCP server that works with pixel-mcp and Aseprite.

## Install

```bash
python3.12 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r src/requirements-lock.txt

# Only for image generation:
echo "FAL_KEY=your-fal-key" > .env
```

You need Node 18 or newer only to build the MCP server in `mcp-server/`.

## Command line: enforce NES constraints offline

The CLI takes any PNG and returns it within NES limits, with a JSON report beside it. It needs no key.

```bash
cd src
python -m retrogaze ../test_sprites/final_validation/early_coin.png --size 16x16 --output /tmp/coin_nes.png
```

`--size` takes multiples of 8. `--max-colors` sets the per-tile cap (NES default: 4).

## Code mode: art drawn as code, proven NES-legal

Code mode draws pixel art from a small `.px.js` program (the [pxl](https://github.com/crsolver/claude-pxl) DSL,
vendored in `third_party/pxl`). No image model is involved. Each build checks the art against real NES hardware
limits (2C02 palette, attribute areas, 3 colors per sprite, 8 sprites per scanline, pattern-table budgets). It exports
the bytes the console loads (CHR, palette, nametable, OAM, plus ca65/cc65 includes), and it marks every output as
code-drawn with provenance you can verify. It needs Node 22.18 or newer.

```bash
cd src
python -m retrogaze.codemode build ../examples/codemode/nes_proof.px.js --console nes --tier legal
python -m retrogaze.codemode verify ../examples/codemode/out/nes/legal
python -m retrogaze.codemode rom ../examples/codemode/nes_proof.px.js     # viewer ROM, needs cc65
```

Every violation names the source line that painted the bad pixels. The `proof/` harness runs the exported bytes in
Mesen 2 to prove the result. See [docs/spec/CODE-MODE-SPEC.md](docs/spec/CODE-MODE-SPEC.md) and the agent skill in
`skills/retrogaze-code-mode/`.

## Web app

```bash
cd src
uvicorn retrogaze.api:app --host 127.0.0.1 --port 8000
# then open http://127.0.0.1:8000
```

Without `FAL_KEY` the app still starts and `/health` answers 200. `/generate` returns a message saying the key is missing.

## MCP server

The server talks to your local API at `http://localhost:8000` by default. Every era and tool is open.

```bash
cd mcp-server
npm ci && npm run build
# point your MCP client at: node /path/to/mcp-server/dist/index.js
# to use another API: RETROGAZE_API_URL=https://your-host
```

## Hosting a free demo (`RETROGAZE_DEMO=1`)

| Setting | Effect |
|---------|--------|
| `RETROGAZE_DEMO=1` | Turns on the demo profile. |
| `RETROGAZE_SAFETY_CHECKER=1` | Required with the demo. The server will not start without it. |
| `RETROGAZE_REPO_URL` | Link shown when the demo runs out of credits. Defaults to this repository. |
| (built in) | One image per request; reference-image uploads refused, since they use a costlier model. |

When the fal balance or a session cap runs out, the API tells visitors so and points them here to run Retrogaze themselves.

## Mock mode is for development only

`RETROGAZE_MOCK=1` skips real fal calls and treats every request as a full-access user. Use it on your own machine and in
tests. Never set it on a public host.

## Leftovers from the hosted product

Retrogaze used to be a paid web service. These modules came along and do nothing unless you configure Supabase,
LemonSqueezy or an email provider. You can run the engine, CLI, web app and MCP server without them.

- `payments.py`, `auth.py`, `supabase_client.py`, `email.py`
- `funnel.py`, `retention.py`, `suppression.py`
- `mcp_keys.py`, `mcp_auth.py`

## Tests

```bash
cd src
RETROGAZE_MOCK=1 python -m pytest tests/ -q
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). MIT licensed ([LICENSE](LICENSE)), copyright 2026 Ray Weiss.

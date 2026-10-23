# @retrogaze/mcp

Classic console pixel art intelligence for MCP clients. Get hardware-accurate drawing instructions, validate sprites against real console constraints, and auto-fix violations.

Works alongside [pixel-mcp](https://github.com/willibrandon/pixel-plugin) — Retrogaze supplies console expertise; pixel-mcp supplies Aseprite drawing tools.

**Supported consoles:** NES, SNES, Genesis/Mega Drive, Game Boy (DMG), Game Boy Color, Commodore 64, and PC Engine/TurboGrafx-16, plus Game Boy Pocket (beta, `gb_pocket`).

## Prerequisites

- Node.js 18+
- A running Retrogaze API (default `http://localhost:8000`)
- Optional: [pixel-mcp](https://github.com/willibrandon/pixel-mcp) + [Aseprite](https://www.aseprite.org/) for drawing

## Build

```bash
npm ci
npm run build
```

## Configure (Claude Desktop example)

```json
{
  "mcpServers": {
    "retrogaze": {
      "command": "node",
      "args": ["/absolute/path/to/retrogaze/mcp-server/dist/index.js"],
      "env": {
        "RETROGAZE_API_URL": "http://localhost:8000"
      }
    }
  }
}
```

## Environment

| Variable | Required | Description |
|----------|----------|-------------|
| `RETROGAZE_API_URL` | No | API endpoint (default `http://localhost:8000`). Non-local URLs must use HTTPS. |
| `RETROGAZE_LICENSE_KEY` | No | Unused. Accepted only so older configs still start. |

All eras and tools are available. The MCP server never spends fal or model-provider budget by itself.

## License

MIT — see the repository root `LICENSE`.

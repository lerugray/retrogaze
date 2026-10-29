#!/usr/bin/env node
/**
 * Retrogaze MCP Server
 *
 * Provides classic console pixel art intelligence as MCP tools.
 * Call retro_generate_prompt before drawing sprites with pixel-mcp
 * to get console-accurate prompts, palettes, and tool guidance.
 * Call retro_validate_sprite after drawing to check hardware compliance.
 *
 * Points at a local Retrogaze API by default (http://localhost:8000).
 * All eras and tools are available; no hosted account or license key required.
 */

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { RetrogazeClient } from "./client.js";
import { registerTools } from "./tools.js";

const VERSION = "1.0.0";
const BANNER = `
  ____      _
 |  _ \\ ___| |_ _ __ ___   __ _  __ _ _______
 | |_) / _ \\ __| '__/ _ \\ / _\` |/ _\` |_  / _ \\
 |  _ <  __/ |_| | | (_) | (_| | (_| |/ /  __/
 |_| \\_\\___|\\__|_|  \\___/ \\__, |\\__,_/___\\___|
                          |___/
  MCP Server v${VERSION} — Classic Console Pixel Art Intelligence
  7 consoles + Game Boy Pocket (beta) | 9 tools | open source
`;

// Handle --version and --help flags
const arg = process.argv[2];
if (arg === "--version" || arg === "-v") {
  console.log(`@retrogaze/mcp v${VERSION}`);
  process.exit(0);
}
if (arg === "--help" || arg === "-h") {
  console.log(BANNER);
  console.log("Usage: retrogaze-mcp");
  console.log("");
  console.log("Environment variables:");
  console.log("  RETROGAZE_API_URL      (optional) API endpoint (default: http://localhost:8000)");
  console.log("                          Non-local URLs must use HTTPS.");
  console.log("  RETROGAZE_LICENSE_KEY  (optional, unused) Accepted for compatibility with");
  console.log("                          older configs; not required.");
  console.log("");
  console.log("Flags:");
  console.log("  --version, -v   Print version and exit");
  console.log("  --help, -h      Print this help and exit");
  console.log("");
  console.log("Add to your Claude Code .mcp.json, Claude Desktop config, or Cursor settings.");
  console.log("See README.md for setup instructions.");
  process.exit(0);
}

// Banner on stderr (stdout is reserved for MCP protocol)
process.stderr.write(BANNER + "\n");

const server = new McpServer(
  {
    name: "retrogaze",
    version: VERSION,
  },
  {
    instructions:
      "Retrogaze provides classic console pixel art intelligence. " +
      "Call retro_generate_prompt BEFORE drawing sprites with pixel-mcp " +
      "to get console-accurate system prompts, palettes, and tool guidance. " +
      "Call retro_validate_sprite AFTER drawing to check hardware compliance. " +
      "Use retro_fix_sprite to auto-correct violations. " +
      "Supports 7 consoles plus Game Boy Pocket (beta, gb_pocket): NES, Game Boy (DMG), Game Boy Color, " +
      "C64, Genesis/Mega Drive, SNES, and PC Engine. " +
      "Pass console parameter to any tool (default: nes). " +
      "Code mode (retro_code_bind, retro_code_build, retro_code_verify) draws art as pxl .px.js code, " +
      "checks it against real NES hardware and exports console bytes with code-drawn provenance.",
    capabilities: {
      tools: {},
    },
  },
);

let client: RetrogazeClient;
try {
  client = new RetrogazeClient();
  const endpoint = process.env.RETROGAZE_API_URL ?? "http://localhost:8000";
  process.stderr.write(`  Connected — endpoint: ${endpoint}\n\n`);
} catch (e) {
  process.stderr.write(`  ERROR: ${(e as Error).message}\n\n`);
  process.exit(1);
}

// Register all 9 tools
registerTools(server, client);

// Graceful shutdown
function shutdown() {
  process.stderr.write("  Shutting down...\n");
  process.exit(0);
}
process.on("SIGINT", shutdown);
process.on("SIGTERM", shutdown);
process.on("unhandledRejection", (reason) => {
  process.stderr.write(`  Unhandled rejection: ${reason}\n`);
});

// Connect via stdio transport
const transport = new StdioServerTransport();
await server.connect(transport);

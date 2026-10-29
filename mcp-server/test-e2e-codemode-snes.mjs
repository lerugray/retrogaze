// End-to-end check of the retro_code_* tools for --console snes (M2): a real MCP client talks to the built
// server over stdio, which talks to a local Retrogaze API with code mode on. Driven by test-e2e-codemode-snes.sh.
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import assert from "node:assert/strict";

const [artFile, apiUrl] = process.argv.slice(2);
const transport = new StdioClientTransport({
  command: process.execPath,
  args: ["dist/index.js"],
  env: { ...process.env, RETROGAZE_API_URL: apiUrl },
  stderr: "ignore",
});
const client = new Client({ name: "retrogaze-e2e-snes", version: "1.0.0" });
await client.connect(transport);
const text = (r) => r.content.map((c) => c.text).join("\n");

const bind = await client.callTool({ name: "retro_code_bind", arguments: { console: "snes" } });
assert.ok(!bind.isError && text(bind).includes("| SNES-H11 |") && text(bind).includes("snes(r5, g5, b5)"), text(bind));
console.log("  PASS: retro_code_bind returns the SNES rule table");

const built = await client.callTool({ name: "retro_code_build", arguments: { file_path: artFile, console: "snes", author: "llm" } });
assert.ok(!built.isError, text(built));
assert.match(text(built), /verdict: legal/);
assert.match(text(built), /slivers per line/);
const out = /wrote \d+ files to (.+)$/m.exec(text(built))[1].trim();
assert.match(out, /out[\\/]snes[\\/]legal$/);
console.log(`  PASS: retro_code_build --console snes -> verdict legal, outputs in ${out}`);

const verified = await client.callTool({ name: "retro_code_verify", arguments: { out_dir: out } });
assert.ok(!verified.isError && text(verified).startsWith("✓ VERIFIED"), text(verified));
console.log("  PASS: retro_code_verify -> verified");

await client.close();

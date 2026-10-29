// End-to-end check of the retro_code_* tools: a real MCP client talks to the built server over stdio,
// which talks to a local Retrogaze API with code mode on. Driven by test-e2e-codemode.sh.
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
const client = new Client({ name: "retrogaze-e2e", version: "1.0.0" });
await client.connect(transport);

const text = (r) => r.content.map((c) => c.text).join("\n");
const { tools } = await client.listTools();
const names = tools.map((t) => t.name);
for (const t of ["retro_code_bind", "retro_code_build", "retro_code_verify"]) assert.ok(names.includes(t), `missing ${t}`);
console.log(`  PASS: ${tools.length} tools listed, including retro_code_bind/build/verify`);

const bind = await client.callTool({ name: "retro_code_bind", arguments: { console: "nes" } });
assert.ok(!bind.isError && text(bind).includes("| NES-H9 |"), text(bind));
console.log("  PASS: retro_code_bind returns the NES rule table");

const built = await client.callTool({ name: "retro_code_build", arguments: { file_path: artFile, author: "llm" } });
assert.ok(!built.isError, text(built));
assert.match(text(built), /verdict: legal/);
const out = /wrote \d+ files to (.+)$/m.exec(text(built))[1].trim();
console.log(`  PASS: retro_code_build -> verdict legal, outputs in ${out}`);

const verified = await client.callTool({ name: "retro_code_verify", arguments: { out_dir: out } });
assert.ok(!verified.isError && text(verified).startsWith("✓ VERIFIED"), text(verified));
console.log("  PASS: retro_code_verify -> verified");

const png = await client.callTool({ name: "retro_code_build", arguments: { file_path: artFile.replace(/\.px\.js$/, ".png") } });
assert.ok(png.isError && /no images/.test(text(png)), text(png));
console.log("  PASS: retro_code_build refuses a non-art (image) file");

await client.close();

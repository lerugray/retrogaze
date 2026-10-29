/**
 * MCP tool definitions and handlers for Retrogaze console intelligence.
 *
 * Nine tools, all prefixed with retro_ to avoid collision with pixel-mcp tools.
 * These provide classic console expertise — prompt generation, constraint
 * validation, palette suggestions. MCP clients use these alongside pixel-mcp
 * for drawing. Each tool accepts a `console` parameter (default: "nes").
 *
 * The three retro_code_* tools drive code mode: art written as pxl .px.js code,
 * checked against real console hardware, exported as console bytes with
 * provenance (docs/spec/CODE-MODE-SPEC.md). They send source text only, never images.
 */

import { z } from "zod";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { readFile, writeFile, lstat, stat, access, mkdir, readdir, rm } from "node:fs/promises";
import { constants } from "node:fs";
import { resolve, extname, dirname, basename, join, isAbsolute, relative, sep } from "node:path";
import { RetrogazeClient, RetrogazeApiError } from "./client.js";
import type { CodeBuildResponse, CodeViolation } from "./types.js";

// Supported console profiles (gb_pocket is beta) — intentionally excludes snes_mode7 (experimental).
// Matches Python ConsoleProfile system for advertised MCP API consoles.
const CONSOLE_ENUM = [
  "nes", "gb_dmg", "gb_pocket", "gbc",
  "c64",
  "genesis", "snes", "pc_engine",
] as const;
const consoleSchema = z.enum(CONSOLE_ENUM).default("nes").describe(
  "Target console: nes, gb_dmg, gb_pocket (beta), gbc, c64, genesis, snes, pc_engine"
);

// Security: max file size for reading (NES sprites are tiny)
const MAX_IMAGE_BYTES = 4 * 1024 * 1024; // 4 MB
const MAX_FIXED_BYTES = 5 * 1024 * 1024; // 5 MB for fixed output

// Security: block access to sensitive paths
const SENSITIVE_PATTERNS = [/[/\\]\.ssh[/\\]/, /[/\\]\.aws[/\\]/, /[/\\]\.gnupg[/\\]/, /credentials/i, /\.env$/, /\.pem$/, /\.key$/];

async function validateFilePath(filePath: string): Promise<string | null> {
  const absPath = resolve(filePath);

  // Extension whitelist — only PNGs
  if (extname(absPath).toLowerCase() !== ".png") {
    return "Only .png files are supported.";
  }

  // Block sensitive paths
  if (SENSITIVE_PATTERNS.some((p) => p.test(absPath))) {
    return "Access to that path is not permitted.";
  }

  // Reject symlinks
  try {
    const lstats = await lstat(absPath);
    if (lstats.isSymbolicLink()) {
      return "Symbolic links are not supported for security reasons.";
    }
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code === "ENOENT") {
      return `File not found: ${filePath}`;
    }
    return "Could not access file.";
  }

  // Size check
  try {
    const fileStat = await stat(absPath);
    if (fileStat.size > MAX_IMAGE_BYTES) {
      return `File is too large (${(fileStat.size / 1024 / 1024).toFixed(1)} MB). Maximum is 4 MB.`;
    }
  } catch {
    return "Could not read file size.";
  }

  return null; // all checks passed
}

// ---------------------------------------------------------------------------
// Code mode helpers: art sources in, outputs out (never images in)
// ---------------------------------------------------------------------------

const ART_SUFFIXES = [".px.js", ".px.ts"];
const MAX_ART_FILES = 32;
const MAX_ART_BYTES = 256 * 1024;
const INCLUDE_RE = /\binclude\(\s*(["'`])([^"'`]+)\1\s*\)/g;

function isArtFile(p: string): boolean {
  return ART_SUFFIXES.some((s) => p.endsWith(s));
}

async function checkArtPath(absPath: string): Promise<string | null> {
  if (!isArtFile(absPath)) return "Only .px.js / .px.ts art files are accepted (code mode takes no images).";
  if (SENSITIVE_PATTERNS.some((p) => p.test(absPath))) return "Access to that path is not permitted.";
  try {
    if ((await lstat(absPath)).isSymbolicLink()) return "Symbolic links are not supported for security reasons.";
  } catch {
    return `File not found: ${absPath}`;
  }
  return null;
}

/** The entry file plus every art file it includes through string-literal include() paths. */
async function readArtFiles(entryPath: string): Promise<{ files: Record<string, string>; entry: string; root: string } | string> {
  const entry = resolve(entryPath);
  const root = dirname(entry);
  const files: Record<string, string> = {};
  const todo = [entry];
  let total = 0;
  while (todo.length) {
    const p = todo.pop()!;
    const rel = relative(root, p).split(sep).join("/");
    if (rel.startsWith("..")) return `${basename(p)} is outside the entry file's folder.`;
    if (rel in files) continue;
    const bad = await checkArtPath(p);
    if (bad) return bad;
    const text = await readFile(p, "utf8");
    total += Buffer.byteLength(text);
    if (total > MAX_ART_BYTES) return `Art sources exceed ${MAX_ART_BYTES / 1024} KiB.`;
    files[rel] = text;
    if (Object.keys(files).length > MAX_ART_FILES) return `More than ${MAX_ART_FILES} art files.`;
    for (const m of text.matchAll(INCLUDE_RE)) {
      const target = resolve(dirname(p), m[2]);
      try {
        if ((await stat(target)).isFile()) todo.push(target);
      } catch {
        /* the build reports the missing include with its location */
      }
    }
  }
  return { files, entry: relative(root, entry).split(sep).join("/"), root };
}

function summarize(result: CodeBuildResponse): string {
  const r = result.report;
  if (r.errors?.length) {
    return r.errors.map((e) => `✗ ${e.code}: ${e.message}`).join("\n");
  }
  const lines = [`verdict: ${result.verdict}`];
  const all: CodeViolation[] = [...(r.violations ?? []), ...(r.scenes ?? []).flatMap((s) => s.violations)];
  for (const v of all) {
    const where = v.blame?.[0]?.loc ?? "";
    lines.push(`  ${v.rule} [${v.severity === "warning" ? "warning" : v.tier}] ${where}: ${v.message}`);
    if (v.hint) lines.push(`      hint: ${v.hint}`);
  }
  for (const s of r.scenes ?? []) {
    if (!s.checked || !s.budgets) continue;
    const b = s.budgets;
    const extra = b.slivers ? `, ${b.slivers.used}/${b.slivers.max} slivers per line, VRAM ${b.vram.used}/${b.vram.max} bytes` : "";
    lines.push(`  scene ${s.name}: ${s.legal ? "legal" : "NOT legal"}; BG tiles ${b.bg_tiles.used}/${b.bg_tiles.max}, ` +
      `OBJ tiles ${b.obj_tiles.used}/${b.obj_tiles.max}, OAM ${b.oam.used}/${b.oam.max}, ` +
      `max ${b.per_line.used}/${b.per_line.max} per line${extra}`);
  }
  return lines.join("\n");
}

async function writeCodeOutputs(root: string, consoleName: string, tier: string, result: CodeBuildResponse): Promise<string> {
  const out = join(root, "out", consoleName, tier);
  try {
    const entries = await readdir(out);
    if (entries.length && !entries.includes("manifest.json")) {
      throw new Error(`${out} exists and is not a code-mode output folder; refusing to overwrite`);
    }
    await rm(out, { recursive: true, force: true });
  } catch (e) {
    if ((e as NodeJS.ErrnoException).code !== "ENOENT") throw e;
  }
  for (const [rel, b64] of Object.entries(result.outputs ?? {})) {
    const target = resolve(out, rel);
    if (!target.startsWith(out + sep)) throw new Error(`refusing to write outside ${out}: ${rel}`);
    await mkdir(dirname(target), { recursive: true });
    await writeFile(target, Buffer.from(b64, "base64"));
  }
  const manifest = { ...(result.manifest ?? {}) } as Record<string, unknown>;
  manifest.build = { ...(manifest.build as Record<string, unknown>), source_dir: relative(out, root).split(sep).join("/") };
  await writeFile(join(out, "manifest.json"), JSON.stringify(manifest, null, 2) + "\n");
  return out;
}

function errorResult(message: string) {
  return { content: [{ type: "text" as const, text: message }], isError: true };
}

function textResult(text: string) {
  return { content: [{ type: "text" as const, text }] };
}

export function registerTools(server: McpServer, client: RetrogazeClient): void {
  // -----------------------------------------------------------------
  // retro_generate_prompt
  // -----------------------------------------------------------------
  server.tool(
    "retro_generate_prompt",
    "Get console-optimized drawing instructions for an MCP-capable client using pixel-mcp. Call this BEFORE drawing sprites to get era-accurate prompts, palettes, and tool guidance.",
    {
      console: consoleSchema,
      description: z.string().max(500).describe("What to draw, e.g. 'a warrior with a sword'"),
      asset_type: z.enum(["character", "enemy", "item", "tile", "tileset", "spritesheet", "directional", "ui_element", "ui_frame"]).default("character").describe("Type of sprite to generate"),
      era: z.enum(["retro", "early", "mid", "late"]).default("mid").describe("Console era: retro (earliest), early, mid, late (most advanced)"),
      size: z.string().regex(/^\d+x\d+$/).default("16x16").describe("Canvas size, e.g. 16x16"),
      view: z.enum(["side", "front", "top_down", "three_quarter"]).default("side").describe("Camera angle: side, front, top_down, three_quarter"),
      palette_mood: z.string().default("auto").describe("Palette mood: auto, warm, cool, earth, dark, etc."),
      outline: z.enum(["Black", "Dark", "No"]).default("Black").describe("Outline style"),
      palette_colors: z.array(z.string().regex(/^#[0-9A-Fa-f]{6}$/)).max(6).optional().describe("Optional: up to 6 hex colors to use"),
      seed: z.number().int().optional().describe("Random seed for reproducibility"),
    },
    { readOnlyHint: true, destructiveHint: false },
    async ({ console: consoleName, description, asset_type, era, size, view, palette_mood, outline, palette_colors, seed }) => {
      try {
        const result = await client.getPrompt({
          console: consoleName,
          description,
          asset_type,
          era,
          size,
          view,
          palette_mood,
          outline,
          palette_colors: palette_colors ?? undefined,
          seed: seed ?? undefined,
        });

        const displayConsole = consoleName.toUpperCase().replace(/_/g, " ");
        const output = [
          `=== ${displayConsole} DRAWING INSTRUCTIONS ===`,
          "",
          `Console: ${displayConsole}`,
          `Canvas: ${result.canvas.width}x${result.canvas.height} (${result.canvas.color_mode})`,
          `Era: ${era} | Outline: ${outline}`,
          `Palette (${result.palette.colors.length} colors):`,
          ...result.palette.colors.map(
            (c) => `  ${c} — ${result.palette.roles[c] ?? "extra"}`,
          ),
          "",
          "=== SYSTEM PROMPT (feed to your drawing model alongside pixel-mcp tools) ===",
          "",
          result.system_prompt,
          "",
          "=== USER PROMPT ===",
          "",
          result.user_prompt,
          "",
          result.remaining_calls != null
            ? `[${result.remaining_calls} API calls remaining this month]`
            : "",
        ];

        return textResult(output.join("\n"));
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.detail);
        throw e;
      }
    },
  );

  // -----------------------------------------------------------------
  // retro_validate_sprite
  // -----------------------------------------------------------------
  server.tool(
    "retro_validate_sprite",
    "Check if an image meets classic console hardware constraints. Returns a compliance report with specific violations.",
    {
      console: consoleSchema,
      file_path: z.string().regex(/\.png$/i).describe("Absolute path to the PNG file to validate"),
      asset_type: z.enum(["sprite", "background"]).default("sprite").describe("Asset type for validation context"),
      target_size: z.string().regex(/^\d+x\d+$/).optional().describe("Optional target size, e.g. 16x16"),
      max_colors_per_tile: z.number().int().min(1).max(8).default(4).describe("Max unique colors per 8x8 tile"),
    },
    { readOnlyHint: true, destructiveHint: false },
    async ({ console: consoleName, file_path, asset_type, target_size, max_colors_per_tile }) => {
      try {
        const pathError = await validateFilePath(file_path);
        if (pathError) return errorResult(pathError);

        const absPath = resolve(file_path);
        const imageData = await readFile(absPath);
        const imageBase64 = imageData.toString("base64");

        const result = await client.validateSprite({
          console: consoleName,
          image_base64: imageBase64,
          asset_type,
          target_size: target_size ?? undefined,
          max_colors_per_tile,
          fix: false,
        });

        const compliance = result.metadata.compliance as Record<string, unknown> ?? {};
        const displayConsole = consoleName.toUpperCase().replace(/_/g, " ");
        const lines = [
          result.compliant ? `✓ ${displayConsole} COMPLIANT` : `✗ NOT ${displayConsole} COMPLIANT`,
          "",
          `Console: ${displayConsole}`,
          `Palette valid: ${compliance.palette_valid ?? "unknown"}`,
          `Colors per tile valid: ${compliance.colors_per_tile_valid ?? "unknown"}`,
          `Grid aligned: ${compliance.grid_aligned ?? "unknown"}`,
        ];

        if (!result.compliant) {
          lines.push(
            "",
            `Use retro_fix_sprite to auto-correct violations.`,
          );
        }

        if (result.remaining_calls != null) {
          lines.push("", `[${result.remaining_calls} API calls remaining]`);
        }

        return textResult(lines.join("\n"));
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.detail);
        if ((e as NodeJS.ErrnoException).code === "ENOENT") {
          return errorResult(`File not found: ${file_path}`);
        }
        return errorResult("An unexpected error occurred. Check your setup and try again.");
      }
    },
  );

  // -----------------------------------------------------------------
  // retro_fix_sprite
  // -----------------------------------------------------------------
  server.tool(
    "retro_fix_sprite",
    "Auto-fix hardware constraint violations in an image. Remaps colors to the console's palette, reduces per-tile colors, aligns to grid. Saves the fixed image alongside the original.",
    {
      console: consoleSchema,
      file_path: z.string().regex(/\.png$/i).describe("Absolute path to the PNG file to fix"),
      asset_type: z.enum(["sprite", "background"]).default("sprite").describe("Asset type"),
      target_size: z.string().regex(/^\d+x\d+$/).optional().describe("Optional target size"),
      max_colors_per_tile: z.number().int().min(1).max(8).default(4).describe("Max unique colors per 8x8 tile"),
    },
    { readOnlyHint: false, destructiveHint: true },
    async ({ console: consoleName, file_path, asset_type, target_size, max_colors_per_tile }) => {
      try {
        const pathError = await validateFilePath(file_path);
        if (pathError) return errorResult(pathError);

        const absPath = resolve(file_path);
        const imageData = await readFile(absPath);
        const imageBase64 = imageData.toString("base64");

        const result = await client.validateSprite({
          console: consoleName,
          image_base64: imageBase64,
          asset_type,
          target_size: target_size ?? undefined,
          max_colors_per_tile,
          fix: true,
        });

        if (result.fixed_image_base64) {
          // Validate response size before writing
          const fixedBuffer = Buffer.from(result.fixed_image_base64, "base64");
          if (fixedBuffer.length > MAX_FIXED_BYTES) {
            return errorResult("API returned an unexpectedly large image. Aborting write.");
          }

          // Write fixed image next to original
          const dir = dirname(absPath);
          const name = basename(absPath, ".png");
          const fixedPath = join(dir, `${name}_${consoleName}_fixed.png`);

          // Refuse to overwrite existing files
          try {
            await access(fixedPath, constants.F_OK);
            return errorResult(`Output file already exists: ${fixedPath}. Delete it first.`);
          } catch {
            // File doesn't exist — safe to write
          }

          await writeFile(fixedPath, fixedBuffer);

          const displayConsole = consoleName.toUpperCase().replace(/_/g, " ");
          return textResult(
            [
              result.compliant ? `✓ Already ${displayConsole} compliant` : `✓ Fixed — ${displayConsole} constraints applied`,
              `Saved to: ${fixedPath}`,
              "",
              result.remaining_calls != null
                ? `[${result.remaining_calls} API calls remaining]`
                : "",
            ].join("\n"),
          );
        }

        const displayConsole = consoleName.toUpperCase().replace(/_/g, " ");
        return textResult(
          result.compliant
            ? `✓ Image is already ${displayConsole} compliant. No fix needed.`
            : "Could not auto-fix. Check the image format (PNG required) and try again.",
        );
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.detail);
        if ((e as NodeJS.ErrnoException).code === "ENOENT") {
          return errorResult(`File not found: ${file_path}`);
        }
        return errorResult("An unexpected error occurred. Check your setup and try again.");
      }
    },
  );

  // -----------------------------------------------------------------
  // retro_suggest_palette
  // -----------------------------------------------------------------
  server.tool(
    "retro_suggest_palette",
    "Get palette colors for a target console. Returns hex colors from the console's authentic hardware palette.",
    {
      console: consoleSchema,
      mood: z.string().default("auto").describe("Palette mood: warm, cool, earth, dark, heroic, eerie, aquatic, fire, or auto"),
      preset: z.string().optional().describe("Named preset: mario_red, megaman_blue, castlevania_dark, etc."),
    },
    { readOnlyHint: true, destructiveHint: false },
    async ({ console: consoleName, mood, preset }) => {
      try {
        const palettes = await client.getPalettes(consoleName);

        if (preset) {
          const colors = palettes.presets[preset];
          if (!colors) {
            return errorResult(
              `Unknown preset "${preset}". Available: ${Object.keys(palettes.presets).join(", ")}`,
            );
          }
          return textResult(
            [`Preset: ${preset}`, ...colors.map((c) => `  ${c}`)].join("\n"),
          );
        }

        const displayConsole = consoleName.toUpperCase().replace(/_/g, " ");
        const paletteKey = palettes.master_palette ?? palettes.nes_palette ?? [];
        const lines = [
          `${displayConsole} palette (${paletteKey.length} colors):`,
          paletteKey.join(", "),
          "",
          "Available moods: " + palettes.moods.join(", "),
          "",
          "Available presets:",
          ...Object.entries(palettes.presets).map(
            ([name, colors]) => `  ${name}: ${colors.join(", ")}`,
          ),
        ];

        return textResult(lines.join("\n"));
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.detail);
        throw e;
      }
    },
  );

  // -----------------------------------------------------------------
  // retro_list_presets
  // -----------------------------------------------------------------
  server.tool(
    "retro_list_presets",
    "List all available palette presets with their colors for the target console.",
    {},
    { readOnlyHint: true, destructiveHint: false },
    async () => {
      try {
        const palettes = await client.getPalettes();

        const lines = Object.entries(palettes.presets).map(
          ([name, colors]) => `${name}: ${colors.join(", ")}`,
        );

        return textResult(lines.join("\n"));
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.detail);
        throw e;
      }
    },
  );

  // -----------------------------------------------------------------
  // retro_check_status
  // -----------------------------------------------------------------
  server.tool(
    "retro_check_status",
    "Check your Retrogaze license tier, API usage, and available eras.",
    {},
    { readOnlyHint: true, destructiveHint: false },
    async () => {
      try {
        const status = await client.getStatus();

        const lines = [
          `Tier: ${status.tier}`,
          `Usage: ${status.monthly_used}${status.monthly_limit ? ` / ${status.monthly_limit}` : " (unlimited)"}`,
          status.remaining_calls != null
            ? `Remaining: ${status.remaining_calls} calls`
            : "Remaining: unlimited",
          `Available eras: ${status.available_eras.join(", ")}`,
        ];

        return textResult(lines.join("\n"));
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.detail);
        throw e;
      }
    },
  );

  // -----------------------------------------------------------------
  // retro_code_bind
  // -----------------------------------------------------------------
  server.tool(
    "retro_code_bind",
    "Code mode: get the console binding cheat sheet (color helpers like nes(byte) or snes(r, g, b), rg.scene, and every hardware rule) BEFORE writing a .px.js art file.",
    {
      console: z.enum(["nes", "snes"]).default("nes").describe("Console (code mode supports nes and snes in this build)"),
      tier: z.enum(["like", "legal"]).default("legal").describe("like = palette and grid of the era; legal = real hardware limits"),
    },
    { readOnlyHint: true, destructiveHint: false },
    async ({ console: consoleName, tier }) => {
      try {
        const res = await client.codeBinding(consoleName, tier);
        return textResult(res.cheatsheet);
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.status === 404 ? "Code mode is off on this API (set RETROGAZE_CODE_MODE=1 on a local server)." : e.detail);
        return errorResult("An unexpected error occurred. Check your setup and try again.");
      }
    },
  );

  // -----------------------------------------------------------------
  // retro_code_build
  // -----------------------------------------------------------------
  server.tool(
    "retro_code_build",
    "Code mode: build a .px.js art file, check it against real console hardware, and write PNGs, a sprite sheet and (when console-legal) the console's bytes to <art dir>/out/<console>/<tier>/. Every violation names the source line to fix. Sends source text only.",
    {
      file_path: z.string().describe("Absolute path to the entry .px.js (or .px.ts) art file"),
      console: z.enum(["nes", "snes"]).default("nes").describe("Console (code mode supports nes and snes in this build)"),
      tier: z.enum(["like", "legal"]).default("legal").describe("like = palette and grid of the era; legal = real hardware limits"),
      author: z.enum(["human", "llm", "mixed", "unknown"]).default("unknown").describe("Who wrote the code: pass llm when you wrote it"),
    },
    { readOnlyHint: false, destructiveHint: false },
    async ({ file_path, console: consoleName, tier, author }) => {
      try {
        const art = await readArtFiles(file_path);
        if (typeof art === "string") return errorResult(art);
        const result = await client.codeBuild({ files: art.files, entry: art.entry, console: consoleName, tier, author });
        if (result.exit_code === 3) return errorResult(summarize(result));
        const out = await writeCodeOutputs(art.root, consoleName, tier, result);
        return textResult(`${summarize(result)}\n\nwrote ${Object.keys(result.outputs ?? {}).length} files to ${out}`);
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.status === 404 ? "Code mode is off on this API (set RETROGAZE_CODE_MODE=1 on a local server)." : e.detail);
        return errorResult(`Code build failed: ${(e as Error).message}`);
      }
    },
  );

  // -----------------------------------------------------------------
  // retro_code_verify
  // -----------------------------------------------------------------
  server.tool(
    "retro_code_verify",
    "Code mode: prove an output folder still comes from its recorded source (rebuilds and compares every file).",
    {
      out_dir: z.string().describe("Absolute path to an out/<console>/<tier> folder written by retro_code_build"),
    },
    { readOnlyHint: true, destructiveHint: false },
    async ({ out_dir }) => {
      try {
        const out = resolve(out_dir);
        const manifest = JSON.parse(await readFile(join(out, "manifest.json"), "utf8")) as Record<string, any>;
        const build = manifest.build ?? {};
        const srcDir = resolve(out, build.source_dir ?? "../../..");
        const files: Record<string, string> = {};
        for (const name of build.files ?? []) {
          const p = resolve(srcDir, name);
          const bad = await checkArtPath(p);
          if (bad) return errorResult(bad);
          files[name] = await readFile(p, "utf8");
        }
        const outputs: Record<string, string> = {};
        for (const rel of Object.keys(manifest.outputs ?? {})) {
          const p = resolve(out, rel);
          if (!p.startsWith(out + sep)) return errorResult(`bad output path in manifest: ${rel}`);
          try {
            outputs[rel] = (await readFile(p)).toString("base64");
          } catch {
            /* missing outputs are reported by verify */
          }
        }
        const res = await client.codeVerify({ files, manifest, outputs });
        const head = res.exit_code === 0 ? "✓ VERIFIED" : res.exit_code === 4 ? "✗ VERSION MISMATCH" : "✗ NOT VERIFIED";
        return textResult([head, "", ...res.messages].join("\n"));
      } catch (e) {
        if (e instanceof RetrogazeApiError) return errorResult(e.status === 404 ? "Code mode is off on this API (set RETROGAZE_CODE_MODE=1 on a local server)." : e.detail);
        return errorResult(`Verify failed: ${(e as Error).message}`);
      }
    },
  );
}

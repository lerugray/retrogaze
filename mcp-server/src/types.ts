/**
 * TypeScript interfaces matching the Retrogaze MCP API request/response shapes.
 */

// --- Prompt API ---

export type ToolFormat = "anthropic" | "openai";

export interface AnthropicTool {
  name: string;
  description: string;
  input_schema: Record<string, unknown>;
}

export interface OpenAiTool {
  type: "function";
  function: {
    name: string;
    description: string;
    parameters: Record<string, unknown>;
  };
}

export interface PromptRequest {
  console?: string;
  description: string;
  asset_type?: string;
  era?: string;
  size?: string;
  view?: string;
  palette_mood?: string;
  outline?: string;
  palette_colors?: string[];
  seed?: number;
  tool_format?: ToolFormat;
}

export interface PromptResponse {
  system_prompt: string;
  user_prompt: string;
  canvas: {
    width: number;
    height: number;
    color_mode: string;
  };
  palette: {
    colors: string[];
    roles: Record<string, string>;
  };
  constraints: {
    max_colors: number;
    outline_style: string;
  };
  tool_whitelist: string[];
  tool_blacklist: string[];
  tools?: AnthropicTool[] | OpenAiTool[];
  remaining_calls: number | null;
}

// --- Validate API ---

export interface ValidateRequest {
  console?: string;
  image_base64: string;
  asset_type?: string;
  target_size?: string;
  max_colors_per_tile?: number;
  fix?: boolean;
}

export interface ValidateResponse {
  compliant: boolean;
  metadata: Record<string, unknown>;
  fixed_image_base64: string | null;
  remaining_calls: number | null;
}

// --- Palettes API ---

export interface PalettesResponse {
  nes_palette: string[];
  master_palette?: string[];
  presets: Record<string, string[]>;
  moods: string[];
}

// --- Status API ---

export interface StatusResponse {
  tier: string;
  monthly_used: number;
  monthly_limit: number | null;
  remaining_calls: number | null;
  available_eras: string[];
}

// --- Error ---

export interface ApiError {
  detail: string;
}

// --- Code mode API (/code/*) ---

export interface CodeBuildRequest {
  files: Record<string, string>;
  entry: string;
  console?: string;
  tier?: "like" | "legal";
  author?: "human" | "llm" | "mixed" | "unknown";
  include_outputs?: boolean;
}

export interface CodeViolation {
  rule: string;
  tier: string;
  scope: string;
  severity: string;
  message: string;
  asset?: string;
  scene?: string;
  hint?: string;
  blame?: { loc: string | null; op: string; pixels: number }[];
}

export interface CodeBuildResponse {
  exit_code: number;
  verdict: string;
  report: {
    verdict: string;
    errors?: { code: string; message: string; loc?: string | null }[];
    violations?: CodeViolation[];
    scenes?: { name: string; legal: boolean; checked: boolean; violations: CodeViolation[]; budgets?: Record<string, { used: number; max: number }> }[];
  };
  provenance: Record<string, unknown> | null;
  manifest: Record<string, unknown> | null;
  outputs: Record<string, string> | null;
}

export interface CodeVerifyRequest {
  files: Record<string, string>;
  manifest: Record<string, unknown>;
  outputs: Record<string, string>;
}

export interface CodeVerifyResponse {
  exit_code: number;
  messages: string[];
}

export interface CodeBindingResponse {
  console: string;
  tier: string;
  cheatsheet: string;
}

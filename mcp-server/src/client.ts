/**
 * Retrogaze API client.
 *
 * Calls a Retrogaze API at RETROGAZE_API_URL (default: local server).
 * All console intelligence lives server-side — this client just handles
 * HTTP and error mapping. RETROGAZE_LICENSE_KEY is accepted but unused
 * (legacy SaaS leftover; safe to omit).
 */

import type {
  PromptRequest,
  PromptResponse,
  ValidateRequest,
  ValidateResponse,
  PalettesResponse,
  StatusResponse,
  ApiError,
} from "./types.js";

export class RetrogazeApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly detail: string,
  ) {
    super(detail);
    this.name = "RetrogazeApiError";
  }
}

function isLocalHttpUrl(rawUrl: string): boolean {
  return (
    rawUrl.startsWith("http://localhost") ||
    rawUrl.startsWith("http://127.0.0.1")
  );
}

export class RetrogazeClient {
  private readonly baseUrl: string;
  private readonly licenseKey: string;

  constructor() {
    // License key is optional and unused in the open-source build.
    // Kept so existing configs that set it still start cleanly.
    this.licenseKey = process.env.RETROGAZE_LICENSE_KEY ?? "";

    const rawUrl = process.env.RETROGAZE_API_URL ?? "http://localhost:8000";
    if (!/^https:\/\//i.test(rawUrl) && !isLocalHttpUrl(rawUrl)) {
      throw new Error(
        "RETROGAZE_API_URL must use HTTPS (http://localhost and http://127.0.0.1 allowed for local use).",
      );
    }
    this.baseUrl = rawUrl.replace(/\/+$/, "");
  }

  get isAnonymous(): boolean {
    return this.licenseKey === "";
  }

  private async request<T>(
    method: "GET" | "POST",
    path: string,
    body?: unknown,
  ): Promise<T> {
    const url = `${this.baseUrl}${path}`;
    const headers: Record<string, string> = {
      "Content-Type": "application/json",
      "User-Agent": "retrogaze-mcp/1.0.0",
    };
    if (this.licenseKey !== "") {
      headers["Authorization"] = `Bearer ${this.licenseKey}`;
    }

    const res = await fetch(url, {
      method,
      headers,
      body: body ? JSON.stringify(body) : undefined,
    });

    if (!res.ok) {
      let detail = `HTTP ${res.status}`;
      try {
        const err = (await res.json()) as ApiError;
        detail = err.detail ?? detail;
      } catch {
        detail = `${res.status} ${res.statusText}`;
      }
      throw new RetrogazeApiError(res.status, this.friendlyError(res.status, detail));
    }

    return (await res.json()) as T;
  }

  private friendlyError(status: number, detail: string): string {
    switch (status) {
      case 401:
        return "API rejected the request (401). Check RETROGAZE_API_URL and that the local server is running.";
      case 403:
        return detail || "Access denied.";
      case 422:
        return `Invalid input: ${detail}`;
      case 429:
        return "Rate limit reached. Wait a moment and try again.";
      default:
        return detail;
    }
  }

  // --- Public API ---

  async getPrompt(params: PromptRequest): Promise<PromptResponse> {
    return this.request<PromptResponse>("POST", "/mcp/prompt", params);
  }

  async validateSprite(params: ValidateRequest): Promise<ValidateResponse> {
    return this.request<ValidateResponse>("POST", "/mcp/validate", params);
  }

  async getPalettes(console?: string): Promise<PalettesResponse> {
    const query = console && console !== "nes" ? `?console=${encodeURIComponent(console)}` : "";
    return this.request<PalettesResponse>("GET", `/mcp/palettes${query}`);
  }

  async getStatus(): Promise<StatusResponse> {
    return this.request<StatusResponse>("GET", "/mcp/status");
  }
}

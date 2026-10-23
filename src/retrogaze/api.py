"""
FastAPI backend for Retrogaze.

Endpoints
---------
POST /generate               — Generate a pixel-art asset from a text description.
GET  /palettes               — Return all NES 2C02 palette colors.
GET  /health                 — Liveness probe.
GET  /health/deep             — Readiness probe (checks FAL_KEY + fal.ai reachability).
GET  /history                — User's generation history (auth required).
GET  /usage                  — User's usage stats (auth required).
GET  /settings               — User's saved settings (auth required).
PUT  /settings               — Update user settings (auth required).
GET  /consent                — ToS/Privacy consent status (auth required).
POST /consent/accept         — Record ToS/Privacy consent (auth required).
POST /checkout               — Create a LemonSqueezy checkout URL (auth required).
POST /webhooks/lemonsqueezy  — LemonSqueezy webhook receiver (HMAC-verified).
GET  /subscription           — Current subscription status (auth required).
POST /billing-portal         — Get LemonSqueezy customer portal URL (auth required).
POST /waitlist               — Pre-launch email collection.
POST /auth/reset-password     — Send password-reset email via custom ESP.
POST /auth/resend-confirmation — Resend signup confirmation via custom ESP.
GET  /admin                  — Admin dashboard (password-protected).
GET  /admin/analytics         — Admin analytics dashboard (read-only, password-protected).
GET  /admin/api/stats        — Admin stats JSON (password-protected).
GET  /admin/api/feedback     — List submitted feedback for triage (password-protected).
PATCH /admin/api/feedback/{id} — Update feedback triage status (password-protected).
"""

from __future__ import annotations

import base64
import hmac
import json
import logging
import os
import re as _re
import tempfile
import time
import uuid
from pathlib import Path

# Load .env file if it exists (for FAL_KEY and other config)
_env_file = Path(__file__).resolve().parent.parent.parent / ".env"
if _env_file.is_file():
    with open(_env_file) as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                value = value.strip()
                # Strip a single pair of matching surrounding quotes (matches
                # python-dotenv behavior) so KEY="VALUE" doesn't import the
                # literal quote chars as part of the value.
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
                    value = value[1:-1]
                os.environ.setdefault(key.strip(), value)

# Sentry error monitoring (optional — set SENTRY_DSN env var to enable)
# Skip Sentry in mock/test mode to avoid polluting production alerts.
import re as _re

# Match Anthropic keys/tokens in any string: sk-ant-api..., sk-ant-oat...,
# and the bare sk-ant- prefix. Scrubs any Anthropic key/token out of an
# error report before it leaves the process (defense-in-depth).
_ANTHROPIC_KEY_RE = _re.compile(r"sk-ant-[A-Za-z0-9_-]+")
_SENTRY_SCRUB_MAX_DEPTH = 12  # guard against pathological/cyclic structures


def _scrub_anthropic_keys(obj, _depth: int = 0):
    """Recursively redact Anthropic API keys/tokens from a Sentry event.

    Sentry captures request bodies AND local variables in stack frames by
    default (``include_local_variables=True``). A user's BYOK key can appear
    in either place — most dangerously as the ``anthropic_key`` local in the
    /generate handler or as the ``api_key`` arg deep in generate_aseprite.
    This walks the whole event and replaces every ``sk-ant-...`` substring
    with a fixed redaction marker, in place where possible.
    """
    if _depth > _SENTRY_SCRUB_MAX_DEPTH:
        return obj
    if isinstance(obj, str):
        return _ANTHROPIC_KEY_RE.sub("[REDACTED_ANTHROPIC_KEY]", obj)
    if isinstance(obj, dict):
        for k in list(obj.keys()):
            obj[k] = _scrub_anthropic_keys(obj[k], _depth + 1)
        return obj
    if isinstance(obj, list):
        for i, item in enumerate(obj):
            obj[i] = _scrub_anthropic_keys(item, _depth + 1)
        return obj
    if isinstance(obj, tuple):
        return tuple(_scrub_anthropic_keys(item, _depth + 1) for item in obj)
    return obj


def _sentry_before_send(event, hint):
    """Sentry before_send hook: strip BYOK Anthropic keys from every event."""
    try:
        return _scrub_anthropic_keys(event)
    except Exception:
        # Never let scrubbing failure drop an error report silently, but a
        # scrub failure must not leak — return None to discard rather than
        # risk sending an unscrubbed event.
        return None


_sentry_dsn = os.environ.get("SENTRY_DSN", "").strip()
_is_mock = os.environ.get("RETROGAZE_MOCK", "").strip() == "1"
if _sentry_dsn and not _is_mock:
    import sentry_sdk
    sentry_sdk.init(
        dsn=_sentry_dsn,
        traces_sample_rate=0.1,
        before_send=_sentry_before_send,
    )

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, PlainTextResponse
from pydantic import BaseModel, Field, field_validator
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded


# Trusted reverse-proxy hops in front of the app. Railway's edge appends the
# real client IP to X-Forwarded-For, so the trustworthy client IP is the
# Nth-from-last entry — NOT the leftmost, which the client fully controls.
_TRUSTED_PROXY_HOPS = max(1, int(os.environ.get("RETROGAZE_TRUSTED_PROXY_HOPS", "1")))


def _get_real_ip(request: Request) -> str:
    """Proxy-aware client IP for rate limiting.

    X-Forwarded-For is a client-supplied header that each trusted proxy
    appends to. Trusting the leftmost value lets an attacker send a fresh
    fake IP per request and bypass per-IP rate limits (→ unbounded free
    generations → real fal.ai cost). We instead take the Nth-from-last
    entry, where N = trusted proxy hops (Railway edge = 1, i.e. rightmost).
    """
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        parts = [p.strip() for p in forwarded.split(",") if p.strip()]
        if parts:
            idx = min(_TRUSTED_PROXY_HOPS, len(parts))
            return parts[-idx]
    return get_remote_address(request)
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.requests import Request as StarletteRequest

from .pipeline import run_pipeline, run_pipeline_best_of_n
from .palette import _NES_PALETTE_HEX, find_nearest_nes_color
from .mcp_routes import router as mcp_router, limiter as mcp_limiter
from .auth import AuthenticatedUser, get_current_user, get_optional_user
from .cost_model import model_path_and_cost
from .supabase_client import supabase_configured
from .payments import payments_configured
from .email_validation import is_valid_signup_email

logger = logging.getLogger("retrogaze")


def _db_enabled() -> bool:
    """True when Supabase is configured AND we're not in mock mode."""
    if os.environ.get("RETROGAZE_MOCK", "").strip() == "1":
        return False
    return supabase_configured()


def _consume_generation_slot(sb, user_id: str) -> dict:
    """Atomically reserve one generation using the canonical tier limits."""
    result = sb.rpc(
        "try_consume_generation",
        {"p_user_id": user_id, "p_tier_limits": _TIER_LIMITS},
    ).execute()
    data = result.data
    if isinstance(data, list):
        data = data[0] if data else {}
    return data


# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

_is_prod = os.environ.get("RETROGAZE_MOCK", "").strip() != "1"

# Guard: mock mode must never be enabled in a deployed environment.
if not _is_prod and os.environ.get("RAILWAY_ENVIRONMENT"):
    raise RuntimeError(
        "RETROGAZE_MOCK=1 is set in a Railway deployment — refusing to start. "
        "Remove RETROGAZE_MOCK from your Railway environment variables."
    )

# Demo profile (hosted free try-out). Settings-first: only enforce what env
# alone cannot. Requires the fal safety checker so public demos stay moderated.
_DEMO = os.environ.get("RETROGAZE_DEMO", "").strip() == "1"
_REPO_URL = (
    os.environ.get("RETROGAZE_REPO_URL", "https://github.com/lerugray/retrogaze").strip()
    or "https://github.com/lerugray/retrogaze"
)


def _demo_credits_message() -> str:
    return (
        "The free demo credits are used up. Retrogaze is open source: "
        f"run it yourself with your own fal key. {_REPO_URL}"
    )


if _DEMO and os.environ.get("RETROGAZE_SAFETY_CHECKER", "").strip() != "1":
    raise RuntimeError(
        "RETROGAZE_DEMO=1 requires RETROGAZE_SAFETY_CHECKER=1. "
        "Refusing to start without the safety checker."
    )

app = FastAPI(
    title="Retrogaze API",
    description="NES-era pixel art generation backend.",
    version="0.1.0",
    docs_url=None if _is_prod else "/docs",
    redoc_url=None if _is_prod else "/redoc",
    openapi_url=None if _is_prod else "/openapi.json",
)

_cors_raw = os.environ.get("CORS_ORIGINS", "").strip()
if not _cors_raw and os.environ.get("RAILWAY_ENVIRONMENT"):
    raise RuntimeError(
        "CORS_ORIGINS must be set in Railway — refusing to start with localhost fallback."
    )
_cors_origins = (
    [o.strip() for o in _cors_raw.split(",") if o.strip()]
    if _cors_raw
    else ["http://127.0.0.1:8642", "http://localhost:8642"]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)

limiter = Limiter(key_func=_get_real_ip)
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Mount MCP server product API
app.include_router(mcp_router, prefix="/mcp", tags=["mcp"])

# Routers mounted above, as (mount prefix, router) pairs. FastAPI >= 0.139 keeps
# an included router nested behind an internal `_IncludedRouter` object instead
# of flattening its children into ``app.routes``, so the /v1 allowlist validator
# (bottom of this file) consults this table to confirm a mounted endpoint exists
# rather than reaching into FastAPI internals. Purely a lookup aid — it grants
# nothing: only paths named in _V1_ALLOWLIST are ever exposed.
_MOUNTED_ROUTERS: tuple[tuple[str, APIRouter], ...] = (("/mcp", mcp_router),)

_enable_hsts = os.environ.get("ENABLE_HSTS", "").strip() == "1"
_API_PATH_PREFIXES = ("/generate", "/config", "/history", "/usage", "/settings",
                       "/checkout", "/webhooks", "/subscription", "/billing-portal",
                       "/waitlist", "/admin", "/api-keys", "/mcp", "/v1")


# ---------------------------------------------------------------------------
# API versioning — the /v1 public-surface ALLOWLIST
# ---------------------------------------------------------------------------
# External programmatic clients (the @retrogaze/mcp npm server, and anyone
# calling the generation endpoint directly) need URLs that survive a future
# breaking change: /v1/* stays frozen while a redesign lands at /v2. The
# un-prefixed originals are NOT moved — they keep working exactly as before,
# because the browser frontend calls them same-origin.
#
# THE ALLOWLIST IS THE WHOLE MECHANISM. A /v1 URL is served *only* for the
# (method, path) pairs literally named below (V1PathRewriteMiddleware rewrites
# those, and only those, to their canonical path before routing). Nothing is
# discovered by iterating app.routes, reflecting over the schema, or re-mounting
# a router — so adding a new endpoint anywhere in this file (or in
# mcp_routes.py) can never silently mint a second, unreviewed URL for it.
# Exposing a new path under /v1 is an explicit, reviewable, one-line edit here.
#
# Each entry must resolve to a real registered route at import time or the app
# refuses to start (see the validation block at the bottom of this file), and
# no entry may touch a money/credential surface (_V1_FORBIDDEN_PREFIXES below).
_V1_PREFIX = "/v1"

_V1_ALLOWLIST: tuple[tuple[str, str], ...] = (
    # Pixel-art generation. The one public endpoint callable without a browser
    # session (anonymous callers get IP rate limiting), and the surface most
    # likely to be scripted against.
    ("POST", "/generate"),
    # MCP product API — the documented, API-key-authenticated surface consumed
    # by the @retrogaze/mcp npm server (mcp-server/src/client.ts). These four
    # ARE the external contract.
    ("POST", "/mcp/prompt"),      # console-accurate drawing instructions
    ("POST", "/mcp/validate"),    # sprite validation / auto-fix
    ("GET", "/mcp/palettes"),     # hardware palette lookup
    ("GET", "/mcp/status"),       # key tier + quota introspection
)

# Money, credential, and privileged surfaces. No /v1 alias may begin with any
# of these — enforced at import time (hard startup failure), not just in tests.
# A payment or webhook endpoint reachable at a second, unreviewed URL is the
# specific failure this guard exists to make impossible.
_V1_FORBIDDEN_PREFIXES: tuple[str, ...] = (
    "/checkout",
    "/webhooks",
    "/subscription",
    "/billing-portal",
    "/auth",
    "/account",
    "/admin",
    "/api-keys",
    "/consent",
    "/settings",
    "/history",
    "/events",
    "/funnel-events",
    "/feedback",
    "/waitlist",
    "/config",
)


_CSP = "; ".join([
    "default-src 'self'",
    # cloudflareinsights.com: Cloudflare auto-injects a Browser Insights
    # beacon on every page. If not allow-listed, the beacon's script
    # load logs a CSP violation in the user's console, which is noise
    # but reads as "the site is broken" to anyone who checks DevTools.
    # Silence by allow-listing the script origin + the beacon POST
    # target (connect-src).
    "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://static.cloudflareinsights.com",
    "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com",
    "font-src 'self' https://fonts.gstatic.com",
    "img-src 'self' data: blob: https://*.supabase.co",
    "connect-src 'self' https://*.supabase.co https://api.lemonsqueezy.com https://cloudflareinsights.com",
    "frame-ancestors 'none'",
])


_STATIC_EXTENSIONS = (".css", ".js", ".svg", ".png", ".jpg", ".jpeg", ".gif",
                      ".ico", ".woff", ".woff2", ".ttf")


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-XSS-Protection"] = "1; mode=block"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        response.headers["Content-Security-Policy"] = _CSP
        if _enable_hsts:
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        if request.url.path.startswith(_API_PATH_PREFIXES):
            response.headers["X-Robots-Tag"] = "noindex, nofollow"
        # Static assets: cache 30 days in browser and CDN, successful responses only
        # (s187: a 404 for a new script was cached for 30 days under its versioned URL).
        if request.url.path.endswith(_STATIC_EXTENSIONS):
            if 200 <= response.status_code < 300:
                response.headers["Cache-Control"] = "public, max-age=2592000"
            else:
                response.headers["Cache-Control"] = "no-store"
        return response

app.add_middleware(SecurityHeadersMiddleware)


# ---------------------------------------------------------------------------
# Rate-limit response headers (/generate + /mcp/*)
# ---------------------------------------------------------------------------
# Standard X-RateLimit-Limit / -Remaining / -Reset headers let programmatic
# and MCP consumers self-throttle *before* hitting a 429 — blind 429s trigger
# retry storms and a poor developer experience, which is load-bearing for API
# adoption.
#
# Why a middleware instead of slowapi's ``headers_enabled=True``: enabling it
# on the shared app limiter would force *every* rate-limited endpoint to take
# a ``response: Response`` parameter (slowapi raises otherwise when an endpoint
# returns a model rather than a Response), a cascade of edits far beyond this
# task's scope. slowapi always populates ``request.state.view_rate_limit``
# during its limit check regardless of ``headers_enabled``, so this middleware
# reads that state after the endpoint runs and injects the three headers only
# on the surfaces that need them. The correct limiter is selected by path so
# ``get_window_stats`` reads the counter store that actually tracks the route
# (the MCP endpoints use a standalone limiter separate from the app limiter).


class RateLimitHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: StarletteRequest, call_next):
        response = await call_next(request)
        path = request.url.path
        # NOTE: a /v1 request has already had its path rewritten to the
        # canonical one by V1PathRewriteMiddleware (registered outermost), so
        # this sees "/generate", not "/v1/generate", and needs no /v1 case.
        if path != "/generate" and not path.startswith("/mcp/"):
            return response
        view_limit = getattr(request.state, "view_rate_limit", None)
        if not view_limit:
            return response
        lim = mcp_limiter if path.startswith("/mcp/") else request.app.state.limiter
        try:
            item, args = view_limit
            stats = lim.limiter.get_window_stats(item, *args)
        except Exception:
            # Never let header computation break a successful response.
            return response
        response.headers["X-RateLimit-Limit"] = str(item.amount)
        response.headers["X-RateLimit-Remaining"] = str(stats.remaining)
        response.headers["X-RateLimit-Reset"] = str(int(1 + stats.reset_time))
        return response


app.add_middleware(RateLimitHeadersMiddleware)


# ---------------------------------------------------------------------------
# API versioning — /v1 as a pre-routing path rewrite
# ---------------------------------------------------------------------------
# A /v1 request on an allowlisted (method, path) has its path rewritten to the
# canonical one BEFORE routing, so it is served by the same route object, the
# same auth dependencies, the same rate-limit bucket and the same downstream
# middleware as the unversioned URL. The unversioned URLs are untouched.
#
# Why a rewrite rather than registering duplicate /v1 routes: slowapi keys its
# counters on ``request["path"]`` (``_check_request_limit``, key_style="url"),
# so a duplicate route at /v1/generate gets its OWN bucket — measured: five
# alternating calls read 29, 28, 29, 28, 27, i.e. the versioned URL hands any
# caller a second full allowance of a paid-generation endpoint. Rewriting makes
# quota-doubling impossible by construction instead of relying on config.
#
# This middleware is registered LAST so it is the OUTERMOST layer: every
# middleware below it (rate-limit headers, security headers, CORS) and the
# router itself see the canonical path. The parity tests in
# src/tests/test_api_v1_allowlist.py fail loudly if that ordering ever changes.
#
# Pure ASGI (not BaseHTTPMiddleware) because the scope must be edited before
# routing, and this adds no per-request task overhead.


class V1PathRewriteMiddleware:
    """Rewrite ``/v1/<allowlisted path>`` to ``<allowlisted path>``.

    Anything not in the allowlist — including every billing, webhook, auth,
    account, admin and API-key path — is left untouched and therefore 404s,
    because no /v1 route exists for it.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            path = scope.get("path", "")
            if path.startswith(_V1_PREFIX + "/"):
                canonical = path[len(_V1_PREFIX):]
                # V1_ALLOWED_PAIRS is produced by the validator at the bottom of
                # this module; the app cannot import (let alone serve) unless it
                # passed the forbidden-surface guards.
                if (scope.get("method", "").upper(), canonical) in V1_ALLOWED_PAIRS:
                    scope = dict(scope)
                    scope["path"] = canonical
                    if scope.get("raw_path"):
                        scope["raw_path"] = canonical.encode("utf-8")
        await self.app(scope, receive, send)


app.add_middleware(V1PathRewriteMiddleware)

# ---------------------------------------------------------------------------
# Static file serving (frontend)
# ---------------------------------------------------------------------------

_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.is_dir():
    _landing_path = _frontend_dir / "landing.html"

    @app.get("/", include_in_schema=False)
    async def serve_landing():
        if _landing_path.is_file():
            return FileResponse(_landing_path)
        return FileResponse(_frontend_dir / "index.html")

    @app.get("/ethics", include_in_schema=False)
    async def serve_ethics():
        return FileResponse(_frontend_dir / "ethics.html")

    @app.get("/terms", include_in_schema=False)
    async def serve_terms():
        return FileResponse(_frontend_dir / "terms.html")

    @app.get("/privacy", include_in_schema=False)
    async def serve_privacy():
        return FileResponse(_frontend_dir / "privacy.html")

    @app.get("/gallery", include_in_schema=False)
    async def serve_gallery():
        return FileResponse(_frontend_dir / "gallery.html")

    @app.get("/mcp-server", include_in_schema=False)
    async def serve_mcp_server():
        return FileResponse(_frontend_dir / "mcp-server.html")

    @app.get("/help", include_in_schema=False)
    async def serve_help():
        return FileResponse(_frontend_dir / "help.html")

    @app.get("/changelog", include_in_schema=False)
    async def serve_changelog():
        return FileResponse(_frontend_dir / "changelog.html")

    @app.get("/app", include_in_schema=False)
    async def serve_app():
        return FileResponse(_frontend_dir / "index.html")

    @app.get("/style.css", include_in_schema=False)
    async def serve_css():
        return FileResponse(_frontend_dir / "style.css", media_type="text/css")

    # Serve minified JS if it exists (built by scripts/minify.py), else source
    _js_path = _frontend_dir / "app.js"
    _js_min_path = _frontend_dir / "app.min.js"

    @app.get("/app.js", include_in_schema=False)
    async def serve_js():
        if _js_min_path.is_file():
            return FileResponse(_js_min_path, media_type="application/javascript")
        return FileResponse(_js_path, media_type="application/javascript")

    @app.get("/favicon.svg", include_in_schema=False)
    async def serve_favicon():
        return FileResponse(_frontend_dir / "favicon.svg", media_type="image/svg+xml")

    @app.get("/og-image.png", include_in_schema=False)
    async def serve_og_image():
        return FileResponse(_frontend_dir / "og-image.png", media_type="image/png")

    @app.get("/sitemap.xml", include_in_schema=False)
    async def serve_sitemap():
        return FileResponse(_frontend_dir / "sitemap.xml", media_type="application/xml")

    _examples_dir = _frontend_dir / "examples"
    if _examples_dir.is_dir():
        app.mount("/examples", StaticFiles(directory=_examples_dir), name="examples")


# ---------------------------------------------------------------------------
# Pydantic models
# ---------------------------------------------------------------------------

class GenerateRequest(BaseModel):
    description: str = Field(..., description="Subject description for the asset.")
    asset_type: str = Field(
        "character",
        description=(
            "Asset category: character, enemy, item, tile, tileset, ui_element, ui_frame."
        ),
    )
    size: str = Field("16x16", description="Target size as WxH, e.g. '16x16'.")
    strict_size: bool = Field(
        False,
        description=(
            "When true, return the exact requested size (Image2Pixel's natural "
            "output is force-resized to size). When false (default), return the "
            "natural higher-resolution output for best quality. Single-frame "
            "FLUX assets only — spritesheet/directional/tileset always use natural."
        ),
    )
    view: str = Field(
        "side",
        description="Camera view (character/enemy only): side, front, top-down, 3/4.",
    )
    palette_mood: str = Field(
        "auto",
        description="Color mood: warm, cool, dark, bright, earth, auto.",
    )
    outline: str = Field(
        "Black",
        description="Outline style: Black, Dark, or No.",
    )
    era: str = Field(
        "mid",
        description="NES era style: early (1983-84), mid (1985-86), late (1987+).",
    )
    reference_image: str | None = Field(
        None,
        max_length=2_800_000,  # ~2MB image in base64
        description=(
            "Base64-encoded reference image (PNG/JPEG, max 2MB). When provided, generation "
            "uses FLUX Dev image-to-image mode."
        ),
    )
    reference_strength: float = Field(
        0.9,
        description=(
            "How much to deviate from the reference "
            "(0.0=exact copy, 1.0=ignore reference). Default 0.9."
        ),
        ge=0.0,
        le=1.0,
    )
    frame_count: int = Field(
        4,
        description="Number of animation frames (for spritesheet type).",
        ge=2,
        le=8,
    )
    animation_type: str = Field(
        "walk",
        description="Animation type: walk, idle, attack, run, jump, death, cast.",
    )
    palette_colors: list[str] | None = Field(
        None,
        description="Lock output to specific NES hex colors (e.g. ['#000000', '#F83800', '#FFFFFF']). Max 6 colors.",
    )
    palette_preset: str | None = Field(
        None,
        description=(
            "Named NES palette preset (e.g. 'mario_red', 'link_green', 'megaman_blue'). "
            "Alternative to palette_colors — provides curated 3-4 color palettes. "
            "Cannot be used together with palette_colors."
        ),
    )
    seed: int | None = Field(
        None,
        description="Random seed for reproducible generation. Use the same seed to get consistent style.",
    )
    max_colors: int | None = Field(
        None,
        description=(
            "Override the maximum number of opaque colors in the output sprite (2-16). "
            "When not set, uses the era default: retro=3, early=4, mid=6, late=6. "
            "Higher values give richer detail but may exceed authentic NES hardware limits."
        ),
        ge=2,
        le=16,
    )
    num_candidates: int = Field(
        1,
        description=(
            "Generate multiple candidates and return all of them (1-4). "
            "Each additional candidate costs one extra generation. "
            "Use this when equipment or detail accuracy is critical — "
            "pick the best result from the set."
        ),
        ge=1,
        le=4,
    )
    generation_mode: str = Field(
        "flux",
        description=(
            "Generation pipeline: 'flux' (FLUX + Image2Pixel, default) or "
            "'aseprite' (Claude API + pixel-mcp, draws natively in Aseprite). "
            "Aseprite mode requires pixel-mcp server and Aseprite installed locally."
        ),
    )
    console: str = Field(
        "nes",
        description=(
            "Target console for constraint enforcement: 'nes' (default), "
            "'gb_dmg', 'gb_pocket', 'gbc', 'c64', 'genesis', 'snes', "
            "'pc_engine'. Determines palette, tile constraints, "
            "and color limits applied to the output."
        ),
    )
    background_color: str | None = Field(
        None,
        description=(
            "Hex color for solid background (e.g. '#000000'). "
            "When set, the sprite is composited onto this color instead of transparent. "
            "Useful for previews, mockups, or engines that don't support transparency."
        ),
    )
    flip_horizontal: bool = Field(
        False,
        description=(
            "Also return a horizontally flipped version of the sprite. "
            "Useful for side-scrollers that need left/right-facing variants."
        ),
    )
    scale_factor: int = Field(
        1,
        description=(
            "Nearest-neighbor upscale factor for the output image (1-8). "
            "1 = native resolution, 2 = 2x, etc. Useful for mockups, marketing, "
            "or engines that expect higher-res source assets."
        ),
        ge=1,
        le=8,
    )
    export_palette: str | None = Field(
        None,
        description=(
            "Export the sprite's palette as a file. Formats: 'gpl' (GIMP/Aseprite), "
            "'hex' (plain text hex list), 'pal' (binary RGB). "
            "Returned as base64-encoded file data in palette_file_base64."
        ),
    )
    export_format: str | None = Field(
        None,
        pattern="^(godot|unity|gamemaker|unreal)$",
        description=(
            "Game engine export format: 'godot' (SpriteFrames .tres), "
            "'unity' (sprite atlas + animation clips JSON), "
            "'gamemaker' (GMSprite .yy resource), "
            "'unreal' (Paper2D sprite + flipbook data). "
            "Returned in engine_export field. Only applies to multi-frame assets."
        ),
    )
    pivot_mode: str = Field(
        "bottom_center",
        pattern="^(bottom_center|center|top_left)$",
        description=(
            "Pivot point preset for atlas frames: 'bottom_center' (default, "
            "standard for characters), 'center' (projectiles, items), "
            "'top_left' (tiles, UI elements)."
        ),
    )


class ComplianceModel(BaseModel):
    palette_valid: bool
    colors_per_tile_valid: bool
    attribute_table_valid: bool
    grid_aligned: bool


class DimensionsModel(BaseModel):
    width_px: int
    height_px: int
    tile_grid: list[int] | None


class MetadataModel(BaseModel):
    retrogaze_version: str
    asset_type: str
    prompt: str | None
    dimensions: DimensionsModel
    compliance: ComplianceModel


class GenerateResponse(BaseModel):
    image_base64: str = Field(..., description="Base64-encoded PNG of the processed image.")
    metadata: dict = Field(..., description="Full NES compliance metadata.")
    frames_base64: list[str] = Field(
        default_factory=list,
        description="Base64-encoded PNGs of individual animation frames (spritesheet type only).",
    )
    generation_id: str | None = Field(
        None,
        description="Database ID for this generation (present when authenticated).",
    )
    candidates_base64: list[str] = Field(
        default_factory=list,
        description=(
            "Base64-encoded PNGs of all candidate sprites when num_candidates > 1. "
            "The first element matches image_base64. Empty when num_candidates == 1."
        ),
    )
    flipped_base64: str | None = Field(
        None,
        description="Base64-encoded PNG of the horizontally flipped sprite (when flip_horizontal=true).",
    )
    palette_file_base64: str | None = Field(
        None,
        description="Base64-encoded palette file (when export_palette is set). Format depends on request.",
    )
    palette_file_format: str | None = Field(
        None,
        description="File extension for the palette file ('gpl', 'hex', or 'pal').",
    )
    atlas_json: dict | None = Field(
        None,
        description=(
            "TexturePacker-compatible atlas JSON for spritesheet/directional/tileset types. "
            "Includes frame coordinates, dimensions, durations, and pivot points. "
            "Compatible with Godot, Unity, and GameMaker atlas importers."
        ),
    )
    engine_export: str | dict | None = Field(
        None,
        description=(
            "Game engine-specific export data. String for Godot (.tres file content), "
            "dict for Unity (sprite atlas + animation clips). "
            "Present when export_format is set and the asset has an atlas."
        ),
    )
    recommendations: list[str] = Field(
        default_factory=list,
        description="Optional tips for better results based on the request parameters.",
    )


class PaletteRow(BaseModel):
    row: int
    colors: list[str]


class PalettesResponse(BaseModel):
    total: int
    rows: list[PaletteRow]


class HealthResponse(BaseModel):
    status: str


class DeepHealthResponse(BaseModel):
    status: str
    fal_key_configured: bool
    fal_reachable: bool
    fal_latency_ms: int | None = None
    checked_at: str


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

_MAX_DIMENSION = 256  # largest sensible NES-era dimension

def _parse_size(size_str: str) -> tuple[int, int]:
    """Parse a 'WxH' size string into an integer tuple."""
    try:
        parts = size_str.lower().split("x")
        if len(parts) != 2:
            raise ValueError
        w, h = int(parts[0]), int(parts[1])
        if w <= 0 or h <= 0:
            raise ValueError
        if w > _MAX_DIMENSION or h > _MAX_DIMENSION:
            raise HTTPException(
                status_code=422,
                detail=f"Size exceeds maximum {_MAX_DIMENSION}x{_MAX_DIMENSION}.",
            )
        return w, h
    except (ValueError, AttributeError):
        raise HTTPException(
            status_code=422,
            detail=f"Invalid size '{size_str}'. Expected format: 'WxH' (e.g. '16x16').",
        )


def _select_output(metadata: dict, strict: bool) -> tuple[Path, dict]:
    """Pick the output file + effective metadata based on strict_size.

    When strict=True and the pipeline produced a strict_nes.png (single-frame
    FLUX path with natural ≠ target), return the strict file and merge in its
    enforce_constraints fields (dimensions/compliance/tiles/palette) so the
    response describes the file actually returned. Falls back to the natural
    primary in all other cases.
    """
    paths = metadata.get("paths", {})
    if strict and "strict_nes" in paths:
        chosen = Path(paths["strict_nes"])
        merged = dict(metadata)
        sm = metadata.get("strict_metadata") or {}
        for key in ("dimensions", "compliance", "tiles", "palette"):
            if key in sm:
                merged[key] = sm[key]
        return chosen, merged
    return Path(paths["processed"]), metadata


# ---------------------------------------------------------------------------
# Input validation allowlists
# ---------------------------------------------------------------------------

_VALID_ASSET_TYPES = {
    "character", "enemy", "item", "tile", "tileset",
    "spritesheet", "directional", "ui_element", "ui_frame",
}
_VALID_ERAS = {"retro", "early", "mid", "late"}
_VALID_VIEWS = {"side", "front", "top_down", "three_quarter"}

# Forgiving view normalization. The docs / marketing / MCP surface advertise
# human-friendly forms ('top-down', '3/4', 'three-quarter'), but the internal
# vocabulary uses underscores. Accept any reasonable spelling (case-insensitive,
# hyphen/space/underscore-insensitive) and normalize to the canonical value so a
# user copy-pasting an advertised value never gets a 422. Keys are lowercased and
# have their separators stripped to '_' before lookup; see _normalize_view.
_VIEW_NORMALIZE = {
    "side": "side",
    "front": "front",
    "top_down": "top_down",
    "topdown": "top_down",
    "three_quarter": "three_quarter",
    "threequarter": "three_quarter",
    "3_4": "three_quarter",
    "3/4": "three_quarter",
}


def _normalize_view(value: str) -> str:
    """Map an advertised/alias view spelling to its canonical form.

    Case-insensitive; treats hyphens and spaces as underscores (so 'top-down',
    'top down', 'Top_Down' all map to 'top_down'; 'three-quarter', '3/4',
    'Three Quarter' all map to 'three_quarter'). Unknown values pass through
    unchanged so the downstream allowlist check still rejects them.
    """
    if not isinstance(value, str):
        return value
    key = value.strip().lower().replace("-", "_").replace(" ", "_")
    # '3/4' has no separator to strip; check the raw lowercased form too.
    return _VIEW_NORMALIZE.get(key) or _VIEW_NORMALIZE.get(value.strip().lower()) or value
_VALID_PALETTE_MOODS = {"auto", "warm", "cool", "dark", "bright", "earth"}
_VALID_OUTLINES = {"Black", "Dark", "No", "black", "dark", "none", "no"}
_VALID_ANIMATION_TYPES = {"walk", "idle", "run", "attack", "jump", "death", "cast"}


def _build_atlas_json(
    asset_type: str,
    frames_b64: list[str],
    metadata: dict,
    sheet_image_bytes: bytes,
    animation_type: str | None = None,
    scale_factor: int = 1,
) -> dict | None:
    """Build a TexturePacker-compatible atlas JSON for multi-frame assets.

    Returns None for single-frame asset types.
    """
    if asset_type not in ("spritesheet", "directional", "tileset") or not frames_b64:
        return None

    import io as _io
    from PIL import Image as _PILImage

    sheet_img = _PILImage.open(_io.BytesIO(sheet_image_bytes))
    sheet_w, sheet_h = sheet_img.size

    # Determine individual frame dimensions from first frame
    first_frame = _PILImage.open(_io.BytesIO(base64.b64decode(frames_b64[0])))
    frame_w, frame_h = first_frame.size

    # Frame duration from pipeline metadata
    frame_duration_ms = 150  # default
    if "animation" in metadata:
        frame_duration_ms = metadata["animation"].get("frame_duration_ms", 150)

    # Direction names for directional sprites
    direction_names = ["front", "right", "back", "left"]
    if "directions" in metadata:
        direction_names = metadata["directions"].get("names", direction_names)

    # Build frame entries
    frames = {}
    for idx, _b64 in enumerate(frames_b64):
        if asset_type == "directional" and idx < len(direction_names):
            frame_name = direction_names[idx]
        elif asset_type == "tileset":
            tile_keys = ["top_left", "top", "top_right", "left", "center", "right",
                         "bottom_left", "bottom", "bottom_right"]
            frame_name = tile_keys[idx] if idx < len(tile_keys) else f"tile_{idx}"
        else:
            frame_name = f"frame_{idx}"

        # For horizontal strip layout, frames are side by side
        if asset_type == "tileset":
            # 3x3 grid layout
            col = idx % 3
            row = idx // 3
            x = col * frame_w
            y = row * frame_h
        else:
            # Horizontal strip
            x = idx * frame_w
            y = 0

        frames[frame_name] = {
            "frame": {"x": x, "y": y, "w": frame_w, "h": frame_h},
            "rotated": False,
            "trimmed": False,
            "spriteSourceSize": {"x": 0, "y": 0, "w": frame_w, "h": frame_h},
            "sourceSize": {"w": frame_w, "h": frame_h},
            "pivot": {"x": 0.5, "y": 1.0},  # bottom-center pivot (standard for game sprites)
            "duration": frame_duration_ms,
        }

    # Build frame tags (animation groups)
    frame_tags = []
    if asset_type == "spritesheet" and animation_type:
        frame_tags.append({
            "name": animation_type,
            "from": 0,
            "to": len(frames_b64) - 1,
            "direction": "forward",
        })
    elif asset_type == "directional":
        for idx, name in enumerate(direction_names[:len(frames_b64)]):
            frame_tags.append({
                "name": name,
                "from": idx,
                "to": idx,
                "direction": "forward",
            })

    atlas = {
        "frames": frames,
        "meta": {
            "app": "Retrogaze",
            "version": "0.1.0",
            "format": "RGBA8888",
            "size": {"w": sheet_w, "h": sheet_h},
            "scale": scale_factor,
            "frameTags": frame_tags,
        },
    }
    return atlas


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------

class ConfigResponse(BaseModel):
    supabase_url: str | None = None
    supabase_anon_key: str | None = None
    oauth_providers: list[str] | None = None
    demo: bool = False


@app.get("/config", response_model=ConfigResponse, tags=["meta"])
async def get_config() -> ConfigResponse:
    """Return public frontend config (Supabase URL and anon key only)."""
    raw_providers = os.environ.get("OAUTH_PROVIDERS", "").strip()
    providers = [p.strip() for p in raw_providers.split(",") if p.strip()] or None
    return ConfigResponse(
        supabase_url=os.environ.get("SUPABASE_URL"),
        supabase_anon_key=os.environ.get("SUPABASE_ANON_KEY"),
        oauth_providers=providers,
        demo=_DEMO,
    )


@app.get("/health", response_model=HealthResponse, tags=["meta"])
async def health() -> HealthResponse:
    """Liveness probe."""
    return HealthResponse(status="ok")


@app.get("/health/deep", response_model=DeepHealthResponse, tags=["meta"])
@limiter.limit("10/minute")
async def health_deep(request: Request) -> DeepHealthResponse:
    """Readiness probe — checks FAL_KEY and fal.ai reachability.

    Unlike the lightweight /health liveness probe (which only confirms the
    process is up), this performs an outbound HTTP request to fal.run so
    external uptime monitors can distinguish "process is alive" from "can
    actually generate sprites".  Returns status "ok" (both healthy),
    "degraded" (one failing), or "down" (both failing).
    """
    import httpx
    from datetime import datetime, timezone

    fal_key = os.environ.get("FAL_KEY", "").strip()
    fal_key_configured = bool(fal_key)
    fal_reachable = False
    fal_latency_ms: int | None = None

    try:
        t0 = time.monotonic()
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.head("https://fal.run/")
            # Any non-server-error HTTP response means fal.ai infra is up.
            fal_reachable = resp.status_code < 500
        fal_latency_ms = int((time.monotonic() - t0) * 1000)
    except Exception:
        fal_reachable = False

    if fal_key_configured and fal_reachable:
        status = "ok"
    elif fal_key_configured or fal_reachable:
        status = "degraded"
    else:
        status = "down"

    return DeepHealthResponse(
        status=status,
        fal_key_configured=fal_key_configured,
        fal_reachable=fal_reachable,
        fal_latency_ms=fal_latency_ms,
        checked_at=datetime.now(timezone.utc).isoformat(),
    )


@app.get("/palettes", response_model=PalettesResponse, tags=["palette"])
@limiter.limit("60/minute")
async def get_palettes(request: Request) -> PalettesResponse:
    """
    Return all 54 NES 2C02 palette colors as hex strings, organised by row.

    The NES palette has 4 rows of 14 colours (56 entries total; rows 0 and 3
    share an identical black entry, reducing unique colours to 54).
    """
    row_size = 14
    rows: list[PaletteRow] = []
    for row_idx in range(0, len(_NES_PALETTE_HEX), row_size):
        rows.append(
            PaletteRow(
                row=row_idx // row_size,
                colors=list(_NES_PALETTE_HEX[row_idx : row_idx + row_size]),
            )
        )
    return PalettesResponse(total=len(_NES_PALETTE_HEX), rows=rows)


@app.get("/presets", tags=["palette"])
@limiter.limit("60/minute")
async def get_presets(request: Request) -> dict:
    """Return all available curated NES palette presets."""
    from .palette import list_presets
    presets = list_presets()
    return {"presets": presets, "total": len(presets)}


class ExtractPaletteRequest(BaseModel):
    image: str = Field(..., max_length=2_800_000, description="Base64-encoded screenshot (PNG/JPEG, max 2MB)")
    n: int = Field(4, ge=2, le=6, description="Number of colors to extract")
    console: str = Field("nes", description="Target console for palette snapping")


@app.post("/extract-palette", tags=["palette"])
@limiter.limit("30/minute")
async def extract_palette(
    request: Request,
    body: ExtractPaletteRequest,
) -> dict:
    """Extract dominant colors from a screenshot and snap to console-valid palette.

    Upload a screenshot from a game you like — returns hex colors ready to use
    as palette_colors in the generate endpoint.
    """
    import io as _io
    from PIL import Image as _PILImage
    from .palette_extract import extract_palette_from_screenshot

    try:
        img_bytes = base64.b64decode(body.image)
        img = _PILImage.open(_io.BytesIO(img_bytes)).convert("RGB")
    except Exception:
        raise HTTPException(status_code=422, detail="Invalid image data.")
    if img.width * img.height > 4_000_000:
        raise HTTPException(status_code=422, detail="Image too large (max ~4MP).")

    colors = extract_palette_from_screenshot(img, n=body.n, console=body.console)
    return {"palette_colors": colors, "console": body.console, "count": len(colors)}


_gen_rate = os.environ.get("RETROGAZE_API_RATE_LIMIT", "30/minute")

@app.post("/generate", response_model=GenerateResponse, tags=["generation"])
@limiter.limit(_gen_rate)
async def generate(
    request: Request,
    body: GenerateRequest,
    user: AuthenticatedUser | None = Depends(get_optional_user),
) -> GenerateResponse:
    """
    Generate a pixel-art asset and return the processed image + metadata.

    When authenticated, enforces per-user DB-backed limits and records the
    generation. Without auth, falls back to IP-based rate limiting only.
    """
    size = _parse_size(body.size)

    # Alias frontend-only asset types to backend equivalents
    _ASSET_ALIASES = {"npc": "character", "background_tile": "tile"}
    if body.asset_type in _ASSET_ALIASES:
        body.asset_type = _ASSET_ALIASES[body.asset_type]

    # Normalize view aliases (case-insensitive; hyphen/slash/space forms). The
    # docs/MCP/marketing advertise 'top-down', '3/4', 'three-quarter'; the
    # internal vocabulary uses underscores. Accept any reasonable spelling so an
    # advertised value never 422s. See _normalize_view / _VIEW_NORMALIZE.
    body.view = _normalize_view(body.view)

    # Validate console profile
    from .console_profile import get_profile
    try:
        _console_profile = get_profile(body.console)
    except KeyError:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid console: '{body.console}'. Valid options: nes, gb_dmg, gb_pocket, gbc, c64, genesis, snes, pc_engine.",
        )

    # Some consoles have a palette profile but no generation prompt data yet
    # (e.g. c64_multicolor). Reject those here with a clean 422 instead of
    # 500ing deep in the pipeline.
    from .console_prompt_data import is_generation_supported
    if not is_generation_supported(body.console):
        raise HTTPException(
            status_code=422,
            detail=(
                f"Console '{body.console}' isn't available for generation yet. "
                "Try: nes, gb_dmg, gb_pocket, gbc, c64, genesis, snes, pc_engine."
            ),
        )

    # Validate enum-like fields against allowlists
    if body.asset_type not in _VALID_ASSET_TYPES:
        raise HTTPException(status_code=422, detail="Invalid asset type.")
    if body.era not in _VALID_ERAS:
        raise HTTPException(status_code=422, detail="Invalid era.")
    if body.view not in _VALID_VIEWS:
        raise HTTPException(
            status_code=422,
            detail=(
                "Invalid view. Valid: side, front, top_down (aka 'top-down'), "
                "three_quarter (aka 'three-quarter' or '3/4')."
            ),
        )
    if body.palette_mood not in _VALID_PALETTE_MOODS:
        raise HTTPException(status_code=422, detail="Invalid palette mood.")
    if body.outline not in _VALID_OUTLINES:
        raise HTTPException(status_code=422, detail="Invalid outline style.")
    if body.asset_type == "spritesheet" and body.animation_type not in _VALID_ANIMATION_TYPES:
        raise HTTPException(status_code=422, detail="Invalid animation type.")

    if len(body.description) > 500:
        raise HTTPException(
            status_code=422,
            detail="Description must be 500 characters or fewer.",
        )

    # Validate palette_colors when provided — snap to nearest NES color
    if body.palette_colors is not None:
        if len(body.palette_colors) > 6:
            raise HTTPException(
                status_code=422,
                detail="palette_colors may contain at most 6 colors.",
            )
        import re
        hex_pattern = re.compile(r"^#[0-9A-Fa-f]{6}$")
        snapped_colors: list[str] = []
        for color in body.palette_colors:
            if not hex_pattern.match(color):
                raise HTTPException(
                    status_code=422,
                    detail=f"Invalid hex color '{color}'. Expected format: '#RRGGBB'.",
                )
            h = color.lstrip("#")
            r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
            nr, ng, nb, _idx = find_nearest_nes_color(r, g, b)
            snapped = f"#{nr:02X}{ng:02X}{nb:02X}"
            snapped_colors.append(snapped)
        body.palette_colors = snapped_colors

    # Generation limit is reserved atomically just before generation (after
    # all synchronous validation below), so failed validation never burns a
    # slot. See the try_consume_generation reservation block further down.
    if body.palette_preset and body.palette_colors:
        raise HTTPException(
            status_code=422,
            detail="Specify palette_preset OR palette_colors, not both.",
        )

    # Validate palette_preset against the known presets at the boundary so an
    # unknown name fails cleanly (422 with the valid list) BEFORE a generation
    # slot is reserved — instead of raising a ValueError deep in the pipeline
    # that surfaces as a generic message after burning the reservation.
    if body.palette_preset is not None:
        from .palette import get_preset_palette, list_presets
        if get_preset_palette(body.palette_preset) is None:
            valid = ", ".join(sorted(list_presets().keys()))
            raise HTTPException(
                status_code=422,
                detail=f"Unknown palette_preset '{body.palette_preset}'. Valid presets: {valid}.",
            )

    # The web generator runs FLUX server-side only. "Aseprite mode" (Claude
    # draws every pixel) runs in the user's OWN Claude via the Retrogaze MCP
    # server (pixel-mcp), so retrogaze never holds an Anthropic credential —
    # point aseprite callers there instead of generating server-side.
    if body.generation_mode == "aseprite":
        raise HTTPException(
            status_code=422,
            detail=(
                "Aseprite mode runs in your own Claude via the Retrogaze MCP "
                "server — the web generator uses 'flux'."
            ),
        )
    if body.generation_mode != "flux":
        raise HTTPException(
            status_code=422,
            detail="generation_mode must be 'flux'.",
        )

    # Demo profile: force one candidate; refuse reference uploads (FLUX Dev).
    num_candidates = body.num_candidates
    if _DEMO:
        num_candidates = 1
        if body.reference_image is not None:
            raise HTTPException(
                status_code=422,
                detail=(
                    "Reference image uploads are disabled on the free demo "
                    "(they use a costlier model). Run Retrogaze yourself with "
                    f"your own fal key: {_REPO_URL}"
                ),
            )

    generation_mode_actual = "flux"

    # --- Atomic generation reservation (authenticated users only) ---
    # Reserve a slot BEFORE any work so concurrent requests can't race past
    # the limit (the old read-only check raced the post-generation increment).
    # try_consume_generation atomically checks the tier limit AND increments
    # the counter in one statement. Fails CLOSED on error. Refunded below if
    # the generation fails. Anonymous users are gated by the per-IP limiter.
    reserved = False
    if user and _db_enabled():
        try:
            from .supabase_client import get_supabase_client
            sb = get_supabase_client()
            consume_data = _consume_generation_slot(sb, user.id)
            if not consume_data.get("allowed", False):
                raise HTTPException(
                    status_code=429,
                    detail=consume_data.get("reason", "Generation limit reached."),
                )
            reserved = True
        except HTTPException:
            raise
        except Exception as exc:
            logger.error("Generation reserve failed, denying (fail closed): %s", exc)
            raise HTTPException(
                status_code=503,
                detail="Couldn't verify your generation limit right now. Please try again.",
            ) from exc

    def _refund_reservation() -> None:
        """Return a reserved slot when generation fails before it's recorded."""
        if not reserved:
            return
        try:
            from .supabase_client import get_supabase_client
            get_supabase_client().rpc(
                "refund_generation", {"p_user_id": user.id}
            ).execute()
        except Exception as exc:
            logger.warning("Failed to refund generation reservation: %s", exc)

    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            # If a reference image was provided, validate and save to a temp file
            ref_image_path: str | None = None
            if body.reference_image is not None:
                ref_bytes = base64.b64decode(body.reference_image)

                # Reject payloads over 2MB (prevents memory abuse)
                if len(ref_bytes) > 2 * 1024 * 1024:
                    raise HTTPException(
                        status_code=422,
                        detail="Reference image must be under 2MB.",
                    )

                # Validate that the bytes are actually an image before writing
                import io
                from PIL import Image as PILImage
                try:
                    img_check = PILImage.open(io.BytesIO(ref_bytes))
                    img_check.verify()
                    # verify() exhausts the buffer; reopen to check dimensions
                    img_check = PILImage.open(io.BytesIO(ref_bytes))
                    if img_check.width * img_check.height > 4_000_000:
                        raise HTTPException(
                            status_code=422,
                            detail="Reference image too large (max 4 megapixels).",
                        )
                except HTTPException:
                    raise
                except Exception:
                    raise HTTPException(
                        status_code=422,
                        detail="Reference image is not a valid image file.",
                    )

                ref_file = Path(tmp_dir) / "reference.png"
                ref_file.write_bytes(ref_bytes)
                ref_image_path = str(ref_file)

            _gen_start = time.monotonic()
            pipeline_result = await run_pipeline_best_of_n(
                num_candidates=num_candidates,
                description=body.description,
                asset_type=body.asset_type,
                size=size,
                view=body.view,
                palette_mood=body.palette_mood,
                outline=body.outline,
                era=body.era,
                output_dir=tmp_dir,
                reference_image_path=ref_image_path,
                reference_strength=body.reference_strength,
                frame_count=body.frame_count,
                animation_type=body.animation_type,
                palette_colors=body.palette_colors,
                palette_preset=body.palette_preset,
                seed=body.seed,
                max_colors=body.max_colors,
                generation_mode=generation_mode_actual,
                console=body.console,
            )

            _gen_duration_ms = int((time.monotonic() - _gen_start) * 1000)

            # Primary result is always the first candidate. When the user
            # opted into strict_size, swap to the exact-target file and use
            # its enforce metadata so dims/compliance match the bytes served.
            primary_metadata = pipeline_result["candidates"][0]
            processed_path, metadata = _select_output(primary_metadata, body.strict_size)
            image_bytes = processed_path.read_bytes()

            # Collect all candidate images when num_candidates > 1. The raw
            # bytes are read NOW, while the temp dir still exists: the
            # Supabase upload happens after this block exits and the dir is
            # deleted (Bug 2 — variations used to be re-read from disk
            # post-exit, so every one of them was silently skipped and
            # history only ever saw the primary image).
            candidates_b64: list[str] = []
            candidate_pngs: list[bytes] = []
            if pipeline_result["num_candidates"] > 1:
                for candidate in pipeline_result["candidates"]:
                    cp, _ = _select_output(candidate, body.strict_size)
                    if cp.exists():
                        png = cp.read_bytes()
                        candidate_pngs.append(png)
                        candidates_b64.append(
                            base64.b64encode(png).decode("ascii")
                        )

            # Collect frame images for spritesheet/directional types
            frames_b64: list[str] = []
            if body.asset_type in ("spritesheet", "directional") and "frames" in metadata.get("paths", {}):
                for frame_path_str in metadata["paths"]["frames"]:
                    fp = Path(frame_path_str)
                    if fp.exists():
                        frames_b64.append(base64.b64encode(fp.read_bytes()).decode("ascii"))

            # Collect tile images for tileset type
            if body.asset_type == "tileset" and "tiles" in metadata.get("paths", {}):
                for tile_path_str in metadata["paths"]["tiles"].values():
                    fp = Path(tile_path_str)
                    if fp.exists():
                        frames_b64.append(base64.b64encode(fp.read_bytes()).decode("ascii"))

    except EnvironmentError as exc:
        logger.error("Environment error during generation: %s", exc)
        _refund_reservation()
        exc_text = str(exc)
        if "FAL_KEY" in exc_text:
            # Keep the developer detail in the server log only (OSS demo UX).
            logger.error("Generation refused: FAL_KEY is not set")
            raise HTTPException(
                status_code=503,
                detail=(
                    "Image generation is not available on this server right now. "
                    "Retrogaze is open source: run it yourself with your "
                    f"own fal.ai key. {_REPO_URL}"
                ),
            ) from exc
        raise HTTPException(
            status_code=503, detail="Service configuration error. Please try again later.",
        ) from exc
    except ValueError as exc:
        _refund_reservation()
        raise HTTPException(status_code=422, detail="Invalid generation parameters.") from exc
    except HTTPException:
        _refund_reservation()
        raise
    except Exception as exc:
        _refund_reservation()
        # Detect fal.ai credit exhaustion (402), session spend/gen caps, or rate limit
        exc_msg = str(exc).lower()
        exhausted = (
            "402" in exc_msg
            or "payment" in exc_msg
            or "insufficient" in exc_msg
            or "spend cap" in exc_msg
            or "session generation limit" in exc_msg
        )
        if exhausted:
            detail = (
                _demo_credits_message()
                if _DEMO
                else "Image generation service temporarily unavailable. Please try again later."
            )
            raise HTTPException(status_code=503, detail=detail) from exc
        if "429" in exc_msg:
            raise HTTPException(
                status_code=429,
                detail="Generation service is busy. Please wait a moment and try again.",
            ) from exc
        logger.error("Generation failed: %s", exc, exc_info=True)
        raise HTTPException(
            status_code=500, detail="Generation failed. Please try again.",
        ) from exc

    # --- Post-processing: background color, flip, scale, palette export ---
    flipped_b64: str | None = None
    palette_file_b64: str | None = None
    palette_file_fmt: str | None = None
    needs_pil = body.background_color or body.flip_horizontal or body.scale_factor > 1 or body.export_palette
    if needs_pil:
        import io
        from PIL import Image as PILImage

        sprite = PILImage.open(io.BytesIO(image_bytes)).convert("RGBA")

        # --- Palette export (before any compositing changes the palette) ---
        if body.export_palette:
            fmt = body.export_palette.lower().strip()
            if fmt not in ("gpl", "hex", "pal"):
                raise HTTPException(status_code=422, detail="export_palette must be 'gpl', 'hex', or 'pal'.")
            # Extract unique opaque colors
            pixels = list(sprite.get_flattened_data())
            unique_colors = []
            seen = set()
            for px in pixels:
                if len(px) >= 4 and px[3] < 10:
                    continue  # skip transparent
                rgb = (px[0], px[1], px[2])
                if rgb not in seen:
                    seen.add(rgb)
                    unique_colors.append(rgb)

            if fmt == "gpl":
                lines = ["GIMP Palette", "Name: Retrogaze NES Palette", f"Columns: {len(unique_colors)}", "#"]
                for r, g, b in unique_colors:
                    lines.append(f"{r:3d} {g:3d} {b:3d}\t#{r:02X}{g:02X}{b:02X}")
                palette_file_b64 = base64.b64encode("\n".join(lines).encode()).decode("ascii")
            elif fmt == "hex":
                lines = [f"#{r:02X}{g:02X}{b:02X}" for r, g, b in unique_colors]
                palette_file_b64 = base64.b64encode("\n".join(lines).encode()).decode("ascii")
            elif fmt == "pal":
                raw = bytearray()
                for r, g, b in unique_colors:
                    raw.extend([r, g, b])
                palette_file_b64 = base64.b64encode(bytes(raw)).decode("ascii")
            palette_file_fmt = fmt

        # --- Background color compositing ---
        if body.background_color:
            hex_str = body.background_color.lstrip("#")
            if len(hex_str) not in (3, 6) or not all(c in "0123456789abcdefABCDEF" for c in hex_str):
                raise HTTPException(status_code=422, detail="Invalid background_color hex format.")
            if len(hex_str) == 3:
                hex_str = "".join(c * 2 for c in hex_str)
            r, g, b = int(hex_str[0:2], 16), int(hex_str[2:4], 16), int(hex_str[4:6], 16)
            bg = PILImage.new("RGBA", sprite.size, (r, g, b, 255))
            bg.paste(sprite, mask=sprite.split()[3])
            sprite = bg

        # --- Scale (nearest-neighbor, applied after bg compositing) ---
        if body.scale_factor > 1:
            new_w = sprite.width * body.scale_factor
            new_h = sprite.height * body.scale_factor
            sprite = sprite.resize((new_w, new_h), PILImage.Resampling.NEAREST)

        # --- Horizontal flip ---
        if body.flip_horizontal:
            flipped = sprite.transpose(PILImage.Transpose.FLIP_LEFT_RIGHT)
            buf = io.BytesIO()
            flipped.save(buf, format="PNG")
            flipped_b64 = base64.b64encode(buf.getvalue()).decode("ascii")

        buf = io.BytesIO()
        sprite.save(buf, format="PNG")
        image_bytes = buf.getvalue()

    image_base64 = base64.b64encode(image_bytes).decode("ascii")

    # --- Build atlas JSON for multi-frame types ---
    atlas_json = _build_atlas_json(
        asset_type=body.asset_type,
        frames_b64=frames_b64,
        metadata=metadata,
        sheet_image_bytes=image_bytes,
        animation_type=body.animation_type if body.asset_type == "spritesheet" else None,
        scale_factor=body.scale_factor,
    )

    # --- Record generation + upload to Supabase Storage ---
    generation_id: str | None = None
    if user and _db_enabled():
        try:
            from .supabase_client import get_supabase_client
            sb = get_supabase_client()

            # Determine model path and cost. Best-of-N runs num_candidates
            # independent fal.ai pipelines, so recorded COGS is per-candidate
            # estimate × how many candidates were actually generated. Quota
            # still counts as one reservation (try_consume above) — cost and
            # quota are intentionally decoupled.
            had_reference = body.reference_image is not None
            model_path, per_candidate_cost = model_path_and_cost(had_reference)
            n_billed = max(1, int(pipeline_result.get("num_candidates") or 1))
            cost_usd = per_candidate_cost * n_billed

            # Upload image to Supabase Storage
            storage_path: str | None = None
            try:
                file_id = str(uuid.uuid4())
                storage_path = f"{user.id}/{file_id}.png"
                sb.storage.from_("generations").upload(
                    storage_path,
                    image_bytes,
                    {"content-type": "image/png"},
                )
            except Exception as exc:
                logger.warning("Storage upload failed: %s", exc)
                storage_path = None

            # Upload additional candidate variations (Bug 2 fix). Each
            # gets its own UUID under the user's storage prefix so the
            # existing RLS policies (path[0] == auth.uid()) cover them
            # without changes. Failures on individual variations don't
            # block the primary record — we just persist what succeeded.
            # Bytes come from candidate_pngs (read inside the temp-dir
            # block); candidates[0] is the primary already uploaded above,
            # so only variations 1..N-1 need new uploads.
            variation_paths: list[str] = []
            if storage_path and len(candidate_pngs) > 1:
                for i, cand_png in enumerate(candidate_pngs[1:], start=1):
                    try:
                        var_id = str(uuid.uuid4())
                        var_path = f"{user.id}/{var_id}.png"
                        sb.storage.from_("generations").upload(
                            var_path,
                            cand_png,
                            {"content-type": "image/png"},
                        )
                        variation_paths.append(var_path)
                    except Exception as exc:
                        logger.warning("Variation %d upload failed: %s", i, exc)

            # Strip paths from metadata before storing in DB
            db_metadata = {k: v for k, v in metadata.items() if k != "paths"}
            db_metadata["duration_ms"] = _gen_duration_ms

            # Record the generation via RPC
            record_result = sb.rpc("record_generation", {
                "p_user_id": user.id,
                "p_description": body.description,
                "p_asset_type": body.asset_type,
                "p_size": body.size,
                "p_era": body.era,
                "p_palette_mood": body.palette_mood,
                "p_outline": body.outline,
                "p_view": body.view,
                "p_palette_colors": body.palette_colors,
                "p_seed": body.seed,
                "p_had_reference": had_reference,
                "p_model_path": model_path,
                "p_cost_usd": cost_usd,
                "p_image_storage_path": storage_path,
                "p_metadata_json": db_metadata,
                "p_source": "web",
                "p_variation_storage_paths": variation_paths,
            }).execute()
            if record_result.data:
                generation_id = str(record_result.data)
        except Exception as exc:
            logger.warning("Failed to record generation: %s", exc)

        # Funnel: first_generation (deduped once-per-user at the DB layer).
        # Best-effort — never let instrumentation break the generation flow.
        try:
            from .funnel import emit_funnel_event
            emit_funnel_event(user.id, "first_generation", {"asset_type": body.asset_type})
        except Exception as exc:
            logger.warning("funnel first_generation emit failed: %s", exc)

    # Strip internal/sensitive info before returning to the client
    _STRIP_KEYS = {
        "paths", "prompt", "cost_usd", "model_path",
        # IP protection: don't reveal pipeline architecture to competitors
        "generation_mode", "tool_calls", "tokens",
    }
    client_metadata = {
        k: v for k, v in metadata.items() if k not in _STRIP_KEYS
    }
    # NOTE: generation_mode_actual intentionally NOT sent to client (IP protection).
    # Pipeline architecture is a trade secret — don't reveal which engine was used.

    # Strip enforcement internals from compliance (IP protection)
    if "compliance" in client_metadata:
        client_metadata["compliance"].pop("palette_slots_required", None)
        client_metadata["compliance"].pop("attribute_table_valid", None)

    # Add console info to response
    client_metadata["console"] = _console_profile.name
    client_metadata["console_display_name"] = _console_profile.display_name

    # Build recommendations for better results
    tips: list[str] = []
    if body.asset_type == "spritesheet" and body.era not in ("mid",):
        tips.append("Spritesheets work best with mid era (1985-87).")
    if body.asset_type in ("character", "item", "enemy") and not body.palette_colors and not body.palette_preset:
        tips.append("Try a palette preset (e.g. 'mario_red', 'megaman_blue') for more authentic NES colors.")
    if body.asset_type in ("tile", "tileset") and body.era in ("retro", "early"):
        tips.append("Tiles work best with mid or late era for cleaner patterns.")

    # Build engine-specific export if requested
    engine_export = None
    if atlas_json and body.export_format:
        from .export_formats import build_godot_tres, build_unity_anim, build_gamemaker_yy, build_unreal_sprite, apply_pivot
        if body.pivot_mode != "bottom_center":
            atlas_json = apply_pivot(atlas_json, body.pivot_mode)
        if body.export_format == "godot":
            engine_export = build_godot_tres(atlas_json)
        elif body.export_format == "unity":
            engine_export = build_unity_anim(atlas_json)
        elif body.export_format == "gamemaker":
            engine_export = build_gamemaker_yy(atlas_json)
        elif body.export_format == "unreal":
            engine_export = build_unreal_sprite(atlas_json)

    return GenerateResponse(
        image_base64=image_base64,
        metadata=client_metadata,
        frames_base64=frames_b64,
        generation_id=generation_id,
        candidates_base64=candidates_b64,
        flipped_base64=flipped_b64,
        palette_file_base64=palette_file_b64,
        palette_file_format=palette_file_fmt,
        atlas_json=atlas_json,
        engine_export=engine_export,
        recommendations=tips,
    )


# ---------------------------------------------------------------------------
# User endpoints (all require authentication)
# ---------------------------------------------------------------------------

class HistoryItem(BaseModel):
    id: str
    description: str
    asset_type: str
    size: str
    era: str
    created_at: str
    image_storage_path: str | None = None
    # rg-018: short-lived signed URL for the generation image. The
    # `generations` bucket is private (per 001_initial_schema.sql),
    # so the frontend cannot use getPublicUrl — that returns a 404.
    # The server batch-signs paths via create_signed_urls and includes
    # the result here. None when signing failed (file missing on
    # storage, etc.); frontend falls back to no thumbnail / no-op click.
    image_url: str | None = None
    # Bug 1 fix: when a generation produced multiple candidates, the
    # extras are stored in variation_storage_paths with their own signed
    # URLs returned in variation_image_urls. Order matches paths. Empty
    # for single-candidate generations and for any pre-migration rows.
    variation_storage_paths: list[str] = Field(default_factory=list)
    variation_image_urls: list[str] = Field(default_factory=list)
    cost_usd: float | None = None
    model_path: str | None = None
    metadata_json: dict | None = None


class HistoryResponse(BaseModel):
    items: list[HistoryItem]
    total: int
    # Whether more rows exist beyond this page. The frontend uses this
    # (rather than total/offset arithmetic) to drive infinite-scroll.
    has_more: bool = False
    # Opaque cursor for the next page. Pass as the ``cursor`` query param
    # on the next /history request to fetch the page after this one.
    # None when there are no more rows. Encodes the last item's
    # ``created_at`` so keyset pagination stays stable as new generations
    # are inserted between page loads (no skipped/duplicated rows).
    next_cursor: str | None = None


def _encode_history_cursor(created_at: str) -> str:
    """Encode a ``created_at`` timestamp into an opaque URL-safe cursor."""
    return base64.urlsafe_b64encode(created_at.encode()).decode()


def _decode_history_cursor(cursor: str) -> str | None:
    """Decode a cursor back to its ``created_at`` timestamp, or None if invalid."""
    try:
        return base64.urlsafe_b64decode(cursor.encode()).decode()
    except Exception:
        return None


@app.get("/history", response_model=HistoryResponse, tags=["user"])
@limiter.limit("30/minute")
async def get_history(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
    limit: int = Query(20, ge=1, le=100),
    offset: int = Query(0, ge=0),
    cursor: str | None = Query(None),
) -> HistoryResponse:
    """Return the authenticated user's generation history, newest first.

    Two pagination modes:

    - **Cursor** (preferred for infinite-scroll): pass ``cursor`` from a
      prior response's ``next_cursor``. Uses keyset pagination
      (``created_at < cursor``) which stays stable as new generations are
      inserted between page fetches — no skipped or duplicated rows for
      active users accumulating history while browsing.
    - **Offset** (backward compatible): pass ``offset`` when ``cursor`` is
      omitted. Simpler but can skip/duplicate rows when new records arrive
      between page loads.
    """
    if not _db_enabled():
        return HistoryResponse(items=[], total=0)

    from .supabase_client import get_user_client
    sb = get_user_client(user.id)

    # Total count — a single indexed count scoped by user_id, cheap even
    # for active users. Kept on every page so the frontend's "N
    # generations" header stays accurate without a separate request.
    count_result = (
        sb.table("generations")
        .select("id", count="exact")
        .execute()
    )
    total = count_result.count or 0

    select_cols = ("id, description, asset_type, size, era, created_at, "
                   "image_storage_path, variation_storage_paths, "
                   "cost_usd, model_path, metadata_json")

    if cursor is not None:
        # Keyset pagination — stable under concurrent inserts.
        cursor_ts = _decode_history_cursor(cursor)
        if cursor_ts is None:
            raise HTTPException(status_code=400, detail="Invalid cursor")
        # Fetch limit+1 to detect whether more rows remain beyond this
        # page without a second round-trip.
        result = (
            sb.table("generations")
            .select(select_cols)
            .lt("created_at", cursor_ts)
            .order("created_at", desc=True)
            .limit(limit + 1)
            .execute()
        )
        rows = result.data or []
        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]
    else:
        # Offset pagination (backward compatible).
        result = (
            sb.table("generations")
            .select(select_cols)
            .order("created_at", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )
        rows = result.data or []
        has_more = (offset + len(rows)) < total

    items = [
        HistoryItem(
            id=row["id"],
            description=row["description"],
            asset_type=row["asset_type"],
            size=row["size"],
            era=row["era"],
            created_at=row["created_at"],
            image_storage_path=row.get("image_storage_path"),
            variation_storage_paths=list(row.get("variation_storage_paths") or []),
            cost_usd=float(row["cost_usd"]) if row.get("cost_usd") else None,
            model_path=row.get("model_path"),
            metadata_json=row.get("metadata_json"),
        )
        for row in rows
    ]

    # rg-018: batch-sign URLs for the private `generations` bucket.
    # Items with no storage path keep image_url=None. Items whose
    # signing fails (file missing, RLS denial, etc.) also stay None;
    # the frontend tolerates a missing image_url as "no thumbnail,
    # click is a no-op." 1-hour expiry covers typical session length;
    # users who keep the page open longer just need to refresh to
    # re-fetch fresh signed URLs.
    signable_paths = [
        item.image_storage_path
        for item in items
        if item.image_storage_path
    ]
    # Include variation paths in the same batch — one round-trip is
    # cheaper than per-item signing, and create_signed_urls returns a
    # path-keyed list that the lookup below handles uniformly.
    for item in items:
        signable_paths.extend(item.variation_storage_paths)

    if signable_paths:
        try:
            signed_responses = sb.storage.from_("generations").create_signed_urls(
                signable_paths, 3600
            )
            url_by_path: dict[str, str] = {}
            for entry in signed_responses or []:
                # storage3 returns dicts with path + signedURL; tolerate
                # either signedUrl or signedURL (both are populated by
                # the client) and skip entries where signing errored.
                if entry.get("error"):
                    continue
                path = entry.get("path")
                signed = entry.get("signedURL") or entry.get("signedUrl")
                if path and signed:
                    url_by_path[path] = signed
            for item in items:
                if item.image_storage_path:
                    item.image_url = url_by_path.get(item.image_storage_path)
                # Map variations in original order; drop any that failed
                # to sign so the frontend doesn't try to render a None.
                item.variation_image_urls = [
                    url_by_path[p]
                    for p in item.variation_storage_paths
                    if p in url_by_path
                ]
        except Exception as exc:
            # Don't fail the whole /history call if signing breaks —
            # cards will render without thumbnails. Surface the error
            # in logs for ops follow-up.
            logger.warning("Failed to sign history image URLs: %s", exc)

    next_cursor = None
    if has_more and items:
        next_cursor = _encode_history_cursor(items[-1].created_at)

    return HistoryResponse(
        items=items, total=total, has_more=has_more, next_cursor=next_cursor
    )


class UsageResponse(BaseModel):
    tier: str
    daily_count: int
    daily_limit: int | None = None
    daily_resets_at: str | None = None
    monthly_count: int
    monthly_limit: int | None = None
    monthly_resets_at: str | None = None
    total_count: int
    total_cost_usd: float


_TIER_LIMITS = {
    "free": {"daily": 5, "monthly": 50},
    "starter": {"daily": None, "monthly": 100},
    "pro": {"daily": None, "monthly": 225},
    "studio": {"daily": None, "monthly": 500},
}

# Monthly subscription price (USD) per tier — used for MRR estimates in the
# admin analytics view. Matches the public pricing page / LemonSqueezy variants.
_TIER_PRICES = {
    "free": 0,
    "starter": 5,
    "pro": 10,
    "studio": 20,
}

# Subscription statuses that still grant paid access (and thus count toward MRR).
# "none" means no active subscription; cancelled/past_due keep access until the
# billing period ends or dunning exhausts (see payments.py webhook handlers).
_REVENUE_STATUSES = frozenset({"active", "cancelled", "past_due", "paused"})


@app.get("/usage", response_model=UsageResponse, tags=["user"])
@limiter.limit("30/minute")
async def get_usage(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> UsageResponse:
    """Return the authenticated user's current usage stats and limits."""
    if not _db_enabled():
        return UsageResponse(
            tier="free", daily_count=0, monthly_count=0,
            total_count=0, total_cost_usd=0.0,
        )

    from .supabase_client import get_user_client
    sb = get_user_client(user.id)

    # Get profile tier
    profile = (
        sb.table("profiles").select("tier").single().execute()
    )
    tier = profile.data["tier"] if profile.data else "free"

    # Get usage counters
    counters = (
        sb.table("usage_counters")
        .select("daily_count, monthly_count, daily_reset_at, monthly_reset_at, "
                "total_count, total_cost_usd")
        .single()
        .execute()
    )
    c = counters.data or {}
    limits = _TIER_LIMITS.get(tier, _TIER_LIMITS["free"])

    return UsageResponse(
        tier=tier,
        daily_count=c.get("daily_count", 0),
        daily_limit=limits["daily"],
        daily_resets_at=c.get("daily_reset_at"),
        monthly_count=c.get("monthly_count", 0),
        monthly_limit=limits["monthly"],
        monthly_resets_at=c.get("monthly_reset_at"),
        total_count=c.get("total_count", 0),
        total_cost_usd=float(c.get("total_cost_usd", 0)),
    )


_HEX_COLOR_RE = _re.compile(r"^#[0-9A-Fa-f]{6}$")


class SavedPaletteModel(BaseModel):
    name: str = Field(..., max_length=30)
    colors: list[str] = Field(..., max_length=6)

    @field_validator("colors", mode="before")
    @classmethod
    def validate_hex_colors(cls, v):
        if not isinstance(v, list):
            raise ValueError("colors must be a list")
        for c in v:
            if not isinstance(c, str) or not _HEX_COLOR_RE.match(c):
                raise ValueError(f"Invalid hex color: {c}")
        return v


class UserSettings(BaseModel):
    default_era: str = "mid"
    default_palette_mood: str = "auto"
    default_outline: str = "Black"
    default_asset_type: str = "character"
    default_size: str = "16x16"
    default_view: str = "side"
    saved_palettes: list[SavedPaletteModel | dict] = Field(default_factory=list)


@app.get("/settings", response_model=UserSettings, tags=["user"])
@limiter.limit("30/minute")
async def get_settings(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> UserSettings:
    """Return the authenticated user's saved settings."""
    if not _db_enabled():
        return UserSettings()

    from .supabase_client import get_user_client
    sb = get_user_client(user.id)

    result = (
        sb.table("user_settings")
        .select("*")
        .single()
        .execute()
    )
    s = result.data or {}
    return UserSettings(
        default_era=s.get("default_era", "mid"),
        default_palette_mood=s.get("default_palette_mood", "auto"),
        default_outline=s.get("default_outline", "Black"),
        default_asset_type=s.get("default_asset_type", "character"),
        default_size=s.get("default_size", "16x16"),
        default_view=s.get("default_view", "side"),
        saved_palettes=s.get("saved_palettes", []),
    )


class UpdateSettingsRequest(BaseModel):
    default_era: str | None = None
    default_palette_mood: str | None = None
    default_outline: str | None = None
    default_asset_type: str | None = None
    default_size: str | None = None
    default_view: str | None = None
    saved_palettes: list[SavedPaletteModel] | None = None


@app.put("/settings", response_model=UserSettings, tags=["user"])
@limiter.limit("10/minute")
async def update_settings(
    request: Request,
    body: UpdateSettingsRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> UserSettings:
    """Update the authenticated user's settings. Only provided fields are changed."""
    if not _db_enabled():
        raise HTTPException(status_code=503, detail="Database not configured.")

    from .supabase_client import get_user_client
    sb = get_user_client(user.id)

    # Build update dict from non-None fields
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=422, detail="No fields to update.")

    result = (
        sb.table("user_settings")
        .update(updates)
        .execute()
    )

    # Return the updated settings
    return await get_settings(request, user)


# ---------------------------------------------------------------------------
# ToS / Privacy Policy consent
#
# Signup requires an explicit checkbox (frontend/app.js, signup-form handler)
# and records consent immediately when a session exists. Existing accounts
# that predate consent tracking (or whose accepted version is stale) get a
# one-time blocking prompt on next login — see checkConsentBackfill() in
# frontend/app.js. Both paths land here.
# ---------------------------------------------------------------------------

# Bump this whenever the Terms of Service or Privacy Policy changes in a way
# that should re-prompt every user, not just new signups — any profile whose
# stored tos_version doesn't match gets the one-time acceptance prompt again.
CURRENT_TOS_VERSION = "2026-07-11"


class ConsentStatusResponse(BaseModel):
    needs_acceptance: bool
    current_version: str
    accepted_version: str | None = None
    accepted_at: str | None = None


@app.get("/consent", response_model=ConsentStatusResponse, tags=["user"])
@limiter.limit("30/minute")
async def get_consent_status(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ConsentStatusResponse:
    """Return whether the authenticated user still needs to accept the
    current Terms of Service / Privacy Policy version."""
    if not _db_enabled():
        return ConsentStatusResponse(
            needs_acceptance=False, current_version=CURRENT_TOS_VERSION
        )

    from .supabase_client import get_user_client
    sb = get_user_client(user.id)

    result = (
        sb.table("profiles")
        .select("tos_version, tos_accepted_at")
        .single()
        .execute()
    )
    d = result.data or {}
    accepted_version = d.get("tos_version")
    return ConsentStatusResponse(
        needs_acceptance=accepted_version != CURRENT_TOS_VERSION,
        current_version=CURRENT_TOS_VERSION,
        accepted_version=accepted_version,
        accepted_at=d.get("tos_accepted_at"),
    )


class ConsentAcceptResponse(BaseModel):
    accepted_version: str
    accepted_at: str


@app.post("/consent/accept", response_model=ConsentAcceptResponse, tags=["user"])
@limiter.limit("10/minute")
async def accept_consent(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> ConsentAcceptResponse:
    """Record that the authenticated user accepted the current Terms of
    Service / Privacy Policy version (signup checkbox or backfill prompt)."""
    if not _db_enabled():
        raise HTTPException(status_code=503, detail="Database not configured.")

    from datetime import datetime, timezone
    from .supabase_client import get_user_client

    accepted_at = datetime.now(timezone.utc).isoformat()
    sb = get_user_client(user.id)
    sb.table("profiles").update({
        "tos_version": CURRENT_TOS_VERSION,
        "tos_accepted_at": accepted_at,
    }).execute()

    # Funnel: signup (top of the conversion funnel). This is the server-side
    # convergence point for a confirmed signup — the frontend records consent
    # here exactly once, right after the first SIGNED_IN following email
    # confirmation. Deduped once-per-user at the DB layer, so it fires only on
    # the user's first consent write. Best-effort — never break the flow.
    #
    # On that FIRST occurrence, also fire the (env-gated, OFF-by-default)
    # welcome email. Gating the send on the newly-recorded signup event keeps it
    # strictly one-shot per user; WELCOME_EMAIL_ENABLED is the real safety.
    try:
        from .funnel import emit_funnel_event
        first_signup = emit_funnel_event(user.id, "signup")
        if first_signup and user.email:
            from .email import welcome_email_enabled, send_welcome_email
            if welcome_email_enabled():
                try:
                    send_welcome_email(user.email)
                except Exception as exc:
                    logger.warning("welcome email send failed: %s", exc)
    except Exception as exc:
        logger.warning("funnel signup emit failed: %s", exc)

    return ConsentAcceptResponse(
        accepted_version=CURRENT_TOS_VERSION, accepted_at=accepted_at
    )


# ---------------------------------------------------------------------------
# Billing endpoints (LemonSqueezy)
# ---------------------------------------------------------------------------

_REFERRAL_CODE_RE = _re.compile(r"^[0-9a-f]{12}$")


async def _validated_referral_code(code: str | None, user_id: str | None = None) -> str | None:
    """Return an existing referral code unless it belongs to ``user_id``."""
    if not code or not _REFERRAL_CODE_RE.fullmatch(code.lower()) or not _db_enabled():
        return None
    normalized = code.lower()
    if user_id and normalized == user_id.replace("-", "")[:12].lower():
        return None
    from .supabase_client import get_supabase_client
    result = (
        get_supabase_client().table("profiles")
        .select("id").eq("referral_code", normalized).limit(1).execute()
    )
    return normalized if getattr(result, "data", None) else None


class ReferralValidationResponse(BaseModel):
    valid: bool


@app.get("/referrals/{code}", response_model=ReferralValidationResponse, tags=["billing"])
@limiter.limit("30/minute")
async def validate_referral(request: Request, code: str) -> ReferralValidationResponse:
    """Validate a share-link code without exposing its member."""
    return ReferralValidationResponse(valid=bool(await _validated_referral_code(code)))

class CheckoutRequest(BaseModel):
    tier: str = Field(..., pattern=r"^(starter|pro|studio)$")
    interval: str = Field("monthly", pattern=r"^(monthly|annual)$")
    return_url: str | None = Field(
        None,
        description="URL the user is redirected to after checkout. LemonSqueezy appends ?checkout=success.",
    )
    ref: str | None = Field(None, pattern=r"^[0-9a-f]{12}$")


class CheckoutResponse(BaseModel):
    checkout_url: str


@app.post("/checkout", response_model=CheckoutResponse, tags=["billing"])
@limiter.limit("5/minute")
async def create_checkout(
    request: Request,
    body: CheckoutRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> CheckoutResponse:
    """Create a LemonSqueezy checkout URL for the given tier."""
    if not payments_configured():
        raise HTTPException(status_code=503, detail="Payments not configured.")

    from .payments import create_checkout_url

    # Derive a return URL so LemonSqueezy redirects back to the app after
    # checkout. Prefer an explicit client-supplied value; fall back to the
    # Referer header (stripped of query/fragment) so the user lands on the
    # page they started from.
    return_url = body.return_url
    if not return_url:
        referer = request.headers.get("referer", "").strip()
        if referer.startswith(("http://", "https://")):
            from urllib.parse import urlsplit, urlunsplit
            parts = urlsplit(referer)
            return_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))

    # Validate the return_url origin against the CORS allowlist to prevent
    # open redirect on the post-checkout return flow. Both the explicit
    # client-supplied value and the Referer fallback are checked here.
    if return_url:
        from .payments import validate_return_url
        return_url = validate_return_url(return_url, _cors_origins)
        if return_url is None:
            raise HTTPException(
                status_code=422,
                detail="return_url origin not allowed.",
            )

    try:
        referral_code = await _validated_referral_code(body.ref, user.id)
        url = await create_checkout_url(
            user.id, user.email, body.tier, body.interval, return_url=return_url,
            referral_code=referral_code,
        )
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid tier or billing interval.") from None
    except Exception as exc:
        logger.error("Checkout creation failed: %s", exc)
        raise HTTPException(status_code=502, detail="Payment service unavailable.") from exc

    return CheckoutResponse(checkout_url=url)


@app.post("/webhooks/lemonsqueezy", tags=["billing"])
async def lemonsqueezy_webhook(request: Request):
    """
    Receive and process LemonSqueezy webhook events.

    Public endpoint — secured by HMAC-SHA256 signature verification,
    not JWT auth.
    """
    from .payments import (
        verify_webhook_signature,
        handle_webhook_event,
        webhook_event_id,
        is_webhook_processed,
        mark_webhook_processed,
    )

    body = await request.body()
    signature = request.headers.get("X-Signature", "")

    if not verify_webhook_signature(body, signature):
        raise HTTPException(status_code=403, detail="Invalid webhook signature.")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    event_name = payload.get("meta", {}).get("event_name", "")
    if not event_name:
        raise HTTPException(status_code=400, detail="Missing event_name in payload.")

    # Idempotency: LemonSqueezy retries deliveries. Short-circuit duplicates so
    # a retry never triggers a double tier-change or double-refund.
    event_id = webhook_event_id(payload)
    if await is_webhook_processed(event_id):
        logger.info(
            "Duplicate webhook skipped (event_id=%s event_name=%s)",
            event_id, event_name,
        )
        return {"status": "ok", "duplicate": True}

    try:
        await handle_webhook_event(event_name, payload)
    except Exception as exc:
        logger.error("Webhook processing failed for %s: %s", event_name, exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed.") from exc

    await mark_webhook_processed(event_id, event_name)

    return {"status": "ok"}


@app.post("/webhooks/resend", tags=["email"])
async def resend_webhook(request: Request):
    """
    Receive Resend email-event webhooks (bounces + spam complaints).

    Public endpoint — secured by Svix HMAC signature verification (svix-id /
    svix-timestamp / svix-signature headers, RESEND_WEBHOOK_SECRET). An
    unverifiable request is rejected with 401 before any processing (fail
    closed). Hard bounces + complaints add the address to the suppression list;
    transient/soft bounces are counted only.
    """
    from .suppression import (
        verify_resend_signature,
        handle_resend_event,
        resend_event_id,
    )
    from .payments import is_webhook_processed, mark_webhook_processed

    body = await request.body()
    if not verify_resend_signature(body, request.headers):
        raise HTTPException(status_code=401, detail="Invalid webhook signature.")

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    # Idempotency: Svix retries deliveries; the svix-id is unique per delivery.
    event_id = resend_event_id(request.headers)
    if await is_webhook_processed(event_id):
        return {"status": "ok", "duplicate": True}

    try:
        handle_resend_event(payload)
    except Exception as exc:
        logger.error("Resend webhook processing failed: %s", exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed.") from exc

    await mark_webhook_processed(event_id, payload.get("type", "resend.event"))
    return {"status": "ok"}


@app.post("/webhooks/postmark", tags=["email"])
async def postmark_webhook(request: Request):
    """
    Receive Postmark email-event webhooks (bounces + spam complaints).

    Postmark does NOT sign its webhooks; its documented recommendation is HTTP
    Basic Auth on the webhook URL (over HTTPS) plus IP allowlisting. We verify
    Basic Auth against POSTMARK_WEBHOOK_USERNAME / POSTMARK_WEBHOOK_PASSWORD; an
    unauthenticated request is rejected with 401 before any processing (fail
    closed). Hard bounces + spam complaints suppress; transient/soft bounces are
    counted only.
    """
    from .suppression import (
        verify_postmark_basic_auth,
        handle_postmark_event,
        postmark_event_id,
    )
    from .payments import is_webhook_processed, mark_webhook_processed

    if not verify_postmark_basic_auth(request.headers.get("authorization", "")):
        raise HTTPException(status_code=401, detail="Unauthorized.")

    body = await request.body()
    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON.")

    event_id = postmark_event_id(payload)
    if await is_webhook_processed(event_id):
        return {"status": "ok", "duplicate": True}

    try:
        handle_postmark_event(payload)
    except Exception as exc:
        logger.error("Postmark webhook processing failed: %s", exc)
        raise HTTPException(status_code=500, detail="Webhook processing failed.") from exc

    await mark_webhook_processed(event_id, "postmark:" + str(payload.get("RecordType", "")))
    return {"status": "ok"}


class SubscriptionResponse(BaseModel):
    tier: str
    subscription_status: str
    subscription_renews_at: str | None = None
    has_subscription: bool = False
    referral_code: str | None = None
    subscription_pause_mode: str | None = None


@app.get("/subscription", response_model=SubscriptionResponse, tags=["billing"])
@limiter.limit("30/minute")
async def get_subscription(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> SubscriptionResponse:
    """Return the authenticated user's current subscription status."""
    if not _db_enabled():
        return SubscriptionResponse(tier="free", subscription_status="none")

    from .supabase_client import get_user_client
    sb = get_user_client(user.id)

    result = (
        sb.table("profiles")
        .select("tier, subscription_status, subscription_renews_at, lemon_customer_id, subscription_pause_mode")
        .single()
        .execute()
    )
    d = result.data or {}
    return SubscriptionResponse(
        tier=d.get("tier", "free"),
        subscription_status=d.get("subscription_status", "none"),
        subscription_renews_at=d.get("subscription_renews_at"),
        has_subscription=bool(d.get("lemon_customer_id")),
        referral_code=user.id.replace("-", "")[:12].lower(),
        subscription_pause_mode=d.get("subscription_pause_mode"),
    )


class PortalResponse(BaseModel):
    portal_url: str


@app.post("/billing-portal", response_model=PortalResponse, tags=["billing"])
@limiter.limit("5/minute")
async def billing_portal(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> PortalResponse:
    """Get the LemonSqueezy customer portal URL for billing management."""
    if not payments_configured():
        raise HTTPException(status_code=503, detail="Payments not configured.")
    if not _db_enabled():
        raise HTTPException(status_code=503, detail="Database not configured.")

    from .supabase_client import get_user_client
    from .payments import get_customer_portal_url

    sb = get_user_client(user.id)
    result = (
        sb.table("profiles")
        .select("lemon_customer_id")
        .single()
        .execute()
    )
    customer_id = (result.data or {}).get("lemon_customer_id")
    if not customer_id:
        raise HTTPException(status_code=404, detail="No active subscription found.")

    try:
        url = await get_customer_portal_url(customer_id)
    except Exception as exc:
        logger.error("Portal URL fetch failed: %s", exc)
        raise HTTPException(status_code=502, detail="Payment service unavailable.") from exc

    return PortalResponse(portal_url=url)


# ---------------------------------------------------------------------------
# API Keys — MCP Server Product license key management
# ---------------------------------------------------------------------------

class CreateKeyRequest(BaseModel):
    name: str = Field(default="Default", max_length=100, pattern=r"^[\x20-\x7E]+$", description="Friendly name for the key (printable ASCII only).")

class CreateKeyResponse(BaseModel):
    key: str = Field(description="Full API key — shown only once. Store it now.")
    key_id: str = Field(description="Key UUID for management.")
    key_prefix: str = Field(description="Truncated prefix for display.")

class KeyInfo(BaseModel):
    id: str
    key_prefix: str
    name: str
    monthly_limit: int | None
    monthly_used: int
    last_used_at: str | None
    revoked_at: str | None
    created_at: str

class KeyListResponse(BaseModel):
    keys: list[KeyInfo]


@app.post("/api-keys", response_model=CreateKeyResponse, tags=["api-keys"])
@limiter.limit("5/minute")
async def create_api_key(
    request: Request,
    body: CreateKeyRequest,
    user: AuthenticatedUser = Depends(get_current_user),
) -> CreateKeyResponse:
    """Create a new MCP API key. The full key is returned only once."""
    if not _db_enabled():
        raise HTTPException(status_code=503, detail="Database not configured.")

    from .supabase_client import get_user_client
    from .mcp_keys import generate_api_key

    # Get user's tier for limit calculation
    sb = get_user_client(user.id)
    profile = sb.table("profiles").select("tier").execute()
    tier = "free"
    if profile.data:
        tier = profile.data[0].get("tier", "free")

    # Cap active keys per user (prevent resource exhaustion / billing bypass)
    existing = (
        sb.table("api_keys")
        .select("id", count="exact")
        .is_("revoked_at", "null")
        .execute()
    )
    if (existing.count or 0) >= 10:
        raise HTTPException(status_code=422, detail="Maximum of 10 active API keys allowed.")

    try:
        full_key, key_id = await generate_api_key(user.id, body.name, tier)
    except Exception as exc:
        logger.error("Key creation failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to create API key.") from exc

    return CreateKeyResponse(
        key=full_key,
        key_id=key_id,
        key_prefix=full_key[:20] + "...",
    )


@app.get("/api-keys", response_model=KeyListResponse, tags=["api-keys"])
@limiter.limit("10/minute")
async def list_api_keys(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> KeyListResponse:
    """List all API keys for the authenticated user."""
    if not _db_enabled():
        raise HTTPException(status_code=503, detail="Database not configured.")

    from .mcp_keys import list_user_keys

    keys = await list_user_keys(user.id)
    return KeyListResponse(keys=[KeyInfo(**k) for k in keys])


@app.delete("/api-keys/{key_id}", tags=["api-keys"])
@limiter.limit("10/minute")
async def delete_api_key(
    request: Request,
    key_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Revoke an API key. This cannot be undone."""
    if not _db_enabled():
        raise HTTPException(status_code=503, detail="Database not configured.")

    from .mcp_keys import revoke_api_key

    revoked = await revoke_api_key(key_id, user.id)
    if not revoked:
        raise HTTPException(status_code=404, detail="Key not found or already revoked.")

    return {"status": "revoked", "key_id": key_id}


# ---------------------------------------------------------------------------
# Account deletion (GDPR "right to erasure") — permanent, irreversible.
# ---------------------------------------------------------------------------

@app.delete("/account", tags=["account"])
@limiter.limit("10/minute")
async def delete_account(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Permanently delete the authenticated user's account and all their data.

    GDPR Article 17 ("right to erasure"). This cannot be undone.

    Order of operations matters:

    1. SAFE-ORG CHECK — refuse (409) if the user solely owns an organization
       that has *other* members. Deleting the user would orphan those members,
       so we ask them to transfer ownership first. Orgs the user occupies
       alone are fine: they cascade-delete with the user.
    2. STORAGE PURGE — delete every object under the user's "{user_id}/" prefix
       in the private "generations" bucket. Storage is NOT foreign-keyed to the
       DB, so the auth-user cascade would leave these files orphaned. We purge
       FIRST so that if storage is flaky we can fail (500, retryable) WITHOUT
       having destroyed the auth user / DB rows.
    3. AUTH-USER DELETE — service-role admin delete of the auth.users row, which
       cascades to profiles and every user-owned table (generations,
       usage_counters, user_settings, api_keys, org_members, and any solely
       owned organizations) via ON DELETE CASCADE.
    """
    if not _db_enabled():
        raise HTTPException(status_code=503, detail="Database not configured.")

    from .supabase_client import get_supabase_client

    sb = get_supabase_client()
    user_id = user.id

    # --- 1. Safe-org check ------------------------------------------------
    # Find organizations this user owns, then for each check whether any
    # OTHER user is a member. If so, abort — the user must transfer ownership
    # before we delete them, or those members would be orphaned.
    try:
        owned_orgs_resp = (
            sb.table("organizations").select("id").eq("owner_id", user_id).execute()
        )
        owned_org_ids = [row["id"] for row in (owned_orgs_resp.data or [])]
    except Exception as exc:
        logger.warning("Account deletion: failed to list owned orgs for %s: %s", user_id, exc)
        raise HTTPException(
            status_code=500, detail="Could not verify organization ownership. Try again."
        ) from exc

    for org_id in owned_org_ids:
        try:
            # Any member row for this org whose user_id is NOT the owner = a
            # shared org. Limit 1 — we only need to know one exists.
            others_resp = (
                sb.table("org_members")
                .select("user_id")
                .eq("org_id", org_id)
                .neq("user_id", user_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            logger.warning(
                "Account deletion: failed to check org_members for org %s: %s", org_id, exc
            )
            raise HTTPException(
                status_code=500,
                detail="Could not verify organization membership. Try again.",
            ) from exc

        if others_resp.data:
            # Shared org with other members — refuse and tell the user what to do.
            # Nothing has been deleted at this point.
            raise HTTPException(
                status_code=409,
                detail=(
                    "You own an organization that has other members. Transfer "
                    "ownership of your organization(s) to another member before "
                    "deleting your account."
                ),
            )

    # --- 2. Storage purge (FIRST, before any destructive DB/auth call) ----
    # The user's objects live under the "{user_id}/" prefix in the private
    # "generations" bucket. Storage is not FK-linked, so it must be removed
    # explicitly. List + remove in a loop to handle many files / pagination;
    # storage3's list() returns at most `limit` entries per call.
    bucket = sb.storage.from_("generations")
    prefix = user_id
    page_limit = 100
    try:
        while True:
            listing = bucket.list(
                prefix,
                {"limit": page_limit, "offset": 0},
            )
            if not listing:
                break
            # Build full object paths ("{user_id}/{name}") for removal. Skip any
            # entry without a name (defensive). Folder-like entries have id=None
            # in storage3, but the user's objects are flat files under the prefix.
            paths = [
                f"{prefix}/{obj['name']}"
                for obj in listing
                if obj.get("name")
            ]
            if not paths:
                break
            bucket.remove(paths)
            # If this page was smaller than the limit, we've removed everything;
            # otherwise loop again (offset stays 0 because we just deleted the
            # objects we listed, so the next page starts fresh at the top).
            if len(listing) < page_limit:
                break
    except Exception as exc:
        logger.error("Account deletion: storage purge failed for %s: %s", user_id, exc)
        # Retryable — the auth user / DB rows are still intact.
        raise HTTPException(
            status_code=500,
            detail="Failed to delete stored files. Please try again.",
        ) from exc

    # --- 3. Delete the auth user (cascades all DB rows) -------------------
    # Service-role admin delete. profiles.id FK -> auth.users(id) ON DELETE
    # CASCADE, and every user table FK's to profiles(id) ON DELETE CASCADE,
    # so this single call removes all of the user's database rows.
    try:
        sb.auth.admin.delete_user(user_id)
    except Exception as exc:
        logger.error("Account deletion: auth.admin.delete_user failed for %s: %s", user_id, exc)
        raise HTTPException(
            status_code=500,
            detail="Failed to delete account. Please try again.",
        ) from exc

    logger.info("Account deleted: %s", user_id)
    return {"deleted": True}


# ---------------------------------------------------------------------------
# Account data export (GDPR "right to data portability") — Article 20.
# ---------------------------------------------------------------------------

@app.get("/account/export", tags=["account"])
@limiter.limit("5/minute")
async def export_account_data(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Export all of the authenticated user's data as a downloadable ZIP archive.

    GDPR Article 20 ("right to data portability"). Returns a ZIP containing
    the user's profile, settings, API keys (metadata only — never the hashed
    key material), usage counters, every generation row, and the PNG images
    stored under their private "generations" bucket prefix.

    Each section is best-effort: a failure fetching one table or downloading
    one image is logged and skipped so a single flaky object can't sink the
    whole export. Nothing is mutated — this is a read-only operation.
    """
    if not _db_enabled():
        raise HTTPException(status_code=503, detail="Database not configured.")

    import io
    import zipfile
    from datetime import datetime, timezone
    from fastapi.responses import StreamingResponse

    from .supabase_client import get_user_client

    sb = get_user_client(user.id)
    user_id = user.id

    # --- Profile ----------------------------------------------------------
    profile: dict = {}
    try:
        profile_resp = sb.table("profiles").select("*").single().execute()
        profile = profile_resp.data or {}
    except Exception as exc:
        logger.warning("Data export: profile fetch failed for %s: %s", user_id, exc)

    # --- Settings ---------------------------------------------------------
    settings: dict = {}
    try:
        settings_resp = sb.table("user_settings").select("*").single().execute()
        settings = settings_resp.data or {}
    except Exception as exc:
        logger.warning("Data export: settings fetch failed for %s: %s", user_id, exc)

    # --- API keys (metadata only — never the hash) ------------------------
    api_keys: list[dict] = []
    try:
        keys_resp = (
            sb.table("api_keys")
            .select("id, key_prefix, name, monthly_limit, monthly_used, "
                    "last_used_at, revoked_at, created_at")
            .order("created_at", desc=True)
            .execute()
        )
        api_keys = keys_resp.data or []
    except Exception as exc:
        logger.warning("Data export: api_keys fetch failed for %s: %s", user_id, exc)

    # --- Usage counters ---------------------------------------------------
    usage_counters: dict = {}
    try:
        usage_resp = sb.table("usage_counters").select("*").single().execute()
        usage_counters = usage_resp.data or {}
    except Exception as exc:
        logger.warning("Data export: usage_counters fetch failed for %s: %s", user_id, exc)

    # --- Generations (paginate to fetch every row) -------------------------
    generations: list[dict] = []
    page_size = 1000
    offset = 0
    try:
        while True:
            page = (
                sb.table("generations")
                .select("*")
                .order("created_at", desc=True)
                .range(offset, offset + page_size - 1)
                .execute()
            )
            rows = page.data or []
            generations.extend(rows)
            if len(rows) < page_size:
                break
            offset += page_size
    except Exception as exc:
        logger.warning("Data export: generations fetch failed for %s: %s", user_id, exc)

    # --- Storage images ---------------------------------------------------
    # Download every image referenced by a generation row from the private
    # "generations" bucket. Individual download failures are logged and
    # skipped so one missing file can't sink the whole export.
    image_files: dict[str, bytes] = {}
    bucket = sb.storage.from_("generations")
    seen_paths: set[str] = set()
    for row in generations:
        paths = [row.get("image_storage_path")]
        paths.extend(row.get("variation_storage_paths") or [])
        for path in paths:
            if not path or path in seen_paths:
                continue
            seen_paths.add(path)
            try:
                img_bytes = bucket.download(path)
                if img_bytes:
                    image_files[Path(path).name] = img_bytes
            except Exception as exc:
                logger.warning(
                    "Data export: image download failed for %s (%s): %s", user_id, path, exc
                )

    # --- Build the ZIP archive in memory ----------------------------------
    exported_at = datetime.now(timezone.utc).isoformat()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("export_meta.json", json.dumps({
            "exported_at": exported_at,
            "user_id": user_id,
            "email": user.email,
            "generations_count": len(generations),
            "images_count": len(image_files),
        }, indent=2, default=str))
        zf.writestr("profile.json", json.dumps(profile, indent=2, default=str))
        zf.writestr("settings.json", json.dumps(settings, indent=2, default=str))
        zf.writestr("api_keys.json", json.dumps(api_keys, indent=2, default=str))
        zf.writestr("usage_counters.json", json.dumps(usage_counters, indent=2, default=str))
        zf.writestr("generations.json", json.dumps(generations, indent=2, default=str))
        for name, data in image_files.items():
            zf.writestr(f"images/{name}", data)
    buf.seek(0)

    logger.info("Data export: built archive for %s (%d generations, %d images)",
                user_id, len(generations), len(image_files))

    filename = f"retrogaze-export-{user_id}.zip"
    return StreamingResponse(
        buf,
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ---------------------------------------------------------------------------
# Auth email delivery — bypass Supabase's built-in sender (capped, spam-prone)
# by generating action links via the admin API and sending through Resend or
# Postmark. See src/retrogaze/email.py for ESP configuration.
# ---------------------------------------------------------------------------

class _AuthEmailRequest(BaseModel):
    email: str = Field(..., max_length=254)
    redirect_to: str | None = Field(
        None,
        description="URL the user lands on after clicking the email link.",
    )


class _AuthEmailResponse(BaseModel):
    ok: bool
    message: str


@app.post("/auth/reset-password", response_model=_AuthEmailResponse, tags=["auth"])
@limiter.limit("5/minute")
async def request_password_reset(request: Request, body: _AuthEmailRequest):
    """Send a password-reset email via custom ESP (Resend/Postmark).

    Bypasses Supabase's built-in sender, which is capped at a few emails per
    hour and lands in spam. Generates a recovery link via the admin
    generate_link API (does NOT trigger Supabase's email) and sends it
    through the configured transactional ESP.
    """
    from .email import send_password_reset_email, email_configured

    if not email_configured():
        raise HTTPException(
            status_code=503,
            detail="Custom email delivery not configured. Set RESEND_API_KEY or POSTMARK_SERVER_TOKEN.",
        )
    try:
        result = send_password_reset_email(body.email, body.redirect_to)
    except RuntimeError as exc:
        logger.warning("Password reset link generation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.ok:
        return {"ok": True, "message": "Password reset email sent."}
    logger.warning("Password reset email send failed: %s", result.error)
    raise HTTPException(status_code=502, detail=result.error or "Email send failed.")


@app.post("/auth/resend-confirmation", response_model=_AuthEmailResponse, tags=["auth"])
@limiter.limit("5/minute")
async def resend_confirmation(request: Request, body: _AuthEmailRequest):
    """Resend a signup confirmation email via custom ESP (Resend/Postmark).

    For users who didn't receive the original Supabase confirmation email
    (spam folder, rate cap, etc.). Generates a signup confirmation link via
    the admin generate_link API and sends it through the configured ESP.
    """
    from .email import send_confirmation_email, email_configured

    if not email_configured():
        raise HTTPException(
            status_code=503,
            detail="Custom email delivery not configured. Set RESEND_API_KEY or POSTMARK_SERVER_TOKEN.",
        )
    try:
        result = send_confirmation_email(body.email, body.redirect_to)
    except RuntimeError as exc:
        logger.warning("Confirmation link generation failed: %s", exc)
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    if result.ok:
        return {"ok": True, "message": "Confirmation email sent."}
    logger.warning("Confirmation email send failed: %s", result.error)
    raise HTTPException(status_code=502, detail=result.error or "Email send failed.")


# ---------------------------------------------------------------------------
# robots.txt — block crawlers from API endpoints
# ---------------------------------------------------------------------------

@app.get("/robots.txt", include_in_schema=False)
async def robots_txt():
    return PlainTextResponse(
        "User-agent: *\n"
        "Allow: /\n"
        "Allow: /app\n"
        "Disallow: /generate\n"
        "Disallow: /config\n"
        "Disallow: /history\n"
        "Disallow: /usage\n"
        "Disallow: /settings\n"
        "Disallow: /checkout\n"
        "Disallow: /webhooks/\n"
        "Disallow: /subscription\n"
        "Disallow: /billing-portal\n"
        "Disallow: /waitlist\n"
        "Disallow: /feedback\n"
        "Disallow: /health\n"
        "Disallow: /admin\n"
        "\n"
        "Sitemap: https://retrogazeai.com/sitemap.xml\n"
    )


# ---------------------------------------------------------------------------
# User feedback / bug reports
# ---------------------------------------------------------------------------

# CREATE TABLE public.feedback (
#   id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
#   created_at timestamptz NOT NULL DEFAULT now(),
#   user_id uuid REFERENCES auth.users(id) ON DELETE SET NULL,
#   message text NOT NULL,
#   category text NOT NULL DEFAULT 'bug',
#   context text,
#   status text NOT NULL DEFAULT 'new',      -- new | read | resolved (admin triage)
#   resolved_at timestamptz                   -- set when status -> resolved
# );
# CREATE INDEX feedback_created_at_idx ON public.feedback (created_at DESC);
# CREATE INDEX feedback_status_idx ON public.feedback (status);

_VALID_FEEDBACK_CATEGORIES = frozenset({"bug", "idea", "other"})


class FeedbackRequest(BaseModel):
    message: str = Field(..., max_length=2000)
    category: str = Field("bug", max_length=20)
    context: str | None = Field(None, max_length=200)

    @field_validator("message")
    @classmethod
    def validate_message(cls, v: str) -> str:
        v = v.strip()
        if not v:
            raise ValueError("message is required")
        return v

    @field_validator("category")
    @classmethod
    def validate_category(cls, v: str) -> str:
        if v not in _VALID_FEEDBACK_CATEGORIES:
            raise ValueError("category must be bug, idea, or other")
        return v

    @field_validator("context")
    @classmethod
    def normalize_context(cls, v: str | None) -> str | None:
        if v is None:
            return None
        v = v.strip()
        return v or None


class FeedbackResponse(BaseModel):
    ok: bool
    message: str


@app.post("/feedback", response_model=FeedbackResponse, tags=["meta"])
@limiter.limit("3/minute")
async def submit_feedback(
    request: Request,
    body: FeedbackRequest,
    user: AuthenticatedUser | None = Depends(get_optional_user),
) -> FeedbackResponse:
    """Submit in-app feedback or a bug report."""
    if _DEMO:
        raise HTTPException(
            status_code=503,
            detail=f"Feedback is not collected on the free demo. Please open an issue: {_REPO_URL}/issues",
        )
    if not _db_enabled():
        return FeedbackResponse(ok=True, message="Thanks for your feedback!")

    from .supabase_client import get_supabase_client

    row = {
        "message": body.message,
        "category": body.category,
        "context": body.context,
        "user_id": user.id if user else None,
    }

    sb = get_supabase_client()
    try:
        sb.table("feedback").insert(row).execute()
    except Exception as exc:
        logger.warning("Feedback insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Something went wrong.") from exc

    return FeedbackResponse(ok=True, message="Thanks for your feedback!")


# ---------------------------------------------------------------------------
# Pre-launch waitlist
# ---------------------------------------------------------------------------

# Email shape + reserved-domain validation lives in .email_validation
# (is_valid_signup_email): the waitlist endpoint must reject the same
# reserved, never-deliverable domains that Supabase Auth rejects at
# signup (2026-09-30 funnel finding B).


class WaitlistRequest(BaseModel):
    email: str = Field(..., max_length=254)


class WaitlistResponse(BaseModel):
    ok: bool
    message: str


@app.post("/waitlist", response_model=WaitlistResponse, tags=["meta"])
@limiter.limit("5/minute")
async def join_waitlist(
    request: Request,
    body: WaitlistRequest,
) -> WaitlistResponse:
    """Add an email to the pre-launch waitlist."""
    email = body.email.strip().lower()
    if not is_valid_signup_email(email):
        raise HTTPException(status_code=422, detail="Invalid email address.")

    if not _db_enabled():
        return WaitlistResponse(ok=True, message="Thanks! We'll be in touch.")

    from .supabase_client import get_supabase_client
    sb = get_supabase_client()
    try:
        sb.table("waitlist").insert({"email": email}).execute()
    except Exception as exc:
        if "duplicate" in str(exc).lower() or "unique" in str(exc).lower():
            return WaitlistResponse(ok=True, message="You're already on the list!")
        logger.warning("Waitlist insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Something went wrong.") from exc

    return WaitlistResponse(ok=True, message="Thanks! We'll be in touch.")


# ---------------------------------------------------------------------------
# Analytics events
# ---------------------------------------------------------------------------

_VALID_EVENT_TYPES = {
    "session_start", "session_heartbeat",
    "landing_view", "cta_click", "waitlist_signup", "pricing_click", "nav_click",
    "page_view", "generation_start", "generation_success", "generation_error",
    "download_png", "download_bundle", "more_like_this", "variations_requested",
    "template_saved", "template_loaded", "reference_uploaded", "palette_locked",
    "signup", "login",
}


class EventRequest(BaseModel):
    session_id: str = Field(..., max_length=64)
    event_type: str = Field(..., max_length=40)
    metadata: dict = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def limit_metadata_size(cls, v):
        if len(json.dumps(v, default=str)) > 2048:
            raise ValueError("Event metadata exceeds 2 KB limit.")
        return v


@app.post("/events", tags=["analytics"])
@limiter.limit("30/minute")
async def record_event(
    request: Request,
    body: EventRequest,
    user: AuthenticatedUser | None = Depends(get_optional_user),
):
    """Record a frontend analytics event."""
    if body.event_type not in _VALID_EVENT_TYPES:
        raise HTTPException(status_code=422, detail="Invalid event type.")

    if not _db_enabled():
        return {"ok": True}

    from .supabase_client import get_supabase_client
    sb = get_supabase_client()

    try:
        sb.rpc("record_event", {
            "p_session_id": body.session_id,
            "p_user_id": user.id if user else None,
            "p_event_type": body.event_type,
            "p_metadata": body.metadata,
        }).execute()
    except Exception as exc:
        logger.warning("Failed to record event: %s", exc)

    return {"ok": True}


# ---------------------------------------------------------------------------
# Conversion-funnel events (client-emitted subset)
#
# The server-side funnel milestones (signup / first_generation /
# checkout_complete) are emitted from their own flows. This endpoint is only for
# the CLIENT-observed milestones the browser must report — the >=90% usage-meter
# nudge being shown, and upgrade-affordance clicks. It requires session auth
# (like the other user endpoints, no anon abuse) and the server writes via the
# service-role client. The event_type allowlist (funnel.CLIENT_EMITTABLE) means
# a client can never spoof a server-owned milestone.
# ---------------------------------------------------------------------------

class FunnelEventRequest(BaseModel):
    event_type: str = Field(..., max_length=40)
    metadata: dict = Field(default_factory=dict)

    @field_validator("metadata", mode="before")
    @classmethod
    def limit_metadata_size(cls, v):
        if len(json.dumps(v, default=str)) > 2048:
            raise ValueError("Event metadata exceeds 2 KB limit.")
        return v


@app.post("/funnel-events", tags=["analytics"])
@limiter.limit("60/minute")
async def record_funnel_event(
    request: Request,
    body: FunnelEventRequest,
    user: AuthenticatedUser = Depends(get_current_user),
):
    """Record a client-observed conversion-funnel event (session auth required).

    Only the client-emittable subset (usage_meter_90_shown, upgrade_click) is
    accepted; server-owned milestones can't be posted here.
    """
    from .funnel import CLIENT_EMITTABLE, emit_funnel_event

    if body.event_type not in CLIENT_EMITTABLE:
        raise HTTPException(status_code=422, detail="Invalid funnel event type.")

    if not _db_enabled():
        return {"ok": True}

    emit_funnel_event(user.id, body.event_type, body.metadata)
    return {"ok": True}


# ---------------------------------------------------------------------------
# Admin dashboard
# ---------------------------------------------------------------------------

_ADMIN_PASSWORD = os.environ.get("RETROGAZE_ADMIN_PASSWORD", "").strip()


def _check_admin(request: Request) -> None:
    """Verify admin password from Authorization header."""
    if not _ADMIN_PASSWORD:
        raise HTTPException(status_code=503, detail="Admin not configured.")
    auth = request.headers.get("authorization", "")
    if not auth.startswith("Bearer ") or not hmac.compare_digest(auth[7:], _ADMIN_PASSWORD):
        raise HTTPException(status_code=401, detail="Unauthorized.")


@app.get("/admin", include_in_schema=False)
async def serve_admin(request: Request):
    # Public / OSS build: admin HTML is not shipped. Avoid FileResponse 500.
    path = _frontend_dir / "admin.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path)


@app.get("/admin/analytics", include_in_schema=False)
async def serve_admin_analytics(request: Request):
    path = _frontend_dir / "admin-analytics.html"
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Not found.")
    return FileResponse(path)


@app.get("/admin/api/stats", include_in_schema=False)
@limiter.limit("5/minute")
async def admin_stats(request: Request):
    """Return dashboard stats. Requires RETROGAZE_ADMIN_PASSWORD."""
    _check_admin(request)

    from datetime import datetime, timedelta, timezone
    now_utc = datetime.now(timezone.utc)
    today_start = now_utc.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    week_start = (now_utc - timedelta(days=7)).isoformat()

    from .cost_model import aggregate_margin_by_tier_month

    stats = {
        "waitlist_count": 0,
        "generation_count": 0,
        "total_cost_usd": 0.0,
        "user_count": 0,
        "gens_today": 0,
        "gens_this_week": 0,
        "recent_waitlist": [],
        "recent_generations": [],
        "tier_breakdown": [],
        "asset_type_distribution": [],
        "era_distribution": [],
        "feature_usage": {},
        "daily_trend": [],
        "active_users": {"dau": 0, "wau": 0},
        # Cost side (margin tracking, f760b9e) and revenue side (MRR) are
        # complementary — the analytics view reads both.
        "margin_by_tier_month": [],
        "free_tier_burn_this_month_usd": 0.0,
        "mrr_usd": 0.0,
        "revenue_per_tier": [],
        "subscription_status_breakdown": [],
        "services": {
            "supabase": supabase_configured(),
            "fal_ai": bool(os.environ.get("FAL_KEY", "").strip()),
            "lemonsqueezy": payments_configured(),
            "sentry": bool(os.environ.get("SENTRY_DSN", "").strip()),
        },
    }

    if _db_enabled():
        from .supabase_client import get_supabase_client
        sb = get_supabase_client()
        try:
            # Waitlist count + recent entries
            wl_count = sb.table("waitlist").select("id", count="exact").execute()
            stats["waitlist_count"] = wl_count.count or 0

            wl_recent = (
                sb.table("waitlist")
                .select("email, created_at")
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            stats["recent_waitlist"] = wl_recent.data or []

            # Generation count + total cost
            gen_count = sb.table("generations").select("id", count="exact").execute()
            stats["generation_count"] = gen_count.count or 0

            gen_cost = (
                sb.table("generations")
                .select("cost_usd")
                .execute()
            )
            if gen_cost.data:
                stats["total_cost_usd"] = sum(
                    float(r.get("cost_usd", 0) or 0) for r in gen_cost.data
                )

            # Gens today + this week
            gens_today = (
                sb.table("generations")
                .select("id", count="exact")
                .gte("created_at", today_start)
                .execute()
            )
            stats["gens_today"] = gens_today.count or 0

            gens_week = (
                sb.table("generations")
                .select("id", count="exact")
                .gte("created_at", week_start)
                .execute()
            )
            stats["gens_this_week"] = gens_week.count or 0

            # Recent generations
            gen_recent = (
                sb.table("generations")
                .select("description, asset_type, era, cost_usd, created_at")
                .order("created_at", desc=True)
                .limit(20)
                .execute()
            )
            stats["recent_generations"] = gen_recent.data or []

            # User count
            user_count = sb.table("users").select("id", count="exact").execute()
            stats["user_count"] = user_count.count or 0

            # --- Extended analytics ---

            # Tier breakdown + revenue (MRR) from profiles.
            # We pull tier + subscription_status in one query and derive both
            # the tier distribution and the estimated monthly recurring revenue.
            try:
                tier_data = sb.table("profiles").select("tier, subscription_status").execute()
                tier_counts = {}
                status_counts: dict[str, int] = {}
                revenue_by_tier: dict[str, dict[str, float | int]] = {}
                mrr = 0.0
                for row in (tier_data.data or []):
                    t = row.get("tier") or "free"
                    tier_counts[t] = tier_counts.get(t, 0) + 1

                    st = row.get("subscription_status") or "none"
                    status_counts[st] = status_counts.get(st, 0) + 1

                    price = _TIER_PRICES.get(t, 0)
                    if price and st in _REVENUE_STATUSES:
                        mrr += price
                        bucket = revenue_by_tier.setdefault(
                            t, {"price": price, "count": 0, "mrr": 0.0}
                        )
                        bucket["count"] += 1
                        bucket["mrr"] += price

                stats["tier_breakdown"] = [
                    {"tier": t, "count": c}
                    for t, c in sorted(tier_counts.items(), key=lambda x: -x[1])
                ]
                stats["mrr_usd"] = round(mrr, 2)
                stats["revenue_per_tier"] = [
                    {"tier": t, "price": v["price"], "count": v["count"], "mrr": round(v["mrr"], 2)}
                    for t, v in sorted(
                        revenue_by_tier.items(),
                        key=lambda x: -x[1]["mrr"],
                    )
                ]
                stats["subscription_status_breakdown"] = [
                    {"status": s, "count": c}
                    for s, c in sorted(status_counts.items(), key=lambda x: -x[1])
                ]
            except Exception:
                pass

            # Asset type distribution
            try:
                asset_data = sb.table("generations").select("asset_type").execute()
                asset_counts = {}
                for row in (asset_data.data or []):
                    at = row.get("asset_type") or "unknown"
                    asset_counts[at] = asset_counts.get(at, 0) + 1
                total_gens = sum(asset_counts.values()) or 1
                stats["asset_type_distribution"] = [
                    {"type": t, "count": c, "pct": round(100 * c / total_gens, 1)}
                    for t, c in sorted(asset_counts.items(), key=lambda x: -x[1])
                ]
            except Exception:
                pass

            # Era distribution
            try:
                era_data = sb.table("generations").select("era").execute()
                era_counts = {}
                for row in (era_data.data or []):
                    e = row.get("era") or "unknown"
                    era_counts[e] = era_counts.get(e, 0) + 1
                total_gens = sum(era_counts.values()) or 1
                stats["era_distribution"] = [
                    {"era": e, "count": c, "pct": round(100 * c / total_gens, 1)}
                    for e, c in sorted(era_counts.items(), key=lambda x: -x[1])
                ]
            except Exception:
                pass

            # Feature usage rates
            try:
                feat_data = sb.table("generations").select(
                    "had_reference_image, palette_colors, asset_type"
                ).execute()
                rows = feat_data.data or []
                total = len(rows) or 1
                with_ref = sum(1 for r in rows if r.get("had_reference_image"))
                with_palette = sum(1 for r in rows if r.get("palette_colors"))
                spritesheets = sum(1 for r in rows if r.get("asset_type") == "spritesheet")
                stats["feature_usage"] = {
                    "total": total,
                    "reference_upload_pct": round(100 * with_ref / total, 1),
                    "palette_lock_pct": round(100 * with_palette / total, 1),
                    "spritesheet_pct": round(100 * spritesheets / total, 1),
                }
            except Exception:
                pass

            # Daily trend (last 14 days) — use generation timestamps
            try:
                fourteen_days_ago = (now_utc - timedelta(days=14)).isoformat()
                trend_data = (
                    sb.table("generations")
                    .select("created_at")
                    .gte("created_at", fourteen_days_ago)
                    .execute()
                )
                day_counts = {}
                for row in (trend_data.data or []):
                    day = row["created_at"][:10]  # "YYYY-MM-DD"
                    day_counts[day] = day_counts.get(day, 0) + 1
                stats["daily_trend"] = [
                    {"day": d, "count": c}
                    for d, c in sorted(day_counts.items())
                ]
            except Exception:
                pass

            # Active users (DAU/WAU from events table)
            try:
                today_events = (
                    sb.table("events")
                    .select("session_id")
                    .gte("created_at", today_start)
                    .execute()
                )
                dau_sessions = set(r["session_id"] for r in (today_events.data or []))

                week_events = (
                    sb.table("events")
                    .select("session_id")
                    .gte("created_at", week_start)
                    .execute()
                )
                wau_sessions = set(r["session_id"] for r in (week_events.data or []))

                stats["active_users"] = {
                    "dau": len(dau_sessions),
                    "wau": len(wau_sessions),
                }
            except Exception:
                pass

            # Margin by tier and month
            try:
                margin_gen_data = (
                    sb.table("generations")
                    .select("created_at, model_path, user_id, cost_usd")
                    .execute()
                )
                gen_rows = margin_gen_data.data or []

                profile_data = sb.table("profiles").select("id, tier").execute()
                tier_by_user = {
                    str(row["id"]): (row.get("tier") or "free").lower()
                    for row in (profile_data.data or [])
                }

                active_subs = (
                    sb.table("profiles")
                    .select("tier")
                    .eq("subscription_status", "active")
                    .execute()
                )
                subscriber_counts: dict[str, int] = {}
                for row in (active_subs.data or []):
                    tier = (row.get("tier") or "free").lower()
                    subscriber_counts[tier] = subscriber_counts.get(tier, 0) + 1

                enriched_rows = [
                    {
                        "created_at": row["created_at"],
                        "model_path": row.get("model_path"),
                        "cost_usd": row.get("cost_usd"),
                        "tier": tier_by_user.get(str(row["user_id"]), "free"),
                    }
                    for row in gen_rows
                ]

                rows, free_burn = aggregate_margin_by_tier_month(
                    enriched_rows, subscriber_counts
                )
                stats["margin_by_tier_month"] = rows
                stats["free_tier_burn_this_month_usd"] = free_burn
            except Exception:
                pass

        except Exception as exc:
            logger.warning("Admin stats query failed: %s", exc)

    return stats


# ---------------------------------------------------------------------------
# Admin: feedback triage
# ---------------------------------------------------------------------------

_VALID_FEEDBACK_STATUSES = frozenset({"new", "read", "resolved"})


class FeedbackTriageRequest(BaseModel):
    status: str = Field(..., max_length=20)

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in _VALID_FEEDBACK_STATUSES:
            raise ValueError("status must be new, read, or resolved")
        return v


@app.get("/admin/api/feedback", include_in_schema=False)
@limiter.limit("10/minute")
async def admin_feedback(
    request: Request,
    status: str | None = None,
    limit: int = 100,
):
    """List submitted feedback for triage. Requires admin password."""
    _check_admin(request)

    if not _db_enabled():
        return {"items": [], "total": 0, "filtered": 0}

    from .supabase_client import get_supabase_client

    sb = get_supabase_client()
    try:
        query = (
            sb.table("feedback")
            .select("id, created_at, user_id, message, category, context, status, resolved_at")
            .order("created_at", desc=True)
        )
        if status:
            query = query.eq("status", status)
        res = query.limit(min(max(limit, 1), 500)).execute()

        count_query = sb.table("feedback").select("id", count="exact")
        if status:
            count_query = count_query.eq("status", status)
        total = count_query.execute().count or 0

        return {
            "items": res.data or [],
            "total": total,
            "filtered": len(res.data or []),
        }
    except Exception as exc:
        logger.warning("Admin feedback query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to load feedback.") from exc


@app.patch("/admin/api/feedback/{feedback_id}", include_in_schema=False)
@limiter.limit("20/minute")
async def admin_triage_feedback(
    request: Request,
    feedback_id: str,
    body: FeedbackTriageRequest,
):
    """Update the triage status of a feedback entry. Requires admin password."""
    _check_admin(request)

    if not _db_enabled():
        return {"ok": True, "entry": None}

    from datetime import datetime, timezone

    from .supabase_client import get_supabase_client

    update: dict[str, object] = {"status": body.status}
    if body.status == "resolved":
        update["resolved_at"] = datetime.now(timezone.utc).isoformat()
    else:
        # new / read → clear any prior resolution timestamp
        update["resolved_at"] = None

    sb = get_supabase_client()
    try:
        res = (
            sb.table("feedback")
            .update(update)
            .eq("id", feedback_id)
            .execute()
        )
        rows = res.data or []
        if not rows:
            raise HTTPException(status_code=404, detail="Feedback not found.")
        return {"ok": True, "entry": rows[0]}
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Feedback triage update failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to update feedback.") from exc


# ---------------------------------------------------------------------------
# Admin: email suppression list (bounce/complaint) + un-suppress path
# ---------------------------------------------------------------------------

class SuppressionRemoveRequest(BaseModel):
    email: str = Field(..., min_length=3, max_length=320)


@app.get("/admin/api/suppressions", include_in_schema=False)
@limiter.limit("10/minute")
async def admin_list_suppressions(request: Request, limit: int = 200):
    """List suppressed email addresses (bounces/complaints). Requires admin password."""
    _check_admin(request)
    from .suppression import list_suppressions
    items = list_suppressions(limit)
    return {"items": items, "total": len(items)}


@app.post("/admin/api/suppressions/remove", include_in_schema=False)
@limiter.limit("20/minute")
async def admin_remove_suppression(request: Request, body: SuppressionRemoveRequest):
    """Un-suppress an email address — remove it from the suppression list so
    Retrogaze will send to it again. Requires admin password."""
    _check_admin(request)
    from .suppression import remove_suppression
    removed = remove_suppression(body.email)
    return {"ok": True, "removed": removed, "email": body.email}


# ---------------------------------------------------------------------------
# Admin: conversion-funnel counts
# ---------------------------------------------------------------------------

@app.get("/admin/api/funnel", include_in_schema=False)
@limiter.limit("10/minute")
async def admin_funnel(request: Request, days: int | None = None):
    """Return conversion-funnel counts per event type, optionally windowed to
    the last ``days`` days (e.g. ?days=30). Requires RETROGAZE_ADMIN_PASSWORD.

    The counts trace signup → first_generation → usage_meter_90_shown →
    upgrade_click → checkout_complete, so drop-off between the upgrade nudges is
    measurable.
    """
    _check_admin(request)
    from .funnel import funnel_counts
    counts = funnel_counts(days)
    return {"counts": counts, "days": days, "total": sum(counts.values())}


# ---------------------------------------------------------------------------
# API versioning — validate the allowlist (import-time, fail-loud)
# ---------------------------------------------------------------------------
# Runs last, after every route above (and the /mcp router mount) exists, so each
# allowlist entry can be checked against a real registered route. Any violation
# raises here, which means the app REFUSES TO START rather than shipping a bad
# alias. The /v1 request path itself is served by V1PathRewriteMiddleware, not
# by duplicate route objects — see that middleware for why.


def _validate_v1_allowlist() -> list[str]:
    """Validate ``_V1_ALLOWLIST`` and return the /v1 paths it exposes.

    Raises at import (app refuses to start) if an entry names a forbidden
    surface, duplicates another entry, or names a route that does not exist.
    """
    from fastapi.routing import APIRoute

    # (METHOD, full path) -> route. Top-level routes, then each mounted router's
    # routes at its mount prefix (FastAPI >= 0.139 does not flatten included
    # routers into app.routes). This is a LOOKUP TABLE ONLY — it is never
    # iterated to decide what gets aliased; _V1_ALLOWLIST is the only source.
    existing: set[tuple[str, str]] = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        for method in route.methods or ():
            existing.add((method.upper(), route.path))
    for mount_prefix, mounted in _MOUNTED_ROUTERS:
        for route in mounted.routes:
            if not isinstance(route, APIRoute):
                continue
            for method in route.methods or ():
                existing.add((method.upper(), mount_prefix + route.path))

    exposed: list[str] = []
    seen: set[tuple[str, str]] = set()

    for method, path in _V1_ALLOWLIST:
        method = method.upper()

        # Guard 1 — never expose a money/credential/privileged surface.
        for forbidden in _V1_FORBIDDEN_PREFIXES:
            if path == forbidden or path.startswith(forbidden + "/"):
                raise RuntimeError(
                    f"/v1 allowlist violation: {method} {path} matches the "
                    f"forbidden prefix {forbidden!r}. Billing, webhook, auth, "
                    f"account, admin and API-key surfaces must never be "
                    f"reachable at a second URL."
                )

        # Guard 2 — no duplicate entries.
        if (method, path) in seen:
            raise RuntimeError(f"/v1 allowlist duplicate entry: {method} {path}")
        seen.add((method, path))

        # Guard 3 — the entry must name a route that actually exists, so a
        # renamed or deleted endpoint can't leave a /v1 URL rewriting to a 404.
        if (method, path) not in existing:
            raise RuntimeError(
                f"/v1 allowlist entry {method} {path} does not match any "
                f"registered route. Fix the allowlist in api.py."
            )

        exposed.append(_V1_PREFIX + path)

    return exposed


# V1PathRewriteMiddleware reads V1_ALLOWED_PAIRS at request time. Both names are
# bound HERE, after the guards have run — if any guard raises, neither is ever
# bound, the module fails to import, and the app cannot start. There is no code
# path in which the middleware serves a pair that was not validated.
V1_ALIAS_PATHS: list[str] = _validate_v1_allowlist()
V1_ALLOWED_PAIRS: frozenset[tuple[str, str]] = frozenset(
    (m.upper(), p) for m, p in _V1_ALLOWLIST
)

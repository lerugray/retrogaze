"""
API key authentication for Retrogaze MCP Server Product.

MCP endpoints use license keys (rg_live_...) instead of JWTs.
Keys are stored as SHA-256 hashes in the existing api_keys table.
"""

from __future__ import annotations

import hashlib
import logging
import os
from dataclasses import dataclass

from fastapi import HTTPException, Request

from .supabase_client import get_supabase_client, supabase_configured  # noqa: F401  (supabase_configured kept importable for test monkeypatch target)

logger = logging.getLogger("retrogaze.mcp_auth")


@dataclass
class McpAuthenticatedUser:
    """Authenticated MCP user resolved from an API key."""
    user_id: str
    key_id: str
    tier: str           # free, starter, pro, studio
    monthly_used: int
    monthly_limit: int | None  # None = unlimited


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw API key, matching the storage format."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


_ANON_USER_ID = "00000000-0000-0000-0000-000000000001"


def _anonymous_user() -> McpAuthenticatedUser:
    """Synthetic free-tier user for callers without a license key.

    Anonymous callers get the free-tier era set (retro + early) and
    no auto-fix. Per-minute slowapi limits still apply per IP so
    anonymous traffic can't overwhelm the service.
    """
    return McpAuthenticatedUser(
        user_id=_ANON_USER_ID,
        key_id="anonymous",
        tier="free",
        monthly_used=0,
        monthly_limit=None,
    )


async def get_mcp_user(request: Request) -> McpAuthenticatedUser:
    """
    FastAPI dependency for MCP endpoints — authenticates via API key.

    Extracts ``Authorization: Bearer rg_live_...`` from the request,
    looks up the key hash in api_keys, joins to profiles for tier,
    and bumps last_used_at / monthly_used.

    In mock mode, returns a fake free-tier user for local testing.
    """
    # Mock mode for local dev. Gate ONLY on RETROGAZE_MOCK=1 — mirroring
    # auth.py's fail-closed pattern. Previously this also short-circuited on
    # `not supabase_configured()`, which meant a production deploy that lost
    # its Supabase env would silently hand EVERY caller a full-access studio
    # tier (the MCP analogue of the auth.py god-user bug). The startup guard
    # in api.py refuses to boot with RETROGAZE_MOCK=1 on Railway, so the mock
    # flag can only be set in genuine dev. No config + no mock flag → fall
    # through to real key validation (which fails closed if Supabase is down).
    if os.environ.get("RETROGAZE_MOCK", "").strip() == "1":
        return McpAuthenticatedUser(
            user_id="00000000-0000-0000-0000-000000000000",
            key_id="00000000-0000-0000-0000-000000000000",
            tier="studio",  # full access in dev
            monthly_used=0,
            monthly_limit=None,
        )

    # Extract Bearer token
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing API key. Set Authorization: Bearer rg_live_...")

    raw_key = auth[7:].strip()
    if not raw_key.startswith("rg_live_"):
        raise HTTPException(status_code=401, detail="Invalid API key format. Keys start with rg_live_")

    key_hash = _hash_key(raw_key)

    try:
        sb = get_supabase_client()

        # Look up active key by hash
        key_result = (
            sb.table("api_keys")
            .select("id, user_id, monthly_limit, monthly_used")
            .eq("key_hash", key_hash)
            .is_("revoked_at", "null")
            .execute()
        )

        if not key_result.data:
            raise HTTPException(status_code=401, detail="Invalid or revoked API key.")

        key_row = key_result.data[0]

        monthly_limit = key_row.get("monthly_limit")
        monthly_used = key_row.get("monthly_used", 0)

        # Atomic check-and-increment. The increment is done in the database as
        # `SET monthly_used = monthly_used + 1` (increment_api_key_usage,
        # migration 007) so it reads the column's live committed value and the
        # cap check happens in the same statement. A Python-side read-then-write
        # (read monthly_used, write monthly_used + 1) loses increments under
        # concurrency and lets a key slip past its monthly cap.
        new_monthly_used = monthly_used + 1
        try:
            consume = sb.rpc(
                "increment_api_key_usage", {"p_key_id": key_row["id"]}
            ).execute()
            cdata = consume.data
            if isinstance(cdata, list):
                cdata = cdata[0] if cdata else {}
            cdata = cdata or {}
            if not cdata.get("allowed", False):
                if cdata.get("reason") == "limit_reached":
                    raise HTTPException(
                        status_code=429,
                        detail=(
                            f"Monthly API limit reached "
                            f"({cdata.get('monthly_used', monthly_used)}/"
                            f"{cdata.get('monthly_limit', monthly_limit)}). "
                            "Resets on the 1st."
                        ),
                    )
                # Key was revoked/removed between the hash lookup and the increment.
                raise HTTPException(status_code=401, detail="Invalid or revoked API key.")
            new_monthly_used = cdata.get("monthly_used", monthly_used + 1)
        except HTTPException:
            raise
        except Exception as exc:
            # RPC unavailable (e.g. code deployed before migration 007) or a
            # transient error — fall back to the guarded UPDATE so MCP auth keeps
            # working. Still limit-checked; just not concurrency-atomic. Remove
            # this fallback once migration 007 is confirmed applied in prod.
            logger.warning(
                "increment_api_key_usage RPC unavailable, using guarded fallback: %s",
                exc,
            )
            try:
                if monthly_limit is not None:
                    update_result = (
                        sb.table("api_keys")
                        .update({"monthly_used": monthly_used + 1, "last_used_at": "now()"})
                        .eq("id", key_row["id"])
                        .lt("monthly_used", monthly_limit)
                        .execute()
                    )
                    if not update_result.data:
                        raise HTTPException(
                            status_code=429,
                            detail=f"Monthly API limit reached ({monthly_used}/{monthly_limit}). Resets on the 1st.",
                        )
                else:
                    sb.table("api_keys").update({
                        "monthly_used": monthly_used + 1,
                        "last_used_at": "now()",
                    }).eq("id", key_row["id"]).execute()
            except HTTPException:
                raise
            except Exception as exc2:
                logger.warning("Failed to update key usage (fallback): %s", exc2)

        # Get user's tier from profiles
        profile_result = (
            sb.table("profiles")
            .select("tier")
            .eq("id", key_row["user_id"])
            .execute()
        )

        tier = "free"
        if profile_result.data:
            tier = profile_result.data[0].get("tier", "free")

        return McpAuthenticatedUser(
            user_id=key_row["user_id"],
            key_id=key_row["id"],
            tier=tier,
            monthly_used=new_monthly_used,
            monthly_limit=monthly_limit,
        )

    except HTTPException:
        raise
    except Exception as exc:
        logger.error("MCP auth error: %s", exc)
        raise HTTPException(status_code=500, detail="Authentication service unavailable.") from exc


async def get_optional_mcp_user(request: Request) -> McpAuthenticatedUser:
    """
    FastAPI dependency for MCP endpoints that allow anonymous use.

    Behaves like ``get_mcp_user`` when an ``Authorization: Bearer rg_live_...``
    header is present (license-key-authenticated user, full tier resolution).
    When no Authorization header is present, returns a synthetic anonymous
    free-tier user — callers get retro + early eras and no auto-fix, with
    slowapi handling per-IP rate limiting to keep anonymous traffic bounded.

    This is the entry point that lets MCP clients running on the user's
    own Claude subscription (Claude Desktop, Claude Code, Cursor, VS Code
    Copilot) use Retrogaze without a separate license key — they just
    don't unlock the paid tiers.

    Mock-mode short-circuit: when ``RETROGAZE_MOCK=1`` is set, defers to
    ``get_mcp_user`` so the test studio-tier user is returned regardless of
    headers. This preserves the existing test fixtures. Gating ONLY on the
    mock flag (not on ``not supabase_configured()``) mirrors auth.py's
    fail-closed pattern: a production deploy that loses its Supabase env must
    NOT silently grant studio tier — it falls through to real validation.
    """
    if os.environ.get("RETROGAZE_MOCK", "").strip() == "1":
        return await get_mcp_user(request)

    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        return _anonymous_user()
    return await get_mcp_user(request)

"""
API key generation and management for Retrogaze MCP Server Product.

Keys use the existing api_keys table. Format: rg_live_<random>.
The full key is shown once on creation; only the SHA-256 hash is stored.
"""

from __future__ import annotations

import hashlib
import logging
import secrets

from .supabase_client import get_user_client

logger = logging.getLogger("retrogaze.mcp_keys")

# Monthly call limits per tier for MCP API endpoints
_MCP_TIER_LIMITS: dict[str, int | None] = {
    "free": 300,       # ~10/day
    "starter": 1000,
    "pro": 3000,
    "studio": None,    # unlimited
}


def _generate_raw_key() -> str:
    """Generate a raw API key: rg_live_ + 32 bytes of URL-safe randomness."""
    return f"rg_live_{secrets.token_urlsafe(32)}"


def _hash_key(raw_key: str) -> str:
    """SHA-256 hash of the raw key."""
    return hashlib.sha256(raw_key.encode()).hexdigest()


async def generate_api_key(
    user_id: str,
    name: str = "Default",
    tier: str = "free",
) -> tuple[str, str]:
    """
    Create a new API key for a user.

    Returns (full_key, key_id). The full key is only available at creation
    time — store it immediately.
    """
    raw_key = _generate_raw_key()
    key_hash = _hash_key(raw_key)
    key_prefix = raw_key[:20] + "..."  # rg_live_XXXXXXXX...

    monthly_limit = _MCP_TIER_LIMITS.get(tier, 300)

    sb = get_user_client(user_id)
    result = (
        sb.table("api_keys")
        .insert({
            "user_id": user_id,
            "key_prefix": key_prefix,
            "key_hash": key_hash,
            "name": name,
            "monthly_limit": monthly_limit,
            "monthly_used": 0,
        })
        .execute()
    )

    key_id = result.data[0]["id"]
    logger.info("Created API key %s for user %s (tier: %s)", key_prefix, user_id, tier)
    return raw_key, key_id


async def revoke_api_key(key_id: str, user_id: str) -> bool:
    """
    Revoke an API key by setting revoked_at.

    Returns True if the key was found and revoked, False if not found
    or already revoked.
    """
    sb = get_user_client(user_id)
    result = (
        sb.table("api_keys")
        .update({"revoked_at": "now()"})
        .eq("id", key_id)
        .is_("revoked_at", "null")
        .execute()
    )
    revoked = bool(result.data)
    if revoked:
        logger.info("Revoked API key %s for user %s", key_id, user_id)
    return revoked


async def list_user_keys(user_id: str) -> list[dict]:
    """
    List all API keys for a user (active and revoked).

    Returns dicts with: id, key_prefix, name, monthly_limit, monthly_used,
    last_used_at, revoked_at, created_at. Never includes the full key or hash.
    """
    sb = get_user_client(user_id)
    result = (
        sb.table("api_keys")
        .select("id, key_prefix, name, monthly_limit, monthly_used, last_used_at, revoked_at, created_at")
        .order("created_at", desc=True)
        .execute()
    )
    return result.data or []

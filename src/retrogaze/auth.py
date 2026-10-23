"""
Authentication dependencies for Retrogaze FastAPI endpoints.

Uses Supabase Auth to validate JWTs from the Authorization header.
When Supabase isn't configured (local dev / RETROGAZE_MOCK=1), auth
is skipped and endpoints work without a token.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

logger = logging.getLogger("retrogaze.auth")

from fastapi import Depends, HTTPException, Request

from .supabase_client import get_supabase_client


@dataclass
class AuthenticatedUser:
    """Authenticated user context attached to a request."""
    id: str          # Supabase user UUID
    email: str | None = None
    is_anonymous: bool = False


def _extract_token(request: Request) -> str | None:
    """Pull the Bearer token from the Authorization header."""
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        return auth[7:].strip()
    return None


async def get_current_user(request: Request) -> AuthenticatedUser:
    """
    Required auth dependency — returns the authenticated user or raises 401.

    In local-dev mode (RETROGAZE_MOCK=1 or no Supabase config), returns a
    fake user so endpoints are testable without a real Supabase instance.
    """
    # Skip auth ONLY when explicitly opted into mock mode. Gating this on
    # `not supabase_configured()` previously meant a production deploy that
    # lost its Supabase env would silently grant EVERY request a full-access
    # god-user. Fail closed instead: no config + no mock flag → 401 below.
    if os.environ.get("RETROGAZE_MOCK", "").strip() == "1":
        return AuthenticatedUser(
            id="00000000-0000-0000-0000-000000000000",
            email="local@dev",
            is_anonymous=False,
        )

    token = _extract_token(request)
    if not token:
        raise HTTPException(status_code=401, detail="Missing Authorization header.")

    try:
        supabase = get_supabase_client()
        user_response = supabase.auth.get_user(token)
        user = user_response.user
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid token.")
        return AuthenticatedUser(
            id=str(user.id),
            email=user.email,
            is_anonymous=user.is_anonymous if hasattr(user, "is_anonymous") else False,
        )
    except HTTPException:
        raise
    except Exception as exc:
        logger.warning("Auth failed: %s", exc)
        raise HTTPException(status_code=401, detail="Authentication failed.") from exc


async def get_optional_user(request: Request) -> AuthenticatedUser | None:
    """
    Optional auth dependency — returns the user if a valid token is present,
    or None if no token was provided. Still raises 401 for *invalid* tokens.
    """
    # Mock mode only (mirrors get_current_user). Don't fall through to anon
    # just because config is missing in a real deploy — go validate the token.
    if os.environ.get("RETROGAZE_MOCK", "").strip() == "1":
        return None

    token = _extract_token(request)
    if not token:
        return None

    # Token was provided — it must be valid
    return await get_current_user(request)

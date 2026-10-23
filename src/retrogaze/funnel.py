"""
Conversion-funnel event instrumentation for Retrogaze.

Records the five discrete conversion-funnel milestones into
``public.funnel_events`` (migration 011) so drop-off between the shipped
upgrade nudges is measurable:

    signup                → a signup was confirmed (once per user)
    first_generation      → a user's first successful generation (once per user)
    usage_meter_90_shown  → the >=90% usage-meter upgrade nudge was shown
    upgrade_click         → an upgrade affordance was clicked
    checkout_complete     → a LemonSqueezy subscription_created webhook landed

This is distinct from the general ``public.events`` table (migration 003):
that is a high-volume, anon-insertable analytics stream; this is a low-volume,
SERVER-AUTHORITATIVE funnel ledger. Every write goes through the service-role
client — the client-originated events (meter-shown, upgrade-click) arrive via
the session-authed ``/funnel-events`` endpoint, which inserts on the server.

``signup`` and ``first_generation`` are semantically once-per-user; the DB
enforces that with a partial UNIQUE index, and ``emit_funnel_event`` surfaces
the unique violation as "already recorded" (returning ``False``) so callers can
gate one-shot side effects (e.g. the welcome email) on the first occurrence.

All emits are best-effort: a failure to record a funnel event never breaks the
user-facing flow it is instrumenting.
"""

from __future__ import annotations

import logging

logger = logging.getLogger("retrogaze.funnel")

# The full set of funnel event types (the DB does not constrain event_type, so
# this is the application-level allowlist / documentation of what we emit).
FUNNEL_EVENT_TYPES: frozenset[str] = frozenset({
    "signup",
    "first_generation",
    "usage_meter_90_shown",
    "upgrade_click",
    "checkout_complete",
})

# Events that are semantically once-per-user. Backed by the partial UNIQUE
# index ``funnel_events_once_per_user`` in migration 011.
ONCE_PER_USER: frozenset[str] = frozenset({"signup", "first_generation"})

# The subset a browser client is permitted to POST to /funnel-events. The
# server-emitted milestones (signup / first_generation / checkout_complete) are
# NOT in here, so a client can never spoof them.
CLIENT_EMITTABLE: frozenset[str] = frozenset({"usage_meter_90_shown", "upgrade_click"})


def _is_duplicate_error(exc: Exception) -> bool:
    """True if the exception looks like a unique-constraint violation."""
    msg = str(exc).lower()
    return (
        "duplicate" in msg
        or "unique" in msg
        or "23505" in msg  # postgres unique_violation SQLSTATE
        or "already exists" in msg
    )


def emit_funnel_event(
    user_id: str | None,
    event_type: str,
    metadata: dict | None = None,
) -> bool:
    """Record a funnel event via the service-role Supabase client.

    Best-effort: any failure is logged and swallowed (funnel instrumentation
    must never break the flow it measures).

    Returns ``True`` when a row was newly recorded, ``False`` when the event was
    a once-per-user milestone that already existed for this user (or when the
    write could not be attempted). Callers gating a one-shot side effect on the
    FIRST occurrence (e.g. the welcome email) should check this return value.
    """
    if event_type not in FUNNEL_EVENT_TYPES:
        logger.warning("emit_funnel_event: unknown event_type %r — skipped", event_type)
        return False

    # No user context and not something we can attribute → nothing to record.
    if not user_id:
        return False

    # Only attempt a write when the DB is actually configured (mirrors the
    # _db_enabled() gate the callers use; kept here so direct callers are safe).
    from .supabase_client import supabase_configured
    import os

    if os.environ.get("RETROGAZE_MOCK", "").strip() == "1" or not supabase_configured():
        return False

    try:
        from .supabase_client import get_supabase_client

        sb = get_supabase_client()
        sb.table("funnel_events").insert({
            "user_id": user_id,
            "event_type": event_type,
            "metadata": metadata or {},
        }).execute()
        return True
    except Exception as exc:
        # A unique violation on a once-per-user event is the expected "already
        # recorded" path — not an error. Everything else is logged.
        if event_type in ONCE_PER_USER and _is_duplicate_error(exc):
            return False
        logger.warning("Failed to record funnel event %s: %s", event_type, exc)
        return False


def funnel_counts(days: int | None = None) -> dict[str, int]:
    """Return a mapping of funnel event_type → count, optionally windowed to the
    last ``days`` days. Service-role read; used by the admin endpoint.

    Returns an all-zero map for every known event type when the DB is
    unavailable or the query fails, so the admin view degrades gracefully.
    """
    counts: dict[str, int] = {et: 0 for et in sorted(FUNNEL_EVENT_TYPES)}

    from .supabase_client import supabase_configured
    import os

    if os.environ.get("RETROGAZE_MOCK", "").strip() == "1" or not supabase_configured():
        return counts

    try:
        from .supabase_client import get_supabase_client

        sb = get_supabase_client()
        q = sb.table("funnel_events").select("event_type")
        if days is not None and days > 0:
            from datetime import datetime, timedelta, timezone
            since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
            q = q.gte("created_at", since)
        rows = q.execute().data or []
        for row in rows:
            et = row.get("event_type")
            if et in counts:
                counts[et] += 1
            elif et:
                counts[et] = counts.get(et, 0) + 1
    except Exception as exc:
        logger.warning("funnel_counts query failed: %s", exc)

    return counts

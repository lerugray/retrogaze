"""
Transactional-email suppression list + ESP bounce/complaint webhook handling.

Retrogaze sends auth emails (signup confirmation, password reset) and billing
dunning notices through a transactional ESP — Resend or Postmark (see
email.py). This module handles the *return path*: bounce and spam-complaint
webhooks from those ESPs, and the suppression list they populate. The send
path in email.py consults ``is_suppressed`` before every send.

Provider verification — FAIL CLOSED (an unverifiable webhook is rejected, no
processing):

  * Resend signs webhooks via Svix. Headers ``svix-id`` / ``svix-timestamp`` /
    ``svix-signature``; the signed content is ``f"{id}.{timestamp}.{body}"``,
    HMAC-SHA256 keyed on the base64-decoded portion of the ``whsec_`` secret,
    base64-encoded; the ``svix-signature`` header carries space-delimited
    ``v1,<sig>`` entries (any one matching is valid). Secret env:
    ``RESEND_WEBHOOK_SECRET``.
      https://resend.com/docs/dashboard/webhooks/verify-webhooks-requests
      https://docs.svix.com/receiving/verifying-payloads/how-manual

  * Postmark does NOT sign webhooks. Postmark's documented recommendation is
    HTTP Basic Auth on the webhook URL (over HTTPS/TLS) plus IP allowlisting.
    We verify Basic Auth against ``POSTMARK_WEBHOOK_USERNAME`` /
    ``POSTMARK_WEBHOOK_PASSWORD``.
      https://postmarkapp.com/developer/webhooks/webhooks-overview
      https://postmarkapp.com/developer/webhooks/bounce-webhook

Soft vs hard — NEVER suppress on a transient failure:

  * HARD bounce or spam complaint  -> suppress (permanent).
  * SOFT / transient bounce         -> counted only (email_soft_bounces),
    promoted to a suppression only after SOFT_BOUNCE_SUPPRESS_THRESHOLD
    transient bounces for the same address (generous, documented below).

  Resend classification: ``data.bounce.type == "Permanent"`` is hard;
  ``"Transient"`` / ``"Undetermined"`` are soft. ``email.complained`` is
  always a complaint (hard).
  Postmark classification: by ``TypeCode`` — HardBounce / SpamComplaint /
  SpamNotification / BadEmailAddress / ManuallyDeactivated / Blocked /
  DMARCPolicy are hard; Transient / SoftBounce / DnsError are soft. Any other
  type is logged only (never suppressed) — conservative for auth email.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os
from datetime import datetime, timezone
from typing import Any, Mapping

from .supabase_client import get_supabase_client, supabase_configured

logger = logging.getLogger("retrogaze.suppression")

# Repeated transient/soft bounces are counted, not suppressed, until this many
# accumulate for one address — deliberately GENEROUS so a run of temporary
# mailbox-full / network / DNS failures never permanently blocks a real user's
# auth email. Only at/above this count is the address promoted to a suppression
# (reason=repeated_soft_bounce). Removing the address (un-suppress) clears the
# counter too, so it starts clean.
SOFT_BOUNCE_SUPPRESS_THRESHOLD = 8

# Postmark bounce TypeCodes that are permanent -> suppress.
# (Reference: Postmark bounce-api. https://postmarkapp.com/developer/api/bounce-api)
_POSTMARK_HARD_TYPE_CODES = frozenset({
    1,       # HardBounce         — permanent delivery failure (unknown user, no mailbox)
    512,     # SpamNotification   — blocked / classified as spam
    100000,  # BadEmailAddress    — not a valid email address
    100001,  # SpamComplaint      — recipient marked as spam
    100002,  # ManuallyDeactivated
    100006,  # Blocked            — ISP block / blacklist
    100009,  # DMARCPolicy        — rejected due to DMARC policy
})
# Postmark TypeCodes that are transient -> count only (email_soft_bounces).
_POSTMARK_SOFT_TYPE_CODES = frozenset({
    2,       # Transient — temporary failure (network trouble, delayed)
    256,     # DnsError  — temporary DNS error
    4096,    # SoftBounce — mailbox full / account disabled / over quota
})


def _env(name: str) -> str | None:
    """Return a stripped env var, or None if unset/empty."""
    return os.environ.get(name, "").strip() or None


def _normalize(email: str | None) -> str:
    """Lowercase + strip an address for consistent keying."""
    return (email or "").strip().lower()


# ---------------------------------------------------------------------------
# Webhook signature / auth verification (fail closed)
# ---------------------------------------------------------------------------

def verify_resend_signature(body: bytes, headers: Mapping[str, str]) -> bool:
    """Verify a Resend (Svix) webhook signature. Returns False on any problem
    (missing secret, missing headers, malformed secret, mismatch) so the
    endpoint can reject with 401. ``headers`` is any case-insensitive mapping
    with ``.get`` (e.g. Starlette request.headers)."""
    secret = _env("RESEND_WEBHOOK_SECRET")
    if not secret:
        logger.error("RESEND_WEBHOOK_SECRET not set — rejecting Resend webhook")
        return False

    svix_id = headers.get("svix-id")
    svix_ts = headers.get("svix-timestamp")
    svix_sig = headers.get("svix-signature")
    if not (svix_id and svix_ts and svix_sig):
        logger.error("Resend webhook missing svix-* headers — rejecting")
        return False

    # whsec_<base64>. The base64 portion (after the underscore) is the HMAC key.
    raw = secret.split("_", 1)[1] if secret.startswith("whsec_") else secret
    try:
        key = base64.b64decode(raw)
    except Exception:
        logger.error("RESEND_WEBHOOK_SECRET is not a valid whsec_ secret — rejecting")
        return False

    signed = svix_id.encode() + b"." + svix_ts.encode() + b"." + body
    expected = base64.b64encode(
        hmac.new(key, signed, hashlib.sha256).digest()
    ).decode()

    # The header is space-delimited "v1,<sig> v1,<sig>"; any matching entry wins.
    for part in svix_sig.split():
        _version, _, candidate = part.partition(",")
        if candidate and hmac.compare_digest(candidate, expected):
            return True

    logger.error("Resend webhook signature mismatch — rejecting")
    return False


def verify_postmark_basic_auth(auth_header: str) -> bool:
    """Verify a Postmark webhook via HTTP Basic Auth. Postmark does not sign
    webhooks; its documented guidance is Basic Auth (+ IP allowlisting). Returns
    False on any problem (creds unconfigured, missing/malformed header,
    mismatch) so the endpoint can reject with 401."""
    user = _env("POSTMARK_WEBHOOK_USERNAME")
    pw = _env("POSTMARK_WEBHOOK_PASSWORD")
    if not (user and pw):
        logger.error(
            "POSTMARK_WEBHOOK_USERNAME/PASSWORD not set — rejecting Postmark webhook"
        )
        return False
    if not auth_header or not auth_header.startswith("Basic "):
        logger.error("Postmark webhook missing Basic auth — rejecting")
        return False
    try:
        decoded = base64.b64decode(auth_header[6:]).decode("utf-8", "replace")
    except Exception:
        return False
    got_user, _, got_pw = decoded.partition(":")
    # Constant-time compare on both halves.
    ok_user = hmac.compare_digest(got_user, user)
    ok_pw = hmac.compare_digest(got_pw, pw)
    return ok_user and ok_pw


# ---------------------------------------------------------------------------
# Idempotency keys (reuse payments.processed_webhooks via the API layer)
# ---------------------------------------------------------------------------

def resend_event_id(headers: Mapping[str, str]) -> str:
    """Per-delivery idempotency key for a Resend webhook (Svix message id)."""
    return "resend:" + (headers.get("svix-id") or "")


def postmark_event_id(payload: dict) -> str:
    """Stable idempotency key for a Postmark webhook delivery. Postmark sends no
    per-delivery id header, so derive one from RecordType + resource id + email."""
    key = ":".join(
        str(payload.get(k, "")) for k in ("RecordType", "ID", "MessageID", "Email")
    )
    return "postmark:" + hashlib.sha256(key.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Suppression storage (service-role; never touched by the public key)
# ---------------------------------------------------------------------------

def is_suppressed(email: str) -> bool:
    """Return True if ``email`` is on the suppression list.

    Fails OPEN (returns False) when Supabase is unconfigured or the lookup
    errors: auth-email deliverability is prioritised over a rare DB blip, and a
    genuinely bad address that slips through is re-caught by the next
    bounce/complaint webhook (suppression is idempotent). Called from the send
    path in email.py.
    """
    e = _normalize(email)
    if not e or not supabase_configured():
        return False
    try:
        sb = get_supabase_client()
        resp = (
            sb.table("email_suppressions")
            .select("email")
            .eq("email", e)
            .limit(1)
            .execute()
        )
        return bool(getattr(resp, "data", None))
    except Exception as exc:
        logger.warning("is_suppressed check failed for %s: %s — allowing send", e, exc)
        return False


def add_suppression(
    email: str,
    reason: str,
    provider: str | None = None,
    detail: str | None = None,
) -> None:
    """Upsert an address onto the suppression list (permanent). Best-effort."""
    e = _normalize(email)
    if not e or not supabase_configured():
        return
    try:
        sb = get_supabase_client()
        sb.table("email_suppressions").upsert(
            {
                "email": e,
                "reason": reason,
                "provider": provider,
                "detail": detail,
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="email",
        ).execute()
        logger.info("Suppressed %s (reason=%s provider=%s)", e, reason, provider)
    except Exception as exc:
        logger.warning("add_suppression failed for %s: %s", e, exc)


def remove_suppression(email: str) -> bool:
    """Remove an address from the suppression list — the un-suppress path.

    Returns True if a suppression row was deleted, False otherwise. Also clears
    any soft-bounce counter so the address starts clean.
    """
    e = _normalize(email)
    if not e or not supabase_configured():
        return False
    try:
        sb = get_supabase_client()
        resp = sb.table("email_suppressions").delete().eq("email", e).execute()
        removed = bool(getattr(resp, "data", None))
        try:
            sb.table("email_soft_bounces").delete().eq("email", e).execute()
        except Exception as exc:  # counter cleanup is best-effort
            logger.warning("clearing soft-bounce counter for %s failed: %s", e, exc)
        if removed:
            logger.info("Un-suppressed %s", e)
        return removed
    except Exception as exc:
        logger.warning("remove_suppression failed for %s: %s", e, exc)
        return False


def list_suppressions(limit: int = 200) -> list[dict[str, Any]]:
    """Return recent suppression rows (for the admin view). Best-effort."""
    if not supabase_configured():
        return []
    try:
        sb = get_supabase_client()
        resp = (
            sb.table("email_suppressions")
            .select("email, reason, provider, detail, created_at, updated_at")
            .order("created_at", desc=True)
            .limit(min(max(limit, 1), 1000))
            .execute()
        )
        return getattr(resp, "data", None) or []
    except Exception as exc:
        logger.warning("list_suppressions failed: %s", exc)
        return []


def record_soft_bounce(
    email: str,
    provider: str | None = None,
    detail: str | None = None,
) -> int:
    """Increment the transient-bounce counter for ``email`` and return the new
    count. When the count reaches SOFT_BOUNCE_SUPPRESS_THRESHOLD the address is
    promoted to a suppression (reason=repeated_soft_bounce). A single soft
    bounce never suppresses. Best-effort; returns 0 if not recorded."""
    e = _normalize(email)
    if not e or not supabase_configured():
        return 0
    try:
        sb = get_supabase_client()
        existing = (
            sb.table("email_soft_bounces")
            .select("bounce_count")
            .eq("email", e)
            .limit(1)
            .execute()
        )
        rows = getattr(existing, "data", None) or []
        prev = rows[0].get("bounce_count", 0) if rows else 0
        count = int(prev or 0) + 1
        sb.table("email_soft_bounces").upsert(
            {
                "email": e,
                "bounce_count": count,
                "provider": provider,
                "last_reason": detail,
                "last_bounce_at": datetime.now(timezone.utc).isoformat(),
            },
            on_conflict="email",
        ).execute()
        logger.info(
            "Soft bounce for %s (count=%d/%d, provider=%s)",
            e, count, SOFT_BOUNCE_SUPPRESS_THRESHOLD, provider,
        )
        if count >= SOFT_BOUNCE_SUPPRESS_THRESHOLD:
            add_suppression(
                e,
                "repeated_soft_bounce",
                provider,
                f"{count} transient bounces ({detail or 'no detail'})",
            )
        return count
    except Exception as exc:
        logger.warning("record_soft_bounce failed for %s: %s", e, exc)
        return 0


# ---------------------------------------------------------------------------
# Event handlers — translate a verified ESP payload into suppression actions
# ---------------------------------------------------------------------------

def handle_resend_event(payload: dict) -> None:
    """Process a verified Resend webhook payload (bounce / complaint)."""
    etype = payload.get("type", "")
    data = payload.get("data", {}) or {}
    recipients = data.get("to") or []
    if isinstance(recipients, str):
        recipients = [recipients]

    if etype == "email.complained":
        for r in recipients:
            add_suppression(r, "complaint", "resend", "spam complaint")
        return

    if etype == "email.bounced":
        bounce = data.get("bounce", {}) or {}
        btype = (bounce.get("type") or "").strip().lower()
        detail = bounce.get("message") or bounce.get("subType")
        for r in recipients:
            if btype == "permanent":
                add_suppression(r, "hard_bounce", "resend", detail)
            else:
                # "Transient" / "Undetermined" / unknown -> soft, count only.
                record_soft_bounce(r, "resend", detail or btype or "transient")
        return

    logger.info("Resend webhook type %r ignored (not a bounce/complaint)", etype)


def handle_postmark_event(payload: dict) -> None:
    """Process a verified Postmark webhook payload (bounce / spam complaint)."""
    record_type = payload.get("RecordType", "")
    email = payload.get("Email", "")
    ptype = payload.get("Type") or ""

    if record_type == "SpamComplaint":
        add_suppression(email, "complaint", "postmark", ptype or "SpamComplaint")
        return

    if record_type == "Bounce":
        code = payload.get("TypeCode")
        try:
            code = int(code)
        except (TypeError, ValueError):
            code = None
        if code in _POSTMARK_HARD_TYPE_CODES:
            add_suppression(email, "hard_bounce", "postmark", ptype)
        elif code in _POSTMARK_SOFT_TYPE_CODES:
            record_soft_bounce(email, "postmark", ptype)
        else:
            logger.info(
                "Postmark bounce type %r (code=%s) for %s logged only (not suppressed)",
                ptype, code, email,
            )
        return

    logger.info("Postmark webhook RecordType %r ignored", record_type)

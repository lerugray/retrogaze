"""
Custom SMTP email sender for auth emails (signup confirmation, password reset).

Supabase's built-in email sender is capped at a few messages per hour and
lands in spam. This module bypasses it by:
  1. Calling Supabase's `/auth/v1/admin/generate_link` endpoint to produce a
     one-time action link WITHOUT triggering Supabase's own email send.
  2. Sending that link through a transactional ESP — Resend or Postmark — via
     their HTTP API, using httpx (already a project dependency).

Provider selection is env-driven:
  - RESEND_API_KEY set  → Resend (https://api.resend.com/emails)
  - POSTMARK_SERVER_TOKEN set → Postmark (https://api.postmarkapp.com/email)

When neither is configured the functions log a warning and return ``False``
so callers can fall back to Supabase's managed sender (or the
``send_recovery_link.py`` manual-link script for dev).

Env vars:
  RESEND_API_KEY           — Resend API key (re_xxx)
  POSTMARK_SERVER_TOKEN    — Postmark server token
  RETROGAZE_EMAIL_FROM     — From address (e.g. "Retrogaze <noreply@example.com>")
  RETROGAZE_EMAIL_FROM_NAME— Display name override (default: "Retrogaze")
  SUPABASE_URL             — Supabase project URL (shared with supabase_client)
  SUPABASE_SERVICE_ROLE_KEY — service-role key (shared with supabase_client)

DNS prerequisites (configure at the DNS provider, not in code):
  - SPF:   TXT  v=spf1 include:resend.com ~all   (Resend)
           TXT  v=spf1 include:spf.postmarkapp.com ~all  (Postmark)
  - DKIM:  CNAME record(s) provided by the ESP on signup
  - DMARC: TXT  _dmarc  v=DMARC1; p=quarantine; rua=mailto:dmarc@example.com
"""

from __future__ import annotations

import logging
import os
import urllib.request
import urllib.error
import json
from dataclasses import dataclass
from typing import Literal

import httpx

from .suppression import is_suppressed

logger = logging.getLogger("retrogaze.email")

_DEFAULT_FROM_NAME = "Retrogaze"
_DEFAULT_FROM_ADDR = "noreply@example.com"
_DEFAULT_REDIRECT = "http://localhost:8000/app"

_EMAIL_PROVIDER: Literal["resend", "postmark", "none"] | None = None


def _get_env(name: str) -> str | None:
    """Return a stripped env var or None if unset/empty."""
    val = os.environ.get(name, "").strip()
    return val or None


def _detect_provider() -> Literal["resend", "postmark", "none"]:
    """Detect which ESP to use based on env vars. Cached after first call."""
    global _EMAIL_PROVIDER
    if _EMAIL_PROVIDER is not None:
        return _EMAIL_PROVIDER
    if _get_env("RESEND_API_KEY"):
        _EMAIL_PROVIDER = "resend"
    elif _get_env("POSTMARK_SERVER_TOKEN"):
        _EMAIL_PROVIDER = "postmark"
    else:
        _EMAIL_PROVIDER = "none"
    return _EMAIL_PROVIDER


def email_configured() -> bool:
    """Return True if a custom ESP (Resend or Postmark) is configured."""
    return _detect_provider() != "none"


def _from_header() -> str:
    """Build the From: header, preferring RETROGAZE_EMAIL_FROM."""
    raw = _get_env("RETROGAZE_EMAIL_FROM")
    if raw:
        return raw
    name = _get_env("RETROGAZE_EMAIL_FROM_NAME") or _DEFAULT_FROM_NAME
    return f"{name} <{_DEFAULT_FROM_ADDR}>"


def _supabase_admin_url() -> str:
    """Return the base Supabase URL (no trailing slash)."""
    url = _get_env("SUPABASE_URL")
    if not url:
        raise EnvironmentError("SUPABASE_URL is not set.")
    return url.rstrip("/")


def _supabase_service_key() -> str:
    """Return the Supabase service-role key."""
    key = _get_env("SUPABASE_SERVICE_ROLE_KEY")
    if not key:
        raise EnvironmentError("SUPABASE_SERVICE_ROLE_KEY is not set.")
    return key


# ---------------------------------------------------------------------------
# Supabase link generation (does NOT send an email)
# ---------------------------------------------------------------------------

def _generate_supabase_link(
    link_type: str,
    email: str,
    redirect_to: str | None = None,
) -> str:
    """
    Call Supabase ``/auth/v1/admin/generate_link`` to get a one-time action
    link without triggering Supabase's own email send.

    ``link_type`` is one of: ``signup`` (confirmation), ``recovery``
    (password reset), ``invite``, ``magiclink``.

    Returns the ``action_link`` URL from the response.
    """
    body = json.dumps({
        "type": link_type,
        "email": email,
        "options": {"redirect_to": redirect_to or _DEFAULT_REDIRECT},
    }).encode()

    req = urllib.request.Request(
        _supabase_admin_url() + "/auth/v1/admin/generate_link",
        data=body,
        headers={
            "apikey": _supabase_service_key(),
            "Authorization": f"Bearer {_supabase_service_key()}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        logger.error("Supabase generate_link failed (%s): %s", exc.code, detail)
        raise RuntimeError(f"Supabase generate_link HTTP {exc.code}") from exc

    link = (
        payload.get("action_link")
        or payload.get("properties", {}).get("action_link")
    )
    if not link:
        logger.error("No action_link in Supabase response: %s", payload)
        raise RuntimeError("Supabase generate_link returned no action_link")
    return link


# ---------------------------------------------------------------------------
# ESP dispatch (Resend / Postmark)
# ---------------------------------------------------------------------------

@dataclass
class _EmailResult:
    ok: bool
    provider: str
    message_id: str | None = None
    error: str | None = None


def _send_via_resend(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> _EmailResult:
    """Send an email through the Resend HTTP API."""
    api_key = _get_env("RESEND_API_KEY")
    if not api_key:
        return _EmailResult(ok=False, provider="resend", error="RESEND_API_KEY not set")

    payload: dict = {
        "from": _from_header(),
        "to": [to],
        "subject": subject,
        "html": html_body,
    }
    if text_body:
        payload["text"] = text_body

    try:
        resp = httpx.post(
            "https://api.resend.com/emails",
            json=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            timeout=15.0,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return _EmailResult(
                ok=True,
                provider="resend",
                message_id=data.get("id"),
            )
        return _EmailResult(
            ok=False,
            provider="resend",
            error=f"HTTP {resp.status_code}: {resp.text}",
        )
    except Exception as exc:
        logger.error("Resend send failed: %s", exc)
        return _EmailResult(ok=False, provider="resend", error=str(exc))


def _send_via_postmark(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> _EmailResult:
    """Send an email through the Postmark HTTP API."""
    token = _get_env("POSTMARK_SERVER_TOKEN")
    if not token:
        return _EmailResult(
            ok=False, provider="postmark", error="POSTMARK_SERVER_TOKEN not set"
        )

    payload: dict = {
        "From": _from_header(),
        "To": to,
        "Subject": subject,
        "HtmlBody": html_body,
    }
    if text_body:
        payload["TextBody"] = text_body

    try:
        resp = httpx.post(
            "https://api.postmarkapp.com/email",
            json=payload,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "X-Postmark-Server-Token": token,
            },
            timeout=15.0,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            return _EmailResult(
                ok=True,
                provider="postmark",
                message_id=str(data.get("MessageId", "")) or None,
            )
        return _EmailResult(
            ok=False,
            provider="postmark",
            error=f"HTTP {resp.status_code}: {resp.text}",
        )
    except Exception as exc:
        logger.error("Postmark send failed: %s", exc)
        return _EmailResult(ok=False, provider="postmark", error=str(exc))


def _send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> _EmailResult:
    """Dispatch through the configured ESP, or return a no-op result.

    Addresses on the suppression list (hard bounce / spam complaint / repeated
    soft bounce — see suppression.py) are skipped before dispatch, with the skip
    logged, so Retrogaze never re-sends to an address an ESP told us to stop
    mailing (sender-reputation protection).
    """
    provider = _detect_provider()
    if provider == "none":
        logger.warning(
            "No custom ESP configured (set RESEND_API_KEY or POSTMARK_SERVER_TOKEN). "
            "Email to %s not sent.",
            to,
        )
        return _EmailResult(ok=False, provider="none", error="No ESP configured")

    if is_suppressed(to):
        logger.info("Email to %s skipped — address is on the suppression list.", to)
        return _EmailResult(ok=False, provider=provider, error="suppressed")

    if provider == "resend":
        return _send_via_resend(to, subject, html_body, text_body)
    if provider == "postmark":
        return _send_via_postmark(to, subject, html_body, text_body)

    return _EmailResult(ok=False, provider="none", error="No ESP configured")


# ---------------------------------------------------------------------------
# Public API: confirmation + password reset
# ---------------------------------------------------------------------------

def send_confirmation_email(
    email: str,
    redirect_to: str | None = None,
) -> _EmailResult:
    """
    Send a signup confirmation email.

    Generates a confirmation link via Supabase's admin generate_link API
    (type=signup), then sends it through the configured ESP.

    Returns an _EmailResult. When no ESP is configured, returns ok=False so
    the caller can fall back to Supabase's built-in sender.
    """
    link = _generate_supabase_link("signup", email, redirect_to)
    subject = "Confirm your Retrogaze account"
    html_body = (
        "<div style=\"font-family:sans-serif;max-width:480px;margin:0 auto;\">"
        "<h2 style=\"color:#1a1a2e;\">Welcome to Retrogaze!</h2>"
        "<p>Confirm your email to activate your account:</p>"
        f'<p><a href="{link}" '
        'style="display:inline-block;padding:12px 24px;'
        "background:#6c5ce7;color:#fff;text-decoration:none;"
        'border-radius:6px;font-weight:bold;">Confirm Email</a></p>'
        "<p style=\"color:#666;font-size:13px;\">"
        "Or paste this link into your browser:<br>"
        f'<a href="{link}">{link}</a></p>'
        "<p style=\"color:#999;font-size:12px;\">"
        "If you didn't create a Retrogaze account, you can ignore this email."
        "</p></div>"
    )
    text_body = (
        "Welcome to Retrogaze!\n\n"
        "Confirm your email to activate your account:\n"
        f"{link}\n\n"
        "If you didn't create a Retrogaze account, you can ignore this email."
    )
    return _send_email(email, subject, html_body, text_body)


def send_password_reset_email(
    email: str,
    redirect_to: str | None = None,
) -> _EmailResult:
    """
    Send a password-reset email.

    Generates a recovery link via Supabase's admin generate_link API
    (type=recovery), then sends it through the configured ESP.

    Returns an _EmailResult. When no ESP is configured, returns ok=False so
    the caller can fall back to Supabase's built-in sender.
    """
    link = _generate_supabase_link("recovery", email, redirect_to)
    subject = "Reset your Retrogaze password"
    html_body = (
        "<div style=\"font-family:sans-serif;max-width:480px;margin:0 auto;\">"
        "<h2 style=\"color:#1a1a2e;\">Reset Your Password</h2>"
        "<p>We received a request to reset your Retrogaze password.</p>"
        f'<p><a href="{link}" '
        'style="display:inline-block;padding:12px 24px;'
        "background:#6c5ce7;color:#fff;text-decoration:none;"
        'border-radius:6px;font-weight:bold;">Reset Password</a></p>'
        "<p style=\"color:#666;font-size:13px;\">"
        "Or paste this link into your browser:<br>"
        f'<a href="{link}">{link}</a></p>'
        "<p style=\"color:#999;font-size:12px;\">"
        "This link expires per your account's auth settings. "
        "If you didn't request a password reset, you can ignore this email."
        "</p></div>"
    )
    text_body = (
        "Reset your Retrogaze password\n\n"
        "We received a request to reset your password.\n"
        f"Click here to reset: {link}\n\n"
        "This link expires per your account's auth settings.\n"
        "If you didn't request a password reset, you can ignore this email."
    )
    return _send_email(email, subject, html_body, text_body)


def send_payment_failed_email(
    email: str,
    invoice_url: str | None = None,
) -> _EmailResult:
    """
    Send a one-time Retrogaze-branded notice when a subscription renewal
    payment fails.

    LemonSqueezy automatically retries a failed renewal (up to 4 attempts
    over roughly two weeks) and sends its own reminder email on every
    attempt — this is a single supplementary notice sent on the FIRST
    failure only (the caller gates repeat failures out; see
    payments.handle_webhook_event) so the user doesn't miss the billing
    issue if LemonSqueezy's email lands in spam or goes unrecognized. Access
    is not revoked at this point; it only lapses if LemonSqueezy's retry/
    dunning window runs out (subscription_expired).

    Returns an _EmailResult. When no ESP is configured, returns ok=False —
    LemonSqueezy's own reminder emails still cover the notice in that case.
    """
    subject = "Action needed: your Retrogaze payment didn't go through"
    cta_url = invoice_url or _DEFAULT_REDIRECT
    html_body = (
        "<div style=\"font-family:sans-serif;max-width:480px;margin:0 auto;\">"
        "<h2 style=\"color:#1a1a2e;\">We couldn't process your payment</h2>"
        "<p>Your Retrogaze subscription renewal payment didn't go through. "
        "No action is needed immediately — we'll automatically retry your "
        "payment method over the next couple of weeks, and your account "
        "stays active in the meantime.</p>"
        "<p>To avoid any interruption, update your payment method now:</p>"
        f'<p><a href="{cta_url}" '
        'style="display:inline-block;padding:12px 24px;'
        "background:#6c5ce7;color:#fff;text-decoration:none;"
        'border-radius:6px;font-weight:bold;">Update Payment Method</a></p>'
        "<p style=\"color:#666;font-size:13px;\">"
        "Or paste this link into your browser:<br>"
        f'<a href="{cta_url}">{cta_url}</a></p>'
        "<p style=\"color:#999;font-size:12px;\">"
        "If your payment method is already up to date, this may resolve "
        "itself automatically on the next retry."
        "</p></div>"
    )
    text_body = (
        "We couldn't process your Retrogaze payment\n\n"
        "Your subscription renewal payment didn't go through. No action is "
        "needed immediately — we'll automatically retry over the next "
        "couple of weeks, and your account stays active in the meantime.\n\n"
        f"To avoid any interruption, update your payment method: {cta_url}\n"
    )
    return _send_email(email, subject, html_body, text_body)


# ---------------------------------------------------------------------------
# Welcome email (mechanism only — copy is a placeholder; feature is env-gated
# OFF so nothing sends until Ray's real copy lands and the flag is flipped)
# ---------------------------------------------------------------------------

def welcome_email_enabled() -> bool:
    """Return True only when the welcome-email feature is explicitly enabled.

    Gated behind the ``WELCOME_EMAIL_ENABLED`` env var, DEFAULT OFF. The body in
    ``send_welcome_email`` is a RAY-COPY-PENDING placeholder, so this flag must
    stay unset until the real copy is written and someone deliberately flips it.
    """
    val = os.environ.get("WELCOME_EMAIL_ENABLED", "").strip().lower()
    return val in ("1", "true", "yes", "on")


def send_welcome_email(
    email: str,
    redirect_to: str | None = None,
) -> _EmailResult:
    """Send a one-time transactional welcome email on signup-confirmed.

    MECHANISM ONLY. The template body below is an obvious placeholder marked
    RAY-COPY-PENDING — do NOT treat this as shippable copy. The whole feature is
    gated behind ``WELCOME_EMAIL_ENABLED`` (default OFF): when the flag is unset
    this returns ok=False WITHOUT dispatching, so nothing can ever send until the
    real copy lands and the flag is flipped. Suppression is still respected
    (dispatch goes through ``_send_email``, which skips suppressed addresses).

    Returns an _EmailResult.
    """
    if not welcome_email_enabled():
        # Hard gate: never dispatch while the placeholder copy is in place.
        return _EmailResult(
            ok=False, provider="none", error="welcome email disabled (WELCOME_EMAIL_ENABLED off)"
        )

    cta_url = redirect_to or _DEFAULT_REDIRECT
    subject = "[RAY-COPY-PENDING] Welcome to Retrogaze"
    html_body = (
        "<div style=\"font-family:sans-serif;max-width:480px;margin:0 auto;\">"
        "<h2 style=\"color:#1a1a2e;\">[RAY-COPY-PENDING] Welcome to Retrogaze</h2>"
        "<p>[RAY-COPY-PENDING] This is placeholder welcome-email body copy. "
        "Ray will replace this with the real onboarding message before the "
        "WELCOME_EMAIL_ENABLED flag is turned on.</p>"
        f'<p><a href="{cta_url}" '
        'style="display:inline-block;padding:12px 24px;'
        "background:#6c5ce7;color:#fff;text-decoration:none;"
        'border-radius:6px;font-weight:bold;">[RAY-COPY-PENDING] Start Creating</a></p>'
        "<p style=\"color:#999;font-size:12px;\">"
        "[RAY-COPY-PENDING] placeholder footer."
        "</p></div>"
    )
    text_body = (
        "[RAY-COPY-PENDING] Welcome to Retrogaze\n\n"
        "[RAY-COPY-PENDING] This is placeholder welcome-email body copy. Ray "
        "will replace this with the real onboarding message before the "
        "WELCOME_EMAIL_ENABLED flag is turned on.\n\n"
        f"[RAY-COPY-PENDING] Start creating: {cta_url}\n"
    )
    return _send_email(email, subject, html_body, text_body)
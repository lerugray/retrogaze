"""
LemonSqueezy payment integration for Retrogaze.

Handles checkout URL creation, webhook signature verification,
webhook event processing, and customer portal URL retrieval.
All LemonSqueezy API interactions are isolated in this module.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import re as _re

import httpx

from .supabase_client import get_supabase_client, supabase_configured

logger = logging.getLogger("retrogaze.payments")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

LEMONSQUEEZY_API_BASE = "https://api.lemonsqueezy.com/v1"

# Map LemonSqueezy variant IDs → Retrogaze tier names.
# Configurable via env vars so product changes don't require code edits.
# Format: LEMONSQUEEZY_VARIANT_<TIER>_<INTERVAL>=<variant_id>
# Falls back to defaults from the Retrogaze store (test mode, store 335886).
def _load_variant_config() -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    """Load variant ID mappings from env vars with hardcoded defaults."""
    defaults = {
        "starter": {"monthly": "1487496", "annual": "1487486"},
        "pro":     {"monthly": "1487508", "annual": "1487517"},
        "studio":  {"monthly": "1487577", "annual": "1487583"},
    }
    tier_to_variant: dict[str, dict[str, str]] = {}
    variant_to_tier: dict[str, str] = {}

    for tier, intervals in defaults.items():
        tier_to_variant[tier] = {}
        for interval, default_id in intervals.items():
            env_key = f"LEMONSQUEEZY_VARIANT_{tier.upper()}_{interval.upper()}"
            vid = os.environ.get(env_key, "").strip() or default_id
            tier_to_variant[tier][interval] = vid
            variant_to_tier[vid] = tier

    return variant_to_tier, tier_to_variant


VARIANT_TO_TIER, TIER_TO_VARIANT = _load_variant_config()


def _get_ls_env(name: str) -> str:
    """Return a LemonSqueezy env var or raise a clear error."""
    val = os.environ.get(name, "").strip()
    if not val:
        raise EnvironmentError(
            f"{name} is not set. Add it to .env or set the environment variable."
        )
    return val


def payments_configured() -> bool:
    """Return True if LemonSqueezy environment variables are set."""
    return bool(
        os.environ.get("LEMONSQUEEZY_API_KEY", "").strip()
        and os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "").strip()
        and os.environ.get("LEMONSQUEEZY_STORE_ID", "").strip()
    )


def _ls_headers() -> dict[str, str]:
    """Return standard headers for LemonSqueezy API requests."""
    return {
        "Authorization": f"Bearer {_get_ls_env('LEMONSQUEEZY_API_KEY')}",
        "Accept": "application/vnd.api+json",
        "Content-Type": "application/vnd.api+json",
    }


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

def verify_webhook_signature(payload: bytes, signature: str) -> bool:
    """Verify the HMAC-SHA256 signature on an incoming LemonSqueezy webhook."""
    secret = os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET", "").strip()
    if not secret:
        logger.error("LEMONSQUEEZY_WEBHOOK_SECRET not set — rejecting webhook")
        return False
    if not signature:
        logger.error("Webhook missing X-Signature — rejecting")
        return False
    if len(signature) != 64 or not _re.fullmatch(r"[0-9a-fA-F]{64}", signature):
        logger.warning("Webhook signature verification failed")
        return False

    secrets = [("current", secret)]
    next_secret = os.environ.get("LEMONSQUEEZY_WEBHOOK_SECRET_NEXT", "").strip()
    if next_secret:
        secrets.append(("next", next_secret))

    matched_slots = [
        slot
        for slot, candidate in secrets
        if hmac.compare_digest(
            hmac.new(candidate.encode(), payload, hashlib.sha256).hexdigest(),
            signature,
        )
    ]
    if not matched_slots:
        logger.warning("Webhook signature verification failed")
        return False
    logger.info("Webhook signature verified using %s secret", matched_slots[0])
    return True


# ---------------------------------------------------------------------------
# Webhook idempotency
# ---------------------------------------------------------------------------

def webhook_event_id(payload: dict) -> str:
    """
    Return a stable idempotency key for a LemonSqueezy webhook delivery.

    LemonSqueezy does not guarantee a per-delivery event id in the body, so we
    prefer ``meta.event_id`` when present and otherwise derive a deterministic
    key from ``event_name`` + resource id. Retries of the same delivery (same
    event and same resource) collapse to the same key, preventing duplicate
    tier-changes or double-refund processing.
    """
    meta = payload.get("meta", {})
    explicit = meta.get("event_id") or meta.get("webhook_id")
    if explicit:
        return str(explicit)
    event_name = meta.get("event_name", "")
    resource_id = str(payload.get("data", {}).get("id", ""))
    raw = f"{event_name}:{resource_id}"
    return hashlib.sha256(raw.encode()).hexdigest()


async def is_webhook_processed(event_id: str) -> bool:
    """Return True if this webhook event has already been handled.

    Fails open: if Supabase is not configured or the lookup errors, we return
    False so the event is still processed (rather than silently dropped).
    """
    if not supabase_configured():
        return False
    try:
        sb = get_supabase_client()
        resp = (
            sb.table("processed_webhooks")
            .select("event_id")
            .eq("event_id", event_id)
            .limit(1)
            .execute()
        )
        return bool(getattr(resp, "data", None))
    except Exception as exc:
        logger.warning(
            "is_webhook_processed check failed (event_id=%s): %s — proceeding",
            event_id, exc,
        )
        return False


async def mark_webhook_processed(event_id: str, event_name: str) -> None:
    """Record that a webhook event has been handled. Best-effort."""
    if not supabase_configured():
        return
    try:
        sb = get_supabase_client()
        sb.table("processed_webhooks").insert({
            "event_id": event_id,
            "event_name": event_name,
        }).execute()
    except Exception as exc:
        logger.warning(
            "mark_webhook_processed failed (event_id=%s): %s",
            event_id, exc,
        )


# ---------------------------------------------------------------------------
# Return URL validation (open-redirect guard)
# ---------------------------------------------------------------------------

def validate_return_url(
    return_url: str,
    allowed_origins: list[str],
) -> str | None:
    """
    Validate a checkout ``return_url`` against an origin allowlist.

    Returns the URL with query and fragment stripped if its origin is
    allowlisted, or ``None`` if the URL is malformed or its origin is not
    permitted. This prevents the post-checkout return flow from being
    abused as an open redirect: a caller who can influence ``return_url``
    could otherwise redirect a user to an arbitrary site after checkout.

    ``allowed_origins`` is a list of bare origins like
    ``["https://retrogazeai.com", "http://localhost:8642"]`` — typically
    the same list the CORS middleware uses.
    """
    from urllib.parse import urlsplit, urlunsplit

    if not return_url or not isinstance(return_url, str):
        return None

    return_url = return_url.strip()
    if not return_url:
        return None

    parts = urlsplit(return_url)
    # Must be an absolute http(s) URL — relative URLs, javascript:, data:,
    # //attacker.com, etc. are rejected.
    if parts.scheme not in ("http", "https") or not parts.netloc:
        return None

    origin = f"{parts.scheme}://{parts.netloc}".rstrip("/")
    # Normalise allowlist entries the same way (strip trailing slash).
    normalised = {o.strip().rstrip("/") for o in allowed_origins if o and o.strip()}
    if origin not in normalised:
        return None

    # Strip query and fragment — LemonSqueezy appends ?checkout=success
    # and a pre-existing query could interfere or carry attacker params.
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


# ---------------------------------------------------------------------------
# Checkout URL creation
# ---------------------------------------------------------------------------

async def create_checkout_url(
    user_id: str,
    email: str | None,
    tier: str,
    interval: str = "monthly",
    return_url: str | None = None,
    referral_code: str | None = None,
) -> str:
    """
    Create a LemonSqueezy checkout session and return the checkout URL.

    The user's Supabase UUID is embedded in ``custom.user_id`` so the
    webhook can link the subscription back to the correct profile.

    If ``return_url`` is provided, LemonSqueezy redirects the user there
    after a successful checkout (appending ``?checkout=success``). This
    lets the frontend detect the return and re-fetch the user's tier.
    """
    variant_id = TIER_TO_VARIANT.get(tier, {}).get(interval)
    if not variant_id:
        raise ValueError(f"No variant configured for tier={tier} interval={interval}")

    store_id = _get_ls_env("LEMONSQUEEZY_STORE_ID")

    custom_data = {"user_id": user_id}
    if referral_code:
        custom_data["ref"] = referral_code
    checkout_data: dict = {"custom": custom_data}
    if email:
        checkout_data["email"] = email

    attributes: dict = {"checkout_data": checkout_data}
    if return_url:
        attributes["return_url"] = return_url

    body = {
        "data": {
            "type": "checkouts",
            "attributes": attributes,
            "relationships": {
                "store": {"data": {"type": "stores", "id": store_id}},
                "variant": {"data": {"type": "variants", "id": variant_id}},
            },
        }
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(
            f"{LEMONSQUEEZY_API_BASE}/checkouts",
            headers=_ls_headers(),
            json=body,
        )
        resp.raise_for_status()

    data = resp.json()
    url = data["data"]["attributes"]["url"]
    logger.info("Checkout created for user=%s tier=%s interval=%s", user_id, tier, interval)
    return url


# ---------------------------------------------------------------------------
# Customer portal URL
# ---------------------------------------------------------------------------

async def get_customer_portal_url(lemon_customer_id: str) -> str:
    """Fetch the LemonSqueezy customer portal URL for billing management."""
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(
            f"{LEMONSQUEEZY_API_BASE}/customers/{lemon_customer_id}",
            headers=_ls_headers(),
        )
        resp.raise_for_status()

    data = resp.json()
    return data["data"]["attributes"]["urls"]["customer_portal"]


# ---------------------------------------------------------------------------
# Webhook event handling
# ---------------------------------------------------------------------------

def _tier_from_variant(variant_id: int | str) -> str | None:
    """Look up the Retrogaze tier for a LemonSqueezy variant ID.

    Returns None for a variant that isn't in our map. Callers MUST treat None
    as "unknown" and fail safe (keep the user's current tier + alert) — never
    default an unmapped variant to 'free', which silently downgrades a paying
    user when the store adds a variant we haven't mapped yet.
    """
    return VARIANT_TO_TIER.get(str(variant_id))


def _alert_unmapped_variant(
    event_name: str,
    variant_id: object,
    *,
    user_id: str | None = None,
    customer_id: str | None = None,
) -> None:
    """Loudly flag a LemonSqueezy variant we don't have mapped to a tier.

    Emitted as logger.error with an ALERT tag so the log-based monitors surface
    it. The paired handler keeps the user's current tier (never downgrades), so
    resolving this is: add the variant to VARIANT_TO_TIER / the
    LEMONSQUEEZY_VARIANT_* env, then fix the affected profile's tier manually.
    """
    logger.error(
        "ALERT unmapped LemonSqueezy variant_id=%s on %s "
        "(user_id=%s customer_id=%s) — kept current tier to avoid a downgrade; "
        "add this variant to VARIANT_TO_TIER / LEMONSQUEEZY_VARIANT_* and "
        "reconcile the affected profile manually",
        variant_id, event_name, user_id, customer_id,
    )


async def handle_webhook_event(event_name: str, payload: dict) -> None:
    """
    Process a LemonSqueezy webhook event and update the user's profile.

    Events handled:
    - subscription_created  → set tier + store LS IDs + status=active
    - subscription_updated  → update tier (upgrade/downgrade) + renewal date
    - subscription_cancelled → status=cancelled (keep tier until period ends)
    - subscription_expired   → downgrade to free (also the terminal event once
                               LemonSqueezy's own retry/dunning window for a
                               past_due subscription runs out — see
                               subscription_payment_failed below)
    - subscription_payment_failed → status=past_due; sends a single
                               Retrogaze-branded notice email on the FIRST
                               failure only. Access is NOT revoked here —
                               LemonSqueezy keeps the subscription active
                               through its own retry window (4 attempts over
                               ~2 weeks, docs.lemonsqueezy.com/help/online-
                               store/recovery-dunning) and sends its own
                               reminder email on every attempt. If retries are
                               exhausted, LemonSqueezy fires subscription_expired
                               (handled above) — the SAME downgrade mechanism
                               subscription_paused uses — with no custom
                               scheduler needed on our side.
    - subscription_payment_recovered → status=active (a renewal succeeded
                               after a prior failure; tier was never revoked
                               during the past_due window, so this is just a
                               status flip back)
    - subscription_resumed   → status=active
    - order_refunded         → downgrade to free (money returned → revoke access)
    - subscription_paused    → downgrade to free (billing paused → revoke access)
    - subscription_unpaused  → restore tier from subscription variant + active status

    NOTE on payload shape: subscription_payment_failed / _recovered (and
    _success / _refunded) carry a Subscription Invoice object in
    ``data.attributes`` — NOT a Subscription object. There is no variant_id
    or renews_at on this payload; there IS a user_email (and optionally
    urls.invoice_url), which the payment-failed notice email uses directly.
    """
    meta = payload.get("meta", {})
    attrs = payload.get("data", {}).get("attributes", {})
    sb = get_supabase_client()

    _UUID_RE = _re.compile(
        r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
        _re.IGNORECASE,
    )

    # For subscription_created, identify user from custom data embedded at checkout.
    # For all subsequent events, look up user by lemon_customer_id.
    custom_data = meta.get("custom_data", {})
    user_id = custom_data.get("user_id")
    lemon_customer_id = str(attrs.get("customer_id", ""))
    lemon_subscription_id = str(payload.get("data", {}).get("id", ""))
    variant_id = attrs.get("variant_id")
    pause = attrs.get("pause") or {}
    pause_mode = pause.get("mode") if isinstance(pause, dict) else None

    # Validate formats (defense-in-depth behind HMAC)
    if user_id and not _UUID_RE.match(str(user_id)):
        logger.error("Webhook %s: invalid user_id format: %s", event_name, user_id)
        return
    if not lemon_customer_id.isdigit() and lemon_customer_id:
        logger.error("Webhook %s: non-numeric customer_id: %s", event_name, lemon_customer_id)
        return
    # Guard the fallback path: if there is no user_id AND no customer_id, every
    # `.eq("lemon_customer_id", "")` below would match all empty-id profiles —
    # a mass cross-account update. Require at least one stable identifier.
    if not user_id and not lemon_customer_id:
        logger.error("Webhook %s: no user_id and empty customer_id — skipping", event_name)
        return

    # Capture a referred purchase for the daily support report. The endpoint's
    # processed-webhook guard makes this insert idempotent under LS retries.
    referral_code = str(custom_data.get("ref") or "").lower()
    if (event_name in {"order_created", "subscription_created"}
            and _re.fullmatch(r"[0-9a-f]{12}", referral_code)):
        sb.table("referral_conversions").insert({
            "referral_code": referral_code,
            "lemon_customer_id": lemon_customer_id or None,
            "lemon_order_id": str(attrs.get("order_id") or payload.get("data", {}).get("id") or ""),
            "lemon_subscription_id": (
                lemon_subscription_id if event_name == "subscription_created" else None
            ),
            "buyer_email": attrs.get("user_email") or attrs.get("email"),
            "event_name": event_name,
        }).execute()

    if event_name == "subscription_created":
        if not user_id:
            logger.error("subscription_created missing custom_data.user_id")
            return
        tier = _tier_from_variant(variant_id)
        update = {
            "lemon_customer_id": lemon_customer_id,
            "lemon_subscription_id": lemon_subscription_id,
            "subscription_status": "active",
            "subscription_renews_at": attrs.get("renews_at"),
        }
        if tier is None:
            # Unmapped variant: record the subscription linkage but do NOT write
            # a tier — never guess 'free' for someone who just paid. Alert so the
            # variant gets mapped and the tier set manually.
            _alert_unmapped_variant(
                event_name, variant_id, user_id=user_id, customer_id=lemon_customer_id
            )
        else:
            update["tier"] = tier
        sb.table("profiles").update(update).eq("id", user_id).execute()
        logger.info("subscription_created: user=%s tier=%s", user_id, tier)
        # Funnel: checkout_complete (bottom of the conversion funnel). Best-effort;
        # never let instrumentation break webhook processing.
        try:
            from .funnel import emit_funnel_event
            emit_funnel_event(user_id, "checkout_complete", {"tier": tier})
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("funnel checkout_complete emit failed: %s", exc)

    elif event_name == "subscription_updated":
        tier = _tier_from_variant(variant_id)
        update = {
            "subscription_status": attrs.get("status", "active"),
            "subscription_renews_at": attrs.get("renews_at"),
            "subscription_pause_mode": pause_mode,
        }
        if attrs.get("status") == "paused" and pause_mode != "free":
            update["tier"] = "free"
        elif tier is None:
            # Unmapped variant: keep the user's current tier. Never downgrade a
            # paying user because our variant map is stale.
            _alert_unmapped_variant(
                event_name, variant_id, user_id=user_id, customer_id=lemon_customer_id
            )
        else:
            update["tier"] = tier
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info("subscription_updated: tier=%s status=%s", tier, attrs.get("status"))

    elif event_name == "subscription_cancelled":
        # Keep current tier — user has access until period ends.
        update = {"subscription_status": "cancelled"}
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info("subscription_cancelled: customer=%s", lemon_customer_id)

    elif event_name == "subscription_expired":
        update = {
            "tier": "free",
            "subscription_status": "none",
            "lemon_subscription_id": None,
            "subscription_renews_at": None,
        }
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info("subscription_expired: customer=%s → free", lemon_customer_id)

    elif event_name == "subscription_payment_failed":
        # Send at most ONE Retrogaze-branded notice per dunning cycle — on
        # the first failure only. LemonSqueezy retries automatically (up to
        # 4 attempts over ~2 weeks) and emails its own reminder on every
        # attempt, so re-notifying on attempts 2-4 would just duplicate that.
        # Fails open (like is_webhook_processed above): if the lookup errors
        # or the row can't be read, treat it as "first failure" so the user
        # is never silently missed.
        already_past_due = False
        try:
            lookup_col = "id" if user_id else "lemon_customer_id"
            lookup_val = user_id if user_id else lemon_customer_id
            existing = (
                sb.table("profiles")
                .select("subscription_status")
                .eq(lookup_col, lookup_val)
                .limit(1)
                .execute()
            )
            rows = getattr(existing, "data", None)
            if isinstance(rows, list) and rows:
                already_past_due = rows[0].get("subscription_status") == "past_due"
        except Exception as exc:
            logger.warning(
                "subscription_payment_failed: status lookup failed (%s) — "
                "treating as first failure", exc,
            )

        update = {"subscription_status": "past_due"}
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info("subscription_payment_failed: customer=%s", lemon_customer_id)

        if not already_past_due:
            notify_email = attrs.get("user_email")
            if notify_email:
                try:
                    from .email import send_payment_failed_email
                    invoice_url = (attrs.get("urls") or {}).get("invoice_url")
                    send_payment_failed_email(notify_email, invoice_url=invoice_url)
                except Exception as exc:
                    logger.warning(
                        "subscription_payment_failed: notice email failed: %s", exc
                    )
            else:
                logger.info(
                    "subscription_payment_failed: no user_email on payload — "
                    "relying on LemonSqueezy's native dunning email only"
                )

    elif event_name == "subscription_payment_recovered":
        # A renewal succeeded after a prior failure (always paired with a
        # subscription_payment_success event). LemonSqueezy keeps the
        # subscription active through the whole past_due/retry window, so
        # tier was never revoked — this is just a status flip back to active.
        update = {"subscription_status": "active"}
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info("subscription_payment_recovered: customer=%s", lemon_customer_id)

    elif event_name == "subscription_resumed":
        update = {"subscription_status": "active"}
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info("subscription_resumed: customer=%s", lemon_customer_id)

    elif event_name == "order_refunded":
        # The customer's money was returned — revoke paid access. Mirrors
        # subscription_expired. Partial refunds are not distinguished here;
        # any order_refunded downgrades to free.
        update = {
            "tier": "free",
            "subscription_status": "none",
            "lemon_subscription_id": None,
            "subscription_renews_at": None,
        }
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info("order_refunded: customer=%s → free", lemon_customer_id)

    elif event_name == "subscription_paused":
        # A free pause is the referral reward: retain the paid tier and IDs.
        # Every other pause mode keeps the existing access-revocation behavior.
        if pause_mode == "free":
            update = {
                "subscription_status": "paused",
                "subscription_pause_mode": "free",
                "subscription_renews_at": attrs.get("renews_at"),
            }
        else:
            update = {
                "tier": "free",
                "subscription_status": "none",
                "subscription_pause_mode": pause_mode,
                "lemon_subscription_id": None,
                "subscription_renews_at": None,
            }
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info("subscription_paused: customer=%s mode=%s", lemon_customer_id, pause_mode)

    elif event_name == "subscription_unpaused":
        # Tier was set to free on pause; restore from LemonSqueezy subscription
        # state in this payload (variant_id, status, renews_at).
        tier = _tier_from_variant(variant_id)
        update = {
            "subscription_status": attrs.get("status", "active"),
            "subscription_pause_mode": None,
            "subscription_renews_at": attrs.get("renews_at"),
            "lemon_subscription_id": lemon_subscription_id if lemon_subscription_id else None,
        }
        if tier is None:
            # Unmapped variant: keep current tier rather than restoring 'free'.
            _alert_unmapped_variant(
                event_name, variant_id, user_id=user_id, customer_id=lemon_customer_id
            )
        else:
            update["tier"] = tier
        if user_id:
            sb.table("profiles").update(update).eq("id", user_id).execute()
        else:
            sb.table("profiles").update(update).eq(
                "lemon_customer_id", lemon_customer_id
            ).execute()
        logger.info(
            "subscription_unpaused: customer=%s tier=%s",
            lemon_customer_id,
            tier,
        )

    else:
        logger.warning("Unhandled webhook event: %s", event_name)

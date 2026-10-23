"""
Tests for the LemonSqueezy payments module.

Tests webhook signature verification, variant-to-tier mapping,
webhook event handling (with mocked Supabase), and billing endpoints.
"""

import hashlib
import hmac
import json
import logging
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock mode — no real API calls, auth bypassed
os.environ["RETROGAZE_MOCK"] = "1"

import httpx
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, AsyncMock
from retrogaze.api import app
from retrogaze.payments import (
    verify_webhook_signature,
    _tier_from_variant,
    VARIANT_TO_TIER,
    TIER_TO_VARIANT,
    payments_configured,
)

client = TestClient(app)


# ---------------------------------------------------------------------------
# Webhook signature verification
# ---------------------------------------------------------------------------

class TestWebhookSignature:
    def test_valid_signature(self):
        secret = "test-secret-123"
        payload = b'{"data": "test"}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"LEMONSQUEEZY_WEBHOOK_SECRET": secret}):
            assert verify_webhook_signature(payload, sig) is True

    def test_invalid_signature(self):
        secret = "test-secret-123"
        payload = b'{"data": "test"}'

        with patch.dict(os.environ, {"LEMONSQUEEZY_WEBHOOK_SECRET": secret}):
            assert verify_webhook_signature(payload, "wrong-sig") is False

    def test_missing_secret(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("LEMONSQUEEZY_WEBHOOK_SECRET", None)
            assert verify_webhook_signature(b"test", "sig") is False

    def test_empty_payload(self):
        secret = "test-secret-123"
        payload = b""
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"LEMONSQUEEZY_WEBHOOK_SECRET": secret}):
            assert verify_webhook_signature(payload, sig) is True

    def test_timing_safe_comparison(self):
        """Verify we use hmac.compare_digest (constant-time)."""
        secret = "test-secret"
        payload = b"data"
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
        # Slightly different sig should fail
        bad_sig = sig[:-1] + ("0" if sig[-1] != "0" else "1")

        with patch.dict(os.environ, {"LEMONSQUEEZY_WEBHOOK_SECRET": secret}):
            assert verify_webhook_signature(payload, bad_sig) is False

    def test_valid_current_signature_with_next_configured(self):
        current_secret = "current-test-secret"
        next_secret = "next-test-secret"
        payload = b'{"data": "test"}'
        sig = hmac.new(current_secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": f"  {current_secret}\n",
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": f"\t{next_secret}  ",
        }):
            assert verify_webhook_signature(payload, sig) is True

    def test_valid_next_signature(self):
        current_secret = "current-test-secret"
        next_secret = "next-test-secret"
        payload = b'{"data": "test"}'
        sig = hmac.new(next_secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": current_secret,
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": next_secret,
        }):
            assert verify_webhook_signature(payload, sig) is True

    def test_invalid_signature_with_current_and_next(self):
        payload = b'{"data": "test"}'

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": "current-test-secret",
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": "next-test-secret",
        }):
            assert verify_webhook_signature(payload, "wrong-sig") is False

    @pytest.mark.parametrize("next_secret", ["", " \t\r\n "])
    def test_blank_next_secret_is_ignored(self, next_secret):
        current_secret = "current-test-secret"
        payload = b'{"data": "test"}'
        next_sig = hmac.new(
            b"next-test-secret", payload, hashlib.sha256
        ).hexdigest()
        current_sig = hmac.new(
            current_secret.encode(), payload, hashlib.sha256
        ).hexdigest()

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": current_secret,
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": next_secret,
        }):
            assert verify_webhook_signature(payload, current_sig) is True
            assert verify_webhook_signature(payload, next_sig) is False

    def test_missing_current_secret_rejects_next_signature(self):
        next_secret = "next-test-secret"
        payload = b'{"data": "test"}'
        sig = hmac.new(next_secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": next_secret,
        }):
            os.environ.pop("LEMONSQUEEZY_WEBHOOK_SECRET", None)
            assert verify_webhook_signature(payload, sig) is False

    def test_missing_signature_rejects(self):
        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": "current-test-secret",
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": "next-test-secret",
        }):
            assert verify_webhook_signature(b"test", "") is False

    @pytest.mark.parametrize("signature", ["é" * 64, "g" * 64, "a" * 63])
    def test_malformed_signature_rejects_and_logs(self, caplog, signature):
        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": "current-test-secret",
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": "next-test-secret",
        }), caplog.at_level(logging.WARNING, logger="retrogaze.payments"):
            assert verify_webhook_signature(b"test", signature) is False

        assert "Webhook signature verification failed" in caplog.messages
        assert signature not in caplog.text

    def test_signature_mismatch_logs_warning(self, caplog):
        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": "current-test-secret",
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": "next-test-secret",
        }), caplog.at_level(logging.WARNING, logger="retrogaze.payments"):
            assert verify_webhook_signature(b"test", "0" * 64) is False

        assert "Webhook signature verification failed" in caplog.messages

    def test_whitespace_current_secret_rejects_next_signature(self):
        next_secret = "next-test-secret"
        payload = b'{"data": "test"}'
        sig = hmac.new(next_secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": " \t\r\n ",
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": next_secret,
        }):
            assert verify_webhook_signature(payload, sig) is False

    def test_identical_current_and_next_logs_current(self, caplog):
        secret = "shared-test-secret"
        payload = b'{"data": "test"}'
        sig = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": secret,
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": secret,
        }), caplog.at_level(logging.INFO, logger="retrogaze.payments"):
            assert verify_webhook_signature(payload, sig) is True

        assert "Webhook signature verified using current secret" in caplog.messages

    @pytest.mark.parametrize("matched_slot", ["current", "next"])
    def test_info_log_names_matched_secret_slot(self, caplog, matched_slot):
        current_secret = "current-test-secret"
        next_secret = "next-test-secret"
        payload = b'{"data": "test"}'
        matched_secret = current_secret if matched_slot == "current" else next_secret
        sig = hmac.new(matched_secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": current_secret,
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": next_secret,
        }), caplog.at_level(logging.INFO, logger="retrogaze.payments"):
            assert verify_webhook_signature(payload, sig) is True

        info_messages = [
            record.getMessage()
            for record in caplog.records
            if record.name == "retrogaze.payments" and record.levelno == logging.INFO
        ]
        assert f"Webhook signature verified using {matched_slot} secret" in info_messages

    def test_logs_do_not_expose_secrets_or_signatures(self, caplog):
        current_secret = "current-secret-that-must-not-leak"
        next_secret = "next-secret-that-must-not-leak"
        payload = b'{"data": "test"}'
        current_sig = hmac.new(
            current_secret.encode(), payload, hashlib.sha256
        ).hexdigest()
        next_sig = hmac.new(next_secret.encode(), payload, hashlib.sha256).hexdigest()
        invalid_sig = "invalid-signature-that-must-not-leak"

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": current_secret,
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": next_secret,
        }), caplog.at_level(logging.INFO, logger="retrogaze.payments"):
            assert verify_webhook_signature(payload, current_sig) is True
            assert verify_webhook_signature(payload, next_sig) is True
            assert verify_webhook_signature(payload, invalid_sig) is False

        for sensitive_value in (current_secret, next_secret, current_sig, next_sig, invalid_sig):
            assert sensitive_value not in caplog.text

    def test_compares_against_every_configured_secret(self):
        current_secret = "current-test-secret"
        payload = b'{"data": "test"}'
        sig = hmac.new(current_secret.encode(), payload, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {
            "LEMONSQUEEZY_WEBHOOK_SECRET": current_secret,
            "LEMONSQUEEZY_WEBHOOK_SECRET_NEXT": "next-test-secret",
        }), patch(
            "retrogaze.payments.hmac.compare_digest", wraps=hmac.compare_digest
        ) as mock_compare:
            assert verify_webhook_signature(payload, sig) is True

        assert mock_compare.call_count == 2


# ---------------------------------------------------------------------------
# Variant mapping
# ---------------------------------------------------------------------------

class TestVariantMapping:
    def test_unknown_variant_returns_none(self):
        # An unmapped variant must NOT resolve to 'free' — that would silently
        # downgrade a paying user. Callers treat None as "unknown, keep tier".
        assert _tier_from_variant("999999") is None
        assert _tier_from_variant(0) is None

    def test_known_variant_resolves_tier(self):
        assert _tier_from_variant(TIER_TO_VARIANT["pro"]["monthly"]) == "pro"
        assert _tier_from_variant(TIER_TO_VARIANT["starter"]["annual"]) == "starter"

    def test_variant_to_tier_and_tier_to_variant_consistency(self):
        """Every variant in TIER_TO_VARIANT should have an entry in VARIANT_TO_TIER."""
        for tier, intervals in TIER_TO_VARIANT.items():
            for interval, variant_id in intervals.items():
                assert str(variant_id) in VARIANT_TO_TIER, (
                    f"Variant {variant_id} ({tier}/{interval}) missing from VARIANT_TO_TIER"
                )
                assert VARIANT_TO_TIER[str(variant_id)] == tier

    def test_variant_to_tier_covers_all_tiers(self):
        """Every tier in TIER_TO_VARIANT should appear in at least one VARIANT_TO_TIER entry."""
        mapped_tiers = set(VARIANT_TO_TIER.values())
        for tier in TIER_TO_VARIANT:
            assert tier in mapped_tiers, f"Tier '{tier}' has no variant mapping"


# ---------------------------------------------------------------------------
# Webhook event handling
# ---------------------------------------------------------------------------

def _make_webhook_payload(event_name, **kwargs):
    """Build a minimal LemonSqueezy webhook payload for testing."""
    return {
        "meta": {
            "event_name": event_name,
            "custom_data": kwargs.get("custom_data", {}),
        },
        "data": {
            "id": kwargs.get("subscription_id", "123456"),
            "attributes": {
                "customer_id": kwargs.get("customer_id", "789012"),
                "variant_id": kwargs.get("variant_id", "111111"),
                "status": kwargs.get("status", "active"),
                "renews_at": kwargs.get("renews_at", "2026-05-01T00:00:00Z"),
                "pause": kwargs.get("pause"),
                "order_id": kwargs.get("order_id"),
                "user_email": kwargs.get("user_email"),
            },
        },
    }


def _make_invoice_webhook_payload(event_name, **kwargs):
    """Build a minimal LemonSqueezy webhook payload shaped like a
    Subscription Invoice object — the actual payload shape for
    subscription_payment_failed / _recovered / _success / _refunded.
    Unlike the Subscription object, there's no variant_id/renews_at, but
    there IS a user_email and optionally urls.invoice_url."""
    attrs = {
        "customer_id": kwargs.get("customer_id", "789012"),
        "subscription_id": kwargs.get("subscription_id", "555555"),
        "billing_reason": kwargs.get("billing_reason", "renewal"),
        "status": kwargs.get("status", "pending"),
    }
    if "user_email" in kwargs:
        attrs["user_email"] = kwargs["user_email"]
    if "invoice_url" in kwargs:
        attrs["urls"] = {"invoice_url": kwargs["invoice_url"]}
    return {
        "meta": {
            "event_name": event_name,
            "custom_data": kwargs.get("custom_data", {}),
        },
        "data": {
            "id": kwargs.get("invoice_id", "888001"),
            "attributes": attrs,
        },
    }


def _select_chain_mock(mock_table, rows):
    """Wire mock_table.select(...).eq(...).limit(...).execute() to return
    ``rows`` as .data, matching the chaining style used elsewhere in this
    file (mock_table returned at each step)."""
    mock_table.select.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.limit.return_value = mock_table

    def _execute(*a, **kw):
        return MagicMock(data=rows)

    mock_table.execute.side_effect = _execute


class TestWebhookEventHandling:
    @pytest.mark.asyncio
    async def test_subscription_created(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_created",
            custom_data={"user_id": "00000000-0000-0000-0000-000000000001"},
            customer_id="100001",
            subscription_id="200001",
            variant_id=TIER_TO_VARIANT["starter"]["monthly"],
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_created", payload)

        mock_sb.table.assert_called_with("profiles")
        update_call = mock_table.update.call_args[0][0]
        assert update_call["tier"] == "starter"
        assert update_call["subscription_status"] == "active"
        assert update_call["lemon_customer_id"] == "100001"
        assert update_call["lemon_subscription_id"] == "200001"
        mock_table.eq.assert_called_with("id", "00000000-0000-0000-0000-000000000001")

    @pytest.mark.asyncio
    async def test_subscription_created_unknown_variant_no_downgrade(self):
        """An unmapped variant records the linkage but must NOT write a tier."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_created",
            custom_data={"user_id": "00000000-0000-0000-0000-000000000001"},
            customer_id="100001",
            variant_id="999999",  # not in VARIANT_TO_TIER
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_created", payload)

        update_call = mock_table.update.call_args[0][0]
        assert "tier" not in update_call  # never guess a tier for an unmapped variant
        assert update_call["subscription_status"] == "active"

    @pytest.mark.asyncio
    async def test_subscription_updated_known_variant_sets_tier(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_updated",
            custom_data={"user_id": "00000000-0000-0000-0000-000000000009"},
            variant_id=TIER_TO_VARIANT["pro"]["monthly"],
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_updated", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["tier"] == "pro"

    @pytest.mark.asyncio
    async def test_subscription_updated_unknown_variant_keeps_tier(self):
        """The core downgrade guard: an unmapped variant on subscription_updated
        must leave the user's tier untouched (no silent downgrade to free)."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_updated",
            custom_data={"user_id": "00000000-0000-0000-0000-000000000009"},
            variant_id="999999",  # not in VARIANT_TO_TIER
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_updated", payload)

        update_call = mock_table.update.call_args[0][0]
        assert "tier" not in update_call  # tier is preserved, not overwritten
        assert update_call["subscription_status"] == "active"

    @pytest.mark.asyncio
    async def test_subscription_unpaused_unknown_variant_keeps_tier(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_unpaused",
            customer_id="100008",
            variant_id="999999",  # not in VARIANT_TO_TIER
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_unpaused", payload)

        update_call = mock_table.update.call_args[0][0]
        assert "tier" not in update_call

    @pytest.mark.asyncio
    async def test_subscription_created_missing_user_id(self):
        """subscription_created without user_id should log error and return."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        payload = _make_webhook_payload(
            "subscription_created",
            custom_data={},  # no user_id
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_created", payload)

        # Should not attempt any DB update
        mock_sb.table.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscription_cancelled_keeps_tier(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_cancelled",
            customer_id="100002",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_cancelled", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["subscription_status"] == "cancelled"
        # Should NOT change tier
        assert "tier" not in update_call

    @pytest.mark.asyncio
    async def test_subscription_expired_downgrades_to_free(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_expired",
            customer_id="100003",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_expired", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["tier"] == "free"
        assert update_call["subscription_status"] == "none"
        assert update_call["lemon_subscription_id"] is None
        assert update_call["subscription_renews_at"] is None

    @pytest.mark.asyncio
    async def test_subscription_payment_failed(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_payment_failed",
            customer_id="100004",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_payment_failed", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["subscription_status"] == "past_due"

    @pytest.mark.asyncio
    async def test_subscription_payment_failed_first_failure_sends_notice(self):
        """First failure (current status != past_due) sends the one-time
        Retrogaze-branded notice, using fields off the invoice payload."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        _select_chain_mock(mock_table, [{"subscription_status": "active"}])

        payload = _make_invoice_webhook_payload(
            "subscription_payment_failed",
            customer_id="100004",
            user_email="player@example.com",
            invoice_url="https://app.lemonsqueezy.com/my-orders/x/subscription-invoice/y",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb), \
             patch("retrogaze.email.send_payment_failed_email") as mock_notify:
            await handle_webhook_event("subscription_payment_failed", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["subscription_status"] == "past_due"
        mock_notify.assert_called_once_with(
            "player@example.com",
            invoice_url="https://app.lemonsqueezy.com/my-orders/x/subscription-invoice/y",
        )

    @pytest.mark.asyncio
    async def test_subscription_payment_failed_no_resend_when_already_past_due(self):
        """A retry attempt (status already past_due) must NOT trigger another
        branded notice — LemonSqueezy's own reminder emails cover retries."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        _select_chain_mock(mock_table, [{"subscription_status": "past_due"}])

        payload = _make_invoice_webhook_payload(
            "subscription_payment_failed",
            customer_id="100004",
            user_email="player@example.com",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb), \
             patch("retrogaze.email.send_payment_failed_email") as mock_notify:
            await handle_webhook_event("subscription_payment_failed", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["subscription_status"] == "past_due"
        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscription_payment_failed_skips_email_without_user_email(self):
        """No user_email on the payload → skip sending, don't crash. Relies
        on LemonSqueezy's own native dunning email instead."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        _select_chain_mock(mock_table, [{"subscription_status": "active"}])

        payload = _make_invoice_webhook_payload(
            "subscription_payment_failed",
            customer_id="100004",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb), \
             patch("retrogaze.email.send_payment_failed_email") as mock_notify:
            await handle_webhook_event("subscription_payment_failed", payload)

        mock_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_subscription_payment_failed_status_lookup_error_fails_open(self):
        """If the pre-update status lookup errors, treat as first failure
        (still send the notice) rather than silently dropping it."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.select.side_effect = RuntimeError("db down")

        payload = _make_invoice_webhook_payload(
            "subscription_payment_failed",
            customer_id="100004",
            user_email="player@example.com",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb), \
             patch("retrogaze.email.send_payment_failed_email") as mock_notify:
            await handle_webhook_event("subscription_payment_failed", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["subscription_status"] == "past_due"
        mock_notify.assert_called_once()

    @pytest.mark.asyncio
    async def test_subscription_payment_recovered_restores_active(self):
        """A renewal succeeding after a prior failure flips status back to
        active. Tier is untouched — it was never revoked during past_due."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_invoice_webhook_payload(
            "subscription_payment_recovered",
            customer_id="100004",
            user_email="player@example.com",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_payment_recovered", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["subscription_status"] == "active"
        assert "tier" not in update_call

    @pytest.mark.asyncio
    async def test_subscription_resumed(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_resumed",
            customer_id="100005",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_resumed", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["subscription_status"] == "active"

    @pytest.mark.asyncio
    async def test_order_refunded_downgrades_to_free(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "order_refunded",
            customer_id="100006",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("order_refunded", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["tier"] == "free"
        assert update_call["subscription_status"] == "none"
        assert update_call["lemon_subscription_id"] is None
        assert update_call["subscription_renews_at"] is None

    @pytest.mark.asyncio
    async def test_subscription_paused_downgrades_to_free(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        payload = _make_webhook_payload(
            "subscription_paused",
            customer_id="100007",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_paused", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["tier"] == "free"
        assert update_call["subscription_status"] == "none"
        assert update_call["lemon_subscription_id"] is None
        assert update_call["subscription_renews_at"] is None

    @pytest.mark.asyncio
    async def test_subscription_paused_free_keeps_paid_tier(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table

        payload = _make_webhook_payload(
            "subscription_paused", customer_id="100007", pause={"mode": "free"},
        )
        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_paused", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["subscription_status"] == "paused"
        assert update_call["subscription_pause_mode"] == "free"
        assert "tier" not in update_call
        assert "lemon_subscription_id" not in update_call

    @pytest.mark.asyncio
    async def test_subscription_updated_paused_other_revokes_access(self):
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        payload = _make_webhook_payload(
            "subscription_updated", customer_id="100007", status="paused",
            pause={"mode": "void"}, variant_id=TIER_TO_VARIANT["pro"]["monthly"],
        )
        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_updated", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["tier"] == "free"
        assert update_call["subscription_status"] == "paused"

    @pytest.mark.asyncio
    async def test_subscription_created_records_referral_conversion(self):
        from retrogaze.payments import handle_webhook_event

        tables = {}
        mock_sb = MagicMock()
        def table(name):
            tables.setdefault(name, MagicMock())
            t = tables[name]
            t.insert.return_value = t
            t.update.return_value = t
            t.eq.return_value = t
            return t
        mock_sb.table.side_effect = table
        payload = _make_webhook_payload(
            "subscription_created",
            custom_data={"user_id": "00000000-0000-0000-0000-000000000001", "ref": "abcdef123456"},
            customer_id="100001", subscription_id="200001", order_id="300001",
            user_email="buyer@example.com", variant_id=TIER_TO_VARIANT["starter"]["monthly"],
        )
        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_created", payload)

        row = tables["referral_conversions"].insert.call_args[0][0]
        assert row["referral_code"] == "abcdef123456"
        assert row["lemon_customer_id"] == "100001"
        assert row["lemon_order_id"] == "300001"
        assert row["buyer_email"] == "buyer@example.com"

    @pytest.mark.asyncio
    async def test_subscription_unpaused_restores_tier_from_subscription_state(self):
        """Tier comes from webhook variant_id (LemonSqueezy subscription), not DB."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.update.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.execute.return_value = None

        # Default mapping: pro monthly variant from store defaults
        pro_monthly_variant = TIER_TO_VARIANT["pro"]["monthly"]
        payload = _make_webhook_payload(
            "subscription_unpaused",
            customer_id="100008",
            subscription_id="300008",
            variant_id=pro_monthly_variant,
            status="active",
            renews_at="2026-06-01T00:00:00Z",
        )

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("subscription_unpaused", payload)

        update_call = mock_table.update.call_args[0][0]
        assert update_call["tier"] == "pro"
        assert update_call["subscription_status"] == "active"
        assert update_call["lemon_subscription_id"] == "300008"
        assert update_call["subscription_renews_at"] == "2026-06-01T00:00:00Z"

    @pytest.mark.asyncio
    async def test_unhandled_event(self):
        """Unknown events should be logged but not raise."""
        from retrogaze.payments import handle_webhook_event

        mock_sb = MagicMock()
        payload = _make_webhook_payload("some_unknown_event")

        with patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await handle_webhook_event("some_unknown_event", payload)

        mock_sb.table.assert_not_called()


# ---------------------------------------------------------------------------
# Billing API endpoints
# ---------------------------------------------------------------------------

class TestBillingEndpoints:
    def test_webhook_rejects_missing_signature(self):
        payload = _make_webhook_payload("subscription_created")
        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=json.dumps(payload),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 403

    def test_webhook_rejects_invalid_signature(self):
        payload = _make_webhook_payload("subscription_created")
        resp = client.post(
            "/webhooks/lemonsqueezy",
            content=json.dumps(payload),
            headers={
                "Content-Type": "application/json",
                "X-Signature": "definitely-wrong",
            },
        )
        assert resp.status_code == 403

    def test_webhook_rejects_invalid_json(self):
        secret = "test-secret"
        body = b"not json at all"
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"LEMONSQUEEZY_WEBHOOK_SECRET": secret}):
            resp = client.post(
                "/webhooks/lemonsqueezy",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": sig,
                },
            )
        assert resp.status_code == 400

    def test_webhook_rejects_missing_event_name(self):
        secret = "test-secret"
        body = json.dumps({"meta": {}, "data": {}}).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"LEMONSQUEEZY_WEBHOOK_SECRET": secret}):
            resp = client.post(
                "/webhooks/lemonsqueezy",
                content=body,
                headers={
                    "Content-Type": "application/json",
                    "X-Signature": sig,
                },
            )
        assert resp.status_code == 400

    def test_subscription_endpoint_returns_free_in_mock(self):
        """In mock mode (no DB), subscription should return free tier."""
        resp = client.get("/subscription")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "free"
        assert data["subscription_status"] == "none"

    def test_checkout_rejects_without_config_or_fails_gracefully(self):
        """Checkout returns 503 when unconfigured, or 502 if API call fails in mock mode."""
        resp = client.post(
            "/checkout",
            json={"tier": "starter", "interval": "monthly"},
        )
        # 503 = payments not configured, 502 = configured but API call failed (mock user)
        assert resp.status_code in (503, 502)

    def test_checkout_validates_tier(self):
        """Checkout should reject invalid tier names."""
        resp = client.post(
            "/checkout",
            json={"tier": "invalid", "interval": "monthly"},
        )
        assert resp.status_code == 422

    def test_checkout_validates_interval(self):
        """Checkout should reject invalid intervals."""
        resp = client.post(
            "/checkout",
            json={"tier": "pro", "interval": "weekly"},
        )
        assert resp.status_code == 422

    def test_billing_portal_requires_payments_config(self):
        """Billing portal should return 503 when LemonSqueezy not configured."""
        resp = client.post("/billing-portal")
        assert resp.status_code == 503

    def test_billing_portal_404_no_customer_id(self):
        """Billing portal returns 404 when user has no lemon_customer_id."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data={})

        with patch("retrogaze.api.payments_configured", return_value=True), \
             patch("retrogaze.api._db_enabled", return_value=True), \
             patch("retrogaze.supabase_client.get_user_client", return_value=mock_sb):
            resp = client.post("/billing-portal")
        assert resp.status_code == 404

    def test_billing_portal_502_on_api_failure(self):
        """Billing portal returns 502 when LemonSqueezy API is unreachable."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.return_value = MagicMock(
            data={"lemon_customer_id": "100001"}
        )

        with patch("retrogaze.api.payments_configured", return_value=True), \
             patch("retrogaze.api._db_enabled", return_value=True), \
             patch("retrogaze.supabase_client.get_user_client", return_value=mock_sb), \
             patch("retrogaze.payments.get_customer_portal_url",
                   new=AsyncMock(side_effect=httpx.HTTPError("API down"))):
            resp = client.post("/billing-portal")
        assert resp.status_code == 502

    def test_billing_portal_success_returns_url(self):
        """Billing portal returns the LemonSqueezy customer portal URL."""
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.single.return_value = mock_table
        mock_table.execute.return_value = MagicMock(
            data={"lemon_customer_id": "100001"}
        )

        portal_url = "https://app.lemonsqueezy.com/billing/portal/abc123"
        with patch("retrogaze.api.payments_configured", return_value=True), \
             patch("retrogaze.api._db_enabled", return_value=True), \
             patch("retrogaze.supabase_client.get_user_client", return_value=mock_sb), \
             patch("retrogaze.payments.get_customer_portal_url",
                   new=AsyncMock(return_value=portal_url)):
            resp = client.post("/billing-portal")
        assert resp.status_code == 200
        assert resp.json()["portal_url"] == portal_url


# ---------------------------------------------------------------------------
# Customer portal URL fetch
# ---------------------------------------------------------------------------

class TestCustomerPortalUrl:
    """Unit tests for get_customer_portal_url."""

    @pytest.mark.asyncio
    async def test_fetches_portal_url_from_customer_endpoint(self):
        from retrogaze.payments import get_customer_portal_url

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "attributes": {
                    "urls": {
                        "customer_portal": "https://app.lemonsqueezy.com/portal/xyz",
                    },
                },
            },
        }

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("retrogaze.payments.httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"LEMONSQUEEZY_API_KEY": "test-key"}):
            url = await get_customer_portal_url("100001")

        assert url == "https://app.lemonsqueezy.com/portal/xyz"
        mock_client.get.assert_awaited_once()
        called_url = mock_client.get.call_args[0][0]
        assert "/customers/100001" in called_url

    @pytest.mark.asyncio
    async def test_raises_on_http_error(self):
        from retrogaze.payments import get_customer_portal_url

        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(side_effect=httpx.HTTPStatusError(
            "Not Found", request=MagicMock(), response=mock_resp,
        ))

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("retrogaze.payments.httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {"LEMONSQUEEZY_API_KEY": "test-key"}):
            with pytest.raises(httpx.HTTPStatusError):
                await get_customer_portal_url("999999")


class TestCheckoutReferral:
    @pytest.mark.asyncio
    async def test_checkout_custom_data_carries_user_and_referral(self):
        from retrogaze.payments import create_checkout_url

        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "data": {"attributes": {"url": "https://checkout.example.test/1"}}
        }
        mock_client = AsyncMock()
        mock_client.post = AsyncMock(return_value=mock_resp)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=None)

        with patch("retrogaze.payments.httpx.AsyncClient", return_value=mock_client), \
             patch.dict(os.environ, {
                 "LEMONSQUEEZY_API_KEY": "test-key",
                 "LEMONSQUEEZY_STORE_ID": "123",
             }):
            await create_checkout_url(
                "00000000-0000-0000-0000-000000000001",
                "buyer@example.com", "starter", referral_code="abcdef123456",
            )

        body = mock_client.post.call_args.kwargs["json"]
        assert body["data"]["attributes"]["checkout_data"]["custom"] == {
            "user_id": "00000000-0000-0000-0000-000000000001",
            "ref": "abcdef123456",
        }


# ---------------------------------------------------------------------------
# Configuration check
# ---------------------------------------------------------------------------

class TestPaymentsConfig:
    def test_not_configured_when_env_missing(self):
        with patch.dict(os.environ, {}, clear=False):
            for key in ["LEMONSQUEEZY_API_KEY", "LEMONSQUEEZY_WEBHOOK_SECRET", "LEMONSQUEEZY_STORE_ID"]:
                os.environ.pop(key, None)
            assert payments_configured() is False

    def test_configured_when_all_env_set(self):
        with patch.dict(os.environ, {
            "LEMONSQUEEZY_API_KEY": "key",
            "LEMONSQUEEZY_WEBHOOK_SECRET": "secret",
            "LEMONSQUEEZY_STORE_ID": "123",
        }):
            assert payments_configured() is True

    def test_not_configured_with_partial_env(self):
        with patch.dict(os.environ, {
            "LEMONSQUEEZY_API_KEY": "key",
        }, clear=False):
            os.environ.pop("LEMONSQUEEZY_WEBHOOK_SECRET", None)
            os.environ.pop("LEMONSQUEEZY_STORE_ID", None)
            assert payments_configured() is False


# ---------------------------------------------------------------------------
# Webhook idempotency
# ---------------------------------------------------------------------------

class TestWebhookIdempotency:
    def test_event_id_prefers_explicit_event_id(self):
        from retrogaze.payments import webhook_event_id

        payload = {
            "meta": {"event_name": "subscription_created", "event_id": "evt_123"},
            "data": {"id": "999999"},
        }
        assert webhook_event_id(payload) == "evt_123"

    def test_event_id_falls_back_to_webhook_id(self):
        from retrogaze.payments import webhook_event_id

        payload = {
            "meta": {"event_name": "subscription_created", "webhook_id": "wh_456"},
            "data": {"id": "999999"},
        }
        assert webhook_event_id(payload) == "wh_456"

    def test_event_id_deterministic_for_same_event_and_resource(self):
        from retrogaze.payments import webhook_event_id

        payload = {
            "meta": {"event_name": "order_refunded"},
            "data": {"id": "order-1"},
        }
        # Two retries of the same delivery produce the same key.
        assert webhook_event_id(payload) == webhook_event_id(dict(payload))

    def test_event_id_differs_for_different_resource(self):
        from retrogaze.payments import webhook_event_id

        a = {"meta": {"event_name": "order_refunded"}, "data": {"id": "order-1"}}
        b = {"meta": {"event_name": "order_refunded"}, "data": {"id": "order-2"}}
        assert webhook_event_id(a) != webhook_event_id(b)

    @pytest.mark.asyncio
    async def test_is_webhook_processed_fails_open_when_unconfigured(self):
        from retrogaze.payments import is_webhook_processed

        with patch("retrogaze.payments.supabase_configured", return_value=False):
            assert await is_webhook_processed("evt_1") is False

    @pytest.mark.asyncio
    async def test_is_webhook_processed_returns_true_when_row_exists(self):
        from retrogaze.payments import is_webhook_processed

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[{"event_id": "evt_1"}])

        with patch("retrogaze.payments.supabase_configured", return_value=True), \
             patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            assert await is_webhook_processed("evt_1") is True
        mock_sb.table.assert_called_with("processed_webhooks")

    @pytest.mark.asyncio
    async def test_is_webhook_processed_returns_false_when_no_row(self):
        from retrogaze.payments import is_webhook_processed

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.return_value = mock_table
        mock_table.eq.return_value = mock_table
        mock_table.limit.return_value = mock_table
        mock_table.execute.return_value = MagicMock(data=[])

        with patch("retrogaze.payments.supabase_configured", return_value=True), \
             patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            assert await is_webhook_processed("evt_2") is False

    @pytest.mark.asyncio
    async def test_is_webhook_processed_fails_open_on_error(self):
        from retrogaze.payments import is_webhook_processed

        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("db down")

        with patch("retrogaze.payments.supabase_configured", return_value=True), \
             patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            assert await is_webhook_processed("evt_3") is False

    @pytest.mark.asyncio
    async def test_mark_webhook_processed_inserts_row(self):
        from retrogaze.payments import mark_webhook_processed

        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.insert.return_value = mock_table
        mock_table.execute.return_value = None

        with patch("retrogaze.payments.supabase_configured", return_value=True), \
             patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            await mark_webhook_processed("evt_4", "subscription_created")

        mock_sb.table.assert_called_with("processed_webhooks")
        insert_call = mock_table.insert.call_args[0][0]
        assert insert_call == {
            "event_id": "evt_4",
            "event_name": "subscription_created",
        }

    @pytest.mark.asyncio
    async def test_mark_webhook_processed_noop_when_unconfigured(self):
        from retrogaze.payments import mark_webhook_processed

        with patch("retrogaze.payments.supabase_configured", return_value=False):
            await mark_webhook_processed("evt_5", "order_refunded")

    @pytest.mark.asyncio
    async def test_mark_webhook_processed_swallows_errors(self):
        from retrogaze.payments import mark_webhook_processed

        mock_sb = MagicMock()
        mock_sb.table.side_effect = RuntimeError("db down")

        with patch("retrogaze.payments.supabase_configured", return_value=True), \
             patch("retrogaze.payments.get_supabase_client", return_value=mock_sb):
            # Must not raise.
            await mark_webhook_processed("evt_6", "order_refunded")

    @pytest.mark.asyncio
    async def test_endpoint_skips_duplicate_webhook(self):
        """A second delivery of the same event is short-circuited."""
        from retrogaze.payments import webhook_event_id

        secret = "test-secret"
        body = json.dumps({
            "meta": {"event_name": "subscription_expired", "custom_data": {}},
            "data": {"id": "sub-1", "attributes": {"customer_id": "12345"}},
        }).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"LEMONSQUEEZY_WEBHOOK_SECRET": secret}), \
             patch("retrogaze.payments.is_webhook_processed", new=AsyncMock(return_value=True)) as \
             mock_is, \
             patch("retrogaze.payments.mark_webhook_processed", new=AsyncMock()) as \
             mock_mark, \
             patch("retrogaze.payments.handle_webhook_event", new=AsyncMock()) as \
             mock_handle:
            resp = client.post(
                "/webhooks/lemonsqueezy",
                content=body,
                headers={"Content-Type": "application/json", "X-Signature": sig},
            )
        assert resp.status_code == 200
        assert resp.json()["duplicate"] is True
        mock_is.assert_awaited_once()
        mock_handle.assert_not_awaited()
        mock_mark.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_endpoint_marks_after_processing(self):
        """A fresh event is processed and then recorded as handled."""
        secret = "test-secret"
        body = json.dumps({
            "meta": {"event_name": "subscription_expired", "custom_data": {}},
            "data": {"id": "sub-2", "attributes": {"customer_id": "12345"}},
        }).encode()
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()

        with patch.dict(os.environ, {"LEMONSQUEEZY_WEBHOOK_SECRET": secret}), \
             patch("retrogaze.payments.is_webhook_processed", new=AsyncMock(return_value=False)), \
             patch("retrogaze.payments.mark_webhook_processed", new=AsyncMock()) as \
             mock_mark, \
             patch("retrogaze.payments.handle_webhook_event", new=AsyncMock()) as \
             mock_handle:
            resp = client.post(
                "/webhooks/lemonsqueezy",
                content=body,
                headers={"Content-Type": "application/json", "X-Signature": sig},
            )
        assert resp.status_code == 200
        mock_handle.assert_awaited_once()
        mock_mark.assert_awaited_once()


# ---------------------------------------------------------------------------
# Return URL validation (open-redirect guard)
# ---------------------------------------------------------------------------

class TestValidateReturnUrl:
    """Tests for the checkout return_url origin allowlist."""

    _ALLOWED = ["https://retrogazeai.com", "http://localhost:8642"]

    def test_valid_origin_with_path(self):
        from retrogaze.payments import validate_return_url
        result = validate_return_url("https://retrogazeai.com/gallery.html", self._ALLOWED)
        assert result == "https://retrogazeai.com/gallery.html"

    def test_valid_origin_strips_query_and_fragment(self):
        from retrogaze.payments import validate_return_url
        result = validate_return_url(
            "https://retrogazeai.com/?foo=bar#baz", self._ALLOWED
        )
        assert result == "https://retrogazeai.com/"
        assert "?" not in result
        assert "#" not in result

    def test_localhost_origin_allowed(self):
        from retrogaze.payments import validate_return_url
        result = validate_return_url("http://localhost:8642/index.html", self._ALLOWED)
        assert result == "http://localhost:8642/index.html"

    def test_disallowed_origin_rejected(self):
        from retrogaze.payments import validate_return_url
        result = validate_return_url("https://evil.com/checkout", self._ALLOWED)
        assert result is None

    def test_external_origin_with_allowed_path_rejected(self):
        """An attacker URL that happens to share a path prefix is still rejected."""
        from retrogaze.payments import validate_return_url
        result = validate_return_url("https://evil.com/gallery.html", self._ALLOWED)
        assert result is None

    def test_javascript_scheme_rejected(self):
        from retrogaze.payments import validate_return_url
        result = validate_return_url("javascript:alert(1)", self._ALLOWED)
        assert result is None

    def test_data_uri_rejected(self):
        from retrogaze.payments import validate_return_url
        result = validate_return_url("data:text/html,<script>alert(1)</script>", self._ALLOWED)
        assert result is None

    def test_protocol_relative_url_rejected(self):
        from retrogaze.payments import validate_return_url
        result = validate_return_url("//evil.com/checkout", self._ALLOWED)
        assert result is None

    def test_relative_path_rejected(self):
        from retrogaze.payments import validate_return_url
        result = validate_return_url("/checkout", self._ALLOWED)
        assert result is None

    def test_empty_string_rejected(self):
        from retrogaze.payments import validate_return_url
        assert validate_return_url("", self._ALLOWED) is None

    def test_none_rejected(self):
        from retrogaze.payments import validate_return_url
        assert validate_return_url(None, self._ALLOWED) is None

    def test_trailing_slash_in_allowlist_normalised(self):
        """Allowlist entries with trailing slashes should still match."""
        from retrogaze.payments import validate_return_url
        result = validate_return_url(
            "https://retrogazeai.com/landing",
            ["https://retrogazeai.com/"],
        )
        assert result == "https://retrogazeai.com/landing"

    def test_scheme_mismatch_rejected(self):
        """http://retrogazeai.com is NOT https://retrogazeai.com."""
        from retrogaze.payments import validate_return_url
        result = validate_return_url(
            "http://retrogazeai.com/gallery.html",
            ["https://retrogazeai.com"],
        )
        assert result is None

    def test_checkout_endpoint_rejects_disallowed_return_url(self):
        """The /checkout endpoint should 422 on a non-allowlisted return_url."""
        with patch("retrogaze.api.payments_configured", return_value=True):
            resp = client.post(
                "/checkout",
                json={
                    "tier": "starter",
                    "interval": "monthly",
                    "return_url": "https://evil.com/checkout",
                },
            )
        assert resp.status_code == 422

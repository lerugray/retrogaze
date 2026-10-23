"""
Tests for ESP bounce/complaint webhook handling + the email suppression list
(src/retrogaze/suppression.py and the /webhooks/resend + /webhooks/postmark +
/admin/api/suppressions endpoints in src/retrogaze/api.py).

Signature-verification tests are deliberately NON-CIRCULAR: the Resend/Svix
test pins the implementation to Svix's OWN published worked example
(secret whsec_plJ3nmyCDGBKInavdOK15jsl -> v1,rAvfW3dJ/X/qxhsaXPOyyCGmRKsaKWcsNccKXlIktD0=,
from https://docs.svix.com/receiving/verifying-payloads/how-manual), so a
correct pass proves the impl matches the documented algorithm, not a signature
produced by the impl itself. The handler tests feed the ESPs' documented
example payloads verbatim
(https://resend.com/docs/webhooks/emails/bounced ,
 https://resend.com/docs/webhooks/emails/complained ,
 https://postmarkapp.com/developer/webhooks/bounce-webhook ).
"""

import base64
import hashlib
import hmac
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from retrogaze.api import app
from retrogaze import suppression as sup

client = TestClient(app)


# ===========================================================================
# Svix / Resend signature verification — pinned to the DOCUMENTED worked example
# ===========================================================================

# Verbatim from the Svix docs' manual-verification worked example.
_SVIX_SECRET = "whsec_plJ3nmyCDGBKInavdOK15jsl"
_SVIX_ID = "msg_loFOjxBNrRLzqYUf"
_SVIX_TS = "1731705121"
_SVIX_BODY = b'{"event_type":"ping","data":{"success":true}}'
_SVIX_SIG = "v1,rAvfW3dJ/X/qxhsaXPOyyCGmRKsaKWcsNccKXlIktD0="


def _svix_headers(mid=_SVIX_ID, ts=_SVIX_TS, sig=_SVIX_SIG):
    return {"svix-id": mid, "svix-timestamp": ts, "svix-signature": sig}


class TestResendSignatureVerification:
    def test_documented_vector_verifies(self):
        """The canonical Svix example must verify — proves algorithm fidelity."""
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": _SVIX_SECRET}):
            assert sup.verify_resend_signature(_SVIX_BODY, _svix_headers()) is True

    def test_tampered_body_rejected(self):
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": _SVIX_SECRET}):
            assert sup.verify_resend_signature(
                _SVIX_BODY + b" ", _svix_headers()
            ) is False

    def test_wrong_secret_rejected(self):
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": "whsec_" + base64.b64encode(b"nope").decode()}):
            assert sup.verify_resend_signature(_SVIX_BODY, _svix_headers()) is False

    def test_missing_secret_fails_closed(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RESEND_WEBHOOK_SECRET", None)
            assert sup.verify_resend_signature(_SVIX_BODY, _svix_headers()) is False

    def test_missing_headers_fails_closed(self):
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": _SVIX_SECRET}):
            assert sup.verify_resend_signature(_SVIX_BODY, {}) is False
            assert sup.verify_resend_signature(
                _SVIX_BODY, {"svix-id": _SVIX_ID, "svix-timestamp": _SVIX_TS}
            ) is False

    def test_multiple_signatures_one_valid(self):
        """svix-signature is space-delimited; any matching v1 entry passes."""
        multi = f"v1,{base64.b64encode(b'bogus').decode()} {_SVIX_SIG}"
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": _SVIX_SECRET}):
            assert sup.verify_resend_signature(
                _SVIX_BODY, _svix_headers(sig=multi)
            ) is True

    def test_wrong_timestamp_changes_signed_content_rejected(self):
        """Timestamp is part of the signed content, so a different ts fails."""
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": _SVIX_SECRET}):
            assert sup.verify_resend_signature(
                _SVIX_BODY, _svix_headers(ts="1731705999")
            ) is False


# ===========================================================================
# Postmark Basic-Auth verification (Postmark does not sign webhooks)
# ===========================================================================

def _basic(user, pw):
    return "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()


class TestPostmarkAuthVerification:
    _ENV = {"POSTMARK_WEBHOOK_USERNAME": "hookuser", "POSTMARK_WEBHOOK_PASSWORD": "hookpass"}

    def test_valid_basic_auth(self):
        with patch.dict(os.environ, self._ENV):
            assert sup.verify_postmark_basic_auth(_basic("hookuser", "hookpass")) is True

    def test_wrong_password_rejected(self):
        with patch.dict(os.environ, self._ENV):
            assert sup.verify_postmark_basic_auth(_basic("hookuser", "WRONG")) is False

    def test_wrong_username_rejected(self):
        with patch.dict(os.environ, self._ENV):
            assert sup.verify_postmark_basic_auth(_basic("nope", "hookpass")) is False

    def test_missing_header_fails_closed(self):
        with patch.dict(os.environ, self._ENV):
            assert sup.verify_postmark_basic_auth("") is False

    def test_unconfigured_creds_fail_closed(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("POSTMARK_WEBHOOK_USERNAME", None)
            os.environ.pop("POSTMARK_WEBHOOK_PASSWORD", None)
            assert sup.verify_postmark_basic_auth(_basic("hookuser", "hookpass")) is False


# ===========================================================================
# Resend event handlers — documented payloads -> suppression actions
# ===========================================================================

# Documented email.bounced payload (Permanent) — resend.com/docs/webhooks/emails/bounced
_RESEND_BOUNCE_PERMANENT = {
    "type": "email.bounced",
    "data": {
        "email_id": "56761188-7520-42d8-8898-ff6fc54ce618",
        "from": "Acme <onboarding@resend.dev>",
        "to": ["delivered@resend.dev"],
        "subject": "Sending this example",
        "bounce": {
            "message": "The recipient's email address is on the suppression list...",
            "subType": "Suppressed",
            "type": "Permanent",
        },
    },
}

_RESEND_COMPLAINT = {
    "type": "email.complained",
    "data": {
        "email_id": "56761188-7520-42d8-8898-ff6fc54ce618",
        "from": "Acme <onboarding@resend.dev>",
        "to": ["complainer@resend.dev"],
        "subject": "Sending this example",
    },
}

_RESEND_BOUNCE_TRANSIENT = {
    "type": "email.bounced",
    "data": {
        "to": ["softbounce@resend.dev"],
        "bounce": {"message": "mailbox full", "subType": "General", "type": "Transient"},
    },
}


class TestResendHandler:
    def test_permanent_bounce_suppresses(self):
        with patch("retrogaze.suppression.add_suppression") as add, \
             patch("retrogaze.suppression.record_soft_bounce") as soft:
            sup.handle_resend_event(_RESEND_BOUNCE_PERMANENT)
        add.assert_called_once()
        args = add.call_args[0]
        assert args[0] == "delivered@resend.dev"
        assert args[1] == "hard_bounce"
        assert args[2] == "resend"
        soft.assert_not_called()

    def test_complaint_suppresses(self):
        with patch("retrogaze.suppression.add_suppression") as add:
            sup.handle_resend_event(_RESEND_COMPLAINT)
        add.assert_called_once()
        assert add.call_args[0][0] == "complainer@resend.dev"
        assert add.call_args[0][1] == "complaint"

    def test_transient_bounce_counts_only(self):
        with patch("retrogaze.suppression.add_suppression") as add, \
             patch("retrogaze.suppression.record_soft_bounce") as soft:
            sup.handle_resend_event(_RESEND_BOUNCE_TRANSIENT)
        add.assert_not_called()
        soft.assert_called_once()
        assert soft.call_args[0][0] == "softbounce@resend.dev"

    def test_unrelated_event_ignored(self):
        with patch("retrogaze.suppression.add_suppression") as add, \
             patch("retrogaze.suppression.record_soft_bounce") as soft:
            sup.handle_resend_event({"type": "email.delivered", "data": {"to": ["x@y.z"]}})
        add.assert_not_called()
        soft.assert_not_called()


# ===========================================================================
# Postmark event handlers — documented payloads -> suppression actions
# ===========================================================================

# Documented bounce payload — postmarkapp.com/developer/webhooks/bounce-webhook
_POSTMARK_HARD_BOUNCE = {
    "RecordType": "Bounce",
    "Type": "HardBounce",
    "TypeCode": 1,
    "Email": "john@example.com",
    "Inactive": True,
    "CanActivate": True,
}

_POSTMARK_SPAM_COMPLAINT = {
    "RecordType": "SpamComplaint",
    "Type": "SpamComplaint",
    "TypeCode": 100001,
    "Email": "spammed@example.com",
}

_POSTMARK_TRANSIENT = {
    "RecordType": "Bounce",
    "Type": "Transient",
    "TypeCode": 2,
    "Email": "temp@example.com",
}

_POSTMARK_SOFT = {
    "RecordType": "Bounce",
    "Type": "SoftBounce",
    "TypeCode": 4096,
    "Email": "full@example.com",
}


class TestPostmarkHandler:
    def test_hard_bounce_suppresses(self):
        with patch("retrogaze.suppression.add_suppression") as add, \
             patch("retrogaze.suppression.record_soft_bounce") as soft:
            sup.handle_postmark_event(_POSTMARK_HARD_BOUNCE)
        add.assert_called_once()
        assert add.call_args[0][0] == "john@example.com"
        assert add.call_args[0][1] == "hard_bounce"
        assert add.call_args[0][2] == "postmark"
        soft.assert_not_called()

    def test_spam_complaint_suppresses(self):
        with patch("retrogaze.suppression.add_suppression") as add:
            sup.handle_postmark_event(_POSTMARK_SPAM_COMPLAINT)
        add.assert_called_once()
        assert add.call_args[0][0] == "spammed@example.com"
        assert add.call_args[0][1] == "complaint"

    def test_transient_bounce_counts_only(self):
        with patch("retrogaze.suppression.add_suppression") as add, \
             patch("retrogaze.suppression.record_soft_bounce") as soft:
            sup.handle_postmark_event(_POSTMARK_TRANSIENT)
        add.assert_not_called()
        soft.assert_called_once()
        assert soft.call_args[0][0] == "temp@example.com"

    def test_soft_bounce_counts_only(self):
        with patch("retrogaze.suppression.add_suppression") as add, \
             patch("retrogaze.suppression.record_soft_bounce") as soft:
            sup.handle_postmark_event(_POSTMARK_SOFT)
        add.assert_not_called()
        soft.assert_called_once()

    def test_unknown_type_logged_only(self):
        """An unclassified Postmark type must neither suppress nor count."""
        payload = {"RecordType": "Bounce", "Type": "AutoResponder", "TypeCode": 64, "Email": "a@b.c"}
        with patch("retrogaze.suppression.add_suppression") as add, \
             patch("retrogaze.suppression.record_soft_bounce") as soft:
            sup.handle_postmark_event(payload)
        add.assert_not_called()
        soft.assert_not_called()


# ===========================================================================
# Suppression storage functions
# ===========================================================================

def _mock_select_chain(rows):
    """Build a mock supabase client where select().eq().limit().execute() -> rows."""
    sb = MagicMock()
    table = MagicMock()
    sb.table.return_value = table
    table.select.return_value = table
    table.eq.return_value = table
    table.limit.return_value = table
    table.execute.return_value = MagicMock(data=rows)
    return sb, table


class TestSuppressionStorage:
    def test_is_suppressed_fails_open_unconfigured(self):
        with patch("retrogaze.suppression.supabase_configured", return_value=False):
            assert sup.is_suppressed("x@y.z") is False

    def test_is_suppressed_true_when_row_exists(self):
        sb, _ = _mock_select_chain([{"email": "x@y.z"}])
        with patch("retrogaze.suppression.supabase_configured", return_value=True), \
             patch("retrogaze.suppression.get_supabase_client", return_value=sb):
            assert sup.is_suppressed("X@Y.Z") is True  # normalised
        sb.table.assert_called_with("email_suppressions")

    def test_is_suppressed_false_when_no_row(self):
        sb, _ = _mock_select_chain([])
        with patch("retrogaze.suppression.supabase_configured", return_value=True), \
             patch("retrogaze.suppression.get_supabase_client", return_value=sb):
            assert sup.is_suppressed("x@y.z") is False

    def test_is_suppressed_fails_open_on_error(self):
        sb = MagicMock()
        sb.table.side_effect = RuntimeError("db down")
        with patch("retrogaze.suppression.supabase_configured", return_value=True), \
             patch("retrogaze.suppression.get_supabase_client", return_value=sb):
            assert sup.is_suppressed("x@y.z") is False

    def test_add_suppression_upserts_normalised(self):
        sb = MagicMock()
        table = MagicMock()
        sb.table.return_value = table
        table.upsert.return_value = table
        table.execute.return_value = None
        with patch("retrogaze.suppression.supabase_configured", return_value=True), \
             patch("retrogaze.suppression.get_supabase_client", return_value=sb):
            sup.add_suppression("HARD@Example.com", "hard_bounce", "resend", "gone")
        sb.table.assert_called_with("email_suppressions")
        row = table.upsert.call_args[0][0]
        assert row["email"] == "hard@example.com"
        assert row["reason"] == "hard_bounce"
        assert row["provider"] == "resend"

    def test_remove_suppression_returns_true_when_deleted(self):
        sb = MagicMock()
        table = MagicMock()
        sb.table.return_value = table
        table.delete.return_value = table
        table.eq.return_value = table
        table.execute.return_value = MagicMock(data=[{"email": "x@y.z"}])
        with patch("retrogaze.suppression.supabase_configured", return_value=True), \
             patch("retrogaze.suppression.get_supabase_client", return_value=sb):
            assert sup.remove_suppression("x@y.z") is True

    def test_remove_suppression_returns_false_when_absent(self):
        sb = MagicMock()
        table = MagicMock()
        sb.table.return_value = table
        table.delete.return_value = table
        table.eq.return_value = table
        table.execute.return_value = MagicMock(data=[])
        with patch("retrogaze.suppression.supabase_configured", return_value=True), \
             patch("retrogaze.suppression.get_supabase_client", return_value=sb):
            assert sup.remove_suppression("x@y.z") is False

    def test_record_soft_bounce_increments(self):
        sb = MagicMock()
        table = MagicMock()
        sb.table.return_value = table
        table.select.return_value = table
        table.eq.return_value = table
        table.limit.return_value = table
        table.upsert.return_value = table
        table.execute.return_value = MagicMock(data=[{"bounce_count": 2}])
        with patch("retrogaze.suppression.supabase_configured", return_value=True), \
             patch("retrogaze.suppression.get_supabase_client", return_value=sb), \
             patch("retrogaze.suppression.add_suppression") as add:
            count = sup.record_soft_bounce("temp@example.com", "postmark", "Transient")
        assert count == 3
        add.assert_not_called()  # well below threshold
        row = table.upsert.call_args[0][0]
        assert row["bounce_count"] == 3

    def test_record_soft_bounce_promotes_at_threshold(self):
        prev = sup.SOFT_BOUNCE_SUPPRESS_THRESHOLD - 1
        sb = MagicMock()
        table = MagicMock()
        sb.table.return_value = table
        table.select.return_value = table
        table.eq.return_value = table
        table.limit.return_value = table
        table.upsert.return_value = table
        table.execute.return_value = MagicMock(data=[{"bounce_count": prev}])
        with patch("retrogaze.suppression.supabase_configured", return_value=True), \
             patch("retrogaze.suppression.get_supabase_client", return_value=sb), \
             patch("retrogaze.suppression.add_suppression") as add:
            count = sup.record_soft_bounce("bad@example.com", "resend", "Transient")
        assert count == sup.SOFT_BOUNCE_SUPPRESS_THRESHOLD
        add.assert_called_once()
        assert add.call_args[0][1] == "repeated_soft_bounce"

    def test_record_soft_bounce_noop_unconfigured(self):
        with patch("retrogaze.suppression.supabase_configured", return_value=False):
            assert sup.record_soft_bounce("x@y.z") == 0


# ===========================================================================
# Endpoints — /webhooks/resend, /webhooks/postmark (fail closed)
# ===========================================================================

class TestWebhookEndpoints:
    def test_resend_missing_signature_401(self):
        resp = client.post(
            "/webhooks/resend",
            content=json.dumps({"type": "email.bounced"}),
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 401

    def test_resend_valid_signature_200(self):
        # Uses the documented Svix vector body/headers so the signature is
        # doc-verified; the handler is patched (endpoint contract, not logic).
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": _SVIX_SECRET}), \
             patch("retrogaze.payments.is_webhook_processed", new=AsyncMock(return_value=False)), \
             patch("retrogaze.payments.mark_webhook_processed", new=AsyncMock()), \
             patch("retrogaze.suppression.handle_resend_event") as handle:
            resp = client.post(
                "/webhooks/resend",
                content=_SVIX_BODY,
                headers={"Content-Type": "application/json", **_svix_headers()},
            )
        assert resp.status_code == 200
        handle.assert_called_once()

    def test_resend_duplicate_short_circuits(self):
        with patch.dict(os.environ, {"RESEND_WEBHOOK_SECRET": _SVIX_SECRET}), \
             patch("retrogaze.payments.is_webhook_processed", new=AsyncMock(return_value=True)), \
             patch("retrogaze.payments.mark_webhook_processed", new=AsyncMock()) as mark, \
             patch("retrogaze.suppression.handle_resend_event") as handle:
            resp = client.post(
                "/webhooks/resend",
                content=_SVIX_BODY,
                headers={"Content-Type": "application/json", **_svix_headers()},
            )
        assert resp.status_code == 200
        assert resp.json()["duplicate"] is True
        handle.assert_not_called()
        mark.assert_not_awaited()

    def test_postmark_missing_auth_401(self):
        with patch.dict(os.environ, {
            "POSTMARK_WEBHOOK_USERNAME": "u", "POSTMARK_WEBHOOK_PASSWORD": "p"
        }):
            resp = client.post(
                "/webhooks/postmark",
                content=json.dumps(_POSTMARK_HARD_BOUNCE),
                headers={"Content-Type": "application/json"},
            )
        assert resp.status_code == 401

    def test_postmark_valid_auth_200(self):
        with patch.dict(os.environ, {
            "POSTMARK_WEBHOOK_USERNAME": "u", "POSTMARK_WEBHOOK_PASSWORD": "p"
        }), \
             patch("retrogaze.payments.is_webhook_processed", new=AsyncMock(return_value=False)), \
             patch("retrogaze.payments.mark_webhook_processed", new=AsyncMock()), \
             patch("retrogaze.suppression.handle_postmark_event") as handle:
            resp = client.post(
                "/webhooks/postmark",
                content=json.dumps(_POSTMARK_HARD_BOUNCE),
                headers={"Content-Type": "application/json", "Authorization": _basic("u", "p")},
            )
        assert resp.status_code == 200
        handle.assert_called_once()

    def test_postmark_wrong_auth_401_no_processing(self):
        with patch.dict(os.environ, {
            "POSTMARK_WEBHOOK_USERNAME": "u", "POSTMARK_WEBHOOK_PASSWORD": "p"
        }), \
             patch("retrogaze.suppression.handle_postmark_event") as handle:
            resp = client.post(
                "/webhooks/postmark",
                content=json.dumps(_POSTMARK_HARD_BOUNCE),
                headers={"Content-Type": "application/json", "Authorization": _basic("u", "WRONG")},
            )
        assert resp.status_code == 401
        handle.assert_not_called()


# ===========================================================================
# Admin un-suppress endpoint
# ===========================================================================

class TestAdminSuppressionEndpoints:
    def test_remove_requires_admin(self):
        with patch("retrogaze.api._ADMIN_PASSWORD", "secretpw"):
            resp = client.post(
                "/admin/api/suppressions/remove",
                json={"email": "x@y.z"},
                headers={"Authorization": "Bearer wrong"},
            )
        assert resp.status_code == 401

    def test_remove_unsuppresses_with_admin(self):
        with patch("retrogaze.api._ADMIN_PASSWORD", "secretpw"), \
             patch("retrogaze.suppression.remove_suppression", return_value=True) as rm:
            resp = client.post(
                "/admin/api/suppressions/remove",
                json={"email": "x@y.z"},
                headers={"Authorization": "Bearer secretpw"},
            )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True and body["removed"] is True
        rm.assert_called_once_with("x@y.z")

    def test_list_requires_admin(self):
        with patch("retrogaze.api._ADMIN_PASSWORD", "secretpw"):
            resp = client.get(
                "/admin/api/suppressions",
                headers={"Authorization": "Bearer wrong"},
            )
        assert resp.status_code == 401

    def test_list_returns_items_with_admin(self):
        with patch("retrogaze.api._ADMIN_PASSWORD", "secretpw"), \
             patch("retrogaze.suppression.list_suppressions",
                   return_value=[{"email": "a@b.c", "reason": "hard_bounce"}]):
            resp = client.get(
                "/admin/api/suppressions",
                headers={"Authorization": "Bearer secretpw"},
            )
        assert resp.status_code == 200
        assert resp.json()["total"] == 1


# ===========================================================================
# Send-path integration — suppressed addresses are skipped
# ===========================================================================

class TestSendPathSuppression:
    def test_send_skips_suppressed_address(self):
        import retrogaze.email as email_mod
        with patch("retrogaze.email._detect_provider", return_value="resend"), \
             patch("retrogaze.email.is_suppressed", return_value=True), \
             patch("retrogaze.email._send_via_resend") as send:
            result = email_mod._send_email("blocked@example.com", "s", "<p>h</p>")
        assert result.ok is False
        assert result.error == "suppressed"
        send.assert_not_called()

    def test_send_proceeds_for_clean_address(self):
        import retrogaze.email as email_mod
        with patch("retrogaze.email._detect_provider", return_value="resend"), \
             patch("retrogaze.email.is_suppressed", return_value=False), \
             patch("retrogaze.email._send_via_resend",
                   return_value=email_mod._EmailResult(ok=True, provider="resend", message_id="m1")) as send:
            result = email_mod._send_email("clean@example.com", "s", "<p>h</p>")
        assert result.ok is True
        send.assert_called_once()

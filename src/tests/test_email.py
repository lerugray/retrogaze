"""
Tests for the payment-failed dunning notice email (src/retrogaze/email.py).

Only the pure-function behavior of send_payment_failed_email is covered here
(subject/body construction, invoice_url vs. default fallback, and the
no-ESP-configured no-op path). The confirmation/reset-email functions predate
this file and aren't covered — this is scoped to the new function.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

from unittest.mock import patch

from retrogaze.email import send_payment_failed_email, _DEFAULT_REDIRECT


class TestSendPaymentFailedEmail:
    def test_no_esp_configured_returns_ok_false(self):
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("RESEND_API_KEY", None)
            os.environ.pop("POSTMARK_SERVER_TOKEN", None)
            # Reset the cached provider detection so the env changes apply.
            import retrogaze.email as email_mod
            email_mod._EMAIL_PROVIDER = None

            result = send_payment_failed_email("player@example.com")

        assert result.ok is False
        assert result.provider == "none"

    def test_uses_invoice_url_as_cta_when_present(self):
        invoice_url = "https://app.lemonsqueezy.com/my-orders/x/subscription-invoice/y"
        with patch("retrogaze.email._send_email") as mock_send:
            send_payment_failed_email("player@example.com", invoice_url=invoice_url)

        args = mock_send.call_args[0]
        # _send_email(to, subject, html_body, text_body)
        assert args[0] == "player@example.com"
        assert invoice_url in args[2]  # html_body
        assert invoice_url in args[3]  # text_body

    def test_falls_back_to_default_redirect_without_invoice_url(self):
        with patch("retrogaze.email._send_email") as mock_send:
            send_payment_failed_email("player@example.com")

        args = mock_send.call_args[0]
        assert _DEFAULT_REDIRECT in args[2]

    def test_subject_mentions_payment_issue(self):
        with patch("retrogaze.email._send_email") as mock_send:
            send_payment_failed_email("player@example.com")

        subject = mock_send.call_args[0][1]
        assert "payment" in subject.lower()

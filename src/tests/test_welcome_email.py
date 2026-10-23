"""
Tests for the welcome-email mechanism (src/retrogaze/email.py).

Mechanism only — the copy is a RAY-COPY-PENDING placeholder and the whole
feature is gated behind WELCOME_EMAIL_ENABLED (default OFF). These tests verify
the gate holds (nothing dispatches while disabled), the body is an obvious
placeholder, and suppression is still respected when enabled.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

from unittest.mock import patch

from retrogaze.email import (
    welcome_email_enabled,
    send_welcome_email,
    _DEFAULT_REDIRECT,
)


class TestWelcomeEmailFlag:
    def test_disabled_by_default(self, monkeypatch):
        monkeypatch.delenv("WELCOME_EMAIL_ENABLED", raising=False)
        assert welcome_email_enabled() is False

    def test_enabled_for_truthy_values(self, monkeypatch):
        for val in ("1", "true", "TRUE", "yes", "on"):
            monkeypatch.setenv("WELCOME_EMAIL_ENABLED", val)
            assert welcome_email_enabled() is True, val

    def test_disabled_for_falsey_values(self, monkeypatch):
        for val in ("", "0", "false", "no", "off"):
            monkeypatch.setenv("WELCOME_EMAIL_ENABLED", val)
            assert welcome_email_enabled() is False, val


class TestSendWelcomeEmail:
    def test_noops_when_disabled(self, monkeypatch):
        monkeypatch.delenv("WELCOME_EMAIL_ENABLED", raising=False)
        with patch("retrogaze.email._send_email") as mock_send:
            result = send_welcome_email("player@example.com")
        # Hard gate: never even reach _send_email while disabled.
        mock_send.assert_not_called()
        assert result.ok is False

    def test_dispatches_when_enabled(self, monkeypatch):
        monkeypatch.setenv("WELCOME_EMAIL_ENABLED", "1")
        with patch("retrogaze.email._send_email") as mock_send:
            send_welcome_email("player@example.com")
        mock_send.assert_called_once()
        args = mock_send.call_args[0]
        assert args[0] == "player@example.com"

    def test_body_is_ray_copy_pending_placeholder(self, monkeypatch):
        monkeypatch.setenv("WELCOME_EMAIL_ENABLED", "1")
        with patch("retrogaze.email._send_email") as mock_send:
            send_welcome_email("player@example.com")
        # _send_email(to, subject, html_body, text_body)
        subject, html_body, text_body = mock_send.call_args[0][1:4]
        assert "RAY-COPY-PENDING" in subject
        assert "RAY-COPY-PENDING" in html_body
        assert "RAY-COPY-PENDING" in text_body

    def test_uses_redirect_cta(self, monkeypatch):
        monkeypatch.setenv("WELCOME_EMAIL_ENABLED", "1")
        with patch("retrogaze.email._send_email") as mock_send:
            send_welcome_email("player@example.com")
        html_body = mock_send.call_args[0][2]
        assert _DEFAULT_REDIRECT in html_body

    def test_respects_suppression_when_enabled(self, monkeypatch):
        # Enabled + a provider configured, but the address is suppressed →
        # _send_email skips dispatch and reports "suppressed".
        monkeypatch.setenv("WELCOME_EMAIL_ENABLED", "1")
        monkeypatch.setenv("RESEND_API_KEY", "re_test")
        import retrogaze.email as email_mod
        email_mod._EMAIL_PROVIDER = None  # reset cached provider detection
        with patch("retrogaze.email.is_suppressed", return_value=True):
            result = send_welcome_email("suppressed@example.com")
        assert result.ok is False
        assert result.error == "suppressed"
        email_mod._EMAIL_PROVIDER = None  # leave detection clean for other tests

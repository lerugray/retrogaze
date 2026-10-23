"""
Tests for the conversion-funnel instrumentation (src/retrogaze/funnel.py) plus
its client endpoint (POST /funnel-events) and admin read endpoint
(GET /admin/api/funnel) in src/retrogaze/api.py.

Covers: emit best-effort behavior, once-per-user dedupe (unique-violation →
"already recorded"), the client-emittable allowlist, session-auth requirement,
and the admin count endpoint's auth gating.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock

from retrogaze.api import app
from retrogaze import funnel

client = TestClient(app)

ADMIN_PW = "test-admin-secret"


def _admin_headers():
    return {"Authorization": "Bearer " + ADMIN_PW}


def _db_on(monkeypatch):
    """Flip the emit-path gates so a mocked DB write is attempted."""
    monkeypatch.setenv("RETROGAZE_MOCK", "")
    monkeypatch.setattr("retrogaze.supabase_client.supabase_configured", lambda: True)


# ---------------------------------------------------------------------------
# emit_funnel_event
# ---------------------------------------------------------------------------

class TestEmitFunnelEvent:
    def test_noops_in_mock_mode(self):
        # RETROGAZE_MOCK=1 (default in this suite) → no write attempted.
        with patch("retrogaze.supabase_client.get_supabase_client") as gc:
            assert funnel.emit_funnel_event("u1", "first_generation") is False
            gc.assert_not_called()

    def test_unknown_event_type_skipped(self):
        assert funnel.emit_funnel_event("u1", "not_a_real_event") is False

    def test_no_user_id_returns_false(self):
        assert funnel.emit_funnel_event(None, "signup") is False
        assert funnel.emit_funnel_event("", "signup") is False

    def test_inserts_when_db_enabled(self, monkeypatch):
        _db_on(monkeypatch)
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.insert.return_value.execute.return_value = MagicMock(data=[{"id": "x"}])
        monkeypatch.setattr("retrogaze.supabase_client.get_supabase_client", lambda: mock_sb)

        assert funnel.emit_funnel_event("u1", "checkout_complete", {"tier": "pro"}) is True
        mock_sb.table.assert_called_with("funnel_events")
        payload = mock_table.insert.call_args[0][0]
        assert payload["user_id"] == "u1"
        assert payload["event_type"] == "checkout_complete"
        assert payload["metadata"] == {"tier": "pro"}

    def test_once_per_user_duplicate_returns_false(self, monkeypatch):
        _db_on(monkeypatch)
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception(
            'duplicate key value violates unique constraint "funnel_events_once_per_user"'
        )
        monkeypatch.setattr("retrogaze.supabase_client.get_supabase_client", lambda: mock_sb)

        # Second signup for the same user → the DB rejects it, reported as
        # "already recorded" (False), NOT an error.
        assert funnel.emit_funnel_event("u1", "signup") is False

    def test_generic_error_swallowed_returns_false(self, monkeypatch):
        _db_on(monkeypatch)
        mock_sb = MagicMock()
        mock_sb.table.return_value.insert.return_value.execute.side_effect = Exception(
            "network blip"
        )
        monkeypatch.setattr("retrogaze.supabase_client.get_supabase_client", lambda: mock_sb)

        # Non-once event, non-duplicate error → swallowed, returns False.
        assert funnel.emit_funnel_event("u1", "upgrade_click") is False


# ---------------------------------------------------------------------------
# funnel_counts
# ---------------------------------------------------------------------------

class TestFunnelCounts:
    def test_noops_in_mock_mode(self):
        counts = funnel.funnel_counts()
        assert set(counts) == set(funnel.FUNNEL_EVENT_TYPES)
        assert all(v == 0 for v in counts.values())

    def test_aggregates_rows(self, monkeypatch):
        _db_on(monkeypatch)
        rows = [
            {"event_type": "signup"},
            {"event_type": "signup"},
            {"event_type": "first_generation"},
            {"event_type": "checkout_complete"},
        ]
        mock_sb = MagicMock()
        q = MagicMock()
        mock_sb.table.return_value.select.return_value = q
        q.gte.return_value = q
        q.execute.return_value = MagicMock(data=rows)
        monkeypatch.setattr("retrogaze.supabase_client.get_supabase_client", lambda: mock_sb)

        counts = funnel.funnel_counts(days=30)
        assert counts["signup"] == 2
        assert counts["first_generation"] == 1
        assert counts["checkout_complete"] == 1
        assert counts["upgrade_click"] == 0
        # windowing applied
        q.gte.assert_called_once()


# ---------------------------------------------------------------------------
# Client endpoint: POST /funnel-events
# ---------------------------------------------------------------------------

class TestFunnelEventsEndpoint:
    def test_accepts_client_emittable_event(self):
        resp = client.post("/funnel-events", json={"event_type": "upgrade_click"})
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

    def test_accepts_meter_shown_event(self):
        resp = client.post(
            "/funnel-events",
            json={"event_type": "usage_meter_90_shown", "metadata": {"meter": "daily"}},
        )
        assert resp.status_code == 200

    def test_rejects_server_owned_event(self):
        # A client must not be able to spoof signup / first_generation / checkout.
        for et in ("signup", "first_generation", "checkout_complete"):
            resp = client.post("/funnel-events", json={"event_type": et})
            assert resp.status_code == 422, et

    def test_rejects_unknown_event(self):
        resp = client.post("/funnel-events", json={"event_type": "bogus"})
        assert resp.status_code == 422

    def test_requires_session_auth(self, monkeypatch):
        # Outside mock mode with no token, the get_current_user dependency 401s.
        monkeypatch.setenv("RETROGAZE_MOCK", "")
        resp = client.post("/funnel-events", json={"event_type": "upgrade_click"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Admin endpoint: GET /admin/api/funnel
# ---------------------------------------------------------------------------

class TestAdminFunnel:
    def test_requires_admin_password(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        resp = client.get("/admin/api/funnel")
        assert resp.status_code == 401

    def test_admin_not_configured_returns_503(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", "")
        resp = client.get("/admin/api/funnel", headers=_admin_headers())
        assert resp.status_code == 503

    def test_returns_counts_with_admin(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        resp = client.get("/admin/api/funnel", headers=_admin_headers())
        assert resp.status_code == 200
        body = resp.json()
        assert set(body["counts"]) == set(funnel.FUNNEL_EVENT_TYPES)
        assert body["total"] == 0  # mock mode → all-zero

    def test_windowed_query_param(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        resp = client.get("/admin/api/funnel?days=7", headers=_admin_headers())
        assert resp.status_code == 200
        assert resp.json()["days"] == 7

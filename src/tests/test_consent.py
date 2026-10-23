"""
Tests for GET /consent and POST /consent/accept — the ToS/Privacy Policy
consent status + acceptance endpoints backing the signup checkbox and the
one-time backfill prompt for existing accounts (see CURRENT_TOS_VERSION in
src/retrogaze/api.py).
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from retrogaze.api import app, CURRENT_TOS_VERSION
from retrogaze.auth import AuthenticatedUser, get_current_user

client = TestClient(app)

TEST_USER = AuthenticatedUser(
    id="00000000-0000-0000-0000-000000000001",
    email="test@example.com",
)


def _mock_supabase_table():
    """Wire a mock matching UserScopedTable's chaining: select()/update() are
    always followed by an .eq(scope_col, user_id) auto-appended by
    get_user_client(), then (for GET /consent) .single() before .execute()."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.select.return_value = mock_table
    mock_table.update.return_value = mock_table
    mock_table.eq.return_value = mock_table
    mock_table.single.return_value = mock_table
    return mock_sb, mock_table


class TestConsentStatusMockMode:
    def test_returns_no_acceptance_needed_without_db(self):
        resp = client.get("/consent")
        assert resp.status_code == 200
        data = resp.json()
        assert data["needs_acceptance"] is False
        assert data["current_version"] == CURRENT_TOS_VERSION


class TestConsentAcceptMockMode:
    def test_requires_supabase(self):
        resp = client.post("/consent/accept")
        assert resp.status_code == 503


class TestConsentStatusWithDb:
    def test_needs_acceptance_when_never_accepted(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb, mock_table = _mock_supabase_table()
        mock_table.execute.return_value = MagicMock(data={
            "tos_version": None,
            "tos_accepted_at": None,
        })
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        try:
            with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
                resp = client.get("/consent")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["needs_acceptance"] is True
        assert data["current_version"] == CURRENT_TOS_VERSION
        assert data["accepted_version"] is None

    def test_needs_acceptance_when_version_stale(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb, mock_table = _mock_supabase_table()
        mock_table.execute.return_value = MagicMock(data={
            "tos_version": "2020-01-01",
            "tos_accepted_at": "2020-01-01T00:00:00+00:00",
        })
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        try:
            with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
                resp = client.get("/consent")
        finally:
            app.dependency_overrides.clear()

        assert resp.json()["needs_acceptance"] is True

    def test_no_acceptance_needed_when_version_current(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb, mock_table = _mock_supabase_table()
        mock_table.execute.return_value = MagicMock(data={
            "tos_version": CURRENT_TOS_VERSION,
            "tos_accepted_at": "2026-07-11T00:00:00+00:00",
        })
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        try:
            with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
                resp = client.get("/consent")
        finally:
            app.dependency_overrides.clear()

        data = resp.json()
        assert data["needs_acceptance"] is False
        assert data["accepted_version"] == CURRENT_TOS_VERSION


class TestConsentAcceptWithDb:
    def test_records_current_version_and_timestamp(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb, mock_table = _mock_supabase_table()
        mock_table.execute.return_value = None
        app.dependency_overrides[get_current_user] = lambda: TEST_USER
        try:
            with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
                resp = client.post("/consent/accept")
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        data = resp.json()
        assert data["accepted_version"] == CURRENT_TOS_VERSION
        assert data["accepted_at"]

        update_call = mock_table.update.call_args[0][0]
        assert update_call["tos_version"] == CURRENT_TOS_VERSION
        assert update_call["tos_accepted_at"] == data["accepted_at"]

"""
Tests for POST /feedback — validation, anonymous + authed paths, Supabase insert.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

import pytest
from unittest.mock import MagicMock, patch
from fastapi.testclient import TestClient

from retrogaze.api import app
from retrogaze.auth import AuthenticatedUser, get_optional_user

client = TestClient(app)

TEST_USER = AuthenticatedUser(
    id="00000000-0000-0000-0000-000000000001",
    email="test@example.com",
)


def _mock_supabase_table():
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table
    mock_table.insert.return_value = mock_table
    mock_table.execute.return_value = MagicMock(data=[{"id": "fb-1"}])
    return mock_sb, mock_table


class TestFeedbackValidation:
    def test_rejects_empty_message(self):
        resp = client.post("/feedback", json={"message": "   "})
        assert resp.status_code == 422

    def test_rejects_message_over_max_length(self):
        resp = client.post("/feedback", json={"message": "x" * 2001})
        assert resp.status_code == 422

    def test_rejects_invalid_category(self):
        resp = client.post("/feedback", json={
            "message": "Something broke",
            "category": "complaint",
        })
        assert resp.status_code == 422

    def test_rejects_context_over_max_length(self):
        resp = client.post("/feedback", json={
            "message": "Something broke",
            "context": "x" * 201,
        })
        assert resp.status_code == 422

    def test_defaults_category_to_bug(self):
        with patch("retrogaze.api._db_enabled", return_value=True):
            mock_sb, mock_table = _mock_supabase_table()
            with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
                resp = client.post("/feedback", json={"message": "Button stuck"})

        assert resp.status_code == 200
        row = mock_table.insert.call_args[0][0]
        assert row["category"] == "bug"


class TestFeedbackAnonymous:
    def test_anonymous_success_without_db(self):
        resp = client.post("/feedback", json={
            "message": "Export failed on Safari",
            "category": "bug",
            "context": "generate",
        })
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "feedback" in data["message"].lower()

    def test_anonymous_insert_sets_null_user_id(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb, mock_table = _mock_supabase_table()
        with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
            resp = client.post("/feedback", json={
                "message": "Page froze after generate",
                "category": "bug",
                "context": "history",
            })

        assert resp.status_code == 200
        mock_sb.table.assert_called_with("feedback")
        row = mock_table.insert.call_args[0][0]
        assert row["user_id"] is None
        assert row["message"] == "Page froze after generate"
        assert row["context"] == "history"

    def test_insert_failure_returns_500(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb, mock_table = _mock_supabase_table()
        mock_table.execute.side_effect = RuntimeError("db down")
        with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
            resp = client.post("/feedback", json={"message": "Something broke"})

        assert resp.status_code == 500


class TestFeedbackAuthenticated:
    def test_authed_insert_includes_user_id(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb, mock_table = _mock_supabase_table()
        app.dependency_overrides[get_optional_user] = lambda: TEST_USER
        try:
            with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
                resp = client.post("/feedback", json={
                    "message": "Palette lock ignored my colors",
                    "category": "idea",
                })
        finally:
            app.dependency_overrides.clear()

        assert resp.status_code == 200
        row = mock_table.insert.call_args[0][0]
        assert row["user_id"] == TEST_USER.id
        assert row["category"] == "idea"

    def test_accepts_all_valid_categories(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        for category in ("bug", "idea", "other"):
            mock_sb, mock_table = _mock_supabase_table()
            with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
                resp = client.post("/feedback", json={
                    "message": "Test message for " + category,
                    "category": category,
                })
            assert resp.status_code == 200
            row = mock_table.insert.call_args[0][0]
            assert row["category"] == category


class TestFeedbackSecurity:
    def test_has_security_headers(self):
        resp = client.post("/feedback", json={"message": "Header check"})
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


# ---------------------------------------------------------------------------
# Admin feedback triage — GET /admin/api/feedback, PATCH /admin/api/feedback/{id}
# ---------------------------------------------------------------------------

ADMIN_PW = "test-admin-secret"


def _admin_headers():
    return {"Authorization": "Bearer " + ADMIN_PW}


def _mock_feedback_table(rows=None, updated_row=None):
    """Mock supabase client for the feedback table (list + update paths)."""
    mock_sb = MagicMock()
    mock_table = MagicMock()
    mock_sb.table.return_value = mock_table

    # Chainable query builder for the list endpoint:
    # .select(...).order(...).eq(...).limit(...).execute()
    chain = MagicMock()
    mock_table.select.return_value = chain
    chain.order.return_value = chain
    chain.eq.return_value = chain
    chain.limit.return_value = chain
    chain.execute.return_value = MagicMock(data=rows or [])

    # Count query reuses .table("feedback").select("id", count="exact")...
    count_chain = MagicMock()
    # When eq is called on the count chain (status filter), keep chaining
    count_chain.eq.return_value = count_chain
    count_chain.execute.return_value = MagicMock(count=len(rows or []))
    # select with count="exact" returns count_chain
    def _select(*args, **kwargs):
        if kwargs.get("count") == "exact":
            return count_chain
        return chain
    mock_table.select.side_effect = _select

    # Update path: .update(...).eq("id", ...).execute()
    update_chain = MagicMock()
    mock_table.update.return_value = update_chain
    update_chain.eq.return_value = update_chain
    update_chain.execute.return_value = MagicMock(data=[updated_row] if updated_row else [])

    return mock_sb, mock_table


class TestAdminFeedbackList:
    def test_requires_admin_password(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        resp = client.get("/admin/api/feedback")
        assert resp.status_code == 401

    def test_admin_not_configured_returns_503(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", "")
        resp = client.get("/admin/api/feedback", headers=_admin_headers())
        assert resp.status_code == 503

    def test_returns_empty_when_db_disabled(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        resp = client.get("/admin/api/feedback", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_lists_feedback_rows(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        rows = [
            {"id": "fb-1", "message": "Export broke", "category": "bug",
             "status": "new", "context": "history", "user_id": None},
            {"id": "fb-2", "message": "Add NES palette", "category": "idea",
             "status": "read", "context": None, "user_id": "u-1"},
        ]
        mock_sb, _ = _mock_feedback_table(rows=rows)
        with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
            resp = client.get("/admin/api/feedback", headers=_admin_headers())

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        assert data["filtered"] == 2
        assert data["items"][0]["id"] == "fb-1"

    def test_status_filter_passes_through(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        rows = [{"id": "fb-1", "status": "new", "message": "x", "category": "bug"}]
        mock_sb, mock_table = _mock_feedback_table(rows=rows)
        with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
            resp = client.get(
                "/admin/api/feedback?status=new", headers=_admin_headers()
            )
        assert resp.status_code == 200
        # The list chain should have received an .eq("status", "new") call
        eq_calls = mock_table.select.return_value.eq.call_args_list
        assert any(
            call.args == ("status", "new") for call in eq_calls
        ), "status filter not applied to list query"

    def test_db_error_returns_500(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb = MagicMock()
        mock_table = MagicMock()
        mock_sb.table.return_value = mock_table
        mock_table.select.side_effect = RuntimeError("db down")
        with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
            resp = client.get("/admin/api/feedback", headers=_admin_headers())
        assert resp.status_code == 500


class TestAdminFeedbackTriage:
    def test_patch_requires_admin_password(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        resp = client.patch(
            "/admin/api/feedback/fb-1", json={"status": "read"}
        )
        assert resp.status_code == 401

    def test_rejects_invalid_status(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        resp = client.patch(
            "/admin/api/feedback/fb-1",
            json={"status": "wontfix"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_updates_status_to_read(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        updated = {"id": "fb-1", "status": "read", "resolved_at": None}
        mock_sb, mock_table = _mock_feedback_table(updated_row=updated)
        with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
            resp = client.patch(
                "/admin/api/feedback/fb-1",
                json={"status": "read"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert data["entry"]["status"] == "read"
        # update() should have been called with status and resolved_at=None
        update_payload = mock_table.update.call_args[0][0]
        assert update_payload["status"] == "read"
        assert update_payload["resolved_at"] is None

    def test_resolved_sets_resolved_at(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        updated = {"id": "fb-1", "status": "resolved", "resolved_at": "2026-07-07T00:00:00Z"}
        mock_sb, _ = _mock_feedback_table(updated_row=updated)
        with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
            resp = client.patch(
                "/admin/api/feedback/fb-1",
                json={"status": "resolved"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 200
        assert resp.json()["entry"]["status"] == "resolved"

    def test_not_found_returns_404(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        monkeypatch.setattr("retrogaze.api._db_enabled", lambda: True)
        mock_sb, _ = _mock_feedback_table(updated_row=None)
        with patch("retrogaze.supabase_client.get_supabase_client", return_value=mock_sb):
            resp = client.patch(
                "/admin/api/feedback/nope",
                json={"status": "read"},
                headers=_admin_headers(),
            )
        assert resp.status_code == 404

    def test_db_disabled_returns_ok(self, monkeypatch):
        monkeypatch.setattr("retrogaze.api._ADMIN_PASSWORD", ADMIN_PW)
        # _db_enabled defaults to False in mock mode
        resp = client.patch(
            "/admin/api/feedback/fb-1",
            json={"status": "read"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["ok"] is True

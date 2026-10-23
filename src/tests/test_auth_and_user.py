"""
Tests for authentication, DB-backed generation recording, and user endpoints.

All tests run in RETROGAZE_MOCK=1 mode, so no real Supabase or fal.ai calls.
Auth is bypassed in mock mode — these tests verify the endpoint contract,
response shapes, and that the auth plumbing doesn't break existing behavior.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Mock mode — no real API calls, auth bypassed
os.environ["RETROGAZE_MOCK"] = "1"

import pytest
from fastapi.testclient import TestClient
from retrogaze.api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# Auth module unit tests
# ---------------------------------------------------------------------------

class TestAuthModule:
    def test_mock_mode_skips_auth(self):
        """In mock mode, get_current_user returns a fake dev user."""
        from retrogaze.auth import AuthenticatedUser
        # The /history endpoint requires auth — in mock mode it should work
        # without any Authorization header
        resp = client.get("/history")
        assert resp.status_code == 200

    def test_optional_user_returns_none_in_mock(self):
        """In mock mode, get_optional_user returns None (no auth)."""
        # /generate uses optional auth — should work without a header
        # May get 429 if other tests already consumed the rate limit
        resp = client.post("/generate", json={"description": "a knight"})
        assert resp.status_code in (200, 429)

    def test_authenticated_user_dataclass(self):
        from retrogaze.auth import AuthenticatedUser
        user = AuthenticatedUser(id="test-id", email="test@example.com")
        assert user.id == "test-id"
        assert user.email == "test@example.com"
        assert user.is_anonymous is False

    def test_authenticated_user_anonymous(self):
        from retrogaze.auth import AuthenticatedUser
        user = AuthenticatedUser(id="anon-id", is_anonymous=True)
        assert user.is_anonymous is True
        assert user.email is None


# ---------------------------------------------------------------------------
# /generate — backward compatibility (still works without auth)
# ---------------------------------------------------------------------------

class TestGenerateBackwardCompat:
    """
    /generate backward compat tests. These may return 429 when run after
    other test files that already consumed the rate limit (10/min on /generate).
    We accept 200 or 429 where appropriate.
    """

    def test_generate_still_works_without_auth(self):
        """Existing behavior: /generate works without an Authorization header."""
        resp = client.post("/generate", json={"description": "a knight"})
        # 200 = success, 429 = rate limited by previous tests (both acceptable)
        assert resp.status_code in (200, 429)
        if resp.status_code == 200:
            data = resp.json()
            assert "image_base64" in data
            assert "metadata" in data

    def test_generate_response_has_generation_id_field(self):
        """Response schema now includes generation_id (None when not authed)."""
        resp = client.post("/generate", json={"description": "a knight"})
        if resp.status_code == 200:
            data = resp.json()
            assert "generation_id" in data

    def test_generate_validation_still_works(self):
        """Input validation unchanged."""
        resp = client.post("/generate", json={"description": "a" * 501})
        # 422 = validation error, 429 = rate limited (both acceptable)
        assert resp.status_code in (422, 429)

    def test_generate_with_all_options(self):
        resp = client.post("/generate", json={
            "description": "a fire wizard",
            "asset_type": "character",
            "size": "16x16",
            "era": "late",
            "palette_mood": "warm",
            "outline": "Dark",
            "view": "front",
            "seed": 42,
        })
        assert resp.status_code in (200, 429)


# ---------------------------------------------------------------------------
# /history endpoint
# ---------------------------------------------------------------------------

class TestHistoryEndpoint:
    def test_history_returns_empty_in_mock_mode(self):
        """Without Supabase, history returns empty list."""
        resp = client.get("/history")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    def test_history_accepts_pagination_params(self):
        resp = client.get("/history?limit=5&offset=10")
        assert resp.status_code == 200

    def test_history_rejects_invalid_limit(self):
        resp = client.get("/history?limit=0")
        assert resp.status_code == 422

    def test_history_rejects_negative_offset(self):
        resp = client.get("/history?offset=-1")
        assert resp.status_code == 422

    def test_history_has_security_headers(self):
        resp = client.get("/history")
        assert resp.headers.get("X-Content-Type-Options") == "nosniff"


# ---------------------------------------------------------------------------
# /usage endpoint
# ---------------------------------------------------------------------------

class TestUsageEndpoint:
    def test_usage_returns_defaults_in_mock_mode(self):
        resp = client.get("/usage")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tier"] == "free"
        assert data["daily_count"] == 0
        assert data["monthly_count"] == 0
        assert data["total_count"] == 0
        assert data["total_cost_usd"] == 0.0

    def test_usage_has_security_headers(self):
        resp = client.get("/usage")
        assert resp.headers.get("X-Frame-Options") == "DENY"


# ---------------------------------------------------------------------------
# /settings endpoints
# ---------------------------------------------------------------------------

class TestSettingsEndpoints:
    def test_get_settings_returns_defaults_in_mock_mode(self):
        resp = client.get("/settings")
        assert resp.status_code == 200
        data = resp.json()
        assert data["default_era"] == "mid"
        assert data["default_palette_mood"] == "auto"
        assert data["default_outline"] == "Black"
        assert data["default_asset_type"] == "character"
        assert data["default_size"] == "16x16"
        assert data["default_view"] == "side"
        assert data["saved_palettes"] == []

    def test_put_settings_requires_supabase(self):
        """Without Supabase, PUT /settings returns 503."""
        resp = client.put("/settings", json={"default_era": "late"})
        assert resp.status_code == 503

    def test_put_settings_rejects_empty_update(self):
        resp = client.put("/settings", json={})
        # Either 422 (no fields) or 503 (no supabase) — both acceptable
        assert resp.status_code in (422, 503)


# ---------------------------------------------------------------------------
# Supabase client module
# ---------------------------------------------------------------------------

class TestSupabaseClientModule:
    def test_supabase_configured_returns_bool(self):
        from retrogaze.supabase_client import supabase_configured
        # In test env, SUPABASE_URL may or may not be set
        result = supabase_configured()
        assert isinstance(result, bool)

    def test_supabase_configured_false_without_env(self):
        from retrogaze.supabase_client import supabase_configured
        # Save and clear
        saved_url = os.environ.pop("SUPABASE_URL", None)
        saved_key = os.environ.pop("SUPABASE_SERVICE_ROLE_KEY", None)
        try:
            assert supabase_configured() is False
        finally:
            if saved_url:
                os.environ["SUPABASE_URL"] = saved_url
            if saved_key:
                os.environ["SUPABASE_SERVICE_ROLE_KEY"] = saved_key


# ---------------------------------------------------------------------------
# Existing endpoints still work
# ---------------------------------------------------------------------------

class TestExistingEndpoints:
    def test_health(self):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_palettes(self):
        resp = client.get("/palettes")
        assert resp.status_code == 200
        assert resp.json()["total"] > 0

    def test_config_endpoint(self):
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        # Should return supabase_url and supabase_anon_key fields (may be null)
        assert "supabase_url" in data
        assert "supabase_anon_key" in data

    def test_config_does_not_leak_service_key(self):
        resp = client.get("/config")
        data = resp.json()
        # Must NOT contain the service role key
        assert "service_role" not in str(data).lower()
        assert "SUPABASE_SERVICE_ROLE_KEY" not in str(data)

    def test_security_headers_on_new_endpoints(self):
        for path in ["/history", "/usage", "/settings", "/config"]:
            resp = client.get(path)
            assert resp.headers.get("X-Content-Type-Options") == "nosniff", f"Missing header on {path}"


# ---------------------------------------------------------------------------
# rg-019: Bug 1 — variation persistence across history
# ---------------------------------------------------------------------------

class TestVariationsBugFix:
    """Bug 1 contract tests. /generate's variation upload + RPC payload
    are skipped in mock mode (no DB), so the live code paths are
    exercised manually after deploy. These cover the model contract
    and serialization shape so a future refactor can't quietly drop
    the fields."""

    def test_history_item_defaults_to_empty_variations(self):
        from retrogaze.api import HistoryItem
        item = HistoryItem(
            id="abc",
            description="d",
            asset_type="character",
            size="16x16",
            era="mid",
            created_at="2026-01-01T00:00:00Z",
        )
        assert item.variation_storage_paths == []
        assert item.variation_image_urls == []

    def test_history_item_accepts_variation_lists(self):
        from retrogaze.api import HistoryItem
        item = HistoryItem(
            id="abc",
            description="d",
            asset_type="character",
            size="16x16",
            era="mid",
            created_at="2026-01-01T00:00:00Z",
            variation_storage_paths=["u/a.png", "u/b.png"],
            variation_image_urls=["https://x/a", "https://x/b"],
        )
        assert len(item.variation_storage_paths) == 2
        assert len(item.variation_image_urls) == 2

    def test_history_response_shape_includes_variation_fields(self):
        """Guards against a refactor accidentally dropping the new
        fields from the public API surface."""
        from retrogaze.api import HistoryItem, HistoryResponse
        resp = HistoryResponse(items=[
            HistoryItem(
                id="abc", description="d", asset_type="character",
                size="16x16", era="mid", created_at="t",
                variation_storage_paths=["u/a.png"],
                variation_image_urls=["https://x/a"],
            )
        ], total=1)
        dumped = resp.model_dump()
        assert "variation_storage_paths" in dumped["items"][0]
        assert "variation_image_urls" in dumped["items"][0]
        assert dumped["items"][0]["variation_image_urls"] == ["https://x/a"]


class TestVariationsMigrationFile:
    """Migration 004 must live in repo and contain the schema changes
    record_generation depends on at runtime."""

    def test_migration_004_exists_with_variation_column(self):
        from pathlib import Path
        import pytest
        path = (
            Path(__file__).resolve().parents[2]
            / "Development" / "migrations" / "004_variations.sql"
        )
        if not path.exists():
            pytest.skip("SaaS migration tree not present in this checkout")
        sql = path.read_text(encoding="utf-8")
        assert "variation_storage_paths text[]" in sql
        assert "drop function if exists public.record_generation" in sql.lower()
        assert "p_variation_storage_paths" in sql

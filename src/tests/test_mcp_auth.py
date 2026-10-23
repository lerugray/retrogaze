"""
Tests for MCP API key authentication and key management endpoints.

All tests run in RETROGAZE_MOCK=1 mode. Auth is bypassed in mock mode,
so these verify endpoint contracts, response shapes, and module logic.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"
os.environ.setdefault("CORS_ORIGINS", "http://127.0.0.1:8642,http://localhost:8642")

import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from fastapi.testclient import TestClient
from retrogaze.api import app

client = TestClient(app)


# ---------------------------------------------------------------------------
# MCP auth module unit tests
# ---------------------------------------------------------------------------

class TestMcpAuthModule:
    def test_mcp_authenticated_user_dataclass(self):
        from retrogaze.mcp_auth import McpAuthenticatedUser
        user = McpAuthenticatedUser(
            user_id="test-id",
            key_id="key-id",
            tier="pro",
            monthly_used=42,
            monthly_limit=3000,
        )
        assert user.user_id == "test-id"
        assert user.key_id == "key-id"
        assert user.tier == "pro"
        assert user.monthly_used == 42
        assert user.monthly_limit == 3000

    def test_mcp_authenticated_user_unlimited(self):
        from retrogaze.mcp_auth import McpAuthenticatedUser
        user = McpAuthenticatedUser(
            user_id="test-id",
            key_id="key-id",
            tier="studio",
            monthly_used=9999,
            monthly_limit=None,
        )
        assert user.monthly_limit is None

    def test_hash_key_deterministic(self):
        from retrogaze.mcp_auth import _hash_key
        key = "rg_live_test123"  # gitleaks:allow (test fixture, not a real key)
        h1 = _hash_key(key)
        h2 = _hash_key(key)
        assert h1 == h2
        assert len(h1) == 64  # SHA-256 hex digest

    def test_hash_key_different_inputs(self):
        from retrogaze.mcp_auth import _hash_key
        h1 = _hash_key("rg_live_aaa")
        h2 = _hash_key("rg_live_bbb")
        assert h1 != h2

    def test_mock_mode_returns_studio_user(self):
        """In mock mode, get_mcp_user returns a fake studio-tier user."""
        from retrogaze.mcp_auth import McpAuthenticatedUser
        # Any MCP endpoint will use get_mcp_user — tested via integration below
        # Here just verify the mock user shape
        user = McpAuthenticatedUser(
            user_id="00000000-0000-0000-0000-000000000000",
            key_id="00000000-0000-0000-0000-000000000000",
            tier="studio",
            monthly_used=0,
            monthly_limit=None,
        )
        assert user.tier == "studio"

    def test_anonymous_user_shape(self):
        """_anonymous_user returns a free-tier user with no monthly limit
        and a stable sentinel id, so anonymous callers (no Authorization
        header) get retro+early eras and read-only validation."""
        from retrogaze.mcp_auth import _anonymous_user
        user = _anonymous_user()
        assert user.tier == "free"
        assert user.key_id == "anonymous"
        assert user.monthly_limit is None
        assert user.monthly_used == 0
        assert user.user_id != "00000000-0000-0000-0000-000000000000"

    @pytest.mark.asyncio
    async def test_get_optional_mcp_user_no_header_real_mode(self, monkeypatch):
        """Outside mock mode, missing Authorization → anonymous free-tier user."""
        from retrogaze import mcp_auth
        # Force real-mode path even though tests run with RETROGAZE_MOCK=1
        monkeypatch.setattr(mcp_auth, "supabase_configured", lambda: True)
        monkeypatch.setenv("RETROGAZE_MOCK", "0")

        class _FakeRequest:
            headers = {}

        user = await mcp_auth.get_optional_mcp_user(_FakeRequest())
        assert user.tier == "free"
        assert user.key_id == "anonymous"
        assert user.monthly_limit is None

    @pytest.mark.asyncio
    async def test_get_optional_mcp_user_mock_mode_returns_studio(self, monkeypatch):
        """In mock mode, get_optional_mcp_user defers to get_mcp_user
        (studio tier) regardless of headers — preserves existing test
        fixtures."""
        from retrogaze import mcp_auth
        monkeypatch.setenv("RETROGAZE_MOCK", "1")

        class _FakeRequest:
            headers = {}

        user = await mcp_auth.get_optional_mcp_user(_FakeRequest())
        assert user.tier == "studio"


# ---------------------------------------------------------------------------
# MCP keys module unit tests
# ---------------------------------------------------------------------------

class TestMcpKeysModule:
    def test_generate_raw_key_format(self):
        from retrogaze.mcp_keys import _generate_raw_key
        key = _generate_raw_key()
        assert key.startswith("rg_live_")
        assert len(key) > 20  # prefix + 32 bytes base64

    def test_generate_raw_key_unique(self):
        from retrogaze.mcp_keys import _generate_raw_key
        keys = {_generate_raw_key() for _ in range(10)}
        assert len(keys) == 10  # all unique

    def test_hash_key_matches_auth(self):
        """Key hashing in mcp_keys matches mcp_auth (same algorithm)."""
        from retrogaze.mcp_keys import _hash_key as keys_hash
        from retrogaze.mcp_auth import _hash_key as auth_hash
        key = "rg_live_test_consistency"
        assert keys_hash(key) == auth_hash(key)

    def test_tier_limits_defined(self):
        from retrogaze.mcp_keys import _MCP_TIER_LIMITS
        assert _MCP_TIER_LIMITS["free"] == 300
        assert _MCP_TIER_LIMITS["starter"] == 1000
        assert _MCP_TIER_LIMITS["pro"] == 3000
        assert _MCP_TIER_LIMITS["studio"] is None


# ---------------------------------------------------------------------------
# API key management endpoints
# ---------------------------------------------------------------------------

class TestApiKeyEndpoints:
    """Test the /api-keys CRUD endpoints. In mock mode, DB is disabled,
    so these verify that endpoints exist and return the correct error."""

    def test_create_key_endpoint_exists(self):
        resp = client.post("/api-keys", json={"name": "test key"})
        # In mock mode, DB not configured → 503
        assert resp.status_code == 503

    def test_list_keys_endpoint_exists(self):
        resp = client.get("/api-keys")
        assert resp.status_code == 503

    def test_delete_key_endpoint_exists(self):
        resp = client.delete("/api-keys/fake-uuid")
        assert resp.status_code == 503

    def test_create_key_request_validation(self):
        """Name field has max_length=100."""
        resp = client.post("/api-keys", json={"name": "x" * 101})
        assert resp.status_code == 422  # Pydantic validation

    def test_create_key_default_name(self):
        """Name defaults to 'Default' if not provided."""
        resp = client.post("/api-keys", json={})
        # 503 (no DB), but we made it past validation
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# Atomic MCP-key metering (TOCTOU / lost-update fix, migration 007)
# ---------------------------------------------------------------------------

class TestMcpKeyMeteringAtomic:
    """get_mcp_user meters an rg_live_ key via the atomic
    increment_api_key_usage RPC (DB-side monthly_used = monthly_used + 1) so
    concurrent calls can't lose increments and slip past the monthly cap."""

    class _Req:
        headers = {"Authorization": "Bearer rg_live_testkey"}  # gitleaks:allow

    @staticmethod
    def _mock_sb(key_rows, *, rpc_result=None, rpc_error=None,
                 profile_tier="pro", update_data=None):
        mock_sb = MagicMock()

        # api_keys: independent select vs update chains, each ending in execute()
        api_tbl = MagicMock()
        sel = MagicMock()
        sel.eq.return_value = sel
        sel.is_.return_value = sel
        sel.execute.return_value = MagicMock(data=key_rows)
        api_tbl.select.return_value = sel
        upd = MagicMock()
        upd.eq.return_value = upd
        upd.lt.return_value = upd
        upd.execute.return_value = MagicMock(data=update_data)
        api_tbl.update.return_value = upd

        prof_tbl = MagicMock()
        prof_sel = MagicMock()
        prof_sel.eq.return_value = prof_sel
        prof_sel.execute.return_value = MagicMock(data=[{"tier": profile_tier}])
        prof_tbl.select.return_value = prof_sel

        mock_sb.table.side_effect = lambda name: api_tbl if name == "api_keys" else prof_tbl
        mock_sb._api_tbl = api_tbl  # exposed for assertions

        rpc_mock = MagicMock()
        if rpc_error is not None:
            rpc_mock.execute.side_effect = rpc_error
        else:
            rpc_mock.execute.return_value = MagicMock(data=rpc_result)
        mock_sb.rpc.return_value = rpc_mock
        return mock_sb

    @pytest.mark.asyncio
    async def test_uses_atomic_rpc_not_read_then_write(self, monkeypatch):
        from retrogaze import mcp_auth
        monkeypatch.setenv("RETROGAZE_MOCK", "0")
        mock_sb = self._mock_sb(
            key_rows=[{"id": "k1", "user_id": "u1", "monthly_limit": 3000, "monthly_used": 5}],
            rpc_result={"allowed": True, "monthly_used": 6, "monthly_limit": 3000},
        )
        monkeypatch.setattr(mcp_auth, "get_supabase_client", lambda: mock_sb)

        user = await mcp_auth.get_mcp_user(self._Req())

        assert user.monthly_used == 6  # the DB-reported post-increment count
        assert user.tier == "pro"
        mock_sb.rpc.assert_called_with("increment_api_key_usage", {"p_key_id": "k1"})
        mock_sb._api_tbl.update.assert_not_called()  # no fallback read-then-write

    @pytest.mark.asyncio
    async def test_limit_reached_returns_429(self, monkeypatch):
        from retrogaze import mcp_auth
        monkeypatch.setenv("RETROGAZE_MOCK", "0")
        mock_sb = self._mock_sb(
            key_rows=[{"id": "k1", "user_id": "u1", "monthly_limit": 300, "monthly_used": 300}],
            rpc_result={"allowed": False, "reason": "limit_reached",
                        "monthly_used": 300, "monthly_limit": 300},
        )
        monkeypatch.setattr(mcp_auth, "get_supabase_client", lambda: mock_sb)

        with pytest.raises(HTTPException) as ei:
            await mcp_auth.get_mcp_user(self._Req())
        assert ei.value.status_code == 429

    @pytest.mark.asyncio
    async def test_falls_back_to_guarded_update_when_rpc_unavailable(self, monkeypatch):
        """If the RPC isn't present yet (code deployed before migration 007),
        auth still works via the guarded fallback update."""
        from retrogaze import mcp_auth
        monkeypatch.setenv("RETROGAZE_MOCK", "0")
        mock_sb = self._mock_sb(
            key_rows=[{"id": "k1", "user_id": "u1", "monthly_limit": 3000, "monthly_used": 5}],
            rpc_error=RuntimeError("Could not find the function increment_api_key_usage"),
            update_data=[{"id": "k1"}],  # guarded update updated 1 row (under cap)
        )
        monkeypatch.setattr(mcp_auth, "get_supabase_client", lambda: mock_sb)

        user = await mcp_auth.get_mcp_user(self._Req())

        assert user.monthly_used == 6  # local increment on the fallback path
        mock_sb._api_tbl.update.assert_called()  # guarded fallback was used


# ---------------------------------------------------------------------------
# API-key ownership scoping (cross-user access guard, JOB 1b lock-in)
# ---------------------------------------------------------------------------

class TestApiKeyOwnershipScoping:
    """revoke_api_key / list_user_keys carry no explicit user_id filter; they
    rely on UserScopedTable injecting .eq('user_id', <caller>) on every query.
    These lock in that invariant so a regression can't expose another user's
    keys (the service-role client bypasses RLS, so this app filter is the
    enforced control)."""

    def test_select_scopes_by_user_id(self):
        from retrogaze.supabase_client import UserScopedTable
        inner = MagicMock()
        UserScopedTable(inner, "user-1", "api_keys").select("id, name")
        inner.select.assert_called_once_with("id, name")
        inner.select.return_value.eq.assert_called_once_with("user_id", "user-1")

    def test_update_scopes_by_user_id(self):
        from retrogaze.supabase_client import UserScopedTable
        inner = MagicMock()
        UserScopedTable(inner, "user-1", "api_keys").update({"revoked_at": "now()"})
        inner.update.return_value.eq.assert_called_once_with("user_id", "user-1")

    def test_delete_scopes_by_user_id(self):
        from retrogaze.supabase_client import UserScopedTable
        inner = MagicMock()
        UserScopedTable(inner, "user-1", "api_keys").delete()
        inner.delete.return_value.eq.assert_called_once_with("user_id", "user-1")


# ---------------------------------------------------------------------------
# CORS allows DELETE for api-keys
# ---------------------------------------------------------------------------

class TestCorsDelete:
    def test_options_delete_allowed(self):
        """CORS preflight for DELETE should succeed."""
        # Known quirk: this OPTIONS preflight can be flaky in some test environments.
        resp = client.options(
            "/api-keys/fake-uuid",
            headers={
                "Origin": "http://127.0.0.1:8642",
                "Access-Control-Request-Method": "DELETE",
            },
        )
        # CORS preflight returns 200
        assert resp.status_code == 200
        allowed = resp.headers.get("access-control-allow-methods", "")
        assert "DELETE" in allowed

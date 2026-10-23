"""
Tests for the /v1 API-versioning allowlist (src/retrogaze/api.py).

/v1 is a pre-routing path rewrite applied ONLY to the (method, path) pairs
named in ``_V1_ALLOWLIST``. These tests pin three properties:

1. The allowlist is exactly the intended public API surface.
2. Money, credential and privileged surfaces are structurally unreachable
   under /v1 — enforced by a sweep over EVERY registered route, so a route
   added later is covered without touching this file, plus a direct test that
   the import-time guard raises on a violating allowlist edit.
3. A /v1 URL behaves identically to its unversioned original — same response,
   same rate-limit headers, same rate-limit bucket.

All tests run in RETROGAZE_MOCK=1 mode.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import retrogaze.api as api
from retrogaze.api import app
from retrogaze.mcp_routes import limiter as mcp_limiter

client = TestClient(app)


# The surface this feature is allowed to expose. Written out literally rather
# than derived from the source constant, so an edit to _V1_ALLOWLIST that was
# not intended by a reviewer fails this test.
EXPECTED_ALLOWLIST = [
    ("POST", "/generate"),
    ("POST", "/mcp/prompt"),
    ("POST", "/mcp/validate"),
    ("GET", "/mcp/palettes"),
    ("GET", "/mcp/status"),
]

# Paths that must never be reachable under /v1, whatever the allowlist says.
FORBIDDEN_PATHS = [
    ("POST", "/v1/checkout"),
    ("POST", "/v1/webhooks/lemonsqueezy"),
    ("POST", "/v1/webhooks/resend"),
    ("POST", "/v1/webhooks/postmark"),
    ("GET", "/v1/subscription"),
    ("POST", "/v1/billing-portal"),
    ("DELETE", "/v1/account"),
    ("GET", "/v1/account/export"),
    ("POST", "/v1/api-keys"),
    ("GET", "/v1/api-keys"),
    ("DELETE", "/v1/api-keys/abc"),
    ("POST", "/v1/auth/reset-password"),
    ("POST", "/v1/auth/resend-confirmation"),
    ("GET", "/v1/admin"),
    ("GET", "/v1/admin/api/stats"),
    ("GET", "/v1/admin/api/funnel"),
    ("POST", "/v1/admin/api/suppressions/remove"),
    ("GET", "/v1/config"),
    ("GET", "/v1/history"),
    ("GET", "/v1/usage"),
    ("GET", "/v1/settings"),
    ("POST", "/v1/consent/accept"),
]


def _all_registered_paths() -> set[tuple[str, str]]:
    """Every (METHOD, path) the app serves, including mounted routers."""
    found: set[tuple[str, str]] = set()
    for route in app.routes:
        if isinstance(route, APIRoute):
            for method in route.methods or ():
                found.add((method.upper(), route.path))
    for prefix, mounted in api._MOUNTED_ROUTERS:
        for route in mounted.routes:
            if isinstance(route, APIRoute):
                for method in route.methods or ():
                    found.add((method.upper(), prefix + route.path))
    return found


# ---------------------------------------------------------------------------
# The allowlist itself
# ---------------------------------------------------------------------------

class TestAllowlistContents:
    def test_allowlist_is_exactly_the_intended_surface(self):
        actual = [(m.upper(), p) for m, p in api._V1_ALLOWLIST]
        assert actual == EXPECTED_ALLOWLIST

    def test_exposed_paths_match_the_allowlist(self):
        assert api.V1_ALIAS_PATHS == [
            "/v1/generate",
            "/v1/mcp/prompt",
            "/v1/mcp/validate",
            "/v1/mcp/palettes",
            "/v1/mcp/status",
        ]

    def test_no_allowlist_entry_touches_a_forbidden_prefix(self):
        for method, path in api._V1_ALLOWLIST:
            for forbidden in api._V1_FORBIDDEN_PREFIXES:
                assert not (path == forbidden or path.startswith(forbidden + "/")), (
                    f"{method} {path} is on the /v1 allowlist but matches the "
                    f"forbidden prefix {forbidden}"
                )

    def test_every_allowlist_entry_names_a_real_route(self):
        registered = _all_registered_paths()
        for method, path in api._V1_ALLOWLIST:
            assert (method.upper(), path) in registered

    def test_billing_and_credential_prefixes_are_declared_forbidden(self):
        # The guard is only as good as its list; pin the load-bearing entries.
        for required in ("/checkout", "/webhooks", "/subscription",
                         "/billing-portal", "/auth", "/account", "/admin",
                         "/api-keys"):
            assert required in api._V1_FORBIDDEN_PREFIXES


# ---------------------------------------------------------------------------
# The import-time guard: a bad allowlist edit must fail loudly
# ---------------------------------------------------------------------------

class TestAllowlistGuardFailsLoudly:
    @pytest.mark.parametrize("bad_entry", [
        ("POST", "/checkout"),
        ("POST", "/webhooks/lemonsqueezy"),
        ("GET", "/subscription"),
        ("POST", "/billing-portal"),
        ("DELETE", "/account"),
        ("POST", "/api-keys"),
        ("POST", "/auth/reset-password"),
        ("GET", "/admin/api/stats"),
    ])
    def test_forbidden_entry_raises(self, monkeypatch, bad_entry):
        """Adding a money/credential surface to the allowlist must refuse to
        start the app, not silently mint a second URL for it."""
        monkeypatch.setattr(api, "_V1_ALLOWLIST", api._V1_ALLOWLIST + (bad_entry,))
        with pytest.raises(RuntimeError, match="forbidden prefix"):
            api._validate_v1_allowlist()

    def test_unknown_route_entry_raises(self, monkeypatch):
        monkeypatch.setattr(
            api, "_V1_ALLOWLIST", api._V1_ALLOWLIST + (("POST", "/not-a-route"),)
        )
        with pytest.raises(RuntimeError, match="does not match any"):
            api._validate_v1_allowlist()

    def test_duplicate_entry_raises(self, monkeypatch):
        monkeypatch.setattr(
            api, "_V1_ALLOWLIST", api._V1_ALLOWLIST + (("POST", "/generate"),)
        )
        with pytest.raises(RuntimeError, match="duplicate"):
            api._validate_v1_allowlist()

    def test_current_allowlist_validates_clean(self):
        assert api._validate_v1_allowlist() == api.V1_ALIAS_PATHS


# ---------------------------------------------------------------------------
# Exclusion — nothing outside the allowlist is reachable under /v1
# ---------------------------------------------------------------------------

class TestForbiddenSurfacesAreUnreachable:
    @pytest.mark.parametrize("method,path", FORBIDDEN_PATHS)
    def test_named_forbidden_path_404s(self, method, path):
        resp = client.request(method, path)
        assert resp.status_code == 404, (
            f"{method} {path} is reachable ({resp.status_code}) — a billing, "
            f"credential or privileged surface gained a /v1 URL"
        )

    def test_every_unallowlisted_route_404s_under_v1(self):
        """Structural sweep: for EVERY route the app registers, /v1/<path> must
        404 unless that exact (method, path) is on the allowlist. A route added
        later is covered automatically."""
        allowed = {(m.upper(), p) for m, p in api._V1_ALLOWLIST}
        leaks = []
        for method, path in sorted(_all_registered_paths()):
            if (method, path) in allowed:
                continue
            if method in ("HEAD", "OPTIONS"):
                continue
            # Substitute a value for path params so the URL is well-formed.
            concrete = path
            while "{" in concrete:
                start = concrete.index("{")
                end = concrete.index("}", start)
                concrete = concrete[:start] + "x" + concrete[end + 1:]
            resp = client.request(method, "/v1" + concrete)
            if resp.status_code != 404:
                leaks.append((method, "/v1" + concrete, resp.status_code))
        assert not leaks, f"non-allowlisted routes reachable under /v1: {leaks}"

    @pytest.mark.parametrize("method", ["GET", "PUT", "DELETE", "PATCH"])
    def test_wrong_method_on_allowlisted_path_404s(self, method):
        # /generate is POST-only on the allowlist; other verbs must not rewrite.
        assert client.request(method, "/v1/generate").status_code == 404

    def test_unknown_v1_path_404s(self):
        assert client.get("/v1/nope").status_code == 404
        assert client.get("/v1/").status_code == 404


# ---------------------------------------------------------------------------
# Parity — /v1 behaves identically to the unversioned original
# ---------------------------------------------------------------------------

class TestUnversionedOriginalsStillWork:
    def test_originals_unchanged(self):
        assert client.get("/mcp/status").status_code == 200
        assert client.get("/mcp/palettes?console=nes").status_code == 200
        assert client.post("/mcp/prompt", json={"description": "a warrior"}).status_code == 200


class TestV1Parity:
    def test_mcp_status_parity(self):
        a = client.get("/mcp/status")
        b = client.get("/v1/mcp/status")
        assert a.status_code == b.status_code == 200
        assert a.json() == b.json()

    def test_mcp_palettes_parity(self):
        a = client.get("/mcp/palettes?console=nes")
        b = client.get("/v1/mcp/palettes?console=nes")
        assert a.status_code == b.status_code == 200
        assert a.json() == b.json()

    def test_mcp_prompt_parity(self):
        body = {"description": "a warrior", "console": "nes", "era": "retro"}
        a = client.post("/mcp/prompt", json=body)
        b = client.post("/v1/mcp/prompt", json=body)
        assert a.status_code == b.status_code == 200
        assert a.json().keys() == b.json().keys()

    def test_mcp_validate_reaches_the_same_handler(self):
        # Empty body -> 422 from the same request model on both URLs.
        assert client.post("/mcp/validate", json={}).status_code == 422
        assert client.post("/v1/mcp/validate", json={}).status_code == 422

    def test_security_headers_apply_to_v1(self):
        resp = client.get("/v1/mcp/status")
        assert resp.headers["X-Content-Type-Options"] == "nosniff"
        assert resp.headers["X-Frame-Options"] == "DENY"
        # API surfaces are marked noindex; the /v1 alias must be too.
        assert resp.headers.get("X-Robots-Tag") == "noindex, nofollow"


# ---------------------------------------------------------------------------
# Rate limiting — headers AND bucket must be identical, not merely present
# ---------------------------------------------------------------------------

class TestV1RateLimiting:
    def test_v1_mcp_prompt_gets_rate_limit_headers(self):
        mcp_limiter._storage.reset()
        resp = client.post("/v1/mcp/prompt", json={"description": "a warrior"})
        assert resp.status_code == 200
        assert resp.headers["X-RateLimit-Limit"] == "30"
        assert "X-RateLimit-Remaining" in resp.headers
        assert "X-RateLimit-Reset" in resp.headers

    def test_v1_and_unversioned_share_one_rate_limit_bucket(self):
        """The versioned URL must not hand a caller a second allowance.

        slowapi keys its counters on the request path, so this is exactly the
        regression that duplicate /v1 route objects would introduce.
        """
        mcp_limiter._storage.reset()
        body = {"description": "a warrior"}
        remaining = []
        for path in ["/mcp/prompt", "/mcp/prompt", "/v1/mcp/prompt",
                     "/v1/mcp/prompt", "/mcp/prompt"]:
            resp = client.post(path, json=body)
            assert resp.status_code == 200
            remaining.append(resp.headers["X-RateLimit-Remaining"])
        assert remaining == ["29", "28", "27", "26", "25"], (
            f"counter did not decrease monotonically across both URLs: {remaining}"
        )

    def test_generate_rate_limit_headers_and_bucket_are_shared(self):
        from retrogaze.api import limiter as app_limiter
        app_limiter._storage.reset()
        gen = {"description": "a warrior", "console": "nes", "era": "retro",
               "asset_type": "character", "size": "16x16"}
        first = client.post("/generate", json=gen)
        second = client.post("/v1/generate", json=gen)
        assert first.status_code == second.status_code == 200
        assert first.headers["X-RateLimit-Limit"] == second.headers["X-RateLimit-Limit"]
        assert first.headers["X-RateLimit-Remaining"] == "29"
        assert second.headers["X-RateLimit-Remaining"] == "28"

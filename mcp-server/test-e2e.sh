#!/usr/bin/env bash
# End-to-end test for Retrogaze MCP server
# Tests: build, API connectivity, auth rejection, and (if key set) full tool flow
#
# Usage:
#   ./test-e2e.sh                          # basic tests (no auth)
#   RETROGAZE_LICENSE_KEY=rg_... ./test-e2e.sh  # full test with API key

set -euo pipefail

API_URL="${RETROGAZE_API_URL:-https://retrogazeai.com}"
PASS=0
FAIL=0
SKIP=0

# Resolve a Python interpreter for the JSON helpers below. Modern macOS /
# Linux ship only `python3` (the bare `python` alias was dropped), so probing
# for both keeps the gate portable. If neither exists, JSON-dependent checks
# are skipped rather than reported as false failures.
PYTHON=""
if command -v python3 > /dev/null 2>&1; then
  PYTHON="python3"
elif command -v python > /dev/null 2>&1; then
  PYTHON="python"
fi

# NOTE: use PASS=$((PASS+1)) not ((PASS++)). Under `set -e`, the arithmetic
# command ((PASS++)) returns exit status 1 when PASS is 0 (post-increment
# yields the pre-increment value of 0, and a zero arithmetic result is a
# "false" exit status), which aborts the whole script after the first pass.
pass() { echo "  PASS: $1"; PASS=$((PASS+1)); }
fail() { echo "  FAIL: $1"; FAIL=$((FAIL+1)); }
skip() { echo "  SKIP: $1"; SKIP=$((SKIP+1)); }

echo "=== Retrogaze MCP Server — End-to-End Tests ==="
echo "API: $API_URL"
echo ""

# ── 1. Build ──────────────────────────────────────────────────────
echo "--- Build ---"
cd "$(dirname "$0")"

if npm run build > /dev/null 2>&1; then
  pass "TypeScript compiles cleanly"
else
  fail "TypeScript build failed"
fi

if [ -f dist/index.js ]; then
  pass "dist/index.js exists"
else
  fail "dist/index.js missing after build"
fi

# ── 2. API Connectivity (no auth needed) ──────────────────────────
echo ""
echo "--- API Connectivity ---"

HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/mcp/palettes" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  pass "GET /mcp/palettes returns 200"
else
  fail "GET /mcp/palettes returned $HTTP_CODE (expected 200)"
fi

# Verify palette response has expected structure
PALETTE_JSON=$(curl -s "$API_URL/mcp/palettes" 2>/dev/null || echo "{}")
if echo "$PALETTE_JSON" | grep -q "nes_palette"; then
  pass "Palettes response contains nes_palette"
else
  fail "Palettes response missing nes_palette"
fi

if echo "$PALETTE_JSON" | grep -q "presets"; then
  pass "Palettes response contains presets"
else
  fail "Palettes response missing presets"
fi

if echo "$PALETTE_JSON" | grep -q "moods"; then
  pass "Palettes response contains moods"
else
  fail "Palettes response missing moods"
fi

# Count palette colors (56 for NES 2C02 including duplicate blacks)
if [ -n "$PYTHON" ]; then
  COLOR_COUNT=$(echo "$PALETTE_JSON" | "$PYTHON" -c "import json,sys; print(len(json.load(sys.stdin)['nes_palette']))" 2>/dev/null || echo "0")
  if [ "$COLOR_COUNT" -ge 54 ] && [ "$COLOR_COUNT" -le 56 ]; then
    pass "NES palette has $COLOR_COUNT colors (expected 54-56)"
  else
    fail "NES palette has $COLOR_COUNT colors (expected 54-56)"
  fi
else
  skip "NES palette color count (no python interpreter found)"
fi

# ── 3. Endpoint Contract (public vs protected) ───────────────────
echo ""
echo "--- Endpoint Contract ---"

# Intended contract (derived from src/retrogaze/mcp_routes.py + mcp_auth.py):
#
#   PUBLIC endpoints — usable anonymously, no license key required:
#     GET /mcp/palettes  (no auth dependency at all; reference data)
#     GET /mcp/status    (get_optional_mcp_user -> anonymous = free tier 200)
#
#   PROTECTED endpoints — the work endpoints. They accept anonymous callers
#   as free tier, but reject privileged/invalid requests with a CLEAN 4xx
#   (never a raw 500):
#     POST /mcp/prompt   -> 403 when an anonymous (free) caller asks for a
#                           paid-only era (mid/late). Era gating enforced
#                           by _check_era_access().
#     POST /mcp/validate -> 422 when the supplied image_base64 decodes to
#                           bytes that are not a parseable image.
#
# Earlier this phase expected 401 across the board; that was wrong for the
# current design, which intentionally lets MCP clients use the service on
# their own Claude subscription without a separate license key. The bar is
# "rejects bad/over-privileged input with a clean 4xx", not "demands a key".

# /mcp/status is public — anonymous callers get a 200 (free tier).
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$API_URL/mcp/status" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" = "200" ]; then
  pass "GET /mcp/status returns 200 anonymously (public, free tier)"
else
  fail "GET /mcp/status returned $HTTP_CODE (expected 200)"
fi

# /mcp/prompt is protected — anonymous request for a paid era is a clean 403.
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d '{"description":"test","asset_type":"character","era":"mid"}' \
  "$API_URL/mcp/prompt" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" -ge 400 ] && [ "$HTTP_CODE" -lt 500 ]; then
  pass "POST /mcp/prompt rejects paid-era anon request with clean 4xx ($HTTP_CODE)"
else
  fail "POST /mcp/prompt returned $HTTP_CODE (expected 4xx, ideally 403)"
fi

# /mcp/validate is protected — well-formed base64 that is not a real image
# must reject with a clean 4xx (422), never a raw 500.
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X POST \
  -H "Content-Type: application/json" \
  -d '{"image_base64":"dGVzdA==","asset_type":"sprite"}' \
  "$API_URL/mcp/validate" 2>/dev/null || echo "000")
if [ "$HTTP_CODE" -ge 400 ] && [ "$HTTP_CODE" -lt 500 ]; then
  pass "POST /mcp/validate rejects non-image input with clean 4xx ($HTTP_CODE)"
else
  fail "POST /mcp/validate returned $HTTP_CODE (expected 4xx, ideally 422; a 500 means the hardening fix is not deployed)"
fi

# ── 4. Authenticated Tests (only if key is set) ──────────────────
echo ""
echo "--- Authenticated Tests ---"

if [ -n "${RETROGAZE_LICENSE_KEY:-}" ]; then
  AUTH_HEADER="Authorization: Bearer $RETROGAZE_LICENSE_KEY"

  # Status endpoint
  STATUS_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH_HEADER" "$API_URL/mcp/status" 2>/dev/null || echo "000")
  if [ "$STATUS_CODE" = "200" ]; then
    pass "GET /mcp/status returns 200 with valid key"
    STATUS_JSON=$(curl -s -H "$AUTH_HEADER" "$API_URL/mcp/status" 2>/dev/null)
    if [ -n "$PYTHON" ]; then
      echo "       Tier: $(echo "$STATUS_JSON" | "$PYTHON" -c "import json,sys; print(json.load(sys.stdin).get('tier','?'))" 2>/dev/null || echo "?")"
      echo "       Usage: $(echo "$STATUS_JSON" | "$PYTHON" -c "import json,sys; d=json.load(sys.stdin); print(f\"{d.get('monthly_used',0)}/{d.get('monthly_limit','unlimited')}\")" 2>/dev/null || echo "?")"
    fi
  else
    fail "GET /mcp/status returned $STATUS_CODE with key (expected 200)"
  fi

  # Prompt endpoint
  PROMPT_CODE=$(curl -s -o /dev/null -w "%{http_code}" -H "$AUTH_HEADER" \
    -H "Content-Type: application/json" \
    -X POST -d '{"description":"a warrior with a sword","asset_type":"character","era":"mid","size":"16x16"}' \
    "$API_URL/mcp/prompt" 2>/dev/null || echo "000")
  if [ "$PROMPT_CODE" = "200" ]; then
    pass "POST /mcp/prompt returns 200 with valid key"
  else
    fail "POST /mcp/prompt returned $PROMPT_CODE with key (expected 200)"
  fi

  # MCP server startup test
  echo ""
  echo "--- MCP Server Startup ---"
  # Send initialize request via stdin, check for proper MCP response
  INIT_MSG='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"test","version":"0.1.0"}}}'

  MCP_RESPONSE=$(echo "$INIT_MSG" | timeout 5 node dist/index.js 2>/dev/null || true)
  if echo "$MCP_RESPONSE" | grep -q "retrogaze"; then
    pass "MCP server responds to initialize with server info"
  else
    fail "MCP server did not respond to initialize correctly"
  fi
else
  skip "Authenticated endpoint tests (set RETROGAZE_LICENSE_KEY to run)"
  skip "Prompt generation test (set RETROGAZE_LICENSE_KEY to run)"
  skip "MCP server startup test (set RETROGAZE_LICENSE_KEY to run)"
fi

# ── Summary ──────────────────────────────────────────────────────
echo ""
echo "=== Results ==="
echo "  Passed: $PASS"
echo "  Failed: $FAIL"
echo "  Skipped: $SKIP"

if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "Some tests failed!"
  exit 1
fi

echo ""
echo "All tests passed!"

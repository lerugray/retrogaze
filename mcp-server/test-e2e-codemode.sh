#!/usr/bin/env bash
# End-to-end test for the code-mode MCP tools (retro_code_bind / retro_code_build / retro_code_verify).
# Starts a local Retrogaze API with code mode on, builds the MCP server, and drives it with a real MCP client.
#
# Usage: ./test-e2e-codemode.sh            (needs Node >= 22.18 and the Python deps from src/requirements.txt)
#        PYTHON=/path/to/python ./test-e2e-codemode.sh

set -euo pipefail
cd "$(dirname "$0")"
REPO="$(cd .. && pwd)"
PYTHON="${PYTHON:-python3}"
PORT="${PORT:-8765}"
WORK="$(mktemp -d)"
API_PID=""
cleanup() { [ -n "$API_PID" ] && kill "$API_PID" 2>/dev/null || true; rm -rf "$WORK"; }
trap cleanup EXIT

echo "=== Retrogaze MCP code mode: end-to-end ==="
npm run build > /dev/null
echo "  PASS: TypeScript compiles cleanly"

(cd "$REPO/src" && RETROGAZE_MOCK=1 RETROGAZE_CODE_MODE=1 "$PYTHON" -m uvicorn retrogaze.api:app \
  --host 127.0.0.1 --port "$PORT" > "$WORK/api.log" 2>&1) &
API_PID=$!
for _ in $(seq 1 60); do
  curl -sf "http://127.0.0.1:$PORT/health" > /dev/null && break
  sleep 0.5
done
curl -sf "http://127.0.0.1:$PORT/health" > /dev/null || { echo "  FAIL: API did not start"; cat "$WORK/api.log"; exit 1; }
echo "  PASS: local API up with RETROGAZE_CODE_MODE=1"

cp "$REPO/examples/codemode/nes_hero.px.js" "$WORK/nes_hero.px.js"
printf 'not an image' > "$WORK/nes_hero.png"
node test-e2e-codemode.mjs "$WORK/nes_hero.px.js" "http://127.0.0.1:$PORT"
test -s "$WORK/out/nes/legal/nes/title.chr" && echo "  PASS: title.chr written next to the art"
echo "=== all code-mode MCP checks passed ==="

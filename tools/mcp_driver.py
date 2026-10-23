"""
MCP Driver for pixel-mcp server.
Reads a JSON file of tool calls, executes them sequentially, reports results.

Usage: python mcp_driver.py commands.json
"""
import sys
import json
import subprocess
import os
import threading
import time

MCP_BIN = os.path.expanduser("~/.claude/plugins/marketplaces/pixel-plugin/bin/pixel-mcp-windows-amd64.exe")
MCP_CONFIG = os.path.expanduser("~/.config/pixel-mcp/config.json")


def run_commands(commands):
    env = os.environ.copy()
    env["PIXEL_MCP_CONFIG"] = MCP_CONFIG

    proc = subprocess.Popen(
        [MCP_BIN],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )

    responses = {}
    errors = []

    def read_stdout():
        for line in proc.stdout:
            line = line.decode("utf-8", errors="replace").strip()
            if not line:
                continue
            try:
                data = json.loads(line)
                rid = data.get("id")
                if rid is not None:
                    responses[rid] = data
            except json.JSONDecodeError:
                pass

    reader = threading.Thread(target=read_stdout, daemon=True)
    reader.start()

    def send(msg):
        proc.stdin.write((json.dumps(msg) + "\n").encode("utf-8"))
        proc.stdin.flush()

    # Initialize
    send({
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "mcp-driver", "version": "1.0"},
        },
    })
    time.sleep(1)

    if 0 not in responses:
        print("ERROR: MCP server did not respond to initialize", file=sys.stderr)
        proc.terminate()
        return False

    sprite_path = None  # captured from create_canvas

    # Execute tool calls
    for i, cmd in enumerate(commands, start=1):
        tool_name = cmd["tool"]
        args = cmd.get("args", {})
        label = cmd.get("label", tool_name)

        # Replace placeholders with actual paths
        output_dir = os.path.abspath(os.path.join(os.path.dirname(sys.argv[1]), "..", "test-outputs"))
        for key, val in args.items():
            if isinstance(val, str):
                if val == "SPRITE" and sprite_path:
                    args[key] = sprite_path
                elif "OUTPUT_DIR" in val:
                    args[key] = val.replace("OUTPUT_DIR", output_dir)

        send({
            "jsonrpc": "2.0",
            "id": i,
            "method": "tools/call",
            "params": {"name": tool_name, "arguments": args},
        })

        # Wait for response (up to 60s)
        deadline = time.time() + 60
        while i not in responses and time.time() < deadline:
            time.sleep(0.2)

        if i in responses:
            resp = responses[i]
            if "error" in resp:
                err_msg = resp["error"].get("message", str(resp["error"]))
                print(f"  FAIL [{i}/{len(commands)}] {label}: {err_msg}")
                errors.append((label, err_msg))
            else:
                result = resp.get("result", {})
                # Extract text content from MCP response
                if isinstance(result, dict) and "content" in result:
                    content = result["content"]
                    if isinstance(content, list) and len(content) > 0:
                        text = content[0].get("text", "")
                        try:
                            parsed = json.loads(text)
                            # Capture sprite_path from create_canvas
                            if tool_name == "create_canvas" and "file_path" in parsed:
                                sprite_path = parsed["file_path"]
                            print(f"  OK   [{i}/{len(commands)}] {label}: {json.dumps(parsed)}")
                        except (json.JSONDecodeError, TypeError):
                            print(f"  OK   [{i}/{len(commands)}] {label}: {text[:120]}")
                    else:
                        print(f"  OK   [{i}/{len(commands)}] {label}: {result}")
                else:
                    print(f"  OK   [{i}/{len(commands)}] {label}: {result}")
        else:
            print(f"  TIMEOUT [{i}/{len(commands)}] {label}")
            errors.append((label, "timeout"))

    proc.stdin.close()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()

    if errors:
        print(f"\n{len(errors)} error(s) out of {len(commands)} commands.")
        return False
    else:
        print(f"\nAll {len(commands)} commands succeeded.")
        return True


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python mcp_driver.py commands.json")
        sys.exit(1)

    with open(sys.argv[1]) as f:
        commands = json.load(f)

    success = run_commands(commands)
    sys.exit(0 if success else 1)

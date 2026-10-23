"""Static script routes for the public frontend (referral.js removed in OSS)."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient

from retrogaze.api import app

client = TestClient(app)


def test_referral_js_is_gone():
    resp = client.get("/referral.js")
    assert resp.status_code == 404


def test_every_page_script_has_a_route():
    """Every local <script src> in a shipped public page resolves."""
    import re
    from pathlib import Path

    frontend = Path(__file__).resolve().parents[2] / "frontend"
    srcs = set()
    for page in frontend.glob("*.html"):
        if page.name.startswith("admin"):
            continue
        for src in re.findall(r'<script[^>]+src="([^"]+)"', page.read_text()):
            if not src.startswith(("http", "//")):
                srcs.add("/" + src.split("?")[0].lstrip("/"))
    assert srcs, "no local scripts found"
    for src in sorted(srcs):
        assert client.get(src).status_code == 200, src


def test_missing_static_file_is_not_cached():
    resp = client.get("/no-such-file-s187.js")
    assert resp.status_code == 404
    assert "max-age=2592000" not in resp.headers.get("cache-control", "")

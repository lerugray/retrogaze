"""
Variation persistence + history display contract (Ricky, 2026-09-11).

Reported bug: "The 4 variations don't save the extra 3 variations in
history." Root cause was ``/generate`` reading each variation's bytes from
disk *after* the ``tempfile.TemporaryDirectory()`` context had exited, so
every candidate path was already deleted and the upload loop skipped them
all. ``p_variation_storage_paths`` was therefore always ``[]`` and
``/history`` only ever had the primary image. The primary survived only
because its bytes were read into memory while the directory still existed.

The fix reads all candidate bytes inside the temp-dir block. These tests
drive the real routes with a faked Supabase client (storage + RPC) so the
upload -> record -> history path is covered without any network or DB.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

os.environ["RETROGAZE_MOCK"] = "1"

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient

from retrogaze.api import app
from retrogaze.auth import AuthenticatedUser, get_current_user, get_optional_user

TEST_USER = AuthenticatedUser(
    id="11111111-1111-1111-1111-111111111111",
    email="tester@example.com",
)


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class _Result:
    def __init__(self, data=None, count=None):
        self.data = data
        self.count = count


class _FakeTable:
    """Chainable stand-in for the supabase-py table builder."""

    def __init__(self, sb):
        self._sb = sb

    def select(self, *args, **kwargs):
        return self

    def order(self, *args, **kwargs):
        return self

    def range(self, *args, **kwargs):
        return self

    def lt(self, *args, **kwargs):
        return self

    def limit(self, *args, **kwargs):
        return self

    def execute(self):
        return _Result(data=list(self._sb.history_rows), count=len(self._sb.history_rows))


class _FakeBucket:
    def __init__(self, sb, name):
        self._sb = sb
        self._name = name

    def upload(self, path, data, opts=None):
        self._sb.uploads.append((path, data))
        if self._sb.fail_upload_number == len(self._sb.uploads):
            raise RuntimeError("simulated storage failure")
        return {"path": path}

    def create_signed_urls(self, paths, expires):
        return [
            {"path": p, "signedURL": f"https://signed.example/{p}"}
            for p in paths
        ]


class _FakeStorage:
    def __init__(self, sb):
        self._sb = sb

    def from_(self, name):
        return _FakeBucket(self._sb, name)


class _FakeRpc:
    def __init__(self, sb, name, params):
        self._sb = sb
        self.name = name
        self.params = params

    def execute(self):
        self._sb.rpc_calls.append((self.name, self.params))
        if self.name == "try_consume_generation":
            return _Result(data={"allowed": True})
        if self.name == "record_generation":
            return _Result(data="generated-uuid")
        return _Result(data=None)


class FakeSupabase:
    def __init__(self, history_rows=None):
        self.uploads = []
        self.rpc_calls = []
        self.history_rows = history_rows or []
        self.fail_upload_number = None
        self.storage = _FakeStorage(self)

    def rpc(self, name, params=None):
        return _FakeRpc(self, name, params)

    def table(self, name):
        return _FakeTable(self)

    def record_call(self):
        for name, params in self.rpc_calls:
            if name == "record_generation":
                return params
        return None


# ---------------------------------------------------------------------------
# /generate -> storage -> RPC
# ---------------------------------------------------------------------------

@pytest.fixture
def client():
    return TestClient(app)


def _run_generate(client, fake, num_candidates):
    app.dependency_overrides[get_optional_user] = lambda: TEST_USER
    try:
        with patch("retrogaze.api._db_enabled", return_value=True), patch(
            "retrogaze.supabase_client.get_supabase_client", return_value=fake
        ):
            resp = client.post(
                "/generate",
                json={
                    "description": "robe",
                    "asset_type": "item",
                    "era": "late",
                    "size": "16x16",
                    "num_candidates": num_candidates,
                },
            )
    finally:
        app.dependency_overrides.pop(get_optional_user, None)
    return resp


class TestGenerateVariationsPersistence:
    def test_multi_candidate_uploads_every_candidate_and_records_variations(self, client):
        fake = FakeSupabase()
        resp = _run_generate(client, fake, num_candidates=4)
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["candidates_base64"]) == 4

        # 1 primary + 3 variations all reach storage.
        assert len(fake.uploads) == 4

        params = fake.record_call()
        assert params is not None
        variation_paths = params["p_variation_storage_paths"]
        assert len(variation_paths) == 3
        # Every variation path is a real upload under the user's prefix.
        uploaded = {p for p, _ in fake.uploads}
        assert set(variation_paths).issubset(uploaded)
        assert all(p.startswith(TEST_USER.id + "/") for p in variation_paths)
        # The primary is recorded separately, not duplicated in variations.
        assert params["p_image_storage_path"] not in variation_paths

    def test_single_candidate_records_no_variations(self, client):
        fake = FakeSupabase()
        resp = _run_generate(client, fake, num_candidates=1)
        assert resp.status_code == 200, resp.text
        assert resp.json()["candidates_base64"] == []
        assert len(fake.uploads) == 1
        assert fake.record_call()["p_variation_storage_paths"] == []

    def test_failed_variation_upload_does_not_block_the_record(self, client):
        fake = FakeSupabase()
        # Uploads in order: 1 primary, then variations 2,3,4. Fail the 3rd
        # overall (i.e. the second variation); the other two must persist.
        fake.fail_upload_number = 3
        resp = _run_generate(client, fake, num_candidates=4)
        assert resp.status_code == 200, resp.text
        params = fake.record_call()
        assert params is not None
        assert len(params["p_variation_storage_paths"]) == 2

    def test_multi_candidate_consumes_one_quota_and_records_n_times_cost(self, client):
        """RG-069: quota stays 1; recorded COGS scales with candidates billed."""
        from retrogaze.cost_model import cost_for_model_path

        fake = FakeSupabase()
        n = 4
        resp = _run_generate(client, fake, num_candidates=n)
        assert resp.status_code == 200, resp.text

        consume_calls = [c for c in fake.rpc_calls if c[0] == "try_consume_generation"]
        assert len(consume_calls) == 1

        params = fake.record_call()
        assert params is not None
        per = cost_for_model_path(params["p_model_path"])
        assert params["p_cost_usd"] == pytest.approx(per * n)

    def test_single_candidate_records_one_times_cost(self, client):
        from retrogaze.cost_model import cost_for_model_path

        fake = FakeSupabase()
        resp = _run_generate(client, fake, num_candidates=1)
        assert resp.status_code == 200, resp.text
        params = fake.record_call()
        assert params is not None
        assert params["p_cost_usd"] == pytest.approx(
            cost_for_model_path(params["p_model_path"])
        )


# ---------------------------------------------------------------------------
# /history -> signed variation URLs
# ---------------------------------------------------------------------------

_HISTORY_ROW = {
    "id": "gen-1",
    "description": "robe",
    "asset_type": "item",
    "size": "16x16",
    "era": "late",
    "created_at": "2026-09-11T12:00:00Z",
    "image_storage_path": f"{TEST_USER.id}/primary.png",
    "variation_storage_paths": [
        f"{TEST_USER.id}/v1.png",
        f"{TEST_USER.id}/v2.png",
        f"{TEST_USER.id}/v3.png",
    ],
    "cost_usd": 0.013,
    "model_path": "schnell+image2pixel",
    "metadata_json": {},
}


def _run_history(client, fake):
    app.dependency_overrides[get_current_user] = lambda: TEST_USER
    try:
        with patch("retrogaze.api._db_enabled", return_value=True), patch(
            "retrogaze.supabase_client.get_user_client", return_value=fake
        ):
            return client.get("/history")
    finally:
        app.dependency_overrides.pop(get_current_user, None)


class TestHistoryVariationsDisplay:
    def test_history_returns_signed_urls_for_every_variation(self, client):
        fake = FakeSupabase(history_rows=[dict(_HISTORY_ROW)])
        resp = _run_history(client, fake)
        assert resp.status_code == 200, resp.text
        item = resp.json()["items"][0]
        assert item["variation_storage_paths"] == _HISTORY_ROW["variation_storage_paths"]
        assert len(item["variation_image_urls"]) == 3
        assert all(u.startswith("https://signed.example/") for u in item["variation_image_urls"])
        # Order is preserved 1:1 with the stored paths.
        assert item["variation_image_urls"] == [
            f"https://signed.example/{p}" for p in _HISTORY_ROW["variation_storage_paths"]
        ]

    def test_history_single_candidate_has_no_variations(self, client):
        row = dict(_HISTORY_ROW)
        row["variation_storage_paths"] = []
        fake = FakeSupabase(history_rows=[row])
        resp = _run_history(client, fake)
        assert resp.status_code == 200, resp.text
        item = resp.json()["items"][0]
        assert item["variation_image_urls"] == []

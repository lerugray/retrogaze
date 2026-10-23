import os
import pytest

# Ensure localhost is always in the CORS allowlist when running tests,
# regardless of any .env that sets CORS_ORIGINS to production origins.
# Must be set before any test file imports retrogaze.api (which configures
# CORSMiddleware at import time using os.environ.get("CORS_ORIGINS")).
os.environ.setdefault("CORS_ORIGINS", "http://127.0.0.1:8642,http://localhost:8642")


@pytest.fixture(autouse=True)
def reset_rate_limiter():
    """Reset the in-memory rate limiter before each test so tests don't
    accumulate request counts across the full suite."""
    from retrogaze.api import limiter
    limiter._storage.reset()
    yield

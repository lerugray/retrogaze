"""
Email-address input validation for Retrogaze's public entry points.

Signup goes through Supabase Auth, whose server-side rules reject reserved,
never-deliverable domains (RFC 2606 §3, RFC 6761) — e.g.
``funnel-test-20260930@example.com`` is refused with
``Email address ... is invalid``. Endpoints that validate emails themselves
(``/waitlist`` in ``api.py``) must mirror that behavior, or the product will
accept addresses it can never confirm while signup rejects them.

Stdlib-only so it can be imported by lightweight tests without the app's
heavy dependencies (FastAPI, Supabase, …).
"""

from __future__ import annotations

import re as _re

_EMAIL_RE = _re.compile(r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$")

# Exact names reserved by RFC 2606 §3 (example.com / .net / .org), plus the
# bare special-use TLDs from RFC 6761 (invalid, test, localhost) and
# RFC 2606 (example). None of these can ever deliver mail.
_RESERVED_EMAIL_NAMES = frozenset({
    "example.com",
    "example.net",
    "example.org",
    "test",
    "invalid",
    "localhost",
})

# Reserved special-use top-level domains. Any address under one of these —
# including subdomains like "foo.example.com" — is non-deliverable.
_RESERVED_TLDS = frozenset({"example", "invalid", "test", "localhost"})


def is_reserved_email_domain(domain: str) -> bool:
    """True if *domain* is RFC-reserved and can never deliver mail.

    Case- and trailing-dot-insensitive. Covers the reserved second-level
    names (example.com/.net/.org) and their subdomains (e.g.
    "mail.example.com"), plus the bare special-use TLDs (test, invalid,
    localhost, example) and anything beneath them (e.g. "foo.test").
    """
    d = domain.lower().rstrip(".")
    if d in _RESERVED_EMAIL_NAMES:
        return True
    # Subdomains of the reserved second-level names (RFC 2606 §3 reserves
    # the whole name, e.g. "mail.example.com" can never be registered).
    if d.endswith((".example.com", ".example.net", ".example.org")):
        return True
    tld = d.rsplit(".", 1)[-1]
    return tld in _RESERVED_TLDS


def is_valid_signup_email(email: str) -> bool:
    """Validate an email the way Supabase Auth does for signup.

    Well-formed per the shared address regex AND not on a reserved,
    never-deliverable domain. Strips surrounding whitespace and lowercases,
    mirroring ``api.join_waitlist``'s normalization.

    Rejecting reserved domains turns no valid real-world address away:
    reserved domains can never receive mail.
    """
    email = email.strip().lower()
    if not _EMAIL_RE.match(email):
        return False
    domain = email.split("@", 1)[1]
    return not is_reserved_email_domain(domain)

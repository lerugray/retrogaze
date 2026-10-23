"""
Supabase client for Retrogaze.

Provides a lazy-initialized service-role client for server-side operations
(auth validation, RPC calls, storage uploads). The client is created on
first access so the app still starts when Supabase isn't configured (local dev).
"""

from __future__ import annotations

import os
from functools import lru_cache

from typing import Any

from supabase import create_client, Client


def _get_env(name: str) -> str:
    """Return an env var or raise a clear error."""
    val = os.environ.get(name, "").strip()
    if not val:
        raise EnvironmentError(
            f"{name} is not set. Add it to .env or set the environment variable."
        )
    return val


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """
    Return a Supabase client using the service-role key.

    This client bypasses RLS — always filter by user_id in queries.
    Cached so only one client is created per process.
    """
    url = _get_env("SUPABASE_URL")
    service_key = _get_env("SUPABASE_SERVICE_ROLE_KEY")
    return create_client(url, service_key)


def supabase_configured() -> bool:
    """Return True if Supabase environment variables are set."""
    return bool(
        os.environ.get("SUPABASE_URL", "").strip()
        and os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )


_USER_SCOPE_COLUMN: dict[str, str] = {
    "profiles": "id",
    "api_keys": "user_id",
    "generations": "user_id",
    "usage_counters": "user_id",
    "user_settings": "user_id",
    "org_members": "user_id",
    "organizations": "owner_id",
}


class UserScopedTable:
    """Table query builder that always scopes by the authenticated user."""

    def __init__(self, table: Any, user_id: str, table_name: str) -> None:
        self._table = table
        self._user_id = user_id
        self._col = _USER_SCOPE_COLUMN.get(table_name, "user_id")

    def _assert_user_scope(self, data: dict[str, Any] | list[dict[str, Any]]) -> None:
        rows = data if isinstance(data, list) else [data]
        for row in rows:
            if row.get(self._col) != self._user_id:
                raise ValueError(
                    f"Insert/upsert to table missing {self._col}={self._user_id!r}"
                )

    def select(self, *args: Any, **kwargs: Any) -> Any:
        return self._table.select(*args, **kwargs).eq(self._col, self._user_id)

    def update(self, data: dict[str, Any], **kwargs: Any) -> Any:
        return self._table.update(data, **kwargs).eq(self._col, self._user_id)

    def delete(self, **kwargs: Any) -> Any:
        return self._table.delete(**kwargs).eq(self._col, self._user_id)

    def insert(self, data: dict[str, Any] | list[dict[str, Any]], **kwargs: Any) -> Any:
        self._assert_user_scope(data)
        return self._table.insert(data, **kwargs)

    def upsert(self, data: dict[str, Any] | list[dict[str, Any]], **kwargs: Any) -> Any:
        self._assert_user_scope(data)
        return self._table.upsert(data, **kwargs)


class UserScopedQuery:
    """
    Thin wrapper that enforces a user_id filter on every table query.

    Built on the service-role client (bypasses RLS as before) but makes the
    scope column mandatory at construction time.
    """

    def __init__(self, user_id: str) -> None:
        if not user_id:
            raise ValueError("user_id is required")
        self.user_id = user_id
        self._client = get_supabase_client()

    def table(self, name: str) -> UserScopedTable:
        return UserScopedTable(self._client.table(name), self.user_id, name)

    @property
    def storage(self) -> Any:
        return self._client.storage

    def rpc(self, fn: str, params: dict[str, Any] | None = None) -> Any:
        return self._client.rpc(fn, params or {})


def get_user_client(user_id: str) -> UserScopedQuery:
    """Return a user-scoped Supabase wrapper for user-owned data."""
    return UserScopedQuery(user_id)

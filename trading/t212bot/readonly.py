"""Read-only facade over T212Client.

Reporting, reconciliation and the withdrawal adviser receive this object, never
the full client, so they cannot place, modify or cancel orders. The Trading 212
public API has no withdrawal or transfer endpoint at all (official OpenAPI spec,
2026-10), so moving money out is impossible from this code base regardless.
"""
from __future__ import annotations

from .config import SafetyError

READ_METHODS = frozenset({
    "account_summary", "positions", "pending_orders", "history_orders",
    "history_transactions", "history_dividends", "exchanges", "instruments",
})


class ReadOnlyClient:
    __slots__ = ("_c",)

    def __init__(self, client):
        object.__setattr__(self, "_c", client)

    def __getattr__(self, name):
        if name not in READ_METHODS:
            raise SafetyError(f"read-only client: '{name}' is not permitted")
        return getattr(object.__getattribute__(self, "_c"), name)

    def __setattr__(self, name, value):
        raise SafetyError("read-only client is immutable")

    def __repr__(self) -> str:
        return "ReadOnlyClient(<redacted>)"

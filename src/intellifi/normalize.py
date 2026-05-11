"""Shared normalisation helpers.

Two recurring pitfalls from the v2 spec (§4.3, §5.3) live here so every
loader handles them identically:

1. Gamma returns some array fields as **stringified JSON** (``outcomes``,
   ``outcomePrices``, ``clobTokenIds``). We accept either shape.
2. Timestamps are reported in different units per endpoint (ISO / seconds /
   milliseconds). Every loader writes a single ``ts_utc`` column
   (``datetime64[ns, UTC]``) and discards the source unit.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any


def parse_array_field(x: Any) -> list:
    """Tolerate both list and stringified-JSON-list shapes returned by Gamma."""
    if x is None:
        return []
    if isinstance(x, list):
        return x
    if isinstance(x, str):
        if not x:
            return []
        return json.loads(x)
    raise TypeError(f"unexpected array field type: {type(x).__name__}")


def to_utc_from_iso(value: str | None) -> datetime | None:
    """Parse an ISO-8601 Gamma timestamp into a tz-aware UTC datetime."""
    if not value:
        return None
    # fromisoformat handles trailing 'Z' from 3.11+ on Linux, but be defensive
    s = value.replace("Z", "+00:00") if value.endswith("Z") else value
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def to_utc_from_seconds(value: int | float | None) -> datetime | None:
    """Parse a seconds-since-epoch timestamp (CLOB /prices-history, Data /trades)."""
    if value is None:
        return None
    return datetime.fromtimestamp(float(value), tz=UTC)


def to_utc_from_millis(value: int | float | None) -> datetime | None:
    """Parse a milliseconds-since-epoch timestamp (CLOB /book)."""
    if value is None:
        return None
    return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)


def safe_float(x: Any) -> float | None:
    """Best-effort float coercion that survives None and empty string."""
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def safe_bool(x: Any) -> bool | None:
    """Best-effort bool coercion."""
    if x is None:
        return None
    if isinstance(x, bool):
        return x
    if isinstance(x, str):
        if x.lower() in ("true", "1", "yes"):
            return True
        if x.lower() in ("false", "0", "no"):
            return False
    return bool(x)

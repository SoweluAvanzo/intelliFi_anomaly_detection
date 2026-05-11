"""CLOB API client: ``/prices-history`` for resolved-market price trajectories.

Notes from the v2 spec (§4.3):

* ``/prices-history.t`` is **seconds** since epoch. Always canonicalised into
  a tz-aware ``ts_utc`` column.
* The endpoint is rate-limited but unauthenticated.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import polars as pl

from . import config
from .http import get_json
from .normalize import safe_float, to_utc_from_seconds

log = logging.getLogger(__name__)


PRICES_HISTORY_DIR = config.PARQUET_DIR / "prices_history"


def fetch_prices_history(
    token_id: str,
    *,
    start_ts: int | None = None,
    end_ts: int | None = None,
    interval: str = "1h",
    fidelity: int | None = None,
) -> list[dict[str, Any]]:
    """Pull the raw ``prices-history`` series for one CLOB token id.

    ``interval`` accepts ``"1m"``, ``"1h"``, ``"6h"``, ``"1d"``, ``"max"``.
    ``fidelity`` (minutes) is honoured when ``interval`` is ``"max"``.
    """
    params: dict[str, Any] = {"market": str(token_id), "interval": interval}
    if start_ts is not None:
        params["startTs"] = int(start_ts)
    if end_ts is not None:
        params["endTs"] = int(end_ts)
    if fidelity is not None:
        params["fidelity"] = int(fidelity)
    data = get_json(f"{config.CLOB}/prices-history", params=params)
    if isinstance(data, dict) and "history" in data:
        return data.get("history", []) or []
    if isinstance(data, list):
        return data
    return []


def history_parquet_path(token_id: str) -> Path:
    return PRICES_HISTORY_DIR / f"{token_id}.parquet"


_HISTORY_SCHEMA: dict[str, pl.DataType] = {
    "token_id": pl.Utf8,
    "ts_utc": pl.Datetime("us", "UTC"),
    "price": pl.Float64,
}


def to_dataframe(rows: list[dict[str, Any]], token_id: str) -> pl.DataFrame:
    cleaned = []
    for r in rows:
        t = r.get("t") or r.get("timestamp")
        p = r.get("p") or r.get("price")
        ts = to_utc_from_seconds(t)
        price = safe_float(p)
        if ts is None or price is None:
            continue
        cleaned.append({"token_id": str(token_id), "ts_utc": ts, "price": price})
    return pl.DataFrame(cleaned, schema=_HISTORY_SCHEMA,
                        orient="row" if cleaned else None)


def fetch_and_store(
    token_id: str,
    *,
    interval: str = "1h",
    overwrite: bool = False,
) -> tuple[Path, int]:
    """Idempotent fetch + parquet write for a single token's price history."""
    PRICES_HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    path = history_parquet_path(token_id)
    if path.exists() and not overwrite:
        existing = int(pl.scan_parquet(path).select(pl.len()).collect().item())
        return path, existing

    rows = fetch_prices_history(token_id, interval=interval)
    raw_dir = config.RAW_DIR / "clob" / "prices_history"
    raw_dir.mkdir(parents=True, exist_ok=True)
    with (raw_dir / f"{token_id}.jsonl").open("w") as fh:
        fh.write(json.dumps(rows, default=str) + "\n")

    df = to_dataframe(rows, token_id)
    df.write_parquet(path, compression="zstd")
    return path, df.height

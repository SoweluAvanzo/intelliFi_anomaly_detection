"""Data API loaders: /trades and /holders, keyed by conditionId.

Empirical caps validated on 2026-05-11 against production:

* ``/trades`` — limit + offset, with a hard ceiling at offset + limit <= 5000.
  Max ``limit`` is 1000. Trades are returned newest-first. We cannot reach
  trades earlier than the most-recent ~5000 via this endpoint; the subgraph
  layer (Phase 3) will fill the gap.
* ``/holders`` — takes a **conditionId** (passing a token id 400s) and returns
  a nested-by-token shape ``[{token, holders: [...]}, ...]`` with one entry
  per outcome. ``minBalance`` must be an integer. Max effective ``limit`` is
  500 per token (so ~1000 per binary market).

Both writers persist:

* ``data/raw/data_api/{endpoint}/{condition_id}.jsonl`` — raw, replayable.
* ``data/parquet/{trades,holders}/condition_id={cid}/part.parquet`` — typed.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import polars as pl

from . import config
from .http import get_json
from .normalize import safe_float, to_utc_from_seconds

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# /trades
# ---------------------------------------------------------------------------

# Empirical API limits (probed 2026-05-11):
#   - max ``limit`` per request: 1000
#   - max ``offset``: 3000 (offset=3500+ returns HTTP 400 regardless of limit)
# So the reachable trade horizon is offset 3000 + limit 1000 = 4000 most-recent.
TRADES_MAX_OFFSET = 3000
TRADES_MAX_LIMIT = 1000
TRADES_MAX_REACHABLE = TRADES_MAX_OFFSET + TRADES_MAX_LIMIT  # 4000


def fetch_trades_page(
    condition_id: str,
    *,
    limit: int = config.TRADES_PAGE_SIZE,
    offset: int = 0,
    filter_amount: float | None = None,
) -> list[dict[str, Any]]:
    params: dict[str, Any] = {"market": condition_id, "limit": limit, "offset": offset}
    if filter_amount is not None:
        params["filterType"] = "CASH"
        params["filterAmount"] = filter_amount
    return get_json(f"{config.DATA}/trades", params=params)


def iter_trades(
    condition_id: str,
    *,
    filter_amount: float | None = None,
    page_limit: int = TRADES_MAX_LIMIT,
) -> Iterator[dict[str, Any]]:
    """Iterate up to ``TRADES_MAX_REACHABLE`` most-recent trades for a market.

    Stops cleanly at the API's offset ceiling — no defensive 400-catching
    needed in the caller.
    """
    page_size = min(page_limit, TRADES_MAX_LIMIT)
    offset = 0
    while offset <= TRADES_MAX_OFFSET:
        batch = fetch_trades_page(
            condition_id, limit=page_size, offset=offset, filter_amount=filter_amount
        )
        if not batch:
            return
        for t in batch:
            yield t
        if len(batch) < page_size:
            return
        offset += len(batch)


# Trade columns kept in parquet. The Data API returns ~20 fields per trade;
# we drop profile-image URLs and other display-only fluff but retain identity
# and economic facts.
TRADE_COLUMNS: tuple[str, ...] = (
    "condition_id", "asset_id", "outcome", "outcome_index",
    "proxy_wallet", "pseudonym", "name", "verified",
    "side", "price", "size", "notional_usdc",
    "ts_utc", "tx_hash",
    "event_slug", "market_slug", "title",
)

_TRADE_SCHEMA: dict[str, pl.DataType] = {
    "condition_id": pl.Utf8, "asset_id": pl.Utf8,
    "outcome": pl.Utf8, "outcome_index": pl.Int32,
    "proxy_wallet": pl.Utf8, "pseudonym": pl.Utf8, "name": pl.Utf8,
    "verified": pl.Boolean,
    "side": pl.Utf8, "price": pl.Float64, "size": pl.Float64,
    "notional_usdc": pl.Float64,
    "ts_utc": pl.Datetime("us", "UTC"), "tx_hash": pl.Utf8,
    "event_slug": pl.Utf8, "market_slug": pl.Utf8, "title": pl.Utf8,
}


def normalise_trade(t: dict[str, Any]) -> dict[str, Any]:
    price = safe_float(t.get("price"))
    size = safe_float(t.get("size"))
    notional = price * size if price is not None and size is not None else None
    return {
        "condition_id": t.get("conditionId"),
        "asset_id": str(t.get("asset")) if t.get("asset") is not None else None,
        "outcome": t.get("outcome"),
        "outcome_index": t.get("outcomeIndex"),
        "proxy_wallet": (t.get("proxyWallet") or "").lower() or None,
        "pseudonym": t.get("pseudonym"),
        "name": t.get("name"),
        "verified": bool(t.get("verified")) if t.get("verified") is not None else None,
        "side": t.get("side"),
        "price": price,
        "size": size,
        "notional_usdc": notional,
        "ts_utc": to_utc_from_seconds(t.get("timestamp")),
        "tx_hash": t.get("transactionHash"),
        "event_slug": t.get("eventSlug"),
        "market_slug": t.get("slug"),
        "title": t.get("title"),
    }


def trades_partition_path(condition_id: str) -> Path:
    return config.TRADES_PARQUET / f"condition_id={condition_id}" / "part.parquet"


def _raw_trades_path(condition_id: str) -> Path:
    p = config.RAW_DIR / "data_api" / "trades"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{condition_id}.jsonl"


def fetch_and_store_trades(
    condition_id: str,
    *,
    persist_raw: bool = True,
    overwrite: bool = False,
) -> tuple[Path, int]:
    """Pull (up to 5000) trades for one market, persist raw + parquet.

    Returns ``(parquet_path, row_count)``. Idempotent: if the parquet already
    exists and ``overwrite=False``, returns immediately with the existing row
    count.
    """
    out = trades_partition_path(condition_id)
    if out.exists() and not overwrite:
        existing = pl.scan_parquet(out).select(pl.len()).collect().item()
        return out, int(existing)

    raw: list[dict[str, Any]] = list(iter_trades(condition_id))
    if persist_raw and raw:
        path = _raw_trades_path(condition_id)
        with path.open("w", encoding="utf-8") as fh:
            for r in raw:
                fh.write(json.dumps(r, separators=(",", ":"), default=str))
                fh.write("\n")

    rows = [normalise_trade(t) for t in raw]
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(rows, schema=_TRADE_SCHEMA, orient="row" if rows else None)
    df.write_parquet(out, compression="zstd")
    return out, df.height


# ---------------------------------------------------------------------------
# /holders
# ---------------------------------------------------------------------------

HOLDERS_LIMIT_PER_TOKEN = 500  # empirical cap


def fetch_holders(
    condition_id: str,
    *,
    limit: int = HOLDERS_LIMIT_PER_TOKEN,
    min_balance: int = 1,
) -> list[dict[str, Any]]:
    """Raw holders response (list of per-token entries, each with ``holders``)."""
    return get_json(
        f"{config.DATA}/holders",
        params={"market": condition_id, "limit": limit, "minBalance": int(min_balance)},
    )


HOLDER_COLUMNS: tuple[str, ...] = (
    "condition_id", "asset_id", "outcome_index",
    "proxy_wallet", "pseudonym", "name", "verified",
    "amount", "snapshot_ts_utc",
)

_HOLDER_SCHEMA: dict[str, pl.DataType] = {
    "condition_id": pl.Utf8, "asset_id": pl.Utf8, "outcome_index": pl.Int32,
    "proxy_wallet": pl.Utf8, "pseudonym": pl.Utf8, "name": pl.Utf8,
    "verified": pl.Boolean, "amount": pl.Float64,
    "snapshot_ts_utc": pl.Datetime("us", "UTC"),
}


def normalise_holders(
    response: list[dict[str, Any]],
    *,
    condition_id: str,
    snapshot_ts_utc,
) -> list[dict[str, Any]]:
    """Flatten the nested-by-token response into a flat row-per-holder list."""
    out: list[dict[str, Any]] = []
    for entry in response:
        token = entry.get("token")
        for h in entry.get("holders", []) or []:
            out.append({
                "condition_id": condition_id,
                "asset_id": str(token) if token is not None else None,
                "outcome_index": h.get("outcomeIndex"),
                "proxy_wallet": (h.get("proxyWallet") or "").lower() or None,
                "pseudonym": h.get("pseudonym"),
                "name": h.get("name"),
                "verified": bool(h.get("verified")) if h.get("verified") is not None else None,
                "amount": safe_float(h.get("amount")),
                "snapshot_ts_utc": snapshot_ts_utc,
            })
    return out


def holders_partition_path(condition_id: str) -> Path:
    return config.HOLDERS_PARQUET / f"condition_id={condition_id}" / "part.parquet"


def _raw_holders_path(condition_id: str) -> Path:
    p = config.RAW_DIR / "data_api" / "holders"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{condition_id}.jsonl"


def fetch_and_store_holders(
    condition_id: str,
    *,
    snapshot_ts_utc,
    persist_raw: bool = True,
    overwrite: bool = False,
) -> tuple[Path, int]:
    out = holders_partition_path(condition_id)
    if out.exists() and not overwrite:
        existing = pl.scan_parquet(out).select(pl.len()).collect().item()
        return out, int(existing)

    raw = fetch_holders(condition_id)
    if persist_raw:
        path = _raw_holders_path(condition_id)
        with path.open("w", encoding="utf-8") as fh:
            fh.write(json.dumps({"condition_id": condition_id,
                                 "snapshot_ts_utc": snapshot_ts_utc.isoformat(),
                                 "response": raw}, separators=(",", ":"), default=str))
            fh.write("\n")

    rows = normalise_holders(raw, condition_id=condition_id, snapshot_ts_utc=snapshot_ts_utc)
    out.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(rows, schema=_HOLDER_SCHEMA, orient="row" if rows else None)
    df.write_parquet(out, compression="zstd")
    return out, df.height

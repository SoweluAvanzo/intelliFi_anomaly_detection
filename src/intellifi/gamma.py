"""Gamma API loaders: /markets, /events, and negRisk family resolution.

This module is intentionally limited to **read** operations and **persistence**
of normalised records. Scoring lives elsewhere.

Two outputs per ingestion run:

* ``data/raw/gamma/markets/<run_id>.jsonl`` — raw JSON, line-delimited, for
  later replay. Per spec §reliability: persist raw before normalisation.
* ``data/parquet/markets/markets.parquet`` — normalised, canonical schema.

For the vertical slice we focus on **closed** markets whose ``endDate`` falls
in the last ``RESOLVED_LOOKBACK_DAYS`` window.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import polars as pl

from . import config
from .http import get_json
from .normalize import (
    parse_array_field,
    safe_bool,
    safe_float,
    to_utc_from_iso,
)

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Raw fetch
# ---------------------------------------------------------------------------

def fetch_markets_page(
    *,
    limit: int = config.GAMMA_PAGE_SIZE,
    offset: int = 0,
    closed: bool | None = None,
    active: bool | None = None,
    archived: bool | None = None,
    order: str | None = None,
    ascending: bool = False,
    end_date_min: str | None = None,
    end_date_max: str | None = None,
) -> list[dict[str, Any]]:
    """One page of Gamma ``/markets``. Caller paginates with ``offset``."""
    params: dict[str, Any] = {"limit": limit, "offset": offset}
    if closed is not None:
        params["closed"] = "true" if closed else "false"
    if active is not None:
        params["active"] = "true" if active else "false"
    if archived is not None:
        params["archived"] = "true" if archived else "false"
    if order is not None:
        params["order"] = order
        params["ascending"] = "true" if ascending else "false"
    if end_date_min is not None:
        params["end_date_min"] = end_date_min
    if end_date_max is not None:
        params["end_date_max"] = end_date_max

    data = get_json(f"{config.GAMMA}/markets", params=params)
    if not isinstance(data, list):
        raise RuntimeError(f"unexpected /markets response shape: {type(data).__name__}")
    return data


def iter_markets(
    *,
    closed: bool | None = None,
    active: bool | None = None,
    archived: bool | None = None,
    order: str | None = None,
    ascending: bool = False,
    end_date_min: str | None = None,
    end_date_max: str | None = None,
    max_pages: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Iterate **all** matching markets, paginating until the API returns []."""
    offset = 0
    page = 0
    while True:
        batch = fetch_markets_page(
            limit=config.GAMMA_PAGE_SIZE,
            offset=offset,
            closed=closed,
            active=active,
            archived=archived,
            order=order,
            ascending=ascending,
            end_date_min=end_date_min,
            end_date_max=end_date_max,
        )
        if not batch:
            return
        for m in batch:
            yield m
        offset += len(batch)
        page += 1
        log.info("Gamma /markets page %d (offset=%d, batch=%d)", page, offset, len(batch))
        if max_pages is not None and page >= max_pages:
            return
        if len(batch) < config.GAMMA_PAGE_SIZE:
            return  # last page


def fetch_event(event_id: str | int) -> dict[str, Any]:
    """One event = one negRisk family (when ``negRisk: true``)."""
    return get_json(f"{config.GAMMA}/events/{event_id}")


# ---------------------------------------------------------------------------
# Normalisation
# ---------------------------------------------------------------------------

# Columns we explicitly project into the markets parquet. Order matters for
# schema readability; everything else is preserved in raw JSONL.
MARKET_COLUMNS: tuple[str, ...] = (
    # identifiers
    "id", "slug", "question", "condition_id", "question_id",
    # outcome arrays (zipped from outcomes / clobTokenIds / outcomePrices)
    "outcomes", "clob_token_ids", "outcome_prices_final",
    # resolution / status
    "closed", "active", "archived", "accepting_orders",
    "uma_resolution_statuses",
    # negRisk
    "neg_risk", "neg_risk_other", "neg_risk_request_id",
    "event_id", "event_slug", "event_neg_risk", "event_neg_risk_market_id",
    # market-quality snapshots (point-in-time from Gamma)
    "best_bid", "best_ask", "spread", "last_trade_price",
    "one_month_price_change",
    # volumes / liquidity
    "volume", "volume_clob",
    "volume_24hr", "volume_24hr_clob",
    "volume_1wk_clob", "volume_1mo_clob", "volume_1yr_clob",
    "liquidity", "liquidity_clob",
    # market-maker rewards
    "rewards_min_size", "rewards_max_spread", "holding_rewards_enabled",
    # microstructure constants
    "order_price_min_tick_size", "order_min_size",
    # UMA
    "uma_bond", "uma_reward",
    # operational
    "enable_order_book", "clear_book_on_start",
    # timestamps (all UTC)
    "start_date", "end_date", "created_at", "updated_at",
    "accepting_orders_timestamp", "deploying_timestamp",
)


def _first_event(m: dict[str, Any]) -> dict[str, Any]:
    events = m.get("events") or []
    return events[0] if events else {}


def normalise_market(m: dict[str, Any]) -> dict[str, Any]:
    """Project a raw Gamma market into the canonical column set.

    The Gamma response carries ~60 fields. We project a curated subset (see
    ``MARKET_COLUMNS``) and keep the full raw record on disk for later
    backfills, so adding columns later is cheap.
    """
    outcomes = parse_array_field(m.get("outcomes"))
    tokens = parse_array_field(m.get("clobTokenIds"))
    prices_raw = parse_array_field(m.get("outcomePrices"))
    prices_final = [safe_float(x) for x in prices_raw]

    ev = _first_event(m)

    return {
        "id": str(m.get("id")) if m.get("id") is not None else None,
        "slug": m.get("slug"),
        "question": m.get("question"),
        "condition_id": m.get("conditionId"),
        "question_id": m.get("questionID"),

        "outcomes": outcomes,
        "clob_token_ids": [str(t) for t in tokens],
        "outcome_prices_final": prices_final,

        "closed": safe_bool(m.get("closed")),
        "active": safe_bool(m.get("active")),
        "archived": safe_bool(m.get("archived")),
        "accepting_orders": safe_bool(m.get("acceptingOrders")),
        "uma_resolution_statuses": m.get("umaResolutionStatuses"),

        "neg_risk": safe_bool(m.get("negRisk")),
        "neg_risk_other": safe_bool(m.get("negRiskOther")),
        "neg_risk_request_id": m.get("negRiskRequestID"),
        "event_id": str(ev.get("id")) if ev.get("id") is not None else None,
        "event_slug": ev.get("slug"),
        "event_neg_risk": safe_bool(ev.get("negRisk")),
        "event_neg_risk_market_id": ev.get("negRiskMarketID"),

        "best_bid": safe_float(m.get("bestBid")),
        "best_ask": safe_float(m.get("bestAsk")),
        "spread": safe_float(m.get("spread")),
        "last_trade_price": safe_float(m.get("lastTradePrice")),
        "one_month_price_change": safe_float(m.get("oneMonthPriceChange")),

        "volume": safe_float(m.get("volume")),
        "volume_clob": safe_float(m.get("volumeClob")),
        "volume_24hr": safe_float(m.get("volume24hr")),
        "volume_24hr_clob": safe_float(m.get("volume24hrClob")),
        "volume_1wk_clob": safe_float(m.get("volume1wkClob")),
        "volume_1mo_clob": safe_float(m.get("volume1moClob")),
        "volume_1yr_clob": safe_float(m.get("volume1yrClob")),
        "liquidity": safe_float(m.get("liquidityNum") or m.get("liquidity")),
        "liquidity_clob": safe_float(m.get("liquidityClob")),

        "rewards_min_size": safe_float(m.get("rewardsMinSize")),
        "rewards_max_spread": safe_float(m.get("rewardsMaxSpread")),
        "holding_rewards_enabled": safe_bool(m.get("holdingRewardsEnabled")),

        "order_price_min_tick_size": safe_float(m.get("orderPriceMinTickSize")),
        "order_min_size": safe_float(m.get("orderMinSize")),

        "uma_bond": safe_float(m.get("umaBond")),
        "uma_reward": safe_float(m.get("umaReward")),

        "enable_order_book": safe_bool(m.get("enableOrderBook")),
        "clear_book_on_start": safe_bool(m.get("clearBookOnStart")),

        "start_date": to_utc_from_iso(m.get("startDate")),
        "end_date": to_utc_from_iso(m.get("endDate")),
        "created_at": to_utc_from_iso(m.get("createdAt")),
        "updated_at": to_utc_from_iso(m.get("updatedAt")),
        "accepting_orders_timestamp": to_utc_from_iso(m.get("acceptingOrdersTimestamp")),
        "deploying_timestamp": to_utc_from_iso(m.get("deployingTimestamp")),
    }


# Schema declared explicitly so an empty result still produces a typed parquet.
_MARKET_SCHEMA: dict[str, pl.DataType] = {
    "id": pl.Utf8, "slug": pl.Utf8, "question": pl.Utf8,
    "condition_id": pl.Utf8, "question_id": pl.Utf8,
    "outcomes": pl.List(pl.Utf8),
    "clob_token_ids": pl.List(pl.Utf8),
    "outcome_prices_final": pl.List(pl.Float64),
    "closed": pl.Boolean, "active": pl.Boolean, "archived": pl.Boolean,
    "accepting_orders": pl.Boolean,
    "uma_resolution_statuses": pl.Utf8,
    "neg_risk": pl.Boolean, "neg_risk_other": pl.Boolean,
    "neg_risk_request_id": pl.Utf8,
    "event_id": pl.Utf8, "event_slug": pl.Utf8,
    "event_neg_risk": pl.Boolean, "event_neg_risk_market_id": pl.Utf8,
    "best_bid": pl.Float64, "best_ask": pl.Float64,
    "spread": pl.Float64, "last_trade_price": pl.Float64,
    "one_month_price_change": pl.Float64,
    "volume": pl.Float64, "volume_clob": pl.Float64,
    "volume_24hr": pl.Float64, "volume_24hr_clob": pl.Float64,
    "volume_1wk_clob": pl.Float64, "volume_1mo_clob": pl.Float64, "volume_1yr_clob": pl.Float64,
    "liquidity": pl.Float64, "liquidity_clob": pl.Float64,
    "rewards_min_size": pl.Float64, "rewards_max_spread": pl.Float64,
    "holding_rewards_enabled": pl.Boolean,
    "order_price_min_tick_size": pl.Float64, "order_min_size": pl.Float64,
    "uma_bond": pl.Float64, "uma_reward": pl.Float64,
    "enable_order_book": pl.Boolean, "clear_book_on_start": pl.Boolean,
    "start_date": pl.Datetime("us", "UTC"),
    "end_date": pl.Datetime("us", "UTC"),
    "created_at": pl.Datetime("us", "UTC"),
    "updated_at": pl.Datetime("us", "UTC"),
    "accepting_orders_timestamp": pl.Datetime("us", "UTC"),
    "deploying_timestamp": pl.Datetime("us", "UTC"),
}


def to_dataframe(records: Iterable[dict[str, Any]]) -> pl.DataFrame:
    """Build a typed Polars frame from normalised market records."""
    rows = list(records)
    return pl.DataFrame(rows, schema=_MARKET_SCHEMA, orient="row" if rows else None)


# ---------------------------------------------------------------------------
# Raw persistence
# ---------------------------------------------------------------------------

def _raw_path(run_id: str) -> Path:
    p = config.RAW_DIR / "gamma" / "markets"
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{run_id}.jsonl"


def write_raw_jsonl(records: Iterable[dict[str, Any]], run_id: str) -> Path:
    """Persist raw market JSON, one record per line, for later replay."""
    path = _raw_path(run_id)
    with path.open("w", encoding="utf-8") as fh:
        for r in records:
            fh.write(json.dumps(r, separators=(",", ":"), default=str))
            fh.write("\n")
    return path


# ---------------------------------------------------------------------------
# Top-level loader for the vertical slice
# ---------------------------------------------------------------------------

def load_resolved_markets(
    *,
    lookback_days: int = config.RESOLVED_LOOKBACK_DAYS,
    top_n: int | None = 1000,
    persist_raw: bool = True,
) -> pl.DataFrame:
    """Fetch resolved markets whose endDate falls in the lookback window.

    The Gamma ``/markets`` endpoint caps pagination at roughly 50k results,
    and Polymarket's long tail of micro-markets dwarfs the analytically
    interesting ones. We therefore sort by ``volumeClob`` descending and
    take the top ``top_n`` markets (default 1000) — empirically the universe
    where wallet-level analysis has enough signal.

    Pass ``top_n=None`` to ingest the entire reachable universe (still capped
    by the API's hard offset limit).

    Returns a Polars frame with the canonical schema. Does NOT write parquet;
    the caller decides whether this is a smoke test or a real ingest.
    """
    config.ensure_dirs()

    now = datetime.now(tz=UTC)
    start = (now - timedelta(days=lookback_days)).date().isoformat()
    end = now.date().isoformat()

    target = f"top {top_n}" if top_n is not None else "all reachable"
    log.info("Fetching %s resolved markets with end_date in [%s, %s], ordered by volumeClob desc",
             target, start, end)

    # Translate top_n into a page budget so we stop early.
    max_pages = None
    if top_n is not None:
        max_pages = (top_n + config.GAMMA_PAGE_SIZE - 1) // config.GAMMA_PAGE_SIZE

    raw: list[dict[str, Any]] = []
    for m in iter_markets(
        closed=True,
        archived=False,
        end_date_min=start,
        end_date_max=end,
        order="volumeClob",
        ascending=False,
        max_pages=max_pages,
    ):
        raw.append(m)
        if top_n is not None and len(raw) >= top_n:
            break

    log.info("Pulled %d raw resolved markets", len(raw))

    if persist_raw and raw:
        run_id = now.strftime("%Y%m%dT%H%M%SZ")
        path = write_raw_jsonl(raw, run_id)
        log.info("Persisted raw JSONL to %s", path)

    normalised = [normalise_market(m) for m in raw]
    return to_dataframe(normalised)


def write_markets_parquet(df: pl.DataFrame, *, filename: str = "markets.parquet") -> Path:
    """Overwrite the canonical markets parquet."""
    config.ensure_dirs()
    out = config.MARKETS_PARQUET / filename
    df.write_parquet(out, compression="zstd")
    return out

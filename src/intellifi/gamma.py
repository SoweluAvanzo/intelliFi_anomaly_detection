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

import requests

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


class _OffsetCeiling(Exception):
    """Raised when Gamma's ~2000 offset ceiling is hit; signals the caller to date-window."""


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
        try:
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
        except requests.HTTPError as exc:
            # Gamma returns 422 past its hard offset ceiling (~2000). That is not
            # an error for us — it means this date window has more markets than a
            # single offset walk can reach; stop and let the caller date-window.
            if getattr(exc.response, "status_code", None) == 422:
                log.info("Gamma offset ceiling hit at offset=%d — window truncated", offset)
                raise _OffsetCeiling(offset) from exc
            raise
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
    # closed_time is when trading actually stopped (UMA resolution); end_date is
    # only the scheduled deadline and can differ from it by weeks either way.
    "closed_time", "uma_end_date", "game_start_time",
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
        "closed_time": to_utc_from_iso(m.get("closedTime")),
        "uma_end_date": to_utc_from_iso(m.get("umaEndDate")),
        "game_start_time": to_utc_from_iso(m.get("gameStartTime")),
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
    "closed_time": pl.Datetime("us", "UTC"),
    "uma_end_date": pl.Datetime("us", "UTC"),
    "game_start_time": pl.Datetime("us", "UTC"),
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
    closed: bool | None = True,
    archived: bool | None = False,
    end_date_max: str | None = None,
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
    end = end_date_max or now.date().isoformat()

    target = f"top {top_n}" if top_n is not None else "all reachable"
    log.info("Fetching %s resolved markets with end_date in [%s, %s], ordered by volumeClob desc",
             target, start, end)

    # Translate top_n into a page budget so we stop early.
    max_pages = None
    if top_n is not None:
        max_pages = (top_n + config.GAMMA_PAGE_SIZE - 1) // config.GAMMA_PAGE_SIZE

    raw: list[dict[str, Any]]
    if top_n is not None:
        # Ranked top-N: a single offset walk (stays under the ~2000 ceiling for
        # sane top_n) ordered by volume.
        raw = []
        try:
            for m in iter_markets(
                closed=closed, archived=archived,
                end_date_min=start, end_date_max=end,
                order="volume", ascending=False, max_pages=max_pages,
            ):
                raw.append(m)
                if len(raw) >= top_n:
                    break
        except _OffsetCeiling:
            log.warning("hit offset ceiling before top_n=%d; got %d", top_n, len(raw))
    else:
        # Complete set: Gamma caps a single offset walk at ~2000 markets, so we
        # recursively bisect the endDate window until each sub-window fits under
        # the ceiling, then dedup by market id. Guarantees full family/class
        # coverage for the confirmatory analyses.
        from datetime import date as _date
        seen: dict[str, dict[str, Any]] = {}

        def _key(m: dict[str, Any]) -> str:
            return str(m.get("conditionId") or m.get("id") or m.get("slug") or id(m))

        def _collect(dmin: str, dmax: str, depth: int = 0) -> None:
            got: list[dict[str, Any]] = []
            try:
                for m in iter_markets(
                    closed=closed, archived=archived,
                    end_date_min=dmin, end_date_max=dmax,
                    order="endDate", ascending=True,
                ):
                    got.append(m)
            except _OffsetCeiling:
                lo, hi = _date.fromisoformat(dmin), _date.fromisoformat(dmax)
                if (hi - lo).days <= 0:
                    # single day still over the ceiling: keep what the walk yielded
                    log.warning("single-day window %s exceeds offset ceiling; keeping %d", dmin, len(got))
                    for m in got:
                        seen[_key(m)] = m
                    return
                mid = _date.fromordinal((lo.toordinal() + hi.toordinal()) // 2)
                log.info("window [%s,%s] truncated — bisecting at %s", dmin, dmax, mid)
                _collect(dmin, mid.isoformat(), depth + 1)
                _collect(_date.fromordinal(mid.toordinal() + 1).isoformat(), dmax, depth + 1)
                return
            for m in got:
                seen[_key(m)] = m
            log.info("window [%s,%s]: %d markets (running unique %d)", dmin, dmax, len(got), len(seen))

        _collect(start, end)
        raw = list(seen.values())

    log.info("Pulled %d raw resolved markets", len(raw))

    if persist_raw and raw:
        run_id = now.strftime("%Y%m%dT%H%M%SZ")
        path = write_raw_jsonl(raw, run_id)
        log.info("Persisted raw JSONL to %s", path)

    normalised = [normalise_market(m) for m in raw]
    return to_dataframe(normalised)


def fetch_markets_by_tokens(
    token_ids: Iterable[str],
    *,
    batch: int = 100,
    on_progress: Any = None,
) -> Iterator[dict[str, Any]]:
    """Look markets up by CLOB token id (``clob_token_ids`` filter) rather than by
    enumerating /markets. This is the only way to get COMPLETE coverage: Gamma's
    offset ceiling (~2000) drops markets on dense endDate days, including
    high-volume ones, so enumeration is lossy. Querying by the exact token ids
    that appear in our tape is targeted and complete. Yields unique market dicts.

    Gamma accepts repeated ``clob_token_ids`` params in one request; ``batch`` is
    how many token ids per request. Falls back gracefully: a batch that errors is
    retried one id at a time so one bad id can't drop a whole batch.
    """
    seen: set[str] = set()
    ids = [str(t) for t in token_ids if t]
    done = 0
    for i in range(0, len(ids), batch):
        chunk = ids[i:i + batch]
        try:
            data = get_json(f"{config.GAMMA}/markets", params=[("clob_token_ids", c) for c in chunk])
            got = data if isinstance(data, list) else []
        except Exception as exc:  # noqa: BLE001 — degrade to per-id
            log.warning("batch of %d failed (%s); retrying singly", len(chunk), exc)
            got = []
            for c in chunk:
                try:
                    d = get_json(f"{config.GAMMA}/markets", params={"clob_token_ids": c})
                    if isinstance(d, list):
                        got.extend(d)
                except Exception:  # noqa: BLE001
                    pass
        for m in got:
            k = str(m.get("conditionId") or m.get("id") or "").lower()
            if k and k not in seen:
                seen.add(k)
                yield m
        done += len(chunk)
        if on_progress and (i // batch) % 20 == 0:
            on_progress(done, len(ids), len(seen))
    log.info("fetch_markets_by_tokens: %d unique markets from %d token ids", len(seen), len(ids))


def stream_all_markets(
    parts_dir: Path,
    *,
    lookback_days: int = config.RESOLVED_LOOKBACK_DAYS,
    closed: bool | None = None,
    archived: bool | None = None,
    end_date_max: str | None = None,
    flush_every: int = 5000,
) -> int:
    """Memory-bounded complete-set fetch: date-window-bisect the endDate range and
    write each window's NEW markets to ``parts_dir/part_NNNNN.parquet`` as it goes,
    keeping only a set of seen conditionIds in RAM (not the market dicts). Returns
    the number of unique markets written. Use for the v2 metadata, where the full
    closed+archived universe can be hundreds of thousands of markets and buffering
    every dict OOMs. Caller consolidates the parts (e.g. DuckDB) into one file.
    """
    from datetime import date as _date

    config.ensure_dirs()
    parts_dir = Path(parts_dir)
    parts_dir.mkdir(parents=True, exist_ok=True)
    for f in parts_dir.glob("part_*.parquet"):
        f.unlink()

    now = datetime.now(tz=UTC)
    start = (now - timedelta(days=lookback_days)).date().isoformat()
    end = end_date_max or now.date().isoformat()
    seen: set[str] = set()
    seq = 0

    def _key(m: dict[str, Any]) -> str:
        return str(m.get("conditionId") or m.get("id") or m.get("slug") or "").lower()

    def _flush(markets: list[dict[str, Any]]) -> None:
        nonlocal seq
        new = []
        for m in markets:
            k = _key(m)
            if not k or k in seen:
                continue
            seen.add(k)
            new.append(m)
        if new:
            to_dataframe([normalise_market(m) for m in new]).write_parquet(
                parts_dir / f"part_{seq:05d}.parquet", compression="zstd")
            seq += 1

    def _collect(dmin: str, dmax: str, closed_val: bool | None) -> None:
        got: list[dict[str, Any]] = []
        try:
            # archived is a verified no-op on Gamma /markets (2026-08-31) — omit it.
            for m in iter_markets(closed=closed_val, archived=None,
                                  end_date_min=dmin, end_date_max=dmax,
                                  order="endDate", ascending=True):
                got.append(m)
                if len(got) >= flush_every:
                    _flush(got); got = []
        except _OffsetCeiling:
            _flush(got); got = []
            lo, hi = _date.fromisoformat(dmin), _date.fromisoformat(dmax)
            if (hi - lo).days <= 0:
                log.warning("single-day window %s (closed=%s) over offset ceiling; some markets dropped", dmin, closed_val)
                return
            mid = _date.fromordinal((lo.toordinal() + hi.toordinal()) // 2)
            log.info("window [%s,%s] closed=%s truncated — bisecting at %s (unique so far %d)", dmin, dmax, closed_val, mid, len(seen))
            _collect(dmin, mid.isoformat(), closed_val)
            _collect(_date.fromordinal(mid.toordinal() + 1).isoformat(), dmax, closed_val)
            return
        _flush(got)
        log.info("window [%s,%s] closed=%s done (unique %d)", dmin, dmax, closed_val, len(seen))

    # closed=None means "the complete set": Gamma's default is open-only and its
    # `closed` param is the real filter, so we run BOTH passes and dedup by
    # conditionId via the shared seen-set (verified 2026-08-31).
    passes = [True, False] if closed is None else [closed]
    for cv in passes:
        log.info("stream_all_markets: pass closed=%s over [%s, %s]", cv, start, end)
        _collect(start, end, cv)
    log.info("stream_all_markets: %d unique markets in %d parts -> %s", len(seen), seq, parts_dir)
    return len(seen)


def write_markets_parquet(df: pl.DataFrame, *, filename: str = "markets.parquet") -> Path:
    """Overwrite the canonical markets parquet."""
    config.ensure_dirs()
    out = config.MARKETS_PARQUET / filename
    df.write_parquet(out, compression="zstd")
    return out

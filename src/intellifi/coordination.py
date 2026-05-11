"""Behavioral coordination detection — the complement to on-chain linkage.

Two wallets can be related without ever transferring USDC or shares to each
other: they can be operated by one actor who simply trades in lockstep, or
they can be part of a copy-trading network. This module surfaces those
behavioural patterns from the ``trades`` view alone.

Three primitives:

* :func:`cotrade_pairs` — for each pair of wallets that ever traded the same
  ``asset_id`` on the same side within a short time window, count how often
  it happened and how much capital it represents. Same-direction near-
  simultaneous activity is the canonical "coordination" signal.

* :func:`leader_lag_pairs` — directed variant: for each (A → B) ordered pair,
  count the number of times A's trade is followed by B's trade on the same
  asset within ``lag_max`` seconds, *with no other wallet trading in between*.
  Strong lead-lag suggests B is mirroring A (or both are mirroring an
  upstream signal).

* :func:`wash_round_trips` — find wallets that buy then sell the same
  ``asset_id`` within a short window with similar size. A proxy for wash
  trading; without maker/taker we cannot prove it, only flag candidates.

All three operate over DuckDB views, so the universe filter is just a
``WHERE proxy_wallet IN (...)`` predicate.
"""
from __future__ import annotations

import duckdb


def cotrade_pairs(
    con: duckdb.DuckDBPyConnection,
    *,
    window_seconds: int = 300,
    universe: list[str] | None = None,
    min_pair_events: int = 2,
) -> duckdb.DuckDBPyRelation:
    """Pairwise undirected co-trading frequency.

    For each (asset_id, side, time_bucket) where two or more universe wallets
    trade, every unordered pair gets an event. The result is the per-pair
    summary: number of co-trade events, distinct markets, total combined
    notional.

    ``window_seconds`` defines the bucket size: 300 = 5 minutes.
    """
    universe_filter = ""
    if universe is not None:
        addrs = ",".join(f"'{a.lower()}'" for a in universe)
        universe_filter = f"AND proxy_wallet IN ({addrs})"

    return con.sql(f"""
        WITH bucketed AS (
            SELECT proxy_wallet,
                   asset_id,
                   side,
                   condition_id,
                   notional_usdc,
                   FLOOR(EPOCH(ts_utc) / {window_seconds})::BIGINT AS bucket
            FROM trades
            WHERE proxy_wallet IS NOT NULL
              AND asset_id IS NOT NULL
              AND side IS NOT NULL
              AND ts_utc IS NOT NULL
              {universe_filter}
        ),
        grouped AS (
            SELECT asset_id, side, bucket, condition_id,
                   list(DISTINCT proxy_wallet) AS wallets,
                   sum(notional_usdc)          AS bucket_notional
            FROM bucketed
            GROUP BY 1, 2, 3, 4
            HAVING len(list(DISTINCT proxy_wallet)) >= 2
        ),
        pairs AS (
            SELECT condition_id, asset_id, side, bucket, bucket_notional,
                   a, b
            FROM grouped,
                 UNNEST(wallets) AS t1(a),
                 UNNEST(wallets) AS t2(b)
            WHERE a < b
        )
        SELECT a, b,
               COUNT(*)                            AS cotrade_events,
               COUNT(DISTINCT condition_id)        AS cotrade_markets,
               COUNT(DISTINCT bucket)              AS cotrade_buckets,
               SUM(bucket_notional)                AS combined_bucket_notional
        FROM pairs
        GROUP BY 1, 2
        HAVING COUNT(*) >= {min_pair_events}
        ORDER BY cotrade_events DESC, combined_bucket_notional DESC;
    """)


def leader_lag_pairs(
    con: duckdb.DuckDBPyConnection,
    *,
    lag_max_seconds: int = 600,
    universe: list[str] | None = None,
    min_events: int = 3,
) -> duckdb.DuckDBPyRelation:
    """Directed leader→follower frequency.

    For each trade by A on ``asset_id`` at time t, find the next trade on
    the same asset by some B (≠ A) within ``lag_max_seconds`` on the same
    side. Count (A→B, B, side) events. A strong skew toward (A→B) over
    (B→A) is evidence A is the leader, B the follower.

    This is a coarse approximation: we don't require A to have *caused* B's
    trade — only that B trades the same direction shortly after A does.
    """
    universe_filter = ""
    if universe is not None:
        addrs = ",".join(f"'{a.lower()}'" for a in universe)
        universe_filter = f"AND proxy_wallet IN ({addrs})"

    return con.sql(f"""
        WITH base AS (
            SELECT proxy_wallet, asset_id, side, ts_utc, notional_usdc, condition_id
            FROM trades
            WHERE proxy_wallet IS NOT NULL
              AND asset_id IS NOT NULL
              AND ts_utc IS NOT NULL
              {universe_filter}
        ),
        ordered AS (
            SELECT *,
                   LEAD(proxy_wallet)     OVER (PARTITION BY asset_id, side ORDER BY ts_utc) AS next_wallet,
                   LEAD(ts_utc)           OVER (PARTITION BY asset_id, side ORDER BY ts_utc) AS next_ts
            FROM base
        ),
        lag_pairs AS (
            SELECT proxy_wallet AS leader,
                   next_wallet  AS follower,
                   side,
                   condition_id,
                   EPOCH(next_ts) - EPOCH(ts_utc) AS lag_seconds
            FROM ordered
            WHERE next_wallet IS NOT NULL
              AND next_wallet <> proxy_wallet
              AND EPOCH(next_ts) - EPOCH(ts_utc) <= {lag_max_seconds}
              AND EPOCH(next_ts) - EPOCH(ts_utc) > 0
        )
        SELECT leader, follower,
               COUNT(*)                       AS lead_events,
               COUNT(DISTINCT condition_id)   AS lead_markets,
               AVG(lag_seconds)               AS mean_lag_seconds,
               MEDIAN(lag_seconds)            AS median_lag_seconds
        FROM lag_pairs
        GROUP BY 1, 2
        HAVING COUNT(*) >= {min_events}
        ORDER BY lead_events DESC;
    """)


def wash_round_trips(
    con: duckdb.DuckDBPyConnection,
    *,
    window_seconds: int = 600,
    universe: list[str] | None = None,
    min_size_overlap: float = 0.5,
) -> duckdb.DuckDBPyRelation:
    """Per-wallet round-trip BUY→SELL on the same asset within a tight window.

    For each wallet, find every BUY trade followed by a SELL on the same
    ``asset_id`` within ``window_seconds`` where the two sizes overlap by at
    least ``min_size_overlap`` (e.g. 0.5 = 50% of the smaller side). Returns
    counts and notional summed per wallet.

    This is a **proxy** for self-wash, not proof — wallets may legitimately
    flip positions intraday. Use the counts as a flag, not a verdict.
    """
    universe_filter = ""
    if universe is not None:
        addrs = ",".join(f"'{a.lower()}'" for a in universe)
        universe_filter = f"AND proxy_wallet IN ({addrs})"

    return con.sql(f"""
        WITH base AS (
            SELECT proxy_wallet, asset_id, side, ts_utc, size, notional_usdc
            FROM trades
            WHERE proxy_wallet IS NOT NULL
              AND asset_id IS NOT NULL
              AND side IN ('BUY', 'SELL')
              AND ts_utc IS NOT NULL
              AND size > 0
              {universe_filter}
        ),
        flips AS (
            SELECT b.proxy_wallet, b.asset_id,
                   b.ts_utc AS buy_ts, b.size AS buy_size, b.notional_usdc AS buy_notional,
                   s.ts_utc AS sell_ts, s.size AS sell_size, s.notional_usdc AS sell_notional,
                   EPOCH(s.ts_utc) - EPOCH(b.ts_utc) AS gap_seconds
            FROM base b
            JOIN base s
              ON b.proxy_wallet = s.proxy_wallet
             AND b.asset_id = s.asset_id
             AND b.side = 'BUY' AND s.side = 'SELL'
             AND s.ts_utc > b.ts_utc
             AND EPOCH(s.ts_utc) - EPOCH(b.ts_utc) <= {window_seconds}
             AND LEAST(b.size, s.size) / GREATEST(b.size, s.size) >= {min_size_overlap}
        )
        SELECT proxy_wallet,
               COUNT(*)                                          AS round_trips,
               COUNT(DISTINCT asset_id)                          AS round_trip_assets,
               AVG(gap_seconds)                                  AS mean_gap_seconds,
               SUM(LEAST(buy_notional, sell_notional))           AS round_trip_notional
        FROM flips
        GROUP BY 1
        ORDER BY round_trips DESC;
    """)

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
    trade, every unordered pair gets one event. The result is the per-pair
    summary: number of co-trade events, distinct markets, distinct buckets,
    and ``pair_notional`` = the two members' own notional in the shared
    buckets (NOT the whole bucket's notional — audit 2026-08-29).

    ``window_seconds`` defines the bucket size: 300 = 5 minutes. Fixed buckets
    miss pairs that straddle a boundary; the count is therefore conservative.
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
        per_wallet_bucket AS (
            SELECT asset_id, side, bucket, condition_id, proxy_wallet,
                   SUM(notional_usdc) AS wallet_notional
            FROM bucketed
            GROUP BY 1, 2, 3, 4, 5
        ),
        pairs AS (
            SELECT x.condition_id, x.asset_id, x.side, x.bucket,
                   x.proxy_wallet AS a, y.proxy_wallet AS b,
                   x.wallet_notional + y.wallet_notional AS pair_notional
            FROM per_wallet_bucket x
            JOIN per_wallet_bucket y
              ON x.asset_id = y.asset_id AND x.side = y.side
             AND x.bucket = y.bucket AND x.condition_id = y.condition_id
             AND x.proxy_wallet < y.proxy_wallet
        )
        SELECT a, b,
               COUNT(*)                            AS cotrade_events,
               COUNT(DISTINCT condition_id)        AS cotrade_markets,
               COUNT(DISTINCT bucket)              AS cotrade_buckets,
               SUM(pair_notional)                  AS pair_notional
        FROM pairs
        GROUP BY 1, 2
        HAVING COUNT(*) >= {min_pair_events}
        ORDER BY cotrade_events DESC, pair_notional DESC, a, b;
    """)


def leader_lag_pairs(
    con: duckdb.DuckDBPyConnection,
    *,
    lag_max_seconds: int = 600,
    universe: list[str] | None = None,
    min_events: int = 3,
) -> duckdb.DuckDBPyRelation:
    """Directed leader→follower frequency.

    Trade timestamps have one-second resolution, so trades in the same second
    are treated as **simultaneous** (they belong to :func:`cotrade_pairs`).
    For each (asset_id, side) the distinct trading seconds are ordered; every
    wallet trading in second *s* is a leader of every *other* wallet trading
    in the next distinct second *s′* with ``s′ − s ≤ lag_max_seconds``.
    The output counts (leader, follower) events, distinct markets, and the
    mean / median lag.

    This replaces an earlier LEAD()-over-rows definition whose result
    depended on the ordering of same-second rows (audit 2026-08-29). It is
    still a coarse approximation: B trading the same direction shortly after
    A is consistent with copy-trading but also with a shared public signal.
    """
    universe_filter = ""
    if universe is not None:
        addrs = ",".join(f"'{a.lower()}'" for a in universe)
        universe_filter = f"AND proxy_wallet IN ({addrs})"

    return con.sql(f"""
        WITH base AS (
            SELECT proxy_wallet, asset_id, side, condition_id,
                   date_trunc('second', ts_utc) AS sec
            FROM trades
            WHERE proxy_wallet IS NOT NULL
              AND asset_id IS NOT NULL
              AND side IN ('BUY', 'SELL')
              AND ts_utc IS NOT NULL
              {universe_filter}
        ),
        per_sec AS (
            SELECT DISTINCT asset_id, side, condition_id, sec, proxy_wallet
            FROM base
        ),
        secs AS (
            SELECT asset_id, side, sec,
                   LEAD(sec) OVER (PARTITION BY asset_id, side ORDER BY sec) AS next_sec
            FROM (SELECT DISTINCT asset_id, side, sec FROM base)
        ),
        lag_pairs AS (
            SELECT l.proxy_wallet AS leader,
                   f.proxy_wallet AS follower,
                   l.condition_id,
                   EPOCH(s.next_sec) - EPOCH(s.sec) AS lag_seconds
            FROM secs s
            JOIN per_sec l ON l.asset_id = s.asset_id AND l.side = s.side AND l.sec = s.sec
            JOIN per_sec f ON f.asset_id = s.asset_id AND f.side = s.side AND f.sec = s.next_sec
            WHERE s.next_sec IS NOT NULL
              AND l.proxy_wallet <> f.proxy_wallet
              AND EPOCH(s.next_sec) - EPOCH(s.sec) <= {lag_max_seconds}
        )
        SELECT leader, follower,
               COUNT(*)                       AS lead_events,
               COUNT(DISTINCT condition_id)   AS lead_markets,
               AVG(lag_seconds)               AS mean_lag_seconds,
               MEDIAN(lag_seconds)            AS median_lag_seconds
        FROM lag_pairs
        GROUP BY 1, 2
        HAVING COUNT(*) >= {min_events}
        ORDER BY lead_events DESC, leader, follower;
    """)


def wash_round_trips(
    con: duckdb.DuckDBPyConnection,
    *,
    window_seconds: int = 600,
    universe: list[str] | None = None,
    min_size_overlap: float = 0.5,
) -> duckdb.DuckDBPyRelation:
    """Per-wallet round-trip BUY→SELL on the same asset within a tight window.

    A candidate is a BUY followed by a SELL on the same ``asset_id`` by the
    same wallet within ``window_seconds`` whose sizes overlap, i.e.
    ``min(size) / max(size) >= min_size_overlap``. Candidates are then matched
    **one-to-one**: each BUY keeps only its nearest subsequent SELL, and each
    SELL keeps only the nearest BUY that chose it, so a wallet with many buys
    and sells in one window is no longer counted combinatorially (audit
    2026-08-29). ``round_trip_notional`` sums the smaller leg of each match.

    This is a **proxy** for self-wash, not proof — only the taker leg of each
    fill is visible, so the counterparty is unknown and legitimate intraday
    position flips look identical. Use the counts as a flag, not a verdict.
    """
    universe_filter = ""
    if universe is not None:
        addrs = ",".join(f"'{a.lower()}'" for a in universe)
        universe_filter = f"AND proxy_wallet IN ({addrs})"

    return con.sql(f"""
        WITH base AS (
            SELECT proxy_wallet, asset_id, side, ts_utc, size, notional_usdc, tx_hash
            FROM trades
            WHERE proxy_wallet IS NOT NULL
              AND asset_id IS NOT NULL
              AND side IN ('BUY', 'SELL')
              AND ts_utc IS NOT NULL
              AND size > 0
              {universe_filter}
        ),
        candidates AS (
            SELECT b.proxy_wallet, b.asset_id,
                   b.tx_hash AS buy_tx, s.tx_hash AS sell_tx,
                   b.notional_usdc AS buy_notional, s.notional_usdc AS sell_notional,
                   EPOCH(s.ts_utc) - EPOCH(b.ts_utc) AS gap_seconds
            FROM base b
            JOIN base s
              ON b.proxy_wallet = s.proxy_wallet
             AND b.asset_id = s.asset_id
             AND b.side = 'BUY' AND s.side = 'SELL'
             AND s.ts_utc > b.ts_utc
             AND EPOCH(s.ts_utc) - EPOCH(b.ts_utc) <= {window_seconds}
             AND LEAST(b.size, s.size) / GREATEST(b.size, s.size) >= {min_size_overlap}
        ),
        nearest_sell AS (
            SELECT *, row_number() OVER (PARTITION BY proxy_wallet, asset_id, buy_tx
                                         ORDER BY gap_seconds, sell_tx) AS rk_b
            FROM candidates
        ),
        matched AS (
            SELECT *, row_number() OVER (PARTITION BY proxy_wallet, asset_id, sell_tx
                                         ORDER BY gap_seconds, buy_tx) AS rk_s
            FROM nearest_sell
            WHERE rk_b = 1
        )
        ,
        profile AS (
            -- maker signature: two-sided activity at extreme prices is
            -- liquidity provision / tick scalping, not wash trading
            SELECT proxy_wallet,
                   AVG(CASE WHEN side = 'BUY' THEN 1.0 ELSE 0.0 END) AS buy_fraction,
                   MEDIAN(price)                                  AS median_price,
                   COUNT(DISTINCT asset_id)                       AS n_assets_traded
            FROM trades
            WHERE proxy_wallet IS NOT NULL AND side IN ('BUY', 'SELL')
            GROUP BY 1
        )
        SELECT m.proxy_wallet,
               COUNT(*)                                          AS round_trips,
               COUNT(DISTINCT m.asset_id)                        AS round_trip_assets,
               AVG(m.gap_seconds)                                AS mean_gap_seconds,
               SUM(LEAST(m.buy_notional, m.sell_notional))       AS round_trip_notional,
               ANY_VALUE(p.buy_fraction)                         AS buy_fraction,
               ANY_VALUE(p.median_price)                         AS median_price,
               ANY_VALUE(p.n_assets_traded)                      AS n_assets_traded
        FROM matched m
        LEFT JOIN profile p USING (proxy_wallet)
        WHERE m.rk_s = 1
        GROUP BY 1
        ORDER BY round_trips DESC, m.proxy_wallet;
    """)


# ---------------------------------------------------------------------------
# Activity-preserving null model (audit 2026-08-29)
# ---------------------------------------------------------------------------

def _bh_qvalues(p: "np.ndarray") -> "np.ndarray":
    """Benjamini–Hochberg q-values."""
    import numpy as np
    n = p.size
    if n == 0:
        return p
    order = np.argsort(p)
    ranked = p[order] * n / (np.arange(n) + 1)
    q = np.minimum.accumulate(ranked[::-1])[::-1]
    out = np.empty(n); out[order] = np.clip(q, 0, 1)
    return out


def cotrade_pairs_with_null(
    con: duckdb.DuckDBPyConnection,
    *,
    window_seconds: int = 300,
    universe: list[str] | None = None,
    min_pair_events: int = 2,
) -> "pl.DataFrame":
    """:func:`cotrade_pairs` plus an activity-preserving null expectation.

    Within each (asset_id, side) stratum with ``B`` distinct occupied buckets,
    a wallet active in ``k_a`` buckets and another in ``k_b`` buckets would,
    if their activity were placed independently, share
    ``k_a * k_b / B`` buckets in expectation. Summing over strata gives
    ``expected_events``; ``excess_ratio = cotrade_events / expected_events``
    and ``p_value`` is the Poisson upper tail. ``q_value`` is
    Benjamini–Hochberg over every pair with at least one co-trade event.
    Pairs whose co-trading is explained by both wallets simply being very
    active in the same markets have ``excess_ratio`` near 1.
    """
    import numpy as np
    import polars as pl
    from scipy.stats import poisson

    universe_filter = ""
    if universe is not None:
        addrs = ",".join(f"'{a.lower()}'" for a in universe)
        universe_filter = f"AND proxy_wallet IN ({addrs})"
    observed = cotrade_pairs(con, window_seconds=window_seconds, universe=universe,
                             min_pair_events=1).pl()
    expected = con.sql(f"""
        WITH bucketed AS (
            SELECT DISTINCT proxy_wallet, asset_id, side,
                   FLOOR(EPOCH(ts_utc) / {window_seconds})::BIGINT AS bucket
            FROM trades
            WHERE proxy_wallet IS NOT NULL AND asset_id IS NOT NULL
              AND side IS NOT NULL AND ts_utc IS NOT NULL
              {universe_filter}
        ),
        strata AS (
            SELECT asset_id, side, COUNT(DISTINCT bucket) AS n_buckets FROM bucketed GROUP BY 1, 2
        ),
        activity AS (
            SELECT asset_id, side, proxy_wallet, COUNT(*) AS k FROM bucketed GROUP BY 1, 2, 3
        )
        SELECT x.proxy_wallet AS a, y.proxy_wallet AS b,
               SUM(x.k * y.k / s.n_buckets) AS expected_events
        FROM activity x
        JOIN activity y ON x.asset_id = y.asset_id AND x.side = y.side AND x.proxy_wallet < y.proxy_wallet
        JOIN strata s ON s.asset_id = x.asset_id AND s.side = x.side
        GROUP BY 1, 2
    """).pl()
    df = observed.join(expected, on=["a", "b"], how="left")
    obs = df["cotrade_events"].to_numpy(); exp = df["expected_events"].fill_null(0.0).to_numpy()
    pvals = poisson.sf(obs - 1, np.maximum(exp, 1e-12))
    df = df.with_columns(
        pl.Series("expected_events", exp),
        (pl.col("cotrade_events") / pl.Series("e", np.maximum(exp, 1e-12))).alias("excess_ratio"),
        pl.Series("p_value", pvals),
        pl.Series("q_value", _bh_qvalues(pvals)),
    )
    return (df.filter(pl.col("cotrade_events") >= min_pair_events)
              .sort(["cotrade_events", "pair_notional", "a", "b"], descending=[True, True, False, False]))


def leader_lag_pairs_with_null(
    con: duckdb.DuckDBPyConnection,
    *,
    lag_max_seconds: int = 600,
    universe: list[str] | None = None,
    min_events: int = 3,
) -> "pl.DataFrame":
    """:func:`leader_lag_pairs` plus an activity-preserving null expectation.

    Within each (asset_id, side) stratum with ``S`` distinct trading seconds,
    of which ``S_adj`` consecutive pairs are within ``lag_max_seconds``, a
    leader active in ``k_a`` seconds and a follower in ``k_b`` seconds have
    expected lead events ``k_a * k_b * S_adj / S^2`` under independent
    placement. ``excess_ratio``, Poisson ``p_value`` and BH ``q_value`` as in
    :func:`cotrade_pairs_with_null`. Symmetric pairs (A→B ≈ B→A) with
    excess near 1 are bursty co-activity, not leadership.
    """
    import numpy as np
    import polars as pl
    from scipy.stats import poisson

    universe_filter = ""
    if universe is not None:
        addrs = ",".join(f"'{a.lower()}'" for a in universe)
        universe_filter = f"AND proxy_wallet IN ({addrs})"
    observed = leader_lag_pairs(con, lag_max_seconds=lag_max_seconds, universe=universe,
                                min_events=1).pl()
    expected = con.sql(f"""
        WITH base AS (
            SELECT DISTINCT proxy_wallet, asset_id, side, date_trunc('second', ts_utc) AS sec
            FROM trades
            WHERE proxy_wallet IS NOT NULL AND asset_id IS NOT NULL
              AND side IN ('BUY', 'SELL') AND ts_utc IS NOT NULL
              {universe_filter}
        ),
        secs AS (
            SELECT asset_id, side, sec,
                   LEAD(sec) OVER (PARTITION BY asset_id, side ORDER BY sec) AS next_sec
            FROM (SELECT DISTINCT asset_id, side, sec FROM base)
        ),
        strata AS (
            SELECT asset_id, side, COUNT(*) AS n_secs,
                   COUNT(CASE WHEN EPOCH(next_sec) - EPOCH(sec) <= {lag_max_seconds} THEN 1 END) AS n_adjacent
            FROM secs GROUP BY 1, 2
        ),
        activity AS (
            SELECT asset_id, side, proxy_wallet, COUNT(*) AS k FROM base GROUP BY 1, 2, 3
        )
        SELECT x.proxy_wallet AS leader, y.proxy_wallet AS follower,
               SUM(x.k * y.k * s.n_adjacent / (s.n_secs * s.n_secs)) AS expected_events
        FROM activity x
        JOIN activity y ON x.asset_id = y.asset_id AND x.side = y.side AND x.proxy_wallet <> y.proxy_wallet
        JOIN strata s ON s.asset_id = x.asset_id AND s.side = x.side
        GROUP BY 1, 2
    """).pl()
    df = observed.join(expected, on=["leader", "follower"], how="left")
    obs = df["lead_events"].to_numpy(); exp = df["expected_events"].fill_null(0.0).to_numpy()
    pvals = poisson.sf(obs - 1, np.maximum(exp, 1e-12))
    df = df.with_columns(
        pl.Series("expected_events", exp),
        (pl.col("lead_events") / pl.Series("e", np.maximum(exp, 1e-12))).alias("excess_ratio"),
        pl.Series("p_value", pvals),
        pl.Series("q_value", _bh_qvalues(pvals)),
    )
    return (df.filter(pl.col("lead_events") >= min_events)
              .sort(["lead_events", "leader", "follower"], descending=[True, False, False]))

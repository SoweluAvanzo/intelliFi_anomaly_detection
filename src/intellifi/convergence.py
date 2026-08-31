"""Resolution convergence analysis (#5 easy variant).

How far in advance does the Polymarket price track the eventually-resolved
outcome? For each resolved market we have:

* The price trajectory ``p(t)`` for each outcome token (from CLOB
  ``/prices-history``).
* The winning outcome index.
* ``closed_time`` from Gamma — when trading actually stopped (falls back to
  the scheduled ``end_date`` only if ``closed_time`` is missing). The two
  differ by a median of ~21 h and by weeks in either direction for markets
  that resolved early or were extended, so ``end_date`` must not be used as
  the reference.

We compute, for each market and at each time offset before ``closed_time``,
the **convergence error** ``|p(t) - 1[winner]|``. Averaged across markets,
this curve answers "how informed is the market as a function of time
remaining". A market that knows the answer 7 days early shows near-zero
error at t = closed_time − 7 days; an inefficient market only converges in
the final minutes.

The module is purely analytical — it expects the CLOB prices_history
parquet to already be ingested.
"""
from __future__ import annotations

import logging
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

from . import config
from .clob import PRICES_HISTORY_DIR

log = logging.getLogger(__name__)


def all_prices_history_relation(con: duckdb.DuckDBPyConnection) -> None:
    """Register a view ``prices_history`` over every per-token parquet.

    When ``INTELLIFI_SOURCE=archive`` the view already exists (minute VWAP
    from the complete fill tape) and is left untouched.
    """
    import os
    if os.getenv("INTELLIFI_SOURCE", "parquet") == "archive":
        return
    glob = str(PRICES_HISTORY_DIR / "*.parquet")
    con.execute(f"""
        CREATE OR REPLACE VIEW prices_history AS
        SELECT token_id, ts_utc, price
        FROM read_parquet('{glob}');
    """)


def convergence_table(
    con: duckdb.DuckDBPyConnection,
    *,
    hours_before_end: tuple[int, ...] = (
        24 * 30, 24 * 14, 24 * 7, 24 * 3, 24, 6, 3, 1,
    ),
) -> pl.DataFrame:
    """Per-market price error vs winner at a series of pre-resolution offsets.

    Returns a long table with columns:
        condition_id, slug, hours_before_end, n_observations,
        winning_token_id, last_price_before_offset,
        abs_error, signed_error, history_span_hours (span of the available
        price history before close — NOT the market lifetime).

    Only markets with prices_history coverage and a valid winning outcome
    are included.
    """
    all_prices_history_relation(con)

    offsets_sql = " UNION ALL ".join(
        f"SELECT {h} AS hours_before_end" for h in hours_before_end
    )

    return con.sql(f"""
        WITH offsets(hours_before_end) AS ({offsets_sql}),
        ph_with_winner AS (
            SELECT ph.token_id, ph.ts_utc, ph.price,
                   w.condition_id, w.slug, w.winning_token_id,
                   COALESCE(m.closed_time, m.end_date) AS close_ref,
                   CASE WHEN m.game_start_time IS NOT NULL THEN 'scheduled_game'
                        WHEN m.closed_time < m.end_date - INTERVAL 1 HOUR THEN 'resolved_early'
                        ELSE 'deadline' END AS market_type,
                   CASE WHEN ph.token_id = w.winning_token_id THEN 1.0 ELSE 0.0 END
                       AS target,
                   DATE_DIFF('second', ph.ts_utc, COALESCE(m.closed_time, m.end_date)) / 3600.0
                       AS hours_to_end
            FROM prices_history ph
            JOIN markets m         ON m.clob_token_ids[1] = ph.token_id
                                   OR m.clob_token_ids[2] = ph.token_id
            JOIN winning_outcomes w ON w.condition_id = m.condition_id
            WHERE COALESCE(m.closed_time, m.end_date) IS NOT NULL
              AND ph.ts_utc < COALESCE(m.closed_time, m.end_date)
        ),
        -- For each (condition_id, offset), take the last observation at or
        -- before close_ref - offset hours.
        ranked AS (
            SELECT p.*,
                   o.hours_before_end,
                   row_number() OVER (
                       PARTITION BY p.condition_id, p.token_id, o.hours_before_end
                       ORDER BY p.ts_utc DESC
                   ) AS rk_within_offset
            FROM ph_with_winner p
            CROSS JOIN offsets o
            WHERE p.hours_to_end >= o.hours_before_end
        )
        SELECT condition_id, slug, market_type, hours_before_end,
               winning_token_id,
               price       AS last_price_before_offset,
               token_id    AS observed_token,
               ABS(price - target)    AS abs_error,
               price - target         AS signed_error,
               EXTRACT('epoch' FROM (
                   SELECT MAX(ts_utc) - MIN(ts_utc) FROM ph_with_winner p2
                   WHERE p2.condition_id = ranked.condition_id
               )) / 3600.0 AS history_span_hours
        FROM ranked
        WHERE rk_within_offset = 1
          AND token_id = winning_token_id
        ORDER BY condition_id, hours_before_end DESC;
    """).pl()


def aggregate_convergence(df: pl.DataFrame) -> pl.DataFrame:
    """Per-offset summary across markets."""
    return df.group_by("hours_before_end").agg(
        n_markets=pl.col("condition_id").n_unique(),
        median_abs_error=pl.col("abs_error").median(),
        mean_abs_error=pl.col("abs_error").mean(),
        p25_abs_error=pl.col("abs_error").quantile(0.25),
        p75_abs_error=pl.col("abs_error").quantile(0.75),
        p90_abs_error=pl.col("abs_error").quantile(0.90),
    ).sort("hours_before_end", descending=True)

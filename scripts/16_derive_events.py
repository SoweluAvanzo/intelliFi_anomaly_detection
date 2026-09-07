#!/usr/bin/env python3
"""Derive the `events` layer from the gamma_v2 markets parquet (NO network fetch).

Polymarket 'events' group related markets (e.g. an N-candidate election). Every
market already carries its event_* fields in gamma_v2, so the event layer is a
pure local aggregation -- one row per event_id. Offline-safe.

Writes data/parquet/events/part.parquet.
"""
from __future__ import annotations

import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi import config  # noqa: E402

SRC = str(config.PARQUET_DIR / "gamma_v2" / "markets_v2.parquet")
OUT_DIR = config.EVENTS_PARQUET
OUT = OUT_DIR / "part.parquet"


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"""
        COPY (
            SELECT
                event_id,
                any_value(event_slug)                      AS event_slug,
                bool_or(coalesce(event_neg_risk, false))   AS event_neg_risk,
                any_value(event_neg_risk_market_id)        AS event_neg_risk_market_id,
                count(DISTINCT condition_id)               AS n_markets,
                count(DISTINCT condition_id) FILTER (WHERE coalesce(neg_risk, false))
                                                           AS n_neg_risk_markets,
                sum(TRY_CAST(volume AS DOUBLE))            AS total_volume,
                sum(TRY_CAST(liquidity AS DOUBLE))         AS total_liquidity,
                count(*) FILTER (WHERE closed)             AS n_closed_markets,
                min(TRY_CAST(start_date AS TIMESTAMP))     AS first_start,
                max(TRY_CAST(end_date AS TIMESTAMP))       AS last_end,
                list(DISTINCT condition_id)                AS member_condition_ids
            FROM read_parquet('{SRC}')
            WHERE event_id IS NOT NULL AND event_id <> ''
            GROUP BY event_id
        ) TO '{OUT}' (FORMAT PARQUET, COMPRESSION ZSTD)
    """)
    n = con.execute(f"SELECT count(*) FROM read_parquet('{OUT}')").fetchone()[0]
    neg = con.execute(
        f"SELECT count(*) FROM read_parquet('{OUT}') WHERE event_neg_risk").fetchone()[0]
    print(f"events derived: {n:,} events ({neg:,} neg-risk) -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

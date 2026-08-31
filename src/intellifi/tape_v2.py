"""Loader for Sample B (the v2 on-chain tape) under the Stage I view names.

``data/parquet/tape_v2/blocks=*/part.parquet`` holds decoded v2 ``OrderFilled``
records (one row per maker order fill plus one taker-order record per taker
order, ``is_taker_order``). ``data/parquet/ctf_v2_conditions.parquet`` (from
``scripts/12``) maps outcome tokens to conditions and gives resolution times,
payouts and the negRisk flag. This module exposes:

* ``fills``   — maker-record granularity in the canonical fills schema;
* ``trades``  — taker-order records as Data-API-like taker rows;
* ``markets`` — one row per condition seen in the window (token ids, winner,
  ``closed_time`` = on-chain resolution time, ``created_at`` = preparation);
* ``winning_outcomes`` / ``prices_history`` (minute VWAP) as for the archive.

Categories are NOT available on-chain; ``markets.category`` is NULL until
Gamma metadata is joined (fetched from an unblocked network).
"""
from __future__ import annotations

import duckdb
import polars as pl

from . import config
from .fills import EXCHANGES_V2, TAPE_V2_DIR

CONDITIONS = config.PARQUET_DIR / "ctf_v2_conditions.parquet"


def register_v2_views(con: duckdb.DuckDBPyConnection, *, from_block: int | None = None,
                      to_block: int | None = None) -> None:
    glob = (TAPE_V2_DIR / "blocks=*" / "part.parquet").as_posix()
    where = ["event = 'OrderFilled'", "exchange IN ('v2_a', 'v2_b')"]   # 'other:*' emitters excluded from Sample B
    if from_block is not None:
        where.append(f"block_number >= {from_block}")
    if to_block is not None:
        where.append(f"block_number <= {to_block}")
    exch = ",".join(f"'{a}'" for a in EXCHANGES_V2.values())
    con.execute(f"""
        CREATE OR REPLACE VIEW v2_raw AS
        SELECT *, (taker IN ({exch})) AS is_taker_rec
        FROM read_parquet('{glob}', hive_partitioning = true)
        WHERE {' AND '.join(where)}
        -- Dedup overlapping chunks: the resumable/rebalanced crawl can write
        -- differently-cut chunk files over the same blocks (crawler races), so a
        -- fill can appear in >1 part.parquet. (tx_hash, evt_index) is the unique
        -- key of an OrderFilled log, so keep one row per key. (2026-08-31)
        QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index ORDER BY block_number) = 1;
    """)
    con.execute(f"""
        CREATE OR REPLACE VIEW v2_conditions AS
        SELECT * FROM read_parquet('{CONDITIONS.as_posix()}');
    """)
    con.execute("""
        CREATE OR REPLACE VIEW v2_tokens AS
        SELECT token0 AS token_id, condition_id, 0 AS outcome_index FROM v2_conditions WHERE token0 IS NOT NULL
        UNION ALL
        SELECT token1, condition_id, 1 FROM v2_conditions WHERE token1 IS NOT NULL;
    """)
    con.execute("""
        CREATE OR REPLACE VIEW markets AS
        SELECT c.condition_id,
               c.condition_id AS slug, c.condition_id AS question,
               c.neg_risk, c.neg_risk AS event_neg_risk,
               NULL::VARCHAR AS category, NULL::VARCHAR AS event_id,
               c.prepared_ts_utc AS created_at,
               c.resolved_ts_utc AS end_date,
               c.resolved_ts_utc AS closed_time,
               NULL::TIMESTAMPTZ AS uma_end_date, NULL::TIMESTAMPTZ AS game_start_time,
               ['Yes', 'No'] AS outcomes,
               [c.token0, c.token1] AS clob_token_ids,
               CASE WHEN c.winning_outcome_index = 0 THEN [1.0, 0.0]
                    WHEN c.winning_outcome_index = 1 THEN [0.0, 1.0] END AS outcome_prices_final,
               c.winning_outcome_index,
               s.share_volume AS volume_clob, s.usdc_volume, s.n_fills
        FROM v2_conditions c
        JOIN (SELECT t.condition_id, SUM(r.shares) FILTER (WHERE r.is_taker_rec) AS share_volume,
                     SUM(r.usdc) FILTER (WHERE r.is_taker_rec) AS usdc_volume, COUNT(*) AS n_fills
              FROM v2_raw r JOIN v2_tokens t ON t.token_id = r.token_id GROUP BY 1) s USING (condition_id);
    """)
    con.execute("""
        CREATE OR REPLACE VIEW winning_outcomes AS
        SELECT condition_id, slug, question, neg_risk, event_id, winning_outcome_index,
               outcomes[winning_outcome_index + 1] AS winning_outcome_name,
               clob_token_ids[winning_outcome_index + 1] AS winning_token_id, 1.0 AS winning_outcome_price
        FROM markets WHERE winning_outcome_index IS NOT NULL;
    """)
    con.execute("""
        CREATE OR REPLACE VIEW fills AS
        SELECT r.exchange, r.block_number, r.ts_utc, r.tx_hash, r.evt_index, r.order_hash,
               r.maker, r.taker, NULL AS maker_asset_id, NULL AS taker_asset_id,
               r.maker_amount_raw, r.taker_amount_raw, r.fee_raw,
               r.token_id, t.condition_id, t.outcome_index,
               r.side AS maker_side, r.usdc, r.shares, r.price, r.is_taker_rec AS is_taker_order,
               r.builder, r.metadata
        FROM v2_raw r LEFT JOIN v2_tokens t ON t.token_id = r.token_id;
    """)
    con.execute("""
        CREATE OR REPLACE VIEW trades AS
        SELECT t.condition_id, r.token_id AS asset_id,
               CASE WHEN t.outcome_index = 0 THEN 'Yes' ELSE 'No' END AS outcome, t.outcome_index,
               r.maker AS proxy_wallet, NULL AS pseudonym, NULL AS name, NULL::BOOLEAN AS verified,
               r.side, r.price, r.shares AS size, r.usdc AS notional_usdc, r.ts_utc, r.tx_hash,
               NULL AS event_slug, t.condition_id AS market_slug, t.condition_id AS title,
               r.fee_raw / 1e6 AS fee_usdc, r.builder
        FROM v2_raw r JOIN v2_tokens t ON t.token_id = r.token_id
        WHERE r.is_taker_rec;
    """)
    con.execute("""
        CREATE OR REPLACE VIEW prices_history AS
        SELECT token_id, date_trunc('minute', ts_utc)::TIMESTAMPTZ AS ts_utc,
               SUM(usdc) / NULLIF(SUM(shares), 0) AS price
        FROM v2_raw WHERE NOT is_taker_rec GROUP BY 1, 2;
    """)

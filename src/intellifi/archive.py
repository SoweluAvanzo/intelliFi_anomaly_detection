"""Loader for the public Polymarket-v1 archive (arXiv:2606.04217, CC-BY-4.0).

The archive's cleaned daily layers (``daily_aligned`` for standard binary
markets, ``daily_aligned_multi`` for negRisk families) hold one row per
**maker fill** — maker, taker, taker direction, price, USDC, fee — joined to
market metadata (category, open/close/resolution times, winning outcome).
Reconciled 2026-08-29 against our own on-chain reconstruction: row counts
equal our maker-record counts exactly (see ``fills.reconcile_fills``).

This module exposes the archive through the *same view names* the Stage I
code expects (``markets``, ``trades``, ``winning_outcomes``, ``fills``), so
concentration, skill, coordination, backtest and convergence run unchanged
on complete v1 data:

* ``fills``   — maker-record granularity (our canonical schema; no tx hash in
  the archive, so ``tx_hash`` is a synthetic key and ``is_taker_order`` is
  False for every row).
* ``trades``  — Data-API-like taker rows: maker fills aggregated per
  (second, taker, token, direction) into one taker order (size = Σ shares,
  price = VWAP), with ``proxy_wallet`` = taker.
* ``markets`` — one row per condition with the columns Stage I uses.
"""
from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from . import config
from .ctf import token_ids

ARCHIVE_DIR = config.DATA_DIR / "external" / "polymarket_v1"


def register_archive_views(con: duckdb.DuckDBPyConnection, *, archive_dir: Path = ARCHIVE_DIR,
                           start: str | None = None, end: str | None = None,
                           condition_ids: list[str] | None = None) -> None:
    """Create ``arc_raw``, ``markets``, ``winning_outcomes``, ``fills``, ``trades`` over the archive."""
    layers = [layer for layer in ("daily_aligned", "daily_aligned_multi")
              if any((archive_dir / layer).glob("*.parquet"))]
    if not layers:
        raise FileNotFoundError(f"no archive partitions under {archive_dir}")
    globs = ", ".join(f"'{(archive_dir / layer / '*.parquet').as_posix()}'" for layer in layers)
    where = []
    if start:
        where.append(f"block_timestamp >= EPOCH(TIMESTAMP '{start}')")
    if end:
        where.append(f"block_timestamp <  EPOCH(TIMESTAMP '{end}')")
    if condition_ids:
        where.append("lower(condition_id) IN (" + ",".join(f"'{c}'" for c in condition_ids) + ")")
    w = ("WHERE " + " AND ".join(where)) if where else ""
    con.execute(f"""
        CREATE OR REPLACE VIEW arc_raw AS
        SELECT lower(condition_id)                           AS condition_id,
               CAST(asset_id AS VARCHAR)                     AS token_id,
               outcome_seq - 1                               AS outcome_index,
               to_timestamp(block_timestamp)::TIMESTAMPTZ    AS ts_utc,
               block_timestamp,
               lower(maker) AS maker, lower(taker) AS taker,
               taker_direction, D, price, usdc_amount, fee_usdc,
               usdc_amount / NULLIF(price, 0)                AS shares,
               neg_risk, category, category_refined, market_slug,
               outcome_label, winning_outcome_label, resolution_status,
               opens_at, close_at, resolved_at, p_event
        FROM read_parquet([{globs}], union_by_name = true)
        {w};
    """)
    con.execute("""
        CREATE OR REPLACE VIEW markets AS
        SELECT condition_id,
               max(market_slug)                  AS slug,
               max(market_slug)                  AS question,
               bool_or(TRY_CAST(neg_risk AS BOOLEAN))  AS neg_risk,
               bool_or(TRY_CAST(neg_risk AS BOOLEAN))  AS event_neg_risk,
               max(category)                     AS category,
               max(category_refined)             AS category_refined,
               min(opens_at)::TIMESTAMPTZ        AS created_at,
               max(close_at)::TIMESTAMPTZ        AS end_date,
               -- any_value() may return a NULL row: use max() for the resolution time
               max(resolved_at)::TIMESTAMPTZ     AS closed_time,
               max(resolution_status)            AS resolution_status,
               list_sort(list(DISTINCT token_id)) AS clob_token_ids_unordered,
               SUM(shares)                       AS volume_clob,
               SUM(usdc_amount)                  AS usdc_volume,
               COUNT(*)                          AS n_fills,
               max(winning_outcome_label)        AS winning_outcome_label,
               max(CASE WHEN outcome_label = winning_outcome_label THEN outcome_index END) AS winning_outcome_index
        FROM arc_raw
        GROUP BY condition_id;
    """)
    con.execute("""
        CREATE OR REPLACE VIEW winning_outcomes AS
        SELECT condition_id, slug, question, neg_risk, NULL AS event_id,
               winning_outcome_index,
               winning_outcome_label AS winning_outcome_name,
               NULL AS winning_token_id, 1.0 AS winning_outcome_price
        FROM markets WHERE winning_outcome_index IS NOT NULL;
    """)
    con.execute("""
        CREATE OR REPLACE VIEW fills AS
        SELECT NULL AS exchange, NULL::BIGINT AS block_number, ts_utc,
               md5(concat_ws('|', block_timestamp, maker, taker, token_id, price, usdc_amount)) AS tx_hash,
               row_number() OVER (ORDER BY block_timestamp, maker, taker, token_id) AS evt_index,
               NULL AS order_hash, maker, taker,
               NULL AS maker_asset_id, NULL AS taker_asset_id,
               NULL::BIGINT AS maker_amount_raw, NULL::BIGINT AS taker_amount_raw,
               CAST(fee_usdc * 1e6 AS BIGINT) AS fee_raw,
               token_id, condition_id, outcome_index,
               CASE WHEN taker_direction = 'BUY' THEN 'SELL' ELSE 'BUY' END AS maker_side,
               usdc_amount AS usdc, shares, price, FALSE AS is_taker_order
        FROM arc_raw;
    """)
    con.execute("""
        CREATE OR REPLACE VIEW prices_history AS
        SELECT token_id, date_trunc('minute', ts_utc)::TIMESTAMPTZ AS ts_utc,
               SUM(usdc_amount) / NULLIF(SUM(shares), 0) AS price
        FROM arc_raw GROUP BY 1, 2;
    """)
    con.execute("""
        CREATE OR REPLACE VIEW trades AS
        SELECT condition_id, token_id AS asset_id,
               any_value(outcome_label) AS outcome, outcome_index,
               taker AS proxy_wallet, NULL AS pseudonym, NULL AS name, NULL::BOOLEAN AS verified,
               taker_direction AS side,
               SUM(usdc_amount) / NULLIF(SUM(shares), 0) AS price,
               SUM(shares) AS size, SUM(usdc_amount) AS notional_usdc,
               min(ts_utc) AS ts_utc,
               md5(concat_ws('|', block_timestamp, taker, token_id, taker_direction)) AS tx_hash,
               NULL AS event_slug, any_value(market_slug) AS market_slug, any_value(market_slug) AS title
        FROM arc_raw
        GROUP BY condition_id, token_id, outcome_index, taker, taker_direction, block_timestamp;
    """)


def token_order(con: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    """Positional clob_token_ids per market from the CTF derivation (outcome 0, outcome 1)."""
    m = con.sql("SELECT condition_id, neg_risk FROM markets").pl()
    rows = [{"condition_id": c, "clob_token_ids": [str(t) for t in token_ids(c, bool(n))]}
            for c, n in zip(m["condition_id"], m["neg_risk"])]
    return pl.DataFrame(rows)


def materialise_markets(con: duckdb.DuckDBPyConnection) -> None:
    """Replace the ``markets`` view by a table with positional ``clob_token_ids``
    (outcome 0, outcome 1) from the CTF derivation and ``outcome_prices_final``
    from the resolved winner, i.e. the columns Stage I scripts index into."""
    m = con.sql("SELECT * FROM markets").pl()
    toks = token_order(con)
    # Resolution time precedence (the archive's resolved_at is NULL for
    # early/contested resolutions and close_at is only the scheduled deadline):
    #   1. on-chain CTF ConditionResolution timestamps (ctf_resolutions*.parquet)
    #   2. Gamma closed_time from markets.parquet (verified == on-chain)
    #   3. archive resolved_at, then close_at — with a loud warning
    import logging
    log = logging.getLogger(__name__)
    roots = [config.PARQUET_DIR, config.REPO_ROOT / "data" / "parquet"]
    res_files = [r / f for r in roots for f in ("ctf_resolutions.parquet", "ctf_resolutions_corpus.parquet") if (r / f).exists()]
    if res_files:
        res = (pl.concat([pl.read_parquet(f, columns=["condition_id", "resolved_ts_utc"]) for f in res_files])
                 .with_columns(pl.col("condition_id").str.to_lowercase()).unique(subset=["condition_id"], keep="last")
                 .rename({"resolved_ts_utc": "ct_chain"}))
        m = (m.join(res, on="condition_id", how="left")
               .with_columns(pl.coalesce(pl.col("ct_chain"), pl.col("closed_time")).alias("closed_time")).drop("ct_chain"))
    ours = next((r / "markets" / "markets.parquet" for r in roots if (r / "markets" / "markets.parquet").exists()), None)
    if ours is not None:
        o = (pl.read_parquet(ours, columns=["condition_id", "closed_time", "end_date", "slug", "question"])
               .with_columns(pl.col("condition_id").str.to_lowercase())
               .rename({"closed_time": "ct_ours", "end_date": "ed_ours", "slug": "slug_ours", "question": "q_ours"}))
        m = (m.join(o, on="condition_id", how="left")
               .with_columns(pl.coalesce(pl.col("closed_time"), pl.col("ct_ours"), pl.col("end_date")).alias("closed_time"),
                             pl.coalesce(pl.col("end_date"), pl.col("ed_ours")).alias("end_date"),
                             pl.coalesce(pl.col("slug_ours"), pl.col("slug")).alias("slug"),
                             pl.coalesce(pl.col("q_ours"), pl.col("question")).alias("question"))
               .drop("ct_ours", "ed_ours", "slug_ours", "q_ours"))
    else:
        m = m.with_columns(pl.coalesce(pl.col("closed_time"), pl.col("end_date")).alias("closed_time"))
    m = m.join(toks, on="condition_id", how="left").with_columns(
        pl.when(pl.col("winning_outcome_index") == 0).then(pl.lit([1.0, 0.0]))
          .when(pl.col("winning_outcome_index") == 1).then(pl.lit([0.0, 1.0]))
          .otherwise(pl.lit(None, dtype=pl.List(pl.Float64))).alias("outcome_prices_final"),
        pl.lit(["Yes", "No"]).alias("outcomes"),
        pl.lit(None, dtype=pl.Utf8).alias("event_id"),
        pl.lit(None, dtype=pl.Utf8).alias("uma_end_date"),
        pl.lit(None, dtype=pl.Datetime("us", "UTC")).alias("game_start_time"),
    )
    n_fallback = int(m["closed_time"].is_null().sum())
    if n_fallback:
        log.warning("%d markets have no resolution timestamp; falling back to close_at (scheduled deadline!)", n_fallback)
        m = m.with_columns(pl.coalesce(pl.col("closed_time"), pl.col("end_date")).alias("closed_time"))
    con.register("markets_df", m.to_arrow())
    con.execute("CREATE OR REPLACE TABLE markets_tbl AS SELECT * FROM markets_df")
    con.execute("DROP VIEW IF EXISTS winning_outcomes")
    con.execute("DROP VIEW IF EXISTS markets")
    con.execute("CREATE VIEW markets AS SELECT * FROM markets_tbl")
    con.execute("""
        CREATE OR REPLACE VIEW winning_outcomes AS
        SELECT condition_id, slug, question, neg_risk, event_id,
               winning_outcome_index,
               winning_outcome_label AS winning_outcome_name,
               clob_token_ids[winning_outcome_index + 1] AS winning_token_id,
               1.0 AS winning_outcome_price
        FROM markets WHERE winning_outcome_index IS NOT NULL;
    """)
    bad = con.execute("""
        SELECT COUNT(*) FROM (SELECT condition_id, max(ts_utc) lf FROM arc_raw GROUP BY 1) f
        JOIN markets m USING (condition_id) WHERE f.lf > m.closed_time + INTERVAL 1 HOUR""").fetchone()[0]
    if bad:
        raise RuntimeError(f"{bad} markets have fills more than 1 h after closed_time: the close reference is wrong "
                           "(provide ctf_resolutions*.parquet or markets.parquet with on-chain closed_time)")

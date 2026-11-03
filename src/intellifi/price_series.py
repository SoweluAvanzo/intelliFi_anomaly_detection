"""Per-market price-at-horizon series for the forecast-quality RQ (calibration).

Pure transforms of cached data (no API calls). For every resolved binary market they give the
market-implied probability of outcome-0 at fixed horizons *before resolution*, plus the realised
outcome, so the series can be calibrated against ground truth (reliability / Brier).

Two eras, one schema (written to separate files; `era` column distinguishes them):

* **v2 (fee era)** — `build_price_series`, source = the v2 tape (`data/parquet/tape_v2`), the
  complete on-chain `OrderFilled` stream. Anchor = oracle resolution (`ctf_v2_conditions`),
  always present, so `anchor_source = 'resolved_at'`.
* **v1 (pre-fee)** — `build_price_series_v1`, source = the public v1 archive
  (`data/external/polymarket_v1`, via `archive.register_archive_views`). Anchor = oracle
  resolution `resolved_at` when the archive has it, else the scheduled close `close_at`
  (`anchor_source` records which). See `docs/PRICE_SERIES_V1.md` for why and the coverage.

Neither store uses `prices_history` (a stale 19-market Stage-I snapshot).

Each fill is mapped to a single outcome-0 frame — `p0 = price` on outcome 0, `p0 = 1 - price` on
outcome 1 — so both legs of a match contribute. Horizon prices are `arg_max(p0, ts)` at or before
`resolved_ts - horizon`; this is dedup-invariant (duplicate rows carry identical `(ts, p0)`), so no
disk-heavy global sort is needed. `p_last` is the last trade at or before `resolved_ts`
(post-resolution settlement trades are excluded from every price column and counted in
`n_post_resolution`).

Output columns (identical across eras): `condition_id, era, resolved_ts, anchor_source,
resolved_at_raw, close_at, win_idx, realized_y0, first_ts, last_ts, lifespan_days, n_price_obs,
n_post_resolution, p_7d, p_1d, p_12h, p_6h, p_1h, p_last, tags, primary_tag, question`.
"""
from __future__ import annotations

from pathlib import Path

import duckdb

from . import config

# horizon column name -> DuckDB INTERVAL literal (time BEFORE resolution)
HORIZONS: dict[str, str] = {
    "p_7d": "7 DAY",
    "p_1d": "1 DAY",
    "p_12h": "12 HOUR",
    "p_6h": "6 HOUR",
    "p_1h": "1 HOUR",
}


def _horizon_sql(resolved_col: str = "resolved_ts") -> str:
    return ",\n        ".join(
        f"arg_max(p0, ts) FILTER (WHERE ts <= {resolved_col} - INTERVAL {lit}) AS {name}"
        for name, lit in HORIZONS.items()
    )


# ---------------------------------------------------------------- v2 (tape) --
def build_price_series(
    con: duckdb.DuckDBPyConnection,
    out_path: str | Path,
    *,
    tape_glob: str | None = None,
    ctf_path: str | None = None,
    clob_path: str | None = None,
) -> Path:
    """v2/fee-era series: single full-tape pass -> enriched parquet at ``out_path``."""
    tape_glob = tape_glob or (config.PARQUET_DIR / "tape_v2" / "*" / "*.parquet").as_posix()
    ctf = ctf_path or (config.PARQUET_DIR / "ctf_v2_conditions.parquet").as_posix()
    clob = clob_path or (config.PARQUET_DIR / "clob_markets" / "tokens.parquet").as_posix()
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    con.execute(
        f"""
        COPY (
          WITH sel AS (
            SELECT condition_id, token0, token1, resolved_ts_utc, winning_outcome_index
            FROM parquet_scan('{ctf}')
            WHERE outcome_slot_count = 2
              AND winning_outcome_index IN (0, 1)
              AND list_contains([[1, 0], [0, 1]], payout_numerators)
          ),
          tok AS (
            SELECT condition_id, token0 AS tok, 0 AS idx, resolved_ts_utc, winning_outcome_index FROM sel
            UNION ALL
            SELECT condition_id, token1 AS tok, 1 AS idx, resolved_ts_utc, winning_outcome_index FROM sel
          ),
          fills AS (
            SELECT tok.condition_id,
                   tok.resolved_ts_utc       AS resolved_ts,
                   tok.winning_outcome_index AS win_idx,
                   t.ts_utc                  AS ts,
                   CASE WHEN tok.idx = 0 THEN t.price ELSE 1.0 - t.price END AS p0
            FROM parquet_scan('{tape_glob}') t
            JOIN tok ON t.token_id = tok.tok
            WHERE t.exchange IN ('v2_a', 'v2_b')
              AND t.event = 'OrderFilled'
              AND t.price IS NOT NULL AND t.price >= 0 AND t.price <= 1
          ),
          agg AS (
            SELECT condition_id,
                   any_value(resolved_ts) AS resolved_ts,
                   any_value(win_idx)     AS win_idx,
                   min(ts)                AS first_ts,
                   max(ts)                AS last_ts,
                   count(*)               AS n_price_obs,
                   count(*) FILTER (WHERE ts > resolved_ts) AS n_post_resolution,
                   {_horizon_sql()},
                   arg_max(p0, ts) FILTER (WHERE ts <= resolved_ts) AS p_last
            FROM fills
            GROUP BY condition_id
          ),
          cat AS (
            SELECT condition_id, any_value(tags) AS tags, any_value(question) AS question
            FROM parquet_scan('{clob}') GROUP BY condition_id
          )
          SELECT a.condition_id,
                 'v2'                                                        AS era,
                 a.resolved_ts,
                 'resolved_at'                                               AS anchor_source,
                 a.resolved_ts                                              AS resolved_at_raw,
                 CAST(NULL AS TIMESTAMPTZ)                                   AS close_at,
                 a.win_idx,
                 (a.win_idx = 0)::INT                                        AS realized_y0,
                 a.first_ts, a.last_ts,
                 date_diff('second', a.first_ts, a.resolved_ts) / 86400.0    AS lifespan_days,
                 a.n_price_obs, a.n_post_resolution,
                 a.p_7d, a.p_1d, a.p_12h, a.p_6h, a.p_1h, a.p_last,
                 c.tags,
                 CASE WHEN len(c.tags) > 0 THEN c.tags[1] END                AS primary_tag,
                 c.question
          FROM agg a
          LEFT JOIN cat c USING (condition_id)
        ) TO '{out_path.as_posix()}' (FORMAT PARQUET)
        """
    )
    return out_path


# ------------------------------------------------------------ v1 (archive) --
def build_price_series_v1(
    con: duckdb.DuckDBPyConnection,
    out_path: str | Path,
    *,
    archive_dir: str | Path | None = None,
) -> Path:
    """v1/pre-fee series from the public archive -> enriched parquet at ``out_path``.

    Two archive passes: (1) a cheap per-condition meta table (resolution anchor + winner +
    category), (2) a hash-aggregate of every fill against that anchor for the horizon prices.
    Anchor = ``resolved_at`` when the archive carries it, else ``close_at`` (``anchor_source``).
    """
    from . import archive

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    kw = {}
    if archive_dir is not None:
        kw["archive_dir"] = Path(archive_dir)
    archive.register_archive_views(con, **kw)

    # pass 1: per-condition resolution anchor + winner + category (project few columns)
    con.execute(
        """
        CREATE OR REPLACE TEMP TABLE _v1_meta AS
        SELECT condition_id,
               max(resolved_at)                                   AS resolved_at_raw,
               max(close_at)                                      AS close_at,
               coalesce(max(resolved_at), max(close_at))          AS resolved_ts,
               CASE WHEN max(resolved_at) IS NOT NULL THEN 'resolved_at' ELSE 'close_at' END AS anchor_source,
               -- win index derivable from EITHER leg (binary): this leg's label vs the winner
               max(CASE WHEN outcome_label = winning_outcome_label THEN outcome_index
                        ELSE 1 - outcome_index END)               AS win_idx,
               any_value(category)                                AS category,
               any_value(category_refined)                        AS category_refined,
               any_value(market_slug)                             AS market_slug
        FROM arc_raw
        WHERE resolution_status = 'resolved'
          AND winning_outcome_label IS NOT NULL
          AND outcome_index IN (0, 1)
        GROUP BY condition_id
        HAVING coalesce(max(resolved_at), max(close_at)) IS NOT NULL
           AND max(CASE WHEN outcome_label = winning_outcome_label THEN outcome_index
                        ELSE 1 - outcome_index END) IN (0, 1)
        """
    )

    # pass 2: horizon prices, one row per market
    con.execute(
        f"""
        COPY (
          WITH fills AS (
            SELECT a.condition_id, m.resolved_ts, m.win_idx,
                   m.resolved_at_raw, m.close_at, m.anchor_source,
                   m.category, m.category_refined, m.market_slug,
                   a.ts_utc AS ts,
                   CASE WHEN a.outcome_index = 0 THEN a.price ELSE 1.0 - a.price END AS p0
            FROM arc_raw a
            JOIN _v1_meta m USING (condition_id)
            WHERE a.price IS NOT NULL AND a.price >= 0 AND a.price <= 1
              AND a.outcome_index IN (0, 1)
          )
          SELECT condition_id,
                 'v1'                                                     AS era,
                 any_value(resolved_ts)                                   AS resolved_ts,
                 any_value(anchor_source)                                 AS anchor_source,
                 any_value(resolved_at_raw)                               AS resolved_at_raw,
                 any_value(close_at)                                      AS close_at,
                 any_value(win_idx)                                       AS win_idx,
                 (any_value(win_idx) = 0)::INT                            AS realized_y0,
                 min(ts)                                                  AS first_ts,
                 max(ts)                                                  AS last_ts,
                 date_diff('second', min(ts), any_value(resolved_ts))/86400.0 AS lifespan_days,
                 count(*)                                                 AS n_price_obs,
                 count(*) FILTER (WHERE ts > resolved_ts)                 AS n_post_resolution,
                 {_horizon_sql()},
                 arg_max(p0, ts) FILTER (WHERE ts <= resolved_ts)         AS p_last,
                 [any_value(category), any_value(category_refined)]       AS tags,
                 any_value(category)                                      AS primary_tag,
                 any_value(market_slug)                                   AS question
          FROM fills
          GROUP BY condition_id
        ) TO '{out_path.as_posix()}' (FORMAT PARQUET)
        """
    )
    return out_path


# --------------------------------------------------------------- verify --
def verify(con: duckdb.DuckDBPyConnection, path: str | Path) -> None:
    """Print data-quality / validity checks for a built series (either era)."""
    t = f"parquet_scan('{Path(path).as_posix()}')"
    print("rows / price-obs:")
    print(con.sql(f"SELECT any_value(era) era, count(*) markets, sum(n_price_obs) price_obs FROM {t}").df().to_string(index=False))
    print("\nanchor source:")
    print(con.sql(f"SELECT anchor_source, count(*) n FROM {t} GROUP BY 1 ORDER BY 2 DESC").df().to_string(index=False))
    print("\nhorizon coverage (% non-null):")
    cov = ", ".join(f"round(100.0*count({c})/count(*),2) AS {c}" for c in [*HORIZONS, "p_last"])
    print(con.sql(f"SELECT {cov} FROM {t}").df().to_string(index=False))
    print("\nlifespan: median / %>=7d / %>=1d / n>=7d:")
    print(con.sql(
        f"SELECT round(median(lifespan_days),4) med_d, round(100.0*avg((lifespan_days>=7)::INT),2) pct_7d, "
        f"round(100.0*avg((lifespan_days>=1)::INT),2) pct_1d, count(*) FILTER (WHERE lifespan_days>=7) n_7d FROM {t}"
    ).df().to_string(index=False))
    print("\nwinner convergence (mean p_last should split ~0 / ~1):")
    print(con.sql(
        f"SELECT realized_y0, count(*) n, round(avg(p_last),4) mean_p_last FROM {t} "
        f"WHERE p_last IS NOT NULL GROUP BY realized_y0 ORDER BY realized_y0"
    ).df().to_string(index=False))
    print("\ncalibration @1d (pred vs empirical by decile):")
    print(con.sql(
        f"WITH b AS (SELECT least(9,floor(p_1d*10))::INT dbin, realized_y0, p_1d FROM {t} WHERE p_1d IS NOT NULL) "
        f"SELECT dbin decile, count(*) n, round(avg(p_1d),3) pred, round(avg(realized_y0),3) emp "
        f"FROM b GROUP BY dbin ORDER BY dbin"
    ).df().to_string(index=False))
    print("\nBrier (0.25 = coin flip):")
    print(con.sql(
        f"SELECT round(avg((p_1d-realized_y0)^2),4) brier_1d, round(avg((p_last-realized_y0)^2),4) brier_last FROM {t}"
    ).df().to_string(index=False))

"""Per-market price-at-horizon series for the forecast-quality RQ (calibration).

This is a **pure transform of cached data** — no API calls. It reconstructs, for
every resolved binary market, the market-implied probability of outcome-0 at a set
of fixed horizons *before resolution*, plus the realised outcome, so the series can
be calibrated against ground truth (reliability / Brier).

Price source is the **v2 tape** (``data/parquet/tape_v2``), NOT ``prices_history``:
the latter is a stale Stage-I 30-day CLOB snapshot covering only 19 markets and is
irrelevant here (see ``docs/PRICE_SERIES_RQ1.md``).

The six read-time rules for the v2 tape (the store is NOT pre-cleaned) are baked in:

1. ``exchange IN ('v2_a','v2_b')``            — drop the other-emitter rows.
2. ``event = 'OrderFilled'``                  — price-bearing logs only.
3. ``price IS NOT NULL AND 0 <= price <= 1``  — drop null / out-of-band prices.
4. null-``token_id`` rows (the ``is_taker_order IS NULL`` defect bucket) drop
   implicitly via the inner join on ``token_id``.
5. dedup of overlapping tape chunks by ``(tx_hash, evt_index)`` is **not** done with
   a global sort (which is disk-expensive): every horizon price is an
   ``arg_max(p0, ts)``, and duplicate chunk rows carry identical ``(ts, p0)`` so the
   result is dedup-invariant. ``n_price_obs`` is therefore a raw fill-leg count that
   may be inflated by the ~2% chunk overlap — it is a liquidity proxy, not a trade
   count.
6. only clean binary resolutions are kept: ``outcome_slot_count = 2``,
   ``winning_outcome_index IN (0,1)`` and ``payout_numerators IN ([1,0],[0,1])``
   (drops the ~1.6% null-winner / void conditions).

Each fill is mapped into a single "outcome-0" frame: ``p0 = price`` when the fill is
on ``token0`` and ``p0 = 1 - price`` when on ``token1`` — so *both* legs of every
match contribute, maximising coverage.

Output: one row per traded market with columns described in ``docs/PRICE_SERIES_RQ1.md``.
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


def _paths(tape_glob: str | None, ctf: str | None, clob: str | None) -> tuple[str, str, str]:
    tape_glob = tape_glob or (config.PARQUET_DIR / "tape_v2" / "*" / "*.parquet").as_posix()
    ctf = ctf or (config.PARQUET_DIR / "ctf_v2_conditions.parquet").as_posix()
    clob = clob or (config.PARQUET_DIR / "clob_markets" / "tokens.parquet").as_posix()
    return tape_glob, ctf, clob


def build_price_series(
    con: duckdb.DuckDBPyConnection,
    out_path: str | Path,
    *,
    tape_glob: str | None = None,
    ctf_path: str | None = None,
    clob_path: str | None = None,
) -> Path:
    """Single full-tape pass -> enriched per-market price-at-horizon parquet at ``out_path``."""
    tape_glob, ctf, clob = _paths(tape_glob, ctf_path, clob_path)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    horizon_cols = ",\n        ".join(
        f"arg_max(p0, ts) FILTER (WHERE ts <= resolved_ts - INTERVAL {lit}) AS {name}"
        for name, lit in HORIZONS.items()
    )

    con.execute(
        f"""
        COPY (
          WITH sel AS (
            SELECT condition_id, token0, token1, resolved_ts_utc, winning_outcome_index
            FROM parquet_scan('{ctf}')
            WHERE outcome_slot_count = 2
              AND winning_outcome_index IN (0, 1)
              AND list_contains([[1, 0], [0, 1]], payout_numerators)       -- rule 6
          ),
          tok AS (  -- one row per outcome token, tagged with its frame index
            SELECT condition_id, token0 AS tok, 0 AS idx, resolved_ts_utc, winning_outcome_index FROM sel
            UNION ALL
            SELECT condition_id, token1 AS tok, 1 AS idx, resolved_ts_utc, winning_outcome_index FROM sel
          ),
          fills AS (
            SELECT tok.condition_id,
                   tok.resolved_ts_utc       AS resolved_ts,
                   tok.winning_outcome_index AS win_idx,
                   t.ts_utc                  AS ts,
                   CASE WHEN tok.idx = 0 THEN t.price ELSE 1.0 - t.price END AS p0   -- outcome-0 frame
            FROM parquet_scan('{tape_glob}') t
            JOIN tok ON t.token_id = tok.tok                                 -- rule 4 (null token drops)
            WHERE t.exchange IN ('v2_a', 'v2_b')                             -- rule 1
              AND t.event = 'OrderFilled'                                    -- rule 2
              AND t.price IS NOT NULL AND t.price >= 0 AND t.price <= 1      -- rule 3
          ),
          agg AS (
            SELECT condition_id,
                   any_value(resolved_ts) AS resolved_ts,
                   any_value(win_idx)     AS win_idx,
                   min(ts)                AS first_ts,
                   max(ts)                AS last_ts,
                   count(*)               AS n_price_obs,                    -- rule 5 caveat (~2% high)
                   count(*) FILTER (WHERE ts > resolved_ts) AS n_post_resolution,  -- settlement trades
                   {horizon_cols},
                   arg_max(p0, ts) FILTER (WHERE ts <= resolved_ts) AS p_last       -- last PRE-resolution forecast
            FROM fills
            GROUP BY condition_id
          ),
          cat AS (
            SELECT condition_id, any_value(tags) AS tags, any_value(question) AS question
            FROM parquet_scan('{clob}') GROUP BY condition_id
          )
          SELECT a.*,
                 (a.win_idx = 0)::INT                                        AS realized_y0,
                 date_diff('second', a.first_ts, a.resolved_ts) / 86400.0    AS lifespan_days,
                 c.tags,
                 CASE WHEN len(c.tags) > 0 THEN c.tags[1] END                AS primary_tag,
                 c.question
          FROM agg a
          LEFT JOIN cat c USING (condition_id)
        ) TO '{out_path.as_posix()}' (FORMAT PARQUET)
        """
    )
    return out_path


def verify(con: duckdb.DuckDBPyConnection, path: str | Path) -> None:
    """Print the data-quality / validity checks for a built series (fail-loud if wrong)."""
    t = f"parquet_scan('{Path(path).as_posix()}')"
    print("rows / price-obs:")
    print(con.sql(f"SELECT count(*) AS markets, sum(n_price_obs) AS price_obs FROM {t}").df().to_string(index=False))
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

#!/usr/bin/env python
"""H3 (+ A-consistent H4 order-size) class-week table for Sample-B.

Extends the class panel with the confirmatory H3/H4 statistics, each computed to MATCH
the atlas Sample-A class_week.parquet definitions (built by atlasA/passB_weekly.py):

  per (cls, week):
    maker_hhi, top5_maker_share, top1_maker_share  -- maker NOTIONAL shares over MAKER-FILL
        records (is_taker_order=False); == A hhi/top5/top1 (== scripts/17 H6 logic).
    spread_proxy = sum((pb-ps)*least(vb,vs)) / sum(least(vb,vs)) over (token, minute) where
        pb/ps = taker BUY / SELL VWAP; == A sp_w_sum/sp_w (price units, taker-direction).
    fill_ord_med, fill_ord_mean  -- passB `ords` on maker-fills: per-order summed usdc,
        GROUP BY (taker, token, ts_sec, is_buy); == A ord_med/ord_mean. USE FOR H4.
    tk_ord_med, tk_ord_mean  -- median/avg usdc over is_taker_order=True records (= the
        panel's taker_order_median_notional); the taker's own matched notional, NOT
        sum-of-fills -> a DIFFERENT quantity than A ord_med. Kept for reference/contrast.
    fee_free_share, n_taker_orders  -- from is_tk records (fees live there).

Memory-safe like scripts/21: block-CHUNKED build of the slim per-fill tables (hashed
maker/taker/token keys), file-backed DuckDB + on-disk temp spill. Class via token_cls.

    python scripts/25_class_week_h3.py --out data/parquet/atlas_v2/class_week_b_h3.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi.fills import TAPE_V2_DIR  # noqa: E402
from intellifi import config as _cfg  # noqa: E402

TOKEN_CLS = _cfg.PARQUET_DIR / "atlas_v2" / "token_cls.parquet"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-block", type=int, default=86_126_978)
    ap.add_argument("--to-block", type=int, default=92_995_000)
    ap.add_argument("--out", default="data/parquet/atlas_v2/class_week_b_h3.parquet")
    ap.add_argument("--memory-limit", default="12GB")
    args = ap.parse_args()

    glob = (TAPE_V2_DIR / "blocks=*" / "part.parquet").as_posix()
    tmp = _cfg.DATA_DIR / "_h3_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    dbf = tmp / "h3.duckdb"
    if dbf.exists():
        dbf.unlink()
    con = duckdb.connect(str(dbf))
    con.execute("SET TimeZone='UTC'; SET preserve_insertion_order=false; SET threads=3")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='150GB'")

    # token -> (cls, condition_id). cls from the mapper cache; condition from clob tokens.
    # A's passB builds maker HHI over (condition, maker) pairs (mkv GROUP BY cid,cat,cls,mk),
    # so B must group HHI/top5/top1 by (condition, maker) too -- else the maker-only-vs-
    # market×maker definition gap shows up as a spurious ~85x B/A ratio in high-fill classes.
    tok = pl.read_parquet(TOKEN_CLS)
    toks = (pl.read_parquet((_cfg.PARQUET_DIR / "clob_markets" / "tokens.parquet").as_posix())
              .select(["token_id", "condition_id"]).unique(subset=["token_id"]))
    meta = tok.join(toks, on="token_id", how="left")
    con.register("meta", meta.to_arrow())
    con.execute("CREATE TABLE token_meta AS SELECT token_id, cls, condition_id FROM meta")

    # slim per-fill MAKER-FILL table (is_taker_order=False), hashed keys, chunked + deduped.
    con.execute("""CREATE TABLE mf (week DATE, cls VARCHAR, tokh UBIGINT, condh UBIGINT, ts BIGINT,
                   takh UBIGINT, makh UBIGINT, is_buy BOOLEAN, usdc DOUBLE, price DOUBLE)""")
    con.execute("""CREATE TABLE tk (week DATE, cls VARCHAR, usdc DOUBLE, is_fee BOOLEAN)""")
    CHUNK = 300_000
    lo = args.from_block
    while lo <= args.to_block:
        hi = min(lo + CHUNK - 1, args.to_block)
        con.execute(f"""
            INSERT INTO mf
            SELECT date_trunc('week', sub.ts_utc)::DATE AS week,
                   COALESCE(c.cls, '__unmapped__') AS cls,
                   hash(sub.token_id) tokh,
                   hash(COALESCE(c.condition_id, sub.token_id)) condh,
                   EPOCH(sub.ts_utc)::BIGINT ts,
                   hash(sub.taker) takh, hash(sub.maker) makh,
                   -- v2 maker-fill `side` is the MAKER's direction; the TAKER is the opposite.
                   -- Verified: maker-side BUY spread = -0.0146 vs is_taker_order ground truth
                   -- +0.0138 (and A-April +0.0156). Store is_buy = TAKER direction (= maker SELL)
                   -- so the realized-spread sign and passB's taker-direction order grouping are correct.
                   (sub.side = 'SELL') is_buy, sub.usdc, sub.price
            FROM (SELECT token_id, ts_utc, taker, maker, side, usdc, price, tx_hash, evt_index
                  FROM read_parquet('{glob}', hive_partitioning=true)
                  WHERE event='OrderFilled' AND exchange IN ('v2_a','v2_b')
                    AND is_taker_order = FALSE AND block_number BETWEEN {lo} AND {hi}
                    AND price > 0 AND price < 1 AND usdc > 0
                  QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1) sub
            LEFT JOIN token_meta c USING (token_id);
        """)
        con.execute(f"""
            INSERT INTO tk
            SELECT date_trunc('week', sub.ts_utc)::DATE AS week,
                   COALESCE(c.cls, '__unmapped__') AS cls, sub.usdc, (sub.fee_raw > 0) is_fee
            FROM (SELECT token_id, ts_utc, usdc, fee_raw, tx_hash, evt_index
                  FROM read_parquet('{glob}', hive_partitioning=true)
                  WHERE event='OrderFilled' AND exchange IN ('v2_a','v2_b')
                    AND is_taker_order = TRUE AND block_number BETWEEN {lo} AND {hi} AND usdc > 0
                  QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1) sub
            LEFT JOIN token_meta c USING (token_id);
        """)
        print(f"  loaded chunk [{lo:,}..{hi:,}]", flush=True)
        lo = hi + 1

    # maker concentration (A hhi/top5/top1) over (CONDITION, MAKER) notional shares -- matches
    # passB's mkv GROUP BY (cid,cat,cls,mk). top5/top1 are the top (condition,maker) PAIR shares.
    hhi = con.execute("""
        WITH mkv AS (SELECT cls, week, condh, makh, SUM(usdc) v FROM mf GROUP BY 1,2,3,4),
        r AS (SELECT cls, week, v, SUM(v) OVER (PARTITION BY cls,week) tot,
                     row_number() OVER (PARTITION BY cls,week ORDER BY v DESC) rk FROM mkv)
        SELECT cls, week, SUM((v/tot)*(v/tot)) maker_hhi,
               SUM(CASE WHEN rk<=5 THEN v/tot ELSE 0 END) top5_maker_share,
               SUM(CASE WHEN rk<=1 THEN v/tot ELSE 0 END) top1_maker_share,
               COUNT(*) n_mm_pairs
        FROM r GROUP BY 1,2
    """).df()
    # distinct makers per class-week (reference / venue-maker-count comparison; not the HHI basis)
    nmk = con.execute("SELECT cls, week, COUNT(DISTINCT makh) n_makers FROM mf GROUP BY 1,2").df()
    hhi = hhi.merge(nmk, on=["cls", "week"], how="left")

    # realized-spread proxy (A sp_w) : (token, minute) taker BUY/SELL VWAP, vol-weighted
    spr = con.execute("""
        WITH mins AS (
            SELECT cls, week, tokh, ts//60 mn,
                   SUM(CASE WHEN is_buy THEN usdc END) vb,
                   SUM(CASE WHEN NOT is_buy THEN usdc END) vs,
                   SUM(CASE WHEN is_buy THEN usdc END)/SUM(CASE WHEN is_buy THEN usdc/price END) pb,
                   SUM(CASE WHEN NOT is_buy THEN usdc END)/SUM(CASE WHEN NOT is_buy THEN usdc/price END) ps
            FROM mf GROUP BY 1,2,3,4)
        SELECT cls, week,
               SUM((pb-ps)*least(vb,vs))/NULLIF(SUM(least(vb,vs)),0) spread_proxy,
               SUM(least(vb,vs)) sp_w, COUNT(*) n_minpairs
        FROM mins WHERE vb>0 AND vs>0 GROUP BY 1,2
    """).df()

    # A-consistent order size (passB ords): per-order summed maker-fill usdc
    ford = con.execute("""
        WITH ords AS (SELECT cls, week, SUM(usdc) sz FROM mf
                      GROUP BY cls, week, takh, tokh, ts, is_buy)
        SELECT cls, week, median(sz) fill_ord_med, avg(sz) fill_ord_mean,
               COUNT(*) n_fill_orders
        FROM ords GROUP BY 1,2
    """).df()

    # is_tk-record order size (panel's taker_order_median_notional) + fee-free share
    tord = con.execute("""
        SELECT cls, week, median(usdc) tk_ord_med, avg(usdc) tk_ord_mean,
               AVG((NOT is_fee)::INT) fee_free_share, COUNT(*) n_taker_orders
        FROM tk GROUP BY 1,2
    """).df()

    out = (hhi.merge(spr, on=["cls", "week"], how="outer")
              .merge(ford, on=["cls", "week"], how="outer")
              .merge(tord, on=["cls", "week"], how="outer")
              .sort_values(["week", "cls"]))
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(out).write_parquet(args.out)
    print(f"wrote {args.out}: {len(out)} class-weeks, {out['cls'].nunique()} classes", flush=True)

    con.close()
    for p in (dbf, dbf.with_suffix(".duckdb.wal")):
        try:
            p.unlink()
        except OSError:
            pass
    print("H3_DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

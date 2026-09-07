#!/usr/bin/env python
"""H1a: taker round-trip VOLUME share by WASH class + fee, Sample-B, matching atlasB s03.

Pre-reg H1a = share of taker VOLUME in same-wallet BUY<->SELL round trips (600s, size-overlap
>= 50%). Reproduces atlasB/s03_daily_rt_pairs.py's lag/lead adjacent-opposite-order rule:
an order is a round-trip leg if its PREVIOUS (close_leg) or NEXT (open_leg) opposite-direction
order on the same asset by the same taker is within 600s with least/greatest share >= 0.5.
rt_any = close OR open (BOTH legs = "volume IN a round trip", the pre-reg primary); rt_close =
closing legs only; rt60 = close within 60s.

Built over the v2 MAKER-FILL records (is_taker_order=False) = A's fill-level data (s03 builds
orders from FILLS), taker direction = OPPOSITE of the maker's `side`, grouped by (taker, token,
ts, taker-dir) into orders like s03's `o`; the order fee_flag is joined from the is_tk taker-order
records (fees live there). Verified: building from is_tk records instead inflates rt ~4x (geo
control 0.059 vs maker-fill 0.0145 vs A 0.0046). Class = WASH taxonomy (coarse): each token's
RAW primary tag (first tag matching wash_category_mapping.csv) -> cls, with NO feeclass
geo-recapture -- matching A's wash reference construction (category_refined -> csv -> cls) so
the B-vs-A comparison is like-for-like (the recapture stays for H3/H4 feeclass only).

    python scripts/26_h1a_rt_wash.py --out data/parquet/atlas_v2/h1a_rt_wash_b.parquet
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import duckdb
import polars as pl

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "docs/atlas_2026-08-30/scripts/atlasA"))
from intellifi.fills import TAPE_V2_DIR  # noqa: E402
from intellifi import config as _cfg  # noqa: E402
import feeclass  # _TENNIS / _ESPORT slug regexes  # noqa: E402

TOKENS = _cfg.PARQUET_DIR / "clob_markets" / "tokens.parquet"
WASH_MAP_CSV = _cfg.PARQUET_DIR / "atlas" / "wash_category_mapping.csv"


def _load_cat2cls() -> dict:
    """category / category_refined -> coarse wash cls, from A's OWN wash_category_mapping.csv
    (first occurrence wins; the csv is vol-sorted, so that's the dominant mapping)."""
    import csv as _csv
    d: dict = {}
    with open(WASH_MAP_CSV) as f:
        for r in _csv.DictReader(f):
            for k in (r["category"], r["category_refined"]):
                if k and k not in d:
                    d[k] = r["cls"]
    return d


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-block", type=int, default=86_126_978)
    ap.add_argument("--to-block", type=int, default=92_995_000)
    ap.add_argument("--out", default="data/parquet/atlas_v2/h1a_rt_wash_b.parquet")
    ap.add_argument("--memory-limit", default="12GB")
    args = ap.parse_args()

    # token -> wash_cls: RAW primary-tag (first tag matching the csv) -> wash cls, NO feeclass
    # geo-recapture -- matches A's wash reference construction (A: category_refined -> csv -> cls).
    # The recapture stays for H3/H4 feeclass; it is wrong HERE because A's wash taxonomy lacks it.
    cat2cls = _load_cat2cls()
    esports_tags = {k for k, v in cat2cls.items() if v == "esports"}

    def _wash(tags) -> str:
        tl = list(tags) if tags is not None else []
        # esports keyword beats a broad 'Sports' at tags[0]: esports markets lead with
        # ['Sports','Esports',...] so a plain first-tag scan leaks ~99% of them to sports.
        # A's category_refined='Esports' for these -> esports. (Only esports gets this priority;
        # the geo/politics split stays first-tag, which matched A: politics 0.118 vs A 0.106.)
        if any(t in esports_tags for t in tl):
            return "esports"
        for t in tl:
            if t in cat2cls:
                return cat2cls[t]
        return "other"

    wm = (pl.read_parquet(TOKENS).select(["token_id", "tags"]).unique(subset=["token_id"])
            .with_columns(pl.col("tags").map_elements(_wash, return_dtype=pl.Utf8).alias("wash_cls"))
            .select(["token_id", "wash_cls"]))

    glob = (TAPE_V2_DIR / "blocks=*" / "part.parquet").as_posix()
    tmp = _cfg.DATA_DIR / "_h1a_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    dbf = tmp / "h1a.duckdb"
    if dbf.exists():
        dbf.unlink()
    con = duckdb.connect(str(dbf))
    con.execute("SET TimeZone='UTC'; SET preserve_insertion_order=false; SET threads=3")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"SET temp_directory='{tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='150GB'")
    con.register("wm", wm.to_arrow())
    con.execute("CREATE TABLE wmap AS SELECT * FROM wm")

    # Ingest MAKER-FILL records (is_taker_order=FALSE) = A's fill-level data (s03 builds orders
    # from FILLS). taker direction = OPPOSITE of the maker's `side`. Separately ingest a
    # taker-order (is_tk) fee lookup, since fees live on is_tk (maker-fills have fee_raw=0).
    # (Verified: building orders from is_tk records instead inflates rt ~4x -- geo control 0.059
    # vs maker-fill 0.0145 vs A 0.0046 -- so maker-fill is the A-consistent construction.)
    con.execute("""CREATE TABLE mfo (wash_cls VARCHAR, takh UBIGINT, tokh UBIGINT, ts BIGINT,
                   dir VARCHAR, usdc DOUBLE, sh DOUBLE)""")
    con.execute("""CREATE TABLE tkf (takh UBIGINT, tokh UBIGINT, ts BIGINT, dir VARCHAR, fee_flag BOOLEAN)""")
    CHUNK = 300_000
    lo = args.from_block
    while lo <= args.to_block:
        hi = min(lo + CHUNK - 1, args.to_block)
        con.execute(f"""
            INSERT INTO mfo
            SELECT COALESCE(w.wash_cls, 'other') wash_cls, hash(sub.taker) takh, hash(sub.token_id) tokh,
                   sub.ts, CASE WHEN sub.side='SELL' THEN 'BUY' ELSE 'SELL' END dir,
                   sub.usdc, sub.usdc/sub.price sh
            FROM (SELECT taker, token_id, EPOCH(ts_utc)::BIGINT ts, side, usdc, price, tx_hash, evt_index
                  FROM read_parquet('{glob}', hive_partitioning=true)
                  WHERE event='OrderFilled' AND exchange IN ('v2_a','v2_b') AND is_taker_order=FALSE
                    AND block_number BETWEEN {lo} AND {hi} AND price>0 AND price<1 AND usdc>0
                  QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1) sub
            LEFT JOIN wmap w ON w.token_id = sub.token_id;
        """)
        con.execute(f"""
            INSERT INTO tkf
            -- on is_taker_order=TRUE records the TAKER WALLET is in the `maker` field (taker =
            -- exchange addr); key on maker so it joins the maker-fill orders' taker (takh).
            SELECT hash(sub.maker), hash(sub.token_id), sub.ts, sub.side, sub.fee_flag
            FROM (SELECT maker, token_id, EPOCH(ts_utc)::BIGINT ts, side, (fee_raw>0) fee_flag, tx_hash, evt_index
                  FROM read_parquet('{glob}', hive_partitioning=true)
                  WHERE event='OrderFilled' AND exchange IN ('v2_a','v2_b') AND is_taker_order=TRUE
                    AND block_number BETWEEN {lo} AND {hi} AND price>0 AND price<1 AND usdc>0
                  QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1) sub;
        """)
        print(f"  ingested chunk [{lo:,}..{hi:,}]", flush=True)
        lo = hi + 1

    # orders (s03 `o`): group maker-fills by (taker, asset, second, taker-dir); fee from is_tk lookup
    con.execute("""CREATE TABLE ordagg AS
        SELECT wash_cls, takh, tokh, ts, dir, SUM(usdc) usdc, SUM(sh) sh
        FROM mfo GROUP BY 1,2,3,4,5""")
    con.execute("""CREATE TABLE feem AS
        SELECT takh, tokh, ts, dir, MAX(fee_flag) fee_flag FROM tkf GROUP BY 1,2,3,4""")
    con.execute("""CREATE TABLE o AS
        SELECT a.*, COALESCE(f.fee_flag, FALSE) fee_flag
        FROM ordagg a LEFT JOIN feem f USING (takh, tokh, ts, dir)""")
    for _t in ("mfo", "tkf", "ordagg", "feem"):
        con.execute(f"DROP TABLE {_t}")

    # lag/lead round-trip legs (s03 rule)
    con.execute("""CREATE TABLE fl AS
        WITH w AS (
            SELECT wash_cls, fee_flag, usdc, ts, dir, sh,
                   lag(ts) OVER win p_ts, lag(dir) OVER win p_dir, lag(sh) OVER win p_sh,
                   lead(ts) OVER win n_ts, lead(dir) OVER win n_dir, lead(sh) OVER win n_sh
            FROM o WINDOW win AS (PARTITION BY takh, tokh ORDER BY ts, dir))
        SELECT wash_cls, fee_flag, usdc, (ts - p_ts) AS gap_close,
               (p_ts IS NOT NULL AND p_dir<>dir AND ts-p_ts<=600 AND least(sh,p_sh)/greatest(sh,p_sh)>=0.5) close_leg,
               (n_ts IS NOT NULL AND n_dir<>dir AND n_ts-ts<=600 AND least(sh,n_sh)/greatest(sh,n_sh)>=0.5) open_leg
        FROM w""")

    res = con.execute("""
        SELECT wash_cls, fee_flag, COUNT(*) n_orders, SUM(usdc) vol,
               SUM(CASE WHEN close_leg THEN usdc ELSE 0 END) rt_close_vol,
               SUM(CASE WHEN close_leg OR open_leg THEN usdc ELSE 0 END) rt_any_vol,
               SUM(CASE WHEN close_leg AND gap_close<=60 THEN usdc ELSE 0 END) rt_close_vol_60s
        FROM fl GROUP BY 1,2 ORDER BY 1,2""").df()
    res["rt_close_share"] = res.rt_close_vol / res.vol
    res["rt_any_share"] = res.rt_any_vol / res.vol
    res["rt60_share"] = res.rt_close_vol_60s / res.vol
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    pl.from_pandas(res).write_parquet(args.out)

    # per-wash-cls VOLUME shares (the peer's eyeball guard vs A class shares)
    tot = float(res["vol"].sum())
    vs = (res.groupby("wash_cls")["vol"].sum() / tot).sort_values(ascending=False)
    print(f"wrote {args.out}: {len(res)} (wash_cls,fee) rows", flush=True)
    print("VOL_SHARE_BY_WASH_CLS:", flush=True)
    for c, s in vs.items():
        print(f"  {c:20s} {s:.4f}", flush=True)
    print("RT_ANY_SHARE (fee_flag rows):", flush=True)
    for r in res[res.fee_flag].itertuples():
        print(f"  {r.wash_cls:20s} rt_any={r.rt_any_share:.4f} rt_close={r.rt_close_share:.4f} n_orders={int(r.n_orders):,}", flush=True)

    con.close()
    for p in (dbf, dbf.with_suffix(".duckdb.wal")):
        try:
            p.unlink()
        except OSError:
            pass
    print("H1A_DONE", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

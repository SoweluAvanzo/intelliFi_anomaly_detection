#!/usr/bin/env python
"""Enumerate the COMPLETE Polymarket market set via CLOB cursor pagination and
write a per-token metadata table for joining to the on-chain tape.

The CLOB /markets endpoint is cursor-paged (no ~2000 offset ceiling) and
token/condition-native, so it captures every market losslessly — unlike Gamma
/markets, whose offset ceiling drops markets (including high-volume ones) on
dense endDate days. Output: data/parquet/clob_markets/tokens.parquet, one row per
(market token) with condition_id, neg_risk, closed, question, market_slug, etc.

    python scripts/14_fetch_clob_markets.py --write -v
"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path

import duckdb
import polars as pl

from intellifi import config
from intellifi.clob import iter_clob_markets, clob_market_token_rows

log = logging.getLogger("scripts.14")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--flush-every", type=int, default=20000, help="token rows per part file")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verbose", "-v", action="count", default=0)
    args = ap.parse_args()
    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")

    out_dir = config.PARQUET_DIR / "clob_markets"
    parts = out_dir / "_parts"
    parts.mkdir(parents=True, exist_ok=True)
    for f in parts.glob("part_*.parquet"):
        f.unlink()

    buf: list[dict] = []
    seq = 0
    n_markets = 0
    seen_cond: set[str] = set()

    def flush() -> None:
        nonlocal seq, buf
        if not buf:
            return
        pl.DataFrame(buf).write_parquet(parts / f"part_{seq:05d}.parquet", compression="zstd")
        seq += 1
        buf = []

    for m in iter_clob_markets():
        n_markets += 1
        cid = (m.get("condition_id") or "").lower()
        if cid:
            seen_cond.add(cid)
        buf.extend(clob_market_token_rows(m))
        if len(buf) >= args.flush_every:
            flush()
        if n_markets % 20000 == 0:
            print(f"  {n_markets:,} markets, {len(seen_cond):,} unique conditions", flush=True)
    flush()
    print(f"enumerated {n_markets:,} markets ({len(seen_cond):,} unique conditions) -> {seq} parts")

    if not args.write or seq == 0:
        return 0
    con = duckdb.connect(); con.execute("PRAGMA memory_limit='1GB'"); con.execute("PRAGMA threads=2")
    tmp = out_dir / ".duckdb_tmp"; tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{tmp}'")   # cwd may be read-only (container uid); 5.7M-row window spills
    out = out_dir / "tokens.parquet"
    con.execute(f"""COPY (
        SELECT * FROM read_parquet('{parts}/part_*.parquet')
        QUALIFY row_number() OVER (PARTITION BY coalesce(nullif(token_id, ''), condition_id)) = 1
    ) TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
    nrows, nconds, nnegrisk = con.execute(
        f"SELECT count(*), count(DISTINCT condition_id), count(*) FILTER (WHERE neg_risk) FROM read_parquet('{out}')").fetchone()
    print(f"wrote {out}: {nrows} token rows, {nconds} conditions, {nnegrisk} negRisk tokens")
    return 0


if __name__ == "__main__":
    sys.exit(main())

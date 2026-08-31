"""Stage 8: fetch CLOB /prices-history per market token and analyse convergence.

Pipeline:
    1. For each market in ``markets.parquet``, fetch prices-history for both
       outcome tokens at ``--interval``. Idempotent via per-token parquet.
    2. Build a price history view in DuckDB and compute, per market, the
       price of the eventual winner at a series of pre-resolution offsets.
    3. Aggregate convergence-error curves across markets and persist.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import logging
import sys

import polars as pl
from tqdm import tqdm

from intellifi import config
from intellifi.clob import fetch_and_store
from intellifi.convergence import aggregate_convergence, convergence_table
from intellifi.warehouse import open_warehouse


def _fetch_one(token_id: str, interval: str, overwrite: bool) -> tuple[str, int, str | None]:
    try:
        _, n = fetch_and_store(token_id, interval=interval, overwrite=overwrite)
        return token_id, n, None
    except Exception as exc:  # noqa: BLE001
        return token_id, 0, repr(exc)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval", default="1h",
                        choices=("1m", "1h", "6h", "1d", "max"))
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip CLOB fetch and just compute convergence")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")

    markets = open_warehouse(":memory:").sql("SELECT * FROM markets").pl()   # source-agnostic (parquet or archive)
    tokens = (markets
              .filter(pl.col("clob_token_ids").list.len() > 0)
              ["clob_token_ids"].list.explode().drop_nulls().unique().to_list())
    print(f"distinct tokens to consider: {len(tokens)}")

    if not args.no_fetch:
        print(f"fetching prices-history (interval={args.interval}, workers={args.workers})...")
        n_ok, n_err = 0, 0
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
            futures = {pool.submit(_fetch_one, t, args.interval, args.overwrite): t
                       for t in tokens}
            with tqdm(total=len(futures), unit="tok") as bar:
                for fut in concurrent.futures.as_completed(futures):
                    _, n, err = fut.result()
                    if err:
                        n_err += 1
                        tqdm.write(f"  ERROR: {err}")
                    else:
                        n_ok += 1
                    bar.update(1)
        print(f"  done: {n_ok} ok, {n_err} errors")

    print("\ncomputing convergence...")
    con = open_warehouse()
    table = convergence_table(con)
    OUT_DIR = config.PARQUET_DIR / "convergence"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    table.write_parquet(OUT_DIR / "per_market.parquet", compression="zstd")
    print(f"  per-market: {table.height} rows")

    summary = aggregate_convergence(table)
    summary.write_parquet(OUT_DIR / "aggregate.parquet", compression="zstd")
    print("\n=== convergence curve (median abs_error vs hours-before-end) ===")
    print(summary)

    return 0


if __name__ == "__main__":
    sys.exit(main())

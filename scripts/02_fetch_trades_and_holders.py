"""Stage 2: ingest trades + holders for every market in the markets parquet.

Usage:
    python scripts/02_fetch_trades_and_holders.py [--overwrite] [--workers N]
                                                  [--limit N] [--no-trades]
                                                  [--no-holders]

Writes:
    data/parquet/trades/condition_id=<cid>/part.parquet
    data/parquet/holders/condition_id=<cid>/part.parquet
    data/raw/data_api/trades/<cid>.jsonl
    data/raw/data_api/holders/<cid>.jsonl
"""
from __future__ import annotations

import argparse
import concurrent.futures
import logging
import sys
from datetime import UTC, datetime

import polars as pl
from tqdm import tqdm

from intellifi import config
from intellifi.data_api import (
    TRADES_MAX_REACHABLE,
    fetch_and_store_holders,
    fetch_and_store_trades,
)


def _ingest_one(condition_id: str, *, do_trades: bool, do_holders: bool,
                overwrite: bool, snapshot_ts) -> dict:
    out = {"condition_id": condition_id, "trades": 0, "holders": 0, "error": None}
    try:
        if do_trades:
            _, n = fetch_and_store_trades(condition_id, overwrite=overwrite)
            out["trades"] = n
        if do_holders:
            _, n = fetch_and_store_holders(condition_id, snapshot_ts_utc=snapshot_ts,
                                           overwrite=overwrite)
            out["holders"] = n
    except Exception as exc:  # noqa: BLE001
        out["error"] = repr(exc)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--overwrite", action="store_true",
                        help="re-fetch even if partition parquet exists")
    parser.add_argument("--workers", type=int, default=4,
                        help="parallel fetch workers (be polite to the API)")
    parser.add_argument("--limit", type=int, default=None,
                        help="cap number of markets processed (debug)")
    parser.add_argument("--no-trades", action="store_true")
    parser.add_argument("--no-holders", action="store_true")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")

    markets_path = config.MARKETS_PARQUET / "markets.parquet"
    if not markets_path.exists():
        print(f"missing {markets_path} — run scripts/01_fetch_resolved_markets.py --write first",
              file=sys.stderr)
        return 1

    df = pl.read_parquet(markets_path).filter(pl.col("condition_id").is_not_null())
    cids = df["condition_id"].to_list()
    if args.limit is not None:
        cids = cids[: args.limit]
    print(f"ingesting {len(cids)} markets "
          f"(trades={not args.no_trades}, holders={not args.no_holders}, "
          f"workers={args.workers}, overwrite={args.overwrite})")
    print(f"per-market trade cap: {TRADES_MAX_REACHABLE} (most-recent, API limitation)")

    snapshot_ts = datetime.now(tz=UTC)
    totals = {"trades": 0, "holders": 0, "errors": 0}

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as pool:
        futures = {
            pool.submit(_ingest_one, cid,
                        do_trades=not args.no_trades,
                        do_holders=not args.no_holders,
                        overwrite=args.overwrite,
                        snapshot_ts=snapshot_ts): cid
            for cid in cids
        }
        with tqdm(total=len(futures), unit="mkt") as bar:
            for fut in concurrent.futures.as_completed(futures):
                res = fut.result()
                if res["error"]:
                    totals["errors"] += 1
                    tqdm.write(f"  ERROR {res['condition_id'][:20]}: {res['error']}")
                totals["trades"] += res["trades"]
                totals["holders"] += res["holders"]
                bar.update(1)

    print(f"\ndone: {totals['trades']:,} trades, {totals['holders']:,} holders, "
          f"{totals['errors']} errors")
    return 0


if __name__ == "__main__":
    sys.exit(main())

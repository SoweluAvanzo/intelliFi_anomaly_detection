"""Stage II, Sample B: the pre-registered completeness gate (docs/stage2_preregistration.md §1).

Checks, for a block window of the v2 tape:
  (a) every 2,000-block chunk in the window is on disk;
  (b) for N random chunks, an independent re-fetch returns the identical (tx, logIndex) set;
  (c) for N random chunks, the number of taker-order records (taker = exchange) equals the
      number of OrdersMatched events fetched independently.
Exit code 0 only if all three pass. Writes the gate report to data/parquet/tape_v2_gate/<window>.json.

    python scripts/11_gate_v2_cohort.py --from-block 88080000 --to-block 88843826 --samples 20 --api-key-env ETHERSCAN_KEY
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

import polars as pl

from intellifi import config
from intellifi.fills import TAPE_V2_DIR, EXCHANGES_V2, fetch_v2_range
from intellifi.onchain import Polygonscan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-block", type=int, required=True)
    ap.add_argument("--to-block", type=int, required=True)
    ap.add_argument("--chunk-blocks", type=int, default=2000)
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--api-key-env", default=None)
    ap.add_argument("--min-interval", type=float, default=0.5)
    args = ap.parse_args()

    chunks = [(a, min(a + args.chunk_blocks - 1, args.to_block)) for a in range(args.from_block, args.to_block + 1, args.chunk_blocks)]
    missing = [(a, b) for a, b in chunks if not (TAPE_V2_DIR / f"blocks={a}-{b}" / "part.parquet").exists()]
    report = {"window": [args.from_block, args.to_block], "n_chunks": len(chunks), "missing": missing}
    print(f"(a) chunks present: {len(chunks) - len(missing)}/{len(chunks)}" + (f" — MISSING {missing[:5]}…" if missing else ""))
    if missing:
        _write(report, args); return 1

    key = os.getenv(args.api_key_env, "") if args.api_key_env else (config.ETHERSCAN_API_KEY or "")
    client = Polygonscan(api_key=key, min_interval_s=args.min_interval, max_calls=60_000, max_retries=12)
    rng = random.Random(args.seed)
    sample = rng.sample(chunks, min(args.samples, len(chunks)))
    exch = set(EXCHANGES_V2.values())
    b_ok, c_ok, details = 0, 0, []
    for a, b in sample:
        disk = pl.read_parquet(TAPE_V2_DIR / f"blocks={a}-{b}" / "part.parquet")
        fresh = fetch_v2_range(client, a, b, events=("OrderFilled", "OrdersMatched"))
        # Like-for-like: the tape is defined as the two v2 exchanges; third-party
        # emitters of the same signatures live in tape_v2_other/ (2026-08-31,
        # pre-registration deviations log entry 1).
        exch_only = pl.col("exchange").is_in(list(EXCHANGES_V2.keys()) + list(EXCHANGES_V2.values())) | pl.col("exchange").is_in(["v2_a", "v2_b"])
        disk, fresh = disk.filter(exch_only), fresh.filter(exch_only)
        k = ["tx_hash", "evt_index"]
        disk_keys = set(map(tuple, disk.filter(pl.col("event") == "OrderFilled").select(k).rows()))
        fresh_of = fresh.filter(pl.col("event") == "OrderFilled")
        fresh_keys = set(map(tuple, fresh_of.select(k).rows()))
        identical = disk_keys == fresh_keys
        n_taker = int(fresh_of["is_taker_order"].sum())
        n_matched = fresh.filter(pl.col("event") == "OrdersMatched").height
        b_ok += identical; c_ok += (n_taker == n_matched)
        details.append({"chunk": [a, b], "disk_rows": len(disk_keys), "refetch_rows": len(fresh_keys), "identical": identical,
                        "taker_orders": n_taker, "orders_matched": n_matched})
        print(f"  {a}-{b}: identical={identical} ({len(disk_keys)} vs {len(fresh_keys)}) | taker orders {n_taker} vs OrdersMatched {n_matched} | calls {client.calls_made}")
    report.update({"samples": details, "b_identical": b_ok, "c_conserved": c_ok, "calls": client.calls_made})
    ok = b_ok == len(sample) and c_ok == len(sample)
    print(f"(b) identical re-fetch: {b_ok}/{len(sample)}   (c) taker orders == OrdersMatched: {c_ok}/{len(sample)}   -> GATE {'PASSED' if ok else 'FAILED'}")
    report["passed"] = ok
    _write(report, args)
    return 0 if ok else 1


def _write(report, args) -> None:
    out = config.PARQUET_DIR / "tape_v2_gate"; out.mkdir(parents=True, exist_ok=True)
    (out / f"{args.from_block}-{args.to_block}.json").write_text(json.dumps(report, indent=1, default=str))


if __name__ == "__main__":
    sys.exit(main())

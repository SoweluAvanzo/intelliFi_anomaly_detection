"""Stage 10 (Stage II, Sample B): the complete Polymarket v2 on-chain tape.

Crawls both v2 exchanges for OrderFilled / OrdersMatched / FeeCharged from
the v2 genesis (2026-04-28) onward, in fixed block chunks, via Etherscan V2
getLogs with bisection (free tier). One parquet per chunk under
data/parquet/tape_v2/blocks=<from>-<to>/part.parquet, skip-if-exists, so the
crawl can be resumed and extended to the latest block at any time. Raw logs
are not kept separately: the parquet rows are lossless decodes.

    python scripts/10_fetch_v2_tape.py --chunk-blocks 20000 --max-calls 90000 -v
    python scripts/10_fetch_v2_tape.py --from-block 92800000 --to-block latest      # extend
"""
from __future__ import annotations

import argparse
import logging
import sys

from intellifi import config
from intellifi.fills import TAPE_V2_DIR, V2_GENESIS_BLOCK, fetch_v2_range, latest_block
from intellifi.onchain import Polygonscan


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-block", type=int, default=V2_GENESIS_BLOCK)
    ap.add_argument("--to-block", default="latest")
    ap.add_argument("--chunk-blocks", type=int, default=20_000, help="~12 h of Polygon blocks")
    ap.add_argument("--max-calls", type=int, default=90_000)
    ap.add_argument("--api-key-env", default=None,
                    help="name of the environment variable holding the Etherscan key to use "
                         "(default: the project key); lets crawlers run under a second free key")
    ap.add_argument("--min-interval", type=float, default=0.4,
                    help="seconds between calls in THIS process; the key allows 3 calls/s in total, "
                         "so N parallel crawlers need min-interval >= N/3 (e.g. 1.4 for four)")
    ap.add_argument("--events", nargs="+", default=["OrderFilled"], choices=["OrderFilled", "OrdersMatched", "FeeCharged"],
                    help="events to crawl (OrderFilled alone reproduces the tape; the others are optional)")
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args()
    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")
    import os
    # Guard 1: only vetted-valid keys. Dead keys poison the per-IP reputation on the
    # first request, so refuse by NAME before any HTTP (no startup validation call).
    key_env = args.api_key_env or "ETHERSCAN_KEY"
    if key_env not in config.CRAWL_KEYS:
        print(f"refusing to start: {key_env} is not on the vetted CRAWL_KEYS allowlist "
              f"{config.CRAWL_KEYS} — dead keys poison the IP. Override with INTELLIFI_CRAWL_KEYS.",
              file=sys.stderr)
        return 2
    # Guard 2: do not launch onto an IP still inside the invalid-key penalty cooldown.
    remaining = Polygonscan.penalty_active()
    if remaining > 0:
        print(f"refusing to start: IP under per-IP penalty cooldown, ~{remaining/60:.0f} min left; "
              f"let it go quiet (clear data/logs/.ip_penalty to force).", file=sys.stderr)
        return 3
    api_key = os.getenv(args.api_key_env, "") if args.api_key_env else (config.ETHERSCAN_API_KEY or "")
    client = Polygonscan(api_key=api_key, max_calls=args.max_calls,
                         min_interval_s=args.min_interval, max_retries=12)
    to_block = latest_block(client) if args.to_block == "latest" else int(args.to_block)
    TAPE_V2_DIR.mkdir(parents=True, exist_ok=True)
    start = args.from_block
    n_chunks = (to_block - start) // args.chunk_blocks + 1
    print(f"v2 tape: blocks {start} -> {to_block} in {n_chunks} chunks of {args.chunk_blocks}")
    for i, a in enumerate(range(start, to_block + 1, args.chunk_blocks)):
        b = min(a + args.chunk_blocks - 1, to_block)
        out = TAPE_V2_DIR / f"blocks={a}-{b}" / "part.parquet"
        # Size-aware skip-if-exists: a 0-byte file is a broken/interrupted write
        # (write_parquet of an empty df still emits a valid non-zero parquet), so it
        # must NOT count as "done" — otherwise it's a silent gap re-crawl never fills.
        if out.exists() and out.stat().st_size > 0:
            continue
        c0 = client.calls_made
        df = fetch_v2_range(client, a, b, events=tuple(args.events))
        out.parent.mkdir(parents=True, exist_ok=True)
        # Atomic write: temp file in the same dir then os.replace (atomic rename on one
        # filesystem). A killed process leaves the .tmp (or nothing), never a partial
        # or 0-byte part.parquet that skip-if-exists would lock in.
        tmp = out.parent / (out.name + ".tmp")
        df.write_parquet(tmp, compression="zstd")
        os.replace(tmp, out)
        ev = df.group_by("event").len().to_dict(as_series=False) if df.height else {}
        print(f"[{i + 1}/{n_chunks}] {a}-{b}: {df.height:,} rows {dict(zip(ev.get('event', []), ev.get('len', [])))} "
              f"in {client.calls_made - c0} calls (total {client.calls_made})")
    print("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())

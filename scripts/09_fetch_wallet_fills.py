"""Stage 9 (Phase 3): complete per-wallet order-fill histories from Etherscan.

For each universe wallet, every ``OrderFilled`` record on both Polymarket
exchanges in which the wallet is maker or taker — all markets, both legs,
counterparties, block timestamps — via Etherscan V2 ``getLogs`` (free tier:
5 calls/s, 100k/day; a wallet costs ~2 x fills / 1,000 calls). Raw logs are
written to data/raw/etherscan/fills/<wallet>.jsonl before decoding; output is
data/parquet/wallet_fills/<wallet>.parquet (skip-if-exists).

    python scripts/09_fetch_wallet_fills.py --validate --limit 3        # check against Dune fills first
    python scripts/09_fetch_wallet_fills.py                            # all universe wallets
"""
from __future__ import annotations

import argparse
import logging
import sys

import polars as pl

from intellifi import config
from intellifi.fills import (WALLET_FILLS_DIR, fetch_wallet_fills, register_fills_view, token_map,
                             validate_wallet_fills_against_dune)
from intellifi.onchain import Polygonscan
from intellifi.warehouse import open_warehouse


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--wallets", nargs="*", help="subset (default: universe.parquet)")
    ap.add_argument("--limit", type=int, default=None, help="first N wallets (after ordering)")
    ap.add_argument("--validate", action="store_true",
                    help="compare each wallet's fills with the Dune fills on covered markets")
    ap.add_argument("--overwrite", action="store_true")
    ap.add_argument("--max-calls", type=int, default=80_000)
    ap.add_argument("-v", "--verbose", action="count", default=0)
    args = ap.parse_args()
    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")

    con = open_warehouse(":memory:")
    markets = con.sql("SELECT * FROM markets").pl()
    tmap = token_map(markets)
    if args.wallets:
        wallets = [w.lower() for w in args.wallets]
    else:
        wallets = pl.read_parquet(config.PARQUET_DIR / "universe.parquet")["proxy_wallet"].str.to_lowercase().to_list()
    if args.validate:
        register_fills_view(con)
        seen = {r[0] for r in con.execute("SELECT maker FROM fills UNION SELECT taker FROM fills").fetchall()}
        wallets = [w for w in wallets if w in seen]
        print(f"{len(wallets)} wallets appear in the Dune-covered markets")
    if args.limit:
        wallets = wallets[: args.limit]
    client = Polygonscan(api_key=config.ETHERSCAN_API_KEY or "", max_calls=args.max_calls)
    results = []
    for i, w in enumerate(wallets):
        out = WALLET_FILLS_DIR / f"{w}.parquet"
        if out.exists() and not args.overwrite:
            df = pl.read_parquet(out); print(f"[{i + 1}/{len(wallets)}] {w[:12]}… cached ({df.height:,} fills)")
        else:
            c0 = client.calls_made
            df = fetch_wallet_fills(client, w, tmap)
            print(f"[{i + 1}/{len(wallets)}] {w[:12]}… {df.height:,} fills "
                  f"({int(df['is_taker_order'].sum()):,} own taker orders) in {client.calls_made - c0} calls")
        if args.validate:
            r = validate_wallet_fills_against_dune(con, w, df)
            ok = r["only_etherscan"] == 0 and r["only_dune"] == 0 and r["identical"] == r["matched"]
            print(f"      validate vs Dune: {'PASS' if ok else 'FAIL'}  {r}")
            results.append(r)
    print(f"\ncalls used: {client.calls_made}")
    if results:
        ok = all(r["only_etherscan"] == 0 and r["only_dune"] == 0 and r["identical"] == r["matched"] for r in results)
        print("VALIDATION", "PASSED" if ok else "FAILED")
        return 0 if ok else 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

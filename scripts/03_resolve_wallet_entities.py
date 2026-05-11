"""Stage 5: build the wallet-entity graph for the top-trader universe.

Pipeline:
    1. Pick universe = union(top-50 notional, top-50 PnL, top-50 calibration).
    2. Pull on-chain ERC-20 (USDC) + ERC-1155 (outcome share) transfers for
       each wallet from Polygonscan into ``data/parquet/onchain_transfers/``.
    3. Build an entity graph: direct transfer edges + common-neighbor edges.
    4. Run Louvain community detection.
    5. Report cluster summary + diff vs. naive "1 wallet = 1 entity".

Requires ``POLYGONSCAN_API_KEY`` (free at polygonscan.com/myapikey).
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

import polars as pl

from intellifi import config
from intellifi.onchain import Polygonscan
from intellifi.warehouse import open_warehouse
from intellifi.wallet_graph import (
    GraphConfig,
    build_entity_graph,
    community_summary,
    detect_communities,
    fetch_universe_transfers,
    select_universe,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--top-notional", type=int, default=50)
    parser.add_argument("--top-pnl", type=int, default=50)
    parser.add_argument("--top-skill", type=int, default=50)
    parser.add_argument("--min-skill-trades", type=int, default=20)
    parser.add_argument("--overwrite", action="store_true",
                        help="re-fetch transfers even if cached")
    parser.add_argument("--no-fetch", action="store_true",
                        help="skip Polygonscan fetch (use existing parquet)")
    parser.add_argument("--min-shared", type=int, default=2)
    parser.add_argument("--popular-threshold", type=int, default=5)
    parser.add_argument("--max-calls", type=int, default=80_000,
                        help="hard cap on Etherscan API calls (daily quota = 100k)")
    parser.add_argument("--max-pages-per-endpoint", type=int, default=10,
                        help="cap pagination depth per (wallet, endpoint): default 10 × 5000 = 50k rows")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")

    con = open_warehouse()
    universe = select_universe(
        con,
        top_n_notional=args.top_notional,
        top_n_pnl=args.top_pnl,
        top_n_skill=args.top_skill,
        min_skill_trades=args.min_skill_trades,
    )
    print(f"\n=== universe: {universe.height} wallets ===")
    print(f"  in top-{args.top_notional} notional: "
          f"{universe.filter(pl.col('rk_notional').is_not_null()).height}")
    print(f"  in top-{args.top_pnl} pnl:       "
          f"{universe.filter(pl.col('rk_pnl').is_not_null()).height}")
    print(f"  in top-{args.top_skill} skill:     "
          f"{universe.filter(pl.col('rk_skill').is_not_null()).height}")

    # Persist universe for downstream reuse
    config.PARQUET_DIR.mkdir(parents=True, exist_ok=True)
    universe_path = config.PARQUET_DIR / "universe.parquet"
    universe.write_parquet(universe_path, compression="zstd")
    print(f"  wrote {universe_path}")

    addresses = universe["proxy_wallet"].to_list()

    if not args.no_fetch:
        if not os.environ.get("POLYGONSCAN_API_KEY"):
            print("\nERROR: POLYGONSCAN_API_KEY env var not set.", file=sys.stderr)
            print("Register at https://polygonscan.com/myapikey (free) and "
                  "`export POLYGONSCAN_API_KEY=...` before re-running.",
                  file=sys.stderr)
            return 2
        client = Polygonscan.from_env()
        client.max_calls = args.max_calls
        print(f"\nfetching transfers for {len(addresses)} wallets "
              f"(throttle ~{1/client.min_interval_s:.1f} req/s, "
              f"max_pages={args.max_pages_per_endpoint}, max_calls={args.max_calls})...")
        summary = fetch_universe_transfers(
            addresses, client=client, overwrite=args.overwrite,
            max_pages=args.max_pages_per_endpoint,
        )
        n_total = sum(v["usdc_e"] + v["usdc_native"] + v["erc1155"]
                      for v in summary.values())
        print(f"  fetched {n_total:,} transfer rows across all wallets")
        print(f"  Etherscan API calls used in this run: {client.calls_made:,}")

    print(f"\nbuilding graph (min_shared={args.min_shared}, "
          f"popular_threshold={args.popular_threshold})...")
    cfg = GraphConfig(min_shared_neighbors=args.min_shared,
                      popular_neighbor_threshold=args.popular_threshold)
    res = build_entity_graph(addresses, cfg=cfg)
    g = res.graph
    print(f"  nodes: {g.number_of_nodes()}, edges: {g.number_of_edges()}")
    print(f"  direct (USDC+ERC1155 universe↔universe): {len(res.direct_edges)}")
    print(f"  common-neighbor edges:                   {len(res.common_edges)}")
    print(f"  popular external addresses suppressed:   {len(res.popular_addresses)}")

    partition = detect_communities(g)
    n_clusters = len(set(partition.values()))
    n_multi = sum(1 for c in set(partition.values())
                  if sum(1 for v in partition.values() if v == c) > 1)
    print(f"\nLouvain: {n_clusters} communities ({n_multi} multi-wallet)")

    summary = community_summary(universe, partition, g)
    print("\n=== top communities by total notional ===")
    head = summary.head(10).with_columns(
        pl.col("members").list.len().alias("size"),
        pl.col("total_notional").map_elements(lambda x: f"${x:,.0f}" if x else "$0",
                                              return_dtype=pl.Utf8).alias("notional"),
        pl.col("total_pnl").map_elements(lambda x: f"${x:,.0f}" if x is not None else "—",
                                         return_dtype=pl.Utf8).alias("pnl"),
    ).select(["community_id", "size", "n_direct_edges", "n_common_edges",
              "notional", "pnl"])
    print(head)

    print("\n=== multi-wallet clusters (≥2 members) — wallet detail ===")
    multi_wallet = summary.filter(pl.col("n_members") >= 2)
    for row in multi_wallet.iter_rows(named=True):
        print(f"\ncluster #{row['community_id']}  size={row['n_members']}  "
              f"direct={row['n_direct_edges']}  common={row['n_common_edges']}  "
              f"notional=${row['total_notional']:,.0f}  pnl=${row['total_pnl']:,.0f}")
        for w in row["members"]:
            wd = universe.filter(pl.col("proxy_wallet") == w).row(0, named=True)
            tn = f"${wd['total_notional']:,.0f}" if wd.get("total_notional") else "—"
            pn = f"${wd['realised_pnl']:,.0f}" if wd.get("realised_pnl") else "—"
            cg = f"{wd['calibration_gap']:+.3f}" if wd.get("calibration_gap") is not None else "—"
            print(f"    {w} | notional={tn} pnl={pn} cal_gap={cg}")

    # Persist
    out_dir = config.PARQUET_DIR / "wallet_graph"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary.write_parquet(out_dir / "communities.parquet", compression="zstd")
    with (out_dir / "partition.json").open("w") as fh:
        json.dump(partition, fh, indent=2)
    print(f"\nwrote {out_dir}/communities.parquet and partition.json")

    return 0


if __name__ == "__main__":
    sys.exit(main())

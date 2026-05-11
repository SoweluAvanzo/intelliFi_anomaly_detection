"""Stage 6: behavioral coordination analysis on the universe.

Three outputs written to ``data/parquet/coordination/``:

* ``cotrade_pairs.parquet``   — undirected co-trade counts per pair
* ``leader_lag.parquet``      — directed leader→follower lag statistics
* ``wash_round_trips.parquet`` — per-wallet BUY→SELL round-trip flags

Plus a behavioural-only entity graph built from the co-trade matrix and
clustered with Louvain, written to ``coordination/behavioural_graph.json``.
This is independent of the on-chain transfer graph and is meant to be
cross-checked against it (Stage 5 output).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter

import networkx as nx
import polars as pl

from intellifi import config
from intellifi.coordination import (
    cotrade_pairs,
    leader_lag_pairs,
    wash_round_trips,
)
from intellifi.warehouse import open_warehouse

OUT_DIR = config.PARQUET_DIR / "coordination"


def build_behavioural_graph(
    cotrade_df: pl.DataFrame,
    universe: list[str],
    *,
    min_events: int = 3,
) -> nx.Graph:
    g = nx.Graph()
    for w in universe:
        g.add_node(w.lower())
    for row in cotrade_df.iter_rows(named=True):
        if row["cotrade_events"] < min_events:
            continue
        # Weight emphasises cross-market events: pairs that co-trade in only
        # one market may share an external signal (sports book, news), not
        # be the same entity. Multi-market co-trading is the stronger signal.
        weight = float(row["cotrade_events"]) * (
            1.0 + 0.5 * (row["cotrade_markets"] - 1)
        )
        g.add_edge(
            row["a"], row["b"],
            weight=weight,
            cotrade_events=row["cotrade_events"],
            cotrade_markets=row["cotrade_markets"],
            combined_notional=row["combined_bucket_notional"],
        )
    return g


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--window-seconds", type=int, default=300,
                        help="bucket size for co-trade detection")
    parser.add_argument("--lag-max-seconds", type=int, default=600)
    parser.add_argument("--wash-window", type=int, default=600)
    parser.add_argument("--min-cotrade-events", type=int, default=3)
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    universe = pl.read_parquet(config.PARQUET_DIR / "universe.parquet")
    addresses = universe["proxy_wallet"].to_list()
    print(f"universe: {len(addresses)} wallets")

    con = open_warehouse()

    print(f"\n[1/3] co-trade pairs (window={args.window_seconds}s, min_events={args.min_cotrade_events})...")
    ct = cotrade_pairs(con, window_seconds=args.window_seconds,
                       universe=addresses, min_pair_events=args.min_cotrade_events).pl()
    ct.write_parquet(OUT_DIR / "cotrade_pairs.parquet", compression="zstd")
    print(f"  {ct.height} pairs written")

    print(f"\n[2/3] leader→follower (lag_max={args.lag_max_seconds}s)...")
    ll = leader_lag_pairs(con, lag_max_seconds=args.lag_max_seconds,
                          universe=addresses, min_events=5).pl()
    ll.write_parquet(OUT_DIR / "leader_lag.parquet", compression="zstd")
    print(f"  {ll.height} directed pairs written")

    print(f"\n[3/3] wash round-trips (window={args.wash_window}s)...")
    wt = wash_round_trips(con, window_seconds=args.wash_window,
                          universe=addresses).pl()
    wt.write_parquet(OUT_DIR / "wash_round_trips.parquet", compression="zstd")
    print(f"  {wt.height} wallets with round-trip activity")

    # Behavioural graph + Louvain
    print("\n[graph] building co-trade Louvain partition...")
    g = build_behavioural_graph(ct, addresses, min_events=args.min_cotrade_events)
    print(f"  nodes={g.number_of_nodes()}  edges={g.number_of_edges()}")
    import community as community_louvain  # type: ignore
    if g.number_of_edges() == 0:
        partition = {n: i for i, n in enumerate(g.nodes)}
    else:
        partition = community_louvain.best_partition(
            g, weight="weight", resolution=1.0, random_state=42
        )
    sizes = Counter(Counter(partition.values()).values())
    n_multi = sum(1 for c, n in Counter(partition.values()).items() if n >= 2)
    print(f"  communities: {len(set(partition.values()))} ({n_multi} multi-wallet)")
    print(f"  size distribution: {dict(sorted(sizes.items()))}")

    with (OUT_DIR / "behavioural_partition.json").open("w") as fh:
        json.dump(partition, fh, indent=2)

    # Cross-check with on-chain strong-evidence entities
    onchain_partition_path = config.PARQUET_DIR / "wallet_graph" / "partition.json"
    if onchain_partition_path.exists():
        from intellifi.wallet_graph import GraphConfig, build_entity_graph
        res = build_entity_graph(addresses, cfg=GraphConfig())
        g_strong = nx.Graph()
        for a in [w.lower() for w in addresses]:
            g_strong.add_node(a)
        for a, b, m in res.direct_edges:
            if m.get("erc1155_count", 0) >= 5 or m.get("usdc_total", 0) >= 10_000:
                g_strong.add_edge(a, b)
        comps = sorted(
            [c for c in nx.connected_components(g_strong) if len(c) >= 2],
            key=len, reverse=True
        )
        print(f"\n[cross-check] strong-evidence on-chain entities: {len(comps)}")
        for i, comp in enumerate(comps):
            comm_ids = {partition[w] for w in comp if w in partition}
            print(f"  on-chain entity #{i} ({len(comp)} wallets) "
                  f"→ {len(comm_ids)} co-trade community(ies): {sorted(comm_ids)}")

    return 0


if __name__ == "__main__":
    sys.exit(main())

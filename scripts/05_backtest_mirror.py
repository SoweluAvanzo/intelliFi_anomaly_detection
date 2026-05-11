"""Stage 7: mirror-strategy backtest comparing leader sets.

Defines four leader sets and runs the mirror strategy for each:

1. on-chain entity #0 — strong-evidence cluster from Stage 5
2. behavioural community #65 — skill cluster from Stage 6
3. top-50 by Bayesian calibration gap (independent of clustering)
4. random universe sample (baseline)

Writes results to ``data/parquet/backtest/`` and prints the summary table.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys

import networkx as nx
import pandas as pd
import polars as pl

from intellifi import config
from intellifi.backtest import BacktestConfig, backtest_mirror, summarise_backtest
from intellifi.wallet_graph import GraphConfig, build_entity_graph
from intellifi.warehouse import open_warehouse

OUT_DIR = config.PARQUET_DIR / "backtest"


def _onchain_entity0(addresses: list[str]) -> list[str]:
    res = build_entity_graph(addresses, cfg=GraphConfig())
    g_strong = nx.Graph()
    for w in [a.lower() for a in addresses]:
        g_strong.add_node(w)
    for a, b, m in res.direct_edges:
        if m.get("erc1155_count", 0) >= 5 or m.get("usdc_total", 0) >= 10_000:
            g_strong.add_edge(a, b)
    return sorted(max([c for c in nx.connected_components(g_strong) if len(c) >= 2],
                      key=len))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latency-seconds", type=int, default=60)
    parser.add_argument("--horizons", type=int, nargs="+",
                        default=[300, 1800, 3600, 86400],
                        help="exit horizons in seconds")
    parser.add_argument("--fee-bps", type=float, default=20.0,
                        help="round-trip fee in basis points")
    parser.add_argument("--min-signal-notional", type=float, default=1000.0)
    parser.add_argument("--no-resolution-exit", action="store_true",
                        help="do not exit at market resolution (removes hindsight bias)")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    con = open_warehouse()
    universe = pl.read_parquet(config.PARQUET_DIR / "universe.parquet")
    addresses = universe["proxy_wallet"].to_list()

    entity0 = _onchain_entity0(addresses)
    beh = json.loads((config.PARQUET_DIR / "coordination" / "behavioural_partition.json")
                     .read_text())
    beh_65 = sorted([w for w, c in beh.items() if c == 65])

    top_skill = (universe.filter(pl.col("rk_skill").is_not_null())
                          .sort("rk_skill")["proxy_wallet"].to_list())

    random.seed(42)
    random_sample = random.sample(addresses, 50)

    cfg = BacktestConfig(
        latency_seconds=args.latency_seconds,
        horizons=tuple(args.horizons),
        fee_bps=args.fee_bps,
        min_signal_notional=args.min_signal_notional,
        exit_at_resolution=not args.no_resolution_exit,
    )

    leader_sets = [
        ("onchain_entity0",   entity0),
        ("behavioural_65",    beh_65),
        ("top_skill_50",      top_skill),
        ("random_sample_50",  random_sample),
    ]

    all_summaries = []
    for name, leaders in leader_sets:
        print(f"\n=== {name} (n_leaders={len(leaders)}) ===")
        df = backtest_mirror(con, leaders=leaders, cfg=cfg)
        if df.empty:
            print("  no events")
            continue
        df.to_parquet(OUT_DIR / f"{name}_events.parquet", compression="zstd")
        s = summarise_backtest(df, by=["horizon_seconds"])
        s.insert(0, "leader_set", name)
        all_summaries.append(s)
        print(s.to_string(index=False))

    combined = pd.concat(all_summaries, ignore_index=True) if all_summaries else pd.DataFrame()
    combined.to_parquet(OUT_DIR / "summary.parquet", compression="zstd")
    print(f"\nwrote summary to {OUT_DIR}/summary.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Stage 7: mirror-strategy backtest comparing leader sets against matched controls.

Leader sets (redesigned after the 2026-08-29 audit):

1. ``onchain_entity0``   — largest component of the USDC direct-transfer graph
                           among universe wallets (structural; ERC-1155 fills
                           are no longer edges).
2. ``behavioural_twin``  — cotrade community maximally overlapping entity0
                           (largest multi-wallet community if none overlaps).
3. ``top_notional_50``   — top-50 by traded notional (outcome-independent).
4. ``top_skill_insample``— top-50 by position-level posterior calibration gap
                           over ALL markets. In-sample by construction; kept
                           only to show what the pre-audit ranking implied.
5. ``top_skill_train``   — position skill ranked on the earlier half of the
                           corpus (by ``closed_time``) and evaluated on the
                           later half: the out-of-sample version of 4.
6. ``random_nonuniverse``— 200 seeded wallets outside the universe with at
                           least one signal-sized trade (unmatched baseline).

Every set is evaluated against a **matched placebo control**: for each
leader event, up to three trades by non-universe wallets on the same asset
and side within ±15 min and ±0.05 in price, mirrored with the same engine.
Leader trades after the market's ``event_ts`` (outcome already priced in)
are excluded. Writes ``<set>_events.parquet``, ``<set>_control_events.parquet``
and ``summary.parquet`` to ``data/parquet/backtest/``.
"""
from __future__ import annotations

import argparse
import json
import logging
import random
import sys
from collections import Counter

import networkx as nx
import pandas as pd
import polars as pl

from intellifi import config
from intellifi.backtest import (BacktestConfig, leader_events, matched_control_events,
                                run_events, summarise_backtest)
from intellifi.skill import PositionSkillConfig, build_bets_view, position_skill
from intellifi.wallet_graph import GraphConfig, build_entity_graph
from intellifi.warehouse import open_warehouse

OUT_DIR = config.PARQUET_DIR / "backtest"


def _onchain_entity0(addresses: list[str], min_usdc_total: float) -> list[str]:
    res = build_entity_graph(addresses, cfg=GraphConfig())
    g_strong = nx.Graph()
    for w in [a.lower() for a in addresses]:
        g_strong.add_node(w)
    for a, b, m in res.direct_edges:
        if m.get("usdc_total", 0) >= min_usdc_total:
            g_strong.add_edge(a, b)
    comps = [c for c in nx.connected_components(g_strong) if len(c) >= 2]
    return sorted(max(comps, key=lambda c: (len(c), sorted(c)))) if comps else []


def _behavioural_twin(entity0: list[str]) -> list[str]:
    beh = json.loads((config.PARQUET_DIR / "coordination" / "behavioural_partition.json").read_text())
    overlap = Counter(beh[w] for w in entity0 if w in beh)
    multi = {c: n for c, n in Counter(beh.values()).items() if n >= 2}
    if overlap and overlap.most_common(1)[0][1] >= 2:
        twin_c = overlap.most_common(1)[0][0]
    elif multi:
        twin_c = max(multi, key=lambda c: (multi[c], -c))
    else:
        return []
    return sorted(w for w, c in beh.items() if c == twin_c)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--latency-seconds", type=int, default=60)
    parser.add_argument("--horizons", type=int, nargs="+", default=[300, 1800, 3600, 86400])
    parser.add_argument("--fee-bps", type=float, default=20.0,
                        help="ONE-WAY fee in price units per share (charged on entry and exit)")
    parser.add_argument("--min-signal-notional", type=float, default=1000.0)
    parser.add_argument("--entity-min-usdc", type=float, default=1000.0,
                        help="min total USDC transferred between two wallets for a strong edge")
    parser.add_argument("--no-resolution-exit", action="store_true")
    parser.add_argument("--include-post-convergence", action="store_true",
                        help="keep leader trades placed after the outcome was priced in")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()
    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for stale in OUT_DIR.glob("*_events.parquet"):
        stale.unlink()

    con = open_warehouse()
    build_bets_view(con)
    universe = pl.read_parquet(config.PARQUET_DIR / "universe.parquet")
    addresses = [a.lower() for a in universe["proxy_wallet"].to_list()]

    markets = con.sql("SELECT condition_id, COALESCE(closed_time, end_date) AS ct FROM markets").pl()
    split_ts = markets["ct"].median()
    train = markets.filter(pl.col("ct") < split_ts)["condition_id"].to_list()
    test = markets.filter(pl.col("ct") >= split_ts)["condition_id"].to_list()
    print(f"temporal split at {split_ts}: train {len(train)} markets, test {len(test)} markets")

    entity0 = _onchain_entity0(addresses, args.entity_min_usdc)
    twin = _behavioural_twin(entity0)
    top_notional = (universe.filter(pl.col("rk_notional").is_not_null())
                            .sort("rk_notional")["proxy_wallet"].str.to_lowercase().to_list())
    ps_cfg = PositionSkillConfig()
    ps_all = position_skill(con, cfg=ps_cfg)
    def _top(ps):
        return ([] if ps.is_empty() or "p_gap_positive" not in ps.columns
                else ps.sort(["p_gap_positive", "calibration_gap"], descending=True).head(50)["proxy_wallet"].to_list())
    top_skill_insample = _top(ps_all)
    ps_train = position_skill(con, cfg=PositionSkillConfig(min_positions=3, min_markets=2), condition_ids=train)
    top_skill_train = _top(ps_train)
    non_universe = con.sql(f"""
        SELECT DISTINCT proxy_wallet FROM trades
        WHERE notional_usdc >= {args.min_signal_notional} AND price BETWEEN 0.02 AND 0.98
          AND proxy_wallet NOT IN ({",".join(f"'{a}'" for a in addresses)})
        ORDER BY proxy_wallet""").pl()["proxy_wallet"].to_list()
    random.seed(42)
    random_nonuniverse = sorted(random.sample(non_universe, min(200, len(non_universe))))

    print(f"entity0={len(entity0)}  twin={len(twin)}  top_notional={len(top_notional)}  "
          f"skill_insample={len(top_skill_insample)}  skill_train={len(top_skill_train)}  "
          f"random_nonuniverse={len(random_nonuniverse)} (pool {len(non_universe)})")

    cfg = BacktestConfig(
        latency_seconds=args.latency_seconds, horizons=tuple(args.horizons),
        fee_bps=args.fee_bps, min_signal_notional=args.min_signal_notional,
        exit_at_resolution=not args.no_resolution_exit,
        exclude_post_convergence=not args.include_post_convergence,
    )
    leader_sets = [  # (name, wallets, evaluation markets or None for all)
        ("onchain_entity0", entity0, None),
        ("behavioural_twin", twin, None),
        ("top_notional_50", top_notional, None),
        ("top_skill_insample", top_skill_insample, None),
        ("top_skill_train", top_skill_train, test),
        ("random_nonuniverse", random_nonuniverse, None),
    ]
    meta = {"split_closed_time": str(split_ts), "train_markets": len(train), "test_markets": len(test),
            "leader_sets": {n: w for n, w, _ in leader_sets}}
    (OUT_DIR / "leader_sets.json").write_text(json.dumps(meta, indent=2))

    summaries = []
    for name, leaders, scope in leader_sets:
        print(f"\n=== {name} (n_leaders={len(leaders)}, scope={'test' if scope else 'all'}) ===")
        if not leaders:
            print("  empty leader set"); continue
        ev = leader_events(con, leaders=leaders, min_notional=cfg.min_signal_notional,
                           condition_ids=scope, exclude_post_convergence=cfg.exclude_post_convergence).df()
        df = run_events(con, ev, cfg=cfg)
        if df.empty:
            print("  no events"); continue
        df.to_parquet(OUT_DIR / f"{name}_events.parquet", compression="zstd")
        s = summarise_backtest(df, by=["horizon_seconds"])
        s.insert(0, "is_control", False); s.insert(0, "eval_scope", "test" if scope else "all"); s.insert(0, "leader_set", name)
        summaries.append(s)
        ctrl_ev = matched_control_events(con, ev, exclude_wallets=addresses + leaders,
                                         min_notional=cfg.min_signal_notional)
        dfc = run_events(con, ctrl_ev, cfg=cfg)
        if not dfc.empty:
            dfc.to_parquet(OUT_DIR / f"{name}_control_events.parquet", compression="zstd")
            sc = summarise_backtest(dfc, by=["horizon_seconds"])
            sc.insert(0, "is_control", True); sc.insert(0, "eval_scope", "test" if scope else "all"); sc.insert(0, "leader_set", name)
            summaries.append(sc)
        show = pd.concat([s, sc] if not dfc.empty else [s])
        print(show[["is_control", "horizon_seconds", "n_events", "n_markets", "hit_rate",
                    "mean_net", "mean_net_by_market", "se_net_by_market"]].to_string(index=False))

    combined = pd.concat(summaries, ignore_index=True) if summaries else pd.DataFrame()
    combined.to_parquet(OUT_DIR / "summary.parquet", compression="zstd")
    print(f"\nwrote summary to {OUT_DIR}/summary.parquet")
    return 0


if __name__ == "__main__":
    sys.exit(main())

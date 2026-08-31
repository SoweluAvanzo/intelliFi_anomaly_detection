"""CSV export of the parquet store for external collaborators.

Every parquet dataset under ``config.PARQUET_DIR`` is flattened to one CSV
file (partitioned datasets are concatenated, with the partition key kept as a
column). In addition, the analysis tables that the notebooks compute on the
fly from the DuckDB views — concentration (Gini/HHI), the ``bets`` table, the
Beta-posterior wallet-skill table, the reliability curve and the winning
outcomes — are materialised with the same parameters the notebooks use, so
the export is a complete record of every figure the pipeline reports.

Conventions applied at export time:

* timestamps are written as ISO-8601 UTC (``YYYY-MM-DDTHH:MM:SS.ffffffZ``);
* list-typed columns (``outcomes``, ``clob_token_ids``, ``members`` ...) are
  serialised as JSON strings so they survive a CSV round-trip;
* the two Louvain partition JSON files are flattened to two-column CSVs.

The on-chain transfer tables (~5M rows) are exported separately from the
core tables so the small analysis outputs can be shared without them.
"""
from __future__ import annotations

import json
import logging
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import duckdb
import numpy as np
import polars as pl

from intellifi import config
from intellifi.concentration import concentration_table, wallet_universe
from intellifi.skill import (SkillConfig, build_bets_view, calibration_by_bin, position_skill,
                             wallet_pnl, wallet_skill)
from intellifi.warehouse import open_warehouse

log = logging.getLogger(__name__)

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"

# Parameters the notebooks use for the on-the-fly analysis tables. Keep in
# sync with notebooks/vertical_slice.ipynb and notebooks/wallet_graph.ipynb.
SKILL_CFG = SkillConfig(min_trades=20, prior_strength=4.0, size_weighted=True)
RELIABILITY_BINS = 20
PLATFORM_TOPN = (10, 100, 1000)

# Files copied verbatim into the export root (source path relative to repo).
SUPPORT_FILES: tuple[tuple[str, str], ...] = (
    ("requirements-lock.txt", "requirements-lock.txt"),
    ("examples/verify_export.py", "verify_export.py"),
)


@dataclass(frozen=True)
class ExportTable:
    name: str                       # output stem, may contain a sub-folder
    glob: str                       # relative to PARQUET_DIR
    description: str
    hive: bool = False              # dataset partitioned as key=value dirs
    json_cols: tuple[str, ...] = ()  # list columns to serialise as JSON
    columns: dict[str, str] = field(default_factory=dict)  # data dictionary


CORE_TABLES: tuple[ExportTable, ...] = (
    ExportTable(
        "markets", "markets/markets.parquet",
        "One row per resolved market (Gamma API). Positional arrays: "
        "outcomes[i] <-> clob_token_ids[i] <-> outcome_prices_final[i].",
        json_cols=("outcomes", "clob_token_ids", "outcome_prices_final"),
        columns={
            "condition_id": "Key for trades/holders (Data API).",
            "clob_token_ids": "JSON list; per-outcome token id, key for prices_history.",
            "outcome_prices_final": "JSON list; final price per outcome (1.0 = winner).",
            "event_id / event_neg_risk": "Event linkage; neg-risk families must be analysed jointly.",
            "uma_resolution_statuses": "UMA oracle resolution state.",
            "volume, liquidity": "Lifetime USDC notional / liquidity as reported by Gamma.",
            "start_date, end_date": "Market open/close, UTC.",
        },
    ),
    ExportTable(
        "neg_risk_families", "neg_risk_families/families.parquet",
        "Membership of neg-risk (multi-outcome) event families.",
    ),
    ExportTable(
        "trades", "trades/*/part.parquet",
        "Executed trades (Data API /trades), all markets concatenated. "
        "Capped at the ~4000 most recent trades per market by the upstream API: "
        "high-volume markets are tail-sampled in their early life.",
        hive=True,
        columns={
            "condition_id": "Market key.",
            "asset_id": "Outcome token traded (matches markets.clob_token_ids). Read as a string.",
            "outcome, outcome_index": "Outcome label and its positional index.",
            "proxy_wallet": "Trader's Polymarket proxy wallet (Polygon address).",
            "side": "BUY / SELL from the taker's perspective.",
            "price": "Execution price in [0,1] = implied probability.",
            "size": "Number of outcome shares.",
            "notional_usdc": "price * size.",
            "ts_utc": "Execution time, UTC.",
            "tx_hash": "Polygon settlement transaction.",
        },
    ),
    ExportTable(
        "holders", "holders/*/part.parquet",
        "Holder snapshot per outcome token at fetch time (Data API /holders).",
        hive=True,
        columns={"amount": "Outcome shares held at snapshot_ts_utc."},
    ),
    ExportTable(
        "prices_history", "prices_history/*.parquet",
        "CLOB /prices-history per outcome token (hourly). Sparse: Polymarket "
        "prunes the endpoint after resolution, so many tokens have short series.",
        columns={"token_id": "Outcome token id. Read as a string.", "price": "Mid price in [0,1]."},
    ),
    ExportTable(
        "universe", "universe.parquet",
        "The 134-wallet analysis universe = union of the top-50 wallets by traded "
        "notional, by realised PnL and by raw calibration gap (>= 20 resolved bets).",
        columns={
            "total_notional, n_trades, n_markets": "Activity in the corpus.",
            "realised_pnl": "Notional-equivalent PnL on resolved positions (see skill.wallet_pnl).",
            "n_bets, realised_hit_rate": "Resolved bets and size-weighted fraction won (NULL if < 20 bets).",
            "mean_implied_p": "Size-weighted mean entry price = probability the wallet paid for.",
            "calibration_gap": "RAW size-weighted gap: realised_hit_rate - mean_implied_p (no prior). "
                               "Headline statistic is skill/position_skill.csv.",
            "rk_notional, rk_pnl, rk_skill": "Rank within each top-50 list (NULL if not in that list).",
        },
    ),
    ExportTable(
        "wallet_communities", "wallet_graph/communities.parquet",
        "Louvain communities over the combined on-chain + cotrade graph. "
        "community_id is NOT stable across reruns; identify clusters by membership.",
        json_cols=("members",),
    ),
    ExportTable(
        "coordination/cotrade_pairs", "coordination/cotrade_pairs.parquet",
        "Universe wallet pairs trading the same (asset, side) within the same "
        "300-second bucket, >= 3 events.",
    ),
    ExportTable(
        "coordination/leader_lag", "coordination/leader_lag.parquet",
        "Directed universe pairs where the follower's next same-side trade on the "
        "asset comes within 600 s of the leader's, >= 5 events. Median lags of a "
        "few seconds are consistent with copy-trading.",
    ),
    ExportTable(
        "coordination/wash_round_trips", "coordination/wash_round_trips.parquet",
        "Universe wallets with BUY->SELL cycles on one asset within 600 s and >= 50% "
        "size overlap (wash-trading signal).",
    ),
    ExportTable(
        "backtest/summary", "backtest/summary.parquet",
        "Mirror-strategy backtest: per leader set x horizon, leader rows and their "
        "matched placebo controls (is_control). n_markets / se_net_by_market are "
        "the cluster-robust statistics; events within a market are not independent.",
    ),
    ExportTable(
        "convergence/per_market", "convergence/per_market.parquet",
        "Winner-price absolute error at fixed offsets before market close, per market.",
    ),
    ExportTable(
        "convergence/aggregate", "convergence/aggregate.parquet",
        "Cross-market distribution of the convergence error per offset.",
    ),
)

ONCHAIN_TABLES: tuple[ExportTable, ...] = (
    ExportTable(
        "onchain/erc1155_transfers", "onchain_transfers/erc1155/*.parquet",
        "ERC-1155 outcome-token transfers touching each universe wallet "
        "(Etherscan V2). `owner` is the universe wallet the row was fetched for; "
        "a transfer between two universe wallets appears once per owner.",
    ),
    ExportTable(
        "onchain/usdc_e_transfers", "onchain_transfers/usdc_e/*.parquet",
        "Bridged USDC.e transfers touching each universe wallet.",
    ),
    ExportTable(
        "onchain/usdc_native_transfers", "onchain_transfers/usdc_native/*.parquet",
        "Native USDC transfers touching each universe wallet.",
    ),
)

PARTITION_JSON: tuple[tuple[str, str, str], ...] = (
    ("wallet_partition", "wallet_graph/partition.json",
     "wallet -> Louvain community_id on the on-chain entity graph."),
    ("coordination/behavioural_partition", "coordination/behavioural_partition.json",
     "wallet -> Louvain community_id on the cotrade (behavioural) graph."),
)

# Analysis tables recomputed from the warehouse views at export time.
BACKTEST_EVENTS_DESCRIPTION = (
    "Per-event mirror backtest rows for one leader set (or its matched placebo "
    "control, *_control_events). See backtest/summary and leader_sets.json.")

DERIVED_DESCRIPTIONS: dict[str, tuple[str, dict[str, str]]] = {
    "skill/position_skill": (
        "HEADLINE skill table. One Bernoulli trial per (wallet, market) = the wallet's net "
        "in-sample direction; positions priced outside [0.05, 0.95] dropped; >= 5 positions "
        "in >= 3 markets. Beta prior strength 4 centred on the wallet's mean implied p; exact "
        "Beta 5/95% quantiles; p_gap_positive = P(hit rate > paid-for rate).",
        {"excess_over_reliability_curve": "mean(won - leave-one-out corpus hit rate in the same implied-p decile): edge beyond the corpus favourite-longshot bias.",
         "calibration_gap": "posterior_mean_hit_rate - mean_implied_p at position level."}),
    "skill/wallet_pnl": (
        "Per-wallet PnL. realised_pnl_usdc marks every fill to resolution; "
        "realised_pnl_covered_usdc scales SELL legs by min(1, bought/sold) per position so "
        "sells with no in-sample cost basis (63% of sold shares) do not count as shorts "
        "held to resolution. Rank on the covered figure.", {}),
    "concentration/market_net_flow": (
        "Per-market concentration of |net signed notional| per wallet (directional footprint; "
        "nets out two-sided liquidity provision).", {}),
    "concentration/family_net_flow": (
        "Net-flow concentration consolidated across neg-risk families.", {}),
    "winning_outcomes": (
        "Resolved winner per market: index of the outcome whose final price is "
        "closest to 1.0 (must be >= 0.5). Ground truth for every bet.", {}),
    "skill/bets": (
        "One directional bet per trade in a resolved market: BUY of X at p bets "
        "X wins at implied_p = p; SELL bets X loses at implied_p = 1 - p. "
        "won = 1 if the bet paid out. Input to all skill statistics.",
        {"implied_p": "Probability the bet wins, as priced at entry.",
         "won": "1 if the bet resolved in the wallet's favour."}),
    "skill/wallet_skill": (
        "Beta-posterior skill per wallet with >= 20 resolved bets, size-weighted "
        "(SkillConfig(min_trades=20, prior_strength=4)). Prior centred on the "
        "wallet's own mean_implied_p; posterior_alpha = prior_alpha + won shares.",
        {"prior_alpha, prior_beta": "mean_implied_p * 4 and (1 - mean_implied_p) * 4.",
         "posterior_alpha, posterior_beta": "prior + size-weighted wins / losses.",
         "posterior_mean_hit_rate": "posterior_alpha / (posterior_alpha + posterior_beta).",
         "calibration_gap": "POSTERIOR gap: posterior_mean_hit_rate - mean_implied_p. "
                            "Differs from the raw gap in universe.csv by the prior shrinkage.",
         "ci_low, ci_high": "posterior mean +/- 1.645 * posterior sd, clipped to [0,1]."}),
    "skill/reliability_size_weighted": (
        "Reliability curve, 20 implied-probability bins, each bet weighted by share size.", {}),
    "skill/reliability_count_weighted": (
        "Reliability curve, 20 implied-probability bins, each trade counted once.", {}),
    "concentration/market_trade_notional": (
        "Per-market wallet concentration of traded notional: n_wallets, Gini, HHI, top-N shares.",
        {"gini": "Sorted-share Gini: 2*sum(i*w_i)/(n*sum(w)) - (n+1)/n, wallets sorted ascending.",
         "hhi": "sum over wallets of (share of total weight)^2.",
         "topK_share": "Fraction of total weight held by the K largest wallets."}),
    "concentration/market_holdings_amount": (
        "Per-market concentration of outcome-share holdings at resolution (holders snapshot).", {}),
    "concentration/family_trade_notional": (
        "Same as market_trade_notional but consolidated across neg-risk families "
        "(group_key = family event id, or 'M:<condition_id>' for standalone markets).", {}),
    "concentration/family_holdings_amount": (
        "Holdings concentration consolidated across neg-risk families.", {}),
    "concentration/platform": (
        "Platform-wide concentration: Gini and top-10/100/1000 shares over every "
        "wallet's total traded notional (and total holdings) across all 100 markets.", {}),
    "concentration/wallet_universe_trade_notional": (
        "Every wallet's total traded notional across the corpus (input to platform Gini).", {}),
    "concentration/wallet_universe_holdings_amount": (
        "Every wallet's total outcome-share holdings across the corpus.", {}),
}


def _source(table: ExportTable) -> str:
    path = (config.PARQUET_DIR / table.glob).as_posix()
    hive = ", hive_partitioning=true" if table.hive else ""
    return f"read_parquet('{path}'{hive})"


def _copy_sql(con: duckdb.DuckDBPyConnection, select_sql: str, out: Path) -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    sql = (f"COPY ({select_sql}) TO '{out.as_posix()}' "
           f"(FORMAT CSV, HEADER, TIMESTAMPFORMAT '{TIMESTAMP_FORMAT}')")
    return con.execute(sql).fetchone()[0]


def _entry(name: str, path: Path, out_dir: Path, n: int, description: str,
           columns: dict[str, str], group: str) -> dict:
    return {"table": name, "file": path.relative_to(out_dir).as_posix(),
            "rows": n, "bytes": path.stat().st_size, "description": description,
            "columns": columns, "group": group}


def export_table(con: duckdb.DuckDBPyConnection, table: ExportTable,
                 out_dir: Path) -> tuple[Path, int]:
    out = out_dir / f"{table.name}.csv"
    replace = ""
    if table.json_cols:
        replace = " REPLACE (" + ", ".join(
            f"to_json({c}) AS {c}" for c in table.json_cols) + ")"
    n = _copy_sql(con, f"SELECT *{replace} FROM {_source(table)}", out)
    log.info("%-45s %10d rows -> %s", table.name, n, out)
    return out, n


def export_partition_json(name: str, rel: str, out_dir: Path) -> tuple[Path, int]:
    src = config.PARQUET_DIR / rel
    out = out_dir / f"{name}.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    mapping = json.loads(src.read_text())
    with out.open("w") as fh:
        fh.write("proxy_wallet,community_id\n")
        for wallet, cid in sorted(mapping.items(), key=lambda kv: (kv[1], kv[0])):
            fh.write(f"{wallet},{cid}\n")
    return out, len(mapping)


def _gini_np(w: np.ndarray) -> float:
    """Equal-step Lorenz Gini over positive weights (as in vertical_slice.ipynb)."""
    w = np.sort(np.asarray(w, dtype=float))
    w = w[w > 0]
    n = w.size
    if n < 2:
        return float("nan")
    return float((2 * (np.arange(1, n + 1) * w).sum()) / (n * w.sum()) - (n + 1) / n)


def export_derived(out_dir: Path) -> list[dict]:
    """Materialise the notebook-only analysis tables from the warehouse views."""
    con = open_warehouse(":memory:")
    con.execute("SET TimeZone='UTC'")
    build_bets_view(con)
    manifest: list[dict] = []

    def emit(name: str, rel: duckdb.DuckDBPyRelation) -> None:
        out = out_dir / f"{name}.csv"
        n = _copy_sql(con, rel.sql_query(), out)
        desc, cols = DERIVED_DESCRIPTIONS[name]
        manifest.append(_entry(name, out, out_dir, n, desc, cols, "core"))
        log.info("%-45s %10d rows -> %s", name, n, out)

    emit("winning_outcomes", con.sql("SELECT * FROM winning_outcomes"))
    emit("skill/bets", con.sql("SELECT * FROM bets"))
    emit("skill/wallet_skill", wallet_skill(con, cfg=SKILL_CFG))
    for name, frame in (("skill/position_skill", position_skill(con)),
                        ("skill/wallet_pnl", wallet_pnl(con).pl())):
        out = out_dir / f"{name}.csv"; out.parent.mkdir(parents=True, exist_ok=True)
        frame.write_csv(out)
        desc, cols = DERIVED_DESCRIPTIONS[name]
        manifest.append(_entry(name, out, out_dir, frame.height, desc, cols, "core"))
        log.info("%-45s %10d rows -> %s", name, frame.height, out)
    emit("skill/reliability_size_weighted",
         calibration_by_bin(con, n_bins=RELIABILITY_BINS, weight="size"))
    emit("skill/reliability_count_weighted",
         calibration_by_bin(con, n_bins=RELIABILITY_BINS, weight="count"))
    for weight in ("trade_notional", "net_flow", "holdings_amount"):
        for group in ("market", "family"):
            emit(f"concentration/{group}_{weight}",
                 concentration_table(con, weight=weight, group=group))
        if weight != "net_flow":
            emit(f"concentration/wallet_universe_{weight}", wallet_universe(con, weight=weight))

    # Platform-wide Gini + top-N shares, exactly as the notebook computes them.
    rows = []
    for weight, col in (("trade_notional", "total_notional"), ("holdings_amount", "total_amount")):
        df = wallet_universe(con, weight=weight).pl().sort(col, descending=True)
        w = df[col].to_numpy()
        total = float(w.sum())
        row = {"metric": weight, "n_wallets": int(df.height), "total_weight": total,
               "gini": _gini_np(w)}
        for k in PLATFORM_TOPN:
            row[f"top{k}_share"] = float(w[:k].sum() / total)
        rows.append(row)
    name = "concentration/platform"
    out = out_dir / f"{name}.csv"
    pl.DataFrame(rows).write_csv(out)
    desc, cols = DERIVED_DESCRIPTIONS[name]
    manifest.append(_entry(name, out, out_dir, len(rows), desc, cols, "core"))
    return manifest


def export_support_files(out_dir: Path) -> list[dict]:
    manifest = []
    for src_rel, dst_name in SUPPORT_FILES:
        src = config.REPO_ROOT / src_rel
        if not src.exists():
            log.warning("support file missing, skipped: %s", src)
            continue
        dst = out_dir / dst_name
        shutil.copyfile(src, dst)
        manifest.append(_entry(dst_name, dst, out_dir, 0, "", {}, "support"))
    return manifest


def export_all(out_dir: Path, include_onchain: bool = True) -> list[dict]:
    """Export every table to ``out_dir``; return a manifest (one dict per file)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute("SET TimeZone='UTC'")
    manifest: list[dict] = []
    tables = CORE_TABLES + (ONCHAIN_TABLES if include_onchain else ())
    for t in tables:
        path, n = export_table(con, t, out_dir)
        manifest.append(_entry(t.name, path, out_dir, n, t.description, t.columns,
                               "onchain" if t in ONCHAIN_TABLES else "core"))
    for path in sorted((config.PARQUET_DIR / "backtest").glob("*_events.parquet")):
        t = ExportTable(f"backtest/{path.stem}", f"backtest/{path.name}", BACKTEST_EVENTS_DESCRIPTION)
        p, n = export_table(con, t, out_dir)
        manifest.append(_entry(t.name, p, out_dir, n, t.description, {}, "core"))
    ls = config.PARQUET_DIR / "backtest" / "leader_sets.json"
    if ls.exists():
        dst = out_dir / "backtest" / "leader_sets.json"; dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(ls, dst)
        manifest.append(_entry("backtest/leader_sets", dst, out_dir, 0,
                               "Leader-set membership and the temporal split used by the backtest.", {}, "core"))
    for name, rel, desc in PARTITION_JSON:
        path, n = export_partition_json(name, rel, out_dir)
        manifest.append(_entry(name, path, out_dir, n, desc, {}, "core"))
    manifest += export_derived(out_dir)
    manifest += export_support_files(out_dir)
    write_manifest(manifest, out_dir)
    write_readme(manifest, out_dir)
    return manifest


def write_manifest(manifest: list[dict], out_dir: Path) -> Path:
    out = out_dir / "MANIFEST.csv"
    with out.open("w") as fh:
        fh.write("table,file,group,rows,bytes\n")
        for m in manifest:
            fh.write(f"{m['table']},{m['file']},{m['group']},{m['rows']},{m['bytes']}\n")
    return out


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024:
            return f"{n:.0f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def write_readme(manifest: list[dict], out_dir: Path) -> Path:
    lines = [
        "# Polymarket market-integrity dataset — CSV export",
        "",
        "Flattened CSV export of the analysis-ready parquet store built by the "
        "`intellifi` pipeline. 100 high-volume resolved Polymarket markets "
        "(180-day lookback, end_date 2025-12-07 → 2026-05-01, fetched 2026-05-11), "
        "their trades and holders, the 134-wallet analysis universe, on-chain "
        "transfer history, and every derived analysis output. The tables under "
        "`skill/` and `concentration/` are the notebooks' on-the-fly analyses "
        "materialised with identical parameters, so every figure reported by the "
        "pipeline is reproducible from this bundle alone.",
        "",
        "## Reproducing the environment",
        "",
        "`requirements-lock.txt` pins the exact package versions used to produce this "
        "export (Python 3.13.5). Only pandas + numpy are needed to read the CSVs; the "
        "full lock file matters if you re-run the pipeline from the repository.",
        "",
        "Run `python verify_export.py` from this directory to recompute the winning "
        "outcomes, per-wallet calibration (raw and Beta-posterior), per-market Gini/HHI "
        "and the cotrade pairs from the raw CSVs and check them against the exported "
        "analysis tables. All checks should print PASS.",
        "",
        "## Conventions",
        "",
        "- All timestamps are UTC, ISO-8601 (`YYYY-MM-DDTHH:MM:SS.ffffffZ`).",
        "- Prices are in `[0, 1]` and read as implied probabilities; notional is USDC.",
        "- **Read `asset_id`, `token_id`, `condition_id`, `tx_hash` as strings** "
        "(`dtype=str` in pandas): token ids are ~77-digit integers that overflow int64 "
        "and silently lose precision as floats.",
        "- List-valued columns (`outcomes`, `clob_token_ids`, `outcome_prices_final`, "
        "`members`) are JSON strings — parse with `json.loads`.",
        "- Identifier discipline: `condition_id` keys a market (trades/holders); "
        "`asset_id` / `token_id` keys one outcome token (prices, on-chain ERC-1155); "
        "`proxy_wallet` is a Polygon address. Arrays in `markets` are positional: "
        "`outcomes[i]` ↔ `clob_token_ids[i]` ↔ `outcome_prices_final[i]`.",
        "- Neg-risk families (`markets.event_neg_risk = true`) must be analysed "
        "jointly across the family, never one Yes/No pair in isolation.",
        "- Louvain `community_id` values are a per-run labelling and are not stable "
        "across reruns of the pipeline; identify clusters by membership.",
        "",
        "## What the trade data is — read this first",
        "",
        "- `trades` is the **taker leg only** of the ~4000 most recent fills per market "
        "(one row per fill, `tx_hash` unique; the maker is never recorded). 92/100 markets "
        "hit the cap; the sample covers a median ~5–7 % of each market's volume and is "
        "dominated by post-convergence trading: ~90 % of trades execute at p ≤ 0.05 or ≥ 0.95.",
        "- `markets.closed_time` is when trading actually stopped; `end_date` is the "
        "scheduled deadline and differs from it by a median of 21 h (range −5433 h … +682 h). "
        "All time-to-close analyses use `closed_time`.",
        "- On-chain ERC-1155 transfers between wallets are CLOB fill settlements, not "
        "relationships; the entity graph uses USDC transfers only.",
        "",
        "## Three `calibration_gap` columns",
        "",
        "- `skill/position_skill.csv.calibration_gap` — **headline**: one trial per "
        "(wallet, market), informative price band, exact Beta posterior.",
        "- `skill/wallet_skill.csv.calibration_gap` — legacy size-weighted posterior "
        "(every share a trial; prior inert; dominated by converged prices). Kept for "
        "comparison with the pre-audit notebooks.",
        "- `universe.csv.calibration_gap` — raw size-weighted gap used only to select "
        "the top-50 'skill' list when the universe was built.",
        "",
        "## Analysis parameters",
        "",
        "- Universe: union of top-50 by traded notional, top-50 by realised PnL, "
        "top-50 by raw calibration gap among wallets with >= 20 resolved bets.",
        "- Position skill (headline): one trial per (wallet, market), implied p in "
        "[0.05, 0.95], >= 5 positions in >= 3 markets, prior strength 4, exact Beta "
        "quantiles, leave-one-out reliability-curve benchmark.",
        "- Legacy skill: size-weighted Bernoulli trials, `prior_strength = 4`, "
        "`min_trades = 20`; interval = posterior mean ± 1.645 posterior sd (normal approx.).",
        "- Reliability curve: 20 equal-width bins on `implied_p`.",
        "- Cotrade pairs: universe wallets, same (asset, side) within a 300 s bucket, "
        ">= 3 events; `expected_events` / `excess_ratio` / `p_value` / `q_value` from an "
        "activity-preserving null (independent placement of each wallet's buckets), "
        "Benjamini–Hochberg over all pairs.",
        "- Leader–lag: wallets trading in second s lead wallets trading in the next "
        "distinct second s' ≤ 600 s later on the same (asset, side); same-second trades "
        "are simultaneous; >= 5 events; same null model.",
        "- Rapid position flips ('wash_round_trips'): BUY→SELL on one asset within 600 s, "
        ">= 50 % size overlap, matched one-to-one; `buy_fraction` / `median_price` "
        "expose the market-maker signature. Not labelled wash trading: the counterparty "
        "is unobserved.",
        "- Entity graph: USDC direct-transfer edges (>= $100) + common-neighbour edges "
        "(shared USDC counterparties; addresses touching >= 5 universe wallets, universe "
        "members included, are suppressed as hubs), Louvain seed 42.",
        "- Backtest: horizons 300 / 1800 / 3600 / 86400 s, 60 s latency, 20 bps one-way "
        "fee, entry within 600 s, exit at last minute VWAP at or before the horizon or at "
        "the payout if `closed_time` precedes it; leader trades after `event_ts` (outcome "
        "priced in) excluded; each set has a matched placebo control (same asset & side, "
        "±15 min, ±0.05 price, non-universe wallets).",
        "",
        "## Known limitations",
        "",
        "- `trades` is capped upstream at ~4000 most-recent trades per market (taker leg only).",
        "- `prices_history` covers the 30 days before the 2026-05-11 fetch at 600 s "
        "spacing (the CLOB `interval` parameter is a lookback window); only the 19 markets "
        "that closed in that window have series.",
        "- `holders` returns at most 500 holders per outcome; 92/100 markets are truncated.",
        "- On-chain transfer history per wallet is bounded by the Etherscan page cap in "
        "script 03; heavy wallets are truncated.",
        "- On-chain tables: ~1 % of rows are duplicates (a transfer between two universe "
        "wallets is stored once under each `owner`) — dedupe on "
        "`(tx_hash, from_address, to_address, token_id/value)` before counting.",
        "",
        "## Files",
        "",
        "| file | rows | size | description |",
        "|---|---:|---:|---|",
    ]
    for m in manifest:
        if m["group"] == "support":
            continue
        lines.append(f"| `{m['file']}` | {m['rows']:,} | {_fmt_bytes(m['bytes'])} | {m['description']} |")
    support = [m for m in manifest if m["group"] == "support"]
    if support:
        lines += ["", "Support files: " + ", ".join(f"`{m['file']}`" for m in support) + "."]
    lines += ["", "## Column notes", ""]
    for m in manifest:
        if not m["columns"]:
            continue
        lines.append(f"### `{m['file']}`")
        lines.append("")
        for col, note in m["columns"].items():
            lines.append(f"- `{col}` — {note}")
        lines.append("")
    out = out_dir / "README.md"
    out.write_text("\n".join(lines))
    return out


def zip_export(out_dir: Path, manifest: list[dict]) -> list[Path]:
    """Bundle core (+ support) and on-chain files into separate zip archives."""
    archives: list[Path] = []
    for group in ("core", "onchain"):
        files = [m["file"] for m in manifest if m["group"] == group]
        if not files:
            continue
        if group == "core":
            files += [m["file"] for m in manifest if m["group"] == "support"]
            files += ["README.md", "MANIFEST.csv"]
        zpath = out_dir.parent / f"polymarket_dataset_{group}.zip"
        with zipfile.ZipFile(zpath, "w", zipfile.ZIP_DEFLATED) as zf:
            for f in files:
                zf.write(out_dir / f, arcname=f)
        archives.append(zpath)
        log.info("wrote %s (%s)", zpath, _fmt_bytes(zpath.stat().st_size))
    return archives

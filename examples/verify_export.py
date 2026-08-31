#!/usr/bin/env python
"""Recompute headline quantities from the raw CSVs and check them against the
exported analysis tables. Confirms your environment reproduces the pipeline
before you extend the analysis.

Usage:
    python verify_export.py [EXPORT_DIR]      # default: directory of this file

Requires only pandas >= 2 and numpy. Runs in ~1 minute.

Checks (all derived from markets.csv, trades.csv, universe.csv only):
    1. winning outcome per market            -> winning_outcomes.csv
    2. bets table row count                  -> skill/bets.csv
    3. raw per-wallet calibration (universe) -> universe.csv
    4. Beta-posterior wallet skill           -> skill/wallet_skill.csv
    5. per-market Gini / HHI / top-N shares  -> concentration/market_trade_notional.csv
    6. cotrade pairs (300 s buckets)         -> coordination/cotrade_pairs.csv
"""
from __future__ import annotations

import itertools
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

TOL = 1e-6
PRIOR_STRENGTH = 4.0
MIN_TRADES = 20
COTRADE_WINDOW_S = 300
COTRADE_MIN_EVENTS = 3
ID_COLS = {"condition_id": str, "asset_id": str, "token_id": str, "tx_hash": str,
           "winning_token_id": str, "proxy_wallet": str, "a": str, "b": str}

root = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent
failures = 0


def check(name: str, ok: bool, detail: str = "") -> None:
    global failures
    failures += (not ok)
    print(f"[{'PASS' if ok else 'FAIL'}] {name}  {detail}")


def read(name: str, dtype: dict | None = None, **kw) -> pd.DataFrame:
    return pd.read_csv(root / name, dtype={**ID_COLS, **(dtype or {})}, **kw)


def maxdiff(a: pd.Series, b: pd.Series) -> float:
    return float((a.astype(float) - b.astype(float)).abs().max())


print(f"export dir: {root}\n")
markets = read("markets.csv")
trades = read("trades.csv")
universe = read("universe.csv")

# ---------------------------------------------------------------- 1. winners
def winner(prices_json: str):
    prices = [(-np.inf if p is None else p) for p in json.loads(prices_json)]
    if not prices:
        return None
    i = int(np.argmax(prices))          # ties -> lowest index (ORDER BY p DESC, idx ASC)
    return i if prices[i] >= 0.5 else None

winners = markets.assign(winning_outcome_index=markets["outcome_prices_final"].map(winner))
winners = winners.dropna(subset=["winning_outcome_index"])[["condition_id", "winning_outcome_index"]]
winners["winning_outcome_index"] = winners["winning_outcome_index"].astype(int)
wo = read("winning_outcomes.csv")
m = winners.merge(wo[["condition_id", "winning_outcome_index"]], on="condition_id",
                  how="outer", suffixes=("", "_exp"), indicator=True)
check("1. winning outcomes", (m["_merge"] == "both").all()
      and (m["winning_outcome_index"] == m["winning_outcome_index_exp"]).all(),
      f"{len(winners)} resolved markets")

# ---------------------------------------------------------------- 2. bets
t = trades.dropna(subset=["proxy_wallet", "price", "size"])
t = t[(t["price"] > 0) & (t["price"] < 1) & (t["size"] > 0)]
bets = t.merge(winners, on="condition_id")
bets = bets[bets["side"].isin(["BUY", "SELL"])].copy()
bets["implied_p"] = np.where(bets["side"] == "BUY", bets["price"], 1.0 - bets["price"])
bets["won"] = np.where(bets["side"] == "BUY",
                       bets["outcome_index"] == bets["winning_outcome_index"],
                       bets["outcome_index"] != bets["winning_outcome_index"]).astype(int)
n_exp = int(read("skill/bets.csv", usecols=["implied_p"])["implied_p"].notna().sum())
check("2. bets table", len(bets) == n_exp, f"{len(bets):,} bets (expected {n_exp:,})")

# ---------------------------------------------------------------- 3. raw calibration
g = bets.groupby("proxy_wallet")
raw = pd.DataFrame({
    "n_bets": g.size(),
    "w": g["size"].sum(),
    "w_won": (bets["size"] * bets["won"]).groupby(bets["proxy_wallet"]).sum(),
    "w_imp": (bets["size"] * bets["implied_p"]).groupby(bets["proxy_wallet"]).sum(),
})
raw["realised_hit_rate"] = raw["w_won"] / raw["w"]
raw["mean_implied_p"] = raw["w_imp"] / raw["w"]
raw["calibration_gap"] = raw["realised_hit_rate"] - raw["mean_implied_p"]

u = universe.dropna(subset=["calibration_gap"]).merge(raw, left_on="proxy_wallet",
                                                       right_index=True, suffixes=("_exp", ""))
ok = (len(u) == universe["calibration_gap"].notna().sum()
      and (u["n_bets"] == u["n_bets_exp"]).all()
      and (u["n_bets"] >= MIN_TRADES).all())
d = max(maxdiff(u["realised_hit_rate"], u["realised_hit_rate_exp"]),
        maxdiff(u["mean_implied_p"], u["mean_implied_p_exp"]),
        maxdiff(u["calibration_gap"], u["calibration_gap_exp"]))
check("3. raw calibration gap (universe.csv)", ok and d < TOL,
      f"{len(u)} wallets, max |diff| = {d:.2e}")

# ---------------------------------------------------------------- 4. Beta posterior
r = raw[raw["n_bets"] >= MIN_TRADES].copy()
r["prior_alpha"] = r["mean_implied_p"] * PRIOR_STRENGTH
r["prior_beta"] = (1.0 - r["mean_implied_p"]) * PRIOR_STRENGTH
a = r["prior_alpha"] + r["w_won"]
b = r["prior_beta"] + (r["w"] - r["w_won"])
r["posterior_mean_hit_rate"] = a / (a + b)
r["calibration_gap"] = r["posterior_mean_hit_rate"] - r["mean_implied_p"]
sd = np.sqrt(a * b / ((a + b) ** 2 * (a + b + 1.0)))
r["ci_low"] = np.clip(r["posterior_mean_hit_rate"] - 1.645 * sd, 0.0, None)
r["ci_high"] = np.clip(r["posterior_mean_hit_rate"] + 1.645 * sd, None, 1.0)
ws = read("skill/wallet_skill.csv").set_index("proxy_wallet")
same_set = set(ws.index) == set(r.index)
r = r.reindex(ws.index)
d = max(maxdiff(r[c], ws[c]) for c in
        ["posterior_mean_hit_rate", "calibration_gap", "ci_low", "ci_high"]) if same_set else np.inf
check("4. Beta-posterior skill (skill/wallet_skill.csv)", same_set and d < TOL,
      f"{len(ws)} wallets with >= {MIN_TRADES} bets, max |diff| = {d:.2e}")
if same_set:
    top = ws.sort_values("calibration_gap", ascending=False).head(3)
    print("     top-3 posterior calibration_gap:",
          ", ".join(f"{w[:10]}…={v:.3f}" for w, v in top["calibration_gap"].items()))

# ---------------------------------------------------------------- 5. concentration
w = trades.dropna(subset=["proxy_wallet", "notional_usdc"])
w = w[w["notional_usdc"] > 0]
ww = w.groupby(["condition_id", "proxy_wallet"])["notional_usdc"].sum().reset_index()


def gini(x: np.ndarray) -> float:
    x = np.sort(np.asarray(x, dtype=float))
    n = x.size
    if n <= 1 or x.sum() == 0:
        return np.nan
    return 2.0 * (np.arange(1, n + 1) * x).sum() / (n * x.sum()) - (n + 1.0) / n


def topk(x: np.ndarray, k: int) -> float:
    x = np.sort(np.asarray(x, dtype=float))[::-1]
    return x[:k].sum() / x.sum()


conc = ww.groupby("condition_id")["notional_usdc"].agg(
    n_wallets="size", gini=gini, hhi=lambda x: ((x / x.sum()) ** 2).sum(),
    top1_share=lambda x: topk(x.values, 1), top10_share=lambda x: topk(x.values, 10))
exp = read("concentration/market_trade_notional.csv", dtype={"group_key": str}).set_index("group_key")
exp = exp.reindex(conc.index)
d = max(maxdiff(conc[c], exp[c]) for c in ["gini", "hhi", "top1_share", "top10_share"])
check("5. per-market Gini/HHI (concentration/market_trade_notional.csv)",
      (conc["n_wallets"] == exp["n_wallets"]).all() and d < TOL,
      f"{len(conc)} markets, mean Gini = {conc['gini'].mean():.4f}, max |diff| = {d:.2e}")

# ---------------------------------------------------------------- 6. cotrade pairs
uni = set(universe["proxy_wallet"].str.lower())
c = trades.dropna(subset=["proxy_wallet", "asset_id", "side", "ts_utc"])
c = c[c["proxy_wallet"].isin(uni)].copy()
epoch = (pd.to_datetime(c["ts_utc"], utc=True) - pd.Timestamp(0, tz="UTC")).dt.total_seconds()
c["bucket"] = np.floor(epoch / COTRADE_WINDOW_S).astype("int64")
per_wb = (c.groupby(["asset_id", "side", "bucket", "condition_id", "proxy_wallet"])["notional_usdc"]
           .sum().reset_index())
grp = (per_wb.groupby(["asset_id", "side", "bucket", "condition_id"])
        .agg(wallets=("proxy_wallet", lambda s: sorted(s)),
             notionals=("notional_usdc", list)).reset_index())
grp = grp[grp["wallets"].str.len() >= 2]
rows = []
for row in grp.itertuples(index=False):
    wn = dict(zip(row.wallets, row.notionals))
    for a_, b_ in itertools.combinations(row.wallets, 2):
        rows.append((a_, b_, row.condition_id, row.bucket, wn[a_] + wn[b_]))
pairs = pd.DataFrame(rows, columns=["a", "b", "condition_id", "bucket", "pair_notional"])
ct = (pairs.groupby(["a", "b"])
           .agg(cotrade_events=("condition_id", "size"), cotrade_markets=("condition_id", "nunique"),
                cotrade_buckets=("bucket", "nunique"), pair_notional=("pair_notional", "sum"))
           .reset_index())
ct = ct[ct["cotrade_events"] >= COTRADE_MIN_EVENTS].set_index(["a", "b"])
exp = read("coordination/cotrade_pairs.csv").set_index(["a", "b"])
same_set = set(ct.index) == set(exp.index)
if same_set:
    exp = exp.reindex(ct.index)
    ok = ((ct["cotrade_events"] == exp["cotrade_events"]).all()
          and (ct["cotrade_markets"] == exp["cotrade_markets"]).all()
          and (ct["cotrade_buckets"] == exp["cotrade_buckets"]).all()
          and maxdiff(ct["pair_notional"], exp["pair_notional"]) < 1e-3)
else:
    ok = False
check("6. cotrade pairs (coordination/cotrade_pairs.csv)", ok,
      f"{len(ct)} pairs (expected {len(exp)})")

print(f"\n{'ALL CHECKS PASSED' if failures == 0 else f'{failures} CHECK(S) FAILED'}")
sys.exit(1 if failures else 0)

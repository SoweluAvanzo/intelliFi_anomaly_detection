#!/usr/bin/env python
"""Wealth x implied-probability x edge: do larger accounts win more than the entry
price implies, specifically in LOW implied-probability (longshot) markets?

Runs on Sample A (the Data-API taker feed) via the warehouse `bets` view
(skill._BETS_SQL): per position it has the entry implied probability, a 0/1 win
flag, and a wallet account-size proxy (cumulative taker notional). Network-free.

Two readings, because reliability is the point:
  (1) POOLED cross-tab: account-size quartile x implied-p band, trade-level
      calibration_gap = realised_hit_rate - mean_implied_p (edge above what they
      paid). Descriptive; a trade-level CI ignores that a wallet's trades are
      correlated, so it OVERSTATES significance.
  (2) WALLET-CLUSTERED test: one calibration_gap per wallet within the low-p band,
      then compare the DISTRIBUTION across account-size quartiles (each wallet = one
      independent observation). This is the honest test of "big accounts win more in
      longshots"; it reports a bootstrap CI on the per-quartile mean and on the
      top-minus-bottom quartile difference.

Caveats surfaced in the output: the feed is a taker-side TAIL sample; account size
from it is a weak wealth proxy (on-chain USDC balance would be better); account size
is outcome-dependent (winners accumulate) so this is associational, not causal.

    python scripts/20_wealth_edge.py --out docs/wealth_edge.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi.warehouse import open_warehouse  # noqa: E402
from intellifi.skill import build_bets_view      # noqa: E402

LOW_P = 0.20   # "low implied probability" / longshot threshold
HIGH_P = 0.80


def boot_ci(x: np.ndarray, n_boot: int = 5000, seed: int = 42) -> tuple[float, float]:
    """95% bootstrap CI for the mean of x (resampling the wallets)."""
    if len(x) == 0:
        return (float("nan"), float("nan"))
    rng = np.random.default_rng(seed)
    means = x[rng.integers(0, len(x), size=(n_boot, len(x)))].mean(axis=1)
    return (float(np.percentile(means, 2.5)), float(np.percentile(means, 97.5)))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/wealth_edge.json")
    ap.add_argument("--min-wallet-bets", type=int, default=5,
                    help="min low-p bets for a wallet to enter the clustered test")
    ap.add_argument("--memory-limit", default=None,
                    help="DuckDB memory_limit (e.g. 9GB); also spills to on-disk temp under DATA_DIR")
    args = ap.parse_args()

    con = open_warehouse(":memory:")
    if args.memory_limit:
        import pathlib
        from intellifi import config as _cfg
        con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
        con.execute("SET preserve_insertion_order=false")
        _tmp = _cfg.DATA_DIR / "_s20_tmp"
        _tmp.mkdir(parents=True, exist_ok=True)
        con.execute(f"SET temp_directory='{_tmp.as_posix()}'")
        con.execute("SET max_temp_directory_size='40GB'")
    build_bets_view(con)

    # Account-size proxy: cumulative taker notional per wallet; quartile-rank wallets.
    con.execute("""
        CREATE TEMP TABLE wsize AS
        SELECT proxy_wallet, SUM(notional_usdc) AS acct_notional, COUNT(*) AS n_bets
        FROM bets WHERE implied_p IS NOT NULL AND won IS NOT NULL
        GROUP BY proxy_wallet;
    """)
    con.execute("""
        CREATE TEMP TABLE wq AS
        SELECT proxy_wallet, acct_notional, n_bets,
               ntile(4) OVER (ORDER BY acct_notional) AS acct_q
        FROM wsize;
    """)
    con.execute("""
        CREATE TEMP TABLE b AS
        SELECT bets.proxy_wallet, wq.acct_q, bets.implied_p, bets.won, bets.size,
               CASE WHEN bets.implied_p < %f THEN 'low(<%.2f)'
                    WHEN bets.implied_p > %f THEN 'high(>%.2f)'
                    ELSE 'mid' END AS pband
        FROM bets JOIN wq USING (proxy_wallet)
        WHERE bets.implied_p IS NOT NULL AND bets.won IS NOT NULL;
    """ % (LOW_P, LOW_P, HIGH_P, HIGH_P))

    rep: dict = {"low_p_threshold": LOW_P, "high_p_threshold": HIGH_P,
                 "n_wallets": con.execute("SELECT count(*) FROM wq").fetchone()[0]}

    # quartile notional boundaries (context)
    rep["acct_quartile_notional"] = [
        {"q": int(q), "n_wallets": int(nw), "min_notional": mn, "median_notional": md, "max_notional": mx}
        for q, nw, mn, md, mx in con.execute("""
            SELECT acct_q, count(*), min(acct_notional), median(acct_notional), max(acct_notional)
            FROM wq GROUP BY acct_q ORDER BY acct_q""").fetchall()]

    # (1) POOLED cross-tab (trade-level; CI is size-weighted normal approx, OVERSTATES)
    rep["pooled_crosstab"] = [
        {"acct_q": int(q), "pband": pb, "n_trades": int(n), "n_wallets": int(nw),
         "mean_implied_p": mip, "realised_hit_rate": hr, "calibration_gap": gap}
        for q, pb, n, nw, mip, hr, gap in con.execute("""
            SELECT acct_q, pband, count(*) n, count(DISTINCT proxy_wallet) nw,
                   avg(implied_p) mip, avg(won::DOUBLE) hr, avg(won::DOUBLE) - avg(implied_p) gap
            FROM b GROUP BY acct_q, pband ORDER BY pband, acct_q""").fetchall()]

    # (2) WALLET-CLUSTERED test in the LOW-p band: one gap per wallet, compare quartiles.
    rows = con.execute(f"""
        SELECT acct_q, proxy_wallet,
               avg(won::DOUBLE) - avg(implied_p) AS wallet_gap, count(*) AS n
        FROM b WHERE pband = 'low(<{LOW_P:.2f})'
        GROUP BY acct_q, proxy_wallet
        HAVING count(*) >= {args.min_wallet_bets}
    """).fetchall()
    import collections
    byq = collections.defaultdict(list)
    for q, _w, gap, _n in rows:
        byq[int(q)].append(gap)
    clustered = []
    for q in sorted(byq):
        x = np.array(byq[q], dtype=float)
        lo, hi = boot_ci(x)
        clustered.append({"acct_q": q, "n_wallets": len(x), "mean_wallet_gap": float(x.mean()),
                          "ci95": [lo, hi], "gap_ci_excludes_0": bool(lo > 0 or hi < 0)})
    rep["lowp_wallet_clustered"] = clustered

    # top-minus-bottom quartile difference in low-p per-wallet gap, with bootstrap CI
    if 4 in byq and 1 in byq:
        q4, q1 = np.array(byq[4]), np.array(byq[1])
        rng = np.random.default_rng(7)
        d = (q4[rng.integers(0, len(q4), (5000, len(q4)))].mean(1)
             - q1[rng.integers(0, len(q1), (5000, len(q1)))].mean(1))
        lo, hi = float(np.percentile(d, 2.5)), float(np.percentile(d, 97.5))
        rep["lowp_Q4_minus_Q1"] = {"diff": float(q4.mean() - q1.mean()), "ci95": [lo, hi],
                                   "reliable_positive": bool(lo > 0)}

    # verdict
    v = rep.get("lowp_Q4_minus_Q1", {})
    q4c = next((c for c in clustered if c["acct_q"] == 4), None)
    rep["verdict"] = (
        "RELIABLE: largest-account wallets have a significantly higher low-p edge than the smallest"
        if v.get("reliable_positive") and q4c and q4c["gap_ci_excludes_0"] and q4c["mean_wallet_gap"] > 0
        else "NOT RELIABLE: no significant wealth->longshot-edge effect at the wallet-clustered level "
             "(trade-level pooled patterns may look larger but ignore within-wallet correlation)")
    rep["caveats"] = [
        "Sample A = taker-side TAIL feed (4000-cap/market, ~90% at extreme prices); a biased slice.",
        "Account size = cumulative feed taker notional — a weak wealth proxy (on-chain USDC balance is better).",
        "Account size is outcome-dependent (winners accumulate): associational, not causal.",
        "Wallet-clustered CI is the honest test; the pooled cross-tab overstates significance.",
    ]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    print("VERDICT:", rep["verdict"])
    if "lowp_Q4_minus_Q1" in rep:
        d = rep["lowp_Q4_minus_Q1"]
        print(f"low-p edge Q4-Q1 diff = {d['diff']:+.4f}  95%CI [{d['ci95'][0]:+.4f}, {d['ci95'][1]:+.4f}]  reliable+={d['reliable_positive']}")
    for c in clustered:
        print(f"  Q{c['acct_q']}: n_wallets={c['n_wallets']:>5} mean low-p gap={c['mean_wallet_gap']:+.4f} "
              f"CI[{c['ci95'][0]:+.4f},{c['ci95'][1]:+.4f}] excl0={c['gap_ci_excludes_0']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

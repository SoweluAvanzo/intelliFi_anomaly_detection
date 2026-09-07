#!/usr/bin/env python
"""Detect a SKILLED POPULATION, not certify individuals.

Per-wallet Benjamini-Hochberg (scripts/skill) answers "which specific wallets are
provably skilled?" — a stringent, low-power question that finds ~0 when wallets have
few positions. This script answers the market-level question instead: "does the
population of traders contain edge/skill beyond chance?", which is far better powered
and is the interesting one for market integrity (a skilled/informed TAIL is the triage
signal). Rigorous + comprehensive:

  A. AGGREGATE gap vs price: pooled (win-rate - entry-implied-p) with a wallet-bootstrap
     CI. Captures the market-average edge vs the maker's price (incl. favorite-longshot).
  B. AGGREGATE excess over the corpus reliability curve (edge beyond fav-longshot). ~0 by
     construction (deviations from the corpus mean) — reported as an anchor/check.
  C. SKILLED-POPULATION test (headline), parametric null wins_i ~ Binom(n_i, implied_p_i)
     ["each wallet wins at the rate it paid"]: is the observed number of nominally-winning
     wallets (one-sided binomial p<alpha) in EXCESS of the ~alpha*N chance rate, and does
     the gap distribution show positive over-dispersion / a heavier positive tail than the
     null? Winners-vs-losers asymmetry is reported (luck is symmetric; skill is not).
  D. EXCESS-OVER-RELIABILITY tail via an ACTIVITY-PRESERVING null: shuffle `won` WITHIN each
     implied-p decile (preserves each wallet's position count + the corpus curve, destroys
     skill), and ask whether the observed positive tail of per-wallet excess beats the null.
     This isolates skill BEYOND the favorite-longshot bias every participant shares.

Runs on whatever INTELLIFI_SOURCE points at; use the COMPLETE v1 archive
(INTELLIFI_SOURCE=archive) for power — the 100-market feed has ~12 qualifiers.

    INTELLIFI_SOURCE=archive python scripts/23_skilled_population.py --out docs/skilled_population.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi.warehouse import open_warehouse  # noqa: E402
from intellifi.skill import build_bets_view, PositionSkillConfig  # noqa: E402


def bootstrap_ci(x: np.ndarray, stat, n_boot=5000, seed=0):
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(x), size=(n_boot, len(x)))
    vals = np.array([stat(x[i]) for i in idx])
    return float(np.percentile(vals, 2.5)), float(np.percentile(vals, 97.5))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/skilled_population.json")
    ap.add_argument("--alpha", type=float, default=0.05)
    ap.add_argument("--n-sims", type=int, default=4000, help="parametric null draws (C)")
    ap.add_argument("--n-shuffle", type=int, default=1000, help="activity-preserving shuffles (D)")
    ap.add_argument("--min-positions", type=int, default=5)
    ap.add_argument("--min-markets", type=int, default=3)
    ap.add_argument("--p-low", type=float, default=0.05)
    ap.add_argument("--p-high", type=float, default=0.95)
    ap.add_argument("--memory-limit", default="8GB")
    ap.add_argument("--seed", type=int, default=42)
    args = ap.parse_args()
    from scipy.stats import binom

    con = open_warehouse(":memory:")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute("SET preserve_insertion_order=false")
    # Spill to REAL DISK (not tmpfs /tmp), bounded, so a heavy archive read neither OOMs
    # nor runaway-fills the disk (the shared box just hit 'No space left' on a 450M-row job).
    from intellifi import config as _cfg
    _tmp = _cfg.DATA_DIR / "_s23_tmp"
    _tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{_tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='40GB'")
    build_bets_view(con)

    # Position-level informative trials (one row per (wallet, market) net direction),
    # mirroring skill.position_skill's b->pos->trials->informative, WITH the decile.
    pos = con.sql(f"""
        WITH b AS (
            SELECT proxy_wallet, condition_id, size, notional_usdc,
                   CASE WHEN (side='BUY' AND outcome_index=0) OR (side='SELL' AND outcome_index<>0) THEN 1 ELSE -1 END AS dir0,
                   CASE WHEN (side='BUY' AND outcome_index=0) OR (side='SELL' AND outcome_index<>0) THEN implied_p ELSE 1.0-implied_p END AS p0,
                   CASE WHEN winning_outcome_index=0 THEN 1 ELSE 0 END AS won0
            FROM bets
            WHERE implied_p IS NOT NULL AND won IS NOT NULL AND outcome_index IN (0,1)
        ),
        pos AS (
            SELECT proxy_wallet, condition_id,
                   SUM(dir0*size) AS net,
                   SUM(CASE WHEN dir0=1 THEN size*p0 END)/NULLIF(SUM(CASE WHEN dir0=1 THEN size END),0) AS p_long,
                   SUM(CASE WHEN dir0=-1 THEN size*(1.0-p0) END)/NULLIF(SUM(CASE WHEN dir0=-1 THEN size END),0) AS p_short,
                   ANY_VALUE(won0) AS won0
            FROM b GROUP BY 1,2 HAVING SUM(dir0*size)<>0
        ),
        trials AS (
            SELECT proxy_wallet,
                   CASE WHEN net>0 THEN p_long ELSE p_short END AS implied_p,
                   CASE WHEN net>0 THEN won0 ELSE 1-won0 END AS won
            FROM pos
        )
        SELECT proxy_wallet, implied_p, won,
               LEAST(9, FLOOR(implied_p*10))::INT AS decile
        FROM trials
        WHERE implied_p BETWEEN {args.p_low} AND {args.p_high}
    """).pl()

    if pos.is_empty():
        print("no informative positions", file=sys.stderr); return 2
    import polars as pl
    # keep wallets with enough positions/markets (markets == positions here: 1 trial/market)
    w = (pos.group_by("proxy_wallet")
         .agg(pl.len().alias("n"), pl.col("won").sum().alias("wins"),
              pl.col("implied_p").mean().alias("p")))
    w = w.filter(pl.col("n") >= args.min_positions)  # n distinct markets == n positions
    wallets = w["proxy_wallet"].to_list()
    n_arr = w["n"].to_numpy().astype(int)
    wins = w["wins"].to_numpy().astype(int)
    p_arr = w["p"].to_numpy().astype(float)
    N = len(n_arr)
    gap = wins / n_arr - p_arr
    rep: dict = {"source": __import__("os").getenv("INTELLIFI_SOURCE", "parquet"),
                 "n_qualifying_wallets": N,
                 "positions_per_wallet": {"min": int(n_arr.min()), "median": float(np.median(n_arr)),
                                          "p90": float(np.percentile(n_arr, 90)), "max": int(n_arr.max())}}

    # A. aggregate gap vs price (pooled over positions), wallet-bootstrap CI
    pos_all = pos.filter(pl.col("proxy_wallet").is_in(wallets))
    agg_win = float(pos_all["won"].mean()); agg_p = float(pos_all["implied_p"].mean())
    # wallet-level gap bootstrap (each wallet one obs, weighted equally)
    lo, hi = bootstrap_ci(gap, np.mean, seed=args.seed)
    rep["A_aggregate_gap_vs_price"] = {"pooled_hit_rate": agg_win, "pooled_implied_p": agg_p,
                                       "pooled_gap": agg_win - agg_p,
                                       "mean_wallet_gap": float(gap.mean()), "wallet_gap_ci95": [lo, hi]}

    # C. parametric null wins~Binom(n, p): excess winners + over-dispersion + tail
    rng = np.random.default_rng(args.seed)
    p_win = binom.sf(wins - 1, n_arr, p_arr)          # one-sided P(X>=wins)
    p_lose = binom.cdf(wins, n_arr, p_arr)            # one-sided P(X<=wins)
    obs_winners = int((p_win < args.alpha).sum())
    obs_losers = int((p_lose < args.alpha).sum())
    sim = rng.binomial(n_arr[None, :], p_arr[None, :], size=(args.n_sims, N))
    sim_pwin = binom.sf(sim - 1, n_arr[None, :], p_arr[None, :])
    sim_winner_counts = (sim_pwin < args.alpha).sum(axis=1)
    sim_gap = sim / n_arr[None, :] - p_arr[None, :]
    rep["C_skilled_population"] = {
        "alpha": args.alpha,
        "observed_winners": obs_winners,
        "null_winners_mean": float(sim_winner_counts.mean()),
        "null_winners_ci95": [float(np.percentile(sim_winner_counts, 2.5)), float(np.percentile(sim_winner_counts, 97.5))],
        "excess_winners": obs_winners - float(sim_winner_counts.mean()),
        "empirical_p_winners": float((sim_winner_counts >= obs_winners).mean()),
        "observed_losers": obs_losers,
        "winner_loser_asymmetry": obs_winners - obs_losers,
        "obs_gap_std": float(gap.std()), "null_gap_std_mean": float(sim_gap.std(axis=1).mean()),
        "obs_gap_p95": float(np.percentile(gap, 95)), "null_gap_p95_mean": float(np.percentile(sim_gap, 95, axis=1).mean()),
        "obs_gap_p99": float(np.percentile(gap, 99)), "null_gap_p99_mean": float(np.percentile(sim_gap, 99, axis=1).mean()),
        "interpretation": ("skilled population beyond chance" if obs_winners > np.percentile(sim_winner_counts, 97.5)
                           else "winner count within chance — no population-level skill signal at this alpha"),
    }

    # D. excess-over-reliability tail via within-decile outcome shuffle (activity-preserving)
    dec = pos_all["decile"].to_numpy()
    won_all = pos_all["won"].to_numpy().astype(float)
    wid = pos_all["proxy_wallet"].to_numpy()
    # map wallet -> index
    widx = {wd: i for i, wd in enumerate(wallets)}
    wi = np.array([widx[x] for x in wid])
    # corpus leave-one-out decile mean per position (observed)
    def per_wallet_excess(won_vec):
        # decile means
        dmean = np.zeros(10); dcnt = np.zeros(10)
        for d in range(10):
            m = dec == d
            dcnt[d] = m.sum(); dmean[d] = won_vec[m].mean() if dcnt[d] else 0.0
        loo = (dmean[dec] * dcnt[dec] - won_vec) / np.maximum(dcnt[dec] - 1, 1)
        exc = won_vec - loo
        # aggregate per wallet
        out = np.zeros(N); cnt = np.zeros(N)
        np.add.at(out, wi, exc); np.add.at(cnt, wi, 1.0)
        return out / np.maximum(cnt, 1)
    obs_excess = per_wallet_excess(won_all)
    obs_tail = float((obs_excess > 0).mean())
    obs_excess_p95 = float(np.percentile(obs_excess, 95))
    # null: shuffle won within each decile
    idx_by_dec = [np.where(dec == d)[0] for d in range(10)]
    null_p95 = np.empty(args.n_shuffle)
    for b in range(args.n_shuffle):
        wv = won_all.copy()
        for d in range(10):
            ii = idx_by_dec[d]
            if len(ii) > 1:
                wv[ii] = won_all[rng.permutation(ii)]
        ex = per_wallet_excess(wv)
        null_p95[b] = np.percentile(ex, 95)
    rep["D_excess_over_reliability_tail"] = {
        "obs_mean_excess": float(obs_excess.mean()),
        "obs_frac_positive": obs_tail,
        "obs_excess_p95": obs_excess_p95,
        "null_excess_p95_mean": float(null_p95.mean()),
        "null_excess_p95_ci95": [float(np.percentile(null_p95, 2.5)), float(np.percentile(null_p95, 97.5))],
        "empirical_p": float((null_p95 >= obs_excess_p95).mean()),
        "interpretation": ("skill beyond favorite-longshot: positive tail exceeds activity-preserving null"
                           if obs_excess_p95 > np.percentile(null_p95, 97.5)
                           else "positive tail within the activity-preserving null — no skill beyond fav-longshot"),
    }

    # top wallets for context
    order = np.argsort(gap)[::-1][:10]
    rep["top_wallets_by_gap"] = [
        {"wallet": wallets[i], "n": int(n_arr[i]), "wins": int(wins[i]), "implied_p": round(float(p_arr[i]), 3),
         "gap": round(float(gap[i]), 3), "binom_p_win": round(float(p_win[i]), 4)} for i in order]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}  (source={rep['source']}, {N} qualifying wallets, median {rep['positions_per_wallet']['median']:.0f} positions)")
    print(f"A pooled gap vs price: {rep['A_aggregate_gap_vs_price']['pooled_gap']:+.4f} | wallet-mean {gap.mean():+.4f} CI{rep['A_aggregate_gap_vs_price']['wallet_gap_ci95']}")
    c = rep["C_skilled_population"]
    print(f"C winners obs {c['observed_winners']} vs null {c['null_winners_mean']:.1f} (CI {c['null_winners_ci95']}), emp_p {c['empirical_p_winners']:.4f}; losers {c['observed_losers']} -> {c['interpretation']}")
    d = rep["D_excess_over_reliability_tail"]
    print(f"D excess p95 obs {d['obs_excess_p95']:+.4f} vs null {d['null_excess_p95_mean']:+.4f}, emp_p {d['empirical_p']:.4f} -> {d['interpretation']}")
    con.close()
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

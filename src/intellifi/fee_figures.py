"""Charts for the fee-effects analysis (RQ1 calibration, incidence, RQ2 price correction).

Each function returns a matplotlib Figure from the `data/export/` outputs. Palette is the
colorblind-safe Okabe-Ito set. Used by `notebooks/fee_effects.ipynb`. See `docs/FEE_EFFECTS.md`.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt

from . import config as _cfg

EXPORT = _cfg.DATA_DIR / "export"
# Okabe-Ito colorblind-safe
BLUE, ORANGE, GREEN, RED, GREY = "#0072B2", "#E69F00", "#009E73", "#D55E00", "#999999"
plt.rcParams.update({"figure.dpi": 110, "axes.spines.top": False, "axes.spines.right": False,
                     "axes.grid": True, "grid.alpha": 0.25, "font.size": 10})


def _p(name):
    return EXPORT / name


def fig_reliability():
    """V1 vs V2 reliability curves (>=7d life, 1-day horizon) — both on the diagonal."""
    df = pd.read_csv(_p("calibration_reliability_1d.csv"))
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color=GREY, lw=1, label="perfect calibration")
    for era, c in [("v1 pre-fee", BLUE), ("v2 fee", ORANGE)]:
        d = df[df.era == era].sort_values("bucket")
        ax.plot(d.bucket, d.empirical, "-o", color=c, lw=2, ms=5, label=era)
    ax.set_xlabel("predicted probability (1 day before)"); ax.set_ylabel("empirical win rate")
    ax.set_title("Forecast calibration is unchanged by the fee"); ax.legend(frameon=False)
    ax.set_xlim(-.02, 1.02); ax.set_ylim(-.02, 1.02); fig.tight_layout(); plt.close(fig); return fig


def fig_brier_decomp():
    """Brier reliability (mis-calibration ~0) vs resolution (sharpness) by era, at last trade."""
    era = pd.read_csv(_p("calibration_era_decomposition.csv"))
    d = era[era.horizon == "p_last"].copy()
    labels = d.era.tolist(); x = np.arange(len(d)); w = 0.38
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar(x - w / 2, d.reliability, w, color=RED, label="reliability (mis-calibration)")
    ax.bar(x + w / 2, d.resolution, w, color=BLUE, label="resolution (sharpness)")
    for xi, r in zip(x - w / 2, d.reliability):
        ax.text(xi, r + .005, f"{r:.4f}", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(labels); ax.set_ylabel("Brier component")
    ax.set_title("Reliability ≈ 0 in both eras; the gap is sharpness/mix"); ax.legend(frameon=False)
    fig.tight_layout(); plt.close(fig); return fig


def fig_incidence_price():
    """Effective fee rate by price region — strongly regressive (longshot vs favorite)."""
    d = pd.read_csv(_p("incidence_by_price.csv"))
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.bar(d.preg, d.eff_rate_pct, color=BLUE)
    for xi, v in zip(range(len(d)), d.eff_rate_pct):
        ax.text(xi, v + .03, f"{v:.2f}%", ha="center", va="bottom", fontsize=8)
    ax.set_ylabel("effective fee rate (% of notional)"); ax.set_xlabel("buy price (outcome probability)")
    ax.set_title("Fee incidence is regressive: longshots pay ~40× favorites")
    plt.setp(ax.get_xticklabels(), rotation=20, ha="right"); fig.tight_layout(); plt.close(fig); return fig


def fig_incidence_size():
    """Effective rate by taker-size decile — smaller traders pay more."""
    d = pd.read_csv(_p("incidence_by_size.csv"))
    fig, ax = plt.subplots(figsize=(6.5, 4))
    ax.plot(d.sz, d.eff_rate_pct, "-o", color=ORANGE, lw=2)
    ax.set_xlabel("taker size decile (1 = smallest)"); ax.set_ylabel("effective fee rate (%)")
    ax.set_title("Smaller takers pay roughly 2× the whales"); ax.set_xticks(d.sz)
    fig.tight_layout(); plt.close(fig); return fig


def _lorenz(x):
    x = np.sort(np.asarray(x, float)); x = x[x >= 0]
    c = np.cumsum(x) / x.sum()
    return np.concatenate([[0], np.arange(1, len(x) + 1) / len(x)]), np.concatenate([[0], c])


def fig_rq2_concentration(prefix="rq2_v2"):
    """Lorenz curve of episode-wins — price correction is highly concentrated."""
    W = pd.read_parquet(_p(f"{prefix}_wallets.parquet"), columns=["ep_wins"])
    fx, fy = _lorenz(W.ep_wins)
    fig, ax = plt.subplots(figsize=(5, 5))
    ax.plot([0, 1], [0, 1], "--", color=GREY, lw=1, label="equal")
    ax.plot(fx, fy, "-", color=GREEN, lw=2, label="episode-wins")
    ax.set_xlabel("cumulative share of wallets"); ax.set_ylabel("cumulative share of corrections")
    ax.set_title("Price correction is concentrated in few wallets"); ax.legend(frameon=False)
    fig.tight_layout(); plt.close(fig); return fig


def fig_rq2_distinctness(prefix="rq2_v2"):
    """ep_wins vs dollar volume (log-log) — correctors are not the volume leaders."""
    W = pd.read_parquet(_p(f"{prefix}_wallets.parquet"), columns=["ep_wins", "vol"])
    d = W[(W.ep_wins > 0) & (W.vol > 0)]
    fig, ax = plt.subplots(figsize=(6, 4.5))
    ax.scatter(d.vol, d.ep_wins, s=8, alpha=0.25, color=BLUE, edgecolors="none")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("taker dollar volume (USDC, log)"); ax.set_ylabel("episodes closed (log)")
    ax.set_title("Correctors are distinct from volume leaders"); fig.tight_layout(); plt.close(fig); return fig


def fig_rq2_profitability(analysis: dict, prefix="rq2_v2"):
    """Correctors: positive gross PnL, but fees turn them net-negative."""
    pr = analysis["profitability"]
    cats = ["gross PnL", "fees", "net"]
    vals = [pr["correctors_gross_pnl"], -pr["correctors_fees"], pr["correctors_net"]]
    colors = [GREEN, RED, BLUE]
    fig, ax = plt.subplots(figsize=(5.5, 4))
    ax.bar(cats, [v / 1e6 for v in vals], color=colors)
    ax.axhline(0, color="k", lw=.8)
    for i, v in enumerate(vals):
        ax.text(i, v / 1e6 + (0.1 if v >= 0 else -0.1), f"${v/1e6:.1f}M", ha="center",
                va="bottom" if v >= 0 else "top", fontsize=9)
    ax.set_ylabel("USD (millions)"); ax.set_title("The fee taxes price correction into a net loss")
    fig.tight_layout(); plt.close(fig); return fig


def fig_rq2_persistence(prefix="rq2_v2"):
    """H1 vs H2 episode-wins per wallet — correction skill persists out-of-sample."""
    ev = pd.read_parquet(_p(f"{prefix}_events.parquet")).dropna(subset=["top_wid"])
    tmid = ev.start.median()
    h1 = ev[ev.start < tmid].groupby("top_wid").size().rename("w1")
    h2 = ev[ev.start >= tmid].groupby("top_wid").size().rename("w2")
    P = pd.concat([h1, h2], axis=1).fillna(0); b = P[(P.w1 > 0) & (P.w2 > 0)]
    fig, ax = plt.subplots(figsize=(5.2, 5))
    ax.scatter(b.w1, b.w2, s=10, alpha=0.3, color=GREEN, edgecolors="none")
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("episodes closed, first half"); ax.set_ylabel("episodes closed, second half")
    ax.set_title("Price-correction skill persists out-of-sample"); fig.tight_layout(); plt.close(fig); return fig


def fig_rq2_lp_economics():
    """Why correctors persist: their liquidity-provision income (rebate + spread capture) vs the
    taker fees they pay. LP income crosses the fee line between the 5- and 15-min markout horizon."""
    import json
    reb = json.loads((EXPORT / "rq2_v2_rebate_summary.json").read_text())
    mk = json.loads((EXPORT / "corrector_markout.json").read_text())
    fees = float(reb["taker_fees_musd"]); rebate = float(reb["rebate_musd"])
    mko = {c["horizon_s"]: c["total_dollar_markout"] / 1e6 for c in mk["curve"]}
    hz = [60, 300, 900]; labels = ["1 min", "5 min", "15 min"]
    x = np.arange(len(hz)); rb = [rebate] * len(hz); mv = [mko[h] for h in hz]
    fig, ax = plt.subplots(figsize=(6.6, 4.3))
    ax.bar(x, rb, color=ORANGE, label="maker rebate (modeled)")
    ax.bar(x, mv, bottom=rb, color=GREEN, label="maker markout (spread capture)")
    ax.axhline(fees, color=RED, ls="--", lw=1.6, label=f"taker fees paid (${fees:.0f}M)")
    for xi, (r, m) in enumerate(zip(rb, mv)):
        ax.text(xi, r + m + 1.5, f"${r + m:.0f}M", ha="center", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels([f"markout @ {l}" for l in labels])
    ax.set_ylabel("USD (millions)")
    ax.set_title("Correctors' LP income offsets their taker fees")
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    fig.tight_layout(); plt.close(fig); return fig


def fig_rq2_prepost(v1_analysis: dict, v2_analysis: dict):
    """Pre- vs post-fee: duration-invariant gross edge vs net margin (bps per $ of volume).
    V1 net margin is a lower bound (archive fee_usdc is overcounted; true pre-fee fees ≈ 0)."""
    p1, p2 = v1_analysis["profitability"], v2_analysis["profitability"]
    eras = ["V1 pre-fee", "V2 fee"]; x = np.arange(2); w = 0.38
    gross = [p1["gross_margin_bps"], p2["gross_margin_bps"]]
    net = [p1["net_margin_bps"], p2["net_margin_bps"]]
    fig, ax = plt.subplots(figsize=(6, 4.3))
    ax.bar(x - w / 2, gross, w, color=GREEN, label="gross edge")
    ax.bar(x + w / 2, net, w, color=BLUE, label="net of fees")
    ax.axhline(0, color="k", lw=.8)
    for xi, v in list(zip(x - w / 2, gross)) + list(zip(x + w / 2, net)):
        ax.text(xi, v + (3 if v >= 0 else -3), f"{v:+.0f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(eras); ax.set_ylabel("margin (bps per $ of volume)")
    ax.set_title("The fee flips price correction from profitable to loss-making")
    ax.legend(frameon=False); fig.tight_layout(); plt.close(fig); return fig

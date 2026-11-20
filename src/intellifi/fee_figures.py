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


# ---- episode-dynamics figures (scripts/51 outputs: data/export/episode_dynamics_{v1,v2}.json) ----
import json as _json  # noqa: E402


def _ed(era):
    return _json.loads((EXPORT / f"episode_dynamics_{era}.json").read_text())


def fig_correction_speed_by_volume():
    """Median correction time vs family volume (log-x), V1 vs V2 — liquidity governs speed, more
    sharply under the fee (V2 reaches ~15 s in the deepest markets)."""
    fig, ax = plt.subplots(figsize=(6.5, 4.3))
    for era, lab, c in [("v1", "V1 pre-fee", BLUE), ("v2", "V2 fee", ORANGE)]:
        dec = _ed(era)["duration_vs_volume"]["by_volume_decile"]
        d = pd.DataFrame(dec)
        ax.plot(d.med_vol, d.med_dur_min, "-o", color=c, lw=2, ms=4, label=lab)
    ax.set_xscale("log"); ax.set_xlabel("family taker volume (USDC, log)")
    ax.set_ylabel("median correction time (min)")
    ax.set_title("Thinner markets correct slower — steeper under the fee")
    ax.legend(frameon=False); fig.tight_layout(); plt.close(fig); return fig


def fig_unconverged_rate():
    """Un-converged rate by weighting — rare in dollars: count ~2-7% but volume-weighted ~0.3%."""
    eras = [("v1", "V1 pre-fee"), ("v2", "V2 fee")]; x = np.arange(2); w = 0.26
    keys = [("unconverged_rate_count", "by count", GREY),
            ("unconverged_rate_peak_weighted", "peak-weighted", ORANGE),
            ("unconverged_rate_volume_weighted", "volume-weighted", BLUE)]
    fig, ax = plt.subplots(figsize=(6.5, 4.3))
    for i, (k, lab, c) in enumerate(keys):
        vals = [100 * _ed(e)["volume_weighting"][k] for e, _ in eras]
        ax.bar(x + (i - 1) * w, vals, w, color=c, label=lab)
        for xi, v in zip(x + (i - 1) * w, vals):
            ax.text(xi, v + .05, f"{v:.2f}", ha="center", va="bottom", fontsize=7)
    ax.set_xticks(x); ax.set_xticklabels([e[1] for e in eras]); ax.set_ylabel("un-converged openings (%)")
    ax.set_title("Never-closed gaps are economically negligible"); ax.legend(frameon=False)
    fig.tight_layout(); plt.close(fig); return fig


def fig_concentration_count_vs_dollar():
    """Correction concentration: top-100 share of episode COUNT vs of corrective DOLLARS, V1 vs V2 —
    economic correction is an even smaller elite."""
    eras = [("v1", "V1 pre-fee"), ("v2", "V2 fee")]; x = np.arange(2); w = 0.38
    cnt = [_ed(e)["volume_weighting"]["concentration_count"]["top100_pct"] for e, _ in eras]
    dol = [_ed(e)["volume_weighting"]["concentration_dollar"]["top100_pct"] for e, _ in eras]
    fig, ax = plt.subplots(figsize=(6, 4.3))
    ax.bar(x - w / 2, cnt, w, color=GREY, label="top-100 share of episodes")
    ax.bar(x + w / 2, dol, w, color=GREEN, label="top-100 share of corrective $")
    for xi, v in list(zip(x - w / 2, cnt)) + list(zip(x + w / 2, dol)):
        ax.text(xi, v + .5, f"{v:.0f}%", ha="center", va="bottom", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels([e[1] for e in eras]); ax.set_ylabel("top-100 correctors' share (%)")
    ax.set_title("Dollar-weighted correction is far more concentrated"); ax.legend(frameon=False)
    fig.tight_layout(); plt.close(fig); return fig


def fig_density_by_category():
    """Episodes per active-family-day by category, V1 vs V2 — the correction-density gap is
    composition (weather/crypto heavy), not a uniform shift."""
    cats = ["sports", "weather", "politics", "crypto", "finance"]
    v1 = _ed("v1")["composition"]["by_category"]; v2 = _ed("v2")["composition"]["by_category"]
    x = np.arange(len(cats)); w = 0.38
    a = [v1.get(c, {}).get("episodes_per_active_family_day", 0) for c in cats]
    b = [v2.get(c, {}).get("episodes_per_active_family_day", 0) for c in cats]
    fig, ax = plt.subplots(figsize=(6.8, 4.3))
    ax.bar(x - w / 2, a, w, color=BLUE, label="V1 pre-fee")
    ax.bar(x + w / 2, b, w, color=ORANGE, label="V2 fee")
    ax.set_xticks(x); ax.set_xticklabels(cats); ax.set_ylabel("episodes per active-family-day")
    ax.set_title("Per-market correction intensity does not rise in V2 (within category)"); ax.legend(frameon=False)
    fig.tight_layout(); plt.close(fig); return fig


# =====================================================================================
# Framing + RQ1 (distribution) figures. Added so the WHOLE outline rebuilds from this
# module (scripts/54). Sources, all tracked:
#   - composition: data/export/category_composition.csv + composition_summary.json
#       (built by scripts/54 --composition from the negRisk fills; see that script).
#   - taker economics + profit-concentration Gini: the committed platform reports
#       docs/platform_wide.json (V1, scripts/27) and docs/v2_platform.json (V2, scripts/28).
#   - Lorenz + top-shares: data/export/rq2_{v1,v2}_wallets.parquet (scripts/47).
#   - rigorous skill: docs/skill_signflip.json (scripts/31) + docs/skill_signflip_v2.json (scripts/53).
# =====================================================================================
DOCS = _cfg.REPO_ROOT / "docs"
_COMP_CATS = ["sports", "weather", "politics", "crypto", "finance", "business"]


def _comp_df():
    return pd.read_csv(_p("category_composition.csv"))


def _comp_summary():
    return _json.loads((EXPORT / "composition_summary.json").read_text())


def fig_comp_markets_per_day():
    """negRisk markets created per day by category (log), V1 vs V2 — the proliferation is
    sports/weather, not uniform."""
    d = _comp_df(); d = d[d.cat.isin(_COMP_CATS)].copy()
    x = np.arange(len(d)); w = 0.38
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar(x - w / 2, d.V1_mkt_day.clip(lower=0.05), w, color=BLUE, label="V1 pre-fee")
    ax.bar(x + w / 2, d.V2_mkt_day.clip(lower=0.05), w, color=ORANGE, label="V2 fee")
    ax.set_yscale("log"); ax.set_xticks(x); ax.set_xticklabels(d.cat)
    ax.set_ylabel("markets created / day (log)")
    ax.set_title("The proliferation is sports (and weather), not uniform")
    ax.legend(frameon=False); fig.tight_layout(); plt.close(fig); return fig


def fig_comp_volume_by_category():
    """Taker volume by category (log), V1 vs V2 — the volume mix flips politics -> sports."""
    d = _comp_df(); d = d[d.cat.isin(_COMP_CATS)].copy()
    x = np.arange(len(d)); w = 0.38
    fig, ax = plt.subplots(figsize=(7, 4.2))
    ax.bar(x - w / 2, d.V1_vol_M.clip(lower=0.1), w, color=BLUE, label="V1 pre-fee")
    ax.bar(x + w / 2, d.V2_vol_M.clip(lower=0.1), w, color=ORANGE, label="V2 fee")
    ax.set_yscale("log"); ax.set_xticks(x); ax.set_xticklabels(d.cat)
    ax.set_ylabel("taker volume (\\$M, log)")
    ax.set_title("Volume mix flips: politics (V1) $\\rightarrow$ sports (V2)")
    ax.legend(frameon=False); fig.tight_layout(); plt.close(fig); return fig


def fig_comp_markets_per_user():
    """Distinct markets traded per user (mean vs median), V1 vs V2 — a bot tail churns markets
    while the typical user trades fewer."""
    s = _comp_summary(); w = 0.38
    v1 = [s["v1"]["mean_mkts_per_user"], s["v1"]["median_mkts_per_user"]]
    v2 = [s["v2"]["mean_mkts_per_user"], s["v2"]["median_mkts_per_user"]]
    x = np.arange(2)
    fig, ax = plt.subplots(figsize=(5.4, 4.2))
    ax.bar(x - w / 2, v1, w, color=BLUE, label="V1 pre-fee")
    ax.bar(x + w / 2, v2, w, color=ORANGE, label="V2 fee")
    for xi, v in zip(x - w / 2, v1):
        ax.text(xi, v + .2, f"{v:g}", ha="center", fontsize=9)
    for xi, v in zip(x + w / 2, v2):
        ax.text(xi, v + .2, f"{v:g}", ha="center", fontsize=9)
    ax.set_xticks(x); ax.set_xticklabels(["mean", "median"]); ax.set_ylabel("distinct markets traded / user")
    ax.set_title("A bot tail churns markets; the typical user trades fewer")
    ax.legend(frameon=False); fig.tight_layout(); plt.close(fig); return fig


def _platform_reports():
    v1 = _json.loads((DOCS / "platform_wide.json").read_text())
    v2 = _json.loads((DOCS / "v2_platform.json").read_text())
    return v1, v2


def fig_rq1_taker_economics():
    """Aggregate taker PnL, V1 vs V2 (platform-wide). V1 is ~fee-free so net==gross; V2 breaks out
    gross / fee / net. Numbers read from docs/platform_wide.json (scripts/27) and
    docs/v2_platform.json (scripts/28)."""
    v1, v2 = _platform_reports()
    v1net = v1["aggregate_taker_pnl"]["total_pnl_usdc"] / 1e6
    g = v2["aggregate_taker_pnl"]
    vals = [v1net, g["gross_pnl_usdc"] / 1e6, -g["total_taker_fee_usdc"] / 1e6, g["net_pnl_usdc"] / 1e6]
    labels = ["V1 net\n(fee-free)", "V2 gross", "V2 fee", "V2 net"]; cols = [BLUE, GREEN, RED, BLUE]
    fig, ax = plt.subplots(figsize=(6, 4.2))
    ax.bar(labels, vals, color=cols); ax.axhline(0, color="k", lw=.8)
    for i, v in enumerate(vals):
        ax.text(i, v + (4 if v >= 0 else -4), f"${v:.0f}M", ha="center", va="bottom" if v >= 0 else "top", fontsize=9)
    ax.set_ylabel("aggregate taker PnL (USD millions)")
    ax.set_title("The fee turns takers' break-even gross into a net loss")
    fig.tight_layout(); plt.close(fig); return fig


def fig_rq1_lorenz():
    """Lorenz curve of winning-wallet PnL, V1 vs V2 (negRisk universe) — more winner-take-all in V2.
    Source: data/export/rq2_{v1,v2}_wallets.parquet (pnl column)."""
    fig, ax = plt.subplots(figsize=(5.2, 5))
    ax.plot([0, 1], [0, 1], "--", color=GREY, lw=1, label="equality")
    for era, lab, c in [("v1", "V1 pre-fee", BLUE), ("v2", "V2 fee", ORANGE)]:
        w = pd.read_parquet(_p(f"rq2_{era}_wallets.parquet"), columns=["pnl"])
        fx, fy = _lorenz(w.pnl[w.pnl > 0].values); ax.plot(fx, fy, "-", color=c, lw=2, label=lab)
    ax.set_xlabel("cumulative share of winning wallets"); ax.set_ylabel("cumulative share of winnings")
    ax.set_title("Profit concentration (Lorenz): more winner-take-all in V2")
    ax.legend(frameon=False); fig.tight_layout(); plt.close(fig); return fig


def fig_rq1_profit_concentration():
    """Top-share of gains (top 0.1/1/5% of winners) + platform Gini, V1 vs V2. Shares computed from
    data/export/rq2_{v1,v2}_wallets.parquet; Gini from the committed platform reports
    (docs/platform_wide.json pnl_gini_positive; docs/v2_platform.json net_pnl_gini_positive)."""
    v1j, v2j = _platform_reports()
    gini = {"v1": v1j["pnl_gini_positive"], "v2": v2j["net_pnl_gini_positive"]}

    def shares(era):
        p = pd.read_parquet(_p(f"rq2_{era}_wallets.parquet"), columns=["pnl"]).pnl.values
        p = np.sort(p[p > 0])[::-1]; tot = p.sum()
        return [round(100 * p[:max(1, int(round(len(p) * q)))].sum() / tot, 1) for q in (0.001, 0.01, 0.05)]

    v1, v2 = shares("v1"), shares("v2"); x = np.arange(3); w = 0.38
    fig, ax = plt.subplots(figsize=(6, 4.2))
    ax.bar(x - w / 2, v1, w, color=BLUE, label=f"V1 (Gini {gini['v1']:.3f})")
    ax.bar(x + w / 2, v2, w, color=ORANGE, label=f"V2 (Gini {gini['v2']:.3f})")
    for xi, v in list(zip(x - w / 2, v1)) + list(zip(x + w / 2, v2)):
        ax.text(xi, v + .6, f"{v:.0f}", ha="center", fontsize=8)
    ax.set_xticks(x); ax.set_xticklabels(["top 0.1%", "top 1%", "top 5%"]); ax.set_ylabel("share of all gains (%)")
    ax.set_title("Profit concentration rose across the transition"); ax.legend(frameon=False)
    fig.tight_layout(); plt.close(fig); return fig


def fig_rq1_skill():
    """Rigorous forecasting skill (sign-flip permutation + split-half persistence), V1 vs V2.
    Panel A: population split (skilled / indistinguishable / worse) with the BH-certified share.
    Panel B: split-half persistence (top vs bottom H1 quintile -> mean H2 PnL) with Spearman rho.
    Sources: docs/skill_signflip.json (scripts/31), docs/skill_signflip_v2.json (scripts/53)."""
    v1 = _json.loads((DOCS / "skill_signflip.json").read_text())
    v2 = _json.loads((DOCS / "skill_signflip_v2.json").read_text())

    def unc(d):
        u = d["uncorrected"]; sk = u["frac_skilled"] * 100
        wo = u.get("frac_worse", u.get("frac_worse_than_chance")) * 100
        return sk, 100 - sk - wo, wo, d["fdr_bh_q0.05"]["frac"] * 100

    def pers(d):
        p = d["persistence"]
        return (p.get("spearman_rho", p.get("spearman_rho_p1_p2")),
                p.get("p1_top_quintile_mean_p2", p.get("p1_top_quintile_mean_p2_pnl")),
                p.get("p1_bottom_quintile_mean_p2", p.get("p1_bottom_quintile_mean_p2_pnl")))

    s1, i1, w1, bh1 = unc(v1); s2, i2, w2, bh2 = unc(v2)
    r1, t1, b1 = pers(v1); r2, t2, b2 = pers(v2)
    fig, (axA, axB) = plt.subplots(1, 2, figsize=(11, 4.4))
    x = np.arange(2)
    sk = [s1, s2]; ind = [i1, i2]; wo = [w1, w2]; bh = [bh1, bh2]
    axA.bar(x, sk, 0.55, color=GREEN, label="skilled (nominal, upper bound)")
    axA.bar(x, ind, 0.55, bottom=sk, color=GREY, label="indistinguishable")
    axA.bar(x, wo, 0.55, bottom=[s + i for s, i in zip(sk, ind)], color=RED, label="worse than chance")
    for xi, (s, wv, bv) in enumerate(zip(sk, wo, bh)):
        axA.text(xi, s / 2, f"{s:.1f}%", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
        axA.text(xi, 100 - wv / 2, f"{wv:.1f}%", ha="center", va="center", color="white", fontsize=9, fontweight="bold")
        axA.text(xi, s + 3.0, f"BH-certified: {bv:.1f}%", ha="center", va="bottom", fontsize=8, color=GREEN, fontweight="bold")
    axA.set_xticks(x); axA.set_xticklabels(["V1\n(pre-fee)", "V2\n(fee)"])
    axA.set_ylabel("share of classifiable wallets (%)"); axA.set_ylim(0, 108)
    axA.set_title("A thin skilled minority — comparable in both eras", fontsize=10.5)
    axA.legend(frameon=False, fontsize=8, loc="upper center", ncol=1, bbox_to_anchor=(0.5, -0.12))
    axA.grid(axis="x", visible=False)
    w = 0.36
    axB.bar(x - w / 2, [t1, t2], w, color=BLUE, label="top-quintile (H1) $\\rightarrow$ mean H2 PnL")
    axB.bar(x + w / 2, [b1, b2], w, color=ORANGE, label="bottom-quintile (H1) $\\rightarrow$ mean H2 PnL")
    for xi, v in zip(x - w / 2, [t1, t2]):
        axB.text(xi, v + 25, f"+${v:,.0f}", ha="center", va="bottom", fontsize=8.5, color=BLUE, fontweight="bold")
    for xi, v in zip(x + w / 2, [b1, b2]):
        axB.text(xi, v - 25, f"−${abs(v):,.0f}", ha="center", va="top", fontsize=8.5, color=ORANGE, fontweight="bold")
    axB.axhline(0, color=GREY, lw=1)
    axB.set_xticks(x); axB.set_xticklabels([f"V1\n$\\rho$ = {r1:.2f}", f"V2\n$\\rho$ = {r2:.2f}"])
    axB.set_ylabel("mean second-half realized PnL ($)")
    axB.set_title("Skill persists out-of-sample in both eras", fontsize=10.5)
    axB.legend(frameon=False, fontsize=8, loc="upper center", ncol=1, bbox_to_anchor=(0.5, -0.12))
    axB.grid(axis="x", visible=False)
    axB.set_ylim(min(b1, b2) * 1.35, max(t1, t2) * 1.25)
    fig.suptitle("Rigorous forecasting skill (sign-flip permutation + split-half persistence), V1 vs V2",
                 fontsize=11, y=1.02)
    fig.tight_layout(); plt.close(fig); return fig

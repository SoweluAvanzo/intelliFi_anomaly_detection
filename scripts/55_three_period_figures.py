#!/usr/bin/env python
"""Three-period (P1 fee-free / P2 fee tail / P3=V2 fee) negRisk figures for the results outline.
Reads the method-matched period outputs (rq2_{p1,p2,v2}_wallets.parquet, episode_dynamics_{p1,p2,v2}.json,
platform_{p1,p2}_negrisk.json + v2_platform.json) and writes clean PNGs to a NEW folder
docs/paper/v1v2_results_outline/figures_3p/ (the two-period figures/ are left untouched).

Design: Wong colorblind-safe palette, honest axes, thin marks, legend + selective direct labels,
recessive grid, one y-axis per chart. P2 NET is hatched (archive fee is unusable; shown for completeness).
"""
from __future__ import annotations
import json, os, sys
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[1]
EXP = REPO / "data" / "export"
DOCS = REPO / "docs"
OUT = REPO / "docs" / "paper" / "v1v2_results_outline" / "figures_3p"
OUT.mkdir(parents=True, exist_ok=True)
sys.path.insert(0, str(REPO / "src"))
import duckdb

# Wong palette (matches src/intellifi/fee_figures.py); P1/P2/P3 fixed order
BLUE, GREEN, ORANGE, GREY, RED = "#0072B2", "#009E73", "#E69F00", "#8C8C8C", "#D55E00"
PCOL = {"p1": BLUE, "p2": GREEN, "v2": ORANGE}
PNAME = {"p1": "P1 (fee-free)", "p2": "P2 (fee tail)", "v2": "P3 = V2 (fee)"}
INK, MUTE = "#222222", "#666666"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#cccccc", "axes.linewidth": 0.8,
                     "axes.grid": True, "grid.color": "#e8e8e8", "grid.linewidth": 0.7,
                     "axes.axisbelow": True, "xtick.color": MUTE, "ytick.color": MUTE,
                     "axes.labelcolor": INK, "text.color": INK, "figure.dpi": 150})

def _style(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)

def gini_pos(x):
    x = np.sort(x[x > 0]); n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())) if n else float("nan")

con = duckdb.connect(); con.execute("PRAGMA memory_limit='3GB'")

def wallet_pnl(tag):
    p = EXP / f"rq2_{tag}_wallets.parquet"
    if not p.exists(): return None, None
    df = con.execute(f"SELECT CAST(pnl AS DOUBLE) pnl, COALESCE(CAST(fee_paid AS DOUBLE),0) fee FROM '{p.as_posix()}'").df()
    return df.pnl.values, df.fee.values

# ---------- Fig 1: Lorenz of winning-wallet profit (RQ1 concentration) ----------
def fig_lorenz():
    fig, ax = plt.subplots(figsize=(5.4, 4.2))
    ax.plot([0, 1], [0, 1], color="#bbbbbb", lw=1, ls=(0, (4, 3)), label="equality")
    for tag in ("p1", "p2", "v2"):
        pnl, _ = wallet_pnl(tag)
        if pnl is None: continue
        w = np.sort(pnl[pnl > 0])
        cx = np.arange(1, len(w) + 1) / len(w)
        cy = np.cumsum(w) / w.sum()
        g = gini_pos(pnl)
        ax.plot(cx, cy, color=PCOL[tag], lw=2, label=f"{PNAME[tag]}  (Gini {g:.3f})")
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("cumulative share of winning wallets (poorest → richest)")
    ax.set_ylabel("cumulative share of total profit")
    ax.set_title("Profit was already near-maximally concentrated before the fee", fontsize=10.5, loc="left", color=INK)
    ax.legend(loc="upper left", frameon=False, fontsize=8.5)
    _style(ax); fig.tight_layout(); fig.savefig(OUT / "fig1_lorenz_3p.png", bbox_inches="tight"); plt.close(fig)

# ---------- Fig 2: gross vs net taker PnL hinge (RQ1 fee) ----------
def fig_pnl_hinge():
    # from the distribution outputs; P2 net uses the UNUSABLE archive fee -> hatch it
    _p2jp = REPO / "docs" / "p2_net_formula.json"
    _p2f = json.load(open(_p2jp)) if _p2jp.exists() else None
    data = {}
    for tag in ("p1", "p2", "v2"):
        pnl, fee = wallet_pnl(tag)
        if pnl is None: continue
        if tag == "p2" and _p2f:
            data[tag] = (pnl.sum() / 1e6, _p2f["baseline"]["net_pnl"] / 1e6)  # net = formula (modeled)
        else:
            data[tag] = (pnl.sum() / 1e6, (pnl.sum() - fee.sum()) / 1e6)  # gross, net ($M)
    fig, ax = plt.subplots(figsize=(5.6, 4.0))
    x = np.arange(len(data)); wq = 0.38
    tags = list(data)
    gross = [data[t][0] for t in tags]; net = [data[t][1] for t in tags]
    b1 = ax.bar(x - wq/2, gross, wq, color=[PCOL[t] for t in tags], label="gross (before fee)", alpha=0.55)
    b2 = ax.bar(x + wq/2, net, wq, color=[PCOL[t] for t in tags], label="net (after fee)")
    # hatch P2 net (unreliable fee)
    for i, t in enumerate(tags):
        if t == "p2":
            b2[i].set_hatch("////"); b2[i].set_edgecolor("white")
    ax.axhline(0, color="#999999", lw=0.8)
    for i, t in enumerate(tags):
        ax.text(x[i]-wq/2, gross[i] - (1.5 if gross[i] < 0 else -1.5), f"{gross[i]:+.0f}", ha="center",
                va="top" if gross[i] < 0 else "bottom", fontsize=8, color=MUTE)
        ax.text(x[i]+wq/2, net[i] - (1.5 if net[i] < 0 else -1.5), f"{net[i]:+.0f}", ha="center",
                va="top" if net[i] < 0 else "bottom", fontsize=8, color=INK)
    ax.set_xticks(x); ax.set_xticklabels([PNAME[t] for t in tags], fontsize=9)
    ax.set_ylabel("aggregate taker PnL ($M)")
    ax.set_title("The fee, not gross trading, drives V2 takers' net loss", fontsize=10.5, loc="left", color=INK)
    ax.legend(loc="lower left", frameon=False, fontsize=8.5)
    ax.text(0.99, 0.02, "P2 net hatched: modeled by formula", transform=ax.transAxes, ha="right",
            va="bottom", fontsize=7.5, color=MUTE, style="italic")
    _style(ax); fig.tight_layout(); fig.savefig(OUT / "fig2_pnl_hinge_3p.png", bbox_inches="tight"); plt.close(fig)

# ---------- Fig 3: calibration gap by category across periods (RQ2) ----------
def fig_calibration():
    srcs = {"p1": DOCS/"platform_p1_negrisk.json", "p2": DOCS/"platform_p2_negrisk.json", "v2": DOCS/"v2_platform.json"}
    cal = {}
    for tag, p in srcs.items():
        if p.exists():
            cal[tag] = {r["cls"]: r.get("calibration_gap") for r in json.load(open(p)).get("per_category", [])}
    # material-volume categories only (exclude thin crypto_other/esports; note separately)
    drop = {"crypto_other", "esports_tennis", "meta_other", "other"}
    cats = [c for c in sorted({c for d in cal.values() for c in d}) if c not in drop]
    fig, ax = plt.subplots(figsize=(5.8, 4.4))
    y = np.arange(len(cats))
    ax.axvspan(-0.5, 0.5, color="#f3f3f3", zorder=0)  # +-0.5pp band
    ax.axvline(0, color="#aaaaaa", lw=0.9)
    for tag in ("p1", "p2", "v2"):
        if tag not in cal: continue
        xs = [100*cal[tag].get(c) if cal[tag].get(c) is not None else np.nan for c in cats]
        ax.scatter(xs, y, s=34, color=PCOL[tag], label=PNAME[tag], zorder=3, edgecolor="white", linewidth=0.5)
    ax.set_yticks(y); ax.set_yticklabels(cats, fontsize=8.5)
    ax.set_xlabel("calibration gap (pp):  hit rate − entry-implied probability")
    ax.set_xlim(-1.1, 1.1)
    ax.set_title("Forecast accuracy is near-perfect in every period and category", fontsize=10.5, loc="left", color=INK)
    ax.legend(loc="lower right", frameon=False, fontsize=8.5)
    ax.text(0.5, -0.5, "±0.5pp band", fontsize=7, color=MUTE, va="center")
    _style(ax); ax.grid(axis="y", visible=False); fig.tight_layout()
    fig.savefig(OUT / "fig3_calibration_3p.png", bbox_inches="tight"); plt.close(fig)

# ---------- Fig 4: liquidity -> correction-speed gradient (RQ3) ----------
def fig_gradient():
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    for tag in ("p1", "p2", "v2"):
        p = EXP / f"episode_dynamics_{tag}.json"
        if not p.exists(): continue
        r = json.load(open(p))
        dec = (r.get("duration_vs_volume") or {}).get("by_volume_decile") or []
        beta = ((r.get("duration_vs_volume") or {}).get("overall") or {}).get("beta_logvol")
        if not dec: continue
        xs = [d["med_vol"] for d in dec]; ys = [d["med_dur_min"] for d in dec]
        ax.plot(xs, ys, color=PCOL[tag], lw=2, marker="o", ms=4,
                label=f"{PNAME[tag]}  (β={beta})" if beta is not None else PNAME[tag])
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("family taker volume ($, log)")
    ax.set_ylabel("median correction time (min, log)")
    ax.set_title("Correction accelerates with liquidity — the gradient steepens P1→P2→V2",
                 fontsize=10.2, loc="left", color=INK)
    ax.legend(loc="upper right", frameon=False, fontsize=8.5)
    _style(ax); fig.tight_layout(); fig.savefig(OUT / "fig4_gradient_3p.png", bbox_inches="tight"); plt.close(fig)

# ---------- Fig 5: corrector mechanism invariance (RQ3) ----------
def fig_corrector():
    metrics = [("corrector Gini\n(count)", lambda r: (r.get("concentration_full") or {}).get("gini")),
               ("corrector Gini\n($)", lambda r: ((r.get("volume_weighting") or {}).get("concentration_dollar") or {}).get("gini")),
               ("persistence\n(Spearman)", lambda r: (r.get("persistence_full") or {}).get("spearman_h1_h2"))]
    reps = {}
    for tag in ("p1", "p2", "v2"):
        p = EXP / f"episode_dynamics_{tag}.json"
        if p.exists(): reps[tag] = json.load(open(p))
    fig, ax = plt.subplots(figsize=(5.8, 4.0))
    x = np.arange(len(metrics)); wq = 0.26; tags = [t for t in ("p1","p2","v2") if t in reps]
    for i, tag in enumerate(tags):
        vals = [m[1](reps[tag]) for m in metrics]
        bars = ax.bar(x + (i - (len(tags)-1)/2)*wq, vals, wq, color=PCOL[tag], label=PNAME[tag])
        for b, v in zip(bars, vals):
            if v is not None:
                ax.text(b.get_x()+b.get_width()/2, v+0.012, f"{v:.2f}", ha="center", va="bottom", fontsize=7.5, color=MUTE)
    ax.set_xticks(x); ax.set_xticklabels([m[0] for m in metrics], fontsize=8.5)
    ax.set_ylim(0, 1.0); ax.set_ylabel("coefficient (0–1)")
    ax.set_title("Who corrects, and how, is invariant across the three periods", fontsize=10.5, loc="left", color=INK, pad=26)
    ax.legend(loc="lower center", ncol=3, frameon=False, fontsize=8.5, bbox_to_anchor=(0.5, 1.01))
    _style(ax); ax.grid(axis="x", visible=False); fig.tight_layout()
    fig.savefig(OUT / "fig5_corrector_3p.png", bbox_inches="tight"); plt.close(fig)

if __name__ == "__main__":
    fig_lorenz(); fig_pnl_hinge(); fig_calibration(); fig_gradient(); fig_corrector()
    print("wrote 3-period figures to", OUT)
    for f in sorted(OUT.glob("*.png")):
        print("  ", f.name, f"{f.stat().st_size//1024}KB")

#!/usr/bin/env python
"""Trader-level fee-incidence figures (the paper's primary contribution).

Reads ONLY docs/fee_incidence_platform.json (produced by scripts/49_fee_incidence.py; both scopes +
concentration + 500-pt Lorenz). No hardcoded series, no scratchpad intermediates. Writes PNGs to
docs/paper/v1v2_results_outline/figures_incidence/ (new folder; existing figures untouched)."""
from __future__ import annotations
import json
from pathlib import Path
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "docs/paper/v1v2_results_outline/figures_incidence"
OUT.mkdir(parents=True, exist_ok=True)
D = json.load(open(REPO / "docs/fee_incidence_platform.json"))
PLAT, NEG = D["platform"], D["negrisk"]
BLUE, ORANGE, GREEN, GREY, RED = "#0072B2", "#E69F00", "#009E73", "#8C8C8C", "#D55E00"
INK, MUTE = "#222222", "#666666"
plt.rcParams.update({"font.size": 10, "axes.edgecolor": "#cccccc", "axes.linewidth": 0.8,
                     "axes.grid": True, "grid.color": "#e8e8e8", "grid.linewidth": 0.7, "axes.axisbelow": True,
                     "xtick.color": MUTE, "ytick.color": MUTE, "axes.labelcolor": INK, "text.color": INK, "figure.dpi": 150})
def _style(ax):
    for s in ("top", "right"): ax.spines[s].set_visible(False)

vd = [d["sz"] for d in PLAT["by_size"]]
eff = [d["eff_rate_pct"] for d in PLAT["by_size"]]
medp = [d["med_price"] for d in PLAT["by_size"]]
NR_EFF = [d["eff_rate_pct"] for d in NEG["by_size"]]
TOP1 = float(PLAT["concentration"]["top1pct_fee_share"])

def fig_regressivity():
    fig, ax = plt.subplots(figsize=(5.8, 4.2))
    ax.plot(vd, eff, color=BLUE, lw=2.2, marker="o", ms=5, label="all V2 markets")
    ax.plot(vd, NR_EFF, color=ORANGE, lw=1.8, ls=(0, (4, 3)), marker="s", ms=4, label="negRisk only")
    ax.annotate(f"{eff[0]:.2f}%", (vd[0], eff[0]), textcoords="offset points", xytext=(6, 6), fontsize=9, color=BLUE)
    ax.annotate(f"{eff[-1]:.2f}%", (vd[-1], eff[-1]), textcoords="offset points", xytext=(-4, -14), fontsize=9, color=BLUE)
    ax.set_xticks(vd); ax.set_xlabel("trader total-volume decile  (1 = smallest, 10 = largest)")
    ax.set_ylabel("effective fee rate paid (% of notional)"); ax.set_ylim(0, max(NR_EFF) * 1.12)
    ax.set_title("The fee is regressive across traders: the smallest pay about twice the rate of the largest",
                 fontsize=9.6, loc="left", color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper right")
    _style(ax); fig.tight_layout(); fig.savefig(OUT / "fig_incidence_regressivity.png", bbox_inches="tight"); plt.close(fig)

def fig_mechanism():
    x = [1 - p for p in medp]
    slope = float(np.polyfit(x, eff, 1)[0])
    fig, ax = plt.subplots(figsize=(5.6, 4.3))
    xs = np.linspace(0, max(x) * 1.05, 50)
    ax.plot(xs, slope * xs, color=GREY, lw=1.3, ls=(0, (4, 3)),
            label="incidence $\\approx$ feeRate$\\,(1-p)$, slope " + f"{slope:.3f}")
    sc = ax.scatter(x, eff, c=vd, cmap="viridis", s=60, zorder=3, edgecolor="white", linewidth=0.6)
    ax.annotate("smallest traders\n(cheaper outcomes)", (x[0], eff[0]), textcoords="offset points", xytext=(-10, -30), ha="right", fontsize=8, color=MUTE)
    ax.annotate("largest traders\n(favourites, high $p$)", (x[-1], eff[-1]), textcoords="offset points", xytext=(16, -20), fontsize=8, color=MUTE)
    cb = fig.colorbar(sc, ax=ax, label="volume decile"); cb.ax.tick_params(labelsize=7)
    ax.set_xlabel("$1-$ (median price traded)   =  the longshot-ness of a trader's book")
    ax.set_ylabel("effective fee rate (% of notional)")
    ax.set_title("The regressivity is price-driven: incidence peaks on cheap outcomes", fontsize=9.8, loc="left", color=INK)
    ax.legend(frameon=False, fontsize=8, loc="upper left")
    _style(ax); fig.tight_layout(); fig.savefig(OUT / "fig_incidence_mechanism.png", bbox_inches="tight"); plt.close(fig)

def fig_concentration():
    lx = [p["x"] for p in PLAT["lorenz"]]; ly = [p["y"] for p in PLAT["lorenz"]]
    fig, ax = plt.subplots(figsize=(5.6, 4.2))
    ax.plot([0, 1], [0, 1], color="#bbbbbb", lw=1, ls=(0, (4, 3)), label="equality")
    ax.plot([0] + lx, [0] + ly, color=RED, lw=2.2, label="fees paid")
    ax.axvline(0.99, color=GREY, lw=0.8, ls=":")
    ax.annotate(f"top 1% of payers\npay {TOP1:.0f}% of fees", (0.99, 1 - TOP1 / 100), textcoords="offset points",
                xytext=(-120, 6), fontsize=8.5, color=INK, arrowprops=dict(arrowstyle="->", color=MUTE, lw=0.8))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1)
    ax.set_xlabel("cumulative share of fee-paying traders (smallest → largest fee)")
    ax.set_ylabel("cumulative share of all fees paid")
    ax.set_title("The fee burden is extremely concentrated: the whales pay the dollars", fontsize=9.8, loc="left", color=INK)
    ax.legend(frameon=False, fontsize=8.5, loc="upper left")
    _style(ax); fig.tight_layout(); fig.savefig(OUT / "fig_incidence_concentration.png", bbox_inches="tight"); plt.close(fig)

if __name__ == "__main__":
    fig_regressivity(); fig_mechanism(); fig_concentration()
    print("wrote incidence figures to", OUT)
    for p in sorted(OUT.glob("*.png")): print("  ", p.name, f"{p.stat().st_size//1024}KB")

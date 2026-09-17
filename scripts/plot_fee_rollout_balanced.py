#!/usr/bin/env python
"""Balanced-panel event-study figure for the fee rollout — the participation NULL, made visual.

Reads docs/fee_rollout_did.json (event_study_balanced) and draws a two-panel event study around
each category's own fee-start, on the balanced (constant-composition) panel:
  top    — mean taker order size ($), with the fee-free PRE-TREND fit and extended as a dashed line;
  bottom — new wallets per category.
A vertical rule marks fee onset (e=0); the effective fee% is annotated on the top panel. The
observed points straddle the extended pre-trend and entry does not fall at onset -> no participation
response is identified. Two stacked panels (never a dual axis).

  python scripts/plot_fee_rollout_balanced.py     # -> docs/fig_fee_rollout_balanced.{pdf,png}
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def _ols(xs, ys):
    """OLS slope, intercept for y = a + b*x."""
    n = len(xs)
    if n < 2:
        return None, None
    sx, sy = sum(xs), sum(ys)
    sxx = sum(x * x for x in xs)
    sxy = sum(x * y for x, y in zip(xs, ys))
    den = n * sxx - sx * sx
    if not den:
        return None, None
    b = (n * sxy - sx * sy) / den
    a = (sy - b * sx) / n
    return a, b


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--json", default="docs/fee_rollout_did.json")
    ap.add_argument("--out", default="docs/fig_fee_rollout_balanced")
    ap.add_argument("--fee-free-thresh", type=float, default=0.2, help="fee%% below this = pre-treatment")
    args = ap.parse_args()

    d = json.loads(Path(args.json).read_text())
    b = d["event_study_balanced"]
    rows = sorted(b["by_event_month"], key=lambda r: r["event_month"])
    e = [r["event_month"] for r in rows]
    order = [r["mean_med_order"] for r in rows]
    entry = [r["mean_new_wallets_per_cat"] for r in rows]
    fee = [r["mean_fee_pct"] for r in rows]

    # pre-trend = the reported fee-free slopes (pretrend_diagnostic), extended from the eve of
    # treatment (last fee-free month) forward — the standard "extend the pre-trend" counterfactual.
    pt = d.get("pretrend_diagnostic", {})
    oslope = pt.get("med_order_slope_per_month")
    eslope = pt.get("mean_new_wallets_per_cat_slope_per_month")
    e0 = max(ee for ee, ff in zip(e, fee) if ff < args.fee_free_thresh)
    i0 = e.index(e0)
    xline = [e0, max(e)]

    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter

    plt.rcParams.update({
        "font.size": 9, "font.family": "DejaVu Serif",
        "axes.spines.top": False, "axes.spines.right": False,
        "axes.grid": True, "grid.color": "#ebebeb", "grid.linewidth": 0.6, "axes.axisbelow": True,
    })
    INK, ACCENT, REF, ONSET = "#1b1b1b", "#2d6a9f", "#8a929c", "#c0563a"
    xs = [min(e), max(e)]

    fig, (ax1, ax2) = plt.subplots(
        2, 1, figsize=(5.3, 4.7), sharex=True, gridspec_kw={"height_ratios": [1, 0.82], "hspace": 0.16})

    # --- top: order size ---
    if oslope is not None:
        ax1.plot(xline, [order[i0] + oslope * (x - e0) for x in xline], ls=(0, (5, 3)), lw=1.5,
                 color=REF, zorder=1, label=f"pre-trend extended ({oslope:+.2f} \\$/mo)")
    ax1.plot(e, order, "-o", lw=1.9, ms=6, color=ACCENT, zorder=3, label="observed (balanced panel)")
    ax1.axvline(0, color=ONSET, lw=1.1, ls=":", zorder=0)
    ax1.set_ylabel("mean order size (\\$)", color=INK)
    ax1.set_ylim(0, max(order) * 1.22)
    for ee, oo, ff in zip(e, order, fee):
        ax1.annotate(f"{ff:.1f}%", (ee, oo), textcoords="offset points", xytext=(0, 9),
                     ha="center", fontsize=7, color="#666")
    ax1.annotate("fee onset", (0, ax1.get_ylim()[1] * 0.965), ha="center", va="top",
                 fontsize=7.5, color=ONSET)
    ax1.legend(loc="lower left", frameon=False, fontsize=7.4)

    # --- bottom: entry ---
    if eslope is not None:
        ax2.plot(xline, [entry[i0] + eslope * (x - e0) for x in xline], ls=(0, (5, 3)), lw=1.5,
                 color=REF, zorder=1, label=f"pre-trend extended ({eslope:+,.0f}/mo)")
    ax2.plot(e, entry, "-s", lw=1.9, ms=6, color=ACCENT, zorder=3, label="observed")
    ax2.axvline(0, color=ONSET, lw=1.1, ls=":", zorder=0)
    ax2.set_ylabel("new wallets / category", color=INK)
    ax2.set_ylim(0, max(entry) * 1.22)
    ax2.set_xlabel("months relative to each category's fee-start")
    ax2.set_xticks(e)
    ax2.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v/1000:.0f}k"))
    ax2.legend(loc="lower left", frameon=False, fontsize=7.4)

    fig.suptitle("Balanced-panel event study: no participation response to the fee",
                 x=0.015, ha="left", fontsize=10.5, fontweight="bold", color=INK)
    fig.text(0.015, 0.005,
             f"{b['n_categories']} categories present at every month of the {b['window']} window "
             "(constant composition). Order size stays on its pre-fee trend; entry does not fall at "
             "onset. Labels on the top panel are the effective fee %.",
             fontsize=6.6, color="#666")

    fig.tight_layout(rect=[0, 0.035, 1, 0.945])
    for ext in ("pdf", "png"):
        fig.savefig(f"{args.out}.{ext}", dpi=200, bbox_inches="tight")
    print(f"wrote {args.out}.pdf and {args.out}.png")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

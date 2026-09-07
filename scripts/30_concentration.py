#!/usr/bin/env python
"""Profit-concentration profile of the v1 archive — how unequal are realised
trading profits, on BOTH sides of the book (takers and makers).

Motivating RQ (docs/results_summary_2026-09-05.md, "Result 2"): winnings are
hyper-concentrated (Gini ~0.95) while a separate test finds NO certifiable skilled
cohort. This script quantifies the concentration rigorously so the two can be read
together (concentration without demonstrable skill => scale/variance/survivorship,
not an edge).

For each side it reports, over per-wallet realised gross PnL:
  * n wallets / winners / losers, total gross PnL
  * Gini of positive PnL (concentration among winners)
  * share of total winnings captured by the top 0.1% / 1% / 10% of winners, and by
    the top 100 / 1,000 wallets
  * how few wallets capture 50% / 90% of all winnings (Lorenz inversion)
  * per-category Gini + top-1% share (taker side)

Realised RAW per-fill PnL (uncovered sells not scaled), outcome-dependent
(survivorship) — descriptive, not skill. v1 ~fee-free so gross ~= net.

  python scripts/30_concentration.py --out docs/concentration.json --memory-limit 9GB
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                              # noqa: E402
from intellifi.archive import register_archive_views      # noqa: E402
from intellifi import config as _cfg                       # noqa: E402


def concentration(pnl: np.ndarray) -> dict:
    """Concentration stats over a per-wallet gross-PnL vector."""
    pos = np.sort(pnl[pnl > 0])[::-1]          # winners, descending
    n_win = len(pos)
    tot = float(pos.sum())
    out: dict = {"n_wallets": int(len(pnl)), "n_winners": n_win, "n_losers": int((pnl < 0).sum()),
                 "total_gross_pnl": float(pnl.sum()), "total_winnings": tot}
    if n_win == 0 or tot == 0:
        return out
    asc = pos[::-1]
    out["gini_positive"] = float((2 * np.arange(1, n_win + 1) - n_win - 1).dot(asc) / (n_win * asc.sum()))
    csum = np.cumsum(pos)
    def top_share(k):
        m = max(1, int(np.ceil(k * n_win)))
        return {"n": m, "frac_of_winners": m / n_win, "share_of_winnings": float(csum[m - 1] / tot)}
    out["top_0.1pct_of_winners"] = top_share(0.001)
    out["top_1pct_of_winners"] = top_share(0.01)
    out["top_10pct_of_winners"] = top_share(0.10)
    for k in (100, 1000):
        if n_win >= k:
            out[f"top_{k}_wallets"] = {"share_of_winnings": float(csum[k - 1] / tot)}
    # how few wallets capture 50% / 90% of all winnings
    for q in (0.5, 0.9, 0.99):
        idx = int(np.searchsorted(csum, q * tot)) + 1
        out[f"wallets_for_{int(q*100)}pct_of_winnings"] = {"n": idx, "frac_of_winners": idx / n_win,
                                                           "frac_of_all_wallets": idx / len(pnl)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/concentration.json")
    ap.add_argument("--memory-limit", default="9GB")
    args = ap.parse_args()

    tmp = _cfg.DATA_DIR / "_s30_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='60GB'")
    register_archive_views(con)

    RESOLVED = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
                "AND taker_direction IN ('BUY','SELL')")
    WON = "(CASE WHEN outcome_label = winning_outcome_label THEN 1 ELSE 0 END)"
    # taker per-fill PnL; maker per-fill PnL = the negative of it
    PNL_T = f"(CASE WHEN taker_direction='BUY' THEN ({WON}-price)*shares ELSE (price-{WON})*shares END)"

    rep: dict = {"scope": "whole v1 archive; realised gross per-fill PnL; outcome-dependent (descriptive)",
                 "note": "read WITH the no-skill null in skilled_population.json: concentration despite no "
                         "certifiable skill => scale/variance/survivorship, not an edge."}

    # per-wallet PnL, both sides (memory-safe group-bys over arc_raw)
    con.execute(f"CREATE TABLE wt AS SELECT taker AS w, SUM({PNL_T}) pnl FROM arc_raw WHERE {RESOLVED} GROUP BY taker")
    con.execute(f"CREATE TABLE wm AS SELECT maker AS w, SUM(-({PNL_T})) pnl FROM arc_raw WHERE {RESOLVED} GROUP BY maker")
    rep["taker_side"] = concentration(con.sql("SELECT pnl FROM wt").fetchnumpy()["pnl"].astype(float))
    rep["maker_side"] = concentration(con.sql("SELECT pnl FROM wm").fetchnumpy()["pnl"].astype(float))

    # per-category concentration (taker side) — ONE pass: (category, taker) -> pnl, group in Python
    import collections
    rep["per_category_taker"] = []
    con.execute(f"CREATE TABLE wtc AS SELECT COALESCE(category,'(none)') category, taker AS w, "
                f"SUM({PNL_T}) pnl FROM arc_raw WHERE {RESOLVED} GROUP BY 1, taker")
    rows = con.sql("SELECT category, pnl FROM wtc").fetchall()
    bycat: dict = collections.defaultdict(list)
    for cat, pnl in rows:
        bycat[cat].append(pnl)
    for cat, arr in sorted(bycat.items(), key=lambda kv: -len(kv[1]))[:12]:
        c = concentration(np.asarray(arr, dtype=float))
        rep["per_category_taker"].append({"category": cat, "n_wallets": c.get("n_wallets"),
            "gini_positive": c.get("gini_positive"), "total_gross_pnl": c.get("total_gross_pnl"),
            "top_1pct_share": c.get("top_1pct_of_winners", {}).get("share_of_winnings")})

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    for side in ("taker_side", "maker_side"):
        s = rep[side]
        print(f"\n=== {side} ===")
        print(f"  wallets={s['n_wallets']:,}  winners={s['n_winners']:,}  losers={s['n_losers']:,}  "
              f"total_gross={s['total_gross_pnl']:,.0f}")
        if "gini_positive" in s:
            print(f"  Gini(+PnL)={s['gini_positive']:.3f}")
            print(f"  top 1% of winners capture {s['top_1pct_of_winners']['share_of_winnings']*100:.1f}% of winnings "
                  f"(that's {s['top_1pct_of_winners']['n']:,} wallets)")
            print(f"  top 0.1% capture {s['top_0.1pct_of_winners']['share_of_winnings']*100:.1f}%; "
                  f"top 100 wallets capture {s.get('top_100_wallets',{}).get('share_of_winnings',float('nan'))*100:.1f}%")
            w90 = s['wallets_for_90pct_of_winnings']
            print(f"  {w90['n']:,} wallets ({w90['frac_of_all_wallets']*100:.2f}% of all) capture 90% of winnings")
    print("\nper-category (taker) Gini / top-1% share:")
    for r in rep["per_category_taker"]:
        g = r.get("gini_positive")
        print(f"  {str(r['category']):16s} Gini={g:.3f} top1%={100*(r['top_1pct_share'] or 0):.1f}%" if g else f"  {r['category']}: n/a")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

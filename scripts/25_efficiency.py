#!/usr/bin/env python
"""Stage B — market efficiency: how the eventually-winning outcome's implied
probability converges to 1 as a function of time before close, BY CATEGORY.

This is the dynamic (time-resolved) counterpart to Stage A's static calibration.
For every resolved market we build the winning outcome's minute-VWAP price path
from the tape, then read the winner price at a series of horizons before
`closed_time` (30d, 14d, 7d, 3d, 24h, 12h, 6h, 3h, 1h). The convergence error
`1 - winner_price` at each horizon says how early the market "knew" the answer:
a market efficient at incorporating information prices the winner high days out;
one that only resolves in the final hours (a jump near an event) converges late,
which is exactly the signature to inspect for insider/event-driven moves.

Source-agnostic and robust: the winner price is taken from `trades.price` where
`outcome_index = winning_outcome_index` (the raw market price of the winning
token — buyers and sellers transact at the same price), so it needs no
derived-token-id join. Use INTELLIFI_SOURCE=archive for the complete tape.

Outputs an overall convergence curve, a per-category curve with the earliest
horizon each category prices the winner below 0.25 and 0.10 error, and a
per-(market, horizon) winner-price table (the seed for the Stage C event study —
e.g. is the Fed/FOMC winner already priced 24h before the meeting, or does it
jump at the announcement?).

  INTELLIFI_SOURCE=archive INTELLIFI_ARCHIVE_CIDS=corpus.txt \
      python scripts/25_efficiency.py --out docs/efficiency.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi.warehouse import open_warehouse            # noqa: E402
from intellifi.categories import register_market_categories  # noqa: E402
from intellifi import config as _cfg                       # noqa: E402

HORIZONS = (720, 336, 168, 72, 24, 12, 6, 3, 1)  # hours before close


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/efficiency.json")
    ap.add_argument("--memory-limit", default="8GB")
    args = ap.parse_args()
    import polars as pl

    con = open_warehouse(":memory:")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute("SET preserve_insertion_order=false")
    _tmp = _cfg.DATA_DIR / "_s25_tmp"
    _tmp.mkdir(parents=True, exist_ok=True)
    con.execute(f"SET temp_directory='{_tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='40GB'")
    n_mapped = register_market_categories(con)

    offs = " UNION ALL ".join(f"SELECT {h} AS h" for h in HORIZONS)
    per = con.sql(f"""
        WITH px AS (
            SELECT t.condition_id, t.outcome_index,
                   date_trunc('minute', t.ts_utc) AS ts,
                   SUM(t.price*t.size)/NULLIF(SUM(t.size),0) AS price
            FROM trades t
            WHERE t.price>0 AND t.price<1 AND t.size>0
            GROUP BY 1,2,3
        ),
        wp AS (
            SELECT px.condition_id, px.ts, px.price AS winner_price,
                   DATE_DIFF('second', px.ts, m.closed_time)/3600.0 AS h2c
            FROM px
            JOIN winning_outcomes w
                 ON w.condition_id=px.condition_id AND px.outcome_index=w.winning_outcome_index
            JOIN markets m ON m.condition_id=px.condition_id
            WHERE m.closed_time IS NOT NULL AND px.ts < m.closed_time
        ),
        offs(h) AS ({offs}),
        ranked AS (
            SELECT wp.condition_id, o.h AS horizon, wp.winner_price, wp.h2c,
                   row_number() OVER (PARTITION BY wp.condition_id, o.h ORDER BY wp.h2c ASC) AS rk
            FROM wp CROSS JOIN offs o
            WHERE wp.h2c >= o.h
        )
        SELECT r.condition_id, c.category, c.slug, r.horizon,
               r.winner_price, 1.0 - r.winner_price AS abs_err, r.h2c AS actual_h2c
        FROM ranked r JOIN mktcat c USING (condition_id)
        WHERE r.rk=1
    """).pl()

    if per.is_empty():
        print("no convergence rows", file=sys.stderr); return 2

    rep: dict = {"source": os.getenv("INTELLIFI_SOURCE", "parquet"),
                 "n_markets_mapped": n_mapped,
                 "n_markets_with_path": per["condition_id"].n_unique(),
                 "horizons_hours": list(HORIZONS)}

    def curve(df: pl.DataFrame) -> list[dict]:
        out = []
        for h in HORIZONS:
            g = df.filter(pl.col("horizon") == h)
            if g.is_empty():
                continue
            ae = g["abs_err"].to_numpy()
            out.append({"hours_before_close": h, "n_markets": g.height,
                        "median_abs_err": float(np.median(ae)),
                        "mean_abs_err": float(np.mean(ae)),
                        "p25_abs_err": float(np.percentile(ae, 25)),
                        "p75_abs_err": float(np.percentile(ae, 75))})
        return out

    def first_below(cv: list[dict], thr: float):
        # earliest (largest) horizon whose median error is already < thr
        for row in cv:  # HORIZONS is descending -> cv is earliest-first
            if row["median_abs_err"] < thr:
                return row["hours_before_close"]
        return None

    rep["overall_curve"] = curve(per)
    rep["by_category"] = []
    for (cat,), g in per.group_by(["category"]):
        cv = curve(g)
        rep["by_category"].append({
            "category": cat, "n_markets": g["condition_id"].n_unique(),
            "curve": cv,
            "prices_winner_below_0.25_by_h": first_below(cv, 0.25),
            "prices_winner_below_0.10_by_h": first_below(cv, 0.10),
        })
    rep["by_category"].sort(key=lambda d: -d["n_markets"])

    # per-(market, horizon) winner price — the Stage C seed. Pivot to one row/market.
    piv = {}
    for r in per.to_dicts():
        d = piv.setdefault(r["condition_id"], {"condition_id": r["condition_id"],
                                               "category": r["category"], "slug": r["slug"],
                                               "winner_price_at": {}})
        d["winner_price_at"][str(r["horizon"])] = round(float(r["winner_price"]), 4)
    rep["per_market_winner_price"] = sorted(piv.values(), key=lambda d: (d["category"], d["slug"] or ""))

    rep["notes"] = [
        "abs_err = 1 - winning-outcome price at that horizon; lower = market prices the winner earlier.",
        "winner price = raw trades.price where outcome_index=winning_outcome_index (source-agnostic; no token-id join).",
        "Late convergence (error still high at 24-1h then collapses) flags event/jump-driven resolution "
        "— the Stage C event-study targets (e.g. Fed FOMC markets: priced days out vs jump at the meeting?).",
        "Illiquid markets have sparse minute paths; horizons with few trades are noisier.",
    ]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}  (source={rep['source']}, {rep['n_markets_with_path']} markets with a price path)")
    print("\nOverall winner-price convergence (median |1 - winner_price| by hours before close):")
    for r in rep["overall_curve"]:
        print(f"  {r['hours_before_close']:>4}h  n={r['n_markets']:>3}  median_err={r['median_abs_err']:.3f}  mean={r['mean_abs_err']:.3f}")
    print("\nBy category — earliest horizon the winner is priced within 0.25 / 0.10 error:")
    for r in rep["by_category"]:
        b25 = r["prices_winner_below_0.25_by_h"]; b10 = r["prices_winner_below_0.10_by_h"]
        print(f"  {r['category']:20s} n={r['n_markets']:>3}  <0.25 by {str(b25)+'h':>6}  <0.10 by {str(b10)+'h':>6}")
    con.close()
    import shutil
    shutil.rmtree(_tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python
"""LEAD-PAPER CORE — the staggered fee rollout on the v1 archive as a natural experiment.

Polymarket phased in taker fees by category over early 2026; the archive's per-fill `fee_usdc`
captures the introduction. This builds the identification for "Taxing liquidity on a prediction
market": per-(feeclass, month) it derives each category's FEE-START (first month fee% jumps),
then an EVENT-STUDY in months-relative-to-own-fee-start of the behavioural/welfare outcomes,
with not-yet-treated categories as the implicit control:
  * INCIDENCE:      taker fee % of notional (and by order-size decile, pooled).
  * PARTICIPATION:  distinct taker wallets, NEW (first-seen) wallets, small-order share.
  * ORDER SIZE:     median taker order notional (fills grouped to (taker,market,second) orders).
  * TRANSFER:       total taker fees paid (the taker->maker+platform transfer).

Also emits a BALANCED-PANEL event study (categories present at every month in [--bwin-lo,--bwin-hi],
per-category means, constant composition) and a PRE-TREND slope over the fee-free pre months —
because the pooled series SUMS over a category set that shrinks with |e| (n_cat_months 9->6->1) and
so conflates the fee effect with panel composition. Use the balanced panel + pre-trend for inference.

Lead with COMPOSITION + INCIDENCE (volume elasticity is likely ~null). MEMORY-SAFE: archive
group-bys (file-backed DuckDB, memory_limit 3GB, spill); launch inside systemd-run -p MemoryMax.

  python scripts/36_fee_rollout_did.py --out docs/fee_rollout_did.json --memory-limit 3GB
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                              # noqa: E402
from intellifi.archive import register_archive_views      # noqa: E402
from intellifi import config as _cfg                       # noqa: E402

ATLAS_MAP = _cfg.PARQUET_DIR / "atlas" / "category_to_feeclass_mapping.csv"
SMALL_ORDER = 10.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/fee_rollout_did.json")
    ap.add_argument("--memory-limit", default="3GB")
    ap.add_argument("--fee-start-thresh", type=float, default=0.2, help="fee%% of notional marking a category as 'treated'")
    ap.add_argument("--bwin-lo", type=int, default=-3, help="balanced-panel event window low bound (months rel. fee-start)")
    ap.add_argument("--bwin-hi", type=int, default=1, help="balanced-panel event window high bound")
    args = ap.parse_args()

    tmp = _cfg.DATA_DIR / "_s36_tmp"; import shutil; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='50GB'")
    register_archive_views(con)

    tag2cls = {}
    with open(ATLAS_MAP) as fh:
        for r in csv.DictReader(fh):
            tag2cls[r["category"].strip().lower()] = r["cls"].strip()
    con.execute("CREATE TABLE c2c(category VARCHAR, cls VARCHAR)")
    con.executemany("INSERT INTO c2c VALUES (?,?)", list(tag2cls.items()))

    BASE = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
            "AND taker_direction IN ('BUY','SELL')")
    # taker-order aggregation: group fills to (taker, condition, second, direction) = one taker order.
    # This is near-per-fill granularity (hundreds of millions of groups) -> OOMs a single GROUP BY.
    # Bucket by hash(taker)%NB and write each bucket's orders to parquet (memory-safe), then a view.
    NB = 8
    ordp = tmp / "ord_parts"; ordp.mkdir(parents=True, exist_ok=True)
    ORD_SEL = f"""SELECT COALESCE(c.cls,'other') cls, date_trunc('month', to_timestamp(block_timestamp))::DATE ym,
               taker w, SUM(usdc_amount) notional, SUM(fee_usdc) fee, MIN(block_timestamp) bt
        FROM arc_raw r LEFT JOIN c2c c ON lower(r.category)=lower(c.category)
        WHERE {BASE} AND (hash(taker)%{NB})={{b}}
        GROUP BY 1,2, taker, condition_id, CAST(block_timestamp AS BIGINT), taker_direction"""
    for b in range(NB):
        con.execute(f"COPY ({ORD_SEL.format(b=b)}) TO '{(ordp/f'p{b}.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)")
    con.execute(f"CREATE VIEW ord AS SELECT * FROM read_parquet('{(ordp/'*.parquet').as_posix()}')")
    # first month per wallet (new-wallet flag) — millions of groups, fits; bucketed source keeps it bounded
    con.execute("CREATE TABLE fm AS SELECT w, min(ym) first_ym FROM ord GROUP BY w")

    # per (cls, month) panel
    panel = con.sql(f"""
        SELECT o.cls, o.ym,
               count(*) n_orders, count(DISTINCT o.w) n_wallets,
               count(DISTINCT o.w) FILTER (WHERE f.first_ym = o.ym) n_new_wallets,
               SUM(o.notional) notional, SUM(o.fee) fee,
               median(o.notional) med_order,
               avg(CASE WHEN o.notional < {SMALL_ORDER} THEN 1.0 ELSE 0 END) small_share
        FROM ord o JOIN fm f ON f.w=o.w
        GROUP BY 1,2 ORDER BY 1,2""").fetchall()
    P = [{"cls": r[0], "ym": str(r[1]), "n_orders": int(r[2]), "n_wallets": int(r[3]),
          "n_new_wallets": int(r[4]), "notional": float(r[5]), "fee": float(r[6]),
          "fee_pct": 100*float(r[6])/float(r[5]) if r[5] else None,
          "med_order": float(r[7]), "small_share": float(r[8])} for r in panel]

    # derive fee-start month per cls (first month fee_pct >= thresh)
    fee_start = {}
    for cls in sorted({r["cls"] for r in P}):
        months = sorted([r for r in P if r["cls"] == cls], key=lambda r: r["ym"])
        for r in months:
            if r["fee_pct"] and r["fee_pct"] >= args.fee_start_thresh:
                fee_start[cls] = r["ym"]; break

    # event-study: outcomes by months-relative-to-own-fee-start, pooled over treated categories
    from datetime import date
    def midx(s):
        y, m, _ = s.split("-"); return int(y)*12 + int(m)
    ev = {}
    for r in P:
        cls = r["cls"]
        if cls not in fee_start:
            continue
        e = midx(r["ym"]) - midx(fee_start[cls])
        if -6 <= e <= 6:
            ev.setdefault(e, []).append(r)
    event_study = []
    for e in sorted(ev):
        rows = ev[e]
        tot_notional = sum(x["notional"] for x in rows) or 1
        event_study.append({"event_month": e, "n_cat_months": len(rows),
            "mean_fee_pct": sum(x["fee_pct"] or 0 for x in rows)/len(rows),
            "sum_new_wallets": sum(x["n_new_wallets"] for x in rows),
            "sum_wallets": sum(x["n_wallets"] for x in rows),
            "mean_small_share": sum(x["small_share"] for x in rows)/len(rows),
            "notional_wt_med_order": sum(x["med_order"]*x["notional"] for x in rows)/tot_notional,
            "total_taker_fee": sum(x["fee"] for x in rows)})

    # ---- BALANCED PANEL + PER-CATEGORY GRID + PRE-TREND (fix the changing-panel artifact) ----
    # The pooled event_study above SUMS over a category set that shrinks with |e| (n_cat_months
    # 9 -> 6 -> 1), so sum_new_wallets / sum_wallets and the pooled median mix a treatment effect
    # with panel composition. Below: (1) the full per-(cls,e) grid; (2) a BALANCED panel over the
    # categories present at EVERY month in [bwin_lo, bwin_hi] (constant composition, per-category
    # means); (3) a PRE-TREND slope over the fee-free pre months, to separate pre-existing drift.
    ev_by_cls = {}
    for r in P:
        cls = r["cls"]
        if cls not in fee_start:
            continue
        e = midx(r["ym"]) - midx(fee_start[cls])
        if -6 <= e <= 6:
            ev_by_cls.setdefault(cls, {})[e] = r
    event_study_per_category = [
        {"cls": cls, "event_month": e, "fee_pct": ev_by_cls[cls][e]["fee_pct"],
         "n_wallets": ev_by_cls[cls][e]["n_wallets"], "n_new_wallets": ev_by_cls[cls][e]["n_new_wallets"],
         "med_order": ev_by_cls[cls][e]["med_order"], "small_share": ev_by_cls[cls][e]["small_share"],
         "notional": ev_by_cls[cls][e]["notional"], "fee": ev_by_cls[cls][e]["fee"]}
        for cls in sorted(ev_by_cls) for e in sorted(ev_by_cls[cls])]

    def _balanced(lo, hi):
        cats = sorted(c for c in ev_by_cls if all(e in ev_by_cls[c] for e in range(lo, hi + 1)))
        rows = []
        for e in range(lo, hi + 1):
            rs = [ev_by_cls[c][e] for c in cats]
            if not rs:
                continue
            tot = sum(x["notional"] for x in rs) or 1
            rows.append({"event_month": e, "n_cat": len(rs),
                "mean_fee_pct": sum(x["fee_pct"] or 0 for x in rs) / len(rs),
                "mean_new_wallets_per_cat": sum(x["n_new_wallets"] for x in rs) / len(rs),
                "mean_wallets_per_cat": sum(x["n_wallets"] for x in rs) / len(rs),
                "mean_small_share": sum(x["small_share"] for x in rs) / len(rs),
                "mean_med_order": sum(x["med_order"] for x in rs) / len(rs),  # equal-weight (balanced headline)
                "notional_wt_med_order": sum(x["med_order"] * x["notional"] for x in rs) / tot})
        return {"window": [lo, hi], "categories": cats, "n_categories": len(cats), "by_event_month": rows}

    balanced = _balanced(args.bwin_lo, args.bwin_hi)

    def _slope(pairs):
        n = len(pairs)
        if n < 3:
            return None
        sx = sum(x for x, _ in pairs); sy = sum(y for _, y in pairs)
        sxx = sum(x * x for x, _ in pairs); sxy = sum(x * y for x, y in pairs)
        den = n * sxx - sx * sx
        return (n * sxy - sx * sy) / den if den else None

    balcats = set(balanced["categories"])
    pre_order, pre_neww = [], []
    for e in range(-6, 0):
        rs = [ev_by_cls[c][e] for c in balcats if e in ev_by_cls[c]]
        if not rs:
            continue
        tot = sum(x["notional"] for x in rs) or 1
        pre_order.append((e, sum(x["med_order"] * x["notional"] for x in rs) / tot))
        pre_neww.append((e, sum(x["n_new_wallets"] for x in rs) / len(rs)))
    pretrend = {"pre_window": [-6, -1], "on_balanced_categories": sorted(balcats),
        "med_order_slope_per_month": _slope(pre_order),
        "mean_new_wallets_per_cat_slope_per_month": _slope(pre_neww),
        "med_order_pre_series": pre_order, "new_wallets_per_cat_pre_series": pre_neww,
        "note": "Slopes over the fee-free pre months. A negative med_order slope pre-treatment is a "
                "downward pre-trend that a naive pre-vs-post comparison misattributes to the fee; read the "
                "post-fee effect as the deviation from this trend, on the balanced panel."}

    # incidence by order-size decile (pooled, treated-category post-fee orders)
    treated_cls = list(fee_start)
    inc = []
    if treated_cls:
        cl_list = "','".join(treated_cls)
        qs = con.sql(f"SELECT quantile_cont(notional,[0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9]) FROM ord WHERE cls IN ('{cl_list}') AND fee>0").fetchone()[0]
        edges = [0.0] + list(qs) + [1e30]
        for j in range(len(edges)-1):
            r = con.sql(f"SELECT count(*), sum(fee), sum(notional) FROM ord WHERE cls IN ('{cl_list}') AND fee>0 AND notional>={edges[j]} AND notional<{edges[j+1]}").fetchone()
            if r[0]:
                inc.append({"decile": j+1, "notional_lo": edges[j], "n": int(r[0]),
                            "fee_pct": 100*float(r[1])/float(r[2]) if r[2] else None})

    rep = {"scope": "v1 archive staggered fee rollout — event-study DiD (participation/incidence/transfer)",
           "fee_start_by_class": fee_start, "n_treated_classes": len(fee_start),
           "event_study_relative_to_fee_start": event_study,
           "event_study_per_category": event_study_per_category,
           "event_study_balanced": balanced,
           "pretrend_diagnostic": pretrend,
           "incidence_by_order_size_decile_posttreat": inc,
           "caveats": ["POOLED event_study_relative_to_fee_start SUMS over a category set that shrinks with |e| "
                       "(n_cat_months 9->6->1): sum_new_wallets / sum_wallets and the pooled median mix a treatment "
                       "effect with panel composition, so the raw 317k->89k / $6.9->$2.9 trajectories overstate the "
                       "fee response. Use event_study_balanced (constant category set, per-category means) and "
                       "pretrend_diagnostic for inference; the pooled series is kept for continuity only.",
                       "Fee-start derived from data (first month fee%>=thresh); confounds: crypto-vol regime, "
                       "sports seasonality, platform growth, cross-category substitution — needs placebo/parallel-"
                       "trends robustness. Lead with composition+incidence (volume elasticity likely ~null).",
                       "Order = fills grouped to (taker,market,second,direction). Realised, descriptive."]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True); Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    print("fee-start by class:", fee_start)
    print("EVENT STUDY (months rel. to own fee-start): e | fee% | new_wallets | small_share | wt_med_order | taker_fee")
    for r in event_study:
        print(f"  e={r['event_month']:+d}  fee%={r['mean_fee_pct']:.2f}  new_W={r['sum_new_wallets']:>8,}  "
              f"small={r['mean_small_share']*100:5.1f}%  med_order={r['notional_wt_med_order']:.2f}  fee={r['total_taker_fee']:,.0f}")
    print(f"BALANCED PANEL {balanced['window']} on {balanced['n_categories']} categories "
          f"{balanced['categories']} (constant composition, per-category means):")
    for r in balanced["by_event_month"]:
        print(f"  e={r['event_month']:+d}  fee%={r['mean_fee_pct']:.2f}  new_W/cat={r['mean_new_wallets_per_cat']:>8,.0f}  "
              f"mean_med_order={r['mean_med_order']:.2f}")
    print(f"PRE-TREND (fee-free) med_order slope/mo = {pretrend['med_order_slope_per_month']}  "
          f"new_W/cat slope/mo = {pretrend['mean_new_wallets_per_cat_slope_per_month']}")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

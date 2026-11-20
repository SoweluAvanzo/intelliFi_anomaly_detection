#!/usr/bin/env python
"""Rebuild EVERY figure in the V1->V2 results outline from tracked data — the single
reproducible path, replacing the ad-hoc generators used while drafting.

Each figure is rendered by a function in ``src/intellifi/fee_figures.py``; this script is a
thin orchestrator that (optionally) rebuilds the one piece of derived data that was not yet
persisted — the category-composition table — and then saves all figures as PNGs.

Data provenance (all tracked code / committed JSON / R2-deposited export):

  framing / composition
    comp_markets_per_day, comp_volume_by_category   <- data/export/category_composition.csv
    comp_markets_per_user                           <- data/export/composition_summary.json
        both built here by ``--composition`` from the negRisk fills (scripts/46).

  RQ1 (distribution)
    rq1_taker_economics        <- docs/platform_wide.json (scripts/27) + docs/v2_platform.json (scripts/28)
    rq1_lorenz                 <- data/export/rq2_{v1,v2}_wallets.parquet (scripts/47)
    rq1_profit_concentration   <- shares from rq2_*_wallets.parquet; Gini from the platform reports
    rq1_skill                  <- docs/skill_signflip.json (scripts/31) + docs/skill_signflip_v2.json (scripts/53)

  RQ2 (efficiency) + fee incidence   <- data/export/* produced by scripts/48-52 and correction.analyze

Usage:
    # render every figure from existing data (fast):
    python scripts/54_build_outline_figures.py

    # (re)build the composition table first, then render (heavy; scans the negRisk fills):
    python scripts/54_build_outline_figures.py --composition

Run the heavy path under a memory cap, per CLAUDE.md:
    systemd-run --user --scope -p MemoryMax=6G python scripts/54_build_outline_figures.py --composition
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
import matplotlib  # noqa: E402
matplotlib.use("Agg")

from intellifi import config as cfg  # noqa: E402
from intellifi import correction, fee_figures as F  # noqa: E402

EXPORT = cfg.DATA_DIR / "export"
PARQUET = cfg.PARQUET_DIR
DEFAULT_OUT = cfg.REPO_ROOT / "docs/paper/v1v2_results_outline/figures"

# negRisk spans in days (archive V1 window vs v2 tape window) — used for markets/day.
SPAN = {"v1": 858.3, "v2": 125.2}
# (fills path, wallet column, extra filter) per era. V2 counts taker-order rows only.
ERA_FILLS = {
    "v1": (PARQUET / "negrisk_v1/fills.parquet", "wallet", ""),
    "v2": (PARQUET / "negrisk_v2/fills.parquet", "maker", "AND is_taker_order=TRUE"),
}
CATS = ["sports", "weather", "politics", "crypto", "finance", "culture",
        "science", "business", "awards", "movies"]


def build_composition(mem_limit: str = "4GB") -> None:
    """Scan the negRisk fills -> data/export/category_composition.csv + composition_summary.json.

    Category is read from the CLOB token registry's first tag per negRisk family. The summary
    JSON holds the mean/median distinct-markets-per-user per era used by comp_markets_per_user.
    """
    import duckdb

    spill = cfg.DATA_DIR / "_comp_spill"
    spill.mkdir(parents=True, exist_ok=True)
    clob = (PARQUET / "clob_markets/tokens.parquet").as_posix()
    con = duckdb.connect()
    con.execute(f"PRAGMA memory_limit='{mem_limit}'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{spill.as_posix()}'")
    con.execute("SET max_temp_directory_size='40GB'")
    con.execute(f"""CREATE TEMP TABLE famcat AS
        SELECT neg_risk_market_id AS family, any_value(lower(tags[1])) AS cat
        FROM '{clob}'
        WHERE neg_risk=TRUE AND neg_risk_market_id IS NOT NULL AND neg_risk_market_id<>''
        GROUP BY 1""")

    res, summary = {}, {}
    for era, (fills, wcol, tf) in ERA_FILLS.items():
        fp = fills.as_posix()
        d = con.execute(f"""
            SELECT fc.cat,
                   count(DISTINCT f.family)         AS n_markets,
                   round(sum(f.usdc)/1e6, 1)        AS vol_m,
                   count(DISTINCT lower(f.{wcol}))  AS n_wallets
            FROM '{fp}' f JOIN famcat fc USING(family)
            WHERE f.price>0 AND f.price<1 {tf}
            GROUP BY 1""").df()
        d["mkts_per_day"] = (d.n_markets / SPAN[era]).round(1)
        res[era] = d.set_index("cat")
        mpu = con.execute(f"""
            SELECT round(avg(nf), 2) AS mean, round(median(nf), 1) AS med FROM (
                SELECT lower({wcol}) w, count(DISTINCT family) nf
                FROM '{fp}' WHERE price>0 AND price<1 {tf} GROUP BY 1)""").df().iloc[0]
        summary[era] = {"mean_mkts_per_user": float(mpu["mean"]),
                        "median_mkts_per_user": float(mpu["med"])}
        print(f"  {era}: markets/user mean={mpu['mean']} median={mpu['med']}")

    rows = []
    for c in CATS:
        a = res["v1"].loc[c] if c in res["v1"].index else None
        b = res["v2"].loc[c] if c in res["v2"].index else None
        rows.append({
            "cat": c,
            "V1_mkts": int(a.n_markets) if a is not None else 0,
            "V2_mkts": int(b.n_markets) if b is not None else 0,
            "V1_mkt_day": a.mkts_per_day if a is not None else 0.0,
            "V2_mkt_day": b.mkts_per_day if b is not None else 0.0,
            "V1_vol_M": a.vol_m if a is not None else 0.0,
            "V2_vol_M": b.vol_m if b is not None else 0.0,
            "V1_wal": int(a.n_wallets) if a is not None else 0,
            "V2_wal": int(b.n_wallets) if b is not None else 0,
        })
    import pandas as pd
    EXPORT.mkdir(parents=True, exist_ok=True)
    df = pd.DataFrame(rows)
    df.to_csv(EXPORT / "category_composition.csv", index=False)
    (EXPORT / "composition_summary.json").write_text(json.dumps(summary, indent=1))
    con.close(); shutil.rmtree(spill, ignore_errors=True)
    print(f"  wrote {EXPORT/'category_composition.csv'} and composition_summary.json")
    print(df.to_string(index=False))


def render_all(out: Path) -> None:
    out.mkdir(parents=True, exist_ok=True)
    # figures that need no args
    jobs = {
        # framing / composition
        "comp_markets_per_day": F.fig_comp_markets_per_day,
        "comp_volume_by_category": F.fig_comp_volume_by_category,
        "comp_markets_per_user": F.fig_comp_markets_per_user,
        # RQ1 distribution
        "rq1_taker_economics": F.fig_rq1_taker_economics,
        "rq1_lorenz": F.fig_rq1_lorenz,
        "rq1_profit_concentration": F.fig_rq1_profit_concentration,
        "rq1_skill": F.fig_rq1_skill,
        # fee incidence (RQ1.2)
        "rq3_incidence_price": F.fig_incidence_price,
        "rq3_incidence_size": F.fig_incidence_size,
        # subsidy / LP economics (RQ1.3)
        "rq3_lp_economics": F.fig_rq2_lp_economics,
        # RQ2 efficiency
        "rq2_reliability": F.fig_reliability,
        "rq2_brier": F.fig_brier_decomp,
        "rq2_speed_by_volume": F.fig_correction_speed_by_volume,
        "rq2_unconverged_rate": F.fig_unconverged_rate,
        "rq2_concentration_count_vs_dollar": F.fig_concentration_count_vs_dollar,
        "rq2_density_by_category": F.fig_density_by_category,
        "rq2_fingerprint_concentration": F.fig_rq2_concentration,
        "rq2_fingerprint_distinctness": F.fig_rq2_distinctness,
        "rq2_fingerprint_persistence": F.fig_rq2_persistence,
    }
    ok = fail = 0
    for name, fn in jobs.items():
        try:
            fn().savefig(out / f"{name}.png", dpi=150, bbox_inches="tight")
            ok += 1; print(f"  ok   {name}")
        except Exception as e:  # noqa: BLE001
            fail += 1; print(f"  FAIL {name}: {str(e)[:100]}")
    # figures that need the pre/post correction analyses
    try:
        a1 = correction.analyze((EXPORT / "rq2_v1").as_posix())
        a2 = correction.analyze((EXPORT / "rq2_v2").as_posix())
        F.fig_rq2_prepost(a1, a2).savefig(out / "rq2_prepost_economics.png", dpi=150, bbox_inches="tight")
        ok += 1; print("  ok   rq2_prepost_economics")
    except Exception as e:  # noqa: BLE001
        fail += 1; print(f"  FAIL rq2_prepost_economics: {str(e)[:100]}")
    print(f"\n{ok} figures written to {out}  ({fail} failed)")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--composition", action="store_true",
                    help="rebuild data/export/category_composition.csv first (scans negRisk fills)")
    ap.add_argument("--mem-limit", default="4GB", help="DuckDB memory_limit for --composition")
    ap.add_argument("--out", default=str(DEFAULT_OUT), help="output directory for the PNGs")
    args = ap.parse_args()
    t0 = time.time()
    if args.composition:
        print("[composition] scanning negRisk fills ...")
        build_composition(args.mem_limit)
    print("[render] building figures ...")
    render_all(Path(args.out))
    print(f"done in {time.time()-t0:.0f}s")


if __name__ == "__main__":
    main()

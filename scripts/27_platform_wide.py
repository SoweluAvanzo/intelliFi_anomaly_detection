#!/usr/bin/env python
"""Platform-wide aggregates over the WHOLE v1 archive (851k markets, 2.6M taker
wallets, 746M fills) — the full-scale version of the corpus discovery findings.

The corpus scripts (23/24/25/26) don't scale to 851k markets / 2.6M wallets
(SQL IN-lists, per-market Python loops, O(n_boot x N) bootstrap arrays). This
script computes the HEADLINE platform-wide facts with memory-safe SQL aggregates
only — no per-market loop, no IN-list, no bootstrap blow-up:

  1. Aggregate taker PnL (takers vs makers) across all resolved markets.
  2. Per-category calibration: size-weighted realised hit-rate vs entry price.
  3. Concentration: Gini of per-wallet realised PnL platform-wide.
  4. Top/bottom wallets by realised PnL (SQL ORDER BY LIMIT, no full pull).

Category from the archive's NATIVE `category` field (per-fill in arc_raw) mapped
via the atlas category->feeclass CSV — no clob_markets IN-list (which breaks at
851k cids). TAKER side (archive proxy_wallet = taker). Memory-safe: file-backed
DuckDB, memory_limit, on-disk spill; wrap in systemd-run -p MemoryMax.

  python scripts/27_platform_wide.py --out docs/platform_wide.json --memory-limit 9GB
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                              # noqa: E402
from intellifi.archive import register_archive_views      # noqa: E402
from intellifi.skill import build_bets_view               # noqa: E402
from intellifi import config as _cfg                       # noqa: E402

ATLAS_MAP = _cfg.PARQUET_DIR / "atlas" / "category_to_feeclass_mapping.csv"


def gini_from_sorted_positive(x: np.ndarray) -> float:
    x = np.sort(x[x > 0])
    n = len(x)
    if n == 0:
        return float("nan")
    return float((2.0 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum()))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/platform_wide.json")
    ap.add_argument("--memory-limit", default="9GB")
    ap.add_argument("--top-k", type=int, default=20)
    args = ap.parse_args()

    tmp = _cfg.DATA_DIR / "_s27_tmp"
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp / 'spill').as_posix()}'")
    con.execute("SET max_temp_directory_size='60GB'")
    con.execute("PRAGMA threads=2")      # fewer parallel spill buffers (the OOM was spill-parallelism x a pathological view)
    register_archive_views(con)          # WHOLE archive (no condition_ids); skip materialise (851k token loop)
    # NB: query arc_raw (raw fills) DIRECTLY — the `trades`/`bets` views GROUP BY to
    # near-746M groups (barely aggregating), which OOM'd the spill. arc_raw is a plain
    # scan; our own group-bys (by category = tiny, by taker = 2.6M) are the only aggregations.

    # category -> feeclass map (small); register as a table
    tag2cls = {}
    with open(ATLAS_MAP) as f:
        for row in csv.DictReader(f):
            tag2cls[row["category"].strip().lower()] = row["cls"].strip()
    con.execute("CREATE TEMP TABLE cat2cls(category VARCHAR, cls VARCHAR)")
    con.executemany("INSERT INTO cat2cls VALUES (?,?)", list(tag2cls.items()))

    # A resolved-taker-fill filter reused everywhere (won_outcome = did THIS traded outcome resolve YES)
    RESOLVED = ("winning_outcome_label IS NOT NULL AND price>0 AND price<1 AND shares>0 "
                "AND taker_direction IN ('BUY','SELL')")
    WON_OUT = "(CASE WHEN outcome_label = winning_outcome_label THEN 1 ELSE 0 END)"
    PNL_FILL = (f"(CASE WHEN taker_direction='BUY' THEN ({WON_OUT}-price)*shares "
                f"ELSE (price-{WON_OUT})*shares END)")

    rep: dict = {"scope": "WHOLE v1 archive (no cid scoping)", "side": "taker (arc_raw.taker)"}

    # (2) per-category calibration — pure SUM group-by over arc_raw (tiny hash: ~20 classes)
    rep["per_category"] = []
    for row in con.sql("""
            SELECT COALESCE(c.cls,'other') AS cls, count(*) AS n, sum(r.shares) AS shares,
                   sum(r.shares * (CASE WHEN r.taker_direction='BUY' THEN r.price ELSE 1-r.price END)) AS w_imp,
                   sum(r.shares * (CASE WHEN (r.taker_direction='BUY'  AND r.outcome_label =  r.winning_outcome_label)
                                          OR (r.taker_direction='SELL' AND r.outcome_label <> r.winning_outcome_label)
                                    THEN 1 ELSE 0 END)) AS w_won
            FROM arc_raw r LEFT JOIN cat2cls c ON lower(r.category)=lower(c.category)
            WHERE r.winning_outcome_label IS NOT NULL AND r.price>0 AND r.price<1 AND r.shares>0
              AND r.taker_direction IN ('BUY','SELL')
            GROUP BY 1 ORDER BY n DESC""").fetchall():
        cls, n, sh, wimp, wwon = row
        rep["per_category"].append({"cls": cls, "n_taker_fills": int(n),
            "mean_implied_p": (wimp / sh) if sh else None, "hit_rate": (wwon / sh) if sh else None,
            "calibration_gap": ((wwon - wimp) / sh) if sh else None})

    # scale + (1) aggregate taker PnL — single SUM, no grouping (raw ~= covered on the complete tape)
    sc = con.sql(f"SELECT count(*), count(DISTINCT condition_id), SUM({PNL_FILL}) FROM arc_raw WHERE {RESOLVED}").fetchone()
    rep["scale"] = {"n_resolved_taker_fills": int(sc[0]), "n_markets": int(sc[1])}
    rep["aggregate_taker_pnl_total_usdc"] = float(sc[2]) if sc[2] is not None else None

    # (3)+(4) per-wallet PnL — GROUP BY taker (2.6M groups, one SUM); then Gini + top/bottom
    con.execute(f"CREATE TABLE wpnl AS SELECT taker AS w, SUM({PNL_FILL}) AS pnl FROM arc_raw WHERE {RESOLVED} GROUP BY taker")
    ag = con.sql("SELECT count(*), SUM(pnl>0), SUM(pnl<0) FROM wpnl").fetchone()
    rep["n_taker_wallets"] = int(ag[0])
    rep["scale"]["n_taker_wallets"] = int(ag[0])
    rep["aggregate_taker_pnl"] = {
        "total_pnl_usdc": rep["aggregate_taker_pnl_total_usdc"], "n_wallets": int(ag[0]),
        "n_winners": int(ag[1]), "n_losers": int(ag[2]),
        "interpretation": "negative total => takers lose net to makers (liquidity providers) platform-wide"}
    pos_pnl = con.sql("SELECT pnl FROM wpnl WHERE pnl>0").fetchnumpy()["pnl"]
    rep["pnl_gini_positive"] = gini_from_sorted_positive(np.asarray(pos_pnl, dtype=float))
    rep["top_winners"] = [{"wallet": r[0], "pnl_usdc": float(r[1])}
        for r in con.sql(f"SELECT w,pnl FROM wpnl ORDER BY pnl DESC LIMIT {args.top_k}").fetchall()]
    rep["top_losers"] = [{"wallet": r[0], "pnl_usdc": float(r[1])}
        for r in con.sql(f"SELECT w,pnl FROM wpnl ORDER BY pnl ASC LIMIT {args.top_k}").fetchall()]

    rep["caveats"] = [
        "TAKER side (archive proxy_wallet=taker); makers are the uncounted counterparty.",
        "Realised RAW per-fill PnL (~= covered on the complete archive tape, where uncovered "
        "sells are rare); outcome-dependent (survivorship) — descriptive, not skill.",
        "Category = archive native `category` -> atlas feeclass; unmapped fall to 'other'.",
        "Whole v1 archive 2022-11..2026-04; the v2 tape (2026-06+) is a separate dataset.",
    ]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    print(f"SCALE: {rep['scale']['n_markets']:,} markets | {rep['scale']['n_taker_wallets']:,} wallets | "
          f"{rep['scale']['n_resolved_taker_fills']:,} resolved taker fills")
    a = rep["aggregate_taker_pnl"]
    print(f"AGGREGATE taker PnL: {a['total_pnl_usdc']:,.0f} USDC over {a['n_wallets']:,} wallets "
          f"({a['n_winners']:,} winners / {a['n_losers']:,} losers); Gini(+PnL)={rep['pnl_gini_positive']:.3f}")
    print("PER-CATEGORY edge (size-wt hit - implied price):")
    for r in rep["per_category"][:14]:
        gap = r['calibration_gap']
        print(f"  {str(r['cls']):20s} n_fills={r['n_taker_fills']:>11,} "
              f"implied={r['mean_implied_p']:.3f} hit={r['hit_rate']:.3f} gap={gap:+.4f}" if gap is not None
              else f"  {str(r['cls']):20s} n_fills={r['n_taker_fills']:>11,} (no calibration)")
    con.close()
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

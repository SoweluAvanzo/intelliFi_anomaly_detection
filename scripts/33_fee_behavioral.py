#!/usr/bin/env python
"""T2 — the v2 fee rollout as behavioral / welfare economics.

Polymarket's fee introduction is a natural experiment nobody has studied for its behavioral
and distributional effects. Using the v2 tape (taker-ORDER records, is_taker_order=TRUE,
where the fee lives), month by month as the effective fee rose (~0.8%%->1.5%% Apr->Aug):
  1. INCIDENCE / regressivity: effective fee rate by taker-order notional decile.
  2. PARTICIPATION: distinct taker wallets, NEW (first-seen) wallets, and the small-order
     share, per month — did the fee price out small/new traders?
  3. ORDER SIZE: median taker-order notional per month.

MEMORY-SAFE: block-range-partitioned dedup of is_tk records written to per-partition parquet
(no giant materialised table), then streaming group-bys. Launch inside systemd-run -p MemoryMax.

  python scripts/33_fee_behavioral.py --out docs/fee_behavioral.json --memory-limit 6GB
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                        # noqa: E402
from intellifi import config as _cfg                 # noqa: E402

TAPE = "data/parquet/tape_v2/**/*.parquet"
STEP = 250_000
SMALL_ORDER_USDC = 10.0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/fee_behavioral.json")
    ap.add_argument("--memory-limit", default="6GB")
    args = ap.parse_args()

    import shutil
    tmp = _cfg.DATA_DIR / "_s33_tmp"; shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='40GB'")

    b0, b1 = con.sql(f"SELECT min(block_number), max(block_number) FROM read_parquet('{TAPE}', union_by_name=true)").fetchone()
    b0, b1 = int(b0), int(b1)
    parts = tmp / "parts"; parts.mkdir()
    # is_tk taker-order records: taker wallet = maker field; notional=usdc; fee=fee_raw/1e6
    SEL = f"""
        SELECT lower(t.maker) AS w, date_trunc('month', t.ts_utc::TIMESTAMP) AS ym,
               t.usdc AS notional, t.fee_raw/1e6 AS fee, t.block_number AS bn
        FROM read_parquet('{TAPE}', union_by_name=true) t
        WHERE t.is_taker_order = TRUE AND t.event='OrderFilled' AND t.exchange IN ('v2_a','v2_b')
          AND t.price>0 AND t.price<1 AND t.shares>0 AND t.usdc>0
          AND t.block_number >= {{lo}} AND t.block_number < {{hi}}
        QUALIFY row_number() OVER (PARTITION BY t.tx_hash, t.evt_index)=1"""
    ranges = list(range(b0, b1 + 1, STEP)); tot = 0
    for i, lo in enumerate(ranges):
        pth = (parts / f"p{i:04d}.parquet").as_posix()
        con.execute(f"COPY ({SEL.format(lo=lo, hi=lo+STEP)}) TO '{pth}' (FORMAT PARQUET, COMPRESSION zstd)")
        if i % 6 == 0 or i == len(ranges) - 1:
            n = con.sql(f"SELECT count(*) FROM read_parquet('{pth}')").fetchone()[0]; tot += n
            print(f"  build {lo:,} ({i+1}/{len(ranges)}) total~{tot:,}", flush=True)
    con.execute(f"CREATE VIEW o AS SELECT * FROM read_parquet('{(parts/'*.parquet').as_posix()}')")

    rep: dict = {"scope": "v2 tape, taker-order records (is_tk=TRUE, deduped, v2_a/v2_b); fee behavioral/welfare"}

    # (2) monthly participation panel
    con.execute("CREATE TABLE wm AS SELECT DISTINCT w, ym FROM o")          # wallet-months (dedup)
    # first month per wallet = MIN(ym) (blocks/time are monotonic) -> new-wallet counts
    con.execute("CREATE TABLE firstym AS SELECT w, min(ym) first_ym FROM o GROUP BY w")
    monthly = con.sql(f"""
        SELECT ym, count(*) n_orders, sum(notional) notional, sum(fee) fee,
               median(notional) med_notional,
               avg(CASE WHEN notional < {SMALL_ORDER_USDC} THEN 1.0 ELSE 0 END) small_order_share
        FROM o GROUP BY ym ORDER BY ym""").fetchall()
    dwall = {str(r[0]): int(r[1]) for r in con.sql("SELECT ym, count(*) FROM wm GROUP BY ym").fetchall()}
    nwall = {str(r[0]): int(r[1]) for r in con.sql("SELECT first_ym, count(*) FROM firstym GROUP BY first_ym").fetchall()}
    rep["monthly"] = [
        {"month": str(r[0])[:7], "n_orders": int(r[1]), "notional_usdc": float(r[2]), "fee_usdc": float(r[3]),
         "fee_pct_of_notional": 100*float(r[3])/float(r[2]) if r[2] else None,
         "median_order_usdc": float(r[4]), "small_order_share": float(r[5]),
         "n_distinct_wallets": dwall.get(str(r[0])), "n_new_wallets": nwall.get(str(r[0]))}
        for r in monthly]

    # (1) fee incidence by notional decile (regressivity)
    qs = con.sql("SELECT quantile_cont(notional, [0.1,0.2,0.3,0.4,0.5,0.6,0.7,0.8,0.9]) FROM o").fetchone()[0]
    edges = [0.0] + list(qs) + [float("inf")]
    inc = []
    for j in range(len(edges) - 1):
        lo, hi = edges[j], edges[j + 1]
        r = con.sql(f"""SELECT count(*), sum(fee), sum(notional) FROM o
                        WHERE notional >= {lo} AND notional < {hi if hi != float('inf') else 1e30}""").fetchone()
        if r[0]:
            inc.append({"decile": j + 1, "notional_lo": lo, "n": int(r[0]),
                        "fee_pct_of_notional": 100*float(r[1])/float(r[2]) if r[2] else None})
    rep["fee_incidence_by_notional_decile"] = inc

    rep["caveats"] = [
        "Within-v2 (avoids the v1->v2 venue confound); taker-ORDER unit (is_tk=TRUE) where the fee lives.",
        "Participation counts are on-chain wallet addresses (sybil not collapsed — see T1); descriptive.",
        "Effective fee rises over the window as fee-free categories shrink; read the monthly panel with that.",
    ]
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    print("MONTHLY: month | orders | distinct W | new W | med$ | small% | fee%")
    for r in rep["monthly"]:
        print(f"  {r['month']}  {r['n_orders']:>11,}  {r['n_distinct_wallets']:>9,}  {r['n_new_wallets']:>9,}  "
              f"{r['median_order_usdc']:>7.2f}  {r['small_order_share']*100:5.1f}%  {r['fee_pct_of_notional']:.3f}%")
    print("INCIDENCE by notional decile (fee% of notional):")
    for r in rep["fee_incidence_by_notional_decile"]:
        print(f"  d{r['decile']:2d}  notional>= {r['notional_lo']:>10.2f}  n={r['n']:>10,}  fee%={r['fee_pct_of_notional']:.3f}")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

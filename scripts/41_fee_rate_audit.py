#!/usr/bin/env python
"""Eq. (1) fee-rate audit on the v2 tape — confirm the taker fee is r*p(1-p)*s with r=7%.

Producer for the fee-formula audit behind Eq. (1)-(2) of the paper
(docs/paper/main.tex). The committed docs/gate1_fee_audit.json was computed on a
token-bucket sample with no script; this reproduces the two numbers the paper
actually states, on the WHOLE deduped tape:

  - median of  fee / [p(1-p)s]  over taker-paid v2 fills  == 0.070   (=> r = 7%)
  - fraction of taker orders whose ratio exceeds the 7% ceiling      < 0.2%

v2 tape conventions (see scripts/28_v2_platform.py, CLAUDE.md "Known latent issues"):
  - The fee lives on the is_taker_order = TRUE records (fee_raw, pUSD 6-dec);
    the maker-fill rows carry fee_raw ~= 0.
  - DEDUP by (tx_hash, evt_index): resumable crawls write overlapping block ranges.
  - exchange IN ('v2_a','v2_b') AND event = 'OrderFilled' (Sample-B tape definition).

Memory-safe: the deduped taker-order rows are written to block-range parquet parts
first (as in scripts/28), then aggregated, so no uncapped scan of the 47 GB tape.
Run inside a memory cap (MemoryMax=9G scope + PRAGMA memory_limit); uncapped DuckDB
scans have OOM-killed the box.

  python scripts/41_fee_rate_audit.py --out docs/gate1_fee_audit_repro.json --memory-limit 4GB
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                         # noqa: E402
from intellifi import config as _cfg                  # noqa: E402

TAPE = "data/parquet/tape_v2/**/*.parquet"
STEP = 250_000


def build_parts(con, select_sql: str, parts_dir: Path, b0: int, b1: int, tag: str) -> int:
    parts_dir.mkdir(parents=True, exist_ok=True)
    tot = 0
    ranges = list(range(b0, b1 + 1, STEP))
    for i, lo in enumerate(ranges):
        pth = (parts_dir / f"p{i:04d}.parquet").as_posix()
        con.execute(f"COPY ({select_sql.format(lo=lo, hi=lo + STEP)}) TO '{pth}' (FORMAT PARQUET, COMPRESSION zstd)")
        n = con.sql(f"SELECT count(*) FROM read_parquet('{pth}')").fetchone()[0]; tot += n
        if i % 6 == 0 or i == len(ranges) - 1:
            print(f"  {tag} build: block {lo:,} ({i+1}/{len(ranges)})  +{n:,}  total={tot:,}", flush=True)
    return tot


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/gate1_fee_audit_repro.json")
    ap.add_argument("--memory-limit", default="4GB")
    args = ap.parse_args()

    tmp = _cfg.DATA_DIR / "_s41_tmp"
    shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='60GB'")

    b0, b1 = con.sql(f"SELECT min(block_number), max(block_number) FROM read_parquet('{TAPE}', union_by_name=true)").fetchone()
    b0, b1 = int(b0), int(b1)

    # Taker-paid rows only; the ratio fee/[p(1-p)s] == r exactly when the fee law holds.
    SEL = f"""
        SELECT (t.fee_raw/1e6) / (t.price*(1-t.price)*t.shares) AS ratio, t.usdc AS notional
        FROM read_parquet('{TAPE}', union_by_name=true) t
        WHERE t.is_taker_order = TRUE AND t.event='OrderFilled' AND t.exchange IN ('v2_a','v2_b')
          AND t.price>0 AND t.price<1 AND t.shares>0 AND t.fee_raw>0
          AND t.block_number >= {{lo}} AND t.block_number < {{hi}}
        QUALIFY row_number() OVER (PARTITION BY t.tx_hash, t.evt_index) = 1"""
    n = build_parts(con, SEL, tmp / "parts", b0, b1, "taker-fee")
    con.execute(f"CREATE VIEW r AS SELECT * FROM read_parquet('{(tmp/'parts'/'*.parquet').as_posix()}')")

    row = con.sql("""
        SELECT count(*) n,
               approx_quantile(ratio, 0.5)  AS median_ratio,
               approx_quantile(ratio, 0.9)  AS p90_ratio,
               approx_quantile(ratio, 0.99) AS p99_ratio,
               avg(CASE WHEN ratio > 0.07 THEN 1 ELSE 0 END) AS frac_over_7pct,
               avg(CASE WHEN ratio > 0.0701 THEN 1 ELSE 0 END) AS frac_over_7pct_eps,
               sum(notional) AS taker_notional_usdc
        FROM r""").fetchone()

    rep = {
        "gate": "Eq.(1) fee-rate audit (reproduced, full tape, scripted)",
        "scope": "v2 tape, taker-paid fills (is_taker_order=TRUE, deduped, v2_a/v2_b, OrderFilled)",
        "n_taker_orders": int(row[0]),
        "feeRate_confirmed": round(float(row[1]), 5),
        "median_fee_over_p1mp_size": float(row[1]),
        "p90_ratio": float(row[2]),
        "p99_ratio": float(row[3]),
        "frac_orders_over_7pct": float(row[4]),
        "frac_orders_over_7pct_strict": float(row[5]),
        "taker_notional_usdc": float(row[6]) if row[6] is not None else None,
        "paper_claims": {"median": 0.070, "frac_over_ceiling": "< 0.2%"},
        "method": "ratio = (fee_raw/1e6) / (price*(1-price)*shares) per taker-paid fill; "
                  "median via approx_quantile; frac_over = share with ratio>0.07.",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1))
    print(f"wrote {args.out}")
    print(f"  n={rep['n_taker_orders']:,}  median ratio={rep['median_fee_over_p1mp_size']:.5f}  "
          f"frac>7%={rep['frac_orders_over_7pct']:.4%}  taker_notional=${rep['taker_notional_usdc']:,.0f}")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

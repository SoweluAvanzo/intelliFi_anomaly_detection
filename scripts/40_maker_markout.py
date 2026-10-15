#!/usr/bin/env python
"""RQ2 (mechanism) — maker MARKOUT on the full v2 on-chain record.

A maker's realised liquidity-provision return is the signed price move AFTER its fill:
for each maker fill, the forward price is the first TAKER trade of the same token in
[t+DELTA, t+DELTA+GRACE] (GRACE=max(2*DELTA,900)s); markout_ps = p_fwd-p_fill for a BUY,
p_fill-p_fwd for a SELL. POSITIVE markout = spread capture; NEGATIVE = adverse selection.
This is outcome-independent (uses the next trade price, not resolution), so it is the clean
microstructure complement to scripts/32's realised, outcome-dependent maker PnL.

Full-tape, memory-safe, resumable:
  * TOKEN-bucketed (hash(token_id)%NB): all fills/trades of a token land together, so the
    per-token ASOF join is complete within a bucket; a bucket is ~1/NB of the data.
  * Stage 1 (per bucket, per horizon): ASOF join -> overall sufficient stats + a per-MAKER
    partial (maker, shares, dollar-markout, n) written to parquet. Resumable: a finished
    bucket writes bucket_<b>.json and is skipped on restart.
  * Stage 2 (once all buckets done): per horizon, re-aggregate the per-maker partials ACROSS
    buckets (a maker trades many tokens) -> volume deciles, Spearman(volume, markout), d1/d10.

Dedup on (tx_hash, evt_index) (overlapping crawl chunks). Launch inside
systemd-run --user --scope -p MemoryMax=6G; DuckDB memory_limit + on-disk spill.

  systemd-run --user --scope -p MemoryMax=6G \
      .venv/bin/python scripts/40_maker_markout.py --out docs/maker_markout.json
"""
from __future__ import annotations

import argparse
import glob
import json
import shutil
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                   # noqa: E402
from intellifi import config as _cfg            # noqa: E402

HORIZONS = [60, 300, 900, 3600, 86400]
TAPE = "data/parquet/tape_v2/**/*.parquet"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/maker_markout.json")
    ap.add_argument("--buckets", type=int, default=12, help="token hash buckets (memory vs #scans)")
    ap.add_argument("--memory-limit", default="4GB")
    ap.add_argument("--limit-files", type=int, default=0, help="VALIDATION ONLY: use first N tape files")
    ap.add_argument("--file-slice", default=None, help="VALIDATION ONLY: 'LO:HI' python slice of sorted files")
    ap.add_argument("--work", default=None, help="work dir (default: scratch under data/)")
    args = ap.parse_args()

    files = sorted(glob.glob(TAPE, recursive=True))
    if args.file_slice:
        lo, hi = args.file_slice.split(":")
        files = files[int(lo):int(hi)]
    elif args.limit_files:
        files = files[:args.limit_files]
    g = "['" + "','".join(files) + "']"
    NB = args.buckets

    work = Path(args.work) if args.work else (_cfg.DATA_DIR / "_markout")
    parts = work / "parts"; parts.mkdir(parents=True, exist_ok=True)
    spill = work / "spill"; spill.mkdir(parents=True, exist_ok=True)
    (work / "bucket_done").mkdir(parents=True, exist_ok=True)

    def connect():
        con = duckdb.connect()
        con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
        con.execute("PRAGMA threads=3"); con.execute("SET timezone='UTC'")
        con.execute("SET preserve_insertion_order=false")
        con.execute(f"SET temp_directory='{spill.as_posix()}'")
        con.execute("SET max_temp_directory_size='60GB'")
        return con

    t0 = time.time()
    # ---------------- Stage 1: per token-bucket ----------------
    for b in range(NB):
        donef = work / "bucket_done" / f"b{b}.json"
        if donef.exists():
            continue
        con = connect()
        con.execute(f"""CREATE TABLE f AS
          SELECT token_id, epoch(ts_utc)::BIGINT t, lower(maker) maker, side, price p, shares, is_taker_order
          FROM read_parquet({g}, union_by_name=true)
          WHERE event='OrderFilled' AND price>0 AND price<1 AND shares>0 AND (hash(token_id)%{NB})={b}
          QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index)=1""")
        con.execute("CREATE TABLE M AS SELECT token_id,t,maker,side,p AS p_fill,shares FROM f WHERE is_taker_order=FALSE")
        # forward reference = ONE deterministic price per (token, second): the volume-weighted taker
        # price. Collapsing ties makes the ASOF match unique, so the result is reproducible and
        # bucket-invariant (several taker trades can share a timestamp; a raw series picks one at random).
        con.execute("""CREATE TABLE P AS SELECT token_id, t, sum(p*shares)/sum(shares) price
                       FROM f WHERE is_taker_order=TRUE GROUP BY token_id, t""")
        nm_b = con.sql("SELECT count(*) FROM M").fetchone()[0]
        overall = {}
        for D in HORIZONS:
            G = max(2 * D, 900)
            con.execute("DROP TABLE IF EXISTS MM; DROP TABLE IF EXISTS MK")
            con.execute(f"""CREATE TABLE MM AS
              SELECT m.maker, m.side, m.p_fill, m.shares, p.price AS p_fwd, (p.t-m.t) gap
              FROM M m ASOF LEFT JOIN P p ON m.token_id=p.token_id AND (m.t+{D})<=p.t""")
            con.execute(f"""CREATE TABLE MK AS
              SELECT maker, shares,
                     (CASE WHEN side='BUY' THEN (p_fwd-p_fill) ELSE (p_fill-p_fwd) END) mko_ps, gap
              FROM MM WHERE p_fwd IS NOT NULL AND gap <= {D}+{G}""")
            # sign uses a 1e-9/share economic-zero threshold: a markout below it is noise, not
            # "adverse selection", which also makes frac_negative reproducible (float-sum order can
            # otherwise flip the sign of a near-zero markout).
            ov = con.sql("""SELECT count(*), coalesce(sum(shares),0), coalesce(sum(mko_ps*shares),0),
                 coalesce(sum(mko_ps),0), coalesce(sum(CASE WHEN mko_ps<-1e-9 THEN 1 ELSE 0 END),0),
                 coalesce(sum(gap),0) FROM MK""").fetchone()
            overall[str(D)] = {"cov": int(ov[0]), "sum_sh": float(ov[1]), "sum_dol": float(ov[2]),
                               "sum_mko": float(ov[3]), "neg": int(ov[4]), "sum_gap": float(ov[5])}
            hp = parts / f"h{D}"; hp.mkdir(exist_ok=True)
            con.execute(f"""COPY (SELECT maker, sum(shares) sh, sum(mko_ps*shares) dol, count(*) n
                               FROM MK GROUP BY maker)
                            TO '{(hp / f'b{b}.parquet').as_posix()}' (FORMAT PARQUET, COMPRESSION zstd)""")
        con.close()
        tmp = donef.with_suffix(".tmp")
        tmp.write_text(json.dumps({"bucket": b, "nm": int(nm_b), "overall": overall}))
        tmp.replace(donef)
        print(f"[{time.strftime('%H:%M:%S')}] bucket {b+1}/{NB} done  maker_fills={nm_b:,}  "
              f"elapsed={ (time.time()-t0)/60:.1f}m", flush=True)

    # ---------------- Stage 2: combine ----------------
    bjs = [json.loads((work / "bucket_done" / f"b{b}.json").read_text()) for b in range(NB)]
    nm_total = sum(j["nm"] for j in bjs)
    con = connect()
    curve = []
    for D in HORIZONS:
        agg = {k: 0.0 for k in ("cov", "sum_sh", "sum_dol", "sum_mko", "neg", "sum_gap")}
        for j in bjs:
            o = j["overall"][str(D)]
            for k in agg:
                agg[k] += o[k]
        cov = int(agg["cov"])
        # per-maker across buckets -> deciles, spearman, d1/d10
        hp = parts / f"h{D}"
        con.execute(f"""CREATE OR REPLACE TABLE mk AS
          SELECT maker, sum(sh) sh, sum(dol) dol
          FROM read_parquet('{(hp / '*.parquet').as_posix()}') GROUP BY maker HAVING sum(sh)>0""")
        con.execute("CREATE OR REPLACE TABLE mq AS SELECT *, ntile(10) OVER (ORDER BY sh, maker) vd FROM mk")
        d1, d10 = con.sql("""SELECT max(CASE WHEN vd=1 THEN m END), max(CASE WHEN vd=10 THEN m END)
            FROM (SELECT vd, sum(dol)/sum(sh) m FROM mq GROUP BY vd)""").fetchone()
        sp = con.sql("""SELECT corr(rv,rm) FROM
            (SELECT rank() OVER (ORDER BY sh) rv, rank() OVER (ORDER BY dol/sh) rm FROM mq)""").fetchone()[0]
        curve.append({
            "horizon_s": D, "coverage": cov, "coverage_frac": cov / nm_total if nm_total else None,
            "mean_gap_s": agg["sum_gap"] / cov if cov else None,
            "dollar_wtd_markout_ps": agg["sum_dol"] / agg["sum_sh"] if agg["sum_sh"] else None,
            "mean_markout_ps": agg["sum_mko"] / cov if cov else None,
            "frac_negative": agg["neg"] / cov if cov else None,
            "total_dollar_markout": agg["sum_dol"],
            "spearman_vol_markout": sp, "d1_markout_ps": d1, "d10_markout_ps": d10})
        print(f"  D={D:>6}s cov={100*cov/nm_total:4.1f}% dw_mko={agg['sum_dol']/agg['sum_sh']:+.5f} "
              f"neg={agg['neg']/cov:.3f} spear={sp:+.3f} d1={d1:+.5f} d10={d10:+.5f}", flush=True)
    con.close()

    rep = {"scope": "v2 on-chain record, MAKER markout vs horizon; outcome-independent (next-trade price)",
           "n_maker_fills": int(nm_total), "n_token_buckets": NB,
           "limit_files": args.limit_files or None, "curve": curve,
           "method": ("per maker fill, forward = first taker trade in [t+D, t+D+max(2D,900)]; "
                      "markout_ps = BUY:(p_fwd-p_fill)/SELL:(p_fill-p_fwd); negative=adverse selection"),
           "caveats": ["Coverage falls with horizon (illiquid tokens have no near-future taker trade) -> "
                       "speaks to liquid-market making.",
                       "Complementary to scripts/32 realised maker PnL (v1); a maker can have +markout and "
                       "still lose realised PnL (inventory / holding to resolution / fee).",
                       "Excludes the maker rebate; measures execution-level liquidity-provision return."]}
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}  ({(time.time()-t0)/60:.1f}m)")
    if not args.work:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

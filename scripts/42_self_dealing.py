#!/usr/bin/env python
"""Whole-tape transaction totals and self-dealing enumeration on the v2 record.

Producer for the two numbers the paper states but that had no committed artifact:
  - Section III-A / V: the V2 record is N_fills fills across N_tx transactions.
  - Section V ("The capture is genuine, not self-dealing"): the share of
    transactions with a participant on BOTH sides (a wallet that is a maker in one
    fill and the taker in another fill of the same transaction), and their volume.

Scope is the WHOLE deduped tape (NOT only resolved markets, unlike scripts/28):
  - exchange IN ('v2_a','v2_b') AND event='OrderFilled', price in (0,1), shares>0.
  - DEDUP by (tx_hash, evt_index); resumable crawls write overlapping block ranges.
  - "fills" = maker-fill records (is_taker_order=FALSE); each economic trade has one
    taker-order record (is_taker_order=TRUE) carrying the fee and the taker notional.
  - A transaction is self-dealing if, within one tx_hash, some wallet appears both as
    a `maker` (on a maker-fill row) and as the `taker`. Fill-level self-match
    (maker=taker in a single row) is reported separately (pre-registered H1c: ~0).

Memory-safe. A transaction is mined in exactly one block and the deduped parts are
block-ranged, so every transaction's fills live entirely inside one part file. The
self-dealing both-sides pass therefore runs PER PART (small group-by, bounded memory)
and accumulates only the self-dealing (tx, wallet) pairs, and the distinct-transaction
count is the sum of per-part distinct counts. This avoids the 257M-group whole-tape
GROUP BY that OOMs even under a cap. Run inside MemoryMax=9G + PRAGMA memory_limit.

  python scripts/42_self_dealing.py --out docs/self_dealing.json --memory-limit 4GB
  python scripts/42_self_dealing.py --reuse   # reuse already-built parts in data/_s42_tmp
"""
from __future__ import annotations

import argparse
import glob
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
    ap.add_argument("--out", default="docs/self_dealing.json")
    ap.add_argument("--memory-limit", default="4GB")
    ap.add_argument("--reuse", action="store_true", help="reuse existing parts in data/_s42_tmp (skip rebuild)")
    args = ap.parse_args()

    tmp = _cfg.DATA_DIR / "_s42_tmp"
    fdir, gdir = tmp / "f", tmp / "g"
    reuse = args.reuse and any(fdir.glob("*.parquet")) and any(gdir.glob("*.parquet"))
    if not reuse:
        shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    (tmp / "spill").mkdir(parents=True, exist_ok=True)

    con = duckdb.connect()  # in-memory catalog; data stays in on-disk parquet parts
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='80GB'")

    if reuse:
        print(f"[reuse] using existing parts in {tmp}", flush=True)
    else:
        b0, b1 = con.sql(f"SELECT min(block_number), max(block_number) FROM read_parquet('{TAPE}', union_by_name=true)").fetchone()
        b0, b1 = int(b0), int(b1)
        WHERE = ("t.event='OrderFilled' AND t.exchange IN ('v2_a','v2_b') AND t.price>0 AND t.price<1 "
                 "AND t.shares>0 AND t.block_number >= {lo} AND t.block_number < {hi}")
        DEDUP = "QUALIFY row_number() OVER (PARTITION BY t.tx_hash, t.evt_index) = 1"
        F_SEL = f"""SELECT t.tx_hash, lower(t.maker) AS mk, lower(t.taker) AS tk, t.usdc AS notional
            FROM read_parquet('{TAPE}', union_by_name=true) t
            WHERE t.is_taker_order = FALSE AND {WHERE} {DEDUP}"""
        G_SEL = f"""SELECT t.tx_hash, t.usdc AS notional
            FROM read_parquet('{TAPE}', union_by_name=true) t
            WHERE t.is_taker_order = TRUE AND {WHERE} {DEDUP}"""
        build_parts(con, F_SEL, fdir, b0, b1, "maker-fill")
        build_parts(con, G_SEL, gdir, b0, b1, "taker-order")

    con.execute(f"CREATE VIEW f AS SELECT * FROM read_parquet('{(fdir/'*.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW g AS SELECT * FROM read_parquet('{(gdir/'*.parquet').as_posix()}')")

    # --- totals (cheap streaming aggregates; distinct-tx summed per part) ---------
    print("[totals] computing ...", flush=True)
    n_fills = con.sql("SELECT count(*) FROM f").fetchone()[0]
    n_orders = con.sql("SELECT count(*) FROM g").fetchone()[0]
    f_notional = con.sql("SELECT sum(notional) FROM f").fetchone()[0]
    taker_volume = con.sql("SELECT sum(notional) FROM g").fetchone()[0]
    fill_self_match = con.sql("SELECT count(*) FROM f WHERE mk = tk").fetchone()[0]
    fparts = sorted(glob.glob((fdir / "*.parquet").as_posix()))
    ntx = 0  # a tx is in one block => one part => per-part distinct counts are disjoint
    for p in fparts:
        ntx += con.sql(f"SELECT count(DISTINCT tx_hash) FROM read_parquet('{p}')").fetchone()[0]
    print(f"[totals] fills={n_fills:,} orders={n_orders:,} tx={ntx:,} "
          f"f_notional=${f_notional:,.0f} taker_vol=${taker_volume:,.0f} fill_self_match={fill_self_match}", flush=True)

    # --- self-dealing: per-part both-sides pass (bounded memory) ------------------
    print("[self-deal] per-part both-sides pass ...", flush=True)
    con.execute("CREATE TABLE bsw_all (tx_hash VARCHAR, w VARCHAR)")
    for i, p in enumerate(fparts):
        con.execute(f"""INSERT INTO bsw_all
            SELECT tx_hash, w FROM (
                SELECT tx_hash, w, max(ismk) hm, max(istk) ht FROM (
                    SELECT tx_hash, mk AS w, 1 ismk, 0 istk FROM read_parquet('{p}')
                    UNION ALL
                    SELECT tx_hash, tk AS w, 0 ismk, 1 istk FROM read_parquet('{p}')
                ) GROUP BY tx_hash, w
            ) WHERE hm = 1 AND ht = 1""")
        if i % 6 == 0 or i == len(fparts) - 1:
            c = con.sql("SELECT count(*) FROM bsw_all").fetchone()[0]
            print(f"  self-deal part {i+1}/{len(fparts)}  bsw_all rows={c:,}", flush=True)

    sd_tx = con.sql("SELECT count(DISTINCT tx_hash) FROM bsw_all").fetchone()[0]
    sd_vol_taker = con.sql("SELECT sum(notional) FROM g WHERE tx_hash IN (SELECT DISTINCT tx_hash FROM bsw_all)").fetchone()[0]
    sd_vol_fill = con.sql("SELECT sum(notional) FROM f WHERE tx_hash IN (SELECT DISTINCT tx_hash FROM bsw_all)").fetchone()[0]
    top = con.sql("SELECT w, count(DISTINCT tx_hash) ntx FROM bsw_all GROUP BY w ORDER BY ntx DESC LIMIT 5").fetchall()
    top_wallet_tx = int(top[0][1]) if top else 0

    rep = {
        "scope": "v2 tape, WHOLE record (all markets), deduped by (tx_hash,evt_index), v2_a/v2_b, OrderFilled",
        "n_maker_fills": int(n_fills),
        "n_taker_orders": int(n_orders),
        "n_transactions": int(ntx),
        "maker_fill_notional_usdc": float(f_notional) if f_notional is not None else None,
        "taker_volume_usdc": float(taker_volume) if taker_volume is not None else None,
        "fill_level_self_match": int(fill_self_match),
        "self_dealing": {
            "definition": "a wallet is a maker on one fill and the taker on another fill of the same tx_hash",
            "n_self_dealing_tx": int(sd_tx),
            "frac_of_transactions": (sd_tx / ntx) if ntx else None,
            "self_dealing_volume_usdc_taker": float(sd_vol_taker) if sd_vol_taker is not None else None,
            "self_dealing_volume_usdc_fill": float(sd_vol_fill) if sd_vol_fill is not None else None,
            "top_wallets_by_self_dealing_tx": [{"wallet": w, "n_tx": int(c)} for w, c in top],
            "top_wallet_share_of_self_dealing_tx": (top_wallet_tx / sd_tx) if sd_tx else None,
        },
        "paper_claims": {"n_fills": "441.5M", "n_transactions": "257.7M",
                         "n_self_dealing_tx": "~7,000 (0.0027%)", "self_dealing_volume": "$77,000",
                         "total_volume": "$14.1B"},
        "method": "deduped maker-fill + taker-order parts (block-ranged => a tx is wholly within one part); "
                  "per-part tx-level both-sides group-by accumulated; fill-level self-match (mk=tk) separate.",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1))
    print(f"wrote {args.out}")
    sd = rep["self_dealing"]
    print(f"  fills={rep['n_maker_fills']:,}  tx={rep['n_transactions']:,}  taker_vol=${rep['taker_volume_usdc']:,.0f}")
    print(f"  self-dealing tx={sd['n_self_dealing_tx']:,} ({(sd['frac_of_transactions'] or 0):.6%})  "
          f"vol(taker)=${(sd['self_dealing_volume_usdc_taker'] or 0):,.0f}  "
          f"top-wallet share={(sd['top_wallet_share_of_self_dealing_tx'] or 0):.1%}  fill-self-match={rep['fill_level_self_match']}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

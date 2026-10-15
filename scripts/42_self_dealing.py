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

Memory-safe (the box has OOM-killed on uncapped scans): deduped rows are written to
block-range parquet parts, the (tx_hash, wallet) both-sides pass is restricted to
multi-fill transactions (single-fill txs can only self-deal at the fill level), and
DuckDB spills to a large temp dir. Run inside MemoryMax=9G + PRAGMA memory_limit.

  python scripts/42_self_dealing.py --out docs/self_dealing.json --memory-limit 5GB
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
    ap.add_argument("--out", default="docs/self_dealing.json")
    ap.add_argument("--memory-limit", default="5GB")
    args = ap.parse_args()

    tmp = _cfg.DATA_DIR / "_s42_tmp"
    shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='80GB'")

    b0, b1 = con.sql(f"SELECT min(block_number), max(block_number) FROM read_parquet('{TAPE}', union_by_name=true)").fetchone()
    b0, b1 = int(b0), int(b1)
    WHERE = ("t.event='OrderFilled' AND t.exchange IN ('v2_a','v2_b') AND t.price>0 AND t.price<1 "
             "AND t.shares>0 AND t.block_number >= {lo} AND t.block_number < {hi}")
    DEDUP = "QUALIFY row_number() OVER (PARTITION BY t.tx_hash, t.evt_index) = 1"

    # maker-fill records (the "fills"): tx, maker wallet, taker wallet, notional
    F_SEL = f"""SELECT t.tx_hash, lower(t.maker) AS mk, lower(t.taker) AS tk, t.usdc AS notional
        FROM read_parquet('{TAPE}', union_by_name=true) t
        WHERE t.is_taker_order = FALSE AND {WHERE} {DEDUP}"""
    # taker-order records: tx, notional (the trade's dollar value / "volume")
    G_SEL = f"""SELECT t.tx_hash, t.usdc AS notional
        FROM read_parquet('{TAPE}', union_by_name=true) t
        WHERE t.is_taker_order = TRUE AND {WHERE} {DEDUP}"""

    n_fills = build_parts(con, F_SEL, tmp / "f", b0, b1, "maker-fill")
    n_orders = build_parts(con, G_SEL, tmp / "g", b0, b1, "taker-order")
    con.execute(f"CREATE VIEW f AS SELECT * FROM read_parquet('{(tmp/'f'/'*.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW g AS SELECT * FROM read_parquet('{(tmp/'g'/'*.parquet').as_posix()}')")

    # --- totals -------------------------------------------------------------
    print("[totals] distinct tx + notional ...", flush=True)
    ntx = con.sql("SELECT count(DISTINCT tx_hash) FROM f").fetchone()[0]
    f_notional = con.sql("SELECT sum(notional) FROM f").fetchone()[0]
    taker_volume = con.sql("SELECT sum(notional) FROM g").fetchone()[0]
    fill_self_match = con.sql("SELECT count(*) FROM f WHERE mk = tk").fetchone()[0]

    # --- self-dealing (tx-level): a wallet on both sides of one tx -----------
    # Single-fill txs can only self-deal at the fill level (mk=tk), already counted.
    # Restrict the (tx, wallet) both-sides pass to multi-fill txs.
    print("[self-deal] multi-fill tx set ...", flush=True)
    con.execute("CREATE TABLE multitx AS SELECT tx_hash FROM f GROUP BY tx_hash HAVING count(*) > 1")
    n_multitx = con.sql("SELECT count(*) FROM multitx").fetchone()[0]
    print(f"           multi-fill txs = {n_multitx:,}", flush=True)

    print("[self-deal] both-sides (tx, wallet) pass ...", flush=True)
    con.execute("""CREATE TABLE bsw AS
        SELECT tx_hash, w FROM (
            SELECT tx_hash, w, max(ismk) hm, max(istk) ht FROM (
                SELECT fx.tx_hash, fx.mk AS w, 1 ismk, 0 istk FROM f fx SEMI JOIN multitx m ON m.tx_hash = fx.tx_hash
                UNION ALL
                SELECT fx.tx_hash, fx.tk AS w, 0 ismk, 1 istk FROM f fx SEMI JOIN multitx m ON m.tx_hash = fx.tx_hash
            ) GROUP BY tx_hash, w
        ) WHERE hm = 1 AND ht = 1""")

    sd_tx = con.sql("SELECT count(DISTINCT tx_hash) FROM bsw").fetchone()[0]
    # volume of self-dealing txs = their taker-order notional (fall back to maker-fill notional)
    sd_vol_taker = con.sql("SELECT sum(notional) FROM g WHERE tx_hash IN (SELECT DISTINCT tx_hash FROM bsw)").fetchone()[0]
    sd_vol_fill = con.sql("SELECT sum(notional) FROM f WHERE tx_hash IN (SELECT DISTINCT tx_hash FROM bsw)").fetchone()[0]
    top = con.sql("""SELECT w, count(DISTINCT tx_hash) ntx FROM bsw GROUP BY w ORDER BY ntx DESC LIMIT 5""").fetchall()
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
            "n_multifill_tx": int(n_multitx),
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
        "method": "deduped maker-fill + taker-order parts; tx-level both-sides via (tx,wallet) group-by "
                  "restricted to multi-fill txs; fill-level self-match (mk=tk) reported separately.",
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1))
    print(f"wrote {args.out}")
    sd = rep["self_dealing"]
    print(f"  fills={rep['n_maker_fills']:,}  tx={rep['n_transactions']:,}  taker_vol=${rep['taker_volume_usdc']:,.0f}")
    print(f"  self-dealing tx={sd['n_self_dealing_tx']:,} ({(sd['frac_of_transactions'] or 0):.6%})  "
          f"vol(taker)=${(sd['self_dealing_volume_usdc_taker'] or 0):,.0f}  "
          f"top-wallet share={ (sd['top_wallet_share_of_self_dealing_tx'] or 0):.1%}  fill-self-match={rep['fill_level_self_match']}")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

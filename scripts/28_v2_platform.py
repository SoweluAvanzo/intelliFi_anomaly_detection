#!/usr/bin/env python
"""Platform-wide taker PnL / calibration / concentration on the v2 tape —
ALL resolved markets (standard USDC.e + negRisk WRAPPED; derivation verified for both).

Mirrors scripts/27 (v1) so the two are apples-to-apples for a v1-vs-v2 comparison.

v2 tape conventions (proven in docs/audit_2026-09-05.md §1-§2, §7):
  - GROSS taker PnL from MAKER-FILL records (is_taker_order = FALSE): taker = the `taker`
    field, taker_side = OPPOSITE of the maker `side` (== the is_taker_order=TRUE record's
    own side, to the dollar). won_out = (this token's outcome won).
  - TAKER FEE from the TAKER-ORDER records (is_taker_order = TRUE): the fee (fee_raw, pUSD
    6-dec) is charged ONCE per taker order and lives on these rows, ~1.0-1.6% of notional
    (NOT on the maker-fill rows, where fee_raw ~= 0). On these rows the taker wallet is the
    `maker` field. NET = GROSS - taker fee; only NET is comparable to v1 (v1 was ~fee-free).
  - DEDUP by (tx_hash, evt_index) on BOTH record types (chunk overlap double-counts them);
    range-partitioned dedup is exact (dups are within a block) and disk-safe.
  - exchange IN ('v2_a','v2_b') and event = 'OrderFilled' (the Sample-B tape definition).

Winner link: token_id -> ctf_v2_conditions (token0=outcome0 / token1=outcome1) ->
winning_outcome_index; ALL resolved conditions (standard + negRisk).

  python scripts/28_v2_platform.py --out docs/v2_platform.json --memory-limit 6GB
"""
from __future__ import annotations

import argparse
import collections
import csv
import json
import sys
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                        # noqa: E402
import polars as pl                                  # noqa: E402
from intellifi import config as _cfg                 # noqa: E402

TAPE = "data/parquet/tape_v2/**/*.parquet"
REG = "data/parquet/ctf_v2_conditions.parquet"
CLOB = "data/parquet/clob_markets/tokens.parquet"
ATLAS_MAP = _cfg.PARQUET_DIR / "atlas" / "category_to_feeclass_mapping.csv"
STEP = 250_000


def gini_pos(x: np.ndarray) -> float:
    x = np.sort(x[x > 0]); n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())) if n else float("nan")


def build_parts(con, select_sql: str, parts_dir: Path, b0: int, b1: int, tag: str) -> int:
    """Write each block-range partition's deduped rows to its own parquet (memory-safe)."""
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
    ap.add_argument("--out", default="docs/v2_platform.json")
    ap.add_argument("--memory-limit", default="6GB")
    ap.add_argument("--top-k", type=int, default=20)
    args = ap.parse_args()

    import shutil
    tmp = _cfg.DATA_DIR / "_s28_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("SET threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp/'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='40GB'")

    # token -> (outcome_index, winning_outcome_index), ALL resolved conditions
    con.execute(f"""CREATE TABLE tokmap AS
        SELECT lower(token0) AS token_id, 0 AS outcome_index, winning_outcome_index FROM read_parquet('{REG}')
          WHERE token0 IS NOT NULL AND winning_outcome_index IS NOT NULL
        UNION ALL
        SELECT lower(token1), 1, winning_outcome_index FROM read_parquet('{REG}')
          WHERE token1 IS NOT NULL AND winning_outcome_index IS NOT NULL""")

    # token -> primary feeclass (clob tags). negRisk tokens aren't in clob -> 'other'.
    tag2cls = {}
    with open(ATLAS_MAP) as fh:
        for row in csv.DictReader(fh):
            tag2cls[row["category"].strip().lower()] = row["cls"].strip()
    rows = con.sql(f"""SELECT lower(token_id) token_id, any_value(tags) tags
                       FROM read_parquet('{CLOB}') WHERE token_id IS NOT NULL GROUP BY lower(token_id)""").fetchall()
    tl, cl = [], []
    for tok, tags in rows:
        cats = [tag2cls.get(t.strip().lower()) for t in (tags or [])]; cats = [c for c in cats if c]
        tl.append(tok); cl.append(collections.Counter(cats).most_common(1)[0][0] if cats else "other")
    con.register("tokcls_df", pl.DataFrame({"token_id": tl, "cls": cl}).to_arrow())
    con.execute("CREATE TABLE tokcls AS SELECT * FROM tokcls_df")

    b0, b1 = con.sql(f"SELECT min(block_number), max(block_number) FROM read_parquet('{TAPE}', union_by_name=true)").fetchone()
    b0, b1 = int(b0), int(b1)
    WHERE_COMMON = ("t.event='OrderFilled' AND t.exchange IN ('v2_a','v2_b') "
                    "AND t.price>0 AND t.price<1 AND t.shares>0 "
                    "AND t.block_number >= {lo} AND t.block_number < {hi}")
    DEDUP = "QUALIFY row_number() OVER (PARTITION BY t.tx_hash, t.evt_index) = 1"

    # GROSS: maker-fill records (taker = taker field, side = opposite of maker side)
    F_SELECT = f"""
        SELECT lower(t.taker) AS taker, t.price, t.shares,
               CASE WHEN t.side='BUY' THEN 'SELL' ELSE 'BUY' END AS taker_side,
               (CASE WHEN m.outcome_index = m.winning_outcome_index THEN 1 ELSE 0 END) AS won_out,
               t.usdc AS notional, COALESCE(c.cls,'other') AS cls,
               date_trunc('month', t.ts_utc::TIMESTAMP) AS ym
        FROM read_parquet('{TAPE}', union_by_name=true) t
        JOIN tokmap m ON m.token_id = lower(t.token_id)
        LEFT JOIN tokcls c ON c.token_id = lower(t.token_id)
        WHERE t.is_taker_order = FALSE AND {WHERE_COMMON} {DEDUP}"""
    # TAKER FEE: taker-order records (taker wallet = maker field; fee lives here)
    G_SELECT = f"""
        SELECT lower(t.maker) AS taker, t.fee_raw/1e6 AS fee_usdc, t.usdc AS notional,
               COALESCE(c.cls,'other') AS cls, date_trunc('month', t.ts_utc::TIMESTAMP) AS ym
        FROM read_parquet('{TAPE}', union_by_name=true) t
        JOIN tokmap m ON m.token_id = lower(t.token_id)
        LEFT JOIN tokcls c ON c.token_id = lower(t.token_id)
        WHERE t.is_taker_order = TRUE AND {WHERE_COMMON} {DEDUP}"""

    n_fills = build_parts(con, F_SELECT, tmp / "f_parts", b0, b1, "GROSS(maker-fill)")
    n_orders = build_parts(con, G_SELECT, tmp / "g_parts", b0, b1, "FEE(taker-order)")
    con.execute(f"CREATE VIEW f AS SELECT * FROM read_parquet('{(tmp/'f_parts'/'*.parquet').as_posix()}')")
    con.execute(f"CREATE VIEW g AS SELECT * FROM read_parquet('{(tmp/'g_parts'/'*.parquet').as_posix()}')")

    IMPLIED = "(CASE WHEN taker_side='BUY' THEN price ELSE 1-price END)"
    WONBET = "(CASE WHEN (taker_side='BUY' AND won_out=1) OR (taker_side='SELL' AND won_out=0) THEN 1 ELSE 0 END)"
    GROSS = "(CASE WHEN taker_side='BUY' THEN (won_out-price)*shares ELSE (price-won_out)*shares END)"

    rep: dict = {"scope": "v2 tape, ALL resolved markets (standard + negRisk); deduped; exchange v2_a/v2_b; OrderFilled",
                 "side": "taker (aggressor)", "n_linked_maker_fills": int(n_fills), "n_linked_taker_orders": int(n_orders)}

    # gross + calibration (from f); taker fee (from g)
    gv = con.sql(f"""SELECT sum(shares*{IMPLIED})/sum(shares), sum(shares*{WONBET})/sum(shares),
                            sum({GROSS}), sum(notional) FROM f""").fetchone()
    fv = con.sql("SELECT sum(fee_usdc), sum(notional) FROM g").fetchone()
    total_fee = float(fv[0]) if fv[0] is not None else 0.0
    rep["_sign_validation"] = {"size_wt_implied_p": gv[0], "size_wt_hit": gv[1],
        "calibration_gap": (gv[1]-gv[0]) if (gv[0] and gv[1]) else None,
        "gross_taker_pnl": gv[2], "expect": "gap within a few pp of 0 (a flipped side gives ~+-0.5)"}
    rep["fees"] = {"total_taker_fee_usdc": total_fee, "taker_notional_usdc": float(fv[1]) if fv[1] else None,
                   "fee_pct_of_notional": (100*total_fee/fv[1]) if fv[1] else None,
                   "source": "is_taker_order=TRUE records (fee charged once per taker order; ~1.0-1.6% of notional)",
                   "note": "v1 was ~fee-free (gross≈net); the NET number below is what compares to v1's -$86M."}

    # per-category: gross+calib from f, fee from g, net = gross - fee
    fee_by_cls = {r[0]: float(r[1] or 0) for r in con.sql("SELECT cls, sum(fee_usdc) FROM g GROUP BY 1").fetchall()}
    rep["per_category"] = [
        {"cls": r[0], "n_fills": int(r[1]), "mean_implied_p": r[2], "hit_rate": r[3],
         "calibration_gap": r[4], "gross_pnl": r[5], "taker_fee": fee_by_cls.get(r[0], 0.0),
         "net_pnl": (r[5] - fee_by_cls.get(r[0], 0.0)) if r[5] is not None else None}
        for r in con.sql(f"""
            SELECT cls, count(*) n, sum(shares*{IMPLIED})/nullif(sum(shares),0),
                   sum(shares*{WONBET})/nullif(sum(shares),0),
                   (sum(shares*{WONBET})-sum(shares*{IMPLIED}))/nullif(sum(shares),0), sum({GROSS})
            FROM f GROUP BY 1 ORDER BY n DESC""").fetchall()]

    # per-month (era heterogeneity): gross from f, fee from g, net
    fee_by_ym = {str(r[0]): float(r[1] or 0) for r in con.sql("SELECT ym, sum(fee_usdc) FROM g GROUP BY 1").fetchall()}
    rep["per_month"] = [
        {"month": str(r[0])[:7], "n_fills": int(r[1]), "gross_pnl": r[2],
         "taker_fee": fee_by_ym.get(str(r[0]), 0.0), "net_pnl": r[2] - fee_by_ym.get(str(r[0]), 0.0),
         "calibration_gap": r[3]}
        for r in con.sql(f"""SELECT ym, count(*) n, sum({GROSS}),
                   (sum(shares*{WONBET})-sum(shares*{IMPLIED}))/nullif(sum(shares),0)
            FROM f GROUP BY 1 ORDER BY 1""").fetchall()]

    # per-wallet NET = gross(by taker field) - fee(by taker wallet = maker field on is_tk rows)
    con.execute(f"CREATE TABLE wg AS SELECT taker AS w, SUM({GROSS}) gross FROM f GROUP BY taker")
    con.execute("CREATE TABLE wf AS SELECT taker AS w, SUM(fee_usdc) fee FROM g GROUP BY taker")
    con.execute("""CREATE TABLE wp AS
        SELECT COALESCE(wg.w, wf.w) w, COALESCE(wg.gross,0) gross, COALESCE(wf.fee,0) fee,
               COALESCE(wg.gross,0) - COALESCE(wf.fee,0) net
        FROM wg FULL OUTER JOIN wf ON wg.w = wf.w""")
    ag = con.sql("SELECT count(*), SUM(gross), SUM(fee), SUM(net), SUM(net>0), SUM(net<0) FROM wp").fetchone()
    rep["aggregate_taker_pnl"] = {
        "gross_pnl_usdc": float(ag[1]) if ag[1] is not None else None,
        "total_taker_fee_usdc": float(ag[2]) if ag[2] is not None else None,
        "net_pnl_usdc": float(ag[3]) if ag[3] is not None else None,
        "n_wallets": int(ag[0]), "n_net_winners": int(ag[4]), "n_net_losers": int(ag[5]),
        "interpretation": "NET < 0 => takers lose to makers after fees (comparable to v1's -$86M gross≈net)"}
    pos = con.sql("SELECT net FROM wp WHERE net>0").fetchnumpy()["net"]
    rep["net_pnl_gini_positive"] = gini_pos(np.asarray(pos, dtype=float))
    rep["top_winners"] = [{"wallet": r[0], "net_pnl_usdc": float(r[1])} for r in con.sql(f"SELECT w,net FROM wp ORDER BY net DESC LIMIT {args.top_k}").fetchall()]
    rep["top_losers"] = [{"wallet": r[0], "net_pnl_usdc": float(r[1])} for r in con.sql(f"SELECT w,net FROM wp ORDER BY net ASC LIMIT {args.top_k}").fetchall()]
    rep["caveats"] = [
        "ALL resolved markets (standard + negRisk); still-open markets excluded (no winner).",
        "GROSS = taker realised PnL (maker-fill records, side=opposite of maker side, proven == the "
        "is_taker_order=TRUE record's own side). Raw per-fill (uncovered sells not scaled).",
        "TAKER FEE from is_taker_order=TRUE records (fee lives there, ~1.0-1.6% of notional; the "
        "maker-fill fee_raw is ~0). NET = gross - fee; only NET compares to v1 (v1 ~fee-free).",
        "DEDUPED by (tx_hash,evt_index) on both record types (chunk overlap double-counts).",
        "Outcome-dependent (survivorship) — descriptive, not skill. per_month shows the GROSS sign is "
        "heterogeneous across eras, but NET is negative every month (the ~1.17% fee dominates).",
        "Per-category via clob tags; negRisk tokens aren't in clob so negRisk fills fall to 'other'.",
    ]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1, default=str))
    print(f"wrote {args.out}")
    sv = rep["_sign_validation"]; fe = rep["fees"]; a = rep["aggregate_taker_pnl"]
    print(f"SIGN-CHECK: implied={sv['size_wt_implied_p']:.3f} hit={sv['size_wt_hit']:.3f} gap={sv['calibration_gap']:+.4f}")
    print(f"FEES: {fe['total_taker_fee_usdc']:,.0f} USDC = {fe['fee_pct_of_notional']:.3f}% of taker notional")
    print(f"v2 taker PnL: GROSS {a['gross_pnl_usdc']:,.0f} - FEE {a['total_taker_fee_usdc']:,.0f} = NET {a['net_pnl_usdc']:,.0f} USDC")
    print(f"  over {a['n_wallets']:,} wallets ({a['n_net_winners']:,}W/{a['n_net_losers']:,}L net); Gini(+net)={rep['net_pnl_gini_positive']:.3f}")
    print("PER-MONTH gross / fee / net:")
    for r in rep["per_month"]:
        print(f"  {r['month']}  n={r['n_fills']:>11,}  gross={r['gross_pnl']:>+13,.0f}  fee={r['taker_fee']:>12,.0f}  net={r['net_pnl']:>+13,.0f}  gap={r['calibration_gap']:+.4f}")
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

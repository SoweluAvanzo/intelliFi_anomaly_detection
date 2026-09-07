#!/usr/bin/env python
"""Stage 17 (Stage II, Sample B): cohort-descriptive statistics on the v2 tape.

Pure-local / network-free: reads only ``data/parquet/tape_v2`` (deduped by
``(tx_hash, evt_index)``) for a block window and writes the descriptive JSON that
the cross-cohort assembler + scripts/18 confirmatory inference consume. Designed to
run OFFLINE and unattended over cohorts 2-6 (all 100% locally covered).

Validation contract: on the cohort-1 window (88,080,000-88,843,826) it must
reproduce ``docs/cohort_reports/cohort1_descriptive.json`` exactly.

Populations (v2 OrderFilled tape, exchanges v2_a/v2_b):
* a row with ``taker`` == an exchange address is the taker-ORDER aggregate record
  (``is_taker_order``); its ``maker`` field is the taker wallet.
* a row with a wallet ``taker`` is a maker FILL (``maker`` = liquidity provider).
So: n_fills = all rows; makers/H6 = maker-fills; taker-order metrics (fee share,
size deciles, order size, round-trips) = taker-order records.

    python scripts/17_cohort_descriptive.py --from-block A --to-block B --cohort N \
        --out docs/cohort_reports/cohortN_descriptive.json
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from intellifi.fills import TAPE_V2_DIR, EXCHANGES_V2  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--from-block", type=int, default=os.getenv("INTELLIFI_V2_FROM_BLOCK"))
    ap.add_argument("--to-block", type=int, default=os.getenv("INTELLIFI_V2_TO_BLOCK"))
    ap.add_argument("--cohort", default=None, help="label only")
    ap.add_argument("--out", required=True)
    ap.add_argument("--dedup", action="store_true",
                    help="dedup overlapping chunks by (tx_hash, evt_index) via a hashed-key "
                         "min-rowid pass. Cohort 1 has no overlaps (skip); cohorts 2-6/genesis "
                         "do (the driver should pass this).")
    ap.add_argument("--memory-limit", default="12GB",
                    help="DuckDB memory_limit; the 84M-row dedup needs ~8-10GB. This box has "
                         "31GB, so 12GB is safe with headroom; lower it on a smaller machine.")
    args = ap.parse_args()
    if args.from_block is None or args.to_block is None:
        print("need --from-block/--to-block (or INTELLIFI_V2_FROM_BLOCK/TO_BLOCK)", file=sys.stderr)
        return 2
    A, B = int(args.from_block), int(args.to_block)
    glob = (TAPE_V2_DIR / "blocks=*" / "part.parquet").as_posix()
    exch = ",".join(f"'{a}'" for a in EXCHANGES_V2.values())

    # A FILE-BACKED db on real disk: an in-memory db keeps the 84M-row temp table +
    # window-sort in RAM and OOMs; a file-backed db spills table storage AND operators
    # to disk. /tmp is tmpfs (RAM) here, so the db + temp_directory MUST live under
    # DATA_DIR (real disk). Threads capped to bound peak memory of the parallel scan.
    from intellifi import config as _cfg
    _tmp = _cfg.DATA_DIR / "_s17_tmp"
    _tmp.mkdir(parents=True, exist_ok=True)
    dbfile = _tmp / f"s17_{A}_{B}.duckdb"
    if dbfile.exists():
        dbfile.unlink()
    con = duckdb.connect(str(dbfile))
    con.execute("SET TimeZone='UTC'")
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute("SET preserve_insertion_order=false")
    con.execute("SET threads=3")
    con.execute(f"SET temp_directory='{_tmp.as_posix()}'")
    con.execute("SET max_temp_directory_size='200GB'")

    # Deduped window, slimmed to the columns the metrics need, materialised once.
    # Streaming materialise of the window into a file-backed table (low peak RAM;
    # the wide-string columns make any grouping/sorting of all 84M rows expensive,
    # so we do NOT sort/group here). Deduplication of overlapping chunks (only
    # cohorts 2-6/genesis have overlaps; cohort 1 has none) is a cheap hashed-key
    # pass applied afterwards only when --dedup is set.
    con.execute(f"""
        CREATE TABLE t0 AS
        SELECT maker, taker, token_id, side, builder, ts_utc, shares, tx_hash, evt_index,
               usdc, fee_raw, (taker IN ({exch})) AS is_tk
        FROM read_parquet('{glob}', hive_partitioning = true)
        WHERE event = 'OrderFilled' AND exchange IN ('v2_a','v2_b')
          AND block_number BETWEEN {A} AND {B};
    """)
    if args.dedup:
        # Keep one row per (tx_hash, evt_index). Group on the 64-bit HASH of the key
        # (collision prob over 84M rows ~2e-4, negligible) carrying only min(rowid) —
        # a narrow aggregate state (~1 GB) that fits in memory, unlike grouping the
        # wide columns. Then keep only those rowids from the full table.
        con.execute("CREATE TABLE keep AS SELECT min(rowid) AS rid FROM t0 GROUP BY hash(tx_hash, evt_index);")
        con.execute("CREATE TABLE t AS SELECT * FROM t0 WHERE rowid IN (SELECT rid FROM keep);")
    else:
        con.execute("CREATE VIEW t AS SELECT * FROM t0;")  # no overlaps: view avoids a copy

    rep: dict = {"cohort": str(args.cohort) if args.cohort is not None else None,
                 "block_range": [A, B]}

    rep["n_fills"] = con.execute("SELECT count(*) FROM t").fetchone()[0]
    # distinct wallets seen in either role across all rows (on taker-order records the
    # 'maker' field is the taker wallet and 'taker' is the exchange address).
    rep["n_makers"] = con.execute("SELECT count(DISTINCT maker) FROM t").fetchone()[0]
    rep["n_takers"] = con.execute("SELECT count(DISTINCT taker) FROM t").fetchone()[0]
    # wash / self-match: a maker fill whose maker and taker wallet are the same.
    rep["self_match_fills"] = con.execute(
        "SELECT count(*) FROM t WHERE NOT is_tk AND maker = taker").fetchone()[0]

    # H6 maker concentration — over maker fills with positive notional, by maker.
    h6 = con.execute("""
        WITH m AS (
            SELECT maker, SUM(usdc) AS notl, COUNT(*) AS fills
            FROM t WHERE NOT is_tk GROUP BY maker HAVING SUM(usdc) > 0
        ), tot AS (SELECT SUM(notl) AS N, SUM(fills) AS F, COUNT(*) AS nm FROM m),
        sh AS (SELECT m.notl, m.fills, m.notl/tot.N AS s FROM m, tot),
        t10 AS (SELECT SUM(notl) tn, SUM(fills) tf FROM (
                    SELECT notl, fills FROM m ORDER BY notl DESC LIMIT 10))
        SELECT (SELECT SUM(s*s) FROM sh) AS hhi,
               (SELECT tn FROM t10)/(SELECT N FROM tot) AS top10_notl,
               (SELECT tf FROM t10)/(SELECT F FROM tot) AS top10_fill,
               (SELECT nm FROM tot) AS n_makers
    """).fetchone()
    rep["H6_maker_concentration"] = {"hhi_notional": h6[0], "top10_notional_share": h6[1],
                                     "top10_fill_share": h6[2], "n_makers": h6[3]}

    # H5 fee incidence by taker-order notional decile.
    h5 = con.execute("""
        WITH tk AS (
            SELECT usdc, fee_raw/1e6 AS fee, ntile(10) OVER (ORDER BY usdc) AS d
            FROM t WHERE is_tk
        )
        SELECT d, count(*) n, median(usdc) med, avg(fee/usdc*100) mean_fee_pct
        FROM tk GROUP BY d ORDER BY d
    """).fetchall()
    rep["H5_fee_incidence_by_size_decile"] = [
        {"decile": int(d), "n": int(n), "median_notional": med, "mean_fee_pct": mfp}
        for d, n, med, mfp in h5]

    rep["taker_orders_fee_paying_share"] = con.execute(
        "SELECT avg((fee_raw>0)::int) FROM t WHERE is_tk").fetchone()[0]

    osz = con.execute("""
        SELECT (fee_raw>0) AS fee_paying, count(*) n,
               exp(avg(ln(usdc))) geomean, median(usdc) med
        FROM t WHERE is_tk AND usdc > 0 GROUP BY 1 ORDER BY 1
    """).fetchall()
    rep["order_size_by_fee"] = [
        {"fee_paying": bool(fp), "n": int(n), "geomean_notional": gm, "median_notional": md}
        for fp, n, gm, md in osz]

    # Builder attribution — over all rows, by builder (12-char prefix as stored).
    b = con.execute("""
        WITH b AS (
            SELECT builder, count(*) fills, SUM(usdc) notl, avg((fee_raw>0)::int) fee_paying
            FROM t GROUP BY builder
        ), tot AS (SELECT SUM(notl) N, COUNT(*) nb FROM b)
        SELECT (SELECT nb FROM tot) n_builders,
               (SELECT SUM((notl/(SELECT N FROM tot))*(notl/(SELECT N FROM tot))) FROM b) hhi
    """).fetchone()
    top8 = con.execute("""
        WITH b AS (
            SELECT builder, count(*) fills, SUM(usdc) notl, avg((fee_raw>0)::int) fee_paying
            FROM t GROUP BY builder
        ), tot AS (SELECT SUM(notl) N FROM b)
        SELECT substr(builder, 1, 12) AS builder, fills, notl/(SELECT N FROM tot) AS notional_share, fee_paying
        FROM b ORDER BY notl DESC LIMIT 8
    """).fetchall()
    rep["builder_attribution"] = {
        "n_builders": int(b[0]), "notional_hhi": b[1],
        "top8": [{"builder": bl, "fills": int(f), "notional_share": ns, "fee_paying": fp}
                 for bl, f, ns, fp in top8]}

    # H1a round-trip share by fee — the audit-corrected one-to-one wash match
    # (coordination.wash_round_trips): a BUY followed by a SELL of the same token by
    # the same taker wallet within 600 s with size-overlap >= 0.5, each buy keeping
    # its nearest sell and each sell its nearest buy. A taker order is a "round-trip"
    # order if its tx is a buy or sell leg of a match; rt_share = flagged/total by fee.
    h1a = con.execute("""
        WITH tk AS (
            SELECT maker AS wallet, token_id AS asset, side, ts_utc,
                   shares AS size, tx_hash, (fee_raw>0) AS fee_paying
            FROM t WHERE is_tk
        ),
        base AS (SELECT * FROM tk WHERE size > 0 AND side IN ('BUY','SELL') AND ts_utc IS NOT NULL),
        cand AS (
            SELECT b.wallet, b.asset, b.tx_hash AS buy_tx, s.tx_hash AS sell_tx,
                   EPOCH(s.ts_utc) - EPOCH(b.ts_utc) AS gap
            FROM base b JOIN base s
              ON b.wallet = s.wallet AND b.asset = s.asset
             AND b.side = 'BUY' AND s.side = 'SELL'
             AND s.ts_utc > b.ts_utc AND EPOCH(s.ts_utc) - EPOCH(b.ts_utc) <= 600
             AND LEAST(b.size, s.size) / GREATEST(b.size, s.size) >= 0.5
        ),
        ns AS (SELECT * FROM (
                 SELECT *, row_number() OVER (PARTITION BY wallet, asset, buy_tx ORDER BY gap, sell_tx) rk_b
                 FROM cand) WHERE rk_b = 1),
        matched AS (SELECT * FROM (
                 SELECT *, row_number() OVER (PARTITION BY wallet, asset, sell_tx ORDER BY gap, buy_tx) rk_s
                 FROM ns) WHERE rk_s = 1),
        rt_tx AS (SELECT buy_tx AS tx FROM matched UNION SELECT sell_tx FROM matched)
        SELECT tk.fee_paying, count(*) n,
               count(*) FILTER (WHERE tk.tx_hash IN (SELECT tx FROM rt_tx))::DOUBLE / count(*) AS rt_share
        FROM tk GROUP BY tk.fee_paying ORDER BY tk.fee_paying
    """).fetchall()
    rep["H1a_roundtrip_share_by_fee"] = [
        {"fee_paying": bool(fp), "rt_share": rs, "n": int(n)} for fp, n, rs in h1a]

    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(args.out).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(rep, indent=1, default=str))
    tmp.replace(args.out)  # atomic: a present out-file means "done" for the driver
    print(f"wrote {args.out}: n_fills={rep['n_fills']:,} taker_fee_share={rep['taker_orders_fee_paying_share']:.5f}")

    con.close()
    for p in (dbfile, dbfile.with_suffix(".duckdb.wal")):
        try:
            p.unlink()
        except OSError:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())

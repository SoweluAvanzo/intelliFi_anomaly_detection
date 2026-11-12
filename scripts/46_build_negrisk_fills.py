#!/usr/bin/env python
"""Build the negRisk YES-token map and extract its OrderFilled fills from the v2 tape (fee era).

Durable substrate for RQ2 price-correction attribution (scripts/41). Writes
`data/parquet/negrisk_v2/{map,fills}.parquet`. Pure transform of cached data (no network).

MEMORY-SAFE: file-backed DuckDB + spill. Launch inside a scope:
  systemd-run --user --scope -p MemoryMax=10G .venv/bin/python scripts/46_build_negrisk_fills.py
Add --test N to extract from only the first N tape files (smoke test).
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                   # noqa: E402
from intellifi import config as _cfg            # noqa: E402
from intellifi import negrisk                   # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["tape", "archive"], default="tape",
                    help="tape = v2/fee era (default); archive = v1/pre-fee")
    ap.add_argument("--memory-limit", default="6GB")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--test", type=int, default=0, help="tape only: extract from the first N tape files")
    args = ap.parse_args()

    outdir = _cfg.PARQUET_DIR / ("negrisk_v2" if args.source == "tape" else "negrisk_v1")
    outdir.mkdir(parents=True, exist_ok=True)
    map_path = str(outdir / "map.parquet")
    fills_path = str(outdir / ("fills_test.parquet" if args.test else "fills.parquet"))

    tmp = _cfg.DATA_DIR / "_s40_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp / 'spill').as_posix()}'")
    con.execute("SET max_temp_directory_size='60GB'")

    if args.source == "archive":
        negrisk.extract_archive_fills(con, fills_path)
        n = con.execute(f"SELECT count(*) FROM '{fills_path}'").fetchone()[0]
        toks = con.execute(f"SELECT count(DISTINCT tok) FROM '{fills_path}'").fetchone()[0]
        fams = con.execute(f"SELECT count(DISTINCT family) FROM '{fills_path}'").fetchone()[0]
        print(f"v1 archive fills: {n:,} rows, {toks:,} YES tokens, {fams:,} families -> {fills_path}")
        con.close()
        shutil.rmtree(tmp, ignore_errors=True)
        return 0

    negrisk.build_map(con, map_path)
    st = negrisk.map_stats(con, map_path)
    print(f"map: {st['conditions']:,} conditions, {st['families']:,} families, "
          f"YES==token0 {st['yes_is_token0_frac']}, winners/family {st['winners_per_family']}")

    if args.test:
        tape = sorted((_cfg.PARQUET_DIR / "tape_v2").glob("**/part.parquet"))[: args.test]
        glob_expr = "[" + ",".join("'" + str(f) + "'" for f in tape) + "]"
        con.execute(f"CREATE OR REPLACE VIEW _map AS SELECT yes_token_id, family, condition_id, resolved_ts_utc, yes_won FROM '{map_path}'")
        con.execute(f"""COPY (
          SELECT m.family, m.condition_id, m.yes_token_id, m.resolved_ts_utc, m.yes_won,
                 t.ts_utc, t.block_number, t.price, t.maker, t.taker, t.side,
                 t.usdc, t.shares, t.fee_raw, t.is_taker_order, t.tx_hash, t.evt_index
          FROM read_parquet({glob_expr}) t JOIN _map m ON t.token_id = m.yes_token_id
          WHERE t.exchange IN ('v2_a','v2_b') AND t.event='OrderFilled'
                AND t.price>0 AND t.price<1) TO '{fills_path}' (FORMAT parquet)""")
    else:
        negrisk.extract_tape_fills(con, map_path, fills_path)

    n = con.execute(f"SELECT count(*) FROM '{fills_path}'").fetchone()[0]
    toks = con.execute(f"SELECT count(DISTINCT yes_token_id) FROM '{fills_path}'").fetchone()[0]
    fams = con.execute(f"SELECT count(DISTINCT family) FROM '{fills_path}'").fetchone()[0]
    print(f"fills: {n:,} rows, {toks:,} YES tokens, {fams:,} families -> {fills_path}")
    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

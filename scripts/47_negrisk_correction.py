#!/usr/bin/env python
"""RQ2 price-correction attribution + analysis on negRisk families (fee era).

Reads `data/parquet/negrisk_v2/fills.parquet` (scripts/40), reconstructs each family's running
price-sum and credits the aggressor of each corrective trade, then reports concentration,
distinctness from volume/profit, OOS persistence, and profitability net of fees.
Writes `data/export/rq2_v2_{wallets,events}.parquet`. See `docs/FEE_EFFECTS.md`.

MEMORY-SAFE. Launch inside a scope:
  systemd-run --user --scope -p MemoryMax=11G .venv/bin/python scripts/47_negrisk_correction.py
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                   # noqa: E402
from intellifi import config as _cfg            # noqa: E402
from intellifi import correction                # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["v2", "v1"], default="v2",
                    help="v2 = fee era (tape); v1 = pre-fee (archive)")
    ap.add_argument("--fills", default=None, help="defaults per source")
    ap.add_argument("--out-prefix", default=None, help="defaults per source")
    ap.add_argument("--memory-limit", default="6GB")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--high", type=float, default=correction.HIGH)
    ap.add_argument("--low", type=float, default=correction.LOW)
    args = ap.parse_args()
    sub = {"v2": "negrisk_v2", "v1": "negrisk_v1"}[args.source]
    args.fills = args.fills or str(_cfg.PARQUET_DIR / sub / "fills.parquet")
    args.out_prefix = args.out_prefix or str(_cfg.DATA_DIR / "export" / f"rq2_{args.source}")
    Path(args.out_prefix).parent.mkdir(parents=True, exist_ok=True)

    tmp = _cfg.DATA_DIR / "_s41_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp / 'spill').as_posix()}'")
    con.execute("SET max_temp_directory_size='60GB'")

    if args.source == "v2":
        n = correction.build_canonical(con, args.fills)
    else:
        n = correction.build_canonical_v1(con, args.fills)
    print(f"canonical taker trades: {n:,}", flush=True)
    summ = correction.attribute(con, args.out_prefix, high=args.high, low=args.low)
    print(f"attribution: {json.dumps(summ)}", flush=True)
    print("\n=== RQ2 analysis ===")
    print(json.dumps(correction.analyze(args.out_prefix), indent=2))

    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

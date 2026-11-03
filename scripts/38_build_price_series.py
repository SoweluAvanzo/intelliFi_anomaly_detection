#!/usr/bin/env python
"""Build the per-market price-at-horizon series for the forecast-quality RQ (calibration).

Pure transform of cached data (no network): one memory-safe full pass over the v2 tape
(`data/parquet/tape_v2`) joined to the resolution registry (`ctf_v2_conditions.parquet`)
and CLOB metadata (`clob_markets/tokens.parquet`). Encodes the six v2-tape read rules and
emits one analysis-ready row per traded resolved-binary market. See `docs/PRICE_SERIES_RQ1.md`
for the column dictionary, the rules, and the horizon-coverage table.

The price source is the tape, NOT `prices_history` (a stale 19-market Stage-I snapshot).

MEMORY-SAFE: file-backed DuckDB, memory_limit (default 8GB) + spill. Launch inside a scope:

  systemd-run --user --scope -p MemoryMax=10G \\
      .venv/bin/python scripts/38_build_price_series.py --out data/export/price_series_rq1.parquet
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                      # noqa: E402
from intellifi import config as _cfg               # noqa: E402
from intellifi import price_series                 # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default=str(_cfg.DATA_DIR / "export" / "price_series_rq1.parquet"))
    ap.add_argument("--memory-limit", default="8GB")
    ap.add_argument("--threads", type=int, default=6)
    ap.add_argument("--no-verify", action="store_true", help="skip the data-quality / validity checks")
    args = ap.parse_args()

    tmp = _cfg.DATA_DIR / "_s38_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp / 'spill').as_posix()}'")
    con.execute("SET max_temp_directory_size='60GB'")

    out = price_series.build_price_series(con, args.out)
    print(f"wrote {out}")
    if not args.no_verify:
        print("\n=== verification ===")
        price_series.verify(con, out)

    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

#!/usr/bin/env python
"""Maker-rebate accounting for the RQ2 correctors (does the fee's rebate offset their taker fees?).

Reads `data/export/rq2_v2_correctors.parquet` (from scripts/47) and the v2 tape; writes per-corrector
taker fees + modeled maker rebate to `data/export/rq2_v2_rebates.parquet`. See `docs/FEE_EFFECTS.md`.

MEMORY-SAFE (full-tape scan, deduped). Launch inside a scope:
  systemd-run --user --scope -p MemoryMax=10G .venv/bin/python scripts/50_maker_rebate.py
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
from intellifi import rebate                     # noqa: E402

OUT = _cfg.DATA_DIR / "export"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--memory-limit", default="5GB")
    ap.add_argument("--threads", type=int, default=4)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = _cfg.DATA_DIR / "_s50_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp / 'spill').as_posix()}'")
    con.execute("SET max_temp_directory_size='60GB'")

    summ = rebate.compute(con, str(OUT / "rq2_v2_correctors.parquet"), str(OUT / "rq2_v2_rebates.parquet"))
    (OUT / "rq2_v2_rebate_summary.json").write_text(json.dumps(summ, indent=2))
    print(json.dumps(summ, indent=2))

    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

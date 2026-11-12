#!/usr/bin/env python
"""Fee incidence / regressivity from the v2 tape (assumption-free, actual fee_raw).

Writes `data/export/incidence_{overall,by_size,by_price}.{json,csv}`. See `docs/FEE_EFFECTS.md`.

MEMORY-SAFE (full-tape scan). Launch inside a scope:
  systemd-run --user --scope -p MemoryMax=9G .venv/bin/python scripts/43_fee_incidence.py
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                   # noqa: E402
from intellifi import config as _cfg            # noqa: E402
from intellifi import incidence                 # noqa: E402

OUT = _cfg.DATA_DIR / "export"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = _cfg.DATA_DIR / "_s43_tmp"
    shutil.rmtree(tmp, ignore_errors=True)
    tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute("PRAGMA memory_limit='5GB'")
    con.execute("PRAGMA threads=6")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp / 'spill').as_posix()}'")
    con.execute("SET max_temp_directory_size='60GB'")

    r = incidence.compute(con)
    (OUT / "incidence_overall.json").write_text(json.dumps({k: float(v) for k, v in r["overall"].items()}, indent=2))
    r["by_size"].to_csv(OUT / "incidence_by_size.csv", index=False)
    r["by_price"].to_csv(OUT / "incidence_by_price.csv", index=False)
    print("=== overall ===", json.dumps({k: float(v) for k, v in r["overall"].items()}, indent=2))
    print("\n=== by taker size decile ===\n", r["by_size"].to_string(index=False))
    print("\n=== by price region ===\n", r["by_price"].to_string(index=False))

    con.close()
    shutil.rmtree(tmp, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

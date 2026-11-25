#!/usr/bin/env python
"""Fee incidence / regressivity from the v2 record (assumption-free, actual fee_raw).

Runs intellifi.incidence.compute on BOTH scopes:
  * whole-platform (raw v2 tape, all markets)
  * negRisk only (data/parquet/negrisk_v2/fills.parquet)
and writes the figure-ready docs/fee_incidence_platform.json (both scopes: overall, by trader-size decile,
by price region, top-1%/10% fee concentration, 500-pt fee Lorenz), plus the whole-platform CSVs under
data/export/. scripts/57 consumes the JSON (no hardcoded series, no scratchpad intermediates).

MEMORY-SAFE: the library uses a plain GROUP BY (no window dedup), so memory stays ~1GB even over the 47G
tape. Still launch inside a scope as a belt:
  systemd-run --user --scope -p MemoryMax=6G .venv/bin/python scripts/49_fee_incidence.py
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
NEGRISK_FILLS = _cfg.PARQUET_DIR / "negrisk_v2" / "fills.parquet"
JSON_OUT = REPO / "docs" / "fee_incidence_platform.json"


def _ser(rep: dict) -> dict:
    """DataFrames -> records; numpy scalars -> float, for JSON."""
    return {"scope": rep["scope"], "note": rep["note"],
            "overall": {k: float(v) for k, v in rep["overall"].items()},
            "by_size": rep["by_size"].to_dict("records"),
            "by_price": rep["by_price"].to_dict("records"),
            "concentration": {k: float(v) for k, v in rep["concentration"].items()},
            "lorenz": rep["lorenz"].to_dict("records")}


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = _cfg.DATA_DIR / "_s49_tmp"
    shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute("PRAGMA memory_limit='3GB'"); con.execute("PRAGMA threads=2")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp / 'spill').as_posix()}'"); con.execute("SET max_temp_directory_size='70GB'")
    import atexit, signal
    def _cleanup(*_a):
        try: con.close()
        except Exception: pass
        shutil.rmtree(tmp, ignore_errors=True)
    atexit.register(_cleanup)
    for _s in (signal.SIGTERM, signal.SIGINT):
        signal.signal(_s, lambda *_a: (_cleanup(), sys.exit(1)))

    plat = incidence.compute(con, source="tape")
    neg = incidence.compute(con, source=str(NEGRISK_FILLS))

    JSON_OUT.write_text(json.dumps({"platform": _ser(plat), "negrisk": _ser(neg)}, indent=1))
    # whole-platform CSVs (backward compatible)
    plat["by_size"].to_csv(OUT / "incidence_by_size.csv", index=False)
    plat["by_price"].to_csv(OUT / "incidence_by_price.csv", index=False)
    (OUT / "incidence_overall.json").write_text(json.dumps({k: float(v) for k, v in plat["overall"].items()}, indent=2))

    print(f"wrote {JSON_OUT.relative_to(REPO)}")
    for lab, r in (("PLATFORM", plat), ("negRisk", neg)):
        o = r["overall"]
        print(f"\n=== {lab}: {int(o['n_takers']):,} takers | eff {o['eff_rate_pct']}% "
              f"| top1%-of-payers {r['concentration']['top1pct_fee_share']}% of fees ===")
        print(r["by_size"][["sz", "eff_rate_pct", "longshot_share", "med_price"]].to_string(index=False))

    _cleanup()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

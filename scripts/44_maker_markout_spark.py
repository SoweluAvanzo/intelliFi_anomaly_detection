#!/usr/bin/env python
"""RQ2 (mechanism) — maker MARKOUT on the v2 tape, PySpark engine (optional).

This is the **alternative** engine for the maker-markout result. It computes the
exact same statistic as ``scripts/40_maker_markout.py`` (DuckDB, the default used
for replication) on Apache Spark, so a user can run the analysis either way:

    # as we do now (DuckDB, single node, no extra install):
    python scripts/40_maker_markout.py --out docs/maker_markout.json

    # the same result on PySpark (local JVM — no cluster, no Databricks):
    pip install -e '.[spark]'
    python scripts/44_maker_markout_spark.py --out docs/maker_markout_spark.json --driver-memory 8g

Both are validated to agree on identical input by ``scripts/45_validate_markout_spark.py``.
Adding this changes nothing in the DuckDB pipeline — ``scripts/40`` remains the
source of truth. See ``docs/SPARK_MARKOUT.md`` and ``src/intellifi/spark_markout.py``.

``--file-slice``/``--limit-files`` select the same sorted tape files as scripts/40,
so a small slice gives a fast, reproducible cross-engine check without a cluster.

Requires Java 17 or 21 (PySpark 4.x); on this workstation Java 21 is present.
"""
from __future__ import annotations

import argparse
import glob
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
from intellifi.spark_markout import HORIZONS, markout_report

TAPE = "data/parquet/tape_v2/**/*.parquet"


def select_files(tape: str, file_slice: str | None, limit_files: int) -> list[str]:
    """Resolve the tape file list exactly as scripts/40 does (sorted glob, then slice)."""
    files = sorted(glob.glob(tape, recursive=True))
    if file_slice:
        lo, hi = file_slice.split(":")
        files = files[int(lo) : int(hi)]
    elif limit_files:
        files = files[:limit_files]
    return files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="docs/maker_markout_spark.json")
    ap.add_argument("--tape", default=TAPE)
    ap.add_argument("--file-slice", default=None, help="'LO:HI' python slice of the sorted tape files (matches scripts/40)")
    ap.add_argument("--limit-files", type=int, default=0, help="use only the first N tape files")
    ap.add_argument("--master", default="local[*]", help="Spark master (default: all local cores)")
    ap.add_argument("--shuffle-partitions", type=int, default=64)
    ap.add_argument("--driver-memory", default="4g")
    args = ap.parse_args()

    files = select_files(args.tape, args.file_slice, args.limit_files)
    if not files:
        print(f"no tape files matched {args.tape!r}", file=sys.stderr)
        return 2

    from pyspark.sql import SparkSession

    spark = (
        SparkSession.builder.appName("intellifi-maker-markout")
        .master(args.master)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", str(args.shuffle_partitions))
        .config("spark.driver.memory", args.driver_memory)
        .config("spark.sql.adaptive.enabled", "true")
        .getOrCreate()
    )
    spark.sparkContext.setLogLevel("WARN")

    t0 = time.time()
    try:
        rep = markout_report(spark, files, HORIZONS)
    finally:
        spark.stop()

    rep["n_tape_files"] = len(files)
    rep["elapsed_s"] = round(time.time() - t0, 1)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rep, indent=1, default=str))

    print(f"wrote {args.out}  ({rep['elapsed_s']}s, {len(files)} files, {rep['n_maker_fills']:,} maker fills)")
    for r in rep["curve"]:
        if r["dollar_wtd_markout_ps"] is None:
            print(f"  D={r['horizon_s']:>6}s cov={r['coverage']:,} (no matches)")
        else:
            print(
                f"  D={r['horizon_s']:>6}s cov={r['coverage']:>11,} "
                f"dw_mko={r['dollar_wtd_markout_ps']:+.6f} neg={r['frac_negative']:.3f} "
                f"spear={(r['spearman_vol_markout'] or 0.0):+.3f}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

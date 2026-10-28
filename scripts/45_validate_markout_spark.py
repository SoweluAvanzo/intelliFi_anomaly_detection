#!/usr/bin/env python
"""Cross-engine validation: PySpark maker-markout vs the DuckDB source of truth.

Runs ``scripts/40_maker_markout.py`` (DuckDB) and ``scripts/44_maker_markout_spark.py``
(PySpark) on an IDENTICAL slice of the tape and diffs their per-horizon curves,
metric by metric. On the same input the two engines must agree to floating-point
tolerance (counts exactly). This is the evidence behind "the two engines produce
the same result": it drives the *shipped* DuckDB pipeline, it does not re-derive it.

    pip install -e '.[spark]'
    python scripts/45_validate_markout_spark.py --file-slice 0:40

Compare a full PySpark run against the shipped DuckDB result instead:

    python scripts/45_validate_markout_spark.py \
        --against docs/maker_markout.json --spark-out docs/maker_markout_spark.json

(The ``--against`` form is only meaningful when the Spark output was produced on
the SAME data as the reference — i.e. a full-tape run against the full-tape JSON.)
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

METRICS = (
    "coverage",
    "coverage_frac",
    "mean_gap_s",
    "dollar_wtd_markout_ps",
    "mean_markout_ps",
    "frac_negative",
    "total_dollar_markout",
    "spearman_vol_markout",
    "d1_markout_ps",
    "d10_markout_ps",
)

# Rank- and decile-based metrics depend on the tie-breaking of floating-point keys
# (``dol/sh``), whose last bits differ between engines because the per-maker sums are
# accumulated in a different order. They are therefore compared at a looser tolerance:
# a swapped rank among near-equal makers shifts them at the ~1e-5 level, which is a
# numerical artifact, not a logic difference. The deterministic aggregates still use
# the tight tolerance.
LOOSE_METRICS = {"spearman_vol_markout", "d1_markout_ps", "d10_markout_ps"}


def _run(cmd: list[str]) -> None:
    print("+", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=REPO)


def _curve_by_h(rep: dict) -> dict[int, dict]:
    return {c["horizon_s"]: c for c in rep["curve"]}


def _close(a, b, tol: float) -> bool:
    if a is None or b is None:
        return a is None and b is None
    a, b = float(a), float(b)
    d = abs(a - b)
    return d <= tol or d <= tol * max(abs(a), abs(b))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file-slice", default="0:40", help="python slice of sorted tape files given to BOTH engines")
    ap.add_argument("--tol", type=float, default=1e-6, help="tolerance for deterministic aggregate metrics")
    ap.add_argument("--loose-tol", type=float, default=1e-3, help="tolerance for rank/decile metrics (float-order sensitive)")
    ap.add_argument("--duckdb-buckets", type=int, default=4)
    ap.add_argument("--shuffle-partitions", type=int, default=16)
    ap.add_argument("--against", default=None, help="skip the DuckDB run; compare the Spark output to this reference JSON")
    ap.add_argument("--spark-out", default=None, help="reuse an existing Spark output JSON instead of recomputing")
    args = ap.parse_args()

    tmp = Path(tempfile.mkdtemp(prefix="markout_val_"))
    py = sys.executable

    if args.against:
        reference = json.loads(Path(args.against).read_text())
        ref_name = args.against
        spark_json = args.spark_out
        if not spark_json:
            spark_json = str(tmp / "spark.json")
            _run([py, "scripts/44_maker_markout_spark.py", "--file-slice", args.file_slice,
                  "--out", spark_json, "--shuffle-partitions", str(args.shuffle_partitions)])
        candidate = json.loads(Path(spark_json).read_text())
    else:
        ref_json = str(tmp / "duckdb.json")
        spark_json = str(tmp / "spark.json")
        _run([py, "scripts/40_maker_markout.py", "--file-slice", args.file_slice,
              "--out", ref_json, "--buckets", str(args.duckdb_buckets)])
        _run([py, "scripts/44_maker_markout_spark.py", "--file-slice", args.file_slice,
              "--out", spark_json, "--shuffle-partitions", str(args.shuffle_partitions)])
        reference = json.loads(Path(ref_json).read_text())
        candidate = json.loads(Path(spark_json).read_text())
        ref_name = "DuckDB (scripts/40)"

    ref_c, got_c = _curve_by_h(reference), _curve_by_h(candidate)
    print(f"\n=== PySpark (scripts/44) vs {ref_name}   tol={args.tol:g} (rank/decile {args.loose_tol:g}) ===")
    ok = True
    worst_tight = worst_loose = 0.0
    horizons = sorted(set(ref_c) & set(got_c))
    for h in horizons:
        for m in METRICS:
            a, b = ref_c[h].get(m), got_c[h].get(m)
            tol_m = args.loose_tol if m in LOOSE_METRICS else args.tol
            if a is not None and b is not None:
                diff = abs(float(a) - float(b))
                if m in LOOSE_METRICS:
                    worst_loose = max(worst_loose, diff)
                else:
                    worst_tight = max(worst_tight, diff)
            if not _close(a, b, tol_m):
                ok = False
                print(f"  FAIL  D={h:>6}s  {m:<24} reference={a!r}  spark={b!r}  (tol {tol_m:g})")

    if "n_maker_fills" in reference and "n_maker_fills" in candidate:
        same = reference["n_maker_fills"] == candidate["n_maker_fills"]
        ok = ok and same
        print(f"  n_maker_fills: reference={reference['n_maker_fills']:,} "
              f"spark={candidate['n_maker_fills']:,}  {'OK' if same else 'MISMATCH'}")

    print(f"  compared {len(horizons)} horizons x {len(METRICS)} metrics")
    print(f"  max abs diff: deterministic metrics {worst_tight:.2e}, rank/decile metrics {worst_loose:.2e}")
    print("RESULT:", "PASS  engines agree" if ok else "FAIL  see diffs above")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

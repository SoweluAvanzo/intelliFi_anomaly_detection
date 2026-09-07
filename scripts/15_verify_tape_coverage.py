#!/usr/bin/env python3
"""Stage 15: verify tape_v2 completeness, and (optionally) requeue gaps.

WHY THIS EXISTS
    Chunk writes were historically non-atomic (`df.write_parquet(out)` straight to
    the final path) and skip-if-exists checked only *existence*. A process killed
    mid-write (a stop/recreate, an Etherscan trip) left a 0-byte part.parquet that
    then counted as "done" forever -> a SILENT GAP re-crawl never fills. On
    2026-09-02 this had swallowed ~250k genesis blocks (388 zero-byte files).

WHAT IT DOES
    Computes BLOCK-LEVEL coverage from the *non-zero* chunk files (a 0-byte file is
    a broken write, NOT coverage), so it finds exactly the gaps skip-if-exists
    misses. It reasons on chunk RANGES (not row data): a block is "covered" iff a
    non-zero chunk spans it -- which correctly treats a genuinely-empty-but-crawled
    block (valid parquet, 0 rows) as covered while flagging never-written ranges.
    Mixed 500-/2000-block granularities merge fine.

USAGE
    python scripts/15_verify_tape_coverage.py --from-block A --to-block B \
        [--fix] [--gaps-out data/genesis_gaps_recrawl.txt]

    --fix        delete the 0-byte markers so the crawler re-crawls them
    --gaps-out   write uncovered ranges (feed to 10_fetch_v2_tape / cohort runner)

    Exit 0 = fully covered (no broken files, no gaps); 2 = issues found (CI-friendly).

Run it at the END of every crawl and periodically; wire the exit code into the
"done" gate so a crawl is never declared complete while gaps remain.
"""
from __future__ import annotations

import argparse
import glob
import os
import re
import sys

from intellifi import config

TAPE = config.PARQUET_DIR / "tape_v2"


def _scan() -> tuple[list, list]:
    """Return (valid, broken) as lists of (a, b, path); broken = 0-byte files."""
    valid, broken = [], []
    for f in glob.glob(str(TAPE / "blocks=*" / "part.parquet")):
        m = re.search(r"blocks=(\d+)-(\d+)", os.path.basename(os.path.dirname(f)))
        if not m:
            continue
        a, b = int(m.group(1)), int(m.group(2))
        (broken if os.path.getsize(f) == 0 else valid).append((a, b, f))
    return valid, broken


def _merge(pairs: list) -> list:
    out: list = []
    for a, b in sorted(pairs):
        if out and a <= out[-1][1] + 1:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return out


def _complement(covered: list, lo: int, hi: int) -> list:
    """Ranges within [lo, hi] not spanned by any (merged) covered interval."""
    gaps, cur = [], lo
    for a, b in covered:
        if b < lo or a > hi:
            continue
        a, b = max(a, lo), min(b, hi)
        if a > cur:
            gaps.append((cur, a - 1))
        cur = max(cur, b + 1)
    if cur <= hi:
        gaps.append((cur, hi))
    return gaps


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from-block", type=int, required=True)
    ap.add_argument("--to-block", type=int, required=True)
    ap.add_argument("--fix", action="store_true",
                    help="delete 0-byte files so skip-if-exists re-crawls them")
    ap.add_argument("--gaps-out", type=str, default=None,
                    help="write uncovered ranges here (for re-crawl)")
    args = ap.parse_args()
    lo, hi = args.from_block, args.to_block
    total = hi - lo + 1

    valid, broken = _scan()
    covered = _merge([(a, b) for a, b, _ in valid])
    gaps = _complement(covered, lo, hi)
    cov_blocks = sum(min(b, hi) - max(a, lo) + 1
                     for a, b in covered if b >= lo and a <= hi)
    gap_blocks = sum(b - a + 1 for a, b in gaps)

    print(f"tape_v2 coverage over [{lo:,}, {hi:,}] = {total:,} blocks")
    print(f"  valid chunks: {len(valid):,}   zero-byte (broken) chunks: {len(broken)}")
    print(f"  covered: {cov_blocks:,} blocks ({100 * cov_blocks / total:.3f}%)")
    print(f"  GAPS: {len(gaps)} ranges / {gap_blocks:,} blocks uncovered")
    if broken:
        bb = sum(b - a + 1 for a, b, _ in broken)
        print(f"  -> {len(broken)} broken 0-byte files span {bb:,} of those blocks")

    if args.fix and broken:
        for _, _, f in broken:
            os.remove(f)
            try:
                os.rmdir(os.path.dirname(f))
            except OSError:
                pass
        print(f"  --fix: deleted {len(broken)} zero-byte files "
              f"(they will be re-crawled on the next pass)")

    if args.gaps_out and gaps:
        with open(args.gaps_out, "w") as fh:
            for a, b in gaps:
                fh.write(f"{a} {b}\n")
        print(f"  wrote {len(gaps)} gap ranges -> {args.gaps_out}")

    ok = not broken and not gaps
    print("RESULT:", "COMPLETE (no broken files, no gaps)" if ok
          else "INCOMPLETE -- see gaps above")
    return 0 if ok else 2


if __name__ == "__main__":
    sys.exit(main())

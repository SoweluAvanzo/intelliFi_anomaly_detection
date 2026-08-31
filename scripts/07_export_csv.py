"""Stage 7: export the parquet store to CSV for external researchers.

Writes one CSV per dataset under ``--out`` (default ``data/export/csv``),
plus ``README.md`` (data dictionary) and ``MANIFEST.csv``. The on-chain
transfer tables (~5M rows) are included unless ``--no-onchain`` is given;
``--zip`` additionally bundles core and on-chain files into two archives
next to the output folder.
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from intellifi import config
from intellifi.export import export_all, zip_export


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=config.DATA_DIR / "export" / "csv")
    parser.add_argument("--no-onchain", action="store_true",
                        help="skip the large on-chain transfer tables")
    parser.add_argument("--zip", action="store_true",
                        help="also write polymarket_dataset_{core,onchain}.zip")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")

    manifest = export_all(args.out, include_onchain=not args.no_onchain)
    total = sum(m["bytes"] for m in manifest)
    print(f"exported {len(manifest)} files, {sum(m['rows'] for m in manifest):,} rows, "
          f"{total / 1e6:.1f} MB -> {args.out}")
    if args.zip:
        for z in zip_export(args.out, manifest):
            print(f"archive {z} ({z.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

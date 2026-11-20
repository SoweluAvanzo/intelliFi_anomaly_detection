#!/usr/bin/env python
"""Episode dynamics for the RQ2 negRisk price-correction analysis (fee vs pre-fee).

Beyond the converged episodes (`scripts/47`), measures correction speed (duration), the openings
that never converge and why, terminal/resolution contamination RELATIVE to market life, the
economics of un-converged gaps, composition-adjusted episode intensity, the duration-vs-volume
relationship (clustered OLS), and volume/dollar-weighted concentration + density.

Reuses the committed canonical builders so the detector is byte-identical to scripts/47.
Writes `data/export/episode_dynamics_{source}.{json,_episodes.parquet,_unconverged.parquet}`.

MEMORY-SAFE. Launch inside a scope:
  systemd-run --user --scope -p MemoryMax=11G .venv/bin/python scripts/51_episode_dynamics.py --source v2
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
from intellifi import episode_dynamics as ed    # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--source", choices=["v2", "v1"], default="v2",
                    help="v2 = fee era (tape); v1 = pre-fee (archive)")
    ap.add_argument("--out-prefix", default=None)
    ap.add_argument("--memory-limit", default="6GB")
    ap.add_argument("--threads", type=int, default=6)
    args = ap.parse_args()
    out_prefix = args.out_prefix or str(_cfg.DATA_DIR / "export" / f"episode_dynamics_{args.source}")

    tmp = _cfg.DATA_DIR / f"_s51_{args.source}_tmp"
    shutil.rmtree(tmp, ignore_errors=True); tmp.mkdir(parents=True)
    con = duckdb.connect((tmp / "w.db").as_posix())
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute(f"PRAGMA threads={args.threads}")
    con.execute("SET preserve_insertion_order=false")
    con.execute(f"SET temp_directory='{(tmp / 'spill').as_posix()}'")
    con.execute("SET max_temp_directory_size='60GB'")

    rep = ed.run(con, args.source, out_prefix)
    con.close(); shutil.rmtree(tmp, ignore_errors=True)
    print("\n=== episode-dynamics summary ===")
    print(json.dumps({k: rep[k] for k in ("source", "closed_matches_committed", "n_openings",
          "n_closed", "n_unconverged", "unconverged_rate")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

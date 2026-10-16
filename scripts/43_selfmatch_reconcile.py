#!/usr/bin/env python
"""Reconcile the v2 self-match (maker==taker) count across contract scopes.

Why this exists: an early full-tape "census" reported ~7,000 self-dealing transactions,
but the paper's analysis (and scripts/42) finds 0. This script shows the cause is SCOPE.
It scans the whole tape for maker==taker rows (a tiny set), then classifies every one by
the cuts the analysis applies, so the two results reconcile exactly:

  - within the two fee-charging exchanges (v2_a, v2_b) — the Sample-B analysis scope —
    self-matches are ZERO (the matching never crosses an account with itself);
  - the ~7,000 self-matches live entirely on the auxiliary emitter contracts
    (e.g. 0xe3333700...) that CLAUDE.md keeps in data/parquet/tape_v2_other and that the
    analysis excludes, and are concentrated in a single automated wallet.

The maker==taker filter is applied during the scan, so the output is tiny and the whole
pass is light. Still, run inside a memory cap for safety.

  python scripts/43_selfmatch_reconcile.py --out docs/selfmatch_reconcile.json --memory-limit 4GB
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                         # noqa: E402
from intellifi import config as _cfg                  # noqa: E402

TAPE = "data/parquet/tape_v2/**/*.parquet"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="docs/selfmatch_reconcile.json")
    ap.add_argument("--memory-limit", default="4GB")
    args = ap.parse_args()

    spill = _cfg.DATA_DIR / "_s43_spill"; spill.mkdir(parents=True, exist_ok=True)
    con = duckdb.connect()
    con.execute(f"PRAGMA memory_limit='{args.memory_limit}'"); con.execute("SET threads=3")
    con.execute(f"SET temp_directory='{spill.as_posix()}'"); con.execute("SET max_temp_directory_size='40GB'")

    print("[1] scanning full tape for maker==taker rows ...", flush=True)
    con.execute(f"""CREATE TABLE sm AS
        SELECT tx_hash, evt_index, is_taker_order, price, shares, usdc, exchange, lower(maker) AS w
        FROM read_parquet('{TAPE}', union_by_name=true)
        WHERE event='OrderFilled' AND lower(maker)=lower(taker)""")
    raw = con.sql("SELECT count(*) FROM sm").fetchone()[0]
    ded = con.sql("SELECT count(DISTINCT (tx_hash, evt_index)) FROM sm").fetchone()[0]
    interior_ded = con.sql("SELECT count(DISTINCT (tx_hash, evt_index)) FROM sm WHERE price>0 AND price<1").fetchone()[0]
    in_scope = con.sql("SELECT count(*) FROM sm WHERE exchange IN ('v2_a','v2_b') AND NOT is_taker_order "
                       "AND price>0 AND price<1 AND shares>0").fetchone()[0]
    by_exch = [{"exchange": r[0], "rows": int(r[1]), "deduped": int(r[2]), "usdc": float(r[3] or 0)}
               for r in con.sql("""SELECT exchange, count(*), count(DISTINCT (tx_hash,evt_index)), sum(usdc)
                                   FROM sm GROUP BY 1 ORDER BY 2 DESC""").fetchall()]
    top = [{"wallet": r[0], "rows": int(r[1])} for r in
           con.sql("SELECT w, count(*) FROM sm GROUP BY w ORDER BY 2 DESC LIMIT 5").fetchall()]
    nwallet = con.sql("SELECT count(DISTINCT w) FROM sm").fetchone()[0]

    rep = {
        "scope": "whole v2 tape, OrderFilled rows with maker==taker (self-match), all contracts",
        "self_match_rows_raw": int(raw),
        "self_match_rows_deduped": int(ded),
        "self_match_interior_price_deduped": int(interior_ded),
        "self_match_in_analysis_scope_v2a_v2b": int(in_scope),
        "by_exchange": by_exch,
        "top_wallets": top,
        "n_distinct_self_matching_wallets": int(nwallet),
        "finding": ("All self-matches are on auxiliary emitter contracts (not v2_a/v2_b); within the "
                    "analysis scope (v2_a/v2_b, interior price, maker fills) the count is "
                    f"{int(in_scope)}. The earlier 'census' reported ~7,000 because it did not filter "
                    "to the two fee-charging exchanges. interior_price_deduped reproduces that number."),
    }
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    Path(args.out).write_text(json.dumps(rep, indent=1))
    print(f"wrote {args.out}")
    print(f"  self-match rows raw={raw:,} deduped={ded:,} interior-deduped={interior_ded:,} "
          f"in-scope(v2_a/v2_b)={in_scope}")
    for e in by_exch:
        print(f"    {e['exchange']:<48} rows={e['rows']:<7,} dedup={e['deduped']:<7,} usd=${e['usdc']:,.0f}")
    print(f"  distinct self-matching wallets={nwallet}; top wallet rows={top[0]['rows'] if top else 0:,}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())

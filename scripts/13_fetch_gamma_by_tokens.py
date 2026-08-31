#!/usr/bin/env python
"""Fetch Gamma market metadata BY clob_token_id for a provided token list.

Enumerating /markets is lossy (offset ceiling ~2000 drops markets on dense days,
including high-volume ones), so for complete coverage we look markets up by the
exact token ids that appear in our tape. Reads a newline-delimited token file,
streams results to part files (memory-bounded), then DuckDB-consolidates into
markets.parquet + neg_risk_families/families.parquet.

    python scripts/13_fetch_gamma_by_tokens.py --tokens-file tokens.txt --write -v
"""
from __future__ import annotations
import argparse, logging, sys
from pathlib import Path

import duckdb

from intellifi import config
from intellifi.gamma import fetch_markets_by_tokens, normalise_market, to_dataframe

log = logging.getLogger("scripts.13")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tokens-file", required=True)
    ap.add_argument("--batch", type=int, default=100)
    ap.add_argument("--flush-every", type=int, default=5000)
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verbose", "-v", action="count", default=0)
    args = ap.parse_args()
    logging.basicConfig(level=max(logging.WARNING - 10 * args.verbose, logging.DEBUG),
                        format="%(levelname)s %(name)s | %(message)s")

    toks = [l.strip() for l in Path(args.tokens_file).read_text().splitlines() if l.strip()]
    print(f"tokens to look up: {len(toks):,}")
    config.ensure_dirs()
    parts = config.MARKETS_PARQUET / "_token_parts"
    parts.mkdir(parents=True, exist_ok=True)
    for f in parts.glob("part_*.parquet"):
        f.unlink()

    buf: list[dict] = []
    seq = 0

    def flush() -> None:
        nonlocal seq, buf
        if not buf:
            return
        to_dataframe([normalise_market(m) for m in buf]).write_parquet(
            parts / f"part_{seq:05d}.parquet", compression="zstd")
        seq += 1
        buf = []

    def prog(done, total, uniq):
        print(f"  {done:,}/{total:,} tokens -> {uniq:,} unique markets", flush=True)

    for m in fetch_markets_by_tokens(toks, batch=args.batch, on_progress=prog):
        buf.append(m)
        if len(buf) >= args.flush_every:
            flush()
    flush()
    print(f"streamed {seq} parts")

    if not args.write or seq == 0:
        return 0
    glob = str(parts / "part_*.parquet")
    con = duckdb.connect(); con.execute("PRAGMA memory_limit='1GB'"); con.execute("PRAGMA threads=2")
    out = config.MARKETS_PARQUET / "markets.parquet"
    con.execute(f"COPY (SELECT * FROM (SELECT *, row_number() OVER (PARTITION BY condition_id) rn "
                f"FROM read_parquet('{glob}')) WHERE rn=1 EXCLUDE (rn)) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"consolidated -> {out} ({rows} rows)")
    fam_dir = config.NEG_RISK_FAMILIES_PARQUET; fam_dir.mkdir(parents=True, exist_ok=True)
    fam_out = fam_dir / "families.parquet"
    con.execute(f"""COPY (
        SELECT event_id AS family_event_id, event_slug AS family_event_slug,
               event_neg_risk_market_id AS neg_risk_market_id, condition_id AS member_condition_id,
               list_extract(clob_token_ids, 1) AS member_token_id_yes,
               list_extract(clob_token_ids, 2) AS member_token_id_no,
               slug AS member_slug, list_extract(outcomes, 1) AS member_outcome_name
        FROM read_parquet('{out}') WHERE event_neg_risk = TRUE
    ) TO '{fam_out}' (FORMAT parquet, COMPRESSION zstd)""")
    fr, fn_ = con.execute(f"SELECT count(*), count(DISTINCT family_event_id) FROM read_parquet('{fam_out}')").fetchone()
    print(f"families -> {fam_out} ({fr} rows, {fn_} families)")
    return 0


if __name__ == "__main__":
    sys.exit(main())

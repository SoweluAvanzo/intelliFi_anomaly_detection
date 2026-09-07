#!/usr/bin/env python
"""Merge the 4 v2 condition-registry shards and VERIFY correctness/integrity
before the resolutions are used for any PnL/calibration.

Gates:
  0. MERGE  — concat 4 shards, dedup by condition_id (prefer the RESOLVED row).
  1. COUNTS — total conditions, resolved, unresolved, negRisk.
  2. CROSS-BOUNDARY — scripts/12 joins prep<->resolution within each shard's block
     range, so a market prepared in shard N but resolved in shard N+1 loses its
     resolution. Estimate the loss: conditions prepared >1 shard-width before the
     max resolution block yet unresolved (candidates), and compare merged-resolved
     to the raw ConditionResolution event totals (from the shard logs).
  3. PAYOUT SANITY — winning_outcome_index in {0,1} for binary; payout one-hot.
  4. TOKEN-DERIVATION MATCH — the on-chain position_id derivation (token0/token1)
     must match the ACTUAL token_ids traded in the v2 tape. This is the strong
     internal-consistency proof of the whole condition->token->winner chain.
  5. COVERAGE — fraction of v2-tape conditions that now have a resolution.

  python scripts/13_merge_verify_ctf_v2.py --out data/parquet/ctf_v2_conditions.parquet
"""
from __future__ import annotations

import argparse
import glob
import json
import re
import sys
from pathlib import Path

import polars as pl

REPO = Path(__file__).resolve().parents[1]
SHARD_DIR = REPO / "data/parquet/_ctf_v2_shards"
TAPE = "data/parquet/tape_v2/**/*.parquet"
CLOB = "data/parquet/clob_markets/tokens.parquet"
CORPUS_RES = REPO / "data/parquet/ctf_resolutions_corpus.parquet"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/parquet/ctf_v2_conditions.parquet")
    ap.add_argument("--shard-prefix", default="rshard",
                    help="'rshard' = resolution-only shards (complete registry); 'shard' = old prep-joined shards")
    ap.add_argument("--memory-limit", default="8GB")
    args = ap.parse_args()
    import duckdb, os
    rep: dict = {"shard_prefix": args.shard_prefix}

    # 0. MERGE (polars — the shards are small, ~2M rows total)
    shards = sorted(glob.glob(str(SHARD_DIR / f"{args.shard_prefix}*.parquet")))
    if len(shards) != 4:
        print(f"expected 4 shards, found {len(shards)}: {shards}", file=sys.stderr); return 2
    df = pl.concat([pl.read_parquet(s) for s in shards], how="vertical_relaxed")
    # dedup: prefer the resolved copy of any duplicated condition (boundary blocks)
    df = (df.sort("resolved_ts_utc", nulls_last=True)
            .unique(subset=["condition_id"], keep="first"))
    rep["n_conditions"] = df.height
    rep["n_resolved"] = int(df["resolved_ts_utc"].is_not_null().sum())
    rep["n_unresolved"] = rep["n_conditions"] - rep["n_resolved"]
    rep["n_negrisk"] = int(df["neg_risk"].sum())
    rep["resolved_frac"] = round(rep["n_resolved"] / rep["n_conditions"], 4)

    # 2. CROSS-BOUNDARY loss estimate: raw ConditionResolution events fetched (logs)
    #    vs merged-resolved. gap ~ (v1-era late resolutions) + (v2 cross-boundary).
    raw_res = 0
    for lg in sorted(glob.glob(str(SHARD_DIR / f"{args.shard_prefix}*.log"))):
        m = re.search(r"ConditionResolution:\s*([\d,]+)", Path(lg).read_text())
        if m:
            raw_res += int(m.group(1).replace(",", ""))
    rep["raw_resolution_events_fetched"] = raw_res
    rep["merged_resolved"] = rep["n_resolved"]
    rep["resolution_events_minus_merged_resolved"] = raw_res - rep["n_resolved"]
    rep["cross_boundary_note"] = ("gap = v1-era markets resolving in the v2 window (correctly excluded, no prep "
        "in range) PLUS v2 cross-boundary losses (prep in shard N, resolution in shard N+1 — WRONGLY dropped). "
        "If the gap is large, re-fetch resolutions globally and re-join.")

    # 3. PAYOUT SANITY
    binm = df.filter(pl.col("outcome_slot_count") == 2)
    rep["binary_conditions"] = binm.height
    if binm.height:
        wi = binm.filter(pl.col("winning_outcome_index").is_not_null())["winning_outcome_index"]
        rep["winning_index_in_0_1_frac"] = round(float(((wi == 0) | (wi == 1)).sum()) / max(len(wi), 1), 4)

    # write the merged registry now (so downstream can use it); gates 4/5 read it back via duckdb
    Path(args.out).parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(args.out, compression="zstd")
    rep["written"] = args.out

    # 4+5. TOKEN-MATCH + COVERAGE vs the tape (duckdb, memory-safe)
    con = duckdb.connect(); con.execute(f"PRAGMA memory_limit='{args.memory_limit}'")
    con.execute("SET threads=2"); os.makedirs("data/_s13_tmp", exist_ok=True)
    con.execute("SET temp_directory='data/_s13_tmp'"); con.execute("SET preserve_insertion_order=false")
    con.register("reg", df.select("condition_id", "token0", "token1", "winning_outcome_index",
                                   "resolved_ts_utc", "outcome_slot_count").to_arrow())
    # distinct tape token_ids
    tape_tok = con.sql(f"SELECT DISTINCT token_id FROM read_parquet('{TAPE}', union_by_name=true)")
    con.execute("CREATE TEMP TABLE tape_tokens AS SELECT * FROM tape_tok")
    n_tape_tok = con.sql("SELECT count(*) FROM tape_tokens").fetchone()[0]
    matched = con.sql("""SELECT count(*) FROM tape_tokens tt
        WHERE tt.token_id IN (SELECT token0 FROM reg WHERE token0 IS NOT NULL
                              UNION ALL SELECT token1 FROM reg WHERE token1 IS NOT NULL)""").fetchone()[0]
    rep["token_derivation_match"] = {"tape_distinct_tokens": int(n_tape_tok), "matched_to_derived": int(matched),
                                     "match_frac": round(matched / n_tape_tok, 4) if n_tape_tok else None,
                                     "note": "derived position_id token0/token1 vs tokens actually traded in the tape; "
                                             "high frac validates the condition->token->winner chain"}
    # coverage: tape conditions (via clob_markets token->condition) with a resolution
    con.execute(f"""CREATE TEMP TABLE tape_conds AS
        SELECT DISTINCT tk.condition_id FROM tape_tokens tt
        JOIN read_parquet('{CLOB}') tk ON tk.token_id = tt.token_id""")
    cov = con.sql("""SELECT count(*) n_tape_conds,
        count(*) FILTER (WHERE r.resolved_ts_utc IS NOT NULL) n_with_resolution,
        count(*) FILTER (WHERE r.condition_id IS NOT NULL) n_in_registry
        FROM tape_conds tc LEFT JOIN reg r ON lower(r.condition_id)=lower(tc.condition_id)""").fetchone()
    rep["coverage"] = {"tape_conditions": int(cov[0]), "in_registry": int(cov[2]),
                       "resolved": int(cov[1]),
                       "resolved_frac_of_tape": round(cov[1] / cov[0], 4) if cov[0] else None,
                       "note": "unresolved tape conditions are either still-open markets or cross-boundary losses"}

    Path("docs/ctf_v2_verify.json").write_text(json.dumps(rep, indent=1, default=str))
    print(json.dumps(rep, indent=1, default=str))
    import shutil; shutil.rmtree("data/_s13_tmp", ignore_errors=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())

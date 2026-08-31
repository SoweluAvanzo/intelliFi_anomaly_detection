"""Stage 1 smoke test: pull resolved markets from Gamma and report the universe.

Usage:
    python scripts/01_fetch_resolved_markets.py [--lookback-days 180] [--write]

Prints a compact report (count, volume distribution, negRisk share, family
count). With ``--write``, also persists the normalised parquet and a derived
``neg_risk_families`` parquet.
"""
from __future__ import annotations

import argparse
import logging
import sys

import polars as pl

from intellifi import config
from intellifi.gamma import load_resolved_markets, write_markets_parquet


def _percentiles(s: pl.Series, qs: list[float]) -> dict[float, float]:
    return {q: float(s.quantile(q) or 0.0) for q in qs}


def derive_neg_risk_families(df: pl.DataFrame) -> pl.DataFrame:
    """One row per (family event, member condition_id).

    Family membership is established via shared ``event_id`` with
    ``event_neg_risk == true`` (per v2 §4.4, NOT via ``negRiskRequestID``).
    """
    fam = df.filter(pl.col("event_neg_risk") == True)  # noqa: E712
    return fam.select([
        pl.col("event_id").alias("family_event_id"),
        pl.col("event_slug").alias("family_event_slug"),
        pl.col("event_neg_risk_market_id").alias("neg_risk_market_id"),
        pl.col("condition_id").alias("member_condition_id"),
        pl.col("clob_token_ids").list.get(0, null_on_oob=True).alias("member_token_id_yes"),
        pl.col("clob_token_ids").list.get(1, null_on_oob=True).alias("member_token_id_no"),
        pl.col("slug").alias("member_slug"),
        pl.col("outcomes").list.get(0, null_on_oob=True).alias("member_outcome_name"),
    ])


def merge_with_existing(df: pl.DataFrame) -> pl.DataFrame:
    """Union ``df`` with the on-disk corpus, keeping the fresh row on conflict.

    Lets successive cohorts (e.g. a post-snapshot hold-out) accumulate instead
    of the fetch replacing the corpus; trade/holder partitions are keyed by
    ``condition_id`` and are therefore unaffected either way.
    """
    path = config.MARKETS_PARQUET / "markets.parquet"
    if not path.exists():
        return df
    existing = pl.read_parquet(path)
    kept = existing.filter(~pl.col("condition_id").is_in(df["condition_id"].to_list()))
    merged = pl.concat([kept, df], how="vertical_relaxed")
    return merged.sort("volume_clob", descending=True, nulls_last=True)


def report(df: pl.DataFrame) -> None:
    n = df.height
    print(f"\n=== Resolved-market universe ({n} markets) ===")
    if n == 0:
        return

    end_min = df["end_date"].min()
    end_max = df["end_date"].max()
    print(f"endDate range: {end_min} → {end_max}")

    vol = df["volume_clob"].fill_null(0.0)
    pcts = _percentiles(vol, [0.50, 0.75, 0.90, 0.99])
    print(
        "volume_clob (USDC):"
        f" total ${float(vol.sum()):,.0f}"
        f" | median ${pcts[0.50]:,.0f}"
        f" | p75 ${pcts[0.75]:,.0f}"
        f" | p90 ${pcts[0.90]:,.0f}"
        f" | p99 ${pcts[0.99]:,.0f}"
    )

    # negRisk membership: per-market flag vs family event
    n_negrisk = int(df["neg_risk"].fill_null(False).sum())
    n_event_negrisk = int(df["event_neg_risk"].fill_null(False).sum())
    print(f"negRisk markets (per-market flag): {n_negrisk}/{n} ({n_negrisk / n:.0%})")
    print(f"negRisk via event link:            {n_event_negrisk}/{n} ({n_event_negrisk / n:.0%})")

    # Families
    fam_count = (
        df.filter(pl.col("event_neg_risk") == True)  # noqa: E712
        .select(pl.col("event_id").n_unique())
        .item()
    )
    print(f"distinct negRisk families:         {fam_count}")

    # Resolution check: in resolved markets, outcome_prices_final should be {0,1}-ish
    resolved_rows = (
        df.select(pl.col("outcome_prices_final"))
        .with_columns(pl.col("outcome_prices_final").list.max().alias("max_p"))
        .filter(pl.col("max_p") >= 0.99)
        .height
    )
    print(f"rows with a final outcome at >= 0.99: {resolved_rows}/{n}")

    # Top 5 by clob volume
    cols = ["slug", "question", "volume_clob", "neg_risk", "end_date"]
    print("\nTop 5 by volume_clob:")
    top = df.sort("volume_clob", descending=True, nulls_last=True).select(cols).head(5)
    with pl.Config(tbl_cols=-1, tbl_width_chars=200, fmt_str_lengths=80):
        print(top)


def _run_streaming(args, closed, archived) -> int:
    """Complete-set fetch that never buffers all markets: stream_all_markets writes
    part files, then DuckDB consolidates (memory-bounded) into markets.parquet and
    derives neg_risk_families. Bounded regardless of universe size."""
    import duckdb
    from intellifi.gamma import stream_all_markets

    config.ensure_dirs()
    parts = config.MARKETS_PARQUET / "_stream_parts"
    n = stream_all_markets(
        parts, lookback_days=args.lookback_days, closed=closed, archived=archived,
        end_date_max=args.end_date_max,
    )
    print(f"\nStreamed {n} unique markets to {parts}")
    if n == 0:
        return 0
    glob = str(parts / "part_*.parquet")
    con = duckdb.connect()
    con.execute("PRAGMA memory_limit='1GB'"); con.execute("PRAGMA threads=2")
    out = config.MARKETS_PARQUET / "markets.parquet"
    # parts are already deduped on condition_id; straight consolidation streams.
    con.execute(f"COPY (SELECT * FROM read_parquet('{glob}')) TO '{out}' (FORMAT parquet, COMPRESSION zstd)")
    rows = con.execute(f"SELECT count(*) FROM read_parquet('{out}')").fetchone()[0]
    print(f"Consolidated -> {out} ({rows} rows)")
    # families: event_neg_risk == true, one row per (family event, member condition_id)
    fam_dir = config.NEG_RISK_FAMILIES_PARQUET; fam_dir.mkdir(parents=True, exist_ok=True)
    fam_out = fam_dir / "families.parquet"
    con.execute(f"""COPY (
        SELECT event_id AS family_event_id,
               event_slug AS family_event_slug,
               event_neg_risk_market_id AS neg_risk_market_id,
               condition_id AS member_condition_id,
               list_extract(clob_token_ids, 1) AS member_token_id_yes,
               list_extract(clob_token_ids, 2) AS member_token_id_no,
               slug AS member_slug,
               list_extract(outcomes, 1) AS member_outcome_name
        FROM read_parquet('{out}') WHERE event_neg_risk = TRUE
    ) TO '{fam_out}' (FORMAT parquet, COMPRESSION zstd)""")
    fam_rows, fam_n = con.execute(
        f"SELECT count(*), count(DISTINCT family_event_id) FROM read_parquet('{fam_out}')").fetchone()
    print(f"Wrote {fam_out} ({fam_rows} rows, {fam_n} families)")
    # closed/archived split for the operator
    split = con.execute(f"SELECT closed, archived, count(*) FROM read_parquet('{out}') GROUP BY 1,2 ORDER BY 3 DESC").fetchall()
    print("closed/archived split:", split)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=config.RESOLVED_LOOKBACK_DAYS)
    parser.add_argument("--top-n", type=int, default=1000,
                        help="cap universe at top-N markets by volumeClob; pass 0 for all reachable")
    parser.add_argument("--write", action="store_true", help="persist parquet files")
    parser.add_argument("--merge-existing", action="store_true",
                        help="union the fetched cohort with the existing markets.parquet "
                             "(dedup by condition_id, fresh rows win) instead of overwriting it")
    parser.add_argument("--closed", choices=["true","false","any"], default="true",
                        help="market closed-state filter; 'any' fetches open+closed (v2 metadata)")
    parser.add_argument("--archived", choices=["false","true","any"], default="false",
                        help="market archived-state filter; 'any' includes archived — REQUIRED for "
                             "the v2 metadata, since resolved ephemeral markets get archived")
    parser.add_argument("--end-date-max", default=None,
                        help="upper endDate bound (YYYY-MM-DD); default today. Set a future "
                             "date with --include-open to capture open markets that end later")
    parser.add_argument("--stream", action="store_true",
                        help="memory-bounded complete-set fetch (implies --top-n 0): stream each "
                             "endDate window to part files and consolidate with DuckDB, so a "
                             "very large closed+archived universe never buffers in RAM")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG), format="%(levelname)s %(name)s | %(message)s")

    closed = {"true": True, "false": False, "any": None}[args.closed]
    archived = {"false": False, "true": True, "any": None}[args.archived]

    if args.stream:
        return _run_streaming(args, closed, archived)

    top_n = None if args.top_n == 0 else args.top_n
    df = load_resolved_markets(
        lookback_days=args.lookback_days,
        top_n=top_n,
        persist_raw=args.write,
        closed=closed,
        archived=archived,
        end_date_max=args.end_date_max,
    )
    report(df)

    if args.merge_existing:
        df = merge_with_existing(df)
        print(f"\nMerged with existing corpus -> {df.height} markets")

    if args.write and df.height > 0:
        out = write_markets_parquet(df)
        print(f"\nWrote {out} ({df.height} rows)")
        fam = derive_neg_risk_families(df)
        fam_path = config.NEG_RISK_FAMILIES_PARQUET / "families.parquet"
        config.ensure_dirs()
        fam.write_parquet(fam_path, compression="zstd")
        print(f"Wrote {fam_path} ({fam.height} rows)")

    return 0


if __name__ == "__main__":
    sys.exit(main())

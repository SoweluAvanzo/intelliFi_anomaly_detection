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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lookback-days", type=int, default=config.RESOLVED_LOOKBACK_DAYS)
    parser.add_argument("--top-n", type=int, default=1000,
                        help="cap universe at top-N markets by volumeClob; pass 0 for all reachable")
    parser.add_argument("--write", action="store_true", help="persist parquet files")
    parser.add_argument("--verbose", "-v", action="count", default=0)
    args = parser.parse_args()

    level = logging.WARNING - 10 * args.verbose
    logging.basicConfig(level=max(level, logging.DEBUG), format="%(levelname)s %(name)s | %(message)s")

    top_n = None if args.top_n == 0 else args.top_n
    df = load_resolved_markets(
        lookback_days=args.lookback_days,
        top_n=top_n,
        persist_raw=args.write,
    )
    report(df)

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

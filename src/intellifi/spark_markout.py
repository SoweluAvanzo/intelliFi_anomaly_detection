"""Maker markout on Apache Spark — a distributed mirror of :mod:`scripts.40_maker_markout`.

This module reimplements the maker-markout statistic (RQ2, mechanism) on the
PySpark DataFrame API. The DuckDB script ``scripts/40_maker_markout.py`` is the
single-node source of truth used for replication; this module computes the
**identical** quantity so that it can be

1. **validated across engines** — on the same input the two engines agree to
   floating-point tolerance (see ``scripts/45_validate_markout_spark.py``), and
2. **scaled horizontally** — the partition→shuffle→reduce shape of the work maps
   onto a cluster unchanged as the on-chain tape keeps growing.

It is additive: it reads the same Parquet tape and changes nothing in the
DuckDB pipeline.

The markout
-----------
For each maker fill (a resting order that a taker lifted) the realised
liquidity-provision return is the signed price move *after* the fill, read from
the next trade rather than from the market's resolution — so it is
outcome-independent and isolates execution from forecasting:

* forward price ``p_fwd`` = the first TAKER trade of the same token in
  ``[t + D, t + D + max(2D, 900)]`` (``D`` = horizon seconds);
* ``markout_ps`` = ``p_fwd - p_fill`` for a BUY, ``p_fill - p_fwd`` for a SELL;
* **positive** markout = spread capture, **negative** = adverse selection.

The as-of join
--------------
Spark has no native ASOF join, so :func:`asof_forward` implements one with a
window: union the maker fills (shifted to their earliest acceptable forward time
``t + D``) with the per-second taker VWAP series, order each token's events by
time, and carry the first following price with
``first(..., ignorenulls=True)`` over a ``currentRow → unboundedFollowing``
frame. This is the canonical windowed as-of pattern and is numerically exact
against DuckDB's ``ASOF LEFT JOIN ... ON (m.t + D) <= p.t``.
"""
from __future__ import annotations

import logging
from collections.abc import Sequence

from pyspark.sql import DataFrame, SparkSession, Window
from pyspark.sql import functions as F

log = logging.getLogger(__name__)

#: Horizons (seconds) at which the forward price is read — identical to scripts/40.
HORIZONS: tuple[int, ...] = (60, 300, 900, 3600, 86400)

#: A per-share markout below this magnitude is economic zero, not adverse
#: selection. Thresholding here also makes ``frac_negative`` reproducible: a
#: float-sum ordering difference can otherwise flip the sign of a near-zero value.
_SIGN_EPS = 1e-9


def read_fills(spark: SparkSession, paths: Sequence[str]) -> DataFrame:
    """Read the raw tape, apply the base filter, and deduplicate.

    ``(tx_hash, evt_index)`` is the unique key of an ``OrderFilled`` log; the
    resumable crawl can write a fill into more than one chunk file, so a fill may
    appear more than once and must be deduplicated on read (the same invariant the
    DuckDB views enforce). Duplicate rows are byte-identical, so an arbitrary
    survivor is correct; we pick it deterministically by ``block_number``.

    Returns one clean row per fill with columns
    ``token_id, t (epoch seconds), maker (lower-cased), side, price, shares,
    is_taker_order``.
    """
    dedup = Window.partitionBy("tx_hash", "evt_index").orderBy(F.col("block_number").asc_nulls_last())
    return (
        spark.read.parquet(*paths)
        .where(
            (F.col("event") == "OrderFilled")
            & (F.col("price") > 0)
            & (F.col("price") < 1)
            & (F.col("shares") > 0)
        )
        .withColumn("_rn", F.row_number().over(dedup))
        .where(F.col("_rn") == 1)
        .select(
            F.col("token_id"),
            F.unix_timestamp("ts_utc").cast("long").alias("t"),
            F.lower("maker").alias("maker"),
            F.col("side"),
            F.col("price").alias("price"),
            F.col("shares"),
            F.col("is_taker_order"),
        )
    )


def maker_fills(fills: DataFrame) -> DataFrame:
    """The maker side of each fill (the liquidity providers whose return we measure)."""
    return fills.where(~F.col("is_taker_order")).select(
        "token_id", "t", "maker", "side", F.col("price").alias("p_fill"), "shares"
    )


def taker_vwap(fills: DataFrame) -> DataFrame:
    """One deterministic forward-reference price per ``(token_id, second)``.

    Several taker trades can share a timestamp; collapsing them to a volume-
    weighted price makes the as-of match unique and the result reproducible.
    """
    return (
        fills.where(F.col("is_taker_order"))
        .groupBy("token_id", "t")
        .agg((F.sum(F.col("price") * F.col("shares")) / F.sum("shares")).alias("price"))
    )


def asof_forward(makers: DataFrame, prices: DataFrame, horizon: int) -> DataFrame:
    """Windowed as-of join: attach to each maker fill the first taker price at ``t >= t + D``.

    Both inputs are unioned onto one per-token timeline; maker rows are placed at
    their *search* time ``t + D`` and price rows at their own time. Ordering by
    ``(ot asc, is_m desc)`` puts a maker strictly before a price at equal time, so
    the maker's ``currentRow → unboundedFollowing`` frame includes a price at
    exactly ``t + D`` (the ``<=`` boundary) and every later one;
    ``first(price, ignorenulls=True)`` then returns the nearest forward price.

    Returns maker rows with ``p_fwd`` (null when no forward price exists) and
    ``gap`` = ``p_fwd.t - fill.t``.
    """
    d = int(horizon)
    cols = ("token_id", "ot", "is_m", "mt", "maker", "side", "p_fill", "shares", "pt", "pval")
    m = makers.select(
        "token_id",
        (F.col("t") + F.lit(d)).alias("ot"),
        F.lit(1).alias("is_m"),
        F.col("t").alias("mt"),
        "maker",
        "side",
        "p_fill",
        "shares",
        F.lit(None).cast("long").alias("pt"),
        F.lit(None).cast("double").alias("pval"),
    )
    p = prices.select(
        "token_id",
        F.col("t").alias("ot"),
        F.lit(0).alias("is_m"),
        F.lit(None).cast("long").alias("mt"),
        F.lit(None).cast("string").alias("maker"),
        F.lit(None).cast("string").alias("side"),
        F.lit(None).cast("double").alias("p_fill"),
        F.lit(None).cast("double").alias("shares"),
        F.col("t").alias("pt"),
        F.col("price").alias("pval"),
    )
    frame = (
        Window.partitionBy("token_id")
        .orderBy(F.col("ot").asc(), F.col("is_m").desc())
        .rowsBetween(Window.currentRow, Window.unboundedFollowing)
    )
    # The value is NULL for maker rows, so ignorenulls skips them and the first
    # non-null is the nearest following taker price. (A bare struct of nulls would
    # not itself be null, hence the when() wrapper.)
    fwd = F.first(
        F.when(F.col("is_m") == 0, F.struct(F.col("pt").alias("pt"), F.col("pval").alias("pval"))),
        ignorenulls=True,
    ).over(frame)
    return (
        m.unionByName(p).select(*cols)
        .withColumn("fwd", fwd)
        .where(F.col("is_m") == 1)
        .select(
            "maker",
            "side",
            "p_fill",
            "shares",
            F.col("fwd.pval").alias("p_fwd"),
            (F.col("fwd.pt") - F.col("mt")).alias("gap"),
        )
    )


def markout(makers: DataFrame, prices: DataFrame, horizon: int) -> DataFrame:
    """Per-fill signed markout within the grace window, from the maker's side.

    Keeps a match only when a forward price exists and ``gap <= D + max(2D, 900)``.
    Returns ``maker, shares, mko_ps, gap``.
    """
    d = int(horizon)
    grace = max(2 * d, 900)
    mko = F.when(F.col("side") == "BUY", F.col("p_fwd") - F.col("p_fill")).otherwise(
        F.col("p_fill") - F.col("p_fwd")
    )
    return (
        asof_forward(makers, prices, d)
        .where(F.col("p_fwd").isNotNull() & (F.col("gap") <= d + grace))
        .select("maker", "shares", mko.alias("mko_ps"), "gap")
    )


def horizon_metrics(makers: DataFrame, prices: DataFrame, horizon: int, n_maker_fills: int) -> dict:
    """Compute one curve point (all statistics for a single horizon).

    Mirrors the stage-1 aggregates and stage-2 dispersion of scripts/40:
    coverage, dollar-weighted and mean markout, negative fraction, mean gap,
    total dollar markout, the Spearman rank correlation between a maker's volume
    and its markout, and the first/last volume-decile means.
    """
    d = int(horizon)
    mk = markout(makers, prices, d).persist()
    try:
        ov = mk.agg(
            F.count(F.lit(1)).alias("cov"),
            F.coalesce(F.sum("shares"), F.lit(0.0)).alias("sum_sh"),
            F.coalesce(F.sum(F.col("mko_ps") * F.col("shares")), F.lit(0.0)).alias("sum_dol"),
            F.coalesce(F.sum("mko_ps"), F.lit(0.0)).alias("sum_mko"),
            F.coalesce(F.sum(F.when(F.col("mko_ps") < -_SIGN_EPS, 1).otherwise(0)), F.lit(0)).alias("neg"),
            F.coalesce(F.sum("gap"), F.lit(0.0)).alias("sum_gap"),
        ).first()
        cov = int(ov["cov"])

        spearman = d1 = d10 = None
        if cov:
            per_maker = (
                mk.groupBy("maker")
                .agg(F.sum("shares").alias("sh"), F.sum(F.col("mko_ps") * F.col("shares")).alias("dol"))
                .where(F.col("sh") > 0)
            ).persist()
            try:
                vd_order = Window.orderBy(F.col("sh").asc(), F.col("maker").asc())
                deciles = {
                    r["vd"]: r["m"]
                    for r in (
                        per_maker.withColumn("vd", F.ntile(10).over(vd_order))
                        .groupBy("vd")
                        .agg((F.sum("dol") / F.sum("sh")).alias("m"))
                        .collect()
                    )
                }
                d1, d10 = deciles.get(1), deciles.get(10)
                ranked = per_maker.withColumn(
                    "rv", F.rank().over(Window.orderBy(F.col("sh").asc()))
                ).withColumn("rm", F.rank().over(Window.orderBy((F.col("dol") / F.col("sh")).asc())))
                spearman = ranked.select(
                    F.corr(F.col("rv").cast("double"), F.col("rm").cast("double"))
                ).first()[0]
            finally:
                per_maker.unpersist()

        return {
            "horizon_s": d,
            "coverage": cov,
            "coverage_frac": (cov / n_maker_fills) if n_maker_fills else None,
            "mean_gap_s": (float(ov["sum_gap"]) / cov) if cov else None,
            "dollar_wtd_markout_ps": (float(ov["sum_dol"]) / float(ov["sum_sh"])) if ov["sum_sh"] else None,
            "mean_markout_ps": (float(ov["sum_mko"]) / cov) if cov else None,
            "frac_negative": (int(ov["neg"]) / cov) if cov else None,
            "total_dollar_markout": float(ov["sum_dol"]),
            "spearman_vol_markout": (float(spearman) if spearman is not None else None),
            "d1_markout_ps": (float(d1) if d1 is not None else None),
            "d10_markout_ps": (float(d10) if d10 is not None else None),
        }
    finally:
        mk.unpersist()


def markout_report(spark: SparkSession, paths: Sequence[str], horizons: Sequence[int] = HORIZONS) -> dict:
    """End-to-end report over ``paths``; same JSON shape as ``docs/maker_markout.json``."""
    fills = read_fills(spark, paths).persist()
    try:
        makers = maker_fills(fills).persist()
        prices = taker_vwap(fills).persist()
        try:
            n_maker_fills = makers.count()
            curve = [horizon_metrics(makers, prices, h, n_maker_fills) for h in horizons]
        finally:
            makers.unpersist()
            prices.unpersist()
    finally:
        fills.unpersist()
    return {
        "scope": "v2 on-chain record, MAKER markout vs horizon; outcome-independent (next-trade price)",
        "engine": "pyspark",
        "n_maker_fills": int(n_maker_fills),
        "curve": curve,
        "method": (
            "per maker fill, forward = first taker trade in [t+D, t+D+max(2D,900)] via a windowed as-of "
            "join; markout_ps = BUY:(p_fwd-p_fill)/SELL:(p_fill-p_fwd); negative=adverse selection"
        ),
        "caveats": [
            (
                "Distributed reimplementation of scripts/40_maker_markout.py (DuckDB) for cross-engine "
                "validation and horizontal scale; numerically equivalent on identical input "
                "(scripts/45_validate_markout_spark.py). The DuckDB version remains the replication source."
            ),
            (
                "The as-of join partitions by token_id over an unbounded-following frame; very hot tokens "
                "are skew points — salt or range-partition the token key for full-tape cluster runs."
            ),
            "Excludes the maker rebate; measures execution-level liquidity-provision return.",
        ],
    }

"""Bayesian wallet-skill calibration vs implied probability.

For each trade in a **resolved** market we know:

* the wallet (``proxy_wallet``);
* the outcome the trade took a position on (``asset_id`` → ``outcome_index``);
* the entry price ``p`` ∈ (0, 1), which equals the implied probability that
  outcome resolves true at the moment of trade;
* the direction (``side`` = BUY / SELL);
* the position size ``size`` and notional ``p * size``;
* the winning outcome (from ``winning_outcomes``).

We translate each trade into one or more **directional bets**:

* ``BUY`` of outcome X at price p — bets that X resolves true, at implied
  probability p. Wins if winning_outcome_index == outcome_index.
* ``SELL`` of outcome X at price p — bets that X resolves false, at
  implied probability (1 - p). Wins if winning_outcome_index != outcome_index.

Each share is a Bernoulli trial. Posterior over a wallet's "true" hit rate
relative to implied probability is then a Beta with conjugate update.

This module is intentionally model-light. Calibration relative to *implied*
probability (not against a benchmark) is the v2 §6.2 contract — we measure
``calibration_gap = posterior_mean_hit_rate − mean_entry_p``. A positive gap
means the wallet's actual win rate exceeded the prices they paid (i.e. they
have alpha or got lucky); a negative gap means they overpaid for risk.

For a Bayesian posterior we use a Beta prior centred on the wallet's own
average implied probability with weak strength (default ``prior_strength=4``),
which encodes "no edge" as the null hypothesis. The posterior mean is then:

    (alpha_prior + wins) / (alpha_prior + beta_prior + n)

with alpha_prior = mean_p * prior_strength and beta_prior = (1-mean_p) * prior_strength.
"""
from __future__ import annotations

from dataclasses import dataclass

import duckdb


# ---------------------------------------------------------------------------
# Per-trade bet construction
# ---------------------------------------------------------------------------

# Build a "bets" view: one row per (trade, side-effect), with implied
# probability and a 0/1 ``won`` flag computed against winning_outcomes.
_BETS_SQL = """
WITH base AS (
    SELECT t.proxy_wallet,
           t.condition_id,
           t.asset_id,
           t.outcome_index,
           t.side,
           t.price,
           t.size,
           t.notional_usdc,
           t.ts_utc,
           w.winning_outcome_index,
           DATE_DIFF('second', t.ts_utc, m.closed_time) / 3600.0 AS hours_to_close
    FROM trades t
    JOIN winning_outcomes w USING (condition_id)
    JOIN markets m USING (condition_id)
    WHERE t.proxy_wallet IS NOT NULL
      AND t.price IS NOT NULL
      AND t.price > 0 AND t.price < 1
      AND t.size IS NOT NULL AND t.size > 0
)
SELECT proxy_wallet,
       condition_id,
       outcome_index,
       side,
       price,
       size,
       notional_usdc,
       ts_utc,
       hours_to_close,
       winning_outcome_index,
       -- implied probability that the bet WINS:
       CASE WHEN side = 'BUY'  THEN price
            WHEN side = 'SELL' THEN 1.0 - price
            ELSE NULL END                      AS implied_p,
       -- did the bet WIN?
       CASE
         WHEN side = 'BUY'  AND outcome_index = winning_outcome_index THEN 1
         WHEN side = 'SELL' AND outcome_index <> winning_outcome_index THEN 1
         WHEN side IN ('BUY', 'SELL') THEN 0
         ELSE NULL
       END                                    AS won
FROM base
"""


def build_bets_view(con: duckdb.DuckDBPyConnection) -> None:
    """(Re)create the ``bets`` view in DuckDB. Idempotent."""
    con.execute(f"CREATE OR REPLACE VIEW bets AS {_BETS_SQL};")


# ---------------------------------------------------------------------------
# Bin-level calibration: for the universe view, bin ALL bets by implied
# probability and report realised hit rate per bin.
# ---------------------------------------------------------------------------

def calibration_by_bin(
    con: duckdb.DuckDBPyConnection,
    *,
    n_bins: int = 10,
    weight: str = "size",   # "size" | "notional" | "count"
) -> duckdb.DuckDBPyRelation:
    """Reliability table over the full universe, weighted by ``weight``.

    ``weight``:
        * ``"size"`` weights each bet by share count (canonical for Bernoulli).
        * ``"notional"`` weights by dollar notional (matches dollar-weighted PnL).
        * ``"count"`` treats every trade as one observation.
    """
    if weight == "size":
        w_expr = "size"
    elif weight == "notional":
        w_expr = "notional_usdc"
    elif weight == "count":
        w_expr = "1.0"
    else:
        raise ValueError(weight)

    return con.sql(f"""
        WITH binned AS (
            SELECT FLOOR(implied_p * {n_bins})::INT AS bin_idx,
                   implied_p,
                   won,
                   {w_expr} AS w
            FROM bets
            WHERE implied_p IS NOT NULL AND won IS NOT NULL
        )
        SELECT bin_idx,
               (bin_idx + 0.5) / {n_bins}                             AS bin_midpoint,
               COUNT(*)                                                AS n_trades,
               SUM(w)                                                  AS total_weight,
               SUM(w * implied_p) / NULLIF(SUM(w), 0)                  AS mean_implied_p,
               SUM(w * won)       / NULLIF(SUM(w), 0)                  AS realised_hit_rate,
               (SUM(w * won) - SUM(w * implied_p)) / NULLIF(SUM(w), 0) AS calibration_gap
        FROM binned
        GROUP BY bin_idx
        ORDER BY bin_idx;
    """)


# ---------------------------------------------------------------------------
# Per-wallet Bayesian skill score
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SkillConfig:
    """Tunables for the Beta posterior."""

    # Strength (alpha + beta) of the prior centred on the wallet's mean implied_p.
    # 4 corresponds to a "two wins, two losses" weight — weak.
    prior_strength: float = 4.0

    # Minimum number of resolved trades for a wallet to be reported.
    min_trades: int = 5

    # If true, weight Bernoulli observations by share size (canonical for
    # variable-size bets). If false, treat each trade as one Bernoulli trial.
    size_weighted: bool = True


def wallet_skill(
    con: duckdb.DuckDBPyConnection,
    *,
    cfg: SkillConfig | None = None,
) -> duckdb.DuckDBPyRelation:
    """Posterior over each wallet's expected hit rate vs implied probability.

    Output columns:
        proxy_wallet, n_trades, total_size, total_notional,
        n_markets, mean_implied_p, realised_hit_rate,
        prior_alpha, prior_beta, posterior_alpha, posterior_beta,
        posterior_mean_hit_rate, calibration_gap, ci_low, ci_high

    ``ci_low`` / ``ci_high`` are a **normal approximation** (posterior mean
    ± 1.645 posterior sd, clipped to [0, 1]) — not exact Beta quantiles; use
    :func:`position_skill` for exact intervals.

    Caveat (audit 2026-08-29): with ``size_weighted=True`` every share is a
    Bernoulli trial, so the effective n is thousands and the prior is inert;
    and because ``/trades`` is capped at the last ~4000 fills per market,
    ~93% of size-weight sits at implied p ≤ 0.01 or ≥ 0.99 where the outcome
    is already known. The headline skill statistic is therefore
    :func:`position_skill`, which counts one trial per (wallet, market) and
    keeps only positions priced in an informative band.
    """
    cfg = cfg or SkillConfig()
    w_expr = "size" if cfg.size_weighted else "1.0"
    return con.sql(f"""
        WITH per_wallet AS (
            SELECT proxy_wallet,
                   COUNT(*)                                        AS n_trades,
                   COUNT(DISTINCT condition_id)                    AS n_markets,
                   SUM(size)                                       AS total_size,
                   SUM(notional_usdc)                              AS total_notional,
                   SUM({w_expr})                                   AS w_total,
                   SUM({w_expr} * implied_p)                       AS w_implied,
                   SUM({w_expr} * won)                             AS w_won
            FROM bets
            WHERE implied_p IS NOT NULL AND won IS NOT NULL
              AND proxy_wallet IS NOT NULL
            GROUP BY proxy_wallet
            HAVING COUNT(*) >= {cfg.min_trades}
        ),
        priors AS (
            SELECT *,
                   w_implied / NULLIF(w_total, 0)                  AS mean_implied_p,
                   w_won     / NULLIF(w_total, 0)                  AS realised_hit_rate,
                   (w_implied / NULLIF(w_total, 0)) * {cfg.prior_strength}             AS prior_alpha,
                   (1.0 - w_implied / NULLIF(w_total, 0)) * {cfg.prior_strength}       AS prior_beta
            FROM per_wallet
        ),
        post AS (
            SELECT *,
                   prior_alpha + w_won                                                  AS posterior_alpha,
                   prior_beta  + (w_total - w_won)                                      AS posterior_beta
            FROM priors
        )
        SELECT proxy_wallet,
               n_trades, n_markets, total_size, total_notional,
               mean_implied_p,
               realised_hit_rate,
               prior_alpha, prior_beta,
               posterior_alpha, posterior_beta,
               posterior_alpha / (posterior_alpha + posterior_beta)  AS posterior_mean_hit_rate,
               posterior_alpha / (posterior_alpha + posterior_beta) - mean_implied_p
                                                                     AS calibration_gap,
               -- Beta CI via SciPy is more accurate; we approximate with
               -- Wilson-style symmetric interval on the posterior mean using
               -- variance = ab / ((a+b)^2 (a+b+1)).
               GREATEST(0.0,
                 posterior_alpha / (posterior_alpha + posterior_beta)
                 - 1.645 * SQRT( (posterior_alpha * posterior_beta)
                                 / (POWER(posterior_alpha + posterior_beta, 2)
                                    * (posterior_alpha + posterior_beta + 1.0))))     AS ci_low,
               LEAST(1.0,
                 posterior_alpha / (posterior_alpha + posterior_beta)
                 + 1.645 * SQRT( (posterior_alpha * posterior_beta)
                                 / (POWER(posterior_alpha + posterior_beta, 2)
                                    * (posterior_alpha + posterior_beta + 1.0))))     AS ci_high
        FROM post
        ORDER BY calibration_gap DESC NULLS LAST;
    """)


def wallet_pnl(con: duckdb.DuckDBPyConnection, *,
               condition_ids: list[str] | None = None) -> duckdb.DuckDBPyRelation:
    """Realised dollar PnL per wallet across resolved markets.

    For a BUY of outcome X at price p, size s:
        winning bet: payoff = (1 - p) * s   (paid $1, paid $p, profit $1 - p)
        losing bet:  payoff = -p * s
    For a SELL at price p (= short the outcome), the wallet effectively
    earned $p upfront and owes $1 if the outcome resolves true:
        winning bet (outcome resolves false): payoff = p * s
        losing bet  (outcome resolves true):  payoff = (p - 1) * s

    ``realised_pnl_usdc`` marks every fill to resolution (a buy→sell round
    trip nets to its cash flow exactly). Because ``/trades`` is a tail sample,
    a SELL frequently has no in-sample BUY: 63% of sold shares in the
    2026-05-11 corpus are uncovered, and treating them as shorts held to
    resolution inflates the PnL of wallets that merely liquidated earlier
    positions. ``realised_pnl_covered_usdc`` therefore scales each
    (wallet, market, outcome) position's SELL leg by
    ``min(1, bought / sold)`` and reports the uncovered remainder separately.
    Use the covered figure for rankings.

    ``condition_ids`` restricts the computation to a subset of markets (for
    train / test splits).
    """
    market_filter = ""
    if condition_ids is not None:
        cids = ",".join(f"'{c}'" for c in condition_ids)
        market_filter = f"AND t.condition_id IN ({cids})"
    return con.sql(f"""
        WITH base AS (
            SELECT t.proxy_wallet, t.condition_id, t.outcome_index,
                   t.side, t.price, t.size,
                   CASE WHEN t.outcome_index = w.winning_outcome_index THEN 1 ELSE 0 END AS outcome_won
            FROM trades t
            JOIN winning_outcomes w USING (condition_id)
            WHERE t.proxy_wallet IS NOT NULL
              AND t.price > 0 AND t.price < 1
              AND t.size > 0
              AND t.side IN ('BUY', 'SELL')
              {market_filter}
        ),
        pos AS (
            SELECT proxy_wallet, condition_id, outcome_index,
                   COUNT(*)                                                  AS n_trades,
                   COALESCE(SUM(CASE WHEN side = 'BUY'  THEN size END), 0)  AS bought,
                   COALESCE(SUM(CASE WHEN side = 'SELL' THEN size END), 0)  AS sold,
                   COALESCE(SUM(CASE WHEN side = 'BUY'  THEN (outcome_won - price) * size END), 0) AS pnl_buy,
                   COALESCE(SUM(CASE WHEN side = 'SELL' THEN (price - outcome_won) * size END), 0) AS pnl_sell
            FROM base
            GROUP BY 1, 2, 3
        ),
        covered AS (
            SELECT *,
                   CASE WHEN sold = 0 THEN 1.0 ELSE LEAST(1.0, bought / sold) END AS covered_frac
            FROM pos
        )
        SELECT proxy_wallet,
               SUM(n_trades)                                    AS n_trades,
               COUNT(*)                                         AS n_positions,
               COUNT(DISTINCT condition_id)                     AS n_markets,
               SUM(pnl_buy + pnl_sell)                          AS realised_pnl_usdc,
               SUM(pnl_buy + pnl_sell * covered_frac)           AS realised_pnl_covered_usdc,
               SUM(pnl_sell * (1.0 - covered_frac))             AS uncovered_sell_pnl_usdc,
               SUM(GREATEST(sold - bought, 0))                  AS uncovered_sell_shares
        FROM covered
        GROUP BY proxy_wallet
        ORDER BY realised_pnl_covered_usdc DESC NULLS LAST;
    """)


# ---------------------------------------------------------------------------
# Position-level skill (headline statistic since the 2026-08-29 audit)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class PositionSkillConfig:
    """Tunables for the position-level calibration test."""

    prior_strength: float = 4.0     # alpha + beta of the prior centred on mean implied p
    min_positions: int = 5          # trials required to report a wallet
    min_markets: int = 3            # distinct markets required
    p_low: float = 0.05             # informative band on the position's entry-implied p
    p_high: float = 0.95
    min_hours_to_close: float = 0.0  # optionally exclude trades in the last N hours


def position_skill(
    con: duckdb.DuckDBPyConnection,
    *,
    cfg: PositionSkillConfig | None = None,
    condition_ids: list[str] | None = None,
) -> "pl.DataFrame":
    """One Bernoulli trial per (wallet, market): the wallet's net in-sample direction.

    For a binary market every fill is a signed exposure to outcome 0 winning
    (BUY outcome 0 / SELL outcome 1 → +size; BUY outcome 1 / SELL outcome 0 →
    −size). The position's direction is the sign of the net exposure, its
    entry-implied probability is the size-weighted mean implied p of the
    fills in that direction, and it wins if the direction matches the
    resolved outcome. Positions whose implied p lies outside
    ``[p_low, p_high]`` are dropped as uninformative (post-convergence dust,
    which dominates the tail-sampled trade data).

    The Beta prior (strength ``prior_strength``) is centred on the wallet's
    mean implied p over its informative positions, so the null is "wins at
    the rate it paid for". ``calibration_gap = posterior_mean − mean_implied_p``.
    ``ci_low`` / ``ci_high`` are exact 5% / 95% Beta posterior quantiles
    (scipy); ``p_gap_positive`` is the posterior probability that the wallet's
    hit rate exceeds its mean implied p. ``excess_over_reliability_curve`` is
    the mean of (won − leave-one-out corpus hit rate in the position's
    implied-p decile): the edge beyond the favourite–longshot bias that every
    participant in this corpus enjoyed. Returns a Polars DataFrame sorted by
    calibration_gap descending.
    """
    import polars as pl
    from scipy.stats import beta as beta_dist

    cfg = cfg or PositionSkillConfig()
    market_filter = ""
    if condition_ids is not None:
        cids = ",".join(f"'{c}'" for c in condition_ids)
        market_filter = f"AND condition_id IN ({cids})"
    df = con.sql(f"""
        WITH b AS (
            SELECT proxy_wallet, condition_id, size, notional_usdc,
                   CASE WHEN (side = 'BUY' AND outcome_index = 0)
                          OR (side = 'SELL' AND outcome_index <> 0) THEN 1 ELSE -1 END AS dir0,
                   CASE WHEN (side = 'BUY' AND outcome_index = 0)
                          OR (side = 'SELL' AND outcome_index <> 0) THEN implied_p
                        ELSE 1.0 - implied_p END                                        AS p0,
                   CASE WHEN winning_outcome_index = 0 THEN 1 ELSE 0 END               AS won0
            FROM bets
            WHERE implied_p IS NOT NULL AND won IS NOT NULL
              AND outcome_index IN (0, 1)
              AND hours_to_close >= {cfg.min_hours_to_close}
              {market_filter}
        ),
        pos AS (
            SELECT proxy_wallet, condition_id,
                   SUM(dir0 * size)                                              AS net_exposure,
                   SUM(notional_usdc)                                            AS notional,
                   ANY_VALUE(won0)                                               AS won0,
                   SUM(CASE WHEN dir0 = 1  THEN size * p0 END)
                     / NULLIF(SUM(CASE WHEN dir0 = 1  THEN size END), 0)         AS p_long,
                   SUM(CASE WHEN dir0 = -1 THEN size * (1.0 - p0) END)
                     / NULLIF(SUM(CASE WHEN dir0 = -1 THEN size END), 0)         AS p_short
            FROM b
            GROUP BY 1, 2
            HAVING SUM(dir0 * size) <> 0
        ),
        trials AS (
            SELECT proxy_wallet, condition_id, notional,
                   CASE WHEN net_exposure > 0 THEN p_long ELSE p_short END       AS implied_p,
                   CASE WHEN net_exposure > 0 THEN won0 ELSE 1 - won0 END        AS won
            FROM pos
        ),
        informative AS (
            SELECT * FROM trials
            WHERE implied_p BETWEEN {cfg.p_low} AND {cfg.p_high}
        ),
        -- corpus reliability curve at position level, 10 bins: the realised
        -- hit rate of *everyone* who took a position at that price. A wallet
        -- is only 'skilled' beyond the favourite-longshot bias of the corpus
        -- if it beats this curve, not the diagonal.
        bins AS (
            SELECT FLOOR(implied_p * 10)::INT AS bin_idx,
                   AVG(won) AS bin_hit_rate, COUNT(*) AS bin_n
            FROM informative GROUP BY 1
        ),
        scored AS (
            SELECT i.*, b.bin_hit_rate,
                   -- leave-one-out so a wallet's own trial does not benchmark itself
                   CASE WHEN b.bin_n > 1
                        THEN (b.bin_hit_rate * b.bin_n - i.won) / (b.bin_n - 1)
                        ELSE NULL END AS bin_hit_rate_loo
            FROM informative i
            JOIN bins b ON b.bin_idx = FLOOR(i.implied_p * 10)::INT
        )
        SELECT proxy_wallet,
               COUNT(*)                        AS n_positions,
               COUNT(DISTINCT condition_id)    AS n_markets,
               SUM(notional)                   AS total_notional,
               AVG(implied_p)                  AS mean_implied_p,
               AVG(won)                        AS realised_hit_rate,
               SUM(won)                        AS wins,
               AVG(won - bin_hit_rate_loo)     AS excess_over_reliability_curve
        FROM scored
        GROUP BY proxy_wallet
        HAVING COUNT(*) >= {cfg.min_positions}
           AND COUNT(DISTINCT condition_id) >= {cfg.min_markets}
    """).pl()
    if df.is_empty():
        return df
    ps = cfg.prior_strength
    df = df.with_columns(
        (pl.col("mean_implied_p") * ps).alias("prior_alpha"),
        ((1.0 - pl.col("mean_implied_p")) * ps).alias("prior_beta"),
    ).with_columns(
        (pl.col("prior_alpha") + pl.col("wins")).alias("posterior_alpha"),
        (pl.col("prior_beta") + pl.col("n_positions") - pl.col("wins")).alias("posterior_beta"),
    ).with_columns(
        (pl.col("posterior_alpha") / (pl.col("posterior_alpha") + pl.col("posterior_beta")))
        .alias("posterior_mean_hit_rate")
    ).with_columns(
        (pl.col("posterior_mean_hit_rate") - pl.col("mean_implied_p")).alias("calibration_gap")
    )
    a = df["posterior_alpha"].to_numpy(); bb = df["posterior_beta"].to_numpy()
    df = df.with_columns(
        pl.Series("ci_low", beta_dist.ppf(0.05, a, bb)),
        pl.Series("ci_high", beta_dist.ppf(0.95, a, bb)),
        # posterior probability that the true hit rate exceeds the paid-for rate
        pl.Series("p_gap_positive", 1.0 - beta_dist.cdf(df["mean_implied_p"].to_numpy(), a, bb)),
    )
    return df.sort("calibration_gap", descending=True)

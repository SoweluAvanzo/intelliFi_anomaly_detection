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
           w.winning_outcome_index
    FROM trades t
    JOIN winning_outcomes w USING (condition_id)
    WHERE t.proxy_wallet IS NOT NULL
      AND t.price IS NOT NULL
      AND t.price > 0 AND t.price < 1
      AND t.size IS NOT NULL AND t.size > 0
)
SELECT proxy_wallet,
       condition_id,
       outcome_index,
       side,
       size,
       notional_usdc,
       ts_utc,
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

    ``ci_low`` / ``ci_high`` are the 5% / 95% quantiles of the Beta posterior.
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


def wallet_pnl(con: duckdb.DuckDBPyConnection) -> duckdb.DuckDBPyRelation:
    """Realised dollar PnL per wallet across resolved markets.

    For a BUY of outcome X at price p, size s:
        winning bet: payoff = (1 - p) * s   (paid $1, paid $p, profit $1 - p)
        losing bet:  payoff = -p * s
    For a SELL at price p (= short the outcome), the wallet effectively
    earned $p upfront and owes $1 if the outcome resolves true:
        winning bet (outcome resolves false): payoff = p * s
        losing bet  (outcome resolves true):  payoff = (p - 1) * s

    These are notional-equivalent PnL units, not USDC realized cash flow
    (which would require netting against the wallet's full position book).
    """
    return con.sql("""
        WITH base AS (
            SELECT t.proxy_wallet,
                   t.side,
                   t.price,
                   t.size,
                   CASE WHEN t.outcome_index = w.winning_outcome_index THEN 1 ELSE 0 END AS outcome_won
            FROM trades t
            JOIN winning_outcomes w USING (condition_id)
            WHERE t.proxy_wallet IS NOT NULL
              AND t.price BETWEEN 0 AND 1
              AND t.size > 0
        ),
        pnl AS (
            SELECT proxy_wallet,
                   CASE
                     WHEN side = 'BUY'  AND outcome_won = 1 THEN (1.0 - price) * size
                     WHEN side = 'BUY'  AND outcome_won = 0 THEN -price * size
                     WHEN side = 'SELL' AND outcome_won = 0 THEN price * size
                     WHEN side = 'SELL' AND outcome_won = 1 THEN (price - 1.0) * size
                     ELSE 0.0
                   END AS pnl
            FROM base
        )
        SELECT proxy_wallet,
               COUNT(*)                AS n_trades,
               SUM(pnl)                AS realised_pnl_usdc
        FROM pnl
        GROUP BY proxy_wallet
        ORDER BY realised_pnl_usdc DESC NULLS LAST;
    """)

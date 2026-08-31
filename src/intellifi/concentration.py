"""Wallet concentration metrics: Gini, top-N share, HHI.

All metrics are computed over **non-negative wallet weights** for a single
market (or family). Two natural weight choices are exposed:

* ``trade_notional`` — sum of ``price * size`` across all trades by wallet.
  Captures *trading activity* concentration. Robust on resolved markets
  because we have the trade-level data (subject to the 4000-trade cap
  documented in ``data_api``).
* ``net_flow`` — |Σ signed notional| per wallet toward outcome 0. Nets out
  two-sided liquidity provision, so it measures *directional* footprint.
* ``holdings_amount`` — wallet's outcome-share balance from the holders
  snapshot taken at fetch time (2026-05-11, after every market's close).
  Caveats (audit 2026-08-29): winners redeem and burn, so most remaining
  weight is on the losing outcome (unredeemed positions), and ``/holders``
  returns at most 500 holders per outcome token, so 92/100 markets are
  truncated and their Gini is biased downward.

All trade-based weights are **taker-side only**: the Data API records one
row per fill, for the taker; maker flow is invisible (audit 2026-08-29).

Both metrics expose a ``per_market`` and a ``per_family`` form so we can
respect the v2 spec rule (§4.4): for negRisk markets, consolidate flow
across the whole family before signing pressure / concentration.

The functions return a DuckDB relation (lazy) so callers can compose them
into larger queries without materialising intermediate results.
"""
from __future__ import annotations

from typing import Literal

import duckdb

WeightKind = Literal["trade_notional", "net_flow", "holdings_amount"]


# ---------------------------------------------------------------------------
# Pure-SQL primitives. All operate on a CTE-style "wallets" table with
# columns (group_key, proxy_wallet, weight).
# ---------------------------------------------------------------------------

# Gini coefficient via the canonical sorted-share formula. For n wallets
# with non-negative weights w_i (sorted ascending), G = (2 * Σ i * w_i) /
# (n * Σ w_i) - (n + 1) / n.
#
# These are SQL **fragments** meant to be embedded as CTEs — no trailing
# semicolons.
_GINI_HHI_BODY = """
    SELECT group_key,
           proxy_wallet,
           weight,
           row_number() OVER (PARTITION BY group_key ORDER BY weight ASC)  AS rk,
           SUM(weight)  OVER (PARTITION BY group_key)                      AS total_w,
           COUNT(*)     OVER (PARTITION BY group_key)                      AS n_w
    FROM wallets
    WHERE weight > 0
"""

# Outer aggregation. References the CTE produced from ``_GINI_HHI_BODY``.
# ``total_w`` and ``n_w`` are constant within each group_key (computed via
# window funcs), so ANY_VALUE / MAX is just a way to surface them through the
# GROUP BY without nesting aggregates.
_GINI_HHI_AGG = """
    SELECT group_key,
           any_value(n_w)                                                  AS n_wallets,
           any_value(total_w)                                              AS total_weight,
           CASE WHEN any_value(n_w) <= 1 OR any_value(total_w) = 0 THEN NULL
                ELSE (2.0 * SUM(rk * weight))
                     / (any_value(n_w) * any_value(total_w))
                     - (any_value(n_w) + 1.0) / any_value(n_w)
           END                                                             AS gini,
           SUM(POWER(weight / NULLIF(total_w, 0), 2))                      AS hhi
    FROM ordered
    GROUP BY group_key
"""

_TOPN_SHARE_BODY = """
    SELECT group_key,
           proxy_wallet,
           weight,
           SUM(weight) OVER (PARTITION BY group_key)                       AS total_weight,
           row_number() OVER (PARTITION BY group_key ORDER BY weight DESC) AS rk
    FROM wallets
    WHERE weight > 0
"""

_TOPN_SHARE_AGG = """
    SELECT group_key,
           SUM(CASE WHEN rk <=  1 THEN weight ELSE 0 END) / NULLIF(MAX(total_weight), 0) AS top1_share,
           SUM(CASE WHEN rk <=  5 THEN weight ELSE 0 END) / NULLIF(MAX(total_weight), 0) AS top5_share,
           SUM(CASE WHEN rk <= 10 THEN weight ELSE 0 END) / NULLIF(MAX(total_weight), 0) AS top10_share,
           SUM(CASE WHEN rk <= 25 THEN weight ELSE 0 END) / NULLIF(MAX(total_weight), 0) AS top25_share
    FROM ranked
    GROUP BY group_key
"""


def _wallet_weights_sql(weight: WeightKind, group: Literal["market", "family"]) -> str:
    """Return SQL that produces a ``wallets(group_key, proxy_wallet, weight)`` CTE."""
    if group == "market":
        group_expr = "t.condition_id"
        family_join = ""
    elif group == "family":
        group_expr = "COALESCE(f.family_event_id, 'M:' || t.condition_id)"
        family_join = "LEFT JOIN neg_risk_families f ON f.member_condition_id = t.condition_id"
    else:
        raise ValueError(group)

    if weight == "trade_notional":
        return f"""
        SELECT {group_expr}            AS group_key,
               t.proxy_wallet          AS proxy_wallet,
               SUM(t.notional_usdc)    AS weight
        FROM trades t
        {family_join}
        WHERE t.proxy_wallet IS NOT NULL
          AND t.notional_usdc IS NOT NULL
          AND t.notional_usdc > 0
        GROUP BY 1, 2
        """

    if weight == "net_flow":
        # |Σ signed notional| toward outcome 0 (BUY outcome 0 / SELL outcome 1
        # positive): a directional footprint that nets out two-sided
        # liquidity provision, which gross notional counts as 'control'.
        return f"""
        SELECT {group_expr}            AS group_key,
               t.proxy_wallet          AS proxy_wallet,
               ABS(SUM(CASE WHEN (t.side = 'BUY' AND t.outcome_index = 0)
                              OR (t.side = 'SELL' AND t.outcome_index <> 0)
                            THEN t.notional_usdc ELSE -t.notional_usdc END)) AS weight
        FROM trades t
        {family_join}
        WHERE t.proxy_wallet IS NOT NULL
          AND t.notional_usdc IS NOT NULL
          AND t.notional_usdc > 0
          AND t.side IN ('BUY', 'SELL')
        GROUP BY 1, 2
        """

    if weight == "holdings_amount":
        # Sum across outcomes within a market or family so a wallet that
        # holds both sides (e.g. arb / wash) is counted as a single weight.
        if group == "market":
            holder_group = "h.condition_id"
            holder_join = ""
        else:
            holder_group = "COALESCE(f.family_event_id, 'M:' || h.condition_id)"
            holder_join = "LEFT JOIN neg_risk_families f ON f.member_condition_id = h.condition_id"
        return f"""
        SELECT {holder_group}      AS group_key,
               h.proxy_wallet      AS proxy_wallet,
               SUM(h.amount)       AS weight
        FROM holders h
        {holder_join}
        WHERE h.proxy_wallet IS NOT NULL
          AND h.amount IS NOT NULL
          AND h.amount > 0
        GROUP BY 1, 2
        """

    raise ValueError(weight)


def concentration_table(
    con: duckdb.DuckDBPyConnection,
    *,
    weight: WeightKind = "trade_notional",
    group: Literal["market", "family"] = "market",
) -> duckdb.DuckDBPyRelation:
    """Return one row per market/family with Gini + topN + HHI + n_wallets.

    Joins with ``markets`` (or ``neg_risk_families``) so the result carries
    human-readable labels (``slug``, ``question``) alongside the metrics.
    """
    wallets_sql = _wallet_weights_sql(weight, group)

    if group == "market":
        label_sql = """
        SELECT m.condition_id AS group_key,
               m.slug, m.question, m.neg_risk, m.event_id,
               m.volume_clob,
               m.outcome_prices_final
        FROM markets m
        """
        order_by = "ORDER BY volume_clob DESC NULLS LAST"
    else:
        # One row per group: a negRisk family (all member markets pooled) or
        # a standalone market keyed 'M:<condition_id>'. volume_clob is summed
        # within the group only.
        label_sql = """
        SELECT COALESCE(f.family_event_id, 'M:' || m.condition_id) AS group_key,
               COALESCE(any_value(f.family_event_slug), any_value(m.slug)) AS slug,
               -- pick any member question as representative
               any_value(m.question)                 AS question,
               bool_or(m.neg_risk)                   AS neg_risk,
               COALESCE(any_value(f.family_event_id), any_value(m.event_id)) AS event_id,
               SUM(m.volume_clob)                    AS volume_clob
        FROM markets m
        LEFT JOIN neg_risk_families f ON f.member_condition_id = m.condition_id
        WHERE f.family_event_id IS NOT NULL OR NOT m.neg_risk
        GROUP BY 1
        """
        order_by = "ORDER BY volume_clob DESC NULLS LAST"

    full_sql = f"""
    WITH wallets  AS ({wallets_sql}),
         ordered  AS ({_GINI_HHI_BODY}),
         gini_hhi AS ({_GINI_HHI_AGG}),
         ranked   AS ({_TOPN_SHARE_BODY}),
         topn     AS ({_TOPN_SHARE_AGG}),
         labels   AS ({label_sql})
    SELECT l.group_key,
           l.slug,
           l.question,
           l.neg_risk,
           l.event_id,
           l.volume_clob,
           g.n_wallets,
           g.total_weight,
           g.gini,
           g.hhi,
           t.top1_share,
           t.top5_share,
           t.top10_share,
           t.top25_share
    FROM labels l
    LEFT JOIN gini_hhi g ON g.group_key = l.group_key
    LEFT JOIN topn     t ON t.group_key = l.group_key
    {order_by};
    """
    return con.sql(full_sql)


def wallet_universe(
    con: duckdb.DuckDBPyConnection,
    *,
    weight: WeightKind = "trade_notional",
) -> duckdb.DuckDBPyRelation:
    """Aggregate weight per wallet across the entire universe.

    Useful for the cross-market concentration view (#1 at the platform level,
    not per market).
    """
    if weight == "trade_notional":
        return con.sql("""
            SELECT proxy_wallet,
                   SUM(notional_usdc) AS total_notional,
                   COUNT(*)           AS n_trades,
                   COUNT(DISTINCT condition_id) AS n_markets
            FROM trades
            WHERE proxy_wallet IS NOT NULL
              AND notional_usdc IS NOT NULL
              AND notional_usdc > 0
            GROUP BY proxy_wallet
            ORDER BY total_notional DESC;
        """)
    if weight == "holdings_amount":
        return con.sql("""
            SELECT proxy_wallet,
                   SUM(amount)        AS total_amount,
                   COUNT(*)           AS n_positions,
                   COUNT(DISTINCT condition_id) AS n_markets
            FROM holders
            WHERE proxy_wallet IS NOT NULL
              AND amount IS NOT NULL
              AND amount > 0
            GROUP BY proxy_wallet
            ORDER BY total_amount DESC;
        """)
    raise ValueError(weight)

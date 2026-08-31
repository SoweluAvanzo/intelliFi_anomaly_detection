"""Mirror-strategy backtest on the resolved-market universe.

The basic question: if you had taken the same direction as a "leader" wallet
within ``latency_seconds`` after they entered, would you have made money?

For each leader trade at time t on asset X with side S (BUY/SELL), we:

1. Look up the **execution price** at t + latency_seconds (using trade-VWAP
   aggregation over the surrounding minute as a proxy for the next available
   fill).
2. Look up the **exit price** at min(t + horizon, market_resolution).
3. Compute mirror PnL per unit position size:
       BUY:  pnl = exit - entry         (if outcome resolves YES at exit_at_resolution)
       SELL: pnl = entry - exit
4. Aggregate hit rate, average return, Sharpe-ish, total PnL.

We deliberately keep the price model lightweight (trade-VWAP per minute)
because the Data API trade horizon is capped at the most-recent ~4000
trades per market, which is short enough that a full CLOB pricing series
isn't strictly necessary. For long-horizon backtests, the CLOB
``/prices-history`` ingest (Stage 8) provides a higher-fidelity series.

Costs:

* The strategy pays ``fee_bps`` on each side of the round-trip (default
  ``20 bps`` = 0.2%, broadly matching Polymarket's fee schedule).
* Slippage is captured implicitly by using the next-minute VWAP rather than
  the exact leader entry price.

Inputs come from the DuckDB warehouse and the existing parquet writers; no
new fetches are required for ``mode='trade_vwap'``.
"""
from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

import duckdb
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-(asset, minute) price series via trade VWAP
# ---------------------------------------------------------------------------

def build_minute_vwap_view(con: duckdb.DuckDBPyConnection) -> None:
    """Create / replace ``trades_minute_vwap``: one row per (asset_id, minute) with VWAP.

    VWAP = Σ(price × size) / Σ(size) within the minute. Empty minutes are
    absent from the view; the caller forward-fills as needed.
    """
    con.execute("""
        CREATE OR REPLACE VIEW trades_minute_vwap AS
        SELECT asset_id,
               condition_id,
               date_trunc('minute', ts_utc)        AS minute_utc,
               SUM(notional_usdc)                  AS minute_notional,
               SUM(size)                           AS minute_size,
               SUM(price * size) / NULLIF(SUM(size), 0) AS vwap,
               COUNT(*)                            AS trade_count
        FROM trades
        WHERE asset_id IS NOT NULL AND ts_utc IS NOT NULL
          AND price BETWEEN 0 AND 1 AND size > 0
        GROUP BY asset_id, condition_id, minute_utc
        ORDER BY asset_id, minute_utc;
    """)


# ---------------------------------------------------------------------------
# Leader-trade event extraction
# ---------------------------------------------------------------------------

def leader_events(
    con: duckdb.DuckDBPyConnection,
    *,
    leaders: list[str],
    min_notional: float = 1000.0,
    condition_ids: list[str] | None = None,
    exclude_post_convergence: bool = True,
) -> duckdb.DuckDBPyRelation:
    """Trades by the supplied leader wallets above a notional threshold.

    ``condition_ids`` restricts events to a market subset (evaluation set);
    ``exclude_post_convergence`` drops trades after ``market_event_ts``.
    """
    addrs = ",".join(f"'{a.lower()}'" for a in leaders)
    market_filter = ""
    if condition_ids is not None:
        cids = ",".join(f"'{c}'" for c in condition_ids)
        market_filter = f"AND t.condition_id IN ({cids})"
    conv_filter = "AND t.ts_utc <= e.event_ts" if exclude_post_convergence else ""
    build_event_ts_view(con)
    return con.sql(f"""
        SELECT t.proxy_wallet, t.condition_id, t.asset_id, t.outcome_index,
               t.side, t.price, t.size, t.notional_usdc, t.ts_utc,
               COALESCE(m.closed_time, m.end_date) AS closed_time,
               e.event_ts
        FROM trades t
        JOIN markets m USING (condition_id)
        JOIN market_event_ts e USING (condition_id)
        WHERE t.proxy_wallet IN ({addrs})
          AND t.notional_usdc >= {min_notional}
          AND t.price BETWEEN 0.02 AND 0.98
          AND t.ts_utc IS NOT NULL
          {market_filter}
          {conv_filter}
        ORDER BY t.ts_utc, t.proxy_wallet, t.asset_id, t.notional_usdc;
    """)


def build_event_ts_view(con: duckdb.DuckDBPyConnection) -> None:
    """``market_event_ts``: per market, the last instant the outcome was still open.

    Defined from the trade sample as the last trade at which the eventual
    winner traded below 0.95 (or the loser above 0.05). After that point the
    sample shows only converged prices, so a leader trade later than
    ``event_ts`` was placed when the outcome was already priced in — copying
    it measures settlement convergence, not information (audit 2026-08-29).
    If the whole sample is converged, ``event_ts`` is the first sampled trade.
    """
    con.execute("""
        CREATE OR REPLACE VIEW market_event_ts AS
        SELECT t.condition_id,
               COALESCE(MAX(CASE WHEN (t.outcome_index =  w.winning_outcome_index AND t.price < 0.95)
                                   OR (t.outcome_index <> w.winning_outcome_index AND t.price > 0.05)
                                 THEN t.ts_utc END),
                        MIN(t.ts_utc)) AS event_ts
        FROM trades t
        JOIN winning_outcomes w USING (condition_id)
        WHERE t.price IS NOT NULL AND t.ts_utc IS NOT NULL
        GROUP BY 1;
    """)


def matched_control_events(
    con: duckdb.DuckDBPyConnection,
    events: pd.DataFrame,
    *,
    exclude_wallets: list[str],
    window_seconds: int = 900,
    max_price_diff: float = 0.05,
    per_event: int = 3,
    min_notional: float = 1000.0,
    seed: int = 42,
) -> pd.DataFrame:
    """Placebo events matched to each leader event.

    For every leader event, up to ``per_event`` trades by wallets outside
    ``exclude_wallets`` on the **same asset and side within ±window_seconds
    and ±max_price_diff** are drawn (deterministically, by hashed tx id).
    Mirroring them with the same engine gives the return an uninformed
    follower would have earned at the same place and time — the baseline
    against which a leader set's edge must be judged. The returned frame has
    the same columns as :func:`leader_events` plus ``matched_event_idx``.
    """
    if events.empty:
        return pd.DataFrame()
    ev = events.reset_index(drop=True).copy()
    ev["matched_event_idx"] = ev.index
    ts_col = "ts_utc" if "ts_utc" in ev.columns else "leader_ts"
    ev_sql = ev[["matched_event_idx", "condition_id", "asset_id", "side", "price", ts_col]].rename(
        columns={ts_col: "ts_utc"})
    ev_sql["ts_utc"] = pd.to_datetime(ev_sql["ts_utc"], utc=True)
    con.register("leader_ev_tmp", ev_sql)
    excl = ",".join(f"'{a.lower()}'" for a in exclude_wallets) or "''"
    build_event_ts_view(con)
    df = con.sql(f"""
        WITH cand AS (
            SELECT l.matched_event_idx,
                   t.proxy_wallet, t.condition_id, t.asset_id, t.outcome_index,
                   t.side, t.price, t.size, t.notional_usdc, t.ts_utc,
                   COALESCE(m.closed_time, m.end_date) AS closed_time,
                   e.event_ts,
                   row_number() OVER (PARTITION BY l.matched_event_idx
                                      ORDER BY md5(t.tx_hash || '{seed}')) AS rk
            FROM leader_ev_tmp l
            JOIN trades t ON t.asset_id = l.asset_id AND t.side = l.side
                         AND ABS(EPOCH(t.ts_utc) - EPOCH(l.ts_utc)) <= {window_seconds}
                         AND ABS(t.price - l.price) <= {max_price_diff}
            JOIN markets m ON m.condition_id = t.condition_id
            JOIN market_event_ts e ON e.condition_id = t.condition_id
            WHERE t.proxy_wallet NOT IN ({excl})
              AND t.notional_usdc >= {min_notional}
        )
        SELECT * EXCLUDE (rk) FROM cand WHERE rk <= {per_event}
        ORDER BY matched_event_idx, ts_utc, proxy_wallet, notional_usdc
    """).df()
    con.unregister("leader_ev_tmp")
    return df


# ---------------------------------------------------------------------------
# Backtest core
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BacktestConfig:
    latency_seconds: int = 60             # how long after the leader before we enter
    horizons: tuple[int, ...] = (300, 1800, 3600, 86400)  # exit horizons in seconds
    fee_bps: float = 20.0                 # ONE-WAY fee in price units per share; charged twice
    min_signal_notional: float = 1000.0   # require leader to commit at least this much
    exit_at_resolution: bool = True       # if the market closed before the horizon, exit at the payout
    max_entry_delay_seconds: int = 600    # skip the event if no fill within this delay after mirror_ts
    exclude_post_convergence: bool = True  # drop leader trades after the outcome was already priced in


def _vwap_at(df: pd.DataFrame, ts: pd.Timestamp) -> tuple[float | None, pd.Timestamp | None]:
    """Find the VWAP entry at or after ``ts`` in a per-asset sorted frame."""
    idx = df["minute_utc"].searchsorted(ts, side="left")
    if idx >= len(df):
        return None, None
    return float(df["vwap"].iloc[idx]), df["minute_utc"].iloc[idx]


def _vwap_before(df: pd.DataFrame, ts: pd.Timestamp) -> tuple[float | None, pd.Timestamp | None]:
    idx = df["minute_utc"].searchsorted(ts, side="right") - 1
    if idx < 0:
        return None, None
    return float(df["vwap"].iloc[idx]), df["minute_utc"].iloc[idx]


def backtest_mirror(
    con: duckdb.DuckDBPyConnection,
    *,
    leaders: list[str],
    cfg: BacktestConfig | None = None,
    condition_ids: list[str] | None = None,
) -> pd.DataFrame:
    """Run the mirror strategy, return one row per (event, horizon) with PnL.

    Exit rule (audit 2026-08-29): the position is closed at the last traded
    minute at or before ``leader_ts + horizon``; if the market's
    ``closed_time`` precedes that instant the resolution payout is used
    instead (``used_resolution_exit``). Events with no post-entry price
    before the horizon are dropped rather than marked at the payout, which
    previously leaked the outcome into the 300 s horizon.

    Columns:
        leader, asset_id, condition_id, side, leader_ts, leader_price,
        leader_notional, mirror_entry_ts, mirror_entry_price,
        horizon_seconds, exit_ts, exit_price, gross_return, net_return,
        used_resolution_exit
    """
    cfg = cfg or BacktestConfig()
    events = leader_events(con, leaders=leaders, min_notional=cfg.min_signal_notional,
                           condition_ids=condition_ids,
                           exclude_post_convergence=cfg.exclude_post_convergence).df()
    return run_events(con, events, cfg=cfg)


def run_events(
    con: duckdb.DuckDBPyConnection,
    events: pd.DataFrame,
    *,
    cfg: BacktestConfig | None = None,
) -> pd.DataFrame:
    """Mirror every row of an event frame (leader or matched-control events)."""
    cfg = cfg or BacktestConfig()
    if events.empty:
        return pd.DataFrame()
    build_minute_vwap_view(con)
    events = events.copy()
    events["leader_ts"] = pd.to_datetime(events["ts_utc"], utc=True)
    events["closed_time"] = pd.to_datetime(events["closed_time"], utc=True)
    events = events.drop(columns=["ts_utc"])

    vwap = con.sql("SELECT * FROM trades_minute_vwap").df()
    vwap["minute_utc"] = pd.to_datetime(vwap["minute_utc"], utc=True)
    by_asset = {aid: g.sort_values("minute_utc").reset_index(drop=True)
                for aid, g in vwap.groupby("asset_id")}

    # Resolution = last observed VWAP minute per asset that corresponds to the
    # market closing — proxied here as the last minute we saw a trade. If
    # ``exit_at_resolution`` is True, exit horizons that overrun this fall
    # back to the realised outcome (0/1) for the winning side.
    winning = con.sql("SELECT condition_id, winning_outcome_index FROM winning_outcomes").df()
    win_by_cid = dict(zip(winning["condition_id"], winning["winning_outcome_index"]))

    rows: list[dict] = []
    fee = cfg.fee_bps / 10_000.0  # one-way
    total_cost = 2 * fee  # round-trip

    for _, ev in events.iterrows():
        aid = ev["asset_id"]
        if aid not in by_asset:
            continue
        df_a = by_asset[aid]
        mirror_ts = ev["leader_ts"] + pd.Timedelta(seconds=cfg.latency_seconds)
        entry_p, entry_t = _vwap_at(df_a, mirror_ts)
        if entry_p is None or entry_p <= 0 or entry_p >= 1:
            continue
        if entry_t - mirror_ts > pd.Timedelta(seconds=cfg.max_entry_delay_seconds):
            continue
        closed_time = ev["closed_time"]
        if pd.notna(closed_time) and entry_t >= closed_time:
            continue

        for horizon in cfg.horizons:
            exit_ts_req = ev["leader_ts"] + pd.Timedelta(seconds=horizon)
            if exit_ts_req <= entry_t:
                continue  # entry fill landed after the horizon
            used_resolution_exit = False
            if cfg.exit_at_resolution and pd.notna(closed_time) and closed_time <= exit_ts_req:
                win_idx = win_by_cid.get(ev["condition_id"])
                if win_idx is None:
                    continue
                exit_p = 1.0 if int(win_idx) == int(ev["outcome_index"]) else 0.0
                exit_t = closed_time
                used_resolution_exit = True
            else:
                exit_p, exit_t = _vwap_before(df_a, exit_ts_req)
                if exit_p is None or exit_t is None or exit_t <= entry_t:
                    continue  # no observable post-entry price before the horizon

            side = ev["side"]
            if side == "BUY":
                gross = exit_p - entry_p
            elif side == "SELL":
                gross = entry_p - exit_p
            else:
                continue
            net = gross - total_cost  # apply round-trip fee

            rows.append({
                "matched_event_idx": ev.get("matched_event_idx", None),
                "leader": ev["proxy_wallet"],
                "asset_id": aid,
                "condition_id": ev["condition_id"],
                "side": side,
                "leader_ts": ev["leader_ts"],
                "leader_price": float(ev["price"]),
                "leader_notional": float(ev["notional_usdc"]),
                "mirror_entry_ts": entry_t,
                "mirror_entry_price": entry_p,
                "horizon_seconds": horizon,
                "exit_ts": exit_t,
                "exit_price": float(exit_p),
                "gross_return": float(gross),
                "net_return": float(net),
                "used_resolution_exit": used_resolution_exit,
            })

    return pd.DataFrame(rows)


def summarise_backtest(df: pd.DataFrame, *, by: Iterable[str] = ("horizon_seconds",)) -> pd.DataFrame:
    """Aggregate a backtest run into per-bucket stats."""
    if df.empty:
        return pd.DataFrame()
    g = df.groupby(list(by))
    out = g.agg(
        n_events=("net_return", "size"),
        n_markets=("condition_id", "nunique"),
        n_leaders=("leader", "nunique"),
        hit_rate=("net_return", lambda s: float((s > 0).mean())),
        mean_gross=("gross_return", "mean"),
        mean_net=("net_return", "mean"),
        std_net=("net_return", "std"),
        total_gross=("gross_return", "sum"),
        total_net=("net_return", "sum"),
    ).reset_index()
    # Events within one market are not independent (same outcome, same
    # tail-sampled window): report the mean of per-market means and its
    # standard error across markets as the cluster-robust statistic.
    per_market = df.groupby(list(by) + ["condition_id"])["net_return"].mean().reset_index()
    pm = per_market.groupby(list(by))["net_return"].agg(
        mean_net_by_market="mean", sd_by_market="std", n="size").reset_index()
    pm["se_net_by_market"] = pm["sd_by_market"] / np.sqrt(pm["n"])
    return out.merge(pm[list(by) + ["mean_net_by_market", "se_net_by_market"]], on=list(by))

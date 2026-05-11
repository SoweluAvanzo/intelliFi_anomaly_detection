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
) -> duckdb.DuckDBPyRelation:
    """Trades by the supplied leader wallets above a notional threshold."""
    addrs = ",".join(f"'{a.lower()}'" for a in leaders)
    return con.sql(f"""
        SELECT proxy_wallet, condition_id, asset_id, outcome_index,
               side, price, size, notional_usdc, ts_utc
        FROM trades
        WHERE proxy_wallet IN ({addrs})
          AND notional_usdc >= {min_notional}
          AND price BETWEEN 0.02 AND 0.98
          AND ts_utc IS NOT NULL
        ORDER BY ts_utc;
    """)


# ---------------------------------------------------------------------------
# Backtest core
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class BacktestConfig:
    latency_seconds: int = 60             # how long after the leader before we enter
    horizons: tuple[int, ...] = (300, 1800, 3600, 86400)  # exit horizons in seconds
    fee_bps: float = 20.0                 # round-trip cost = 2 * one-way fee
    min_signal_notional: float = 1000.0   # require leader to commit at least this much
    exit_at_resolution: bool = True       # if horizon > resolution, exit at outcome


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
) -> pd.DataFrame:
    """Run the mirror strategy, return one row per (event, horizon) with PnL.

    Columns:
        leader, asset_id, condition_id, side, leader_ts, leader_price,
        leader_notional, mirror_entry_ts, mirror_entry_price,
        horizon_seconds, exit_ts, exit_price, gross_return, net_return,
        used_resolution_exit
    """
    cfg = cfg or BacktestConfig()
    build_minute_vwap_view(con)

    events = leader_events(con, leaders=leaders, min_notional=cfg.min_signal_notional).df()
    if events.empty:
        return pd.DataFrame()
    events["leader_ts"] = pd.to_datetime(events["ts_utc"], utc=True)
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

        for horizon in cfg.horizons:
            exit_ts_req = ev["leader_ts"] + pd.Timedelta(seconds=horizon)
            exit_p, exit_t = _vwap_before(df_a, exit_ts_req)
            used_resolution_exit = False
            if exit_p is None or exit_t is None or exit_t <= entry_t:
                if cfg.exit_at_resolution:
                    win_idx = win_by_cid.get(ev["condition_id"])
                    if win_idx is None:
                        continue
                    # Pay $1 on the winning outcome, $0 on losing
                    exit_p = 1.0 if int(win_idx) == int(ev["outcome_index"]) else 0.0
                    used_resolution_exit = True
                else:
                    continue

            side = ev["side"]
            if side == "BUY":
                gross = exit_p - entry_p
            elif side == "SELL":
                gross = entry_p - exit_p
            else:
                continue
            net = gross - total_cost  # apply round-trip fee

            rows.append({
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
    return g.agg(
        n_events=("net_return", "size"),
        hit_rate=("net_return", lambda s: float((s > 0).mean())),
        mean_gross=("gross_return", "mean"),
        mean_net=("net_return", "mean"),
        std_net=("net_return", "std"),
        total_gross=("gross_return", "sum"),
        total_net=("net_return", "sum"),
    ).reset_index()

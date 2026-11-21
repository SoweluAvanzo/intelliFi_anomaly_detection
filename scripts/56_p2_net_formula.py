#!/usr/bin/env python
"""P2 (V1 fee-tail) negRisk NET taker PnL BY FORMULA — fills the one "pending" cell of the 3-period table.

The archive has no measured FeeCharged for the P2 window (2026-03-01..2026-04-28), so P2 net is a MODELED
estimate (V2 net is measured). Fee = feeRate * p * (1-p) * shares (makers never pay); since shares=usdc/price,
per taker order fee = feeRate * (1-price) * usdc. Category = clob tags[1] per negRisk family; rates = the
documented per-tag schedule used for V2 (intellifi.episode_dynamics._FEERATE, default 0.05). Rollout gating:
the all-markets fee begins 30 Mar 2026, crypto from 6 Mar 2026; before that non-crypto negRisk is fee-free.

Applied on the EXACT rq2_p2 taker-order universe (build_canonical_v1 aggregation) so net = gross - fee is
consistent with the three-period distribution table. Writes docs/p2_net_formula.json.

  python scripts/56_p2_net_formula.py
"""
from __future__ import annotations
import json, sys
from pathlib import Path
import numpy as np, pandas as pd

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))
import duckdb                                      # noqa: E402
from intellifi.episode_dynamics import _FEERATE    # noqa: E402  (same map V2 uses)

FILLS = REPO / "data/parquet/negrisk_v1/fills.parquet"
CLOB  = REPO / "data/parquet/clob_markets/tokens.parquet"
RQ2P2 = REPO / "data/export/rq2_p2_wallets.parquet"
OUT   = REPO / "docs/p2_net_formula.json"
P2_LO, MAR06, MAR30, P2_HI = 1772323200, 1772755200, 1774828800, 1777680000  # 03-01, 03-06, 03-30, 04-28


def gini_pos(x):
    x = np.sort(x[x > 0]); n = len(x)
    return float((2 * np.arange(1, n + 1) - n - 1).dot(x) / (n * x.sum())) if n else float("nan")


def main() -> int:
    con = duckdb.connect(); con.execute("PRAGMA memory_limit='4GB'"); con.execute("PRAGMA threads=4")
    fam = con.execute(f"""SELECT neg_risk_market_id AS family, any_value(lower(tags[1])) AS cat
      FROM '{CLOB.as_posix()}' WHERE neg_risk=TRUE AND neg_risk_market_id IS NOT NULL
      AND neg_risk_market_id<>'' GROUP BY neg_risk_market_id""").df()
    fam["feerate"] = fam.cat.map(lambda c: _FEERATE.get(c, 0.05) if isinstance(c, str) else np.nan)
    con.register("famcat", fam[["family", "cat", "feerate"]])
    W = pd.read_parquet(RQ2P2, columns=["wallet", "pnl"]); W["pnl"] = W.pnl.astype(float)

    def compute(gate_mar30=True, impute_rate=0.05):
        ncg = MAR30 if gate_mar30 else P2_LO
        q = f"""WITH orders AS (
              SELECT family, tok, wallet, is_buy, ts, sum(usdc) usdc, sum(usdc)/nullif(sum(usdc/price),0) price
              FROM '{FILLS.as_posix()}' WHERE price>0 AND price<1 AND ts>={P2_LO} AND ts<{P2_HI}
              GROUP BY family, tok, wallet, is_buy, ts),
            o AS (SELECT o.wallet, o.usdc, o.price, o.ts, COALESCE(f.feerate,{impute_rate}) rate,
                     CASE WHEN f.cat='crypto' THEN {MAR06} ELSE {ncg} END gate
                  FROM orders o LEFT JOIN famcat f USING(family))
            SELECT wallet, sum(usdc) notional,
                   sum(CASE WHEN ts>=gate THEN rate*(1-price)*usdc ELSE 0 END) fee,
                   sum(CASE WHEN ts>=gate THEN usdc ELSE 0 END) notional_charged
            FROM o GROUP BY wallet"""
        fee = con.execute(q).df()
        m = W.merge(fee, on="wallet", how="left").fillna({"fee": 0.0, "notional": 0.0, "notional_charged": 0.0})
        g, f, net = m.pnl.values, m.fee.values, m.pnl.values - m.fee.values
        return {"gross_pnl": float(g.sum()), "fee": float(f.sum()), "net_pnl": float(net.sum()),
                "gini_gross": round(gini_pos(g), 4), "gini_net": round(gini_pos(net), 4),
                "eff_rate_all_pct": round(100 * f.sum() / m.notional.sum(), 2),
                "eff_rate_charged_pct": round(100 * f.sum() / m.notional_charged.sum(), 2) if m.notional_charged.sum() else None,
                "charged_notional_frac_pct": round(100 * m.notional_charged.sum() / m.notional.sum(), 1),
                "notional": float(m.notional.sum())}

    rep = {"description": "P2 negRisk net taker PnL by formula (modeled; archive has no measured fee)",
           "formula": "fee = feeRate*(1-price)*usdc per taker order; rates = _FEERATE (V2 schedule); gate: all-markets 2026-03-30, crypto 2026-03-06",
           "baseline": compute(True, 0.05),
           "sensitivity": {"no_rollout_gate": compute(False, 0.05), "unmatched_rate_zero": compute(True, 0.0)}}
    OUT.write_text(json.dumps(rep, indent=1))
    b = rep["baseline"]
    print(f"wrote {OUT}")
    print(f"P2 gross {b['gross_pnl']:,.0f} | formula fee {b['fee']:,.0f} ({b['eff_rate_all_pct']}% all / "
          f"{b['eff_rate_charged_pct']}% charged; {b['charged_notional_frac_pct']}% of $ charged) | "
          f"net {b['net_pnl']:,.0f} | Gini gross {b['gini_gross']} -> net {b['gini_net']}")
    con.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

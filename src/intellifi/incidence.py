"""Fee incidence / regressivity from the v2 tape (fee era), assumption-free (actual `fee_raw`).

The fee payer (aggressor/taker) is the `maker` field on `is_taker_order=TRUE` rows; `taker` is the
operator. effective_rate = (fee_raw/1e6) / usdc. Result: strongly regressive in price
(longshot buyers pay ~40x the rate of favorite buyers) and by trader size. See `docs/FEE_EFFECTS.md`.
"""
from __future__ import annotations

import pandas as pd

from . import config as _cfg


def _tape() -> str:
    return str(_cfg.PARQUET_DIR / "tape_v2" / "**" / "part.parquet")


def compute(con) -> dict:
    """Returns overall incidence, by-taker-size-decile regressivity, and by-price-region rate.
    Taker fills are deduped by (tx_hash, evt_index) (overlapping crawl chunks) so the absolute
    totals are correct; the rates are dedup-invariant either way."""
    con.execute(f"""CREATE OR REPLACE TABLE T AS
      SELECT maker, price, shares, usdc, fee_raw FROM read_parquet('{_tape()}')
      WHERE exchange IN ('v2_a','v2_b') AND event='OrderFilled' AND is_taker_order=TRUE
            AND price>0 AND price<1 AND usdc>0
      QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index)=1""")
    con.execute("""CREATE OR REPLACE TABLE tkr AS
      SELECT maker AS wallet, sum(usdc) notional, sum(fee_raw)/1e6 fee, count(*) n_fills,
             sum(price*usdc)/nullif(sum(usdc),0) vwap_price,
             sum((least(price,1-price)<=0.10)::INT * usdc) notional_longshot,
             sum((fee_raw>0)::INT) n_fee_fills
      FROM T GROUP BY maker""")
    overall = con.execute("""SELECT round(sum(fee)/sum(notional)*100,3) eff_rate_pct, round(sum(fee),0) total_fee,
        round(sum(notional),0) total_notional, round(avg((n_fee_fills>0)::INT),3) frac_takers_any_fee,
        count(*) n_takers FROM tkr""").df().iloc[0].to_dict()

    by_size = con.execute("""WITH d AS (SELECT *, ntile(10) OVER (ORDER BY notional) sz FROM tkr)
      SELECT sz, count(*) n_takers, round(sum(notional),0) notional, round(sum(fee)/sum(notional)*100,3) eff_rate_pct,
         round(sum(notional_longshot)/sum(notional),3) longshot_share, round(median(vwap_price),3) med_vwap_price
      FROM d GROUP BY sz ORDER BY sz""").df()

    con.execute("""CREATE OR REPLACE TABLE pr AS
      SELECT CASE WHEN price<=0.05 THEN '1 <=0.05' WHEN price<=0.10 THEN '2 0.05-0.10' WHEN price<=0.30 THEN '3 0.10-0.30'
                  WHEN price<=0.70 THEN '4 0.30-0.70' WHEN price<=0.90 THEN '5 0.70-0.90' ELSE '6 >0.90' END preg,
             sum(usdc) notional, sum(fee_raw)/1e6 fee, count(*) n, sum((fee_raw>0)::INT) n_fee
      FROM T GROUP BY preg""")
    by_price = con.execute("""SELECT preg, n, round(fee/nullif(notional,0)*100,3) eff_rate_pct,
        round(n_fee::DOUBLE/n,3) frac_fee_charged FROM pr ORDER BY preg""").df()

    return {"overall": overall, "by_size": by_size, "by_price": by_price}

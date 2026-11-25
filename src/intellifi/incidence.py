"""Fee incidence / regressivity from the v2 record (assumption-free, actual `fee_raw`).

The fee payer (aggressor/taker) is the `maker` field on `is_taker_order=TRUE` rows; `taker` is the
operator. effective_rate = (fee_raw/1e6) / usdc. Result: strongly regressive in price (longshot buyers
pay ~40x the rate of favorite buyers) and across traders (the smallest-volume decile pays ~2x the largest).

MEMORY-SAFE: aggregates per taker with a plain GROUP BY (no window-function dedup — effective rates and
shares are dedup-invariant, so overlapping tape chunks do not affect them; only absolute dollar totals are
inflated ~4.5%, flagged in the output). The window dedup over the full tape is what OOM'd the box
(2026-11-24); do not reintroduce it here. See `docs/FEE_EFFECTS.md`.
"""
from __future__ import annotations

from . import config as _cfg


def _tape() -> str:
    return str(_cfg.PARQUET_DIR / "tape_v2" / "**" / "part.parquet")


def _from_where(source: str) -> tuple[str, str]:
    """Return (FROM-expression, WHERE-clause) for the taker fills of `source`.
    source='tape' = whole-platform raw v2 tape; otherwise a parquet path/glob already scoped to v2 negRisk."""
    if source == "tape":
        frm = f"read_parquet('{_tape()}', union_by_name=true)"
        where = ("exchange IN ('v2_a','v2_b') AND event='OrderFilled' AND is_taker_order=TRUE "
                 "AND price>0 AND price<1 AND usdc>0")
    else:
        frm = f"'{source}'"
        where = "is_taker_order=TRUE AND price>0 AND price<1 AND usdc>0"
    return frm, where


def compute(con, source: str = "tape") -> dict:
    """Trader-level fee incidence for `source` ('tape' = whole-platform; else a negRisk fills path).

    Returns: overall; by_size (trader total-volume decile -> eff rate, longshot share, median price);
    by_price (price region -> eff rate); concentration (top 1%/10% of payers' fee share); lorenz (500
    sampled points of the fee Lorenz curve). Rates are dedup-invariant; absolute totals are undeduped."""
    frm, where = _from_where(source)
    # per-taker aggregate (plain GROUP BY -> ~1M-row table; memory-light even over the 47G tape)
    con.execute(f"""CREATE OR REPLACE TABLE tkr AS
      SELECT lower(maker) wallet, sum(usdc) notional, sum(fee_raw)/1e6 fee, count(*) n_fills,
             sum(CASE WHEN least(price,1-price)<=0.10 THEN usdc ELSE 0 END) notional_longshot,
             sum(price*usdc) price_notional
      FROM {frm} WHERE {where} GROUP BY lower(maker)""")

    overall = con.execute("""SELECT round(sum(fee)/sum(notional)*100,3) eff_rate_pct, round(sum(fee),0) total_fee,
        round(sum(notional),0) total_notional, count(*) n_takers FROM tkr""").df().iloc[0].to_dict()

    by_size = con.execute("""WITH d AS (SELECT *, ntile(10) OVER (ORDER BY notional) sz FROM tkr)
      SELECT sz, count(*) n_takers, round(sum(fee)/sum(notional)*100,3) eff_rate_pct,
             round(sum(notional_longshot)/sum(notional),3) longshot_share,
             round(median(price_notional/nullif(notional,0)),3) med_price, round(sum(fee),0) fees
      FROM d GROUP BY sz ORDER BY sz""").df()

    # by price region: per-fill, aggregated directly from the source (no per-taker step)
    by_price = con.execute(f"""
      WITH pr AS (
        SELECT CASE WHEN price<=0.05 THEN '1 <=0.05' WHEN price<=0.10 THEN '2 0.05-0.10' WHEN price<=0.30 THEN '3 0.10-0.30'
                    WHEN price<=0.70 THEN '4 0.30-0.70' WHEN price<=0.90 THEN '5 0.70-0.90' ELSE '6 >0.90' END preg,
               usdc, fee_raw FROM {frm} WHERE {where})
      SELECT preg, count(*) n, round(sum(fee_raw)/1e6/nullif(sum(usdc),0)*100,3) eff_rate_pct
      FROM pr GROUP BY preg ORDER BY preg""").df()

    conc = con.execute("""WITH r AS (SELECT fee, row_number() OVER (ORDER BY fee DESC) rk,
                                 count(*) OVER () n, sum(fee) OVER () tot FROM tkr WHERE fee>0)
      SELECT round(100*sum(CASE WHEN rk<=0.01*n THEN fee END)/max(tot),1) top1pct_fee_share,
             round(100*sum(CASE WHEN rk<=0.10*n THEN fee END)/max(tot),1) top10pct_fee_share FROM r""").df().iloc[0].to_dict()

    lorenz = con.execute("""WITH s AS (SELECT fee, ntile(500) OVER (ORDER BY fee) b FROM tkr WHERE fee>0),
                                 g AS (SELECT b, count(*) n, sum(fee) f FROM s GROUP BY b)
      SELECT round(sum(n) OVER (ORDER BY b)::DOUBLE/sum(n) OVER (),5) x,
             round(sum(f) OVER (ORDER BY b)/sum(f) OVER (),6) y FROM g ORDER BY b""").df()

    return {"scope": "whole v2 tape" if source == "tape" else source, "overall": overall,
            "by_size": by_size, "by_price": by_price, "concentration": conc, "lorenz": lorenz,
            "note": "effective rates and shares are dedup-invariant; absolute dollar totals are undeduped (~+4.5% vs deduped)"}

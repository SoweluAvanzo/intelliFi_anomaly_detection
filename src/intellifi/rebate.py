"""Maker rebate accounting for the RQ2 price-correctors (the fee's return side).

Per DATA_DICTIONARY §10.3 the daily per-market rebate pool is `ρ·(taker fees)` and a maker's rebate
is its `fee_equivalent = feeRate·p·(1−p)·s` share of the pool. Because every fill's maker
fee_equivalent sums to its taker fee, the pool denominator cancels and a maker's rebate reduces to
**`rebate = ρ · Σ(feeRate·p·(1−p)·s)` over its maker fills** — computable per wallet from the trade
record (modeled, not the on-chain payout; bounded hard by "rebate ≤ the whole pool ≈ ρ̄·total fees").
`feeRate`/`ρ` are per category (§10.2). See `docs/FEE_EFFECTS.md`.
"""
from __future__ import annotations

import pandas as pd

from . import config as _cfg

# category (clob primary tag) -> taker feeRate, rebate share rho  (DATA_DICTIONARY §10.2/10.3)
_FEERATE = ("CASE WHEN lower(tags[1])='crypto' THEN 0.07 WHEN lower(tags[1])='sports' THEN 0.05 "
            "WHEN lower(tags[1]) IN ('finance','politics','tech','mentions') THEN 0.04 "
            "WHEN lower(tags[1]) IN ('geopolitics','world') THEN 0.0 ELSE 0.05 END")
_RHO = ("CASE WHEN lower(tags[1]) IN ('crypto','sports') THEN 0.20 "
        "WHEN lower(tags[1]) IN ('geopolitics','world') THEN 0.0 ELSE 0.25 END")


def compute(con, correctors_path: str, out_path: str) -> dict:
    """Per-corrector taker fees (paid) and modeled maker rebate (received), deduped. Writes a
    per-wallet parquet and returns the group summary + the hard pool bound."""
    tape = str(_cfg.PARQUET_DIR / "tape_v2" / "**" / "part.parquet")
    clob = str(_cfg.PARQUET_DIR / "clob_markets" / "tokens.parquet")
    con.execute(f"CREATE OR REPLACE TABLE corr AS SELECT lower(wallet) wallet FROM '{correctors_path}'")
    con.execute(f"""CREATE OR REPLACE TABLE tfr AS
      SELECT token_id, {_FEERATE} feeRate, {_RHO} rho FROM '{clob}'
      WHERE token_id IS NOT NULL AND token_id<>''""")
    # correctors' own fills (filter first keeps this small), then dedup in a SEPARATE step so the
    # window can spill the materialized table (one combined join+window query OOMs).
    con.execute(f"""CREATE OR REPLACE TABLE f AS
      SELECT lower(t.maker) wallet, t.is_taker_order, t.token_id, t.price, t.shares, t.fee_raw,
             t.tx_hash, t.evt_index, t.block_number
      FROM read_parquet('{tape}') t JOIN corr ON lower(t.maker)=corr.wallet
      WHERE t.exchange IN ('v2_a','v2_b') AND t.event='OrderFilled' AND t.price>0 AND t.price<1""")
    con.execute("""CREATE OR REPLACE TABLE fd AS
      SELECT wallet, is_taker_order, token_id, price, shares, fee_raw FROM f
      QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index ORDER BY block_number)=1""")
    con.execute("DROP TABLE f")
    con.execute(f"""CREATE OR REPLACE TABLE perw AS
      SELECT wallet,
        sum(CASE WHEN is_taker_order THEN fee_raw/1e6 ELSE 0 END) taker_fees,
        sum(CASE WHEN is_taker_order THEN price*shares ELSE 0 END) taker_vol,
        sum(CASE WHEN NOT is_taker_order THEN price*shares ELSE 0 END) maker_vol,
        sum(CASE WHEN NOT is_taker_order THEN feeRate*price*(1-price)*shares ELSE 0 END) maker_fee_equiv,
        sum(CASE WHEN NOT is_taker_order THEN rho*feeRate*price*(1-price)*shares ELSE 0 END) rebate
      FROM (SELECT fd.*, tfr.feeRate, tfr.rho FROM fd LEFT JOIN tfr USING(token_id))
      GROUP BY wallet""")
    con.execute(f"COPY perw TO '{out_path}' (FORMAT parquet)")
    s = con.execute("""SELECT count(*) n, sum(taker_fees) taker_fees, sum(rebate) rebate,
        sum(maker_fee_equiv) maker_fee_equiv, avg((maker_vol>0)::INT) frac_make FROM perw""").df().iloc[0]
    # hard upper bound: correctors' rebate <= whole pool <= rho_max * total platform taker fees
    return {"n_correctors": int(s.n), "taker_fees_musd": round(s.taker_fees / 1e6, 1),
            "rebate_musd": round(s.rebate / 1e6, 1),
            "rebate_as_frac_of_their_fees": round(s.rebate / s.taker_fees, 3),
            "frac_also_make": round(float(s.frac_make), 2),
            "note": "modeled (DATA_DICTIONARY §10.3), not on-chain; rebate <= whole pool ~= 0.22*total_fees"}

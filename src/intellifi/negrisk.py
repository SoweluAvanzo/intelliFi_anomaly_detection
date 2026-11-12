"""negRisk price-correction (RQ2) data layer: family map + fill extract.

Builds the YES-token -> negRisk-family map and extracts the OrderFilled fills for those tokens
from the v2 tape (fee era) or the v1 archive (pre-fee), as the substrate for RQ2 price-correction
attribution (see `intellifi.correction`). Documented in `docs/FEE_EFFECTS.md`.

Field semantics (easy to get wrong, verified 2026-11-11):
  * `OPERATOR` (0xe2222d27...) is the Polymarket CTF-exchange operator, NOT a trader. It is the
    `taker` on EVERY taker-order row (1 distinct value over 21.6M rows; never a maker). The real
    aggressor/taker is the `maker` field on `is_taker_order=TRUE` rows.
  * Each economic fill appears as one taker-aggregate row AND maker-leg row(s) with swapped labels;
    summing both double-counts volume. Canonical trades = `is_taker_order=TRUE` rows (= volumeClob).
  * For negRisk, the YES token is always ctf.token0, so yes_won == (winning_outcome_index == 0).
"""
from __future__ import annotations

from . import config as _cfg

OPERATOR = "0xe2222d279d744050d28e00520010520000310f59"  # CTF-exchange operator; exclude from trader stats


def _p(*parts) -> str:
    return str(_cfg.PARQUET_DIR.joinpath(*parts))


def build_map(con, out_path: str) -> str:
    """Write one row per resolved negRisk YES-token condition: condition_id, yes_token_id, family
    (neg_risk_market_id), resolved_ts_utc, winning_outcome_index, yes_won, question, market_slug."""
    ctf = _p("ctf_v2_conditions.parquet")
    clob = _p("clob_markets", "tokens.parquet")
    con.execute(f"""CREATE OR REPLACE TABLE _m AS
      SELECT cmk.condition_id, cmk.token_id AS yes_token_id, cmk.neg_risk_market_id AS family,
             ctf.resolved_ts_utc, ctf.winning_outcome_index,
             (cmk.token_id = ctf.token0) AS yes_is_token0,
             CASE WHEN cmk.token_id = ctf.token0 THEN (ctf.winning_outcome_index = 0)::INT
                  ELSE (ctf.winning_outcome_index = 1)::INT END AS yes_won,
             cmk.question, cmk.market_slug
      FROM (SELECT DISTINCT condition_id, token_id, neg_risk_market_id, question, market_slug
            FROM '{clob}'
            WHERE neg_risk = TRUE AND outcome = 'Yes'
              AND token_id IS NOT NULL AND token_id <> ''
              AND neg_risk_market_id IS NOT NULL AND neg_risk_market_id <> '') cmk
      JOIN '{ctf}' ctf USING (condition_id)
      WHERE ctf.resolved_ts_utc IS NOT NULL""")
    con.execute(f"COPY _m TO '{out_path}' (FORMAT parquet)")
    return out_path


def extract_tape_fills(con, map_path: str, out_path: str) -> str:
    """Extract v2-tape OrderFilled fills on negRisk YES tokens (all legs; dedup done downstream)."""
    tape = str(_cfg.PARQUET_DIR / "tape_v2" / "**" / "part.parquet")
    con.execute(f"""CREATE OR REPLACE VIEW _map AS
      SELECT yes_token_id, family, condition_id, resolved_ts_utc, yes_won FROM '{map_path}'""")
    con.execute(f"""COPY (
      SELECT m.family, m.condition_id, m.yes_token_id, m.resolved_ts_utc, m.yes_won,
             t.ts_utc, t.block_number, t.price, t.maker, t.taker, t.side,
             t.usdc, t.shares, t.fee_raw, t.is_taker_order, t.tx_hash, t.evt_index
      FROM read_parquet('{tape}') t
      JOIN _map m ON t.token_id = m.yes_token_id
      WHERE t.exchange IN ('v2_a','v2_b') AND t.event = 'OrderFilled'
            AND t.price IS NOT NULL AND t.price > 0 AND t.price < 1
    ) TO '{out_path}' (FORMAT parquet)""")
    return out_path


def extract_archive_fills(con, out_path: str) -> str:
    """Extract pre-fee (v1 archive) negRisk YES-token fills (outcome_seq=1). Each archive row is a
    maker fill with the taker (aggressor) attached; taker_direction is the aggressor's side."""
    arc = str(_cfg.DATA_DIR / "external" / "polymarket_v1" / "daily_aligned_multi" / "*.parquet")
    con.execute(f"""COPY (
      SELECT neg_risk_market_id AS family, condition_id, asset_id AS tok, taker AS wallet,
             (taker_direction = 'BUY') AS is_buy, block_timestamp AS ts,
             usdc_amount AS usdc, fee_usdc AS fee, price,
             (outcome_label = winning_outcome_label)::INT AS yes_won
      FROM read_parquet('{arc}', union_by_name=true)
      WHERE neg_risk = TRUE AND outcome_seq = 1
            AND winning_outcome_label IS NOT NULL AND outcome_label IS NOT NULL
            AND resolution_status IS DISTINCT FROM 'disputed'  -- winner known; per-fill status lags
            AND neg_risk_market_id IS NOT NULL AND neg_risk_market_id <> ''
            AND taker IS NOT NULL AND price > 0 AND price < 1 AND usdc_amount > 0
    ) TO '{out_path}' (FORMAT parquet)""")
    return out_path


def map_stats(con, map_path: str) -> dict:
    """Integrity stats: #conditions/families, YES==token0 fraction, and winners-per-family
    (should be exactly 1 for a mutually-exclusive negRisk family)."""
    base = con.execute(f"""SELECT count(*) n, count(DISTINCT family) fams,
        avg(yes_is_token0::INT) tok0 FROM '{map_path}'""").df().iloc[0]
    fam = con.execute(f"""SELECT sum_yes_won, count(*) nf FROM
        (SELECT family, sum(yes_won) sum_yes_won FROM '{map_path}' GROUP BY family)
        GROUP BY 1 ORDER BY 1""").df()
    return {"conditions": int(base.n), "families": int(base.fams),
            "yes_is_token0_frac": round(float(base.tok0), 4),
            "winners_per_family": {int(k): int(v) for k, v in zip(fam.sum_yes_won, fam.nf)}}

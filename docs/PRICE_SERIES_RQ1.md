# Price-at-horizon series for the forecast-quality RQ

`data/export/price_series_rq1.parquet` — one row per resolved binary market, giving the
market-implied probability of outcome-0 at fixed horizons before resolution, plus the
realised outcome. It is the input for the calibration question: does the market's forecast
match what actually happened, and how does that vary by market type and fee regime.

Regenerate it with `scripts/38_build_price_series.py`; the logic is `src/intellifi/price_series.py`.

## Do not use `prices_history`

`data/parquet/prices_history/` is a stale Stage-I artifact: a single CLOB `/prices-history`
snapshot taken on 2026-05-11 covering the 30 days before that fetch, for only 19 markets
(≈200 files, most empty). The `/prices-history` `interval` is a lookback window, not a full
series, and Polymarket prunes the endpoint after resolution. It cannot answer a fee-era
calibration question and is not the price source here. The price series is reconstructed
directly from the v2 tape instead.

## Source and method

Price source is the v2 tape, `data/parquet/tape_v2` — the complete on-chain `OrderFilled`
log stream for the two v2 exchanges. Resolution and winner come from
`data/parquet/ctf_v2_conditions.parquet`; category tags from
`data/parquet/clob_markets/tokens.parquet`.

Each fill carries the execution price of one outcome token, in probability units. For a
binary market the two tokens are complementary, so every fill is mapped into a single
outcome-0 frame — `p0 = price` on `token0`, `p0 = 1 − price` on `token1` — which lets both
legs of every match contribute. For each market and horizon the series takes the last `p0`
at or before `resolved_ts − horizon`.

The tape is not pre-cleaned; six read rules are baked into the build:

1. `exchange IN ('v2_a','v2_b')` — drop the other-emitter rows.
2. `event = 'OrderFilled'` — price-bearing logs only.
3. `price IS NOT NULL AND 0 ≤ price ≤ 1` — drop null and out-of-band prices.
4. null-`token_id` rows drop implicitly via the inner join on `token_id`.
5. overlapping tape chunks are deduped by `(tx_hash, evt_index)` implicitly: every horizon
   price is an `arg_max(p0, ts)`, and duplicate chunk rows carry identical `(ts, p0)`, so the
   price is dedup-invariant and no disk-heavy global sort is needed. `n_price_obs` is a raw
   fill-leg count and may run ~2% high from chunk overlap — treat it as a liquidity proxy,
   not a trade count.
6. only clean binary resolutions are kept: `outcome_slot_count = 2`,
   `winning_outcome_index IN (0,1)`, `payout_numerators IN ([1,0],[0,1])`.

## Columns

The pre-fee counterpart is `data/export/price_series_v1.parquet`, same schema, documented in
`docs/PRICE_SERIES_V1.md`. Both carry an `era` column (`v1` / `v2`) so they stack into one
pre/post panel for the fee-regime comparison.

| column | meaning |
|---|---|
| `condition_id` | CTF condition id, the market key |
| `era` | `v2` for this file (fee era) |
| `resolved_ts` | resolution timestamp (the horizon anchor), UTC |
| `anchor_source` | `resolved_at` for v2 — the anchor is always the oracle resolution |
| `resolved_at_raw` | oracle resolution time (equals `resolved_ts` for v2) |
| `close_at` | NULL for v2 (the tape has no scheduled-close field) |
| `win_idx` | winning outcome index, 0 or 1 |
| `realized_y0` | 1 if outcome-0 won, else 0 — the calibration target |
| `first_ts`, `last_ts` | first and last on-tape trade timestamps |
| `lifespan_days` | `resolved_ts − first_ts` in days — trading life |
| `n_price_obs` | fill-leg count, liquidity proxy, ~2% high, see rule 5 |
| `n_post_resolution` | fill legs after `resolved_ts` — settlement/redemption trades, excluded from every `p_*` |
| `p_7d`, `p_1d`, `p_12h`, `p_6h`, `p_1h` | outcome-0 implied probability at the last trade at or before that horizon before resolution; NULL when the market had no trade that early |
| `p_last` | outcome-0 implied probability at the last trade **at or before** `resolved_ts`; the market's final pre-resolution forecast |
| `tags` | CLOB category tags |
| `primary_tag` | first tag, a convenience category label |
| `question` | market question text |

For the category grouping used by the fee-rollout work, join `tags` to
`data/parquet/atlas/category_to_feeclass_mapping.csv`.

## Scope and coverage

Universe: 2,074,395 clean binary markets resolved in the fee era, 2026-04-28 → 2026-09-05.
Of these 1,222,069 traded on the tape and appear in the file; the rest never traded and have
no price.

Fixed horizons are sparse because the fee era is dominated by ultra-short recurring markets —
median trading life ≈ 0.13 days, about three hours. Price availability on the traded set:

| horizon | markets with a price |
|---|---|
| 7 days before | 3.2% |
| 1 day before | 23.0% |
| 12 hours before | 32.2% |
| 6 hours before | 39.8% |
| 1 hour before | 66.9% |
| last trade | 99.95% |

The 0.05% without a `p_last` are 571 markets that traded only *after* resolution, so they have no
pre-resolution forecast.

This is a market-universe property, not missing data: most markets did not exist 7 or even 1
day before they resolved. Two ways to use the series for RQ1:

- the full set with short horizons — `p_last`, `p_1h`, `p_6h` cover the ephemeral mass;
- the long-lived subset for literal 7d/1d calibration — 39,061 markets live ≥7 days, and
  29,317 of them also carry ≥50 price observations, which is well powered for
  calibration-by-market-type.

Because the fee regime coincides with market vintage, a before/after mean confounds the fee
with the changing market mix; use a difference-in-differences or vintage control.

## Completeness

Every v2_a/v2_b tape row is accounted for. Of 713,142,365 rows: 688,175,533 are clean-binary
`OrderFilled` fills that enter the series, 24,023,602 are on tokens of open or unresolved markets
(no resolution to calibrate against), 816,291 are on null-winner or void conditions, and 126,939
are non-`OrderFilled` logs. The in-series count equals the file's summed `n_price_obs` to the row,
so no resolved-binary fill was dropped.

Per market the history is the full on-chain `OrderFilled` stream — there is no trade-count cap and
no lookback window, unlike `/trades` or `prices_history`. Internal consistency is checked on every
build: a market that lived ≥7 d always has a non-null `p_7d` (same for 1 d and 12 h), every market
with a pre-resolution trade has a `p_last` (the 571 without one traded only after resolution), and
`first_ts ≤ last_ts`. About 5.8% of markets keep trading after
resolution (settlement); those fills are counted in `n_post_resolution` and excluded from all
`p_*`, so `last_ts` can exceed `resolved_ts` while the forecast columns stay pre-resolution.

## Validity checks

`scripts/38_build_price_series.py` prints these on every build:

- Prices lie in [0.001, 0.999].
- Winner convergence: mean `p_last` is 0.028 for markets outcome-0 lost and 0.968 for markets
  it won — the implied probability goes to the right corner.
- Calibration at 1 day tracks the diagonal across deciles, e.g. predicted 0.25 → empirical
  0.25, predicted 0.84 → empirical 0.82, predicted 0.97 → empirical 0.94.
- Brier score 0.10 at 1 day and 0.013 at the last trade, against 0.25 for a coin flip.
- Category tags cover 99.93% of traded markets.

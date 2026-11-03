# Pre-fee price-at-horizon series (v1)

`data/export/price_series_v1.parquet` — the **pre-fee** counterpart to `price_series_rq1.parquet`
(v2, fee era; see `docs/PRICE_SERIES_RQ1.md`). Same schema and the same `era` column, so the two
stack into one pre/post panel for the fee-regime calibration comparison. One row per resolved
binary market.

Built by `scripts/38_build_price_series.py --source archive` (logic in
`src/intellifi/price_series.py::build_price_series_v1`). Pure transform of cached data, no network.

## Source

The public Polymarket **v1 archive** at `data/external/polymarket_v1/`, read through
`archive.register_archive_views` — its `arc_raw` view unions the `daily_aligned` (standard binary)
and `daily_aligned_multi` (negRisk) layers, maps `outcome_seq − 1 → outcome_index` and
`block_timestamp → ts_utc`. Each row is a **maker fill** carrying price, outcome, winner label,
category, and lifecycle timestamps. Coverage **2022-11-21 → 2026-04-28** — it ends exactly where
the v2 tape begins, so v1 and v2 partition the timeline with no gap and no overlap.

## The resolution anchor — read this first

Horizon prices are measured backwards from a per-market **resolution anchor**. v2 uses the oracle
resolution time, which the v2 registry has for 100% of markets. The v1 archive does not:

- `resolved_at` (oracle resolution) is on only **~30% of `daily_aligned` conditions and 0% of the
  negRisk `multi` layer**, and it is missing *disproportionately on long-lived markets* (~15% of
  markets living ≥7 days carry it) — exactly where a 7-day horizon matters.
- `close_at` (scheduled close) is on **99.9%**. Where both exist, `close_at − resolved_at` is ~0 at
  the median, within 1 hour for ~50% and within 1 day for ~88% of markets, but has a long tail
  (p99 ≈ 136 days) for markets the oracle resolved early.

So the anchor is **`resolved_at` when the archive has it, else `close_at`**, and which one was used
is recorded per market in `anchor_source`. This maximises coverage and preserves v2-comparability
where possible. In the built file: **`resolved_at` 311,310 markets (37.2%), `close_at` 526,094
(62.8%)**. Both raw timestamps are kept (`resolved_at_raw`, `close_at`) so the gap can be inspected
or controlled for.

**For a strictly v2-comparable pre-fee subset, filter `anchor_source = 'resolved_at'`.**

## Columns

Identical to the v2 file (`docs/PRICE_SERIES_RQ1.md`), with these v1 specifics:

| column | v1 meaning |
|---|---|
| `era` | `v1` |
| `resolved_ts` | the anchor used (oracle `resolved_at`, else `close_at`) |
| `anchor_source` | `resolved_at` or `close_at` — which produced `resolved_ts` |
| `resolved_at_raw` | oracle resolution time where the archive has it, else NULL |
| `close_at` | scheduled close (nearly always present) |
| `tags` | `[category, category_refined]` from the archive's own category fields (not CLOB) |
| `primary_tag` | `category` |
| `question` | `market_slug` |
| `p_7d … p_last` | maker-fill implied probability of outcome 0 at that horizon before `resolved_ts` |

All other columns (`condition_id, win_idx, realized_y0, first_ts, last_ts, lifespan_days,
n_price_obs, n_post_resolution`) carry the same meaning as in the v2 file.

## Rules baked in

1. binary only — `outcome_index ∈ {0,1}` (both archive layers are binary at condition level).
2. resolved only — `resolution_status = 'resolved'` and `winning_outcome_label` present.
3. `price ∈ [0,1]`.
4. each fill mapped to the outcome-0 frame — `p0 = price` on outcome 0, `1 − price` on outcome 1.
5. horizon prices and `p_last` are `arg_max(p0, ts)` at or before `resolved_ts`; post-anchor
   settlement trades are excluded from every `p_*` and counted in `n_post_resolution`.
6. the winning index is derived from either leg, so single-sided markets still resolve.

## Scope and coverage

Universe: **837,404** resolved binary markets that traded, 2022-11-21 → 2026-04-28. Median trading
life **0.32 days**; **107,734 markets live ≥7 days** — about 2.8× the v2 count (39,061), so the
pre-fee era is actually richer for literal 7d/1d calibration.

| horizon | markets with a price |
|---|---|
| 7 days before | 12.91% |
| 1 day before | 36.17% |
| 12 hours before | 45.73% |
| 6 hours before | 52.19% |
| 1 hour before | 75.60% |
| last trade | 94.25% |

The 5.75% without a `p_last` are 48,136 markets that traded **only after** the anchor (so they have
no pre-anchor forecast); they are flagged by `p_last IS NULL` and should be dropped for calibration.
Note the ≥7d markets are mostly `close_at`-anchored — of 107,734, only ~6.4k carry the oracle
`resolved_at` anchor and ~101k rely on `close_at`.

## Validity

- **Winner convergence:** mean `p_last` is 0.076 for markets outcome-0 lost and 0.895 for markets
  it won — correct direction. The split is a touch less extreme than v2 (0.028 / 0.968) because the
  `close_at` fallback dates the "final" price imprecisely for part of the sample (see below).
- **Calibration @1d** tracks the diagonal (e.g. predicted 0.25 → empirical 0.24, 0.45 → 0.45,
  0.84 → 0.80, 0.99 → 0.98).
- **Brier** 0.089 @1d and 0.043 @last, against 0.25 for a coin flip. The @last figure is higher
  than v2's 0.013 — expected, because `close_at`-anchored markets have a less precise final-price
  timestamp.

## Completeness and retrieval validation

A full-archive audit accounts for every fill: of the fills on resolved markets, 730,173,213 are
clean binary candidates and 729,440,573 enter the series — the 0.1% gap is conditions missing both
`resolved_at` and `close_at` (no anchor), correctly dropped. Non-resolved (15.0M fills) and
no-winner-label (0.6M) fills are excluded by design.

Internal consistency holds: every market living ≥12h / ≥1d / ≥7d has its horizon price (≤4
boundary cases out of 837,404), timestamps are ordered, and every null `p_last` is an explained
all-post-anchor market.

The retrieval is validated by splitting on `anchor_source`:

| anchor_source | mean `p_last` lost → won | Brier @last |
|---|---|---|
| `resolved_at` (oracle) | 0.017 → 0.984 | 0.005 |
| `close_at` (fallback) | 0.108 → 0.818 | ~0.05–0.10 |

When the true oracle anchor is available, v1 converges and calibrates **as tightly as v2** — direct
evidence the price reconstruction from the archive is correct. The `close_at` fallback is the known,
quantified noise source, not a bug. Both anchor groups track the 1-day reliability diagonal.

## Comparing v1 and v2

- Stack `price_series_v1.parquet` and `price_series_rq1.parquet` on the shared schema; the `era`
  column separates pre-fee from fee.
- For the cleanest pre/post calibration comparison, restrict v1 to `anchor_source = 'resolved_at'`
  (matches v2's oracle anchor) or include `anchor_source` as a control.
- Both eras are dominated by ephemeral recurring markets (more so in the fee era). Use the ≥7d /
  minimum-liquidity subset or lifespan-relative horizons, and — because the fee regime coincides
  with market vintage — a difference-in-differences or vintage control rather than a raw pre/post
  mean.

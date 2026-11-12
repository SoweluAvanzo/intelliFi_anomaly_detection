# Fee effects on Polymarket market quality

Reproducible pipeline answering the project's two research questions about Polymarket's taker fee —
**RQ1** (does the fee change price *quality*?) and **RQ2** (who maintains that quality, and how does
the fee change their incentives?) — plus the fee's **incidence**. All results regenerate from the
cached parquet store; charts come from `notebooks/fee_effects.ipynb`.

## Research questions, results, and how they relate

**RQ1 — does the fee change the *quality* of the market's prices?** Two dimensions:

- **Single-market calibration** (are the probability forecasts right?): **no change.** Brier
  *reliability* ≈ 0.000 in both the pre-fee (V1) and fee (V2) eras; the V1/V2 Brier gap is the
  *resolution* (sharpness / market-mix) term, not forecast quality. *(well-powered null)*
- **Cross-market consistency** (do linked/negRisk YES prices sum to 1 — is the no-arbitrage band
  `|S−1|` tight?): **no robust change.** The "+3.4–4.2 pp band widening" is a liquidity/composition
  artifact — it vanishes in the cleanest treated class and a never-treated placebo reproduces it.
  *(rejected)*

→ The fee does **not** measurably degrade price quality on either dimension.

**RQ2 — who keeps linked markets consistent, and how does the fee change their incentives?** The
negRisk arbitrage band (RQ1's cross-market object) is closed by a **distinct, concentrated,
persistent** group of arbitrageurs — not the volume or profit leaders, cross-family generalists,
stable out-of-sample. The taker fee turns their positive gross edge into a **net loss** (net margin
**+42.8 → −106.5 bps**, pre → post), without changing who they are. *(publishable, positive)*

**How the two RQs relate.** The band `|S−1|` is the **shared object**: RQ1 asks about its *level*
(does the fee widen it? — no), RQ2 about its *agents* (who closes it, and does the fee change their
economics? — yes, it taxes them). Combined, they give the central tension of the paper: **the fee
does not measurably degrade market quality, yet it makes the price-correction that maintains that
quality unprofitable.** The correctors keep correcting at a loss — which both explains why quality is
preserved and raises the open question (*why persist?*) that the **maker-rebate extension** is meant
to answer (rebate income to the same wallets is the leading candidate).

**Incidence (supporting, not an RQ).** The fee is **regressive**: longshot buyers (p≤0.05) pay ~3.7%
of notional vs ~0.09% for favorites (p>0.90) — ~40×; smallest takers pay ~2× the whales. It describes
*who pays* for the quality that RQ1/RQ2 show is maintained.

## Pipeline

| Step | Script | Output |
|------|--------|--------|
| 1 | `scripts/40_build_negrisk_fills.py [--source tape\|archive]` | `data/parquet/negrisk_{v2,v1}/{map,fills}.parquet` |
| 2 | `scripts/41_negrisk_correction.py [--source v2\|v1]` | `data/export/rq2_{v2,v1}_{wallets,events}.parquet` + RQ2 analysis |
| 3 | `scripts/42_fee_calibration.py` | `data/export/calibration_era_decomposition.csv`, `calibration_reliability_1d.csv`, `negrisk_band_audit.json` |
| 4 | `scripts/43_fee_incidence.py` | `data/export/incidence_{overall.json,by_size.csv,by_price.csv}` |
| — | `notebooks/fee_effects.ipynb` | all tables + charts |

Logic lives in `src/intellifi/{negrisk,correction,fee_calibration,incidence,fee_figures}.py`. RQ1
also depends on the price series (`scripts/38`, `docs/PRICE_SERIES_RQ1.md` / `PRICE_SERIES_V1.md`).
Heavy scans are memory-safe (file-backed DuckDB + spill); launch inside
`systemd-run --user --scope -p MemoryMax=NG`.

End-to-end from a populated parquet store (each heavy step inside its own scope):

```
scripts/40_build_negrisk_fills.py              # v2 fee-era negRisk fills
scripts/41_negrisk_correction.py               # RQ2 v2
scripts/40_build_negrisk_fills.py --source archive   # v1 pre-fee negRisk fills
scripts/41_negrisk_correction.py --source v1   # RQ2 v1 (pre/post)
scripts/42_fee_calibration.py                  # RQ1 + band audit
scripts/43_fee_incidence.py                    # incidence
jupyter nbconvert --to notebook --execute --inplace notebooks/fee_effects.ipynb
```

Inputs required in `data/parquet/`: `tape_v2/`, `ctf_v2_conditions.parquet`, `clob_markets/tokens.parquet`,
`atlas/negrisk_family_hour_sums.parquet` (band audit), `../export/price_series_{rq1,v1}.parquet` (RQ1),
and `data/external/polymarket_v1/daily_aligned_multi/` (V1).

## Data and processing (correctness notes)

Verified field semantics that are easy to get wrong:

- **The exchange operator is not a trader.** `0xe2222d279d744050d28e00520010520000310f59` is the CTF
  operator — the `taker` on *every* taker-order row (1 distinct value over 21.6M rows; never a maker).
  The real aggressor/taker is the **`maker` field on `is_taker_order=TRUE` rows**.
- **No double-counting.** Each fill appears as a taker-aggregate row and maker-leg row(s) with swapped
  labels; canonical trades = `is_taker_order=TRUE` rows only (= `volumeClob`).
- **Dedup** the overlapping tape by `(tx_hash, evt_index)`; order trades by on-chain causal order
  `(block_number, evt_index)` (not second-resolution `ts`) for a deterministic running sum.
- **negRisk YES token** is always `ctf.token0`, so `yes_won == (winning_outcome_index == 0)`; 99.6% of
  families have exactly one winning candidate (mutual-exclusivity check).
- **Fees** are the actual `fee_raw/1e6` (USDC); no theoretical formula is assumed.
- V1 (pre-fee) uses the archive `daily_aligned_multi` layer, where each row is already a maker fill
  with the taker (aggressor) attached — no operator/double-count issue.

## RQ1 — calibration (`fee_calibration.py`)

`era_comparison()` computes the Murphy Brier decomposition (reliability − resolution + uncertainty)
for V1 (all / oracle-anchored) and V2 at the 1-hour and last-trade horizons, from
`price_series_{v1,rq1}.parquet`. **reliability** is the mis-calibration (forecast-quality) term;
**resolution** is sharpness. Result: reliability is ~0.0001 everywhere; the Brier difference between
eras is entirely resolution (composition). Reliability curves (`reliability_curve()`) for the ≥7-day
subset overlap on the diagonal in both eras.

## negRisk band audit (`band_audit()`) — rejected

Reproduces the raw fee>no-fee `|S−1|` gap (~0.028), then standardizes on volume × candidate-count and
runs a never-treated (politics/geopolitics) placebo. The placebo gap (~0.05) is as large as the raw
gap and far exceeds the cleanest-treated crypto gap (small, bin-sensitive, ≤~0.01) — so the
cross-sectional contrast is confounded by liquidity/market-type selection, not a fee effect. Bootstrap
CIs are seeded.

## Fee incidence (`incidence.py`) — regressive

Effective rate = `fee_raw / usdc` over canonical taker fills, by taker-size decile and price region.
Overall ~1.1% of notional; strongly regressive in price (≈3.7% at p≤0.05 → ≈0.09% at p>0.90) and by
size (smallest decile ≈2× whales, because whales trade favorites).

## RQ2 — price correction (`correction.py`)

For each negRisk family, reconstruct the running price-sum `S = Σ(YES last prices)` (carry-forward,
48 h staleness cap, ≥3 candidates). A taker trade is **corrective** if it reduces `|S−1|`; a mispricing
**episode** = `|S−1|` crossing `HIGH=0.05` then converging below `LOW=0.02`. Credit the aggressor; the
episode's **closer** = the wallet with the most corrective magnitude during it. `analyze()` reports:

- **Concentration** — only a few % of wallets ever close an episode (Gini ≈ 0.98).
- **Distinctness** — episode-wins barely correlate with dollar volume or profit (Spearman ≈ 0.26 / −0.03;
  top-100 overlap ≈ 0.09 / 0.03); correctors are cross-family generalists, not the whales.
- **Persistence** — first-half vs second-half episode-wins correlate (Spearman ≈ 0.49), including within
  families active in both halves → wallet-level skill, not luck or family recurrence.
- **Profitability** — correctors have positive gross PnL but the taker fee makes them **net-negative**.

Thresholds (`HIGH/LOW/MIN_CAND/STALE`) are **design choices**, not proven-optimal, and are exposed as
`attribute()` parameters. They are expected to be non-fragile (the median detected episode peaks at
`|S−1|` ≈ 0.10, well above `HIGH=0.05`, so the set of episodes is not balanced on the threshold), but
a full sensitivity sweep is not run in-pipeline — treat the point estimates, not the exact counts, as
the result.

### Pre- vs post-fee (duration-invariant margins)

The structural findings (concentration, distinctness, generalism, persistence) are **identical** in the
pre-fee V1 archive and the fee-era V2 tape — the phenomenon is stable across the regime. The economics
are not. Using margins (bps per $ of corrector volume) to remove the different time spans (V1 ~843 d,
V2 ~125 d):

| | V1 pre-fee | V2 fee |
|---|---|---|
| gross edge | +145.8 bps | +34.5 bps (edge ~4× smaller) |
| fee drag | ~0 (archive `fee_usdc` overcounted; true pre-fee ≈ 0) | −141.0 bps (reliable `fee_raw`) |
| **net margin** | **≥ +42.8 bps** (profitable) | **−106.5 bps** (loss-making) |

The fee does two things: the per-dollar arbitrage edge is ~4× smaller in the fee era, and the fee
(141 bps) exceeds that edge, so **price correction flips from profitable to a net loss** — the fee taxes
the arbitrageurs who keep linked markets consistent, without changing who they are. (V1 net is a lower
bound: the archive overcounts low-price sell fees, and true pre-fee fees are ≈ 0.)

## Caveats

- RQ2 measures the **taker/aggressor** correction channel; maker-side (liquidity-provider) repricing and
  the **maker rebate** link are not yet included (the natural resolution of "why correct at a loss?").
- V1 ordering is second-resolution (archive has no log index); V2 uses true `(block_number, evt_index)`.
- V1/V2 category taxonomies differ; the fee rollout is staggered (see `docs/atlas_2026-08-30/`), so the
  clean fee contrast is per-market fee status, not the V1/V2 data boundary.

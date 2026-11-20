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
stable out-of-sample. On the correction leg *alone* the taker fee turns their gross edge into a **net
loss** (net margin **+42.8 → −106.5 bps**, pre → post); but these traders are the platform's major
**maker-side liquidity providers** (by settled-fill volume), and their rebate + spread-capture income offsets most-to-all of their taker fees, so
they are **not net-taxed** — the fee/rebate design *sustains* correction rather than deterring it.
*(publishable, positive)*

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
| 1 | `scripts/46_build_negrisk_fills.py [--source tape\|archive]` | `data/parquet/negrisk_{v2,v1}/{map,fills}.parquet` |
| 2 | `scripts/47_negrisk_correction.py [--source v2\|v1]` | `data/export/rq2_{v2,v1}_{wallets,events}.parquet` + RQ2 analysis |
| 3 | `scripts/48_fee_calibration.py` | `data/export/calibration_era_decomposition.csv`, `calibration_reliability_1d.csv`, `negrisk_band_audit.json` |
| 4 | `scripts/49_fee_incidence.py` | `data/export/incidence_{overall.json,by_size.csv,by_price.csv}` |
| 5 | `scripts/50_maker_rebate.py` | `data/export/rq2_v2_rebate*` (fee's return side) |
| 6 | `scripts/51_episode_dynamics.py [--source v2\|v1]` | `data/export/episode_dynamics_{v2,v1}.{json,_episodes,_unconverged}.parquet` |
| 7 | `scripts/52_fee_did.py` | `data/export/fee_did.json` (causal layer: baseline + refined DiD) |
| — | `notebooks/fee_effects.ipynb` | all tables + charts |

Logic lives in `src/intellifi/{negrisk,correction,fee_calibration,incidence,fee_figures}.py`. RQ1
also depends on the price series (`scripts/38`, `docs/PRICE_SERIES_RQ1.md` / `PRICE_SERIES_V1.md`).
Heavy scans are memory-safe (file-backed DuckDB + spill); launch inside
`systemd-run --user --scope -p MemoryMax=NG`.

End-to-end from a populated parquet store (each heavy step inside its own scope):

```
scripts/46_build_negrisk_fills.py              # v2 fee-era negRisk fills
scripts/47_negrisk_correction.py               # RQ2 v2
scripts/46_build_negrisk_fills.py --source archive   # v1 pre-fee negRisk fills
scripts/47_negrisk_correction.py --source v1   # RQ2 v1 (pre/post)
scripts/48_fee_calibration.py                  # RQ1 + band audit
scripts/49_fee_incidence.py                    # incidence
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

## RQ2 maker economics — why the correctors persist (the fee's return side)

The correctors are the platform's **major liquidity providers** (65% also make; their maker volume ≈
their taker volume, ~$4.4B each, deduped), so the fee's *return* side flows back to them. Two
components, from `src/intellifi/rebate.py` (`scripts/50_maker_rebate.py`) and the validated markout
producer run with a corrector filter (`scripts/40_maker_markout.py --makers`):

- **Rebate** (modeled, DATA_DICTIONARY §10.3; `rebate = ρ·Σ fee_equivalent` — the pool denominator
  cancels): **$13.0M**, ~27% of their $48.3M taker fees (the 20–25%-of-fees design; ≤ the whole pool by
  construction, so it cannot alone offset the fee).
- **Markout / spread capture** (gross, outcome-independent next-trade price): **+$19.6M @60s →
  +$48.4M @900s → +$129M @1h**; under 45% of fills are adverse at every horizon.

Net-net: taker fees **−$48.3M** vs liquidity-provision income (**rebate +$13.0M + markout +$20–48M**)
→ LP income **covers ~⅔ of the fee bill at 1-min horizons and all of it at ≥15-min**. So the −$7.5M
negRisk correction loss is a **loss-leader inside profitable, rebate-subsidized maker-side liquidity
provision**: the fee does **not** net-tax the correctors, which is why they persist and why price
quality is preserved (RQ1). *Honest limits:* markout is gross of inventory/holding costs; the rebate is
modeled, not the on-chain payout; and the correctors' full taker *trading* PnL across all markets is
not closed — this is the LP-income-vs-fee piece, enough to explain persistence, not a books-closed net.

## Episode dynamics and the fee DiD (`scripts/51`, `scripts/52`)

`scripts/51_episode_dynamics.py` (module `episode_dynamics.py`) instruments the RQ2 detector to also
record correction *speed*, openings that never converge, and volume/dollar weighting;
`scripts/52_fee_did.py` (module `fee_did.py`) is the causal layer. The canonical build is now
**deterministic** (V1 = 365,587 closed episodes; V2 gate = 210,993 exact).

**Descriptive (V1 pre-fee vs V2 fee — robust, regime-level):**
- **Un-converged openings** are economically negligible: 6.8% (V2) / 1.8% (V1) by count but
  **0.29% / 0.07% volume-weighted**; 94.7% (V2) are resolution-ended (the market ended, not the fee
  deterring correction). Never-closed gaps are big-gap but tiny-dollar — quality is preserved where it
  matters.
- **Correction speed is governed by liquidity**: log10(correction s) on log10(family volume) has
  elasticity **−0.58 (V2) vs −0.21 (V1)** (clustered SE ~0.02), ~2.7× steeper under the fee; median
  correction ~5 min (V2) / 7 min (V1), down to ~15 s in the deepest V2 markets.
- **Volume-weighted density**: V2 is 1.22× V1 by episode count per active-family-day but **1.30× by
  corrective-$/afd**; mean corrective-$ per closed episode is regime-invariant (~$180). The extra V2
  correction is real in dollars, not a swarm of tiny episodes (that is the un-converged tail). ~4× per
  calendar day = ~3.2× more active families/day × ~1.2× per-family intensity.
- **Concentration**: top-100 correctors do 32.6% of episode *count* but **57.6% of corrective dollars**
  (Gini 0.77→0.94); distinctness-from-volume-leaders **survives** dollar-weighting (Spearman
  0.262→0.263). The terminal/clean split uses a window **relative to family life** (a fixed 48 h window
  ≈ a whole short V2 market); ~26% of closes are terminal in both eras and concentration holds on the
  clean (~74%) subset.

**Causal (fee vs no-fee DiD) — not identifiable; a clean null.** Treatment = each family's empirical
fee-activation. **Zero families traded both before and after their fee turned on** (the fee attaches at
market birth), so a within-family DiD is impossible. Pooled TWFE shows apparent effects (duration
+0.20, un-converged +2.1 pp, a −0.15 liquidity-gradient interaction), but under the refined spec
(V1 rollout window + family-age control) they collapse — duration +0.19 with a **placebo still +0.10
(p≈0.06)**, the interaction **−0.04 (insignificant)** with a clean placebo, un-converged **+0.4 pp**.
So the V1/V2 correction-dynamics differences are **composition/regime, not the fee** — consistent with
the calibration null (RQ1) and the rejected band-widening. The fee's *measured* consequences are the
directly-observed incidence and subsidy capture, not DiD'd behavioral outcomes.

## Caveats

- RQ2 measures the **taker/aggressor** correction channel; maker-side (liquidity-provider) repricing and
  the **maker rebate** link are not yet included (the natural resolution of "why correct at a loss?").
- **Fill-attribution scope (cf. Nechepurenko, arXiv:2605.11640):** "correctors" and their maker-side role
  are defined by *settled-fill* roles (aggressor on is_taker rows; maker-side volume), not quoting /
  cancellation behaviour, which is unobservable from fills — do not read "market maker" as continuous quoting.
- **Mint/merge-clean:** volume/dollar metrics use YES-token legs only (the NO leg of complete-set mints is
  excluded) and is_taker_order=TRUE taker-order aggregates (maker-leg fragmentation collapsed); verified
  2026-11-19 (34.6M maker legs → 22.07M taker legs; 0 logs carry both is_taker values).
- V1 ordering is second-resolution (archive has no log index); V2 uses true `(block_number, evt_index)`.
  `build_canonical_v1` is now fully deterministic (ORDER BY on code tables + evt_index tie-break incl.
  `is_buy`); scripts/47 and scripts/51 agree (V1 = 365,587).
- V1/V2 category taxonomies differ; the fee rollout is staggered (see `docs/atlas_2026-08-30/`), so the
  clean fee contrast is per-market fee status, not the V1/V2 data boundary — and the fee attaches at
  market birth, so a within-family DiD is unidentified (0 switchers).

## Reproducing every figure

All figures in the results outline rebuild from one tracked path:

```bash
# render every figure from existing data/export + committed docs/*.json (fast):
python scripts/54_build_outline_figures.py
# or rebuild the derived category-composition table first (scans the negRisk fills, ~40s):
systemd-run --user --scope -p MemoryMax=6G python scripts/54_build_outline_figures.py --composition
```

Each figure is a function in `src/intellifi/fee_figures.py`; `scripts/54` is a thin orchestrator.
Sources (all tracked code / committed JSON / R2-deposited `data/export`):

| figure group | producer | data source |
|---|---|---|
| `comp_*` (composition) | `fig_comp_*` | `data/export/category_composition.csv` + `composition_summary.json` (built by `scripts/54 --composition` from the negRisk fills) |
| `rq1_taker_economics` | `fig_rq1_taker_economics` | `docs/platform_wide.json` (scripts/27), `docs/v2_platform.json` (scripts/28) |
| `rq1_lorenz`, `rq1_profit_concentration` | `fig_rq1_lorenz`, `fig_rq1_profit_concentration` | `data/export/rq2_{v1,v2}_wallets.parquet` (scripts/47); Gini from the platform JSONs |
| `rq1_skill` | `fig_rq1_skill` | `docs/skill_signflip.json` (scripts/31), `docs/skill_signflip_v2.json` (scripts/53) |
| `rq3_incidence_*` | `fig_incidence_*` | `data/export/incidence_by_{price,size}.csv` (scripts/49) |
| `rq3_lp_economics` | `fig_rq2_lp_economics` | `data/export/rq2_v2_rebate_summary.json`, `corrector_markout.json` (scripts/50) |
| `rq2_reliability`, `rq2_brier` | `fig_reliability`, `fig_brier_decomp` | `data/export/calibration_*.csv` (scripts/48) |
| `rq2_speed_by_volume`, `rq2_unconverged_rate`, `rq2_concentration_count_vs_dollar`, `rq2_density_by_category` | episode-dynamics figs | `data/export/episode_dynamics_{v1,v2}.json` (scripts/51) |
| `rq2_fingerprint_*`, `rq2_prepost_economics` | `fig_rq2_*` | `data/export/rq2_{v1,v2}_{wallets,events}.parquet` (scripts/47) + `correction.analyze` |

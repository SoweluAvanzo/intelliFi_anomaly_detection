# Stage II pre-registration — Sample B (Polymarket v2 tape)

**Registered:** 2026-08-30 (Europe/Rome), before any confirmatory statistic on Sample B was computed.
**Protocol:** `polymarket_anomaly_detection_spec_v2.md` §10 (explore on A → register → confirm on B).
**Exploration record:** `docs/atlas_2026-08-30/` (Sample A: v1 archive, Oct 2025 → Apr 2026 for fee questions; 2023-01 → 2026-04 for structural questions).

## 0. Disclosure of what was seen on Sample B before registration

One descriptive pass over 31 hours of v2 fills (6–7 June 2026, 7.5 M `OrderFilled`) was run on 2026-08-30 to verify the decoder: it showed 728 distinct `builder` codes with 87 % of taker orders unattributed, fee-paying shares of 92–98 % of taker orders in every price bucket, an average fee of ~98 bps of notional, maker HHI 0.004 with the top 1 % of makers supplying 69 % of maker volume, and zero self-matched fills. These figures informed H1c, H3 and the exploratory items in §6; they are **not** confirmatory evidence and the 6–7 June hours are excluded from every confirmatory test below.

## 1. Sample B definition (frozen)

- **Source:** on-chain `OrderFilled` events of the two v2 exchanges (`0xe111180000d2663c0091e4f400237545b87b996b`, `0xe2222d279d744050d28e00520010520000310f59`), decoded by `intellifi.fills.decode_v2_log`; resolution outcomes and times from the v2 conditional-tokens `ConditionResolution` events; market metadata (question, category tags, negRisk family) from Gamma, fetched from an unblocked network. Collateral pUSD (`0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`).
- **Confirmatory window:** blocks 88,080,000 → 88,843,826 (≈ 2026-06-08 00:00 UTC → 2026-06-22 00:00 UTC; exact bounds taken from block timestamps once crawled). Markets: all markets with ≥ 1 fill in the window. Time-to-resolution statistics use only markets that resolve within the window + 14 days.
- **Completeness gate:** the window is analysed only if (a) every 2,000-block chunk is present, (b) for a random sample of 20 chunks a second independent fetch returns the identical (tx, logIndex) set, and (c) the taker-order records equal the `OrdersMatched` count on a sample of 20 chunks fetched with all events. Failure → fix collection, do not analyse.
- **Unit conventions:** one row per maker fill; the taker-order record is the row whose `taker` is an exchange address; `shares = usdc / price`; fee per fill from the event's `fee` field (pUSD, 6 decimals). Category classes via the same tag→class mapping as Sample A (`data/parquet/atlas/category_to_feeclass_mapping.csv`, extended for new tags by the same rules before any outcome is computed).

## 2. Treatment definition (frozen)

Fee status per fill = `fee > 0`. Fee status per market = ≥ 50 % of taker orders fee-paying. **Contingency registered now:** Sample A showed fee exemption for geopolitics/world/macro/US-politics categories; if in Sample B fewer than 5 % of taker orders in *every* class are fee-free, the within-B control group does not exist and H3–H4 are tested as within-class pre/post comparisons against Sample A (April 2026 for the same classes, and the never-treated classes' own April → B change as the control), which is a weaker design and will be labelled as such.

## 3. Confirmatory hypotheses (primary; Holm-corrected at α = 0.05 across H1–H4)

Each hypothesis states the statistic exactly as computed on Sample A (script names in `docs/atlas_2026-08-30/scripts/`), the prediction derived from A, the null model, and the decision rule.

**H1 — Wash-like activity does not rise under v2 fees (integrity).**
- H1a *One-step round trips*: share of taker volume in same-wallet BUY→SELL (or reverse) on the same token within 10 min with size overlap ≥ 50 % (`atlasB/s03_daily_rt_pairs.py`). Prediction: in fee-paying classes ≤ the Sample A April level of the same class + 1 pp. Decision: TOST equivalence with bounds ±1 pp on the B − A(April) difference, class-clustered SE; "confirmed" if both one-sided p < 0.05.
- H1b *Concentrated pairs*: volume share of wallets with counterparty HHI ≥ 0.5 and ≥ 100 fills whose top counterparty reciprocates (`atlasB/s06_pairs_rollup.py`). Prediction: ≤ 0.1 % of fee-paying volume. Decision: point estimate ≤ 0.1 % with the upper 95 % bootstrap bound ≤ 0.5 %.
- H1c *Self-matching*: fills with `maker == taker`. Prediction: exactly 0 (structural). Decision: any non-zero count refutes; report count.

**H2 — The negRisk no-arbitrage band is wider under fees than fee-free, and scales with the fee rate (integrity / price consistency).**
- Statistic: hourly family price sum S = Σ last YES price over alive candidates, hours with ≥ 80 % of candidates traded and ≥ 3 alive (`atlasB/s02_multi_hourly.py`, `s04_q4.py`); outcome |S − 1|.
- Prediction: median |S − 1| in B fee-paying families > 0.012 (A fee-free median) and, because the v2 effective fee is lower than the archive-implied v1 fee, ≤ 0.031 (A fee median); the regression coefficient of |S − 1| on the fee-band size (0.10 × Σ min(p, 1−p) in A; the v2 fee-rate equivalent in B) is positive with family-clustered p < 0.01.
- Decision: both the ordering and the coefficient sign/significance must hold.

**H3 — Provider structure is unchanged under fees (market quality).**
- Statistics: maker-volume HHI and top-5 maker share per class-week (`atlasA/passB_weekly.py`); realized-spread proxy = per (token, minute) VWAP(taker BUY) − VWAP(taker SELL), volume-weighted.
- Prediction (from A's nulls with CIs ±25 % on HHI, ±0.5 cents on spread): B fee-paying classes are within ±25 % of their A April HHI and top-5 share, and within ±0.5 cents of their A April spread proxy.
- Decision: TOST equivalence at those bounds, class-clustered SE, p < 0.05 for all three statistics; failure of any one is reported as "not confirmed" for that statistic.

**H4 — Taker order size is lower under fees (the one directional effect A could not identify).**
- Statistic: log mean and log median taker order size per class-week.
- Design: DiD of B vs A(Oct–Dec 2025, pre-fee) for classes treated during A vs never-treated classes (if a fee-free control exists in B; else the §2 contingency).
- Prediction: β < 0 (A's TWFE −0.40 / −0.16 log points, all specifications negative). Decision: one-sided p < 0.05, class-clustered SE (G = 8) with wild-cluster bootstrap p also reported.

## 4. Secondary hypotheses (reported with 95 % CIs; no confirmatory claim)

- **H5 Fee incidence** (`atlasA/q3_incidence.py`): within-fee-market fee rate is decreasing in taker size decile (regressive); exemptions = 0; entrants' rate exceeds incumbents' through exposure. Prediction: same pattern as A; report the decile table.
- **H6 Maker concentration** (`atlasC/q6b.py`): top-10 share of maker notional in 8–14 %, top-10 fill share ≤ 5 %, month-to-month persistence 0.3–0.6.
- **H7 Share creation** (`atlasC/q5ctf.py`, conditional on identifying the v2 conditional-tokens contract): exchange minting = 55–75 % of binary share volume.
- **H8 Resolution-anchored convergence** (`atlasC/q6a.py`, resolution time from `ConditionResolution`): median |1 − p| one hour before resolution ≤ 0.01; the distribution remains bimodal (p90 ≥ 0.30), with sports and price-action classes driving the upper mode.
- **H9 Feed-vs-tape universe** (Stage I `select_universe` on B taker rows vs on all B rows): overlap of the top-50-by-notional lists < 50 %.

## 5. Frozen parameters

Cotrade bucket 300 s, ≥ 3 events; lead–lag ≤ 600 s consecutive distinct seconds, ≥ 5 events; round-trip 600 s, ≥ 50 % overlap; pair-HHI ≥ 0.5 with ≥ 100 fills; negRisk hours ≥ 80 % coverage, ≥ 3 alive candidates, prices ≤ 24 h old; position skill ≥ 5 positions in ≥ 3 markets, implied p ∈ [0.05, 0.95], prior strength 4; class-week panels require ≥ 100 fills; DiD event windows −8…+8 weeks; all standard errors clustered at the class (or family) level with wild-cluster bootstrap when G ≤ 12. Activity-preserving nulls and BH q-values as in Stage I. Any parameter change after this date is a deviation (§7).

## 6. Exploratory on B (not registered; reported as descriptive)

Order-flow attribution by `builder` (fill share, fee incidence, maker/taker mix, price impact by source); rebate flows (`FeeCharged` receivers, rebate concentration, rebate per notional); v1→v2 wallet migration (same address or shared funding source), entry/exit by wallet type; ghost-fill incidence if `OrdersMatched` and settlement reverts can be linked. Findings here generate hypotheses for a later sample, never confirmatory claims on B.

## 7. Deviations log


### Deviation 1 — 2026-08-31: tape definition and gate comparison

The cohort-1 gate (first run, 2026-08-30 22:00 UTC) FAILED invariant (b): 3/20 sample chunks
re-fetched identically; invariant (c) passed 20/20. Diagnosis (chunk 88318000–88319999,
re-fetched independently): the on-disk chunk is a strict subset of the re-fetch (0 rows on
disk missing from the re-fetch); every one of the 158 extra rows is emitted by a third
Polymarket contract (`0xe3333700ca9d93003f00f0f71f8515005f6c00aa`) whose `OrderFilled`
signature the crawler only began retaining as `other:*` rows on 2026-08-30, mid-collection.
No data loss occurred; the tape was definitionally heterogeneous.

Remedy, decided before the amended gate was re-run:
1. The Sample B tape is **defined** as the two v2 exchanges (`v2_a`, `v2_b`). Rows from any
   other emitter of the same signatures live in `data/parquet/tape_v2_other/` (241 mixed
   chunks rewritten on 2026-08-31, 270,387 rows moved; verified 0 non-exchange rows remain).
2. The gate compares disk vs re-fetch **within the two exchanges** (like-for-like);
   `scripts/11_gate_v2_cohort.py` amended accordingly.
3. The third contract's full event history is backfilled into `tape_v2_other/` by
   address-filtered fetch, so nothing is discarded; third-contract activity is analysed
   separately (research plan RQ6/C3 residual-vectors item).
4. The amended gate is re-run on the same 20-chunk sample (seed unchanged). Analyses remain
   blocked until it passes.

Any change to §1–§5 is appended here with date, reason and the statistic affected, before the changed analysis is run.

| date | change | reason |
|---|---|---|
| — | — | — |

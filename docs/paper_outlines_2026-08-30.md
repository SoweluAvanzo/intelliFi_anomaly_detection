# Paper outlines — three papers, one line of reasoning (2026-08-30)

Companion to `research_plan_2026-08-30.md`. Each paper has one general research question decomposed into three sub-questions, and each sub-question owns one results section. The three papers form a sequence: **A** establishes what can be measured from Polymarket data and shows that the cross-sectional manipulation signals do not survive correct measurement; **B** applies that measurement stack to the two 2026 regime changes (taker fees, v2 migration) and asks how they changed who pays, who provides liquidity, and whether the behaviour that disciplines prices weakened; **C** uses the v2 architecture to open two things that were never observable before — the origin of order flow and the reliability of settlement — and releases the tape.

Data legend used throughout: **have** = on disk and validated; **cohort k** = v2 tape cohort k (cohort 1 closes today; six cohorts of two weeks cover 28 April → today); **needs** = external input we do not control.

---

## Paper A — *Measuring manipulation on Polymarket: what public data can and cannot support*

**Venue:** workshop / short paper (FC workshops, DeFi Security, or an arXiv data note); drafted from data we already have.

### General question

**RQ_A.** Which manipulation-consistent signals on Polymarket can be established from public data, once measurement is validated against complete on-chain ground truth and evaluated against appropriate null models?

### Line of reasoning

The literature reports whale concentration, coordinated clusters, copy-trading, wash volume, mispricing that persists to close, and a skilled minority — mostly from the platform's public feeds. We first show that the public feeds are biased samples of the tape and that several measurement conventions in use produce spurious signals (A1). We then re-measure the signals on the feed and on the complete tape, with activity-preserving null models, matched controls and the correct close reference, and show that they vanish (A2). Finally we address the one signal the literature treats as robust — a skilled minority — with a position-level design that separates skill from the price paid, and establish what sample is needed for it to be detectable at all (A3). The output is a set of measurement rules and a corrected baseline that Papers B and C build on.

### Sub-questions

**A1 — Measurement.** How do the public feeds (Gamma, Data API `/trades` and `/holders`, CLOB `/prices-history`) relate to the complete on-chain tape, and which measurement conventions produce spurious manipulation signals? — *have.*

Evidence: `/trades` is a taker-only tail sample (4,000-row cap hit by 92/100 markets; ~90 % of rows at p ≤ 0.05 or ≥ 0.95); feed-based and tape-based "whale" universes overlap 20/134; the whales are 96 % makers; Gamma `volume` is a share count equal to Σ taker-order shares (ratio 1.000 on five markets); three distinct close timestamps (`end_date`, `closed_time`, on-chain resolution; median gap +21 h, range −5,433 … +682 h); ERC-1155 wallet-to-wallet transfers are fill settlements, not relationships; `/holders` truncates at 500 per outcome (92/100 markets); the CLOB never crosses a wallet with itself (self-match exactly 0 in v1 and v2, which settles the direct-self-match component of the published two-tier wash-suspect bound; the ~1 % median is then flipped pairs, to be decomposed on the same window); ≈71 % of binary share volume is exchange minting, under-identified 2.7× by tape-only rules. The public v1 archive is validated row-for-row against an independent reconstruction (171,126 = 171,126 maker fills; 12,532/12,532 feed rows reconciled; 100 % share conservation).

**A2 — Signal survival.** Do concentration, coordination, copy-trading, wash and mispricing-at-close signals survive activity-preserving null models, matched placebo controls and the correct close reference — on the feed and on the complete tape? — *have.*

Evidence: before/after audit table (Gini 0.94 whales, 65 communities, 2–4 s copy-trading, 2–2.5× mirror edge, heavy mispricing tail → all artefacts); cotrade and leader–lag pairs at 0 BH discoveries under the null; wash round-trips 1–2 % of volume, none concentrated; mirror backtest indistinguishable from matched controls at every horizon; prices converged by `closed_time` in every market; every null replicates on the complete tape for the same 100 markets.

**A3 — Skill versus price paid.** Can wallets that win more than the prices they paid imply be separated from calibration noise, and what sample is required? — *have (v1); the cross-regime extension is Paper B.*

Evidence: position-level Beta calibration with exact intervals against a leave-one-out reliability-curve benchmark; 14,949 wallets on the complete tape, 0 BH discoveries; power curve: minimum number of informative-band positions per wallet for a given calibration gap to be detectable, and the fraction of wallets that reach it; on the feed the design is not estimable because the maker side is missing.

### Section plan

1. **Introduction.** Manipulation claims about prediction markets rest on public data; the SoK lists the taxonomy but no validated measurement. Contributions: (i) a validation of the public feeds and of the CC-BY archive against independent on-chain reconstruction; (ii) a catalogue of measurement conventions that generate spurious signals, with magnitudes; (iii) corrected null results with null models and matched controls; (iv) a position-level skill test with a power analysis. Headline sentence: on data the platform exposes, none of the manipulation-consistent signals survives correct measurement, and the reasons are structural, not sample-size.
2. **Background.** Polymarket mechanics needed to read the paper: CTF outcome tokens and the mint/merge mechanism; the CLOB as an off-chain book with on-chain settlement (`OrderFilled`, maker vs taker records, operator-submitted matches); negRisk families; UMA resolution and the three close timestamps; the public endpoints and their caps; identifier map (`conditionId`, token ids, slugs).
3. **Related works.** The SoK (Rahman, Al-Chami, Clark 2025) and its gaps 1, 3, 8, 10; the 2026 complete-data papers (Mitts & Ofir; Gómez-Cram, Guo, Kung & Jensen; Sirolly, Ma, Kanoria & Sethi; the archive paper 2606.04217; 2604.24366; 2603.03136; 2606.16852); wash-trading measurement in crypto (Cong et al. 2023; Victor & Weintraud 2021); null models for co-occurrence networks; calibration and reliability curves. Position: we are the measurement paper the others presuppose.
4. **Methodology.** Data: feed corpus (100 markets, 382,554 trades, holders, price histories, on-chain transfers for a 134-wallet universe); the v1 archive; Dune and Etherscan reconstructions used only for validation. Validation invariants (taker match, per-transaction conservation, coverage gain, completeness vs share volume). Analysis stack: concentration (gross, net-flow, holdings; family consolidation); cotrade / leader–lag / wash with activity-preserving nulls and BH; matched-control mirror backtest with a temporal split; convergence from `closed_time`; position-level calibration. Reproducibility: seeded, sorted, snapshot-compared; verifier shipped with the CSV bundle.
5. **Results 1 — A1.** Table 1: feed vs tape (coverage, side, price band, universe overlap, maker share, volume unit, close references, holders, ERC-1155, minting share, self-match bound). Figure: price distribution of feed rows vs tape fills; hours-to-close distribution under each close reference.
6. **Results 2 — A2.** Table 2: before/after audit table with the correction responsible for each change. Figure: null distributions vs observed for cotrade and leader–lag; mirror-backtest PnL vs matched controls by horizon; convergence curves from `closed_time`. Replication column on the complete tape.
7. **Results 3 — A3.** Figure: reliability curve with wallet positions; distribution of calibration gaps with BH threshold; power curve. Table: wallets by positions-in-band and detectable gap.
8. **Discussion.** What a valid detection pipeline needs (complete fills, both sides, resolution ground truth, nulls); implications for the SoK gaps and for the published magnitudes we contradict; limits (v1 only, resolved markets, no order-book depth, wallet ≠ person).
9. **Conclusion.** Restate the measurement rules; release the validation code and the corrected baseline; point to B and C.

---

## Paper B — *Fees, rebates and market integrity: evidence from Polymarket's 2026 transition* (main paper)

**Venue:** finance journal (Journal of Financial Markets, Journal of Banking & Finance) or Management Science fintech; pre-registered.

### General question

**RQ_B.** How did the introduction of taker fees and the migration to a rebate-paying exchange change who pays for trading on Polymarket, how liquidity is provided, and whether the taker behaviour that disciplines prices — arbitrage, wash trading, informed trading — weakened?

### Line of reasoning

A fee is a treatment only once we know what it is and who bears it, so incidence comes first (B1). The supply side responds next: with a zero maker fee and, after the migration, per-market rebates, make/take theory predicts a shift toward liquidity provision and a change in concentration and spreads (B2). The demand side then determines whether prices stay disciplined: arbitrageurs keep multi-outcome prices consistent, wash traders inflate volume, informed takers move prices toward fundamentals — each is taxed by the fee, so each may withdraw (B3). Identification is two-step: January → April isolates fees with contracts unchanged; April → June isolates the migration with fees in place on both sides; fee-exempt categories serve as within-period controls, and six v2 cohorts test whether effects persist.

### Sub-questions

**B1 — Incidence.** What fee is actually charged, who pays it, and is it regressive across trader size, price and vintage? — *have (v1); cohort 1–6 for exact fee-receiver accounting.*

Evidence: fee attaches at market birth by category (the `taker_base_fee` field is decorative; zero exemptions); fee = 0.10 · shares · min(p, 1−p); within-market effective rate 7.9 % of notional for small long-shot takers vs 4.4 % for the largest; post-rollout entrants pay 5.7× the pre-2024 cohort through exposure (69 % vs 12 % of their volume in fee categories), not through rate. v2 adds exact platform take from fee-receiver transfers (~98 bps in June) and the rebate outflow.

**B2 — Liquidity provision and market quality.** Did fees, and then rebates, change liquidity provision, maker concentration, spreads, order size and participation? — *partial (v1: concentration and spread null, volume not identified); cohorts 1–6 supply the post-period and the rebate test.*

Evidence so far: no pre-trend and no effect on maker HHI (CI ±25 %) or realized-spread proxy (±0.5 ¢); order size negative in every specification; volume and participation not identified with ≤ 3 post weeks for 49 % of tags. Predictions registered for v2: rebates raise maker participation and lower maker concentration in rebated markets relative to non-rebated; spread response bounded by the rebate.

**B3 — Price discipline.** Did the takers that discipline prices change behaviour: the negRisk no-arbitrage band, wash-like activity, and informed-taker participation? — *have (v1 band, wash); cohorts for replication; informed-taker persistence needs cohorts 1–6.*

Evidence so far: median |Σp − 1| across candidates 0.012 (fee-free) → 0.031 (fee), +3.4–4.2 pp with fixed effects (SE 0.002–0.003), signed mean unchanged — fees widen the band within which prices can be inconsistent or moved before arbitrage corrects them; one-step round trips 1–2 % of volume, lower in fee fills in 7 of 8 classes, staggered DiD +0.1–0.3 pp n.s., concentrated pairs ≤ 0.02 %; self-match exactly 0. Registered for v2: band median between 0.012 and 0.031; positive fee-band coefficient; the same wallets tracked by address across regimes, with the skilled-minority share stable or lower under fees and informed taker volume shifting to the maker side.

### Section plan

1. **Introduction.** Prediction markets are the first exchange type to introduce fees on a live, fully observable book; the fee scales with p(1−p) and has no maker leg — a design with no equity analogue. Two regime changes in four months give two-step identification. Contributions: incidence, the first prediction-market test of make/take theory, and the integrity results (band widening, wash bounds, informed-taker response). Headline: fees are regressive on entrants and long-shot takers, do not move liquidity provision measurably, and loosen the arbitrage constraint by about 3–4 pp.
2. **Background.** The fee rollout timeline by category (January → April 2026); the v2 migration (28 April: new exchanges, pUSD collateral, per-market rebates, builder attribution, no self-crossing); how the fee is computed and who receives it on-chain; the negRisk gadget and why Σp = 1 is the arbitrage condition; the taker/maker roles in the CLOB.
3. **Related works.** Make/take fee theory and evidence (Colliard & Foucault 2012; Malinova & Park 2015; Battalio, Corwin & Jennings 2016; Foucault, Kadan & Kandel 2013); transaction-tax literature (Colliard & Hoffmann 2017; Jones & Seguin 1997); combinatorial arbitrage in prediction markets (Saguillo et al. 2025); wash-trading bounds and liquidity-reward manipulation (Sirolly et al.; 2604.24366; 2606.16852); informed trading on Polymarket (Gómez-Cram et al.; Mitts & Ofir); staggered DiD (Callaway & Sant'Anna 2021; Goodman-Bacon 2021). Position: first causal evidence on fees in a prediction market and first evidence on fee effects on cross-market consistency.
4. **Methodology.** Data: complete v1 tape (October 2025 → April 2026 for the fee step; 16,718 negRisk families, 311 k family-hours; 323 category tags, 105 treated / 218 never-treated) and the v2 tape (cohorts 1–6). Units and panels: category-week for B2, family-hour for the band, wallet-pair-week for wash, wallet-position for informed trading. Identification: staggered DiD with never-treated controls and event-time plots; dose (fee-band size) as continuous treatment; the April → June step by class; TOST equivalence for nulls; class- or family-clustered SEs with wild bootstrap when G ≤ 12; Holm across primary hypotheses. Pre-registration (`stage2_preregistration.md`, hash recorded) and the explore/confirm split: v1 explores, v2 cohorts confirm. Threats: market vintage (dose and within-vintage comparisons), seasonality and event mix (class × calendar controls), platform growth (week FE, never-treated trend), fee-level uncertainty (on-chain fee-receiver accounting).
5. **Results 1 — B1.** Table: fee rule verification (fee vs 0.10·shares·min(p,1−p), residual); effective rate by trader-size decile × price band; incidence by vintage. Figure: Lorenz curve of fees paid vs notional; v2 fee-receiver inflow vs implied fee by cohort.
6. **Results 2 — B2.** Event-time plots for HHI, top-5 share, spread proxy, order size, participation, volume (v1 fee step); April → June by class (migration step); rebated vs non-rebated markets within cohorts. Table: DiD estimates with equivalence bounds.
7. **Results 3 — B3.** Figure: distribution of |Σp − 1| by fee status and by band size; event-time plot of the band. Table: band coefficients (FE, dose, v2 replication by cohort). Wash: round-trip share and pair statistics by fee status with null bands. Informed trading: skilled-minority share and calibration gaps for wallets observed in both regimes; taker/maker mix of the informed set.
8. **Discussion.** Fees as a manipulation-resilience parameter (wider band = cheaper to move a candidate's price unnoticed); why volume-based wash metrics mislead under fees; rebate design and the liquidity-reward manipulation literature; external validity (Kalshi, on-chain exchanges); limits (bundled migration treatment, no order-book depth, ≤ 6 cohorts).
9. **Conclusion.** Who pays, what did not change, and what loosened; policy implication for fee design in prediction markets; roadmap for cohorts beyond six.

---

## Paper C — *Order flow and settlement on Polymarket v2: a complete on-chain tape*

**Venue:** AFT or Financial Cryptography main track; the tape is released CC-BY as part of the contribution.

### General question

**RQ_C.** What does the v2 architecture make observable about the origin of order flow and the reliability of settlement, and did the migration remove the settlement-layer integrity failures documented on v1?

### Line of reasoning

v2 changed the exchange contracts, the collateral, the event layouts and the matching rules, so the first task is to show that the complete tape can be rebuilt from public logs and validated, and to establish where v2 differs from v1 on-chain (C1). The tape carries a field v1 never had — a builder code on every taker order — so for the first time order flow can be attributed to its channel and integrity signatures compared across channels (C2). Finally, the migration's stated engineering goals (no self-crossing, a rewritten CLOB, a new collateral token) can be tested against the settlement-failure modes documented on v1 — ghost fills, reverted matches, self-trades (C3).

### Sub-questions

**C1 — Tape reconstruction and v1 → v2 comparison.** Can the complete v2 tape be reconstructed and validated from public logs alone, and in which respects does v2's on-chain footprint differ from v1's? — *cohort 1 (gate runs today); cohorts 2–6 extend.*

Evidence: decoder for the new `OrderFilled` / `OrdersMatched` / `FeeCharged` layouts; conservation per (transaction, market); re-fetch invariants (pre-registered gate); genesis at block 86,126,978; a third contract (`0xe3333700…`) emitting dust self-trades. Comparison domains: event layouts and fee accounting (explicit `FeeCharged` vs implicit), collateral (USDC.e → pUSD), matching rules (self-cross allowed → impossible), mint/merge expression, maker concentration (HHI 0.004 in June vs the v1 series), fee level (~98 bps).

**C2 — Order-flow attribution.** Where does order flow come from, how concentrated is third-party flow, and do integrity signatures differ by channel? — *cohort 1 exploratory; cohorts 2–6 confirmatory once hypotheses are registered.*

Evidence so far: 728 builder codes in June; 87 % of taker orders unattributed (native front-end); third-party flow HHI 0.84. Planned: fill share, fee incidence, order size, maker/taker mix, round-trip and pair statistics, calibration gaps by channel; whether bot channels supply or consume liquidity; whether wash-like or copy-trading signatures concentrate in a channel.

**C3 — Settlement integrity.** Did the post-May-4 fix hold — i.e. did ghost fills stay near zero after the migration's initial spike — and which settlement-layer failure modes remain? — *cohorts 1–6 plus operator transaction lists for v1 and v2 weeks (Etherscan `txlist`, free).*

Evidence: self-match exactly 0 in both versions (a structural property of the operator, not a migration effect); ghost fills measured on-chain as reverted operator transactions to the exchange (the v1 baseline is measured the same way for matched weeks, so the comparison is like-for-like and independent of the 24 % peak reported from API data); residual failure modes: reverts by cause, dust self-trades on the third contract, and settlement-path MEV (SoK Gap 8) via same-block reordering around matches.

### Section plan

1. **Introduction.** On-chain settlement of an off-chain book is the design pattern of every large prediction market; its integrity has only been studied on v1 and from the API side. Contributions: the first complete v2 tape with validation; the first order-flow attribution on a prediction market; a like-for-like settlement-integrity comparison across a platform migration. Headline: the migration removed the self-crossing vector by construction and (prediction) reduced reverted matches to near zero, while order flow is dominated by the native channel with a highly concentrated third-party tail.
2. **Background.** v1 and v2 contract architectures side by side (exchanges, CTF, collateral, fee receiver, operator); the matching and settlement path (order signing → operator match → on-chain `OrdersMatched`); the builder attribution field; what a ghost fill is at the protocol level.
3. **Related works.** Settlement integrity and ghost fills (2606.16852); MEV and operator-ordered settlement (Daian et al. 2020; Qin, Zhou & Gervais 2022); order-flow attribution and payment for order flow in equities (Battalio, Corwin & Jennings 2016); DEX tape reconstruction and validation (the archive paper 2606.04217; our Paper A); wash-trading in DEX and NFT markets (Victor & Weintraud 2021; von Wachter et al. 2022).
4. **Methodology.** Log crawl and decoding (Etherscan V2 `getLogs` by signature; adaptive walker; four keys); validation gate (conservation, duplicate-free, re-fetch agreement, share volume vs on-chain resolution registry); cohort design and pre-registration; attribution measures and their nulls; reverted-transaction measure and matched-week v1 baseline; MEV detection on the settlement path (same-block adjacency to matches by non-operator senders).
5. **Results 1 — C1.** Table: gate results per cohort; v1 vs v2 comparison table by domain. Figure: daily fills, fees and rebates from genesis; maker HHI series continued from v1.
6. **Results 2 — C2.** Table: channel share, HHI, per-channel fee incidence, order size, maker/taker mix. Figure: channel composition over cohorts; integrity signatures by channel with null bands.
7. **Results 3 — C3.** Figure: reverted-operator-transaction share, v1 matched weeks vs v2 cohorts. Table: revert causes; third-contract activity; settlement-path MEV candidates and their null rate.
8. **Discussion.** What operator-settled books can and cannot guarantee; which integrity monitors are feasible from public logs alone (a live version of the gate); the value and limits of builder attribution for surveillance; data release terms.
9. **Conclusion.** Tape, validation and monitors as reusable artefacts; what changes with cohorts beyond six.

---

## Dependencies, sequencing and gaps

- **A** needs nothing further; draft now, in parallel with collection. Its Methodology section is reused verbatim as the measurement basis of B and C.
- **B** needs cohorts 1–6 (B2 post-period, B3 replication, informed-taker persistence) and **Gamma metadata for v2 markets** (categories and negRisk families for the v2 side of B2/B3) — *needs an unblocked network: an EU VPS*. Without it, the v2 side of B3's band test is limited to families identifiable from the on-chain condition registry.
- **C** needs cohorts 1–6 and two free additions: operator transaction lists for reverts (C3) and, for C2 category splits, the same Gamma metadata as B.
- Order of writing: A (weeks 1–6) → C1 and C3 as cohorts land (they need no metadata) → B once cohort 6 and metadata are in → C2 last, since its confirmatory hypotheses are registered only after cohort 1's exploratory pass.

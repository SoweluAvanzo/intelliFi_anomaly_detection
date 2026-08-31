# Paper outline (main paper) — 2026-08-31

**Working title:** *Fees, migration, and market integrity in a decentralized prediction market: evidence from Polymarket's 2026 transition*

**Target:** finance / fintech journal (Journal of Financial Markets, Journal of Banking & Finance, or Management Science fintech); FC/AFT for the systems companion (Paper C).

**General research question.** How did the 2026 introduction of taker fees, and the subsequent migration to a new exchange architecture, change *who pays* to trade on Polymarket, whether *prices stay internally consistent*, and the *structure of liquidity provision* — and can these be separated from each other with the data the platform exposes?

Decomposed into three sub-questions, one per results section:

- **SQ1 (Results 1) — Incidence.** What fee is actually levied, who bears it, and is it regressive across trader size, price, and vintage?
- **SQ2 (Results 2) — Price discipline.** Do fees loosen the no-arbitrage constraint that keeps multi-outcome prices consistent, and do they change wash-like and informed taker behaviour?
- **SQ3 (Results 3) — Liquidity provision and the migration.** Did fees, and then the migration, change maker concentration, order size, and market quality — and which changes are the fee versus the platform change?

---

## 1. Introduction
- Prediction markets are the first fully-transparent exchange type to introduce trading fees on a live, on-chain book; the fee scales with p(1−p) and has no maker leg — a design with no equity-market analogue.
- Two regime changes in four months (category-staggered taker fees Jan→Apr 2026; a full exchange migration on 28 Apr) create a two-step natural experiment on a market where **every order, fill, and settlement is observable on-chain**.
- Contributions: (i) the first measurement of fee **incidence** on a prediction market; (ii) the first evidence that fees **loosen cross-market price consistency** (the negRisk no-arbitrage band), with a magnitude; (iii) well-identified **nulls** — fees do not degrade liquidity provision or raise wash trading — separated from a large **migration** structural shock; (iv) the first complete **v2 on-chain tape**, validated and released.
- Headline: fees are regressive on entrants and long-shot takers, widen the no-arbitrage band by ~3–4 pp, and are otherwise integrity-neutral; the big structural changes are the migration, not the fee.

## 2. Institutional background
*(written for a reader new to Polymarket)*
- What Polymarket is; outcome tokens (Conditional Token Framework: mint/merge, YES/NO per market).
- The CLOB: an **off-chain** limit order book with **on-chain settlement** — the `OrderFilled` event is the atomic record; maker vs taker; the operator submits matched trades.
- negRisk (multi-candidate) markets: one family, many YES tokens, Σ YES prices ≈ 1 by no-arbitrage.
- The fee rollout: category-staggered, attaches at market creation; fee = 0.10 · shares · min(p, 1−p); geopolitics/world exempt.
- The 28 Apr 2026 migration: new exchange contracts, pUSD collateral, per-market maker rebates, order-flow "builder" attribution, self-cross prevention.
- UMA resolution; the three close timestamps and why they differ.

## 3. Related work
- Make/take fee theory and evidence (Colliard & Foucault 2012; Malinova & Park 2015; Battalio, Corwin & Jennings 2016; Foucault, Kadan & Kandel 2013) — never tested on a prediction market.
- Transaction taxes (Colliard & Hoffmann 2017; Jones & Seguin 1997).
- Combinatorial/no-arbitrage structure in prediction markets (Saguillo et al. 2025; the negRisk gadget).
- Wash-trading measurement in crypto and on Polymarket (Cong et al. 2023; Victor & Weintraud 2021; Sirolly, Ma, Kanoria & Sethi 2025; Dubach 2026); informed trading on Polymarket (Gómez-Cram et al. 2026; Mitts & Ofir 2026); complete-data microstructure (arXiv 2604.24366, 2603.03136, 2606.04217).
- Staggered DiD and equivalence testing (Callaway & Sant'Anna 2021; Goodman-Bacon 2021; TOST / Lakens 2017).
- **Position:** first causal-style evidence on fees in a prediction market; first evidence on fee effects on cross-market price consistency; first complete v2 tape.

## 4. Data and methodology
*(the section the collaborator needs most — see the companion brief for the pedagogical long form)*
- **Two samples.** Sample A: the complete v1 tape (public CC-BY archive, validated row-for-row against our independent on-chain reconstruction), used to *explore* and derive predictions. Sample B: the v2 tape, reconstructed by us from Polygon logs, used to *confirm* the pre-registered predictions. Explore/confirm protocol; pre-registration hash recorded before any Sample B statistic.
- **The tape.** One row per on-chain `OrderFilled`; how maker/taker, price, fee, and token id are decoded; validation invariants (conservation per transaction, re-fetch identity, taker-order count = OrdersMatched); the pre-registered completeness gate.
- **Market metadata.** The complete market universe from the CLOB cursor API (2.87 M conditions); why Gamma enumeration is lossy; category from CLOB `tags`; negRisk families from `neg_risk_market_id`; the join to the tape by token id (100 % coverage on cohort 1).
- **Class scheme.** The common 8-class taxonomy; how a market's tags map to a class; fee status per class.
- **Estimators.** TOST equivalence (for "unchanged" claims); staggered/two-step DiD with a fee-free control (geopolitics); class-clustered SEs and wild-cluster bootstrap when the number of clusters is small; Holm across the primary hypotheses.
- **Assumptions and threats**, stated plainly: fee formula; class assignment; **the migration confound** (v2 vs v1-April conflates fee with migration — the two-step design and the within-v2 cohort trend address it); market-vintage confound; seasonality/event mix.

## 5. Results 1 — Incidence (SQ1)
- Fee-rule verification; effective rate by trader-size decile × price band (regressive: 3.0 % small long-shot → 1.15 % large in cohort 1); incidence by vintage (entrants 5.7× via exposure); on-chain fee-receiver accounting (v2).

## 6. Results 2 — Price discipline (SQ2)  ← headline
- **negRisk no-arbitrage band:** A: median |S−1| 0.012 (fee-free) → 0.031 (fee), +3.4–4.2 pp; **B cohort 1: fee-family median 0.020, inside the predicted (0.012, 0.031] band — the widening replicates.**
- **Wash-like activity:** self-matching structurally 0 (both regimes); round trips small and not systematically higher under fees.
- **Informed taker behaviour** (RQ7, as cohorts allow): skilled-minority share stable/lower under fees.

## 7. Results 3 — Liquidity provision and the migration (SQ3)
- Fees: maker HHI, top-5 share, order size — **null under fees** once the migration is netted out (DiD, within-B control).
- Migration: the **large** structural shock — maker concentration and order size shifted platform-wide (order size −2.7 log points across all classes including the fee-free control); this is the natural-experiment result.
- Cohort trend (cohorts 2–6) separates fee from migration cleanly within v2.

## 8. Discussion
- Fees as a manipulation-resilience parameter (a wider band makes it cheaper to move a candidate's price unnoticed) — with a measured magnitude.
- Why volume-based wash metrics mislead; the value of a well-identified null.
- The migration as a market-design experiment; external validity (Kalshi, on-chain exchanges).
- Limits: bundled migration treatment; ≤ 6 cohorts; no order-book depth in the on-chain tape (spread is a proxy).

## 9. Conclusion
- Who pays, what did not change, what loosened, and what the migration moved; policy implication for fee design in prediction markets; the released tape and reproducible pipeline.

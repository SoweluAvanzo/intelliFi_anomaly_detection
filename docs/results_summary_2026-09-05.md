# Results summary and research-question coverage — 2026-09-05

What the study establishes, whether the methodology and implementation actually answer
the questions it set out to answer, and what it does not deliver. All numbers below are
the post-audit corrected figures (`docs/audit_2026-09-05.md`); every one traces to a
source JSON or doc named inline.

---

## 1. Major results

### 1.1 Takers lose to makers — in both market eras
- **v1 archive (2022-11 → 2026-04, ~fee-free), whole platform:** the taker side loses
  **−$86.07M** net to makers over 838,385 resolved markets and 2.59M taker wallets;
  **67% of wallets are net-negative** (854,262 winners vs 1,731,905 losers). Source:
  `platform_wide.json`, `scripts/27`. (Concentration of the winnings is Result 1.2.)
- **v2 tape (2026-04 → 2026-08, fee era), whole platform:** takers are ≈**break-even on
  the spread** (size-weighted calibration gap **+0.0007 ≈ 0**, gross PnL +$20.0M) but pay a
  **~1.17% taker fee** ($149.5M on $12.8B notional), so **net PnL is −$129.5M** —
  net-negative every month; **64% of wallets net-negative** (373,294 vs 670,064).
  Source: `v2_platform.json`, `scripts/28`.
- **Combined reading:** takers lose in **both** eras. v1 to the spread; v2 ≈flat on the
  spread but losing to the fee the platform introduced. There is **no v1→v2 reversal** — an
  earlier "+$21M v2 takers win" figure was an artifact of one-sided chunk-overlap inflation
  and an omitted fee, both corrected (`audit_2026-09-05.md §1,§7,§8`).

### 1.2 Winnings are hyper-concentrated — on both sides of the book
Realised winnings are captured by a tiny minority, and this holds for takers **and** makers
alike (`concentration.json`, `scripts/30`):
- **Takers.** Among 854,262 net winners, the **Gini of positive PnL is 0.954**; the **top 1%
  of winners (8,543 wallets) capture 69.7%** of all taker winnings, the top 0.1% capture 41.5%,
  the top 100 wallets alone 20.1% — and just **2.08% of all taker wallets capture 90%** of the
  winnings.
- **Makers.** The maker side wins **+$86.07M** in aggregate (the mirror of takers' loss), yet
  **more than half of individual maker wallets still lose** (637,311 losers vs 572,312 winners),
  and maker winnings are equally concentrated (**Gini 0.946**; top 1% of maker winners take
  69.3%). Caveat: a small number of the top maker "wallets" may be operator/relayer addresses —
  worth screening before publication.
- **Universal across categories** — per-category taker Gini runs **0.94–0.98** (highest in
  Politics/Trump/Soccer/NBA/Ethereum ~0.975–0.978; lowest in hourly "Up or Down" 0.937).

Read with §1.3 (no certifiable skill), this is the study's sharpest tension: **a hyper-concentrated
winner distribution with no demonstrable skilled elite behind it** — consistent with scale,
variance, and survivorship rather than edge.

### 1.3 No statistically certifiable skilled population
Of 14,948 archive wallets with enough resolved positions, the number of net winners is a
**deficit** against the "win at the rate you paid for" null — **123 observed vs 257
expected**. The extreme upper tail beats the activity-preserving null only trivially
(+0.007, p=0.001). **No skilled cohort can be certified from public data.**
Source: `skilled_population.json`, `scripts/23`.

### 1.4 Markets are efficient well before close
The median market already prices the eventual winner at **0.97 a month before close** and
**0.99 a week before**. The exceptions are genuine surprises — the US-strikes-Iran market
went **0.06 (24h before) → 1.00 (1h before)** — not slow leakage.
Source: `efficiency.json`, `scripts/25`.

### 1.5 Fees are regressive, near-universal, and fall hardest on entrants
Effective fee rate falls monotonically from **2.99% of notional for the smallest taker
orders to 1.15% for the largest**; **96% of taker orders are fee-paying**; post-rollout
entrants bear **~5.7×** the fee exposure of incumbents. Source: `cross_cohort_results.md`,
`scripts/17`.

### 1.6 No integrity degradation detected under fees
The pre-registered confirmatory tests (Sample B, v2) are all null:
- **H1c self-matching = 0** of 84.3M fills — clean structural pass on the frozen window.
- **H1a wash round-trips** (frozen window): mean **+1.21pp** vs A-April, TOST p=0.61 — not
  confirmed unchanged, but the elevation is entirely in **crypto and politics** (the window
  is the June US-Iran event fortnight); mechanically inconsistent with a fee cause (fees
  deter round-trips). Read as event-churn, not integrity failure.
- **H3 provider structure**: point differences small (HHI +12%, top-5 +7%, spread ~0.2¢)
  but the equivalence TOST is underpowered (p 0.10–0.38) — stable but not formally certified.
- **H4 taker order size**: inconclusive under **both** control definitions (registered
  never-treated mean β=−0.56 p=0.14; single-control mean −0.48 p=0.21) — robust to the choice.
- **Holm across the available tests rejects nothing.** Source: `confirmatory_verdict.md`,
  `confirmatory_h1_h4.json`, `scripts/22`.

### 1.7 One suggestive but uncertified signal: negRisk band widening under fees
On v1, the negRisk no-arbitrage deviation |ΣYES−1| widens from 0.012 (fee-free) to 0.031
(fee) — a solid Sample-A result. On v2 cohort 1 the fee families sit at 0.020, directionally
consistent, but the within-v2 fee>fee-free ordering **fails** (control is 818 family-hours)
and the **confirmatory H2 is still pending**. Treat as a directional single-cohort signal,
not a certified replication. Source: `cohort1_2026-08-31.md`, `class_contingency_h2.json`.

### 1.8 No coordinated-insider signature; a thin geopolitics tail flagged for triage
The insider-timing event study finds broad public speculation, **not** a ring: positioning
is diffuse (3,440 / 2,138 wallets), and **no wallet front-ran both** US-Iran events. The
largest cheap-entry positioner made +$623k (784k shares at $0.21). This is investigative
**triage, not classification** — trade data alone cannot separate informed trading from
public-escalation speculation. Source: `event_study.json`, `scripts/26`.

---

## 2. Research-question coverage

Legend: **ANSWERED** clean · **PARTIAL** answered with a real limit · **EXPLORATORY**
descriptive only · **NOT ADDRESSED** no implementation.

| Research question | Status | Result | Binding gap |
|---|---|---|---|
| Who wins/loses, on which markets (Q1) | ANSWERED | takers −$86M; makers win; Gini 0.954 | survivorship; taker side |
| Is there a skilled cohort (Q2) | ANSWERED (null) | 123 vs 257 expected winners | population-level, not per-wallet |
| Market efficiency over time (Q4) | ANSWERED | winner priced 0.97 a month out | corpus-scoped (100 markets) |
| Fee incidence / regressivity (RQ4/H5) | ANSWERED | 2.99%→1.15%, regressive | v2-only, descriptive |
| Wash activity under fees (RQ2/H1) | PARTIAL | H1c=0 clean; H1a +1.2pp benign; H1b pending | taker tail; H1b unshipped |
| Do big accounts win longshots (Q3) | PARTIAL | +0.47pp Q4−Q1, absolute edge ~0 | endogenous size proxy |
| Market quality under fees (RQ3/H3,H4) | PARTIAL | H3 underpowered, H4 inconclusive | 7–12 class obs; cross-era confound |
| Informed-trading persistence (RQ7) | PARTIAL | takers lose net in both eras | platform calibration only; skill test not re-run on v2 |
| negRisk band under fees (RQ1/H2) | EXPLORATORY | directional (0.020), not certified | confirmatory H2 pending; thin control |
| Order-flow attribution by channel (RQ5) | EXPLORATORY | 1,169–1,446 builders, HHI ~0.8 | no price-impact-by-channel |
| Insider timing / classification (Gap 1, Q5) | PARTIAL/EXPLORATORY | triage flags, no ring | no classifier, no labels, needs news timeline |
| Copy-trading & herding (Gap 3) | PARTIAL (null) | no detectable coordination | taker tail; no occurrence rate |
| MEV extraction (Gap 8) | NOT ADDRESSED | — | no implementation |
| Stepwise replay engine (Gap 10) | NOT ADDRESSED | — | no implementation |
| Composite suspicion score (spec §6/§20) | NOT ADDRESSED | — | sub-scores exist, never combined |
| Arbitrage detector; UMA dispute labels; live SPRT alerts | NOT ADDRESSED | — | Phases 2/3/4 not shipped |
| What public data can/can't reveal (RQ8) | ANSWERED | the honest spine of the study | — |

---

## 3. Does the methodology and implementation answer the questions?

**Yes for the questions it actually adjudicates; no for the spec's stated end-product.**

- **Sound where it counts.** The economic conventions (taker = aggressor, own direction;
  identical PnL/calibration formula across v1 and v2) are proven, not assumed
  (`audit_2026-09-05.md §1`). The v2 winner-linkage registry (2,108,903 resolved conditions)
  is verified end-to-end (`ctf_v2_verify.json`, §5). Every prose number matches its source
  JSON. Nulls are reported honestly and carry their scope caveats in-band. The dominant
  correction this audit forced — the v2 net-of-fee number — is now reproducible from
  `scripts/28`.
- **The study is a measurement study, not a detector.** It answers "what can public
  Polymarket data tell you about manipulation, and how do fees change the market" — and the
  answer is a well-supported, mostly-null picture: an efficient, maker-favoured market with
  no certifiable skilled cohort, no coordinated-insider ring, and fees that are regressive
  and integrity-neutral so far.
- **It does not deliver the spec's product.** The composite `suspicion_score` (the spec's
  headline object) and three of four north-star Rahman gaps — MEV (8), stepwise replay (10),
  and insider *classification* (1, delivered only as triage) — are not built. Gap 3
  (copy-trading) has real but null engineering behind it. This is a genuine
  ambition-versus-delivery gap and should be stated as such in any writeup.
- **The confirmatory layer is honestly weak.** It tests fee-regime effects (not the
  manipulation gaps), on 7–12 class-level observations with a v1↔v2 cross-era/venue confound,
  and — as documented in `stage2_preregistration.md §7` Deviation 2 — H1a/H3/H4 were run on
  the full tape rather than the frozen window (a pre-registration design flaw: the 14-day
  window cannot host the weekly-panel hypotheses). H1c is the one clean on-window pass. The
  follow-up re-runs (H1a on the window; H4 under the registered controls) leave every verdict
  unchanged.

## 4. Scope and limits to keep attached to every headline

1. **Stage I wallet statistics are a taker-side tail sample** — `/trades` caps at 4,000
   taker fills/market; ~96% of universe wallets are makers. Wallet-level claims describe the
   taker minority.
2. **Realised-PnL rankings are outcome-dependent (survivorship)** — descriptive, not skill.
3. **v1↔v2 is a cross-era and cross-venue comparison** — normalise per-fill/notional, not raw
   totals; v2 magnitudes are read net of the ~1.17% fee.
4. **The confirmatory layer is underpowered** and rests on a cross-sample confound; read as
   "no integrity problem detected," not "the null is proven."
5. **The north-star manipulation gaps are largely unbuilt** — see §2.

## 5. To close the gaps, if pursued

- Overlay a **news timeline** (spec Stage D) to promote the insider-timing triage toward
  classification, and wire **UMA dispute labels** for clean anomaly ground truth.
- **Re-run the position-level skill test on v2** so RQ7 is answered at the wallet level, not
  only platform calibration.
- **Assemble the composite `suspicion_score`** from the sub-scores that already exist
  (concentration, calibration gap, round-trip ratio, convergence).
- MEV (Gap 8) and the stepwise replay engine (Gap 10) remain greenfield.

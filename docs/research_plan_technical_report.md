# Research Plan — Technical Report

*Taxing liquidity on a decentralized prediction market: incidence, participation response, and who captures the maker subsidy*

Draft technical report laying the foundations for one or more Q1 submissions in DeFi / Information
Systems venues (e.g., *Information Systems Research*, *Journal of Management Information Systems*,
*Decision Support Systems*, *Electronic Commerce Research and Applications*; finance-crossover:
*Journal of Financial Markets*, *Management Science*). All quantitative figures trace to the
project's result artifacts in `docs/*.json`; citation reliability is discussed in §6.

> **Citation-integrity note.** Every claim attributed to prior work below is stated as that work
> actually reports it, per two independent literature reviews conducted for this project. Two
> items could **not** be fully verified against primary text and are flagged explicitly in §4 and
> §6 (the full feature schema of Akey et al.; the absence of a non-academic dashboard reporting an
> on-chain wallet-type population split). These must be re-checked against the live sources before
> submission.

---

## 1. Introduction

### 1.1 State of the art, in brief
Polymarket is the largest **decentralized prediction market** — an on-chain venue where users buy
and sell binary outcome shares that settle to \$1 (if the event occurs) or \$0 (otherwise), so a
share's price is a market-implied probability. Trading runs on a **central limit order book
(CLOB)**: a *maker* posts a resting limit order that provides liquidity, and a *taker* crosses the
spread with a marketable order that consumes it. Settlement, custody, and order matching are
recorded on the Polygon blockchain, so — unlike centralized exchanges — the near-complete trade
history is publicly observable.

A cluster of 2025–2026 studies has established the market's first-order facts:

- **Who wins and loses.** Akey et al. (2026, SSRN 6443103), using the reconciled full history
  (~2.4M users, ~\$67B volume, 2022–2026), find that a small minority captures nearly all gains
  (top 1% of positive-PnL users ≈ 76.5% of profits; ≈69% of users end negative) and that
  **liquidity provision (posting limit/maker orders) is the single strongest predictor of
  finishing profitable** (≈ +9 percentage points per standard-deviation increase in maker-volume
  share).
- **Skill vs. luck.** Gómez-Cram et al. (2026, SSRN 6617059), on ~1.72M accounts, use a
  **sign-randomization test** (repeatedly shuffle each account's buy/sell directions and compare
  actual profit to the resulting null distribution) and conclude that ~3% of accounts are
  persistently skilled, that market-makers plus that skilled minority (<3.5% of accounts) capture
  >30% of all gains, and that "the majority does not produce accuracy; it funds it."
- **Fill-side behavior.** Nechepurenko (2026, arXiv 2605.11640) attempted a behavioral tiering of
  *maker-side* participants on the on-chain fill tape but, in the current version, **retracts the
  tiers** — retaining only a one-cluster null and concluding that **public fill records cannot
  identify market-making** without the order/quote lifecycle (a ~2.3-day sample; no profit, no
  account-type layer).
- **Informed / insider trading.** Mitts & Ofir (2026, SSRN 6426778) build a per-(wallet, market)
  suspicion score for informed trading, using *newly created wallets* as one signal, and flag a
  large set of suspicious positions.
- **Foundations.** The Polymarket-v1 public archive (Qin & Yang, 2026, arXiv 2606.04217) supplies a
  reconciled, ground-truth trade record; Rahman et al. (2025, arXiv 2510.15612) give a systematization
  of knowledge (SoK) for decentralized-prediction-market microstructure and enumerate open research
  gaps (insider timing, coordination, MEV, replay).

### 1.2 The gap
The literature above answers *who profits* and *whether skill exists*. It does **not** address the
economic event that most directly shapes those outcomes going forward: **Polymarket's introduction
of a trading fee.** Specifically, three questions are untouched by all of the work in §1.1:

1. **Incidence and behavior of the fee.** No study measures the fee's *incidence* (who bears it,
   as a share of the value they trade), whether it is *regressive* (falls proportionally more on
   small traders), or how participants change behavior (order size, entry, exit) after it is
   introduced. The financial-economics literature has strong analogues — Umlauf (1993) and Colliard
   & Hoffmann (2017) on securities-transaction taxes, and the SEC tick-size pilot — but none on a
   prediction market, and only Whelan (working paper) models prediction-market fees theoretically.
2. **Who captures the maker subsidy.** Polymarket's fee is levied on takers and (partly) rebated to
   makers. The concurrent papers show *makers win on average* but not **which** makers capture the
   rebate, nor the mechanism. **Adverse selection** — the tendency for a passive liquidity provider
   to be "picked off" by better-informed counterparties (Glosten & Milgrom, 1985) — is the natural
   candidate mechanism and has never been measured on this venue.
3. **Who, structurally, is trading.** Prior work treats wallets as homogeneous users. It never
   resolves each wallet's **on-chain account type** — an externally owned account (EOA, a raw
   private key) versus a smart-contract wallet, and among the latter which *proxy* implementation
   (Polymarket's own factory proxy vs. a Gnosis Safe) — nor crosses that structural layer with a
   discrete behavioral-actor classification and profitability.

### 1.3 Why this matters for Polymarket (and DePMs broadly)
A prediction market is only socially useful if its prices aggregate information — which requires
participation, and especially participation by the small, price-taking "crowd" whose flow the
informed minority trades against. A fee that is **regressive** and that **transfers value from the
retail crowd to a professional market-making elite** could erode exactly the participation that
makes prices informative, while concentrating rents. Whether that is happening — and who ends up
bearing versus capturing the fee — is a first-order market-design and welfare question for
Polymarket specifically and for the design of decentralized prediction markets generally. Because
the entire ledger is on-chain, it is also a rare setting where these distributional questions can
be answered on the *near-complete population* rather than a sample.

### 1.4 Research questions
Consistent with the taxonomy in §4 (which we build first and which the gap above is derived from),
we pose one main question, decomposed into four sub-questions selected as the most novel and
publishable given both our results and the state of the art. The main question is framed in the
design-oriented "How to" form standard in Information Systems research; the sub-questions ask "what"
the on-chain record reveals.

**Main RQ — How to** measure, from public on-chain data alone, the incidence and distributional
consequences of introducing a transaction fee on a decentralized prediction market: who pays it,
who captures it, how participants respond, and what structural types of actors sit on each side.

- **Sub-RQ 1 — What** is the incidence of the dynamic fee across order sizes and trader roles, and
  is it regressive?
- **Sub-RQ 2 — What** behavioral and participation responses (order size, new-entrant inflow,
  churn) does the fee's introduction induce?
- **Sub-RQ 3 — What** distinguishes the liquidity providers who capture the maker subsidy from
  those who lose it, and what role does adverse selection play?
- **Sub-RQ 4 — What** is the on-chain account-type and behavioral-actor composition of the trader
  population, and how does account type map onto who pays versus who captures?

### 1.5 How we answer each (preview)
- **Sub-RQ 1.** The staggered per-category fee rollout is used as a natural experiment; fee
  incidence is computed per taker order and per order-size decile. Result: the fee is **steeply
  regressive** — small orders bear multiples of the rate that large orders do (§5.1).
- **Sub-RQ 2.** An event study aligned to each category's own fee-start date measures order size,
  new-wallet inflow, and churn before/after. Result: **median order size roughly halves and
  new-entrant inflow falls sharply** post-fee, with the growth-trend confound explicitly bounded
  (§5.2).
- **Sub-RQ 3.** Maker-side realised PnL is decomposed against a counterparty-informedness proxy.
  Result: **most makers lose; a professional/automated elite that escapes adverse selection
  captures the rebate** (§5.3).
- **Sub-RQ 4.** Every trader is classified by on-chain contract type (from bytecode/storage) and by
  behavioral function (from activity timing), then crossed with PnL. Result: a **~97%-proxy
  population with an onboarding-channel split, in which market-makers and high-frequency automated
  accounts capture the edge** (§5.4) — the economic direction replicates Akey/Gómez-Cram; the
  *account-type axis* is new to this literature.

---

## 2. Methodology

We describe methods in plain terms; technical terms are explained at first use.

**2.1 Realised profit-and-loss (PnL).** For each fill we compute the trader's realised PnL from the
resolved outcome: buying a share of the winning outcome at price *p* for *s* shares yields
(1 − *p*)·*s*; buying the loser yields −*p*·*s* (symmetrically for sells). Summing over a wallet's
fills gives its realised PnL. This is *outcome-dependent* — it uses the eventual result, so it
measures realised (not risk-adjusted or forward-looking) performance and is subject to
**survivorship** (wallets that stopped trading are still counted only where they appear). We report
it as descriptive, never as certified skill.

**2.2 Maker vs. taker and the fee.** On each on-chain `OrderFilled` event we identify the *maker*
(resting-order owner) and *taker* (aggressor). The **fee** (in the platform's 6-decimal USD unit)
is charged once per taker order and recorded on the taker-order record; we therefore read fee
incidence from those records and PnL from the maker-fill records, a distinction established and
validated in the project audit (`docs/audit_2026-09-05.md`).

**2.3 The fee rollout as a natural experiment.** Fees were introduced **staggered by market
category** over early 2026. We *recover* each category's fee-start month from the data (the first
month its effective fee rate jumps above a threshold) and run an **event study** — outcomes aligned
to "months relative to that category's own fee-start," with not-yet-treated categories serving as
the implicit control (a **difference-in-differences**, DiD, design: comparing the change in treated
units to the change in not-yet-treated units).

**2.4 Fee incidence and regressivity.** Incidence = fee paid ÷ notional traded, reported per
order-size decile. "Regressive" means the rate is *higher* for smaller orders.

**2.5 Adverse selection.** A passive maker is *adversely selected* when it disproportionately
trades against counterparties who turn out to be right. We proxy each maker's exposure by the
size-weighted rate at which its taker counterparties' directional bets won, and relate it to the
maker's PnL by Spearman rank correlation (a correlation robust to non-linearity and outliers).

**2.6 Skill test (supporting).** To separate skill from luck we use a **sign-randomization
(permutation) test**: holding each wallet's positions, prices and outcomes fixed, we randomly flip
the buy/sell direction of each *market position* many times; if the wallet's actual PnL is not
better than this null, its side-selection is indistinguishable from chance. We report the fraction
"certifiably skilled" both uncorrected and after **Benjamini–Hochberg** false-discovery-rate
control (which bounds the expected share of false positives among the wallets we call skilled), and
we cross-check with a correlation-immune **split-half persistence** test (does period-1 PnL predict
period-2 PnL). We flag that this test's independence assumption is inflated by cross-market outcome
correlation, so we treat the skilled fraction as an upper bound and the persistence result as the
robust signal.

**2.7 On-chain account-type classification.** For a wallet, we call the Polygon node's `eth_getCode`
to distinguish an **EOA** (externally owned account — no contract code, i.e. a raw key) from a
**smart-contract wallet**. Contract wallets are keyed by their code hash and, for proxies, their
implementation: an **EIP-1167 minimal proxy** embeds its implementation address in the bytecode; a
**Gnosis Safe** proxy stores its singleton in a storage slot. This maps to Polymarket's documented
`signature_type` (0 = EOA, 1 = Polymarket factory proxy for email/"Magic" users, 2 = Gnosis Safe
for browser-wallet users). Classification is computed on an activity- and PnL-stratified sample plus
the full set of top winners, with rate-limit-resilient, cached calls.

**2.8 Behavioral-actor classification.** Independently of the account type, we classify each active
wallet (≥20 fills) by *function* using activity features: **maker-share** (fraction of fills as
maker), **fills per active day** (intensity), and **hour-of-day entropy** (how evenly its trades
spread across the 24 hours — a high value indicates near-24/7 activity consistent with automation).
Heuristic labels: *market-maker* (maker-share ≥ 0.7), *hft_bot* (≥40 fills/active-day and near-24/7),
*active_trader*, *retail_casual*, *one_shot*. **Caveat (per Nechepurenko, 2026):** public fills
without the quote lifecycle cannot *prove* market-making; we therefore present these as heuristic
behavioral classes, not identified market-maker status.

**2.9 Entity / coordination (supporting, negative).** We attempt to collapse wallets to beneficial
owners via a shared-**funding graph** (wallets funded by a common non-hub USDC sender), excluding
high-degree "hub" funders (exchange/relayer/platform contracts), and we build a co-trading graph
(same market, same side, same day). These test for sybil concentration and coordinated syndicates.

**2.10 Memory-safe, reproducible computation.** All population-scale aggregations are computed with
DuckDB over the parquet store using wallet-hash / block-range **bucketing** (each aggregation
processes a bounded fraction of the data with on-disk spill), so the full ~1.5-billion-row scans run
within a fixed memory budget. Every figure is written to a versioned JSON artifact.

---

## 3. Data

**3.1 Two eras, near-complete.** We use two independent, near-complete on-chain records:

- **v1 archive** (Qin & Yang, 2026, arXiv 2606.04217; CC-BY): the reconciled Polymarket history,
  **~746 million maker-fill records** across ~851k markets and ~2.6 million wallets, Nov 2022 – Apr
  2026, with ground-truth aggressor direction, prices, per-fill fee, category, and resolved outcome.
  This is the *fee-free-to-fee-introduction* era (fees phased in during early 2026).
- **v2 on-chain tape**: our own extraction of the `OrderFilled` / `OrdersMatched` / `FeeCharged`
  events of the two v2 exchange contracts on Polygon, **~715 million raw / ~697 million deduplicated
  fills**, Apr–Aug 2026 — the *mature-fee* era. Winner outcomes come from a verified on-chain
  conditional-tokens **resolution registry** (2,108,903 resolved conditions; token→winner derivation
  validated for both standard USDC-collateral and negRisk wrapped-collateral markets).

**3.2 Coverage and comparability.** Both eras cover essentially the whole population, matching the
coverage of the concurrent full-population studies (Akey ≈2.4M users; Gómez-Cram ≈1.72M). The
differentiator of this work is therefore **not** data coverage but the **fee lens and the actor/
account-type classification applied to that population**.

**3.3 Known data caveats (carried into every result).**
- **Taker-side tail (v1 feed only).** Some legacy per-wallet statistics derive from a taker-side
  4,000-fill API tail; all population results here instead use the complete archive/tape, removing
  that bias. The earlier "no skilled cohort" finding was an artifact of that tail and is corrected.
- **Chunk overlap (v2).** The resumable crawl can duplicate a fill across overlapping files; all v2
  aggregates deduplicate on (tx-hash, event-index). Undeduplicated PnL was ~6–8% inflated; corrected.
- **Fee location.** The taker fee lives on `is_taker_order = TRUE` records, not the maker-fill rows;
  net-of-fee PnL uses the former (audit §1, §8).
- **Survivorship / outcome-dependence** (§2.1) applies throughout; results are descriptive.
- **Fees vs. eras.** v1 is ~fee-free (gross ≈ net); v2 carries a ~1.17% effective taker fee, so
  cross-era PnL comparisons use v2 **net** of fees.

---

## 4. State-of-the-art taxonomy

We first map the recent literature against the analytical dimensions this work touches, then (§4.3)
state the gap that the RQs in §1.4 are derived from. The point of the table is to show, dimension by
dimension, exactly what has and has not been done, so the gap is demonstrated rather than asserted.

### 4.1 Coverage matrix

| Work (year, id) | Population-scale | Who-wins / concentration | Skill test | Maker vs. taker | **Fee incidence / behavior** | **Maker-subsidy capture / adverse selection** | **On-chain account TYPE** | **Behavioral-actor taxonomy** |
|---|---|---|---|---|---|---|---|---|
| Akey et al. (2026, SSRN 6443103) | ✔ full | ✔ (top-1% ≈76.5%) | mixture model | ✔ maker-share = top predictor (continuous) | ✗ | partial (maker-share→profit, no AS mechanism) | ✗ | ✗ (continuous features, no discrete classes) |
| Gómez-Cram et al. (2026, SSRN 6617059) | ✔ full | ✔ | ✔ sign-randomization (~3% skilled) | ✔ MMs separated functionally | ✗ | partial (MMs+skilled capture >30%) | ✗ | partial (MM vs skilled, skill-based) |
| Nechepurenko (2026, arXiv 2605.11640) | ✗ (~2.3-day) | ✗ | ✗ | maker-side only | ✗ | ✗ | ✗ | **attempted, then retracted** (fills can't identify MM) |
| Mitts & Ofir (2026, SSRN 6426778) | large | ✗ | ✗ (informed-trading score) | ✗ | ✗ | ✗ | wallet *provenance* (new wallets), not TYPE | ✗ |
| Whelan (working paper) | theory | ✗ | ✗ | ✔ maker/taker economics | **✔ theory only** (no on-chain incidence) | partial (theory) | ✗ | ✗ |
| Qin & Yang (2026, arXiv 2606.04217) | ✔ (dataset) | ✗ | ✗ | ✔ (aggressor direction) | ✗ | ✗ | ✗ | ✗ |
| Rahman et al. (2025, arXiv 2510.15612) | SoK | — | — | — | lists as open | lists as open | ✗ | ✗ |
| **This work** | ✔ full (both eras) | ✔ (replicates) | ✔ (reconciles) | ✔ | **✔ empirical, staggered DiD** | **✔ AS mechanism, −0.58; who captures** | **✔ EOA/Safe/proxy/custom** | **✔ MM/HFT/active/retail (heuristic)** |

(✔ = addressed; partial = touched but not the focus; ✗ = not addressed.)

### 4.2 What each did and did not do
- The full-population papers (Akey; Gómez-Cram) **own** who-wins, concentration, skill, and the
  *maker-advantage direction*; they do **not** study the fee, the adverse-selection mechanism, the
  on-chain account type, or a discrete behavioral-actor taxonomy.
- Nechepurenko is the **only** prior fill-side behavioral attempt and it **disclaims** its own tiers
  on identifiability grounds — a direct methodological warning we adopt, and a gap we partly fill by
  adding profit and the whole population (while conceding the same identification limit for MM/HFT).
- Whelan supplies the **theoretical** fee framing but no on-chain incidence.
- Mitts & Ofir use wallet *provenance* (age) for insider detection — adjacent to, but not, an
  account-*type* taxonomy.

### 4.3 The gap the RQs address (derived from §4.1–4.2)
Two columns of the matrix are **empty across the entire literature**: *fee incidence / behavior*
and *maker-subsidy capture / adverse selection*; a third, *on-chain account type*, is empty as a
research taxonomy (it exists only as documented product infrastructure — Polymarket's
`signature_type`). These three empty columns are precisely Sub-RQs 1–2 (fee), 3 (subsidy/adverse
selection), and 4 (account type). Conversely, the *who-wins / concentration / skill / maker-vs-taker*
columns are **filled** — so we treat those results (§5 and the skill/concentration artifacts) as a
**replication backdrop**, cited to Akey and Gómez-Cram, never as our contribution. This is why the
lead contribution is the fee experiment and the maker-subsidy mechanism, with the account-type axis
as the novel supporting layer. **Verification debt (must close before "first-to" claims):** confirm
Akey's full ~87-feature schema contains no hidden account-type column, and confirm no public Dune
dashboard already reports the proxy/Safe/EOA population split.

---

## 5. Results

Figures are the post-audit corrected values from the project artifacts (`docs/*.json`).

### 5.1 A steeply regressive fee: the smallest orders bear the highest rates
Reading incidence per taker-order-size decile in the mature (v2) regime, the effective fee
**declines from ~2.7–3.2% of notional on the smallest orders to ~1.0% on the largest**
(`fee_behavioral.json`) — a broadly declining gradient (deciles 1–4 sit at 2.7–3.2%, decile 10 at
1.0%), not strictly monotone through the middle deciles. The archive rollout's per-order incidence
shows the same steep decline, from an implausible **~514%** on the smallest sub-dollar orders (a
fixed-minimum-fee artifact on dust — we read the *gradient*, never these levels) down to **~8.8%**
on the largest. In the staggered rollout, each category's effective fee jumps from **≈0% pre-start
to ~3.3% at its fee-start month, ramping to ~12%** as adoption completes (`fee_rollout_did.json`);
over the mature-fee window (Apr–Aug 2026) the platform collected **≈\$149.5M in taker fees**
(`v2_platform.json`). The fee is thus real, sharp at introduction, and **regressive** — it taxes
small, price-taking flow proportionally hardest. *(Sub-RQ 1.)*

### 5.2 The fee shrinks orders and slows new entry
Aligned to each category's own fee-start (event study, `fee_rollout_did.json`), **median taker order
size falls from ~\$6.9 (pre) to ~\$2.9 (three months post)** — orders shrink by more than half — and
**new-wallet inflow drops from ~317k in the fee-start month to ~89k three months later.** The
small-order share of activity rises rather than falls, consistent with larger directional orders
retreating faster than small ones. We are explicit that the new-entrant decline is **confounded with
the platform's own growth/adoption S-curve**; the event-study alignment to each category's own start
(with not-yet-treated categories as controls) partially absorbs this, but a clean elasticity would
need a placebo/synthetic-control robustness check, which we flag as required. The defensible,
composition-level reading is that **the fee is associated with smaller orders and a marked slowdown
in new-participant inflow** — the participation channel that matters most for price informativeness.
*(Sub-RQ 2.)*

### 5.3 The fee is a transfer to a professional market-making elite that escapes adverse selection
On the maker side of the archive, **637,314 of 1,214,275 maker wallets (52.5%) are net-negative**
(`maker_economics.json`) — just over half of all liquidity providers *lose* — and positive maker
PnL is hyper-concentrated (Gini ≈ 0.95; the top 1% of winning makers take ~69%). Yet makers as a
class net **+\$86.0M**, the exact mirror of the takers' −\$86.1M. The split is driven by **adverse
selection**: across makers, the size-weighted rate at which their taker counterparties' bets won is
**strongly negatively correlated with maker PnL (Spearman ≈ −0.58, p≈0)**. Small/amateur makers
(bottom volume deciles) face counterparties who win **~55–56%** of the time and lose on average; the
**top-volume decile faces winning counterparties only ~43% of the time, earns ~+\$1,061 mean, and
captures +\$128.8M in aggregate** — more than the entire net maker profit, while the middle-volume
deciles lose. Size-weighted across *all* makers the counterparty win-rate is 0.43 (<0.5): weighted
by the volume that matters, the professional elite escapes adverse selection and the amateurs absorb
it. Combined with §5.1–5.2 this frames the fee as a **regressive transfer** — small directional
takers pay it; it is rebated to makers but captured by the professional, adverse-selection-avoiding
minority, not the amateur LPs. The *direction* (liquidity provision captures the edge) replicates
Akey and Gómez-Cram; the **adverse-selection mechanism and the within-maker heterogeneity are the new
elements.** *(Sub-RQ 3.)*

### 5.4 Who trades: an on-chain account map and the actors who capture the edge
**Account type.** Resolving on-chain contract types on an activity- and PnL-stratified classified
sample (n≈27,111) shows the population is **~97% smart-contract proxy wallets**, split by onboarding
channel: **~74.5% Gnosis Safe (browser-wallet users, `signature_type` 2), ~21% Polymarket factory
proxy (email/"Magic" users, `signature_type` 1), ~3.3% EOA**, and a ~1% tail of minor-variant
contracts (`account_types.json`). Winners are almost exclusively the two dominant standard proxy
types; the minor-variant contracts are low-activity one-offs, and we do **not** claim they are or
are not bots. Mean realised PnL is highest for the **email/Magic proxy (~\$65k)** — but this is
driven by a few extreme winners: the **median account of every type is a net loser (−\$1 to −\$12)**,
so account type by itself does *not* separate winners from losers. It is an
onboarding-channel/infrastructure axis, not a skill axis.

**Behavioral actors.** Classifying active wallets by function (`actor_taxonomy.json`, 1.52M wallets):

| actor type | n | maker-share | fills/day | 24-7 (entropy frac) | mean PnL | win-rate |
|---|--:|--:|--:|--:|--:|--:|
| market_maker | 84,120 | 0.84 | 16 | 0.72 | **+\$1,991** | 47% |
| hft_bot (near-24/7) | 50,441 | 0.22 | 109 | 0.96 | **+\$1,152** | 29% |
| active_trader (directional) | 274,031 | 0.13 | 32 | 0.63 | −\$312 | 21% |
| retail_casual | 1,086,388 | 0.18 | 4 | 0.67 | −\$89 | 32% |
| one_shot | 23,961 | 0.11 | 13 | 0.31 | −\$346 | 23% |

As a class, **market-makers (+\$167.5M aggregate) and high-frequency near-24/7 automated accounts
(+\$58.1M)** are the net winners — capturing the edge via **spread capture**, not forecasting —
while directional and retail classes lose in aggregate (−\$85.4M active, −\$96.5M retail). Within
*every* class the median account is a small net loser, so the class-level edge sits in each class's
right tail (mean ≫ median). This is precisely the population that captures the maker subsidy in §5.3. Two honesty
points: (i) this economic *direction* replicates the concurrent papers; (ii) per Nechepurenko (2026),
fills alone cannot *prove* market-making, so these are heuristic behavioral classes. The **new-to-PM
contribution is the on-chain account-type axis and its crossing with function and PnL** — most EOAs
behave as retail (~62%), with a minority (~6% of the HFT class, ~1.8× over-represented) automated, so
account type maps to *onboarding channel*, not cleanly to bot-vs-human. *(Sub-RQ 4.)*

### 5.5 Supporting / replicated backdrop (cited, not claimed as novel)
For completeness and to situate §5.1–5.4: takers lose **−\$86.1M** in the ~fee-free v1 era; in the
fee era they are **gross-positive (+\$20.0M) but −\$129.5M net** — the ~1.17% taker fee (**≈\$149.5M**)
is the entire loss channel and then some, so the loss mechanism *shifts* from adverse selection (v1)
to the fee (v2). Winnings are hyper-concentrated (Gini ≈ 0.95; the top 1% of winning wallets take
~70% of all winnings) — **replicating Akey**. On skill, a full-population sign-randomization test
yields **~4.3% certifiably skilled after Benjamini–Hochberg correction** (7.1% uncorrected) — the
same order as Gómez-Cram's ~3%, and an **upper bound** given cross-market outcome correlation; the
correlation-immune signal is **weak-but-real persistence** (split-half Spearman ≈ 0.15, p≈0;
period-1 top-quintile → +\$1,174 mean in period 2 vs −\$134 for the bottom). Skill is expressed as
**breadth** — the skilled tier trades far more markets (mean ~314 vs ~113 neutral) at a much higher
market-level win-rate (~85%), not one lucky bet; a stricter position-level test in the informative
price band is by contrast **null** (observed skilled winners 123 < chance 257), reinforcing the
upper-bound reading. Coordination is a **negative** result: funding-graph entity collapse is small
(**~4.3%** of top-20k-winner diversity is sybil), dominated by a single 377-wallet cluster (+\$48M)
with the remainder singletons — **no broad coordinated syndicate**, consistent with the project's
prior coordination null. These support, but are not, the contribution.

---

## 6. Limitations, integrity, and next steps

- **Citations.** All prior-work claims are stated as the sources report them, per two literature
  reviews. **Not fully verified (must close before submission):** (i) the complete ~87-feature schema
  of Akey et al. (SSRN PDF returned 403) — a hidden account-type column cannot be 100% excluded; (ii)
  the absence of a non-academic dashboard reporting an on-chain wallet-type population split. 2026
  preprints (Akey, Gómez-Cram, Nechepurenko, Mitts & Ofir, Qin & Yang) should be re-pulled at their
  current versions (Nechepurenko in particular has a superseded "tiers" v1 and a later "identification
  limits" version — cite the version relied upon).
- **Causal caveats.** The fee event study is confounded with platform growth and cross-category
  substitution; lead the causal claims with *incidence* and *composition* (robust) and treat the
  participation-elasticity magnitude as provisional pending placebo/synthetic-control checks.
- **Identification limit.** Market-maker/HFT labels are heuristic behavioral classes; public fills do
  not carry the quote lifecycle (Nechepurenko, 2026). The account-type axis must be shown to add signal
  *orthogonal to* the onboarding channel or it reads as descriptive.
- **Descriptive PnL.** Realised, outcome-dependent, survivorship-subject; not risk-adjusted skill.
- **Next analyses to strengthen the lead paper.** (a) A formal DiD with placebo categories and a
  synthetic control for the participation response; (b) a spread/adverse-selection decomposition of
  maker PnL where the order lifecycle is reconstructable; (c) proxy→owner resolution (Gnosis Safe
  `getOwners()` / factory owner) to test entity-level concentration cleanly, which the funding graph
  cannot; (d) net-of-fee incidence by account type to close the fee↔type link.

## References (as verified; see §6 on reliability)
- Akey, P., Grégoire, V., Harvie, ?, Martineau, C. (2026). *Who Wins and Who Loses in Prediction
  Markets? Evidence from Polymarket.* SSRN 6443103 (CEPR DP 21615). Data: HuggingFace
  `vgregoire/polymarket-users`.
- Gómez-Cram, R., Guo, ?, Jensen, ?, Kung, ? (2026). *Prediction Market Accuracy: Crowd Wisdom or
  Informed Minority?* SSRN 6617059.
- Nechepurenko, ? (2026). *Fill-Side Behavioral Concentration on Polymarket: Identification Limits
  under Record-Level Attribution.* arXiv 2605.11640 (SSRN 6751284).
- Mitts, J., Ofir, ? (2026). *From Iran to Taylor Swift: Informed Trading in Prediction Markets.*
  SSRN 6426778.
- Qin, ?, Yang, ? (2026). *The Polymarket-v1 Database.* arXiv 2606.04217 (CC-BY-4.0).
- Rahman, N., Al-Chami, ?, Clark, J. (2025). *SoK: Market Microstructure for Decentralized Prediction
  Markets.* arXiv 2510.15612.
- Whelan, K. (working paper). *How Do Prediction Market Fees Affect Prices and Participants?* and
  *Makers and Takers: The Economics of the Kalshi Prediction Market.*
- Umlauf, S. R. (1993). *Transaction taxes and the behavior of the Swedish stock market.* Journal of
  Financial Economics 33(2), 227–240.
- Colliard, J.-E., & Hoffmann, P. (2017). *Financial Transaction Taxes, Market Composition, and
  Liquidity.* Journal of Finance 72(6), 2685–2716.
- Glosten, L. R., & Milgrom, P. R. (1985). *Bid, ask and transaction prices in a specialist market
  with heterogeneously informed traders.* Journal of Financial Economics 14(1), 71–100.
- Milionis, J., Moallemi, C. C., Roughgarden, T., & Zhang, A. L. (2022). *Automated Market Making and
  Loss-Versus-Rebalancing.* arXiv 2208.06046.
- Meiklejohn, S., et al. (2013). *A Fistful of Bitcoins: Characterizing Payments Among Men with No
  Names.* ACM IMC.
- Victor, F. (2020). *Address Clustering Heuristics for Ethereum.* Financial Cryptography and Data
  Security.
- Barber, B. M., & Odean, T. (2000). *Trading Is Hazardous to Your Wealth.* Journal of Finance 55(2),
  773–806.

*Author initials marked "?" are unconfirmed and must be completed from the primary sources before
submission.*

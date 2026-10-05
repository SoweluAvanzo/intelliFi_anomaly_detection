# Research Plan — Technical Report

*Taxing liquidity on a decentralized prediction market: who pays the fee and who captures the maker subsidy*

Draft technical report laying the foundations for one or more Q1 submissions in DeFi / Information
Systems venues (e.g., *Information Systems Research*, *Journal of Management Information Systems*,
*Decision Support Systems*, *Electronic Commerce Research and Applications*; finance-crossover:
*Journal of Financial Markets*, *Management Science*).

---

## 1. Introduction

### 1.1 State of the art
Polymarket is the largest decentralized prediction market — an on-chain venue where users buy
and sell binary outcome shares that settle to \$1 (if the event occurs) or \$0 (otherwise), so a
share's price is a market-implied probability. Trading runs on a central limit order book
(CLOB): a *maker* posts a resting limit order that provides liquidity, and a *taker* crosses the
spread with a marketable order that consumes it. Settlement, custody, and order matching are
recorded on the Polygon blockchain, so — unlike centralized exchanges — the near-complete trade
history is publicly observable.

A cluster of 2025–2026 studies has established the market's first-order facts:

- **Who wins and loses.** Akey et al. (2026, SSRN 6443103), using the reconciled full history
  (~2.4M users, ~\$67B volume, 2022–2026), find that a small minority captures nearly all gains
  (top 1% of positive-PnL users ≈ 76.5% of profits; ≈69% of users end negative) and that
  liquidity provision (posting limit/maker orders) is the single strongest predictor of
  finishing profitable (≈ +9 percentage points per standard-deviation increase in maker-volume
  share). Their sample ends on 29 March 2026, the day before Polymarket introduced fees on all
  markets, deliberately stopping there because the fee "materially changes the economics of
  trading" — so their account is the definitive statement of the *pre-fee* distribution and leaves
  the fee-and-rebate era untouched.
- **Skill vs. luck.** Gómez-Cram et al. (2026, SSRN 6617059), on ~1.72M accounts, use a
  sign-randomization test (repeatedly shuffle each account's buy/sell directions and compare
  actual profit to the resulting null distribution) and conclude that ~3% of accounts are
  persistently skilled, that market-makers plus that skilled minority (<3.5% of accounts) capture
  >30% of all gains, and that "the majority does not produce accuracy; it funds it."
- **Fill-side behavior.** Nechepurenko (2026, arXiv 2605.11640) attempted a behavioral tiering of
  *maker-side* participants on the on-chain fill tape but, in the current version, retracts the
  tiers — retaining only a one-cluster null and concluding that public fill records cannot
  identify market-making without the order/quote lifecycle (a ~2.3-day sample; no profit, no
  account-type layer).
- **Informed / insider trading.** Mitts & Ofir (2026, SSRN 6426778) build a per-(wallet, market)
  suspicion score for informed trading, using *newly created wallets* as one signal, and flag a
  large set of suspicious positions.
- **Foundations.** The Polymarket-v1 public archive (Qin & Yang, 2026, arXiv 2606.04217) supplies a
  reconciled, ground-truth trade record; Rahman et al. (2025, arXiv 2510.15612) give a systematization
  of knowledge (SoK) for decentralized-prediction-market microstructure and enumerate open research
  gaps (insider timing, coordination, MEV, replay).

### 1.2 The gap
The literature above answers *who profits* and *whether skill exists* — and it answers them for the
*pre-fee* market, because the definitive who-wins study stops on the eve of the fee. It does not
address the economic event that most directly reshapes those outcomes: Polymarket's introduction of
a trading fee. Two questions about that event are untouched by all of the work in §1.1.

1. **Who bears the fee, and is it regressive.** No study measures the fee's *incidence* — who bears
   it, as a share of the value they trade — or whether it is *regressive*, falling proportionally
   more on small orders. The financial-economics literature has strong analogues — Umlauf (1993) and
   Colliard & Hoffmann (2017) on securities-transaction taxes, and the SEC tick-size pilot — but none
   on a prediction market, and only Whelan (working paper) models prediction-market fees theoretically.
2. **Who captures the maker subsidy, and who structurally are they.** Polymarket's fee is levied on
   takers and partly rebated to makers, so its ultimate beneficiaries are whichever makers keep that
   rebate net of trading losses. The concurrent papers show *makers win on average* but not which
   makers capture the rebate, nor the mechanism. Adverse selection — the tendency for a passive
   liquidity provider to be "picked off" by better-informed counterparties (Glosten & Milgrom, 1985) —
   is the natural candidate mechanism and has never been measured on this venue. Nor does any prior
   work resolve the beneficiary's on-chain account type — an externally owned account versus a
   smart-contract wallet, and among the latter which proxy implementation — which puts a concrete
   structural identity on who ends up capturing the transfer.

A third question — how participants change their behavior after the fee, in order size, entry, and
exit — is of secondary interest here. It is theoretically ambiguous for a cost this small (a fee can
both deter marginal flow and prune noise; Cipriani & Guarino, 2008), the market-quality side of it
is partly addressed by concurrent microstructure work, and the staggered rollout affords too few
treated categories for a well-powered causal estimate. We therefore examine it descriptively, as
market context for the two incidence-and-capture questions above, rather than as a headline claim.

### 1.3 Why this matters for Polymarket (and DePMs broadly)
A prediction market is only socially useful if its prices aggregate information — which requires
participation, and especially participation by the small, price-taking "crowd" whose flow the
informed minority trades against. A fee that is regressive and that transfers value from the
retail crowd to a professional market-making elite could erode exactly the participation that
makes prices informative, while concentrating rents. Whether that is happening — and who ends up
bearing versus capturing the fee — is a first-order market-design and welfare question for
Polymarket specifically and for the design of decentralized prediction markets generally. Because
the entire ledger is on-chain, it is also a rare setting where these distributional questions can
be answered on the *near-complete population* rather than a sample.

### 1.4 Research questions
We pose one main question, decomposed into two sub-questions.

Main RQ — How to measure, from public on-chain data, the incidence and distributional consequences
of introducing a transaction fee on a decentralized prediction market?

Each sub-question isolates one facet of that measurement. For each, we state the question, why it is
worth answering, and the gap in the literature it closes.

Sub-RQ 1 — What is the incidence of the fee across order sizes and trader roles, and is it
regressive?
*Why, and the gap it closes.* Incidence — who actually bears a levy, as a share of the value they
trade — is the first-order welfare question about any transaction cost, and it has never been
measured for a prediction market. The equity-market transaction-tax literature (Umlauf, 1993;
Colliard & Hoffmann, 2017) measures aggregate liquidity and volume effects but not per-trader
incidence, because it lacks the trader-level, whole-population record that an on-chain venue
provides. This answer establishes whether the fee is flat or regressive — the fact the rest builds on.

Sub-RQ 2 — Who captures the maker subsidy the fee funds, through what mechanism, and what is their
structural identity? Specifically, what distinguishes the liquidity providers who keep the rebate
from those who lose it, what role does adverse selection play, and what on-chain account type and
behavioral actor do the beneficiaries correspond to?
*Why, and the gap it closes.* The fee is levied on takers and partly rebated to makers, so its
ultimate beneficiaries are whichever makers keep that rebate net of trading losses. The concurrent
full-population studies (Akey et al., 2026; Gómez-Cram et al., 2026) establish the *pre-fee* picture —
makers win *on average*, and liquidity provision is the strongest predictor of profit — but not
*which* makers keep the fee-funded rebate, nor the mechanism, nor who structurally they are. Adverse
selection — a passive maker being "picked off" by better-informed counterparties (Glosten & Milgrom,
1985) — is the classic candidate mechanism and has never been measured on this venue. And no prior
work resolves the beneficiary's on-chain account type — an externally owned account versus a
smart-contract wallet, and among the latter which proxy implementation — nor crosses that structural
layer with a behavioral classification and profitability. This answer names the beneficiary of the
transfer, explains why, and attaches a concrete structural identity to it.

Together, the two answers compose the main question. Sub-RQ 1 fixes *what* is charged and *on whom* —
the incidence. Sub-RQ 2 follows the money to *who ultimately keeps it*, *why*, and *who they are* —
the mechanism and the distributional consequence, down to a structural identity. Incidence plus
capture-with-identity is precisely what "the incidence and distributional consequences of introducing
the fee, measured from public on-chain data" means, so the two sub-answers are jointly sufficient for
the main RQ. The market's behavioral response to the fee — whether order size and entry fall — is
examined as context in §5.2, not as a third claim, for the reasons given in §1.2.

### 1.5 How we answer each (preview)
- Sub-RQ 1. Fee incidence is computed per taker order and per order-size decile in the mature-fee
  regime, with the staggered per-category rollout corroborating the onset. Result: the fee is
  regressive — the smallest orders bear roughly two to three times the rate of the largest (§5.1).
- Sub-RQ 2. Maker-side realised PnL is decomposed against a counterparty-informedness proxy, and the
  beneficiaries are then given a structural identity: every active wallet is classified by on-chain
  account type (from bytecode and storage) and by behavioral function (from activity timing) and
  crossed with capture. Result: most makers lose, and a professional, largely automated elite that
  escapes adverse selection captures the rebate; account type resolves to an onboarding channel, not
  a skill axis (§5.3–§5.4). The economic direction replicates Akey and Gómez-Cram; the
  adverse-selection mechanism and the account-type identity are new to this literature.

The market's behavioral response to the fee is reported as context, not as a research claim: a
balanced event study holding category composition constant around each category's own fee-start
measures order size and new-wallet inflow, netting out pre-trends, and finds no participation or
volume response attributable to the fee — order size follows a pre-existing downtrend and new entry
does not fall at onset; the earlier "orders halve / entry collapses" figures were panel-composition
artifacts (§5.2).

---

## 2. Methodology

We describe methods in plain terms; technical terms are explained at first use.

**2.1 Realised profit-and-loss (PnL).** For each fill we compute the trader's realised PnL from the
resolved outcome: buying a share of the winning outcome at price *p* for *s* shares yields
(1 − *p*)·*s*; buying the loser yields −*p*·*s* (symmetrically for sells). Summing over a wallet's
fills gives its realised PnL. This is *outcome-dependent* — it uses the eventual result, so it
measures realised (not risk-adjusted or forward-looking) performance and is subject to
survivorship (wallets that stopped trading are still counted only where they appear). We report
it as descriptive, never as certified skill.

**2.2 Maker vs. taker and the fee.** On each on-chain `OrderFilled` event we identify the *maker*
(resting-order owner) and *taker* (aggressor). The fee (in the platform's 6-decimal USD unit)
is charged once per taker order and recorded on the taker-order record; we therefore read fee
incidence from those records and PnL from the maker-fill records.

**2.3 The fee rollout as a natural experiment.** Fees were introduced staggered by market
category over early 2026. We *recover* each category's fee-start month from the data (the first
month its effective fee rate jumps above a threshold) and run an event study — outcomes aligned
to "months relative to that category's own fee-start," with not-yet-treated categories serving as
the implicit control (a difference-in-differences, DiD, design: comparing the change in treated
units to the change in not-yet-treated units).

**2.4 Fee incidence and regressivity.** Incidence = fee paid ÷ notional traded, reported per
order-size decile. "Regressive" means the rate is *higher* for smaller orders.

**2.5 Adverse selection.** A passive maker is *adversely selected* when the price moves against it
right after it fills — informed flow picking it off. We measure this with an identified signed
post-fill *markout*: for each maker fill, the token's forward price minus the fill price, signed by
the maker's side, so a negative markout is adverse selection (Glosten & Harris, 1988; Dubach, 2026).
We report it over horizons from 60 s to one day and by maker-volume decile.

**2.6 Skill test (supporting).** To separate skill from luck we use a sign-randomization
(permutation) test: holding each wallet's positions, prices and outcomes fixed, we randomly flip
the buy/sell direction of each *market position* many times; if the wallet's actual PnL is not
better than this null, its side-selection is indistinguishable from chance. We report the fraction
"certifiably skilled" both uncorrected and after Benjamini–Hochberg false-discovery-rate
control (which bounds the expected share of false positives among the wallets we call skilled), and
we cross-check with a correlation-immune split-half persistence test (does period-1 PnL predict
period-2 PnL). We flag that this test's independence assumption is inflated by cross-market outcome
correlation, so we treat the skilled fraction as an upper bound and the persistence result as the
robust signal.

**2.7 On-chain account-type classification.** For a wallet, we call the Polygon node's `eth_getCode`
to distinguish an EOA (externally owned account — no contract code, i.e. a raw key) from a
smart-contract wallet. Contract wallets are keyed by their code hash and, for proxies, their
implementation: an EIP-1167 minimal proxy embeds its implementation address in the bytecode; a
Gnosis Safe proxy stores its singleton in a storage slot. This maps to Polymarket's documented
`signature_type` (0 = EOA, 1 = Polymarket factory proxy for email/"Magic" users, 2 = Gnosis Safe
for browser-wallet users). Classification is computed on an activity- and PnL-stratified sample plus
the full set of top winners, with rate-limit-resilient, cached calls.

**2.8 Behavioral-actor classification.** Independently of the account type, we classify each active
wallet (≥20 fills) by *function* using activity features: maker-share (fraction of fills as
maker), fills per active day (intensity), and hour-of-day entropy (how evenly its trades
spread across the 24 hours — a high value indicates near-24/7 activity consistent with automation).
Heuristic labels: *market-maker* (maker-share ≥ 0.7), *hft_bot* (≥40 fills/active-day and near-24/7),
*active_trader*, *retail_casual*, *one_shot*. Caveat (per Nechepurenko, 2026): public fills
without the quote lifecycle cannot *prove* market-making; we therefore present these as heuristic
behavioral classes, not identified market-maker status.

**2.9 Entity / coordination (supporting, negative).** We attempt to collapse wallets to beneficial
owners via a shared-funding graph (wallets funded by a common non-hub USDC sender), excluding
high-degree "hub" funders (exchange/relayer/platform contracts), and we build a co-trading graph
(same market, same side, same day). These test for sybil concentration and coordinated syndicates.

**2.10 Memory-safe, reproducible computation.** All population-scale aggregations are computed with
DuckDB over the parquet store using wallet-hash / block-range bucketing (each aggregation
processes a bounded fraction of the data with on-disk spill), so the full ~1.5-billion-row scans run
within a fixed memory budget. Every figure is written to a versioned JSON artifact.

---

## 3. Data

**3.1 Two eras, near-complete.** We use two independent, near-complete on-chain records:

- **v1 archive** (Qin & Yang, 2026, arXiv 2606.04217; CC-BY): the reconciled Polymarket history,
  ~746 million maker-fill records across ~851k markets and ~2.6 million wallets, Nov 2022 – Apr
  2026, with ground-truth aggressor direction, prices, per-fill fee, category, and resolved outcome.
  This is the *fee-free-to-fee-introduction* era (fees phased in during early 2026).
- **v2 on-chain tape**: our own extraction of the `OrderFilled` / `OrdersMatched` / `FeeCharged`
  events of the two v2 exchange contracts on Polygon, ~715 million raw / ~697 million deduplicated
  fills, Apr–Aug 2026 — the *mature-fee* era. Winner outcomes come from a verified on-chain
  conditional-tokens resolution registry (2,108,903 resolved conditions; token→winner derivation
  validated for both standard USDC-collateral and negRisk wrapped-collateral markets).

**3.2 Coverage and comparability.** Both eras cover essentially the whole population, matching the
coverage of the concurrent full-population studies (Akey ≈2.4M users; Gómez-Cram ≈1.72M). The
differentiator of this work is therefore not data coverage but the fee lens and the actor/
account-type classification applied to that population.

**3.3 Known data caveats (carried into every result).**
- **Taker-side tail (v1 feed only).** All population results use the complete archive and tape, not
  the taker-side 4,000-fill API tail, so wallet-level statistics are not subject to that sampling bias.
- **Chunk overlap (v2).** The resumable crawl can duplicate a fill across overlapping files, so all v2
  aggregates deduplicate on (tx-hash, event-index).
- **Fee location.** The taker fee lives on `is_taker_order = TRUE` records, not the maker-fill rows;
  net-of-fee PnL uses the former.
- **Survivorship / outcome-dependence** (§2.1) applies throughout; results are descriptive.
- **Fees vs. eras.** The v1 window is fee-free until the early-2026 rollout (gross ≈ net for its
  2022–2025 bulk); v2 carries a ~1.17% effective taker fee, so cross-era PnL comparisons use v2 net of
  fees.
- **Fee source.** The v1 archive's per-row fee column does not follow the on-chain fee formula, so fee
  levels are taken from the v2 on-chain fee (which matches the documented `feeRate·p·(1−p)·size`); the
  archive-era fee is reconstructed from the documented formula and the per-category rate, and the
  archive's rate field dates the staggered rollout.

---

## 4. State-of-the-art taxonomy

This section maps the recent literature against the analytical dimensions this work touches,
dimension by dimension, so the gap the research questions address is visible directly in the table.

### 4.1 Coverage matrix

| Work (year, id) | Population-scale | Who-wins / concentration | Skill test | Maker vs. taker | Fee incidence / behavior | Maker-subsidy capture / adverse selection | On-chain account TYPE | Behavioral-actor taxonomy |
|---|---|---|---|---|---|---|---|---|
| Akey et al. (2026, SSRN 6443103) | ✔ full | ✔ (top-1% ≈76.5%) | mixture model | ✔ maker-share = top predictor (continuous) | ✗ | partial (maker-share→profit, no AS mechanism) | ✗ | ✗ (continuous features, no discrete classes) |
| Gómez-Cram et al. (2026, SSRN 6617059) | ✔ full | ✔ | ✔ sign-randomization (~3% skilled) | ✔ MMs separated functionally | ✗ | partial (MMs+skilled capture >30%) | ✗ | partial (MM vs skilled, skill-based) |
| Nechepurenko (2026, arXiv 2605.11640) | ✗ (~2.3-day) | ✗ | ✗ | maker-side only | ✗ | ✗ | ✗ | attempted, then retracted (fills can't identify MM) |
| Mitts & Ofir (2026, SSRN 6426778) | large | ✗ | ✗ (informed-trading score) | ✗ | ✗ | ✗ | wallet *provenance* (new wallets), not TYPE | ✗ |
| Whelan (working paper) | theory | ✗ | ✗ | ✔ maker/taker economics | ✔ theory only (no on-chain incidence) | partial (theory) | ✗ | ✗ |
| Qin & Yang (2026, arXiv 2606.04217) | ✔ (dataset) | ✗ | ✗ | ✔ (aggressor direction) | ✗ | ✗ | ✗ | ✗ |
| Rahman et al. (2025, arXiv 2510.15612) | SoK | — | — | — | lists as open | lists as open | ✗ | ✗ |
| This work | ✔ full (both eras) | ✔ (replicates) | ✔ (reconciles) | ✔ | ✔ incidence (empirical); behavior null (context) | ✔ identified markout: makers +, spread capture, no fill-time AS; who captures | ✔ EOA/Safe/proxy/custom | ✔ MM/HFT/active/retail (heuristic) |

(✔ = addressed; partial = touched but not the focus; ✗ = not addressed.)

### 4.2 What each did and did not do
- The full-population papers (Akey; Gómez-Cram) own who-wins, concentration, skill, and the
  *maker-advantage direction*; they do not study the fee, the adverse-selection mechanism, the
  on-chain account type, or a discrete behavioral-actor taxonomy.
- Nechepurenko is the only prior fill-side behavioral attempt and it disclaims its own tiers
  on identifiability grounds — a direct methodological warning we adopt, and a gap we partly fill by
  adding profit and the whole population (while conceding the same identification limit for MM/HFT).
- Whelan supplies the theoretical fee framing but no on-chain incidence.
- Mitts & Ofir use wallet *provenance* (age) for insider detection — adjacent to, but not, an
  account-*type* taxonomy.

### 4.3 The gap the RQs address
Two columns of the matrix are empty across the entire literature: *fee incidence / behavior* and
*maker-subsidy capture / adverse selection*; a third, *on-chain account type*, is empty as a research
taxonomy — it exists only as documented product infrastructure, Polymarket's `signature_type`. The
first empty column is Sub-RQ 1 (the incidence of the fee). The second and third together are Sub-RQ 2
(who captures the fee-funded subsidy and the on-chain account-type identity of the beneficiary). Conversely, the *who-wins / concentration / skill / maker-vs-taker*
columns are filled — and filled specifically for the pre-fee market, since the definitive who-wins
study ends on the eve of the fee — so we treat those results as a replication backdrop, cited to Akey
and Gómez-Cram, never as our contribution. The lead contribution is therefore the fee experiment and
the maker-subsidy mechanism, with the account-type identity as the structural layer within it.

---

## 5. Results

All figures are computed on the full datasets described in §3.

### 5.1 A regressive fee: the smallest orders bear the highest rates
Reading incidence per taker-order-size decile in the mature (v2) regime, the effective fee declines
from ~2.7–3.2% of notional on the smallest orders to ~1.0% on the largest (`fee_behavioral.json`) — a
broadly declining gradient, with deciles 1–4 at 2.7–3.2% and decile 10 at 1.0%, not strictly monotone
through the middle deciles. This is the fee the documented formula implies, and the v2 tape confirms
it to the basis point: the on-chain taker fee equals `feeRate · p · (1−p) · size` with `feeRate ≈ 0.07`
(the median of `fee ÷ [p·(1−p)·size]` over v2 taker orders is 0.0700), so fee-over-notional equals
`feeRate · (1−p)`, is bounded by the headline rate, and falls as larger orders execute at prices
closer to the extremes — the smallest, price-taking orders bear the highest rate. Fewer than 0.2% of
v2 taker orders exceed the ceiling (rounding and wrapped-collateral edges). The taker rate varies by
category — 7% on crypto, 5% on sports, economics, culture, weather and other, 4% on finance, politics,
tech and mentions, and zero on geopolitics — so the gradient is a blend of category rates.
Reconstructed from the documented formula and the per-category rate, the v1-era staggered rollout
reproduces the same regressive gradient across both eras. Over the mature-fee window (Apr–Aug 2026) the
platform collected ≈\$149.5M in taker fees (`v2_platform.json`). The fee is thus real, sharp at
introduction, and regressive — it taxes small, price-taking flow proportionally hardest. *(Sub-RQ 1.)*

### 5.2 Market context: no participation response is identified once pre-trends are removed
A balanced event study — the six market categories present at every month of a [−3, +1] window
around each category's own fee-start, compared at constant composition (`fee_rollout_did.json`,
`event_study_balanced`) — finds no participation response attributable to the fee. Median taker
order size was **already falling before any fee** (pre-fee slope ≈ −\$0.51/month); across the window
the per-category mean runs 5.68 → 5.96 → 4.42 → 3.85 → 3.61, and the decline at fee onset does not
exceed that pre-trend (−\$0.57 from month −1 to 0 against a −\$0.51 trend) and in fact *decelerates*
as the fee ramps up (−\$0.24 from 0 to +1). New-entrant inflow was **rising** pre-fee
(≈ +4,400 wallets per category per month) and does not fall at onset — per category it runs
32,664 (−1) → 46,542 (0) → 37,744 (+1). On the balanced panel the volume/participation response
is therefore **not identified**, consistent with the near-null elasticity expected for a small
transaction cost. What is robust is the fee's sharp onset itself — the effective rate rises from
zero before fee-start to a positive, climbing level as the schedule ramps. The welfare case for the
fee thus rests on its **incidence and distribution**
(§5.1, §5.3–§5.4), not on a participation collapse. *(Market context; see §1.2.)*

### 5.3 The fee is a transfer to high-volume makers, who capture the spread — not by avoiding adverse selection
On the maker side of the archive, 637,314 of 1,214,275 maker wallets (52.5%) are net-negative in
realised PnL (`maker_economics.json`) — just over half of all liquidity providers *lose* — and
positive maker PnL is hyper-concentrated (Gini ≈ 0.95; the top 1% of winning makers take ~69%).
Makers as a class net +\$86.0M, the exact mirror of the takers' −\$86.1M, and the surplus sits in the
top volume decile (~+\$1,061 mean, +\$128.8M aggregate — more than the entire net maker profit), while
the upper-middle (7th–9th) volume deciles carry essentially all the aggregate losses (−\$24.4M,
−\$12.0M, −\$9.9M). Realised maker profit is thus non-monotonic in volume and concentrated in the
largest makers.

The *mechanism* for that edge is spread capture. An identified signed post-fill markout on the mature
(v2) tape — for each maker fill, the token's forward price minus the fill price, signed by the maker's
side, across 42M maker fills — is **positive at every horizon from 60 s to one day** (dollar-weighted
+0.002 to +0.006 per share): makers systematically earn the post-fill move, capturing the spread rather
than being picked off by informed flow. The maker edge is thus not adverse-selection avoidance; across
makers the correlation of volume with markout is ≈ 0, and the only trace of adverse selection is a
transient effect on the smallest makers at the 60-second horizon that reverts within five minutes. The
realised-PnL dispersion among makers is therefore not driven by fill-time picking-off — the execution
component is favourable across the maker population — but by position and inventory selection and the
eventual outcome.

Combined with §5.1–§5.2 this frames the fee as a regressive transfer whose proceeds, together with the
bid-ask spread, flow from price-taking takers to the high-volume makers who capture them. The
fee-funded rebate is allocated by Polymarket's published rule in proportion to the fee value each
maker's liquidity generates, so it accrues to these same high-volume makers. The *direction* —
liquidity provision earns the edge — replicates Akey and Gómez-Cram; the new element is the identified
markout showing the maker edge is spread capture, with adverse selection only a negligible, transient,
small-maker effect. *(Sub-RQ 2, capture and mechanism.)*

### 5.4 Who captures, structurally: the on-chain account map and the actors behind the edge
**Account type.** Resolving on-chain contract types on an activity- and PnL-stratified classified
sample (n≈27,111) shows the population is ~97% smart-contract proxy wallets, split by onboarding
channel: ~74.5% Gnosis Safe (browser-wallet users, `signature_type` 2), ~21% Polymarket factory
proxy (email/"Magic" users, `signature_type` 1), ~3.3% EOA, and a ~1% tail of minor-variant
contracts (`account_types.json`). Winners are almost exclusively the two dominant standard proxy
types; the minor-variant contracts are low-activity one-offs, and we do not claim they are or
are not bots. Mean realised PnL is highest for the email/Magic proxy (~\$65k) — but this is
driven by a few extreme winners: the median account of every type is a net loser (−\$1 to −\$12),
so account type by itself does *not* separate winners from losers. It is an
onboarding-channel/infrastructure axis, not a skill axis.

**Behavioral actors.** Classifying active wallets by function (`actor_taxonomy.json`, 1.52M wallets):

| actor type | n | maker-share | fills/day | 24-7 (entropy frac) | mean PnL | win-rate |
|---|--:|--:|--:|--:|--:|--:|
| market_maker | 84,120 | 0.84 | 16 | 0.72 | +\$1,991 | 47% |
| hft_bot (near-24/7) | 50,441 | 0.22 | 109 | 0.96 | +\$1,152 | 29% |
| active_trader (directional) | 274,031 | 0.13 | 32 | 0.63 | −\$312 | 21% |
| retail_casual | 1,086,388 | 0.18 | 4 | 0.67 | −\$89 | 32% |
| one_shot | 23,961 | 0.11 | 13 | 0.31 | −\$346 | 23% |

As a class, market-makers (+\$167.5M aggregate) and high-frequency near-24/7 automated accounts
(+\$58.1M) are the net winners — capturing the edge via spread capture, not forecasting —
while directional and retail classes lose in aggregate (−\$85.4M active, −\$96.5M retail). Within
*every* class the median account is a small net loser, so the class-level edge sits in each class's
right tail (mean ≫ median). This is precisely the population that captures the maker subsidy in §5.3. Two qualifications apply:
the economic *direction* — liquidity provision and automation earn the edge — replicates the
concurrent papers, and, because public fills do not carry the order/quote lifecycle (Nechepurenko,
2026), these are functional behavioral classes rather than identified market-maker roles. The
new-to-the-literature contribution is the on-chain account-type axis and its crossing with function
and PnL — most EOAs behave as retail (~62%), with a minority (~6% of the HFT class, ~1.8×
over-represented) automated, so account type maps to *onboarding channel*, not cleanly to
bot-vs-human. *(Sub-RQ 2, structural identity.)*

### 5.5 Supporting / replicated backdrop (cited, not claimed as novel)
For completeness and to situate §5.1–5.4: takers lose −\$86.1M in the ~fee-free v1 era; in the
fee era they are gross-positive (+\$20.0M) but −\$129.5M net — the ~1.17% taker fee (≈\$149.5M)
is the entire loss channel and then some, so the loss mechanism *shifts* from the maker spread (v1)
to the fee (v2). Winnings are hyper-concentrated (Gini ≈ 0.95; the top 1% of winning wallets take
~70% of all winnings) — replicating Akey. On skill, a full-population sign-randomization test
yields ~4.3% certifiably skilled after Benjamini–Hochberg correction (7.1% uncorrected) — the
same order as Gómez-Cram's ~3%, and an upper bound given cross-market outcome correlation; the
correlation-immune signal is weak-but-real persistence (split-half Spearman ≈ 0.15, p≈0;
period-1 top-quintile → +\$1,174 mean in period 2 vs −\$134 for the bottom). Skill is expressed as
breadth — the skilled tier trades far more markets (mean ~314 vs ~113 neutral) at a much higher
market-level win-rate (~85%), not one lucky bet; a stricter position-level test in the informative
price band is by contrast null (observed skilled winners 123 < chance 257), reinforcing the
upper-bound reading. Coordination is a negative result: funding-graph entity collapse is small
(~4.3% of top-20k-winner diversity is sybil), dominated by a single 377-wallet cluster (+\$48M)
with the remainder singletons — no broad coordinated syndicate, consistent with the project's
prior coordination null. These support, but are not, the contribution.

---

## 6. Limitations

- **Participation response.** The event study holds category composition constant and removes the
  fee-free pre-trend; on that basis no participation or volume response to the fee is identified. The
  rollout affords only about nine treated categories, too few for cluster-robust inference, so this is
  an underpowered null, not a demonstrated absence of effect, and the incidence and capture results do
  not depend on it.
- **Descriptive, outcome-dependent PnL.** All profit-and-loss is realised against the resolved outcome
  and subject to survivorship; it measures realised performance, not risk-adjusted skill. The
  dispersion in realised PnL among makers reflects position and inventory selection and the eventual
  outcome, not the fill-time execution component, which is favourable across the maker population (§5.3).
- **Behavioral classes and account type.** Market-maker and HFT labels are functional classes inferred
  from public fill activity, which does not carry the order/quote lifecycle (Nechepurenko, 2026), so
  they are behavioral types, not identified roles. On-chain account type resolves an onboarding and
  infrastructure channel, not a beneficial owner or human-versus-bot status.
- **Rebate capture is argued from the published rule.** The maker rebate is allocated by Polymarket's
  published fee-curve rule in proportion to the fee value each maker's liquidity generates, so it
  accrues to the high-volume makers shown here to capture the spread (§5.3–§5.4). This is an inference
  from the published rule and the measured concentration of the maker edge, not a recipient-level
  accounting of the rebate distribution.

## References
- Akey, P., Grégoire, V., et al. (2026). *Who Wins and Who Loses in Prediction Markets? Evidence
  from Polymarket.* SSRN 6443103 (CEPR DP 21615). Data: HuggingFace `vgregoire/polymarket-users`.
- Gómez-Cram, R., et al. (2026). *Prediction Market Accuracy: Crowd Wisdom or Informed Minority?*
  SSRN 6617059.
- Nechepurenko (2026). *Fill-Side Behavioral Concentration on Polymarket: Identification Limits
  under Record-Level Attribution.* arXiv 2605.11640 (SSRN 6751284).
- Mitts, J., & Ofir (2026). *From Iran to Taylor Swift: Informed Trading in Prediction Markets.*
  SSRN 6426778.
- Qin & Yang (2026). *The Polymarket-v1 Database.* arXiv 2606.04217 (CC-BY-4.0).
- Rahman, N., Clark, J., et al. (2025). *SoK: Market Microstructure for Decentralized Prediction
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

*Make/take fees and trading costs.*
- Malinova, K., & Park, A. (2015). *Subsidizing Liquidity: The Impact of Make/Take Fees on Market
  Quality.* Journal of Finance 70(2), 509–536.
- Colliard, J.-E., & Foucault, T. (2012). *Trading Fees and Efficiency in Limit Order Markets.* Review
  of Financial Studies 25(11), 3389–3421.
- Foucault, T., Kadan, O., & Kandel, E. (2013). *Liquidity Cycles and Make/Take Fees in Electronic
  Markets.* Journal of Finance 68(1), 299–341.
- Angel, J. J., Harris, L. E., & Spatt, C. S. (2011). *Equity Trading in the 21st Century.* Quarterly
  Journal of Finance 1(1), 1–53.
- Galati, L. (2024). *Exchange fees, maker rebates, and the distribution of trading gains.* Working
  paper.
- Polymarket (2026). *Trading Fees* and *Maker Rebates Program.* Polymarket Help Center.

*Adverse selection and spread decomposition.*
- Kyle, A. S. (1985). *Continuous Auctions and Insider Trading.* Econometrica 53(6), 1315–1335.
- Glosten, L. R., & Harris, L. E. (1988). *Estimating the Components of the Bid/Ask Spread.* Journal of
  Financial Economics 21(1), 123–142.
- Huang, R. D., & Stoll, H. R. (1997). *The Components of the Bid-Ask Spread: A General Approach.*
  Review of Financial Studies 10(4), 995–1034.
- Lee, C. M. C., & Ready, M. J. (1991). *Inferring Trade Direction from Intraday Data.* Journal of
  Finance 46(2), 733–746.
- Easley, D., López de Prado, M. M., & O'Hara, M. (2012). *Flow Toxicity and Liquidity in a
  High-Frequency World.* Review of Financial Studies 25(5), 1457–1493.

*Information aggregation under trading costs.*
- Cipriani, M., & Guarino, A. (2008). *Transaction Costs and Informational Cascades in Financial
  Markets.* Journal of Economic Behavior & Organization 68(3–4), 581–592.
- Avery, C., & Zemsky, P. (1998). *Multidimensional Uncertainty and Herd Behavior in Financial
  Markets.* American Economic Review 88(4), 724–748.

*Staggered difference-in-differences methods.*
- Callaway, B., & Sant'Anna, P. H. C. (2021). *Difference-in-Differences with Multiple Time Periods.*
  Journal of Econometrics 225(2), 200–230.
- Sun, L., & Abraham, S. (2021). *Estimating Dynamic Treatment Effects in Event Studies with
  Heterogeneous Treatment Effects.* Journal of Econometrics 225(2), 175–199.
- Bertrand, M., Duflo, E., & Mullainathan, S. (2004). *How Much Should We Trust
  Differences-in-Differences Estimates?* Quarterly Journal of Economics 119(1), 249–275.
- Goodman-Bacon, A. (2021). *Difference-in-Differences with Variation in Treatment Timing.* Journal of
  Econometrics 225(2), 254–277.
- de Chaisemartin, C., & D'Haultfœuille, X. (2020). *Two-Way Fixed Effects Estimators with
  Heterogeneous Treatment Effects.* American Economic Review 110(9), 2964–2996.

*Trader taxonomy and prediction-market microstructure.*
- Rothschild, D. M., & Sethi, R. (2016). *Trading Strategies and Market Microstructure: Evidence from a
  Prediction Market.* Working paper / Journal of Prediction Markets.
- Kirilenko, A., Kyle, A. S., Samadi, M., & Tuzun, T. (2017). *The Flash Crash: High-Frequency Trading
  in an Electronic Market.* Journal of Finance 72(3), 967–998.
- Dubach (2026). *The Anatomy of a Decentralized Prediction Market: Microstructure Evidence from the
  Polymarket Order Book.* arXiv 2604.24366.
- Kober (2026). *On-chain reconstruction of Polymarket fees and maker rebates.* Working paper.
- Becker (2025). *Maker–taker wealth transfer on a centralized event exchange: evidence from Kalshi.*
  Working paper.
- Della Vedova (2026). *Humans, bots, and the anatomy of profit on Polymarket.* Working paper.

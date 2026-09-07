# Methods and novel topics — 2026-09-05

Additional methods for testing skill and manipulation, and creative publishable topics,
scoped to the data we already hold. The strategic constraint (`research_framing_2026-09-05.md`):
the who-profits/concentration/skill story is scooped by Akey (2026) and Gomez-Cram (2026),
who used **API-level transaction data**. Our edge is everything the API does not expose.

## 0. Our unique data assets (what the competitors did not have)

1. **The on-chain v2 tape** — block number, tx hash, intra-block event index, and **builder/
   relayer code** per fill. Enables *ordering*, *MEV*, and *routing* analysis impossible from
   the API. 427M fills, 2026-04→08.
2. **Both maker AND taker identities** on every fill (the Data API is taker-only). Enables
   maker-side economics and true counterparty graphs.
3. **The fee rollout** — a staggered natural experiment (v1 fee-free → v2 fees; and within-v2
   category-staggered), which no published Polymarket paper studies.
4. **On-chain funding graph** — USDC transfers + entity resolution (Louvain) → beneficial-owner
   clustering the wallet-level literature cannot do.
5. **negRisk family structure** + resolution registry (2.1M conditions) → multi-outcome
   no-arbitrage and resolution dynamics.

---

## 1. Additional methods to test SKILL (beyond the sign-randomization null now running)

| Method | What it adds | Data we have | Feasible now |
|---|---|---|---|
| **Split-half persistence** (Barber-Lee-Liu-Odean; poker) | Rank wallets by PnL/skill in period 1; test if the rank predicts period-2 PnL out-of-sample. The cleanest skill-vs-luck test; competitors report 44% (G-C) / "modest, may be selection" (Akey). | full history, per-wallet, both sides | **Yes** |
| **Finite-mixture decomposition** (Akey) | Fit a 2–3 component mixture (skilled/lucky/unskilled) to the PnL-vs-null z's; estimate the skilled fraction as a parameter, not a threshold. | z's from scripts/31 | **Yes** |
| **Empirical-Bayes shrinkage** (extends our `skill.py` Beta prior) | Shrink per-wallet win-rates to the population; the posterior "true skill" separates signal from small-sample noise — directly answers "is the tail real." | positions, prices | **Yes** |
| **Skill ⟂ liquidity provision regression** (Akey's key control) | Regress P(win)/PnL on maker-share; if "skill" vanishes once you control for making, the tail is spread-capture, not forecasting. Our maker identities make this clean. | maker+taker | **Yes** |
| **Out-of-sample predictive skill** | Train on period-1 features (calibration, size, category mix, maker-share), predict period-2 profit; AUC>0.5 OOS = skill. | full history | **Yes** |
| **Calibration/Brier resolution decomposition** (Convexly) | Split forecast quality into reliability vs resolution; we already have reliability curves. | prices, outcomes | **Yes** |

The **novel methodological contribution** is running *several* of these on the *same* population
and showing which null/estimator drives the "3% skilled" vs "no skill" divergence — nobody has
done a like-for-like bake-off. That is RQ2 in the framing doc, upgraded.

---

## 2. Additional methods to test MANIPULATION (on-chain, beyond the API papers)

| Method | Signature it targets | Our unique enabler | Feasible |
|---|---|---|---|
| **Funding-cluster wash** | Wallets sharing a funding source trading *with each other* → self-dealing volume | USDC funding graph + cotrade graph + Louvain | **Yes** (stronger than Sirolly's pure-network wash) |
| **Incentive/airdrop farming** | Volume churned to farm rewards: round-trips, self-clusters, timing spikes around reward epochs | funding graph + timing + fee_raw | **Yes** (Solidus flagged; we can quantify) |
| **On-chain MEV on settlement** | Sandwiching / front-running of large orders; JIT liquidity around big fills | block+tx+evt_index ordering, builder | **Yes** (Gap 8; genuinely unstudied on Polymarket) |
| **Insider provenance** | Pre-event positioners funded from a fresh/exchange wallet just before the event | funding provenance + event study | **Yes** (the API can't trace capital origin) |
| **Cross-market coordination** | Correlated directional pushes across negRisk siblings or related markets by one cluster | family structure + entity graph | **Yes** |
| **Momentum ignition / order anticipation** | A big order systematically preceded/followed by a cluster within N blocks | block-level lead-lag | **Yes** |
| **Pump-and-reversal** | Abnormal price move + concentrated flow + reversal near resolution | prices + concentration + convergence | **Yes** (our §6 subscores) |
| Spoofing/layering | Book churn without execution | needs full L2 book history | **No** (Phase 4 WS, not built) |

---

## 3. Creative novel topics (ranked by novelty × feasibility × data-fit)

**T1 — Entity-level concentration: sybils and the "true" inequality (one-ups the who-profits papers).**
Akey/Gomez-Cram measure concentration at the **wallet** level. Collapse wallets to beneficial owners
via the on-chain **funding graph**, then re-measure: the Gini and top-k share almost certainly *rise*,
and some fraction of the "independent winners" are the **same entity**. Headline: *"the wallet is the
wrong unit; at the entity level, prediction-market profits are even more concentrated than reported,
and N% of the apparent winner diversity is sybil structure."* Directly novel vs the two competitors,
uses data they lack. **High novelty, feasible now.** Risk: entity resolution is noisy — report a
sensitivity band and validate against known operators.

**T2 — The fee rollout as behavioral & welfare economics (the primary paper).**
Beyond incidence: a behavioral DiD on how the fee changed *behavior* — did it price out the smallest/
newest traders (participation elasticity), shrink order sizes, cut round-tripping, professionalise
making, and did market quality (spreads, depth, efficiency) improve or degrade? A public-economics
framing (regressive incidence + deadweight + who exits) on a clean natural experiment nobody has
touched. **High novelty, feasible now** (v2 tape + staggered rollout).

**T3 — The economics of losing liquidity provision (maker-side adverse selection).**
Our finding that **637k of 1.21M makers lose** while a tiny maker elite captures +$86M is *not* in the
literature (which treats "maker share" as a winning predictor). Who are the losing makers, and are
they *adversely selected* by informed takers (amateur LPs providing free options)? A microstructure
paper on the professionalisation and adverse selection of DePM liquidity. **High novelty** (maker-side
is unstudied), **feasible** (we have maker identities).

**T4 — MEV and the ordering layer of a prediction market (Gap 8).**
Is there extractable value on the settlement path — sandwiching large fills, builder-privileged
execution, JIT liquidity? Even a rigorous **null** ("DePM design X makes it MEV-resistant") is
publishable and unique; a positive is stronger. **High novelty, medium feasibility** (careful
on-chain work; may be null). Uses block/builder data no competitor has.

**T5 — Order-flow routing & builder execution quality (a PFOF analog).**
1,169–1,446 builder codes, notional HHI ~0.8. Do some builders systematically get better prices /
lower adverse selection? A "payment-for-order-flow in a decentralized market" study — a topical,
unstudied routing-economics angle. **Medium-high novelty, feasible.**

**T6 — Skill-null reconciliation (methodological, RQ2).**
Why do a paid-rate/calibration null (ours: no skill), a sign-randomization null (G-C: ~3%), and a
finite-mixture (Akey: ~29%) disagree on the same platform? A bake-off clarifying what each measures.
**Medium novelty, feasible now** (partly running).

**T7 — Detection ceiling / limits of on-chain surveillance (reframes the original mission).**
What is the *smallest* wash cluster, insider ring, or coordinated push detectable from public on-chain
data, and what fraction of markets is even computable? A "limits of public-data market surveillance"
result — honest nulls turned into a contribution, fitting the project's integrity mission. **Medium
novelty, feasible** (needs the news overlay for the insider ceiling).

**Recommended portfolio:** **T2 (fee experiment) as the lead paper**, **T1 (entity-level
concentration)** and **T3 (losing makers)** as the two novel differentiators that beat the scooped
literature, with **T6** folded in as method and **T4/T5/T7** as follow-ups. T1+T3 both exploit exactly
what the API-based competitors could not see (funding graph, maker identities), which is the whole
point of having collected the on-chain tape.

---

## 4. What needs new collection vs. runs on existing data

- **No new collection:** T1, T2, T3, T5, T6, and all §1–§2 methods except spoofing — everything is
  on disk (archive + v2 tape + funding graph + registry).
- **New collection helps:** T4 (MEV) may need mempool/bundle data for a positive result; T7's insider
  ceiling needs a **news timeline** (spec Stage D); UMA dispute labels would sharpen resolution-
  manipulation work.

---

## 5. NEW FOCUS (2026-09-06) — account-type taxonomy: who (or what) actually trades and wins

**Origin:** the user asked whether the traded addresses are EOAs or smart contracts. On-chain
measurement (`scripts/37`, `eth_getCode`) found the answer is neither uniform nor what anyone has
reported — and it is **completely ignored by Akey (SSRN 6443103) and Gómez-Cram (SSRN 6617059),
who treat every wallet as a homogeneous human trader.** That omission is a fresh opening.

**Findings so far (samples; being scaled in `scripts/37`):**
- Trader addresses are **~1.3% EOA, ~98.7% smart contracts.** The contract population is **not**
  monolithic: two dominant standard proxy code-hashes (`f5c625…` ≈40%, `cefa4f…` = a 46-byte
  EIP-1167 minimal proxy ≈20%) plus a long tail — **~39% of contracts have *unique* bytecode**
  (bespoke/bot candidates or per-user CREATE2 proxies); **385 distinct code-types** in a 1k sample.
- **The winners are almost exclusively the two standard proxy types** (top-1000 winners: only **4**
  code-hashes, **0.1%** custom, **1.1%** EOA) — i.e. ordinary users on Polymarket's official UI,
  **not** EOAs and **not** bespoke bots. The ~39% custom/exotic contracts are **absent from the
  winners.** → The intuitive "the sharp winners are bots" is **refuted**; automation does *not*
  visibly confer edge here.

**Why novel:** nobody has published an on-chain **account-type × profit/skill** analysis of a
prediction market. It reframes the who-wins debate as *who/what structurally*, and supplies a
mechanism the competitors lack.

**Research questions (this may become a standalone paper or the mechanism section of the
who-profits/fee work):**
- **RQ-A1 (taxonomy):** on-chain account-type composition (EOA / Gnosis-Safe / Polymarket-proxy /
  custom-contract), and its mapping to onboarding paths (email→Safe vs browser→proxy). Identify the
  two dominant hashes via `getOwners()`/known bytecode.
- **RQ-A2 (profit by type):** does realised profit/skill differ by account type? [Finding: winners
  ≈ standard proxies; custom/EOA under-represented among winners.]
- **RQ-A3 (automation ≠ edge):** do behaviourally-automated accounts (high-frequency, regular-
  interval, 24/7) win or lose? Test whether automation confers edge on a prediction market —
  initial evidence says **no**, unlike equities/crypto-DEX where bots dominate profits.
- **RQ-A4 (entity/sybil via owner):** with **proxy→owner resolution** (`resolve_controller`), how
  many "distinct winners" collapse to the same beneficial owner? (This is the *right* T1 method for
  a ~99%-proxy population — cleaner than shared-funding, since a proxy's funder is often the
  Polymarket relayer hub.)
- **RQ-A5 (the exotic-contract tail):** are the ~39% custom-code contracts active bots that lose,
  or one-off/sybil/abandoned accounts? Characterise by activity, PnL, and inter-trade timing.

**Interaction with the fee paper:** account type likely conditions fee incidence and participation
(do the standard-proxy retail users bear the fee while EOAs/bots avoid or arbitrage it?), which
would *strengthen* the lead paper's welfare story. `scripts/37` (phases cache→analyze) runs in the
overnight stage-3; proxy→owner resolution is the next build.

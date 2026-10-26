# Derived data: derivation rules and rationale

This is the lineage / provenance catalog. For each result the pipeline **derives** from the collected
data, it states:

- **Inputs** — which collected stores it is computed from (documented in `DATA_DICTIONARY.md`);
- **Rule** — the exact **processing method** applied to the data: the sequence of operations that
  turns each input datum into the derived value and the result, with the formula where there is one;
- **Why** — the methodological justification for computing it that way;
- **Producer** — the script that writes it, which is the **authoritative implementation**.

It documents the *logic and rationale*, not column schemas — those live with each producer (see
`DATA_DICTIONARY.md §8`). Commands to re-run everything are in `REPLICATE.md`; determinism guarantees
are in `REPRODUCING.md`.

## Research questions

The fee study is organised around two questions; results below are tagged **RQ1** / **RQ2**.

- **RQ1 — fee incidence.** What is the incidence of the fee across order sizes and trader roles — who
  ultimately bears it, measured as a share of the value they trade — and is it *regressive* (a higher
  rate on smaller trades)?
- **RQ2 — the maker subsidy.** Who captures the maker rebate the fee funds, through what mechanism,
  and what is their structural identity (what kind of trader)?

## Why this study: the literature gap and why the fee matters

**The gap.** Two literatures bear on this question but neither answers it. Market microstructure has
studied make/take fees extensively on **equity venues** (Malinova & Park; Colliard & Foucault; Foucault,
Kadan & Kandel; Battalio et al.; Angel, Harris & Spatt) and on **centralized crypto exchanges** (Galati;
Brauneis et al.), finding that fee changes tend to shift value toward liquidity providers — but from
broker- or venue-level aggregates that cannot say *which individual actors* bear or capture it.
Separately, a growing body characterizes **who profits on Polymarket** (Akey et al.; Gómez-Cram et al.;
Mitts & Ofir; Dubach; Nechepurenko) — but only on the **pre-fee** record. No prior work has measured the
*incidence and distribution of a fee on a decentralized prediction market at the level of individual
traders*; the transition from freely subsidized liquidity to a fee-funded model is itself unstudied.

**Why the fee specifically — and not other aspects of Polymarket.** The fee is the pivotal, recent,
deliberate design change: it replaced free liquidity provision with a charge on takers that funds a
subsidy to makers, directly reshaping who can afford to trade and how gains are split. On a prediction
market a fee is, in effect, a **tax on the trading that makes prices informative**, so its distributional
effect is a first-order question for the market's integrity and its forecasting value. Crucially, this
question is **measurable here in a way it is not elsewhere**: because a decentralized venue settles on a
public blockchain, incidence and capture can be computed on the *complete population* of trades, with the
true buyer and seller of each — exactly the trader-level data the equity and centralized-crypto fee
studies lack, and that Polymarket's own public feed cannot provide. Other aspects (for example,
manipulation patterns) were examined in the project's earlier stage and found null; the fee transition is
where the novel, consequential, and tractable question lies.

**Implications.** The results speak to fairness and participation (the fee is **regressive** — heaviest,
as a share of money staked, on the smallest, longshot trades), to market structure (the maker subsidy is
**captured by a small professional class**, not the broad population), and to integrity (whether a
fee-funded rebate can be **farmed** through self-dealing). Together they inform how prediction markets —
and other on-chain venues — should design fees and liquidity subsidies, and they give the community the
first trader-level evidence on what a liquidity tax does to a market whose social value is accurate
probabilities.

## Shared definitions (reused below)

- **price `p`** ∈ (0,1): USDC per share = implied probability of the outcome. **shares `s`**: number of
  outcome-token shares. **notional** (dollar value of a trade) `= p · s`.
- **Realized PnL** of an account = USDC received at resolution (winning shares redeem at \$1) minus
  USDC paid to acquire its net position, cost-basis-aware; uncovered sells are scaled to the position
  actually held. Computable **only once the market's outcome is known**.
- **Taker fee** (`DATA_DICTIONARY.md §10`): V1 `0.10·min(p,1−p)·s`; V2 `feeRate·p·(1−p)·s`
  (`feeRate` 0.04–0.07 by category). **Incidence** (V2) `= fee/notional = feeRate·(1−p)`.
- **Deduplication**: the v2 tape is deduped by `(tx_hash, evt_index)` before any aggregation.
  **Fee treatment** is defined from `fee_usdc>0` (V1) / the taker-order fee rows (V2), never from the
  non-binding `taker_base_fee`.

---

## 1. Fee incidence and regressivity — RQ1

- **Inputs**: v2 tape (`fee_raw`, `price`, `shares`, `usdc`) for the fee law; v1 archive for the
  rollout-era incidence by size.
- **Rule**: confirm the rate `r` as the median of `fee / [p(1−p)·s]`; compute the **incidence**
  `= fee/notional = r·(1−p)`; report the effective rate across ten **equal-count order-size deciles**.
- **Why**: the economically meaningful burden is the incidence (fee as a share of money staked), not
  the raw `fee/[p(1−p)s]` ratio — the ratio's upper tail is a per-order-aggregate artifact of the
  concavity of `p(1−p)`, so it is reported separately from the incidence ceiling. Size-decile binning
  exposes the regressivity: the smallest orders sit on lower-priced (longshot) outcomes where `(1−p)`
  is larger, so they bear the highest rate. The fee law is **confirmed on-chain**, not assumed.
- **Producer**: `scripts/41_fee_rate_audit.py` → `gate1_fee_audit_repro.json`;
  `scripts/33_fee_behavioral.py` → `fee_behavioral.json`.

## 2. Participation response to the fee — RQ1

- **Inputs**: v1 archive — each market's fee-start (first day with `fee_usdc>0` on ≥50% of fills), and
  per-category weekly active traders, first-time traders, and median order size.
- **Rule**: a **staggered difference-in-differences / event study** on a **balanced
  (constant-composition) panel**; treatment = a category's fee-start; outcomes = active traders,
  new-wallet inflow, median order size; the effect is read as the **deviation from the fitted
  pre-treatment trend**, with not-yet-treated categories as controls.
- **Why**: a balanced panel of fixed category composition + not-yet-treated controls + pre-trend
  subtraction guard against the three confounds — platform-wide growth, a shifting category mix, and
  selection of already-growing categories into treatment. Treatment uses `fee_usdc>0` because
  `taker_base_fee=1000` is a non-binding declared rate. With only nine categories and a short post-fee
  window the result is reported as **"no detectable effect," not proof of none**.
- **Producer**: `scripts/36_fee_rollout_did.py` → `fee_rollout_did.json`.

## 3. Maker-profit concentration — RQ2

- **Inputs**: the **fully-resolved v1 archive** — per-maker realized PnL.
- **Rule**: realized gross PnL per maker over resolved markets; **Gini** among profitable makers;
  top-k capture shares (0.1% / 1% / 10%); aggregate PnL by equal-count **volume decile**; negRisk
  families deduplicated to one unit.
- **Why**: realized profit needs known outcomes, so concentration is measured on the fully-resolved V1
  record (the V2 fee era is not fully resolved). It is measured over **makers** because the rebate
  rewards liquidity provision; Gini and top-share are the standard concentration measures; the volume
  deciles show whether aggregate profit tracks volume rather than a per-trade edge (it does).
- **Producer**: `scripts/30_concentration.py` → `concentration.json`;
  `scripts/32_maker_economics.py` → `maker_economics.json`.

## 4. Maker mechanism: markout vs adverse selection — RQ2

- **Inputs**: v2 tape (maker fills: `price`, `side`) and the token's trading price a short interval
  `Δ` later.
- **Rule**: the **markout** `m = σ·(p_{t+Δ} − p_fill)`, with `σ=+1` for a maker buy and `σ=−1` for a
  maker sell; volume-weighted across makers at horizons `Δ` from 1 minute to 1 day. Positive `m` =
  spread capture; negative `m` = adverse selection.
- **Why**: the markout uses only **near-term prices and no eventual outcome**, so it isolates adverse
  selection **at the time of the fill** — this is the classic Huang–Stoll spread decomposition. It
  avoids a measurement trap: the correlation between a maker's realized profit and whether its
  counterparties eventually won is ≈ −0.6, but that is an **accounting identity** (maker PnL = −
  counterparty PnL by construction), not adverse selection.
- **Producer**: `scripts/40_maker_markout.py` → `maker_markout.json`.

## 5. Self-dealing — RQ2

- **Inputs**: v2 tape restricted to the two fee-charging exchanges (`v2_a`, `v2_b`), deduped.
- **Rule**: enumerate every fill and count (a) fill-level self-matches (`maker == taker`) and
  (b) transaction-level self-dealing (one account that is the maker on one fill and the taker on
  another fill of the **same transaction**); plus whole-tape transaction/volume totals.
- **Why**: single-account self-dealing — the obvious way to farm a fee-funded rebate — is **directly
  and exactly enumerable on-chain**, so it is counted rather than estimated. It is scoped to
  `v2_a`/`v2_b` so it matches every other reported number (auxiliary-emitter dust is excluded). It is
  also unprofitable by construction (the rebate returns only 20–25% of the fee paid). Wash trading
  **coordinated across many wallets one party controls** is beyond a single-account enumeration and is
  flagged as a limitation, not claimed as absent.
- **Producer**: `scripts/42_self_dealing.py` → `self_dealing.json`;
  `scripts/43_selfmatch_reconcile.py` (contract-scope reconciliation).

## 6. Platform-wide taker PnL (the backdrop)

- **Inputs**: v1 archive (fee-free baseline) and v2 tape (fee regime).
- **Rule**: realized gross PnL per taker aggregated platform-wide; on v2 the **fee** (carried on the
  taker-order rows) is subtracted to give net; deduped by `(tx_hash, evt_index)`.
- **Why**: establishes that takers lose in aggregate and isolates the **fee as the loss channel** on
  v2 (gross vs net), replicating the direction of prior work (Akey; Gómez-Cram) on the complete record
  rather than a sampled feed.
- **Producer**: `scripts/27_platform_wide.py` → `platform_wide.json`;
  `scripts/28_v2_platform.py` → `v2_platform.json`.

## 7. Skilled population and calibration

- **Inputs**: the resolved v1 archive — per-`(wallet, market)` directional positions and the winner.
- **Rule**: each position is a directional bet that wins per the realized outcome. A **Bayesian Beta
  posterior** is formed with the **prior centred on the wallet's own mean implied probability** (weak
  strength); `calibration_gap = posterior_mean − mean_implied_p`. The population test is a
  **sign-randomization (permutation) test** — under the null, flipping each bet's buy/sell sign leaves
  expected PnL unchanged — with a correlation-immune persistence cross-check and Holm/BH multiplicity
  control.
- **Why**: centring the prior on the **entry-implied probability** makes the null "this wallet wins at
  the rate it paid for," so a positive gap is edge **above the price paid**, not above 0.5. The
  permutation test is immune to within-wallet correlation across bets. The design certifies a skilled
  **population**, not individuals, and requires known outcomes (hence V1).
- **Producer**: `scripts/31_skill_signflip.py` → `skill_signflip.json`;
  `scripts/23_skilled_population.py` → `skilled_population.json`; `src/intellifi/skill.py`.

## 8. Cross-market skill breadth

- **Inputs**: v1 archive — per-wallet performance across markets and categories.
- **Rule**: measure whether accounts that look skilled are skilled across **many** markets/categories
  or only a few.
- **Why**: breadth separates genuine skill from luck or single-market specialization that a
  pooled test would mistake for skill.
- **Producer**: `scripts/38_skill_breadth.py` → `skill_breadth.json`.

## 9. Actor taxonomy and account types

- **Inputs**: v1 archive behaviour (maker share, fills/day, breadth across markets) and the on-chain
  account bytecode (`code_len`) per wallet.
- **Rule**: the **account type** is the on-chain code class (EOA / Polymarket proxy / Gnosis Safe); the
  **behavioural class** is a heuristic partition by maker share, trading frequency, and breadth into
  market-maker / HFT / active / retail / one-shot, with per-class net PnL and win rate.
- **Why**: on this venue nearly all accounts are smart-contract proxy wallets, so wallet **form**
  cannot separate professional from retail — **behaviour** does. The taxonomy gives the structural
  identity of the subsidy's beneficiaries.
- **Producer**: `scripts/37_account_types.py` → `account_types.json`;
  `scripts/39_actor_taxonomy.py` → `actor_taxonomy.json`.

## 10. Coordination nulls

- **Inputs**: on-chain **USDC** transfers between universe wallets (the funding graph); the co-trading
  graph built from fills.
- **Rule**: resolve wallets into entities via the funding graph (direct + common-neighbour edges) +
  Louvain; build the winning-cluster / co-trading graph among top winners; compare against
  **activity-preserving null models** and **matched placebo controls**; identify clusters
  **structurally** (maximum overlap with a reference entity), never by a literal Louvain id.
- **Why**: raw co-trade and lead–lag statistics overstate coordination, so an activity-preserving null
  and matched controls are required to separate structure from coincidence. **ERC-1155 transfers are
  excluded** from the entity graph — they are fill settlements, not relationships; only USDC transfers
  are relationship evidence. Louvain ids are not stable across runs, hence structural identification.
- **Producer**: `scripts/34_entity_funding.py` → `entity_concentration.json`;
  `scripts/35_winning_graph.py` → `winning_graph.json`; `scripts/04_coordination_analysis.py`;
  `src/intellifi/wallet_graph.py`, `src/intellifi/coordination.py`.

## 11. Resolution convergence

- **Inputs**: CLOB `prices_history` per token; each market's `closed_time`; the winning outcome.
- **Rule**: per market, the absolute error of the winning outcome's price vs `1.0`, as a function of
  hours **before the actual close (`closed_time`)**, then aggregated.
- **Why**: "late mispricing" must be measured from the **true** close. `end_date` is only the scheduled
  deadline (median +21 h vs the real close, with a wide range), so measuring from it reproduces a known
  bug; `closed_time` is used instead.
- **Producer**: `scripts/06_convergence.py` → `convergence/`.

## 12. Registries and the events layer (derived lookups)

- **Inputs**: the CTF contract's `ConditionResolution` events; the CLOB `/markets` enumeration;
  `gamma_v2` market metadata.
- **Rule**: the condition/resolution registry takes the winner from `payout_numerators` (the index
  with numerator 1); the token→market map and category tags come from **cursor-enumerating** the CLOB
  API; the `events` layer is derived from `gamma_v2` with no network fetch.
- **Why**: fills must be attached to their market, **category** (hence fee rate / rollout group), and
  **winning outcome**. CLOB cursor enumeration is lossless where Gamma's `/markets` is lossy (an
  offset ceiling truncates it), so it is the canonical market set.
- **Producer**: `scripts/12_fetch_v2_conditions.py`, `scripts/13_merge_verify_ctf_v2.py`,
  `scripts/14_fetch_clob_markets.py`, `scripts/16_derive_events.py`.

---

## Lineage at a glance

| Result (JSON) | Derived from | Rule | Producer |
|---|---|---|---|
| `gate1_fee_audit_repro.json` | v2 tape | §1 | `scripts/41` |
| `fee_behavioral.json` | v1 archive | §1 | `scripts/33` |
| `fee_rollout_did.json` | v1 archive | §2 | `scripts/36` |
| `concentration.json` | v1 archive (resolved) | §3 | `scripts/30` |
| `maker_economics.json` | v1 archive (resolved) | §3 | `scripts/32` |
| `maker_markout.json` | v2 tape | §4 | `scripts/40` |
| `self_dealing.json` | v2 tape (v2_a/v2_b) | §5 | `scripts/42`, `scripts/43` |
| `platform_wide.json` | v1 archive | §6 | `scripts/27` |
| `v2_platform.json` | v2 tape | §6 | `scripts/28` |
| `skill_signflip.json` | v1 archive (resolved) | §7 | `scripts/31` |
| `skilled_population.json` | v1 archive (resolved) | §7 | `scripts/23` |
| `skill_breadth.json` | v1 archive | §8 | `scripts/38` |
| `account_types.json` | v1 archive + bytecode | §9 | `scripts/37` |
| `actor_taxonomy.json` | v1 archive | §9 | `scripts/39` |
| `entity_concentration.json` | USDC funding graph | §10 | `scripts/34` |
| `winning_graph.json` | co-trading graph | §10 | `scripts/35` |
| `convergence/` | prices_history + closed_time | §11 | `scripts/06` |

For the exact column schema of any output, read its producer script or `DESCRIBE` the parquet
(`DATA_DICTIONARY.md §9`).

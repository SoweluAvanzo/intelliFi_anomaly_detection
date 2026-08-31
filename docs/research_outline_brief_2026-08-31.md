# Research outline brief — motivation, methods, and current results
*2026-08-31. A self-contained overview of the project — motivation, prior work, the identified gap, research questions, data collection, methodology, and current results — assuming no prior knowledge of the pipeline or the platform.*

---

## 1. Motivation

Polymarket is the largest decentralized prediction market: people trade YES/NO shares in real-world events (elections, sports, crypto price levels), and the share price behaves like a crowd-sourced probability. Because it settles on a public blockchain (Polygon), **every trade, every wallet, and every settlement is observable** — a level of transparency no traditional exchange offers. That makes it a natural laboratory for questions that are normally invisible in equities.

In 2026 Polymarket did two things that had never been studied on a prediction market:

1. **It introduced trading fees** — a *taker* fee, phased in category by category between January and April 2026. The fee has an unusual shape: `fee = 0.10 × shares × min(p, 1−p)`, i.e. it is largest for shares priced near 0.50 and near zero for long-shots priced near 0 or 1. There is **no maker fee**. Some categories (geopolitics/world) were left exempt.
2. **It migrated to a new exchange architecture on 28 April 2026** — new smart contracts, new collateral token (pUSD), per-market maker rebates, an order-flow "builder" attribution field, and self-cross prevention.

These two events, four months apart, are a **two-step natural experiment**: the January→April window changes *fees* while the exchange stays fixed; the April→June window changes the *architecture* with fees already in place. Because everything is on-chain, we can measure the effects directly rather than inferring them.

The practical stakes: fees change who can afford to trade, whether arbitrageurs keep prices consistent, and whether the market attracts or repels informed traders — all of which bear on whether these markets remain trustworthy "probability" signals.

## 2. How Polymarket works

*The platform primer, assuming no prior crypto or trading knowledge; key terms are defined inline where they first appear.*

**A prediction market.** Polymarket lets people trade **outcome shares** in a future event ("Will X happen?"). Each market has two **outcome tokens**, YES and NO, each of which pays **$1 if its outcome occurs and $0 otherwise**. Because a winning share is worth exactly $1, a YES share trading at $0.63 means the market prices the event at a **63 % probability** — the price *is* a live, crowd-sourced probability, which is what makes these markets worth studying.

**A market is a "condition"; shares are on-chain tokens.** Each market is registered on-chain as a **condition** (identified by a `conditionId` — the key our metadata is built on), and its YES/NO shares are **ERC-1155 "conditional tokens"** (Gnosis Conditional Tokens Framework, *CTF*) — one **token id** per outcome. Anyone can **mint** a **complete set** (one YES + one NO) by locking **$1 of collateral**, and **merge** a complete set back into $1. This mint/merge mechanism pins YES + NO ≈ $1 by construction. The **collateral** token is USDC on v1 and the new **pUSD** stablecoin on v2.

**Trading is an order book, not an AMM.** Polymarket does *not* use an automated market maker (**AMM**, the Uniswap/Augur design); it runs a **central limit order book (CLOB)**. The book is a **hybrid**: **limit orders are signed off-chain** and matched by Polymarket's **operator**, so the order book and its **depth** are *not* on-chain and are absent from our data — but when orders match, Polymarket's **exchange smart contract settles the trade on Polygon**, emitting an **`OrderFilled`** event (and an `OrdersMatched` event per match). So the *book* is off-chain and private, while every executed trade — a **fill** — is public and on-chain. This "**on-chain settlement of an off-chain book**" is why the complete trade history (the **tape**) can be rebuilt from the blockchain at all.

**Maker vs taker.** Every match has two sides. The **maker** is the party whose limit order was already resting in the book — the liquidity *provider* ("makes" the market); the **taker** is the party whose incoming order crosses the book and executes against it — the liquidity *consumer* ("takes"). On-chain, each match yields one **maker-order record** per resting order filled, plus one **taker-order record** whose counterparty is the exchange. This split drives both the fee (below) and market-quality measures such as **maker concentration** and the **bid–ask spread**.

**Fees — a taker-only, p(1−p) fee (the "make/take" question).** Exchanges commonly use **maker–taker pricing** (a.k.a. **make/take fees**): the **taker pays**, the **maker is often paid a rebate**, the point being to reward liquidity provision. In 2026 Polymarket introduced a **taker fee** — `fee = 0.10 × shares × min(p, 1−p)` — charged only to the taker, **with no maker fee**, phased in category-by-category (Jan→Apr 2026); the v2 migration later added **per-market maker rebates**. The shape is unusual — largest near $0.50, ~0 for long-shots near $0/$1 — and the **zero maker leg** has no equity analogue, which is exactly why the make/take literature (§3) has never been tested on a fee like it.

**Multi-candidate markets: negRisk families.** Events with more than two outcomes (e.g. a field of candidates) are grouped into a **negRisk ("negative-risk") family** in which **exactly one candidate resolves YES**. No-arbitrage then forces the candidates' YES prices to **sum to 1**; a persistent deviation of `Σ YES − 1` from zero is an unclosed **arbitrage**, and the size of that deviation — the **no-arbitrage band** — is our main price-consistency measure. A negRisk **"gadget"/conversion** lets traders convert positions across candidates on-chain.

**Settlement (resolution).** Once the real outcome is known, the condition is **resolved** via **UMA's optimistic oracle** (a decentralized, dispute-based reporting mechanism): winning tokens **redeem for $1**, losing tokens for $0. Each market carries **three close timestamps** (scheduled end, last trade, resolution), which matter for measuring when prices converge.

**The two 2026 changes we study.** (1) the **fee rollout** above; (2) the **v2 migration (28 Apr 2026)** — new exchange contracts (a **CTF Exchange** and a **NegRisk CTF Exchange**), the **pUSD** collateral token, per-market **maker rebates**, an order-flow **"builder" attribution** field (which front-end/integrator routed an order), and **self-cross prevention** (the contract forbids a wallet matching its own order — structurally closing one wash-trading route). Everything below analyzes these two events.

## 3. State of the art

Three strands of literature are relevant, and each has a gap we can fill.

- **Market-microstructure of prediction markets.** A wave of 2026 papers reconstructed the *complete* Polymarket v1 history and measured stylized facts, informed trading, and wash trading (Mitts & Ofir 2026; Gómez-Cram, Guo, Kung & Jensen 2026; Sirolly, Ma, Kanoria & Sethi 2025; Dubach 2026, arXiv 2604.24366; Tsang & Yang 2603.03136; Qin & Yang 2606.04217). These are cross-sectional descriptions of the *fee-free* v1 era. None studies the fee rollout or the migration.
- **Make/take fees and transaction taxes in finance.** A large theoretical and empirical literature (Colliard & Foucault 2012; Malinova & Park 2015; Battalio, Corwin & Jennings 2016) predicts how a maker/taker fee split changes liquidity provision and spreads. It has **never been tested on a prediction market**, and never on a fee that scales with p(1−p) with a zero maker leg.
- **No-arbitrage in combinatorial/multi-outcome markets.** In a multi-candidate ("negRisk") market exactly one outcome wins, so the YES prices should sum to 1; deviations are arbitrage (Saguillo et al. 2025). The effect of *fees* on how tightly this holds has never been measured.

## 4. The gap we identified

Everything published is on the **fee-free v1 era** and is **cross-sectional**. No one has measured:
- how the fee is actually borne (incidence),
- whether the fee loosens the multi-outcome no-arbitrage constraint,
- whether the fee changes liquidity provision, wash-like activity, or informed trading,
- what the migration did to market structure,

and no one has a **complete v2 (post-migration) tape** — the platform stopped publishing the public archive at the migration, so the only way to study the new regime is to reconstruct it from the blockchain, which we did.

## 5. Research questions

The general question — *how did fees and the migration change who pays, whether prices stay consistent, and how liquidity is provided* — decomposes into:

- **RQ1 (price consistency).** Do fees loosen the negRisk no-arbitrage band (the deviation of Σ YES-prices from 1)?
- **RQ2 (wash / architecture).** Do fees change wash-like activity, and does the architecture bound self-dealing?
- **RQ3 (market quality).** Did the fee rollout and the migration change liquidity provision (maker concentration, order size, spreads)?
- **RQ4 (incidence).** Who pays the fee, and is it regressive?
- **RQ5–RQ7 (v2-only, in progress).** Order-flow attribution by channel; post-migration settlement integrity; informed-trading persistence across regimes.

## 6. How the data was collected

**The raw object is one blockchain event per fill.** Every time two orders match on Polymarket, the exchange contract emits an `OrderFilled` log on Polygon. We fetch these logs directly from the chain (via Etherscan's free `getLogs` API), and decode each into a row: which token, maker and taker wallet, price, size, fee, and a timestamp. This is the "tape". We do this for two eras:

- **Sample A = the v1 tape.** Polymarket's complete v1 history is available as a public research archive (CC-BY licensed, arXiv 2606.04217). We use it as-is, **after validating it**: we independently reconstructed five markets' full histories from the raw chain and confirmed the archive matched us row-for-row (171,126 = 171,126 fills, exact). Sample A is where we *explore* and form predictions.
- **Sample B = the v2 tape.** No public archive exists after the migration, so we crawl the two new v2 exchange contracts ourselves, block by block, and rebuild the tape. Sample B is where we *confirm* the predictions.

**Why "explore then confirm".** Looking at data suggests patterns; testing those same patterns on the same data over-fits. So we split: derive predictions on Sample A, **write them down (pre-register) with a cryptographic hash before touching Sample B**, then test exactly those predictions on Sample B. This is the standard safeguard against fishing, and it is documented in `docs/stage2_preregistration.md`.

**Validation of the v2 tape.** Before any analysis, cohort 1 passed a pre-registered "gate": we re-fetched 20 random block-chunks independently and required (i) byte-identical results and (ii) that the number of taker-order records equals the number of `OrdersMatched` events (a conservation check). It passed 20/20 on both.

**Market metadata.** The tape identifies *tokens*, not human-readable markets or categories. We map each token to its market (condition), category, and — for multi-candidate markets — its family, using Polymarket's CLOB API (`clob.polymarket.com`), enumerated by cursor (the complete universe: 2.87 M conditions). Category comes from the CLOB `tags` field; multi-candidate families come from the `neg_risk_market_id` field. Joining the tape to this metadata by token id covers **100 % of cohort-1 trading volume**.

**One honest data caveat (the migration confound).** Sample B is the *new* platform. When we compare a v2 statistic to its v1 value, we are seeing *fees + the migration together*. To isolate the fee we use (a) the fee-free control category that exists in both eras (geopolitics), (b) difference-in-differences that nets out changes common to all categories, and (c) the trend across successive v2 cohorts (all under the same architecture, so differences there are fees, not migration).

## 7. Methodology

- **Unit of analysis** varies by question: a *fill* (incidence), a *taker order* (order size, round trips), a *(maker, class)* pair (concentration), a *family-hour* (no-arbitrage band).
- **Class scheme.** We assign every market to one of 8 categories (crypto, sports, politics, geopolitics, finance, culture, esports, other) from its tags, using the same mapping on v1 and v2 so the two are comparable. A market with several tags is assigned by a fixed precedence rule.
- **Fee status.** A fill is fee-paying if its on-chain fee > 0; a class is "fee-paying" if ≥ 50 % of its taker orders pay. Geopolitics is the fee-free control (31 % fee-paying in v2 vs 94–100 % elsewhere).
- **"Unchanged" claims use equivalence tests (TOST), not the absence of significance.** To claim fees did *not* change something, we require the effect to fall inside a pre-set band (e.g. ±25 % for concentration), which is the correct way to assert a null.
- **"Changed" claims use difference-in-differences** with the fee-free control, so any shock common to all categories (crucially, the migration) cancels out. Standard errors are clustered at the class level, with a wild-cluster bootstrap because the number of classes is small (8). Across the primary hypotheses we apply a Holm multiple-testing correction.
- **Key assumptions, stated for the paper:** (1) the fee formula `0.10·shares·min(p,1−p)` (verified to the cent on Sample A); (2) the tag→class mapping; (3) that a token's last trade price in an hour is a usable "quote" for the no-arbitrage sum (a known approximation — the on-chain tape has no order-book depth, so the spread is a proxy); (4) the migration confound above.

Everything is reproducible: the pipeline is seeded and deterministic, intermediates are parquet files, and each figure/table has a script.

## 8. Results

**Consolidated (strong):**
- **RQ4 incidence — regressive.** The effective fee rate falls monotonically from 3.0 % of notional (a trade's dollar value, price × shares) for the smallest taker orders to 1.15 % for the largest (cohort 1); 96 % of taker orders are fee-paying; post-rollout entrants bear ~5.7× the exposure of pre-2024 wallets. Exact fee formula verified.
- **RQ1 no-arbitrage band — the headline positive result.** On v1, the median deviation |Σ YES − 1| widens from 0.012 (fee-free) to 0.031 (fee), a +3.4–4.2 pp (percentage-point) increase robust to fixed effects (controls that absorb fixed differences across categories and periods). On v2 cohort 1, fee families sit at **0.020 — inside the predicted (0.012, 0.031] range**: the widening replicates. Interpretation: fees make it cheaper to move a candidate's price out of line before arbitrage corrects it — a manipulation-resilience result with a measured magnitude.

**Cohort-1 confirmatory (v2), with the migration caveat:**
- **RQ2 wash — no rise.** Self-matching is exactly 0 of 84.3 M fills (a structural property of the exchange, in both eras). One-step round trips are small and only mixed-slightly-higher under fees (4/7 classes within ±1 pp).
- **RQ3 market quality — fee-null, migration-large.** Netting out the migration, fees show **no** effect on maker concentration or order size. But the migration itself is a *large* shock: taker order size fell ~2.7 log points (a natural-log change, ≈ % change for small moves) across *every* class including the fee-free control, and maker concentration shifted. That uniform drop is the migration (and the explosion of tiny "hourly" markets in v2), not the fee — which is itself a clean natural-experiment finding.

**The single most important methodological result:** cohort 1 shows that a v2 snapshot compared to v1 conflates fees with the migration, and the migration dominates the raw levels. This *validates the design*: the clean fee identification comes from the within-v2 cohort trend (cohorts 2–6, in collection now), and the migration is a publishable natural experiment in its own right.

Full numbers and the exact tests: `docs/cohort_reports/cohort1_2026-08-31.md`.

## 9. Project scope, venue, and reproducibility

**Data.** Two on-chain tapes: v1 (complete, ~24 GB, validated public archive) and v2 (under reconstruction, ~17 GB so far, ~51 GB at completion), plus the complete market/metadata universe (2.87 M conditions) and on-chain resolutions. Analyses: fee incidence, the negRisk no-arbitrage band, wash/round-trip measures with null models, maker-concentration and order-size DiD, and (in progress) order-flow attribution and settlement integrity.

**Venue and schedule.** A finance/fintech journal (Journal of Financial Markets, Journal of Banking & Finance, or Management Science fintech) for the main paper; a CS-venue companion (FC/AFT) for the v2 tape and settlement integrity. The core (RQ1, RQ4, methodology) can be drafted now; cohorts 2–6 slot in as they complete (~2–3 Sep for collection).

**Writing order.** Introduction, institutional background, and related work are the highest-value places to begin — they do not depend on the last cohorts. RQ7 (informed-trading persistence) is a natural standalone empirical section, connecting directly to the informed-trading literature.

**Main direction.** Fees and the migration as a two-step natural experiment on market integrity — with RQ1 (no-arbitrage band widening) as the positive headline, RQ4 (regressive incidence) as the policy result, well-identified nulls on market quality, and the migration as the structural experiment.

**Division of labour.** Two natural tracks: (a) introduction, related work, and one empirical section (RQ7, or the make/take framing of RQ3); (b) the data pipeline, collection, and RQ1/RQ2/RQ4/RQ5/RQ6. A short results update accompanies each completed cohort.

**Reproducibility.** Result files and intermediates live under `data/parquet/` (not in the repository — too large; shipped separately or regenerated); cohort reports and analysis outputs are in `docs/cohort_reports/` and `docs/atlas_2026-08-30/`, and every headline number has a script under `scripts/` or the atlas `scripts/`. The environment is pinned — `requirements-lock.txt` (exact versions), `pyproject.toml` (dependencies), and the project virtual environment (required, because the base Python's older pyarrow cannot read the parquet files) — and documented in `REPRODUCING.md`. A minimal reproducible example ships in the repository: `examples/verify_export.py` recomputes the core statistics from exported CSVs with pandas only, and `examples/compare_outputs.py` checks a regenerated store against a reference snapshot.

**Status note.** The v2 pipeline and cohort-1 results now exist; the metadata coverage problem is fully solved (100 % via the CLOB cursor API), cohort 1 is validated and analysed, and the paper's spine has sharpened to: fees are largely integrity-neutral except the no-arbitrage band, and the migration is the dominant structural shock.

# Market integrity across Polymarket's fee and platform transition — research plan

*2026-08-30. Builds on `docs/atlas_2026-08-30/` (Sample A results), `PROJECT_OVERVIEW.md` (Stage I nulls), `docs/stage2_preregistration.md` and `docs/stage2_cohorts.md` (Sample B).*

## 1. Positioning

Three things are settled. (i) The cross-sectional questions about Polymarket v1 — informed trading at population scale, wash-trading networks, order-book stylized facts, price impact on the 2024 election — have been answered on complete data in 2026 (Mitts & Ofir; Gómez-Cram, Guo, Kung & Jensen; Sirolly, Ma, Kanoria & Sethi; arXiv:2604.24366, 2603.03136, 2606.16852, 2606.04217). (ii) Our own manipulation-detection signals are null once measured correctly, and the public feeds mislead in documented ways (`PROJECT_OVERVIEW.md §3–5`). (iii) Polymarket changed regime twice in 2026: taker fees phased in by category from January to April, and a full platform migration (new exchanges, CLOB, collateral, per-market maker rebates, order-flow attribution, no self-crossing) on 28 April. No published work covers either change, and no public archive exists after 28 April.

Our unique assets: the complete v1 tape (validated row-for-row against our on-chain reconstruction), the only complete v2 tape (validated by conservation and re-fetch invariants), on-chain resolution ground truth for every market, a two-step identification design (Jan→Apr isolates fees with v1 contracts unchanged; Apr→Jun isolates the migration with fees in place on both sides), fee-exempt categories as within-period controls, and a pre-registered explore/confirm protocol.

## 2. Research questions

Status: **C** consolidated (Sample A result with numbers), **P** partial (Sample A result with identified limits), **N** planned (Sample B or later). Each RQ lists the literature it extends, the data, the identification, the statistics, the prediction and the publication target.

### RQ1 — Do transaction fees loosen the no-arbitrage constraint that keeps multi-outcome prices consistent? (C on v1; N on v2)
- *Extends:* Saguillo et al. 2025 (combinatorial arbitrage in negRisk families); SoK §3.3 (negRisk gadget). Nobody has measured fee effects on cross-candidate consistency.
- *Data:* hourly family price sums S over negRisk candidates; v1 Oct 2025 → Apr 2026 (16,718 families, 311 k hours); v2 cohorts 1–6.
- *Identification:* fee vs fee-free families within month × family-size × class (v1); fee-band size as continuous treatment; v2 cohorts as replication under a different fee formula.
- *Result so far:* median |S−1| 0.012 (fee-free) → 0.031 (fee); +3.4 to +4.2 pp with FE, SE 0.002–0.003; signed mean unchanged. Registered v2 prediction: 0.012 < median < 0.031 (lower effective fee), positive band coefficient.
- *Contribution:* fees widen the band within which cross-market prices can be inconsistent — and be moved — before arbitrageurs correct them: a manipulation-resilience result with a known theoretical magnitude.

### RQ2 — Do fees and maker rebates change wash-like activity, and does the platform's architecture bound it? (P on v1; N on v2)
- *Extends:* Sirolly et al. 2025 (network wash volume up to 60 %), arXiv:2604.24366 (two-tier wash-suspect bound — self-match or flipped pair within 128 blocks — median 0.97 %), arXiv:2606.16852 (liquidity-reward manipulation).
- *Data:* counterparty-exact fills; v1 Oct 2025 → Apr 2026; v2 cohorts with on-chain rebate flows (`FeeCharged`, fee receiver `0x115F…ccc9`).
- *Identification:* staggered DiD across 105 treated tags vs 218 never-treated (v1); v2 replication; rebate-farming test directly on rebate receivers (v2 only).
- *Result so far:* self-matching is exactly 0 in v1 and v2 (the CLOB never crosses a wallet with itself — this settles component (a) of the published two-tier bound; it does not contradict the 0.97 % median, which must then be flipped pairs, and we will decompose that rule on the same window); one-step round trips 1–2 % of volume, lower in fee fills in 7/8 classes; DiD +0.1–0.3 pp, n.s.; concentrated pairs ≤0.02 % of fee volume. Limits: ≤8 post weeks, market-vintage confound.
- *Prediction (registered H1):* no rise under v2 fees; rebate concentration reported.
- *Contribution:* the first fee-regime evidence on wash-like activity with exact counterparties, and a structural correction to the literature's self-match measures.

### RQ3 — Did the fee rollout and the migration change liquidity provision and market quality? (P on v1; N on v2)
- *Extends:* Colliard & Foucault 2012; Malinova & Park 2015; Battalio, Corwin & Jennings 2016 (make/take fees; never tested on a prediction market); arXiv:2604.24366 (52-day stylized facts).
- *Data:* category-week panels of maker HHI, top-5 share, realized-spread proxy, taker order size, participation, volume; v1 (4,100 tag-weeks, 80 treated / 103 never-treated tags) and v2 cohorts.
- *Identification:* staggered DiD (CS-style) with never-treated controls for the fee step; April→June before/after by class for the migration step; dose (weekly fee share) robustness.
- *Result so far:* concentration and spread: no pre-trend, no effect (HHI CI ±25 %, spread ±0.5 c); volume/participation/order size not identified (treated categories were growing; ≤3 post weeks for 49 % of tags); order size negative in every spec. v2 supplies the missing post-period.
- *Prediction (registered H3–H4):* provider structure unchanged; order size lower under fees.
- *Contribution:* the first prediction-market test of make/take theory, with a fee that scales with p(1−p) and a zero maker fee — a setting with no equity analogue.

### RQ4 — Who pays the fee, and is the incidence regressive? (C on v1; N on v2)
- *Extends:* market-design / consumer-protection literature; new for prediction markets.
- *Result so far:* zero exemptions; fee = 0.10·shares·min(p,1−p); within-market rate 7.9 % of notional for small long-shot takers vs 4.4 % for the largest; post-rollout entrants pay 5.7× pre-2024 wallets via exposure (69 % vs 12 % of volume in fee categories), not rate. Level caveat: verify platform take against fee-receiver transfers (v2 makes this exact).
- *Prediction (H5):* same regressive pattern under v2; exact revenue and rebate accounting from chain.

### RQ5 — Where does order flow come from, and do integrity signatures differ by channel? (N; v2 only)
- *Extends:* nothing directly — order-flow attribution has never been observable on a prediction market; related to broker-routing and PFOF literatures in equities.
- *Data:* v2 `builder` codes (June: 728 codes, 87 % of taker orders unattributed = native front-end), per-fill fees.
- *Statistics:* fill share, wallet counts, fee incidence, order size, maker/taker mix, round-trip and pair measures, informed-trading signatures by builder; concentration of third-party flow (HHI 0.84).
- *Exploratory in cohort 1; registered for cohorts 2–6 once hypotheses are formed.*

### RQ6 — Did the post-migration fix for settlement-layer failures hold, and which vectors remain? (N)
- *Extends:* arXiv:2606.16852 (ghost fills = reverted `matchOrders`; 1.95 M reverts Aug 2025 → 6 May 2026; the 24.3 % hourly peak on 4 May 2026 was on the **v2** contracts, cut to 0.3 %/day by the Deposit Wallet upgrade; public BigQuery code).
- *Data:* reverted `matchOrders` to the v2 exchanges from 6 May 2026 onward (their BigQuery recipe on the public Polygon dataset, or Etherscan `txlist` on the two v2 exchanges), joined to our cohorts.
- *Prediction:* the post-fix daily revert rate stays ≤ 0.5 % through the cohorts; residual reverts are allowance revokes and proxy traps rather than balance drains. Extends a published series by three months with the same measure.

### RQ7 — Do informed-trading signatures persist across regimes? (N)
- *Extends:* Gómez-Cram et al. (sign-randomization skill test; 3.14 % skilled), Mitts & Ofir (composite informed-trading score), ForesightFlow ILS with the FFIC documented-case inventory (CC-BY).
- *Data:* v1 Jan–Apr (fees in) and v2 cohorts; position-level calibration with the reliability-curve benchmark; on-chain resolution times.
- *Identification:* same wallets across regimes (v1→v2 migration is observable by address); documented cases as validation; activity-preserving nulls.
- *Prediction:* fees reduce informed *taker* participation (Kyle-type); skilled-minority share stable or lower under fees.

### RQ8 — What can public Polymarket data support about manipulation? (C)
- *Result:* Stage I nulls replicated on the complete tape; feed-vs-tape universe overlap 20/134; whales are 96 % makers; Gamma volume = share count; `end_date`/`close_at`/`resolved_at` pitfalls; ERC-1155 fills as edges; ~71 % of binary share volume is minting and the tape-only rule under-identifies it 2.7×.
- *Contribution:* the measurement paper (partly pre-empted on "feed ≠ tape", not on its consequences), and the validation of the public v1 archive against an independent reconstruction.

## 3. Papers

| paper | RQs | venue tier | data | timing |
|---|---|---|---|---|
| **A. Measurement & nulls** — "What public Polymarket data can (not) tell you about manipulation" | RQ8 (+ archive data note) | workshop / short paper; arXiv now | Stage I + Sample A | draft in 4–6 weeks |
| **B. Fees, rebates and market integrity across the transition** (main) | RQ1–RQ4, RQ7 | finance journal (JFM / JBF; Management Science fintech) | Sample A + cohorts 1–6 | draft at ~12 weeks after cohort 6 |
| **C. Order-flow attribution and settlement integrity in v2** | RQ5–RQ6 (+ v2 tape release, CC-BY) | AFT / FC main track | cohorts 1–6 | parallel to B |

Paper A carries the corrected Stage I story and protects priority on the pitfalls; B is the journal target with the two-step identification as its spine and the integrity results (RQ1–RQ2) as its headline; C is the CS-venue paper where the v2 tape itself is a contribution.

## 4. Design commitments

- Two-step identification: Jan→Apr (fees; contracts fixed) and Apr→Jun (migration; fees fixed); fee-exempt categories as controls in both, if v2 retained the exemption (checked first in cohort 1 — contingency registered).
- Cohort time series: six two-week v2 cohorts, each gated (`scripts/11`) and analysed; cohort 1 confirmatory, 2–6 replication; effects that fade or reverse across cohorts are reported as such.
- Nulls and controls everywhere: activity-preserving nulls with BH for pair statistics; matched placebo controls for any wallet-following claim; class/family-clustered SEs with wild bootstrap when G ≤ 12; Holm across primary hypotheses.
- Threats addressed by design: market vintage (fee status attaches at birth) → dose and within-vintage comparisons; seasonality/event mix → class × calendar controls and never-treated classes; platform growth → week FE and never-treated trend; fee-level uncertainty → on-chain fee-receiver accounting in v2.
- Reproducibility: every table from parquet intermediates with scripts in the repo; archive and tape validated by invariants; pre-registration committed before Sample B statistics.

## 5. Data status

| asset | coverage | status |
|---|---|---|
| Polymarket-v1 archive (CC-BY) | 2022-11 → 2026-04-28, all markets | on disk (24 GB), validated 171,126 = 171,126 |
| On-chain resolutions / token derivation | all markets | corpus done; v2 registry script ready |
| v2 tape (own) | cohort 1 ≈ 75 %, cohort 2 ≈ 20 %, cohorts 3–6 + genesis gap pending | crawling at ~50 chunks/h on four keys; ≈ 51 GB at completion |
| Gamma metadata for v2 (categories, families) | pending | requires an unblocked network (collaborator / EU VPS) |
| Stage I corpus, exports, Dune/Etherscan reconstructions | done | reference snapshots |

## 6. Work split (to decide)

Natural ownership units: [collaborator] — introduction and related work for A; RQ7 (informed-trading persistence with the FFIC inventory) or RQ3 (make/take framing) for B. [you] — data pipeline, gates, cohorts, RQ1–RQ2, RQ5–RQ6. Weekly cadence: cohort report every ~3 days while collection runs; paper A draft by week 6.

## 7. Risks

Bundled migration treatment (accepted; two-step design bounds it); fee exemption possibly gone in v2 (contingency); seasonality; third v2 contract (`0xe3333700…`, dust in June — tracked per cohort); Gamma access for categories; compute limits (memory caps, quota-bound collection ≈ 3 days for the summer tape).

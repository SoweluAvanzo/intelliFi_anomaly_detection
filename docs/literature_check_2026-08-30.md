# Can our nulls oppose the published positives? Literature check (2026-08-30)

Question: is Paper A's line "the literature's signals come from feeds → measured correctly they vanish" defensible against the papers that report non-null findings? Method: for each published positive, verify the data source, sample, definition, test and code availability from the primary text; compare with the exact scope of our null; where the tape overlaps, recompute the published statistic on our archive.

## Verdict in one line

**No — not as a contradiction.** Our nulls are scoped to the 100 highest-volume markets and to per-wallet samples too small to detect anything; every published positive is measured on a different population, period or definition, and where we can recompute a published number on our tape we *reproduce* it. Paper A must be reframed from "signals vanish" to "one validated tape reconciles the published measures and shows which differences are definition, sample and feed effects". The new measurement facts stand.

## Claim-by-claim

### 1. Skill / informed minority — our null is underpowered, not contradictory

Published: Gómez-Cram, Guo, Jensen & Kung (SSRN 6617059, Apr 2026): 1.72 M accounts, 210 k markets, 2023–2025, accounts with ≥ 10 events; event-level sign-randomization of PnL (10,000 draws); 3.14 % "skilled winners" (p < 0.05), 44 % persistence on a random hold-out; market makers (0.1 %) identified separately. No FDR control stated; code and account list not released (confirmed by arXiv:2605.02287, 2605.00459). Mitts & Ofir (SSRN 6426778): 93 k markets, ~50 k wallets, five-criterion composite on (wallet, market) pairs, buy-side ≥ $500; 210,718 flagged pairs, 69.9 % win rate; profitability is one of the criteria; code not released.

Ours (Sample A, recomputed today, `data/parquet/atlas/replications/sampleA_position_skill.parquet`): 14,941 eligible wallets, but positions per wallet are **median 6, p90 11, p99 22, max 52** because the sample is 100 markets. Only 2,504 wallets reach the ≥ 10-event floor the published test uses. Under BH across 14,941 wallets, only **550 wallets could be discovered even with a perfect record**; the minimum detectable calibration gap at 80 % power is 0.98 (median wallet) under BH and 0.45 uncorrected. Simulation: if 3.14 % of our wallets had a true +0.10 edge, BH finds **0 discoveries in 20/20 replications**; at +0.25, 0–1. The observed 152 wallets above posterior 0.95 (vs 747 expected) show taker orders in these markets slightly underperform the price paid — a statement about top-volume markets, not about the population.

Note: the published 3.14 % is itself *below* the 5 % false-positive rate of an uncorrected p < 0.05 tail; the evidence for a skilled minority rests on the 44 % out-of-sample persistence, not on the tail count. That is the quantity to target.

**Direction:** replicate platform-wide on the archive (all markets, all accounts with ≥ 10 resolved events, on-chain `ConditionResolution` as ground truth): (i) their sign-randomization tail count; (ii) their persistence split; (iii) our position-level calibration against the reliability curve with BH; release code and per-account labels. If persistence reproduces, RQ7 (persistence across fee regimes) rests on a replicated positive; if not, it is a documented, reproducible contradiction with public code — either is publishable. Cost: one full-archive scan (hours under the memory caps).

### 2. Wash trading — three published numbers, none contradicted; one reproduced today

- **Sirolly, Ma, Kanoria & Sethi (SSRN 5714122, Nov 2025):** complete on-chain history 2022-11-21 → 2025-10-12 reconstructed from Polygonscan transfer logs (both sides); network/cluster score iterated over the counterparty matrix; 24.2 % of all-time share volume flagged, weekly peak ~60 % (Dec 2024), Sports 45 %, Elections 17 %, Crypto 3 %; **the three largest markets receive no detections** (threshold criterion unmet); simpler pairwise analogue — dyadic open-and-close within 180 s — 7.5 % of share volume (6.0 % of dollars). Self-matches not discussed; mint/merge excluded. No code released.
  Ours: one-step round trips 1–2 % and concentrated pairs ≤ 5.3 % → ≤ 0.4 % for Oct 2025 → Apr 2026 (their period ends before ours starts; the airdrop era is over); our 100-market corpus is the region where their method also finds nothing. **No contradiction.** Their dyadic-180 s measure is recomputable on our archive (same tape) for their period — that is the validation to run.
- **Dubach (arXiv:2604.24366):** SF7 rule = maker == taker **or** flipped pair (maker, taker) ↔ (taker, maker) within 128 blocks, per market, count-based, 600 pre-registered markets, 2026-02-28 → 03-27, CTF Exchange v1 logs; median 0.97 %, p90 4.5 %, p99 10.6 %, max 22.2 %. Code, panel and per-market results public (GitHub `philippdubach/polymarket-microstructure`, Zenodo 10.5281/zenodo.19811426).
  **Replica on our archive today** (`docs/atlas_2026-08-30/sf7_replica.py`, 128 blocks ≈ 270 s): 600/600 panel markets, 4.01 M maker fills; **direct self-match component = 0 in every market**; flipped-pair component median 1.91 %, p90 8.9 %, p99 22.7 %, max 45.4 %; **Spearman ρ = 0.99 with his shipped per-market shares**. The ≈2× level difference is his denominator (raw `OrderFilled` rows including the per-taker-order row with the exchange as taker: 6.40 M rows vs our 4.01 M maker fills) and his one-partner-per-anchor flagging. So his 1 % is entirely flipped pairs; **our earlier statement that self-match = 0 "contradicts" his bound was wrong and has been corrected** in the atlas README, atlas B, research plan and outlines. The correct contribution: decomposition of a published bound on a validated tape, with ρ = 0.99 agreement.
- **Qin & Yang (arXiv:2606.04217, the archive paper):** wash proxy = directed trading cycles ≤ 5 hops within market-month (precision/recall "not independently validated"); fee-reform DiD on market-months: β = −0.00036 (SE 0.00004, t = −9.91, N = 1.30 M) with the authors flagging under-estimated SEs. Fee status by category-month dates. This partially pre-empts B3's "wash under fees"; our tag-week design with never-treated controls, verified fee flag (`fee_usdc > 0`), clustering and event-time plots is the defensible version and must cite theirs as the prior estimate.

### 3. Coordination / copy-trading — no published positive with a null model

Nechepurenko (2605.11640): DBSCAN on 2.3 days of April 2026 fills, "every run returned one dense cluster", no role identification. Tsang & Yang (2603.03136): 2024 election, capital flowed into both sides simultaneously — against single-actor steering; tick-rule signing, no SEs. Mitts & Ofir's insider heuristic (accounts created ≤ 7 days before an event, dormant after; 1,950 accounts) is descriptive. Our null (134 universe wallets, 100 markets, activity-preserving nulls, matched controls) is consistent with all of them and opposes none; it must be stated as scoped.

### 4. Concentration — the positives are maker-side and we agree

Archive paper Table 5: lifetime maker Gini 0.970, top-1 % 84.1 %; taker Gini 0.943, top-1 % 69.7 %. Nechepurenko: 68 whales = 28 % of 2.3-day notional. Our per-market taker Gini 0.94 and the atlas maker-concentration series (top-10 share 69 % → 9–12 %, 2023 → 2026) are consistent; the time dimension is ours. Not a null.

### 5. Mispricing at close — nobody claims persistence on complete data

Longshot bias (archive paper deciles; Le 2602.19520) is a return-by-price statement compatible with convergence; Saguillo et al. report $39.6 M realized arbitrage without addressing closes. Our convergence result is a measurement correction (`closed_time`/on-chain resolution vs `end_date`), not opposition.

### 6. Ghost fills — our C3 prediction was wrong

Shen et al. (2606.16852): BigQuery public Polygon receipts, failed `matchOrders` to the v1 Fee Modules and, from 2026-04-28, the v2 exchanges; 1.95 M reverts Aug 2025 → May 6 2026; "V2's daily revert rate runs more than an order of magnitude above V1's"; **the 24.3 % hourly peak (May 4) is on v2**; the Deposit Wallet upgrade on May 4 cut the daily rate from ~8 % to 0.3 % within two days. Code public (`shenyimings/ghost-hunter`). The migration therefore *increased* reverts before a separate fix removed them; C3 must ask whether the post-fix regime held from May 6 onward (our cohorts) and which vectors remain — with their query as the like-for-like baseline.

### 7. Feed critique — a published ally, not an opponent

Dubach: WebSocket-inferred direction agrees with on-chain on 0.59 of buckets — the strongest published warning about public feeds; ours concerns the Data API `/trades` (taker-only tail, 20/134 whale overlap, volume = shares, close references). Complementary.

## What this means for the papers

- **Paper A** → "Reconciling manipulation measures on Polymarket: replication and decomposition on a validated tape". A1 (feed vs tape) stands. A2 becomes *reconciliation*: recompute Sirolly's dyadic-180 s, Dubach's SF7 (done, ρ = 0.99) and the archive paper's cycle proxy on one tape and show what is definition, period and sample; report our scoped nulls as the top-volume complement to Sirolly's own exclusion of the largest markets. A3 becomes the platform-wide replication of the skilled-minority test with persistence and a calibration alternative, plus the power analysis that explains why market-subset studies cannot see it.
- **Paper B**: B3 cites the archive paper's fee DiD as the prior estimate and improves on it; the negRisk band result is untouched (no prior work).
- **Paper C**: C3 reframed as post-fix persistence and residual vectors; C1/C2 unchanged.

## Replications to run (all free, all on disk except R4)

| id | what | data | cost | status |
|---|---|---|---|---|
| R1 | Dubach SF7 decomposition on his 600-market panel and window | archive | minutes | **done** — ρ = 0.99, direct = 0 |
| R2 | Sirolly dyadic open-and-close ≤ 180 s, share volume, 2022-11 → 2025-10-12 (their 7.5 %), extended → 2026-04 | archive | full scan, hours | to run |
| R3 | Gómez-Cram sign-randomization tail + persistence + our calibration, all accounts ≥ 10 resolved events | archive + CTF resolutions | full scan, hours | to run |
| R4 | Ghost-fill revert series 2026-05-06 → today (their BigQuery recipe or Etherscan `txlist` on the v2 exchanges) | external | free tier | to run |

# Update for [collaborator's name] — answers to your three questions, an audit of our pipeline, and what it changes

*Draft prepared 2026-08-30. Items in [brackets] are for [your name] to fill in or decide.*

Dear [name],

Thank you for the three questions — they pushed us to do something we should have done before sharing any figure: a full correctness and methodology audit of the pipeline. The short version is that the audit found real problems, that we have fixed them, and that **the corrected results are materially different from the figures in the overview you received**. This note answers your questions, explains each problem and its fix with the numbers, and proposes where the project goes from here. Please treat everything you received before this note as superseded.

## 1. Your three questions

**Result files.** The CSV bundle now contains every figure the pipeline reports — nothing is computed only inside a notebook anymore. Besides the raw tables (markets, trades, holders, price histories, on-chain transfers) and the derived outputs (universe, communities, coordination, backtest, convergence), the bundle now includes the intermediate tables that were previously notebook-only: the per-market and per-family concentration tables (Gini, HHI, top-N shares, for gross notional, net directional flow and holdings), the `bets` table underlying every skill statistic, the full Beta-posterior skill table with prior/posterior parameters and credible intervals, the position-level skill table (the headline statistic, see §3), a cost-basis-aware PnL table, the reliability curves, and the resolved winners. One trap to know: three columns are named `calibration_gap` and mean different things — `universe.csv` holds the raw size-weighted gap used only to select wallets; `skill/wallet_skill.csv` the legacy size-weighted posterior; `skill/position_skill.csv` the position-level posterior, which is the one to cite. The README data dictionary documents each.

**Environment.** `requirements-lock.txt` (Python 3.13.5, every package pinned with `pip freeze`) ships inside the bundle and in the repository. Only pandas and numpy are needed to read the CSVs; the lock file matters if you re-run the pipeline.

**Minimal reproducible example.** `verify_export.py` (inside the bundle) recomputes, from the raw CSVs with pandas only, the resolved winners, the bets table, both calibration gaps, per-market Gini/HHI and the cotrade pairs, and checks them against the exported tables to 1e-6 — all six checks pass. If you clone the repository, `REPRODUCING.md` explains the full re-run: analysis stages are deterministic given the parquet store (seeded community detection, order-independent graph construction, explicit tie-breaks), two independent re-runs agree on every table, and `examples/compare_outputs.py` verifies a regenerated store against the reference snapshot. The parquet store itself is shipped as `polymarket_parquet_store.tar`. [Where the files are: link / transfer method.]

## 2. What the audit found

We ran three independent code audits and one methodology review, then verified every flagged item empirically. The problems fall into three groups.

**Data properties we had misread.**
- The public `/trades` feed is the **taker side only** of the ~4,000 most recent fills per market. 92 of our 100 markets hit the cap; about 90 % of sampled trades execute at prices ≤ 0.05 or ≥ 0.95, i.e. after the outcome was effectively known. We later reconstructed complete fill histories from the chain: the largest market's feed held 4.7 % of its taker orders and 2,595 of its 21,293 wallets, and the "top wallets" we had been studying are **96 % market makers**, of whose fills the feed showed a median 20 %.
- Gamma's `end_date` is the scheduled deadline, not the close of trading; the actual close (`closedTime`, which we verified equals the on-chain resolution timestamp to the second) differs by a median of 21 hours and by weeks in both directions.
- Gamma's `volume` fields are **share volume** (shares × $1 face value), not USDC paid — verified exactly against complete on-chain histories.
- ERC-1155 transfers between wallets are the settlement of CLOB fills, not relationships.
- The 2026-05-11 price histories cover only the 30 days before the fetch (the CLOB `interval` parameter is a lookback window), so only 19 markets had series.

**Methodological problems.**
- The mirror backtest's "random control" was drawn from a wallet universe selected on realised PnL and hit rate in the same markets, so it was not a control; the 5-minute horizon used the resolution payout while markets were still trading; leader trades placed after the outcome was priced in were included.
- The "wash trading" counts were combinatorial (one BUY matched to many SELLs) and lacked any maker signature: the headline wallet buys at 0.996 and sells at 0.999 with a 50 % buy fraction — a tick-scalping market maker.
- Coordination pairs (co-trading, lead–lag) had no null model; the lead–lag ordering depended on how same-second rows happened to be scanned.
- The skill statistic treated every share as an independent Bernoulli trial, so the prior was inert and intervals were overconfident by orders of magnitude; PnL counted sells without an in-sample cost basis as short positions held to resolution.

**Code bugs** (all fixed): convergence measured from `end_date`; ERC-1155 transfers as graph edges; family-level concentration duplicating rows and mis-aggregating volume; non-deterministic community labels and lead–lag results across runs; a resolution threshold that would have labelled unresolved markets as resolved.

## 3. How the results change

Every number below is produced by the corrected pipeline and reproducible from the bundle.

| Claim in the overview you received | Cause | Corrected result (same 100 markets, feed sample) |
|---|---|---|
| A heavy tail of markets stays mispriced until close (mean 1-h error 0.13–0.17, p90 0.42) | offsets measured from `end_date` | mean 1-h error **0.0006**; no late-mispricing tail |
| 65 communities; a 44-wallet on-chain entity with $98.5 M | ERC-1155 fills read as relationships; a market maker as shared neighbour | USDC-only graph: six components of 2–6 wallets |
| 61 lead–lag pairs with 2–4 s lags "indicative of copy-trading" | no null model; scan-order tie handling | 3 of 75 pairs exceed an activity-preserving null (BH q < 0.05); not interpreted as copying |
| 19 wash-trading wallets; top one 138 round-trips, $970 k | combinatorial matching; no maker check | relabelled "rapid position flipping"; top wallet is a tick-scalping maker |
| Skilled and clustered leader sets earn 2–2.5× the random control at 1 h | control drawn from the outcome-selected universe; payout leakage | matched placebo controls match or beat every leader set |
| Calibration gap as wallet skill (1,301 wallets) | shares as trials; 93 % of weight at converged prices | position-level test: 12 eligible wallets, none significant |

We then replicated the whole chain on the **complete v1 fill tape** (the public Polymarket-v1 archive, arXiv:2606.04217, which we validated row-for-row against our own on-chain reconstruction: 171,126 = 171,126 fills over five markets' lifetimes) for the same 100 markets: 4.49 M taker orders from 607,584 wallets instead of 382,554 rows from 139,164.

| Statistic | Feed sample | Complete tape |
|---|---|---|
| Top-wallet universe overlap | 134 wallets | 139 wallets, only 20 in common |
| Cotrade pairs above null (q < 0.05) | 0 / 130 | 3 / 254 |
| Lead–lag pairs above null; with median lag ≤ 5 s | 3 / 75; 1 | 11 / 331; 0 |
| Backtest, leader vs matched control | equal within SE (n = 9–22 markets) | equal within ±0.01 (n = 50–67 markets) |
| Winner error 1 h before resolution (median / mean / p90) | 0.0005 / 0.0006 / 0.000 (19 markets) | 0.001 / 0.015 / 0.003 (100 markets) |
| Winner error 24 h / 14 d before (p90) | 0.003 / 0.40 | 0.19 / 0.69 |
| Position-level skill | 12 eligible, none significant | 14,949 eligible; 154 above posterior 0.95 where chance gives ~747; 0 BH discoveries |

**What this means for the research questions.** RQ1: the quantities can be computed, but on public data none of the three signals (concentration, round-trips, late mispricing) is a manipulation signal; prices are converged well before trading stops. RQ2: no coordination or copy-trading is detectable once activity-preserving nulls are applied. RQ3: no skilled minority is detectable among taker orders in these markets, and the feed cannot support wallet-level claims at all. The pipeline's substantive contribution today is therefore a set of well-controlled null results plus a documented map of how the public feeds mislead — not the detection findings the earlier overview described. We would rather tell you this now than after you had written around the old numbers.

## 4. What changed in the literature while we worked

Several 2026 papers, mostly still preprints, answer the cross-sectional versions of our questions on complete data: informed trading at population scale (Mitts & Ofir, SSRN 6426778; Gómez-Cram, Guo, Kung & Jensen — see arXiv:2605.02287 for the comparison), wash-trading networks (Sirolly, Ma, Kanoria & Sethi, 2025), order-book microstructure and the "feed ≠ tape" finding (arXiv:2604.24366; arXiv:2606.16852), price impact on the 2024 election (arXiv:2603.03136), the ForesightFlow insider-case inventory (arXiv:2605.00493), and the complete v1 archive itself (arXiv:2606.04217). The peer-reviewed anchors remain the SoK's sources, Saguillo et al. (AFT 2025), Eskandari et al. (AFT 2021) and Hanson (2007). Re-asking RQ1–RQ3 cross-sectionally is no longer a contribution; the measurement pitfalls above are partly pre-empted too (the feed's direction inference is known to be ~59 % accurate), though their downstream consequences for manipulation studies are not documented anywhere.

## 5. Where we propose to go

Polymarket phased in **taker fees with maker rebates** by market category from January to April 2026 (fee schedule v2 on 30 March; geopolitics/world events fee-exempt) and migrated to new exchange contracts on 28 April. That is a natural experiment with a built-in control group, testable on the complete archive for the pre-period and first treatment window, and on a v2 tape we are collecting from the chain (no published work covers v2). It maps onto a classic finance literature (Colliard & Foucault 2012; Malinova & Park 2015; Battalio, Corwin & Jennings 2016) never tested on a prediction market, and it lets the three research questions be asked *longitudinally*: liquidity provision and price impact under rebates; wash-like activity versus rebate farming; persistence of informed-trading signatures across regimes. We have written an explore/confirm protocol into the specification (explore on v1, register hypotheses, confirm on v2) so that nothing is retrofitted.

Current data: the complete v1 archive (2022-11 → 2026-04-28, ~24 GB, validated); on-chain resolution timestamps and token-id derivation for every market; the first v2 fills (31 hours: 7.5 M fills, 802 order-flow "builder" codes, on-chain fee incidence of ~98 bps of notional, and — a structural fact — zero self-matched fills, so v1-style self-counterparty wash measures do not transfer to v2). Three analyses on the archive (fee rollout and liquidity provision; wash and negRisk arbitrage bounds under fees; platform-wide minting, convergence and maker concentration) are in progress.

[Decisions for you to state: venue and timeline; which part you would like her to own — the related-work/introduction fits the measurement paper as it stands, and the insider-timing event study or the fee DiD are natural Stage II ownership units; weekly time.]

## 6. Practical notes

- Please discard the earlier bundle/overview if you received one; the current bundle (`polymarket_dataset_core.zip`, `polymarket_dataset_onchain.zip`, `polymarket_parquet_store.tar`) and the revised `PROJECT_OVERVIEW.md` (with a before/after table in its §5) supersede it.
- Cite from `skill/position_skill.csv`, `coordination/*.csv` (which carry `expected_events`, `excess_ratio`, `p_value`, `q_value`), `backtest/summary.csv` (leader rows and their `is_control` counterparts) and `convergence/*.csv`. Do not cite the notebooks; they still narrate the pre-audit figures and will be regenerated.
- Read `asset_id`, `token_id`, `condition_id` and `tx_hash` as strings; token ids overflow int64.
- If you want to work on the archive directly, it is public (CC-BY-4.0) but ~53 GB in full; we can share the validated Oct 2025 → Apr 2026 window and our loaders.

With apologies for the churn and thanks for the rigour of your questions,

[your name]

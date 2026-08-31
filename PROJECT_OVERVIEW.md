# A Market-Integrity Analysis Pipeline for Polymarket Prediction Markets

> Revised 2026-08-29 after a full correctness and methodology audit. Every
> figure below is produced by the current pipeline from the 2026-05-11 corpus
> and is reproducible from the shipped parquet store (see `REPRODUCING.md`).
> Findings that the audit showed to be artefacts of the data collection are
> reported as such; the earlier claims they replace are listed in §5.

## Abstract

We describe a reproducible data pipeline that reconstructs, from Polymarket's
public endpoints and the Polygon blockchain, the trading footprint of resolved
prediction markets and of the wallets active in them, and that scores
patterns *consistent with* market manipulation — concentration of flow,
rapid position flipping, coordinated trading, and wallets that beat the
probabilities they paid for. Applied to one hundred high-volume resolved
markets, the pipeline yields three substantive results: (i) prices are
almost perfectly converged by the actual close of trading (median winner
error 0.0005, mean 0.0006 one hour before close), so "late mispricing" is not
a feature of these markets once the true close time is used; (ii) neither
co-trading, lead–lag timing, nor mirroring any identifiable wallet group
produces evidence of coordination or exploitable edge once compared with an
activity-preserving null or a matched placebo control; and (iii) the public
trade feed is a taker-side, resolution-tail sample that cannot support
wallet-level skill or insider claims without on-chain order-fill
reconstruction — the pipeline's most important finding for anyone building
on this data. We document the pitfalls that produced the opposite
conclusions in an earlier version (scheduled deadline used as close time,
ERC-1155 settlement transfers read as relationships, in-sample controls).

## 1. Data acquisition

The pipeline draws on Polymarket's public, unauthenticated endpoints and on
the Polygon chain via Etherscan V2. The Gamma API supplies market and event
metadata, including negative-risk family linkage, the scheduled `end_date`
and the actual `closed_time` at which trading stopped. The Data API supplies
executed trades and holder snapshots, partitioned by condition identifier.
The CLOB API supplies per-outcome price histories. USDC.e, native USDC and
ERC-1155 transfers are recovered for the analysis universe of wallets.

Two invariants govern ingestion: every raw response is persisted before
normalisation, and partition keys are content-derived so loaders are
idempotent. All timestamps are coerced to UTC at the loader boundary.
Negative-risk markets are consolidated into families before flow is signed.

The corpus comprises 100 resolved markets (top-100 by CLOB volume with a
scheduled `end_date` in the 180 days before 2026-05-11), 382,554 trades,
62,831 holder rows, and a universe of 134 wallets (union of the top-50 by
traded notional, by realised PnL and by raw calibration gap) with their
on-chain transfer history.

**Properties of the trade sample that condition every result.** The Data
API returns the ~4,000 most recent fills per market and records the taker
side only (one row per fill; the maker is never present). 92/100 markets hit
the cap, and about 90 % of sampled trades execute at prices ≤ 0.05 or
≥ 0.95 — after the outcome was effectively known. On-chain reconstruction of
five markets (§2.6) shows what the cap hides: the largest market's feed
holds 4.7 % of its taker orders and 2,595 of 21,293 participating wallets,
and the universe wallets are 96 % makers, of whose fills the feed shows a
median 20 %. Gamma's `volume` fields are share volumes at $1 face value, not
USDC paid. `closed_time` differs from the scheduled `end_date` by a median of
21 h (range −5,433 h to +682 h): markets resolve early or are extended, and
25 % of all trades post-date `end_date`. Price histories cover the 30 days
before the fetch only (19 markets). Holder snapshots are capped at 500 per
outcome.

## 2. Analytical methods

### 2.1 Concentration

Gini, Herfindahl and top-N shares of per-wallet weight at market, family and
platform level, for three weights: gross taker notional, |net signed
notional| toward one outcome (a directional footprint that nets out
two-sided liquidity provision), and unredeemed holdings at snapshot time.

### 2.2 Wallet calibration

For each wallet, one Bernoulli trial per market: the wallet's net in-sample
direction, its size-weighted entry-implied probability, and whether that
direction won. Positions priced outside [0.05, 0.95] are dropped as
post-convergence. A Beta prior of strength 4 centred on the wallet's own mean
implied probability encodes the null "wins at the rate it paid for";
`calibration_gap` is the posterior mean minus that rate, with exact Beta
credible intervals and the posterior probability of a positive gap. Because
favourites in this corpus win more often than their price implies
(favourite–longshot bias), each trial is also benchmarked against the
leave-one-out corpus hit rate in its implied-probability decile. A
cost-basis-aware PnL scales sells with no in-sample buy by the covered
fraction of the position.

### 2.3 Entity resolution and coordination

An on-chain graph connects universe wallets through direct USDC transfers and
shared USDC counterparties; addresses that touch five or more universe
wallets (universe members included) are suppressed as hubs. ERC-1155
transfers are excluded: every CLOB fill moves outcome shares seller→buyer, so
such a transfer is evidence of a trade, not a relationship. A cotrade graph
connects wallets trading the same (asset, side) within a 300 s bucket.
Louvain (seed 42) recovers communities on each graph. Lead–lag pairs are
wallets trading in consecutive distinct seconds on the same (asset, side)
within 600 s. Both cotrade and lead–lag counts are compared with an
activity-preserving null (independent placement of each wallet's active
buckets/seconds within each stratum), giving per-pair excess ratios, Poisson
p-values and Benjamini–Hochberg q-values. Rapid position flips (BUY→SELL on
one asset within 600 s, ≥ 50 % size overlap) are matched one-to-one and
reported with each wallet's buy fraction and median price.

### 2.4 Mirror-strategy backtest

For each leader set, every signal-sized trade (≥ $1,000, price in
[0.02, 0.98]) placed before the market's `event_ts` — the last moment the
eventual winner still traded below 0.95 — is mirrored 60 s later at the next
minute's VWAP and exited at the last minute VWAP at or before four horizons
(5 min, 30 min, 1 h, 24 h), or at the payout if `closed_time` precedes the
horizon; 20 bps one-way fee. Every set is paired with a **matched placebo
control**: up to three trades by non-universe wallets on the same asset and
side within ±15 min and ±0.05 in price. Six leader sets: the largest USDC
transfer component, its cotrade twin, the top-50 by notional, the top-12 by
in-sample position skill, the top-29 by position skill on the earlier half
of the corpus evaluated on the later half, and 200 random non-universe
wallets. Inference is clustered by market.

### 2.5 Resolution convergence

Absolute error between the winner's price and 1 at fixed offsets before
`closed_time`, on the 19 markets with price history, stratified by market
type (deadline, resolved early, scheduled game).

### 2.6 On-chain fill reconstruction (prototype)

Every fill is an `OrderFilled` event on the CTF or NegRisk CTF exchange: one
record per maker order plus a taker-order record. Reconstructed from Dune and
validated against the feed with four invariants — every feed row matches a
taker-order record exactly in shares, price and side (12,532/12,532 on five
markets); shares conserve per transaction (105,711/105,711); coverage gain per
market; and completeness, since Gamma's `volumeClob` equals the sum of
taker-order shares exactly. This is the data source on which the wallet-level
questions can be re-asked.

## 3. Empirical results

**Concentration.** Mean per-market Gini is 0.94 on gross taker notional,
0.95 on net directional flow and 0.91 on holdings; the median top-1 wallet
share is 16 % (gross), 19 % (net) and 31 % (holdings). These are descriptive
statistics of a taker-side sample without a reference distribution; they
establish that a small number of wallets dominate visible flow, not that
those wallets move prices.

**Coordination.** The USDC transfer graph among the 134 universe wallets
contains 9 direct and 6 common-counterparty edges and six multi-wallet
components (sizes 6, 3, 3, 2, 2, 2). The cotrade graph has 130 pairs with
≥ 3 shared buckets; **none** exceeds its activity-preserving expectation at
q < 0.05 (median excess ratio 1.2). Of 75 lead–lag pairs with ≥ 5 events,
three are significant at q < 0.05 and only one has a median lag ≤ 5 s;
the tightest pairs involve automated near-resolution sweep and dust-
liquidation wallets. Nineteen universe wallets flip positions within ten
minutes; the most active (138 matched flips, $0.97 M) buys at 0.996 and sells
at 0.999 with a 50 % buy fraction — a tick-scalping market maker, not a wash
trader. We find no evidence of coordinated or copy trading in this corpus.

**Calibration.** Twelve wallets have five or more informative positions in
three or more markets. Their posterior calibration gaps range from −0.05 to
+0.07; none has a posterior probability of positive edge above 0.75, and the
maximum excess over the corpus reliability curve is 0.07. The corpus cannot
support per-wallet skill or insider claims: the trade tail is
post-convergence and taker-only.

**Mirror backtest.** At every horizon and for every leader set the matched
control earns the same or a higher mean net return, and leader–control
differences lie within the market-clustered standard errors (e.g. USDC
component at 1 h: +0.037 ± 0.027 vs control +0.038 ± 0.026; out-of-sample
skill set at 24 h: +0.029 ± 0.022 vs +0.041 ± 0.033; n = 8–22 markets per
cell). Positive 24-hour returns are shared by leaders and controls alike and
reflect drift toward resolution in the sampled tail. There is no exploitable
copy-trading edge in this data.

**Convergence.** Measured from `closed_time`, the median winner error is
0.007 at 14 days, 0.0025 at 3 days and 0.0005 in the final 6 hours; the mean
is 0.0006 at 1 h. A heavy tail exists only at ≥ 7 days (p90 0.22–0.40),
driven by deadline markets whose outcome was decided late. Polymarket prices
are, on this evidence, fully converged well before trading stops.

**Replication on the complete tape (Stage II, Sample A).** Every Stage I
statistic was recomputed on the public Polymarket-v1 archive — the complete
maker/taker fill tape, validated row-for-row against our independent
on-chain reconstruction (171,126 = 171,126 fills over five markets) — for the
same 100 markets, with the on-chain `ConditionResolution` timestamp as the
close reference (4.49 M taker orders from 607,584 wallets, versus 382,554 and
139,164 in the feed). The conclusions hold and sharpen: (i) the top-wallet
universe selected from complete flow shares only 20 of 134 wallets with the
feed-based one — the feed misidentifies who the large participants are;
(ii) coordination stays null (3 of 254 cotrade pairs and 11 of 331 lead–lag
pairs above the activity null, none with median lag ≤ 5 s; median cotrade
excess 0.35); (iii) every backtest leader set equals its matched control
within ±0.01 at 1 h and 24 h on 50–67 markets — the small positive drifts of
the feed sample were tail-sampling artefacts; (iv) convergence: on all 100
markets the median winner error one hour before resolution is 0.001 (mean
0.015, p90 0.003), 24 h before it is 0.002 (p90 0.19), and two weeks before
p90 is 0.69 — uncertainty resolves over the final days, not the final hour;
(v) position-level skill on 14,949 eligible wallets: 154 exceed posterior
0.95 where chance alone would give ~747, no Benjamini–Hochberg discovery, and
the posterior distribution sits below uniform (median 0.495) — taker orders
in these markets on average slightly underperform the prices they pay.

## 4. Implementation

Single-concern modules under `src/intellifi/` (unit of correctness), thin
per-stage scripts (`scripts/01`–`07`), and notebooks that read the parquet
outputs. Analysis stages are deterministic given the parquet store (seeded
Louvain, sorted graph construction, explicit tie-breaks); two independent
re-runs agree to floating-point summation order. `scripts/07_export_csv.py`
produces the CSV bundle with a data dictionary and a pandas-only verifier.

## 5. What changed in the 2026-08-29 revision

| Earlier claim | Cause | Status now |
|---|---|---|
| Heavy tail of markets "mispriced until close" (mean 1-h error 0.17, p90 0.42) | Offsets measured from scheduled `end_date`, not `closed_time` | Mean 1-h error 0.0006; no late-mispricing tail |
| On-chain entity of 16 wallets; 65 communities, largest 44 wallets / $98.5 M | ERC-1155 fill settlements treated as relationships; universe market maker acted as shared neighbour | USDC-only graph: six components of 2–6 wallets |
| 61 lead–lag pairs, 2–4 s lags "indicative of copy-trading" | No null model; scan-order-dependent tie handling | 3 of 75 pairs exceed an activity null; not interpreted as copying |
| 19 wash-trading wallets, top one 138 round trips / $970 k | Combinatorial matching; no maker signature | Relabelled rapid flipping; top wallet is a tick-scalping maker |
| Skilled/clustered leader sets earn 2–2.5× the random control at 1 h | Control drawn from the outcome-selected universe; 300 s horizon leaked the payout; post-outcome trades included | Matched placebo controls match or beat every leader set |
| Calibration gap as wallet skill (size-weighted, 1,301 wallets) | Every share a trial; 93 % of weight at converged prices; favourite–longshot bias | Position-level test: 12 eligible wallets, none significant |

The corrected pipeline's contribution is methodological: a reproducible
measurement stack for decentralised prediction markets with explicit null
models and controls, and a documented map of the ways the public data
misleads. Closing the trade-sample gap (on-chain `OrderFilled`
reconstruction, Phase 3 of the specification) is the prerequisite for any
positive claim about wallet skill, insider timing or coordination.

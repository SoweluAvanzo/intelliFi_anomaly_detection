# Wash-like activity and negRisk no-arbitrage bounds under Polymarket taker fees (Oct 2025 – Apr 2026)

Source: Polymarket-v1 public archive (`data/external/polymarket_v1/daily_aligned` + `daily_aligned_multi`), one row = one maker fill with the taker attached. Window: 2025-10-01 → 2026-04-28 (archive end). Totals: **663,507,158 fills, $20.133 B notional** (binary archive 568.7 M fills / $15.69 B; negRisk archive 94.8 M fills / $4.44 B). All computation in DuckDB (aggregation in SQL, parquet intermediates); every connection opened after the memory constraint was issued used `PRAGMA memory_limit='4GB'`, `PRAGMA threads=4`, `PRAGMA temp_directory=<scratch>/duck_tmp`, month-by-month; the pair roll-up additionally ran inside `systemd-run --scope -p MemoryMax=6G`. (The initial full scans s01/s03 earlier in the session ran with 16–18 GB DuckDB limits before the constraint existed; they are not re-run.) Outputs: `data/parquet/atlas/wash_*.parquet|csv` and `negrisk_*.parquet`.

## 0. Facts about the fee regime established from the data (needed to read everything below)

* **Fee formula.** On fee-paying BUY fills `fee_usdc = 0.10 × shares × min(p, 1−p)` exactly: the ratio has q10 = q50 = q90 = 0.100 in every class (2026-04-20, 8 classes, 391 k BUY fills). SELL rows carry the same quantity divided by price (median ratio to `shares×min(p,1−p)/p` = 0.100), so `fee_usdc` sums are inflated for low-price sells; I use `fee_usdc > 0` only as a flag, and the BUY formula for the theoretical fee band. Base rate 1000 bps (`taker_base_fee`) → max 5 % of notional at p = 0.5, 1 % at p = 0.9.
* **Fee status is a property of the market, not the fill.** On 2026-03-15 and 2026-04-15, **0 of 11,079 / 11,218** conditions have both fee and no-fee fills. In the negRisk archive **no family has both fee and no-fee hours** (3,880 fee families vs 12,838 no-fee families, disjoint). Fees were enabled for new markets by category; existing markets kept their status. Consequence: every "fee vs no-fee" contrast within a month compares different (newer vs older) markets.
* **Adoption timeline (weekly share of volume that is fee-paying, tag level).** Crypto "Up or Down" 0.68 in week of 2026-01-05, ≥0.97 from 01-12; Bitcoin/Ethereum/Solana tags ramp 0.45–0.55 (03-09) → 0.83–0.97 (03-30/04-06); Basketball 0.96 from 02-23; "Sports" tag 0.32 (03-16) → 0.76 (03-30) → 1.00 (04-20); Tennis 0.96 (03-30); Esports 0.91 (03-30) → 1.00; "Finance" tag 0.95 (03-30); NBA 0.65 (04-06) → 1.00; NFL 0.28 (04-20); Weather (negRisk) ≈ Apr. Never/barely treated: geopolitics_world 0.000–0.002 every week; politics ≤ 0.04 until the partial last week (0.47 on 04-27, Trump tag 0.65); culture ≤ 0.075. Class-level fee-paying volume share, Apr 2026: crypto 97.5 %, esports 98.9 %, sports 81.8 %, finance 55.0 %, culture 58.8 %, other 80.6 %, politics 2.2 %, geopolitics 0.0 %.
* **Category mapping.** 1,069 raw `category` tags (1,619 tag × refined pairs) → 8 classes by whole-word keyword rules on the raw tag (99.3 % of volume) with `category_refined` as fallback (0.7 %); file `data/parquet/atlas/wash_category_mapping.csv` (tag, refined, class, subclass, rule, volume, fee share, first fee day). Class volume shares Oct–Apr: sports 37.4 %, crypto (incl. up-or-down) 29.5 %, politics 9.3 %, geopolitics_world 8.8 %, esports 5.8 %, finance 3.5 %, culture 3.3 %, other 2.4 % (weather, tech, misc). Known judgement calls: "Middle East" (63 M under refined Sports) → geopolitics; "nyc"/"United States" → politics; "Games" → sports; "Weather" → other.

## 1. Q3 — wash-like activity by month, class and fee status

### 1(a) Self-counterparty share (maker == taker)

**Exactly zero.** 0 of 663,507,158 fills, $0 of $20.13 B, in every class, month and fee status (`wash_q3a_selfmatch_monthly_class_fee.parquet`). Also 0 (case-insensitive) on sampled days 2024-11-05, 2025-03-15, 2025-11-10, 2026-04-10 in both archives — i.e. the CLOB never crosses a wallet with itself. The archive is on-chain `OrderFilled` maker/taker pairs, so this is exact for the literal self-match definition; wash trading in this venue necessarily uses ≥2 wallets. (Not analysed further: 40,272 (asset, second, wallet) triples on 2026-04-10 where the same wallet was maker and taker in the same second against different counterparties.)

### 1(b) One-step round-trip share (same taker, same asset_id, opposite direction, ≤ 10 min, size overlap ≥ 50 %)

Taker orders = fills aggregated by (taker, asset, second, direction); a "closing leg" is an order whose immediately preceding order by the same taker on the same asset is opposite-direction within 600 s with min/max share ratio ≥ 0.5. Share = closing-leg volume / all volume ("either leg" counts both legs). Round trips crossing UTC midnight are lost (≈0.7 % of windows).

Platform (both archives), % of volume:

| month | volume $M | closing leg | either leg | closing leg ≤60 s | closing-leg orders % |
|---|---|---|---|---|---|
| 2025-10 | 1,313 | 2.14 | 3.67 | 1.13 | 6.61 |
| 2025-11 | 1,689 | 1.44 | 2.50 | 0.54 | 4.71 |
| 2025-12 | 2,173 | 1.45 | 2.57 | 0.71 | 5.11 |
| 2026-01 | 3,260 | 1.67 | 2.94 | 0.80 | 5.67 |
| 2026-02 | 3,363 | 1.75 | 3.08 | 0.97 | 5.19 |
| 2026-03 | 4,594 | 1.70 | 3.07 | 0.66 | 3.43 |
| 2026-04 | 3,739 | 1.08 | 1.96 | 0.50 | 2.94 |

Closing-leg share by class × month (all fills, %):

| month | crypto | culture | esports | finance | geopol. | other | politics | sports |
|---|---|---|---|---|---|---|---|---|
| 2025-10 | 2.17 | 0.91 | 0.86 | 1.65 | 1.11 | 2.22 | 7.54 | 0.92 |
| 2025-11 | 2.36 | 0.91 | 1.32 | 1.74 | 1.39 | 0.59 | 1.61 | 0.89 |
| 2025-12 | 2.93 | 0.80 | 1.74 | 1.62 | 1.29 | 0.61 | 0.77 | 0.69 |
| 2026-01 | 3.31 | 1.23 | 1.62 | 1.98 | 0.76 | 5.27 | 1.13 | 0.74 |
| 2026-02 | 2.72 | 1.69 | 1.27 | 2.21 | 0.96 | 4.21 | 1.48 | 0.95 |
| 2026-03 | 2.15 | 2.87 | 1.64 | 1.75 | 1.44 | 2.25 | 2.34 | 1.12 |
| 2026-04 | 1.92 | 1.10 | 1.43 | 0.72 | 0.43 | 0.51 | 0.63 | 0.90 |

(Politics Oct 2025 = "nyc" tag, 15.8 % of $58.5 M; "other" Jan–Feb = Pandemics/Tech tags, small volumes. Largest absolute contributor every month is "Up or Down": $11–20 M/month, 2.0–4.1 % of the tag.)

By fee status (closing leg, %): platform Jan fee 4.06 vs no-fee 1.34; Feb 3.03 vs 1.39; Mar 1.93 vs 1.58; Apr 1.27 vs 0.72. Within class, fee-paying vs no-fee fills:

| class | Mar fee | Mar no-fee | Apr fee | Apr no-fee |
|---|---|---|---|---|
| crypto | 2.15 | 2.20 | 1.77 | 8.06* |
| sports | 0.92 | 1.15 | 0.94 | 0.76 |
| esports | 1.46 | 1.65 | 1.43 | 1.79 |
| finance | 1.91 | 1.75 | 0.70 | 0.76 |
| culture | 0.58 | 2.88 | 0.99 | 1.26 |
| other | 0.43 | 2.33 | 0.40 | 0.99 |
| politics | 0.08 | 2.35 | 0.36 | 0.63 |
| geopol. | 4.50 | 1.44 | 0.22 | 0.43 |

*Apr crypto no-fee = residual old markets ($22 M) dominated by one bot pair (see 1c). The platform-level "fee > no-fee" gap is composition (crypto up-or-down markets had 2.4–3.8 % round-trip share already in Nov–Dec 2025, before fees); within class, fee-paying fills have a *lower* round-trip share than no-fee fills in 7 of 8 classes in April.

**DiD (tag-week panel).** Unit = tag (raw category × refined), week = Monday-start, outcome = closing-leg volume share, weights = volume (and unweighted). Treatment week g = first week with fee-paying share ≥ 0.5 sustained; never-treated = tags whose weekly fee share never exceeds 0.05; tags in between (44) dropped. Sample: tag-weeks with ≥ 200 taker orders, tags with ≥ 8 weeks; partial week 04-27 dropped. 105 treated tags (crypto 30, finance 25, sports 20, other 9, culture 8, politics 7, esports 6; cohorts 01-05 (5), 01-12 (3), 02-09 (1), 02-23 (3), 03-02 (3), 03-09 (8), 03-16 (5), 03-23 (7), 03-30 (19), 04-06 (13), 04-13 (24), 04-20 (14)), 218 never-treated (geopolitics 60, finance 39, politics 38, other 34, culture 17, crypto 15, sports 15), 5,838 tag-weeks. First stage on fee share: β = 0.798 (SE 0.058, tag clusters) / stacked 0.804 (0.038); event-time jump from 0 to +0.56 at k = 0 and +0.73–0.77 at k ≥ 3.

| spec | weights | β (share, pp) | SE tag-cluster (G=323/321) | SE class-cluster (G=8) | wild-cluster p (class, 256 draws) | N |
|---|---|---|---|---|---|---|
| TWFE static | volume | +0.282 | 0.133 | 0.167 | 0.070 | 5,838 |
| stacked static (−8…+8) | volume | +0.256 | 0.232 | 0.317 | 0.289 | 24,434 |
| TWFE static | unweighted | −0.528 | 0.223 | 0.254 | 0.219 | 5,838 |
| stacked static (−8…+8) | unweighted | +0.105 | 0.274 | 0.413 | 0.734 | 24,434 |

Event time (stacked, volume-weighted, ref k = −1, pp; SE tag-cluster / class-cluster; n = treated tag-weeks):

| k | −8 | −7 | −6 | −5 | −4 | −3 | −2 | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| β | 0.44 | 0.67 | 0.91 | 0.64 | 0.69 | 0.47 | 0.48 | 0.88 | 1.00 | 0.75 | 0.95 | 0.59 | 1.19 | 0.14 | −0.15 | −0.35 |
| SE tag | 0.45 | 0.44 | 0.56 | 0.37 | 0.36 | 0.34 | 0.41 | 0.42 | 0.38 | 0.44 | 0.42 | 0.35 | 1.02 | 0.39 | 0.43 | 0.44 |
| SE class | 0.53 | 0.42 | 0.29 | 0.24 | 0.32 | 0.37 | 0.33 | 0.57 | 0.54 | 0.68 | 0.56 | 0.38 | 0.47 | 0.45 | 0.45 | 0.52 |
| n | 82 | 77 | 86 | 84 | 87 | 83 | 81 | 87 | 83 | 60 | 51 | 32 | 25 | 20 | 11 | 11 |

Pre-period coefficients are all positive (+0.4 to +0.9 pp, none with |t| ≥ 2) and post coefficients +0.6 to +1.0 pp for k = 0…3 (t = 1.7–2.6), fading to ≈0 by k = 6–8 (n ≤ 20). By treated class (stacked static, never-treated controls, tag clusters): crypto −0.36 pp (SE 0.32), sports +1.05 (0.31), esports +1.16 (0.34), other +1.15 (0.36), culture +0.26 (0.29), finance −2.03 (0.83), politics −10.5 (1.44; 5 tags, late-April cohort, driven by one high-pre-period tag).

Reading: no robust change in one-step round-trip share at fee start; point estimates are +0.1 to +0.3 pp on a base of ~1.5 % (≈ +10–20 % relative) with class-clustered p ≥ 0.07, sign-unstable across weighting, and no persistence.

### 1(c) Volume between concentrated wallet pairs (counterparty HHI ≥ 0.5 with ≥ 100 fills, per period)

Per month (and per week for the panel), for every wallet: fills against each counterparty (as maker or taker, self excluded), HHI over counterparties; a wallet with ≥ 100 fills and HHI ≥ 0.5 is "concentrated" and its pair = (wallet, top counterparty). Share = volume of fills between flagged pairs / all volume; "reciprocal" = both wallets flagged with each other as top.

| month | wallets | wallets ≥100 fills | concentrated | flagged pairs | reciprocal pairs | median HHI (≥100) | pair-volume share % | reciprocal % |
|---|---|---|---|---|---|---|---|---|
| 2025-10 | 477,831 | 18,297 | 270 (1.48 %) | 174 | 96 | 0.023 | **5.28** | 3.96 |
| 2025-11 | 500,496 | 33,156 | 76 (0.23 %) | 59 | 17 | 0.020 | 0.044 | 0.011 |
| 2025-12 | 519,127 | 41,440 | 154 (0.37 %) | 111 | 43 | 0.020 | 0.059 | 0.046 |
| 2026-01 | 648,021 | 71,882 | 359 (0.50 %) | 237 | 122 | 0.016 | 0.372 | 0.259 |
| 2026-02 | 671,414 | 98,533 | 215 (0.22 %) | 183 | 32 | 0.016 | 0.198 | 0.123 |
| 2026-03 | 784,435 | 142,108 | 96 (0.07 %) | 92 | 4 | 0.015 | 0.021 | 0.000 |
| 2026-04 | 657,792 | 135,802 | 105 (0.08 %) | 100 | 5 | 0.013 | 0.114 | 0.093 |

By class (pair-volume share %, all fills): crypto 15.74 (Oct: Bitcoin 29.9 %, Ethereum 33.6 %, Solana 48.8 % of those tags, $51 M, reciprocal — a market-maker bot pair), 0.11, 0.14, 0.36, 0.05, 0.02, 0.40 (Apr: Bitcoin tag, $3.4 M reciprocal, all no-fee); other 2.38, 0.00, 0.04, 12.98 (Jan: Pandemics 94 %, Tech 34 % of tiny tags), 0.38, 0.06, 0.03; finance 0.10, 0.06, 0.00, 0.50, 2.95 (Feb: Earnings Calls 86 % of $1.3 M), 0.00, 0.00; sports ≤ 0.12 every month; esports ≤ 0.15; politics ≤ 0.30; geopolitics ≤ 0.19; culture 1.64 (Oct) then ≤ 0.28.

By fee status: **fee-paying fills 0.000 % (Jan), 0.000 % (Feb, $2.4 k), 0.020 % (Mar), 0.004 % (Apr)** vs no-fee fills 0.42 / 0.25 / 0.02 / 0.32 %. Concentrated-pair activity is essentially absent from fee-enabled markets.

DiD (same design; unit = raw tag; tag-weeks with ≥ 1,000 fills; flag recomputed within week): 75 treated / 96 never-treated tags, 3,096 tag-weeks. Pre-period levels: treated 1.78 % vs never 0.05 % (the Oct 2025 crypto bot pair). TWFE volume-weighted −0.365 pp (SE tag 0.413; class 0.249; wild p = 0.023 — unstable, see next rows); stacked +0.204 (0.174; 0.144; p = 0.219); unweighted TWFE −1.171 (0.524; 0.632; p = 0.227); stacked unweighted +0.115 (0.340; 0.415; p = 0.734). Event-time coefficients all within ±0.5 pp (|t| < 2) except k = +5 (+1.7 pp, SE 1.4, n = 17). By class: finance −5.4 pp (SE 1.4; the Feb "Earnings Calls" episode ends as tags become fee-enabled), crypto +0.39 (0.29), all others |β| < 0.1 pp.

### Rebate-farming hypothesis (directional)

Maker rebates are **not observable per fill** in v1 data (no maker-side fee/rebate column; `maker_base_fee` = 0 everywhere), so the test is indirect: if taker fees fund maker rebates, a farmer must generate taker-fee-paying volume against its own maker quotes. (a) Literal self-matching is impossible (0 fills). (b) Round-trip share in fee-paying fills does not rise relative to controls (DiD +0.1…+0.3 pp, p ≥ 0.07, transient), and within class it is lower than in no-fee fills in April (7/8 classes). (c) Concentrated maker–taker pairs carry ≤ 0.02 % of fee-paying volume in every month, versus 0.02–0.42 % of no-fee volume and 5.3 % platform-wide in Oct 2025. **Direction: self-matching / paired wash activity did not rise in fee categories; the measurable wash-like proxies fell or were unchanged.** A farmer using many rotating wallets with dispersed counterparties would evade all three measures; that is the residual hypothesis, not a finding.

## 2. Q4 — negRisk family price sums under fees

Method: `daily_aligned_multi`, YES tokens (`outcome_seq = 1`), per (family = `neg_risk_market_id`, hour): last traded price per candidate; candidate "alive" if it traded before the hour ends and again at/after the hour starts (first/last trade in the archive); hour kept only if ≥ 80 % of alive candidates traded within the hour, ≥ 3 alive candidates, every alive candidate has a price ≤ 24 h old (carry-forward for the ≤ 20 % non-traded), and the hour precedes the family's last trade hour. S = Σ last prices; dev = S − 1; fee status = fee-paying share of the hour's volume > 0.5 (equivalently market vintage, see §0). Fee band = 0.10 × Σ min(p, 1−p) = taker cost of buying the whole basket.

Coverage: 20,752 families / 128,523 conditions in the window; 1,567,426 family-hours with any trade → 358,318 with ≥ 80 % coverage → 324,030 with ≥ 3 candidates → **311,474 usable family-hours from 16,718 families** (3,880 fee families / 50,364 hours; 12,838 no-fee / 261,110 hours; families disjoint by status). Pre-period Oct–Dec 2025: 72,081 hours, 4,742 families.

| month | status | fam-hours | families | mean S−1 | SE (family-cluster) | p50 |S−1| | p75 | p90 | p95 | share >1 c | >5 c | >10 c | mean fee band | mean alive |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-10 | no-fee | 17,547 | 1,492 | −0.0056 | 0.0020 | 0.012 | 0.032 | 0.081 | 0.154 | 0.591 | 0.160 | 0.083 | 0.066 | 10.3 |
| 2025-11 | no-fee | 25,290 | 1,852 | −0.0027 | 0.0012 | 0.012 | 0.030 | 0.070 | 0.118 | 0.582 | 0.151 | 0.061 | 0.068 | 10.6 |
| 2025-12 | no-fee | 29,244 | 2,158 | −0.0151 | 0.0016 | 0.013 | 0.031 | 0.076 | 0.145 | 0.601 | 0.160 | 0.074 | 0.068 | 10.5 |
| 2026-01 | no-fee | 41,446 | 2,570 | −0.0159 | 0.0014 | 0.013 | 0.032 | 0.074 | 0.136 | 0.596 | 0.159 | 0.070 | 0.068 | 11.2 |
| 2026-02 | no-fee | 49,393 | 3,138 | −0.0137 | 0.0012 | 0.014 | 0.033 | 0.080 | 0.142 | 0.608 | 0.168 | 0.076 | 0.071 | 11.0 |
| 2026-03 | **fee** | 4,224 | 363 | +0.0026 | 0.0032 | **0.032** | 0.066 | **0.140** | 0.264 | 0.823 | 0.337 | 0.153 | 0.089 | 9.9 |
| 2026-03 | no-fee | 72,300 | 3,624 | −0.0127 | 0.0009 | 0.013 | 0.033 | 0.072 | 0.116 | 0.597 | 0.159 | 0.062 | 0.073 | 10.6 |
| 2026-04 | **fee** | 46,140 | 3,738 | −0.0134 | 0.0010 | **0.030** | 0.060 | **0.114** | 0.204 | 0.788 | 0.322 | 0.120 | 0.078 | 8.9 |
| 2026-04 | no-fee | 25,890 | 1,434 | −0.0146 | 0.0025 | 0.010 | 0.025 | 0.066 | 0.110 | 0.526 | 0.130 | 0.060 | 0.064 | 13.1 |

Pooled: pre-period (Oct–Dec 2025) p50 |S−1| = 0.012, p90 = 0.075, p95 = 0.137; no-fee Mar–Apr 2026 0.012 / 0.071 / 0.114; **fee Mar–Apr 2026 0.031 / 0.116 / 0.209**. Share of hours with |S−1| larger than the full-basket fee band: fee 23.9 % vs no-fee 16.9 %. Sign: S > 1.01 in 48.2 % of fee hours vs 27.9 % of no-fee hours; S < 0.99 in 30.8 % vs 31.2 % (buy-the-basket under-pricing is unchanged; over-pricing of the basket is more common under fees, consistent with sellers of the basket now needing the fee cushion).

Regression (family-hour, OLS, SE clustered by family, G = 16,718; identical on all months or Mar–Apr only because status is family-fixed):

| outcome | fixed effects | β(fee) | SE | N |
|---|---|---|---|---|
| |S−1| | month | **+0.0339** | 0.0022 | 311,474 |
| |S−1| | month × size-bucket × class | **+0.0417** | 0.0027 | 311,474 |
| S−1 | month | +0.0040 | 0.0024 | 311,474 |
| S−1 | month × size-bucket × class | −0.0037 | 0.0023 | 311,474 |

Within size bucket (Mar–Apr 2026, p50 / p90 |S−1|, no-fee → fee): 3 candidates 0.010/0.056 → 0.010/0.090; 4–6: 0.008/0.066 → 0.021/0.480; 7–12: 0.016/0.081 → 0.037/0.111; 13+: 0.013/0.057 → 0.039/0.300. By class (Apr 2026 p50 |S−1|, fee-hour share): crypto 0.036 (98 %), other/weather 0.033 (90 %), esports 0.021 (77 %), sports 0.010 (47 %), politics 0.013 (16 %), finance 0.014 (24 %), culture 0.019 (43 %), geopolitics 0.010 (2 %). Robustness with traded-only prices and 100 % coverage: fee Mar 0.034/0.163, Apr 0.029/0.117 vs no-fee 0.010–0.011/0.056–0.070.

Reading: fees widen the median no-arbitrage band by ≈ +2 pp at the median and +3.4 to +4.2 pp on average, roughly **half** the theoretical taker cost of the full basket (mean fee band 7.9 pp in fee families; the marginal arbitrage is usually a partial basket or a maker-side trade, so half is plausible). The signed mean is unchanged (−1.2 to −1.5 pp in every group), so the band widens symmetrically around a slightly under-priced basket.

## 3. Threats to validity

1. **Taker-side attribution.** The archive identifies maker and taker per fill, so self-match is exact and pairs are exact; but multi-wallet wash (≥ 3 wallets, rotating counterparties) is invisible to (b) and (c). Round trips are defined on taker orders only (a maker whose quote is hit twice is not counted). Fill rows for one taker order are aggregated per second; orders split across seconds count as separate orders.
2. **Fee status = market vintage.** Fee-enabled markets are those created after each category's switch; within-month fee/no-fee contrasts confound fees with market age, remaining lifetime and novelty (e.g. fee families in Q4 are mostly 7–12-candidate events). The tag-level DiD addresses this for Q3 (tag composition changes as old markets expire, which is the treatment); for Q4 there is no within-family switch, only the stratified regression.
3. **Short post-period.** The archive ends 2026-04-28; most sports/finance/esports cohorts have ≤ 4 post weeks (event-time n ≤ 25 for k ≥ 5); the 04-27 week is 2 days and dropped. Politics/culture were only just being switched.
4. **Category granularity.** Raw tags are the market's first tag; some tags are heterogeneous ("Games", "Other", "Sports") and the negRisk archive's `category_refined` equals its raw tag. Class clusters G = 8 → wild-cluster bootstrap p-values reported; tag clusters (G ≈ 170–320) are the primary inference.
5. **Q4 pricing.** Last traded price ≠ quote; hours require ≥ 80 % of alive candidates to trade (biased to liquid hours); ≤ 24 h carry-forward; "alive" inferred from first/last trade (resolved candidates drop out, `resolved_at` is NULL for 100 % of rows here and never substituted by `close_at`).
6. **Measurement noise in pair flags**: the ≥ 100-fill threshold within a week is stricter than within a month, so the weekly DiD panel under-counts pairs in small tags (hence the ≥ 1,000-fills filter).

## 4. Novelty vs cited work

* **Sirolly, Ma, Kanoria & Sethi (2025)** infer wash trading from network patterns and report peaks near 60 % of volume (Dec 2024). For Oct 2025–Apr 2026 the direct on-chain counterparty measures give far smaller magnitudes: concentrated-pair volume 5.3 % (Oct 2025) then ≤ 0.4 %, one-step round trips 1.1–2.1 % of volume — a different period and a narrower, counterparty-exact definition rather than an inference. New here: the measures are broken out by fee status and the fee switch is used as a quasi-experiment.
* **Anatomy paper (arXiv:2604.24366)**: reports a wash-suspect lower bound (median 0.97 % of trades per market, p99 10.6 %, max 22.2 % over a 600-market panel, 2026-02-28 → 03-27). **Correction (2026-08-30 literature check):** the rule is two-tier — "(a) maker == taker (direct self-match), or (b) a flipped pair (maker_a, taker_a) ↔ (taker_a, maker_a) within 128 blocks on the same market" — and the two components are not reported separately. Our 0-of-663.5 M result settles component (a) only; it does **not** contradict the 1 % figure, which is presumably all component (b). The right comparison is to recompute his rule on our archive for his window and panel (code and panel are public: GitHub philippdubach/polymarket-microstructure, Zenodo 10.5281/zenodo.19811426) and decompose it.
* **Saguillo et al. (2025)** measure combinatorial arbitrage in negRisk families in a fee-free regime. New: the fee regime shifts the empirical band — median |S−1| 0.012 → 0.031, p90 0.075 → 0.116, +3.4–4.2 pp regression-adjusted with family-clustered SE ≤ 0.003 — about half the theoretical basket fee, with 16,718 families / 311 k family-hours.

## 5. Verdicts

* **Q3(a) self-match**: *not supported* — self-counterparty fills are exactly zero in the v1 tape (self-trade prevention at the CLOB); publishable as a structural fact (wash in this venue needs ≥ 2 wallets) and as the direct-self-match component of the Anatomy two-tier bound — not as a contradiction of it.
* **Q3(b)/(c) round-trip and paired wash under fees**: *needs more* — null/transient DiD (+0.1…+0.3 pp round trip, p ≥ 0.07; pairs ±0.2 pp), concentrated pairs absent from fee-paying volume (≤ 0.02 %), but post-period ≤ 8 weeks and treatment is entangled with market vintage; extend past 2026-04-28 and add maker-side round trips before publishing. Rebate farming: directionally *not supported* in any of the three proxies.
* **Q4 negRisk band under fees**: *publishable* — large, precise widening of |S−1| (+3.4 to +4.2 pp, SE 0.002–0.003, 16,718 families) with no shift in the signed mean, subject to the market-vintage caveat.

## Files (data/parquet/atlas/)
`wash_category_mapping.csv`, `wash_q3a_selfmatch_monthly_class_fee.parquet`, `wash_q3b_roundtrip_monthly_class_fee.parquet`, `wash_q3c_pair_hhi_monthly_class_fee.parquet`, `wash_q3c_pair_hhi_wallet_stats_monthly.parquet`, `wash_did_{firststage,roundtrip,pairhhi}_{static,eventtime,byclass}.parquet`, `negrisk_family_hour_sums.parquet` (311,474 rows), `negrisk_q4_summary_month_fee.parquet`, `negrisk_q4_meandev_clusterSE.parquet`, `negrisk_q4_by_class_month.parquet`, `negrisk_q4_fee_regression.parquet`. Scripts and logs in the scratch dir `atlasB/` (`s01`…`s09`, `catmap.py`, `did.py`).

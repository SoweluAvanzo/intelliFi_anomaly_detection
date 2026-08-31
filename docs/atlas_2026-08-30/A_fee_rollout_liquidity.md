# Polymarket taker-fee rollout (Jan–Apr 2026): treatment timing, liquidity-provision DiD, and fee incidence

Atlas A — computed 2026-08-30 from the public Polymarket-v1 archive (arXiv:2606.04217) on disk at `data/external/polymarket_v1/`, daily files 2025_10_01 … 2026_04_28 (`daily_aligned` + `daily_aligned_multi`), 663.5 M maker-fill rows, 765,152 markets (condition_ids). No external API was called. All intermediate aggregates are persisted under `data/parquet/atlas/` (inventory in §9); scripts and logs are in the scratch dir `scratchpad/atlasA/`.

**Compute / memory.** Passes A (market-day) and B (weekly panel) ran before the memory constraint was issued, with DuckDB `memory_limit` 12–13 GB and 8 threads. Every pass executed after the constraint (C2/C3 per-taker aggregates, D2 first-seen history, Q2/Q3/extras analyses) opened DuckDB with `PRAGMA memory_limit='4GB'; PRAGMA threads=4; PRAGMA temp_directory='<scratch>/duck_tmp'` before any query, ran under `systemd-run --user --scope -p MemoryMax=6G -p MemoryHigh=5G timeout …`, aggregated in SQL, and never materialised more than ~0.6 GB in pandas (largest: 1.37 M taker rows). `statsmodels` is not in the venv; all estimators are numpy (two-way demeaning, Liang–Zeger cluster VCE with G/(G−1)·(N−1)/(N−K), cluster bootstrap).

## 0. One-line verdicts

| Q | Verdict | Why |
|---|---|---|
| Q1 Treatment identification | **Publishable** | Fee status is a market-birth attribute (345,605 / 345,646 fee markets charge from their first fill; 41 switchers, all on 2026-01-07). Category-level rollout is genuinely staggered across 11 weekly cohorts (Jan 5 → Apr 20) with a large never-treated block (geopolitics, macro, US politics). `taker_base_fee` is **not** a valid treatment indicator (9,583 markets, $1.07 B notional, carry `taker_base_fee=1000` but charge nothing); `fee_usdc>0` is. |
| Q2 Liquidity provision DiD | **Needs more** (concentration/spread: precise-enough nulls at market level, imprecise at category level; volume/order-size: not identified) | Category-week TWFE/CS: maker HHI, top-5 share and the minute round-trip-cost proxy show no pre-trend (Wald p = 0.78 / 0.76 / 0.32) and no post effect distinguishable from zero (CS ATT: HHI +0.0003 ± 0.0085; top-5 −0.006 ± 0.026; spread +0.0040 ± 0.0043 price units on a 0.029 baseline). Taker volume, participation and order size have strong pre-trends (treated categories were growing when Polymarket chose them) and cannot be attributed. The within-category×week market-level comparison (young fee vs no-fee markets) rules out a spread increase larger than ≈ +0.5 cents (CI [−0.003, +0.005]) and shows *less* concentrated, *broader* provision in fee markets. The post-period is short (≤ 3 weeks for 49 % of treated categories). |
| Q3 Fee incidence | **Publishable** (descriptive) | Zero taker-level exemptions: 0.0023 % of fee-charging-market notional is filled fee-free; the volume-weighted paid rate equals the schedule rate to 4 decimals in every size decile. Incidence differences are entirely category exposure × price mix. U-shape by size (1.84 % of notional for the smallest decile, 0.94 % for deciles 8–9, 1.54 % top decile, 1.77 % top 0.1 %). Newcomers pay 2.84 % vs 0.50 % for pre-2024 wallets because 69 % (vs 12 %) of their volume is in fee-charging markets, not because of a different within-market rate (4.10 % vs 4.23 %). |

## 1. Anatomy of the fee column (must read before using `fee_usdc`)

Empirically (2026-04-01, 4.6 M fee rows; `explore_month_category_feeparams.parquet` for all months):

* For taker-**BUY** rows, `fee_usdc / (shares · min(p, 1−p)) = 0.1000` (median, every price decile). This is the CTF-Exchange `calculateFee` SELL-side (collateral) formula with `feeRateBps = 1000`.
* For taker-**SELL** rows, `fee_usdc / shares = 0.1000` for p ≤ 0.5 and `= 0.1·(1−p)/p` for p > 0.5, i.e. the BUY-side formula **in share units** (`rate·min(p,1−p)·shares/p`). The archive therefore stores the fee in *outcome-token* units on taker-SELL rows and in USDC on taker-BUY rows.
* USDC value used everywhere below: `fee_val = fee_usdc · price` if `taker_direction='SELL'`, else `fee_usdc`. After the conversion the value is `0.10 · min(p,1−p) · shares` on both sides, which is `10 % of notional` for p ≤ 0.5 and `10 %·(1−p)/p` above. Exactly one rate (1000 bps) appears in the whole window; `maker_base_fee` is always equal to `taker_base_fee` (0 or 1000).
* **Level caveat.** This is the on-chain formula applied at 1000 bps. If Polymarket's effective schedule differs (e.g. a per-share rate), *levels* of fee revenue and incidence scale proportionally; *treatment status*, *timing*, *relative incidence* and all DiD estimates (which use fee-share-of-fills, not fee value) are unaffected. Verify against fee-collector USDC transfers on Polygon before quoting dollar revenue.
* `taker_base_fee > 0` does **not** mean fees are charged: 359,428 markets carry `taker_base_fee = 1000`, 13,783 of them charge on < 50 % of lifetime fills (in fact ≈ 0 %: politics_us 3,585 markets / $305 M, sports 3,941 / $311 M, geopolitics 497 / $95 M, culture 1,142 / $110 M). Within markets that *do* charge (≥ 50 % of lifetime fills), only 0.007 % of fills are fee-free. Treatment is therefore defined from `fee_usdc > 0`, never from `taker_base_fee`.

Fee revenue implied by the column (USDC-valued): Jan 2026 $15.7 M, Feb $32.4 M, Mar $66.5 M, Apr 1–28 $105.6 M; platform fee take rose from 0.53 % of taker notional (week of 2026-01-05) to 3.24 % (week of 2026-04-20) — `platform_week_totals.csv`.

## 2. Q1 — Treatment identification

### 2.1 Market level (`market_fee_start.parquet`, 765,152 markets)
* Fee start day = first day with `fee_usdc>0` on ≥ 50 % of fills. 345,646 markets have one; **345,605 (99.99 %) charge from their first traded day**; 41 switch mid-life, all crypto Up/Down markets switched on **2026-01-07** (median 2 fee-free days before); **0** markets revert to fee-free after starting.
* Consequence: a category's fee share rises as fee-bearing *new* markets replace legacy fee-free ones. Category-level treatment intensity is a market-vintage composition process; for the always-new short-horizon crypto series it is a step (0.53 → 0.78 fee share within one week), for long-lived categories (Politics, Soccer, NHL) it never crosses 50 % inside the archive.

### 2.2 Fee-class level (`q1_class_timing.csv`, 7-day rolling fee share of fills; `class_day.parquet` is the figure-ready daily series)

| class | first fee fill | first day ≥ 10 % | first day ≥ 50 % | April fee share (fills) | April fee share (notional) | notional Oct–Apr | fee value |
|---|---|---|---|---|---|---|---|
| crypto_updown | 2026-01-06 | 2026-01-07 | 2026-01-11 | 0.999 | 0.995 | $5.44 B | $129.2 M |
| crypto_other | 2026-03-05 | 2026-03-12 | 2026-03-18 | 0.683 | 0.439 | $0.52 B | $0.59 M |
| esports_tennis | 2026-02-18 | 2026-03-30 | 2026-04-02 | 0.981 | 0.985 | $1.92 B | $24.8 M |
| weather | 2026-03-27 | 2026-03-31 | 2026-04-03 | 0.995 | 0.994 | $0.18 B | $0.90 M |
| sports | 2026-02-18 | 2026-03-21 | 2026-04-06 | 0.609 | 0.785 | $6.78 B | $62.6 M |
| finance | 2026-03-08 | 2026-04-02 | 2026-04-08 | 0.628 | 0.734 | $0.27 B | $0.91 M |
| culture | 2026-03-24 | 2026-04-01 | 2026-04-10 | 0.551 | 0.526 | $0.74 B | $0.80 M |
| politics_us | 2026-03-04 | never | never | 0.060 | 0.022 | $1.76 B | $0.11 M |
| geopolitics_world | 2026-03-11 | never | never | 0.004 | 0.001 | $1.68 B | $0.08 M |
| finance_macro | 2026-03-11 | never | never | 0.050 | 0.006 | $0.62 B | $0.03 M |
| tech_science | 2026-03-31 | 2026-04-26 | never | 0.073 | 0.051 | $0.14 B | $0.03 M |
| meta_other | 2026-03-04 | 2026-04-01 | never | 0.386 | 0.306 | $0.10 B | $0.06 M |

Weekly fee share by class (`extras.log`, `class_week.parquet`): crypto_updown 0.53 (w/o 2026-01-05) → 0.78 → … → 0.99 (Mar 9 on); sports 0.01 (Feb 16) → 0.08 (Feb 23 – Mar 2, Basketball/NCAA) → 0.49 (Mar 30) → 0.55 / 0.59 / 0.77 (Apr 6/13/20); esports_tennis 0.91 (Mar 30) → 0.99; weather 0.94 (Mar 30) → 1.00; finance 0.26 → 0.60 → 0.71 → 0.67; culture 0.31 → 0.59 → 0.65 → 0.60; politics_us ≤ 0.08; geopolitics_world ≤ 0.01; finance_macro ≤ 0.06 throughout.

### 2.3 Category-tag level (`q1_category_timing.csv`; DiD unit)
Category = archive `category` tag (1,069 distinct tags in the window; 183 enter the main panel). Treatment date g = first of two consecutive weeks with fee share ≥ 50 %. **80 treated tags in 11 cohorts**: 2026-01-05 (Up or Down $2.97 B, Crypto Prices, Hide From New, 15M), 01-12 (Recurring, Ripple), 02-23 (Bitcoin $0.68 B, Basketball, NCAA Basketball), 03-02 (Crypto $1.13 B, Solana, XRP, NCAA, Neg Risk), 03-09 (Ethereum, Multi Strikes, 1H, 4H, BNB, Today), 03-16 (Weekly, Dogecoin), 03-23 (La Liga, Daily, New York City, COIN), 03-30 (Esports $1.12 B, Tennis $0.47 B, Games, Weather, Finance, Premier League, league of legends, EPL, MicroStrategy, bundesliga, Tweet Markets, Dota 2, Cricket, Inflation, HOOD), 04-06 (Sports $6.13 B, Culture $0.44 B, Equities, Trump Cabinet, Chess, CPI), 04-13 (Jerome Powell, NBA, SPX, YouTube, Big Tech, UFC, and 21 single-stock/index tags), 04-20 (MLB, counter strike 2, Celebrities, Hockey, Apple, South Korea). **103 never-treated tags** (max weekly fee share < 5 %, active in April): Geopolitics $0.69 B, World, Iran, Economy, United States, Gov Shutdown, Fed Rates, Middle East, Israel, Epstein, Foreign Policy, NYMEX Crude, President, Economic Policy, Venezuela, Awards, Trump Presidency, … (`q2_never_treated.csv`). 71 tags are partially treated (Politics 0.11 in April, Trump 0.06, Soccer 0.14, NHL 0.05, Movies 0.35, NCAA 0.42, Mentions 0.19, Formula 1 0.03 …) and are excluded from the binary design, included in the dose design.

**First stage.** In the panel, fee share of fills jumps by +0.60 at k = 0 and +0.66 to +0.80 at k ≥ 1 (TWFE, SE 0.03–0.06); the pre-period coefficients are ≈ −0.15 relative to k = −1 because fee share starts creeping in the week before crossing (`q2_twfe_eventstudy.csv`, outcome `fee_share`).

## 3. Category-tag → fee-schedule class mapping (`feeclass.py`, `category_to_feeclass_mapping.csv`, `class_mapping_coverage.csv`)

Twelve classes, assigned per *market* from (`category`, `category_refined`, `market_slug`), then a tag is summarised by its modal class. Rules, in priority order: (1) slug regex `updown|up-or-down|-above-|-below-|-dip-to-|-reach-|hit-\$|price-on|-ath-` together with a coin token → **crypto_updown** (also catches meta-tagged series such as "Hide From New", "Recurring", "Rewards …"); (2) an explicit dictionary of ~330 tags → class; (3) meta tags (`Rewards*`, `Depreciated*`, `Parent For Derivative`, `All`, `Neg Risk`, …) fall back to `category_refined` and then to slug patterns (`-vs-|-spread-|-moneyline` → sports; coin names → crypto_other); (4) residual → **meta_other**. 175 tags map to more than one class because of the slug override (e.g. "Crypto", "Bitcoin", "Ethereum" split between crypto_updown price series and crypto_other event markets).

| class | schedule class it proxies | tags | markets | notional share | top tags |
|---|---|---|---|---|---|
| sports | sports (league-by-league rollout) | 249 | 223,664 | 33.7 % | Sports, Basketball, Soccer, NBA, NFL, NCAA, CFB, Premier League |
| crypto_updown | "Up or Down"/crypto price series (Jan rollout) | 38 | 273,872 | 27.0 % | Up or Down, Crypto, Bitcoin, Crypto Prices, Ethereum, Hide From New, Recurring, Solana |
| esports_tennis | esports / tennis | 11 | 166,251 | 9.5 % | Esports, Tennis, Games, league of legends, counter strike 2, Dota 2 |
| politics_us | US politics | 200 | 13,467 | 8.7 % | Politics, Trump, United States, nyc, Epstein, President |
| geopolitics_world | geopolitics / world (fee-exempt) | 49 | 4,392 | 8.4 % | Geopolitics, World, Iran, Israel, Middle East, Foreign Policy, Venezuela |
| culture | culture / entertainment | 43 | 14,192 | 3.7 % | Culture, Movies, Awards, Mentions, MrBeast, box office, Music |
| finance_macro | macro / rates / policy (status ambiguous) | 14 | 1,674 | 3.1 % | Jerome Powell, Economy, Gov Shutdown, Fed Rates, Economic Policy, Trade War |
| crypto_other | crypto event markets | 68 | 11,100 | 2.6 % | Crypto, Bitcoin, Monad, Ethereum, Lighter, Airdrops |
| finance | equities / indices / commodities | 145 | 17,622 | 1.3 % | NYMEX Crude, Finance, Commodities, Pre-Market, SPX, Business, Gold |
| weather | weather | 3 | 28,045 | 0.9 % | Weather, Daily Temperature |
| tech_science | tech / AI / science | 74 | 2,804 | 0.7 % | Tech, AI, Gemini 3, Claude 5, OpenAI, Science |
| meta_other | operational tags, unmapped | 413 | 8,069 | 0.5 % | All, Rewards …, Parent For Derivative, Depreciated… |

Validation against observed April fee status (§2.2): the mapping separates the schedule cleanly — the three classes the schedule exempts (geopolitics_world 0.4 %, finance_macro 5 %, politics_us 6 % April fee share) versus 55–100 % for the treated classes. Two known impurities: `category_refined` is itself noisy ("Middle East" → Sports, "Monad" → Politics in the archive), and within `sports` the rollout is league-specific (NBA 0.67, NFL 0.56, Soccer 0.14, NHL 0.05, MLS 0.00 in April), so `sports` is a mixture of treated and not-yet-treated leagues; the DiD is therefore run at the tag level, not the class level.

## 4. Q2 — Liquidity provision under fees

### 4.1 Panel and outcomes (`q2_panel_category_week.parquet`)
Category-tag × ISO week, full weeks 2025-10-06 … 2026-04-20 (29 weeks; the partial weeks Oct 1–5 and Apr 27–28 are dropped). Tag-weeks with ≥ 100 fills; tags with ≥ 12 such weeks. Main sample: 183 tags (80 treated, 103 never-treated), 4,100 tag-weeks. Outcomes per tag-week, all computed in DuckDB from the raw fills (`category_week.parquet`):
* **taker volume** = Σ usdc_amount (log); **taker orders** = distinct (block_timestamp, taker, asset_id, taker_direction) (log); distinct takers / makers (log);
* **maker concentration**: HHI of maker volume shares and top-5 maker share (levels and logs);
* **round-trip-cost proxy**: within each (outcome token, minute) with both taker buys and taker sells, `vwap(taker BUY) − vwap(taker SELL)`, averaged over minute-pairs with weight min(buy vol, sell vol) — in price units (1 = $1 per share); `rspread` divides by the pair midpoint. 86 % of tag-weeks have a positive proxy; 82 % of minute-pairs are positive;
* **taker order size**: mean and median of order notional (log).
Baselines (treated tags, pre-period mean / median): HHI 0.063 / 0.032; top-5 0.349 / 0.304; spread proxy 0.0294 / 0.0123; mean order $83 / $49; median order $6.0 / $3.4; weekly notional $6.5 M / $0.09 M (`q2_panel_baselines.csv`).

### 4.2 Estimators
(i) **TWFE static**: y_ct = α_c + λ_t + β·1[t ≥ g_c] + ε, tag-clustered SE (G = 183). (ii) **TWFE event study**: indicators for k = t − g_c ∈ [−8, +8], binned at the ends, k = −1 omitted, never-treated tags carry zeros; pre-trend test = Wald test of k ≤ −2 (cluster VCE). (iii) **Callaway–Sant'Anna-style ATT(g,k)**: for each cohort g, mean of Y_{g+k} − Y_{g−1} over cohort tags minus the same long difference over never-treated tags; event-time aggregates weighted by cohort size; SEs from 400 cluster (tag) bootstrap draws; "post" = mean over k = 0…8, "pre" = mean over k = −8…−2 (a placebo). Robustness (`q2_robustness.csv`): continuous dose (weekly fee share) unweighted; binary D weighted by pre-period notional; dose on all 254 tags including partially treated ones.

### 4.3 Results (`q2_twfe_static.csv`, `q2_cs_summary.csv`, `q2_log_outcomes.csv`; event-time tables `q2_twfe_eventstudy.csv`, `q2_cs_eventtime.csv`, `q2_log_outcomes_eventtime.csv`)

| outcome | TWFE β (SE) | CS ATT post (SE) | CS "ATT" pre, placebo (SE) | pre-trend Wald p (k ≤ −2) |
|---|---|---|---|---|
| log taker notional | +0.172 (0.208) | −0.000 (0.223) | **+0.631 (0.190)** | 0.189 |
| log taker orders | +0.573 (0.180) | +0.141 (0.170) | +0.200 (0.138) | 0.961 |
| log distinct takers | +0.383 (0.148) | +0.215 (0.153) | **+0.280 (0.114)** | 0.676 |
| log distinct makers | +0.308 (0.132) | +0.121 (0.131) | **+0.247 (0.111)** | 0.512 |
| maker HHI (level) | −0.0032 (0.0061) | +0.0003 (0.0085) | −0.0099 (0.0063) | 0.779 |
| log maker HHI | −0.320 (0.135) | −0.025 (0.156) | −0.083 (0.111) | 0.802 |
| top-5 maker share | −0.022 (0.018) | −0.006 (0.026) | −0.029 (0.018) | 0.763 |
| log top-5 share | −0.141 (0.083) | +0.026 (0.099) | −0.065 (0.072) | 0.770 |
| spread proxy (price units) | +0.0062 (0.0041) | +0.0040 (0.0043) | −0.0098 (0.0057) | 0.323 |
| log spread proxy | +0.165 (0.134) | +0.243 (0.119) | −0.334 (0.216) | 0.519 |
| relative spread | +0.0006 (0.0138) | −0.006 (0.020) | −0.030 (0.022) | 0.786 |
| log mean order size | **−0.401 (0.095)** | −0.141 (0.123) | **+0.432 (0.098)** | **< 0.001** |
| log median order size | −0.164 (0.091) | −0.179 (0.176) | **+0.321 (0.116)** | **0.005** |
| fee share of fills (first stage) | +0.810 (0.021) | +0.658 (0.050) | −0.144 (0.021) | — |

Event-time detail (CS ATT, SE; number of treated tags contributing):
* **HHI**: k=0 −0.009 (0.010), k=1 −0.020 (0.007), k=2 −0.002 (0.012), k=3 −0.004 (0.010), k=4 −0.002 (0.014), k=5 +0.042 (0.027), k=6 −0.002 (0.016), k=7 +0.005 (0.008), k=8 −0.004 (0.011); pre k=−8…−2 between −0.019 and +0.001. Contributing tags: 65, 62, 37, 35, 21, 19, 17, 11, 9.
* **top-5 share**: k=0 −0.026 (0.025), k=1 −0.050 (0.021), k=2 −0.012 (0.033), k=3 −0.025 (0.037), k=4 −0.003 (0.046), k=5 +0.086 (0.049), k=6 −0.019 (0.056), k=7 +0.010 (0.028), k=8 −0.012 (0.055).
* **spread proxy**: k=0 −0.005 (0.007), k=1 +0.003 (0.014), k=2 −0.005 (0.006), k=3 −0.002 (0.007), k=4 +0.005 (0.010), k=5 +0.026 (0.008), k=6 +0.007 (0.005), k=7 +0.005 (0.005), k=8 +0.002 (0.006); pre −0.019 (0.005) at k=−8 rising to −0.011 (0.009) at k=−2 (spreads were compressing before treatment). Log spread: k=0 −0.16 (0.24), k=1 +0.18 (0.25), k=2 +0.05 (0.20), k=3 +0.01 (0.21), k=4 +0.35 (0.30), k=5 +0.96 (0.23, 18 tags), k=6 +0.26 (0.25), k=7 +0.31 (0.17), k=8 +0.22 (0.25).
* **log mean order size**: pre k=−8…−5 = +0.69, +0.68, +0.78, +0.48 (SE ≈ 0.14) falling to +0.03 at k=−2; post k=0…3 = +0.12, +0.23, +0.04, +0.35; k=4…8 = −0.44, −0.50, −0.55, −0.13, −0.37 (SE 0.14–0.36; 9–21 tags).
* **log taker notional**: pre +1.08, +0.98, +1.05, +0.77, +0.25, +0.29, −0.01 (SE 0.16–0.31); post +0.45, +0.66, +0.52, +0.61, −0.40, −1.08, −0.66, +0.03, −0.12.

Reading. (a) **Concentration**: no pre-trend, no post effect. In level terms the 95 % CI for the post ATT on HHI is [−0.016, +0.017] against a baseline of 0.063 (≈ ±25 % of the mean), on top-5 share [−0.057, +0.046] against 0.35 (≈ ±15 %); in logs, HHI [−0.33, +0.28], top-5 [−0.17, +0.22]. The TWFE static coefficient on log HHI (−0.32, SE 0.14) is driven entirely by k ≥ 6, i.e. the Jan crypto cohort, whose maker count grew 3× over the post period (composition, not a fee response); the CS long-difference estimator, which does not use those late observations as controls, is −0.02. (b) **Round-trip cost proxy**: point estimates are small and positive (+0.004 to +0.006 price units, i.e. +0.4–0.6 cents on a 2.9-cent mean / 1.2-cent median; log +0.17 to +0.24), the CI in levels is [−0.004, +0.012] and in logs [−0.10, +0.48]. The pre-period placebo is negative (−0.33 log, SE 0.22): spreads were narrowing in treated tags before the fee, so the post rise is at least partly mean reversion. The only large coefficient (k = +5, +0.96 log) rests on 18 tags in one calendar week. (c) **Volume, participation, order size**: the CS placebo "pre-ATT" is +0.63 log for notional, +0.43 for mean order size — Polymarket rolled fees out to categories whose activity had been rising relative to the controls over the previous two months (the CS placebo pre-ATT on log notional is +0.63, SE 0.19; the sports/esports cohorts were also entering their seasonal peaks). The TWFE event study for order size rejects parallel pre-trends (p < 0.001). These outcomes are **not identified** by the category-level design. Directionally, post-fee order sizes are smaller in every specification (TWFE −0.40 log mean, −0.16 log median; dose −0.46 / −0.12; weighted −0.43 / −0.24), consistent with fee-sensitive small takers not leaving and large takers splitting or scaling down — but the pre-trend forbids a causal reading.
(d) Robustness: dose and weighted specifications give the same signs; the weighted spec (pre-period notional weights) turns HHI/top-5/spread slightly positive and significant (+0.012 (0.003), +0.029 (0.014), +0.0058 (0.0017)) — the weights concentrate almost all mass on "Up or Down", so that spec is essentially a single-tag before/after and is not credited.

### 4.4 Design B — market level, within category × week (`q2b_market_level_within_catweek.csv`, `q2b_market_level_by_class.csv`)
Because fee status is fixed at market birth, the cleanest comparison is between *young* markets (age 0–3 weeks) that charge fees and young markets in the **same tag and same week** that do not (legacy series, fee-exempt sub-types). Sample: weeks 2026-01-05…04-20, markets with ≥ 50 fills/week, tag-weeks containing both types: 52,524 market-weeks, 279 tag-weeks, 76 tags, 32,023 fee-charging market-weeks. Regression: y = tag×week FE + age dummies + β·FeeMarket, tag-clustered SE.

| outcome | β fee market (SE) | interpretation |
|---|---|---|
| log notional | +0.59 (0.21) | fee markets are the more active new series |
| log distinct takers | +0.59 (0.13) | |
| log distinct makers | +0.46 (0.12) | |
| log taker orders | +0.64 (0.15) | |
| maker HHI | −0.038 (0.017) | less concentrated provision in fee markets |
| top-5 maker share | −0.079 (0.030) | |
| spread proxy | +0.0011 (0.0019) | CI [−0.003, +0.005] price units on a 0.02–0.03 baseline |
| log mean order size | −0.05 (0.25) | |
| log median order size | +0.11 (0.12) | |

By class (β for spread, SE): crypto_updown +0.0078 (0.0019) — the one class where fee markets show a wider minute round-trip (0.8 cents), with HHI −0.11 (0.01), top-5 −0.22 (0.02), takers +1.07 (0.09), order size −0.70 (0.07); sports −0.0012 (0.0017); esports_tennis −0.0088 (0.0073); finance −0.0089 (0.0127); culture −0.0079 (0.0052); politics_us −0.0036 (0.0038). The crypto_updown result is confounded by the type of comparator (the fee-free young crypto markets in the same week are longer-horizon "Monthly / Hit Price" series with different price dynamics), so it is reported, not credited.

### 4.5 Theory
Colliard & Foucault (2012) predict that the *split* of a fee between makers and takers is neutral for the cum-fee spread while the *total* fee matters; Malinova & Park (2015) show that a maker-rebate/taker-fee restructuring changed quoted spreads and the composition of liquidity providers. Polymarket's rollout is a **pure taker-fee increase with makers at zero** (the maker fee parameter is set but never charged), i.e. a total-fee change, so Colliard–Foucault predicts a lower raw (pre-fee) spread if competing makers pass part of the taker fee back, and Malinova–Park a change in who provides liquidity. What the data show: (i) the raw minute round-trip proxy does not fall — if anything it rises slightly (+0.4–0.6 cents, not significant), so there is no evidence of pass-through into tighter raw spreads; (ii) concentration of liquidity provision does not change at the category level and is *lower* in fee markets at the market level; (iii) the share of maker volume supplied by wallets first seen after 2026-01-05 rises from 15 % to 77–79 % in crypto_updown and from 5–10 % to 40–60 % in every other class, treated or not (`q3_maker_composition_class_week.parquet`) — provider turnover is platform-wide, not fee-driven.

## 5. Q3 — Fee incidence by participant (`q3_incidence_by_size_decile_v2.csv`, `q3_incidence_by_tenure_v2.csv`, `q3_incidence_tenure_x_size_v2.csv`, `q3_rate_by_logsize.csv`, `q3_taker_window.parquet`)

Window: full weeks 2026-01-05 … 2026-04-26; 1,369,645 takers, $14.44 B taker notional, $215.9 M fee value (1.50 % of notional; 4.31 % of notional inside fee-charging markets, which carry 34.7 % of notional). "Fee-charging market" = ≥ 50 % of lifetime fills carry a fee (345,645 markets). Tenure = first appearance (as taker *or* maker) anywhere in the archive from 2022-11-21 (full 2022–2025 history scanned, 2,651,203 wallets).

**No participant-level exemptions.** Inside fee-charging markets, fee-free notional is $0.116 M = 0.0023 % of $5.0 B; zero takers with > $10 k fee-market notional are > 90 % fee-free; the volume-weighted paid rate equals the schedule rate implied by each group's price mix (`0.10·Σ min(p,1−p)·shares / Σ notional`) to four decimals in every decile and tenure bucket. Incidence heterogeneity therefore decomposes exactly into **(share of volume in fee-charging markets) × (price mix)**.

By taker size decile (equal counts; decile 10 = ≥ $8,553 notional over the window):

| decile | n takers | notional | share of notional | fee % of all notional | median taker fee % | share in fee-charging mkts | fee % within fee-charging | avg price |
|---|---|---|---|---|---|---|---|---|
| 1 (< $4.2) | 136,965 | $0.19 M | 0.00 % | 1.84 | 0.00 | 23.2 % | 7.90 | 0.38 |
| 2 | 136,964 | $1.3 M | 0.01 % | 1.54 | 0.00 | 25.7 % | 5.99 | 0.60 |
| 3 | 136,965 | $4.4 M | 0.03 % | 1.33 | 0.00 | 26.1 % | 5.10 | 0.63 |
| 4 | 136,964 | $11.6 M | 0.08 % | 1.31 | 0.00 | 27.8 % | 4.69 | 0.66 |
| 5 | 136,965 | $26.3 M | 0.18 % | 1.17 | 0.00 | 29.8 % | 3.93 | 0.71 |
| 6 | 136,964 | $59.7 M | 0.41 % | 1.19 | 0.02 | 30.9 % | 3.85 | 0.74 |
| 7 | 136,964 | $134 M | 0.93 % | 1.07 | 0.02 | 31.3 % | 3.40 | 0.76 |
| 8 | 136,965 | $292 M | 2.02 % | 0.94 | 0.01 | 28.6 % | 3.27 | 0.78 |
| 9 | 136,964 | $716 M | 4.96 % | 0.95 | 0.00 | 27.8 % | 3.41 | 0.81 |
| 10 | 136,965 | $13.19 B | 91.4 % | 1.54 | 0.10 | 35.3 % | 4.38 | 0.75 |
| top 1 % (≥ $126 k) | 13,697 | $9.77 B | 67.7 % | 1.63 | 0.39 | 34.9 % | 4.68 | 0.73 |
| top 0.1 % (≥ $1.17 M) | 1,370 | $5.81 B | 40.2 % | 1.77 | 0.57 | 33.7 % | 5.25 | 0.69 |

Incidence is U-shaped. Small takers pay a high *rate within* fee markets (7.9 % for decile 1) because they buy long-shot low-price outcomes where `min(p,1−p)/p` is largest, but a majority of takers (median = 0) never touch a fee-charging market. The largest takers carry the largest fee-market exposure (35 %) and trade nearer p = 0.5 (rate 4.4–5.3 %), so the top 0.1 % pays 1.77 % of notional and 47.7 % of all fees. By log10(size) bin inside fee markets the paid rate is 3.80 % ($100–1 k), 3.37 % ($1–10 k), 3.56 % ($10–100 k), 3.84 % ($100 k–1 M), 5.20 % (> $1 M).

By tenure:

| first seen | n takers | notional | fee % of notional | share in fee-charging mkts | fee % within fee-charging | schedule rate given price mix |
|---|---|---|---|---|---|---|
| < 2024 | 1,656 | $0.11 B | 0.50 | 11.8 % | 4.23 | 4.23 |
| 2024 | 172,156 | $1.10 B | 0.75 | 18.2 % | 4.10 | 4.10 |
| 2025 H1 | 97,821 | $0.96 B | 0.80 | 17.5 % | 4.54 | 4.54 |
| 2025 Q3 | 40,113 | $0.94 B | 0.98 | 20.7 % | 4.73 | 4.73 |
| 2025 Q4 (pre-fee) | 232,358 | $3.44 B | 1.30 | 26.8 % | 4.83 | 4.83 |
| 2026-01-05 … 02-28 | 426,754 | $4.80 B | 1.44 | 35.3 % | 4.10 | 4.10 |
| 2026-03-01 … 03-29 | 237,793 | $2.07 B | 2.30 | 53.9 % | 4.27 | 4.27 |
| 2026-03-30 + (schedule v2) | 160,994 | $1.01 B | 2.84 | 69.3 % | 4.10 | 4.10 |

Wallets that entered after the fee schedule went live pay 5.7× the rate of pre-2024 wallets as a share of notional, entirely because 69 % of their volume is in fee-charging categories (crypto Up/Down, sports, esports) versus 12 %; conditional on trading in a fee market the rate is the same (4.1 %). The tenure × size cross-tab (`q3_incidence_tenure_x_size_v2.csv`) shows the exposure gradient inside every size bin (e.g. > $100 k takers: 11 % → 70 % fee-market share from oldest to newest cohort; fee % 0.48 → 3.38).

## 6. Threats to validity
1. **Fee-column convention and level** (§1): fee values on taker-SELL rows are in share units and were converted; the 1000-bps on-chain formula implies a 10 %-of-notional rate at p ≤ 0.5 — if the true effective schedule is lower, revenue and incidence levels scale down proportionally; nothing in §2 and §4 depends on the level.
2. **Treatment is vintage composition, not a switch.** Fees attach at market creation; category fee share rises as legacy markets expire. The category "date" is a threshold on a continuous process; results for dose (fee share) and binary D agree in sign.
3. **Selection of treated categories on growth.** CS placebo pre-ATTs of +0.63 (volume), +0.28 (takers), +0.43 (order size) show that fees were rolled out to categories that had been growing relative to controls; volume-type outcomes are not identified. Concentration and spread outcomes pass the pre-trend tests but the never-treated controls (geopolitics, macro, US politics) are structurally different markets (long-lived, event-driven, larger orders: control mean order $91 vs $83; median $7.2 vs $6.0).
4. **Short post-period.** The archive ends 2026-04-28; 33 of 80 treated tags have ≤ 2 post weeks, 39 (49 %) have ≤ 3; only the Jan–Feb cohorts (9 tags) reach k = +8. Event-time coefficients at k ≥ 4 rest on 9–21 tags and are dominated by crypto Up/Down.
5. **Category-tag granularity.** 1,069 tags, one per market, mixing topics (Sports) with operational labels (Hide From New, Recurring, Rewards …, Neg Risk) and duplicated concepts (Crypto/Bitcoin/Ethereum as both price series and event markets). The slug override fixes the main confusions; `sports` remains a mixture of leagues treated on different dates, handled by working at tag level and clustering by tag.
6. **Round-trip proxy limitations.** No quotes in the archive: the proxy needs both a taker buy and a taker sell on the same token within one minute (18 % of minute-pairs are negative — price drift dominates spread inside a minute); it measures effective round-trip cost for *takers in the same minute*, is weighted toward active tokens, and is unavailable for 6 % of tag-weeks (spread) and 14 % (log spread).
7. **Maker fee accounting.** `maker_base_fee = taker_base_fee` on every row; the fee value is recorded once per maker fill and could in principle be the maker's on-chain charge (Polymarket refunds makers off-chain). The incidence tables attribute it to the taker; if part of it were borne by makers the *taker* incidence would be lower but the cross-sectional pattern unchanged.
8. **Other April shocks.** The rollout coincides with March Madness/NBA playoffs (sports volume), a platform-wide activity decline (weekly notional fell 21 % from $1.10 B in the week of 2026-03-16 to $0.87 B in the week of 2026-04-20), and the 2026-04-28 exchange migration announcement; week fixed effects absorb common shocks only.
9. **Multiplicity.** ~11 outcomes × 3 estimators; isolated significant event-time cells (k = +5 spread, k = +1 HHI) should be read against ≈ 150 tested coefficients.

## 7. Novelty relative to the literature
* *Anatomy of a DePM* (arXiv:2604.24366) documents stylised facts for 52 days pre-migration; the fee rollout itself has not been studied. This is, to our knowledge, the first identification of the rollout at market level (fees attach at birth; 41 mid-life switches), the first staggered category-cohort map (11 cohorts, 80 treated / 103 never-treated tags), and the first evidence that `taker_base_fee` in the public archive/Gamma is a non-binding parameter.
* Maker–taker fee theory has been tested on equity venues with rebates (Malinova & Park 2015; Cardella et al.; Battalio et al.). A binary-outcome market with a **price-dependent fee (`rate·min(p,1−p)`)**, zero maker fee, and a category-staggered rollout is a new setting: the fee schedule itself makes incidence a function of the *price mix* of a participant's trades, which we quantify (7.9 % effective rate for the smallest, long-shot-buying takers vs 4.4 % for whales) — a regressivity channel with no analogue in equity fee schedules.
* The incidence decomposition (exposure × price mix, zero exemptions, 5.7× higher burden on post-rollout entrants) and the provider-composition series (new-maker share 15 % → 78 % in crypto Up/Down) are new descriptive facts. The DiD nulls on concentration and round-trip cost are informative at the market level (design B CI on spread [−0.3, +0.5] cents) but only weakly at the category level; a fully credible causal paper needs the post-28-April tape (v2 exchanges) to lengthen the post-period, quote-level data for true spreads, and league-level rollout dates for sports.

## 8. Reproduction
`scratchpad/atlasA/`: `common.py` (connection with PRAGMA memory_limit 4GB / threads 4 / temp dir; fee conversion), `feeclass.py` (mapping), `passA_market_day.py`, `passB_weekly.py`, `passC2_taker_chunks.py`, `passC3_taker_feechg.py`, `passD2_firstseen_hist.py`, `q1_timing.py`, `econ.py` (TWFE, cluster VCE, CS-style ATT with bootstrap), `q2_did.py`, `q2b_market_level.py`, `q2c_logs.py`, `q3_incidence.py`, `q3b_decomp.py`, `extras.py`; logs `*.log`.

## 9. Files written to `data/parquet/atlas/` (this task only; `wash_*` and `negrisk_*` files belong to other agents)
* Raw aggregates: `explore_month_category_feeparams.parquet` (month × category × fee params), `market_day.parquet` (2.61 M market-days), `market_class.parquet`, `market_fee_start.parquet`, `class_day.parquet`, `market_week.parquet` (1.2 M market-weeks, all Q2 outcomes), `category_week.parquet`, `class_week.parquet`, `taker_week_class.parquet` (taker × class × week), `maker_week_class.parquet`, `taker_week_feecharging.parquet`, `wallet_first_seen.parquet` (2.65 M wallets, 2022-11-21 onward), `platform_week_totals.csv`.
* Q1: `q1_class_timing.csv`, `q1_category_timing.csv/.parquet`, `q2_treated_cohorts.csv`, `q2_never_treated.csv`, `category_to_feeclass_mapping.csv`, `class_mapping_coverage.csv`.
* Q2: `q2_panel_category_week.parquet`, `q2_panel_baselines.csv`, `q2_twfe_static.csv`, `q2_twfe_eventstudy.csv`, `q2_cs_eventtime.csv`, `q2_cs_summary.csv`, `q2_log_outcomes.csv`, `q2_log_outcomes_eventtime.csv`, `q2_robustness.csv`, `q2_class_means.csv`, `q2_class_prepost_descriptive.csv`, `q2b_market_level_within_catweek.csv`, `q2b_market_level_by_class.csv`.
* Q3: `q3_taker_window.parquet`, `q3_incidence_by_size_decile_v2.csv`, `q3_incidence_by_tenure_v2.csv`, `q3_incidence_tenure_x_size_v2.csv`, `q3_rate_by_logsize.csv`, `q3_incidence_by_class.csv`, `q3_maker_composition_class_week.parquet` (the `_v1` decile/tenure files `q3_incidence_by_size_decile.csv`, `q3_incidence_by_tenure.csv`, `q3_incidence_tenure_x_size.csv`, `q3_exemption_by_decile.csv` use the non-binding `taker_base_fee>0` definition and are superseded).

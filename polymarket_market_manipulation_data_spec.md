# Polymarket Data Retrieval & Market-Manipulation Analysis Specification

**Version:** 1.0  
**Date:** 2026-05-11  
**Purpose:** Define how to retrieve Polymarket data and structure analyses for detecting suspicious market behavior using econometrics, probabilistic inference, machine learning, graph/network methods, and LLM-assisted research.  
**Important framing:** This specification supports **suspicion scoring and investigative triage**, not legal proof of manipulation. Any final claim of manipulation requires human review, legal review, and corroborating evidence.

---

## 1. Executive Summary

For a free or low-cost first implementation, use:

1. **Polymarket Gamma API** for market/event discovery and metadata.
2. **Polymarket Data API** for trades, wallet-level activity, holders, positions, and leaderboards.
3. **Polymarket CLOB API** for current order books, current prices/midpoints/spreads, and historical price series.
4. **Polymarket WebSocket market channel** to collect live L2 order-book data going forward.
5. **PMXT public archive** for free historical WebSocket/order-book parquet data where coverage exists.
6. Optional paid providers only when historical tick-level L2 is required beyond free coverage.

The central caveat is:

> Official Polymarket APIs provide free historical price series and wallet/trade data, but not full historical order-book depth for arbitrary past periods. To prove mechanical price impact, we need historical L2 order-book state immediately before/after each trade. For that, use our own collector going forward, PMXT where available, or a paid archive.

---

## 2. Source Map

| Data need | Free official source | Historical availability | Notes |
|---|---|---:|---|
| Market metadata | Gamma API | Yes | Market question, slug, `conditionId`, `outcomes`, `outcomePrices`, `clobTokenIds`, volume, liquidity |
| Current price / midpoint / spread | CLOB API | Current only | Public endpoints, no auth |
| Historical price/probability series | CLOB `/prices-history` | Yes | Per outcome token / asset ID |
| Trades by market/wallet | Data API `/trades` | Yes | Wallet, side, asset, size, price, timestamp, transaction hash |
| Holders | Data API `/holders` | Current / limited | Top holders, capped |
| Positions | Data API `/positions` / market positions | Current/open/closed depending endpoint | Useful for whale concentration |
| Current L2 order book | CLOB `/book` or `/books` | Current only | Use token IDs |
| Live L2 stream | WebSocket market channel | From time we collect | Book snapshots, price changes, last trade, best bid/ask |
| Historical L2 | PMXT archive | Partial coverage | Free parquet archive; useful for high-quality historical investigations where available |
| Enriched historical L2 | Paid providers | Varies | Oddpool, MarketLens, Telonex, PredictionData.dev, SupaGamma, etc. |

---

## 3. Core Identifiers

Polymarket data has several identifiers. Store all of them.

| Identifier | Meaning | Source |
|---|---|---|
| `event_id` | Event/container ID | Gamma |
| `market_id` | Gamma market ID | Gamma |
| `slug` | Human-readable market slug | Gamma |
| `conditionId` | Market condition ID, often used by Data API | Gamma/Data |
| `clobTokenIds` | Outcome token IDs used by CLOB | Gamma |
| `asset_id` / `token_id` | CLOB token ID for a specific outcome | CLOB/WebSocket |
| `outcome` | Usually `Yes` or `No`, but can be multi-outcome | Gamma/Data |
| `outcomeIndex` | Index mapping outcome to price/token | Gamma/Data |
| `proxyWallet` | Polymarket user profile wallet | Data API |
| `transactionHash` | On-chain transaction hash | Data API / Polygon |

Important mapping rule:

```text
Gamma outcomes[i]  <->  Gamma outcomePrices[i]  <->  Gamma clobTokenIds[i]
```

For binary markets:

```text
outcomes = ["Yes", "No"]
clobTokenIds = [YES_TOKEN_ID, NO_TOKEN_ID]
```

---

## 4. Official Polymarket API Retrieval Specification

### 4.1 Authentication

For this project’s read-only analysis layer:

- **Gamma API:** no authentication required.
- **Data API:** no authentication required.
- **CLOB market-data endpoints:** no authentication required.
- **CLOB trading/order-management endpoints:** authentication required; not needed for analysis unless we later build trading execution tools.

### 4.2 Base URLs

```text
Gamma API:  https://gamma-api.polymarket.com
CLOB API:   https://clob.polymarket.com
Data API:   usually documented under Polymarket Data/Core API endpoints
WebSocket:  wss://ws-subscriptions-clob.polymarket.com/ws/market
```

---

## 5. Market Discovery

### 5.1 List markets

```bash
curl --request GET \
  --url "https://gamma-api.polymarket.com/markets"
```

Use this to build the market universe. Persist at least:

```text
id
question
conditionId
slug
category
description
outcomes
outcomePrices
clobTokenIds
volume
volumeNum
volume24hr
volume1wk
volume1mo
liquidity
liquidityNum
active
closed
archived
startDate
endDate
createdAt
updatedAt
enableOrderBook
acceptingOrders
```

### 5.2 Get market by slug

```bash
curl --request GET \
  --url "https://gamma-api.polymarket.com/markets/slug/{slug}"
```

Use this when starting from a human-readable market URL.

### 5.3 Parse stringified arrays

Some fields are returned as stringified JSON arrays.

Example parser:

```python
import json

def parse_array_field(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return json.loads(x)

outcomes = parse_array_field(market["outcomes"])
prices = [float(x) for x in parse_array_field(market["outcomePrices"])]
tokens = parse_array_field(market["clobTokenIds"])
```

---

## 6. Historical Price / Probability Series

### 6.1 Single outcome token

The CLOB price-history endpoint uses the **asset ID / CLOB token ID**, not the human-readable slug.

```bash
curl --request GET \
  --url "https://clob.polymarket.com/prices-history?market={TOKEN_ID}&startTs={START_UNIX}&endTs={END_UNIX}&interval=1m&fidelity=1"
```

Typical response shape:

```json
{
  "history": [
    {"t": 1710000000, "p": 0.42},
    {"t": 1710000060, "p": 0.43}
  ]
}
```

Parameters:

| Parameter | Type | Meaning |
|---|---|---|
| `market` | string | Required; token/asset ID |
| `startTs` | unix seconds | Start timestamp |
| `endTs` | unix seconds | End timestamp |
| `interval` | enum | `max`, `all`, `1m`, `1h`, `6h`, `1d`, `1w` |
| `fidelity` | integer minutes | Data accuracy; default 1 minute |

### 6.2 Yes/No probability series

```python
def yes_no_token_map(market):
    outcomes = parse_array_field(market["outcomes"])
    tokens = parse_array_field(market["clobTokenIds"])
    return dict(zip(outcomes, tokens))

token_map = yes_no_token_map(market)
yes_token = token_map["Yes"]
no_token = token_map["No"]
```

Retrieve both:

```bash
curl "https://clob.polymarket.com/prices-history?market={YES_TOKEN}&startTs={START}&endTs={END}&interval=1m&fidelity=1"

curl "https://clob.polymarket.com/prices-history?market={NO_TOKEN}&startTs={START}&endTs={END}&interval=1m&fidelity=1"
```

### 6.3 Batch historical prices

Use batch retrieval for many token IDs.

```bash
curl --request POST \
  --url "https://clob.polymarket.com/batch-prices-history" \
  --header "Content-Type: application/json" \
  --data '{
    "markets": ["TOKEN_ID_1", "TOKEN_ID_2"],
    "start_ts": 1710000000,
    "end_ts": 1710100000,
    "interval": "1m",
    "fidelity": 1
  }'
```

Implementation note: check the live docs/schema before productionizing the exact request-body key names, because Polymarket has changed some endpoint shapes over time.

---

## 7. Trades / Wallet-Level Activity

### 7.1 Market trades

Use the Data API trade endpoint to retrieve wallet-level trades.

Main query parameters:

| Parameter | Meaning |
|---|---|
| `limit` | Max records, up to documented cap |
| `offset` | Pagination offset |
| `takerOnly` | Defaults to `true`; set explicitly depending on analysis |
| `filterType` | `CASH` or `TOKENS`; must be paired with `filterAmount` |
| `filterAmount` | Minimum trade amount |
| `market` | Comma-separated condition IDs; mutually exclusive with `eventId` |
| `eventId` | Comma-separated event IDs; mutually exclusive with `market` |
| `user` | Proxy wallet address |
| `side` | `BUY` or `SELL` |

Example:

```bash
curl --request GET \
  --url "https://data-api.polymarket.com/trades?market={CONDITION_ID}&limit=1000&offset=0&takerOnly=false"
```

Persist:

```text
proxyWallet
side
asset
conditionId
size
price
timestamp
title
slug
eventSlug
outcome
outcomeIndex
name
pseudonym
transactionHash
```

### 7.2 Whale trade query

```bash
curl --request GET \
  --url "https://data-api.polymarket.com/trades?market={CONDITION_ID}&filterType=CASH&filterAmount=10000&limit=1000&takerOnly=false"
```

### 7.3 Wallet-specific query

```bash
curl --request GET \
  --url "https://data-api.polymarket.com/trades?user={PROXY_WALLET}&limit=1000&offset=0"
```

---

## 8. Holders and Positions

### 8.1 Top holders

```bash
curl --request GET \
  --url "https://data-api.polymarket.com/holders?market={CONDITION_ID}&limit=20&minBalance=1"
```

Use cases:

- Holder concentration.
- Top-holder share.
- Whale discovery.
- Identifying wallets to backfill in the trade API.

Caveat: top-holder responses are capped, so this is not a complete holder distribution.

### 8.2 Positions for a market

```bash
curl --request GET \
  --url "https://data-api.polymarket.com/positions?market={CONDITION_ID}&status=ALL&limit=1000"
```

Useful fields typically include wallet, outcome, token amount, average price, current price/value, and PnL. Store both open and closed positions when available.

---

## 9. Current Order Book and Top-of-Book

### 9.1 Single token order book

```bash
curl --request GET \
  --url "https://clob.polymarket.com/book?token_id={TOKEN_ID}"
```

Response includes:

```text
market
asset_id
timestamp
hash
bids[]: price, size
asks[]: price, size
min_order_size
tick_size
neg_risk
last_trade_price
```

### 9.2 Batch order books

```bash
curl --request POST \
  --url "https://clob.polymarket.com/books" \
  --header "Content-Type: application/json" \
  --data '[
    {"token_id": "TOKEN_ID_1"},
    {"token_id": "TOKEN_ID_2"}
  ]'
```

### 9.3 Derived order-book metrics

For each token and timestamp:

```text
best_bid = max(bids.price)
best_ask = min(asks.price)
mid = (best_bid + best_ask) / 2
spread = best_ask - best_bid
depth_1c = sum(size where |price - mid| <= 0.01)
depth_2c = sum(size where |price - mid| <= 0.02)
depth_5c = sum(size where |price - mid| <= 0.05)
book_imbalance_1c = (bid_depth_1c - ask_depth_1c) / (bid_depth_1c + ask_depth_1c)
```

---

## 10. Live WebSocket Collector

### 10.1 Market channel

Endpoint:

```text
wss://ws-subscriptions-clob.polymarket.com/ws/market
```

Subscribe with token IDs:

```json
{
  "assets_ids": ["YES_TOKEN_ID", "NO_TOKEN_ID"],
  "type": "market",
  "custom_feature_enabled": true
}
```

Expected event types:

| Event type | Meaning |
|---|---|
| `book` | Full order-book snapshot |
| `price_change` | Price-level update |
| `tick_size_change` | Tick-size change |
| `last_trade_price` | Trade execution |
| `best_bid_ask` | Best bid/ask update; requires custom feature |
| `new_market` | New market notification |
| `market_resolved` | Market resolution notification |

### 10.2 Collector requirements

The collector should:

1. Refresh market universe from Gamma API every 1–5 minutes.
2. Subscribe to all active `clobTokenIds`.
3. Persist all raw WebSocket events to immutable object storage.
4. Normalize events into relational/parquet tables.
5. Periodically reconcile with CLOB `/book`.
6. Track gaps, disconnects, and recovery snapshots.
7. Use UTC timestamps everywhere.

Recommended raw storage path:

```text
s3://polymarket-raw/ws_events/date=YYYY-MM-DD/hour=HH/part-*.jsonl.gz
```

Recommended normalized storage:

```text
s3://polymarket-clean/order_book_events/date=YYYY-MM-DD/hour=HH/*.parquet
s3://polymarket-clean/top_of_book/date=YYYY-MM-DD/hour=HH/*.parquet
s3://polymarket-clean/trades/date=YYYY-MM-DD/hour=HH/*.parquet
```

---

## 11. Free Historical L2 Option: PMXT Archive

Use PMXT as a free public archive for historical order-book/WebSocket data where coverage exists.

What it is useful for:

- Reconstructing top-of-book and depth historically.
- Validating official price-history movements.
- Backtesting manipulation detectors on real L2 events.
- High-priority investigation windows.

Caveats:

- Coverage starts only from the archive’s available start date.
- Data is large and parquet-based.
- Requires engineering work to map PMXT schemas to Polymarket identifiers.
- Always validate against official Gamma/CLOB metadata.

Example ingestion pattern:

```python
import pandas as pd

df = pd.read_parquet("pmxt_hour_file.parquet")

# Normalize timestamps to UTC.
df["ts"] = pd.to_datetime(df["timestamp"], unit="ms", utc=True)

# Filter by token/asset ID.
df_token = df[df["asset_id"] == YES_TOKEN_ID]
```

---

## 12. Optional Paid Historical Data Providers

Use only if free sources are insufficient.

| Provider | Best for | Pricing signal / caveat |
|---|---|---|
| Oddpool | API, whale tracking, cross-venue data, historical snapshots | Free tier exists; Pro/Premium/Enterprise; historical Polymarket data from 2026-03-20 onward per docs |
| MarketLens | Tick-level Polymarket order-book replay and backtesting | Backtesting-focused; recurring/coverage caveats should be verified |
| Telonex | Tick-level trades, order books, quotes, on-chain fills | Clean downloadable datasets; commercial use may require enterprise tier |
| PredictionData.dev | Institutional L2 and on-chain data | More expensive; tick-level L2, 100B+ updates, full replay |
| SupaGamma | Pay-per-download historical data | 60-second order-book snapshots; less suitable for precise tick-level impact |
| PolymarketData.co | Full-history order book and metrics | Contact/pricing varies |

Product recommendation:

- **Free MVP:** official APIs + WebSocket collector + PMXT.
- **Serious historical microstructure:** PredictionData.dev / MarketLens / Telonex / Oddpool.
- **Low-frequency research:** SupaGamma or other snapshot datasets may be enough.

---

## 13. Storage Schema

### 13.1 `markets`

```sql
CREATE TABLE markets (
  market_id TEXT,
  event_id TEXT,
  slug TEXT,
  question TEXT,
  description TEXT,
  condition_id TEXT,
  category TEXT,
  outcomes JSON,
  clob_token_ids JSON,
  outcome_prices JSON,
  active BOOLEAN,
  closed BOOLEAN,
  archived BOOLEAN,
  enable_order_book BOOLEAN,
  accepting_orders BOOLEAN,
  volume_num DOUBLE,
  liquidity_num DOUBLE,
  volume_24h DOUBLE,
  volume_1w DOUBLE,
  volume_1m DOUBLE,
  start_time TIMESTAMP,
  end_time TIMESTAMP,
  created_at TIMESTAMP,
  updated_at TIMESTAMP,
  ingested_at TIMESTAMP
);
```

### 13.2 `outcomes`

```sql
CREATE TABLE outcomes (
  condition_id TEXT,
  market_id TEXT,
  slug TEXT,
  outcome_index INT,
  outcome TEXT,
  token_id TEXT,
  latest_probability DOUBLE,
  ingested_at TIMESTAMP
);
```

### 13.3 `price_history`

```sql
CREATE TABLE price_history (
  token_id TEXT,
  condition_id TEXT,
  outcome TEXT,
  ts TIMESTAMP,
  price DOUBLE,
  interval TEXT,
  fidelity_minutes INT,
  source TEXT,
  ingested_at TIMESTAMP,
  PRIMARY KEY (token_id, ts, interval, source)
);
```

### 13.4 `trades`

```sql
CREATE TABLE trades (
  transaction_hash TEXT,
  condition_id TEXT,
  token_id TEXT,
  outcome TEXT,
  outcome_index INT,
  proxy_wallet TEXT,
  side TEXT,
  size DOUBLE,
  price DOUBLE,
  notional DOUBLE,
  ts TIMESTAMP,
  slug TEXT,
  event_slug TEXT,
  name TEXT,
  pseudonym TEXT,
  source TEXT,
  ingested_at TIMESTAMP
);
```

### 13.5 `order_book_snapshots`

```sql
CREATE TABLE order_book_snapshots (
  token_id TEXT,
  condition_id TEXT,
  ts TIMESTAMP,
  best_bid DOUBLE,
  best_ask DOUBLE,
  mid DOUBLE,
  spread DOUBLE,
  bid_depth_1c DOUBLE,
  ask_depth_1c DOUBLE,
  bid_depth_2c DOUBLE,
  ask_depth_2c DOUBLE,
  bid_depth_5c DOUBLE,
  ask_depth_5c DOUBLE,
  book_imbalance_1c DOUBLE,
  book_imbalance_2c DOUBLE,
  book_hash TEXT,
  source TEXT,
  ingested_at TIMESTAMP
);
```

### 13.6 `wallet_features`

```sql
CREATE TABLE wallet_features (
  proxy_wallet TEXT,
  asof_ts TIMESTAMP,
  total_trades INT,
  total_notional DOUBLE,
  total_markets INT,
  avg_trade_size DOUBLE,
  max_trade_size DOUBLE,
  buy_sell_imbalance DOUBLE,
  pnl_realized DOUBLE,
  pnl_unrealized DOUBLE,
  new_wallet_flag BOOLEAN,
  first_seen_ts TIMESTAMP,
  last_seen_ts TIMESTAMP,
  source TEXT
);
```

### 13.7 `suspicious_events`

```sql
CREATE TABLE suspicious_events (
  event_id TEXT,
  condition_id TEXT,
  token_id TEXT,
  wallet TEXT,
  event_ts TIMESTAMP,
  event_type TEXT,
  suspicion_score DOUBLE,
  whale_share_5m DOUBLE,
  price_move_1m DOUBLE,
  price_move_5m DOUBLE,
  reversal_30m DOUBLE,
  spread_before DOUBLE,
  depth_before_2c DOUBLE,
  impact_lambda DOUBLE,
  wash_cluster_score DOUBLE,
  insider_timing_score DOUBLE,
  explanation TEXT,
  created_at TIMESTAMP
);
```

---

## 14. Feature Engineering

### 14.1 Trade signing

For binary Yes/No markets, express flow as a signed Yes-probability pressure.

```text
signed_yes_pressure =
  + size * price   if BUY Yes
  - size * price   if SELL Yes
  - size * price   if BUY No
  + size * price   if SELL No
```

Alternative token-unit version:

```text
signed_token_pressure =
  + size if BUY Yes
  - size if SELL Yes
  - size if BUY No
  + size if SELL No
```

### 14.2 Whale features

```text
wallet_share_5m = wallet_notional_5m / total_market_notional_5m
wallet_share_1h = wallet_notional_1h / total_market_notional_1h
wallet_percentile_trade_size = percentile(trade_notional within market)
new_wallet_before_trade = first_seen_ts >= trade_ts - 7 days
```

### 14.3 Price-impact features

```text
p_before = price at t - 1m or mid immediately before trade
p_after_1m = price at t + 1m
p_after_5m = price at t + 5m
impact_1m = p_after_1m - p_before
impact_5m = p_after_5m - p_before
reversal_30m = p_after_30m - p_after_5m
```

For L2 data:

```text
slippage = vwap_fill_price - mid_before
impact_lambda = delta_mid / signed_notional
depth_consumed = executed_size / depth_available_within_5c
```

### 14.4 Wash-trading graph features

Construct a directed graph:

```text
nodes = proxy wallets
edges = trades between counterparties, if maker/taker/counterparty available
edge_weight = notional
```

If counterparty is not available in free API, approximate with:

- same transaction hash;
- rapid opposite-side trades;
- repeated round trips in same market;
- closed clusters based on common funding / on-chain transfers.

Features:

```text
round_trip_ratio
self_cluster_volume_share
closed_component_ratio
reciprocity
wallet_age_similarity
common_funding_score
repeated_counterparty_score
abnormal_volume_without_price_move
```

### 14.5 Insider-timing features

```text
longshot_entry = price_before < 0.20
large_pre_event_trade = notional > percentile_99 and before public news timestamp
new_wallet_large_trade = new_wallet_flag and trade_notional > threshold
high_success_longshot_rate = realized_win_rate >> implied_probability
```

Use external event timestamps from news APIs, manual labels, or LLM-assisted event extraction.

---

## 15. Manipulation Typology and Detection Logic

### 15.1 Whale-driven price impact

Suspicious pattern:

```text
large concentrated wallet flow
+ sharp probability move
+ low pre-trade depth or wide spread
+ short-term reversal
```

Score:

```text
score_whale_impact =
  z(wallet_share_5m)
+ z(abs(price_move_5m))
+ z(reversal_30m)
+ z(spread_before)
- z(depth_before_2c)
```

### 15.2 Pump-and-reversal

Suspicious pattern:

```text
wallet buys aggressively -> price jumps -> wallet sells/hedges -> price reverts
```

Detection:

```text
if buy_pressure_t > threshold
and delta_p_5m > threshold
and same_wallet_sell_pressure_next_30m > threshold
and reversal_2h < -0.5 * delta_p_5m:
    flag
```

### 15.3 Wash trading / artificial volume

Suspicious pattern:

```text
large volume
+ little net position change
+ repeated back-and-forth flow
+ closed wallet clusters
+ limited price discovery
```

Detection:

```text
wash_score =
  high_round_trip_ratio
+ high_volume_low_position_change
+ high_closed_cluster_ratio
+ repeated_same_wallet_pairs
+ abnormal_volume_without_probability_move
```

### 15.4 Spoofing-like behavior

Strict spoofing detection requires order-level placement/cancellation attribution, which free public data usually does **not** provide.

Feasible free-data proxy:

```text
large displayed depth appears near top of book
then disappears before trade
then price moves
```

This is only a proxy and should be labeled as **order-book instability**, not proven spoofing.

### 15.5 Liquidity vacuum manipulation

Suspicious pattern:

```text
depth vanishes or spread widens
then small trade moves probability sharply
then depth returns
```

Needs L2 data.

### 15.6 Insider / information leakage behavior

Suspicious pattern:

```text
new or inactive wallet
+ large longshot trade
+ public event shortly afterward
+ high ex-post payoff
+ repeated success across similar markets
```

This does not prove illegal insider trading; it identifies wallets worth investigation.

---

## 16. Econometric Models

### 16.1 Event study

Goal: measure abnormal probability movement around whale trades.

Define event time:

```text
t0 = timestamp of whale trade or whale-flow burst
```

Windows:

```text
pre:  [-60m, -5m]
event: [-5m, +5m]
post: [+5m, +120m]
```

Outcome variables:

```text
delta_p_1m
delta_p_5m
delta_p_30m
reversal_2h
abnormal_volume
abnormal_spread
abnormal_depth
```

Regression:

```text
Δp_{m,t+h} = α
           + β1 * whale_flow_{m,t}
           + β2 * liquidity_controls_{m,t-}
           + β3 * market_fixed_effects
           + β4 * time_fixed_effects
           + ε_{m,t}
```

Interpretation:

- `β1 > 0`: whale buy pressure predicts probability increase.
- Reversal after positive `β1` can suggest temporary pressure rather than information.

### 16.2 Kyle lambda / price impact

```text
Δp_t = λ * signed_volume_t + ε_t
```

Estimate per market and per time regime.

High lambda means thin liquidity / high price sensitivity.

### 16.3 VAR / Granger causality

Variables:

```text
signed_whale_flow_t
retail_flow_t
Δp_t
spread_t
depth_t
external_news_intensity_t
```

Question:

```text
Does whale flow Granger-cause price movements after controlling for lagged price moves?
```

### 16.4 Difference-in-differences

Treatment:

```text
markets with whale shock
```

Control:

```text
similar markets without whale shock
```

Model:

```text
p_{m,t} = α + β * treated_m * post_t + γ_m + δ_t + ε_{m,t}
```

### 16.5 Synthetic control

Build a weighted control basket of similar markets to estimate counterfactual price path without the suspicious event.

---

## 17. Probabilistic / Inference-Based Models

### 17.1 Bayesian change-point detection

Detect abrupt regime changes in price, spread, or flow.

```text
p_t ~ Normal(μ_k, σ_k), where k changes at unknown changepoints
```

Flag when a changepoint coincides with concentrated wallet flow.

### 17.2 Hawkes process

Model clustered trade arrivals.

```text
λ(t) = μ + Σ α exp(-β(t - t_i))
```

Use for:

- abnormal trade clustering;
- cascade detection;
- coordinated activity.

### 17.3 Sequential probability ratio test

Online flagging:

```text
H0: normal flow/price behavior
H1: abnormal concentrated flow/price behavior
```

Use for live alerts.

### 17.4 Bayesian wallet skill / information model

Estimate whether a wallet’s success rate is statistically compatible with its entry prices.

```text
wins_i ~ Bernoulli(q_i)
q_i ~ Beta(a, b)
```

Compare realized returns/win rates against implied probabilities at entry.

### 17.5 Placebo tests

Randomly reassign event timestamps within the same market and recompute scores.

A manipulation score is more credible when the observed score is extreme versus placebo distribution.

---

## 18. Machine Learning Methods

### 18.1 Unsupervised anomaly detection

Models:

- Isolation Forest
- Local Outlier Factor
- One-class SVM
- Robust covariance / Mahalanobis distance
- Autoencoders for time series

Input features:

```text
wallet_share_5m
signed_flow_zscore
price_move_zscore
reversal_zscore
spread_zscore
depth_zscore
round_trip_ratio
new_wallet_flag
longshot_trade_flag
```

Output:

```text
anomaly_score in [0, 1]
```

### 18.2 Supervised classification

Only use if labels exist.

Labels:

```text
0 = normal
1 = suspicious
2 = confirmed manipulation / enforcement / manually validated
```

Models:

- XGBoost / LightGBM
- Logistic regression with calibrated probabilities
- Random forest
- Temporal CNN / Transformer only if sufficient data volume

Evaluation:

```text
precision@k
recall@k
AUC-PR
false-positive review rate
calibration error
```

### 18.3 Graph ML

Graph nodes:

```text
wallets
markets
funding addresses
transactions
```

Edges:

```text
traded_market
funded_by
transferred_to
same_tx
same_cluster
```

Methods:

- Louvain / Leiden community detection
- Node2Vec embeddings
- GraphSAGE / GAT if labels exist
- Connected-component / closed-cluster heuristics

High-value use case:

```text
Detect sybil clusters whose individual wallets look normal but collectively dominate market volume.
```

### 18.4 Time-series models

Use for forecasting normal expected probability movement.

Models:

- ARIMA / ARIMAX
- state-space models
- temporal gradient boosting
- Temporal Fusion Transformer only if enough history

Flag:

```text
actual_move - expected_move > threshold
```

---

## 19. LLM-Assisted Analysis

LLMs should **not** be used as the primary statistical proof engine. Use them for:

1. Market question parsing.
2. Resolution-criteria extraction.
3. Event/news timeline summarization.
4. Narrative explanations for flagged events.
5. Analyst report generation.
6. Code/query generation.
7. Human-review triage.

### 19.1 Example LLM tasks

```text
Given this market question and description, extract:
- underlying event
- resolution source
- resolution deadline
- possible external news triggers
- whether the market is binary, scalar, or multi-outcome
```

```text
Given a suspicious-event feature vector and relevant trades, write a neutral analyst note explaining:
- what happened
- what data supports suspicion
- what alternative explanations exist
- what data would be needed to escalate
```

### 19.2 LLM guardrails

- Never let the LLM label a wallet as manipulative without statistical backing.
- Always include uncertainty.
- Always distinguish correlation from causation.
- Store prompts and outputs for auditability.
- Keep raw private/user data out of prompts unless legally approved.

---

## 20. Scoring Framework

Recommended composite score:

```text
suspicion_score =
  0.25 * whale_concentration_score
+ 0.20 * abnormal_price_move_score
+ 0.15 * reversal_score
+ 0.15 * low_liquidity_score
+ 0.10 * wash_cluster_score
+ 0.10 * insider_timing_score
+ 0.05 * recurrence_score
```

Each subscore should be normalized to `[0, 1]`.

Severity tiers:

| Score | Tier | Meaning |
|---:|---|---|
| 0.00–0.40 | Low | Likely normal market activity |
| 0.40–0.60 | Medium | Worth monitoring |
| 0.60–0.80 | High | Requires analyst review |
| 0.80–1.00 | Critical | Strong anomaly; escalate |

---

## 21. Free MVP Build Plan

### Phase 1: Static market/trade dataset

- Pull active and recently closed markets.
- Parse token mappings.
- Pull price history for Yes/No tokens.
- Pull trades by condition ID.
- Pull holders and positions.
- Compute whale and price-move features.

Deliverable:

```text
ranked_suspicious_events.csv
market_summary.parquet
wallet_summary.parquet
```

### Phase 2: Event-study engine

- Define whale trades by percentile or notional threshold.
- Compute pre/post price moves.
- Compute reversals.
- Run placebo tests.
- Generate analyst notes.

### Phase 3: Live collector

- Subscribe to WebSocket market channel.
- Store raw events.
- Normalize L2.
- Compute live spread/depth.
- Alert on sharp whale-flow + thin-book patterns.

### Phase 4: Historical L2 enrichment

- Ingest PMXT archive where available.
- Add paid provider only if necessary.
- Reconstruct top-of-book and depth for flagged windows.

### Phase 5: ML/graph layer

- Build wallet graph.
- Add anomaly detection.
- Add wallet cluster/entity inference.
- Calibrate scores with human review.

---

## 22. Minimal Python Retrieval Skeleton

```python
import json
import time
import requests
import pandas as pd

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
DATA = "https://data-api.polymarket.com"

def get_json(url, params=None, retries=3, sleep=1):
    for i in range(retries):
        r = requests.get(url, params=params, timeout=30)
        if r.status_code == 429:
            time.sleep(sleep * (2 ** i))
            continue
        r.raise_for_status()
        return r.json()
    raise RuntimeError(f"Failed after retries: {url}")

def parse_array_field(x):
    if x is None:
        return []
    if isinstance(x, list):
        return x
    return json.loads(x)

def get_market_by_slug(slug):
    return get_json(f"{GAMMA}/markets/slug/{slug}")

def get_token_map(market):
    outcomes = parse_array_field(market["outcomes"])
    tokens = parse_array_field(market["clobTokenIds"])
    return dict(zip(outcomes, tokens))

def get_price_history(token_id, start_ts, end_ts, interval="1m", fidelity=1):
    data = get_json(
        f"{CLOB}/prices-history",
        params={
            "market": token_id,
            "startTs": start_ts,
            "endTs": end_ts,
            "interval": interval,
            "fidelity": fidelity
        }
    )
    df = pd.DataFrame(data.get("history", []))
    if not df.empty:
        df["token_id"] = token_id
        df["ts"] = pd.to_datetime(df["t"], unit="s", utc=True)
        df = df.rename(columns={"p": "price"})
    return df

def get_trades(condition_id, limit=1000, taker_only=False):
    rows = []
    offset = 0
    while True:
        batch = get_json(
            f"{DATA}/trades",
            params={
                "market": condition_id,
                "limit": limit,
                "offset": offset,
                "takerOnly": str(taker_only).lower()
            }
        )
        if not batch:
            break
        rows.extend(batch)
        if len(batch) < limit:
            break
        offset += limit
    return pd.DataFrame(rows)

def get_order_book(token_id):
    return get_json(f"{CLOB}/book", params={"token_id": token_id})

def book_metrics(book):
    bids = [(float(x["price"]), float(x["size"])) for x in book.get("bids", [])]
    asks = [(float(x["price"]), float(x["size"])) for x in book.get("asks", [])]
    if not bids or not asks:
        return None
    best_bid = max(p for p, s in bids)
    best_ask = min(p for p, s in asks)
    mid = (best_bid + best_ask) / 2
    spread = best_ask - best_bid
    bid_depth_2c = sum(s for p, s in bids if mid - p <= 0.02)
    ask_depth_2c = sum(s for p, s in asks if p - mid <= 0.02)
    return {
        "token_id": book["asset_id"],
        "condition_id": book["market"],
        "timestamp": book["timestamp"],
        "best_bid": best_bid,
        "best_ask": best_ask,
        "mid": mid,
        "spread": spread,
        "bid_depth_2c": bid_depth_2c,
        "ask_depth_2c": ask_depth_2c
    }
```

---

## 23. Minimal Event-Study Skeleton

```python
def compute_event_study(trades, prices, whale_notional_threshold=10_000):
    trades = trades.copy()
    trades["notional"] = trades["size"].astype(float) * trades["price"].astype(float)
    trades["ts"] = pd.to_datetime(trades["timestamp"], unit="s", utc=True)

    whale_trades = trades[trades["notional"] >= whale_notional_threshold].copy()

    prices = prices.sort_values("ts").copy()

    def nearest_price(ts):
        idx = prices["ts"].searchsorted(ts)
        if idx <= 0 or idx >= len(prices):
            return None
        return prices.iloc[idx]["price"]

    rows = []
    for _, tr in whale_trades.iterrows():
        t0 = tr["ts"]
        p_before = nearest_price(t0 - pd.Timedelta(minutes=1))
        p_after_5m = nearest_price(t0 + pd.Timedelta(minutes=5))
        p_after_30m = nearest_price(t0 + pd.Timedelta(minutes=30))

        if p_before is None or p_after_5m is None:
            continue

        rows.append({
            "wallet": tr["proxyWallet"],
            "trade_ts": t0,
            "side": tr["side"],
            "outcome": tr["outcome"],
            "notional": tr["notional"],
            "p_before": p_before,
            "p_after_5m": p_after_5m,
            "p_after_30m": p_after_30m,
            "impact_5m": p_after_5m - p_before,
            "reversal_30m": None if p_after_30m is None else p_after_30m - p_after_5m
        })

    return pd.DataFrame(rows)
```

---

## 24. API Rate-Limit and Reliability Practices

- Implement exponential backoff on HTTP 429.
- Cache Gamma metadata aggressively.
- Persist raw JSON before transformations.
- Use idempotent ingestion keyed by source identifiers.
- Store ingestion timestamp and source URL.
- Reconcile price-history data with live top-of-book where available.
- Use UTC timestamps and unix seconds.
- Keep per-endpoint request counters.
- Avoid high-frequency polling of `/book`; use WebSocket for live L2.

---

## 25. Data Quality Checks

### Market metadata

```text
outcomes length == clobTokenIds length
conditionId is non-null
enableOrderBook == true for CLOB analysis
closed/resolved markets handled separately
```

### Prices

```text
0 <= price <= 1
Yes + No approximately 1, allowing spread/friction
no duplicate token_id + timestamp rows
no large gaps without flagging
```

### Trades

```text
size > 0
0 <= price <= 1
timestamp parseable
conditionId matches market table
transactionHash not null where expected
```

### L2

```text
best_bid <= best_ask
spread >= 0
depth >= 0
snapshot sequence has no long gaps
book hash changes tracked
```

---

## 26. Key Limitations

1. **Free historical L2 is incomplete.** Official Polymarket APIs do not provide arbitrary full historical order-book depth.
2. **Displayed probability is not always causal.** Price movements may reflect news, liquidity, or spread changes.
3. **Correlation is not causation.** A whale trading before a move may be informed rather than manipulative.
4. **Spoofing is hard to prove.** Public L2 updates can show book changes, but not always the owner of canceled orders.
5. **Wallet identity is pseudonymous.** Entity clustering is probabilistic.
6. **Wash trading can resemble market making.** Network and round-trip indicators require careful false-positive control.
7. **On-chain settlement differs from off-chain matching.** Use both CLOB and Polygon/on-chain data when precision matters.
8. **Legal language matters.** Use “suspicious,” “anomalous,” or “consistent with manipulation,” not “manipulation proven,” unless supported by formal evidence.

---

## 27. Research Background

### Polymarket-specific research

- **Network-Based Detection of Wash Trading**  
  Working paper / SSRN / Columbia Business School. Proposes a network-based wash-trading detection method based on closed clusters of counterparties. Applies the method to Polymarket and estimates substantial suspicious/wash-trading-like activity during certain periods.  
  URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5714122

- **The Anatomy of Polymarket: Evidence from the 2024 Presidential Election**  
  arXiv preprint. Transaction-level analysis of Polymarket’s 2024 U.S. election market using Polygon data; useful for understanding volume accounting, mint/burn/conversion mechanics, and whale activity.  
  URL: https://arxiv.org/html/2603.03136v1

- **Price Discovery and Trading in Modern Prediction Markets**  
  SSRN paper comparing Polymarket, Kalshi, PredictIt, and Robinhood around the 2024 U.S. presidential election. Relevant for cross-market price discovery and order-flow analysis.  
  URL: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5331995

### Peer-reviewed prediction-market manipulation research

- **The effect of malicious manipulations on prediction market accuracy**  
  Published in *Information Systems Frontiers*. Finds that manipulations affect prices, but effects may be rapidly reduced by rational traders.  
  URL: https://link.springer.com/article/10.1007/s10796-015-9617-7

- **Affecting policy by manipulating prediction markets: Experimental evidence**  
  Published in *Journal of Economic Behavior & Organization*. Lab evidence that well-funded, single-minded manipulators can mislead market prices, while outstanding bids/asks may remain informative.  
  URL: https://www.sciencedirect.com/science/article/abs/pii/S0167268112002223

Important conclusion:

> As of this specification date, there is rigorous Polymarket-specific work, but much of it is working-paper/preprint status. Peer-reviewed manipulation literature exists for prediction markets generally, not necessarily Polymarket specifically.

---

## 28. Reference URLs

### Official Polymarket

- API introduction: https://docs.polymarket.com/api-reference/introduction
- Market data overview: https://docs.polymarket.com/market-data/overview
- List markets: https://docs.polymarket.com/api-reference/markets/list-markets
- Get market by slug: https://docs.polymarket.com/api-reference/markets/get-market-by-slug
- Get prices history: https://docs.polymarket.com/api-reference/markets/get-prices-history
- Batch prices history: https://docs.polymarket.com/api-reference/markets/get-batch-prices-history
- Get trades: https://docs.polymarket.com/api-reference/core/get-trades-for-a-user-or-markets
- Get top holders: https://docs.polymarket.com/api-reference/core/get-top-holders-for-markets
- Get positions for market: https://docs.polymarket.com/api-reference/core/get-positions-for-a-market
- Order book guide: https://docs.polymarket.com/trading/orderbook
- Get order book: https://docs.polymarket.com/api-reference/market-data/get-order-book
- Get order books batch: https://docs.polymarket.com/api-reference/market-data/get-order-books-request-body
- WebSocket overview: https://docs.polymarket.com/market-data/websocket/overview
- WebSocket market channel: https://docs.polymarket.com/market-data/websocket/market-channel
- Public client methods: https://docs.polymarket.com/trading/clients/public
- Clients and SDKs: https://docs.polymarket.com/api-reference/clients-sdks

### Free / third-party historical data

- PMXT archive overview: https://archive.pmxt.dev/
- PMXT v2 docs: https://archive.pmxt.dev/docs/v2-data-overview
- Oddpool docs: https://docs.oddpool.com/
- Oddpool pricing: https://www.oddpool.com/pricing
- MarketLens: https://marketlens.trade/
- Telonex: https://telonex.io/
- PredictionData.dev: https://predictiondata.dev/
- PredictionData.dev order books docs: https://docs.predictiondata.dev/datasets/polymarket/order-books
- SupaGamma: https://supagamma.com/
- PolymarketData.co: https://www.polymarketdata.co/

---

## 29. Recommended First Implementation

Build the first version as:

```text
1. Market loader:
   Gamma /markets + /markets/slug/{slug}

2. Price loader:
   CLOB /prices-history for each Yes/No token

3. Trade loader:
   Data API /trades by conditionId

4. Whale/event-study engine:
   detect large wallet flow + price jump + reversal

5. Suspicion dashboard:
   ranked markets, wallets, timestamps, explanations

6. Live L2 collector:
   WebSocket market channel for all active markets

7. Historical L2 enrichment:
   PMXT where available; paid archive only if necessary
```

Minimum output table:

```text
market_slug
condition_id
wallet
event_ts
outcome
side
trade_notional
wallet_share_5m
price_before
price_after_5m
price_after_30m
impact_5m
reversal_30m
spread_before
depth_before_2c
suspicion_score
explanation
```

---

## 30. Bottom Line

A free API-based manipulation analysis pipeline is viable for:

- whale-flow detection;
- price-impact screening;
- pump/reversal detection;
- holder concentration;
- abnormal volume;
- wallet recurrence;
- initial wash-trading indicators.

But rigorous attribution of manipulation requires:

- historical L2 order-book reconstruction;
- wallet/entity clustering;
- placebo tests;
- external event/news controls;
- human review.

The most defensible product is therefore a **market-integrity intelligence API**, not a simple Polymarket data wrapper.

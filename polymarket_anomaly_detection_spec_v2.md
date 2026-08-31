# Polymarket Anomaly-Detection Tool — Specification v2

**Date:** 2026-05-11 (initial); last refresh 2026-05-25
**Supersedes:** `polymarket_market_manipulation_data_spec.md` (v1)
**Status:** Living spec — Phases 1–2 implemented; Phase 3 partial (on-chain transfer enrichment only, no CTF/UMA subgraph yet); Phase 5 prototype (mirror backtest + entity-resolution); Phases 4 and 6 pending. See `CLAUDE.md` for the up-to-date implementation status and the module map.

This v2 spec is informed by:

1. The v1 data spec already in the repo.
2. The SoK paper *Market Microstructure for Decentralized Prediction Markets (DePMs)* (Rahman, Al-Chami, Clark, arXiv:2510.15612v2).
3. Live probes of the Gamma, CLOB, and Data APIs performed 2026-05-11.

It deliberately narrows scope from v1's broad survey to a single defensible product: a **market-integrity intelligence layer for Polymarket** that produces ranked, explained suspicion signals — combining what the academic literature already validates with what Polymarket's APIs actually expose.

---

## 1. What changed since v1

| Area | v1 stance | v2 stance | Why |
|---|---|---|---|
| Surface | Generic "retrieve + score" pipeline | Two layers: (a) **on-chain ground-truth replay** (CTF, UMA, ERC-1155 logs) and (b) **off-chain microstructure** (CLOB, WS, Gamma) | The SoK shows on-chain logs are the canonical settlement record and can serve as a verification ledger against off-chain CLOB matches |
| `negRisk` markets | Treated as a metadata flag | First-class concept; YNB-NR markets have a **conversion gadget** (No-share → portfolio of Yes-shares for all other outcomes), so flow analysis must consolidate across an entire YNB-NR family before signing pressure | Paper §3.3 + Gamma exposes `negRisk`/`negRiskOther`/`negRiskRequestID` |
| Scoring | Single composite score | **Two scores**: (a) market-microstructure score (whale, reversal, liquidity), (b) wallet-skill score (Bayesian win-rate vs. implied probability over time) — recombined at triage time, but stored separately for auditability | Paper Insight 5 + Research Gap 1 |
| LLM role | Auxiliary narrative writer | Bounded role: **temporal-reasoning resolution analysis** (Chainlink study: 89.3% accuracy on 1,660 Polymarket questions) — only for resolution-criteria parsing, never for scoring | Paper §3.6 cites the 2025 Chainlink eval |
| Storage | S3 + SQL warehouse | Local-first: DuckDB + parquet on disk for the MVP; warehouse only once volume justifies it | Latest probe of Gamma + Data API runs entirely from a single workstation |

---

## 2. Paper summary (1 page)

The Rahman et al. SoK is a **taxonomy paper**, not an anomaly-detection survey. Its contribution is a modular 8-stage decomposition of DePMs (infrastructure → market topic → share structure & pricing → initialization → trading → resolution → settlement → archiving), used to compare 35+ historical and current systems. Important conclusions for our work:

- **Polymarket is YNB-NR with splitting-based initialization** (no automated bookmaker / no LMSR loss fund). Pricing comes from an **off-chain CLOB**, while minting/burning of ERC-1155 outcome shares and settlement happen on-chain via Gnosis CTF + UMA. (§3.1, §3.4, §3.5, Appendix A entry 26)
- **Solvency is provable from blockchain data alone** (Insight 5). Every $1 paid to a winner is a $1 from a loser or a bounded loss fund — there is no "platform can refuse to pay" failure mode like in traditional sportsbooks. This is what makes on-chain verification high-value here.
- **negRisk gadget** (§3.3) converts a single No-share into a portfolio of Yes-shares across all other candidates in a YNB-NR family. Analysing flow on a single Yes/No pair in isolation is therefore wrong for negRisk markets; flow must be consolidated across the family.
- **AMMs are not used by Polymarket today** — trading is CLOB-matched. So the price-impact literature for AMMs (LVR, divergence loss) does not directly apply to Polymarket spot trading, but it does apply to Omen, Augur, and any future scalar-on-AMM markets.
- The paper **does not survey anomaly detection** but explicitly opens four research gaps that map onto our project:
  - **Gap 1**: Can insider trades be classified from blockchain data with reasonable precision?
  - **Gap 3**: Can we classify copy traders, measure occurrence, evaluate herding effects on accuracy?
  - **Gap 8**: Can we measure MEV extraction for on-chain DePMs?
  - **Gap 10**: A tool that replays past markets by integrating on-chain + API + external data (news/social). The paper says this tool does not exist yet.
- **Cheap-talk filtering works** (Table 1, HBO Satoshi market): traders correctly de-weighted four fake news items and weighted the truthful ones. This is empirically useful: real signal-to-noise behaviour on Polymarket is better than naive priors suggest, so a manipulation-detection tool should not assume markets are easily fooled — outlier reactions are themselves anomalous.
- **Open ledger ≈ panopticon**: §3.8 archiving shows everything settles on-chain. Polymarket settles via UMA Optimistic Oracle → writes payout vector into Gnosis CTF → emits ERC-1155 events. We can reconstruct settlement from `etherscan-style` Polygon indexers (The Graph / Goldsky / Bitquery / Dune) without ever calling Polymarket's API.

---

## 3. State-of-the-art useful for our project

The paper itself does not survey detection methods, so this section maps the **techniques cited or implied** by the paper to proven implementations in adjacent fields. Each entry below is something that has shipped in another market or proven publishable, not speculative.

### 3.1 Direct from the paper's references

| Paper ref | Method | Where it applies to us |
|---|---|---|
| Hanson 2007 [39] – "Insider trading and prediction markets" | Theoretical model of insider entry / longshot trades | Calibrates Gap 1 insider-timing detector — gives a baseline expectation for new-wallet longshot win rate vs. implied probability |
| Saguillo et al. 2025 [72] – "Unravelling the probabilistic forest: Arbitrage in prediction markets" | Combinatorial arbitrage on Polymarket logically-related markets; ~$40M realized arbitrage measured | **Direct port**: arbitrage opportunities can be a feature in our detector. Wallets that systematically realize cross-market arbitrage are sophisticated, not manipulators — useful as a counter-signal |
| Milionis et al. 2025 [56] – "Incentive-compatible recovery from manipulated signals" | Robust aggregation under signal manipulation, applied to DePIN | Inspiration for the meta-aggregator that combines our subscores while bounding the influence of any single feature |
| Zintus-art & Ward 2025 [88] – Chainlink AI oracle eval | LLM temporal reasoning on 1,660 Polymarket questions, 89.3% accuracy (sports 99.7%, politics 84.3%) | Validates a **bounded LLM role**: parse resolution rules and detect ambiguity (Gap 4), do not score |
| Eskandari et al. 2021 [27] – "SoK: Oracles from the ground truth to market manipulation" | Taxonomy of oracle attack surfaces | Defines what UMA disputes look like; UMA dispute history is a free signal of contested markets |
| Heimbach & Wattenhofer 2022 [41] – "SoK: Preventing transaction reordering manipulations in DeFi" | MEV countermeasures including FBA | Methodology for measuring MEV on Polygon Polymarket settlements (Gap 8) — sandwich-attack detection has off-the-shelf tooling (Flashbots' mev-inspect) |

### 3.2 Established techniques from outside the paper

These are proven in TradFi market surveillance, DeFi forensics, or academic finance, and map cleanly onto Polymarket's data shape.

| Technique | Established in | Polymarket fit | Novelty in this context |
|---|---|---|---|
| **Kyle's lambda** (price impact per signed volume) | Foundational market microstructure (Kyle 1985); used by NASDAQ surveillance | CLOB price-history + signed trades give what's needed | Low — but useful as a baseline regime indicator |
| **Hawkes process for trade clustering** | High-frequency finance (Bacry, Bowsher, etc.) | Trade timestamps are dense enough | Medium — Hawkes on Polymarket is publishable but not novel methodologically |
| **Bayesian change-point detection (BOCPD)** | Adams & MacKay 2007; widely used in financial regime detection | Probability series has clear regimes around news | Medium — pairing change-points with on-chain news-anchor timestamps is novel |
| **Wallet-cluster graph + Louvain / Leiden** | DeFi forensics (Chainalysis, Elliptic, TRM), academic anti-money-laundering | Polygon addresses are fully open; proxy-wallet relationships discoverable via Polygon transfer history | **High novelty if combined with Polymarket's wallet skill scoring** — most graph forensics tools have no notion of skill/win-rate |
| **Network-based wash-trading detection (closed-cluster volume share)** | Cong et al. 2023 on crypto exchanges; Columbia working paper on Polymarket (v1 spec §27 ref) | Counterparty inference is approximate (no maker/taker public attribution), but on-chain ERC-1155 transfers give partial truth | High — closed-cluster volume share specifically validated on Polymarket in 2025 work |
| **Bayesian wallet-skill (Beta-Bernoulli over win rate vs. implied probability)** | Sports-betting analytics; Glickman ratings | Trade entries have a price ⇒ implied probability; outcomes are eventually known with certainty | **High novelty**: skill calibration against implied probability, not against a competitor's odds, is unique to prediction markets |
| **Synthetic control** (Abadie) | Causal inference in economics, validated in many policy studies | Build a control basket of similar markets without the suspicious event | Medium — used by the v1 spec already; the novelty is the basket construction (similar negRisk family, similar liquidity tier) |
| **Sequential probability ratio test (SPRT)** | Wald 1947, used in online A/B testing and surveillance | Trivial to wire to a WebSocket stream | Low — but the right primitive for live alerts |
| **MEV / sandwich detection (mev-inspect-style)** | Flashbots' mev-inspect-py, Eigenphi | Polygon has its own MEV ecosystem; Polymarket's off-chain CLOB matching means sandwiches mostly hit splitting/merging txns and AMM legs (Omen/Uniswap) rather than the CLOB itself | Medium — measuring MEV extraction on the *settlement* path of Polymarket markets is Gap 8 verbatim |
| **Polymarket-replay tool (on-chain + API + external news)** | Does not exist — Gap 10 | All inputs are retrievable | **Highest novelty in this entire list** — Gap 10 is a research-grade open problem |

### 3.3 Tools (libraries / services) that are battle-tested

Picking tools that have been load-bearing in other production systems, not toys:

| Tool | Role | Why this one |
|---|---|---|
| **DuckDB** (parquet-native, in-process SQL) | Local analytics + warehouse on a single workstation | Reads PMXT parquet directly, can join with API pulls, single binary. Used by Hugging Face, Mode, dbt — production-trusted |
| **Polars** | DataFrame engine | Outperforms pandas on group-bys over millions of trades; native Arrow → DuckDB |
| **The Graph / Goldsky subgraph** | On-chain event indexing for Polygon | Used by Aave, Uniswap, Polymarket itself for the public Gamma indexer. Gives ERC-1155 mint/burn/transfer + UMA dispute events without running a Polygon node |
| **Bitquery GraphQL** | Polymarket-on-Polygon trades, settlements, volume | Search showed it's the cleanest hosted alternative to building our own indexer for v1 |
| **Dune Analytics** | Cross-checking and exploratory SQL on Polymarket dashboards | Free public dashboards already exist (e.g. *Polymarket — Activity and Volume*, referenced in the paper footnote 18 for YNB vs YNB-NR split) |
| **PMXT archive** | Free historical L2 parquet | Mentioned in v1; only realistic free historical L2 source |
| **mev-inspect-py** | Polygon MEV detection | Production tool, Flashbots-maintained |
| **NetworkX + igraph + graph-tool** | Wallet-graph community detection (Louvain/Leiden) | Battle-tested; graph-tool is significantly faster for >1M edges |
| **PyMC / NumPyro** | Bayesian change-point + wallet-skill | Industry-standard probabilistic programming |
| **`tick` (Hawkes processes)** | Trade-arrival clustering | INRIA-maintained, exact MLE for parametric Hawkes |
| **Anthropic / OpenAI APIs** | Resolution-criteria parsing only | Bounded role per paper Gap 4 |
| **Polygon archive node (Erigon) — optional Phase 4** | Full historical chain replay | Only if we need exact reorg-safe state |
| **Apache Arrow / Parquet** | All persistence | Lingua franca; PMXT is parquet, DuckDB is parquet-native |

What we are **deliberately not** picking:

- Heavy distributed runtimes (Spark/Flink) — overkill until daily volume justifies it.
- Vector DBs — no embedding-based retrieval in scope yet.
- Custom blockchain indexers from scratch — The Graph / Bitquery / Dune solve this with less engineering.
- Proprietary trading analytics (Bloomberg Terminal-style) — license costs and no Polymarket coverage.

### 3.4 Profitable / novel angles ranked

1. **Replay tool (Gap 10)** — a stepwise market replayer with synchronized on-chain events, CLOB top-of-book, and news/social anchors. Useful as a research artifact, sellable to academic and journalistic users. Nothing equivalent ships today.
2. **Wallet skill calibration with negRisk-aware portfolio reconstruction**. Existing leaderboards rank by PnL only. Calibrating realised win rate against entry-time implied probability across a wallet's full position history (including negRisk conversions) is non-obvious and publishable.
3. **Cross-market arbitrage detection as a counter-signal**. Wallets that systematically realize the ~$40M of measured combinatorial arbitrage (Saguillo et al.) should be tagged as professional arbitrageurs, not manipulators. Reduces false positives — a real product-quality differentiator.
4. **UMA-dispute-aware market scoring**. Markets that ended in disputes are anomalous a priori; flagging them and tracking the wallets that pre-positioned before the dispute is a Gap 1 signal with extremely clean labels (dispute = ground truth label).
5. **Polygon MEV side-channel on settlement** (Gap 8). Niche but publishable; less commercially valuable.

---

## 4. Compatibility with Polymarket's actually-available data

This section was confirmed by live probes on 2026-05-11 against the production endpoints. All findings supersede v1 §5–9 where they conflict.

### 4.1 Confirmed working endpoints

```text
GET  https://gamma-api.polymarket.com/markets             (no auth, paginated)
GET  https://gamma-api.polymarket.com/markets/slug/{slug}
GET  https://clob.polymarket.com/book?token_id={...}
GET  https://clob.polymarket.com/prices-history?market={token}&startTs=...&endTs=...&interval=1h&fidelity=60
GET  https://data-api.polymarket.com/trades?market={conditionId}&filterType=CASH&filterAmount=10000&limit=...
GET  https://data-api.polymarket.com/holders?market={conditionId}&limit=...
```

### 4.2 Field-level facts that affect schema design

**Gamma `/markets` adds these fields that v1 did not enumerate**, and they materially change the design:

```text
bestBid, bestAsk           # top-of-book snapshot in Gamma itself — reduces /book polling
lastTradePrice             # last execution
spread                     # pre-computed
negRisk, negRiskOther, negRiskRequestID  # YNB-NR family membership
oneMonthPriceChange        # pre-computed momentum
volume24hrClob, volume1wkClob, volume1moClob, volume1yrClob  # CLOB-only volume separable from total volume
liquidityClob              # CLOB-only liquidity
rewardsMinSize, rewardsMaxSpread, holdingRewardsEnabled  # market-maker reward params
umaBond, umaReward, umaResolutionStatuses                 # resolution-stage state
clearBookOnStart           # operational, affects book-history continuity
orderPriceMinTickSize, orderMinSize                       # microstructure constants
```

⇒ Add these to the `markets` table in v1 §13.1.

### 4.3 Time-unit landmines

Different endpoints use different time units. Getting this wrong silently breaks every downstream join.

| Endpoint | Field | Unit |
|---|---|---|
| Gamma | `startDate`/`endDate`/`createdAt`/`updatedAt` | ISO-8601 strings (UTC) |
| Gamma | `acceptingOrdersTimestamp`/`deployingTimestamp` | ISO-8601 strings (UTC) |
| CLOB `/book` | `timestamp` | **milliseconds since epoch** |
| CLOB `/prices-history` | `t` | seconds since epoch |
| Data API `/trades` | `timestamp` | seconds since epoch |
| WebSocket market events | varies by event type | check per event |

Mitigation: every loader writes a single canonical `ts_utc` column (timezone-aware `datetime64[ns, UTC]`) and discards the source unit immediately.

### 4.4 negRisk membership matters

In the live Gamma probe, the top-volume Bitcoin market had `negRisk: False`. But many high-volume political markets (election fields, sports brackets) are negRisk YNB-NR. **Family linkage is via the `event` id, not via `negRiskRequestID`** — each market carries its own `negRiskRequestID` (per-market, points at UMA), while family membership is established by all members sharing the same `events[0].id` (and that event has `negRisk: true` and a `negRiskMarketID`). Confirmed against `GET /events/{id}.markets` in the live notebook exploration. **Wallet-flow analysis on a negRisk market in isolation will systematically undercount conversion-based positioning.** v2 introduces a `neg_risk_families` table:

```sql
CREATE TABLE neg_risk_families (
  family_event_id TEXT,           -- Gamma event id (e.g. "30615")
  family_event_slug TEXT,
  neg_risk_market_id TEXT,        -- event.negRiskMarketID
  member_condition_id TEXT,
  member_token_id_yes TEXT,
  member_token_id_no TEXT,
  member_slug TEXT,
  member_outcome_name TEXT,
  PRIMARY KEY (family_event_id, member_condition_id)
);
```

Whenever a wallet trades a member, the analyzer must consider all family members for the same wallet within the lookback window before signing pressure.

### 4.5 Holders endpoint takes conditionId and returns nested-by-token

Live probe + notebook confirmed: `/holders` takes a **conditionId** as the `market=` parameter (passing a token id returns HTTP 400). One call returns *both* outcomes — the response is a list `[{token, holders: [...]}, ...]` with one entry per outcome token. Also: `minBalance` must be an **integer** (`1`, not `1.0`, or the endpoint 400s). The loader must flatten this nested shape and never assume a single call returns only one outcome.

### 4.6 What is NOT free from Polymarket

Confirming v1 §11 with the SoK paper's archiving section:

- Historical full-depth L2 order books beyond what PMXT covers.
- Maker/taker counterparty attribution (taker is implicit, maker is not exposed).
- Order placement / cancellation events at granularity needed for spoofing proof.

⇒ Spoofing is detectable only as a **proxy** (book instability) and must be labelled as such. The paper's Insight 4 explicitly notes matching-based CLOBs are expensive on-chain at scale; Polymarket matches off-chain, so the CLOB internals are not on Polygon.

### 4.7 What IS free, that v1 underused

- **ERC-1155 mint/burn/transfer events on Polygon** (from Goldsky / The Graph subgraph or Bitquery). Every splitting/merging operation per spec §3.4 emits these events. Wallet position changes by exact token are reconstructable independently of the Data API.
- **UMA Optimistic Oracle dispute logs**. Disputed markets are pre-labelled high-anomaly samples.
- **Gnosis CTF events**. The final payout vector is written here at resolution — clean ground truth.
- **Polymarket leaderboard endpoints** (mentioned in `Awesome-Prediction-Market-Tools` index; existence to be verified) — pre-computed PnL rankings, useful for calibration.

---

## 5. Architecture

```
                      ┌───────────────────────┐
                      │   Resolution-criteria │  ← Anthropic / OpenAI, bounded
                      │   LLM parser          │     (Gap 4 only)
                      └───────────┬───────────┘
                                  │
┌──────────────┐   ┌──────────────▼──────────────┐   ┌────────────────┐
│ Gamma API    │──▶│   markets / families table  │◀──│ Subgraph       │
│ Data API     │   │   (DuckDB + parquet)        │   │ (Goldsky/Graph)│
│ CLOB REST    │──▶│                              │◀──│ → ERC-1155,    │
│ CLOB WS      │──▶│   trades / book_snapshots   │   │   UMA, CTF     │
└──────────────┘   │   prices / wallet_positions │   └────────────────┘
                   └──────────┬───────────────────┘
                              │
                  ┌───────────▼───────────┐
                  │  Feature builders     │
                  │  - microstructure     │
                  │  - wallet skill       │
                  │  - graph / clusters   │
                  │  - arbitrage          │
                  └───────────┬───────────┘
                              │
              ┌───────────────┴────────────────┐
              ▼                                ▼
      ┌──────────────┐                ┌─────────────────┐
      │ Subscores    │                │ Replay engine   │
      │ (per event)  │                │ (Gap 10)        │
      └──────┬───────┘                └─────────────────┘
             │
             ▼
      ┌──────────────┐
      │ Triage UI    │
      │ analyst note │  ← LLM, narrative only
      └──────────────┘
```

Storage is **local-first**: a single workstation with DuckDB + parquet handles the MVP for any reasonable backtest period. Migrate to S3 + a real warehouse only when daily ingest exceeds ~10 GB sustained.

---

## 6. Scoring (revised from v1)

Two independent scores, recombined at triage time:

### 6.1 Microstructure event score (per suspicious window)

```
s_micro =
  0.30 * whale_concentration_z          # wallet_share_5m, family-aware
+ 0.20 * price_move_magnitude_z         # |Δp_5m| relative to market regime
+ 0.15 * reversal_z                     # Δp_30m vs Δp_5m
+ 0.15 * liquidity_thinness_z           # spread_before, depth_before_2c (negated)
+ 0.10 * book_instability_z             # order-book churn proxy for spoofing
+ 0.10 * mev_proximity_z                # nearby MEV bundle indicator (Polygon)
```

Each term is z-scored within a comparable cohort (same negRisk family OR same volume tier), then squashed via logistic to `[0, 1]`.

### 6.2 Wallet skill / coordination score (per wallet, rolling)

```
s_wallet =
  0.30 * bayesian_calibration_gap       # realised win rate − implied probability at entry (Beta posterior)
+ 0.20 * longshot_concentration         # fraction of notional placed at p<0.20 with win
+ 0.20 * graph_cluster_volume_share     # share of wallet's volume inside its closed Louvain cluster
+ 0.15 * round_trip_ratio               # wash-trade proxy
+ 0.10 * pre_dispute_positioning        # took winning side before UMA dispute resolved
+ 0.05 * mev_attribution                # wallet appears in MEV bundles
```

A wallet that scores high on both `s_wallet` and is involved in events with high `s_micro` is the strongest signal — but the scores stay separate in storage so analysts can audit each independently. **Professional arbitrageurs will show high `bayesian_calibration_gap` because they win consistently; the `arbitrage_share` counter-feature exists specifically to subtract their contribution from suspicion.**

---

## 7. Data model (v2)

Add to v1 §13:

```sql
CREATE TABLE neg_risk_families (
  family_id TEXT,
  member_condition_id TEXT,
  member_token_id_yes TEXT,
  member_token_id_no TEXT,
  member_slug TEXT,
  PRIMARY KEY (family_id, member_condition_id)
);

CREATE TABLE uma_disputes (
  request_id TEXT,
  condition_id TEXT,
  disputed_at TIMESTAMP,
  resolved_at TIMESTAMP,
  proposer TEXT,
  disputer TEXT,
  final_outcome TEXT,
  bond_amount DOUBLE,
  reward_amount DOUBLE
);

CREATE TABLE wallet_positions_onchain (
  -- reconstructed from ERC-1155 mints/burns/transfers
  proxy_wallet TEXT,
  token_id TEXT,
  ts TIMESTAMP,
  delta_amount DOUBLE,
  running_amount DOUBLE,
  tx_hash TEXT,
  event_type TEXT,        -- mint, burn, transfer_in, transfer_out, split, merge, convert
  source TEXT             -- subgraph, bitquery, dune
);

CREATE TABLE arbitrage_legs (
  -- detected combinatorial arbitrage per Saguillo et al. 2025 method
  arb_id TEXT,
  leg_idx INT,
  wallet TEXT,
  condition_id TEXT,
  token_id TEXT,
  ts TIMESTAMP,
  side TEXT,
  size DOUBLE,
  price DOUBLE,
  realized_pnl DOUBLE
);

CREATE TABLE mev_bundles (
  -- from mev-inspect-py output on Polygon
  bundle_hash TEXT,
  block_number BIGINT,
  searcher TEXT,
  bundle_type TEXT,        -- sandwich, backrun, liquidation
  victim_tx TEXT,
  affected_token_id TEXT,
  ts TIMESTAMP
);

CREATE TABLE replay_timeline (
  -- the Gap 10 stepwise replay tape
  market_or_family_id TEXT,
  ts TIMESTAMP,
  event_kind TEXT,          -- trade, book_change, news, social, dispute_filed, dispute_resolved, resolution
  payload JSON,
  source TEXT
);
```

---

## 8. Phased build plan

### Phase 1 — read-only static loaders (Week 1–2)
Goal: pull, persist, validate. No scoring.

- Gamma `/markets` paginator with all confirmed fields (§4.2).
- CLOB `/prices-history` per token, 1h and 1m fidelities.
- Data API `/trades` by `conditionId` with full pagination.
- Data API `/holders` per token (handle nested-by-token shape).
- Persist as parquet via Polars → DuckDB views.
- Build `neg_risk_families` table from the `negRiskRequestID` field.
- Data-quality assertions (v1 §25), enriched with `bestBid <= bestAsk` and `volume24hrClob <= volume24hr`.

**Exit criterion**: can answer "list the 50 most volume-active markets in the last 7 days with their YNB-NR families and current top-3 holders per outcome" in a single DuckDB query.

### Phase 2 — event study + arbitrage detector (Week 3–4)
- Implement v1 §23 event-study skeleton at the family level (not per-market).
- Implement Saguillo-style combinatorial arbitrage detector for negRisk families and logically-equivalent markets.
- Bayesian wallet skill with `Beta(α, β)` posterior on win/loss vs. implied probability, accounting for outcome via Polymarket's leaderboard endpoints + on-chain settlement.

**Exit criterion**: `arbitrage_legs` and `wallet_features` tables populated for one full month, manually spot-checked against three known whale wallets.

### Phase 3 — on-chain ground truth (Week 5–6)
- Subgraph wiring (Goldsky or Bitquery hosted) to ingest ERC-1155 mint/burn/transfer and UMA disputes.
- Reconcile Polymarket Data API trade counts against on-chain settlement totals — any divergence is itself a quality signal.
- Populate `wallet_positions_onchain` and `uma_disputes`.

**Exit criterion**: every event in `uma_disputes` has a populated `final_outcome` reconciled with Polymarket's stated resolution, and divergences are flagged.

### Phase 4 — live WebSocket collector + SPRT alerts (Week 7–8)
- Subscribe to all active `clobTokenIds`.
- Persist raw events to JSONL before normalisation (v1 §10.2.3).
- Online SPRT over signed-pressure with a per-family-cohort null distribution learned in Phase 2.

**Exit criterion**: a live alert fires within 60 seconds of a synthetic whale-burst injection in test markets.

### Phase 5 — replay engine (Gap 10) + triage UI (Week 9–12)
- Stepwise tape over `replay_timeline` with seekable per-second resolution.
- Synchronise external news/social anchors (manual MVP, LLM-extracted later).
- LLM-generated analyst notes with mandatory citation of feature values that drove the score.

**Exit criterion**: an analyst can scrub through a contested market's last 24 hours and see news, on-chain settlement events, whale trades, book changes, and dispute filings on one synchronised timeline.

### Phase 6 — MEV side-channel (Gap 8) (optional, Week 13+)
- Run `mev-inspect-py` against Polygon blocks where Polymarket settlement / splitting / merging txns appear.
- Cross-tag suspicious events with nearby MEV bundles.

---

## 9. Risks & open questions

1. **negRisk conversion event observability**. Conversions are on-chain (CTF gadget calls) but the Data API may not surface them as trades. Phase 3 must verify.
2. **Maker/taker counterparty inference**. Without exposed maker, wash-trade graph edges are approximated. We accept this in v2 and flag it in every analyst note.
3. **Survivorship bias in PMXT coverage**. PMXT started its archive at a specific date; backtests before that date have no L2. Document the coverage window in every backtest report.
4. **LLM resolution-parser drift**. Chainlink reports 89.3% accuracy but with model-specific results. Pin the model and version; re-run a calibration sample monthly.
5. **Polygon reorg safety**. Subgraphs handle reorgs; if we add an Erigon node, reorg handling must be explicit.

---

## 9b. 2026-08-29 audit addendum (overrides earlier sections where they conflict)

1. **Time reference.** All "hours before close" quantities use Gamma `closedTime` (`markets.closed_time`), never `endDate`. §6.1 windows anchored on `end_date` are void.
2. **Entity graph edges.** ERC-1155 transfers are settlement of CLOB fills and are excluded from relationship inference; direct edges are USDC transfers only; universe members count toward counterparty popularity. Sybil/entity claims require funding-flow evidence.
3. **Null models.** Cotrade and lead–lag tables carry activity-preserving expected counts, Poisson p-values and BH q-values; only pairs with q < 0.05 may be described as anomalous. Lead–lag adjacency is defined on consecutive distinct seconds.
4. **Skill (§6.2).** The wallet skill / calibration score is the position-level statistic (`skill.position_skill`): one trial per (wallet, market), implied p ∈ [0.05, 0.95], ≥ 5 positions in ≥ 3 markets, Beta prior strength 4 centred on the wallet's mean implied p, exact quantiles, leave-one-out reliability-curve benchmark. The size-weighted variant is legacy.
5. **Backtest.** Leader trades after `event_ts` (last unconverged trade) are excluded; exits use `closed_time`; every leader set is compared with a matched placebo control (same asset, side, ±900 s, ±0.05) and inference is clustered by market. Universe-drawn random sets are not controls.
6. **Data limitations to state in every output.** Taker-side, 4000-fill tail sample; holders capped at 500/outcome; price history = 30-day window; on-chain history page-capped. Positive wallet-level claims are deferred until the Phase 3 `OrderFilled` reconstruction ships.
7. **Wash trading.** Renamed "rapid position flipping"; one-to-one matching; maker signature reported. Wash labels require counterparty attribution (Phase 3).

8. **Fill reconstruction (Phase 3) is the data source for every wallet-level claim.** `OrderFilled` on the CTF Exchange (0x4bfb…982e) and NegRisk CTF Exchange (0xc5d5…f80a): one record per maker order plus one taker-order record whose `taker` is the exchange; mint/merge matches pair the taker's token with the complementary token at 1 − p, so shares conserve per (tx, market). Reconciliation invariants: exact taker match with the feed, per-tx conservation, coverage gain, and completeness = Σ taker shares / Gamma `volumeClob` (Gamma volume is share volume). Validated 2026-08-29 on 5 markets.

## 10. Stage II — Explore / confirm protocol (subsequent stage, added 2026-08-29)

Stage I (everything above, as corrected by the §9b audit) is complete: a
validated, reproducible measurement stack whose corrected results on the
2026-05-11 corpus are null. Stage II is a **new stage of the project**, not a
revision of Stage I, and it changes the study design in response to two facts
established on 2026-08-29:

1. The cross-sectional versions of RQ1–RQ3 have been answered in 2026 on
   complete data by other groups (Mitts & Ofir 2026; Gómez-Cram, Guo, Kung &
   Jensen 2026; Sirolly, Ma, Kanoria & Sethi 2025; arXiv:2603.03136;
   arXiv:2604.24366; arXiv:2606.16852; the Polymarket-v1 Database,
   arXiv:2606.04217, CC-BY-4.0). Re-asking them cross-sectionally is not a
   contribution.
2. Polymarket migrated to v2 on 2026-04-28 (new exchange contracts
   `0xe111180000d2663c0091e4f400237545b87b996b` and
   `0xe2222d279d744050d28e00520010520000310f59`, pUSD collateral
   `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`) after phasing in taker fees
   with per-market maker rebates from 2026-03-30 by category, with
   geopolitics / world events fee-exempt. No published work covers v2.

### 10.1 Design: two independent samples

- **Sample A (exploration): v1, 2025-10-01 → 2026-04-28**, from the public
  Polymarket-v1 archive (`OrderFilled`, `daily_aligned`, `daily_aligned_multi`,
  `CTF` layers; maker, taker, ground-truth direction, price, fee, categories,
  resolutions, redemptions). Our own Dune/Etherscan reconstruction (5 markets,
  134 wallets, `fills.py` invariants) is the QA layer: it must reconcile
  exactly with the archive on the overlap before the archive is used.
- **Sample B (confirmation): v2, 2026-04-28 → collection date**, collected by
  us from the chain: v2 `OrderFilled(orderHash, maker, taker, side, tokenId,
  makerAmountFilled, takerAmountFilled, fee, builder, metadata)`,
  `OrdersMatched`, `FeeCharged(receiver, amount)` on both v2 exchanges, and
  the v2 conditional-tokens resolution / redemption events; Etherscan V2
  `getLogs` with block-range bisection (free tier, ≈1–2k calls per day of
  tape). Invariants: taker match via `OrdersMatched`, per-tx conservation,
  completeness vs `FeeCharged` totals. Market metadata and the category →
  fee mapping come from Gamma, which must be fetched from an unblocked
  network (EU VPS or collaborator).

### 10.2 Protocol

1. **Explore on A only.** Compute the atlas (§10.3) and report it as
   descriptive statistics — no hypothesis tests presented as confirmatory.
2. **Register before touching B.** Every hypothesis suggested by the atlas is
   written into `docs/stage2_preregistration.md` with its statistic,
   direction, subgroup, null model and decision rule, dated and committed
   *before* any B-side statistic is computed. Thresholds (buckets, lags,
   notional cuts, minimum positions) are frozen there.
3. **Confirm on B.** The registered hypotheses are tested on B with the
   fee-regime design (§10.4). Unregistered findings on B are reported as
   exploratory in a separate section.
4. **Replication rule.** A result is claimed only if it (a) holds on B under
   the registered rule, or (b) is the registered difference between A and B
   attributable to the regime change. Atlas findings that fail on B are
   reported as such.

### 10.3 Atlas statistics (exploration set; computed on A, then on B)

- Order-flow attribution (B only has `builder`): fill share, maker/taker mix,
  effective half-spread, price impact and informed-trading signatures by
  order-flow source.
- Fee / rebate flows (B): per-fill fee incidence, rebate concentration,
  rebate per notional by wallet, self-matching that earns rebates.
- Liquidity provision: maker share and concentration by market, category,
  negRisk status; Kyle's λ per market; effective half-spread from fills.
- Wallet lifecycle: entry, exit, v1→v2 migration by wallet type (maker-
  dominant, taker-dominant, skilled minority per Gómez-Cram criteria).
- Position-level calibration with the leave-one-out reliability-curve
  benchmark (`skill.position_skill`), stratified by category, lifetime,
  holding horizon; documented insider cases (FFIC, CC-BY) as validation.
- Coordination with counterparty attribution: self-counterparty and one-step
  round-trip shares, activity-preserving nulls with BH control, network
  clusters; negRisk family consolidation.
- Redemption behaviour: resolution-to-redemption delay, unredeemed winnings
  by wallet type.

### 10.4 Confirmatory design

Difference-in-differences / event study around 2026-03-30 (fee schedule) and
2026-04-28 (exchange upgrade), treated = fee-charged categories, control =
fee-exempt categories; staggered rollout handled with a staggered-DiD
estimator; category-by-week panels; market-clustered standard errors;
pre-trend checks; sensitivity excluding reverted matches (ghost fills), the
migration week, and 15-minute crypto markets. Refined questions: RQ1′
liquidity provision and price impact under maker rebates; RQ2′ wash-like
activity vs rebate farming; RQ3′ persistence of informed-trading signatures
across regimes.

### 10.5 Constraints

Measured 2026-08-29: v2 runs ~3.4 M `OrderFilled` per day across the two
exchanges (first 2,000 v2 blocks: 166,576 fills, 64,377 taker orders, 297
distinct `builder` codes). Etherscan bisection needs roughly 5,000 calls per
day of tape for `OrderFilled` alone, so the full May–August tape is ~6 days
of the 100k/day quota; the crawl (`scripts/10`) is chunked, resumable and
relaunched daily. `OrdersMatched` and `FeeCharged` are not crawled by
default: the taker-order record and the per-fill `fee` field carry the same
information. **Close reference:** the archive's `resolved_at` is NULL for
early/contested resolutions and `close_at` is the scheduled deadline; the
on-chain `ConditionResolution` timestamp (`ctf_resolutions*.parquet`) is the
only authoritative close and is used first (`archive.materialise_markets`
refuses to proceed if any market shows fills after its close).

All data sources are free: the v1 archive (HuggingFace), Etherscan V2
(5 calls/s, 100k/day), Blockscout (keyless), Gamma (unblocked network
required). Dune is not used (per-row billing). Nothing in Stage II modifies
Stage I outputs; Stage I snapshots remain the reference for the audit
history.

## 11. References

- Rahman, Al-Chami, Clark. *SoK: Market Microstructure for Decentralized Prediction Markets*, arXiv:2510.15612v2 (2026).
- Saguillo et al. *Unravelling the probabilistic forest: Arbitrage in prediction markets*. Advances in Financial Technology 2025.
- Hanson. *Insider trading and prediction markets*. JL Econ & Pol'y 4, 2007.
- Milionis et al. *Incentive-compatible recovery from manipulated signals*. arXiv:2503.07558, 2025.
- Zintus-art & Ward. *Empirical evidence in AI oracle development*. Chainlink, 2025.
- Eskandari et al. *SoK: Oracles from the ground truth to market manipulation*. AFT 2021.
- Polymarket API docs: https://docs.polymarket.com
- PMXT archive: https://archive.pmxt.dev
- The Graph: https://thegraph.com
- Bitquery Polymarket: https://docs.bitquery.io/docs/examples/polymarket-api/
- mev-inspect-py: https://github.com/flashbots/mev-inspect-py
- v1 spec in this repo: `polymarket_market_manipulation_data_spec.md`
- `polymarket_free_api_exploration.ipynb` — end-to-end live demo of the free APIs, preprocessing pitfalls, and a toy 5-min suspicion score

# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Status

This repository currently contains **no code** — only planning specifications and a background research PDF. It is not yet a git repository. The documents present:

1. `polymarket_anomaly_detection_spec_v2.md` — **current spec, supersedes v1**. Adds: paper synthesis, SOTA tool mapping, negRisk-family awareness, two-score model (microstructure × wallet skill), on-chain ground-truth layer (subgraph + UMA disputes + CTF events), Gap-10 replay engine, MEV side-channel. Confirmed against live API probes.
2. `polymarket_market_manipulation_data_spec.md` — **v1, retained for context**. v2 explicitly overrides v1 in any conflict.
3. `Nahid Rahman - SoK Market Microstructure for Decentralized Prediction Markets (DePMs) [2025]-1.pdf` — Rahman, Al-Chami, Clark (arXiv:2510.15612v2). Taxonomy paper, not a detection survey, but its **Research Gaps 1, 3, 8, 10** drive v2.

When implementing, **v2 is the source of truth**. Read it before proposing structure, dependencies, or APIs.

## What this project is

A **market-integrity intelligence pipeline for Polymarket**, not a generic data wrapper. The goal is **suspicion scoring and investigative triage** of market-manipulation patterns (whale-driven price impact, pump-and-reversal, wash trading, liquidity vacuums, insider-timing). Output is ranked suspicious events with explanations — never a legal claim of manipulation. This framing affects naming, copy, and how confidence is surfaced: prefer "suspicious", "anomalous", or "consistent with manipulation" over "manipulation detected".

## Architecture the spec mandates

The spec defines a five-phase build. Earlier phases must be usable standalone; later phases enrich, they do not replace.

1. **Static loaders** — Gamma (`gamma-api.polymarket.com`) for market metadata, CLOB (`clob.polymarket.com`) for prices/books, Data API (`data-api.polymarket.com`) for trades/holders/positions. All read-only, no auth.
2. **Event-study engine** — whale-trade detection + pre/post price moves + reversals + placebo tests.
3. **Live WebSocket collector** — `wss://ws-subscriptions-clob.polymarket.com/ws/market`, subscribing to all active `clobTokenIds`, persisting raw events before normalization.
4. **Historical L2 enrichment** — PMXT archive (free) first; paid providers only when justified.
5. **ML / graph layer** — anomaly detection, wallet-cluster/entity inference, calibration via human review.

Storage layout is parquet-on-object-store with a parallel SQL schema (see spec §13). Raw WebSocket events are persisted **before** normalization — never normalize-and-discard.

### Identifier discipline (easy to get wrong)

Polymarket has multiple overlapping IDs and they are not interchangeable:

- `conditionId` keys the **Data API** (`/trades`, `/holders`, `/positions`).
- `clobTokenIds` / `asset_id` (per outcome) keys the **CLOB API** (`/book`, `/prices-history`) and the **WebSocket**.
- `slug` is the only ID a human URL gives you.
- For binary markets, `outcomes[i] <-> outcomePrices[i] <-> clobTokenIds[i]` is positional — preserve order when zipping.

Gamma returns several array fields as **stringified JSON** (`outcomes`, `outcomePrices`, `clobTokenIds`). Always run them through a parser that tolerates both list and string forms (spec §5.3).

Persist all identifiers on every row from day one. Backfilling missing IDs later is expensive.

### Reliability conventions the spec requires

- UTC everywhere, but **time units differ per endpoint** (v2 §4.3): Gamma uses ISO-8601 strings; `CLOB /book.timestamp` is **milliseconds**; `CLOB /prices-history.t` and `Data /trades.timestamp` are **seconds**. Every loader converts to a canonical `ts_utc` (`datetime64[ns, UTC]`) immediately and discards the source unit.
- Exponential backoff on HTTP 429.
- Persist raw JSON before transformation; ingestion must be idempotent keyed by source identifiers.
- Do **not** poll `/book` at high frequency — use the WebSocket for live L2.
- Reconcile WebSocket-derived books against periodic CLOB `/book` snapshots; track gaps and disconnects explicitly.
- For negRisk markets, **never analyze a single Yes/No pair in isolation** — consolidate flow across the full negRisk family (linked by `negRiskRequestID`) before signing pressure.

### Scoring framework

The composite `suspicion_score` is the weighted sum in spec §20 with tiers Low / Medium / High / Critical at 0.40 / 0.60 / 0.80. Each sub-score (whale concentration, abnormal price move, reversal, low liquidity, wash cluster, insider timing, recurrence) is normalized to `[0, 1]` independently before weighting. Do not invent new weights without updating §20.

### LLM guardrails

LLMs are used for parsing market questions, summarizing news timelines, and writing analyst notes — **never** as the primary statistical engine and never to label a wallet as manipulative without statistical backing. Prompts and outputs must be stored for auditability.

## Working without code

Until source files exist, "implementing X" means **writing the first cut of X consistent with the spec**, not retrofitting an existing module. Before writing code:

- Confirm the language/runtime/framework with the user (the spec uses Python snippets but does not mandate Python overall).
- Confirm where state will live (the spec assumes S3-style object storage + a SQL warehouse; a laptop-only first cut may use local parquet + DuckDB).
- Confirm whether this is the MVP "Phase 1 static loader" or a later phase — they have very different scopes.

There is no build, lint, or test command yet. Add this section to CLAUDE.md once tooling is chosen.

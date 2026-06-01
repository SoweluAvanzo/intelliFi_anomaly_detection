# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A **market-integrity intelligence pipeline for Polymarket**, not a generic data wrapper. The goal is **suspicion scoring and investigative triage** of market-manipulation patterns (whale-driven price impact, pump-and-reversal, wash trading, liquidity vacuums, insider-timing). Output is ranked suspicious events with explanations — never a legal claim of manipulation. This framing affects naming, copy, and how confidence is surfaced: prefer "suspicious", "anomalous", or "consistent with manipulation" over "manipulation detected".

The repo is named `IntelliFi_anomaly_detection` for historical reasons (typo for "Polymarket"); the work is entirely about Polymarket.

## Spec hierarchy

1. `polymarket_anomaly_detection_spec_v2.md` — **current design spec**, source of truth. Read it before proposing structure, dependencies, or APIs.
2. `polymarket_market_manipulation_data_spec.md` — **v1, retained for context only**. v2 explicitly overrides v1 in any conflict.
3. `Nahid Rahman - SoK Market Microstructure for Decentralized Prediction Markets (DePMs) [2025]-1.pdf` — Rahman, Al-Chami, Clark (arXiv:2510.15612v2). Taxonomy paper, not a detection survey. Its **Research Gaps 1, 3, 8, 10** are the project's north star.

## Implementation status (as of 2026-05-25)

**Shipped:**

- Phase 1 (static loaders) — Gamma, CLOB, Data API loaders writing typed parquet.
- Phase 2 (event study) — concentration metrics, skill calibration, mirror-strategy backtest, resolution-convergence analysis.
- Parts of Phase 3 (on-chain ground truth) — Etherscan V2 enrichment of USDC.e, native USDC, and ERC-1155 transfers for the universe of top-trading wallets. **CTF/UMA subgraph not yet wired** — trades are still capped at the Data API's ~4000-most-recent limit.
- Phase 5 prototype — wallet entity resolution (on-chain × cotrade graphs + Louvain) and a four-leader-set mirror-strategy backtest.

**Not shipped yet:**

- Polygon CTF / UMA subgraph backfill — would close the 4000-trade cap and provide UMA-dispute labels.
- Live WebSocket collector + SPRT alerts (Phase 4).
- Gap-10 stepwise replay engine (Phase 5 full).
- MEV side-channel on settlement path (Phase 6 / Gap 8).
- Insider-timing pre-event positioning ("Phase 4 Gap 1" in spec).

The current state is a coherent vertical slice covering objectives 1–5 in v2 §6 with documented data-quality caveats. It is sufficient for a workshop-tier submission today; full-venue publishability is blocked by the items above.

## How to run

Local-first; everything runs from a single workstation with no auth except an optional free Etherscan-V2 key for on-chain transfers.

```bash
# install (Python 3.11+)
pip install -e .[notebook]

# end-to-end pipeline (each script is independently re-runnable)
python scripts/01_fetch_resolved_markets.py --lookback-days 180 --top-n 1000 --write
python scripts/02_fetch_trades_and_holders.py --workers 4
export POLYGONSCAN_API_KEY=...   # free at polygonscan.com/myapikey
python scripts/03_resolve_wallet_entities.py
python scripts/04_coordination_analysis.py
python scripts/05_backtest_mirror.py
python scripts/06_convergence.py

# notebooks
jupyter lab notebooks/
```

There is no lint / test target yet. `pyproject.toml` declares `ruff` and `pytest` in `[project.optional-dependencies].dev`, but no tests exist. Add them under `tests/` if introducing new behaviour.

## Module map (`src/intellifi/`)

| Module | Responsibility |
|---|---|
| `config.py` | Endpoint roots, storage paths, tunable constants. All overridable by `INTELLIFI_*` env vars. |
| `http.py` | HTTP layer with exponential backoff on 429. |
| `normalize.py` | JSON → typed Python coercion (array-field parser, ISO/epoch → UTC, safe casts). |
| `gamma.py` | Gamma API loader: `/markets`, `/events`. Writes `markets.parquet` + `neg_risk_families/families.parquet`. |
| `data_api.py` | Data API loader: `/trades` (4000-trade cap acknowledged), `/holders`. Partitioned by `condition_id`. |
| `clob.py` | CLOB `/prices-history` per outcome token. |
| `onchain.py` | Polygon JSON-RPC + Etherscan V2 client (USDC.e, native USDC, ERC-1155 transfers). |
| `warehouse.py` | DuckDB views over the parquet store. Views are recreated on every call — globs, never materialized. |
| `concentration.py` | Gini / HHI / Lorenz at market, negRisk-family, and platform-wide level. |
| `skill.py` | Reliability curve + Bayesian Beta posterior with prior centred on each wallet's own mean implied probability. PnL helper. |
| `wallet_graph.py` | Universe selection + on-chain entity graph (direct + common-neighbour edges) + Louvain. |
| `coordination.py` | Cotrade pairs, leader-lag, wash-round-trips. |
| `backtest.py` | Mirror-strategy engine: latency, exit horizons, fee model. |
| `convergence.py` | Per-market winner-price abs-error over hours-before-end. |

Scripts in `scripts/` are thin orchestrators (one per pipeline stage). Notebooks in `notebooks/` are narrative and read parquet outputs only.

## Storage layout

```
data/
├── raw/                            # immutable JSONL, written before normalization
│   ├── gamma/markets/<run_id>.jsonl
│   └── data_api/{trades,holders}/<condition_id>.jsonl
└── parquet/                        # typed, analysis-ready
    ├── markets/markets.parquet
    ├── neg_risk_families/families.parquet
    ├── trades/condition_id=<cid>/part.parquet
    ├── holders/condition_id=<cid>/part.parquet
    ├── prices_history/<token_id>.parquet
    ├── onchain_transfers/{erc1155,usdc_e,usdc_native}/<address>.parquet
    ├── universe.parquet
    ├── wallet_graph/{communities.parquet, partition.json}
    ├── coordination/{cotrade_pairs, leader_lag, wash_round_trips, behavioural_partition}
    ├── backtest/<leader_set>_events.parquet, summary.parquet
    └── convergence/{per_market, aggregate}.parquet
```

`intellifi.duckdb` holds **only view definitions** over the parquet glob — no data, no cached state. Whatever is on disk is the truth.

## Architecture and conventions

### Three invariants

1. **Raw before normalized.** Every API call writes its raw JSON to `data/raw/...` before normalization. Schema changes upstream can be backfilled without re-hitting the API.
2. **Content-derived partition keys.** `condition_id=<cid>`, `<address>.parquet`, `<token_id>.parquet`. Existence-of-file = "already fetched"; loaders skip-if-exists by default. Pass `--overwrite` to refresh.
3. **UTC everywhere, but time units differ per endpoint** (v2 §4.3). Gamma uses ISO-8601, `CLOB /prices-history.t` is **seconds**, `CLOB /book.timestamp` is **milliseconds**, `Data API /trades.timestamp` is **seconds**. Every loader converts to canonical `ts_utc` (`datetime64[us, UTC]`) at the boundary and discards the source unit.

### Identifier discipline (easy to get wrong)

Polymarket has multiple overlapping IDs and they are not interchangeable:

- `conditionId` keys the **Data API** (`/trades`, `/holders`).
- `clob_token_ids` / `asset_id` (per outcome) keys the **CLOB API** (`/book`, `/prices-history`) and the **WebSocket**.
- `slug` is the only ID a human URL gives you.
- For binary markets, `outcomes[i] <-> outcome_prices_final[i] <-> clob_token_ids[i]` is positional — preserve order when zipping.

Gamma returns `outcomes`, `outcomePrices`, `clobTokenIds` as **stringified JSON** in some responses and native arrays in others. Always parse via `normalize.parse_array_field`.

Persist all identifiers on every row from day one. Backfilling missing IDs later is expensive.

### NegRisk consolidation

For markets with `event_neg_risk=True`, **never analyze a single Yes/No pair in isolation** — consolidate flow across the full negRisk family (linked by `event_id`) before signing pressure. See `concentration_table(con, group='family')`.

### Bayesian skill prior

The Beta prior in `skill.wallet_skill` is centred on each wallet's own `mean_implied_p`, not on 0.5. The null hypothesis is therefore "this wallet wins at the rate it paid for", and `calibration_gap = posterior_mean − mean_implied_p` measures edge above the wallet's own entry-implied probability. This is the project's headline statistic; do not change the prior centring without updating the spec.

### Louvain community ids are not stable

`networkx` / `python-louvain` produces a fresh integer labelling per run. **Never reference a community by literal id** (`c == 65`) in code. Always identify clusters structurally — e.g. "the community that maximally overlaps with on-chain entity #0" (see the `Counter`-based selector in `scripts/05_backtest_mirror.py`, the `behavioural_twin` leader set). A latent bug of this form was patched on 2026-05-25 — watch for similar patterns when extending the pipeline.

### Scoring framework

The composite `suspicion_score` is the weighted sum in spec §6/§20 with tiers Low / Medium / High / Critical at 0.40 / 0.60 / 0.80. Each sub-score (whale concentration, abnormal price move, reversal, low liquidity, wash cluster, insider timing, recurrence) is normalized to `[0, 1]` independently before weighting. Do not invent new weights without updating the spec.

### Reliability conventions

- Exponential backoff on HTTP 429.
- Persist raw JSON before transformation; ingestion must be idempotent keyed by source identifiers.
- Do **not** poll `/book` at high frequency — use the WebSocket for live L2 (Phase 4, not yet built).
- Reconcile WebSocket-derived books against periodic CLOB `/book` snapshots; track gaps and disconnects explicitly.

### LLM guardrails

LLMs are used for parsing market questions, summarizing news timelines, and writing analyst notes — **never** as the primary statistical engine and never to label a wallet as manipulative without statistical backing. Prompts and outputs must be stored for auditability.

## Known latent issues

- **`/trades` 4000-trade cap.** `data_api.TRADES_MAX_REACHABLE = 4000`. High-volume markets are tail-sampled in their early phase. Phase 3 (Polygon CTF subgraph) closes this gap.
- **`/prices-history` pruning.** Polymarket aggressively prunes the endpoint after resolution; in the current dataset only ~17 of 100 markets return non-empty `interval=max` series. Convergence analysis is biased toward recently-resolved markets.
- **Orphan partitions.** If `markets.parquet` is rebuilt with a different top-N and a previously-included `condition_id` falls out, its `trades/holders` partitions remain on disk. The `trades` view still surfaces those rows; queries that join `markets` drop them cleanly, but `select_universe` in `wallet_graph.py` aggregates `trades` *without* joining to `markets`, so the universe ranking would be slightly inconsistent with the `bets` view. Workaround: rerun with `--top-n 0` (strict superset), or manually remove orphan partitions before rerunning.
- **Stale cached layers on partial rerun.** Each idempotent loader skips its existing partitions; pass `--overwrite` to refresh trade tails, holder snapshots, or on-chain transfer history when extending the lookback window.
- **Notebook narrative may lag a rerun.** Markdown text in the three notebooks references concrete numbers (Gini 0.94, behavioural community 65, etc.) from the 2026-05-11 fetch. After a dataset extension, regenerate the notebooks rather than hand-editing the markdown.

## When asked to extend the dataset

For a wider lookback, the safe invocation is:

```bash
python scripts/01_fetch_resolved_markets.py --lookback-days 365 --top-n 0 --write -v
python scripts/02_fetch_trades_and_holders.py --overwrite --workers 4 -v
python scripts/03_resolve_wallet_entities.py --overwrite -v
python scripts/04_coordination_analysis.py -v
python scripts/05_backtest_mirror.py -v
python scripts/06_convergence.py -v
```

Then re-run the notebooks. The `behavioural_twin` leader set in script 05 selects the community by maximum overlap with on-chain entity #0, so it stays coherent across Louvain re-numbering.

## When asked to "implement X"

The library code in `src/intellifi/` is the unit of correctness; the scripts are thin orchestrators; the notebooks are narrative. Add new logic in `src/intellifi/<topic>.py` and expose it through a script if it requires fetching, or directly via the notebooks if it only transforms cached data. Avoid adding new top-level files unless absolutely necessary.

When extending the spec (e.g. wiring Phase 3 subgraph, Phase 4 WebSocket, Phase 5 replay, Gap 8 MEV, UMA-dispute labels), update `polymarket_anomaly_detection_spec_v2.md` together with the code so the spec remains source-of-truth.

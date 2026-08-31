# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A **market-integrity intelligence pipeline for Polymarket**, not a generic data wrapper. The goal is **suspicion scoring and investigative triage** of market-manipulation patterns (whale-driven price impact, pump-and-reversal, wash trading, liquidity vacuums, insider-timing). Output is ranked suspicious events with explanations — never a legal claim of manipulation. This framing affects naming, copy, and how confidence is surfaced: prefer "suspicious", "anomalous", or "consistent with manipulation" over "manipulation detected".

The repo is named `IntelliFi_anomaly_detection` for historical reasons (typo for "Polymarket"); the work is entirely about Polymarket.

## Spec hierarchy

1. `polymarket_anomaly_detection_spec_v2.md` — **current design spec**, source of truth. Read it before proposing structure, dependencies, or APIs.
2. `polymarket_market_manipulation_data_spec.md` — **v1, retained for context only**. v2 explicitly overrides v1 in any conflict.
3. `Nahid Rahman - SoK Market Microstructure for Decentralized Prediction Markets (DePMs) [2025]-1.pdf` — Rahman, Al-Chami, Clark (arXiv:2510.15612v2). Taxonomy paper, not a detection survey. Its **Research Gaps 1, 3, 8, 10** are the project's north star.

## Implementation status (as of 2026-08-29)

**Shipped:**

- Phase 1 (static loaders) — Gamma, CLOB, Data API loaders writing typed parquet. `markets` carries `closed_time` / `uma_end_date` / `game_start_time` (re-normalised from raw on 2026-08-29).
- Phase 2 (event study) — concentration (gross, net-flow, holdings), position-level skill calibration with exact Beta intervals and a reliability-curve benchmark, cost-basis-aware PnL, mirror-strategy backtest with matched placebo controls and a temporal split, resolution convergence from `closed_time`.
- Parts of Phase 3 (on-chain ground truth) — Etherscan V2 enrichment of USDC.e, native USDC, and ERC-1155 transfers for the universe. **CTF/UMA subgraph not yet wired.**
- Phase 5 prototype — wallet entity resolution (USDC-only on-chain graph × cotrade graph + Louvain) with activity-preserving null models for cotrade and lead–lag.
- Stage 07 — CSV export with data dictionary, pandas-only verifier, snapshot comparison tool (`REPRODUCING.md`).
- Stage II data layer (spec §10, 2026-08-29): the public **Polymarket-v1 archive** (arXiv:2606.04217, CC-BY-4.0) is on disk under `data/external/polymarket_v1/` (daily `daily_aligned` + `daily_aligned_multi` for 2022-11-21 → 2026-04-28, plus the `CTF` lifecycle files; ~30 GB). `archive.py` serves it under the Stage I view names when `INTELLIFI_SOURCE=archive` (optional `INTELLIFI_ARCHIVE_CIDS` file, `INTELLIFI_ARCHIVE_START/END`). **Validated exactly** against our Dune/Etherscan reconstruction: 171,126 = 171,126 maker fills over five markets' full lifetimes, identical multiplicity, none one-sided. Archive rows are maker fills (taker attached; mint/merge legs re-expressed from the taker's side); the taker-order aggregate is not a row. **Archive `resolved_at` is NULL for ~4 % of resolved rows — including markets that resolved *before* their `close_at`** (e.g. the corpus's top market, resolved 2026-04-09 with `close_at` 2026-04-30): using `close_at` as the close would reproduce the `end_date` bug fixed in the audit. `archive.materialise_markets` therefore takes `closed_time` from our on-chain/Gamma value when the market is in `markets.parquet`; for other cohorts derive it from the CTF `ConditionResolution` block (`CTF/resolutions.parquet` id = `137_<block>_<logIndex>`, block → time via Etherscan proxy). Gotcha: never iterate days by adding 86,400 s in local time — 2026-03-29 (DST) was silently skipped by a shell loop; use `datetime.date` arithmetic. `scripts/10_fetch_v2_tape.py` crawls the v2 exchanges (`fills.EXCHANGES_V2`, new `OrderFilled`/`OrdersMatched`/`FeeCharged` layouts) into `data/parquet/tape_v2/`.

**2026-08-29 audit.** Three code audits and a methodology review (see `PROJECT_OVERVIEW.md §5` for the before/after table). Substantive corrections: convergence measured from `closed_time` not `end_date`; ERC-1155 transfers removed from the entity graph (they are CLOB fill settlements); in-universe hubs count toward popularity; backtest no longer leaks the payout at short horizons, excludes post-convergence leader trades, and compares against matched controls instead of an in-sample "random" set; leader-lag uses distinct-second adjacency instead of a scan-order-dependent LEAD(); wash round-trips matched one-to-one; skill measured per (wallet, market) position in an informative price band; PnL scales uncovered sells; family-level concentration deduplicated. **The corrected results are null**: no coordination, copy-trading or exploitable edge is detectable in the taker-side tail sample, and prices are converged by `closed_time`.

**Stage II, Sample A (2026-08-29):** the Stage I chain re-run on the complete v1 tape for the same 100 markets (`data/snapshots/20260829_stage2_v1/`, produced from `data_stage2_v1/` with `INTELLIFI_SOURCE=archive`) confirms every null and the convergence result (see `PROJECT_OVERVIEW.md §3`, "Replication on the complete tape"). Universe overlap with the feed-based universe is 20/134. Position skill on 14,949 wallets: 0 BH discoveries.

**Sample B tape definition (2026-08-31):** `data/parquet/tape_v2/` contains only the two v2 exchanges (`v2_a`/`v2_b`); same-signature events from other emitters (third contract `0xe3333700…`) live in `data/parquet/tape_v2_other/` (split + address-filtered backfill). The cohort gate compares like-for-like within the two exchanges — see pre-registration §7 deviation 1 (first gate run failed on this; no data loss). The v2 condition registry is `data/parquet/ctf_v2_conditions.parquet`.

**Stage II atlas (2026-08-30):** three archive analyses (fee rollout & liquidity provision; wash & negRisk bounds under fees; minting, convergence, maker concentration) are in `docs/atlas_2026-08-30/` with verdicts per question in its README; intermediates in `data/parquet/atlas/` (3.9 GB). Publishable: fee-rollout identification, fee incidence, negRisk band widening under fees (+3.4–4.2 pp), share-creation accounting (≈71 % of binary share volume is exchange minting), maker-concentration series. Run heavy archive jobs with `PRAGMA memory_limit='4GB'` and inside `systemd-run --user --scope -p MemoryMax=6G`: uncapped DuckDB scans OOM-killed the desktop twice on 2026-08-30.

**Not shipped yet:**

- Polygon CTF / UMA backfill at corpus scale. The Dune prototype (`scripts/08`, `fills.py`) is validated on 5 markets (12,532/12,532 feed rows reconcile exactly; 100 % share conservation; completeness 1.000) — see `data/parquet/fills/` and `fills_reconciliation/`. **Dune bills API results per row** (measured 2026-08-29: ~13 credits per 1,000 rows; 31 executions / ~290k rows consumed ~2,200 of the 2,500 monthly free credits), so full-row fill extraction for the corpus (0.4–13 M rows) is not affordable on Dune at any plan below Plus. Goldsky's Polymarket subgraphs are deprecated. Route for scale: Etherscan V2 `getLogs` on the two exchanges filtered by indexed `maker`/`taker` topics for the universe wallets (free key, complete per-wallet fill histories), plus Dune only for small server-side aggregates (per-token minute VWAP, per-market totals). Then UMA dispute labels and re-running the analysis stack on `fills`.
- Live WebSocket collector + SPRT alerts (Phase 4).
- Gap-10 stepwise replay engine (Phase 5 full).
- MEV side-channel on settlement path (Phase 6 / Gap 8).
- Insider-timing pre-event positioning ("Phase 4 Gap 1" in spec).

## How to run

Local-first; everything runs from a single workstation with no auth except optional free keys in a gitignored `.env` (see `.env.example`): `POLYGONSCAN_API_KEY` for on-chain transfers, `DUNE_API_KEY` for fill reconstruction.

Always use the project venv (`.venv/bin/python` or `source .venv/bin/activate`). The parquet files are written by pyarrow 24; the base anaconda python has an older pyarrow that fails with `Repetition level histogram size mismatch` when reading them.

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
python scripts/07_export_csv.py --zip      # CSV bundle for external researchers -> data/export/
python scripts/08_fetch_fills_dune.py --query-id <id> -v   # Phase 3 prototype: on-chain OrderFilled fills via Dune (needs DUNE_API_KEY in .env)

# notebooks
jupyter lab notebooks/
```

`REPRODUCING.md` is the reproducibility guide: analysis stages 03–07 are deterministic given the parquet store (seeded Louvain, sorted graph construction, explicit leader-lag tie-break); `examples/compare_outputs.py` checks a regenerated store against `data/snapshots/<date>/`, and `examples/verify_export.py` (shipped inside the CSV bundle) recomputes the core statistics from the raw CSVs with pandas only. Run both after any change to the analysis modules.

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
| `export.py` | Flattens the whole parquet store to CSV (+ README data dictionary, MANIFEST) for external researchers. |
| `fills.py` | Phase 3 prototype: Dune client, `OrderFilled` SQL for both exchanges, fill normaliser, and a four-invariant reconciliation against the Data API sample (taker match, per-tx conservation, coverage gain, completeness vs Gamma share volume). Exchange addresses verified empirically; `is_taker_order` derived at read time. |

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
└── export/                         # gitignored; produced by scripts/07_export_csv.py
    ├── csv/                        # one CSV per dataset + README.md + MANIFEST.csv
    └── polymarket_dataset_{core,onchain}.zip
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

- **Gamma `/markets` API caps (2026-08-31).** `order=volumeClob` now returns HTTP 500 (field retired — use `order=volume`); a page is capped at **100 rows** (`limit=500` still returns 100, so `GAMMA_PAGE_SIZE` must be 100 or pagination stops after one page); and there is a hard **offset ceiling ~2000** (offset ≥2100 → HTTP 422). The `archived` param is a **verified no-op** (all rows archived=false), and omitting `closed` **defaults to open-only** — so the complete set needs a **two-pass** union `closed=true` (resolved: the huge ephemeral/hourly set) ∪ `closed=false` (open, future endDates), deduped by conditionId. Use `scripts/01 --stream --closed any` (`gamma.stream_all_markets`): it runs both passes, recursively **bisects the endDate window** under the ceiling, streams each window to `_stream_parts/part_*.parquet` keeping only a conditionId seen-set in RAM (bounded for millions of markets), then DuckDB-consolidates — the plain in-memory path OOMs on the closed=true set. Category is NOT in `/markets`; it lives on the event (`/events` tags, keyed by `event_id`). **Gamma has no working per-token/condition lookup** (`clob_token_ids`/`condition_ids` filters are ignored → default page), so enumeration is the only Gamma path and it is lossy. **Canonical fix: the CLOB API** (`clob.polymarket.com/markets`) is cursor-paged (no offset ceiling → complete/lossless) and token/condition-native; `clob.iter_clob_markets()` + `scripts/14_fetch_clob_markets.py` enumerate it into `data/parquet/clob_markets/tokens.parquet` (one row per market token: condition_id, neg_risk, closed, question, slug) to join the tape by token_id. `GET /markets/{conditionId}` is an exact per-market lookup. The CLOB object lacks Gamma's volume and has no event_id, but carries a **`tags` array** (e.g. ["Ethereum","Finance","crypto",…]) — that is the v2 **category source** (classify off tags; no /events fetch). NegRisk CLOB markets return **empty token_id** (join them to the tape by condition_id via the CTF registry's derived token ids, `ctf_v2_conditions.parquet`); `scripts/14` emits a condition-level row for them so they are not dropped.
- **Gamma `volume` / `volumeClob` are share volumes, not USDC.** Verified 2026-08-29 against complete on-chain fill histories: `volumeClob == Σ taker-order shares` exactly (ratio 1.000 on 5 markets). Never divide USDC notional by it; use `fills.share_volume_vs_gamma` as the completeness check for on-chain reconstruction.
- **Universe wallets are ~96 % makers** (on-chain fills of the 40 universe wallets seen so far); the taker-only feed shows a median 20 % of their fills. Any wallet-level statistic from the feed is a statement about their taker minority.
- **`/trades` is a taker-side tail sample.** `data_api.TRADES_MAX_REACHABLE = 4000`; one row per fill, taker only (the maker is never recorded; `tx_hash` is unique). 92/100 markets hit the cap; ~90 % of sampled trades are at p ≤ 0.05 or ≥ 0.95. Every wallet-level statistic inherits this. Phase 3 (Polygon CTF subgraph, `OrderFilled`) closes it.
- **`end_date` is not the close of trading.** Use `markets.closed_time` (median +21 h vs `end_date`, range −5433 h … +682 h). Never measure "hours before close" from `end_date`.
- **ERC-1155 transfers between wallets are fills**, not relationships (`GraphConfig.include_erc1155=False`). Only USDC transfers are relationship evidence.
- **`/prices-history` `interval` is a lookback window**, not a resolution; the 2026-05-11 fetch covers the 30 days before the fetch at 600 s spacing (19 markets). Pass `start_ts`/`end_ts` with `fidelity` for full-lifetime series.
- **`/holders` returns ≤ 500 holders per outcome**; 92/100 markets truncated; most remaining weight is unredeemed losing positions.
- **On-chain history is page-capped** (`--max-pages-per-endpoint` in script 03); heavy wallets are truncated, and the USDC leg of many fills is missing from disk.
- **Universe selection is outcome-dependent** (PnL and skill ranks). It is kept for on-chain enrichment only; evaluation must use matched controls / temporal splits, never a "random universe sample".
- **Orphan partitions.** If `markets.parquet` is rebuilt with a different top-N and a previously-included `condition_id` falls out, its `trades/holders` partitions remain on disk. `select_universe` aggregates `trades` without joining `markets`. Workaround: `--top-n 0`, or remove orphans.
- **Stale cached layers on partial rerun.** Pass `--overwrite` to refresh trade tails, holder snapshots, or on-chain history.
- **Notebook narrative lags the audit.** The three notebooks still narrate the pre-audit (2026-05-11) figures; regenerate them from the current parquet outputs before citing anything from them.

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

For an **out-of-sample hold-out cohort** (same selection rule applied to markets resolved after the last snapshot), snapshot the derived outputs first, then fetch only the new window and union it with the corpus instead of overwriting it:

```bash
cp -r data/parquet/{markets/markets.parquet,neg_risk_families/families.parquet,universe.parquet,wallet_graph,coordination,backtest,convergence} data/snapshots/<YYYYMMDD>/
python scripts/01_fetch_resolved_markets.py --lookback-days <days since last cohort end> --top-n 100 --write --merge-existing -v
python scripts/02_fetch_trades_and_holders.py --workers 4 -v      # skip-if-exists: only the new cohort is fetched
python scripts/06_convergence.py -v                                # fetch prices-history early — it is pruned after resolution
```

Snapshot `data/snapshots/20260511/` holds the outputs of the original 100-market corpus (end_date 2025-12-07 → 2026-05-01).

**Geo-blocking.** All Polymarket hosts (Gamma, Data API, CLOB, website) return HTTP 451 / Cloudflare 1026 from blocked jurisdictions — observed 2026-08-26 from a South Korean network. From an Italian ISP (observed 2026-08-29, Turin) the block is different: every Polymarket hostname is DNS-hijacked to 217.175.53.72 (a block page with a mismatched certificate), even via 1.1.1.1 — an AGCOM-style domain block at the ISP; needs DNS-over-HTTPS or a VPS in another EU country. Collection must run from an unblocked network (or a small EU VPS with `INTELLIFI_DATA_DIR` and rsync). Polygon on-chain sources (Etherscan V2, subgraphs) are unaffected.

Then re-run the notebooks. The `behavioural_twin` leader set in script 05 selects the community by maximum overlap with on-chain entity #0, so it stays coherent across Louvain re-numbering.

## When asked to "implement X"

The library code in `src/intellifi/` is the unit of correctness; the scripts are thin orchestrators; the notebooks are narrative. Add new logic in `src/intellifi/<topic>.py` and expose it through a script if it requires fetching, or directly via the notebooks if it only transforms cached data. Avoid adding new top-level files unless absolutely necessary.

When extending the spec (e.g. wiring Phase 3 subgraph, Phase 4 WebSocket, Phase 5 replay, Gap 8 MEV, UMA-dispute labels), update `polymarket_anomaly_detection_spec_v2.md` together with the code so the spec remains source-of-truth.

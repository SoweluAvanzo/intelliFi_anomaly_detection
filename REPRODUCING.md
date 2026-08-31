# Reproducing the results

This document is for collaborators who have the repository and want to
regenerate every table and figure exactly. Read it before running anything.

## What can and cannot be reproduced

The pipeline has two kinds of stages.

**Collection stages (scripts 01, 02, the on-chain fetch inside 03, and the
price-history fetch inside 06)** query live public endpoints whose answers
change over time: the Data API returns only the ~4000 most recent trades per
market, `/holders` is a snapshot at fetch time, and `/prices-history` is
pruned after a market resolves. Re-running them today therefore cannot
recreate the corpus fetched on 2026-05-11 — by construction, not by accident.
(Polymarket also geo-blocks some jurisdictions with HTTP 451.) The raw API
responses are preserved verbatim under `data/raw/`, so the collection step is
*auditable*, but reproduction starts from the shipped parquet store.

**Analysis stages (03 without fetch, 04, 05, 06 without fetch, 07)** are
deterministic functions of the parquet store: every random element is seeded
(`random_state=42` for both Louvain partitions, `random.seed(42)` for the
random-control leader set), graph construction iterates wallets and edges in
sorted order, and the leader–lag window function has an explicit tie-break.
Two independent re-runs agree exactly on every value up to floating-point
summation order (relative differences ≈ 1e-15, from DuckDB's parallel
aggregation), which `examples/compare_outputs.py` treats as equal — verified
on 2026-08-29 for all 20 output tables.

## Steps

```bash
git clone <repo> && cd IntelliFi_anomaly_detection
python3.13 -m venv .venv && source .venv/bin/activate
pip install -r requirements-lock.txt      # exact versions used for the export
pip install -e .

# 1. Unpack the parquet store shipped with the export (inputs + reference outputs)
tar -xf polymarket_parquet_store.tar -C .   # creates data/parquet/ (inputs + outputs) and data/snapshots/

# 2. Regenerate every analysis output offline
python scripts/03_resolve_wallet_entities.py --no-fetch -v   # universe + on-chain entity graph + Louvain
python scripts/04_coordination_analysis.py -v                # cotrade / leader-lag / wash + behavioural Louvain
python scripts/05_backtest_mirror.py -v                      # four leader sets x four horizons
python scripts/06_convergence.py --no-fetch -v               # winner-price convergence

# 3. Check that what you produced matches the reference outputs
python examples/compare_outputs.py --ref data/snapshots/20260829   # expects ALL TABLES REPRODUCE

# 4. Rebuild the CSV bundle and check it against independent recomputation
python scripts/07_export_csv.py --zip
python data/export/csv/verify_export.py                      # expects ALL CHECKS PASSED
```

Always use the project venv: the parquet files are written by pyarrow 24 and
older pyarrow builds fail to read them.

## What the checks prove

- `compare_outputs.py` compares your regenerated `data/parquet` outputs against
  the reference snapshot table by table (row order ignored, Louvain communities
  matched by membership, numeric tolerance 1e-9 relative).
- `verify_export.py` recomputes winning outcomes, the bets table, raw and
  Bayesian calibration, per-market Gini/HHI and the cotrade pairs from the raw
  CSVs with pandas only, and compares them with the exported analysis tables —
  an implementation-independent check of the core formulas.

## Parameters that define the reported results

| Stage | Parameter | Value |
|---|---|---|
| 01 | corpus | top-100 resolved markets by `volumeClob`, scheduled `end_date` in a 180-day window ending 2026-05-11; `closed_time` re-normalised from the raw Gamma JSON |
| 03 | universe | union of top-50 by traded notional, top-50 by realised PnL, top-50 by raw calibration gap (≥ 20 resolved bets) — unchanged since May so the on-chain history on disk stays valid |
| 03 | entity graph | USDC direct-transfer edges (≥ $100) + common-counterparty edges (≥ 1 shared, non-hub); hubs = addresses touching ≥ 5 universe wallets, universe members included; ERC-1155 excluded; Louvain resolution 1.0, seed 42 |
| 04 | cotrade | same (asset, side) within a 300 s bucket, ≥ 3 events; activity-preserving null, BH q-values |
| 04 | leader–lag | consecutive distinct seconds on the same (asset, side), ≤ 600 s, ≥ 5 events; same null |
| 04 | position flips | BUY→SELL on one asset within 600 s, ≥ 50 % size overlap, one-to-one nearest matching |
| 05 | backtest | signal ≥ $1,000, price in [0.02, 0.98], before `event_ts`; latency 60 s, entry within 600 s; horizons 300 / 1800 / 3600 / 86400 s; 20 bps one-way fee; matched control ±900 s, ±0.05 price, 3 per event, non-universe wallets; temporal split at the median `closed_time` (2026-02-01); random set seed 42 |
| 06 | convergence | offsets from `closed_time`; last observation at or before each offset |
| skill | position skill | one trial per (wallet, market), implied p in [0.05, 0.95], ≥ 5 positions in ≥ 3 markets, prior strength 4, exact Beta quantiles, leave-one-out decile benchmark |
| skill | legacy | size-weighted trials, prior strength 4, ≥ 20 trades (kept for comparison only) |

Reference snapshots: `data/snapshots/20260829/` is the current reference
(post-audit); `data/snapshots/20260511/` preserves the pre-audit outputs so
the revision table in `PROJECT_OVERVIEW.md §5` can be checked.

## Phase 3 prototype: on-chain fill reconstruction (stage 08)

`scripts/08_fetch_fills_dune.py` reconstructs every fill of the corpus markets
from the `OrderFilled` events of both Polymarket exchanges via Dune, and
reconciles them against the Data API sample with three invariants (every
feed row matches one taker-order record exactly; maker legs conserve shares
per transaction; coverage gain per market and per universe wallet). Needs
`DUNE_API_KEY` in `.env` and a saved Dune query built from
`data/export/dune_fills_query.sql`. `--reconcile-only` re-runs the checks
offline. The normaliser and reconciliation are self-tested against synthetic
`OrderFilled` rows derived from the taker sample (100 % exact match required).

## Extending the dataset

Collection needs a network Polymarket does not block and, for on-chain
transfers, a free Etherscan V2 key in `POLYGONSCAN_API_KEY`. See CLAUDE.md
("When asked to extend the dataset") for the hold-out cohort procedure that
adds newly resolved markets without overwriting the reference corpus.

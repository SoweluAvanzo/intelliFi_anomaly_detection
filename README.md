# Polymarket market-integrity dataset

A near-complete, on-chain record of trading on **Polymarket** (a decentralized prediction market on
Polygon), assembled for a study of the introduction of its transaction fee — who bears it, who
captures the maker subsidy, and the structure of the trader population. This file orients a new
reader; `DATA_DICTIONARY.md` documents every table and column, and
`research_plan_technical_report.pdf` gives the research questions and findings.

The share is a ready-to-run repository: unpack `polymarket_code.tar.gz` at the root and the code finds
the data under `data/` with no configuration. See `REPLICATE.md` for the step-by-step download and
reproduction guide.

## What's in the share
```
polymarket-dataset/
├── REPLICATE.md                        ← download + reproduction guide (start here)
├── README.md                           ← this file
├── DATA_DICTIONARY.md                  ← every store, every column, with units and gotchas
├── research_plan_technical_report.pdf  ← context: RQs, methodology, results
├── polymarket_code.tar.gz              ← the full pipeline (src/, scripts/, notebooks/, specs)
├── results_json/                       ← headline result artifacts (fee incidence, maker economics, …)
├── csv_bundle/                         ← human-readable CSV subset (Stage I corpus) + verify_export.py
└── data/                               ← the analysis-ready data (read directly by the code)
    ├── parquet/
    │   ├── tape_v2/                     ← v2 on-chain tape: ~697M OrderFilled fills, Apr–Aug 2026 (47 GB)
    │   ├── ctf_v2_conditions.parquet   ← v2 winner/resolution registry
    │   ├── ctf_resolutions_corpus.parquet ← corpus-wide resolutions
    │   ├── clob_markets/               ← token → market join + category tags
    │   ├── gamma_v2/                    ← v2 market metadata
    │   ├── neg_risk_families/           ← negRisk family membership
    │   ├── onchain_transfers/           ← USDC + ERC-1155 transfers for the universe wallets
    │   ├── wallet_fills/                ← per-wallet v2 fill histories
    │   ├── entity/                      ← account-type classification (EOA / proxy / Gnosis Safe)
    │   └── markets/ trades/ holders/ prices_history/ universe.parquet   ← Stage I feed corpus
    └── external/
        └── polymarket_v1/              ← public Polymarket-v1 archive (24 GB)
```

## The v1 archive
`data/external/polymarket_v1/` holds the **Polymarket-v1 archive** (~746M maker fills,
Nov 2022 – Apr 2026, ~24 GB; subfolders `daily_aligned/`, `daily_aligned_multi/`, `CTF/`). It is also
a public CC-BY dataset — **Qin & Yang (2026), arXiv:2606.04217** — so it can be re-fetched from source
instead. The code loads it under the same view names as everything else via
`src/intellifi/archive.py::register_archive_views` (see `DATA_DICTIONARY.md §7`).

## How to read the data
Parquet is the working format — every tool reads it directly (no CSV needed). Use a **recent
pyarrow (≥ 14)**; older versions fail on these files with a "Repetition level histogram size
mismatch".

```python
import pandas as pd, duckdb, polars as pl

# pandas
df = pd.read_parquet("parquet/ctf_v2_conditions.parquet")

# DuckDB over a whole store (globs, no load) — best for the big tape
duckdb.sql("SELECT exchange, count(*) FROM 'parquet/tape_v2/**/*.parquet' GROUP BY 1").show()

# polars lazy
pl.scan_parquet("parquet/clob_markets/*.parquet").head().collect()
```

The `csv_bundle/` mirrors the smaller Stage I tables as CSV, with its own `README.md` (data
dictionary) and `verify_export.py` (recomputes the core statistics from the raw CSVs with pandas
only).

## Four things to know before you compute (full detail in `DATA_DICTIONARY.md`)
- **Dedup the v2 tape by `(tx_hash, evt_index)`** — the resumable crawl can write a fill into more
  than one chunk file. `QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1`.
- **`price` is a probability in [0, 1]** (USDC per share); `shares = usdc / price`; a winning share redeems for \$1.
- **The taker fee** sits on the `is_taker_order = TRUE` rows in the v2 tape (and on the maker-fill
  row in the v1 archive); PnL is read from the maker-fill rows. Maker and taker are the two sides of
  the same fill (zero-sum before fees).
- **`volume` fields are share volumes, not USDC**; use `closed_time` / `resolved_ts_utc` for the
  actual close of trading, never the scheduled `end_date` / `close_at`.

## Code
The pipeline that produced all of this is in the project repository (`src/intellifi/` for the
library, `scripts/` for the stages). Analyses are deterministic given the parquet store; heavy scans
need a `PRAGMA memory_limit` and wallet-/block-bucketing (uncapped DuckDB scans can exhaust memory).

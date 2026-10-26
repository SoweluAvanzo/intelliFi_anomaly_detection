# Polymarket market-integrity dataset

A near-complete, **on-chain record of trading on Polymarket** — the largest *decentralized prediction
market*: a venue on the Polygon blockchain where people trade **shares of yes/no outcomes of
real-world events**. One share pays \$1 if its outcome happens and \$0 otherwise, so its price (a number
between 0 and 1) reads as the market's probability for that event. Because trades settle on a public
blockchain, the complete trade record is observable; this dataset reconstructs it **with the true buyer
and seller of every trade** — something Polymarket's public API feed does not provide.

## What this project studied

The work has **two stages**:

- **Stage II — the make/take fee (current focus).** In 2026 Polymarket introduced a *make/take fee*: a
  fee charged to the **taker** (the trader who removes liquidity by accepting a resting order), part of
  which funds a **rebate** to the **maker** (the trader who posted that resting order). We measure the
  fee's distributional effect at the level of individual traders, around two research questions:
  - **RQ1 — incidence:** who bears the fee across order sizes and trader roles, and is it *regressive*
    (heavier, as a share of the money staked, on smaller trades)?
  - **RQ2 — the maker subsidy:** who captures the rebate the fee funds, by what mechanism, and what is
    their structural identity?
- **Stage I — market-integrity / anomaly detection (earlier).** An event-study pipeline that scores
  patterns *consistent with* manipulation (flow concentration, coordinated trading, late mispricing) on
  a smaller, feed-based corpus. Its results are null; it is documented in `PROJECT_OVERVIEW.md`.

Most readers want Stage II, which this README orients.

**Headline findings (full results + figures in `DERIVATIONS.md`).** *RQ1:* the fee is **regressive** — its effective rate runs from ~3% on the smallest trades to ~1% on the largest (it bites hardest on low-priced longshots) — and its introduction did not measurably reduce participation. *RQ2:* most liquidity providers lose (52.5% of 1.21M makers), the gains are hyper-concentrated (top 1% take 69%) in a **professional market-making class** (~84k accounts) that profits by **capturing the spread**, not by avoiding adverse selection, with **no self-dealing**.

## Start here — documentation map (read in this order)

1. **`README.md`** (this file) — what the project is, what data exist, the vocabulary.
2. **`DATA_DICTIONARY.md`** — every dataset: what each table/row is, every column, and the full fee
   model (§10). The reference for *what the data mean*.
3. **`DERIVATIONS.md`** — for every result: the inputs, the exact processing method, why it is computed
   that way, and the producing script. The reference for *how the results are obtained*.
4. **`REPLICATE.md`** — how to download the data and re-run a result.
5. **`REPRODUCING.md`** — what is and is not reproducible, and the determinism guarantees.
6. **`PROJECT_OVERVIEW.md`** — the earlier Stage-I market-integrity analysis (null results).

`REPLICATE.md` (download + Stage-II) and `REPRODUCING.md` (Stage-I, repo-based) are **alternative entry points for different goals, not sequential steps**. Other files under `docs/` — literature, the pre-registration, the result JSONs, the atlas — are **working material, not part of this reader set**.

## Where am I: the git repo vs. the data share

The same material is distributed two ways, with **different layouts**:

- **The git repository** (code + documentation): the pipeline is in `src/intellifi/` (library) and
  `scripts/` (stages); the documentation and the **result artifacts** are under `docs/` — the headline
  numbers are the JSON files `docs/*.json` — and a human-readable CSV subset is under `data/export/csv/`.
  The bulk data is *not* in git; fetch it from the share.
- **The data share** (the ~80 GB download described in `REPLICATE.md`): a ready-to-run bundle whose
  layout is shown below — `polymarket_code.tar.gz` (the pipeline), `results_json/` (the same
  `docs/*.json`, renamed on export), `csv_bundle/`, and `data/`.

### Layout of the data share
(paths in parentheses show where the same thing lives in the git repo)
```
polymarket-dataset/
├── REPLICATE.md                        ← download + reproduction guide
├── README.md                           ← this file
├── DATA_DICTIONARY.md                  ← every store, every column, with units and gotchas
├── DERIVATIONS.md                      ← per-result derivation rules and rationale
├── polymarket_code.tar.gz              ← the pipeline (src/, scripts/, notebooks/, specs)
├── results_json/                       ← headline result artifacts   (git repo: docs/*.json)
├── csv_bundle/                         ← human-readable CSV subset    (git repo: data/export/csv/)
└── data/                               ← the analysis-ready data (read directly by the code)
    ├── parquet/
    │   ├── tape_v2/                     ← v2 on-chain trade tape: ~697M fills, Apr–Aug 2026 (47 GB)
    │   ├── ctf_v2_conditions.parquet    ← v2 winner/resolution registry
    │   ├── ctf_resolutions_corpus.parquet ← corpus-wide resolutions
    │   ├── clob_markets/                ← token → market map + category tags
    │   ├── gamma_v2/                    ← v2 market metadata
    │   ├── neg_risk_families/           ← negRisk family membership
    │   ├── onchain_transfers/           ← USDC + ERC-1155 transfers for the universe wallets
    │   ├── wallet_fills/                ← per-wallet v2 fill histories
    │   ├── entity/                      ← account-type classification (EOA / proxy / Gnosis Safe)
    │   └── markets/ trades/ holders/ prices_history/ universe.parquet  ← Stage I feed corpus
    └── external/
        └── polymarket_v1/               ← public Polymarket-v1 archive (24 GB)
```

## The two trade records (the core data)

- **v1 archive** (`data/external/polymarket_v1/`) — the **fully-resolved past**: ~746M **fills** (a
  *fill* is one executed trade), Nov 2022–Apr 2026 (~24 GB). "Fully resolved" means every market's
  outcome is already known, so realized profit/loss can be computed. It is a public CC-BY dataset —
  *Qin & Yang (2026), "Polymarket-v1 Database," arXiv:2606.04217* — so it can be re-fetched from source.
  The code loads it via `src/intellifi/archive.py::register_archive_views` (see `DATA_DICTIONARY.md §7`).
- **v2 tape** (`data/parquet/tape_v2/`) — the **fee era**: ~697M fills, Apr–Aug 2026 (47 GB),
  reconstructed by us from the exchange's on-chain event logs.

Recurring vocabulary (full definitions in `DATA_DICTIONARY.md`): **CLOB** = central limit order book,
the order book that matches trades; **CTF** = Conditional Tokens Framework, the on-chain contracts that
mint and settle the outcome shares; **UMA** = the optimistic oracle that reports each market's
real-world outcome; **negRisk** = a *negative-risk* market group — a set of mutually-exclusive outcomes
whose prices are constrained to sum to 1, so flow is consolidated per group; **universe** = the set of
wallets *selected* (by trading size, profit, and skill rank) for on-chain enrichment, i.e. a subset, not
all wallets; **EOA** = externally-owned account (a normal wallet controlled by a private key, not a smart contract).

## How to read the data

Parquet is the working format — every tool reads it directly (no CSV needed). Use **pyarrow ≥ 15** (the
files are written with pyarrow 24; older builds fail with a "Repetition level histogram size mismatch").

```python
import pandas as pd, duckdb, polars as pl

# pandas
df = pd.read_parquet("parquet/ctf_v2_conditions.parquet")

# DuckDB over a whole store (globs, no load) — best for the big tape
duckdb.sql("SELECT exchange, count(*) FROM 'parquet/tape_v2/**/*.parquet' GROUP BY 1").show()

# polars lazy
pl.scan_parquet("parquet/clob_markets/*.parquet").head().collect()
```

The CSV subset (`csv_bundle/` in the share, `data/export/csv/` in the repo) mirrors the smaller Stage I
tables, with its own `README.md` (data dictionary) and `verify_export.py` (recomputes the core
statistics from the raw CSVs with pandas only).

## Four things to know before you compute (full detail in `DATA_DICTIONARY.md`)

- **Dedup the v2 tape by `(tx_hash, evt_index)`** — the resumable crawl can write a fill into more
  than one chunk file. `QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1`.
- **`price` is a probability in [0, 1]** (USDC per share); `shares = usdc / price`; a winning share redeems for \$1.
- **The taker fee** sits on the `is_taker_order = TRUE` rows in the v2 tape (and on the maker-fill
  row in the v1 archive); PnL is read from the maker-fill rows. Maker and taker are the two sides of
  the same fill (zero-sum before fees).
- **`volume` fields are share volumes, not USDC**; use `closed_time` / `resolved_ts_utc` for the
  actual close of trading, never the scheduled `end_date` / `close_at`.

## The pipeline

Two script families: **`scripts/01`–`07`** are the Stage-I feed pipeline; **`scripts/1x`–`4x`** are the
Stage-II fee pipeline (plus the archive "atlas" analyses). The library is `src/intellifi/`. Analyses are
deterministic given the parquet store; heavy scans need a `PRAGMA memory_limit` and wallet-/block-
bucketing (uncapped DuckDB scans can exhaust memory). `DERIVATIONS.md` maps each result to its producer.

# Replicating the results

This share is self-contained: **code + data + docs**. Every headline number in
`research_plan_technical_report.pdf` is produced by one script in `polymarket_code.tar.gz`, reading
the parquet stores in this same bucket. This file says how to set it up and which script produces
which result.

## What's in the share
```
polymarket-dataset/
├── REPLICATE.md                       ← this file
├── README.md                          ← dataset orientation
├── DATA_DICTIONARY.md                 ← every table + column, with units and gotchas
├── research_plan_technical_report.pdf ← the write-up (RQs, methodology, results)
├── polymarket_code.tar.gz             ← the full pipeline (src/, scripts/, notebooks/, specs)
├── results_json/                      ← the exact result artifacts the report cites
├── csv_bundle/                        ← human-readable CSV subset of the Stage I corpus
├── parquet/                           ← v2 on-chain tape + registries + Stage I stores (analysis data)
└── v1_archive/                        ← the public Polymarket-v1 archive (24 GB; arXiv:2606.04217)
```

## Quick start
```bash
# 1. download the whole share (read-only rclone remote you were given, here called r2)
rclone copy -P --transfers=16 r2:polymarket-dataset ./polymarket_dataset
cd polymarket_dataset

# 2. unpack the code
tar xzf polymarket_code.tar.gz -C code            # (mkdir code first: `mkdir -p code`)

# 3. Python 3.11+ venv and install (the parquet needs a recent pyarrow; the base
#    anaconda python has an old one that fails with "Repetition level histogram size mismatch")
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e code[notebook]

# 4. point the code at the data (the code expects  <DATA_DIR>/parquet  and
#    <DATA_DIR>/external/polymarket_v1 ; wire this bucket's folders to that shape once)
mkdir -p data/external
ln -s "$PWD/parquet"    data/parquet
ln -s "$PWD/v1_archive" data/external/polymarket_v1
export INTELLIFI_DATA_DIR="$PWD/data"

# 5. reproduce a result (see the map below). Heavy full-population scans need a memory cap
#    + on-disk spill; wrap them so an uncapped DuckDB scan can't OOM the machine:
systemd-run --user --scope -p MemoryMax=6G \
  python code/scripts/33_fee_behavioral.py --out fee_behavioral.json --memory-limit 3GB
# compare your fee_behavioral.json against results_json/fee_behavioral.json
```

## Which script produces which result
Each script writes one JSON (its `--out`); the report cites those JSONs, and copies are in
`results_json/` so you can diff your re-run against ours. Scripts are independently re-runnable.

| Report section (result) | Script | Output JSON |
|---|---|---|
| §5.1 Regressive fee, per-order incidence | `scripts/33_fee_behavioral.py` | `fee_behavioral.json` |
| §5.1–5.2 Staggered fee rollout (event-study DiD): incidence, order size, new-entrant inflow | `scripts/36_fee_rollout_did.py` | `fee_rollout_did.json` |
| §5.3 Maker adverse selection & who captures the subsidy | `scripts/32_maker_economics.py` | `maker_economics.json` |
| §5.4 On-chain account types (EOA / proxy / Gnosis Safe) | `scripts/37_account_types.py` | `account_types.json` |
| §5.4 Behavioral actor taxonomy (MM / HFT / retail) | `scripts/39_actor_taxonomy.py` | `actor_taxonomy.json` |
| §5.5 Platform-wide taker PnL, v1 (fee-free era) | `scripts/27_platform_wide.py` | `platform_wide.json` |
| §5.5 Platform-wide taker PnL, v2 (net of fee) | `scripts/28_v2_platform.py` | `v2_platform.json` |
| §5.5 Winnings concentration (Gini, top-1%) | `scripts/30_concentration.py` | `concentration.json` |
| §5.5 Skill: sign-randomization + persistence | `scripts/31_skill_signflip.py` | `skill_signflip.json` |
| §5.5 Skill: cross-market breadth | `scripts/38_skill_breadth.py` | `skill_breadth.json` |
| §5.5 Coordination null: funding-graph entity collapse | `scripts/34_entity_funding.py` | `entity_concentration.json` |
| §5.5 Coordination null: co-trading / winning graph | `scripts/35_winning_graph.py` | `winning_graph.json` |
| (supporting) Position-level skilled population | `scripts/23_skilled_population.py` | `skilled_population.json` |

Run `python code/scripts/<name>.py --help` for each script's options (`--out`, `--memory-limit`,
`--buckets`, window flags). Most v1 scripts build their views over the archive with
`intellifi.archive.register_archive_views`; the v2 tape is read through the `v2_raw` view, which
**deduplicates overlapping chunk files by `(tx_hash, evt_index)`** — do the same for any direct tape
query (`QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index)=1`).

## Notebooks
`code/notebooks/` (`strategy_and_efficiency.ipynb`, `vertical_slice.ipynb`, `wallet_graph.ipynb`) are
narrative and read the parquet outputs only. `jupyter lab code/notebooks/` after step 3. Note: the
notebooks narrate an earlier (pre-audit) run — regenerate their figures from the current parquet
before citing them; the report and `results_json/` are the current source of truth.

## Gotchas that will bite otherwise
- **Use the venv's Python**, not base anaconda (old pyarrow → "Repetition level histogram size mismatch").
- **Cap memory on full-population scans**: `PRAGMA memory_limit` + wallet-hash / block-range bucketing,
  inside `systemd-run --user --scope -p MemoryMax=…`. Uncapped DuckDB scans over the full tape OOM.
- **Dedup the v2 tape** by `(tx_hash, evt_index)` (the `v2_raw` view does it automatically).
- **The taker fee** lives on `is_taker_order = TRUE` rows in the v2 tape (and on the maker-fill row in
  v1); net-of-fee PnL uses the former. **`price` ∈ [0,1]** is a probability; `shares = usdc / price`.
- **Close of trading** is `closed_time` / `resolved_ts_utc`, never the scheduled `end_date` / `close_at`.
- Full column semantics for every store are in `DATA_DICTIONARY.md`.

## The v1 archive
`v1_archive/` is the public **Polymarket-v1 archive** (Qin & Yang, 2026, arXiv:2606.04217, CC-BY-4.0):
`daily_aligned/`, `daily_aligned_multi/`, `CTF/`. Bundled here for convenience; also re-fetchable from
the arXiv source. Step 4 wires it to where the code expects it
(`<DATA_DIR>/external/polymarket_v1/`).

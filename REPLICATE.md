# Replication guide

This dataset is self-contained: **code + data + documentation + result artifacts**. Every headline
number in `research_plan_technical_report.pdf` is produced by one script in
`polymarket_code.tar.gz`, reading the parquet stores under `data/`. After download, the folder is a
ready-to-run repository — no path configuration is needed.

This guide has two parts: **(1) downloading the dataset**, and **(2) running the analyses to
reproduce the results**.

---

## Contents of the share
```
polymarket-dataset/
├── REPLICATE.md                        ← this guide
├── README.md                           ← dataset orientation
├── DATA_DICTIONARY.md                  ← every table and column, with units and gotchas
├── research_plan_technical_report.pdf  ← the write-up: research questions, methodology, results
├── polymarket_code.tar.gz              ← the full pipeline (src/, scripts/, notebooks/, specs)
├── results_json/                       ← the exact result artifacts the report cites (reference copies)
├── csv_bundle/                         ← a human-readable CSV subset of the Stage I corpus
└── data/                               ← the analysis data (read directly by the code)
    ├── parquet/
    │   ├── tape_v2/                     ← v2 on-chain tape: ~697M OrderFilled fills, Apr–Aug 2026 (47 GB)
    │   ├── ctf_v2_conditions.parquet   ← v2 winner / resolution registry
    │   ├── ctf_resolutions_corpus.parquet
    │   ├── clob_markets/               ← token → market join + category tags
    │   ├── gamma_v2/                    ← v2 market metadata
    │   ├── neg_risk_families/           ← negRisk family membership
    │   ├── onchain_transfers/           ← USDC + ERC-1155 transfers for the universe wallets
    │   ├── wallet_fills/                ← per-wallet v2 fill histories
    │   ├── entity/                      ← account-type classification (EOA / proxy / Gnosis Safe)
    │   └── markets/ trades/ holders/ prices_history/ universe.parquet   ← Stage I feed corpus
    └── external/
        └── polymarket_v1/              ← public Polymarket-v1 archive, ~746M maker fills (24 GB)
```

---

## 1. Downloading the dataset

The dataset lives in a Cloudflare R2 bucket named `polymarket-dataset`. Access is via the S3-style
credentials provided separately: an **Access Key ID**, a **Secret Access Key**, and an **endpoint**
of the form `https://<ACCOUNT_ID>.r2.cloudflarestorage.com`.

### Install rclone (version 1.64 or newer)
```bash
# any of:
curl https://rclone.org/install.sh | sudo bash      # latest, recommended
# or a distro package if it is recent enough:  sudo apt install rclone
rclone version                                       # confirm >= 1.64
```

### Configure the remote
```bash
rclone config
#  n) New remote
#  name>              r2
#  Storage>           s3
#  provider>          Cloudflare
#  env_auth>          false
#  access_key_id>     <the provided Access Key ID>
#  secret_access_key> <the provided Secret Access Key>
#  region>            auto
#  endpoint>          https://<ACCOUNT_ID>.r2.cloudflarestorage.com
#  (accept defaults for the rest; Edit advanced config? n; Keep this remote? y; then q)
rclone lsf r2:polymarket-dataset          # should list the folders above
```

Alternatively, skip the interactive step and drive rclone directly from the API key with environment
variables (nothing is written to a config file — useful on a server or in a script):
```bash
export RCLONE_CONFIG_R2_TYPE=s3
export RCLONE_CONFIG_R2_PROVIDER=Cloudflare
export RCLONE_CONFIG_R2_ACCESS_KEY_ID=<the provided Access Key ID>
export RCLONE_CONFIG_R2_SECRET_ACCESS_KEY=<the provided Secret Access Key>
export RCLONE_CONFIG_R2_ENDPOINT=https://<ACCOUNT_ID>.r2.cloudflarestorage.com
export RCLONE_CONFIG_R2_REGION=auto
rclone lsf r2:polymarket-dataset          # same remote name "r2:", now backed by the env vars
```

### Download
```bash
# everything (~80 GB) — resumable; if it stops, re-run the same command to continue
rclone copy -P --transfers=16 r2:polymarket-dataset ./polymarket-dataset
```

To download only part of it, add filters:
```bash
# code + docs + result artifacts, without the bulk data (a few hundred MB):
rclone copy -P r2:polymarket-dataset ./polymarket-dataset --exclude "data/**"

# skip the 47 GB v2 tape (keep registries, on-chain, Stage I, and the v1 archive):
rclone copy -P --transfers=16 r2:polymarket-dataset ./polymarket-dataset --exclude "data/parquet/tape_v2/**"

# skip the 24 GB v1 archive:
rclone copy -P --transfers=16 r2:polymarket-dataset ./polymarket-dataset --exclude "data/external/**"
```

The v1 archive is also the public dataset **Qin & Yang (2026), arXiv:2606.04217** (CC-BY-4.0); it can
be re-fetched from that source instead of downloaded here.

---

## 2. Running the analyses to reproduce the results

### Set up the code
```bash
cd polymarket-dataset

# unpack the pipeline at the root (creates src/, scripts/, notebooks/, pyproject.toml, docs/, …)
tar xzf polymarket_code.tar.gz

# create a Python 3.11+ environment and install the package
python3.11 -m venv .venv && . .venv/bin/activate
pip install -e .[notebook]
```

Use this environment's Python for everything. A too-old pyarrow (for example the one in a base
Anaconda install) fails to read these parquet files with `Repetition level histogram size mismatch`.

No path configuration is required: the code anchors data at `<repo>/data`, which is exactly where the
download placed it. (To keep the data elsewhere, set `INTELLIFI_DATA_DIR=/absolute/path/to/data`.)

### Reproduce a single result
Each analysis script writes one JSON and is independently re-runnable. Full-population scans must be
run with a memory cap and on-disk spill — an uncapped DuckDB scan over the full tape can exhaust
memory — so wrap heavy jobs as shown:
```bash
mkdir -p replication_out
systemd-run --user --scope -p MemoryMax=6G \
  python scripts/33_fee_behavioral.py --out replication_out/fee_behavioral.json --memory-limit 3GB

# compare against the shipped reference
diff <(python -m json.tool replication_out/fee_behavioral.json) \
     <(python -m json.tool results_json/fee_behavioral.json)
```
On a machine without `systemd-run`, run the script directly but keep `--memory-limit` set (for
example `--memory-limit 3GB`) and prefer a machine with ≥ 16 GB of RAM for the tape-scale jobs.

### Which script reproduces which result
The report's numbers map one-to-one to these scripts and their output JSONs. Reference copies of
every JSON are in `results_json/`.

| Result in the report | Script | Output JSON |
|---|---|---|
| §5.1 Regressive fee, per-order incidence | `scripts/33_fee_behavioral.py` | `fee_behavioral.json` |
| §5.1–5.2 Staggered fee rollout (event-study DiD): incidence, order size, new-entrant inflow | `scripts/36_fee_rollout_did.py` | `fee_rollout_did.json` |
| §5.3 Maker adverse selection & who captures the subsidy | `scripts/32_maker_economics.py` | `maker_economics.json` |
| §5.4 On-chain account types (EOA / proxy / Gnosis Safe) | `scripts/37_account_types.py` | `account_types.json` |
| §5.4 Behavioral actor taxonomy (market-maker / HFT / retail) | `scripts/39_actor_taxonomy.py` | `actor_taxonomy.json` |
| §5.5 Platform-wide taker PnL, v1 (fee-free era) | `scripts/27_platform_wide.py` | `platform_wide.json` |
| §5.5 Platform-wide taker PnL, v2 (net of fee) | `scripts/28_v2_platform.py` | `v2_platform.json` |
| §5.5 Winnings concentration (Gini, top-1%) | `scripts/30_concentration.py` | `concentration.json` |
| §5.5 Skill: sign-randomization + persistence | `scripts/31_skill_signflip.py` | `skill_signflip.json` |
| §5.5 Skill: cross-market breadth | `scripts/38_skill_breadth.py` | `skill_breadth.json` |
| §5.5 Coordination null: funding-graph entity collapse | `scripts/34_entity_funding.py` | `entity_concentration.json` |
| §5.5 Coordination null: co-trading / winning graph | `scripts/35_winning_graph.py` | `winning_graph.json` |
| Supporting: position-level skilled population | `scripts/23_skilled_population.py` | `skilled_population.json` |

Run `python scripts/<name>.py --help` for each script's options (`--out`, `--memory-limit`,
`--buckets`, and window flags).

### Reproduce everything
```bash
mkdir -p replication_out
for s in 27_platform_wide 28_v2_platform 30_concentration 31_skill_signflip 32_maker_economics \
         33_fee_behavioral 34_entity_funding 35_winning_graph 36_fee_rollout_did 37_account_types \
         38_skill_breadth 39_actor_taxonomy; do
  echo "=== $s ==="
  systemd-run --user --scope -p MemoryMax=6G \
    python "scripts/${s}.py" --out "replication_out/${s#*_}.json" --memory-limit 3GB
done
```
The tape-scale jobs (27, 28, 30–39) each take on the order of tens of minutes on a workstation; the
full set is a multi-hour run.

### Notebooks
`notebooks/` (`strategy_and_efficiency.ipynb`, `vertical_slice.ipynb`, `wallet_graph.ipynb`) are
narrative and read the parquet outputs only: `jupyter lab notebooks/`. These narrate an earlier
(pre-audit) run — regenerate their figures from the current parquet before citing them. The report
and `results_json/` are the current source of truth.

---

## Conventions that matter (full detail in `DATA_DICTIONARY.md`)
- **Deduplicate the v2 tape** by `(tx_hash, evt_index)` — the resumable crawl can write a fill into
  more than one chunk file. The `v2_raw` view does this automatically; for a direct query use
  `QUALIFY row_number() OVER (PARTITION BY tx_hash, evt_index) = 1`.
- **The taker fee** lives on `is_taker_order = TRUE` rows in the v2 tape (and on the maker-fill row in
  the v1 archive); net-of-fee PnL uses the former.
- **`price` is a probability in [0, 1]** (USDC per share); `shares = usdc / price`; a winning share
  redeems for \$1.
- **Close of trading** is `closed_time` / `resolved_ts_utc`, never the scheduled `end_date` /
  `close_at`.
- **`volume` fields are share volumes, not USDC.**
- Most v1 analyses build their views over the archive with
  `intellifi.archive.register_archive_views`; the v2 tape is read through the `v2_raw` view.

# Maker markout — two interchangeable engines (DuckDB and PySpark)

The maker-markout result (RQ2, *mechanism*: do liquidity providers earn by **spread
capture** or lose to **adverse selection**?) can be computed two ways that produce the
**same numbers**:

| | Engine | Producer | Install | Use it for |
|---|---|---|---|---|
| **Default** | DuckDB / Polars over Parquet | `scripts/40_maker_markout.py` | nothing extra | replication, day-to-day analysis |
| **Optional** | Apache Spark (PySpark) | `scripts/44_maker_markout_spark.py` | `pip install -e '.[spark]'` (Java 17/21) | cross-engine validation, horizontal scale |

The DuckDB path is the **source of truth** and is unchanged. The PySpark path is
**purely additive**: it reads the same Parquet tape, writes the same JSON shape, and
removes nothing from the replication pipeline. `scripts/45_validate_markout_spark.py`
proves the two agree on identical input.

Pick an engine by the situation, not by preference: DuckDB is faster and simpler on a
single workstation (which is where this project runs); the PySpark implementation exists
so the heaviest stage can be validated independently and scaled out horizontally as the
on-chain tape keeps growing.

---

## What the statistic is

For each **maker** fill (a resting order a taker lifted), the realised
liquidity-provision return is the signed price move *after* the fill, read from the next
trade rather than from the market's resolution — so it is **outcome-independent** and
separates execution return from forecasting:

- forward price `p_fwd` = the first **taker** trade of the same token in
  `[t + D, t + D + max(2D, 900)]` seconds (`D` = horizon);
- `markout_ps = p_fwd − p_fill` for a BUY, `p_fill − p_fwd` for a SELL;
- **positive markout = spread capture**, **negative = adverse selection**.

Reported per horizon `D ∈ {60, 300, 900, 3600, 86400}` s: coverage, dollar-weighted and
mean markout, negative fraction, mean gap, total dollar markout, the Spearman rank
correlation between a maker's volume and its markout, and the first/last volume-decile
means.

---

## How to run

### Default (DuckDB, as today)

```bash
# full tape (heavy scan — cap memory as the pipeline normally does)
systemd-run --user --scope -p MemoryMax=6G \
    .venv/bin/python scripts/40_maker_markout.py --out docs/maker_markout.json
```

### Optional (PySpark, same result)

```bash
pip install -e '.[spark]'          # pulls PySpark 4.x; needs Java 17 or 21

# small, fast cross-engine check — a slice of the tape, local JVM, no cluster:
python scripts/44_maker_markout_spark.py --file-slice 0:40 --out /tmp/spark_markout.json

# full tape, still a single machine (all local cores, out-of-core with spill):
python scripts/44_maker_markout_spark.py \
    --out docs/maker_markout_spark.json --driver-memory 8g --shuffle-partitions 128
```

`--file-slice LO:HI` / `--limit-files N` pick the **same sorted tape files** as
`scripts/40`, so a slice is a like-for-like subset on both engines.

### Validate that they agree

```bash
# runs BOTH engines on the same slice and diffs every metric (counts exactly,
# floats to tolerance). Exit code 0 = PASS.
python scripts/45_validate_markout_spark.py --file-slice 0:40

# or compare a full Spark run to the shipped DuckDB result:
python scripts/45_validate_markout_spark.py \
    --against docs/maker_markout.json --spark-out docs/maker_markout_spark.json
```

---

## The one non-trivial piece: an as-of join in Spark

DuckDB has a native `ASOF LEFT JOIN … ON (m.t + D) <= p.t` that finds, for each maker
fill, the nearest taker price at or after `t + D`. Spark has **no** as-of join, so
`src/intellifi/spark_markout.py::asof_forward` implements one with a window:

1. union the maker fills (placed at their *search* time `t + D`) with the per-second
   taker VWAP price series;
2. order each token's events by `(time asc, is_maker desc)` — at equal time a maker sorts
   strictly before a price, so a price at exactly `t + D` (the `<=` boundary) is in the
   maker's forward view;
3. carry the first following price with
   `first(price, ignorenulls=True)` over a `currentRow → unboundedFollowing` frame.

This is the canonical windowed as-of pattern and is numerically exact against DuckDB's
ASOF (the validator confirms it). The window partitions by `token_id`; a few extremely
active tokens are skew points, so for a full-tape cluster run salt or range-partition the
token key — noted in the module's caveats.

---

## Design notes

- **Layering** mirrors the rest of the project: reusable transforms live in the library
  (`src/intellifi/spark_markout.py`), the script (`scripts/44`) is a thin orchestrator
  that builds the `SparkSession` and writes JSON — the same split as
  `convergence.py` ↔ `scripts/06`, or the logic in `scripts/40`.
- **Dependency isolation**: PySpark is an *optional* extra (`[spark]` in
  `pyproject.toml`), so the default DuckDB/Polars/pyarrow environment is untouched for
  anyone who does not opt in. `src/intellifi/__init__.py` does not import the Spark
  module, so importing the package never requires a JVM.
- **Determinism / dedup**: like the DuckDB views, the reader deduplicates the tape on
  `(tx_hash, evt_index)` (overlapping crawl chunks) before any aggregation.
- **Honest scope**: on ~78 GB on one machine DuckDB is the better tool and this document
  says so; the PySpark engine's value is cross-engine validation and a code base that
  scales out unchanged when the data outgrows the workstation.

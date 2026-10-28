# Running the pipeline with Apache Airflow (optional orchestration layer)

The pipeline can be driven two ways that do the **same work**:

| | How | Where it lives | Use it for |
|---|---|---|---|
| **Default** | run the numbered `scripts/NN_*.py` by hand, or via the `scripts/run_*.sh` drivers | nothing extra | replication, day-to-day analysis |
| **Optional** | trigger Airflow DAGs that orchestrate those same scripts | `airflow/` (isolated env) | dependency management, retries, run history, monitoring |

Airflow is **purely additive**: the DAGs call the existing scripts unchanged (via
`BashOperator`, in the project `.venv`), so `python scripts/01_…` and
`bash scripts/run_offline_analysis.sh` keep working exactly as before. Nothing in the
replication path depends on Airflow being installed.

## Why Airflow at all

The repo already orchestrates itself — with a dozen hand-rolled shell drivers
(`run_overnight.sh` … `run_overnight7.sh`, `run_offline_analysis.sh`,
`finalize_and_publish.sh`). Each re-implements, in bash, the things a workflow engine
gives for free: ordered dependencies, continue-on-error, per-step retries, a
`pgrep`-loop to wait on an upstream job, per-step logs, and a `systemd-run` memory
cgroup around every heavy step. The three DAGs here express that same orchestration
declaratively, with a dependency graph, per-task logs, run history (auditability), and
a retry policy that is **configured per task** — which matters because of the IP-penalty
rule below.

**Honest scope.** For a research corpus fetched a handful of times, the bash drivers
work and there is no scheduling need — the DAGs run `schedule=None` (on-demand). The
value is maintainability, observability and a safe, explicit retry/penalty policy, not a
capability the project lacked.

## Install (isolated — never into the analysis venv)

Airflow pins an old `pyarrow`; the analysis stack needs `pyarrow>=24` to read the
parquet store (CLAUDE.md). So Airflow gets its **own** venv and the DAGs shell out to
the project `.venv`:

```bash
bash airflow/setup.sh        # creates .venv-airflow (Python 3.12) + inits the metadata DB
source airflow/env.sh        # AIRFLOW_HOME=airflow/home (gitignored), DAGS_FOLDER=airflow/dags
airflow dags list            # -> polymarket_{collection,analysis,markout}
```

All Airflow state (SQLite metadata DB, logs) stays under `airflow/home/` and is
gitignored. The official Docker Compose is an equivalent, more portable runtime — the
DAGs are standard and run there unchanged (mount the repo, set `INTELLIFI_REPO`/`INTELLIFI_PY`).

## The DAGs

### `polymarket_markout` — fully local, the quickest thing to run
Maker-markout (RQ2) with the **engine switch** from `scripts/40` (DuckDB) ↔ `scripts/44`
(PySpark), over a configurable tape slice; an optional `validate` task runs `scripts/45`
to prove the engines agree. Network-free — the end-to-end smoke test of the whole layer.

```bash
airflow dags test polymarket_markout                                   # DuckDB, 16-file slice
airflow dags trigger polymarket_markout --conf '{"engine":"spark","file_slice":"0:40","validate":true}'
```

### `polymarket_analysis` — offline, network-free
The Airflow form of `run_offline_analysis.sh`: per cohort, coverage gate (`15`) →
descriptive pass (`17`, memory-capped, skip-if-exists); then the cross-cohort table and
inference (`19`). Reads only the local tape.

### `polymarket_collection` — the alternative way to collect the data
Orchestrates the collection scripts (`01` → `02`/`14`/`06`, then on-chain `03`) in the
documented order. Two safety properties are built in because this DAG hits live,
rate-limited, geo-sensitive endpoints:

- **`preflight` fails the run before any fetch** unless the Polymarket APIs resolve from
  this host *and* no IP-penalty cooldown is active. On a geo-blocked network the DAG
  stops here by design — run collection from a network where Polymarket resolves (set
  `INTELLIFI_DATA_DIR` there and rsync the parquet back, per CLAUDE.md).
- the on-chain crawl (`03`) sits behind **`IPPenaltySensor`** and uses **`retries=0`**:
  Airflow must never auto-retry a fetch into a warm IP, which would re-arm the per-IP
  Etherscan/Polygonscan penalty ("silence, not retries" — CLAUDE.md). The sensor waits
  out an active cooldown in `reschedule` mode instead of hammering it.

```bash
# ONLY from a network where Polymarket resolves and the IP is clean:
airflow dags test polymarket_collection
airflow dags trigger polymarket_collection --conf '{"lookback_days":365,"top_n":0}'
```

## Testing

```bash
bash airflow/test_dags.sh
```

Runs the checks that are **safe on the analysis box**: all DAGs parse; DAG-integrity and
fail-safe assertions (`airflow/tests/validate_dags.py` — including that the penalty
sensor holds on a warm marker and that preflight refuses to collect during a cooldown,
all with a *temp* marker, never the real `data/logs/.ip_penalty`); and a real
end-to-end run of `polymarket_markout` on a 16-file slice. The collection DAG's live
*fetch* is intentionally not exercised here — it is validated on the collection box,
where the preflight gate passes.

## Design notes

- **Isolation.** Airflow process ↔ work process are separated by venv: the Airflow env
  needs only `apache-airflow` (+ stdlib); the DAGs/sensor import no project code. This is
  why `_common.py` checks the penalty marker with the standard library rather than
  importing `intellifi.config`.
- **2.x / 3.x portable.** Operator imports fall back from `airflow.operators.*` to
  `airflow.providers.standard.operators.*`, and `Param` from `airflow.models.param` to
  `airflow.sdk`.
- **Idempotent / resumable.** Fetch tasks rely on the scripts' content-derived
  skip-if-exists; the analysis descriptive tasks add an explicit `skip_if` on their output
  — the same resume semantics as the shell drivers, now as task state.
- **Memory caps preserved.** Heavy tasks wrap the call in `systemd-run --scope
  MemoryMax=…` when available (falling back to a plain run), matching the shell drivers.

"""DAG ``polymarket_analysis`` — offline Sample-B analysis, orchestrated by Airflow.

The Airflow expression of ``scripts/run_offline_analysis.sh``: for each two-week v2
cohort, a local coverage gate (``15``) then the tape-only descriptive pass (``17``);
once all six cohorts are done, assemble the cross-cohort table
(``cohort_results_table.py``) and run the cross-cohort replication-stability inference
(``19``).

Pure-local / network-free — reads only ``data/parquet/tape_v2`` (deduped). Each heavy
descriptive pass is wrapped in a ``systemd-run`` memory cgroup (16G) when available,
exactly as the shell driver does, and is skipped if its output already exists
(idempotent resume). Cohort-1 writes a ``_repro`` file so the committed original is
never clobbered — the validation contract is that it reproduces
``cohort1_descriptive.json`` exactly.
"""
from __future__ import annotations

from airflow import DAG

from _common import (
    DEFAULT_ARGS,
    START,
    TAGS,
    BashOperator,
    EmptyOperator,
    run,
)

# cohort block windows — canonical: docs/stage2_cohorts.md (mirrors run_offline_analysis.sh)
COHORTS = {
    1: (88_080_000, 88_843_826),
    2: (88_844_000, 89_607_826),
    3: (89_608_000, 90_371_826),
    4: (90_372_000, 91_135_826),
    5: (91_136_000, 91_899_826),
    6: (91_900_000, 92_995_000),
}
REPORTS = "docs/cohort_reports"

with DAG(
    dag_id="polymarket_analysis",
    description="Offline Sample-B cohort analysis + cross-cohort inference (network-free)",
    default_args=DEFAULT_ARGS,
    start_date=START,
    schedule=None,
    catchup=False,
    tags=[*TAGS, "analysis", "offline"],
    doc_md=__doc__,
) as dag:
    start = EmptyOperator(task_id="start")
    descriptive_done = EmptyOperator(task_id="descriptive_done", trigger_rule="all_success")

    for n, (lo, hi) in COHORTS.items():
        # cohort 1 is the validation target: write _repro, never the committed original
        out = f"{REPORTS}/cohort1_descriptive_repro.json" if n == 1 else f"{REPORTS}/cohort{n}_descriptive.json"

        gate = BashOperator(
            task_id=f"coverage_gate_c{n}",
            bash_command=run("15_verify_tape_coverage.py", "--from-block", str(lo), "--to-block", str(hi)),
        )
        descriptive = BashOperator(
            task_id=f"descriptive_c{n}",
            bash_command=run(
                "17_cohort_descriptive.py",
                "--from-block", str(lo), "--to-block", str(hi),
                "--cohort", str(n), "--dedup", "--out", out, "--memory-limit", "12GB",
                mem="16G", skip_if=out,
            ),
        )
        start >> gate >> descriptive >> descriptive_done

    cohort_table = BashOperator(
        task_id="cross_cohort_table",
        bash_command=run("cohort_results_table.py"),
    )
    confirmatory = BashOperator(
        task_id="cross_cohort_inference",
        bash_command=run(
            "19_confirmatory_inference.py",
            "--dir", REPORTS, "--out", f"{REPORTS}/cross_cohort_inference.json",
        ),
    )

    descriptive_done >> cohort_table >> confirmatory

"""DAG ``polymarket_markout`` — maker-markout (RQ2), either engine, via Airflow.

A one-decision pipeline that showcases the DuckDB <-> PySpark engine switch built in
``scripts/40`` / ``scripts/44``: a branch picks the engine from the ``engine`` param
(``duckdb`` default, or ``spark``), runs it over a configurable ``file_slice`` of the
sorted tape, and an optional ``validate`` task runs ``scripts/45`` to prove the two
engines agree on the same input.

Fully local and network-free — the ideal end-to-end test of the Airflow layer on this
workstation. Trigger with a small slice for a fast check:

    airflow dags test polymarket_markout
    # or pick the engine / slice:
    airflow dags trigger polymarket_markout --conf '{"engine":"spark","file_slice":"0:40"}'

Writes to ``docs/maker_markout_airflow.json`` by default, so it never clobbers the
canonical ``docs/maker_markout.json`` produced by the replication run.
"""
from __future__ import annotations

from airflow import DAG

try:  # Airflow 3.x moved Param
    from airflow.sdk import Param
except ImportError:
    from airflow.models.param import Param

from _common import (
    DEFAULT_ARGS,
    START,
    TAGS,
    BashOperator,
    BranchPythonOperator,
    EmptyOperator,
    run,
)

PARAMS = {
    "engine": Param("duckdb", type="string", enum=["duckdb", "spark"],
                    description="markout engine: duckdb (scripts/40) or spark (scripts/44)"),
    "file_slice": Param("0:16", type="string",
                        description="'LO:HI' python slice of the sorted tape files (both engines agree)"),
    "out": Param("docs/maker_markout_airflow.json", type="string",
                 description="output JSON path (default keeps the canonical result untouched)"),
    "validate": Param(False, type="boolean",
                      description="also run scripts/45 to diff DuckDB vs Spark on the same slice"),
}


def _pick_engine(**ctx) -> str:
    return f"markout_{ctx['params']['engine']}"


def _maybe_validate(**ctx) -> str:
    return "validate" if ctx["params"]["validate"] else "skip_validate"


with DAG(
    dag_id="polymarket_markout",
    description="Maker markout (RQ2) on the v2 tape — DuckDB or PySpark engine",
    default_args=DEFAULT_ARGS,
    start_date=START,
    schedule=None,
    catchup=False,
    tags=[*TAGS, "rq2", "markout"],
    params=PARAMS,
    doc_md=__doc__,
) as dag:
    pick = BranchPythonOperator(task_id="pick_engine", python_callable=_pick_engine)

    markout_duckdb = BashOperator(
        task_id="markout_duckdb",
        bash_command=run(
            "40_maker_markout.py",
            "--file-slice", "{{ params.file_slice }}",
            "--out", "{{ params.out }}",
            "--buckets", "4",
        ),
    )
    markout_spark = BashOperator(
        task_id="markout_spark",
        bash_command=run(
            "44_maker_markout_spark.py",
            "--file-slice", "{{ params.file_slice }}",
            "--out", "{{ params.out }}",
            "--shuffle-partitions", "16",
        ),
    )

    # join the two branches, then decide whether to cross-validate
    decide_validate = BranchPythonOperator(
        task_id="decide_validate",
        python_callable=_maybe_validate,
        trigger_rule="none_failed_min_one_success",
    )
    validate = BashOperator(
        task_id="validate",
        bash_command=run("45_validate_markout_spark.py", "--file-slice", "{{ params.file_slice }}"),
    )
    skip_validate = EmptyOperator(task_id="skip_validate")
    done = EmptyOperator(task_id="done", trigger_rule="none_failed_min_one_success")

    pick >> [markout_duckdb, markout_spark] >> decide_validate >> [validate, skip_validate] >> done

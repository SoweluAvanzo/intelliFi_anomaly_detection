#!/usr/bin/env bash
# Live tests for the Airflow layer that are SAFE on the analysis workstation:
#   1. all DAGs parse (no import errors) and list;
#   2. DAG-integrity + fail-safe checks (airflow/tests/validate_dags.py);
#   3. a real end-to-end run of the markout DAG on a small tape slice (local, no network).
# The collection DAG's live FETCH is NOT run here (geo-block + IP safety) — run it from a
# network where Polymarket resolves:  airflow dags test polymarket_collection
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root
# shellcheck disable=SC1091
source airflow/env.sh

echo "== 1/3  airflow dags list =="
airflow dags list

echo "== 2/3  DAG-integrity + safety checks =="
python airflow/tests/validate_dags.py

echo "== 3/3  markout DAG end-to-end (DuckDB, 16-file slice) =="
airflow dags test polymarket_markout

echo "== OK =="

#!/usr/bin/env bash
# Build the ISOLATED Airflow environment for the IntelliFi DAGs.
#
# Airflow lives in its own venv (.venv-airflow) on Python 3.12 and NEVER in the
# project .venv — it pins an old pyarrow that cannot read the parquet store. The
# DAGs shell out to the project .venv for the actual work (see docs/AIRFLOW.md).
#
#   bash airflow/setup.sh            # create .venv-airflow + init metadata DB
#   source airflow/env.sh            # export AIRFLOW_HOME + DAGS_FOLDER
#   airflow dags list                # should list polymarket_{collection,analysis,markout}
#
set -euo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root

AIRFLOW_VERSION="${AIRFLOW_VERSION:-2.10.5}"
PY_BIN="${AIRFLOW_PYTHON:-python3.12}"
AF_VENV="${AF_VENV:-.venv-airflow}"

command -v "$PY_BIN" >/dev/null || { echo "need $PY_BIN on PATH (Airflow $AIRFLOW_VERSION supports 3.12)"; exit 1; }
PYV="$("$PY_BIN" -c 'import sys;print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"

echo "== creating $AF_VENV ($("$PY_BIN" --version)) =="
"$PY_BIN" -m venv "$AF_VENV"
"$AF_VENV/bin/pip" install --no-cache-dir --upgrade pip >/dev/null

echo "== installing apache-airflow==$AIRFLOW_VERSION (constraints for $PYV) =="
CONSTRAINTS="https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-${PYV}.txt"
"$AF_VENV/bin/pip" install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" --constraint "$CONSTRAINTS"

# shellcheck disable=SC1091
source airflow/env.sh
echo "== AIRFLOW_HOME=$AIRFLOW_HOME  DAGS_FOLDER=$AIRFLOW__CORE__DAGS_FOLDER =="
"$AF_VENV/bin/airflow" db migrate

cat <<EOF

Done. Next:
  source airflow/env.sh
  airflow dags list
  airflow dags test polymarket_markout      # fast, fully-local end-to-end run
  bash airflow/test_dags.sh                  # DAG-integrity + safety checks

Run collection (only from a network where Polymarket resolves):
  airflow dags test polymarket_collection
EOF

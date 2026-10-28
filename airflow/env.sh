# Source me: export the Airflow environment for the IntelliFi DAGs.
#   source airflow/env.sh
# Keeps all Airflow state (SQLite metadata DB, logs) under airflow/home (gitignored),
# points the scheduler at airflow/dags, and disables example DAGs + the DB-connection
# warning so `airflow dags list` is clean.
_REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export AIRFLOW_HOME="${AIRFLOW_HOME:-$_REPO/airflow/home}"
export AIRFLOW__CORE__DAGS_FOLDER="$_REPO/airflow/dags"
export AIRFLOW__CORE__LOAD_EXAMPLES="False"
export AIRFLOW__CORE__DAGS_ARE_PAUSED_AT_CREATION="True"
export INTELLIFI_REPO="$_REPO"
export INTELLIFI_PY="${INTELLIFI_PY:-$_REPO/.venv/bin/python}"
# Put the isolated venv first so `airflow` resolves to it.
export PATH="$_REPO/${AF_VENV:-.venv-airflow}/bin:$PATH"
mkdir -p "$AIRFLOW_HOME"

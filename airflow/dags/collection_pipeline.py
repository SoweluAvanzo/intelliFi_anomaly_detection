"""DAG ``polymarket_collection`` — collect the dataset, orchestrated by Airflow.

This is the Airflow-driven **alternative** to running the collection scripts by hand
(CLAUDE.md "How to run"). It orchestrates the same numbered scripts, in the same order,
with the same identifiers — Airflow adds dependency edges, per-task logs, run history
and a safe retry policy on top; it changes nothing in the scripts themselves.

    preflight ─┬─> fetch_markets (01) ─┬─> fetch_trades_holders (02) ─> ip_penalty_gate ─> resolve_entities_onchain (03)
               │                       └─> fetch_convergence_prices (06)   # both read markets.parquet
               └─> fetch_clob_markets (14)                                 # independent CLOB enumeration

Two safety properties are built in, because this DAG hits live, rate-limited and
geo-sensitive endpoints:

* **preflight** fails the whole run *before any fetch* unless the Polymarket APIs
  resolve from this host AND no IP-penalty cooldown is active. On a geo-blocked
  network (e.g. the analysis workstation) the DAG stops here by design — run it from
  a network where Polymarket resolves.
* the on-chain Etherscan crawl (``03``) sits behind ``IPPenaltySensor`` and uses
  ``retries=0``: Airflow must never auto-retry a fetch into a warm IP, which would
  re-arm the per-IP penalty ("silence, not retries" — CLAUDE.md).

Every fetch task is idempotent (the scripts skip-if-exists by content-derived path),
so a cleared/continued run only re-fetches what is missing. Tune the window via params.
"""
from __future__ import annotations

from airflow import DAG

try:
    from airflow.sdk import Param
except ImportError:
    from airflow.models.param import Param

from _common import (
    DEFAULT_ARGS,
    PENALTY_COOLDOWN_S,
    PENALTY_MARKER,
    START,
    TAGS,
    BashOperator,
    IPPenaltySensor,
    PythonOperator,
    collection_preflight,
    run,
)

PARAMS = {
    "lookback_days": Param(180, type="integer", description="market lookback window for scripts/01"),
    "top_n": Param(1000, type="integer", description="top-N markets by volume for scripts/01 (0 = all)"),
    "workers": Param(4, type="integer", description="parallel workers for scripts/02 trade/holder fetch"),
}

with DAG(
    dag_id="polymarket_collection",
    description="Collect the Polymarket dataset (Gamma/CLOB/Data API + on-chain), orchestrated",
    default_args=DEFAULT_ARGS,
    start_date=START,
    schedule=None,  # research corpus: triggered on demand, not on a cron
    catchup=False,
    tags=[*TAGS, "collection"],
    params=PARAMS,
    doc_md=__doc__,
) as dag:
    preflight = PythonOperator(
        task_id="preflight",
        python_callable=collection_preflight,
        retries=0,  # a geo-block / penalty is not transient within a run
    )

    fetch_markets = BashOperator(
        task_id="fetch_markets",
        bash_command=run(
            "01_fetch_resolved_markets.py",
            "--lookback-days", "{{ params.lookback_days }}",
            "--top-n", "{{ params.top_n }}",
            "--write",
        ),
    )
    fetch_trades_holders = BashOperator(
        task_id="fetch_trades_holders",
        bash_command=run("02_fetch_trades_and_holders.py", "--workers", "{{ params.workers }}"),
    )
    fetch_clob_markets = BashOperator(
        task_id="fetch_clob_markets",
        bash_command=run("14_fetch_clob_markets.py"),
    )
    fetch_convergence_prices = BashOperator(
        task_id="fetch_convergence_prices",
        bash_command=run("06_convergence.py"),
    )

    # on-chain enrichment hits Etherscan/Polygonscan -> penalty-sensitive.
    ip_penalty_gate = IPPenaltySensor(
        task_id="ip_penalty_gate",
        marker=str(PENALTY_MARKER),
        cooldown_s=PENALTY_COOLDOWN_S,
        mode="reschedule",   # free the worker slot while waiting out a cooldown
        poke_interval=300,
        timeout=PENALTY_COOLDOWN_S + 300,
    )
    resolve_entities_onchain = BashOperator(
        task_id="resolve_entities_onchain",
        bash_command=run("03_resolve_wallet_entities.py"),
        retries=0,  # never auto-retry a crawl into a warm IP
    )

    # 14 (CLOB enumeration) is independent; 01 (markets) feeds everything else.
    preflight >> [fetch_markets, fetch_clob_markets]
    # 02 (trades/holders) and 06 (prices-history) both read markets.parquet -> both need 01.
    fetch_markets >> fetch_trades_holders >> ip_penalty_gate >> resolve_entities_onchain
    fetch_markets >> fetch_convergence_prices

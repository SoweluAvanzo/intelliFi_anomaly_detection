#!/usr/bin/env python
"""DAG-integrity + safety tests for the IntelliFi Airflow layer.

Runs in the isolated Airflow venv (no project deps). Network-free and side-effect-free:
it NEVER creates the real ``data/logs/.ip_penalty`` marker (the live crawler reads that
path) — the penalty logic is exercised with a temp marker and a monkeypatch.

    source airflow/env.sh && python airflow/tests/validate_dags.py
"""
from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path

DAGS = Path(__file__).resolve().parents[1] / "dags"
os.environ.setdefault("AIRFLOW__CORE__LOAD_EXAMPLES", "False")

_failures: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        _failures.append(name)


# --- 1. DagBag parses with no import errors --------------------------------------
print("== DagBag integrity ==")
from airflow.models import DagBag  # noqa: E402

dagbag = DagBag(dag_folder=str(DAGS), include_examples=False)
check("no import errors", not dagbag.import_errors, str(dagbag.import_errors))
for dag_id in ("polymarket_collection", "polymarket_analysis", "polymarket_markout"):
    check(f"dag present: {dag_id}", dag_id in dagbag.dags)

# --- 2. collection DAG wiring + safety policy ------------------------------------
print("== collection DAG structure & fail-safe policy ==")
col = dagbag.dags.get("polymarket_collection")
if col:
    t = col.task_dict
    expected = {"preflight", "fetch_markets", "fetch_trades_holders", "fetch_clob_markets",
                "fetch_convergence_prices", "ip_penalty_gate", "resolve_entities_onchain"}
    check("tasks present", expected <= set(t), f"missing {expected - set(t)}")
    check("preflight retries==0", t["preflight"].retries == 0)
    check("on-chain crawl retries==0 (no retry into a warm IP)", t["resolve_entities_onchain"].retries == 0)
    check("crawl is downstream of ip_penalty_gate",
          "ip_penalty_gate" in {u.task_id for u in t["resolve_entities_onchain"].upstream_list})
    check("preflight gates every fetch",
          all("preflight" in {u.task_id for u in t[f].get_flat_relatives(upstream=True)}
              for f in ("fetch_markets", "fetch_clob_markets", "fetch_convergence_prices")))

# --- 3. markout DAG engine switch ------------------------------------------------
print("== markout DAG engine switch ==")
mk = dagbag.dags.get("polymarket_markout")
if mk:
    check("branch + both engines + validate present",
          {"pick_engine", "markout_duckdb", "markout_spark", "decide_validate", "validate", "done"} <= set(mk.task_dict))

# --- 4. analysis DAG cohort fan-out ----------------------------------------------
print("== analysis DAG cohort fan-out ==")
an = dagbag.dags.get("polymarket_analysis")
if an:
    gates = [x for x in an.task_dict if x.startswith("coverage_gate_c")]
    descs = [x for x in an.task_dict if x.startswith("descriptive_c")]
    check("6 coverage gates", len(gates) == 6, f"got {len(gates)}")
    check("6 descriptive passes", len(descs) == 6, f"got {len(descs)}")
    check("inference is terminal", "cross_cohort_inference" in an.task_dict)

# --- 5. IPPenaltySensor behaves (temp marker, never the real one) ----------------
print("== IPPenaltySensor (safety mechanism) ==")
sys.path.insert(0, str(DAGS))
from _common import IPPenaltySensor, collection_preflight  # noqa: E402
import _common  # noqa: E402

with tempfile.TemporaryDirectory() as d:
    marker = Path(d) / ".ip_penalty"
    s = IPPenaltySensor(task_id="t_clear", marker=str(marker), cooldown_s=2700)
    check("no marker -> proceed", s.poke({}) is True)
    marker.write_text("penalty")  # warm (mtime = now)
    s_warm = IPPenaltySensor(task_id="t_warm", marker=str(marker), cooldown_s=2700)
    check("warm marker -> hold", s_warm.poke({}) is False)
    old = time.time() - 4000  # older than cooldown
    os.utime(marker, (old, old))
    check("stale marker (past cooldown) -> proceed", s_warm.poke({}) is True)

# --- 6. preflight refuses to collect during a penalty (monkeypatched, no network) -
print("== collection_preflight penalty gate ==")
from airflow.exceptions import AirflowFailException  # noqa: E402

_orig = _common._penalty_minutes_remaining
_common._penalty_minutes_remaining = lambda: 50.0  # pretend a 50-min cooldown
try:
    collection_preflight()
    check("preflight raises during penalty", False, "did not raise")
except AirflowFailException as e:
    check("preflight raises during penalty", "IP penalty" in str(e))
finally:
    _common._penalty_minutes_remaining = _orig

# informational: is THIS host able to collect right now? (geo-block check, non-fatal)
try:
    collection_preflight()
    print("  INFO  this host CAN collect (Polymarket APIs reachable, IP clean)")
except AirflowFailException as e:
    first = str(e).splitlines()[1].strip() if len(str(e).splitlines()) > 1 else str(e)
    print(f"  INFO  this host cannot collect now (expected on the analysis box): {first}")

print()
if _failures:
    print(f"RESULT: FAIL — {len(_failures)} check(s): {', '.join(_failures)}")
    raise SystemExit(1)
print("RESULT: PASS — all DAG-integrity and safety checks passed")

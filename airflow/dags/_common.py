"""Shared helpers for the IntelliFi Airflow DAGs.

The DAGs are a thin *orchestration* layer over the existing pipeline scripts: every
task shells out to a numbered ``scripts/NN_*.py`` run in the **project** virtualenv
(``.venv``), never in the Airflow environment. This keeps Airflow's dependency tree
(which pins an old ``pyarrow``) completely isolated from the analysis stack (which
needs ``pyarrow>=24`` to read the parquet store) — see ``docs/AIRFLOW.md``.

Nothing here imports ``intellifi``; the Airflow process only needs the standard
library plus Airflow itself, so a plain ``apache-airflow`` install can parse and run
these DAGs with no project dependencies.

Operator imports are written to work on both Airflow 2.x (``airflow.operators.*``)
and Airflow 3.x (``airflow.providers.standard.operators.*``).
"""
from __future__ import annotations

import os
import time
import urllib.request
from datetime import timedelta
from pathlib import Path

import pendulum
from airflow.exceptions import AirflowFailException
from airflow.sensors.base import BaseSensorOperator

# --- operator imports, 2.x / 3.x compatible -------------------------------------
try:  # Airflow 2.x
    from airflow.operators.bash import BashOperator
except ImportError:  # Airflow 3.x
    from airflow.providers.standard.operators.bash import BashOperator
try:
    from airflow.operators.python import BranchPythonOperator, PythonOperator
except ImportError:
    from airflow.providers.standard.operators.python import BranchPythonOperator, PythonOperator
try:
    from airflow.operators.empty import EmptyOperator
except ImportError:
    from airflow.providers.standard.operators.empty import EmptyOperator

__all__ = [
    "REPO", "PY", "PENALTY_MARKER", "PENALTY_COOLDOWN_S", "START", "DEFAULT_ARGS",
    "TAGS", "run", "guarded_run", "IPPenaltySensor", "collection_preflight",
    "BashOperator", "PythonOperator", "BranchPythonOperator", "EmptyOperator",
]

# --- paths: resolved from this file, overridable by env -------------------------
# airflow/dags/_common.py -> parents[2] == repo root
REPO = Path(os.environ.get("INTELLIFI_REPO", str(Path(__file__).resolve().parents[2])))
PY = os.environ.get("INTELLIFI_PY", str(REPO / ".venv" / "bin" / "python"))
PENALTY_MARKER = REPO / "data" / "logs" / ".ip_penalty"
# Mirrors Polygonscan.penalty_active default (CLAUDE.md): a poisoned IP needs ~45 min silence.
PENALTY_COOLDOWN_S = int(os.environ.get("INTELLIFI_PENALTY_COOLDOWN_S", "2700"))

START = pendulum.datetime(2026, 1, 1, tz="UTC")
TAGS = ["intellifi", "polymarket"]
DEFAULT_ARGS = {
    "owner": "intellifi",
    "retries": 1,
    "retry_delay": timedelta(minutes=2),
    "depends_on_past": False,
}


def run(script: str, *args: str, mem: str | None = None, skip_if: str | None = None) -> str:
    """Build the bash command for a project-script task.

    Runs ``<PY> scripts/<script> <args...>`` from the repo root. ``mem`` wraps the
    call in a ``systemd-run`` memory cgroup when one is available (preserving the
    hard cap the heavy DuckDB scans in scripts/17, scripts/40 rely on — falls back
    to a plain run when systemd-run is absent). ``skip_if`` is a path that, when a
    non-empty file, makes the task a no-op (idempotent resume, like the shell drivers).
    """
    call = f'"{PY}" "scripts/{script}" ' + " ".join(args)
    if mem:
        call = (
            'if command -v systemd-run >/dev/null 2>&1; then '
            f'systemd-run --user --scope -p MemoryMax={mem} {call}; '
            f'else {call}; fi'
        )
    body = f'cd "{REPO}" && {call}'
    if skip_if:
        body = f'cd "{REPO}" && if [ -s "{skip_if}" ]; then echo "[skip] {skip_if} present"; else {call}; fi'
    return body


def guarded_run(*args, **kwargs) -> str:  # alias for readability at call sites
    return run(*args, **kwargs)


# --- IP-penalty fail-safe -------------------------------------------------------
def _penalty_minutes_remaining() -> float:
    """Minutes left on the shared cross-process IP-penalty marker, 0 if clear."""
    if not PENALTY_MARKER.exists():
        return 0.0
    age = time.time() - PENALTY_MARKER.stat().st_mtime
    return max(0.0, (PENALTY_COOLDOWN_S - age) / 60.0)


class IPPenaltySensor(BaseSensorOperator):
    """Hold a crawl task while the shared ``.ip_penalty`` marker is warm.

    CLAUDE.md is explicit that a poisoned Etherscan/Polygonscan IP "needs silence,
    not retries": relaunching onto a warm IP re-arms the per-IP penalty for ~45 min.
    So every on-chain crawl task sits behind this sensor (and sets ``retries=0``) —
    Airflow must never auto-retry a fetch into a penalty window. Uses only the marker
    file (stdlib), so it runs in the Airflow env without importing the project.
    """

    def __init__(self, *, marker: str | os.PathLike = PENALTY_MARKER,
                 cooldown_s: int = PENALTY_COOLDOWN_S, **kwargs) -> None:
        super().__init__(**kwargs)
        self.marker = Path(marker)
        self.cooldown_s = cooldown_s

    def poke(self, context) -> bool:  # noqa: ANN001
        if not self.marker.exists():
            return True
        remaining = self.cooldown_s - (time.time() - self.marker.stat().st_mtime)
        if remaining <= 0:
            return True
        self.log.warning(
            "IP penalty active: ~%.0f min remaining; holding crawl (silence, not retries).",
            remaining / 60.0,
        )
        return False


def _reachable(url: str, timeout: int = 8) -> bool:
    """True if the host resolves and answers (any non-5xx). Geo-block/DNS-block -> False."""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "intellifi-airflow-preflight"})
        with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 (fixed https hosts)
            return 200 <= getattr(r, "status", r.getcode()) < 500
    except Exception:  # noqa: BLE001 — any failure means "not safely reachable"
        return False


def collection_preflight(**_context) -> None:
    """Fail the collection DAG BEFORE any fetch unless it is safe to collect.

    Two gates: (1) no warm IP-penalty marker; (2) the Polymarket public APIs actually
    resolve from this host (they return nothing on a geo-blocked network — CLAUDE.md).
    Raising here stops the DAG at the first task, so no fetch runs on a blocked network
    or a poisoned IP.
    """
    problems: list[str] = []
    mins = _penalty_minutes_remaining()
    if mins > 0:
        problems.append(f"IP penalty active (~{mins:.0f} min remaining) — crawl unsafe; wait it out.")
    for name, url in (
        ("gamma", "https://gamma-api.polymarket.com/markets?limit=1"),
        ("clob", "https://clob.polymarket.com/markets?limit=1"),
    ):
        if not _reachable(url):
            problems.append(
                f"{name} API unreachable ({url}) — this network is likely geo-blocked; "
                "run collection from a network where Polymarket resolves (set INTELLIFI_DATA_DIR there and rsync back)."
            )
    if problems:
        raise AirflowFailException("collection preflight failed:\n  - " + "\n  - ".join(problems))
    print("preflight OK: IP clean and Polymarket APIs reachable — safe to collect.")

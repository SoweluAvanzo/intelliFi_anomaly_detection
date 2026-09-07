#!/bin/bash
# Autonomous overnight research pipeline — 2026-09-05.
# Sequential, memory-safe (each heavy step in its own 9G cgroup; DuckDB memory_limit 3GB;
# wallet-hash / block-range bucketing keeps every aggregation small). Continue-on-error so
# one failure does not stop the night. Waits for the already-running full skill job first.
set -u
cd /home/sowelo/Scrivania/IntelliFi_anomaly_detection || exit 1
PY=.venv/bin/python
LOGD=data/logs/overnight; mkdir -p "$LOGD"
prog() { echo "[$(date '+%F %T')] $*" | tee -a "$LOGD/_progress.log"; }
mem()  { free -g | awk '/Mem/{printf "mem used=%sG avail=%sG",$3,$7}'; }
runcap() {  # runcap <name> <cmd...>
  local name="$1"; shift
  prog "START $name ($(mem))"
  systemd-run --user --scope -p MemoryMax=9G "$@" > "$LOGD/$name.log" 2>&1
  prog "END   $name exit=$? ($(mem))"
  sleep 20   # let memory settle between steps
}

prog "=== overnight orchestrator started ($(mem)) ==="

# 0. wait for the running full skill job to finish (completion OR kill)
while pgrep -f "scripts/31_skill_signflip.py --out docs/skill_signflip.json" >/dev/null; do sleep 60; done
if [ -f docs/skill_signflip.json ]; then prog "skill run: COMPLETE (json present)"; else
  prog "skill run: no json (killed) -> retry with 16 buckets"
  runcap skill_retry $PY -u scripts/31_skill_signflip.py --out docs/skill_signflip.json \
    --buckets 16 --min-pos 10 --n-sim 2000 --n-sim-refine 200000 --memory-limit 3GB
fi

# 1. T2 — fee behavioral / welfare (v2 tape, partitioned)
runcap t2_fee $PY -u scripts/33_fee_behavioral.py --out docs/fee_behavioral.json --memory-limit 3GB

# 2. T1 — entity concentration on the top-20k winners (comprehensive tail; uses the internet)
runcap t1_winners $PY -u scripts/34_entity_funding.py --phase winners --top-k 20000 --memory-limit 3GB
runcap t1_fetch   $PY -u scripts/34_entity_funding.py --phase fetch   --top-k 20000 --max-pages 2
runcap t1_cl5  $PY -u scripts/34_entity_funding.py --phase cluster --top-k 20000 --hub-thresh 5  --out docs/entity_concentration.json
runcap t1_cl3  $PY -u scripts/34_entity_funding.py --phase cluster --top-k 20000 --hub-thresh 3  --out docs/entity_concentration_hub3.json
runcap t1_cl10 $PY -u scripts/34_entity_funding.py --phase cluster --top-k 20000 --hub-thresh 10 --out docs/entity_concentration_hub10.json

# 3. winning-cluster / syndicate graph (co-trading + shared funding among top winners)
runcap t_graph $PY -u scripts/35_winning_graph.py --graph-k 6000 --cotrade-min 3 --out docs/winning_graph.json

prog "=== overnight orchestrator DONE ($(mem)) ==="

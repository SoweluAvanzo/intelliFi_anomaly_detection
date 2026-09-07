#!/bin/bash
set -u
cd /home/sowelo/Scrivania/IntelliFi_anomaly_detection || exit 1
PY=.venv/bin/python; LOGD=data/logs/overnight; mkdir -p "$LOGD"
prog() { echo "[$(date '+%F %T')] [stage7] $*" | tee -a "$LOGD/_progress.log"; }
prog "stage7 waiter started; waiting for stage-6 (fee-rollout DiD) to finish"
sleep 120
while pgrep -f "scripts/run_overnight6.sh" >/dev/null || pgrep -f "scripts/36_fee_rollout" >/dev/null; do sleep 90; done
prog "stage6 done; re-running fixed scripts/39 actor taxonomy"
systemd-run --user --scope -p MemoryMax=9G $PY -u scripts/39_actor_taxonomy.py --out docs/actor_taxonomy.json --buckets 8 --memory-limit 3GB > "$LOGD/t_actor.log" 2>&1
prog "scripts/39 rerun exit=$?"
prog "=== stage7 DONE — ALL ANALYSES COMPLETE ==="

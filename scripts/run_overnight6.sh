#!/bin/bash
set -u
cd /home/sowelo/Scrivania/IntelliFi_anomaly_detection || exit 1
PY=.venv/bin/python; LOGD=data/logs/overnight; mkdir -p "$LOGD"
prog() { echo "[$(date '+%F %T')] [stage6] $*" | tee -a "$LOGD/_progress.log"; }
prog "stage6 waiter started; waiting for stage-5 (all others) to finish"
sleep 300
while pgrep -f "scripts/run_overnight5.sh" >/dev/null || pgrep -f "scripts/39_actor" >/dev/null || pgrep -f "scripts/38_skill" >/dev/null || pgrep -f "scripts/37_account" >/dev/null; do sleep 120; done
prog "all prior stages done; re-running fixed scripts/36 fee-rollout DiD (bucketed)"
systemd-run --user --scope -p MemoryMax=9G $PY -u scripts/36_fee_rollout_did.py --out docs/fee_rollout_did.json --memory-limit 3GB > "$LOGD/t1fee_rollout.log" 2>&1
prog "scripts/36 exit=$?"
prog "=== stage6 DONE — FULL PIPELINE COMPLETE ==="

#!/bin/bash
# Second-stage overnight waiter: after the main orchestrator finishes, run the lead-paper
# fee-rollout DiD (and any late additions), memory-safe and sequential. No concurrency.
set -u
cd /home/sowelo/Scrivania/IntelliFi_anomaly_detection || exit 1
PY=.venv/bin/python
LOGD=data/logs/overnight; mkdir -p "$LOGD"
prog() { echo "[$(date '+%F %T')] [stage2] $*" | tee -a "$LOGD/_progress.log"; }

prog "stage2 waiter started; waiting for main orchestrator to finish"
sleep 90
while pgrep -f "scripts/run_overnight.sh" >/dev/null; do sleep 120; done
prog "main orchestrator finished; running scripts/36 fee-rollout DiD"

systemd-run --user --scope -p MemoryMax=9G \
  $PY -u scripts/36_fee_rollout_did.py --out docs/fee_rollout_did.json --memory-limit 3GB \
  > "$LOGD/t1fee_rollout.log" 2>&1
prog "scripts/36 exit=$?"
prog "=== stage2 DONE ==="

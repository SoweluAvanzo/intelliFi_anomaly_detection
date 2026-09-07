#!/bin/bash
# Stage-4 waiter: after stage-3 (account types) finishes, run cross-market skill-breadth.
set -u
cd /home/sowelo/Scrivania/IntelliFi_anomaly_detection || exit 1
PY=.venv/bin/python
LOGD=data/logs/overnight; mkdir -p "$LOGD"
prog() { echo "[$(date '+%F %T')] [stage4] $*" | tee -a "$LOGD/_progress.log"; }
prog "stage4 waiter started; waiting for stage-3"
sleep 180
while pgrep -f "scripts/run_overnight3.sh" >/dev/null || pgrep -f "scripts/37_account_types.py" >/dev/null; do sleep 120; done
prog "stage3 done; running scripts/38 skill-breadth"
systemd-run --user --scope -p MemoryMax=9G $PY -u scripts/38_skill_breadth.py --out docs/skill_breadth.json --buckets 8 --memory-limit 3GB > "$LOGD/t_skill_breadth.log" 2>&1
prog "scripts/38 exit=$?"
prog "=== stage4 DONE ==="

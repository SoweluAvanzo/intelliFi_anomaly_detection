#!/bin/bash
set -u
cd /home/sowelo/Scrivania/IntelliFi_anomaly_detection || exit 1
PY=.venv/bin/python; LOGD=data/logs/overnight; mkdir -p "$LOGD"
prog() { echo "[$(date '+%F %T')] [stage5] $*" | tee -a "$LOGD/_progress.log"; }
prog "stage5 waiter started; waiting for stage-4"
sleep 240
while pgrep -f "scripts/run_overnight4.sh" >/dev/null || pgrep -f "scripts/38_skill_breadth.py" >/dev/null; do sleep 120; done
prog "stage4 done; running scripts/39 actor taxonomy"
systemd-run --user --scope -p MemoryMax=9G $PY -u scripts/39_actor_taxonomy.py --out docs/actor_taxonomy.json --buckets 8 --memory-limit 3GB > "$LOGD/t_actor.log" 2>&1
prog "scripts/39 exit=$?"
prog "=== stage5 DONE (all overnight analyses complete) ==="

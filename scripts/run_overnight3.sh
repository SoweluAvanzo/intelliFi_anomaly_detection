#!/bin/bash
# Stage-3 waiter: after stage-2 (fee-rollout DiD) finishes, run the account-type taxonomy
# investigation (NEW focus: are winners bots or standard proxies?). Memory-safe, sequential.
set -u
cd /home/sowelo/Scrivania/IntelliFi_anomaly_detection || exit 1
PY=.venv/bin/python
LOGD=data/logs/overnight; mkdir -p "$LOGD"
prog() { echo "[$(date '+%F %T')] [stage3] $*" | tee -a "$LOGD/_progress.log"; }
prog "stage3 waiter started; waiting for stage-2 to finish"
sleep 120
while pgrep -f "scripts/run_overnight2.sh" >/dev/null || pgrep -f "scripts/36_fee_rollout_did.py" >/dev/null; do sleep 120; done
prog "stage2 done; account-type cache (archive PnL-stratified sample + top winners, code fetch)"
systemd-run --user --scope -p MemoryMax=9G $PY -u scripts/37_account_types.py --phase cache --n-sample 30000 --memory-limit 3GB > "$LOGD/t_acct_cache.log" 2>&1
prog "account-type cache exit=$?; analyze"
systemd-run --user --scope -p MemoryMax=6G $PY -u scripts/37_account_types.py --phase analyze --out docs/account_types.json > "$LOGD/t_acct_analyze.log" 2>&1
prog "account-type analyze exit=$?"
prog "=== stage3 DONE ==="

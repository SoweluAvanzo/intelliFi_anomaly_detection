#!/usr/bin/env bash
# Run ON the remote box. Launches a crawler fleet over a FIXED block range,
# one contiguous sub-range per (key x per_key) slot, each detached and capped.
# Designed to crawl a range DISJOINT from the local machine's, so the two never
# collide (default: the v2 genesis gap 86,126,978 -> 88,079,999).
#
#   ./run_fleet.sh <from_block> <to_block> [per_key] [max_calls] [min_interval]
#
# Isolation: each crawler runs under `systemd-run --user --scope` with a memory
# cap and Nice=10 so it cannot starve co-hosted web services. If systemd-run is
# unavailable it falls back to `nice -n 15 setsid nohup`.
set -euo pipefail
cd "${INTELLIFI_REMOTE_DIR:-$HOME/intellifi_crawler}"
set -a; [ -f .env.dune ] && . ./.env.dune; set +a
FROM="${1:?from_block}"; TO="${2:?to_block}"; PER_KEY="${3:-4}"; MAXC="${4:-25000}"; MININT="${5:-1.4}"
KEYS=(); for k in ETHERSCAN_KEY ETHERSCAN_KEY2 ETHERSCAN_KEY3 ETHERSCAN_KEY4 ETHERSCAN_KEY5 ETHERSCAN_KEY6; do
  [ -n "${!k:-}" ] && KEYS+=("$k"); done
[ ${#KEYS[@]} -eq 0 ] && { echo "no ETHERSCAN_KEY* in .env.dune"; exit 2; }
SLOTS=$(( ${#KEYS[@]} * PER_KEY )); SPAN=$(( (TO - FROM + 1 + SLOTS - 1) / SLOTS ))
STAMP=$(date -u +%Y%m%dT%H%M)
i=0
for k in "${KEYS[@]}"; do
  for _ in $(seq 1 "$PER_KEY"); do
    A=$(( FROM + i*SPAN )); B=$(( A + SPAN - 1 )); [ "$B" -gt "$TO" ] && B=$TO
    [ "$A" -gt "$TO" ] && break
    KEYARG=(); [ "$k" != "ETHERSCAN_KEY" ] && KEYARG=(--api-key-env "$k")
    LOG="data/logs/fleet_${STAMP}_slot${i}_${k}.log"
    CMD=(./.venv/bin/python -u scripts/10_fetch_v2_tape.py --from-block "$A" --to-block "$B" \
         --chunk-blocks 2000 --max-calls "$MAXC" --min-interval "$MININT" "${KEYARG[@]}")
    if command -v systemd-run >/dev/null 2>&1; then
      systemd-run --user --scope -p MemoryMax=1500M -p CPUWeight=30 -q \
        setsid nohup nice -n 10 "${CMD[@]}" >"$LOG" 2>&1 &
    else
      nice -n 15 setsid nohup "${CMD[@]}" >"$LOG" 2>&1 &
    fi
    echo "slot $i $k blocks $A-$B -> $LOG"
    i=$(( i + 1 ))
  done
done
echo "launched $i crawlers over $FROM-$TO"

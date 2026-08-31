#!/usr/bin/env bash
# Supervisor: crawl the assigned block range with the keys in the environment,
# relaunching the gap-filler once per day (after the 00:00 UTC quota reset) until
# the range has zero missing chunks, then idle. Purely outbound; no open ports.
set -euo pipefail
FROM="${CRAWL_FROM_BLOCK:?set CRAWL_FROM_BLOCK}"
TO="${CRAWL_TO_BLOCK:?set CRAWL_TO_BLOCK}"
PER_KEY="${CRAWL_PER_KEY:-4}"
MAXC="${CRAWL_MAX_CALLS:-25000}"
MININT="${CRAWL_MIN_INTERVAL:-1.4}"
CHUNK="${CRAWL_CHUNK_BLOCKS:-2000}"
cd /app
# /data is a bind mount (empty on first run); ensure the log dir exists before the
# per-slot log redirects below, or the crawlers fail to launch.
mkdir -p /data/logs
gaps() { python scripts/10_relaunch_v2_gaps.py --dry-run --to-block "$TO" 2>/dev/null | awk '/missing_blocks/{print $3}'; }
nchunks() { ls "$INTELLIFI_DATA_DIR/parquet/tape_v2" 2>/dev/null | wc -l; }
while true; do
  echo "[$(date -u +%FT%TZ)] launching fleet over $FROM-$TO (per_key=$PER_KEY)"
  # one contiguous sub-range per (key x per_key) slot; each process caps at MAXC
  KEYS=(); for k in ETHERSCAN_KEY ETHERSCAN_KEY2 ETHERSCAN_KEY3 ETHERSCAN_KEY4 ETHERSCAN_KEY5 ETHERSCAN_KEY6; do
    [ -n "${!k:-}" ] && KEYS+=("$k"); done
  SLOTS=$(( ${#KEYS[@]} * PER_KEY )); SPAN=$(( (TO - FROM + 1 + SLOTS - 1) / SLOTS )); i=0; pids=()
  for k in "${KEYS[@]}"; do
    for _ in $(seq 1 "$PER_KEY"); do
      A=$(( FROM + i*SPAN )); B=$(( A + SPAN - 1 )); [ "$B" -gt "$TO" ] && B=$TO
      [ "$A" -gt "$TO" ] && break
      KEYARG=(); [ "$k" != "ETHERSCAN_KEY" ] && KEYARG=(--api-key-env "$k")
      python -u scripts/10_fetch_v2_tape.py --from-block "$A" --to-block "$B" \
        --chunk-blocks "$CHUNK" --max-calls "$MAXC" --min-interval "$MININT" "${KEYARG[@]}" \
        > "/data/logs/fleet_slot${i}_${k}.log" 2>&1 &
      pids+=($!); i=$(( i+1 ))
    done
  done
  BEFORE="$(nchunks)"
  echo "[$(date -u +%FT%TZ)] $i crawlers running (chunks=$BEFORE)"
  # 30-min supervisor heartbeat so `docker logs` shows liveness without digging slot logs
  ( while kill -0 "${pids[0]}" 2>/dev/null; do sleep 1800; \
      kill -0 "${pids[0]}" 2>/dev/null && echo "[$(date -u +%FT%TZ)] heartbeat: chunks=$(nchunks) (+$(( $(nchunks) - BEFORE )) this pass)"; done ) &
  HB=$!
  wait "${pids[@]}" || true
  kill "$HB" 2>/dev/null || true
  AFTER="$(nchunks)"; MISS="$(gaps || echo 1)"; GAINED=$(( AFTER - BEFORE ))
  echo "[$(date -u +%FT%TZ)] pass complete; +$GAINED chunks; missing_blocks=$MISS"
  [ "${MISS:-1}" = "0" ] && { echo "range complete -- idling"; sleep 86400; continue; }
  if [ "$GAINED" -ge 5 ]; then
    # still making progress => quota remains; relaunch on the next gaps immediately (continuity)
    echo "[$(date -u +%FT%TZ)] progress continues -- relaunching immediately"; sleep 5; continue
  fi
  # a pass gained ~nothing => per-key daily quota is spent; wait for the 00:00 UTC reset + jitter
  now=$(date -u +%s); reset=$(( (now/86400 + 1)*86400 + 300 ))
  echo "[$(date -u +%FT%TZ)] quota spent -- sleeping $(( (reset-now)/3600 ))h to reset"; sleep $(( reset - now ))
done

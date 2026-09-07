#!/usr/bin/env bash
# Cohort-runner (temporary, while the local fleet is paused) — WORK-QUEUE version.
#
# WHY: static round-robin assignment stranded the dense remaining sub-ranges on a
# couple of keys while the other keys sat idle (observed: stuck at 1-2 live workers
# for hours => only 1-2 of 7 keys working). This version puts every key's worker on
# a SHARED queue: each worker PULLS the next sub-range the instant it's free, so no
# key idles while work remains. Throughput on the dense tail is per-key-rate-limited
# by Etherscan (~45 chunks/hr/key), so keeping all 7 keys busy ~= 7x a 1-key tail.
#
# 1 worker per key by default (WPK=1): 1 concurrent request/key avoids Etherscan's
# per-key 429 backoff (measured: >2/key regresses). Zero re-crawl (skip-if-exists);
# boundaries irrelevant (peer dedups by (tx_hash, evt_index)). Outbound-only.
set -uo pipefail

GAPS_FILE="${CRAWL_GAPS_FILE:-/data/cohort_gaps.txt}"
CHUNK="${CRAWL_CHUNK_BLOCKS:-500}"
MAXC="${CRAWL_MAX_CALLS:-25000}"
MININT="${CRAWL_MIN_INTERVAL:-0.6}"
MAXSPAN="${CRAWL_MAX_SPAN:-10000}"
WPK="${CRAWL_WORKERS_PER_KEY:-1}"
DATA="${INTELLIFI_DATA_DIR:-/data}"
cd /app
mkdir -p "$DATA/logs" "$DATA/parquet/tape_v2"
[ -f "$GAPS_FILE" ] || { echo "[cohort] gaps file $GAPS_FILE missing -- idling"; sleep 86400; exec "$0"; }

KEYS=()
for k in ETHERSCAN_KEY ETHERSCAN_KEY2 ETHERSCAN_KEY3 ETHERSCAN_KEY4 ETHERSCAN_KEY5 ETHERSCAN_KEY6 ETHERSCAN_KEY7; do
  [ -n "${!k:-}" ] && KEYS+=("$k")
done
NKEYS=${#KEYS[@]}
W=$(( NKEYS * WPK ))

# Split each gap into <=MAXSPAN chunk-aligned sub-ranges (balanced work units).
mapfile -t RAW < <(grep -E '^[0-9]+[[:space:]]+[0-9]+' "$GAPS_FILE")
NGAPS=${#RAW[@]}
SUB=()
for r in "${RAW[@]}"; do
  read -r A B <<< "$r"; x=$A
  while [ "$x" -le "$B" ]; do
    y=$(( x + MAXSPAN - 1 )); [ "$y" -gt "$B" ] && y=$B
    SUB+=("$x $y"); x=$(( y + 1 ))
  done
done
nchunks(){ find "$DATA/parquet/tape_v2" -name 'part.parquet' 2>/dev/null | wc -l; }

QFILE=/tmp/cohort_queue.txt          # tmpfs; not pulled; fast
QLOCK=/tmp/cohort_queue.lock         # mkdir = portable atomic lock (no flock dependency)

echo "[$(date -u +%FT%TZ)] [cohort] ${#SUB[@]} sub-ranges (from $NGAPS gaps, <=$MAXSPAN blk) | $NKEYS keys x $WPK = $W workers (WORK-QUEUE, dynamic pull) | chunk=$CHUNK min_interval=$MININT"

# Atomically pop the first queued sub-range (empty string when the queue is drained).
pop(){
  local l=""
  while ! mkdir "$QLOCK" 2>/dev/null; do sleep 0.05; done
  l=$(head -n1 "$QFILE" 2>/dev/null || true)
  [ -n "$l" ] && sed -i '1d' "$QFILE" 2>/dev/null
  rmdir "$QLOCK" 2>/dev/null || true
  printf '%s' "$l"
}

worker(){
  local key="${KEYS[$(( $1 % NKEYS ))]}"
  local KEYARG=(); [ "$key" != "ETHERSCAN_KEY" ] && KEYARG=(--api-key-env "$key")
  local line A B
  while true; do
    line=$(pop); [ -z "$line" ] && break
    read -r A B <<< "$line"
    echo "[$(date -u +%FT%TZ)] [$key] ${A}-${B}"
    python -u scripts/10_fetch_v2_tape.py --from-block "$A" --to-block "$B" \
      --chunk-blocks "$CHUNK" --max-calls "$MAXC" --min-interval "$MININT" "${KEYARG[@]}" \
      >> "$DATA/logs/cohort_${key}.log" 2>&1 || echo 1 >> "$DATA/.pass_errors"
  done
}

zero=0
while true; do
  # IP-penalty circuit-breaker guard (2026-09-01): if a worker stamped a warm penalty
  # marker (/data/logs/.ip_penalty via onchain.py), SLEEP the remaining cooldown instead
  # of relaunching workers onto a penalized IP -- relaunching just grinds it warm and
  # resets the decay. penalty_active() returns seconds remaining; old code / no marker -> 0.
  REMAIN=$(python -c "from intellifi.onchain import Polygonscan; import math; print(int(math.ceil(Polygonscan.penalty_active())))" 2>/dev/null || echo 0)
  if [ "${REMAIN:-0}" -gt 0 ]; then
    echo "[$(date -u +%FT%TZ)] [cohort] IP penalty marker warm (${REMAIN}s left) -- sleeping, NOT relaunching"; sleep "$REMAIN"; continue
  fi
  rmdir "$QLOCK" 2>/dev/null || true
  printf '%s\n' "${SUB[@]}" > "$QFILE"          # (re)fill the queue; done pieces skip fast
  : > "$DATA/.pass_errors"                       # reset per-pass worker-error tally
  BEFORE="$(nchunks)"; PSTART=$(date +%s)
  echo "[$(date -u +%FT%TZ)] [cohort] pass start: $W workers draining ${#SUB[@]}-item queue (chunks=$BEFORE)"
  pids=()
  for (( i=0; i<W; i++ )); do worker "$i" & pids+=($!); done
  wait "${pids[@]}" || true
  AFTER="$(nchunks)"; GAINED=$(( AFTER - BEFORE )); PDUR=$(( $(date +%s) - PSTART ))
  echo "[$(date -u +%FT%TZ)] [cohort] pass done in ${PDUR}s; +$GAINED chunks (total $AFTER)"

  ERRS=$(wc -l < "$DATA/.pass_errors" 2>/dev/null || echo 0)
  if [ "$GAINED" -ge 5 ]; then zero=0; sleep 5; continue; fi
  # An errored pass (NOTOK / rate-limit / invalid-key / daily-quota) with low gain is NOT
  # completion -- it's a failure. Back off and retry; do NOT idle (the false-idle-at-32% bug).
  if [ "${ERRS:-0}" -gt 0 ]; then
    echo "[$(date -u +%FT%TZ)] [cohort] pass had $ERRS worker errors + low gain -- NOT complete; backing off 300s then retrying"; sleep 300; continue
  fi
  # Low gain AND zero errors AND fast (queue all skipped in <300s) => genuinely complete.
  if [ "$PDUR" -lt 300 ]; then
    echo "[$(date -u +%FT%TZ)] [cohort] all ${#SUB[@]} sub-ranges COMPLETE -- idling"; sleep 86400; zero=0; continue
  fi
  # Long pass, ~no gain => per-key daily quota spent; wait for the 00:00 UTC reset.
  now=$(date -u +%s); reset=$(( (now/86400+1)*86400+300 ))
  echo "[$(date -u +%FT%TZ)] [cohort] low gain over ${PDUR}s -- likely quota spent; sleeping $(( (reset-now)/3600 ))h to reset"; sleep $(( reset-now ))
done

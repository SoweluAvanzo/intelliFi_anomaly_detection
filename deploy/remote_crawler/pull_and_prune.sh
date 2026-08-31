#!/usr/bin/env bash
# LOCAL machine. Pull new chunks from the box, then delete from the box ONLY the
# chunk dirs confirmed present locally (safe: never deletes un-backed-up data).
# The box (~4.2 GB free) cannot hold the whole ~7 GB genesis gap, so pruning
# after a verified pull is required to keep the crawler writing.
set -uo pipefail
REMOTE="${1:?usage: pull_and_prune.sh user@host [remote_out_dir]}"
ROUT="${2:-polymarket-crawler/deploy/remote_crawler/out}"
LOCAL="${INTELLIFI_DATA_DIR:-$HOME/Scrivania/IntelliFi_anomaly_detection/data}"
DEST="$LOCAL/parquet/tape_v2"; RTV="$ROUT/parquet/tape_v2"
echo "[pull] $REMOTE:$RTV -> $DEST"
rsync -az --ignore-existing "$REMOTE:$RTV/" "$DEST/"
# prune: keep only what is NOT yet local; delete confirmed-local dirs on the box
# Prune is OFF by default: the box has ample disk (~70 GB) and its crawler uses
# skip-if-exists keyed on part.parquet — deleting a pulled chunk makes the next
# pass RE-CRAWL it, wasting quota. Keeping chunks on the box lets skip-if-exists
# short-circuit. Set PRUNE=1 only if box disk genuinely gets tight.
if [ "${PRUNE:-0}" = "1" ]; then
  ssh "$REMOTE" "ls '$RTV' 2>/dev/null" | while read -r d; do
    [ -z "$d" ] && continue
    if [ -s "$DEST/$d/part.parquet" ]; then echo "$d"; fi
  done > /tmp/_prune_confirmed.txt
  NP=$(wc -l < /tmp/_prune_confirmed.txt || echo 0)
  if [ "${NP:-0}" -gt 0 ]; then
    # truncate (not rm): leave a 0-byte marker so skip-if-exists still short-circuits
    ssh "$REMOTE" "cd '$RTV' && while read -r d; do : > \"\$d/part.parquet\" 2>/dev/null; done" < /tmp/_prune_confirmed.txt || echo "[prune] truncate failed"
  fi
  echo "[prune] truncated $NP confirmed-local chunks to 0-byte markers; local chunks: $(ls "$DEST" | wc -l)"
else
  echo "[pull-only] box chunks kept (skip-if-exists short-circuits; no re-crawl). local chunks: $(ls "$DEST" | wc -l)"
fi

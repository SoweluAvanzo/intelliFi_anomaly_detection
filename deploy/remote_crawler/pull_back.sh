#!/usr/bin/env bash
# Run ON THE LOCAL machine. Pulls the remote crawler's parquet output back and
# merges it into the local tape (skip-if-exists: chunk dirs are content-keyed, so
# a merge never overwrites and both machines' chunks coexist). Purely a pull over
# SSH (outbound from here to the box's sshd) — the box needs no inbound app port.
set -euo pipefail
REMOTE="${1:?usage: pull_back.sh user@host [remote_out_dir]}"
ROUT="${2:-polymarket-crawler/deploy/remote_crawler/out}"
LOCAL="${INTELLIFI_DATA_DIR:-$HOME/Scrivania/IntelliFi_anomaly_detection/data}"
DEST="$LOCAL/parquet/tape_v2"
echo "pulling $REMOTE:$ROUT/parquet/tape_v2/ -> $DEST"
rsync -az --info=progress2 --ignore-existing \
  "$REMOTE:$ROUT/parquet/tape_v2/" "$DEST/"
echo "done. chunk dirs now: $(ls "$DEST" | wc -l)"

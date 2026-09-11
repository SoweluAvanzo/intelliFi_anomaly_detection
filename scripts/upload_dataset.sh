#!/usr/bin/env bash
# Upload the own-collected Polymarket dataset (~49 GB, Parquet) to ANY rclone remote
# (Backblaze B2, Cloudflare R2, S3, SFTP/Storage Box, Proton Drive, ...).
# Backend-agnostic: fast multi-stream by default, auto-switching to Proton's slow
# single-stream mode only when the remote is a protondrive.
#
# Does NOT upload the 24 GB v1 archive (public: arXiv:2606.04217) or the atlas intermediates.
#
# USAGE:
#   RCLONE_REMOTE=b2 RCLONE_DEST=polymarket-dataset ./scripts/upload_dataset.sh all
#   ... arg: small | tape | all   (small = everything except the 47 GB tape)
#   Defaults: RCLONE_REMOTE=proton  RCLONE_DEST=polymarket_dataset
# Re-runnable: rclone skips files already uploaded, so just run it again if it stops.
#
# QUICK REMOTE SETUP:
#   Backblaze B2 : create a bucket + app key at backblaze.com, then
#                  rclone config -> n -> name b2 -> b2 -> account=keyID -> key=appKey
#   Cloudflare R2: create a bucket + S3 API token in the R2 dashboard, then
#                  rclone config -> n -> name r2 -> s3 -> provider Cloudflare
#                  -> access_key_id / secret_access_key -> endpoint https://<accountid>.r2.cloudflarestorage.com
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"; cd "$REPO"

MODE="${1:-all}"; do_small=1; do_tape=1; do_v1=0
case "$MODE" in
  small) do_tape=0 ;;
  tape)  do_small=0 ;;
  v1)    do_small=0; do_tape=0; do_v1=1 ;;   # just the 24 GB public v1 archive
  full)  do_v1=1 ;;                          # everything incl. v1
  all)   ;;                                  # small + tape (default)
  *) echo "usage: $0 [all|small|tape|v1|full]"; exit 2 ;;
esac

REMOTE="${RCLONE_REMOTE:-proton}"
DEST="${RCLONE_DEST:-polymarket_dataset}"
BWLIMIT="${BWLIMIT:-}"

command -v rclone >/dev/null || { echo "rclone not found"; exit 1; }
rclone listremotes | grep -qx "${REMOTE}:" || { echo "rclone remote '${REMOTE}:' not configured — run 'rclone config'"; exit 1; }

TYPE="$(rclone config show "$REMOTE" 2>/dev/null | awk -F' = ' '/^type/{print $2; exit}')"
if [ "$TYPE" = "protondrive" ]; then
  TRANSFERS="${TRANSFERS:-1}"     # Proton times out under concurrency and has no within-file resume
  RC=(rclone copy -P --transfers="$TRANSFERS" --checksum
      --protondrive-replace-existing-draft=true --retries 20 --low-level-retries 20 --timeout 120s)
else
  TRANSFERS="${TRANSFERS:-8}"     # B2/R2/S3: fast, resumable, robust
  RC=(rclone copy -P --transfers="$TRANSFERS" --retries 10 --low-level-retries 20)
fi
[ -n "$BWLIMIT" ] && RC+=(--bwlimit "$BWLIMIT")

echo "== mode=$MODE  remote=$REMOTE ($TYPE)  dest=$DEST  transfers=$TRANSFERS =="
rclone mkdir "${REMOTE}:${DEST}" || true

if [ "$do_small" = 1 ]; then
  "${RC[@]}" README.md                               "${REMOTE}:${DEST}/"
  "${RC[@]}" docs/DATA_DICTIONARY.md                 "${REMOTE}:${DEST}/"
  "${RC[@]}" docs/research_plan_technical_report.pdf "${REMOTE}:${DEST}/"
  "${RC[@]}" --include '*.json' docs                 "${REMOTE}:${DEST}/results_json/"
  "${RC[@]}" data/export/csv                          "${REMOTE}:${DEST}/csv_bundle/"
  "${RC[@]}" data/parquet/ctf_v2_conditions.parquet   "${REMOTE}:${DEST}/parquet/"
  "${RC[@]}" data/parquet/ctf_resolutions_corpus.parquet "${REMOTE}:${DEST}/parquet/"
  "${RC[@]}" data/parquet/universe.parquet            "${REMOTE}:${DEST}/parquet/"
  for store in clob_markets gamma_v2 neg_risk_families onchain_transfers wallet_fills entity markets trades holders prices_history; do
    "${RC[@]}" "data/parquet/$store"                  "${REMOTE}:${DEST}/parquet/$store/"
  done
fi

if [ "$do_tape" = 1 ]; then
  echo "== v2 tape (47 GB, resumable) =="
  "${RC[@]}" data/parquet/tape_v2                      "${REMOTE}:${DEST}/parquet/tape_v2/"
fi

if [ "$do_v1" = 1 ]; then
  echo "== v1 public archive (24 GB, arXiv:2606.04217) =="
  "${RC[@]}" data/external/polymarket_v1              "${REMOTE}:${DEST}/v1_archive/"
fi

echo "== done ($MODE). Remote size: =="
rclone size "${REMOTE}:${DEST}"

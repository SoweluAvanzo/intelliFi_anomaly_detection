#!/usr/bin/env bash
# Upload the own-collected Polymarket dataset (~49 GB, Parquet) to Proton Drive via rclone,
# building a clean, self-describing folder the collaborator can pull with no Proton account.
#
# Does NOT upload the 24 GB v1 archive (public: arXiv:2606.04217) or the atlas intermediates.
#
# USAGE:
#   ./scripts/upload_to_proton.sh small    # docs + JSONs + CSV bundle + registries + small parquet (NO tape)
#   ./scripts/upload_to_proton.sh tape     # ONLY the 47 GB v2 tape (Proton may time out on this — see README note)
#   ./scripts/upload_to_proton.sh all      # everything (default)
# Re-runnable: rclone skips files already uploaded, so just run it again if it stops.
#
# ------------------------------------------------------------------------------------------
# ONE-TIME SETUP (rclone >= v1.64 has a native Proton Drive backend):
#   rclone config
#     n) New remote  ->  name: proton  ->  Storage: protondrive
#     enter your Proton e-mail + password (+ 2FA code if you use one)
#   Verify:  rclone lsd proton:
#
# AFTER UPLOAD (rclone cannot create Proton share links):
#   open Proton Drive in the browser -> right-click the "polymarket_dataset" folder ->
#   Share / Get link -> set a password + expiry -> send that link to the collaborator.
# ------------------------------------------------------------------------------------------
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"

MODE="${1:-all}"                           # all | small | tape
do_small=1; do_tape=1
case "$MODE" in
  small) do_tape=0 ;;
  tape)  do_small=0 ;;
  all)   ;;
  *) echo "usage: $0 [all|small|tape]"; exit 2 ;;
esac

REMOTE="${PROTON_REMOTE:-proton}"          # rclone remote name (from rclone config)
DEST="${PROTON_DEST:-polymarket_dataset}"  # target folder on Proton Drive
TRANSFERS="${TRANSFERS:-1}"                 # Proton's backend times out under concurrency; 1 is most reliable
# Set BWLIMIT (e.g. 20M) to be polite on a shared link; empty = no limit.
BWLIMIT="${BWLIMIT:-}"

# Proton Drive (E2E-encrypted, experimental backend) is flaky on bulk uploads:
#   --protondrive-replace-existing-draft clears half-uploaded drafts left by an interrupted run;
#   generous retries + a bounded per-op timeout ride out the 504/499 gateway timeouts.
RC=(rclone copy -P --transfers="$TRANSFERS" --checksum
    --protondrive-replace-existing-draft=true
    --retries 20 --low-level-retries 20 --timeout 120s)
[ -n "$BWLIMIT" ] && RC+=(--bwlimit "$BWLIMIT")

command -v rclone >/dev/null || { echo "rclone not found — see ONE-TIME SETUP at the top of this script"; exit 1; }
rclone listremotes | grep -qx "${REMOTE}:" || { echo "rclone remote '${REMOTE}:' not configured — run 'rclone config' (see top of script)"; exit 1; }

echo "== mode=$MODE -> ${REMOTE}:${DEST} (transfers=$TRANSFERS${BWLIMIT:+, bwlimit=$BWLIMIT}) =="
rclone mkdir "${REMOTE}:${DEST}" || true

if [ "$do_small" = 1 ]; then
  # 1) loose docs at the folder root
  "${RC[@]}" README.md                               "${REMOTE}:${DEST}/"
  "${RC[@]}" docs/DATA_DICTIONARY.md                 "${REMOTE}:${DEST}/"
  "${RC[@]}" docs/research_plan_technical_report.pdf "${REMOTE}:${DEST}/"
  # 2) headline result artifacts (small JSONs)
  "${RC[@]}" --include '*.json' docs                 "${REMOTE}:${DEST}/results_json/"
  # 3) human-readable CSV subset (Stage I) — includes its own README + verify_export.py
  "${RC[@]}" data/export/csv                          "${REMOTE}:${DEST}/csv_bundle/"
  # 4) the small Parquet stores + registries (everything except the tape)
  "${RC[@]}" data/parquet/ctf_v2_conditions.parquet   "${REMOTE}:${DEST}/parquet/"
  "${RC[@]}" data/parquet/ctf_resolutions_corpus.parquet "${REMOTE}:${DEST}/parquet/"
  "${RC[@]}" data/parquet/universe.parquet            "${REMOTE}:${DEST}/parquet/"
  for store in clob_markets gamma_v2 neg_risk_families onchain_transfers wallet_fills entity markets trades holders prices_history; do
    "${RC[@]}" "data/parquet/$store"                  "${REMOTE}:${DEST}/parquet/$store/"
  done
fi

if [ "$do_tape" = 1 ]; then
  echo "== uploading the 47 GB v2 tape (resumable — re-run if it stops; Proton may 504 on bulk) =="
  "${RC[@]}" data/parquet/tape_v2                      "${REMOTE}:${DEST}/parquet/tape_v2/"
fi

echo "== done ($MODE). Remote size: =="
rclone size "${REMOTE}:${DEST}"
echo "Create the share link in the Proton web app (see the note at the top of this script)."

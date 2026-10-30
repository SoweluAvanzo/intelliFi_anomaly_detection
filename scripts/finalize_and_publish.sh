#!/usr/bin/env bash
# Publish the current committed HEAD: (optionally) regenerate the figure, rebuild the
# code bundle, re-upload the changed artifacts to R2, and push to GitHub.
# It NEVER fabricates a commit — if the tree is dirty it stops and asks you to commit
# yourself (this repo's commits carry no attribution line). Needs a working shell + the
# r2 rclone remote configured.
#   bash scripts/finalize_and_publish.sh                 # sync HEAD to R2 + GitHub
#   REGEN_FIGURE=1 bash scripts/finalize_and_publish.sh  # also regenerate the balanced-panel figure
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate 2>/dev/null || true

REMOTE="${RCLONE_REMOTE:-r2}"; DEST="${RCLONE_DEST:-polymarket-dataset}"

# Figure regen is opt-in: matplotlib stamps a fresh timestamp into the tracked PDF/PNG on
# every run, which would dirty the tree with no real content change. Enable it explicitly
# only when the figure must actually change (then commit the result yourself, see below).
if [[ "${REGEN_FIGURE:-0}" == "1" ]]; then
  echo "== 1/6  balanced-panel figure (REGEN_FIGURE=1) =="
  python scripts/plot_fee_rollout_balanced.py
else
  echo "== 1/6  balanced-panel figure — skipped (set REGEN_FIGURE=1 to regenerate) =="
fi

echo "== 3/6  require a clean tree (this script never fabricates a commit) =="
# A canned commit message can't honestly describe whatever happens to be staged, and this
# repo's history carries no attribution/AI markers. So we do not auto-commit: if the tree
# is dirty, stop and let you commit it yourself (your own message, no attribution line).
# The bundle (git archive HEAD) and the push below then reflect exactly the HEAD you set.
if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: working tree has uncommitted changes — refusing to publish." >&2
  git status --short >&2
  echo >&2
  echo "Commit them yourself (no attribution line), then re-run this script." >&2
  exit 1
fi

echo "== 4/6  rebuild code bundle (data/ is gitignored) =="
TARDIR="$(mktemp -d)"
git archive --format=tar HEAD > "$TARDIR/polymarket_code.tar"
gzip -f "$TARDIR/polymarket_code.tar"

echo "== 5/6  re-upload changed artifacts to ${REMOTE}:${DEST} =="
# rclone copy takes ONE source per call; keep these one-per-line.
rclone copy "$TARDIR/polymarket_code.tar.gz"        "${REMOTE}:${DEST}/"              --checksum
rclone copy docs/fee_rollout_did.json               "${REMOTE}:${DEST}/results_json/" --checksum
rclone copy docs/fig_fee_rollout_balanced.pdf       "${REMOTE}:${DEST}/results_json/" --checksum
rclone copy docs/fig_fee_rollout_balanced.png       "${REMOTE}:${DEST}/results_json/" --checksum
rclone copy REPLICATE.md                            "${REMOTE}:${DEST}/"              --checksum
rclone copy README.md                               "${REMOTE}:${DEST}/"              --checksum
rclone copy docs/DATA_DICTIONARY.md                 "${REMOTE}:${DEST}/"              --checksum

echo "== 6/6  push to GitHub =="
git push origin main
echo "== done =="

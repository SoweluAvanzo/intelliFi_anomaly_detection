#!/usr/bin/env bash
# One-shot: regenerate the figure + report PDF, commit the pending analysis/report changes,
# rebuild the code bundle, re-upload the changed artifacts to R2, and push to GitHub.
# Run next session (needs a working shell + the r2 rclone remote configured).
#   bash scripts/finalize_and_publish.sh
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."
source .venv/bin/activate 2>/dev/null || true

REMOTE="${RCLONE_REMOTE:-r2}"; DEST="${RCLONE_DEST:-polymarket-dataset}"

echo "== 1/6  balanced-panel figure =="
python scripts/plot_fee_rollout_balanced.py

echo "== 2/6  report PDF =="
bash scripts/build_report_pdf.sh

echo "== 3/6  commit report + analysis changes =="
git add -A
git commit -F - <<'MSG'
Fee event study: correct §5.2 to a null participation response; add balanced panel + figure

- scripts/36: balanced-panel event study + per-category grid + pre-trend diagnostic (fixes the
  changing-panel artifact where the pooled series summed over a shrinking category set 9->1).
- docs/fee_rollout_did.json regenerated with event_study_balanced + pretrend_diagnostic.
- report: §5.2 reframed to a NULL participation response (order size on its pre-fee trend; entry
  not falling at onset); §5.1 fee-onset softened; §5.3 refined to a non-monotonic profitability-
  volume relationship with an interior minimum at the upper-middle (7-9) deciles; §1.5/§6 synced.
- scripts/plot_fee_rollout_balanced.py (figure) + scripts/build_report_pdf.sh (durable PDF build);
  regenerated docs/research_plan_technical_report.pdf.

Claude-Session: https://claude.ai/code/session_01CCGVEf9t8efYSYsWoPxaov
MSG

echo "== 4/6  rebuild code bundle (exclude internal notes; data/ is gitignored) =="
TARDIR="$(mktemp -d)"
git archive --format=tar HEAD | tar --delete docs/internal_verification_notes.md > "$TARDIR/polymarket_code.tar"
gzip -f "$TARDIR/polymarket_code.tar"

echo "== 5/6  re-upload changed artifacts to ${REMOTE}:${DEST} =="
rclone copy "$TARDIR/polymarket_code.tar.gz"        "${REMOTE}:${DEST}/"              --checksum
rclone copy docs/research_plan_technical_report.pdf "${REMOTE}:${DEST}/"              --checksum
rclone copy docs/fee_rollout_did.json               "${REMOTE}:${DEST}/results_json/" --checksum
rclone copy docs/fig_fee_rollout_balanced.pdf docs/fig_fee_rollout_balanced.png \
                                                    "${REMOTE}:${DEST}/results_json/" --checksum
rclone copy REPLICATE.md README.md docs/DATA_DICTIONARY.md "${REMOTE}:${DEST}/"        --checksum

echo "== 6/6  push to GitHub =="
git push origin main
echo "== done =="

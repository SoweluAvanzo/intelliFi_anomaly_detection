#!/usr/bin/env bash
# Phase-2 OFFLINE confirmatory driver: registered class-level H1-H4 analysis.
# NETWORK-FREE. Runs AFTER phase-1 (run_offline_analysis.sh). Two stages, split by
# RELIABILITY, with a HARD GATE between them:
#   scripts/21_class_panels.py         -> VALIDATABLE foundation. Imports the atlas
#       catmap (exact Sample-A class logic) to join the v2 tape -> condition -> fee-class,
#       emits the Sample-B class-week panel + the §2 CONTINGENCY (is there a within-B
#       fee-free control?) + (if clean) the H2 negRisk band by class. Self-validates the
#       class assignment (coverage + distribution vs data/parquet/atlas/class_mapping_coverage.csv);
#       exits non-zero if that validation fails, so a bad mapping can NEVER feed 22.
#   scripts/22_confirmatory_hclass.py  -> CONFIRMATORY DiD/TOST/Holm for H1a/H3/H4 vs the
#       Sample-A reference. Arg-free; reads 21's panel + contingency + the A panel. Reads
#       the contingency FIRST: if control_exists==false, H3/H4 emit
#       "not_identified_no_fee_free_control" (NO forced DiD). Every output is stamped
#       pending_review=true -- the USER must review the fee-class assignment + DiD spec +
#       equivalence bounds before ANY confirmatory claim. Runs ONLY if 21 validated.
#
# Launch AFTER phase-1 completes (or standalone):
#   cd <repo-root> && nohup bash scripts/run_offline_analysis_phase2.sh >/dev/null 2>&1 & disown
# Watch:  tail -f data/logs/offline_analysis_phase2.log
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root
PY="./.venv/bin/python"
LOGDIR="data/logs"
mkdir -p "$LOGDIR" "data/parquet/atlas_v2" "docs/cohort_reports"
LOG="$LOGDIR/offline_analysis_phase2.log"
exec >>"$LOG" 2>&1

run_capped() {   # systemd hard mem-cap (MemoryMax 16G) when available, else direct
  if command -v systemd-run >/dev/null 2>&1; then
    systemd-run --user --scope -p MemoryMax=16G "$@"
  else
    "$@"
  fi
}

echo ""
echo "======== [$(date -u +%FT%TZ)] PHASE-2 confirmatory driver START (pid $$) ========"

PANEL="data/parquet/atlas_v2/class_week_b.parquet"
CONTING="docs/cohort_reports/class_contingency_h2.json"
S21_OK=0

# ---- Stage 21: validatable class-panel foundation (self-validates class assignment) ----
echo ""
echo "-------- [$(date -u +%FT%TZ)] scripts/21_class_panels.py (panel + §2 contingency + H2 band by class) --------"
if [ -s "$CONTING" ] && [ -e "$PANEL" ]; then
  echo "[skip] phase-2a outputs already present ($CONTING, $PANEL)"; S21_OK=1
elif [ -f scripts/21_class_panels.py ]; then
  if run_capped "$PY" scripts/21_class_panels.py --out "$PANEL" --json-out "$CONTING"; then
    # belt-and-suspenders: 21 exits non-zero + writes no panel on failure, but ALSO require the
    # "class_validation_passed": true flag so a bad class assignment can't slip into 22 either way.
    if "$PY" -c "import json,sys; sys.exit(0 if json.load(open('$CONTING')).get('class_validation_passed', True) else 1)" 2>/dev/null; then
      echo "[ok] scripts/21 done + class_validation_passed=true -> $PANEL, $CONTING"; S21_OK=1
    else
      echo "[FAIL] scripts/21 ran but class_validation_passed=false -- NOT feeding 22 (bad class assignment)."
    fi
  else
    echo "[FAIL] scripts/21 non-zero -- class-assignment validation FAILED; NOT feeding 22."
  fi
else
  echo "[pending] scripts/21_class_panels.py not present yet -- peer is building it. Re-launch phase-2 when it lands."
fi

# ---- Surface the §2 contingency + class-assignment validation ----
if [ -s "$CONTING" ]; then
  echo ""
  echo "-------- [$(date -u +%FT%TZ)] phase-2a foundation summary (§2 contingency + class validation + H2) --------"
  "$PY" -c "import json; d=json.load(open('$CONTING')); print(json.dumps(d, indent=1)[:2500])" 2>/dev/null || cat "$CONTING"
fi

# ---- Stage 22: confirmatory inference -- AUTO-RUN, but GATED on 21 validating ----
echo ""
echo "-------- [$(date -u +%FT%TZ)] scripts/22_confirmatory_hclass.py -- confirmatory H1a/H3/H4 (PENDING-REVIEW) --------"
if [ "$S21_OK" != "1" ]; then
  echo "[skip] 21 did not validate/produce a sound panel -- NOT running 22. A bad or unvalidated class"
  echo "       assignment must never feed a confirmatory claim (the whole point of the reliability gate)."
elif [ -f scripts/22_confirmatory_hclass.py ]; then
  echo "[REVIEW-REQUIRED] running 22: outputs are stamped pending_review=true. It reads 21's contingency"
  echo "                  FIRST -- if control_exists==false, H3/H4 emit 'not_identified_no_fee_free_control'"
  echo "                  (no forced DiD). Before ANY confirmatory claim, the USER must review:"
  echo "                  (a) the v2 fee-class assignment, (b) the DiD spec, (c) the equivalence bounds."
  run_capped "$PY" scripts/22_confirmatory_hclass.py \
    && echo "[ok] 22 done -> docs/cohort_reports/confirmatory_h1_h4_PENDING_REVIEW.json (PENDING USER REVIEW)" \
    || echo "[FAIL] scripts/22_confirmatory_hclass.py non-zero"
else
  echo "[pending] scripts/22_confirmatory_hclass.py not present yet -- re-launch phase-2 when it lands."
fi

echo "======== [$(date -u +%FT%TZ)] PHASE-2 driver DONE ========"

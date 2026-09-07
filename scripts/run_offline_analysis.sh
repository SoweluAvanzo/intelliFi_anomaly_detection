#!/usr/bin/env bash
# Autonomous OFFLINE analysis driver (cohorts 1-6). NETWORK-FREE.
#
# Per cohort: local coverage gate (scripts/15_verify_tape_coverage.py) then the
# tape-only descriptive pass (scripts/17_cohort_descriptive.py) over the local v2
# tape. Then assemble the cross-cohort table (scripts/cohort_results_table.py) and
# run the confirmatory inference (scripts/18_confirmatory_inference.py). Resumable
# (skips a cohort whose out-JSON exists), fully logged, nohup-safe.
#
# Launch unattended (survives the terminal closing / user leaving):
#   cd <repo-root> && nohup bash scripts/run_offline_analysis.sh >/dev/null 2>&1 &
# Watch:  tail -f data/logs/offline_analysis.log
#
# Cohort c0 (genesis 86,126,978-88,079,999) is EXCLUDED -- still crawling on the box.
set -uo pipefail
cd "$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"   # repo root
PY="./.venv/bin/python"
REPORTS="docs/cohort_reports"
LOGDIR="data/logs"
mkdir -p "$REPORTS" "$LOGDIR"
LOG="$LOGDIR/offline_analysis.log"
exec >>"$LOG" 2>&1

echo ""
echo "======== [$(date -u +%FT%TZ)] OFFLINE analysis driver START (pid $$) ========"

# cohort block windows (canonical: docs/stage2_cohorts.md)
CIDS=(1 2 3 4 5 6)
declare -A LO=( [1]=88080000 [2]=88844000 [3]=89608000 [4]=90372000 [5]=91136000 [6]=91900000 )
declare -A HI=( [1]=88843826 [2]=89607826 [3]=90371826 [4]=91135826 [5]=91899826 [6]=92995000 )

for N in "${CIDS[@]}"; do
  A="${LO[$N]}"; B="${HI[$N]}"
  # c1 is the validation target: write a _repro file, never clobber the committed original
  if [ "$N" = "1" ]; then OUT="$REPORTS/cohort1_descriptive_repro.json"; else OUT="$REPORTS/cohort${N}_descriptive.json"; fi
  echo ""
  echo "-------- [$(date -u +%FT%TZ)] cohort $N  blocks ${A}-${B}  -> ${OUT} --------"

  # 1) offline coverage gate (pure-local; never fetches)
  "$PY" scripts/15_verify_tape_coverage.py --from-block "$A" --to-block "$B" \
    || echo "[warn] cohort $N coverage gate non-zero (gaps? see above)"

  # 2) resumable: skip a cohort whose descriptive output is already present + non-empty
  if [ -s "$OUT" ]; then
    echo "[skip] cohort $N output already present ($OUT)"
    continue
  fi

  # 3) descriptive pass (tape-only, offline, dedup). Primary mem control = the script's
  #    own --memory-limit 12GB; wrap in a systemd --scope MemoryMax=16G hard cap when
  #    available (laptop 31G; ~11G temp under data/_s17_tmp auto-cleaned; ~4-6 min/cohort).
  if command -v systemd-run >/dev/null 2>&1; then
    systemd-run --user --scope -p MemoryMax=16G \
      "$PY" scripts/17_cohort_descriptive.py --from-block "$A" --to-block "$B" --cohort "$N" --dedup --out "$OUT" --memory-limit 12GB \
      && echo "[ok] cohort $N done -> $OUT" \
      || echo "[FAIL] cohort $N descriptive pass non-zero (systemd-run path)"
  else
    "$PY" scripts/17_cohort_descriptive.py --from-block "$A" --to-block "$B" --cohort "$N" --dedup --out "$OUT" --memory-limit 12GB \
      && echo "[ok] cohort $N done -> $OUT" \
      || echo "[FAIL] cohort $N descriptive pass non-zero (direct path)"
  fi
done

echo ""
echo "-------- [$(date -u +%FT%TZ)] assemble cross-cohort results table --------"
"$PY" scripts/cohort_results_table.py \
  || echo "[warn] assembler non-zero (scripts/cohort_results_table.py)"

echo ""
echo "-------- [$(date -u +%FT%TZ)] confirmatory inference (TOST / bootstrap / Holm) --------"
if [ -f scripts/19_confirmatory_inference.py ]; then
  "$PY" scripts/19_confirmatory_inference.py \
    || echo "[warn] confirmatory inference non-zero"
else
  echo "[pending] scripts/19_confirmatory_inference.py not present yet -- run it once the peer lands it (light stats on the assembled table, offline)."
fi

echo "======== [$(date -u +%FT%TZ)] OFFLINE analysis driver DONE ========"

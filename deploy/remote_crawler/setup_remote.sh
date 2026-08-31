#!/usr/bin/env bash
# Run ON the remote box (Hetzner / any non-geoblocked host). Idempotent.
# Sets up an isolated Python venv for the v2 tape crawler. Does NOT touch any
# other service on the box. Assumes: git, python3.11+, rsync present.
set -euo pipefail
DEST="${INTELLIFI_REMOTE_DIR:-$HOME/intellifi_crawler}"
REPO_URL="${INTELLIFI_REPO_URL:-}"     # optional: git URL; else expects code already rsync'd to $DEST
echo "== IntelliFi remote crawler setup -> $DEST =="
mkdir -p "$DEST"
if [ -n "$REPO_URL" ] && [ ! -d "$DEST/.git" ]; then
  git clone --depth 1 "$REPO_URL" "$DEST"
fi
cd "$DEST"
if [ ! -d .venv ]; then python3 -m venv .venv; fi
./.venv/bin/pip -q install --upgrade pip
# Minimal deps for crawling only (no notebook/analysis extras).
./.venv/bin/pip -q install -e . 2>/dev/null || ./.venv/bin/pip -q install polars pyarrow requests duckdb
mkdir -p data/parquet/tape_v2 data/logs
echo "OK. Put keys in $DEST/.env.dune (ETHERSCAN_KEY, ETHERSCAN_KEY2, ...), then run run_fleet.sh"
